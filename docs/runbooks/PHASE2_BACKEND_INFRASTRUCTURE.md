# Phase 2: Backend Infrastructure Runbook

## Worker Assignment
**Focus:** Async processing infrastructure, database tables, repository methods
**FLAGS:** 1, 2, 9

---

## Overview

Transform the ride upload from synchronous to asynchronous processing. Client uploads raw file → backend queues job → background worker processes → client polls for status.

---

## FLAG 1: Async Processing Infrastructure

### 1.1 Install Dependencies

Add to `requirements.txt`:
```
celery>=5.3.0
redis>=4.5.0
```

### 1.2 Create Celery Configuration

**File:** `backend/app/celery_app.py`
```python
import os
from celery import Celery

celery_app = Celery(
    "boulder_rollers",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minute timeout
    worker_prefetch_multiplier=1,
)
```

### 1.3 Create Task Definitions

**File:** `backend/app/tasks.py`
```python
from uuid import UUID
from .celery_app import celery_app
from .services.ride_processor import RideProcessor
from .repositories import DatabaseRepository

@celery_app.task(bind=True, max_retries=3)
def process_ride_upload(
    self,
    ride_id: str,
    file_data_b64: str,
    file_type: str,
    user_id: str,
    user_weight_kg: float = 75.0,
    user_ftp_w: int = 200,
):
    """
    Background task to process uploaded ride file.

    Steps:
    1. Parse file (FIT/GPX/TCX)
    2. Extract activity streams
    3. Calculate metrics
    4. Store GPS points
    5. Match segments
    6. Detect achievements
    7. Create Solana proof
    8. Mint DUNG
    9. Update ride status
    """
    import asyncio

    async def _process():
        processor = RideProcessor()
        return await processor.process_ride(
            ride_id=UUID(ride_id),
            file_data_b64=file_data_b64,
            file_type=file_type,
            user_id=UUID(user_id),
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
        )

    try:
        result = asyncio.run(_process())
        return {
            "status": "completed",
            "ride_id": ride_id,
            "metrics": result.get("metrics"),
            "dung_minted": result.get("dung_reward"),
        }
    except Exception as exc:
        # Mark ride as failed
        asyncio.run(_mark_failed(ride_id, str(exc)))
        raise self.retry(exc=exc, countdown=60)

async def _mark_failed(ride_id: str, error: str):
    repo = DatabaseRepository()
    await repo.update_ride_status(UUID(ride_id), "failed", error_message=error)
```

### 1.4 Modify Rides Upload Endpoint

**File:** `backend/app/routes/rides.py`

Modify the existing upload endpoint to queue async job:

```python
from ..tasks import process_ride_upload

class RideUploadRequest(BaseModel):
    file_data_b64: str  # Base64-encoded file content
    file_type: str  # "fit", "gpx", "tcx"

class RideUploadResponse(BaseModel):
    ride_id: str
    status: str  # "processing", "queued"
    message: str

@router.post("/upload", response_model=RideUploadResponse)
async def upload_ride(
    request: RideUploadRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Upload a ride file for processing.
    Returns immediately with ride_id - processing happens async.
    """
    # 1. Check CAL balance
    cal_balance = await repo.get_user_cal_balance(current_user.user_id)
    cal_cost = 1.0  # Cost per ride upload

    if cal_balance < cal_cost:
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient CAL. Need {cal_cost}, have {cal_balance}"
        )

    # 2. Create ride record with "processing" status
    ride_id = await repo.create_ride(
        user_id=current_user.user_id,
        status="processing",
        file_type=request.file_type,
    )

    # 3. Get user profile for FTP/weight
    profile = await repo.get_user_profile(current_user.user_id)
    user_weight = profile.get("weight_kg", 75.0) if profile else 75.0
    user_ftp = profile.get("ftp_w", 200) if profile else 200

    # 4. Queue background processing task
    process_ride_upload.delay(
        ride_id=str(ride_id),
        file_data_b64=request.file_data_b64,
        file_type=request.file_type,
        user_id=str(current_user.user_id),
        user_weight_kg=user_weight,
        user_ftp_w=user_ftp,
    )

    return RideUploadResponse(
        ride_id=str(ride_id),
        status="processing",
        message="Ride uploaded. Processing in background.",
    )


@router.get("/{ride_id}/status")
async def get_ride_status(
    ride_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Poll for ride processing status."""
    ride = await repo.get_ride(ride_id)

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    if ride["user_id"] != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride")

    return {
        "ride_id": ride_id,
        "status": ride["processing_status"],
        "error_message": ride.get("error_message"),
        "metrics": {
            "tss": ride.get("tss"),
            "kcals": ride.get("kcals"),
            "distance_m": ride.get("distance_m"),
            "elevation_gain_m": ride.get("elevation_gain_m"),
        } if ride["processing_status"] == "completed" else None,
        "dung_minted": ride.get("dung_minted"),
        "tx_signature": ride.get("tx_signature"),
    }
```

