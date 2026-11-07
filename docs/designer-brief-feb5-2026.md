# Boulder Roller — Designer Sync
**Feb 5, 2026 | Meeting #4**

---

## Executive Summary

Since our last meeting, we've shipped 100+ improvements across auth, uploads, vault systems, and leaderboards. The biggest theme: **removing crypto friction** and making the app feel like a fitness tool, not a DeFi dashboard.

---

## Major Work Streams

### 1. Language & Jargon Overhaul (Jan 20-26)

**The Problem:** App was littered with crypto terms that alienated fitness users. "Harvest your DUNG," "stake CAL," "epoch distributions" — none of this means anything to a cyclist.

**What We Did:** Systematic pass through every user-facing component:

| Before | After |
|--------|-------|
| DUNG / CAL | Points / Rewards |
| Epoch | Week |
| Harvest | Claim |
| Stake | Back (a climb) |
| Mint | Create |
| POL / PROTOCOL | Platform fees |
| TOKEN badge | LIVE badge |
| TGE | Launch |

**Files touched:** 20+ components across VaultView, Settings, Profile, Leaderboard, RideView, ClimbsTable, VaultPanel, PatternInspector

**Commits:**
- `c2eb8f3` Replace CAL/DUNG labels with pts/rewards
- `a37bde9` Replace epoch terminology with week
- `9844eb5` Polish vault creation and staking components
- `969174d` Polish Settings: remove crypto jargon
- `fcd27ad` Polish ClimbsTable: remove crypto jargon

**Design impact:** All mockups should use fitness-friendly language. No "staking," "minting," "epochs."

---

### 2. Login Flow Polish (Jan 27)

**The Problem:** Auth was confusing. Invite code entry was a hidden 3-click easter egg. Modals weren't responsive. Session expiry was jarring.

**What We Did (12 fixes in one pass):**

**Critical:**
- Added visible "Enter with Invite Code" button to InviteGate (was buried)
- Made all auth modals responsive with max-width constraints
- Surface wallet creation loading state in InviteModal

**High Priority:**
- Created `auth-errors.ts` with user-friendly error messages
- Deep-links now preserved through auth flow (sessionStorage)
- Added SessionExpiredModal for graceful expiry
- SetupModal fields now truly optional (skip actually works)

**Medium Priority:**
- App loading now shows "Checking your session..." text
- Case-insensitive hint for invite codes
- "Request an invite" mailto link in footer
- Abandoned invite codes cleared from localStorage

**Second pass (82b8b29):**
- Multi-tab auth sync (login in one tab, others update)
- Accessibility improvements
- Better timeout handling

**Commits:** `694731c`, `82b8b29`

**Design impact:** Auth flow should feel seamless. No dead ends.

---

### 3. UX Gap Plan — 85+ Improvements (Jan 27)

**The Problem:** We had a comprehensive UX audit that identified gaps across 12 work packages. Needed to ship fast.

**What We Shipped:**

#### Session & Auth (WP2-4)
- Token refresh with retry on network failure
- Offline detection vs auth failure differentiation
- Session expired modal with retry option
- Remember me preference (localStorage)
- Session expiration warning toasts
- Multi-tab auth sync
- Logout confirmation dialog

#### Upload Flow (WP5-6)
- Upload cancellation support
- Frontend file validation (type, size limits)
- Retry button for failed uploads
- Parser error messages surfaced to user
- Pending match explanation with spinner
- Duplicate detection → "View existing ride" link
- Improved timeout messaging

#### Strava Integration (WP7)
- Activity pagination with "Load More"
- Batch size limits (max 10 at once)
- Per-activity error details
- Disconnect confirmation modal
- Scope validation feedback
- Better auth failure messaging

#### Vault Creation (WP8)
- Link to existing vault on duplicate attempt
- Retry button after on-chain failure
- Human-readable error messages
- Loading skeleton during creation
- Success modal with vault ID
- "Share this climb" CTA
- Minter rights explanation tooltip

#### Leaderboard (WP9-10)
- Rank trend indicators (↑↓ arrows)
- Personal effort history on segments
- Friends filter UI (placeholder, coming soon)
- Attempt count visible
- PR progression chart
- Celebration banners for Top 10 / KOM
- Total vault earnings summary
- Comparison to previous best time

