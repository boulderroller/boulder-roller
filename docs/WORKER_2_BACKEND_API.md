# Worker 2: Backend API Engineer

**Context:** Read `BOULDER_ROLLERS_V1_SPEC.md` first for full game design.

**Your Responsibility:** Extend the existing FastAPI backend with V1 features.

**Tech Stack:**
- Python 3.11+ + FastAPI ✅ **Already exists**
- PostgreSQL + PostGIS
- Redis (add for caching)
- Solana.py (for on-chain calls)

**Working Directory:** `/backend/`

---

## Current State (Already Built ✅)

You have a **working FastAPI backend** with:
- ✅ Auth routes (Solana wallet signing)
- ✅ Segments API (list with bounding box)
- ✅ Rides, Proofs, Mint routes
- ✅ Repository pattern
- ✅ Tests

**DO NOT REWRITE. Just extend what exists.**

---

## Your 7-Week Plan

### Week 1: Audit & Database Schema Updates

#### Task 2.1: Audit Existing Code (Day 1)

**Goal:** Understand what's already built.

```bash
cd backend

# Check dependencies
cat requirements.txt

# Check database schema
cat sql/*.sql  # or migrations/

# Run existing tests
pytest

# Start dev server
uvicorn app.main:app --reload
```

**Document in Slack:**
- What routes exist
- What database tables exist
- What's missing for V1

---

#### Task 2.2: Add Missing Database Tables (Day 2-3)

**Goal:** Add tables for V1 features (staking, epochs, Swannys).

**Create `sql/002_v1_features.sql`:**
```sql
-- User State (track CAL balance off-chain for caching)
CREATE TABLE user_state (
    user_id BIGINT PRIMARY KEY REFERENCES users(id),
    cal_balance BIGINT DEFAULT 0,
    cal_earned_today BIGINT DEFAULT 0,
    last_cal_mint TIMESTAMPTZ,
    total_rides BIGINT DEFAULT 0,
    total_tss BIGINT DEFAULT 0,
    bio_score INT DEFAULT 1000,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Claims (staking cache from on-chain)
CREATE TABLE claims (
    user_id BIGINT REFERENCES users(id),
    segment_id BIGINT REFERENCES segments(id),
    amount BIGINT NOT NULL,
    lp_tokens BIGINT NOT NULL,
    staked_at TIMESTAMPTZ NOT NULL,
    last_harvest TIMESTAMPTZ,
    PRIMARY KEY(user_id, segment_id)
);
CREATE INDEX idx_claims_segment ON claims(segment_id);

-- Swanny Seats (cache from on-chain)
CREATE TABLE swanny_seats (
    segment_id BIGINT REFERENCES segments(id),
    seat_index SMALLINT CHECK (seat_index IN (0, 1, 2)),
    holder_pubkey TEXT,
    locked_at TIMESTAMPTZ,
    unlock_at TIMESTAMPTZ,
    tasks_completed SMALLINT DEFAULT 0,
    PRIMARY KEY(segment_id, seat_index)
);

-- Epochs (cache from on-chain)
CREATE TABLE epochs (
    segment_id BIGINT REFERENCES segments(id),
    epoch_number BIGINT,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    total_pot BIGINT,
    distributed BOOLEAN DEFAULT FALSE,
    PRIMARY KEY(segment_id, epoch_number)
);
CREATE INDEX idx_epochs_end_time ON epochs(end_time) WHERE NOT distributed;

-- Leaderboard Entries (cached for fast queries)
CREATE TABLE leaderboard_entries (
    segment_id BIGINT REFERENCES segments(id),
    epoch_number BIGINT,
    user_id BIGINT REFERENCES users(id),
    rank INT,
    time_seconds INT,
    tss INT,
    PRIMARY KEY(segment_id, epoch_number, user_id)
);
CREATE INDEX idx_leaderboard_segment_epoch ON leaderboard_entries(segment_id, epoch_number, rank);
```

