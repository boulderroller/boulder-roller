# Boulder Roller - Design System Rules (Figma MCP Integration)

> **Purpose:** This document captures what currently exists in the codebase — warts and all.
> It is an audit of the current state, NOT a prescriptive design system.
> Corey's first task is to create the real design system in Figma, using this as context
> for what exists, what's inconsistent, and what needs decisions.
>
> **Active contract:** use `docs/design/PORTAL_DESIGN_SYSTEM_2026.md` for the
> current public-root-to-portal visual system. This file remains historical
> audit context only.

---

## 0. Known Inconsistencies & Design Debt

**Read this section first.** The current UI was built iteratively without a designer. It works,
but it's not a coherent system. Corey's design system should resolve these issues.

### Color System: Three Competing Approaches

The codebase applies colors three different ways, and they don't always agree:

| Approach | Where Used | Problem |
|----------|-----------|---------|
| `useTheme()` + inline styles | Beetle components (`BeetleButton`, `BeetleCard`, etc.) | Correct approach, but some values are hardcoded to Hoo-Breddin theme |
| Tailwind CSS vars (`bg-background`, `text-foreground`) | shadcn/ui components | Works via ThemeContext → CSS var mapping, but disconnected from Beetle components |
| Hardcoded hex values | Scattered throughout | Breaks when switching themes |

**Specific hardcoding issues:**
- `BeetleCard` line 31: `isDarkMode ? '#2a2d1e' : colors.bg` — `#2a2d1e` is Hoo-Breddin dark bg, wrong for all other themes
- `BeetleButton` secondary variant: `isDarkMode ? '#3a3d2e' : 'white'` — Hoo-Breddin specific
- `BeetleInput`: hover border `#8b6f47` and focus border `#c89b5c` are hardcoded, not theme-aware

**Decision needed:** Pick ONE canonical way to apply theme colors. Recommendation: `useTheme()` for custom components, CSS vars for shadcn, eliminate all hardcoded hex values.

### Typography: No Defined Scale

Font sizes are ad-hoc across components. There is no type scale — sizes were chosen per-component:

```
text-[9px], text-[10px], text-[11px], text-[12px], text-[13px], text-[14px], text-[16px]
text-xs, text-sm, text-base, text-lg, text-xl, text-2xl
```

That's 13+ different sizes with no clear hierarchy or rules for when to use which. Some components mix arbitrary values (`text-[13px]`) with Tailwind defaults (`text-sm` = 14px) — nearly identical sizes used for different purposes.

**Decision needed:** Define a type scale (6-8 sizes max) with clear semantic roles (heading, subheading, body, caption, data, micro).

### shadcn/ui vs Beetle Components: Unclear Boundaries

Both `Button` (shadcn) and `BeetleButton` exist. Both `Card` (shadcn) and `BeetleCard` exist. Both `Input` (shadcn) and `BeetleInput` exist. It's unclear which to use when, and some pages mix both.

**Decision needed:** Are Beetle components the standard going forward? Should shadcn primitives only be used internally by Beetle components? Or do we keep both?

### 30+ Markdown Docs in `src/`

There are 30+ `.md` files in `web/portal/src/` from various audits, brainstorms, and session summaries. Many are outdated or contradictory. They include:

- Multiple "audit" docs with overlapping findings
- Session summaries from specific work sessions
- Brainstorm docs with ideas that were/weren't implemented
- Fix plans that may or may not have been executed

**Decision needed:** These should be triaged — keep what's still relevant, archive or delete the rest. They shouldn't live in `src/`.

### Responsive Design: Minimal

Most components are desktop-first with minimal mobile consideration. Grid layouts use fixed columns. Many components have no responsive breakpoints at all. Mobile support is limited to sidebar collapse and a few `hidden sm:flex` toggles.

**Decision needed:** Is mobile a priority for alpha? If so, the responsive approach needs real design work, not just hide/show toggles.

### Zero Radius: Intentional or Overcorrected?

The `* { --radius: 0px !important }` global override is aggressive — it kills radius on everything including shadcn components that were designed with it. The only exception is `BeetleInput` which manually applies `rounded-[8px]`.

**Decision needed:** Is pure zero radius the final aesthetic, or should some elements (inputs, avatars, badges) have controlled radius? Corey should make this call.

### What IS Consistent (Keep These)