**Commit:** `482c49f`

**Design impact:** Most empty states and error states now have content. Review for visual consistency.

---

### 4. Comprehensive Vault Leaderboard System (Jan 21-27)

**The Problem:** Leaderboards were basic. No history, no validation, no notifications when you get bumped.

**What We Built:**

| Feature | Description |
|---------|-------------|
| Full leaderboard view | Pagination for all positions (not just top 10) |
| History tracking | Entry, exit, bump, earnings events logged |
| Time validation | Distance and VAM-based bounds check |
| Tiebreaker logic | Earlier submission wins on equal times |
| User summary | Your leaderboard positions across all vaults |
| Epoch snapshots | Freeze leaderboard state for distribution integrity |
| On-chain sync | Keep Anchor program consistent with DB |
| Flagging system | Mark suspicious times for review |
| Notifications | Alerts for rank changes and bumps |
| Global aggregates | Site-wide KOM counts, total earnings |
| Nearby riders | "3 riders within 10 seconds of your time" |
| Vault backfill | Retroactively match old rides to new vaults |

**Critical bug fixes included:**
- VAM validation was returning minutes as seconds (times were being rejected incorrectly)
- LP staking had race condition (atomic DB function now)
- Empty leaderboard edge case (redirect rewards to stakers/treasury)

**Commits:** `198643b`, `b5f0572`, `35998b3`

**Design impact:** Leaderboard is now a rich, animated component. Needs visual design review.

---

### 5. Ride Processing Feedback & Caching (Feb 2)

**The Problem:** Upload felt like a black box. User clicks upload, waits, gets result. No sense of progress.

**What We Did:**
- Added processing stage indicators
- Caching layer for repeated queries
- Better error surfacing in UploadActivityModal
- Rate limiting infrastructure
- Metrics collection for processing times

**Files touched:** 18 files across backend services, routes, and frontend modal

**Commit:** `61774fa`

**Design impact:** Upload modal needs progress stages visualized. Currently functional but not delightful.

---

### 6. Settings Page Stabilization (Jan 28 - Feb 2)

**The Problem:** Settings page was crashing, had infinite loops, API errors.

