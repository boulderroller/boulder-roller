# Coordinated backend deploy: threshold stack + deletion backend

Tim-ratified 2026-08-29: one coordinated deploy AFTER threshold slice .3
(rider surfaces) lands. Nothing below is rider-visible until .3 ships, so we
deploy once. This runbook freezes the ordering; execution waits for the gate.

EXECUTED 2026-08-31 (Tim-approved), deploy commit 0b01d81d:
- Migrations 154 + 155 + 156 applied to live; PostgREST reloaded.
- API + indexer images built from the deploy commit (wheel built in-image).
- API deployed and healthy: /health, /feed/home, /leaderboard 200 internal
  and through Cloudflare; the new threshold release-recovery loop runs
  clean (all-zero passes on empty state).
- INDEXER ROLLED BACK to the prior image: the new indexer hard-refuses
  ABI 0x4B ("ProgramConfig version mismatch: expected 0x4c, got 0x4b"),
  which would have taken ordinary indexing down. New image is tagged
  boulder-repo-indexer:abi0x4c-pending on the droplet — the protocol lane
  switches to it immediately after the program upgrade (retag to latest +
  compose up -d indexer).
- Portal production deploy to Vercel initiated from the same commit.
- iOS: dogfood build of the same commit installed on Tim's device
  (DeviceDev entitlements); TestFlight remains behind the paid Apple
  Developer Program gate.

Previously done (2026-08-29, recorded on beads yyus6 / 8uxpd):
- Migrations 152 (account deletion lifecycle) and 153 (RLS lockdown) are
  APPLIED to the live Supabase project (`qzkqjevawthyboymqrle` — the sole
  project; "boulder-rollers-dev" is its name, not a second environment).
- The deployed API predates all of this and is unaffected (health 200,
  service_role paths verified).

## Ordered steps (execute after 2982.3 lands and is reviewed)

1. **Freeze**: confirm no in-flight codex/protocol-lane deploys; snapshot
   `git log -1 origin/main` as the deploy commit.
2. **Migrations 154 + 155** (threshold authority, provisional hold) via
   `apply_sql_migrations.py` from the deploy commit, full `backend/sql`
   directory (no staging subsets), inside the api container. Both were
   review-verified byte-identical to their Supabase mirrors.
3. **workout-parse wheel rebuild** — MANDATORY with the same image build.
   The threshold ingest path probes-and-abstains on a stale wheel (no
   outage), but every ride abstains from threshold evidence until the wheel
   ships `compute_threshold_power_anchors`.
4. **Backend image build + deploy** (api, indexer) from the deploy commit.
   Includes: deletion lifecycle backend, threshold authority + hold/release,
   release recovery runtime, RLS-gated runner env plumbing
   (`APPROVED_PUBLIC_DATA_API_RLS_*` already in compose defaults as empty —
   only needed when re-running 153-class migrations).
5. **Anchor program upgrade to ABI 0x4C** — protocol-lane coordinated
   (release authority + held-release instructions). Devnet upgrade via the
   protocol agent's flow; addresses from `protocol/anchor/addresses.devnet.json`.
   Backend release paths are gated until the indexer observes the 0x4C ABI.
6. **Portal deploy** (Vercel): main already carries the ledger skin, format
   path, and RankMark primitive; .3 adds the threshold surfaces. Deploy from
   the same commit family as the backend.
7. **iOS**: TestFlight build from main (RankMark assets + deletion recovery
   + threshold vocabulary). N14 consent copy must be resolved (Tim words or
   Tim-delegated functional copy) before the build that enables deletion
   with unuploaded recordings; the path fails closed meanwhile.
8. **Post-deploy verification**: threshold runtime postgres suite against a
   shadow DB; one real ride end-to-end (upload -> evidence row -> no hold
   for established rider); deletion preflight on the audit account
   (no destructive step); Supabase linter glance.

## Standing constraints
- No Strava data purge (revocation-only tool; see qht6b — provider 403 must
  be fixed by refreshing the Strava app credentials before cutover).
- Devnet program upgrade is the protocol lane's hand on the wheel; this
  runbook only sequences it.
- Rollback: images are tagged per deploy; migrations 154/155 are additive
  (new tables/functions + scoped triggers) — rollback = redeploy prior
  image; schema stays (dormant), per the same posture 152/153 hold today.
