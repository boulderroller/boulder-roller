# Duplicate Upload Detection Plan

## Goal
Prevent users from uploading the same workout file multiple times, returning a clear error with a link to the existing ride.

## Current State
- **No duplicate detection exists** - users can upload the same file unlimited times
- **No hash/fingerprint stored** - only parsed metrics
- **No unique constraints** on rides table (only UUID PK)

---

## Recommended Approach: Two-Layer Detection

### Layer 1: File Content Hash (Fast, Exact Duplicates)
**When:** At upload endpoint, before queueing task
**How:** SHA256 hash of raw file bytes
**Catches:** Exact re-uploads of same file

### Layer 2: Timestamp Window Check (Smart, Re-exports)
**When:** During task processing, after parsing `started_at`
**How:** Query rides within ±2 min of start time for same user
**Catches:** Same ride exported from different sources (Garmin Connect vs Wahoo)

---

## Implementation Steps

### Step 1: Database Migration
Add fingerprint column to rides table:
```sql
ALTER TABLE rides ADD COLUMN file_hash VARCHAR(64);
CREATE INDEX idx_rides_user_file_hash ON rides(user_id, file_hash);
```

**File:** `backend/sql/030_ride_dedup.sql`

### Step 2: Update Upload Endpoint
**File:** `backend/app/routes/rides.py` (~line 128)

Before creating ride:
1. Decode `file_data_b64` to bytes
2. Compute `SHA256(bytes).hexdigest()`
3. Query: `SELECT id FROM rides WHERE user_id = ? AND file_hash = ?`
4. If found: Return `409 Conflict` with `existing_ride_id`
5. If not: Continue, pass `file_hash` to task

### Step 3: Update Ride Creation
**File:** `backend/app/repositories.py` - `create_ride()`

Add `file_hash` parameter, store in rides table.

### Step 4: Add Timestamp Window Check
**File:** `backend/app/services/ride_processor.py` (~line 100)

After parsing `started_at`:
1. Query: `SELECT id FROM rides WHERE user_id = ? AND started_at BETWEEN ? AND ? AND id != ?`
2. Window: ±2 minutes
3. If found: Mark as duplicate, return error

### Step 5: Update API Response Models
**File:** `backend/app/models/rides.py`

Add `DuplicateRideError` response model with `existing_ride_id`.

---

## Error Response Format
```json
{
  "error": "duplicate_ride",
  "message": "This workout has already been uploaded",
  "existing_ride_id": "uuid-here",
  "existing_ride_url": "/rides/uuid-here"
}
```

HTTP Status: `409 Conflict`

---

## Files to Modify

| File | Change |
|------|--------|
| `backend/sql/030_ride_dedup.sql` | New migration for `file_hash` column |
| `backend/app/routes/rides.py` | Hash check at upload endpoint |
| `backend/app/repositories.py` | Store `file_hash` in create_ride |
| `backend/app/services/ride_processor.py` | Timestamp window check |
| `backend/app/models/rides.py` | Duplicate error response model |

---

## Edge Cases

1. **Same ride, different file format** (FIT vs GPX export)
   - Layer 1 won't catch (different bytes)
   - Layer 2 catches via timestamp window

2. **Multiple devices recording same ride**
   - Different timestamps, different files
   - Consider this a valid scenario (not duplicate)

3. **User re-uploads after failed processing**
   - Check should exclude `status = 'failed'` rides
   - Allow retry of genuinely failed uploads

4. **Hash collision** (astronomically unlikely)
   - SHA256 has 2^256 possibilities
   - Not a practical concern

---

## Rollback Plan
- Remove `file_hash` column if issues arise
- Feature flag: `ENABLE_DUPE_CHECK=true/false` env var
