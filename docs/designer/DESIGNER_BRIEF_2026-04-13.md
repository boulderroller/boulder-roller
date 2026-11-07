# Boulder Rollers — Brand Designer Brief

**Date:** 2026-04-13
**Contact:** Tim Weigelt (solo founder)
**Supersedes:** `DESIGNER_HANDOFF_JAN2026.md`, `designer-brief-feb5-2026.md` (both contain stale Points-era references — ignore)

---

## What we are

Boulder Rollers is a decentralized cycling platform. Riders earn tokens by completing climbs, discovering tiles, and competing on leaderboards. We financialize geographic routes: stake tokens in a climb, earn yield from everyone else who rides it.

**One-line pitch:** *"That hill you climbed 100 times? Stake in it and earn from everyone else who climbs it."*

**Status:** Live on Solana devnet. Real on-chain completions, real token flows, no simulation.

## The two tokens (this is the whole economy — there is nothing else)

| Token | Role | Verb |
|---|---|---|
| **CAL** | Effort token. Earned from Training Stress Score (TSS) on every ride. Tributed to vaults you cross. | *"Earned 847 CAL"* |
| **DUNG** | Value token. 1B fixed supply. Minted into vault reward pots at 1000 CAL : 1 DUNG, distributed to riders/stakers/legends weekly. | *"Collect 12 DUNG"* |

A **vault** is an on-chain climb or route. Riders earn CAL by riding it, can deposit CAL to stake in it, and collect DUNG rewards from its weekly pot.

> ⚠️ **Important — ignore in any old doc you see:**
> There is **no Points system**. There is **no shadow mode**. There are **no entitlement tiers** or "mode switching." All removed April 2026. If a doc or mockup mentions Points, `PointsCounter`, "pre-TGE points," `ProtocolModeContext`, or "points period" — it's stale. CAL and DUNG are the only currencies.

## Design philosophy (non-negotiable)

- **Fitness-first, not crypto-first.** Riders should feel like they're using a serious cycling product. Crypto shows up naturally as rewards, not as jargon.
- **Clean, minimal, utilitarian.** Not cartoonish. Data visualization quality should be comparable to TrainingPeaks, not Axie Infinity.
- **Light touch on the beetle metaphor.** Dung beetle rolls the ball up the hill — that's the reference. Elegant and memorable, not a mascot plastered everywhere.
- **Differentiation from Strava:** we are an *economy*, not a social network. No kudos, no comments. Leaderboards pay.
- **Zero toggles.** Features appear because you did the thing, not because you flipped a setting.

## Product surfaces you're branding

| Surface | What it is | Audience |
|---|---|---|
| **Portal** (`web/portal/`) | The cycling app. Feed, rides, vaults, portfolio. | Riders |
| **BoulderScan** (`scan.boulderroller.xyz`) | Power-user chain explorer. Shows the protocol piping (CAL tributes, vault flows) that Portal hides. | Power users, protocol nerds |
| **Mobile** | iOS (riders) + Android demo (Solana Mobile Builder Grant). Three tabs: Feed / Vaults / Profile. | Riders |

All three share one identity but have different tones: Portal is warm and rider-focused, BoulderScan is technical and data-dense, Mobile is compact and on-the-go.

## What we need from you

1. **Logo + wordmark** — Boulder Rollers primary, plus lockups for BoulderScan sub-brand.
2. **Color system** — primary, accents, semantic (success/warning/error), dark mode tokens. Exportable as CSS variables.
3. **Typography scale** — display, headline, body, mono (for data). We currently use Cousine for data readouts; open to replacement.
4. **Beetle motif treatment** — how the dung beetle shows up (icon set? loading state? empty states?) without becoming a mascot.
5. **Component kit** — buttons, cards, modals, form controls, data tables, leaderboard rows, vault cards, ride summary cards. Figma library preferred.
6. **Post-ride reveal moment** — this is the "Fortnite gold cascade" of our app. See `docs/design/LANGUAGE_SPEC.md` §"Post-Ride Summary Screen."
7. **Token iconography** — CAL and DUNG glyphs that read at 16px and 256px.

## What to read (all current as of 2026-04-13)

**Authoritative:**
- `CLAUDE.md` — project overview + §"Design Philosophy" at the bottom
- `docs/FRESHEST_SPEC.md` — the single internal source of truth for economics and on-chain behavior
- `docs/design/LANGUAGE_SPEC.md` — UX voice, Deposit/Withdraw/Collect CTAs, what riders see vs what the chain does
- `docs/gitbook/` — public-facing language (intentionally vague on economics)

**Visual exploration history** (reference only — nothing here is blessed):
- `docs/DESIGN_EVOLUTION_CONCEPTS.html`
- `docs/COLOR_SYSTEM_STUDY.html`
- `docs/CURVE_GREY_STUDY.html` + `docs/GREY_FOUNDATION_SWITCHER.html`
- `docs/Boulder_Rollers_Web_Portal_*.html` (Retro, Neo_Retro, Curve_Light, Carbon, Hybrid — range of explorations)
- `docs/2027_INTERFACE_STUDY.html`
- `docs/DUNG_BEETLE_CYCLING_SPEC.html` — beetle metaphor exploration

**Live product (working code, poke at it):**
- `docs/design/Portalalpha-main/` + `docs/design/Boulderrollercopy-main/` — Figma-export React scaffolds. **Warning:** these predate the Points removal — ignore any `PointsCounter`, `calculateTGE(points)`, or "points" balance UI. The visual direction is still useful; the economy model in the code is not.

**Mobile (if in scope):**
- `docs/research/MOBILE_UX_DEEP_RESEARCH.md`

## What's intentionally missing

You're filling these gaps — that's the job:

- No brand book
- No logo source files (we have a placeholder mark only)
- No typography or color tokens document
- No component library
- No illustration style

## Constraints

- **Budget-conscious.** Solo founder, single DigitalOcean droplet infra. Free-tier everything where possible.
- **Apple App Store sensitive.** App Store rejects overtly crypto-framed apps. Brand should read "cycling rewards platform," not "crypto app." Follow Coinbase/Phantom precedent — crypto is present but not loud.
- **No vesting.** 100% token unlock at TGE (Hyperliquid-style). This shapes messaging: no "coming soon" countdowns, no vesting cliffs to illustrate.

---

*Questions? Ping Tim directly. Don't ask an LLM to summarize this doc — read it straight.*
