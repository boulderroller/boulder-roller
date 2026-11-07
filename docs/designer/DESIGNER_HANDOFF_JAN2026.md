# Boulder Rollers Portal — Designer Handoff (January 2026)

**Status:** Active
**Replaces:** `DESIGNER_TOPOLOGY.md` (deprecated)
**Last Updated:** January 2, 2026

---

## Quick Reference

| Item | Value |
|------|-------|
| **Brand** | Boulder Rollers |
| **Value Token** | DUNG |
| **Energy Token** | CAL |
| **Live Portal** | `web/portal/` |
| **API** | `https://api.boulderroller.xyz` |
| **Source of Truth** | `docs/TOKENOMICS_V2.md`, `docs/spec2025.md` |

---

## 1. Brand & Visual Philosophy

### Current Branding

Boulder Rollers is a decentralized cycling economy. The beetle (dung beetle) is a **meaningful cultural touchpoint** - not easter-egg-hidden, not overwhelming. Think: elegant presence that rewards those who notice.

**Core Value Proposition:** "That hill you climbed 100 times? Stake in it and earn from everyone else who climbs it."

### Beetle Treatment (Balanced Approach)

| Context | Beetle Usage |
|---------|--------------|
| Logo/Header | Beetle icon alongside "BOULDER ROLLER" wordmark |
| Loading states | Beetle emoji pulse animation |
| Vault markers on map | Beetle emoji or icon |
| Empty states | Tasteful beetle illustration with context |
| Achievement badges | Beetle-themed iconography |
| BeetleCard NFT | Full beetle avatar with accessories |
| Error states | Minimal - beetle not dominant |

**Philosophy:** The beetle is memorable without being cartoonish. MF DOOM reference for those who get it. Serious athletes first, crypto/meme culture second.

### Future Brand Considerations

There's internal discussion about evolving to "Motion" (app) / "MOMO" (token) for a cleaner first impression. **Current implementation stays Boulder Rollers/DUNG.** Designer should create assets that work for both futures:
- Wordmark that doesn't require beetle
- Icon system that can standalone
- Color palette not beetle-dependent

---

## 2. Design System

### Visual Language

**Neo-brutalism with cycling sophistication:**
- 3px solid borders
- Hard offset shadows (`4px 4px 0 0`, `6px 6px 0 0`)
- Bold typography (weight 700-800)
- High contrast, generous whitespace
- Rounded corners on cards (12px)

### 6 Theme Palettes

Each theme has **light** and **dark** variants (12 total).

| Theme ID | Name | Emoji | Vibe |
|----------|------|-------|------|
| `hoo-breddin` | Hoo-Breddin | 🍂 | Earthy olive/cream (default) |
| `water` | Water | 🌊 | Deep blue aquatic |
| `sunny` | Sunny | ☀️ | Warm golden |
| `safari` | Safari | 🦒 | Tan/brown expedition |
| `moss` | Moss | 🌲 | Forest green |
| `foundries` | Foundries | 🏭 | Industrial gray |

### Color Token Structure

```css
/* Applied dynamically by ThemeContext */
--color-bg           /* Primary background */
--color-bg-secondary /* Cards, panels */
--color-accent       /* Interactive elements, highlights */
--color-text         /* Primary text */
--color-text-muted   /* Secondary text */
--color-border       /* Borders, shadows */

/* Shadows */
--shadow-sm: 4px 4px 0 0 var(--color-border);
--shadow-md: 6px 6px 0 0 var(--color-border);
--shadow-lg: 8px 8px 0 0 var(--color-border);
```

### Typography

| Element | Font | Weight | Notes |
|---------|------|--------|-------|
| Headings | System sans | 700-800 | Letter-spacing: -0.025em |
| Body | System sans | 400-500 | |
| Numbers | JetBrains Mono / SF Mono | 400 | `font-variant-numeric: tabular-nums` |
| Labels | System sans | 600 | Uppercase for categories |

### Responsive Breakpoints

| Size | Width | Layout |
|------|-------|--------|
| Mobile | < 768px | Single column, drawer nav |
| Tablet | 768-1024px | Condensed two-column |
| Desktop | > 1024px | Full dashboard layout |

---

## 3. Portal Architecture

### Route Structure (21 Pages)