**Run migration:**
```bash
# Apply to database
psql $DATABASE_URL < sql/002_v1_features.sql
```

---

#### Task 2.3: Update Repository Layer (Day 4-5)

**Goal:** Add repository methods for new tables.

**Update `app/repositories.py`:**
```python
from typing import Optional, List, Tuple
from datetime import datetime

class DatabaseRepository:
    # ... existing methods ...

    # User State
    async def get_user_state(self, user_id: int) -> Optional[dict]:
        """Get user's CAL balance and stats."""
        query = """
            SELECT cal_balance, cal_earned_today, last_cal_mint,
                   total_rides, total_tss, bio_score
            FROM user_state
            WHERE user_id = $1
        """
        row = await self.conn.fetchrow(query, user_id)
        return dict(row) if row else None

    async def update_cal_balance(self, user_id: int, amount: int) -> None:
        """Update user's CAL balance."""
        query = """
            INSERT INTO user_state (user_id, cal_balance, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET cal_balance = user_state.cal_balance + $2,
                          updated_at = NOW()
        """
        await self.conn.execute(query, user_id, amount)

    # Claims
    async def get_user_claims(self, user_id: int) -> List[dict]:
        """Get all segments user has staked in."""
        query = """
            SELECT c.segment_id, c.amount, c.lp_tokens, c.staked_at,
                   s.name as segment_name, s.distance_meters, s.elevation_gain
            FROM claims c
            JOIN segments s ON s.id = c.segment_id
            WHERE c.user_id = $1
        """
        rows = await self.conn.fetch(query, user_id)
        return [dict(row) for row in rows]

    async def upsert_claim(self, user_id: int, segment_id: int,
                           amount: int, lp_tokens: int) -> None:
        """Cache claim from on-chain."""
        query = """
            INSERT INTO claims (user_id, segment_id, amount, lp_tokens, staked_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id, segment_id)
            DO UPDATE SET amount = $3, lp_tokens = $4
        """
        await self.conn.execute(query, user_id, segment_id, amount, lp_tokens)

    # Epochs
    async def get_current_epoch(self, segment_id: int) -> Optional[dict]:
        """Get current active epoch for segment."""
        query = """
            SELECT epoch_number, start_time, end_time, total_pot, distributed
            FROM epochs
            WHERE segment_id = $1
              AND end_time > NOW()
            ORDER BY epoch_number DESC
            LIMIT 1
        """
        row = await self.conn.fetchrow(query, segment_id)
        return dict(row) if row else None

    async def get_leaderboard(self, segment_id: int,
                              epoch_number: int, limit: int = 100) -> List[dict]:
        """Get leaderboard for segment/epoch."""
        query = """
            SELECT le.rank, u.pubkey, u.username,
                   le.time_seconds, le.tss
            FROM leaderboard_entries le
            JOIN users u ON u.id = le.user_id
            WHERE le.segment_id = $1 AND le.epoch_number = $2
            ORDER BY le.rank ASC
            LIMIT $3
        """
        rows = await self.conn.fetch(query, segment_id, epoch_number, limit)
        return [dict(row) for row in rows]
```

**Deliverable:** Database schema updated, repository methods working

---

### Week 2: CAL System & Staking Endpoints

#### Task 2.4: CAL System Routes (Day 1-2)