**Timeline:**
1. `f8c84a3` — Remove useBlocker (required data router we don't have)
2. `20d001a` — Fix infinite loop in tab deep linking
3. `e980446` — Fix API errors (schema mismatch)
4. `59d737e` — Add camelCase aliases to UserProfileUpdate schema

**Also added:**
- Privacy Zones component wired in (`a2120be`)
- FTP input validation, NaN handling (`480979f`)

**Design impact:** Settings is stable but visually basic. Good candidate for polish pass.

---

### 7. VaultView — User Effort History (Feb 2)

**The Problem:** VaultView showed vault stats but not YOUR history on that climb.

**What We Did:** Wired effort history to real API. Now shows:
- Your attempts on this climb
- Your best time
- Your rank (if on leaderboard)
- Points earned from this vault

**Commit:** `3c6fe8c`

**Design impact:** This is a key "ownership moment." User sees their relationship to a specific climb.

---

### 8. Mobile Navigation Fix (Jan 15)

**The Problem:** Mobile nav had scroll issues. Content was clipped, overflow wasn't working.

**What We Did:**
- Reset inset styles
- Enable proper overflow
- Fix scroll behavior

**Commits:** `10309da`, `22da821`

**Design impact:** Mobile should be tested again end-to-end.

---

## Direction Changes / Decisions Made

| Decision | Date | Context |
|----------|------|---------|
| **Points period = indefinite** | Jan 20 | No public countdown. Hyperliquid-style stealth launch. |
| **Strava = manual import only** | Jan 15 | No auto-sync. User pulls activities on demand. Avoids rate limits. |
| **Local Legend replaces Swanny** | Jan 18 | 1 seat per vault (not 3), elected by completions, no lock required. |
| **Fitness-first language** | Jan 20 | Systematic removal of crypto jargon across all UI. |
| **Creator becomes first Soigneur** | Jan 22 | Vault creator automatically gets Local Legend seat for first 8 weeks. |
| **Staker unlock curve** | Jan 22 | First staker only gets 1% of pool. Prevents gaming, rewards network growth. |
| **Privacy zones** | Jan 25 | Users can define areas where GPS is fuzzy (home, work). |
| **Anonymous display names** | Jan 25 | Default to generated names, not wallet addresses. |

---

## Current State

| Area | Status |
|------|--------|
| **Staging API** | ✅ `[STAGING_IP]:8080` healthy |
| **Auth** | ✅ Privy (social + wallet) working |
| **Invite codes** | ✅ `alpha-code-1`, `alpha-code-2`, `alpha-code-3`, `alpha-code-4` |
| **Ride upload** | ✅ FIT/GPX/TCX parsing, vault matching |
| **Vault creation** | ✅ Gated by lifetime points |
| **Leaderboards** | ✅ Full system with history, notifications |
| **Points** | ✅ Earning, displaying, but not prominent in UI |
| **Mobile** | ⚠️ Functional but needs testing |
| **Settings** | ⚠️ Stable but visually plain |

---

## Designer Discussion Points

### 1. Upload Progress Visualization
User uploads a file. Backend does: parse → validate → project to tiles → detect climbs → match vaults → award points.

**Current:** Single spinner, then result.
**Desired:** Staged progress indicator. Each step visualized.

**Question:** Horizontal stepper? Vertical list? Animation style?

---

### 2. Vault Match Moment
User uploads ride. We detect they crossed 3 known climbs. This is THE key moment.

**Current:** Text list of matched vaults.
**Desired:** Celebratory but not cheesy. "You completed Box Hill. Earned 47 points."

**Question:** Modal? Inline expansion? Card stack?

---

### 3. Points Balance Placement
Users earn points. Where do they see this?

**Options:**
- Header (always visible, subtle)
- Dashboard hero stat
- Profile page only
- Dedicated "Earnings" tab

**Context:** Pre-token, so we don't want to overhype. But users need feedback loop.

---

### 4. Leaderboard Visual Design
Now a rich component with: rank, trend arrows, time, gap to next, attempt count, earnings.

**Current:** Functional table.
**Desired:** Feels competitive. Rank 1 should feel special.

**Reference:** Strava segment leaderboards, but with earnings column.

---

### 5. Settings Polish Pass
Stable but boring. Tabs: Profile, Privacy, Connections, Sessions.

**Quick wins:**
- Better section headers
- Input field consistency
- Privacy zones map preview
- Connected accounts visual state

---

### 6. Empty States Audit
We added empty state copy in UX gap work. Need visual pass.

**Key empty states:**
- No rides yet
- No vaults staked
- No leaderboard positions
- Strava not connected

---

## Appendix: Full Commit Log (Jan 15 - Feb 5)

```
61774fa Improve ride processing feedback and caching
3c6fe8c Wire VaultView user effort history to real API
59d737e Add camelCase aliases to UserProfileUpdate schema
e980446 Fix Settings page API errors
20d001a Fix Settings infinite loop in tab deep linking
f8c84a3 Fix Settings page crash
bb047f3 Implement backend items for UX gap plan
482c49f Implement UX gap plan: 85+ improvements
82b8b29 Polish login flow UX round 2
694731c Polish login flow UX with 12 fixes
198643b Implement comprehensive vault leaderboard system
c5f63bd Implement protocol-level climb detection tuning
64cbeb4 Implement dual-path vault matching
82b20e1 Add unified protocol mode switch
b5d8318 Fix Privy auth integration
c2eb8f3 Replace CAL/DUNG labels with pts/rewards
a37bde9 Replace epoch terminology with week
9844eb5 Polish vault creation and staking components
969174d Polish Settings: remove crypto jargon
9252f66 Polish VaultView: simplify crypto/DeFi language
a2120be Wire PrivacyZones component into Settings
4f2b900 Conceptual refinement: anonymous names, privacy zones
10309da Fix mobile navigation scroll behavior
22da821 Fix mobile scrolling
```

---

**What's feeling most urgent on your end?**
