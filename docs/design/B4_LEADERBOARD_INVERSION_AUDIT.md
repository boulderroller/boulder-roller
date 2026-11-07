# B4 — Leaderboard Truth Direction Inversion: Audit

**Bead:** `boulderroller-v2-mfab.3`
**Date:** 2026-04-17
**Author:** Backend agent (worktree `agent-ac59d308`)
**Status:** Audit complete — safe-fix path confirmed.

---

## Summary

`backend/app/services/leaderboard_sync_service.py` inverts the TRUTHS arrow of
truth: its docstring names DB as source of truth and chain as mirror. This
violates `BACKEND_TRUTHS §10.1` / §10.3 and `PROTOCOL_TRUTHS §5.1` /
§5.3.

The audit confirms:

1. The chain **is** already authoritative for `VaultLeaderboard`.
   Receipt-backed `record_climb_completion` writes directly to the
   `VaultLeaderboard` PDA via `leaderboard.update_entry(...)`; the retained
   receipt-less compatibility instruction now fails closed.
2. `distribute_epoch_rewards` reads the on-chain `VaultLeaderboard` PDA
   directly for Record Royalty payout — it does not read DB.
3. There is no live DB→chain write path. The sync service's own comments
   (lines 367–375) admit "we don't have a direct `admin_update_leaderboard`
   instruction yet … For now, just detect and log the mismatch." The only
   DB→chain instruction on-chain is `admin_replace_vault_leaderboard`, which
   is gated on `!activation.is_active` (historical pre-activation seeding
   only).
4. The indexer **already** projects on-chain VaultLeaderboard into a DB cache
   table — `indexed_leaderboards`, written by `indexer/src/writers/leaderboard.ts`
   from the on-chain account decode. This is the canonical projection path.
5. `vault_leaderboards` (the table `leaderboard_sync_service.py` reads) is a
   parallel DB-native leaderboard populated by SQL functions
   (`record_vault_completion_with_best_time` etc.) called from the backend's
   ride processor, the backfill service, and the vault activation service.
   This table is a **legacy projection** that predates the indexer
   `indexed_leaderboards` table and is what the existing "sync" service
   compares to chain.

The inversion is therefore not only docstring-level — the *existence* of the
sync service's DB→chain direction claim is cargo-cult. No code path actually
writes DB→chain. The sync service's only real behavior is "compare and
report," which is a read-layer verification task, and its docstring misnames
the truth direction.

The fix is safe: gut the DB→chain framing, keep the comparison/verification
capability as a chain-projection consistency check, and rename/refactor the
docstrings + helper verbs. The §10.1 gate test flips PASS once the three
drift regexes no longer match the module.

---

## Phase A findings (detailed)

### A1. What `_sync_leaderboards_before_distribution()` actually does

`backend/app/services/epoch_processor.py:325–362`.

- **Reads from:** DB (`vault_leaderboards` via `LeaderboardSyncService`), then
  on-chain `VaultLeaderboard` PDA (for comparison).
- **Writes:** nothing to chain. It only updates `indexed_vaults.onchain_sync_status`
  and inserts rows into `leaderboard_sync_log` for audit.
- **Blocking?** No — swallows exceptions, logs a warning, and continues. The
  comment explicitly says "Don't fail distribution if sync fails" and
  "Continuing with distribution using DB state." The word "using DB state"
  is itself misleading: `distribute_epoch_rewards` reads the on-chain
  VaultLeaderboard PDA, not DB, so the downstream distribution does **not**
  depend on this sync step at all.

The pre-distribution invocation was cargo-cult under the inverted model: it
was placed there because the old mental model said "DB needs to match chain
before we distribute." Under correct TRUTHS framing, the invocation is
unnecessary — the chain already holds authoritative leaderboard state that
the distribute instruction consumes directly.

### A2. Is chain `VaultLeaderboard` authoritative today?

**Yes, unambiguously.**

- `protocol/anchor/programs/boulder_rollers/src/lib.rs:586` (`record_climb_completion`)
  calls `leaderboard.update_entry(rider.key(), completion_time_s, completed_at)`.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs:1323` (`record_vault_completion`)
  calls `leaderboard.update_entry(user.key(), completion_time_s, completed_at)`.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs:1871` (`distribute_epoch_rewards`)
  reads `let leaderboard = &ctx.accounts.vault_leaderboard;` and iterates
  `leaderboard.entries` for Record Royalty payout.

The only DB→chain write-side is `admin_replace_vault_leaderboard` (line 2288),
which is activation-only (`require!(!activation.is_active, …)`) and exists to
seed historical pre-activation leaderboards from Strava imports — not to
reconcile drift on live vaults.

### A3. Callers of `_sync_leaderboards_before_distribution()`

Single caller: `_process_epoch_end` in `epoch_processor.py:181`. Called once
per settlement week transition.

### A4. What `distribute_epoch_rewards` reads

From `lib.rs:1871`: reads `vault_leaderboard` PDA directly. Does not read
DB at all. The backend-side sync step has zero bearing on what the chain
distributes — confirmed by the on-chain source.

### A5. Other paths writing to `vault_leaderboards` DB

- `backend/sql/047_full_leaderboard.sql:215` defines
  `record_vault_completion_with_best_time(p_vault_signature, p_wallet, …)` —
  an SQL function that UPSERTs `vault_leaderboards` on each completion.
  Called from `projection_writer.record_vault_completion_with_best_time()`.
- `backend/sql/050_tiebreaker.sql`, `053_leaderboard_metadata.sql`,
  `054_leaderboard_flagging.sql`, `055_leaderboard_notifications.sql`,
  `059_fix_leaderboard_function.sql` — successor / augmented variants.