Some things are working well and should be preserved:
- **Beetle interaction physics** — hover lifts, click depresses, hard shadows. This is distinctive.
- **Geist Sans + Geist Mono role system** — UI and headings remain distinct from numeric and technical data.
- **SEMANTIC_COLORS constants** — well-organized domain colors (CAL blue, DUNG gold, ranks, status).
- **Dark mode support** — the ThemeContext approach works, it just needs the hardcoded values fixed.
- **6-theme system** — novel and distinctive, worth keeping.

---

## 1. Tech Stack

| Layer | Technology |
|-------|-----------|
| **Framework** | React 18 (SPA, client-side routing via react-router-dom) |
| **Build** | Vite 6 + SWC (`@vitejs/plugin-react-swc`) |
| **Styling** | Tailwind CSS v4 (CSS-first config, no tailwind.config file) |
| **Component Primitives** | shadcn/ui + Radix UI (~25 Radix packages) |
| **Animations** | Framer Motion (`motion`) + CSS keyframe animations |
| **Charts** | Recharts |
| **Maps** | Leaflet + react-leaflet + h3-js |
| **Icons** | lucide-react (no SVG files in project) |
| **Path Alias** | `@/` maps to `./src/` |
| **Deploy** | Vercel (SPA rewrites) |

---

## 2. Design Aesthetic: "Brutalist Beetle"

The UI follows a **brutalist, mechanical** design language. This is non-negotiable and must be preserved when implementing any Figma design.

### Core Rules

| Rule | Implementation |
|------|---------------|
| **Zero border radius** | `--radius: 0px !important` enforced globally in `globals.css`. All corners are sharp. |
| **Hard shadows** | `2px 2px 0px 0px` (sm), `3px 3px 0px 0px` (md), `4px 4px 0px 0px` (lg) — no blur, no spread |
| **Mechanical interactions** | Hover lifts elements, active/click depresses them. Shadow grows on hover, collapses on press. |
| **Role-based typography** | Authored casing, zero tracking, and a 12px/16px floor for labels and captions |
| **Blocky scrollbars** | Custom 12px mechanical scrollbars, zero radius |
| **Hard focus rings** | 2px solid outline, 2px offset. No soft glows. |

### Exception

`BeetleInput` and `BeetleTextarea` use `rounded-[8px]` — the **only** elements with border radius.

---

## 3. Token Definitions

### 3a. Color Tokens

**Three color layers coexist:**

#### Layer 1: Theme Colors (runtime-dynamic)

**Source:** `src/contexts/ThemeContext.tsx`

Six selectable themes, each with light + dark variants. The active theme writes CSS variables to `:root` at runtime via `document.documentElement.style.setProperty()`.

| Theme | ID | Accent (Light) | Accent (Dark) |
|-------|----|----------------|---------------|
| Hoo-Breddin (default) | `hoo-breddin` | `#8b9475` | `#8b9475` |
| Water | `water` | `#4a90d9` | `#6ba8d4` |
| Sunny | `sunny` | `#f0c869` | `#f0c869` |
| Safari | `safari` | `#c7a76f` | `#d9b885` |
| Moss | `moss` | `#6b8e5a` | `#8ba87a` |
| Foundries | `foundries` | `#6b7a8e` | `#8e9aab` |

Each theme provides 6 values: `bg`, `bgSecondary`, `accent`, `text`, `textMuted`, `border`.

**Access pattern in components:**
```tsx
const { isDarkMode, colors } = useTheme();
// colors.bg, colors.accent, colors.text, etc.
```

**CSS variable mapping (ThemeContext → shadcn vars):**
```
colors.bg → --background
colors.text → --foreground
colors.bgSecondary → --card, --secondary, --muted, --sidebar
colors.accent → --primary, --accent, --ring
colors.textMuted → --muted-foreground
colors.border → --border
```

#### Layer 2: Semantic Colors (static constants)

**Source:** `src/constants/colors.ts`

Used for domain-specific meanings that don't change with theme:

```typescript
// Token colors
calGlow: '#4fc3f7'        // CAL - electric blue
dungGlow: '#c89b5c'       // DUNG - golden
dungDisplay: '#d4a574'
crownGold: '#d4af37'

// Status
dangerRed: '#d45d5d'
successGreen: '#8ba87a'
warningYellow: '#d4c993'

// Ranks
rankS: '#d4af37'  // Gold
rankA: '#c7a76f'  // Bronze-gold
rankB: '#8ba87a'  // Green
rankC: '#a0a89a'  // Gray-green
rankD: '#6b7a5a'  // Muted green
```

