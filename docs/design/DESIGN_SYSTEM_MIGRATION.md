# Design System Migration Plan

**Status:** Planning
**Owner:** Design + Frontend
**Goal:** Evolve from generic shadcn to a distinctive Boulder Rollers design system

---

## Current State

| Metric | Value |
|--------|-------|
| UI Components | 58 in `components/ui/` |
| Custom Already | 7 (beetle-*, AchievementBadge, LeaderboardTable, PointsCounter, StatPill) |
| Pure shadcn | ~51 (standard Radix + Tailwind) |
| UI Library | shadcn/ui (Radix primitives + Tailwind) |
| Styling | Tailwind CSS with shadcn defaults |
| Icons | Lucide React |
| Charts | Recharts |
| Maps | Mapbox GL |

**The Problem:** shadcn is recognizable. Every indie SaaS looks like this now. Boulder Rollers has brand potential (beetle metaphor, cycling culture, effort-as-currency) that's not reflected in the UI.

---

## Migration Strategy: "Parallel Evolution"

Don't rewrite. Evolve in parallel while shipping features.

```
Week 1-2: Design Foundation (Designer)
    ↓
Week 3-4: Token System + Component Audit (Designer + Dev)
    ↓
Week 5-8: Core Component Reskin (Dev, guided by design)
    ↓
Week 9+: Feature Components (Ongoing)
```

---

## Phase 1: Design Foundation (Designer-Led)

**Duration:** 2 weeks
**Blocker:** No - engineering continues shipping

### Deliverables

1. **Brand Audit Document**
   - What makes Boulder Rollers visually distinct?
   - Beetle metaphor: how literal vs abstract?
   - Cycling culture references: pro peloton? gravel? MTB?
   - Mood: gritty/industrial? clean/premium? playful?

2. **Design Tokens Spec**
   ```
   colors/
     primary, secondary, accent
     semantic: success, warning, error, info
     surfaces: background, card, muted
     text: primary, secondary, muted

   typography/
     font-family (display, body, mono)
     scale (xs through 4xl)
     weights, line-heights

   spacing/
     scale (0-96 or custom)

   radii/
     none, sm, md, lg, full

   shadows/
     sm, md, lg, glow?

   motion/
     duration (fast, normal, slow)
     easing curves
   ```

3. **Component Style Guide (Figma/Sketch)**
   - Button states (default, hover, active, disabled, loading)
   - Input states (default, focus, error, disabled)
   - Card variations
   - Navigation patterns
   - Data visualization style (charts, stats)
   - Empty states, loading states, error states

4. **Key Screens Mockups**
   - Dashboard (the "home base")
   - Ride detail (data-rich, the "wow" moment)
   - Leaderboard (competitive feel)
   - Vault/staking (trust + clarity)
   - Profile/BeetleCard (identity expression)

---

## Phase 2: Token System Implementation

**Duration:** 1-2 weeks
**Dependencies:** Phase 1 deliverables

### Technical Work

1. **Create design token files**
   ```
   web/portal/src/styles/
     tokens/
       colors.css
       typography.css
       spacing.css
       shadows.css
       animations.css
     themes/
       light.css
       dark.css
   ```

2. **Update Tailwind config**
   ```js
   // tailwind.config.js
   export default {
     theme: {
       extend: {
         colors: {
           // Replace shadcn defaults with BR tokens
           primary: 'hsl(var(--br-primary))',
           // ...
         },
         fontFamily: {
           display: ['var(--font-display)', 'sans-serif'],
           body: ['var(--font-body)', 'sans-serif'],
         },
         // ...
       },
     },
   }
   ```

3. **Component audit spreadsheet**

   | Component | Uses | Complexity | Reskin Priority |
   |-----------|------|------------|-----------------|
   | Button | 89 | Low | P0 |
   | Card | 67 | Low | P0 |
   | Input | 45 | Medium | P0 |
   | Dialog | 23 | Medium | P1 |
   | Table | 18 | High | P1 |
   | ... | ... | ... | ... |

---

## Phase 3: Core Component Reskin

**Duration:** 4 weeks
**Approach:** Replace shadcn styles, keep Radix primitives