```
/                           → Activity Feed (home)
├── /profile                → User profile (own)
├── /athletes/:beetleNumber → User profile (public)
├── /my-activities          → Ride list with upload
├── /my-segments            → User's segments
├── /data                   → Training data & analytics
├── /portfolio              → DUNG/CAL holdings, stakes, claims
├── /map                    → Global map exploration
├── /leaderboard            → Global leaderboards (climb/steady/explorer)
├── /vaults                 → Vault browser
├── /vaults/:vaultId        → Vault detail + leaderboard
├── /vault-demo             → Vault creation flow demo
├── /find-friends           → Rider discovery
├── /achievements           → Badge collection
├── /store                  → BeetleCard accessories
├── /activities/:activityId → Ride detail view
├── /activities/:activityId/analyze → Ride analysis
├── /segments/:segmentId    → Segment detail
├── /rider/:riderId         → Rider public profile
├── /settings               → User preferences
└── /docs                   → Documentation
```

### Component Inventory (~100+ components)

**Layout (5):**
- `DashboardLayout` - Main app shell
- `DashboardHeader` - Top nav bar
- `AppSidebar` - Left navigation
- `ProfileDropdown` - User menu
- `ScrollProgress` / `ScrollToTop`

**Ride Components (15+):**
- `RideView` - Main ride page (44KB, complex)
- `AnalyzeView` - Deep analytics
- `RouteMap` - Mapbox integration
- `ElevationChart` - Recharts profile
- `StatsPanel` - Metrics display
- `PatternInspector` - Climb/steady/explore patterns
- `VaultPanel` - Vault matching on rides
- `DungBreakdown` - Earnings display
- `LapsTable` - Interval data
- `SegmentRow` - Segment list item
- `KudosCard` - Social kudos
- `WeatherCard` - Conditions

**Vault Components (5):**
- `Vaults` - Browser page
- `VaultView` - Detail page
- `VaultFlowDemo` - Creation flow
- `ClimbToVaultFlow` - Ride→Vault wizard

**Feed/Social (5):**
- `ActivityFeed` - Main feed
- `ActivityFilter` - Feed filtering
- `MiniMap` - Activity preview map
- `LeaderboardRow` - Leaderboard entry
- `LeaderboardTable` - Full leaderboard

**Auth (3):**
- `InviteGate` - Stealth landing with beetle easter egg
- `InviteModal` - Code entry + social login
- `WalletContext` - Solana wallet adapter

**UI Primitives (40+ from shadcn/Radix):**
- Layout: Card, Dialog, Drawer, Sheet, Tabs, Accordion
- Forms: Input, Textarea, Select, Checkbox, Switch, Slider
- Display: Avatar, Badge, Button, Progress, Skeleton
- Overlay: Popover, HoverCard, Tooltip, DropdownMenu
- Data: Table, Chart

**Custom UI (15+):**
- `beetle-button` - Branded button
- `beetle-card` - Branded card
- `beetle-input` - Branded input
- `StatPill` - Stat chip
- `PointsCounter` - Animated counter
- `AchievementBadge` - Badge display
- `empty-state` - Empty state component
- `loading-skeleton` - Loading skeletons

---

## 4. Authentication Flow

### Dual Auth System

Users can authenticate via:

1. **Social Login (Privy)** - Primary for new users
   - Google, Apple, Email
   - Creates embedded Solana wallet automatically
   - No crypto knowledge required

2. **Wallet Login (SIWS)** - For crypto natives
   - Phantom, Solflare, Backpack
   - Sign message to prove ownership
   - Full wallet control

### Login Modal Design

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│              🪲 BOULDER ROLLER                              │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  G  Continue with Google               (primary) │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  🍎  Continue with Apple                        │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  ✉️  Continue with Email                        │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     ───────────────── or ─────────────────────────────     │
│                                                             │
│     ┌─────────────────────────────────────────────────┐    │
│     │  🦊  Connect Solana Wallet              (crypto) │    │
│     └─────────────────────────────────────────────────┘    │
│                                                             │
│     Have a wallet? Phantom, Solflare, Backpack...          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key:** Social options first, wallet option secondary.

### Entry Gate (Invite-Only Alpha)

Current landing is a stealth page:
- Minimal: just beetle emoji centered
- Click beetle 3x → reveals invite modal
- Valid codes stored in code (will be API-gated)

