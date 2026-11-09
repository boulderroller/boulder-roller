# Figma Design System Workflow

This document describes how the Boulder Roller design system is built, maintained, and translated into code. It covers the full loop: extracting what exists in the codebase into Figma, iterating on the design, and implementing changes back into the app.

---

## The Approach in One Sentence

Extract the existing codebase into Figma as a living design system, explore and refine designs there, then implement changes directly in the codebase with Claude Code.

---

## Why This Stack

The app is built on **shadcn/ui** (Radix UI primitives + Tailwind CSS + CVA). This means:

- **Components are owned files** — not a locked external library. They live in `web/portal/src/components/ui/` and can be freely modified.
- **Design tokens are CSS custom properties** — `--primary`, `--background`, `--border`, etc. Changing a token in one place updates the whole app.
- **This maps cleanly to Figma variables** — a color token change in Figma is a one-line CSS update in code.

---

## The Three-Part Loop

### 1. Generate the Figma design system from existing code

Claude Code reads the codebase (CSS variables, Tailwind config, component files) and builds a Figma file that mirrors what's actually in production:

- **Variable collections** — Primitives (raw colors), Color (semantic Light/Dark aliases), Spacing, Typography — all wired to the real CSS variable names so Dev Mode shows `var(--token-name)`, not hex values
- **Text styles** — the full type scale extracted from actual usage across the codebase, using the real font (Geist)
- **Effect styles** — shadows extracted from portal CSS
- **Components** — built as Figma component sets with variants matching the real React prop API (size, variant, state), bound to the token variables

This is a one-time setup that takes a few sessions. After it's done, Figma reflects production.

### 2. Iterate on the design in Figma

The designer works freely in Figma:

- **Token-level changes** (new color palette, different radius, updated type scale) — change values in the Figma variable collections
- **Component-level changes** (new button styles, card layouts, new variants) — edit component sets directly
- **Screen-level exploration** — compose screens from the component library

Nothing needs to go through code to explore. Figma is the exploration space.

### 3. Implement changes with Claude Code

When a direction is decided, bring it to this session:

- **Token change** → "Update `--primary` to #177865 and remap the dark mode value" → Claude edits `globals.css` (one file, immediate global effect)
- **Component change** → "The button now has a `ghost-terrain` variant that uses the terrain color" → Claude edits `button.tsx` and adds the CVA variant
- **New component** → Describe or show the Figma spec → Claude builds the component file and wires it into the system

The key: Figma is the source of truth for decisions, Claude Code is the implementation path.

---

## What's Been Built (July 2026)

**Figma file:** https://www.figma.com/design/6XQS2Gin1LJCsJENxF761l

### Variable collections (98 variables total)

| Collection | Modes | Count | What's in it |
|---|---|---|---|
| Primitives | Value | 29 | Raw brand colors (terrain, CAL, DUNG, red), ink scale, gray scale, paper scale, chart palette |
| Color | Light / Dark | 36 | Semantic aliases — background, foreground, primary, muted, accent, destructive, border, sidebar, portal brand, chart |
| Spacing | Value | 15 | 9 spacing steps (4–48px) + 6 radius steps (0–9999px) |
| Typography | Value | 18 | Font families (Geist, Geist Mono), 10 size steps, 6 weight steps |

All variables have WEB code syntax set (`var(--token-name)`) so Dev Mode shows real CSS references.

### Text styles (16 total)
`Display/Hero`, `Display/Large` → `Heading/H1–H3` → `Body/Large–XSmall` → `Label/Large–XSmall` → `Mono/Base–XSmall`

All in **Geist** (sans) and **Geist Mono** (monospace), matching what the app actually loads.

### Effect styles (2 total)
`Shadow/Panel` (12px/34px), `Shadow/Sheet` (20px/48px) — from the portal surface layer.

---

### File structure (Phase 2, July 2026)

Page skeleton built and populated:
- **Cover** — title, subtitle, meta line
- **Getting Started** — the three-part loop written out for a new visitor
- **Foundations — Color** — 29 Primitives swatches + 36 semantic tokens shown as Light/Dark pairs, all bound to the real variables
- **Foundations — Typography** — full type specimen, all 16 text styles rendered live
- **Foundations — Spacing & Radius** — proportional bars for the 9 spacing steps, rounded-corner swatches for the 6 radius steps
- **`―――――――――――`** — separator page marking where the component section begins

### Components (Phase 3, July 2026)

All three tiers built — 26 component pages, each token-bound and screenshot-verified, prop APIs matched against the actual `web/portal/src/components/ui/*.tsx` source:

**Tier 1 — Atoms:** Button (18 variants), BeetleButton (12), Badge (4), Avatar (2), Input (4), BeetleInput (2), Label (1), Separator (2), Skeleton (1)

**Tier 2 — Composed:** Card (1 composed layout), Tabs (2 + example), Select (trigger 4 + item 2), Checkbox (3), Switch (2), Radio Group (2), Toggle (12), Tooltip (1)

**Tier 3 — Overlay:** Dialog (1), Sheet (4 sides), Drawer (1), ResponsiveModal (2 breakpoints), Navigation Menu (2 + example), Table (1 composed example), Accordion (2), Alert (2), Sonner (1)

**Token cleanup done alongside:** Phase 1's variable extraction predated a large upstream merge and had drifted — `color/accent` was bound to the wrong primitive (causing a real low-contrast bug on BeetleButton), and 19 other semantic tokens (`background`, `foreground`, `primary`, `secondary`, `muted`, `border`, `sidebar*`, etc.) pointed to slightly-off shades. All corrected to exact-match primitives against current `globals.css`.

**Known gaps, not yet fixed:**
- `color/popover` / `color/popover-foreground` were never extracted as Figma variables — Select content, Navigation Menu content, and Sonner approximate with `card` instead.
- `--destructive` (`#b84d4a`) and `--ring` (oklch) have no exact-match primitive.
- `--switch-background` is a literal hex not yet in the token set.

## What's Next

### Phase 4 — Code Connect
Wire each Figma component to its React counterpart via `.figma.ts` mapping files. Once set up, Figma Dev Mode shows real code snippets (`<Button variant="outline" size="sm" />`) instead of raw values — the developer can copy-paste exact usage.

---

## Day-to-Day Reference

### Making a token change
1. Update the value in the Figma variable collection
2. Tell Claude: "Update `--muted` to X in light mode" → one-line edit in `globals.css`

### Making a component change
1. Redesign the component in Figma
2. Tell Claude what changed (new variant, different padding, updated states)
3. Claude edits the component `.tsx` file to match

### Adding a new component
1. Design it in Figma using the existing token variables
2. Tell Claude: "Build a new `ClimbCard` component matching this spec"
3. Claude creates the file in `web/portal/src/components/ui/`

### Checking what's in the design system
- Variables: Figma Variables panel (left sidebar)
- Text/Effect styles: Figma right panel → local styles
- Components: Component pages in the Figma file (Phase 3+)

---

## Key Files

| File | Purpose |
|---|---|
| `web/portal/src/styles/globals.css` | Semantic CSS tokens (the source of truth for color values in code) |
| `web/portal/src/styles/portal-surfaces.css` | Portal-specific surface tokens and component styles |
| `web/portal/src/styles/portal-spine.css` | Core portal layout and component styles |
| `web/portal/src/components/ui/` | All shadcn/ui components (owned, editable) |
| `web/portal/src/components/ui/button.tsx` | Button — the canonical example of CVA variant pattern |
