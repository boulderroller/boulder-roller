# Boulder Rollers V2 - Complete System & Design Topology
## Designer Meeting Resource - December 2025

> **DEPRECATED** (January 2, 2026)
>
> This document is outdated. Please refer to:
>
> **[DESIGNER_HANDOFF_JAN2026.md](./DESIGNER_HANDOFF_JAN2026.md)** — Current designer handoff document
>
> Key changes since this doc:
> - Privy social login implemented (Google, Apple, Email)
> - Vault system fully operational with staking + leaderboards
> - Points period active with entitlement tiers
> - 21 pages now (was 8 tabs)
> - 100+ components (was 73)
> - Updated theme system and brand guidelines

---

# PART 1: SYSTEM ARCHITECTURE

## High-Level System Topology

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                        │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                      │
│   │   iOS App    │    │  Web Portal  │    │ Dev Dashboard│                      │
│   │  (SwiftUI)   │    │   (Next.js)  │    │   (FastAPI)  │                      │
│   │              │    │              │    │              │                      │
│   │ • SIWS Auth  │    │ • 73 comps   │    │ • Tile viz   │                      │
│   │ • Ride list  │    │ • 6 Themes   │    │ • Vault mgmt │                      │
│   │ • Upload     │    │ • Neo-brutal │    │ • OSM debug  │                      │
│   │ • Patterns   │    │ • Strava-ish │    │ • Detection  │                      │
│   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                      │
│          │                   │                   │                               │
│          └───────────────────┴───────────────────┘                               │
│                              │                                                   │
│                         HTTPS + JWT                                              │
└──────────────────────────────┼───────────────────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           API LAYER (FastAPI)                                    │
│                        [STAGING_IP]:8080                                       │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                         31 ROUTE MODULES                                 │   │
│   ├──────────────┬──────────────┬──────────────┬──────────────┬─────────────┤   │
│   │ /auth        │ /rides       │ /scoring     │ /leaderboard │ /cal        │   │
│   │ /beetles     │ /portfolio   │ /mint        │ /analytics   │ /feed       │   │
│   │ /social      │ /users       │ /compliance  │ /admin       │ /health     │   │
│   └──────────────┴──────────────┴──────────────┴──────────────┴─────────────┘   │
│                                                                                  │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                         PROCESSING PIPELINE                              │   │
│   │                                                                          │   │
│   │  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐  │   │
│   │  │ RideParser  │──▶│ TileService │──▶│PatternEngine│──▶│ VaultMatch  │  │   │
│   │  │             │   │    (H3)     │   │             │   │             │  │   │
│   │  │ FIT/GPX/TCX │   │ res 10 ~50m │   │ • Climb     │   │ • Signature │  │   │
│   │  │ Rust 6.4x ⚡│   │ • project   │   │ • Steady    │   │ • Tile ovlp │  │   │
│   │  │             │   │ • sequence  │   │ • Explore   │   │ • OSM attr  │  │   │
│   │  └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘  │   │
│   │                                                                          │   │
│   │  ┌─────────────────────────────────────────────────────────────────┐    │   │
│   │  │                    SCORING SERVICE                               │    │   │
│   │  │  CAL Budget (2200/day) ──▶ Pattern Score ──▶ DUNG Mint Request  │    │   │
│   │  └─────────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
┌──────────────────────────┐ ┌──────────────────────┐ ┌──────────────────────────┐
│      SUPABASE            │ │        REDIS         │ │         SOLANA           │
│   (Postgres + Auth)      │ │    (Cache/Queue)     │ │        (Devnet)          │
├──────────────────────────┤ ├──────────────────────┤ ├──────────────────────────┤
│ • rides                  │ │ • Celery tasks       │ │ DUNGcoin Program         │
│ • activity_streams       │ │ • Session cache      │ │ • mint_dung()            │
│ • patterns_climb         │ │ • Rate limiting      │ │ • TSS authority          │
│ • patterns_steady        │ │                      │ │                          │
│ • patterns_exploration   │ │                      │ │ kCAL Program             │
│ • climb_vault            │ │                      │ │ • record_effort()        │
│ • cal_balances           │ │                      │ │ • settle_segment()       │
│ • beetle_cards           │ │                      │ │                          │
└──────────────────────────┘ └──────────────────────┘ └──────────────────────────┘
```

## Core Data Flow

```
Upload FIT → Rust Parse (6.4x faster) → H3 Tiles → Pattern Detect →
Vault Match → OSM Attribution → CAL Check → Score → DUNG Mint → Leaderboard
```

## Component Maturity

| Component | Status | Notes |
|-----------|--------|-------|
| Backend API | ✅ 95% | 31 routes, all core flows |
| Climb Detection | ✅ 100% | 16 tests passing |
| Rust Parser | ✅ 100% | FIT/GPX/TCX, deployed |
| Tile System | ✅ 95% | H3 projection working |
| Vault Matching | ✅ 90% | Signature + tile overlap |
| Solana Programs | ✅ Devnet | DUNGcoin + kCAL |
| iOS App | ⚠️ 70% | Core works, UI partial |
| Web Portal | ⚠️ 60% | Components ready, API wiring |

---

# PART 2: PORTAL-V2 FRONTEND ARCHITECTURE

## Project Structure

```
/web/portal-v2/
├── src/
│   ├── app/                    # Next.js 16 App Router
│   │   ├── layout.tsx          # Root layout + providers
│   │   ├── page.tsx            # Landing (StealthLanding)
│   │   ├── app/
│   │   │   ├── layout.tsx      # App shell (Header, auth check)
│   │   │   └── page.tsx        # Dashboard (tab router)
│   │   └── globals.css         # Theme vars + typography
│   │
│   ├── components/             # 73 COMPONENTS
│   │   ├── ui/                 # 30+ shadcn/radix primitives
│   │   ├── [Tabs]              # HomeTab, RidesTab, PilesTab...
│   │   ├── [Modals]            # RideDetailModal, StakeModal...
│   │   ├── [Layout]            # Header, Sidebar, ProfilePanel
│   │   └── [Widgets]           # BeetleCard, StatBadge...
│   │
│   ├── contexts/               # Global state
│   │   ├── AppContext.tsx      # User, rides, auth, tabs
│   │   ├── ThemeContext.tsx    # 6 themes × 2 (light/dark)
│   │   └── WalletContext.tsx   # Solana wallet
│   │
│   ├── hooks/                  # 15 custom hooks
│   │   ├── useRides.ts
│   │   ├── useSegments.ts
│   │   ├── useStaking.ts
│   │   ├── useCAL.ts
│   │   └── ...
│   │
│   ├── lib/
│   │   ├── api.ts              # APIClient (auth, CRUD)
│   │   ├── theme.ts            # 12 theme variants
│   │   └── format.ts           # Utilities
│   │
│   └── types/
│       ├── app.ts              # Domain models
│       └── api.ts              # API contracts
│
├── public/                     # Static (minimal - 5 SVGs)
├── tailwind.config.ts
└── package.json
```

## Component Inventory (73 Total)

### Tab Components (8)
| Component | Purpose | Status |
|-----------|---------|--------|
| `HomeTab` | Hero + daily energy + weekly stats | ✅ |
| `RidesTab` | Ride list + upload modal | ✅ |
| `PilesTab` | Map + leaderboard + staking | ✅ |
| `PortfolioTab` | Holdings + claims | ✅ |
| `FeedTab` | Activity feed + social | ✅ |
| `ProfileTab` | User profile + achievements | ✅ |
| `ChallengesTab` | Active/available challenges | ✅ |
| `DiscoverTab` | Find riders + segments | ✅ |

### Modal Components (15+)
| Component | Purpose |
|-----------|---------|
| `RideDetailModal` | Full ride info + segments |
| `RideSummaryModal` | Quick ride overview |
| `RideUploadModal` | FIT/GPX/TCX upload |
| `PileDetailModal` | Segment details + ranking |
| `StakeModal` | Stake LP tokens |
| `ClaimRewardsModal` | Claim epoch rewards |
| `CALBoostModal` | Buy CAL energy |
| `WalletModal` | Connect Phantom/Solflare |
| `AccessoryModal` | Beetle customization |
| `RankingModal` | Rank progression |
| `FollowingModal` | User follow list |
| `CreatePileModal` | Create new segment |
| `OnboardingFlow` | Initial setup wizard |
| `QuickSetup` | Username + FTP setup |
| `SettingsPanel` | Theme switcher + prefs |

### UI Primitives (30+ from shadcn/Radix)
- Layout: `Card`, `Dialog`, `Drawer`, `Sheet`, `Tabs`, `Accordion`
- Forms: `Input`, `Textarea`, `Select`, `Checkbox`, `Switch`, `Slider`
- Display: `Avatar`, `Badge`, `Button`, `Progress`, `Skeleton`
- Overlay: `Popover`, `HoverCard`, `Tooltip`, `DropdownMenu`
- Data: `Table`, `Chart` (Recharts wrapper)

### Custom Widgets
| Component | Purpose |
|-----------|---------|
| `BeetleCard` | NFT progression card |
| `BeetleAvatar` | User avatar with beetle |
| `StatBadge` | Stat display chip |
| `EpochCountdown` | Time to epoch end |
| `PowerCurveCard` | Power duration curve |
| `FitnessDashboard` | CTL/ATL/TSB display |
| `AICoach` | Training recommendations |
| `GlobalActivityFeed` | Public activity stream |
| `NotificationPanel` | Toast notifications |
| `NotificationInbox` | Modal notification list |

---

## Design System

### Visual Language: Neo-Brutalism

```
┌────────────────────────────────────────────────────┐
│                                                    │
│   ┌──────────────────────────────────────────┐    │
│   │  3px solid border                         │    │
│   │                                           │    │
│   │   BOLD TYPOGRAPHY                         │    │
│   │   Font-weight: 800                        │    │
│   │   Letter-spacing: tight                   │    │
│   │                                           │    │
│   │   Offset shadow: 6px 6px 0 0 #000        │    │
│   └──────────────────────────────────────────┘    │
│        ↑                                          │
│        Shadow creates depth                       │
│                                                   │
└────────────────────────────────────────────────────┘
```

### 6 Theme Palettes

| Theme | Inspiration | Primary Colors |
|-------|-------------|----------------|
| **Default** | Neo-Brutalism | Purple #8b5cf6, Blue, Cyan |
| **Monet** | Water Lilies | Muted blues/purples |
| **Degas** | Ballet Rose | Mauve/pink tones |
| **Renoir** | Sunny Afternoon | Warm browns/yellows |
| **Cezanne** | Mont Sainte-Victoire | Muted greens/browns |
| **Seurat** | Pointillist Dream | Muted grays/taupes |

Each theme has **light** and **dark** variants = **12 total variants**

### Color Token Structure

```css
:root {
  /* Base */
  --black: #000000;
  --white: #ffffff;

  /* Neutrals */
  --grey-50: #fafafa;
  --grey-100: #f4f4f5;
  --grey-200: #e4e4e7;
  --grey-700: #3f3f46;
  --grey-900: #18181b;

  /* Brand */
  --purple: #8b5cf6;
  --purple-dark: #7c3aed;
  --blue: #3b82f6;
  --cyan: #06b6d4;
  --green: #22c55e;
  --yellow: #eab308;
  --orange: #f97316;
  --pink: #ec4899;
  --red: #ef4444;

  /* Shadows (Neo-Brutalism signature) */
  --shadow-sm: 4px 4px 0 0 #000000;
  --shadow-md: 6px 6px 0 0 #000000;
  --shadow-lg: 8px 8px 0 0 #000000;
  --shadow-xl: 12px 12px 0 0 #000000;
}
```

### Typography

```css
/* Headings */
h1: font-weight: 800, letter-spacing: -0.025em
h2: font-weight: 700, letter-spacing: -0.02em
h3: font-weight: 600

