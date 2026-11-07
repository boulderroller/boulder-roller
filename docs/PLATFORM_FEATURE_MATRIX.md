# Platform Feature Matrix — Historical Web Portal vs iOS Snapshot

Current surface authority is [PORTAL_TRUTHS.md](PORTAL_TRUTHS.md) and [MOBILE_TRUTHS.md](MOBILE_TRUTHS.md), with the native app documented in [`ios/README.md`](../ios/README.md).

**Purpose:** Source-of-truth for what ships on Web Portal vs iOS for the current MVP, aligned to the live backend (dev: http://STAGING_LB_IP, Solana devnet IDs in docs/SESSION_3_COMPLETION_REPORT.md). Use this to brief the web and iOS agents; portal Figma is the design source of truth.

## Principles
- Web: full surface area, desktop-first, analytics depth, admin-ish views.
- iOS: ride-first, upload + essentials, light analytics, minimal admin.
- Both: share auth/wallet primitives, respect the same API contracts, keep units consistent (DUNG 9 decimals, CAL, TSS).
- Segment creation: web-only for now (per product call).
- No points→token conversion UI yet; no privacy constraints enforced yet.

## Shared Primitives (both)
- Auth: nonce/verify → JWT; wallet binding.
- Profile: basic user info, wallet address, balances summary.
- Segments: list/nearby, detail, leaderboard (top 10), efforts per ride.
- Rides: list and detail with segment efforts and proof status.
- Balances: CAL (with mint status), points, DUNG (read-only).
- Settings: API base URL env, support/help link; optional theme toggle.

## Web Portal Scope
- **Must:** Dashboard (CAL/points/DUNG summary), segment explorer (search/filter/map), leaderboard explorer, staking dashboard (stake/unstake/claims), ride ingestion status, achievement browser, referral link surface, roadmap/changelog, admin-ish flags/tribunal view.
- **Should:** Analytics panels (power curve, TSS attribution by segment), staking portfolio charts, governance/proposals read-only, basic marketplace surfacing if backed.
- **Will Not (MVP):** On-device recording, offline mode, push notifications, mobile-optimized layout guarantees, native map editing beyond segment creation flow.

## iOS App Scope
- **Must:** Auth (nonce/verify), wallet key mgmt, base URL setting, ride upload (FIT/TCX/GPX), ride detail with matched segments, CAL mint trigger/status, balances display (points/DUNG/CAL), nearby segments (map+list), basic segment detail + top 10 leaderboard, profile summary, referral copy/share.
- **Should:** Simple staking (stake/unstake flows), achievements list (earned/pending), ride history with proof status, in-app notifications feed (polling), offline-aware upload retry.
- **Will Not (MVP):** Full analytics dashboards, admin/tribunal, governance UI, advanced staking analytics, heavy marketplace UI, segment creation, push notifications until infra exists.

## Backend Contracts To Rely On
- Auth: `POST /auth/nonce`, `POST /auth/verify`, `POST /auth/refresh`, `GET /auth/me`.
- Rides: `POST /rides/upload`, `GET /rides`, `GET /rides/{id}`, `GET /rides/{id}/segments`.
- CAL: `GET /cal/balance`, `POST /cal/mint`.
- Segments: `GET /segments/list` (bbox/search), `GET /segments/nearby`, `GET /segments/{id}?` (if added), `GET /leaderboard/{segment_id}?epoch_number=`.
- Staking: `POST /staking/stake`, `POST /staking/unstake`, `GET /staking/claims`, `POST /staking/harvest` (if enabled).
- Achievements (if exposed): `GET /achievements` (list user + available), `GET /achievements/{id}`.
- Referrals (if exposed): `GET /referral/code`, `GET /referral/stats`.
- Health/meta: `GET /health/db` (env check); consider `/meta` if added for version.
- Notes: Staking endpoints exist and are wired to devnet programs per Integration Registry. No points→token conversion endpoints yet.

## Data / UX Constraints
- Env: Base URL http://STAGING_LB_IP (LB → droplet:8080). Solana RPC devnet. Program IDs in docs/INTEGRATION_REGISTRY.md.
- Map tokens: Mapbox token in registry (iOS already configured).
- State: Show pending states for Solana ops (CAL mint, stake/unstake); be resilient to slow RPC.
- Pagination: Web can batch; iOS should paginate and cache lightly.
- Units: DUNG 9 decimals; CAL raw integer; TSS integer; w/kg only if backend returns it.

## Non-Goals / Deferred
- Governance voting flows.
- Marketplace trading flows (beyond simple surfacing on web).
- Points→token conversion UI (post-TGE).
- Push notifications.
- Advanced privacy controls (none required yet).

## Clarified Answers (Dec 2025)
- Segment creation: Web-only for now.
- Staking: Endpoints present and assumed live against devnet.
- Points conversion UI: Not needed yet.
- Privacy: No additional constraints beyond JWT auth.