---

## 5. Token Economy Display

### Points Period (Current State)

Pre-TGE, users earn **Points** which convert to DUNG at Token Generation Event.

| Metric | Display Location |
|--------|------------------|
| Total Points | Header chip, Profile, Portfolio |
| Points from ride | RideView summary |
| Points leaderboard | Leaderboard page |
| Entitlement tier | Portfolio (vaults unlocked, stake cap) |

### CAL (Energy Token)

- Daily allocation: 2,500 CAL
- Regenerates midnight UTC
- Distributed to segments crossed on rides
- Not user-visible as separate balance currently

### DUNG (Value Token)

Post-TGE:
- Total supply: 1B
- Earned from riding, staking, leaderboards
- Used for vault creation, staking, upgrades

### Vault Economics Display

Each vault shows:
- Total completions
- Total staked (points/DUNG)
- KOM holder + time
- Leaderboard (top 10)
- Local Legend (current curator)
- Weekly pot distribution preview

---

## 6. Key User Flows

### 1. Ride Upload → Earn Points

```
User uploads FIT/GPX/TCX
        ↓
Rust parser → TSS, NP, patterns detected
        ↓
RideView displays: stats, map, elevation, patterns
        ↓
Vault matching: detected climbs matched to existing vaults
        ↓
Points earned = TSS × multiplier
        ↓
If new KOM or leaderboard entry → celebration modal
```

### 2. Vault Creation

```
User rides a climb (detected in RideView)
        ↓
Pattern shows "No vault match" → Create Vault CTA
        ↓
VaultFlowDemo: name vault, confirm signature
        ↓
Cost: Entitlement tier unlocks (pre-TGE free, logged)
        ↓
Vault created on-chain → User is "Minter"
```

### 3. Staking

```
User navigates to vault they want to stake in
        ↓
VaultView: "Stake" button
        ↓
Modal: Enter points amount (up to stake cap)
        ↓
Stake recorded → LP tokens issued
        ↓
Weekly: 27% of vault pot distributed to stakers pro-rata
```

### 4. Leaderboard Competition

```
User completes vault (ride matches signature)
        ↓
Time recorded, compared to existing leaderboard
        ↓
If top 10 → Leaderboard position + weekly rewards
        ↓
If KOM → Crown + 30% of leaderboard share
```

---

## 7. API Integration

### Base URL
- Production: `https://api.boulderroller.xyz`
- Staging: `http://[STAGING_IP]:8080`

### Key Endpoints (Implemented)

| Category | Endpoints |
|----------|-----------|
| **Auth** | `POST /auth/nonce`, `POST /auth/verify`, `POST /auth/privy/verify`, `POST /auth/refresh` |
| **Rides** | `GET /rides`, `POST /rides/upload`, `GET /rides/:id`, `GET /rides/:id/gps`, `GET /rides/:id/patterns`, `GET /rides/:id/tiles` |
| **Vaults** | `GET /vaults`, `GET /vaults/:id`, `POST /vaults/create`, `POST /vaults/:id/stake`, `POST /vaults/:id/complete` |
| **Points** | `GET /points/balance`, `GET /points/events`, `GET /points/tiers`, `GET /points/leaderboard` |
| **Social** | `GET /feed`, `GET /feed/global`, `POST /rides/:id/kudos`, `GET /social/suggested` |
| **Leaderboard** | `GET /leaderboard/:type` (climb/steady/exploration) |
| **Analytics** | `GET /analytics/fitness`, `GET /analytics/training-load` |

### Case Conversion
- Request bodies: camelCase → snake_case (automatic)
- Response bodies: snake_case → camelCase (automatic)

---

## 8. Current State vs. Gaps

### Implemented ✅

| Feature | Status |
|---------|--------|
| Ride upload + parsing | ✅ Working |
| Pattern detection (climb/steady/explore) | ✅ Working |
| Vault creation + matching | ✅ Working |
| Vault staking | ✅ Working |
| Leaderboards (global, per-vault) | ✅ Working |
| Points period + entitlements | ✅ Working |
| Privy social login | ✅ Working |
| Wallet login (SIWS) | ✅ Working |
| Theme system (6 × 2 = 12) | ✅ Working |
| Profile editing | ✅ Working |
| Activity feed | ✅ Working (global + following) |
| Kudos + comments | ✅ Working |
| Route map + elevation chart | ✅ Working |