/* Body */
body: font-family: system-ui, -apple-system, sans-serif

/* Monospace (for numbers) */
.font-mono: 'JetBrains Mono', 'SF Mono', monospace
font-variant-numeric: tabular-nums
```

### Responsive Breakpoints

| Breakpoint | Width | Layout |
|------------|-------|--------|
| Mobile | < 768px | Single column, drawer sidebar |
| Tablet | 768-1024px | Two column |
| Desktop | > 1024px | Three column (Strava-style) |

---

## Page/Route Structure

```
/                           → StealthLanding (invite gate)
│   • Beetle emoji easter egg (3 clicks → invite modal)
│   • Email waitlist signup
│   • Invite codes: 'alpha-code-1', 'alpha-code-2', 'alpha-code-3'
│
└── /app                    → Protected Dashboard
    │
    ├── Header ─────────────┬─── CAL Balance Display
    │                       ├─── Wallet Button
    │                       ├─── Notifications Bell
    │                       └─── Theme Switcher
    │
    ├── Sidebar (8 tabs) ───┬─── Home
    │                       ├─── Rides
    │                       ├─── Piles (Segments)
    │                       ├─── Portfolio
    │                       ├─── Feed
    │                       ├─── Profile
    │                       ├─── Challenges
    │                       └─── Discover
    │
    └── Main Content Area ──── [Active Tab Component]
