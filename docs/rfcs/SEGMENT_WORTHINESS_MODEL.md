# Segment-Worthiness Model

**Status:** RESEARCH COMPLETE — ready for implementation
**Date:** 2026-03-21
**Sources:** Cyclist forum ethnography, Strava documentation, OSM road feature analysis, golden corpus data

## The Central Finding

Segment creation is a **social and experiential** act, not a topographic one. A cyclist does not look at an elevation profile and decide to create a segment. They ride a piece of road, experience something notable (suffering, competition, identity), and codify that experience digitally.

Our detector asks: "Is this a topologically significant elevation feature?"
Cyclists ask: "Is this a perceptually distinct effort on a known road?"

These are different questions. The topological approach works for alpine passes. For 25m urban climbs, perceptual distinctness matters more than topological persistence.

## Seven Motivations for Segment Creation

1. **Competition** — "I want to race you HERE" (dominant motivation, Strava's origin story)
2. **Progress tracking** — "I want to see my fitness on this climb over time"
3. **Cultural codification** — "Everyone calls this The Wall, it deserves a segment"
4. **Suffering recognition** — "This hurt me, and I want that acknowledged"
5. **Landmark formalization** — "From the bridge to the church"
6. **Training structure** — coaches use segments as calibrated workout zones
7. **Territorial marking** — claiming a piece of road as meaningful to your cycling life

## The Three Conditions of Segment-Worthiness

A road is segment-worthy when it has all three:
1. **Effort threshold** — demands enough effort to feel meaningful
2. **Distinctness** — clear boundaries separating it from surrounding terrain
3. **Repeatability** — a cyclist would ride it again and compare performances

## Ten Encodable Insights

### From Cyclist Psychology

1. **Gradient inflection > absolute gradient** — the RATE of gradient change marks perceived climb start, not the gradient itself. Where the road goes 1%→5% in 200m is where cyclists think "I'm climbing."

2. **Intersections are boundary magnets** — cyclists choose intersections, bridges, signs as start/end points. Snap detected boundaries to nearest OSM intersection within ~150m.

3. **3-minute minimum** — meaningful climbing efforts take ≥3 minutes. Segments under 90 seconds are "bumps." (~500m at 5% or 1km at 3%)

4. **Gradient consistency > average gradient** — steady 6% feels more like "a climb" than alternating 2%/10% at the same average. Low gradient variance = more segment-worthy.

5. **Named roads are always segment-worthy** — if a climb has a road name and that road ascends, it's inherently segment-worthy regardless of metrics.

6. **Merge heuristic** — two uphill sections separated by <500m of <2% grade should merge into one climb. If a cyclist can't recover between them, they're one effort.

7. **Summits are unambiguous endpoints** — end where gradient drops below 1% and stays below for >200m.

### From Road Features

8. **Topographic isolation is the #1 predictor** — elevation gain relative to local terrain variance. A 25m rise from flat river trail to plateau is perceptually a "climb." A 25m rise within rolling terrain with 15m oscillations is invisible. Formula: `vert_m / local_elev_stddev > 3 → isolated`.

9. **Pre/post flatness** — if 200m before and after are <1% grade, the climb is perceptually distinct. Computable from ride elevation profile.

10. **Onset steepness** — how quickly gradient ramps up (d(grade)/d(distance)). Wall: >2%/100m (always segmented). Step: 1-2%/100m (usually segmented). False flat: <0.5%/100m (never segmented).

## Anti-Segment Filters

Detections with these properties should be penalized:

1. **Too short** (<500m or <90 seconds) — GPS noise, not a real effort
2. **>25% flat lead-in/tail** — includes approach road a cyclist wouldn't count
3. **Erratic gradient** (>3 sign changes) — rollers, not a climb
4. **Ends mid-slope** (gradient >3% at endpoint) — partial detection
5. **Max gradient never exceeds 5% AND average <3%** — false flat, not a climb

## Gradient Profile Shape Taxonomy

| Shape | Example | Segment-Worthy? |
|-------|---------|-----------------|
| **Wall** (0→10%→0, 200-800m) | Manayunk Wall | Always |
| **Step** (0→4-7%→0, 500m-2km) | Henry Ave, Gorgas | Almost always |
| **Kicker** (long flat→5%→0, 100-300m) | River Road KICKER | Usually (if on named road) |
| **Staircase** (steep-flat-steep-flat) | BMCC Total | Sometimes (whole or individual steps) |
| **Ramp/False flat** (0→2%→0, 1-5km) | Random approach | Rarely |

## Proposed Segment-Worthiness Score

```
Score (0-100) = Core Merit (0-40) + Isolation (0-30) + Shape (0-15) + Road Context (0-15)

Core Merit:
  gradient ≥8%: +30 | ≥5%: +20 | ≥3%: +12 | ≥2%: +5
  vert: min(10, vert_m / 10)

Isolation:
  vert / local_elev_stddev ratio: min(15, ratio × 3)
  pre-climb <1%: +7.5 | <2%: +3
  post-climb <1%: +7.5 | <2%: +3

Shape:
  onset steepness ≥2%/100m: +10 | ≥1%: +6 | ≥0.5%: +3
  gradient consistency bonus: +5 if avg≥4% and vert≥20m

Road Context:
  named road: +5
  paved: +2
  through-road: +3
  intersection boundaries: +5
```

Calibration: Wall=95, Henry Ave=80, Gorgas=85, Shawmont=65, Random roller=20, False flat=12.

## Data Availability

| Signal | Available Now? | Source |
|--------|---------------|--------|
| Vert, gradient, distance, duration | Yes | ClimbPattern |
| Pre/post climb flatness | Yes | RideClimbProfile (tile_samples) |
| Onset steepness | Yes | Computable from smoothed elevation |
| Road name, road class | Yes | road_features table (OSM enrichment) |
| Intersection boundaries | Yes | road_features intersections |
| Paved/through-road | Yes | OSM tags |
| Gradient consistency (stddev) | Yes | Computable from tile_samples |
| Topographic isolation (local stddev) | **No — needs SRTM DEM** | One-time ~30MB download |
| Traffic density | **No — needs vault/ride history** | Available post-alpha |

## Implementation Priority

The highest-impact signals that are available NOW (no SRTM, no Valhalla):

1. **Pre/post flatness** — from existing ride elevation profile
2. **Onset steepness** — from existing smoothed elevation
3. **Gradient consistency** — stddev of gradient within the climb
4. **Road name boost** — from existing OSM enrichment
5. **Intersection boundary snapping** — from existing road_features

These five can be encoded as a new heuristic layer (H10: segment-worthiness) in the chooser, using only data we already compute.
