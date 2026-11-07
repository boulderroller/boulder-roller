"""Opt-in weekly keeper. Run: python -m app.services.stage1_keeper.

Required only when STAGE1_KEEPER_ENABLED=true: STAGE1_KEEPER_RPC_URL,
STAGE1_KEEPER_PROGRAM_ID, STAGE1_KEEPER_PUBLISHER_KEYPAIR,
STAGE1_KEEPER_EXPORT_DIR, and STAGE1_KEEPER_DATABASE_URL. Cluster allowlist:
STAGE1_KEEPER_ALLOWED_CLUSTERS=localnet (default); add devnet explicitly to
admit its genesis. mainnet-beta also requires the independent
STAGE1_KEEPER_MAINNET_RELEASE_ENABLED=true gate (default false). Remote RPCs
require HTTPS. Credentials stay in memory, outside logs and durable plans.
The keeper database is permanently bound to the admitted genesis before any
scope/archive/plan reuse. An older unbound database with existing keeper state
requires a verified migration; do not adopt it by changing the RPC setting.

--archive imports immutable finalized boundary inputs supplied by the boundary
attestor, never today's indexer state masquerading as history. The JSON is an
array of {scope_id, week, inputs}. Opening live/backing and closing board/earned
Legend evidence must cover the exact boundary; absent history waits for retry.
The producer is app.services.stage1_boundary. Its durable task is keyed by
chain genesis, program, hill and week. The indexer retains single-bank finalized
account checkpoints and contiguous signature replay. At Monday 12:00 UTC the
producer independently decodes the retained bytes, replays supported record
events, and freezes the exact before-boundary state. Missing history/rates hold
the affected opening; closing records can still be retained for the prior week.

The indexer operator owns capture, durable retention, retries and missing-boundary
alerts; the keeper operator imports the resulting JSON with --archive. Compute
SHA-256 over canonical JSON (sorted keys, compact separators, UTF-8): an
independent replay must reproduce closing.records_digest over the exact
{record_climb,record_version,board,legend} projection before import. The importer
checks that digest against the bounded projection, freezes seat order, retains
per-component hashes plus their envelope hash, and refuses differing retries.
Opening live/backing needs the same independently replayable boundary witness;
an opaque evidence string is an attestation, not a verified source proof.

At close+24h grace, the keeper freezes admitted field/ride inputs from
patterns_climb, rides, ride_economic_plans, canon_traversal_evidence and canon_climbs
using COMPLETIONS_SQL and retained weekly admissions; it then hashes the full
measurement and checks independent allocation. Producer-witness imports resolve immutable source records from the same bound
database and check the complete opening/closing envelopes before freezing.
Localnet validation does not enable production or establish real-rider evidence.

Automatic payout uses the publication event's cash terms, counters-first claim
bitmaps, once-only sponsored ATAs, same-person batches of up to four distinct
sets, and serialized packet sizing. Oversized batches split into plain transactions;
only an oversized single needs an ALT, which is deactivated and closed after use.
A durable destination fingerprint prevents re-sponsorship after rent reclaim.
Low SOL waits with a deduplicated alert and resumes automatically when funded. A permanent destination
failure alerts once and leaves that leaf/set open; other leaves continue. DUNG
claims wait 48 hours and respect settlement pause; cash claims and rent recovery
remain available during pauses. No new intake is submitted by this service.

The publisher manifest STAGE1_KEEPER_PUBLISHER_KEYS is a JSON map with distinct
localnet/devnet/mainnet-beta public keys. The loaded secret must match the admitted
cluster's entry. Before every signature and submission, a fresh finalized city
read must name that publisher. Genesis is an additional guard, not key isolation.
Never reuse a local key on a public cluster. This lane exercises localnet only.

The loop has no default step limit. One service-wide DB scheduling query backs
idle work off to 900 seconds; pending signatures retain a short cadence. Periodic
rediscovery admits newly configured hills/assets/DUNG. The existing shared
program_compatibility gate persists the version window: at 0x4C no scope or plan
is created; polling starts work at 0x4D or 0x4E without redeployment. See the supervision
and recovery procedure in docs/runbooks/STAGE1_DEVNET_UPGRADE.md.

Estimated RPC calls per 30 days, not provider credits: the same workload of
10 hills x 2 cash tokens, 100 registered paid people per hill/week, steady funding,
no retries, no boosts/ALTs, and prompt closure now budgets about 170,000 at launch,
six months and twelve months (previously 460,000). Use 30/7 weeks, 57,600 idle Clock
reads and 20,160 shared compatibility/discovery reads. Budget 190 publication
calls and 900 claim/close calls per cash scope-week. For payouts, seven calls per
transaction cover fresh authority before sign/send, blockhash, balance, message
fee, send and finalized transaction evidence. Eight shared status/observation
cycles (including genesis, compatibility, custody inventory and destination reads),
first-ATA rent reads and both closes round this to about nine calls per person,
versus the former 43. Signatures batch up to 256; payouts send before polling;
reconciliation and genesis verification each occur once per payout cycle.
Add DUNG across the same 10 hills (100 riders + 10 distinct backers) and budget
about 220,000 at each age (previously 670,000): approximately 200 publication and
1,000 claim/close calls per hill-week. One cash token plus DUNG is about 175,000
(previously 450,000). The totals are 37%, 33% and 39% of the old estimates;
shared idle/discovery reads set a floor. New SOL checks are included. These are
rounded workload estimates, not production measurements or provider credits.
Age alone no longer adds per-person receipt lookups: closed sets disappear from
RPC inventory while their finalized witnesses remain in PostgreSQL. A warm
observation reads one counter-slice GPA; only new/unsealed headers and changed
paid/count bitmaps need batched account reads (100 per call). After restart,
open-set headers are reloaded once. Unpaid sets, boosts, active lots, long proofs,
node finality, historical witness recovery and retries change payloads/call counts;
GPA provider credits can exceed one credit per call. These are explicit workload
estimates, not a live production measurement.

--costs reports actual finalized transaction fees (including failed transactions),
weekly claim/funding/DUNG refundable deposits, retained ALT deposits, and sponsor
ATA rent separately by week. ALT reservations retain their observed funded
balance until a finalized close/refund witness; missing history waits. The keeper
deactivates unused tables, waits for SlotHashes cooldown and closes to its payer. Recipient ATAs belong to
the recipient, so their rent is sponsor outlay rather than a refundable keeper
balance. Cost summaries are also logged after payout finalization.

"""
import argparse
import asyncio
import json
import os
import logging
from pathlib import Path