Helper functions for theme-aware overlays:
- `getOverlay(isDarkMode, strength?)` — border/bg overlays
- `getHoverBg(isDarkMode)` — hover backgrounds
- `getDivider(isDarkMode)` — subtle dividers
- `getAccentHighlight(isDarkMode, intensity?)` — golden accent highlights

#### Layer 3: CSS Custom Properties (globals.css fallbacks)

**Source:** `src/styles/globals.css`

Static fallback values in `:root` and `.dark` selectors. These are overwritten at runtime by ThemeContext but define the initial/SSR state. Mapped to Tailwind via `@theme inline`.

### 3b. Typography Tokens

**Fonts** (loaded via Google Fonts in `index.html`):

| Font | Use | Weights |
|------|-----|---------|
| **Geist Sans** | UI text, labels, headings, body | 400, 500, 600, 700; 800/900 only for app-entry display |
| **Geist Mono** | Numbers, data values, monospace/terminal | 400, 500, 600, 700 |

**Application pattern:**
```tsx
// Geist Sans is the global UI default
className="text-[14px] font-medium"

// Numeric and technical data use a semantic class backed by --br-font-mono
className="portal-metric__value"
```

**Typography rules** (from the active portal contract):
- UI and data both use `letter-spacing: 0` and authored casing.
- Labels and captions use at least `12px / 16px`.
- Product UI uses only 400, 500, 600, and 700 weights.
- 800 and 900 are reserved for public-root/app-entry editorial display.

**Common sizes used in components:**
- `text-[12px]` — small button text, captions
- `text-[13px]` — data values (Geist Mono)
- `text-[14px]` — body text, input text, button default
- `text-[16px]` — large button text
- `text-sm` / `text-base` / `text-lg` — standard Tailwind sizes

### 3c. Spacing

**Base unit:** 4px (Tailwind v4 default `--spacing: 0.25rem`)

Standard Tailwind spacing classes used throughout: `p-2`, `p-3`, `p-4`, `gap-2`, `gap-3`, `mb-1`, etc.

No custom spacing scale — use Tailwind defaults.

### 3d. Shadows

**Source:** `src/constants/colors.ts` (BEETLE_SHADOWS)

| Size | Value | Use |
|------|-------|-----|
| `sm` | `2px 2px 0px 0px` | Buttons (resting state) |
| `md` | `3px 3px 0px 0px` | Buttons (hover state) |
| `lg` | `4px 4px 0px 0px` | Cards (resting state) |

Shadow color is always the theme's `border` color (or darker variant in dark mode).

**Glow effects** (for token/reward displays):
```typescript
GLOW_EFFECTS.cal: '0 0 16px rgba(79, 195, 247, 0.3)'    // Blue CAL glow
GLOW_EFFECTS.dung: '0 0 20px rgba(200, 155, 92, 0.3)'   // Golden DUNG glow
GLOW_EFFECTS.crown: '0 0 16px rgba(212, 175, 55, 0.4)'  // Crown/rank glow
```

### 3e. Border Radius

**Global:** `0px` everywhere (enforced via `* { --radius: 0px !important }`)

**Exception:** `BeetleInput` / `BeetleTextarea` use `rounded-[8px]`

### 3f. Breakpoints

Tailwind v4 defaults:
| Prefix | Width |
|--------|-------|
| `sm` | 640px |
| `md` | 768px (primary mobile breakpoint) |
| `lg` | 1024px |
| `xl` | 1280px |

Mobile detection hook: `useIsMobile()` from `src/components/ui/use-mobile.ts` (breakpoint: 768px)

---

## 4. Component Architecture

### Two-Layer System

**Layer 1: shadcn/ui primitives** — `src/components/ui/`

Standard Radix-based components with `cn()` class merging. ~45 files. These provide accessible, headless behavior. Used for generic UI needs (dialogs, dropdowns, tabs, tooltips, etc.).

**Layer 2: Beetle components** — Custom components implementing the brutalist aesthetic.

