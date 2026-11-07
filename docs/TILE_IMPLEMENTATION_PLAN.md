# Boulder Rollers v2: Tile-Based Attestation Architecture

## Executive Summary

**The Core Insight**: Replace Strava's polyline-segment-matching architecture with a **tile-based attestation system**. GPS points project to H3 hexagonal cells, patterns emerge from tile sequences, and competitive structures derive from statistical fields over tiles—not user-defined routes.

**Why This Matters**:
1. **IP Differentiation**: No polyline matching = no Strava patent concerns
2. **Emergent Geography**: Arenas and Flows discover themselves from usage data
3. **Privacy by Default**: Tile aggregation naturally obscures exact routes
4. **Simpler Architecture**: O(N) tile projection vs complex segment matching

---

## Architecture Philosophy

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

---

## Tile Resolution Math

### The Design Constraints

For tile edge length `L`:
```
L >= 5 × σ (GPS noise ~5m)     → L >= 25m (noise robustness)
L >= 2 × w (road width ~8m)    → L >= 16m (lateral stability)
L <= R / 10 (feature length)   → L <= 100-300m (preserve shape)
```

**Sweet spot for road cycling: 50-100m tiles (H3 res 10-11)**

### Multi-Scale Strategy
- **Base resolution** (res 10-11): Truth grid, never go finer
- **Arena resolution** (res 9-10): Gameplay and scoring
- **City/stats resolution** (res 6-7): Aggregate views

### Adaptive Refinement
- Merge underused tiles (no rides, no effort)
- Track high-variation tiles (multiple routes through same cell)
- Per-arena tuning as data accumulates

---

## Core Data Model

### Primitives (Locked)
| Internal | User-Facing |
|----------|-------------|
| Tile | (hidden) |
| Arena | "Climb zones", "Areas near you" |
| Flow | "Popular lines" |
| RideTemplate | "Today's Climb", "Easy Spin" |
| RidePlan | "You picked this ride" |
| RideResult | "Ride Complete" |
| Attestation | (hidden - signed proof) |
| Ladder | "Boulder Climb Rankings" |
| CAL | "Daily budget" (keep metabolic vibe) |

### Pattern Types

**ClimbPattern**
- Continuous vertical gain window within Arena tiles
- Constraints: `vert >= 300-600m`, `drop_tolerance <= 20-30m`, `duration 5-60min`
- Best window by: max vert, then min time

**SteadyPattern**
- Sustained aerobic effort (Z2-Z3 intensity band)
- Constraints: `duration >= 20min`, `variability < threshold`
- Best window by: longest duration or highest workload

**ExplorationPattern**
- Novel tile coverage (new to rider or new to system)
- Constraints: `new_tile_ratio >= 20%` OR `global_new >= N` OR `night_minutes >= M`

---

## Core Flow: Detect → Display → Score

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
User sees: "Nice ride! 450m climb, 35min steady, 12 new tiles"
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

## Key Design Decisions

### 1. Competition Model: Effort-Based Primary
**Decision**: Effort-based leaderboards (novel), time-based Flows later (v2)

**Why Effort-Based is Better Than Strava**:
- Strava rewards absolute speed (favors bigger riders, better aero)
- We reward relative effort (W/kg, suffering, training adaptation)
- A 60kg rider doing 5.0 W/kg beats a 80kg rider doing 4.0 W/kg
- This is "value activation for cycling fiends" - rewards FITNESS, not just power

**v1 Leaderboards (Effort-Based)**:
- "Best effort in Boulder North today"
- Ranking metrics: W/kg, effort score, vert/time ratio
- Route-agnostic: different routes through same Arena compete fairly
- More inclusive: you don't need to know THE route

**v2 Leaderboards (Time-Based Flows)**:
- Derive Flows from PTS rider data (tile sequences)
- "Fastest on Flagstaff Flow" (classic KOM feel)
- Familiar competition for those who want it
- Requires Flow emergence pipeline

**PTS Seeding Strategy**:
- PTS period: effort-based only, collect all tile sequences
- Post-PTS: analyze sequences, identify stable Flows
- Early riders become the cartographers
- Flow promotion when N riders take same sequence with M% overlap