async def run(args):
    if os.getenv("STAGE1_KEEPER_ENABLED", "false").lower() not in ("true", "1"):
        return {"state": "disabled"}
    # Keep imports, key/config access, network and database IO behind the flag.
    import asyncpg
    from .stage1_keeper_chain import KeeperChain
    from .stage1_keeper_store import KeeperStore, BoundaryWriteRefused
    from .stage1_keeper_worker import KeeperWorker
    required = ("RPC_URL", "PROGRAM_ID", "PUBLISHER_KEYPAIR", "EXPORT_DIR", "DATABASE_URL")
    settings = {name: os.environ[f"STAGE1_KEEPER_{name}"] for name in required}
    allowed = tuple(s.strip() for s in os.getenv("STAGE1_KEEPER_ALLOWED_CLUSTERS", "localnet").split(","))
    release = os.getenv("STAGE1_KEEPER_MAINNET_RELEASE_ENABLED", "false").lower() in ("true", "1")
    chain = KeeperChain(settings["RPC_URL"], settings["PROGRAM_ID"], settings["PUBLISHER_KEYPAIR"],
                        allowed_clusters=allowed, mainnet_release=release,
                        publisher_keys=json.loads(os.environ['STAGE1_KEEPER_PUBLISHER_KEYS']))
    pool = None
    try:
        await chain.start()
        pool = await asyncpg.create_pool(settings["DATABASE_URL"], min_size=1, max_size=4, command_timeout=30)
        store = KeeperStore(pool)
        await store.bind_genesis(chain.genesis)
        from app.program_compatibility import STAGE1_UNAVAILABLE
        while not (await chain.compatibility(pool)).stage1_available:
            logging.getLogger(__name__).warning(STAGE1_UNAVAILABLE)
            if args.once:
                return {'state': 'not available on this network'}
            await asyncio.sleep(900)
        scopes = await chain.discover()
        ids = [await store.add_scope(scope) for scope in scopes]
        archive_refusals = 0
        if args.archive:
            for entry in json.loads(Path(args.archive).read_text()):
                if entry["scope_id"] not in ids:
                    raise ValueError("archive scope is not admitted on this cluster")
                try:
                    await store.archive_boundary(entry["scope_id"], entry["week"], entry["inputs"])
                except BoundaryWriteRefused:
                    archive_refusals += 1
        from .stage1_keeper_payout import PayoutWorker
        payouts = PayoutWorker(store, chain)
        worker = KeeperWorker(store, chain, settings["EXPORT_DIR"], enabled=True)
        if getattr(args,'costs',False):
            return {'state':'costs','weeks':await store.weekly_costs()}
        if args.retry_job:
            await worker.retry(args.retry_job)
        results = {"archive_refused": archive_refusals} if archive_refusals else {}
        steps = 0
        refresh_at = asyncio.get_running_loop().time()+900
        while args.max_steps is None or steps < args.max_steps:
            if asyncio.get_running_loop().time() >= refresh_at:
                (await chain.compatibility(pool)).require_stage1()
                ids = [await store.add_scope(scope) for scope in await chain.discover()]
                refresh_at = asyncio.get_running_loop().time()+900
            active, delay, remaining = await store.due_scopes(ids, args.through_week)
            if args.through_week is not None and not remaining:
                break
            for scope_id in active:
                result = await worker.run_once(scope_id)
                results[result] = results.get(result, 0) + 1
            for scope_id in await payouts.due(ids):
                result = await payouts.run_once(scope_id)
                results['payout_' + result] = results.get('payout_' + result, 0) + 1
                if result=='finalized':
                    logging.getLogger(__name__).info('stage1_keeper_weekly_costs %s',json.dumps(await store.weekly_costs(),sort_keys=True))
            steps += 1
            if args.once:
                break
            # One database scheduling query for the whole service, not one per
            # scope each second. In-flight signed work keeps its short cadence.
            if active:
                _, delay, _ = await store.due_scopes(ids, args.through_week)
            async with pool.acquire() as c:
                payout_delay = await c.fetchval("SELECT extract(epoch FROM min(payout_retry_at)-now()) FROM stage1_keeper_jobs WHERE state='complete' AND NOT payout_done")
            if payout_delay is not None:
                delay = min(delay, float(payout_delay))
            await asyncio.sleep(max(1, min(900, delay)))
        async with pool.acquire() as c:
            summary = await c.fetch("SELECT id,next_week,blocked FROM stage1_keeper_scopes WHERE id=ANY($1::text[])", ids)
        return {"state": "blocked" if archive_refusals or any(r["blocked"] for r in summary) else "stopped",
                "cluster": chain.cluster, "transitions": results, "scopes": [dict(r) for r in summary],
                'weekly_costs':await store.weekly_costs()}
    finally:
        await chain.close()
        if pool:
            await pool.close()


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--through-week", type=int)
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--archive")
    parser.add_argument('--costs',action='store_true',help='Report retained finalized fees and weekly refundable deposits, then exit')
    parser.add_argument("--retry-job", help="Explicitly resume a blocked job; replan only if no signature was ever persisted")
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result, sort_keys=True))
    if result["state"] == "blocked":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