| Component | File | Purpose |
|-----------|------|---------|
| `BeetleButton` | `ui/beetle-button.tsx` | Primary button with press physics |
| `BeetleCard` | `ui/beetle-card.tsx` | Card surface with lift/press interaction |
| `BeetleInput` | `ui/beetle-input.tsx` | Text input with hover/focus states |
| `BeetleTextarea` | `ui/beetle-input.tsx` | Multiline input (same file) |
| `StatPill` | `ui/StatPill.tsx` | Stat display (icon + Geist Mono value + Geist Sans label) |
| `PointsCounter` | `ui/PointsCounter.tsx` | Animated golden counter |
| `AchievementBadge` | `ui/AchievementBadge.tsx` | Progress badge with emoji |
| `LeaderboardTable` | `ui/LeaderboardTable.tsx` | Ranked table with medals |
| `EmptyState` | `ui/empty-state.tsx` | Centered empty state with CTA |
| `LoadingSkeleton` | `ui/loading-skeleton.tsx` | Multi-variant skeleton loader |

### Utility Function

```typescript
// src/components/ui/utils.ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

Use `cn()` for all conditional/merged Tailwind classes in shadcn-style components.

### BeetleButton Details

**Variants:** `primary` | `secondary` | `danger` | `ghost`
**Sizes:** `sm` (12px) | `md` (14px) | `lg` (16px)

```tsx
<BeetleButton variant="primary" size="md">UPLOAD</BeetleButton>
<BeetleButton variant="secondary" isLoading>SAVING</BeetleButton>
<BeetleButton variant="danger" size="sm">DELETE</BeetleButton>
```

Interaction physics:
- **Resting:** 2px hard shadow
- **Hover:** Shadow grows to 3px, element lifts 1px, slight brightness increase
- **Active:** Shadow collapses to 0, element presses down 2px, slight brightness decrease
- **Loading:** Shows "CALIBRATING_" with blinking cursor
- **Disabled:** 40% opacity, no pointer, no transform

Buttons use authored casing, zero tracking, Geist Sans, and the supported 500/600/700 weights.

### BeetleCard Details

**Variants:** `default` (hard shadow) | `flat` (no shadow)
**Interactive prop:** `true` renders as `<button>`, `false` renders as `<div>`

```tsx
<BeetleCard interactive onClick={handleClick}>Clickable</BeetleCard>
<BeetleCard variant="flat">Static content</BeetleCard>
```

Interaction physics (interactive only):
- **Resting:** 4px hard shadow, 3px border
- **Hover:** Shadow grows to 5px, element lifts 2px
- **Active:** Returns to resting position

### BeetleInput Details

```tsx
<BeetleInput placeholder="Enter name" error={hasError} />
<BeetleTextarea placeholder="Description" rows={4} />
```

- 2px border, 8px radius (exception to zero-radius rule)
- Hover: border color shifts to `#8b6f47` (golden brown)
- Focus: border becomes `#c89b5c` (DUNG gold), no box-shadow glow
- Error: red border (`#d45d5d`)

---

## 5. Animation System

### CSS Keyframe Animations (globals.css)

| Animation | Duration | Use |
|-----------|----------|-----|
| `fadeIn` | 0.2-0.3s | Page entry, element appearance |
| `slideIn` | 0.4s | Directional entry |
| `slideInRight` | 0.3s | Panel/drawer entry |
| `modalFade` | 0.2s | Modal appearance (scale 0.95→1) |
| `pulseScale` | 2s loop | Attention-drawing pulse |
| `dungPulse` | 2s loop | Golden glow pulse for rewards |
| `shimmer` | 2s loop | Loading skeleton shimmer |
| `shake` | 0.4s | Error/validation shake |

### React Animation Components (`src/components/ui/animations.tsx`)

```tsx
<FadeIn delay={0.1}><Content /></FadeIn>
<SlideIn direction="up" delay={0.2}><Content /></SlideIn>
<DungGlow isActive={hasReward}><Amount /></DungGlow>
<PulseScale isActive={isNew}><Badge /></PulseScale>
<ModalFade><DialogContent /></ModalFade>
<Shake trigger={hasError}><Input /></Shake>
```

### Interaction Timing

| Action | Duration | Easing |
|--------|----------|--------|
| Button hover/active | 75ms | ease-out |
| Card hover | 150ms | ease-out |
| Input focus | 120ms | ease-out |
| Page transitions | 200-300ms | ease-out |
| Attention loops | 2s | ease-in-out |

---

## 6. Styling Approach: Dual Paradigm

The codebase uses **two coexisting styling methods:**