**Technical approach for Flows (v2)**:
- Store tile sequences at res 11 (~25m)
- Sequence matching: edit distance or Jaccard on tile arrays
- Flow = tile sequence with statistical stability

### 2. Arena Bootstrap: World Arena + Manual Curation
**Decision**: Launch with single "World Arena", manually create named Arenas later

- v1: One global "World Arena" - any climb anywhere counts
- Named Arenas (Boulder North, Marin, etc.) created manually when ready
- No algorithmic Arena discovery in v1 (separate project for later)
- Arena definitions stored as tile sets, but created by admin, not algorithm

### 3. Beetle Card Scopes
**Decision**: Simplify for v1

| Beetle Type | Scope | Rationale |
|-------------|-------|-----------|
| ClimbBeetle | arenaId | Per-arena climb identity |
| SteadyBeetle | GLOBAL | Endurance is location-agnostic |
| ExplorerBeetle | GLOBAL | Exploration is cumulative |

Seasons can be added later as time-bounded scopes.

### 4. CAL Framing
**Decision**: Keep metabolic metaphor, simplify implementation

- 2200 CAL/day baseline (BMR vibes)
- v1: Fixed for all users
- Future: Personalization by weight/age/training load
- UI: "Daily budget" without over-explaining the metaphor

---

## Existing Codebase Integration

### What We Keep
- **proof_verifier**: Extend to handle pattern-based proofs
- **dung_mint**: Works as-is (mint from proofs)
- **boulder_rollers**: CAL system already exists, adapt to pattern scoring
- **Ride parsing**: Keep FIT/GPX/TCX ingestion, add tile projection step

### What We Add

**Database Tables**:
```sql
activity_tile_samples (activity_id, t, tile_id, elevation_m, power_w, hr_bpm, speed_mps)
arenas (arena_id, name, region_hash, created_at)
arena_tiles (arena_id, tile_id)
patterns_climb (id, activity_id, arena_id, vert_m, time_s, avg_power_w, start_offset_s, end_offset_s)
patterns_steady (id, activity_id, duration_s, avg_power_w, intensity_index, start_offset_s, end_offset_s)
patterns_exploration (id, activity_id, new_tiles_wallet, new_tiles_global, night_minutes)
scored_patterns (id, activity_id, pattern_type, pattern_id, cal_cost, dung_total, tx_hash, status)
cal_daily_balances (wallet, date, cal_allocated, cal_used)
wallet_tile_history (wallet, tile_id, first_visited_at)
```

**Backend Services**:
1. **TileProjectionService**: `(lat, lon) → H3 tile_id`
2. **PatternEngine**: Detect Climb/Steady/Exploration from tile sequences
3. **ArenaService**: Manage Arena definitions, tile membership
4. **CALService**: Daily budget tracking, scoring eligibility
5. **ScoringService**: Compute rewards, call on-chain

**Solana Programs**:
1. **Beetle Card Program**: New - soulbound NFT with (wallet, cardType, scopeId) → score/level
2. **Scoring Program**: Modify existing to handle pattern types and distribution splits

### 5. Leaderboard Access
**Decision**: Free leaderboards, CAL gates DUNG only

- All detected patterns appear on leaderboards automatically
- No CAL required to compete
- CAL only gates the "score for DUNG" economic action
- More inclusive, separates competition from tokenomics

### 6. Tile Abstraction - Hidden from Users
**Decision**: Tiles are infrastructure, never exposed in UI

Users see:
- "Nice climb in Boulder North" (not "You traversed 847 tiles")
- "35 new areas explored" (not "35 new tiles")
- Rankings and effort metrics

Users never see:
- Tile IDs, counts, or resolutions
- H3/S2 terminology
- Any mention of "tiles" at all

### 7. Polyline Rendering
**Decision**: Ride tracks CAN be displayed as polylines

- Displaying a rider's GPS track on a map = standard, allowed
- This is NOT the same as segment matching (which we avoid)
- Polyline display is good UX, expected feature
- We avoid: user-defined segment polylines as competition objects

---

## Implementation Roadmap

