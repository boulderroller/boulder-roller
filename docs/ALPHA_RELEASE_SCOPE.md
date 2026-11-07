# Boulder Rollers — Alpha Release Scope
**Status:** HISTORICAL — earlier Alpha scope and precedence
**Last updated:** 2026-04-08
**Audience:** Cofounders + product/eng leads

Follow the TRUTHS-first hierarchy in [FRESHEST_SPEC.md](FRESHEST_SPEC.md#source-of-truth-hierarchy) for current authority; the scope and precedence below are retained as history.

> ⚠️ **UPDATE (April 2026):** Points system removed. CAL/DUNG tokens are live on devnet.
> CAL is earned from TSS, tributed to vaults, converted to DUNG (1000:1). See `docs/FRESHEST_SPEC.md`.

## 0) TL;DR
Alpha is an **invite-only, small-cohort** release to validate the Boulder Rollers core loop:

1) **Upload a ride** → 2) **automatic pattern detection** (Climb / Steady / Exploration) → 3) **leaderboards + identity (Beetle Cards)** → 4) **CAL earned** (from TSS), tributed to vaults, converted to DUNG.

Anything that doesn’t directly prove this loop (or keep it stable/safe) is out of scope for Alpha.

---

## 1) Sources of truth (use these when conflicts appear)
This scope is derived from the latest in-repo sources. If documents conflict, prefer them in this order:

1. `docs/ALPHA_RELEASE_SCOPE.md` (this file)
2. `docs/TILE_ATTESTATION_ARCHITECTURE.md` (product/architecture intent: tile → patterns)
3. `docs/design/WEB_PORTAL_WIRING_SPEC.md` (portal routes/states; “patterns not segments” UX)
4. `docs/INTEGRATION_REGISTRY.md` (live envs + program IDs; do not copy secrets out of it)
5. `docs/rfcs/ingest-v2.md` (planned scaling path; not required for Alpha unless explicitly pulled in)
6. `docs/MVP_DEMO_GUIDE.md` + `docs/PLATFORM_DELIVERY_CHECKLIST.md` (demo/QA scripts)
7. Legacy context (helpful, not authoritative for Alpha): `docs/DUNG_BEETLE_CYCLING_COMPLETE.md`, `docs/PLATFORM_FEATURE_MATRIX.md`

---

## 2) What Alpha is (and is not)
### Alpha is:
- A **closed, invite-gated** product surface for ~10–50 riders.
- A **learning release**, optimized for fast iteration and qualitative feedback.
- **Devnet-first** (crypto components are real integrations, but economic value is “test-mode”).
- A chance to validate the **tile-based, pattern-first** differentiation (not Strava segment matching).

### Alpha is not:
- A public launch.
- A promise of stable token economics, governance, or marketplace mechanics.
- A mainnet deployment or any “real money” claim.

---

## 3) Alpha goals (the outcomes we’re trying to prove)
### 3.1 Product hypotheses
- Riders understand and value **Patterns** (Climb/Steady/Exploration) as primary objects.
- Effort-based competition (e.g., W/kg-ish climb ranking) is compelling even without Strava-like “KOM segments”.
- Earning CAL from effort and staking in vaults is an understandable, repeatable action that feels fair and optional.
- Beetle Cards provide a motivating identity/progression layer without feeling childish.

### 3.2 System hypotheses
- Ride ingest + pattern detection is reliable enough for a small cohort (even if not yet “Ferrari ingest”).
- Wallet-based auth is acceptable friction for our early adopters, with clear trust moments.
- Devnet integration is stable (no constant RPC flakiness) and failures degrade gracefully (pending/retry states).

---

## 4) Scope boundaries (what’s in / out)
### 4.1 In-scope (Must ship in Alpha)
**Access + onboarding**
- Landing waitlist capture and basic contact surface.
- Invite gate UX in front of the app.
- Wallet-based authentication (nonce/sign/verify) and session persistence.
- Minimal profile setup/editing (username, FTP/weight, units, theme).

**Core loop**
- Upload ride files (FIT/GPX/TCX) and view processing status.
- Pattern detection on processed rides:
  - ClimbPattern (multiple per ride)
  - SteadyPattern (0–1 per ride)
  - ExplorationPattern (0–1 per ride)
- Ride detail view that surfaces patterns + a human summary (no raw tile jargon).
- Pattern-based leaderboards (week/today/month/all-time, where supported).
- Beetle Cards:
  - “My cards” view with level + progress to next
  - Leaderboards by card type (and scope when applicable)

**Token System (Live on Devnet)**
- CAL earned automatically from TSS, tributed to Vaults crossed.
- CAL balance display and earning history.
- Vault staking with CAL (deposit/withdraw/collect rewards).
- Settlement Week finalization (weekly, 24-hour grace window) with per-bucket discrete allocation — Record Board / stakers / Local Legend / protocol / POL.

**Safety + operability**
- Rate limiting on sensitive endpoints (uploads, scoring).
- Admin kill switches for uploads/minting/staking (emergency controls).
- Health endpoint(s) for uptime checks.