```

---

## State Management

### Context Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Providers Wrapper                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│   ┌─────────────────┐                                   │
│   │  ThemeContext   │  • theme (colors)                 │
│   │                 │  • themeName                      │
│   │                 │  • isDark                         │
│   │                 │  • setTheme(), cycleTheme()       │
│   └────────┬────────┘                                   │
│            │                                            │
│   ┌────────▼────────┐                                   │
│   │  WalletContext  │  • Solana wallet adapter          │
│   │                 │  • Phantom, Solflare              │
│   │                 │  • publicKey, signMessage         │
│   └────────┬────────┘                                   │
│            │                                            │
│   ┌────────▼────────┐                                   │
│   │   AppContext    │  • isAuthenticated                │
│   │                 │  • user, wallet, userId           │
│   │                 │  • rides[], piles[], claims[]     │
│   │                 │  • calBalance, canMint            │
│   │                 │  • activeTab                      │
│   │                 │  • weeklyStats                    │
│   └─────────────────┘                                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### TanStack Query (Server State)

```typescript
// Query Keys
['user']           // Current user profile
['rides']          // User's rides
['cal-balance']    // CAL token balance
['segments']       // Available segments/piles
['leaderboard', segmentId, epoch]
['notifications']
['achievements']
```

### localStorage Persistence

```
access_token       // JWT access token
refresh_token      // JWT refresh token
br_access          // Invite code validation
br-active-tab      // Current tab
br-simple-mode     // UI mode preference
dungbeetle-theme   // Theme name
dungbeetle-theme-dark  // Dark mode flag
quickSetupSkipped  // Onboarding state
```

---

## API Integration

### APIClient Methods

```typescript
// Authentication
POST /auth/nonce        → { nonce, expiresAt }
POST /auth/verify       → { accessToken, refreshToken }
POST /auth/refresh      → { accessToken, refreshToken }

