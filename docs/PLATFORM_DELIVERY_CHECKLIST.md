# Platform Delivery Checklist — Web Portal & iOS

Use this to hand off tasks to the web and iOS agents. Keep commits scoped; update Integration Registry after key milestones.

## Shared Preflight
- Base URL set to `http://STAGING_LB_IP` (dev LB).
- Solana devnet IDs loaded (see docs/INTEGRATION_REGISTRY.md).
- Auth flow verified: `/auth/nonce` → `/auth/verify` → `/auth/me`.
- Mapbox token available (in registry).
- Error/pending states for Solana ops (stake/unstake, CAL mint) visible.

## Web Portal Handoff
- Env/config: Frontend env points to dev API; map token wired; feature flags for staking on.
- Feature wiring: Segment explorer (list/nearby), segment detail + leaderboard (epoch input), staking dashboard (stake/unstake/claims), ride list/detail with segment efforts, CAL mint status display, achievements list (if API exposed), referrals (if API exposed).
- Analytics: Power/TSS panels if data available; otherwise placeholder with “coming soon.”
- Admin-ish: Flags/tribunal view (if backend route exists) read-only is fine.
- Non-goals: No on-device recording, no push, no governance vote flows, no points→token UI.
- QA: Basic auth flow, segment search with bbox/nearby, stake/unstake happy path, CAL mint once-per-day enforcement, ride upload flow (manual file), leaderboard read, error states for RPC failures.

## iOS App Handoff
- Env/config: Base URL configurable (default dev); Mapbox token in Info.plist; Solana devnet IDs bundled or fetched.
- Feature wiring: Auth (nonce/verify), wallet key mgmt, ride upload (FIT/TCX/GPX), ride list/detail with matched segments, CAL mint trigger/status, balances (points/DUNG/CAL), nearby segments (map+list), segment detail + top 10 leaderboard, profile summary, referral copy/share.
- Nice-to-have: Simple staking (stake/unstake), achievements list (earned/pending), in-app notifications feed (polling), offline-aware upload retry.
- Non-goals: Full analytics dashboards, admin/tribunal, governance UI, advanced staking analytics, marketplace UI, push notifications, segment creation.
- QA: Build with current deps (Kingfisher, TweetNacl), auth round-trip against dev API, upload a ride and view matched segments, CAL mint once per day, stake/unstake smoke test if enabled, leaderboard read, base URL switch test.

## Backend Touchpoints (for both)
- Auth: `/auth/nonce`, `/auth/verify`, `/auth/refresh`, `/auth/me`.
- Rides: `/rides/upload`, `/rides`, `/rides/{id}`, `/rides/{id}/segments`.
- CAL: `/cal/balance`, `/cal/mint`.
- Segments: `/segments/list`, `/segments/nearby`, `/leaderboard/{segment_id}?epoch_number=`.
- Staking: `/staking/stake`, `/staking/unstake`, `/staking/claims`, `/staking/harvest` (if enabled).
- Achievements/referrals: Only if endpoints are exposed; otherwise defer UI.
- Health: `/health/db` for env checks.