### 1.5 Add Celery Worker to Docker/Deployment

**File:** `backend/docker-compose.yml` (add worker service)
```yaml
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  celery-worker:
    build: .
    command: celery -A app.celery_app worker --loglevel=info
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
```

---

## FLAG 2: Activity Streams Storage

### 2.1 Create Activity Streams Table

**File:** `backend/sql/011_activity_streams.sql`
```sql
-- Activity streams: time-series data for power, HR, cadence, speed
CREATE TABLE IF NOT EXISTS activity_streams (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID NOT NULL,
    stream_type VARCHAR(20) NOT NULL,  -- 'power', 'heart_rate', 'cadence', 'speed'

    -- Store as arrays for efficient retrieval
    timestamps TIMESTAMPTZ[] NOT NULL,
    values FLOAT[] NOT NULL,

    -- Metadata
    sample_count INT NOT NULL,
    min_value FLOAT,
    max_value FLOAT,
    avg_value FLOAT,

    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_activity_streams_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE,
    CONSTRAINT unique_ride_stream_type
        UNIQUE (ride_id, stream_type)
);

CREATE INDEX idx_activity_streams_ride ON activity_streams(ride_id);
CREATE INDEX idx_activity_streams_type ON activity_streams(stream_type);
```

### 2.2 Create GPS Points Table

**File:** `backend/sql/012_gps_points.sql`
```sql
-- Enable PostGIS if not already enabled
CREATE EXTENSION IF NOT EXISTS postgis;

-- GPS track points for segment matching
CREATE TABLE IF NOT EXISTS gps_points (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID NOT NULL,

    -- Point data
    sequence_num INT NOT NULL,  -- Order in track
    timestamp TIMESTAMPTZ NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    elevation_m FLOAT,
    distance_m FLOAT,  -- Accumulated distance from start

    -- PostGIS geography for spatial queries
    location GEOGRAPHY(POINT, 4326),

    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_gps_points_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE
);

-- Indexes for efficient queries
CREATE INDEX idx_gps_points_ride ON gps_points(ride_id, sequence_num);
CREATE INDEX idx_gps_points_timestamp ON gps_points(ride_id, timestamp);
CREATE INDEX idx_gps_points_location ON gps_points USING GIST(location);

-- Trigger to auto-populate location from lat/lon
CREATE OR REPLACE FUNCTION update_gps_location()
RETURNS TRIGGER AS $$
BEGIN
    NEW.location := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326)::geography;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_gps_points_location
    BEFORE INSERT OR UPDATE ON gps_points
    FOR EACH ROW
    EXECUTE FUNCTION update_gps_location();
```

### 2.3 Add Repository Methods

**File:** `backend/app/repositories.py` (add methods)

```python
# Add to DatabaseRepository class:

async def store_activity_stream(
    self,
    ride_id: UUID,
    stream_type: str,
    timestamps: List[datetime],
    values: List[float],
) -> UUID:
    """Store activity stream data for a ride."""
    sample_count = len(values)
    min_val = min(values) if values else None
    max_val = max(values) if values else None
    avg_val = sum(values) / len(values) if values else None

    result = await self.client.table("activity_streams").insert({
        "ride_id": str(ride_id),
        "stream_type": stream_type,
        "timestamps": [t.isoformat() for t in timestamps],
        "values": values,
        "sample_count": sample_count,
        "min_value": min_val,
        "max_value": max_val,
        "avg_value": avg_val,
    }).execute()

    return UUID(result.data[0]["id"])

async def get_activity_stream(
    self,
    ride_id: UUID,
    stream_type: str,
) -> Optional[Dict]:
    """Retrieve activity stream for a ride."""
    result = await self.client.table("activity_streams").select("*").eq(
        "ride_id", str(ride_id)
    ).eq("stream_type", stream_type).single().execute()

    return result.data if result.data else None

async def store_gps_points(
    self,
    ride_id: UUID,
    points: List[Dict],  # [{timestamp, lat, lon, elevation, distance}]
) -> int:
    """Bulk insert GPS points for a ride."""
    records = [
        {
            "ride_id": str(ride_id),
            "sequence_num": i,
            "timestamp": p["timestamp"].isoformat(),
            "latitude": p["latitude"],
            "longitude": p["longitude"],
            "elevation_m": p.get("elevation"),
            "distance_m": p.get("distance"),
        }
        for i, p in enumerate(points)
    ]

    # Batch insert
    result = await self.client.table("gps_points").insert(records).execute()
    return len(result.data)

async def get_gps_track(
    self,
    ride_id: UUID,
    limit: int = 10000,
) -> List[Dict]:
    """Retrieve GPS track for a ride."""
    result = await self.client.table("gps_points").select(
        "sequence_num, timestamp, latitude, longitude, elevation_m, distance_m"
    ).eq("ride_id", str(ride_id)).order("sequence_num").limit(limit).execute()

    return result.data

async def update_ride_status(
    self,
    ride_id: UUID,
    status: str,
    error_message: str = None,
    **metrics,
) -> None:
    """Update ride processing status and optionally metrics."""
    update_data = {"processing_status": status}

    if error_message:
        update_data["error_message"] = error_message

    update_data.update(metrics)

    await self.client.table("rides").update(update_data).eq(
        "id", str(ride_id)
    ).execute()
```