### Needs Polish ⚠️

| Area | Issue |
|------|-------|
| Mobile responsive | Some pages need mobile optimization |
| Loading skeletons | Inconsistent across pages |
| Empty states | Generic, need custom illustrations |
| Error states | Need calmer "trust moment" treatment |
| BeetleCard visuals | Accessory rendering not implemented |
| Achievement graphics | Using emoji, need designed badges |
| Map styling | Default Mapbox, could match theme |
| Dark mode contrast | Some themes have readability issues |

### Not Yet Built ❌

| Feature | Priority |
|---------|----------|
| Strava Connect OAuth | High |
| Native GPS recording | Medium |
| BeetleCard marketplace | Medium |
| Bio-passport anti-cheat | Low |
| Governance voting | Low |

---

## 9. Designer Deliverables

### Required Assets

1. **Logo System**
   - Wordmark: "BOULDER ROLLER" (stacked and horizontal)
   - Icon: Beetle icon that works at 16px-512px
   - Lockup: Combined logo for various contexts
   - Favicon + app icons

2. **Beetle Illustrations**
   - BeetleCard base illustration (layered for accessories)
   - 8 accessory categories: Boulder, Legs, Trail, Headgear, Background, Shell, Antennae, Aura
   - Achievement-tier variations

3. **Achievement Badges (50+)**
   - Categories: Distance, Elevation, Streak, Leaderboard, TSS, w/kg
   - Consistent style, scalable
   - Lock/unlock states

4. **Empty/Loading States**
   - No rides yet
   - No vaults found
   - No achievements earned
   - Loading skeleton patterns

5. **Error State Illustrations**
   - Network error
   - Not found
   - Permission denied
   - Calm, non-alarming style

6. **Marketing/Social**
   - Twitter/X header + profile
   - Open Graph cards
   - Email templates

### Figma Components Needed

- Button variants (primary, secondary, ghost, destructive)
- Card variants (content, stat, CTA, vault)
- Form elements (inputs, selects, checkboxes)
- Modal templates
- Navigation (sidebar, header, mobile drawer)
- Leaderboard row
- Activity feed item
- Vault card
- Achievement badge
- BeetleCard display

### Design System Documentation

- Color palette with all 6 themes
- Typography scale
- Spacing scale
- Border/shadow tokens
- Icon guidelines (Lucide set)
- Animation principles

---

## 10. Technical Stack Reference

| Layer | Technology |
|-------|------------|
| Framework | React 18 + Vite |
| Routing | React Router 6 |
| Styling | Tailwind CSS + CSS Variables |
| Components | shadcn/ui + Radix UI |
| State | React Context + local state |
| Icons | Lucide React |
| Charts | Recharts |
| Maps | Mapbox GL JS |
| Wallet | @solana/wallet-adapter |
| Social Auth | Privy SDK |
| Toasts | Sonner |

---

## 11. Distribution Economics (Reference)

For vault-related UI, these are the distribution splits:

| Recipient | Share | Notes |
|-----------|-------|-------|
| Top 10 Leaderboard | 55% | 30/20/15/10/8/6/5/3/2/1% |
| Stakers | 27% | Pro-rata by LP tokens |
| Local Legend | 3% | Single curator seat |
| Protocol | 10% | Treasury operations |
| POL | 5% | Protocol-owned liquidity |

Epoch duration: 7 days (Sunday 12:00 UTC anchor)

---

## 12. File References

| Document | Purpose |
|----------|---------|
| `docs/TOKENOMICS_V2.md` | Token economics source of truth |
| `docs/spec2025.md` | Founder interview, brand evolution |
| `docs/rfcs/PRIVY_AUTH_UX.md` | Privy integration architecture |
| `web/portal/src/contexts/ThemeContext.tsx` | Theme implementation |
| `web/portal/src/lib/api.ts` | API client + types |
| `web/portal/src/App.tsx` | Route structure |

---

## 13. Contact

- **Email:** info@boulderroller.com
- **Repo:** Private (designer will have access)

---

*This document supersedes DESIGNER_TOPOLOGY.md. Reference TOKENOMICS_V2.md and spec2025.md for source-of-truth on tokenomics and product direction.*
