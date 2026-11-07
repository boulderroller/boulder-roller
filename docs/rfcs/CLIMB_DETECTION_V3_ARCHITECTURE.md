# RFC: Climb Detection v3 — Persistence + Road Fusion

**Status:** Draft
**Author:** Claude (with Gabe)
**Date:** 2026-03-17
**Supersedes:** v2 persistence-only detector

---

## 1. Problem Statement

The v2 persistence detector produces topologically correct climb candidates from
barometric elevation data. However, effort boundaries (where the user is told the
climb starts/ends) are determined by gradient analysis on the 1D elevation signal,
which has no knowledge of roads, intersections, or infrastructure.

This produces five classes of errors:

| # | Problem | Root Cause |
|---|---------|------------|
| 1 | Bridge/tunnel artifacts | Elevation ≠ terrain when on infrastructure |
| 2 | Merged climbs at intersections | Valley between climbs < noise gate |
| 3 | Boundaries at wrong locations | Gradient threshold ≠ road feature |
| 4 | First-rep run-in on races | Approach from different road included |
| 5 | Altimeter startup drift | Sensor calibration ≠ real elevation |

Industry survey: every pure-elevation system (Garmin ClimbPro, Strava auto-segments)
exhibits these same failures. Every system that solves them (Hammerhead Karoo,
ClimbFinder, Tour de France categorization) uses road network data or human curation.

## 2. Architecture

### 2.1 Design Principles

1. **Persistence generates, road network structures, fusion decides.**
   Neither signal alone is sufficient. Persistence finds elevation features that
   road data would miss (unnamed trails, multi-road climbs). Road data provides
   context that elevation cannot (bridges, intersections, road names).

2. **Road features are tiebreakers, not magnets.**
   If the climb naturally flattens 30m before a stop sign, the boundary is at the
   flattening — not dragged to the stop sign. Road features matter when the
   gradient is ambiguous (could reasonably end at several points). A few meters
   of trim past a road feature is preferred to extending to reach one.

3. **Signatures are sacred.**
   The 64-byte DCT-II signatures are computed from canonical (birth/death) bounds,
   NOT effort bounds. Road-aware boundary adjustments change effort bounds only.
   Vault matching is unaffected.

4. **Graceful degradation.**
   If no road data is available (new region, OSM gaps), the system falls back to
   v2 behavior (gradient-walk boundaries). Road enrichment improves quality but
   is never required.