**Create `app/routes/cal.py`:**
```python
from fastapi import APIRouter, Depends, HTTPException
from ..dependencies import get_repository, get_current_user
from ..repositories import DatabaseRepository
from ..schemas import User

router = APIRouter()

@router.get("/balance")
async def get_cal_balance(
    current_user: User = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get user's current CAL balance."""
    state = await repo.get_user_state(current_user.id)

    if not state:
        # Initialize if doesn't exist
        return {"cal_balance": 0, "can_mint": True}

    # Check if can mint today
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    can_mint = (
        not state["last_cal_mint"] or
        state["last_cal_mint"].date() < now.date()
    )

    return {
        "cal_balance": state["cal_balance"],
        "cal_earned_today": state["cal_earned_today"],
        "can_mint": can_mint,
        "last_cal_mint": state["last_cal_mint"]
    }

@router.post("/mint")
async def mint_daily_cal(
    current_user: User = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Mint 2500 CAL (once per day)."""
    # This would call Worker 1's on-chain mint_daily_cal() instruction
    # For now, just cache the result

    state = await repo.get_user_state(current_user.id)

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    if state and state["last_cal_mint"]:
        if state["last_cal_mint"].date() == now.date():
            raise HTTPException(400, "Already minted CAL today")

    # TODO: Call Solana program
    # For now, just update cache
    await repo.update_cal_balance(current_user.id, 2500)

    return {"cal_balance": 2500, "minted": 2500}
```

**Register in `app/main.py`:**
```python
from .routes import auth, health, mint, proofs, rides, segments, cal  # Add cal

app.include_router(cal.router, prefix="/cal", tags=["cal"])
```

---

#### Task 2.5: Staking Endpoints (Day 3-5)

**Create `app/routes/staking.py`:**
```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from ..dependencies import get_repository, get_current_user
from ..repositories import DatabaseRepository
from ..schemas import User

router = APIRouter()

class StakeRequest(BaseModel):
    segment_id: int
    amount: int  # In DUNG (lamports)

class UnstakeRequest(BaseModel):
    segment_id: int
    lp_amount: int

@router.post("/stake")
async def stake_in_segment(
    request: StakeRequest,
    current_user: User = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Stake DUNG in a segment."""
    if request.amount < 10_000_000_000:  # Min 10 DUNG
        raise HTTPException(400, "Minimum stake is 10 DUNG")

    # TODO: Call Worker 1's stake_in_segment() on-chain
    # For now, mock the response

    lp_tokens = request.amount  # 1:1 for first staker

    # Cache in database
    await repo.upsert_claim(
        current_user.id,
        request.segment_id,
        request.amount,
        lp_tokens
    )

    return {
        "segment_id": request.segment_id,
        "amount_staked": request.amount,
        "lp_tokens_received": lp_tokens,
        "tx_signature": "mock_signature"
    }

@router.post("/unstake")
async def unstake_from_segment(
    request: UnstakeRequest,
    current_user: User = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Unstake DUNG from a segment."""
    # TODO: Call Worker 1's unstake_from_segment()

    # Calculate DUNG to return (pro-rata)
    dung_returned = request.lp_amount  # Simplified

    # Delete from cache
    await repo.conn.execute(
        "DELETE FROM claims WHERE user_id = $1 AND segment_id = $2",
        current_user.id, request.segment_id
    )

    return {
        "segment_id": request.segment_id,
        "lp_tokens_burned": request.lp_amount,
        "dung_returned": dung_returned,
        "tx_signature": "mock_signature"
    }

@router.get("/claims")
async def get_my_claims(
    current_user: User = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get all segments user has staked in."""
    claims = await repo.get_user_claims(current_user.id)
    return {"claims": claims}
```

**Deliverable:** CAL and staking endpoints working

---

### Week 3: Ride Processing & Segment Intersection

#### Task 2.6: Enhanced Ride Upload (Day 1-2)

