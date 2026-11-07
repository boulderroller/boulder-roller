# Mobile Design Constitution — Boulder Roller iOS

**Status: Ratified by Tim 2026-08-09 and merged to main.**

Use this constitution with [MOBILE_TRUTHS.md](../MOBILE_TRUTHS.md) for the native app in [`ios/`](../../ios/README.md).

The complete design system for the native iOS app, extracted from the 2026-08-08
ideation session (Tim + Claude). Full visual record: the surface gallery
artifact — https://claude.ai/code/artifact/98735d7a-8c8a-46ad-b1f6-2ff34796323c
(sixteen screens, hand-drawn at true scale; the build inherits real cartography,
real canon gradients, and live Liquid Glass).

Thesis in one line: **default skin, mastered** — Strava's information bones,
ChatGPT's restraint, Apple's exact tells, and the economy expressed through
luminance and ceremony rather than chrome.

Rider-facing copy follows the rider-experience-first rules in `AGENTS.md` and
`docs/design/PROOF_ECONOMY_PRIMITIVES.md`, and the CTA vocabulary in
`docs/design/LANGUAGE_SPEC.md`. On conflict, the TRUTHS trio wins.

---

## 1. The four constants

Everything measurable derives from four numbers. They are law; deviations are
bugs, not taste.

| Constant | Value | Meaning |
|---|---|---|
| Crown | 40pt | Sheet top corner radius |
| Margin | 20pt | Horizontal page inset |
| Row | 52pt | Standard list row height |
| Body | 17pt | The one text size doing almost all work |

- **Concentric corner rule:** inner radius = outer radius − inset, recursively.
  Sheet crown 40 − margin 20 = card radius 20. Use SwiftUI's concentric corner
  support rather than hand-computing per device.
- Everything sits on the 4pt grid. When something feels off, it is off by a
  multiple of 4.
- Secondary text 11–13pt; section headers are Apple's small tracked uppercase.
- **Open item (device test):** section-header voice — Apple uppercase (current)
  vs ChatGPT sentence-case. One voice wins app-wide; decide on true material.

## 2. Color ledger

The entire palette, exhaustively:

| Color | Value | Meaning |
|---|---|---|
| Chrome/grays | fixed **warm** dark ramp (`#0F0E0C` screen · `#1B1A17` sheet · `#2A2825` card · `#9A9488` / `#6A6660` / `#4E4B46` grays) | Everything, by default — value is luminance, never hue; the hue of the whole ladder is warm charcoal |
| Ink | `#F1EEE8` | Primary text and glyphs — the same temperature as the chrome, so the blue stands alone as the one cool note (recording numerals and the map start dot stay pure white: the outdoor screen and the window keep their own temperature) |
| Cobalt blue | `#5592E2` exactly | *Something to do or see* — the only action color. Chosen over system blue (ratified 2026-08-21): it is the route line's authority on the map and it does not bloom on eyes that halate on electric blue. Thin blue text gets its crispness from weight (semibold), never from chroma |
| Ink at medium weight | — | *A number that matters* — value is luminance, never hue |
| Gold | `#E8C15A` | *Earning events only* — on screen seconds, never a state |

*Ledger history:* neutral Apple-gray ramp + system blue `#0A84FF` from the
2026-08-08 ratification through 2026-08-21; warm ramp + ink + cobalt ratified
by Tim 2026-08-21 after same-luminance side-by-side renders (the decision was
made on the route line and on the 1:1 thin-text zoom; tempered `#3A86E6` was
rejected as a hedge; a second chrome blue was rejected — one blue).

- One blue action per screen (Deposit owns the climb sheet; Record owns the feed).
- Blue also marks live/counting things: route lines, counted relief spans, the
  PR tag, the settlement dot, "−0:07 vs PR".
- Gold appears in exactly one flow: the post-ride reveal (and lingers only on a
  leaderboard-entry splash). It then drains to white forever. No yellow states
  anywhere — no champagne balances, no gold chrome.
- The brand's wider palette lives only *inside ride data* (portal parity), never
  in furniture.

## 3. Typography

