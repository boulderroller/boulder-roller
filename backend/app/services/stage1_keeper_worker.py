"""One durable, fenced transition at a time. Disabled callers do no IO."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from collections import Counter
from asyncpg import ObjectNotInPrerequisiteStateError

from .stage1_keeper_allocation import allocate
from .stage1_keeper_merkle import canonical, claim_set, leaf_hash, root_from_hashes, digest
from .stage1_keeper_store import LeaseLost, WaitingForArchive
from .stage1_keeper_erasure import export_lock
from .stage1_keeper_paths import ORACLE_TOOLS
from .stage1_keeper_snapshot import bind_recipients, recipient_people, WEEK, DAY

IDLE_SECONDS = 900


def idle_delay(scope, week, now):
    """Wake at most every 15 minutes, including the exact boundary/grace edge."""
    close = scope["launch"] + (week + 1) * WEEK
    edges = [at - now for at in (close, close + DAY) if at > now]
    return min(IDLE_SECONDS, *edges) if edges else IDLE_SECONDS


class Blocked(ValueError):
    def __init__(self, kind, details):
        super().__init__(kind)
        self.kind, self.details = kind, details


async def independent(snapshot, sources):
    process = await asyncio.create_subprocess_exec(sys.executable, "-m", "stage1_reference.keeper",
        cwd=ORACLE_TOOLS, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(canonical({"snapshot": snapshot, "sources": sources})), timeout=60)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise Blocked("oracle_failed", {"exit_code": process.returncode})
    return json.loads(stdout)


def export_claims(directory, job_id, payload):
    """Durable deterministic bytes, atomic rename + directory fsync before signing."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with export_lock(directory, job_id):
        return _export_claims_locked(directory, job_id, payload)