---

## FLAG 9: Additional Database Migrations

### 9.1 Segment Efforts Table

**File:** `backend/sql/013_segment_efforts.sql`
```sql
-- Segment efforts: matched ride segments with performance data
CREATE TABLE IF NOT EXISTS segment_efforts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ride_id UUID NOT NULL,
    segment_id INT NOT NULL,
    user_id UUID NOT NULL,

    -- Timing
    started_at TIMESTAMPTZ,
    elapsed_time_sec INT NOT NULL,

    -- Performance
    effort_score FLOAT NOT NULL,  -- Power-weighted time
    average_power_w FLOAT,
    average_hr_bpm FLOAT,
    average_speed_mps FLOAT,

    -- Segment data
    elevation_gain_m FLOAT,
    distance_m FLOAT,

    -- Ranking
    rank_at_time INT,  -- Rank when effort was recorded
    is_pr BOOLEAN DEFAULT FALSE,  -- Personal record
    is_kom BOOLEAN DEFAULT FALSE, -- King of Mountain

    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_segment_efforts_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE CASCADE,
    CONSTRAINT fk_segment_efforts_segment
        FOREIGN KEY (segment_id) REFERENCES segments(id) ON DELETE CASCADE
);

CREATE INDEX idx_segment_efforts_ride ON segment_efforts(ride_id);
CREATE INDEX idx_segment_efforts_segment ON segment_efforts(segment_id);
CREATE INDEX idx_segment_efforts_user ON segment_efforts(user_id);
CREATE INDEX idx_segment_efforts_score ON segment_efforts(segment_id, effort_score DESC);
```

### 9.2 Achievements Table

**File:** `backend/sql/014_achievements.sql`
```sql
-- User achievements: KOMs, PRs, milestones, badges
CREATE TABLE IF NOT EXISTS achievements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    ride_id UUID,  -- Optional: achievement may not be ride-specific
    segment_id INT,  -- Optional: for segment-based achievements

    -- Achievement details
    achievement_type VARCHAR(50) NOT NULL,
    -- Types: 'kom', 'pr', 'power_record', 'distance_milestone',
    --        'elevation_milestone', 'streak', 'first_ride', 'badge'

    title TEXT NOT NULL,
    description TEXT,

    -- Values
    value FLOAT,  -- Numeric value (e.g., watts, km, count)
    rank INT,  -- For ranked achievements (1 = KOM, etc)

    -- Metadata
    metadata JSONB,

    -- Flags
    is_public BOOLEAN DEFAULT TRUE,
    notified BOOLEAN DEFAULT FALSE,

    created_at TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT fk_achievements_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_achievements_ride
        FOREIGN KEY (ride_id) REFERENCES rides(id) ON DELETE SET NULL
);

CREATE INDEX idx_achievements_user ON achievements(user_id);
CREATE INDEX idx_achievements_type ON achievements(achievement_type);
CREATE INDEX idx_achievements_created ON achievements(created_at DESC);
```

### 9.3 Update Rides Table

**File:** `backend/sql/015_rides_status.sql`
```sql
-- Add processing status and error tracking to rides
ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS processing_status VARCHAR(20) DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS file_type VARCHAR(10),
    ADD COLUMN IF NOT EXISTS dung_minted INT,
    ADD COLUMN IF NOT EXISTS tx_signature VARCHAR(128);

-- Index for status queries
CREATE INDEX IF NOT EXISTS idx_rides_status ON rides(processing_status);
CREATE INDEX IF NOT EXISTS idx_rides_user_status ON rides(user_id, processing_status);
```

---

## Testing Checklist

- [ ] Redis server running and accessible
- [ ] Celery worker starts without errors
- [ ] `/rides/upload` accepts base64 file and returns ride_id
- [ ] Background task is queued in Redis
- [ ] `/rides/{id}/status` returns processing status
- [ ] Activity streams table accepts array data
- [ ] GPS points table accepts batch inserts
- [ ] PostGIS spatial index working
- [ ] All migrations apply cleanly
- [ ] Repository methods return expected data

---

## Deployment Notes

1. **Redis Required:** Must have Redis instance for Celery broker
2. **PostGIS Required:** Supabase includes PostGIS, verify extension enabled
3. **Worker Process:** Need separate process for Celery worker
4. **Environment Variables:**
   - `REDIS_URL` - Redis connection string
   - Existing Supabase vars unchanged