- SF Pro for words; **SF Rounded for every numeral** (the Apple Fitness tell).
- `.monospacedDigit()` wherever digits column-align (leaderboards, stats).
- Weight discipline: regular and semibold do nearly everything; Done is semibold
  (Apple's actual weight — a regular Done reads subtly wrong).

## 4. Row grammar

Every list row in the app is one template with slots toggled:

```
[icon] [label] ................ [one trailing value] [›]
```

- **At most one trailing element plus an optional chevron.** Never two values,
  never a dot + value + chevron pile-up.
- Chevron = tappable; value without chevron = read-only fact (CAL balance).
- **No pills/chips species exists.** Where itemization tempts, use names in a
  grammar row (feed footer) or real rows (ride sheet).
- **The card is the tap, the chevron is the hint — no verb links** ("Open ›" is
  banned).
- "See All" lives in the section header, small and gray (gray = navigation;
  blue = action). Apple Music grammar.
- Centered blue text row = grouped action (Deposit on the climb sheet; Collect
  in Settlements). Settings' "Sign Out" species.
- **Filled capsule = transaction commit only**, states the amount, and is held
  (~600ms fill, one deep haptic): "Hold to Deposit 250 CAL". Blue for deposit,
  gray for withdraw — blue in, gray out. The only filled buttons in the app.

## 5. Laws

1. **Ceremony never explains mechanism.** The moment something is felt, the
   screen shows the noun and stops. Education lives in grouped-list footers
   (the sanctioned home: settlement timing, Local Legend term) and in the loop
   itself — the first Sunday receipt is the tutorial. If cohort testing shows
   real confusion, the approved fallback is two words ("Settles Sundays"), never
   a sentence.
2. **Feed whispers, sheet speaks.** Aggregate at feed level (names, one CAL
   figure), itemize in detail surfaces (times, per-climb CAL, "Everything
   between").
3. **Each surface gets exactly one hero.** Feed card → map (*where*). Ride sheet
   → elevation trace (*what it cost*). Climb sheet → composite: map band above
   canon profile (*place + shape = the canon object*).
4. **Monuments don't accordion.** Permanent records never expand in place —
   depth gets its own surface (the leaderboard room, dates carved per time).
5. **Loud once, stone forever.** Earning is celebrated in gold for seconds;
   the record is quiet white-on-gray forever after.
6. **Times are public, money is private.** Profiles show rides, seats, crowns —
   never CAL or DUNG, theirs or yours. Other riders' feed cards show climb
   names without CAL. Your money lives behind the top-bar avatar only.
7. **Pushes, not rooms.** Displacement and settlement arrive as notifications
   deep-linking to surfaces. No notifications tab, no kudos, no social organs —
   we are an economy, not a social network.
8. **No marquee** anywhere except the recording screen's climb band (single
   hero surface, Music-app precedent).
9. **No invented copy.** Screens say their name; taglines, slogans, and any
   rider-facing prose beyond ratified strings are Tim's to write or omit.
   Agents draw empty slots.
10. **Precedent rule.** Before inventing any element, ask *where has Apple
    already solved this?* (Fitness award splashes, Music "See All", Settings
    action rows, Apple Pay amount-in-button, Workout metrics screen). Every
    precedent adopted tonight made the page both more beautiful and more ours.
11. **Two truth standards** *(ratified by Tim 2026-08-18)*. The economy and
    the diary hold different evidence bars, and neither may leak into the
    other.
    - **Economic surfaces** (CAL, TSS, boards, settlements, attestation)
      keep strict abstention: dash or absence, never a derived or fallback
      value. Frozen economic figures are never recomputed for display.
    - **Reading surfaces** (ride pages, climb efforts, splits, profiles)
      show the best honest arithmetic the evidence allows: speed derived
      from the recorded track, one climbing number per ride
      (DEM-corrected wherever any correction exists, device elevation
      otherwise — `shownElevationM`), VAM and effort speed from canon
      identity and the clock. Derivation is division over recorded
      evidence; modeled estimation (invented power, interpolated effort)
      remains forbidden everywhere.
    - **Stable anatomy.** A surface with any footing keeps its full
      skeleton in fixed order and degrades *inside* sections; sections
      never vanish to signal missing data (one effort is a dot, not an
      absent chart). A surface with no footing renders no empty object —
      this law and the no-empty-objects rule meet at "footing," never
      conflict.
    - The rider never adjudicates provenance: one number per concept on
      the surface, provenance kept underneath (`elevationCorrection`,
      device summaries) for the day it matters.

## 6. Naming

| Rider-facing | Never | Why |
|---|---|---|
| Leaderboard | "Record Board" | collides with the Record button; internal docs may keep protocol vocabulary |
| Settlements | "Receipts" | ratified 2026-08-08 |
| Climbs | "Segments" | Strava-era term, prohibited |
| Seats / Crowns | — | profile stat vocabulary (board positions / #1s) |
| Deposit / Withdraw / Collect | stake/unstake/harvest/claim | per LANGUAGE_SPEC |

Zero-start copy discipline: no "rent", "yield", "income", "earnings" framing;
"earn DUNG every settlement week" is the ceiling. No chain names in rider copy.

## 7. The sixteen surfaces

**Arrival**
1. **Onboarding** — wordmark, one blue profile line as decoration, Sign in with
   Apple (Apple-mandated prominence), email, invite-code line. No tagline.

**The loop at rest**
2. **Feed** — the app's one screen. Chronological ride cards (header / title /
   x·y·z stat trio / full-bleed map / footer: mountain icon + climb names +
   CAL). Blue settlement dot on the top-bar avatar. Truncation Apple-style
   ("+2"), never wraps, never marquees. Glass record pill floats bottom-center
   (fallback if it fails on device: bottom toolbar — one-line swap).
3. **Avatar sheet** — the ChatGPT settings pattern verbatim: identity header;
   Riding group (CAL balance · Settlements · Sensors · Units); Account group.
4. **Ride sheet** — Strava's mobile anatomy at 95% (header, map, stat rows,
   relief, climb list); the 5% is ours: counted spans tinted blue, canon grade
   subtitles, per-climb CAL + "Everything between". Phase 2: scrub-the-relief
   (finger on chart drives a dot on the map with live power/HR/gradient — the
   "we mean business" moment; Strava mobile can't).
5. **Climb sheet** — composite hero (map band / canon profile), Leaderboard card
   (top 3 + You pinned, See All in header), Vault card (Deposited / Your
   position / Local Legend / blue Deposit action row), two-sentence footer,
   ODbL attribution ("Climb data © OpenStreetMap contributors" — legally
   required on canon surfaces, doubles as provenance flex).
6. **Leaderboard room** — all ten inscriptions with dates set; your row
   highlighted with racer math ("PR today"); future: tap rider → profile,
   long-press → time provenance (attestation status).
7. **Rider profile** — avatar, name, neighborhood; Rides/Seats/Crowns trio;
   Leaderboards card; recent rides. Own name opens the same page + pencil.
8. **Sensor pairing** — stock Bluetooth-settings choreography (My Devices with
   type subtitles + "Connected" in gray; Available with blue Pair; Searching…).
   Per-device attestation status lands here when hardware signing does.
9. **Map viewer** — full-bleed dark map, glass ✕, bottom glass card (name +
   canon facts + gray chevron; whole card taps into the climb sheet).

**The money room**
10. **Deposit sheet** — Uniswap's giant-numeral input, card stack reading as a
    sentence, no gas/approve/slippage anywhere (Balance eats it — the absence
    is the feature), footnote: counts from next settlement week. Blue held
    capsule stating the amount.
11. **Withdraw sheet** — mirror, gray capsule. Footnote: "Pending DUNG is
    collected to your settlements first." Backed by the composed
    collect-before-unstake Balance action (backend ask; see resume strategy).
    Exit-fee line appears here if/when the 0.5% fee ships.
12. **Settlements** — Uncollected card with Collect action; History in gray.
    Luminance splits pending from past.

**In motion**
13. **Recording** — Apple Workout's bones: black, giant rounded numerals,
    tracked labels, pause circle. Plus: sensor provenance row (paired devices,
    live dot) and the climb band — canon recognizes the hill, shows live grade,
    progress, and delta vs PR in blue. Edge rule from platform: power is the
    hero numeral.
14. **Reveal, beat one** — gold CAL count-up, label "CAL" (gold already means
    earned). Paged like Fitness awards, dots + gray Continue pill.
15. **Reveal, beat two (conditional)** — leaderboard entry splash: "LEADERBOARD"
    eyebrow, giant gold rank, climb name, "4:41 · was 4:44". No economy
    sentence — Sunday says it. Skipped entirely on ordinary rides (ceremony
    proportional to consequence).
16. **Reveal, beat three** — summary handing ceremony back to ledger: stat trio,
    gold checks with times, "Tribute · 31 CAL" as a noun row, Done → feed.

**States, not rooms** (design at build time): first-run empty feed (invitation,
not apology), processing beat ("Reading your ride…"), share-sheet GPX/FIT import
joining the same pipeline. Vault creation stays portal-side day-one.

**Deferred with rationale:** explore-the-canon map page — first post-launch
surface, not day-one; discovery is the portal's job until the loop is proven.

## 8. Interaction tier

- Springs on sheet arrival; haptic detents crossing round numbers in the
  numeral input; Max tick-and-settle.
- Hold-to-commit on both money capsules (~600ms, deep haptic at completion).
- Reveal sequencing: gold count-up → (stone splash + deep haptic) → checks tick
  in → tribute fades → Continue. Ordinary rides run one beat shorter.
- Liquid Glass strictly on the chrome layer (record pill, top bar, toolbars) —
  never on content. Apple's own rule, and ours.
- Respect Reduce Motion: reveal degrades to crossfades; no particle drift.

## 9. Build notes

- Target iOS 26 / Xcode 26.x. Stock components adopt Liquid Glass on recompile;
  the theme file is the four constants + the color ledger and little else.
- Maps: MapKit snapshots in a custom dark style for card bands (static, cheap),
  full MapKit on the viewer. The gallery's street grids are placeholders.
- Canon profiles render real gradient data — terrain personality is the beauty;
  no smoothing.
- Dynamic Type: the constitution's sizes are the `large` (default) anchors;
  scale with the system, test at accessibility sizes.
- Parser: the real `workout-parse` crate over UniFFI (spike bead
  `boulderroller-v2-8mp46`); device hash must equal backend hash.

## 10. Open items

1. Section-header voice: uppercase vs sentence-case (device test, one wins).
2. Record pill vs bottom toolbar (feel both on device).
3. Composed collect-before-unstake Balance action (backend bead when lane opens).
4. Reveal-confusion fallback ("Settles Sundays", two words max) — only if cohort
   testing demands it.
5. Composite hero beauty verdict — real cartography + real gradient on device;
   fallback is profile-solo + "View map" row (one-hour swap).
