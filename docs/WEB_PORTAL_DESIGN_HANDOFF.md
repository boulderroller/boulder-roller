# Boulder Roller Web Portal — Design Handoff (Dec 2025)

This is the distilled brief for the Figma design agent (Gemini 3 Pro) to deliver the full portal UI. Source docs: `docs/SESSION_2025-12-06_PORTAL_V2_REDESIGN.md` (latest UX decisions), `docs/PLATFORM_FEATURE_MATRIX.md` (surface-area scope), `docs/INTEGRATION_REGISTRY.md` (API/base URLs), `docs/PLATFORM_DELIVERY_CHECKLIST.md` (MVP guardrails), and the live Next.js code in `web/portal`.

## Brand and Visual Language
- Core vibe: neo-brutalism with 3px borders, hard shadows (`--shadow-sm/md/lg/xl`), chunky cards, tabular monospace numbers. Landing uses stealth noir variant (grid/noise, offset shadows), app keeps lively neo-brutalism.
- Typography: heavy sans for headings (weight 800); monospace for all numbers (`font-mono`, JetBrains/SF Mono). Landing imports JetBrains Mono for everything critical.
- Color tokens (set as CSS variables in ThemeProvider): primaries `--purple`, `--pink`, `--blue`, `--cyan`, `--green`, `--orange`, `--yellow`, `--red`, neutrals `--grey-50/100/200/700/900`, backgrounds `--background`, shadows `--shadow-*`. Six art-inspired palettes plus dark variants: `default` (neo-brutalism), Monet, Degas, Renoir, Cezanne, Seurat. Preserve emoji labels in theme switcher.
- Logo lockup: “BOULDER ROLLER” (no S), beetle icon can appear; brand treatments in header (stacked BOULDER / ROLLER).
- Motion: subtle lift/translate on hover; staggered reveals; landing beetle uses pulse + float; mobile drawer slides from left.

## Entry Flow and Access
- Stealth landing (`/`): dark palette with grid/noise overlay, 3px borders, offset shadows. Hero copy introduces “exclusive club entrance.” Waitlist form posts to `POST /waitlist` (Supabase upsert, always shows success). Success state is bordered box with check. Contact link `mailto:info@boulderroller.com`.
- Hidden invite gate: beetle easter egg opens invite modal after 3 clicks. Valid codes array in code: `alpha-code-1`, `alpha-code-2`, `alpha-code-3`, `dung`, `alpha-code-4`. On success set `localStorage.br_access = 'granted'` then route to `/app`. Error shakes the field.
- /app access gate: allow if authenticated or `br_access === 'granted'`; otherwise redirect to `/`. The current portal uses HttpOnly auth cookies; only lightweight UI flags such as `br_authenticated` and invite gating remain in localStorage.
- QuickSetup modal: for authenticated users with no `userName`, unless skipped (`localStorage.quickSetupSkipped`). Collects beetle ID, username, basics; needs calm, low-ink treatment per “trust moments deserve calm.”

## Global Layout
- Header (horizontal, Strava-style): brand left, color-coded nav in center, energy chip + progress bar, notifications bell, wallet/profile on right. Mobile uses hamburger drawer. Nav IDs: home, rides, piles, portfolio, challenges, feed, discover (profile reachable via avatar).
- Grid philosophy: desktop 12-col; target 3-column frame (stats | content | feed) with sticky side panels where possible. Mobile collapses to single column with stacked key cards.
- Cards: `neo-card` with 3px borders, rounded 12px, `var(--shadow-md)` → lift on hover; gradients for action cards; white or theme background for content cards.
- Breakpoints: Desktop ≥1024 shows full grid; tablet tightens typography; mobile hides side panels (`hide-mobile` utility).