### Priority Tiers

**P0 - Foundation (Week 5-6)**
High usage, high visibility. Do these first.

- [ ] Button (all variants)
- [ ] Card
- [ ] Input, Textarea
- [ ] Select, Combobox
- [ ] Badge, Tag
- [ ] Avatar
- [ ] Skeleton loaders

**P1 - Interactive (Week 7-8)**
Important for flows but lower frequency.

- [ ] Dialog, Sheet, Drawer
- [ ] Dropdown Menu
- [ ] Tabs
- [ ] Table
- [ ] Toast notifications
- [ ] Form validation states

**P2 - Specialized (Ongoing)**
Feature-specific, can evolve with features.

- [ ] Charts (Recharts theming)
- [ ] Maps (Mapbox style)
- [ ] Leaderboard rows
- [ ] Ride cards
- [ ] BeetleCard display
- [ ] Vault cards

### Implementation Pattern

For each component:

```tsx
// Before: shadcn default
import { Button } from "@/components/ui/button"

// After: same API, new styles
// 1. Update the component file with new classes
// 2. Use design tokens instead of hardcoded values
// 3. Add any new variants needed
// 4. Document in Storybook (optional but recommended)
```

Keep Radix primitives. They handle:
- Accessibility (ARIA, keyboard nav)
- Focus management
- Portal rendering
- Animation coordination

Only change the Tailwind classes and CSS custom properties.

---

## Phase 4: Feature Components

**Duration:** Ongoing
**Approach:** New features get new design; old features get reskinned opportunistically

### New Feature Protocol

1. Designer provides mockup before dev starts
2. Dev builds with new design system tokens
3. No shadcn defaults on new code

### Reskin Backlog

Track pages/features that still have old styling:

- [ ] Settings page
- [ ] Auth flow (login, signup)
- [ ] Onboarding wizard
- [ ] Profile edit
- [ ] ...

Reskin during feature work that touches these areas.

---

## Design System Documentation

### Living Style Guide

Create a `/design-system` route in the portal (dev-only or public):

```
/design-system
  /colors      - Color palette with tokens
  /typography  - Type scale examples
  /components  - Interactive component demos
  /patterns    - Common UI patterns
  /icons       - Icon library
```

### Storybook (Optional)

If the team wants isolated component development:

```bash
cd web/portal
npx storybook@latest init
```

Pros: Isolated dev, visual regression testing
Cons: Another thing to maintain

---

## Decision Points

### Week 2 Checkpoint
- [ ] Brand direction approved by founders
- [ ] Design tokens finalized
- [ ] Key screens approved

### Week 4 Checkpoint
- [ ] Token system implemented
- [ ] Component audit complete
- [ ] P0 components identified

### Week 8 Checkpoint
- [ ] P0 + P1 components reskinned
- [ ] One full user flow feels "new"
- [ ] Decision: Continue or pause for alpha feedback?

---

## What NOT To Do

1. **Don't rewrite from scratch** - 141 components is months of work
2. **Don't switch frameworks** - React + Radix is solid
3. **Don't remove Tailwind** - It's the right tool, just needs better tokens
4. **Don't design in code** - Designer leads, dev implements
5. **Don't block features** - Design system evolves alongside product

---

## Resources

- [Radix Primitives Docs](https://www.radix-ui.com/primitives)
- [Tailwind Design Tokens](https://tailwindcss.com/docs/customizing-colors)
- [Design Tokens Format](https://design-tokens.github.io/community-group/format/)
- [shadcn/ui Source](https://github.com/shadcn-ui/ui) - See what we're replacing

---

## Appendix: Current Component Inventory

Run this to get current component usage:

```bash
# Count component imports
cd web/portal
grep -r "from.*@/components/ui" src --include="*.tsx" | \
  sed 's/.*from.*\/\([^"]*\)".*/\1/' | \
  sort | uniq -c | sort -rn
```

Current shadcn components in use:
- button, card, input, label, select
- dialog, sheet, drawer
- dropdown-menu, context-menu
- tabs, accordion
- table, badge, avatar
- toast, sonner
- form (react-hook-form integration)
- skeleton, spinner
- separator, scroll-area
