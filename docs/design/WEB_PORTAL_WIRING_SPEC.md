# Web Portal Wiring Spec (for Figma) — Boulder Roller

Purpose: scoped, implementation-aware brief so screens/states match the live wiring work. This repo (`docs/design/Boulderrollercopy-main`) already has most UI scaffolding; below maps each surface to real data, states, and backend contracts from `docs/INTEGRATION_REGISTRY.md` and `docs/PLATFORM_FEATURE_MATRIX.md`, and folds in the latest tile-based attestation/pattern architecture (`docs/TILE_ATTESTATION_ARCHITECTURE.md`, `docs/TILE_IMPLEMENTATION_PLAN.md`, `docs/CLIMB_PATTERN_IMPLEMENTATION.md`). Frontend needs to stop surfacing “segments” to users—use effort patterns (Climb / Steady / Exploration) as the primary UX objects.

## Environment & Primitives
- Base API (browser): same-origin `/api` facade (rewritten upstream to `https://api.boulderroller.xyz`; local dev proxy target `http://localhost:8080`). Main portal auth uses HttpOnly cookies; only lightweight UI flags belong in localStorage.
- Auth: wallet-based nonce/verify (`POST /auth/nonce`, `POST /auth/verify`, `POST /auth/refresh`, `GET /auth/me`). Invite gating sits in front of auth.
- Invite gate (current UI: beetle click x3 → InviteModal): should call a backend check; on success set `br_access=granted` and proceed to wallet auth.
- Wallet connect: Phantom/Solflare/Backpack/Glow; sign nonce → store JWT; show wallet address in TopNav + ProfileSheet.
- Themes: tokens in ThemeContext; heavy use of monospace numbers; 3px borders + offset shadows. Preserve light/dark and art palettes.
- Global states to design: loading, success, error, empty, unauthenticated, and “gate-locked” for each surface.

## Screen Wiring Map (routes in `src/App.tsx`)
- `/` InviteGate: three-click beetle → InviteModal → WalletConnect → SetupModal (username, FTP, weight, rider type). Needs error/success for invite and wallet, plus optional skip.
- `/` ActivityFeed (home): replace mocks with paginated feed (`GET /rides` + social if available). States: loading skeleton, empty feed, item click → ActivityDetailModal, double-click → open detail. Include infinite scroll/pagination, real timestamps, kudos/comments if exposed; otherwise placeholders labeled “coming soon”.
- `/activities/:activityId` RideView: data from `GET /rides/{id}` + pattern summaries (attestations) instead of segments. Show detected patterns (ClimbPattern, SteadyPattern, ExplorationPattern) with stats: vert/time/power if present, new areas count. States: loading, 404, Solana pending (mint/attest), error, map unavailable, patterns empty.
- `/my-activities` MyActivities: list of user rides (`GET /rides`). Filters by date/type; empty state CTA → UploadActivityModal. Include upload flow `POST /rides/upload` (drag/drop FIT/GPX), with progress, success, error, duplicate file. After upload, surface tile/pattern detection status (pending/complete/failed).
- `/patterns` (replace `/my-segments`): user effort patterns from attestations (Climb/Steady/Exploration). Backed by `/rides/{id}` pattern payloads or dedicated endpoints if added. States: no patterns yet, filters by pattern type, leaderboard slots optional.
- `/arenas/:arenaId` (replace `/segments/:segmentId`): if Arenas are exposed, show region summary (name, “area tiles” obfuscated), recent top patterns, leaderboard per pattern type. Otherwise keep placeholder with “coming soon”.
- `/map` Map: nearby effort density. Until tile APIs are public, show “areas explored” and “recent climbs” using rides’ pattern summaries. States: geolocation denied, no results, loading clusters, hover/click card details.
- `/leaderboard` Leaderboard: pattern leaderboards (per pattern type, per arena if available). Inputs for timeframe/arena/pattern; states: loading, empty, slow.
- `/portfolio` Portfolio: staking dashboard wired to `/staking/stake`, `/staking/unstake`, `/staking/claims`, `/staking/harvest` (if on). States: pending Solana tx, success toast, failure (RPC), no positions, claim available. Show CAL/DUNG balances (`GET /cal/balance`) and LP tokens.
- `/data` Data: analytics panels; if backend lacks data, show “coming soon” with expected metrics (power curve, TSS attribution). Keep space for charts fed by rides + pattern aggregates (e.g., climbs per week, new areas per ride).
- `/profile` Profile: user settings from `/auth/me` and `PUT /users/me` (when added). Fields: username, bio, FTP, weight, rider type, units, theme, dark toggle, wallet, notifications. Save button with saving/saved/error states. Support username validation errors.
- `/find-friends` FindFriends: search riders (`GET /riders?query=`), follow/unfollow; empty state for no matches.
- `/achievements` Achievements: list from `/achievements` (if exposed). States: earned vs locked (gated by card level), progress bars, revoked/broken states, loading/empty.
- `/store` BeetleStore: hinges on marketplace; if API not ready, keep placeholder card grid with “connect to marketplace” note. Future: `GET /store/items`, `POST /store/purchase`.
- `/portfolio` + `/store` should show CAL/DUNG tokens as read-only; DUNG has 9 decimals (display whole).
- `/settings` Settings: theme toggle, data export/delete placeholders. When APIs exist: export/delete endpoints; session list.
- `/docs` Docs: static; keep links to whitepaper/specs.
- 404 NotFound: already present; include “Back to feed” CTA.