### 2.2 Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         RIDE UPLOAD                                 │
│                                                                     │
│  FIT/GPX file                                                       │
│      │                                                              │
│      ▼                                                              │
│  ┌──────────────────────────────┐                                   │
│  │  RUST PARSER (workout-parse) │                                   │
│  │                              │                                   │
│  │  1. Parse file → 1Hz samples │                                   │
│  │     (t, lat, lon, elev,      │                                   │
│  │      power, hr, speed)       │                                   │
│  │                              │                                   │
│  │  2. GPS → H3 tiles (res 10)  │                                   │
│  │                              │                                   │
│  │  3. Persistence homology     │                                   │
│  │     → (valley, peak) pairs   │                                   │
│  │     → canonical bounds       │                                   │
│  │     → 64-byte signatures     │                                   │
│  │                              │                                   │
│  │  4. Menger curvature         │◄── NEW: junction detection        │
│  │     → junction indices       │    R < 30m + speed dip            │
│  │       (8-12 per ride)        │                                   │
│  │                              │                                   │
│  │  5. Effort boundary trim     │                                   │
│  │     → gradient walk          │                                   │
│  │     → junction-aware snap    │◄── NEW: prefer junction when      │
│  │                              │    gradient is ambiguous           │
│  │                              │                                   │
│  │  OUTPUT: Vec<ClimbV2>        │                                   │
│  │    - canonical bounds        │                                   │
│  │    - effort bounds           │                                   │
│  │    - signature               │                                   │
│  │    - junction_at_start: bool │◄── NEW                            │
│  │    - junction_at_end: bool   │◄── NEW                            │
│  │    - nearby_junctions: []    │◄── NEW                            │
│  └──────────┬───────────────────┘                                   │
│             │                                                       │
│             ▼                                                       │
│  ┌──────────────────────────────┐  ┌───────────────────────────┐    │
│  │  PYTHON: Road Enrichment     │  │  SUPABASE: road_features  │    │
│  │  (road_enrichment.py)        │◄─┤                           │    │
│  │                              │  │  - intersections (50-80K) │    │
│  │  For each ClimbV2:           │  │  - bridges (~500-1K)      │    │
│  │                              │  │  - tunnels (~50-100)      │    │
│  │  a. Collect H3 tiles in span │  │  - road segments (15-25K) │    │
│  │  b. Batch query road_features│  │                           │    │
│  │  c. Bridge overlap check     │  │  Indexed by H3 tile       │    │
│  │  d. Intersection proximity   │  │  Philly metro: ~100K rows │    │
│  │  e. Road name attribution    │  │  Cost: $0 (Supabase free) │    │
│  │  f. Suppression decision     │  └───────────────────────────┘    │
│  │  g. Split decision           │                                   │
│  │  h. Boundary refinement      │                                   │
│  │                              │                                   │
│  │  OUTPUT: Vec<EnrichedClimb>  │                                   │
│  │    - road_name               │                                   │
│  │    - is_bridge_artifact      │                                   │
│  │    - suppressed (bool)       │                                   │
│  │    - split_at (Option<idx>)  │                                   │
│  │    - refined_start           │                                   │
│  │    - refined_end             │                                   │
│  │    - boundary_source         │                                   │
│  │      (gradient | junction |  │                                   │
│  │       intersection | road_   │                                   │
│  │       name_change)           │                                   │
│  └──────────┬───────────────────┘                                   │
│             │                                                       │
│             ▼                                                       │
│  ┌──────────────────────────────┐                                   │
│  │  PATTERN ENGINE              │                                   │
│  │  (pattern_engine.py)         │                                   │
│  │                              │                                   │
│  │  - Vault signature matching  │  (unchanged — uses canonical      │
│  │  - Abstention evaluation     │   bounds, not effort bounds)      │
│  │  - Decision trace logging    │                                   │
│  │  - Economic eligibility      │                                   │
│  └──────────────────────────────┘                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.3 Decision Logic: Boundary Placement

The boundary placement algorithm runs for each ClimbV2 candidate:

```
INPUT:
  - canonical_start, canonical_end  (from persistence)
  - effort_start, effort_end        (from gradient walk + junction snap)
  - osm_intersections[]             (from road_features, near start/end)
  - osm_bridges[]                   (from road_features, overlapping climb)
  - road_names[]                    (from road_features, along climb)

STEP 1: BRIDGE SUPPRESSION
  bridge_tiles = climb_tiles ∩ bridge_tiles
  bridge_pct = |bridge_tiles| / |climb_tiles|
  IF bridge_pct > 0.6 AND vert_m < 50 AND time_s < 180:
    → SUPPRESS (abstain: "INFRA:bridge_overlap")
    → STOP

STEP 2: INTERSECTION SPLITTING
  FOR each intersection I in the climb's interior:
    IF gradient at I < 1.5% over ±30 samples:       // flat section
      AND road_name_before(I) ≠ road_name_after(I):  // different roads
      AND each sub-climb has vert ≥ 15m:              // both halves viable
        → SPLIT at I
        → Recurse on each half

STEP 3: START BOUNDARY REFINEMENT
  gradient_start = effort_start  (from gradient walk in Rust)

  // Find nearest OSM intersection within search window
  search_lo = canonical_start
  search_hi = canonical_start + 0.4 * span
  nearby = osm_intersections in [search_lo, search_hi]
         + road_name_changes in [search_lo, search_hi]

  IF nearby is empty:
    → USE gradient_start                    // no road features, keep gradient walk

  ELSE:
    best_candidate = nearest to gradient_start

    IF |best_candidate - gradient_start| <= 5 samples:
      → USE best_candidate                 // close enough, snap to road feature

    ELIF gradient is ambiguous at gradient_start:
      // "ambiguous" = gradient between 0.5% and 2.0% at the walk point
      → USE best_candidate                 // road feature breaks the tie

    ELIF best_candidate < gradient_start:
      // Road feature is BEFORE gradient walk result (less trimming)
      // Only use if gradient at best_candidate is still > 0.5%
      IF gradient_at(best_candidate) > 0.5%:
        → USE best_candidate
      ELSE:
        → USE gradient_start

    ELSE:
      // Road feature is AFTER gradient walk result (more trimming)
      // Prefer tighter trim: use road feature (trim a few meters past it)
      → USE best_candidate + 3 samples     // trim slightly past the feature

STEP 4: END BOUNDARY REFINEMENT
  (mirror of Step 3, walking backward from canonical_end)

  Additional rule: summit-seeking
  IF smoothed[effort_end] < max(smoothed[effort_start..canonical_end]):
    // The gradient walk stopped before the actual summit
    summit_idx = argmax(smoothed[effort_start..canonical_end])
    → EXTEND effort_end to summit_idx (or nearest road feature past summit)

STEP 5: ROAD NAME ATTRIBUTION
  road_samples = map each sample to nearest road_segment by H3 tile
  name_counts = count occurrences of each road name
  climb.road_name = most_common(name_counts)
  // Future: "Rock Hill Rd → Bryn Mawr Ave" for multi-road climbs

STEP 6: RECORD BOUNDARY SOURCE
  climb.boundary_source = {
    start: "gradient" | "junction" | "intersection" | "road_name_change",
    end:   "gradient" | "junction" | "intersection" | "summit" | "road_name_change",
    confidence: 0.0..1.0
  }
```