def _export_claims_locked(directory, job_id, payload):
    target, data = directory / f"{job_id}.json", canonical(payload) + b"\n"
    if target.exists():
        if target.read_bytes() != data:
            raise Blocked("proof_export_conflict", {"job": job_id})
    else:
        fd, name = tempfile.mkstemp(prefix=f".{job_id}-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            # Concurrent identical planners are lease-fenced in the DB. Refuse
            # replacing any existing evidence even if a lease expires mid-write.
            try:
                os.link(name, target)
            except FileExistsError:
                if target.read_bytes() != data:
                    raise Blocked("proof_export_conflict", {"job": job_id})
            dfd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            os.unlink(name)
    return str(target), hashlib.sha256(data).hexdigest()


def proof_payload(snapshot, allocation, claims, skipped):
    def redact(value):
        if isinstance(value,list):
            return [redact(v) for v in value]
        if isinstance(value,dict):
            value = {k:redact(v) for k,v in value.items()}
            if any(str(value.get(k,'')).startswith('anonymous:') for k in ('person','recipient')):
                value = {k:v for k,v in value.items() if k not in ('person','recipient')}
                value['identity_erased'] = True
        return value
    return {"schema": 1, "claims": redact(claims), "cap": allocation["cap"], "snapshot_commitment": snapshot["commitment"],
            "cash_skipped": skipped, "claim_instruction": "claim_stage1_dung_batch" if claims.get('kind')=='dung' else "claim_stage1"}



def verify_export(job):
    # The immutable DB plan/proofs precede filesystem IO. A crash or unavailable
    # volume is recoverable from those exact bytes without taking a new cutoff.
    if job.get("export_suspended"):
        raise Blocked("export_suspended_for_deletion", {"job": job["id"]})
    if not Path(job["export_path"]).exists():
        export_claims(Path(job["export_path"]).parent, job["id"], proof_payload(
            job["snapshot"], job["allocation"], job["claims"],
            not any(op["kind"] == "publish" for op in job["operations"])))
    data = Path(job["export_path"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != job["export_digest"]:
        raise Blocked("proof_export_changed", {"job": job["id"]})


def check_accounting(observation, jobs):
    """Independent inventory reconciliation, including paid receipts and custody."""
    if observation.get('kind') == 'dung':
        from .stage1_keeper_dung import check_dung
        return check_dung(observation, jobs)
    from .stage1_keeper_records import restore_cash_books
    restore_cash_books(observation,jobs)
    a, books, sets, lots = (observation[k] for k in ("asset", "books", "sets", "lots"))
    # Historical paid liabilities survive account closure. Only a successful
    # finalized close plus the previously reconciled final bitmap authorizes it.
    sets = dict(sets)
    for job in jobs:
        for address, publication in job.get('publications', {}).items():
            if publication.get('closed'):
                account = publication['account']
                if address in sets or not publication['closed'].get('signature') or account['paid'] != account['total'] or account['claimed_count'] != account['leaf_count']:
                    raise Blocked('closure_witness_mismatch', {'claim_set': address})
                sets[address] = account
    observation['sets'] = sets
    ledger = a["ledger"]
    wanted = {}
    def same(name, actual, expected):
        if actual != expected:
            wanted[name] = {"chain": actual, "database_or_inventory": expected}
    paid = sum(s['paid'] for s in sets.values())
    streams = observation.get('streams', {})
    if 'receipts' not in observation:
        observation['receipts'] = []
    total = sum(s["total"] for s in sets.values())
    held = sum(b["available"] + sum(b["holds"]) + b["pool"] + (b.get("boost_released",0) if not b.get("published",False) else 0) for b in books.values())
    held += sum(sum(map(sum, s['holds'])) + s['pool'] for s in streams.values())
    pool = sum(b["pool"] for b in books.values()) + sum(s['pool'] for s in streams.values())
    realized, fees = a["harvested_units"], a["fees_assessed"]
    same("paid", ledger["paid"], paid)
    same("claimable", ledger["claimable"], total - paid)
    same("held", ledger["held"], held)
    same("pool", ledger["pool"], pool)
    same("income", realized, sum(b["harvested_net"] for b in books.values()) + fees)
    same("lot_harvest", realized, sum(l["harvested_units"] for l in lots))
    same("owner_custody", ledger["owner_custody"], sum(l["units"] + l["owner_units"] for l in lots))
    same("owner_returns", ledger["owner_returns"], sum(l["returned_units"] for l in lots))
    same("income_equality", ledger["paid"] + fees + ledger["claimable"] + ledger["held"], realized + ledger.get("admitted_cash_lifetime", 0))
    same("custody_equality", ledger["earnings"], fees + ledger["claimable"] + ledger["held"])
    same("deposit_equality", ledger["deposited"], ledger["owner_custody"] + ledger["owner_returns"] + ledger["earnings"] + ledger["paid"] - ledger.get("admitted_cash_lifetime", 0))
    if observation["earnings_balance"] < ledger["earnings"] or pool > held:
        wanted["custody_coverage"] = {"chain": observation["earnings_balance"], "required": ledger["earnings"]}
    plans = {(j["claims"]["context"][2], j["week"]): j for j in jobs if j.get("claims")}
    chain_contexts = {(s["hill"], s["week"]) for s in sets.values()}
    for context, job in plans.items():
        if job["state"] == "complete" and any(op["kind"] == "publish" for op in job["operations"]) and context not in chain_contexts:
            wanted[f"missing_set:{context[0]}:{context[1]}"] = {"database": job["claims"]["root"]}
    for key, s in sets.items():
        job = plans.get((s["hill"], s["week"]))
        if not job:
            wanted[f"untracked_set:{key}"] = {"chain": s["root"]}
            continue
        if s.get('sealed') is False:
            continue
        for field, expected in (("root", job["claims"]["root"]), ("total", job["claims"]["total"])):
            same(f"{key}:{field}", s[field], expected)
        if 'bitmap' in s:
            bits, leaves = bytes.fromhex(s['bitmap']), job['claims']['leaves']
            if s['leaf_count'] != len(leaves) or len(bits) != (len(leaves)+7)//8:
                wanted[f'{key}:bitmap'] = {'invalid': True}
                continue
            receipts = [{'claim_set': key, 'index': l['index'], 'person': l.get('person'), 'amount': l['amount']}
                        for l in leaves if bits[l['index']//8] & (1 << (l['index']%8))]
            observation['receipts'].extend(r for r in receipts if not any(x['claim_set']==key and x['index']==r['index'] for x in observation['receipts']))
            same(f'{key}:claimed_count', s['claimed_count'], len(receipts))
        else:
            receipts = [r for r in observation["receipts"] if r["claim_set"] == key]
        if root_from_hashes(job["claims"]["context"], job["claims"]["leaves"]) != (job["claims"]["root"], job["claims"]["total"]):
            wanted[f"{key}:retained_commitments"] = {"invalid": True}
        if job["snapshot"].get("schema") == 2 and digest(job["snapshot"]["commitment_inputs"]) != job["snapshot"]["commitment"]:
            wanted[f"{key}:snapshot_commitment"] = {"invalid": True}
        same(f"{key}:paid", s["paid"], sum(r["amount"] for r in receipts))
        for r in receipts:
            if 'bitmap' in s:
                continue  # The root/proof witness plus claimed index binds the exact retained leaf.
            leaves = job["claims"]["leaves"]
            registration = observation["recipients"].get(r["person"])
            if (r["index"] >= len(leaves) or not registration or
                leaf_hash(job["claims"]["context"], r["index"], r["person"], registration["recipient"], r["amount"]) != leaves[r["index"]]["leaf_hash"]):
                wanted[f"{key}:receipt"] = {"chain": r}
    if wanted:
        raise Blocked("ledger_mismatch", wanted)
    return {"commitment": "finalized", "slot": observation["slot"], "ledger": ledger,
            "income": realized, "fees": fees, "earnings_balance": observation["earnings_balance"], "checks": "three equalities and inventory/database match"}


class KeeperWorker:
    def __init__(self, store, chain, export_dir, *, enabled=False, recompute=independent):
        self.store, self.chain, self.export_dir = store, chain, export_dir
        if chain is not None:
            chain.store = store
        self.enabled, self.recompute = enabled, recompute

    async def retry(self, job_id):
        if not self.enabled:
            return 'disabled'
        await self.store.bind_genesis(self.chain.genesis)
        claim=await self.store.retry_context(job_id)
        scope=claim['scope']
        async with self.store.asset_lock(scope) as locked:
            if not locked:
                raise RuntimeError('token is busy')
            # Another hill may have blocked this asset while we waited.
            claim=await self.store.retry_context(job_id)
            scope=claim['scope']
            await self.store.refresh(claim)
            reconciled=False
            if scope['block_kind']=='ledger_mismatch':
                observed=await self.chain.observe(scope,claim['job']['week'],claim['job']['floor_slot'])
                from .stage1_keeper_payout import reconcile
                await reconcile(self.store,self.chain,scope,observed)
                reconciled=True
            await self.store.unblock(job_id,token_reconciled=reconciled)

    async def plan(self, claim, observation, *, snapshot=None, reserved=None):
        scope, job = claim["scope"], claim["job"]
        week = job["week"]
        if observation["now"] < scope["launch"] + (week + 1) * 604800 + 86400:
            return False
        if scope.get('kind') == 'dung':
            from .stage1_keeper_dung import plan_dung
            return await plan_dung(self, claim, observation, snapshot)
        cursor = observation["cursor"]
        if cursor and cursor["next_week"] != week:
            raise Blocked("cursor_mismatch", {"expected": week, "chain": cursor["next_week"]})
        if cursor:
            expected_holds = [0] * 26
            for book in observation["books"].values():
                if book["hill"] == scope["hill"] and book["published"]:
                    expected_holds[book["week"] % 26] += sum(book["holds"])
            expected_cash_holds = [0]*26
            for stream in observation.get('streams', {}).values():
                if stream['hill'] == scope['hill']:
                    for index, buckets in enumerate(stream['holds']):
                        born = stream['start_week'] + index
                        if born < week:
                            expected_cash_holds[born % 26] += sum(buckets)
            if cursor.get('cash_holds',[0]*26) != expected_cash_holds:
                raise Blocked('cursor_cash_hold_mismatch', {'chain':cursor.get('cash_holds'), 'inventory':expected_cash_holds})
            if cursor["holds"] != expected_holds:
                raise Blocked("cursor_hold_mismatch", {"chain": cursor["holds"], "inventory": expected_holds})
        if reserved is None:
            reserved = await self.store.recipient_holds(scope)
        held_people = {p for people in reserved.values() for p in people}
        if snapshot is None:
            snapshot = await self.store.snapshot(claim, {}, observation["now"], held_people)
        people = recipient_people(snapshot, held_people)
        slot, registrations = await self.chain.recipient_registrations(people - observation["recipients"].keys(), observation["slot"])
        snapshot = bind_recipients(snapshot, {**observation["recipients"], **registrations}, held_people)
        book_key = self.chain.funding(scope, week)
        current = observation["books"].get(book_key)
        if current and (current["published"] or current["snapshot"] != "00" * 32):
            raise Blocked("unowned_frozen_week", {"week": week})
        sources = [{"id": book_key, "born": week, "due": week, "kind": "sponsor" if observation["asset"].get("adapter") == 254 else "yield", "lineage": current["lineage"] if current else "00" * 32,
                    "buckets": [current["available"] if current else 0, 0, 0, 0, 0]}]
        for key, b in observation["books"].items():
            if b["hill"] == scope["hill"] and b["week"] < week and any(b["holds"]):
                sources.append({"id": key, "born": b["week"], "due": b["due_week"], "kind": "sponsor" if observation["asset"].get("adapter") == 254 else "yield",
                                "lineage": b["lineage"], "buckets": b["holds"], "reserved": reserved.get(key, {}),'closed_source':b.get('closed_source',False)})
        active_streams = {k: stream for k, stream in observation.get('streams', {}).items()
                          if stream['hill'] == scope['hill'] and not stream['retired']}
        for address, stream in active_streams.items():
            opening = scope['launch'] + stream['start_week'] * WEEK
            close = opening + stream['weeks'] * WEEK
            ascents = dict(Counter(r['person'] for r in snapshot.get('boost_rides', [])
                                  if stream['start_week'] <= r['ride_week'] < stream['start_week']+stream['weeks']))
            for index, buckets in enumerate(stream['holds']):
                ident = f'{address}:{index}'
                sources.append({'id': ident, 'stream': address, 'tranche': index,
                                'born': stream['start_week'] + index, 'due': stream['start_week'] + index,
                                'kind': 'boost', 'last_ride_week': stream['start_week'] + stream['weeks'] - 1,
                                'buckets': buckets, 'ascents': ascents, 'reserved': reserved.get(ident, {})})
        allocation = allocate(snapshot, sources)
        if any(s['kind']=='boost' and week>s['last_ride_week'] and week-s['born']<26
               and allocation['holds'][s['id']] != s['buckets'] for s in sources):
            raise Blocked('boost_attributed_release_abi', {'week':week})
        claims = claim_set(snapshot["context"], allocation["payments"], snapshot["recipients"])
        actual = {"allocation": allocation, "claims": claims}
        expected = await self.recompute(snapshot, sources)
        if canonical(actual) != canonical(expected):
            raise Blocked("oracle_disagreement", {"backend": actual, "oracle": expected})
        # Retain the ordinary measurement even for cash skips. A separate DUNG
        # cursor or another asset cannot lose its work through this cash cursor.
        skip = not active_streams and not any(sum(s["buckets"]) for s in sources) and (not cursor or not any(cursor["holds"])) and (not current or (current["harvested_net"] == 0 and current["lineage"] == "00" * 32 and current["pool"] == 0 and not current["proposed"]))
        operations = []
        if not cursor:
            operations.append({"kind": "init"})
        if skip:
            operations.append({"kind": "skip", "from": week, "through": week})
        else:
            if not current:
                operations.append({"kind": "open", "week": week})
            operations.append({"kind": "freeze", "week": week, "snapshot": snapshot["commitment"], "cap": allocation["cap"]})
            for address, stream in active_streams.items():
                operations.append({'kind': 'boost', 'week': week, 'stream': address,
                                   'remaining': [allocation['holds'][f'{address}:{i}'] for i in range(13)]})
            released = []
            for source in sources[1:]:
                if source['kind'] == 'boost':
                    continue
                if allocation["pool"][source["id"]]:
                    operations.append({"kind": "expire", "source": source["id"], "week": week,
                                       'closed_source':source.get('closed_source',False),'born':source['born']})
                elif allocation["holds"][source["id"]] != source["buckets"]:
                    operations.append({"kind": "prepare", "source": source["id"], "week": week, "remaining": allocation["holds"][source["id"]]})
                    released.append(source["id"])
            publication = {"kind": "publish", "week": week, "root": claims["root"], "total": claims["total"],
                           "count": claims["count"], "holds": allocation["holds"][book_key], "sources": released}
            if len(released) > 16:
                lookup = self.chain.lookup_plan(observation["slot"], released)
                operations.append(lookup)
                publication["requires_lookup"] = True
            operations.append({'kind': 'prepare_set', 'week': week, 'count': claims['count']})
            operations.append(publication)
        payload = {"schema": 1, "snapshot": snapshot, **actual, "sources": sources,
                   "cash_skipped": skip, "claim_instruction": "claim_stage1", "evidence_class": "publisher-attested inputs"}
        path = str(Path(self.export_dir) / f"{job['id']}.json")
        sha = hashlib.sha256(canonical(proof_payload(snapshot, allocation, claims, skip)) + b"\n").hexdigest()
        await self.store.save_plan(claim, {**payload, "operations": operations, "floor_slot": slot,
                    "export_path": path, "export_digest": sha, "through_week": week})
        return True

    async def run_once(self, scope_id=None):
        if not self.enabled:
            return "disabled"
        await self.store.bind_genesis(self.chain.genesis)
        claim = await self.store.claim(scope_id)
        if not claim:
            return "idle"
        delay = 0
        stopped = asyncio.Event()
        async def heartbeat():
            while True:
                try:
                    await asyncio.wait_for(stopped.wait(), 15)
                    return
                except asyncio.TimeoutError:
                    await self.store.renew(claim)
        task = asyncio.create_task(heartbeat())
        lock, lock_entered = None, False
        try:
            scope, job = claim["scope"], claim["job"]
            lock = self.store.asset_lock(scope)
            acquired = await lock.__aenter__()
            lock_entered = True
            if not acquired:
                delay = 1
                return "asset_busy"
            # Erasure preparation may have waited for this same lock after our
            # claim. Never regenerate an export from a pre-lock copy.
            await self.store.refresh(claim)
            job = claim["job"]
            if job["state"] == "planning":
                clock = await self.chain.clock(job["floor_slot"])
                if clock["now"] < scope["launch"] + (job["week"] + 1) * WEEK + DAY:
                    delay = idle_delay(scope, job["week"], clock["now"])
                    return "not_due"
                reserved = await self.store.recipient_holds(scope)
                admission = {'admission_bond':await self.chain.admission_bond(scope,clock['slot'])} if hasattr(self.chain,'admission_bond') else {}
                # Missing archive is a DB-only wait after the cheap Clock read.
                # Freeze the shared measurement once, before inventory IO.
                snapshot = await self.store.snapshot(claim, {}, clock["now"],
                    {p for people in reserved.values() for p in people}, **admission)
                observed = await self.chain.observe(scope, job["week"], clock["slot"])
                # Every new week is fenced by all prior known asset obligations.
                from .stage1_keeper_payout import reconcile
                await reconcile(self.store,self.chain,scope,observed)
                if not await self.plan(claim, observed, snapshot=snapshot, reserved=reserved):
                    delay = idle_delay(scope, job["week"], observed["now"])
                    return "not_due"
                await self.store.refresh(claim)
                job = claim["job"]
            if scope.get('kind') == 'dung':
                from .stage1_keeper_dung import verify_dung_plan
                await verify_dung_plan(self, scope, job)
            verify_export(job)
            if job["operation_index"] == len(job["operations"]):
                observed = await self.chain.observe(scope, job["week"], job["floor_slot"])
                from .stage1_keeper_payout import reconcile
                evidence = await reconcile(self.store,self.chain,scope,observed)
                self.chain.verify_plan(scope, job, observed)
                await self.store.complete(claim, evidence)
                return "complete"
            op = job["operations"][job["operation_index"]]
            if job["signed"]:
                status = await self.chain.status(job["signed"])
                if status["state"] == "finalized":
                    observed = await self.chain.observe(scope, job["week"], max(job["floor_slot"], status["slot"]))
                    from .stage1_keeper_payout import capture_publication
                    evidence = await self.chain.transaction_evidence(job["signed"]["signature"],status["slot"])
                    await capture_publication(self.store, self.chain, claim, op, observed, evidence)
                    self.chain.verify_operation(scope, op, observed)
                    lookup = await self.chain.lookup_deposit(job['signed']['lookup_address'],status['slot']) if op['kind']=='lookup' else None
                    await self.store.advance(claim, status["slot"], evidence["fee"],lookup)
                    return "finalized"
                if status['state']=='failed':
                    evidence=await self.chain.transaction_evidence(job['signed']['signature'],status['slot'],allow_failed=True)
                    await self.store.failed_transaction(claim,evidence)
                    status['unfunded']=status.get('unfunded') or evidence.get('unfunded')
                if status["state"] == "failed" and (status.get('paused') or status.get('unfunded')):
                    await self.store.expired(claim,status['slot'])
                    await self.store.wait_alert(claim,'settlement_paused' if status.get('paused') else 'sponsor_unfunded')
                    delay = IDLE_SECONDS
                    return 'settlement_paused' if status.get('paused') else 'sponsor_unfunded'
                if status["state"] == "failed":
                    raise Blocked("transaction_failed", {"operation": op["kind"], "signature": job["signed"]["signature"]})
                if status["state"] == "expired":
                    floor = max(job["floor_slot"], status["slot"])
                    observed = await self.chain.observe(scope, job["week"], floor)
                    applied = (await self.chain.lookup_exists(job["signed"]["lookup_address"], floor)) if op["kind"] == "lookup" else self.chain.operation_applied(scope, op, observed)
                    if applied:
                        raise Blocked("ambiguous_effect_without_signature", {"operation": op["kind"]})
                    await self.store.expired(claim, observed["slot"])
                    return "expired_no_effect"
                if status["state"] != "absent":
                    delay = 1
                    return "reconciling"
                signed = job["signed"]
            else:
                if op.get("requires_lookup"):
                    op = {**op, "lookup": job["lookup_address"]}
                    if not op["lookup"]:
                        raise ValueError("publication lacks finalized lookup transport")
                signed = await self.chain.prepare(scope, {**op,**({"_job_id":job["id"]} if op['kind']=='lookup' else {})}, floor=job["floor_slot"])
                await self.store.signed(claim, signed)
            if scope.get('kind') == 'dung':
                self.chain.verify_signed_operation(scope, op, signed)
            # Fence immediately before any externally visible effect. If this
            # worker dies after signing, another sends only these durable bytes.
            await self.store.renew(claim)
            await self.chain.submit(signed)
            delay = 1
            return "submitted"
        except LeaseLost:
            return "lease_lost"
        except WaitingForArchive:
            delay = IDLE_SECONDS
            return "waiting_for_archive"
        except RuntimeError as exc:
            if type(exc).__name__ == 'SettlementPaused':
                delay = IDLE_SECONDS
                await self.store.wait_alert(claim, 'settlement_paused')
                return 'settlement_paused'
            if type(exc).__name__ == 'SponsorUnfunded':
                await self.store.wait_alert(claim,'sponsor_unfunded')
                delay = 30
                return 'sponsor_unfunded'
            delay = 5
            return 'retry'
        except Blocked as exc:
            try:
                await self.store.block(claim, exc.kind, exc.details)
            except LeaseLost:
                return "lease_lost"
            return "blocked"
        except ObjectNotInPrerequisiteStateError as exc:
            if exc.message not in ("account_deleted", "account_deletion_pending"):
                delay = 5
                return "retry"
            try:
                await self.store.block(claim, "account_deletion_write_refused",
                    {"week": claim["job"]["week"], "reason": exc.message})
            except LeaseLost:
                return "lease_lost"
            return "blocked"
        except ValueError as exc:
            try:
                await self.store.block(claim, "invalid_measurement", {"reason": str(exc)})
            except LeaseLost:
                return "lease_lost"
            return "blocked"
        except Exception:
            # Never include transport errors (possibly credentials) in output.
            # Persisted bytes/signature remain authoritative after dropped replies.
            delay = 5
            return "retry"
        finally:
            if lock_entered:
                await lock.__aexit__(None, None, None)
            stopped.set()
            try:
                await task
            except LeaseLost:
                pass
            finally:
                await self.store.release(claim, delay)