## Global Components and States
- TopNav: show wallet address, energy chip (from `GET /cal/balance`), notifications (placeholder), profile dropdown. Include loading shimmer until auth loads.
- Modals (ActivityDetail, UploadActivity, Search, Settings, Share, AchievementUnlock, DeleteConfirm, EditActivity, InviteFriend, StoreConfirm, SegmentDetail): all need focus trap, ESC, scroll lock, loading/error states. Show success toasts via Sonner.
- Toasts: success/error for upload, stake/unstake, claim, save profile, invite, wallet connect, CAL mint.
- Skeletons: ActivityFeedSkeleton used as Suspense fallback; ensure matching heights with real items.

## Data Shapes (high-level, attestation-aligned)
- Ride: `id`, `title`, `started_at`, `distance_m`, `elevation_m`, `tss`, `calories`, `dung_earned`, `patterns[]`, `map_polyline?`, `duration_sec`.
- Pattern (attestation summary): `type` (`climb|steady|exploration`), `duration_s`, `elevation_m` (climb), `power_w?`, `intensity`, `new_tiles_wallet`, `new_tiles_global`, `region_name?` (arena label), `cal_awarded`, `dung_awarded`, `status` (`pending|verified|failed`), `region_hash?` (not user-facing).
- Arena (if exposed): `id`, `name`, `summary` (effort density), `pattern_counts`, `leaderboard[]`.
- Staking claim: `segment_id` (or future arena id), `amount`, `lp_tokens`, `status`, `tx_sig?`.
- CAL balance: `cal_balance`, `can_mint_today`, `last_mint`.
- User: `id`, `wallet_address`, `beetle_id`, `userName`, `rank`, `ftp`, `weight`, `theme`, `rider_type`, `units`, `notifications`.

## States to Design For
- Auth: unauthenticated (show gate), auth-loading (skeleton), authenticated, token-expired (retry/refresh).
- Network: loading, empty, error (calm UI), partial (some panels fail).
- Solana ops: pending (spinner + “settling on-chain”), success, failure with retry.
- Upload: in-progress, success, duplicate, invalid file, exceeded size, tile/pattern processing pending/failed.
- Leaderboard: timeframe/arena/pattern loading, no data, stale data warning.
- Achievements: locked, earned, revoked, progress toward next.
- Map/patterns: geolocation denied, throttled, low-data fallback (list view). Exploration patterns should show “new areas” counts even if map tiles are obfuscated.

## Copy & UX Notes
- Keep invite/auth “trust moments” calmer (per Ive critique); reduce heavy borders in error states.
- Rename “Segments” to “Patterns”/“Efforts”; avoid surfacing “tiles/H3” in UI. User-facing terms: “Climb”, “Steady”, “Exploration”, “Arena” (optional label), “New areas”.
- Buttons: uppercase, 3px border, hover lift; disabled styles.
- Empty states should propose the next action (upload, connect wallet, enter invite, search again).
- Accessibility: focus outlines on all controls, skip-to-content link in App shell, aria-live for feed counts, ESC closes modals.

## Deliverables to Request from Figma Agent
- Annotated frames for each route with: loading, empty, error, and success states; auth gate flow; Solana pending overlays; pattern detection pending state post-upload.
- Component variants: buttons (default/hover/pressed/disabled/loading), inputs (success/error), toasts, progress bars, cards (stat/content/CTA), tables/lists, badges/pills, tabs/filters, modals with focus order.
- Pattern cards: Climb/Steady/Exploration variants with stats (vert/time/new areas), status chips (pending/verified/failed), optional arena label; leaderboards by pattern type.
- Token sheet: colors (light/dark + art palettes), borders (2px inputs, 3px cards/buttons), radius (8/12/16), shadows (offset), spacing and typography scale, monospace usage.
- Interaction notes: infinite scroll thresholds for feed, map hover/click behaviors, leaderboard filters (timeframe/arena/pattern), staking/claim flow steps, upload → processing → attested success.

## Code/Figma Sync Checklist (rename/redirect map)
- Rename UI strings/labels from “Segments” → “Patterns” (Climb/Steady/Exploration); “Segment Detail” → “Effort Detail” or “Arena”.
- Routes/components:
  - `/my-segments` → `/patterns`; `MySegments.tsx` → `Patterns.tsx`.
  - `/segments/:segmentId` → `/arenas/:arenaId` (or `/patterns/:id` if arena not exposed); `SegmentView.tsx` → `ArenaView.tsx` or `PatternView.tsx`.
  - Any “segment leaderboard” components → “pattern leaderboard” with filters for pattern type/timeframe/arena.
  - Map overlays: remove “segments nearby” copy; use “recent climbs/steady efforts” and “new areas explored”.
- Data bindings: swap `segments[]` props to `patterns[]` in RideView/MyActivities; hide tile IDs/region hashes, show friendly arena name if present.
- Empty/placeholder copy: “No patterns yet — upload a ride to detect climbs/steady efforts/new areas” instead of “No segments”.
- Icons: replace map-pin/flag icons used for segments with effort badges (mountain for climb, wave for steady, compass for exploration).