### Phase 1: Tile Infrastructure (Foundation)
**Goal**: Project GPS to H3 tiles, store tile sequences

**Files to modify**:
- `backend/app/services/ride_parser.py` - Add tile projection step
- `backend/app/models/` - Add new SQLAlchemy models

**Files to create**:
- `backend/app/services/tile_service.py` - H3 projection logic
- `backend/app/models/tiles.py` - Tile-related models

**Database migrations**:
```sql
-- activity_tile_samples: time-series of tiles per ride
CREATE TABLE activity_tile_samples (
    id UUID PRIMARY KEY,
    activity_id UUID REFERENCES rides(id),
    t INTEGER NOT NULL,  -- seconds since ride start
    tile_id TEXT NOT NULL,  -- H3 index as string
    elevation_m FLOAT,
    power_w FLOAT,
    hr_bpm INTEGER,
    speed_mps FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_tile_samples_activity ON activity_tile_samples(activity_id, t);
CREATE INDEX idx_tile_samples_tile ON activity_tile_samples(tile_id);

-- wallet_tile_history: first visit tracking for exploration
CREATE TABLE wallet_tile_history (
    wallet TEXT NOT NULL,
    tile_id TEXT NOT NULL,
    first_visited_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (wallet, tile_id)
);
```

**Dependencies**:
- `h3` Python library (pip install h3)

**Deliverables**:
- [ ] Ride upload now projects GPS → tiles
- [ ] Tile sequences stored per ride
- [ ] Wallet tile history tracked

---

### Phase 2: Pattern Engine
**Goal**: Detect Climb/Steady/Exploration patterns from tile sequences

**Files to create**:
- `backend/app/services/pattern_engine.py` - Main detection logic
- `backend/app/services/patterns/climb.py` - ClimbPattern algorithm
- `backend/app/services/patterns/steady.py` - SteadyPattern algorithm
- `backend/app/services/patterns/exploration.py` - ExplorationPattern algorithm
- `backend/app/models/patterns.py` - Pattern models

**Database migrations**:
```sql
-- patterns_climb
CREATE TABLE patterns_climb (
    id UUID PRIMARY KEY,
    activity_id UUID REFERENCES rides(id),
    wallet TEXT NOT NULL,
    arena_id UUID,  -- NULL for World Arena
    vert_m FLOAT NOT NULL,
    time_s INTEGER NOT NULL,
    avg_power_w FLOAT,
    w_per_kg FLOAT,
    avg_hr INTEGER,
    start_offset_s INTEGER NOT NULL,
    end_offset_s INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- patterns_steady
CREATE TABLE patterns_steady (
    id UUID PRIMARY KEY,
    activity_id UUID REFERENCES rides(id),
    wallet TEXT NOT NULL,
    duration_s INTEGER NOT NULL,
    avg_power_w FLOAT,
    np_power_w FLOAT,
    avg_hr INTEGER,
    intensity_index FLOAT,
    start_offset_s INTEGER NOT NULL,
    end_offset_s INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- patterns_exploration
CREATE TABLE patterns_exploration (
    id UUID PRIMARY KEY,
    activity_id UUID REFERENCES rides(id),
    wallet TEXT NOT NULL,
    new_tiles_wallet INTEGER NOT NULL,
    new_tiles_global INTEGER,
    night_minutes INTEGER,
    start_offset_s INTEGER NOT NULL,
    end_offset_s INTEGER NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Algorithm parameters** (configurable):
```python
CLIMB_CONFIG = {
    "vert_min_m": 300,
    "drop_tolerance_m": 30,
    "time_min_s": 300,   # 5 min
    "time_max_s": 3600,  # 60 min
}

STEADY_CONFIG = {
    "window_min_s": 1200,  # 20 min
    "intensity_band": (0.6, 0.85),  # Z2-Z3 as % of FTP
    "variability_max": 0.15,
}

