# Boulder Rollers - Tile-Based Attestation Architecture

**Version:** 1.0
**Date:** December 2025
**Status:** HISTORICAL — superseded tile-first architecture

Current canon-first Climb identity and attestation authority is [PROTOCOL_TRUTHS.md](PROTOCOL_TRUTHS.md), with build decisions in [CANON_BUILD_DECISIONS.md](design/CANON_BUILD_DECISIONS.md).

> ⚠️ **PARTIALLY OUTDATED**: References to "scoring patterns" with CAL are from an
> earlier model. The current model: **CAL is earned from TSS on rides**, automatically
> tributed to vaults crossed. No manual scoring flow. See `docs/TOKENOMICS_V2.md`.

---

## Executive Summary

Boulder Rollers replaces Strava's polyline-segment-matching architecture with a **tile-based attestation system**. GPS points project to H3 hexagonal cells, patterns emerge from tile sequences, and competitive structures derive from statistical fields over tiles—not user-defined routes.

### Why This Matters

1. **IP Differentiation**: No polyline matching = no Strava patent concerns
2. **Emergent Geography**: Arenas and Flows discover themselves from usage data
3. **Privacy by Default**: Tile aggregation naturally obscures exact routes
4. **Simpler Architecture**: O(N) tile projection vs complex segment matching

---

## 1. Architecture Philosophy

### Two-Layer System

**Layer 1: Rich Data Substrate (Complex, Hidden)**
- Fine-grained H3 tiles (res 10-11, ~50-100m)
- Full attestation history with metrics
- Emergent Arenas, Flows, difficulty fields
- Dynamic tile merging/refinement based on usage

**Layer 2: Simple User Surface (Minimal, Visible)**
- "Today's Climb in Boulder North"
- "Ride Complete - You hit the target"
- "Boulder Climb Rankings"
- No mention of tiles, attestations, flows

**Mantra**: "Map is huge; menu is tiny."

### Key Principles

1. **Post-hoc, not live** - System ingests completed activity files, no real-time tracking
2. **Patterns, not segments** - Recognize effort shapes, not polyline matches
3. **Emergent geography** - Arenas and Flows derive from data, not hand-authored
4. **Simple, explicit rules** - Small number of clearly defined rules
5. **Separation of concerns** - Heavy data off-chain, minimal on-chain surface
6. **Optional participation** - Scoring/rewards are optional layers

---

## 2. Tile Resolution Math

### Design Constraints

For tile edge length `L`:
```
L >= 5 × σ (GPS noise ~5m)     → L >= 25m (noise robustness)
L >= 2 × w (road width ~8m)    → L >= 16m (lateral stability)
L <= R / 10 (feature length)   → L <= 100-300m (preserve shape)
```

**Sweet spot for road cycling: 50-100m tiles (H3 res 10-11)**

### Multi-Scale Strategy

| Resolution | Cell Size | Use Case |
|------------|-----------|----------|
| Res 6-7 | ~3-7 km | City/region stats |
| Res 8 | ~500m | Neighborhood |
| Res 9 | ~200m | Arena level |
| Res 10 | ~50-100m | **Default for cycling** |
| Res 11 | ~25m | Flow detection |
| Res 12 | ~10m | High precision |

### Adaptive Refinement
- Merge underused tiles (no rides, no effort)
- Track high-variation tiles (multiple routes through same cell)
- Per-arena tuning as data accumulates

---

## 3. Core Data Model

### Primitives

| Internal Term | User-Facing |
|---------------|-------------|
| Tile | (hidden) |
| Arena | "Climb zones", "Areas near you" |
| Flow | "Popular lines" |
| RideTemplate | "Today's Climb", "Easy Spin" |
| RidePlan | "You picked this ride" |
| RideResult | "Ride Complete" |
| Attestation | (hidden - signed proof) |
| Ladder | "Boulder Climb Rankings" |
| CAL | "Daily budget" |

### Activities

```typescript
interface Activity {
  activityId: string;
  wallet: string;
  source: "garmin" | "strava" | "whoop" | "manual";
  startTime: string;
  endTime: string;
  distance_m?: number;
  duration_s: number;
  totalAscent_m?: number;
  canonicalStreamRef: string;  // FK to streams
  tilesRef: string;            // FK to tile_samples
}
```

### Tile Samples

```typescript
interface ActivityTileSample {
  id: string;
  activityId: string;
  t: number;           // seconds since start
  tileId: string;      // H3 index
  elevation_m?: number;
  power_w?: number;
  heartRate_bpm?: number;
  speed_mps?: number;
}
```

### Arenas

```typescript
interface Arena {
  arenaId: string;
  name: string;
  description?: string;
  tiles: Set<string>;     // Set of H3 tile IDs
  regionHash: string;     // Hash of tile set for integrity
}
```

---

## 4. Pattern Types

### 4.1 ClimbPattern

**Purpose**: Capture "I did a substantive climb in this area"