## Pages / Tabs (authenticated)
- Home: Hero with weekly DUNG earned, daily CAL energy bar, Upload Ride CTA (opens RideUploadModal), weekly stat trio (rides/TSS/rank), AI Coach panel, FitnessDashboard, Recent Activity card. Design for loading skeleton and empty recent ride state.
- Rides: Monthly stat cards (rides, distance, elevation, TSS, DUNG), rides list with segment count pill, calories, TSS badge; click opens RideDetailModal. “Plan Route” CTA opens RidePlanner. Empty state CTA should point to upload ride.
- Piles (staking map objects): Toggle All vs Your Piles; cards show name, category pill, distance/elevation, weekly pot, crossings. “View” opens PileDetailModal with stake/unstake, pot, APY. Loading and empty states needed.
- Portfolio: Staking positions summary, claims/harvest CTA, charts for staking composition and performance (placeholder OK). Include pending state for Solana ops.
- Challenges: Achievement browser (earned vs available), badges by category (distance/segments/streak/leaderboard/TSS/wkg). Support locking by card level gates.
- Feed: Activity feed with kudos/comments, leaderboard preview, upcoming events card. Provide “View all” affordance to full feed/leaderboard pages.
- Discover: Segment explorer/map search, nearby/ bbox filters, leaderboard per segment (epoch input). Room for referral surfacing.
- Profile: ProfilePanel with explicit Save button (handleSaveAll) instead of auto-save; editable username, bio, FTP, weight, theme selector, light/dark toggle, wallet binding, notifications prefs. Needs save/saving states and validation hints.

## Guest Experience
- If not authenticated on /app: 3-column guest view with blurred stats (left), live global feed (center), discovery teaser (right). Mobile stacks panels under feed.
- Landing waitlist is the main public funnel; ensure form success feels premium even on failure (silent success).

## Data Contracts / States to Respect
- Base API URL (browser): same-origin `/api` facade (rewritten upstream to `https://api.boulderroller.xyz`; local dev proxy target `http://localhost:8080`). Wallet auth uses nonce/verify plus HttpOnly cookies; bearer tokens should not be documented as persistent localStorage state for the main portal.
- Backend endpoints (see `docs/INTEGRATION_REGISTRY.md`): auth (`/auth/nonce|verify|refresh|me`), rides (`/rides`, `/rides/upload`, `/rides/{id}`, `/rides/{id}/segments`), CAL (`/cal/balance`, `/cal/mint`), staking (`/staking/stake|unstake|claims`), segments (`/segments/list`, `/segments/nearby`, `/leaderboard/{segment_id}?epoch_number=`), waitlist (`/waitlist`), optional achievements/referrals if exposed.
- Units: DUNG 9 decimals (but display whole tokens), CAL integer, TSS integer, distance km (portal currently shows km, some cards show miles—align to one system), elevation meters, energy percent derived from calBalance/calMax.
- State handling: show pending, success (toasts), error (calm treatment) for Solana ops (stake/unstake, mint). Include empty and loading skeletons across tabs.

## Interaction Patterns
- Buttons: large, high-contrast, uppercase labels; 3px borders; hover lift; disabled/loading states with spinners where async.
- Modals: WalletModal, RideUploadModal, RideDetailModal, PileDetailModal, QuickSetup, RidePlanner; clicking outside closes. Provide consistent header/footer spacing and focus order.
- Toasters: success/error variants stack; auto-dismiss ~3s.
- Animations: fade/slide-in for list rows; progress bars animated width; beetle easter egg pulse.
- Error copy tone: “Resume” / “Try again” vs harsh alerts; trust moments (auth/payment) should be calmer per Ive critique.

## Accessibility and Responsiveness
- Keyboard focus outlines on all controls (including modal buttons and close icons). Ensure invite modal and upload modal trap focus.
- Color contrast: maintain readability on gradients; provide solid-light/dark variants for critical text.
- Reduced motion: allow turning off heavy transitions; avoid flashing effects.
- Mobile: header condenses, nav goes to drawer, side columns hidden; key CTAs stay above the fold (Upload Ride, Stake, Save).

## Deliverables for Figma
- Updated components for: Header (desktop + mobile), Cards (content/stat/CTA), Buttons (primary/secondary/ghost), Form fields (stealth + standard), Modals, Toasters, Progress bars, Tabs/nav pills, Tables/lists, Empty/skeleton states.
- Page frames: Landing (stealth hero + waitlist + beetle invite modal), Authenticated app shell with 3-col option, each tab layout, guest 3-col view.
- Token sheet: palettes for all themes, spacing scale, radii (12px cards), border weights (3px core, 1px internals), shadows, typography scale, icon set (Lucide) mapping.
- Annotations: note API-driven data, loading/empty/error states, hover/pressed behaviors, and responsive breakpoints.

## Known Open Items / Caveats
- Some feed/leaderboard data still mocked; design should accommodate placeholders and “connect to device/API” prompts.
- Mobile optimization for 3-col layout is partial; propose better stacking for stats/feed sidebars.
- Wallet modal and error states need calmer “trust” treatment; design recommendations welcome.

Hand this to the design agent as the source of truth; align visuals to the existing ThemeProvider tokens so the build stays close to code.