**Update `app/routes/rides.py`:**
```python
# Add GPX/FIT parsing
import gpxpy
from fitparse import FitFile

@router.post("/upload")
async def upload_ride(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Upload GPX or FIT file."""
    content = await file.read()

    # Parse based on file type
    if file.filename.endswith('.gpx'):
        ride_data = parse_gpx(content)
    elif file.filename.endswith('.fit'):
        ride_data = parse_fit(content)
    else:
        raise HTTPException(400, "File must be .gpx or .fit")

    # Store in database
    ride_id = await repo.create_ride(
        user_id=current_user.id,
        gpx_data=ride_data["raw"],
        distance_meters=ride_data["distance"],
        elevation_gain=ride_data["elevation"],
        tss=ride_data.get("tss")
    )

    # Trigger async processing (Redis queue or background task)
    await enqueue_ride_processing(ride_id)

    return {"ride_id": ride_id, "status": "processing"}

def parse_gpx(content: bytes) -> dict:
    """Parse GPX file."""
    gpx = gpxpy.parse(content.decode('utf-8'))

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                points.append({
                    "lat": point.latitude,
                    "lon": point.longitude,
                    "ele": point.elevation,
                    "time": point.time
                })

    # Calculate distance
    distance = gpx.length_2d()

    # Calculate elevation gain
    elevation_gain = gpx.get_uphill_downhill().uphill

    return {
        "raw": points,
        "distance": int(distance),
        "elevation": int(elevation_gain),
        "tss": None  # Calculate if power data available
    }

def parse_fit(content: bytes) -> dict:
    """Parse FIT file (from Garmin/Wahoo)."""
    fitfile = FitFile(content)

    points = []
    total_distance = 0
    total_ascent = 0

    for record in fitfile.get_messages('record'):
        data = {}
        for field in record:
            data[field.name] = field.value

        if 'position_lat' in data and 'position_long' in data:
            points.append({
                "lat": data['position_lat'] * (180 / 2**31),
                "lon": data['position_long'] * (180 / 2**31),
                "ele": data.get('altitude'),
                "time": data.get('timestamp'),
                "hr": data.get('heart_rate'),
                "power": data.get('power')
            })

    # TODO: Calculate TSS from power data

    return {
        "raw": points,
        "distance": int(total_distance),
        "elevation": int(total_ascent),
        "tss": None
    }
```

**Add dependencies:**
```bash
pip install gpxpy fitparse
echo "gpxpy==1.6.2" >> requirements.txt
echo "fitparse==1.2.0" >> requirements.txt
```

---

#### Task 2.7: Segment Intersection Worker (Day 3-5)

**Create `app/workers/ride_processor.py`:**
```python
import asyncio
from ..repositories import DatabaseRepository
from ..services.segment_matcher import SegmentMatcher

async def process_ride(ride_id: int):
    """Process uploaded ride: find segment intersections."""
    repo = DatabaseRepository()

    # Load ride
    ride = await repo.get_ride(ride_id)
    if not ride:
        return

    # Get nearby segments (PostGIS query)
    segments = await repo.get_segments_near_ride(ride["polyline"])

    # Match segments
    matcher = SegmentMatcher(ride["polyline"])

    for segment in segments:
        match = matcher.match_segment(segment)

        if match:
            # Insert segment effort
            await repo.create_segment_effort(
                ride_id=ride_id,
                segment_id=segment["id"],
                user_id=ride["user_id"],
                time_seconds=match["time_seconds"],
                tss=ride["tss"]
            )

            # TODO: Call Worker 1's record_ride() on-chain

            # Update leaderboard cache
            await repo.update_leaderboard(
                segment_id=segment["id"],
                user_id=ride["user_id"],
                time_seconds=match["time_seconds"],
                tss=ride["tss"]
            )

    # Mark ride as processed
    await repo.mark_ride_processed(ride_id)
```