**Eligibility**:
- All samples in window have `tileId ∈ Arena.tiles`
- `vert_gain >= CLIMB_VERT_MIN` (300-600m)
- `max_drop <= CLIMB_DROP_TOLERANCE` (20-30m)
- `CLIMB_TIME_MIN <= duration <= CLIMB_TIME_MAX` (5-60 min)

**Selection**: Maximum vert, then minimum time

```typescript
interface ClimbPattern {
  id: string;
  activityId: string;
  arenaId: string;
  vert_m: number;
  time_s: number;
  avg_power_w?: number;
  w_per_kg?: number;
  avg_hr?: number;
  startTimeOffset_s: number;
  endTimeOffset_s: number;
}
```

### 4.2 SteadyPattern

**Purpose**: Capture "I held a steady aerobic effort"

**Eligibility**:
- `duration >= STEADY_WINDOW_MIN` (20-60 min)
- Intensity in Z2-Z3 band for most of window
- Variability below threshold

**Selection**: Longest duration or highest workload

```typescript
interface SteadyPattern {
  id: string;
  activityId: string;
  duration_s: number;
  avg_power_w?: number;
  np_power_w?: number;
  avg_hr?: number;
  intensityIndex?: number;
  startTimeOffset_s: number;
  endTimeOffset_s: number;
}
```

### 4.3 ExplorationPattern

**Purpose**: Capture "I went somewhere new or unusual"

**Eligibility** (any of):
- `new_tiles_wallet / total_tiles >= 0.2` (20% new to rider)
- `new_tiles_global >= N` (new to system)
- `night_minutes >= M` (unusual time)

```typescript
interface ExplorationPattern {
  id: string;
  activityId: string;
  newTiles_wallet: number;
  newTiles_global?: number;
  nightMinutes?: number;
  startTimeOffset_s: number;
  endTimeOffset_s: number;
}
```

---

## 5. Core Flow: Detect → Display → Score

```
Ride Upload
    ↓
Pattern Detection (automatic, free)
    ↓
├── ClimbPattern(s) detected
├── SteadyPattern detected
├── ExplorationPattern detected
    ↓
All patterns stored, displayed, feed Beetle Cards passively
Leaderboards updated (no CAL required to compete)
    ↓
User sees: "Nice ride! 450m climb, 35min steady, 12 new areas explored"
    ↓
User decides: "Score my climb for DUNG" (opportunistic upgrade)
    ↓
Scoring (CAL-gated, DUNG reward)
    ↓
CAL consumed, DUNG minted, on-chain attestation
```

**Key principle**: CAL is the ONLY limiter on scoring
- No "one pattern per activity" constraint
- Score any pattern from any activity if you have CAL
- CAL cost varies by pattern type/intensity

---

## 6. CAL System

### Daily Budget
- 2200 CAL/day baseline (metabolic framing)
- v1: Fixed for all users
- Future: Personalization by weight/age/training load

### CAL Cost Formula (v1)
```python
def cal_cost(pattern):
    if pattern.type == "CLIMB":
        return int(pattern.vert_m * 0.5)  # ~150-300 CAL
    elif pattern.type == "STEADY":
        return int(pattern.duration_s / 60 * 10)  # 10 CAL/min
    elif pattern.type == "EXPLORATION":
        return int(pattern.new_tiles_wallet * 5)  # 5 CAL/tile
```

### Scoring Flow
1. User selects pattern to score
2. Check CAL availability
3. Compute DUNG reward
4. Consume CAL, mint DUNG
5. Update Beetle Card

---

## 7. Competition Model

### Effort-Based Primary (v1)

**Why Effort-Based is Better Than Strava**:
- Strava rewards absolute speed (favors bigger riders, better aero)
- We reward relative effort (W/kg, suffering, training adaptation)
- A 60kg rider doing 5.0 W/kg beats an 80kg rider doing 4.0 W/kg
- Rewards FITNESS, not just power

**v1 Leaderboards**:
- "Best effort in Boulder North today"
- Ranking metrics: W/kg, effort score, vert/time ratio
- Route-agnostic: different routes through same Arena compete fairly

### Time-Based Flows (v2)

**PTS Seeding Strategy**:
- PTS period: effort-based only, collect all tile sequences
- Post-PTS: analyze sequences, identify stable Flows
- Early riders become the cartographers
- Flow = tile sequence with statistical stability

**Flow Detection**:
- Store tile sequences at res 11 (~25m)
- Sequence similarity via edit distance or Jaccard
- Flow promotion when N riders take same sequence with M% overlap

---

## 8. On-Chain Objects

### DUNG Token
- Standard fungible token (SPL)
- Mint authority: Scoring Contract only

### Beetle Cards (Soulbound NFTs)
```rust
pub struct BeetleCard {
    pub owner: Pubkey,
    pub card_type: CardType,  // Climb, Steady, Explorer
    pub scope_id: [u8; 32],   // Arena ID or "GLOBAL"
    pub score: u64,
    pub level: u8,
    pub last_updated: i64,
}
```

| Beetle Type | Scope |
|-------------|-------|
| ClimbBeetle | arenaId |
| SteadyBeetle | GLOBAL |
| ExplorerBeetle | GLOBAL |