### 2.4 Menger Curvature Junction Detection (Rust)

Replaces the failed `detect_turns()` (35° angular threshold → 75 detections).

```
FOR each sample i in [window..N-window]:
  p1 = samples[i - window]    // 5 samples back
  p2 = samples[i]             // current
  p3 = samples[i + window]    // 5 samples ahead

  a = haversine(p1, p2)
  b = haversine(p2, p3)
  c = haversine(p1, p3)
  area = triangle_area(p1, p2, p3)

  IF area < 0.1: SKIP         // collinear (straight road)

  radius = (a * b * c) / (4 * area)

  IF radius < 30m:            // tight turn (junction-like)
    angle = angular_diff(bearing(p1→p2), bearing(p2→p3))
    speed = haversine(p1, p3) / (t3 - t1)

    IF angle > 25° AND speed > 1.5 m/s:
      candidates.push(i, radius, angle, speed)

DEDUP: within 15-sample windows, keep smallest radius

CLASSIFY:
  R < 30m AND speed_dip > 40%  → StrongJunction
  R < 30m AND speed_dip < 40%  → SharpCurve (switchback)
  R < 50m AND speed_dip > 60%  → ProbableJunction (light/stop)
  R > 50m                      → RoadCurve (ignore)
```

Expected: 75 detections → 8-12 junctions per ride.

## 3. Data Model

### 3.1 Supabase: road_features

```sql
CREATE TABLE road_features (
    id          BIGSERIAL PRIMARY KEY,
    tile_id     TEXT NOT NULL,              -- H3 res 10
    feature_type TEXT NOT NULL,             -- 'intersection' | 'bridge' | 'tunnel' | 'road_segment'
    osm_id      BIGINT NOT NULL,
    name        TEXT,                       -- road name (nullable for intersections)
    highway_class TEXT,                     -- 'primary' | 'secondary' | 'tertiary' | 'residential' | ...
    lat         DOUBLE PRECISION NOT NULL,
    lon         DOUBLE PRECISION NOT NULL,
    road_names  TEXT[],                     -- for intersections: names of meeting roads
    degree      SMALLINT,                   -- for intersections: number of connecting roads
    tags        JSONB,                      -- raw OSM tags for future use
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_road_features_tile ON road_features(tile_id);
CREATE INDEX idx_road_features_type_tile ON road_features(feature_type, tile_id);
```

### 3.2 ClimbV2 Extensions (Rust)