**Create `app/services/segment_matcher.py`:**
```python
from typing import List, Dict, Optional
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

class SegmentMatcher:
    """Match ride GPS trace to segments."""

    def __init__(self, ride_polyline: List[Dict]):
        self.ride_line = LineString([
            (p["lon"], p["lat"]) for p in ride_polyline
        ])
        self.ride_points = ride_polyline

    def match_segment(self, segment: Dict) -> Optional[Dict]:
        """
        Check if ride crosses this segment.
        Returns time taken if matched, None otherwise.
        """
        start_point = Point(segment["start_lon"], segment["start_lat"])
        end_point = Point(segment["end_lon"], segment["end_lat"])

        # Check if ride passes within 50m of start and end
        start_dist = start_point.distance(self.ride_line)
        end_dist = end_point.distance(self.ride_line)

        THRESHOLD_DEGREES = 0.0005  # ~50 meters

        if start_dist > THRESHOLD_DEGREES or end_dist > THRESHOLD_DEGREES:
            return None  # Ride doesn't cross this segment

        # Find closest points on ride to segment start/end
        start_on_ride = nearest_points(start_point, self.ride_line)[1]
        end_on_ride = nearest_points(end_point, self.ride_line)[1]

        # Extract timestamps from ride points
        start_idx = self._find_point_index(start_on_ride)
        end_idx = self._find_point_index(end_on_ride)

        if start_idx is None or end_idx is None or start_idx >= end_idx:
            return None

        # Calculate time difference
        start_time = self.ride_points[start_idx]["time"]
        end_time = self.ride_points[end_idx]["time"]

        time_seconds = int((end_time - start_time).total_seconds())

        return {
            "time_seconds": time_seconds,
            "start_idx": start_idx,
            "end_idx": end_idx
        }

    def _find_point_index(self, target_point: Point) -> Optional[int]:
        """Find index of ride point closest to target."""
        min_dist = float('inf')
        closest_idx = None

        for i, p in enumerate(self.ride_points):
            point = Point(p["lon"], p["lat"])
            dist = point.distance(target_point)

            if dist < min_dist:
                min_dist = dist
                closest_idx = i

        return closest_idx
```

**Add dependencies:**
```bash
pip install shapely
echo "shapely==2.0.2" >> requirements.txt
```

**Deliverable:** Ride upload works, segment intersection calculated

---

### Week 4-5: Leaderboards, Integration, Testing

**Task 2.8:** Redis caching for leaderboards

**Task 2.9:** Integrate with Worker 1 (call Solana programs via solana-py)

**Task 2.10:** Add rate limiting

**Task 2.11:** Performance testing

---

### Week 6-7: Deployment & Monitoring

**Task 2.12:** Deploy to Worker 4's infrastructure

**Task 2.13:** Add metrics endpoint for Prometheus

**Task 2.14:** Load testing

---

## Integration with Worker 1 (Solana)

**Install solana-py:**
```bash
pip install solana anchorpy
echo "solana==0.30.2" >> requirements.txt
echo "anchorpy==0.18.0" >> requirements.txt
```

**Create `app/services/solana_client.py`:**
```python
from solana.rpc.async_api import AsyncClient
from solana.keypair import Keypair
from anchorpy import Provider, Wallet, Program

class SolanaService:
    def __init__(self):
        self.client = AsyncClient(os.getenv("SOLANA_RPC_URL"))
        # Load program IDL from Worker 1
        self.program = Program(...)

    async def mint_daily_cal(self, user_pubkey: str):
        """Call Worker 1's mint_daily_cal instruction."""
        # Build transaction
        # Sign and send
        pass

    async def stake_in_segment(self, user_pubkey: str, segment_id: int, amount: int):
        """Call Worker 1's stake_in_segment instruction."""
        pass
```

---

## Deliverables Each Week

1. New routes working (test with curl/Postman)
2. Tests passing (`pytest`)
3. Deploy to dev environment
4. Update API docs

---

## Communication with Other Workers

**From Worker 1 you need:**
- Program IDs (add to `.env`)
- IDL files (for anchorpy)

**Worker 3 (iOS) calls your API:**
- Keep routes stable
- Document changes in Slack

**Worker 4 deploys your code:**
- Provide updated `requirements.txt`
- Health check endpoint exists

---

## Resources

- FastAPI: https://fastapi.tiangolo.com/
- SQLAlchemy: https://www.sqlalchemy.org/
- PostGIS: https://postgis.net/docs/
- solana-py: https://github.com/michaelhly/solana-py
- Your working directory: `/backend/`
- Start: `uvicorn app.main:app --reload`
- Test: `pytest`