// Rides
GET  /rides             → Ride[]
POST /rides/upload      → { rideId, status }
GET  /rides/{id}        → Ride
GET  /rides/{id}/segments → Segment[]

// Segments (Piles)
GET  /segments/list     → Pile[]
GET  /segments/nearby   → Pile[]
GET  /leaderboard/{id}  → LeaderboardEntry[]
POST /staking/stake     → void
POST /staking/unstake   → void

// CAL Token
GET  /cal/balance       → { balance, canMint }
POST /cal/mint          → { txSignature }

// Social
GET  /feed              → Activity[]
POST /kudos/{rideId}    → void
POST /comments/{rideId} → Comment

// Analytics
GET  /analytics/fitness → { ctl, atl, tsb, form }
GET  /analytics/power-zones → PowerZone[]
```

### Case Conversion
- Request: camelCase → snake_case (automatic)
- Response: snake_case → camelCase (automatic)

---

## Key User Flows

### 1. Authentication (SIWS)

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│  User   │────▶│ Wallet  │────▶│  Sign   │────▶│  JWT    │
│ clicks  │     │  Modal  │     │ Message │     │ Tokens  │
│ Connect │     │ appears │     │ (SIWS)  │     │ stored  │
└─────────┘     └─────────┘     └─────────┘     └─────────┘
```

