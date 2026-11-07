# Known Stubs & TODOs

This document tracks features that are intentionally incomplete or stubbed out for future implementation.

**Last Updated:** 2025-12-06 (Full Sweep Complete + Audit)

---

## Guest View (Intentional - Preview Mode)

- [ ] **GuestRightPanel** - "Follow" buttons are decorative (blurred fake discovery content)
- [ ] **GuestLeftPanel** - Stats shown are placeholder values (blurred fake stats)
- [ ] **GlobalActivityFeed** - Generates fake stats based on activity ID for guests

---

## Hidden Tabs (Removed from Nav)

- [x] **ChallengesTab** - Hidden from nav *(2025-12-06)* - File still has "Coming Soon" banner
- [x] **DiscoverTab** - Hidden from nav *(2025-12-06)* - File still has "Coming Soon" banner
- [ ] **useChallenges.ts** - Uses MOCK_CHALLENGES array (lines 7-77)
- [ ] **useDiscover.ts** - Uses MOCK_RIDERS array (lines 7-99)

---

## Tabs - Active

- [x] **MapTab** - Filter button fully implemented *(2025-12-06)*
- [ ] **SwannyTab** - Lock modal mentioned but not rendered
- [ ] **ProfileTab** - Settings gear button has no click handler
- [ ] **ProfileTab:92** - Mock activity days for streak (last 90 days)
- [ ] **ChallengesTab:227** - `alert('View details')` placeholder for challenge details

---

## Feed & Social

- [x] **FeedTab** - Kudos wired to backend API *(2025-12-06)*
- [x] **FeedTab** - Comments integrated with CommentThread *(2025-12-06)*
- [x] **FeedTab:81** - Removed alert from EmptyFeed *(2025-12-06)*
- [x] **FeedTab:297** - Share now copies link to clipboard *(2025-12-06)*
- [x] **Leaderboard** - Now API-driven *(2025-12-06)*
- [x] **Follow** - FollowingModal button now functional *(2025-12-06)*

---

## Profile

- [x] **ProfilePopover:222** - Removed hardcoded "1" sessions count *(2025-12-06)*
- [x] **ProfilePanel** - Save button added *(2025-12-06)*

---

## Charts & Visualizations

- [ ] **PowerCurve.tsx:16** - Uses mockPowerData array
- [ ] **RideSummaryModal.tsx:471** - Uses mockElevation array

---

## Modals & Features

- [ ] **RidePlanner.tsx:100** - "Map view placeholder" text
- [ ] **RidePlanner.tsx:39** - Creates mock polyline
- [ ] **DataExport.tsx** - All export buttons use `alert()` instead of real export
- [ ] **CALBoostModal.tsx:214** - Uses `alert()` for boost confirmation

---

## Landing Page

- [x] **page.tsx** - Waitlist POSTs to /waitlist *(2025-12-06)*
- [ ] **page.tsx** - Invite codes hardcoded (move to env/database)

---

## Backend

- [x] `POST /waitlist` - Implemented *(2025-12-06)*
- [x] `GET /leaderboard/{segment_id}` - Implemented *(2025-12-06)*
- [ ] `POST /auth/verify-invite` - Not implemented (client-side only)
- [ ] Strava OAuth - Not implemented (manual upload only)
- [x] CAL airdrop - Real (Celery task every 5 min)

---

## Design System

- [x] Dark theme variants (6 themes) *(2025-12-06)*
- [x] Dark mode toggle *(2025-12-06)*
- [x] ErrorState component *(2025-12-06)*
- [x] Tablet breakpoints *(2025-12-06)*
- [ ] Some inline styles instead of CSS variables

---

## Priority Matrix

| Priority | Category | Count |
|----------|----------|-------|
| ~~P0~~ | ~~User-facing alerts~~ | ~~3~~ ✅ Done |
| P1 | Mock data in hooks | 2 |
| P1 | Mock data in charts | 2 |
| P2 | Guest view placeholders | 3 |
| P2 | Modal placeholders | 3 |
| P3 | Hardcoded values | 2 |

---

## Notes

- Items marked with `[x]` have been completed
- Guest view stubs are intentional (preview/teaser for unauthenticated users)
- ChallengesTab/DiscoverTab hidden from nav but files remain for future
- **2025-12-06 Full Sweep:** P0 API wiring, P1 hide stubbed tabs, P2 polish
