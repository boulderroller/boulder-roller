# Rank-mark look-dev pipeline

Parametric Blender (4.3, Cycles/Metal) look-dev for the city-standing rank
marks. Tim accepted the rough marks 2026-08-27 ("on board with what we have").
Tracker: boulderroller-v2-dtgj1. Renders: docs/design/renderings/rankmarks/.

Run headless:

    /Applications/Blender.app/Contents/MacOS/Blender -b -P paramset.py   # numbered-band sheet
    /Applications/Blender.app/Contents/MacOS/Blender -b -P podium.py     # podium row (3/2/1)
    /Applications/Blender.app/Contents/MacOS/Blender -b -P crown.py      # single crown mark hero

## Ratified system (as of 2026-08-27)

- Standing, not XP: numbers DESCEND; rank 1 is apex. Demotion immediate, no
  hysteresis.
- One band generator; corner radius is the progression — pure circle at the
  bottom, hardening continuously to square at the top (square = senior, per
  Halo 2). `hard` in MARKS is the corner-radius factor.
- Colorway ladder (bottom → top): iron 6E6A63, bronze 9C6234, green 447A4E,
  cobalt 4F8BC9, plum 7743AB, crimson AC3F3A. Tile carries a 3% tint of its
  band color; corner charge glows in the NEXT band's color (approach signal).
- Finish: bead-blasted matte anodized (granulated micro-grain, satin, never
  glossy — gloss was rejected as "Mardi Gras beads"). Numeral: matte bisque
  ivory E7DDC3, extruded, proud of the band so it casts its own keyline shadow.
- No accent lines. Every ornament must name what it highlights or it dies.
  (The "watermelon" combo was an anecdote, never a spec.)
- Podium tier (ranks 1/2/3) replaces the numeral with an object and leaves the
  band system entirely — each object on its own background, no corner charge:
  1 = crown on pure ink 0F0E0C, 2 = laurel on green-black 141B12,
  3 = faceted cobble on granite 232120. Numbered marks start at 4.
- Post chain is part of the look: fog-glow bloom (threshold 2.2), slight
  contrast grade, vignette.

## Typeface (ratified 2026-08-27)

Archivo Black (OFL, in fonts/ with license) — won the small-proof duel against
Geist Black at 110px: wider stance and open counters keep the digits legible
at row scale. The marks are objects, not text, so house-face continuity with
Geist lost to small-size survivability. SF remains prohibited in exports.

## Podium (ACCEPTED 2026-08-29)

Ranks 1/2/3 as night portraits — full-bleed carved-stone objects on their own
near-black tiles, numbered-mark staging: crown = photo-carved white marble
(drawn heraldic silhouette, mesh-converted, noise-carved, Marble012 skin);
laurel = carved jade (hand-jittered folded leaves, marble surface tinted
green, marble knot); cobble = granite sett (photo displacement, dry dust on
upward faces). All CC0 (pbr/CREDITS.md). Pipeline: podium_night.py; accepted
renders + 110px proofs in docs/design/renderings/rankmarks/nt_*.png.
Living-plant wreaths were tried (PolyHaven scans) and rejected — upright
groundcover reads wrong, and living green breaks the stone family.

## Production work remaining (Phase 2/3 on the bead)

- Full bake: every rank numeral x band, alpha, 1x/2x/3x + sprite manifest for
  portal and iOS; per-mark lighting (sheet rig compromises the band's dark
  quadrant).
- Corner charge baked at 5 intensity steps per band.
- Gold stays out of the marks (earning-only ledger rule).