### Method 1: Tailwind Utility Classes (shadcn components)

```tsx
// Standard pattern for shadcn/ui components
<div className={cn(
  "flex items-center gap-2 p-4 border border-border",
  "bg-card text-card-foreground",
  isActive && "bg-accent",
  className
)}>
```

### Method 2: Inline Styles + useTheme() (Beetle components)

```tsx
// Pattern for beetle/custom components
const { isDarkMode, colors } = useTheme();

<div
  className="flex items-center gap-2 p-4 border-[2px]"
  style={{
    backgroundColor: colors.bg,
    borderColor: colors.border,
    color: colors.text,
  }}
>
```

### When to Use Which

| Situation | Method |
|-----------|--------|
| Using shadcn/ui component | Tailwind classes with `cn()` |
| Theme-aware custom component | `useTheme()` + inline styles |
| Static semantic colors | Import from `constants/colors.ts` |
| Layout/spacing | Always Tailwind classes |
| Dynamic theme colors (bg, border, text) | Always `useTheme()` inline styles |

---

## 7. Icon System

**Library:** `lucide-react` (tree-shakeable, individually imported)

```tsx
import { Activity, Mountain, Trophy, MapPin } from "lucide-react";

<Activity className="w-4 h-4" />
<Mountain className="w-5 h-5" style={{ color: colors.textMuted }} />
```

**Standard sizes:**
- `w-3 h-3` / `w-4 h-4` — inline with text, small UI
- `w-5 h-5` — sidebar nav, button icons
- `w-6 h-6` — section headers
- `w-8 h-8` or larger — empty states, hero areas

**Emoji as branding:** The project uses emoji for branding elements:
- `🪲` — beetle/app logo
- `🏆` — achievements
- `🥇🥈🥉` — leaderboard medals
- Theme emojis: `🍂🌊☀️🦒🌲🏭`

**No SVG asset files exist.** All icons come from lucide-react or inline SVG in components.

---

## 8. Asset Management

Extremely minimal — almost no static assets:

| Asset | Location | Notes |
|-------|----------|-------|
| Anchor IDL | `public/idl/boulder_rollers.json` | Solana program interface |
| Map tiles | External URLs (CARTO, OpenTopoMap, Esri) | Defined in `src/lib/mapColors.ts` |
| Fonts | Google Fonts CDN | Geist Sans + Geist Mono |
| Images | None | `ImageWithFallback` handles broken images |

For new image assets: place in `public/` and reference as `/filename.ext`.

---

## 9. Project Structure

```
web/portal/src/
├── main.tsx                    # Entry point, Sentry init
├── App.tsx                     # Router + provider tree
├── index.css                   # Tailwind v4 compiled output
├── styles/
│   └── globals.css             # Theme vars, animations, beetle interaction CSS
├── constants/
│   └── colors.ts               # Semantic colors, glows, shadows
├── contexts/
│   ├── ThemeContext.tsx         # Multi-theme system (6 themes + dark mode)
│   ├── AuthContext.tsx          # Authentication state
│   ├── PrivyContext.tsx         # Privy wallet abstraction
│   ├── WalletContext.tsx        # Solana wallet adapter
│   └── ProtocolModeContext.tsx  # Points vs token mode toggle
├── hooks/                      # Custom React hooks (10 files)
├── lib/
│   ├── api.ts                  # API client
│   ├── mapColors.ts            # Topographic/cartographic palettes
│   ├── formatters.ts           # Display formatters
│   └── solana.ts               # Solana helpers
├── types/
│   └── index.ts                # TypeScript interfaces
├── pages/                      # Route-level components (20 pages)
└── components/
    ├── ui/                     # Primitives: shadcn (~45) + beetle components
    ├── auth/                   # InviteGate, WalletConnect, etc.
    ├── beetle/                 # BeetleAvatar, BeetleCard display
    ├── feed/                   # ActivityFeed, ProfileCard, MiniMap
    ├── layout/                 # DashboardLayout, Sidebar, TopNav
    ├── leaderboard/            # LeaderboardRow
    ├── loading/                # Skeleton loaders
    ├── modals/                 # Upload, Search, Share, Achievement modals
    ├── ride/                   # RouteMap, StatsPanel, ClimbsTable (16 files)
    ├── settings/               # PrivacyZones, SessionManager
    └── vault/                  # CanonVaultCreationModal, StakeWidget
```