EXPLORATION_CONFIG = {
    "new_tile_ratio": 0.2,
    "global_new_min": 10,
    "night_hours": (22, 4),  # 10pm - 4am
}
```

**Deliverables**:
- [ ] Pattern detection runs on ride upload
- [ ] All three pattern types detected and stored
- [ ] Patterns displayed to user post-ride

---

### Phase 3: Effort-Based Leaderboards
**Goal**: Show effort rankings per Arena (World Arena initially)

**Files to modify**:
- `backend/app/routes/leaderboard.py` - Add pattern-based leaderboards

**Files to create**:
- `backend/app/services/leaderboard_service.py` - Leaderboard queries
- `backend/app/models/arenas.py` - Arena models

**Database migrations**:
```sql
-- arenas
CREATE TABLE arenas (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    region_hash TEXT,  -- hash of tile set
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- arena_tiles
CREATE TABLE arena_tiles (
    arena_id UUID REFERENCES arenas(id),
    tile_id TEXT NOT NULL,
    PRIMARY KEY (arena_id, tile_id)
);

-- Seed World Arena
INSERT INTO arenas (id, name, description)
VALUES ('00000000-0000-0000-0000-000000000001', 'World Arena', 'Global climb arena');
```

**API endpoints**:
- `GET /arenas/{arena_id}/leaderboard?metric=w_per_kg&period=today`
- `GET /arenas/{arena_id}/leaderboard?metric=vert&period=week`

**Deliverables**:
- [ ] World Arena seeded
- [ ] Effort-based leaderboards queryable
- [ ] Leaderboard UI in iOS app

---

### Phase 4: CAL & Scoring System
**Goal**: Implement CAL accounting and pattern scoring for DUNG

**Files to modify**:
- `backend/app/routes/cal.py` - Extend CAL endpoints
- `backend/app/services/cal_service.py` - Daily balance logic

**Files to create**:
- `backend/app/services/scoring_service.py` - Score pattern → mint DUNG
- `backend/app/routes/scoring.py` - Scoring API

**Database migrations**:
```sql
-- cal_daily_balances
CREATE TABLE cal_daily_balances (
    wallet TEXT NOT NULL,
    date DATE NOT NULL,
    cal_allocated INTEGER DEFAULT 2200,
    cal_used INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (wallet, date)
);

-- scored_patterns
CREATE TABLE scored_patterns (
    id UUID PRIMARY KEY,
    activity_id UUID REFERENCES rides(id),
    wallet TEXT NOT NULL,
    pattern_type TEXT NOT NULL,  -- CLIMB, STEADY, EXPLORATION
    pattern_id UUID NOT NULL,
    arena_id UUID REFERENCES arenas(id),
    cal_cost INTEGER NOT NULL,
    dung_total NUMERIC NOT NULL,
    tx_hash TEXT,
    status TEXT DEFAULT 'PENDING',  -- PENDING, SUCCESS, FAILED
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**API endpoints**:
- `GET /cal/balance` - Today's CAL balance
- `POST /patterns/{pattern_id}/score` - Score a pattern for DUNG

**CAL cost formula** (v1 simple):
```python
def cal_cost(pattern):
    if pattern.type == "CLIMB":
        return int(pattern.vert_m * 0.5)  # ~150-300 CAL for typical climb
    elif pattern.type == "STEADY":
        return int(pattern.duration_s / 60 * 10)  # 10 CAL per minute
    elif pattern.type == "EXPLORATION":
        return int(pattern.new_tiles_wallet * 5)  # 5 CAL per new tile
```

**Deliverables**:
- [ ] Daily CAL balance tracking
- [ ] Score pattern endpoint
- [ ] Integration with existing DUNG mint

---

### Phase 5: Beetle Cards (On-Chain)
**Goal**: Soulbound NFTs tracking effort history

**Files to create**:
- `protocol/anchor/programs/beetle_cards/` - New Solana program

**Solana program structure**:
```rust
// State
pub struct BeetleCard {
    pub owner: Pubkey,
    pub card_type: CardType,  // Climb, Steady, Explorer
    pub scope_id: [u8; 32],   // Arena ID or "GLOBAL"
    pub score: u64,
    pub level: u8,
    pub last_updated: i64,
    pub bump: u8,
}

// Instructions
pub fn initialize_card(ctx, card_type, scope_id) -> Result<()>
pub fn increment_score(ctx, delta_score) -> Result<()>  // Only callable by scoring program
```

**Integration**:
- Scoring Service calls Beetle Card program after DUNG mint
- Card score increments based on pattern metrics

**Deliverables**:
- [ ] Beetle Card program deployed to devnet
- [ ] Integration with scoring flow
- [ ] Card display in iOS app

---

## Codebase Changes: Keep / Modify / Purge

### KEEP AS-IS
| Component | Reason |
|-----------|--------|
| `dung_mint` program | Works perfectly, just call from new scoring flow |
| Ride parsing (FIT/GPX/TCX) | Keep all ingestion logic, add tile projection step |
| User/wallet auth | No changes needed |
| Activity streams storage | Keep time-series data, add tiles alongside |

### MODIFY
| Component | Changes |
|-----------|---------|
| `boulder_rollers` program | Adapt CAL system for pattern-based scoring (not segment-based) |
| `backend/app/routes/cal.py` | Extend for daily balance tracking |
| `backend/app/services/ride_parser.py` | Add tile projection after GPS parsing |
| `backend/app/routes/leaderboard.py` | Replace segment leaderboards with pattern leaderboards |
| `proof_verifier` program | May need pattern_type field, or replace entirely |

### POTENTIALLY REDUNDANT (Evaluate for Purge)
| Component | Status | Notes |
|-----------|--------|-------|
| `segments` table | **LIKELY PURGE** | Polyline-based segments replaced by tile patterns |
| `segment_efforts` table | **LIKELY PURGE** | Replaced by `patterns_*` tables |
| Segment creation endpoints | **PURGE** | No user-created segments in new model |
| Segment matching logic | **PURGE** | Core thing we're eliminating |
| Current segment leaderboards | **REPLACE** | Replace with pattern-based effort leaderboards |

### Migration Decision: FULL REPLACEMENT
**Decision**: Remove all segment infrastructure for IP clarity

- Segment tables, endpoints, and matching logic will be purged
- Patterns are the ONLY competition system
- This ensures clean separation from polyline-based segment IP
- No "segment" terminology in the codebase

---

## Files Summary

### Backend (Python/FastAPI)
| File | Action | Purpose |
|------|--------|---------|
| `backend/app/services/tile_service.py` | CREATE | H3 projection |
| `backend/app/services/pattern_engine.py` | CREATE | Pattern detection orchestration |
| `backend/app/services/patterns/*.py` | CREATE | Individual pattern algorithms |
| `backend/app/services/leaderboard_service.py` | CREATE | Effort-based leaderboards |
| `backend/app/services/scoring_service.py` | CREATE | CAL → DUNG scoring |
| `backend/app/routes/admin/arenas.py` | CREATE | Manual Arena management |
| `backend/app/models/tiles.py` | CREATE | Tile models |
| `backend/app/models/patterns.py` | CREATE | Pattern models |
| `backend/app/models/arenas.py` | CREATE | Arena models |
| `backend/app/routes/scoring.py` | CREATE | Scoring API |
| `backend/app/services/ride_parser.py` | MODIFY | Add tile projection |
| `backend/app/routes/leaderboard.py` | MODIFY | Add pattern leaderboards |
| `backend/app/routes/cal.py` | MODIFY | Extend CAL balance |

### Solana (Anchor/Rust)
| File | Action | Purpose |
|------|--------|---------|
| `protocol/anchor/programs/beetle_cards/` | CREATE | Soulbound NFT program |
| `protocol/anchor/programs/boulder_rollers/` | MODIFY | Adapt CAL for patterns |

### iOS
| File | Action | Purpose |
|------|--------|---------|
| Pattern display views | CREATE | Show detected patterns |
| Leaderboard views | MODIFY | Effort-based rankings |
| Beetle Card views | CREATE | Display cards |

---

## Open Items (v2+)

1. **Flow NFTs**: Time-based leaderboards via tile sequence matching
2. **Epistemic Layer**: Challenge/dispute mechanics
3. **Revenue Splits**: Arena owner shares (β > 0)
4. **Device Trust**: Credibility scores per GPS source
5. **Multi-activity**: Different resolutions for running/MTB
6. **Arena Discovery Algorithm**: Auto-discover Arenas from elevation/usage data (separate project)