```rust
pub struct ClimbV2 {
    // ... existing fields ...

    // NEW: junction context from Menger curvature
    pub junction_at_start: bool,
    pub junction_at_end: bool,
    pub nearby_junctions: Vec<JunctionInfo>,
}

pub struct JunctionInfo {
    pub sample_idx: usize,
    pub radius_m: f64,           // Menger curvature radius
    pub angle_deg: f64,          // heading change
    pub speed_dip_ratio: f64,    // speed_at / speed_context
    pub classification: JunctionType,
}

pub enum JunctionType {
    StrongJunction,     // R < 30m + speed dip > 40%
    ProbableJunction,   // R < 50m + speed dip > 60%
    SharpCurve,         // R < 30m, no speed dip (switchback)
}
```

### 3.3 EnrichedClimb (Python)

```python
@dataclass
class EnrichedClimb:
    climb: ClimbV2                      # original detection
    road_name: Optional[str]            # attributed road name
    road_names_sequence: list[str]      # ordered road names along climb
    bridge_pct: float                   # fraction of climb on bridge tiles
    is_bridge_artifact: bool            # bridge_pct > 0.6 and short/low
    suppressed: bool                    # should not create vault
    suppression_reason: Optional[str]   # "INFRA:bridge_overlap" etc.
    split_candidates: list[SplitCandidate]
    refined_start: int                  # adjusted effort start index
    refined_end: int                    # adjusted effort end index
    start_boundary_source: str          # "gradient" | "intersection" | ...
    end_boundary_source: str
    start_intersection: Optional[dict]  # OSM intersection details
    end_intersection: Optional[dict]
    confidence: float                   # 0-1, how much road data contributed
```

## 4. Implementation Phases

### Phase A: Menger Curvature in Rust (hours)
- Replace `detect_turns()` with `detect_junctions()` using circumradius
- Add speed-dip classification
- Thread through existing `turn_indices` parameter as `junction_indices`
- Add `JunctionInfo` to `ClimbV2` output
- Validate: 75 → ~10 detections on test rides

### Phase B: OSM Feature Extraction (1-2 days)
- Script: download Philly metro PBF, extract intersections + bridges + road segments
- Output: CSV → load into Supabase `road_features` table
- Tools: pyosmium or osm2pgsql + PostGIS (local, one-time)
- Coverage: ~30km radius from City Hall, ~100K features

### Phase C: Road Enrichment Service (2-3 days)
- `backend/app/services/road_enrichment.py`
- Batch query `road_features` by H3 tiles for each ride's climbs
- Bridge suppression logic
- Road name attribution
- Intersection proximity for boundary candidates
- Wire into `pattern_engine.py` after detection, before vault matching

### Phase D: Boundary Fusion (2-3 days)
- Implement Section 2.3 decision logic in `road_enrichment.py`
- Intersection-based splitting for merged climbs
- Boundary refinement with road features as tiebreakers
- Summit-seeking for end boundaries
- `boundary_source` tracking for decision traces

### Phase E: Validation & Tuning (1-2 days)
- Visual review tool: add junction markers, road features, boundary sources
- Test 4 key rides + 20-ride Philly sample
- Corpus regeneration + scorecard comparison
- Tune thresholds (bridge_pct, search window, ambiguity range)

## 5. Risks

| Risk | Mitigation |
|------|-----------|
| Signature instability | Signatures use canonical bounds, not effort bounds. Unaffected. |
| OSM data gaps | Graceful degradation to gradient-walk boundaries |
| Intersection noise (driveways, parking lots) | Filter to degree ≥ 3 or highway_class ≥ tertiary |
| Bridge detection false positives (riding under a bridge) | Elevation check: bridge suppression only if elevation RISES over bridge tiles |
| Performance (road_features query per ride) | Batch query by tile set, <50ms for typical ride |

## 6. Success Criteria

Applied to the 4 test rides from user review:

| Ride | Expected Result |
|------|----------------|
| 5682409188 | Climb #3 (Rock Hill + Bryn Mawr) split at Conshohocken State Rd intersection |
| 1573845543 | Chamounix first rep: start boundary at intersection where approach road meets climb road |
| 10763959 | Bridge climbs (#1, #8, #10, #11) suppressed. Shawmont starts at fork, Cresheim ends at road end. |
| 3567898592 | Port Royal: clean boundaries at road features |

Aggregate: impossible_vam_count → 0. No regression in significant climb count (±5%).
