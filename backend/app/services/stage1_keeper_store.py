"""PostgreSQL leases and immutable plan/proof persistence for the opt-in keeper."""
import json
import uuid
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import hashlib
from asyncpg import ObjectNotInPrerequisiteStateError

from .stage1_keeper_merkle import canonical, digest
from .stage1_keeper_snapshot import COMPLETIONS_SQL, build_snapshot, freeze_records
from .stage1_keeper_erasure import export_lock


def unpack(row):
    if row is None:
        return None
    result = dict(row)
    for key in ("snapshot", "sources", "allocation", "claims", "operations", "signed", "inputs", "evidence", "leaf", "publications", "dung_publication", "funding_publication", "operation", "attempts"):
        if isinstance(result.get(key), str):
            result[key] = json.loads(result[key])
    return result


class LeaseLost(RuntimeError):
    pass


class WaitingForArchive(RuntimeError):
    pass


class BoundaryWriteRefused(ValueError):
    pass


class KeeperStore:
    def __init__(self, pool):
        self.pool = pool
        self.genesis = None

    async def bind_genesis(self, genesis):
        """Admit an empty store once; never adopt unknown historical state."""
        if not genesis:
            raise ValueError("keeper cluster genesis must be admitted first")
        if self.genesis is not None:
            if self.genesis != genesis:
                raise ValueError("keeper database genesis mismatch")
            return
        async with self.pool.acquire() as c, c.transaction():
            await c.execute("SELECT pg_advisory_xact_lock(hashtextextended('stage1_keeper_network',0))")
            bound = await c.fetchval('SELECT genesis FROM stage1_keeper_network WHERE singleton')
            if bound is None:
                if await c.fetchval('SELECT EXISTS(SELECT 1 FROM stage1_keeper_scopes) OR EXISTS(SELECT 1 FROM stage1_keeper_measurements)'):
                    raise ValueError("existing unbound keeper state requires a verified migration")
                await c.execute('INSERT INTO stage1_keeper_network(genesis) VALUES($1)', genesis)
            elif bound != genesis:
                raise ValueError("keeper database genesis mismatch")
        self.genesis = genesis

    @asynccontextmanager
    async def asset_lock(self, scope):
        async with self.pool.acquire() as c:
            key = f"stage1:{scope['program']}:{scope['mint']}"
            locked = await c.fetchval("SELECT pg_try_advisory_lock(hashtextextended($1,0))", key)
            try:
                yield locked
            finally:
                if locked:
                    await c.execute("SELECT pg_advisory_unlock(hashtextextended($1,0))", key)

    async def recipient_holds(self, scope):
        async with self.pool.acquire() as c:
            allocation = await c.fetchval("SELECT allocation FROM stage1_keeper_jobs WHERE scope_id=$1 AND state='complete' ORDER BY week DESC LIMIT 1", scope["id"])
        return json.loads(allocation).get("reserved", {}) if allocation else {}

    async def asset_floor(self,scope):
        async with self.pool.acquire() as c:
            return await c.fetchval('SELECT coalesce(max(j.floor_slot),0) FROM stage1_keeper_jobs j JOIN stage1_keeper_scopes s ON s.id=j.scope_id WHERE s.program=$1 AND s.mint=$2',scope['program'],scope['mint'])

    async def retry_context(self, job_id):
        async with self.pool.acquire() as c:
            job=unpack(await c.fetchrow('SELECT * FROM stage1_keeper_jobs WHERE id=$1',job_id))
            if not job:
                raise ValueError('unknown keeper job')
            scope=dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes WHERE id=$1',job['scope_id']))
        return {'scope':scope,'job':job}

    async def unblock(self, job_id, *, token_reconciled=False):
        async with self.pool.acquire() as c, c.transaction():
            job = await c.fetchrow("SELECT * FROM stage1_keeper_jobs WHERE id=$1 FOR UPDATE", job_id)
            if not job:
                raise ValueError("job is not blocked")
            scope=await c.fetchrow('SELECT * FROM stage1_keeper_scopes WHERE id=$1',job['scope_id'])
            payout_recovery = job['state']=='complete' and scope['blocked'] and scope['block_kind']=='ledger_mismatch' and token_reconciled
            if job['state']!='blocked' and not payout_recovery:
                raise ValueError('job is not blocked')
            if scope['block_kind']=='ledger_mismatch' and not token_reconciled:
                raise ValueError('token reconciliation required before retry')
            attempted = await c.fetchval("SELECT EXISTS(SELECT 1 FROM stage1_keeper_attempts WHERE job_id=$1)", job_id)
            # Persisted signatures bind the plan forever; a retry after a chain
            # effect can only reconcile that same plan, never publish a new root.
            if payout_recovery:
                await c.execute('UPDATE stage1_keeper_jobs SET payout_retry_at=now() WHERE scope_id=$1',scope['id'])
            elif attempted:
                await c.execute("UPDATE stage1_keeper_jobs SET state='running' WHERE id=$1", job_id)
            else:
                if job["export_path"] and Path(job["export_path"]).exists():
                    path = Path(job["export_path"])
                    with export_lock(path.parent, job_id):
                        if path.exists():
                            if hashlib.sha256(path.read_bytes()).hexdigest() != job["export_digest"]:
                                raise ValueError("unpublished export changed")
                            path.unlink()
                await c.execute("DELETE FROM stage1_keeper_proofs WHERE job_id=$1", job_id)
                await c.execute("UPDATE stage1_keeper_jobs SET state='planning',snapshot=NULL,sources=NULL,allocation=NULL,claims=NULL,operations=NULL,export_path=NULL,export_digest=NULL,operation_index=0 WHERE id=$1", job_id)
            if scope['block_kind']=='ledger_mismatch':
                await c.execute("""UPDATE stage1_keeper_scopes SET blocked=false,block_kind=NULL,retry_at=now()
                    WHERE program=$1 AND mint=$2 AND block_kind='ledger_mismatch'""",scope['program'],scope['mint'])
            else:
                await c.execute("UPDATE stage1_keeper_scopes SET blocked=false,block_kind=NULL,retry_at=now() WHERE id=$1", job["scope_id"])

    async def add_scope(self, scope):
        if self.genesis is None:
            raise ValueError("keeper database genesis must be bound before adding scopes")
        ident = digest([scope["program"], scope["hill"], scope["mint"]])
        async with self.pool.acquire() as c:
            await c.execute("""INSERT INTO stage1_keeper_scopes(id,program,city,hill,mint,canon_id,launch,next_week,kind)
                VALUES($1,$2,$3,$4,$5,$6::uuid,$7,$8,$9) ON CONFLICT(id) DO NOTHING""",
                ident, scope["program"], scope["city"], scope["hill"], scope["mint"], uuid.UUID(str(scope["canon_id"])), scope["launch"], scope["next_week"], scope.get("kind","cash"))
        return ident

    async def archive_boundary(self, scope_id, week, inputs):
        try:
            await self._archive_boundary(scope_id, week, inputs)
        except ObjectNotInPrerequisiteStateError as exc:
            if exc.message not in ("account_deleted", "account_deletion_pending"):
                raise
            # The failed archive transaction has rolled back. Keep an alert
            # without its private payload; only this missing boundary waits,
            # including when importing a future week before earlier work.
            await self.alert({"scope": {"id": scope_id}, "job": {"id": None, "week": week}},
                "account_deletion_write_refused", {"week": week, "reason": exc.message, "write": "boundary"})
            raise BoundaryWriteRefused("account_deletion_write_refused") from None

    async def _archive_boundary(self, scope_id, week, inputs):
        # Fail on differing retries, rather than updating historical evidence.
        async with self.pool.acquire() as c, c.transaction():
            await c.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"boundary:{scope_id}:{week}")
            inputs = json.loads(canonical(inputs))
            request_digest = digest(inputs)
            existing = await c.fetchrow("SELECT request_digest FROM stage1_keeper_boundaries WHERE scope_id=$1 AND week=$2", scope_id, week)
            if existing:
                if existing['request_digest'] != request_digest:
                    raise ValueError("boundary archive conflicts with frozen evidence")
                # Validate the exact retry through its retained commitment;
                # do not reinsert erased identity or reread newer projections.
                return
            # Erasure replaces exported files before the finalizer chooses its
            # anonymous marker. Resolve only an exact, authenticated manifested
            # entry to the current witness; arbitrary caller edits still fail.
            manifested=await c.fetchval("""SELECT EXISTS(SELECT 1 FROM stage1_boundary_exports e
                CROSS JOIN LATERAL jsonb_array_elements(e.payload) entry
                WHERE e.redacted_digest IS NOT NULL AND NOT e.suspended
                AND entry->>'scope_id'=$1 AND (entry->>'week')::bigint=$2 AND entry->'inputs'=$3::jsonb)""",
                scope_id,week,canonical(inputs).decode())
            if manifested:
                refreshed=await c.fetchval('SELECT stage1_refresh_archive($1::jsonb)',canonical([dict(scope_id=scope_id,week=week,inputs=inputs)]).decode())
                inputs=json.loads(refreshed)[0]['inputs']
            producer_verified=False
            if inputs["closing"].get("records_digest"):
                scope = await c.fetchrow("SELECT * FROM stage1_keeper_scopes WHERE id=$1", scope_id)
                if inputs['closing'].get('producer_witness'):
                    from .stage1_boundary import verified_archive_records
                    records = await verified_archive_records(c, self.genesis, scope, inputs)
                    producer_verified=True
                else:
                    records = await self.records_at_boundary(c, scope["canon_id"], inputs["closing"])
                if digest(records) != inputs["closing"]["records_digest"]:
                    raise ValueError("record projection does not match attested boundary")
                inputs["closing"].update(records)
            from .stage1_keeper_dung import freeze_dung_opening
            if any(l['owner'].startswith('anonymous:') for l in inputs['opening'].get('dung',{}).get('lots',[])):
                # Cross-asset reuse is authenticated by this database's immutable
                # retained archive, never by caller-supplied digest fields.
                known = await c.fetchval("""SELECT EXISTS(SELECT 1 FROM stage1_keeper_boundaries b
                    JOIN stage1_keeper_scopes s ON s.id=b.scope_id WHERE s.program=$1 AND s.hill=$2 AND b.week=$3
                    AND b.inputs->'opening'=$4::jsonb)""",inputs['context'][0],inputs['context'][2],week,canonical(inputs['opening']).decode())
                if not known and not producer_verified:
                    raise ValueError('new anonymous lot archive is not admissible')
            else:
                inputs['opening'] = freeze_dung_opening(inputs['opening'],inputs['context'])
            inputs["closing"] = freeze_records(inputs["closing"])
            commitment = {k: digest(v) for k,v in inputs.items()}
            await c.execute("""INSERT INTO stage1_keeper_boundaries(scope_id,week,inputs,digest,commitment_inputs,request_digest)
                VALUES($1,$2,$3::jsonb,$4,$5::jsonb,$6)""", scope_id, week,
                canonical(inputs).decode(), digest(commitment), canonical(commitment).decode(),request_digest)
            actual = await c.fetchval("SELECT digest FROM stage1_keeper_boundaries WHERE scope_id=$1 AND week=$2", scope_id, week)
            if actual != digest(commitment):
                raise ValueError("boundary archive conflicts with frozen evidence")
            if inputs['closing'].get('producer_witness'):
                await c.execute('SELECT stage1_indexer_imported($1,$2)',scope_id,week)

    async def records_at_boundary(self, c, canon_id, closing):
        """Capture current projection ONLY against an independent as-of digest.

        Retired canon versions remain lineage history, while record seats come
        from exactly the version active at the close (new_record_board policy).
        Missing historical coverage is never repaired with today's row.
        """
        lineage = await c.fetchrow("""SELECT i.pda,i.canon_version,i.chain_slot,v.id AS vault_id
            FROM indexed_climbs i LEFT JOIN indexed_vaults v ON v.pda=i.vault_pda
             AND v.climb_pda=i.pda AND v.canon_climb_id=i.canon_climb_id
             AND v.canon_commitment_hex=i.canon_commitment_hex AND v.signature_hash_hex=i.commitment_hash_hex
             AND v.canon_binding_status='active'
            WHERE i.canon_id=$1 AND NOT i.quarantined AND i.registered_at < to_timestamp($2)
            ORDER BY i.canon_version DESC LIMIT 1""", canon_id, closing["boundary"])
        if not lineage or lineage["chain_slot"] > closing["slot"]:
            raise ValueError("missing historical canon board binding")
        board = legend = None
        if lineage["vault_id"] is not None:
            board = await c.fetchrow("SELECT entries,chain_slot FROM indexed_leaderboards WHERE vault_id=$1", lineage["vault_id"])
            legend = await c.fetchrow("""SELECT holder,is_active,is_bootstrap,chain_slot,
                floor(extract(epoch from term_start_at))::bigint AS term_start,
                floor(extract(epoch from term_end_at))::bigint AS term_end FROM indexed_legends WHERE vault_id=$1""", lineage["vault_id"])
        if any(row and row["chain_slot"] > closing["slot"] for row in (board, legend)):
            raise ValueError("current record projection is newer than frozen boundary")
        entries = json.loads(board["entries"]) if board and isinstance(board["entries"], str) else board["entries"] if board else []
        return {"record_climb": lineage["pda"], "record_version": lineage["canon_version"],
                "board": [{"person": e["user"], "time_s": int(e["time_s"]), "recorded_at": int(e["recorded_at"])} for e in entries],
                "legend": {"person": legend["holder"], "active": legend["is_active"], "bootstrap": legend["is_bootstrap"],
                           "term_start": legend["term_start"], "term_end": legend["term_end"]} if legend and legend["holder"] else None}

    async def claim(self, scope_id=None, lease_seconds=60):
        token = uuid.uuid4()
        async with self.pool.acquire() as c, c.transaction():
            scope = await c.fetchrow("""SELECT * FROM stage1_keeper_scopes
                WHERE NOT blocked AND retry_at <= now() AND (lease_until IS NULL OR lease_until <= now())
                AND ($1::text IS NULL OR id=$1) ORDER BY next_week,id FOR UPDATE SKIP LOCKED LIMIT 1""", scope_id)
            if not scope:
                return None
            await c.execute("UPDATE stage1_keeper_scopes SET lease_token=$2,lease_until=now()+$3*interval '1 second' WHERE id=$1", scope["id"], token, lease_seconds)
            job_id = digest([scope["id"], scope["next_week"]])
            floor = await c.fetchval("""SELECT coalesce(max(j.floor_slot),0) FROM stage1_keeper_jobs j
                JOIN stage1_keeper_scopes s ON s.id=j.scope_id WHERE s.program=$1 AND s.mint=$2""", scope["program"], scope["mint"])
            await c.execute("""INSERT INTO stage1_keeper_jobs(id,scope_id,week,through_week,state,floor_slot)
                VALUES($1,$2,$3,$3,'planning',$4) ON CONFLICT DO NOTHING""", job_id, scope["id"], scope["next_week"], floor)
            job = unpack(await c.fetchrow("SELECT * FROM stage1_keeper_jobs WHERE id=$1", job_id))
            return {"scope": dict(scope), "token": token, "job": job}

    async def _fence(self, c, claim):
        row = await c.fetchrow("""SELECT id FROM stage1_keeper_scopes WHERE id=$1
            AND lease_token=$2 AND lease_until>now() AND NOT blocked FOR UPDATE""", claim["scope"]["id"], claim["token"])
        if not row:
            raise LeaseLost("Stage 1 keeper lease was lost")

    async def renew(self, claim, seconds=60):
        async with self.pool.acquire() as c, c.transaction():
            await self._fence(c, claim)
            await c.execute("UPDATE stage1_keeper_scopes SET lease_until=now()+$3*interval '1 second' WHERE id=$1 AND lease_token=$2", claim["scope"]["id"], claim["token"], seconds)

    async def snapshot(self, claim, registrations, freeze_at=None, held_people=(), admission_bond=None):
        scope, week = claim["scope"], claim["job"]["week"]
        async with self.pool.acquire() as c, c.transaction():
            # Serialize only the short shared measurement freeze. Asset workers
            # still own separate durable submission leases and claim sets.
            await c.execute("SELECT pg_advisory_xact_lock(hashtextextended($1,0))", f"{scope['program']}:{scope['hill']}:{week}")
            row = unpack(await c.fetchrow("SELECT inputs FROM stage1_keeper_boundaries WHERE scope_id=$1 AND week=$2", scope["id"], week))
            if not row:
                raise WaitingForArchive("missing finalized historical opening/closing archive")
            inputs = row["inputs"]
            expected = [scope["program"], scope["city"], scope["hill"], week, scope["mint"]]
            if inputs["context"] != expected or inputs["canon_id"] != str(scope["canon_id"]) or inputs["launch"] != scope["launch"]:
                raise ValueError("boundary namespace mismatch")
            inputs["kind"] = scope.get("kind", "cash")
            inputs["recipients"] = registrations
            inputs["held_people"] = list(held_people)
            if freeze_at is not None:
                inputs["freeze_at"] = freeze_at
            if admission_bond:
                inputs['admission_bond'] = admission_bond
            shared = await c.fetchval("SELECT inputs FROM stage1_keeper_measurements WHERE program=$1 AND hill=$2 AND week=$3", scope["program"], scope["hill"], week)
            if shared:
                shared = json.loads(shared)
                if any(shared[k] != inputs[k] for k in ("opening", "closing", "canon_id", "launch")):
                    raise ValueError("assets disagree on the frozen hill/week boundary")
                if shared.get('admission_bond'):
                    inputs['admission_bond'] = shared['admission_bond']
                inputs['rider_tie_ranks'] = shared.get('rider_tie_ranks')
                return build_snapshot(inputs, [], shared["rows"])
            rows = await c.fetch(COMPLETIONS_SQL, scope["canon_id"], scope["launch"] + (week + 1) * 604800 + 86400)
            # Already frozen paid-ascent ownership/field survives deletion of a
            # rider's private ride row. Keep only the public receipt facts, not
            # GPS or the mutable user profile. All assets share hill admission.
            prior = await c.fetch("""SELECT inputs FROM stage1_keeper_measurements
                WHERE program=$1 AND hill=$2 AND week < $3 ORDER BY week DESC LIMIT 1""", scope["program"], scope["hill"], week)
            history = json.loads(prior[0]["inputs"])["rows"] if prior else []
            from .stage1_keeper_dung import measured_tss
            measured = []
            for r in rows:
                row = dict(r)
                if isinstance(row.get('_power'), str):
                    row['_power'] = json.loads(row['_power'])
                measured.append(measured_tss(row))
            snapshot = build_snapshot(inputs, measured, history)
            if snapshot['rider_tie_ranks'] is None:
                raise WaitingForArchive('missing historical rider allocation order for this hill/week')
            shared = {k: inputs[k] for k in ("opening", "closing", "canon_id", "launch")}
            shared["rows"] = snapshot["admissions"]
            shared['rider_tie_ranks'] = snapshot.get('rider_tie_ranks')
            if inputs.get('admission_bond'):
                shared['admission_bond'] = inputs['admission_bond']
            await c.execute("INSERT INTO stage1_keeper_measurements(program,hill,week,inputs) VALUES($1,$2,$3,$4::jsonb)",
                            scope["program"], scope["hill"], week, canonical(shared).decode())
            return snapshot

    async def save_plan(self, claim, plan):
        async with self.pool.acquire() as c, c.transaction():
            await self._fence(c, claim)
            job = await c.fetchrow("SELECT state FROM stage1_keeper_jobs WHERE id=$1 FOR UPDATE", claim["job"]["id"])
            if job["state"] != "planning":
                raise ValueError("week plan is already frozen")
            await c.execute("""UPDATE stage1_keeper_jobs SET state='running',snapshot=$2::jsonb,sources=$3::jsonb,
                allocation=$4::jsonb,claims=$5::jsonb,operations=$6::jsonb,floor_slot=$7,
                export_path=$8,export_digest=$9,through_week=$10 WHERE id=$1""", claim["job"]["id"],
                *(canonical(plan[k]).decode() for k in ("snapshot", "sources", "allocation", "claims", "operations")),
                plan["floor_slot"], plan["export_path"], plan["export_digest"], plan["through_week"])
            for leaf in plan["claims"]["leaves"]:
                await c.execute("INSERT INTO stage1_keeper_proofs(job_id,leaf_index,person,leaf,role) VALUES($1,$2,$3,$4::jsonb,$5)",
                    claim["job"]["id"], leaf["index"], leaf["person"], canonical(leaf).decode(), leaf.get("role",-1))

    async def signed(self, claim, signed):
        async with self.pool.acquire() as c, c.transaction():
            await self._fence(c, claim)
            job = claim["job"]
            await c.execute("""UPDATE stage1_keeper_jobs SET signed=$2::jsonb WHERE id=$1 AND signed IS NULL""", job["id"], canonical(signed).decode())
            await c.execute("""INSERT INTO stage1_keeper_attempts(job_id,signature,operation_index,signed)
                VALUES($1,$2,$3,$4::jsonb)""", job["id"], signed["signature"], job["operation_index"], canonical(signed).decode())

    async def advance(self, claim, slot, fee_lamports=None, lookup_deposit=None):
        async with self.pool.acquire() as c, c.transaction():
            await self._fence(c, claim)
            if lookup_deposit is not None:
                await c.execute('UPDATE stage1_keeper_lookup_tables SET deposited_lamports=$2 WHERE address=$1',claim['job']['signed']['lookup_address'],lookup_deposit)
            await c.execute("""UPDATE stage1_keeper_attempts SET finalized_slot=$3,fee_lamports=$4,
                signed=CASE WHEN $5::bigint IS NULL THEN signed ELSE signed||jsonb_build_object('lookup_deposit_lamports',$5::bigint) END WHERE job_id=$1 AND signature=$2""",
                claim["job"]["id"], claim["job"]["signed"]["signature"], slot, fee_lamports,lookup_deposit)
            await c.execute("""UPDATE stage1_keeper_jobs SET operation_index=operation_index+1,signed=NULL,
                floor_slot=greatest(floor_slot,$2),lookup_address=coalesce($3,lookup_address) WHERE id=$1""",
                claim["job"]["id"], slot, claim["job"]["signed"].get("lookup_address"))

    async def failed_transaction(self,claim,evidence):
        async with self.pool.acquire() as c,c.transaction():
            await self._fence(c,claim)
            await c.execute('UPDATE stage1_keeper_attempts SET finalized_slot=$3,fee_lamports=$4 WHERE job_id=$1 AND signature=$2',
                claim['job']['id'],claim['job']['signed']['signature'],evidence['slot'],evidence['fee'])

    async def expired(self, claim, floor):
        async with self.pool.acquire() as c, c.transaction():
            await self._fence(c, claim)
            await c.execute("UPDATE stage1_keeper_jobs SET signed=NULL,floor_slot=greatest(floor_slot,$2) WHERE id=$1", claim["job"]["id"], floor)

    async def complete(self, claim, evidence):
        async with self.pool.acquire() as c, c.transaction():
            await self._fence(c, claim)
            await c.execute("INSERT INTO stage1_keeper_reconciliations(job_id,evidence) VALUES($1,$2::jsonb)", claim["job"]["id"], canonical(evidence).decode())
            await c.execute("UPDATE stage1_keeper_jobs SET state='complete',completed_at=now(),floor_slot=greatest(floor_slot,$2) WHERE id=$1", claim["job"]["id"], evidence["slot"])
            await c.execute("UPDATE stage1_keeper_scopes SET next_week=$2 WHERE id=$1", claim["scope"]["id"], claim["job"]["through_week"] + 1)
            recent = await c.fetch("SELECT snapshot FROM stage1_keeper_jobs WHERE scope_id=$1 AND state='complete' ORDER BY week DESC LIMIT 2", claim["scope"]["id"])
        if len(recent) == 2 and all(not json.loads(r["snapshot"])["ascents"] for r in recent):
            await self.alert(claim, "two_weeks_without_ascents", {"through_week": claim["job"]["week"]})

    async def alert(self, claim, kind, details):
        # Alert insertion does not require a live lease. Losing a fence must
        # never erase the failure that needs an operator's attention.
        async with self.pool.acquire() as c:
            await c.execute("INSERT INTO stage1_keeper_alerts(scope_id,job_id,kind,details) VALUES($1,$2,$3,$4::jsonb)",
                            claim["scope"]["id"], claim["job"]["id"], kind, canonical(details).decode())
        logging.getLogger(__name__).error("stage1_keeper_alert kind=%s scope=%s week=%s", kind, claim["scope"]["id"], claim["job"]["week"])

    async def wait_alert(self, claim, kind):
        async with self.pool.acquire() as c:
            exists = await c.fetchval("SELECT EXISTS(SELECT 1 FROM stage1_keeper_alerts WHERE job_id=$1 AND kind=$2)", claim['job']['id'], kind)
        if not exists:
            await self.alert(claim, kind, {'week': claim['job']['week']})

    async def due_scopes(self, ids, through=None):
        async with self.pool.acquire() as c:
            rows = await c.fetch("""SELECT id, extract(epoch FROM greatest(retry_at,coalesce(lease_until,retry_at))-now()) AS delay
                FROM stage1_keeper_scopes WHERE id=ANY($1::text[]) AND NOT blocked
                AND ($2::bigint IS NULL OR next_week <= $2)""", ids, through)
        due = [r['id'] for r in rows if r['delay'] <= 0]
        return due, min([max(0, float(r['delay'])) for r in rows] or [900]), bool(rows)

    async def block(self, claim, kind, details):
        await self.alert(claim, kind, details)
        async with self.pool.acquire() as c, c.transaction():
            await self._fence(c, claim)
            await c.execute("UPDATE stage1_keeper_jobs SET state='blocked' WHERE id=$1", claim["job"]["id"])
            if kind == "ledger_mismatch":
                await c.execute("UPDATE stage1_keeper_scopes SET block_kind=CASE WHEN blocked THEN block_kind ELSE 'ledger_mismatch' END,blocked=TRUE WHERE program=$1 AND mint=$2", claim["scope"]["program"], claim["scope"]["mint"])
            else:
                await c.execute("UPDATE stage1_keeper_scopes SET blocked=TRUE,block_kind=$2 WHERE id=$1", claim["scope"]["id"],kind)

    async def release(self, claim, delay=0):
        async with self.pool.acquire() as c:
            await c.execute("""UPDATE stage1_keeper_scopes SET lease_token=NULL,lease_until=NULL,
                retry_at=now()+$3*interval '1 second' WHERE id=$1 AND lease_token=$2""", claim["scope"]["id"], claim["token"], delay)

    async def refresh(self, claim):
        async with self.pool.acquire() as c:
            claim["job"] = unpack(await c.fetchrow("SELECT * FROM stage1_keeper_jobs WHERE id=$1", claim["job"]["id"]))
            floor = await c.fetchval("""SELECT coalesce(max(j.floor_slot),0) FROM stage1_keeper_jobs j
                JOIN stage1_keeper_scopes s ON s.id=j.scope_id WHERE s.program=$1 AND s.mint=$2""",
                claim["scope"]["program"], claim["scope"]["mint"])
            claim["job"]["floor_slot"] = max(claim["job"]["floor_slot"], floor)

    async def published(self, program, mint):
        async with self.pool.acquire() as c:
            return [unpack(r) for r in await c.fetch("""SELECT j.* FROM stage1_keeper_jobs j JOIN stage1_keeper_scopes s ON s.id=j.scope_id
                WHERE s.program=$1 AND s.mint=$2 AND j.claims IS NOT NULL""", program, mint)]

    async def record_paid(self, scope, observation):
        """Only after inventory/root reconciliation of a finalized observation."""
        async with self.pool.acquire() as c, c.transaction():
            await c.execute('UPDATE stage1_keeper_jobs j SET floor_slot=greatest(floor_slot,$3) FROM stage1_keeper_scopes s WHERE s.id=j.scope_id AND s.program=$1 AND s.mint=$2',scope['program'],scope['mint'],observation['slot'])
            for receipt in observation["receipts"]:
                # Record an unresolved sponsorship attempt atomically with the
                # paid proof that permits erasure. A paid bit alone can come
                # from an external non-ATA claim: this is an ambiguity hold,
                # not a false assertion that the keeper created the account.
                await c.execute("""INSERT INTO stage1_keeper_token_accounts(fingerprint,observed_slot,established,attempt_signature)
                    SELECT DISTINCT a.operation->>'destination',$3::bigint,false,a.signed->>'signature'
                    FROM stage1_keeper_payout_actions a JOIN stage1_keeper_scopes s ON s.id=a.scope_id
                    WHERE s.program=$1 AND s.mint=$2 AND a.state='ready' AND a.signed IS NOT NULL
                    AND a.operation->>'create_ata'='true' AND a.operation->>'destination' IS NOT NULL
                    AND EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(a.operation->'refs','[]')) r
                        WHERE r->>'claim_set'=$4 AND (r->>'index')::int=$5)
                    ON CONFLICT(fingerprint) DO UPDATE SET attempt_signature=excluded.attempt_signature,creation_excluded=false
                    WHERE NOT stage1_keeper_token_accounts.established AND stage1_keeper_token_accounts.creation_excluded""",scope['program'],scope['mint'],observation['slot'],receipt['claim_set'],receipt['index'])
                claim_set = observation["sets"][receipt["claim_set"]]
                await c.execute("""UPDATE stage1_keeper_proofs p SET paid_slot=$1
                    FROM stage1_keeper_jobs j JOIN stage1_keeper_scopes s ON s.id=j.scope_id
                    WHERE p.job_id=j.id AND s.program=$2 AND s.mint=$3 AND s.hill=$4
                    AND j.week=$5 AND p.leaf_index=$6 AND p.role=$7 AND p.paid_slot IS NULL""",
                    observation["slot"], scope["program"], scope["mint"], claim_set["hill"], claim_set["week"], receipt["index"], receipt.get("role",-1))

    async def reserve_lookup(self, scope, op, address):
        owner=digest([scope['id'],op['_job_id'],op['addresses']])
        async with self.pool.acquire() as c:
            await c.execute('INSERT INTO stage1_keeper_lookup_tables(address,owner_key,scope_id,job_id) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING',address,owner,scope['id'],op['_job_id'])
            row=await c.fetchrow('SELECT owner_key,closed FROM stage1_keeper_lookup_tables WHERE address=$1',address)
            if row['owner_key']!=owner or row['closed']:
                raise RuntimeError('lookup slot reserved; wait for another completed slot')

    async def weekly_costs(self):
        async with self.pool.acquire() as c:
            jobs = [unpack(r) for r in await c.fetch('SELECT * FROM stage1_keeper_jobs ORDER BY week,id')]
            fees = await c.fetch("SELECT job_id,sum(fee_lamports) AS fees,sum((signed->>'lookup_deposit_lamports')::bigint) AS lookup FROM stage1_keeper_attempts WHERE finalized_slot IS NOT NULL GROUP BY job_id")
            payouts = [unpack(r) for r in await c.fetch("SELECT job_id,evidence FROM stage1_keeper_payout_actions WHERE evidence IS NOT NULL")]
            tables = await c.fetch('SELECT job_id,sum(coalesce(deposited_lamports,0)) AS rent FROM stage1_keeper_lookup_tables WHERE NOT closed GROUP BY job_id')
        fee_by_job = {r['job_id']:int(r['fees'] or 0) for r in fees}
        lookup_by_job = {r['job_id']:int(r['lookup'] or 0) for r in fees}
        ata_by_job = {}
        for action in payouts:
            fee_by_job[action['job_id']] = fee_by_job.get(action['job_id'],0) + int(action['evidence'].get('fee',0))
            ata_by_job[action['job_id']] = ata_by_job.get(action['job_id'],0) + int(action['evidence'].get('sponsored_ata_deposits_lamports',0))
            lookup_by_job[action['job_id']] = lookup_by_job.get(action['job_id'],0) + int(action['evidence'].get('lookup_deposit_lamports',0)) - int(action['evidence'].get('lookup_refund_lamports',0))
        # The unique reservation owns the deposit even if erasure completed a
        # signed creation before its transaction-evidence response arrived.
        lookup_by_job = {r['job_id']:int(r['rent']) for r in tables}
        weeks = {}
        for job in jobs:
            entry = weeks.setdefault(job['week'], {'week':job['week'],'fees_lamports':0,'refundable_deposits_lamports':0,'open_claim_sets':0,'sponsored_ata_deposits_lamports':0,'retained_lookup_deposits_lamports':0})
            entry['fees_lamports'] += fee_by_job.get(job['id'],0)
            entry['sponsored_ata_deposits_lamports'] += ata_by_job.get(job['id'],0)
            entry['retained_lookup_deposits_lamports'] += lookup_by_job.get(job['id'],0)
            entry['refundable_deposits_lamports'] += lookup_by_job.get(job['id'],0)
            for publication in job['publications'].values():
                if not publication['closed']:
                    entry['refundable_deposits_lamports'] += publication['account']['lamports']
                    entry['open_claim_sets'] += 1
            for field in ('dung_publication','funding_publication'):
                record = job.get(field)
                if record and not record['closed']:
                    entry['refundable_deposits_lamports'] += record['account']['lamports']
        return list(weeks.values())