- `backend/app/services/vault_activation_service.py:549,586` — reads DB
  leaderboard to push historical entries via `admin_replace_vault_leaderboard`
  at activation time (one-way, pre-activation only, legitimate).
- `backend/app/services/backfill_service.py:22` — updates DB leaderboards
  during historical backfill.

**Indexer/NATS path:** the indexer writes `VaultLeaderboard` PDA state into
`indexed_leaderboards` (JSONB entries, one row per vault), written by
`indexer/src/writers/leaderboard.ts`. This is the canonical chain→DB
projection. The `vault_leaderboards` table is a separate, DB-native
leaderboard maintained by ride-processing SQL calls.

**Gap note:** `vault_leaderboards` is not downstream of chain. It's a
parallel ingest path where the backend writes DB on ride processing, the
chain writes its own `VaultLeaderboard` PDA independently, and the two can
drift. The "sync" service exists to observe this drift. Under TRUTHS, the
cache (`indexed_leaderboards`) is the right source for reads, and
`vault_leaderboards` is a legacy shape that will want consolidation in a
follow-up bead (see Follow-ups below).

---

## Phase B plan (safe fix)

The audit confirms a clean safe-fix path exists. Execute:

1. **Invert the module docstring.** Rewrite the file-level docstring to say
   "DB mirrors chain, not the reverse," cite `BACKEND_TRUTHS §10.1` and
   `§10.3`, and add a 0uv8 recovery-plan comment describing where to patch
   when `VaultLeaderboard` chain fields change.

2. **Reframe the class docstring + method docstrings** away from "source of
   truth" language. The service becomes a **verifier** that detects
   projection drift, never a syncer that pushes DB→chain. Rename nothing at
   the module-file / class level to keep diff small — callers (admin routes,
   tasks, epoch_processor) don't need to change. The `sync_vault_leaderboard`
   method stays named for back-compat but its docstring says "verify chain
   vs DB cache."

3. **Retire `_sync_leaderboards_before_distribution` as a no-op precursor.**
   Since `distribute_epoch_rewards` reads chain directly and the sync was
   never writing to chain, the pre-distribution invocation is cargo-cult. I
   will convert it into an explicit read-only `_verify_leaderboard_projection_before_distribution`
   observability step whose docstring states it is pure observability —
   drift does not block distribution, it is logged for indexer-health
   dashboards. Keep the invocation so operators still get the audit log
   entries but rename to signal intent.

4. **Update the existing callers' docstrings/comments** (admin routes, tasks,
   method-level) to talk about "verify" / "check" rather than "sync to chain."
   No behavior change — the underlying `sync_vault_leaderboard` method already
   only compares and logs.

5. **Add module-level citations** to `§10.1` and `§10.3` + a note explaining
   that any future DB→chain reconciliation must go through reindex from
   on-chain `VaultLeaderboard` via the indexer, per `§10.3`.

6. **Verify §10.1 gate flips PASS.** The three drift regex patterns must all
   fail to match the module source.

7. **Spot-check service tests** touching leaderboard code do not regress.

### Scope — explicitly NOT touched

- `protocol/anchor/` (protocol lane, iced agent).
- `vault_leaderboards` DB column/table shape (storage detail, separate
  migration concern — `§10.1` is about truth direction, not schema).
- `/leaderboard/*` API contracts (routes/climbs.py, routes/leaderboards.py
  unchanged — Gate 1 §12 covers naming separately).
- Mobile / portal.
- `vault_activation_service.py` pre-activation seeding — legitimate
  one-way DB→chain path for historical import (gated on
  `!activation.is_active`). Leave as-is.

### Follow-up beads to consider (NOT part of this PR)

- **FB-1:** Consolidate `vault_leaderboards` and `indexed_leaderboards`.
  The DB currently holds two parallel leaderboards — one written from ride
  processing (`vault_leaderboards`) and one projected from chain
  (`indexed_leaderboards`). Reads should migrate to `indexed_leaderboards`
  so the read layer is chain-rooted by definition. This is a bigger lift —
  covers API routes, vault_repository, climbs route, etc. — and belongs
  under a successor of the `mfab` epic. Flag to dispatcher.
- **FB-2:** Remove `vault_leaderboards` write-side from the ride-processing
  SQL function `record_vault_completion_with_best_time`. Once FB-1 lands,
  the ride-processing path should write chain only, and
  `indexed_leaderboards` catches up via the indexer. Today's ride processor
  writes both in parallel — by design for migration readability, but
  redundant long-term.
- **FB-3:** Delete the `sync-status` admin endpoints and the sync log table
  once the indexer projection is the only chain→DB arrow. Today they're
  retained for operator observability during the transition.

These follow-ups are structural. This PR stays minimal.

---

## Gift-posture self-check

- **Does the arrow of truth flow chain → DB, never DB → chain?** After the
  fix: yes. The module no longer claims DB is authoritative, the pre-
  distribution call is renamed to reflect verification-only intent, and the
  docstrings cite `§10.1`/§10.3.
- **Would protocol agent smile?** The clean inversion preserves all existing
  behavior (the module never wrote to chain anyway) while restoring
  TRUTHS-coherent framing. No functional regression, pure semantic clean-up.
- **0uv8 recovery plan:** added to the module top-of-file comment.

---

## Gate status forecast

- **Before:** §10.1 leaderboard-direction gate FAILs (intentional DRIFT).
- **After:** §10.1 leaderboard-direction gate PASSes; the rest of Gate 1
  unchanged (PASS × 10, SKIP × 1, FAIL × 0 expected).