### 4.2 In-scope (Should ship if time permits)
- Social “light”: follow/unfollow, global feed, kudos/comments on rides.
- Arenas list + filtering for climb leaderboards (World Arena baseline is acceptable).
- Basic map experience for rides (polyline display) and “areas explored” summaries (no tile IDs).
- Simple portfolio surface for staking claims (read-only first, transact second).
- Invite enforcement on the backend (not only client-side gating).

### 4.3 Explicitly out of scope for Alpha (Non-goals)
**Scale & infra**
- Ingest v2 (presigned uploads, NATS, Rust ingest worker) unless pulled in explicitly.
- Full CI/CD automation and production-grade monitoring/alerting (basic uptime + logs only).

**Product**
- Real-time ride recording (post-hoc file ingest only).
- Push notifications.
- Strava-like user-defined segment creation and polyline matching (“Flows” are post-alpha).
- Full governance (Local Legend management UI), proposals, voting.
- Marketplace/store purchases beyond placeholder UX.
- Token “cash out” surface or DEX integration.
- Advanced analytics dashboards (TrainingPeaks-class) beyond minimal summaries.
- Full privacy controls beyond baseline authentication and “don’t expose tiles”.

---

## 5) System scope by component
### 5.1 Web Portal (primary Alpha surface)
**Must**
- Gate → wallet auth → setup.
- Upload ride → processing UI (queued/processing/completed/failed).
- Ride list + ride detail (patterns summary + statuses).
- Patterns view (filter by type; show scoreable patterns).
- Leaderboards (Climb/Steady/Exploration) + basic filters.
- Vault staking flow (deposit/withdraw/collect) and clear pending/success/error states.
- Profile edit + explicit save feedback.

**Should**
- Feed + interactions (kudos/comments) if stable.
- Portfolio view for staking claims; staking transactions only if reliability is high.

### 5.2 iOS (secondary Alpha surface)
Alpha iOS is “nice if ready,” not the gate for Alpha shipping.

**Must (if we ship iOS in Alpha)**
- Wallet key management + auth with the backend.
- Ride upload (file share/import) and ride list/detail.
- Pattern display and summary.
- Leaderboards read.

**Should**
- Vault staking UI.
- Simple profile editing + settings (API base URL).

### 5.3 Backend API
Alpha requires a stable, documented contract for:
- Auth + profile: `/auth/*`, `/users/me`, `/users/check-username`
- Rides: `/rides`, `/rides/upload`, `/rides/{id}/status`, `/rides/{id}/patterns`, (optional) `/rides/{id}/gps`
- Leaderboards: `/leaderboard/climb`, `/leaderboard/steady`, `/leaderboard/exploration`, `/leaderboard/arenas`
- CAL/DUNG: `/cal/onchain`, `/distributions/*`, `/portfolio/*`
- Beetles: `/beetles/my-cards`, `/beetles/leaderboard/*`
- Vaults: `/vaults`, `/vaults/{id}/stake`, `/vaults/{id}/complete`
- Waitlist: `POST /waitlist`
- Optional social: `/social/*`, `/feed/*`, `/rides/{id}/kudos`, `/rides/{id}/comments`
- Admin ops: `/admin/*`, `/health/*`

### 5.4 Protocol (Solana)
**Alpha requirement**
- Devnet deployments and stable RPC integration for DUNG minting operations invoked by backend scoring.

**Not required for Alpha**
- Mainnet deployment.
- Full on-chain representation of every Alpha concept (backend caching is acceptable where needed).

---

## 6) Release criteria (“Alpha is shippable when…”)
Alpha is ready when these are true for a small test cohort:

1. Invite-gated users can authenticate and create/edit a profile without support.
2. Ride upload works end-to-end for common FIT/GPX/TCX files, with clear status + failure states.
3. At least one pattern type (Climb) is consistently detected and displayed; Steady/Exploration can be “best effort” but must not break the UI.
4. Leaderboards load reliably and do not expose internal tile IDs/jargon.
5. Score-for-DUNG works (or shows pending and later reconciles) and never double-scores the same pattern.
6. Admin can pause uploads/minting quickly if something goes wrong.

---

## 7) Alpha success metrics (what we’ll measure)
Pick targets before starting Alpha; these are the metrics to instrument:

- Activation: % of invited users who complete wallet auth + upload 1 ride.
- Time-to-value: median time from upload → “patterns visible”.
- Reliability: upload success rate, processing failure rate, median/95p processing time.
- Pattern usefulness: % of rides with ≥1 detected pattern; user-reported “that looks right”.
- Engagement: rides/week per active user; leaderboard views/week; feed interactions.
- Monetization proxy: % of active users who score ≥1 pattern; CAL utilization rate.

---

## 8) Open decisions (cofounder calls)
- **Invite enforcement:** purely UX (front-end) vs hard backend enforcement for Alpha.
- **Devnet vs mainnet:** Alpha stays devnet; decide when “Beta” requires mainnet.
- **Staking in Alpha:** ship read-only portfolio vs enable stake/unstake in-app.
- **Map privacy posture:** show full user polyline by default vs opt-in.
- **Ingest v2 timing:** keep base64 + Celery for Alpha, or pull partial v2 early (presigned uploads only).