### 2. Ride Upload

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│  User   │────▶│ Upload  │────▶│  Parse  │────▶│ Patterns│
│ selects │     │  Modal  │     │  File   │     │ detected│
│  file   │     │  opens  │     │ (Rust)  │     │ + scored│
└─────────┘     └─────────┘     └─────────┘     └─────────┘
```

### 3. Scoring for DUNG

```
┌─────────┐     ┌─────────┐     ┌─────────┐     ┌─────────┐
│ Pattern │────▶│  CAL    │────▶│  Score  │────▶│  DUNG   │
│ detected│     │ deducted│     │ recorded│     │ minted  │
│         │     │ (2200/d)│     │         │     │ (Solana)│
└─────────┘     └─────────┘     └─────────┘     └─────────┘
```

---

## Missing Assets (Designer Action Items)

### Required Graphics
- [ ] Beetle illustrations (currently only emoji 🪲)
- [ ] Achievement/badge graphics (50+ badges)
- [ ] Accessory/customization items
- [ ] Logo/branding assets
- [ ] Social media graphics
- [ ] Loading/empty state illustrations

### Fonts to Confirm
- [ ] JetBrains Mono (for numbers)
- [ ] System fonts sufficient? Or custom brand font?

### Icons
- Currently using **Lucide React** (500+ icons)
- [ ] Any custom icons needed?

---

## Design Opportunities

### Polish Areas
1. **Micro-interactions** - Button hovers, tab transitions
2. **Loading states** - Custom skeletons per component
3. **Empty states** - Illustrated "no rides yet" etc.
4. **Error states** - Friendly error illustrations
5. **Dark mode contrast** - Some themes need work
6. **Mobile navigation** - Drawer could be more polished

### Feature Enhancements
1. **Beetle customization** - Visual accessory system
2. **Achievement celebrations** - Confetti/animation on unlock
3. **Leaderboard animations** - Rank change effects
4. **Map styling** - Custom Mapbox style matching theme
5. **Chart theming** - Recharts custom colors per theme

---

## Tech Stack Summary

| Layer | Technology |
|-------|------------|
| Framework | Next.js 16 + React 19 |
| Language | TypeScript 5 (strict) |
| Styling | Tailwind CSS 4 + CSS Variables |
| Components | shadcn/ui + Radix UI |
| State | React Context + TanStack Query 5 |
| Icons | Lucide React (500+) |
| Charts | Recharts 3 |
| Maps | Mapbox GL 2 |
| Wallet | @solana/wallet-adapter |
| Auth | SIWS (Sign In With Solana) + JWT |

---

# PART 3: NAMING NOMENCLATURE MAPPING

## Backend ↔ Frontend Term Mapping

| Backend Term | Frontend Term | UI Label |
|--------------|---------------|----------|
| `patterns_climb` | `ClimbPattern` | "Climb" |
| `patterns_steady` | `SteadyPattern` | "Steady Effort" |
| `patterns_exploration` | `ExplorePattern` | "Exploration" |
| `segments` | `Pile` / `Segment` | "Pile" |
| `cal_balances` | `calBalance` | "Daily Energy" |
| `scored_patterns` | `scoredPattern` | "Scored" |
| `beetle_cards` | `BeetleCard` | "Beetle Card" |
| `climb_vault` | `vaultClimb` | "Canonical Climb" |
| `h3_tile_ids` | `tileSequence` | (internal) |

## Pattern Types

| Type | Description | Scoring Basis |
|------|-------------|---------------|
| **Climb** | Sustained elevation gain (50m+) | Vertical + Power |
| **Steady** | Z2-Z3 aerobic (20min+) | Duration + NP |
| **Explore** | New territory discovery | New tiles % |

## Beetle Progression

| Level | Name | Requirement |
|-------|------|-------------|
| 1 | Larva | 0 rides |
| 2 | Pupa | 10 rides |
| 3 | Beetle | 50 rides |
| 4 | Dung Roller | 100 rides |
| 5 | Scarab | 250 rides |

---

# PART 4: QUICK REFERENCE

## Key File Locations

```
BACKEND
├── backend/app/routes/          # API endpoints
├── backend/app/services/        # Business logic
├── backend/app/models/          # Data models
└── backend/sql/                 # Migrations

FRONTEND (portal-v2)
├── src/app/                     # Pages/routes
├── src/components/              # 73 components
├── src/contexts/                # State management
├── src/hooks/                   # 15 custom hooks
├── src/lib/api.ts               # API client
└── src/lib/theme.ts             # 12 theme variants

SOLANA
├── protocol/programs/dungcoin/  # DUNG minting
└── protocol/programs/kcal/      # kCAL tracking
```

## Live Endpoints

| Service | URL |
|---------|-----|
| API | `http://[STAGING_IP]:8080` |
| Supabase | `db.qzkqjevawthyboymqrle.supabase.co` |
| Solana | Devnet |

## Current Blockers for Alpha

1. ⚠️ iOS TestFlight build
2. ⚠️ Web portal API wiring
3. ⚠️ Asset library (illustrations, badges)
4. ⚠️ Basic monitoring/alerts

---

# APPENDIX: Design System Comparison

## portal-v2 vs org (marketing site)

| Aspect | portal-v2 (App) | org (Marketing) |
|--------|-----------------|-----------------|
| Purpose | Full dashboard | Landing page |
| Components | 73 | 4 |
| Styling | Neo-brutalism | Bronze/gold stealth |
| 3D | None | React Three Fiber |
| Auth | Full SIWS | None |
| Themes | 6 × 2 = 12 | Single palette |

The **org** site is the "premium first impression" → leads to **portal** (where action happens).

---

*Document generated for designer meeting - December 2024*
*System topology + frontend architecture combined*