### Arena NFTs (Optional)
- Transferable NFTs representing regions
- `regionHash` links to off-chain tile definition
- Enable revenue sharing when β > 0

### DUNG Distribution
```
α = 0.9 (90% to rider)
β = 0.0 (Arena share - future)
γ = 0.0 (Flow share - future)
τ = 0.1 (10% to treasury)
```

---

## 9. Design Decisions

### Tiles Hidden from Users
Users see:
- "Nice climb in Boulder North" (not "You traversed 847 tiles")
- "35 new areas explored" (not "35 new tiles")

Users never see:
- Tile IDs, counts, or resolutions
- H3/S2 terminology

### Polyline Rendering Allowed
- Displaying rider's GPS track on map = standard, allowed
- NOT the same as segment matching (which we avoid)
- We avoid: user-defined segment polylines as competition objects

### Full Segment Replacement
- Remove all segment infrastructure for IP clarity
- Patterns are the ONLY competition system
- No "segment" terminology in codebase

### Arena Bootstrap
- v1: Single "World Arena" - any climb anywhere counts
- Named Arenas created manually when ready
- No algorithmic Arena discovery in v1

### Free Leaderboards
- All detected patterns appear on leaderboards automatically
- No CAL required to compete
- CAL only gates the "score for DUNG" economic action

---

## 10. Implementation Phases

### Phase 1: Tile Infrastructure ✅
- H3 library integration
- Tile projection in ride pipeline
- `activity_tile_samples` and `wallet_tile_history` tables

### Phase 2: Pattern Engine
- ClimbPattern detection algorithm
- SteadyPattern detection algorithm
- ExplorationPattern detection algorithm

### Phase 3: Effort-Based Leaderboards
- World Arena seeding
- Pattern-based rankings
- Leaderboard API endpoints

### Phase 4: CAL & Scoring System
- Daily CAL accounting
- Pattern scoring API
- DUNG minting integration

### Phase 5: Beetle Cards
- Solana soulbound NFT program
- Scoring → Card integration
- Card display in apps

### Phase 6: Segment Purge
- Remove segment tables
- Remove segment matching logic
- Remove segment endpoints

---

## 11. Database Schema

### New Tables

```sql
-- Activity tile samples
CREATE TABLE activity_tile_samples (
    id UUID PRIMARY KEY,
    activity_id UUID REFERENCES rides(id) ON DELETE CASCADE,
    t INTEGER NOT NULL,
    tile_id TEXT NOT NULL,
    elevation_m FLOAT,
    power_w FLOAT,
    hr_bpm INTEGER,
    speed_mps FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Wallet tile history
CREATE TABLE wallet_tile_history (
    wallet TEXT NOT NULL,
    tile_id TEXT NOT NULL,
    first_visited_at TIMESTAMPTZ DEFAULT NOW(),
    visit_count INTEGER DEFAULT 1,
    last_visited_at TIMESTAMPTZ,
    PRIMARY KEY (wallet, tile_id)
);

-- Arenas
CREATE TABLE arenas (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    region_hash TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Arena tiles
CREATE TABLE arena_tiles (
    arena_id UUID REFERENCES arenas(id),
    tile_id TEXT NOT NULL,
    PRIMARY KEY (arena_id, tile_id)
);

-- Pattern tables
CREATE TABLE patterns_climb (...);
CREATE TABLE patterns_steady (...);
CREATE TABLE patterns_exploration (...);
CREATE TABLE scored_patterns (...);
CREATE TABLE cal_daily_balances (...);
```

---

## 12. Open Items (v2+)

1. **Flow NFTs**: Time-based leaderboards via tile sequence matching
2. **Epistemic Layer**: Challenge/dispute mechanics for suspicious attestations
3. **Revenue Splits**: Arena owner shares (β > 0)
4. **Device Trust**: Credibility scores per GPS source
5. **Multi-activity**: Different tile resolutions for running/MTB
6. **Arena Discovery Algorithm**: Auto-discover Arenas from elevation/usage data

---

## Appendix A: H3 Reference

H3 is Uber's Hexagonal Hierarchical Spatial Index:
- 64-bit cell IDs
- Hierarchical (can roll up resolutions)
- Consistent global coverage
- Battle-tested at massive scale

Python: `pip install h3`
```python
import h3
tile_id = h3.geo_to_h3(lat, lon, resolution=10)
```

## Appendix B: Pattern Detection Parameters

```python
CLIMB_CONFIG = {
    "vert_min_m": 300,
    "drop_tolerance_m": 30,
    "time_min_s": 300,   # 5 min
    "time_max_s": 3600,  # 60 min
}

STEADY_CONFIG = {
    "window_min_s": 1200,  # 20 min
    "intensity_band": (0.6, 0.85),  # Z2-Z3
    "variability_max": 0.15,
}

EXPLORATION_CONFIG = {
    "new_tile_ratio": 0.2,
    "global_new_min": 10,
    "night_hours": (22, 4),
}
```