### Provider Tree (App.tsx)

```
ThemeProvider
  └── ErrorBoundary
       └── WalletContextProvider
            └── AuthProvider
                 └── PrivyProvider
                      └── ProtocolModeProvider
                           └── AppContent (Router)
```

---

## 10. Responsive Design

**Approach:** Desktop-first with mobile breakpoint adjustments.

**Primary breakpoint:** `md` (768px) — sidebar collapses to sheet overlay.

**Patterns:**
```tsx
// Show/hide based on viewport
className="hidden sm:flex"        // Hidden mobile, flex desktop
className="sm:hidden"             // Show mobile only

// Sidebar: auto-collapses on mobile
<Sidebar collapsible="icon">      // Icon-only on collapse, sheet on mobile

// Mobile detection hook
const isMobile = useIsMobile();   // true if viewport < 768px
```

**Sidebar widths:**
- Desktop expanded: `16rem`
- Desktop collapsed: `3rem`
- Mobile overlay: `18rem`

---

## 11. Figma-to-Code Translation Guide

When implementing a Figma design in this codebase:

### Step 1: Identify Token Mapping
- Map Figma colors to theme colors (`colors.bg`, `colors.accent`, etc.) or semantic colors (`SEMANTIC_COLORS.dungGlow`)
- Map Figma fonts: sans-serif → `var(--br-font-sans)`, monospace → `var(--br-font-mono)`
- Map Figma spacing to Tailwind spacing classes

### Step 2: Choose Component Layer
- Generic UI (dialog, dropdown, tooltip) → use existing shadcn/ui component
- Interactive surface → `BeetleCard`
- Action button → `BeetleButton`
- Text input → `BeetleInput` / `BeetleTextarea`
- Data display → `StatPill` or a semantic class using `var(--br-font-mono)`

### Step 3: Apply Beetle Aesthetic
- Remove any border radius from Figma design (global zero-radius)
- Convert soft shadows to hard shadows (`Npx Npx 0px 0px`)
- Ensure interaction states follow beetle physics (lift on hover, depress on click)
- Use authored casing and zero letter-spacing; never shrink labels below 12px/16px

### Step 4: Handle Theming
- Use `useTheme()` for any color that should respond to theme changes
- Use `isDarkMode` for dark/light conditional rendering
- Never hardcode background/text/border colors that should be theme-aware

### Step 5: Responsive Considerations
- Test at 768px breakpoint minimum
- Sidebar collapses at mobile — content should fill available width
- Consider `useIsMobile()` for fundamentally different mobile layouts

---

## 12. Existing Design Documentation

Reference these files in `web/portal/src/` for established patterns:

| File | Topic |
|------|-------|
| `BEETLE_PHYSICS_GUIDE.md` | Interaction physics and animation rules |
| `MODAL_DESIGN_SYSTEM.md` | Modal patterns and standards |
| `VISUAL_HIERARCHY_AUDIT.md` | Visual hierarchy analysis |
| `DATA_HIERARCHY_PRINCIPLES.md` | Data display hierarchy |
| `STRAVA_3COL_RULES.md` | 3-column layout rules |

**Note:** There are 30+ additional `.md` files in `src/` from various audits and brainstorms. Many are stale. Treat them as historical context, not current guidance.

---

## 13. Corey's Design System: What We Need

This doc captures what exists. Corey's Figma design system should resolve the open questions and establish:

1. **Canonical color palette** — Define the actual colors for each theme, confirm the 6-theme approach, eliminate hardcoded hex values
2. **Type scale** — 6-8 sizes with clear roles (heading, body, data, caption, etc.)
3. **Component inventory** — Which components are keepers, which need redesign, which are missing
4. **Radius decision** — Pure zero everywhere? Or controlled radius on specific elements?
5. **Spacing system** — Confirm 4px base or define custom scale
6. **Interaction states** — All components: default, hover, active, disabled, loading, error, empty
7. **Responsive strategy** — Mobile priority level, breakpoint behavior for key layouts
8. **Icon/illustration direction** — Continue with lucide-react + emoji? Or add custom iconography?

Once Corey's Figma system is established, this doc should be updated to reflect the **canonical** design system rather than the current state.

---

*Last updated: 2026-02-10*
*Generated from codebase analysis — documents current state, not prescriptive system*
*Section 0 (Known Inconsistencies) is the most important section for Corey to read first*
