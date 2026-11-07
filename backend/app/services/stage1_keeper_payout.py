"""Automatic claims and rent recovery, with durable references and signed bytes.

The asset advisory lock is shared with publication and erasure. Claim terms are
recovered from successful finalized publication logs, never guessed from a set.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from .stage1_keeper_merkle import canonical, digest
from .stage1_keeper_store import unpack
from .stage1_keeper_worker import Blocked, check_accounting
from .stage1_keeper_chain import SettlementPaused, SponsorUnfunded
from .stage1_keeper_abi import cash_terms


async def recover_closed_publication(chain,scope,job,op,observed,event,evidence):
    """A finalized publish can be paid/closed before its first keeper poll."""
    import hashlib
    import struct
    from .stage1_keeper_chain import key
    address = event['claim_set']
    saved = job['signed'].get('publication_witness')
    closed = None
    if address not in observed['sets']:
        if not saved:
            raise Blocked('publication_account_witness_missing',{'week':op['week']})
        prior = saved['set']
        closed = await chain.closure_witness(address,prior['rent_payer'],scope.get('kind','cash'),evidence['slot'])
        if not closed or closed['slot']>observed['slot']:
            raise RuntimeError('publication closure is not yet covered by observation')
        count=event['leaf_count']
        account={**prior,'root':bytes(event['root']).hex(),'total':event['total'],'leaf_count':count,
                 'paid':event['total'],'claimed_count':count,'sealed':True,
                 'bitmap':(bytes([255]*(count//8))+bytes([(1<<(count%8))-1] if count%8 else [])).hex()}
        if op['kind']=='publish':
            terms=event['terms']
            account['metadata_hash']=hashlib.sha256(b'BR-stage1-v2:claim-terms\0'+bytes(key(address))+
                struct.pack('<Qq',terms['cap'],terms['frozen_at'])+bytes(terms['audit_hash'])).hexdigest()
        else:
            account['published_at']=event['published_at']
            account['hill'],account['week']=scope['hill'],op['week']
        observed['sets'][address]=account
    book_closed=None
    if op['kind']=='publish':
        book_address=chain.funding(scope,op['week'])
        current=observed['books'].get(book_address)
        if not current or current.get('closed_source'):
            if not saved or not saved.get('funding'):
                raise Blocked('funding_account_witness_missing',{'week':op['week']})
            prior=saved['funding']
            book_closed=await chain.closure_witness(book_address,prior['rent_payer'],'funding',evidence['slot'],scope,op['week'])
            if not book_closed or book_closed['slot']>observed['slot']:
                raise RuntimeError('funding closure is not yet covered by observation')
            observed['books'][book_address]={**prior,'available':0,'published':True,'holds':op['holds'],'closed_source':True}
    return closed,book_closed


async def capture_publication(store, chain, claim, op, observed, evidence=None):
    if op['kind']=='dung_publish':
        await capture_dung_mint(store,chain,claim,op,observed,evidence)
        return
    if op['kind'] not in ('publish','dung_root'):
        return
    job = claim['job']
    address = chain.dung_claim_address(claim['scope'],op['week'],op['role']) if op['kind']=='dung_root' else chain.claim_address(claim['scope'], op['week'])
    evidence = evidence or await chain.transaction_evidence(job['signed']['signature'], job['floor_slot'])
    event_name = 'Stage1DungRolePublished' if op['kind']=='dung_root' else 'Stage1CashPublished'
    events = [e['data'] for e in evidence['events'] if e['name'] == event_name and e['data']['claim_set'] == address]
    if len(events) != 1:
        raise Blocked('publication_event_missing', {'claim_set': address})
    if (bytes(events[0]['root']).hex(),events[0]['total'],events[0]['leaf_count'])!=(op['root'],op['total'],op['count']):
        raise Blocked('publication_event_plan_mismatch',{'week':op['week']})
    closed,book_closed = await recover_closed_publication(chain,claim['scope'],job,op,observed,events[0],evidence)
    account = observed['sets'][address]
    terms = cash_terms(address, events[0], account) if op['kind']=='publish' else None
    if op['kind']=='dung_root' and (bytes(events[0]['root']).hex()!=account['root'] or events[0]['total']!=account['total'] or events[0]['published_at']!=account['published_at']):
        raise Blocked('dung_publication_event_mismatch', {'claim_set':address})
    publication = {'account': account, 'event': events[0], 'terms': terms,
                   'transaction': evidence, 'closed': closed}
    async with store.pool.acquire() as c, c.transaction():
        await store._fence(c, claim)
        await c.execute("UPDATE stage1_keeper_jobs SET publications=publications||$2::jsonb,floor_slot=greatest(floor_slot,$3) WHERE id=$1",
                        job['id'], canonical({address: publication}).decode(),observed['slot'])
        if op['kind']=='publish':
            book_address = chain.funding(claim['scope'],op['week'])
            await c.execute('UPDATE stage1_keeper_jobs SET funding_publication=$2::jsonb WHERE id=$1',job['id'],
                            canonical({'address':book_address,'account':observed['books'][book_address],
                                       'transaction':evidence,'closed':book_closed}).decode())


async def capture_dung_mint(store,chain,claim,op,observed,evidence=None):
    import hashlib
    import struct
    from .stage1_keeper_chain import key
    address = chain.dung_address(claim['scope'],op['week'])
    evidence = evidence or await chain.transaction_evidence(claim['job']['signed']['signature'],claim['job']['floor_slot'])
    events = [e['data'] for e in evidence['events'] if e['name']=='Stage1DungPublished' and e['data']['dung']==address]
    if len(events)!=1:
        raise Blocked('dung_publication_event_missing', {'dung':address})
    event = events[0]
    data = {**event['input'],'source_snapshot':bytes(event['input']['source_snapshot']).hex()}
    if data != op['input']:
        raise Blocked('dung_publication_input_mismatch', {'dung':address})
    input_bytes = chain.coder.instruction.encode('publish_stage1_dung',{'week':op['week'],'input':event['input']})[16:]
    raw = b''.join(bytes(key(event[k])) for k in ('dung','city','hill','mint')) + struct.pack('<Q',event['week']) + input_bytes
    raw += struct.pack('<4Q',*(event['allocation'][k] for k in ('potential','riders','backers','unminted')))
    raw += event['backer_weight_quarters'].to_bytes(16,'little') + struct.pack('<q',event['frozen_at'])
    account = observed['mints'][address]
    if (hashlib.sha256(b'BR-stage1-v2:dung-publication\0'+raw).hexdigest()!=account['snapshot'] or
        account['role_totals'] != [event['allocation']['riders'],event['allocation']['backers']] or
        account['unminted'] != event['allocation']['unminted'] or
        any(event['allocation'][k] != claim['job']['allocation'][k] for k in ('potential','unminted')) or
        account['role_totals'] != op['input']['payable_role_totals']):
        raise Blocked('dung_publication_commitment_mismatch', {'dung':address})
    async with store.pool.acquire() as c,c.transaction():
        await store._fence(c,claim)
        await c.execute('UPDATE stage1_keeper_jobs SET dung_publication=$2::jsonb,floor_slot=greatest(floor_slot,$3) WHERE id=$1',claim['job']['id'],
                        canonical({'address':address,'account':account,'event':event,'transaction':evidence,'closed':None}).decode(),observed['slot'])


async def reconcile(store, chain, scope, observed):
    jobs = await store.published(scope['program'],scope['mint'])
    for job in jobs:
        for address, publication in job.get('publications',{}).items():
            if address in observed['sets'] or publication.get('closed'):
                continue
            account = publication['account']
            witness = await chain.closure_witness(address,account['rent_payer'],scope.get('kind','cash'),publication['transaction']['slot'])
            if not witness:
                raise Blocked('claim_set_missing_without_closure', {'job':job['id'],'claim_set':address})
            if witness['slot']>observed['slot']:
                raise RuntimeError('claim closure is not yet covered by observation')
            # The successful canonical close enforces full paid/count equality.
            # Derive final bits from that proof, retaining the source witness.
            count = account['leaf_count']
            bitmap = bytes([255]*(count//8)+([(1 << (count%8))-1] if count%8 else []))
            publication['account'] = {**account,'paid':account['total'],'claimed_count':count,'bitmap':bitmap.hex()}
            publication['closed'] = witness
            async with store.pool.acquire() as c:
                await c.execute('UPDATE stage1_keeper_jobs SET publications=publications||$2::jsonb,floor_slot=greatest(floor_slot,$3) WHERE id=$1',job['id'],canonical({address:publication}).decode(),observed['slot'])
        for field,inventory,kind in [('funding_publication','books','funding'),('dung_publication','mints','dung_mint')]:
            retained = job.get(field)
            if not retained or retained.get('closed'):
                continue
            row = observed.get(inventory,{}).get(retained['address'])
            if row and not row.get('closed_source'):
                continue
            account = retained['account']
            owner_scope = {**scope,'hill':account['hill']}
            witness = await chain.closure_witness(retained['address'],account['rent_payer'],kind,
                                                 retained['transaction']['slot'],owner_scope,job['week'])
            if not witness:
                raise Blocked('weekly_record_missing_without_closure', {'week':job['week'],'kind':kind})
            if witness['slot']>observed['slot']:
                raise RuntimeError('weekly closure is not yet covered by observation')
            retained['closed'] = witness
            if kind=='dung_mint':
                retained['account'] = {**account,'minted':account['role_totals'],'published_roles':3}
            async with store.pool.acquire() as c:
                await c.execute(f'UPDATE stage1_keeper_jobs SET {field}=$2::jsonb,floor_slot=greatest(floor_slot,$3) WHERE id=$1',job['id'],canonical(retained).decode(),observed['slot'])
    result = check_accounting(observed,jobs)
    await store.record_paid(scope,observed)
    return result


class PayoutWorker:
    def __init__(self, store, chain):
        self.store, self.chain = store, chain
        if chain is not None:
            chain.store=store

    async def due(self, ids):
        async with self.store.pool.acquire() as c:
            rows = await c.fetch("""SELECT DISTINCT scope_id FROM stage1_keeper_jobs
                WHERE scope_id=ANY($1::text[]) AND state='complete' AND NOT payout_done AND payout_retry_at<=now()""", ids)
        return [r['scope_id'] for r in rows]

    async def delay(self, scope, seconds):
        async with self.store.pool.acquire() as c:
            await c.execute("""UPDATE stage1_keeper_jobs SET payout_retry_at=now()+$2*interval '1 second'
                WHERE scope_id=$1 AND state='complete' AND NOT payout_done""", scope['id'], seconds)

    async def action(self, scope, job_id, operation):
        ident = digest([scope['id'], operation])
        async with self.store.pool.acquire() as c:
            await c.execute("""INSERT INTO stage1_keeper_payout_actions(id,scope_id,job_id,operation,state)
                VALUES($1,$2,$3,$4::jsonb,'ready') ON CONFLICT DO NOTHING""", ident, scope['id'], job_id, canonical(operation).decode())
            return unpack(await c.fetchrow('SELECT * FROM stage1_keeper_payout_actions WHERE id=$1', ident))

    async def persist_signed(self, action, signed):
        async with self.store.pool.acquire() as c:
            return bool(await c.fetchval("""UPDATE stage1_keeper_payout_actions a
                SET signed=$2::jsonb,attempts=attempts||jsonb_build_array($2::jsonb)
                WHERE id=$1 AND state='ready' AND signed IS NULL
                AND NOT EXISTS(SELECT 1 FROM stage1_keeper_jobs j WHERE j.id=a.job_id AND j.export_suspended)
                AND NOT EXISTS(
                  SELECT 1 FROM jsonb_array_elements(coalesce(a.operation->'refs','[]'::jsonb)) ref
                  JOIN stage1_keeper_jobs j ON j.id=ref->>'job_id' WHERE j.export_suspended)
                RETURNING true""",action['id'],canonical(signed).decode()))

    async def fail(self, scope, action, reason):
        if reason not in ('frozen','closed','wrong_owner'):
            raise ValueError('only destination problems are terminal')
        async with self.store.pool.acquire() as c:
            await c.execute("UPDATE stage1_keeper_payout_actions SET state='failed' WHERE id=$1", action['id'])
            seen = await c.fetchval("SELECT EXISTS(SELECT 1 FROM stage1_keeper_alerts WHERE kind='payout_unpayable' AND details->>'destination'=$1)",action['operation']['destination'])
        if not seen:
            await self.store.alert({'scope': scope, 'job': {'id': action['job_id'], 'week': action['operation']['week']}},
                'payout_unpayable', {'destination':action['operation']['destination'],'reason':reason})

    async def defer(self, scope, action, reason, *, finalized=False):
        seconds = min(900,30*2**min(action.get('retries',0),5))
        async with self.store.pool.acquire() as c:
            await c.execute("""UPDATE stage1_keeper_payout_actions SET retry_at=now()+$2*interval '1 second',retries=retries+1,
                signed=CASE WHEN $3 THEN NULL ELSE signed END WHERE id=$1""",action['id'],seconds,finalized)
        await self.store.wait_alert({'scope':scope,'job':{'id':action['job_id'],'week':action['operation']['week']}},reason)

    async def remember_destination(self, fingerprint, slot, evidence=None, *, established=True):
        async with self.store.pool.acquire() as c:
            await c.execute("""INSERT INTO stage1_keeper_token_accounts(fingerprint,observed_slot,creation_signature,sponsored_lamports,established)
                VALUES($1,$2,$3,$4,$5) ON CONFLICT(fingerprint) DO UPDATE SET
                established=stage1_keeper_token_accounts.established OR excluded.established,
                creation_excluded=CASE WHEN excluded.established THEN false ELSE stage1_keeper_token_accounts.creation_excluded END,
                creation_signature=coalesce(stage1_keeper_token_accounts.creation_signature,excluded.creation_signature),
                sponsored_lamports=greatest(stage1_keeper_token_accounts.sponsored_lamports,excluded.sponsored_lamports)""",fingerprint,slot,
                (evidence or {}).get('signature') if (evidence or {}).get('sponsored_ata_deposits_lamports',0) else None,
                (evidence or {}).get('sponsored_ata_deposits_lamports',0),established)

    async def failed_evidence(self,action,status):
        evidence = await self.chain.transaction_evidence(action['signed']['signature'],status['slot'],allow_failed=True)
        evidence.pop('events',None)
        prior=action.get('evidence') or {}
        evidence['fee'] = prior['fee'] if prior.get('signature')==evidence['signature'] else evidence['fee']+prior.get('fee',0)
        async with self.store.pool.acquire() as c:
            await c.execute("UPDATE stage1_keeper_payout_actions SET evidence=$2::jsonb,signed=signed-'bytes',attempts=(SELECT coalesce(jsonb_agg(a-'bytes'),'[]'::jsonb) FROM jsonb_array_elements(attempts) a) WHERE id=$1",
                            action['id'],canonical(evidence).decode())
        return evidence

    async def _finish(self, scope, action, observed, status):
        op = action['operation']
        evidence = await self.chain.transaction_evidence(action['signed']['signature'], status['slot'])
        evidence.pop('events', None)
        evidence['fee'] += (action.get('evidence') or {}).get('fee',0)
        if op['kind'] in ('cash_claim','dung_claim'):
            await self.remember_destination(op['destination'],status['slot'],evidence)
        if op['kind']=='lookup':
            address = action['signed']['lookup_address']
            evidence['lookup_deposit_lamports'] = await self.chain.lookup_deposit(address,status['slot'])
            if evidence['lookup_deposit_lamports'] is None:
                raise Blocked('lookup_effect_mismatch', {'action':action['id']})
            evidence['lookup_address'] = address
        if op['kind']=='lookup_close':
            if await self.chain.lookup_exists(op['address'],status['slot']):
                raise Blocked('lookup_close_effect_mismatch',{})
            evidence['lookup_refund_lamports']=op['lamports']
        async with self.store.pool.acquire() as c, c.transaction():
            if op['kind']=='lookup':
                await c.execute('UPDATE stage1_keeper_lookup_tables SET deposited_lamports=$2 WHERE address=$1',evidence['lookup_address'],evidence['lookup_deposit_lamports'])
            if op['kind']=='lookup_close':
                await c.execute('UPDATE stage1_keeper_lookup_tables SET closed=true WHERE address=$1',op['address'])
            if op['kind'] in ('cash_close','dung_close'):
                if op['claim_set'] in observed['sets']:
                    raise Blocked('closure_effect_mismatch', {'action': action['id']})
                # Absence alone is insufficient: require this successful finalized
                # instruction and the retained fully paid bitmap before closure.
                await c.execute("""UPDATE stage1_keeper_jobs SET publications=jsonb_set(publications,$2::text[],$3::jsonb)
                    WHERE id=$1""", action['job_id'], [op['claim_set'], 'closed'], canonical(evidence).decode())
            elif op['kind'] in ('funding_close','dung_mint_close'):
                field,inventory,address = ('funding_publication','books',op['funding']) if op['kind']=='funding_close' else ('dung_publication','mints',op['dung'])
                account = observed[inventory].get(address)
                if account and not account.get('closed_source'):
                    raise Blocked('weekly_closure_effect_mismatch', {'action':action['id']})
                await c.execute(f"UPDATE stage1_keeper_jobs SET {field}=jsonb_set({field},'{{closed}}',$2::jsonb) WHERE id=$1",
                                action['job_id'],canonical(evidence).decode())
            await c.execute("UPDATE stage1_keeper_payout_actions SET state='complete',evidence=$2::jsonb,signed=signed-'bytes',attempts=(SELECT coalesce(jsonb_agg(a-'bytes'),'[]'::jsonb) FROM jsonb_array_elements(attempts) a) WHERE id=$1",
                            action['id'], canonical(evidence).decode())
            await c.execute('UPDATE stage1_keeper_jobs SET floor_slot=greatest(floor_slot,$2) WHERE id=$1',action['job_id'],status['slot'])

    async def weekly_close(self, scope, job, observed):
        dung = scope.get('kind')=='dung'
        field,inventory = ('dung_publication','mints') if dung else ('funding_publication','books')
        address = self.chain.dung_address(scope,job['week']) if dung else self.chain.funding(scope,job['week'])
        retained,account = job.get(field),observed[inventory].get(address)
        if retained and retained.get('closed'):
            return None
        if not account:
            return None  # Skipped week never created a record.
        if account.get('closed_source'):
            raise Blocked('weekly_closure_witness_missing',{'week':job['week']})
        record = {**(retained or {}),'address':address,'account':account if dung else (retained or {}).get('account',account),
                  'close_account':account,'closed':None,
                  'transaction':(retained or {}).get('transaction',{'slot':observed['slot']})}
        async with self.store.pool.acquire() as c:
            await c.execute(f'UPDATE stage1_keeper_jobs SET {field}=$2::jsonb WHERE id=$1',job['id'],canonical(record).decode())
        return {'kind':'dung_mint_close' if dung else 'funding_close','week':job['week'],
                'dung' if dung else 'funding':address,'rent_payer':account['rent_payer']}

    async def expired_lookup(self,scope,action,status):
        op=action['operation']
        address=action['signed'].get('lookup_address') or op['address']
        try:
            if op['kind']=='lookup':
                exists=await self.chain.lookup_exists(address,status['slot'])
                await self.defer(scope,action,'lookup_history_wait' if exists else 'lookup_retry',finalized=not exists)
                return
            state,_=await self.chain.lookup_state(address,status['slot'])
            if op['kind']=='lookup_close' and state=='missing':
                evidence=await self.chain.lookup_close_witness(address)
                if not evidence:
                    await self.defer(scope,action,'lookup_history_wait')
                    return
            elif op['kind']=='lookup_deactivate' and state in ('cooling','closeable'):
                evidence={'deactivation_observed':status['slot']}
            else:
                await self.defer(scope,action,'lookup_retry',finalized=True)
                return
            async with self.store.pool.acquire() as c,c.transaction():
                prior=action.get('evidence') or {}
                if 'fee' in evidence:
                    evidence['fee']=prior['fee'] if prior.get('signature')==evidence.get('signature') else evidence['fee']+prior.get('fee',0)
                await c.execute("UPDATE stage1_keeper_payout_actions SET state='complete',evidence=coalesce(evidence,'{}')||$2::jsonb,signed=signed-'bytes',attempts=(SELECT coalesce(jsonb_agg(a-'bytes'),'[]'::jsonb) FROM jsonb_array_elements(attempts) a) WHERE id=$1",action['id'],canonical(evidence).decode())
                if op['kind']=='lookup_close':
                    await c.execute('UPDATE stage1_keeper_lookup_tables SET closed=true WHERE address=$1',address)
                    await c.execute('UPDATE stage1_keeper_jobs SET floor_slot=greatest(floor_slot,$2) WHERE id=$1',action['job_id'],evidence['slot'])
        except Exception:
            await self.defer(scope,action,'lookup_history_wait')

    async def recover_missing_lookup(self,scope,job,address):
        # A reservation can precede signing. Erasure may also have
        # completed a signed creation after external self-payment.
        async with self.store.pool.acquire() as c:
            candidates=[unpack(r)['signed'] for r in await c.fetch("SELECT signed FROM stage1_keeper_payout_actions WHERE signed->>'lookup_address'=$1 UNION SELECT signed FROM stage1_keeper_attempts WHERE signed->>'lookup_address'=$1",address)]
        statuses=await self.chain.status_batch(candidates) if candidates else {}
        witness=await self.chain.lookup_close_witness(address) if candidates else None
        if witness:
            action=await self.action(scope,job['id'],{'kind':'lookup_close','week':job['week'],'address':address,'lamports':witness['lookup_refund_lamports']})
            prior=action.get('evidence') or {}
            witness['fee']=prior['fee'] if prior.get('signature')==witness['signature'] else witness['fee']+prior.get('fee',0)
            async with self.store.pool.acquire() as c:
                await c.execute("UPDATE stage1_keeper_payout_actions SET state='complete',evidence=$2::jsonb WHERE id=$1",action['id'],canonical(witness).decode())
                await c.execute('UPDATE stage1_keeper_jobs SET floor_slot=greatest(floor_slot,$2) WHERE id=$1',job['id'],witness['slot'])
        async with self.store.pool.acquire() as c:
            deposit=await c.fetchval('SELECT deposited_lamports FROM stage1_keeper_lookup_tables WHERE address=$1',address)
        if witness or deposit is None and all(statuses[s['signature']]['state'] in ('failed','expired') for s in candidates):
            async with self.store.pool.acquire() as c:
                await c.execute('UPDATE stage1_keeper_lookup_tables SET closed=true WHERE address=$1',address)
        return witness['slot'] if witness else 0

    async def run_once(self, scope_id):
        async with self.store.pool.acquire() as c:
            scope = dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes WHERE id=$1', scope_id))
        async with self.store.asset_lock(scope) as locked:
            if not locked:
                return 'asset_busy'
            async with self.store.pool.acquire() as c:
                scope = dict(await c.fetchrow('SELECT * FROM stage1_keeper_scopes WHERE id=$1', scope_id))
            try:
                @asynccontextmanager
                async def offline_cycle():
                    yield
                async with (self.chain.cycle() if hasattr(self.chain,'cycle') else offline_cycle()):
                    return await self._locked(scope)
            except SettlementPaused:
                async with self.store.pool.acquire() as c:
                    job = await c.fetchrow("SELECT id,week FROM stage1_keeper_jobs WHERE scope_id=$1 AND NOT payout_done ORDER BY week LIMIT 1",scope['id'])
                if job:
                    await self.store.wait_alert({'scope':scope,'job':dict(job)},'settlement_paused')
                await self.delay(scope, 900)
                return 'settlement_paused'
            except Blocked as exc:
                # A custody mismatch fences the whole mint; never pay around it.
                async with self.store.pool.acquire() as c:
                    await c.execute("UPDATE stage1_keeper_scopes SET blocked=true,block_kind='ledger_mismatch' WHERE program=$1 AND mint=$2",
                                    scope['program'], scope['mint'])
                async with self.store.pool.acquire() as c:
                    job = await c.fetchrow("SELECT id,week FROM stage1_keeper_jobs WHERE scope_id=$1 ORDER BY week DESC LIMIT 1",scope['id'])
                if job:
                    await self.store.wait_alert({'scope':scope,'job':dict(job)},exc.kind)
                await self.delay(scope,900)
                return 'blocked'
            except (RuntimeError, asyncio.TimeoutError):
                await self.delay(scope, 30)
                return 'retry'
            except Exception:
                # No exception text: provider errors can contain credentials.
                async with self.store.pool.acquire() as c:
                    job=await c.fetchrow('SELECT id,week FROM stage1_keeper_jobs WHERE scope_id=$1 ORDER BY week DESC LIMIT 1',scope['id'])
                if job:
                    await self.store.wait_alert({'scope':scope,'job':dict(job)},'unexpected_payout_error')
                await self.delay(scope,30)
                return 'retry'

    async def _locked(self, scope):
        if scope['blocked'] and scope['block_kind'] not in (
            'account_deletion_write_refused','invalid_measurement','oracle_disagreement','boost_attributed_release_abi',
            'dung_payable_total_mismatch','dung_signed_operation_mismatch'):
            return 'blocked'
        async with self.store.pool.acquire() as c:
            jobs = [unpack(r) for r in await c.fetch("SELECT * FROM stage1_keeper_jobs WHERE scope_id=$1 AND state='complete' AND NOT payout_done ORDER BY week",scope['id'])]
            actions = [unpack(r) for r in await c.fetch('SELECT * FROM stage1_keeper_payout_actions WHERE scope_id=$1 ORDER BY created_at,id',scope['id'])]
        if not jobs:
            return 'idle'
        floor=await self.store.asset_floor(scope)
        pending=[a for a in actions if a['state']=='ready' and a['signed']]
        statuses = (await self.chain.status_batch([a['signed'] for a in pending]) if hasattr(self.chain,'status_batch') else
                    {a['signed']['signature']:await self.chain.status(a['signed']) for a in pending}) if pending else {}
        unsettled=False
        finalized,expired=[],[]
        for action in pending:
            status=statuses[action['signed']['signature']]
            floor=max(floor,status.get('slot',0))
            if action['retry_at']>datetime.now(timezone.utc):
                unsettled=True
                continue
            if status['state']=='finalized':
                finalized.append((action,status))
            elif status['state']=='failed':
                try:
                    evidence=await self.failed_evidence(action,status)
                except Blocked:
                    raise
                except Exception:
                    await self.defer(scope,action,'payout_evidence_wait')
                    unsettled=True
                    continue
                status['unfunded']=status.get('unfunded') or evidence.get('unfunded')
                if status.get('paused') or status.get('unfunded'):
                    await self.defer(scope,action,'settlement_paused' if status.get('paused') else 'sponsor_unfunded',finalized=True)
                elif len(action['operation'].get('refs',[]))>1:
                    # The parent raises no alert. Diagnose each leaf separately.
                    async with self.store.pool.acquire() as c:
                        await c.execute("UPDATE stage1_keeper_payout_actions SET state='complete',evidence=evidence||jsonb_build_object('split',true) WHERE id=$1",action['id'])
                else:
                    await self.defer(scope,action,'payout_retry',finalized=True)
            elif status['state']=='expired':
                if action['operation']['kind'] in ('lookup','lookup_deactivate','lookup_close'):
                    await self.expired_lookup(scope,action,status)
                    floor=max(floor,await self.store.asset_floor(scope))
                    unsettled=True
                    continue
                expired.append((action,status))
            else:
                unsettled=True
                if status['state']=='absent' and action['retry_at']<=datetime.now(timezone.utc):
                    try:
                        await self.chain.submit(action['signed'])
                    except Exception as exc:
                        await self.defer(scope,action,'sponsor_unfunded' if isinstance(exc,SponsorUnfunded) else 'payout_retry')
        observed=await self.chain.observe(scope,jobs[0]['week'],floor)
        # Record our successful closes before reconciliation, avoiding a history
        # scan for a closure whose exact finalized signature is already known.
        for action,status in finalized:
            if action['operation']['kind'] not in ('cash_claim','dung_claim'):
                try:
                    await self._finish(scope,action,observed,status)
                except Blocked:
                    raise
                except Exception:
                    await self.defer(scope,action,'payout_evidence_wait')
                    unsettled=True
        await reconcile(self.store,self.chain,scope,observed)
        for action,status in expired:
            op=action['operation']
            if op.get('destination') and any(any(r['claim_set']==ref['claim_set'] and r['index']==ref['index']
                for r in observed['receipts']) for ref in op.get('refs',[])):
                # External claims may use a non-ATA account. Preserve ambiguity
                # until exact creation evidence or a valid ATA is observed.
                await self.remember_destination(op['destination'],observed['slot'],established=False)
            async with self.store.pool.acquire() as c:
                await c.execute("UPDATE stage1_keeper_payout_actions SET state='complete',evidence=coalesce(evidence,'{}')||$2::jsonb,signed=signed-'bytes',attempts=(SELECT coalesce(jsonb_agg(a-'bytes'),'[]'::jsonb) FROM jsonb_array_elements(attempts) a) WHERE id=$1",
                    action['id'],canonical({'expired_without_signature':status,'observed':observed['slot']}).decode())
        for action,status in finalized:
            if action['operation']['kind'] in ('cash_claim','dung_claim'):
                if not all(any(r['claim_set']==ref['claim_set'] and r['index']==ref['index'] for r in observed['receipts']) for ref in action['operation']['refs']):
                    raise Blocked('payout_effect_mismatch',{'action':action['id']})
                try:
                    await self._finish(scope,action,observed,status)
                except Blocked:
                    raise
                except Exception:
                    await self.defer(scope,action,'payout_evidence_wait')
                    unsettled=True
        async with self.store.pool.acquire() as c:
            jobs=[unpack(r) for r in await c.fetch("SELECT * FROM stage1_keeper_jobs WHERE scope_id=$1 AND state='complete' AND NOT payout_done ORDER BY week",scope['id'])]
            actions=[unpack(r) for r in await c.fetch('SELECT * FROM stage1_keeper_payout_actions WHERE scope_id=$1 ORDER BY created_at,id',scope['id'])]
            reserved=[dict(r) for r in await c.fetch('SELECT * FROM stage1_keeper_lookup_tables WHERE scope_id=$1',scope['id'])]
        leaves,by_job=[],{j['id']:j for j in jobs}
        identity=lambda r:(r['job_id'],r.get('role',-1),r['index'])
        failed={identity(r) for a in actions if a['state']=='failed' for r in a['operation'].get('refs',[])}
        split={identity(r) for a in actions if (a.get('evidence') or {}).get('split') for r in a['operation'].get('refs',[])}
        closing,finished,waiting=[],set(),900
        role_jobs = [(job,role,claims) for job in jobs for role,claims in
                     (list(enumerate(job['claims']['roles'])) if scope.get('kind')=='dung' else [(-1,job['claims'])])]
        for job,role,claims in role_jobs:
            address = self.chain.dung_claim_address(scope,job['week'],role) if role>=0 else self.chain.claim_address(scope, job['week'])
            if not any(op['kind'] in ('publish','dung_root') for op in job['operations']):
                operation = await self.weekly_close(scope,job,observed)
                if operation:
                    closing.append((job,operation))
                    continue
                finished.add(job['id'])
                continue
            if job.get('export_suspended'):
                # Only this job waits for its atomic export rewrite. Other
                # sets and hills remain payable under the same custody checks.
                await self.store.wait_alert({'scope':scope,'job':job},'export_suspended_for_deletion')
                continue
            publication = job['publications'].get(address)
            if not publication:
                raise Blocked('publication_event_missing', {'job': job['id']})
            if publication['closed']:
                if not all(p['closed'] for p in job['publications'].values()):
                    continue
                operation = await self.weekly_close(scope,job,observed)
                if operation:
                    closing.append((job,operation))
                    continue
                finished.add(job['id'])
                continue
            account = observed['sets'].get(address)
            if not account:
                raise Blocked('claim_set_missing_without_closure', {'claim_set': address})
            if account['paid']==account['total'] and account['claimed_count']==account['leaf_count']:
                # Freeze final bitmap and counters BEFORE signing its close.
                async with self.store.pool.acquire() as c:
                    await c.execute("UPDATE stage1_keeper_jobs SET publications=jsonb_set(publications,$2::text[],$3::jsonb) WHERE id=$1",
                                    job['id'], [address, 'account'], canonical(account).decode())
                closing.append((job, {'kind':'dung_close' if role>=0 else 'cash_close', 'week':job['week'], 'claim_set': address, 'rent_payer':account['rent_payer']}))
                continue
            if role >= 0 and observed['now'] < account['published_at']+172800:
                waiting = min(waiting, account['published_at']+172800-observed['now'])
                continue
            bits = bytes.fromhex(account['bitmap'])
            for leaf in claims['leaves']:
                if not bits[leaf['index']//8] & (1 << (leaf['index']%8)) and (job['id'],role,leaf['index']) not in failed:
                    leaves.append({**leaf, 'claim_set': address, 'job_id':job['id'], 'role':role, 'terms':publication['terms'], **({'dung':account['dung']} if role>=0 else {})})
        now=datetime.now(timezone.utc)
        ready=[a for a in actions if a['state']=='ready']
        # One creation per destination can be in flight across every hill/set.
        async with self.store.pool.acquire() as c:
            history={r['fingerprint']:dict(r) for r in await c.fetch('SELECT * FROM stage1_keeper_token_accounts')}
            known={k:v['established'] for k,v in history.items() if not v['creation_excluded']}
            in_flight=set(await c.fetchval("SELECT coalesce(array_agg(operation->>'destination'),ARRAY[]::text[]) FROM stage1_keeper_payout_actions a JOIN stage1_keeper_scopes s ON s.id=a.scope_id WHERE s.program=$1 AND s.mint=$2 AND a.state='ready' AND a.signed IS NOT NULL AND operation->>'create_ata'='true'",scope['program'],scope['mint']))
        if leaves:
            slot,destinations=await self.chain.destinations(scope,leaves,observed['slot'])
            observed['slot']=max(observed['slot'],slot)
        else:
            destinations={}
        available=[]
        for leaf in leaves:
            fingerprint=self.chain.destination_fingerprint(scope,leaf)
            state=destinations[self.chain.destination(scope,leaf)]
            if state=='valid':
                # A pre-existing destination is also never re-created later.
                await self.remember_destination(fingerprint,observed['slot'])
                known[fingerprint]=True
            if state=='missing' and fingerprint in known:
                if not known[fingerprint]:
                    candidate=history[fingerprint].get('attempt_signature')
                    proof=None
                    if candidate:
                        try:
                            proof=await self.chain.sponsorship_evidence(scope,fingerprint,candidate)
                        except Exception:
                            pass
                    if proof and proof['established']:
                        await self.remember_destination(fingerprint,proof['slot'],proof)
                        known[fingerprint]=True
                    elif proof:
                        async with self.store.pool.acquire() as c:
                            await c.execute('UPDATE stage1_keeper_token_accounts SET creation_excluded=true WHERE fingerprint=$1 AND NOT established',fingerprint)
                        del known[fingerprint]
                    else:
                        await self.store.wait_alert({'scope':scope,'job':by_job[leaf['job_id']]},'sponsorship_history_wait')
                        waiting=min(waiting,30)
                        continue
                if known.get(fingerprint):
                    state='closed'
            if state in ('frozen','closed','wrong_owner'):
                ref={k:leaf[k] for k in ('job_id','role','index','claim_set')}
                action=await self.action(scope,leaf['job_id'],{'kind':'dung_claim' if scope.get('kind')=='dung' else 'cash_claim',
                    'week':by_job[leaf['job_id']]['week'],'refs':[ref],'destination':fingerprint})
                await self.fail(scope,action,state)
                # Unsigned retries of this leaf must not remain executable.
                async with self.store.pool.acquire() as c:
                    for prior in ready:
                        if not prior['signed'] and any(identity(r)==identity(ref) for r in prior['operation'].get('refs',[])):
                            await c.execute("UPDATE stage1_keeper_payout_actions SET state='complete' WHERE id=$1",prior['id'])
                continue
            if fingerprint not in in_flight:
                available.append({**leaf,'create_ata':state=='missing','destination':fingerprint})
        by_ref={identity(l):l for l in available}
        work,covered=[],set()
        for action in ready:
            refs=action['operation'].get('refs',[])
            if action['signed']:
                covered.update(identity(r) for r in refs)
                continue
            if refs and not all(identity(r) in by_ref for r in refs):
                if any(any(p['claim_set']==r['claim_set'] and p['index']==r['index'] for p in observed['receipts']) for r in refs):
                    async with self.store.pool.acquire() as c:
                        await c.execute("UPDATE stage1_keeper_payout_actions SET state='complete',evidence=coalesce(evidence,'{}')||jsonb_build_object('externally_paid',true) WHERE id=$1 AND signed IS NULL",action['id'])
                continue
            covered.update(identity(r) for r in refs)
            if action['retry_at']<=now:
                work.append(action)
            else:
                waiting=min(waiting,max(1,int((action['retry_at']-now).total_seconds())))
        remaining=[l for l in available if identity(l) not in covered]
        batches=[]
        singles=[l for l in remaining if identity(l) in split]
        for leaf in singles:
            batches.extend(self.chain.payout_batches(scope,[leaf],dung=scope.get('kind')=='dung'))
        batches.extend(self.chain.payout_batches(scope,sorted([l for l in remaining if identity(l) not in split],key=lambda l:(l['person'],l['recipient'],l['claim_set'])),dung=scope.get('kind')=='dung'))
        for batch in batches:
            refs=[{k:l[k] for k in ('job_id','role','index','claim_set')} for l in batch['leaves']]
            operation={k:v for k,v in batch.items() if k!='leaves'}
            operation.update(week=by_job[refs[0]['job_id']]['week'],refs=refs,destination=batch['leaves'][0]['destination'],
                             generation=sum(a['operation'].get('refs')==refs for a in actions))
            work.append(await self.action(scope,refs[0]['job_id'],operation))
        for job,operation in closing:
            prior=[a for a in actions if all(a['operation'].get(k)==v for k,v in operation.items())]
            if not any(a['state']=='ready' for a in prior):
                work.append(await self.action(scope,job['id'],{**operation,'generation':len(prior)}))
        # Publication tables and the rare deep-proof table have the same durable
        # deactivate/cooldown/close lifecycle. Keep the job due until refund.
        for job in jobs:
            tables=set([job['lookup_address']] if job.get('lookup_address') else [])
            tables.update(r['address'] for r in reserved if r['job_id']==job['id'] and not r['closed'])
            tables.update(a['evidence']['lookup_address'] for a in actions if a['job_id']==job['id'] and a['operation']['kind']=='lookup' and a['state']=='complete' and (a.get('evidence') or {}).get('lookup_address'))
            for address in tables:
                closed=any(a['operation']['kind']=='lookup_close' and a['operation']['address']==address and a['state']=='complete' and (a.get('evidence') or {}).get('lookup_refund_lamports') is not None for a in actions)
                if closed or any(r['address']==address and r['closed'] for r in reserved):
                    continue
                finished.discard(job['id'])
                dependents=actions+work
                creators=[a for a in actions if (a.get('evidence') or {}).get('lookup_address')==address]
                reservation=next((r for r in reserved if r['address']==address),None)
                if any(a['state']=='ready' and a['operation']['kind']=='lookup' and
                    ((a.get('signed') or {}).get('lookup_address')==address or
                     reservation and digest([scope['id'],a['job_id'],a['operation'].get('addresses')])==reservation['owner_key']) for a in actions):
                    continue
                if any(a['state']=='ready' and (a['operation'].get('lookup')==address or
                    any(a['operation'].get('lookup_addresses') and a['operation']['lookup_addresses']==t['operation'].get('addresses') for t in creators)) for a in dependents):
                    continue
                try:
                    state,lamports=await self.chain.lookup_state(address,observed['slot'])
                except Exception:
                    await self.store.wait_alert({'scope':scope,'job':job},'lookup_cleanup_wait')
                    waiting=min(waiting,30)
                    continue
                if state=='missing':
                    try:
                        recovered_floor=await self.recover_missing_lookup(scope,job,address)
                        observed['slot']=max(observed['slot'],recovered_floor)
                    except Exception:
                        await self.store.wait_alert({'scope':scope,'job':job},'lookup_cleanup_wait')
                    waiting=min(waiting,30)
                    continue
                async with self.store.pool.acquire() as c:
                    await c.execute('UPDATE stage1_keeper_lookup_tables SET deposited_lamports=$2 WHERE address=$1',address,lamports)
                if state=='cooling':
                    waiting=min(waiting,30)
                    continue
                op={'kind':'lookup_deactivate' if state=='active' else 'lookup_close','week':job['week'],'address':address,'lamports':lamports}
                if not any(a['state']=='ready' and a['operation']['kind']==op['kind'] and a['operation'].get('address')==address for a in ready):
                    work.append(await self.action(scope,job['id'],op))
        sent=False
        # No status polling inside this loop: all independent work goes first.
        for action in {a['id']:a for a in work}.values():
            try:
                operation=dict(action['operation'])
                if operation['kind'] in ('cash_claim','dung_claim'):
                    if not all(identity(r) in by_ref for r in operation['refs']):
                        continue
                    expanded=[by_ref[identity(r)] for r in operation['refs']]
                    fingerprint=expanded[0]['destination']
                    if fingerprint in in_flight:
                        continue
                    operation.update(leaves=expanded,create_ata=expanded[0]['create_ata'])
                    if operation.get('lookup_addresses'):
                        table=None
                        for candidate in reversed(actions):
                            address=(candidate.get('evidence') or {}).get('lookup_address')
                            if candidate['state']!='complete' or candidate['operation']['kind']!='lookup' or candidate['operation'].get('addresses')!=operation['lookup_addresses'] or not address:
                                continue
                            if any(a['operation']['kind'] in ('lookup_deactivate','lookup_close') and a['operation']['address']==address for a in actions+work):
                                continue
                            state,_=await self.chain.lookup_state(address,observed['slot'])
                            if state=='active':
                                table=candidate
                                break
                        if table:
                            operation['lookup']=table['evidence']['lookup_address']
                            async with self.store.pool.acquire() as c:
                                await c.execute("UPDATE stage1_keeper_payout_actions SET operation=operation||$2::jsonb WHERE id=$1",action['id'],canonical({'lookup':operation['lookup']}).decode())
                        else:
                            prior=[a for a in actions if a['operation']['kind']=='lookup' and a['job_id']==action['job_id'] and a['operation'].get('addresses')==operation['lookup_addresses']]
                            lookup=next((a for a in prior if a['state']=='ready'),None)
                            if lookup is None:
                                lookup=await self.action(scope,action['job_id'],{'kind':'lookup','week':operation['week'],'addresses':operation['lookup_addresses'],'refs':operation['refs'],'generation':len(prior)})
                                actions.append(lookup)
                            if lookup['signed'] or lookup['retry_at']>now:
                                continue
                            action,operation=lookup,lookup['operation']
                    if operation['kind'] in ('cash_claim','dung_claim') and operation['create_ata']:
                        in_flight.add(fingerprint)
                signed=await self.chain.prepare(scope,{**operation,'_job_id':action['job_id']},observed['slot'])
                if await self.persist_signed(action,signed):
                    await self.chain.submit(signed)
                    sent=True
            except Exception as exc:
                # Signatures remain durable on ambiguous submission. Low SOL,
                # program refusals and unexpected work-item errors never kill
                # the service or become an unpayable leaf.
                await self.defer(scope,action,'sponsor_unfunded' if isinstance(exc,SponsorUnfunded) else
                    'settlement_paused' if isinstance(exc,SettlementPaused) else 'payout_retry')
                waiting=min(waiting,30)
        if finished:
            async with self.store.pool.acquire() as c:
                await c.execute("""UPDATE stage1_keeper_jobs j SET payout_done=true WHERE id=ANY($1::text[])
                    AND NOT EXISTS(SELECT 1 FROM stage1_keeper_payout_actions a WHERE a.state='ready' AND
                        (a.job_id=j.id OR EXISTS(SELECT 1 FROM jsonb_array_elements(coalesce(a.operation->'refs','[]')) r WHERE r->>'job_id'=j.id)))""",list(finished))
        await self.delay(scope,2 if sent or unsettled else waiting)
        return 'submitted' if sent else 'reconciling' if unsettled else 'finalized' if finalized else 'idle'
