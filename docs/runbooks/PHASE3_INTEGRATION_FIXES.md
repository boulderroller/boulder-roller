# Phase 3: Integration Testing & Bug Fixes

## Worker Prompt

```
You are a full-stack engineer fixing integration bugs and testing the Boulder Rollers ride upload pipeline.

## Context
- Infrastructure is ALREADY SET UP: Redis running, Celery worker running, migrations applied
- Phase 2 workers wrote code but couldn't test because infra wasn't ready
- You need to fix 3 bugs and verify E2E flow works

## Your Tasks (Sequential)

### 1. Backend Bug Fix
**File:** `backend/app/services/ride_parser.py`
**Issue:** `ParsedRide` dataclass (around line 57-69) is missing `file_name` field
**Fix:** Add `file_name: Optional[str] = None` after `sport` field

Then sync to server:
```bash
scp backend/app/services/ride_parser.py root@STAGING_IP:/root/boulder-repo/backend/app/services/
ssh root@STAGING_IP "chmod 644 /root/boulder-repo/backend/app/services/ride_parser.py && cd /root/boulder-repo/backend && docker build -t boulder-api . && docker stop boulder-api boulder-celery && docker rm boulder-api boulder-celery && docker run -d --name boulder-api --env-file .env --network host boulder-api && docker run -d --name boulder-celery --env-file .env --network host boulder-api celery -A app.celery_app worker --loglevel=info"
```

### 2. Web Portal Fix 1
**File:** `web/portal/src/hooks/useRides.ts` (line ~27)
**Issue:** Calls `api.uploadRide()` but method is `api.uploadRideFile()`
**Fix:** Change to correct method name

### 3. Web Portal Fix 2
**File:** `web/portal/src/components/HomeTab.tsx` (lines 85-104)
**Issue:** "UPLOAD RIDE" button opens wrong modal
**Fix:** Wire to `RideUploadModal` instead of `RideSummaryModal`

### 4. Verify Web Build
```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2/web/portal && npm run build
```

### 5. E2E Test (if time permits)
- Check Celery logs: `ssh root@STAGING_IP "docker logs boulder-celery --tail 20"`
- Verify services running: `ssh root@STAGING_IP "docker ps"`

## Important Notes
- Server: STAGING_IP
- iOS code is COMPLETE - do not modify
- Backend services already deployed - just fix the one file and rebuild
- Web portal needs the 2 fixes above

## Success Criteria
1. ride_parser.py has file_name field
2. Web build passes with no errors
3. Services restart successfully on server
```

---

## Bug Details

### BUG 1: Missing `file_name` in ParsedRide
**Severity:** LOW
**Location:** `backend/app/services/ride_parser.py:57-69`

The `ParsedRide` dataclass is missing a `file_name` field that `ride_processor.py:213` tries to access:
```python
file_name=getattr(parsed_ride, "file_name", None),  # Always returns None
```

**Fix:**
```python
@dataclass
class ParsedRide:
    # ... existing fields ...
    sport: str = "cycling"
    file_name: Optional[str] = None  # ADD THIS LINE
```

---

### BUG 2: Wrong API Method Name
**Severity:** MEDIUM
**Location:** `web/portal/src/hooks/useRides.ts:27`

Hook calls non-existent method:
```typescript
return api.uploadRide(formData);  // WRONG
```

Should be:
```typescript
return api.uploadRideFile(file);  // CORRECT
```

Note: This hook appears unused, but fix for consistency.

---

### BUG 3: Upload Button Wiring
**Severity:** HIGH
**Location:** `web/portal/src/components/HomeTab.tsx:85-104`

The "UPLOAD RIDE" button opens `RideSummaryModal` (a display modal) instead of the upload modal.

**Fix:** Import and use `RideUploadModal` instead, or add state to trigger upload flow.

---

## Server Reference

```bash
# SSH
ssh root@STAGING_IP

# Check services
docker ps
redis-cli ping

# View logs
docker logs boulder-api --tail 30
docker logs boulder-celery --tail 30

# Full restart after code sync
cd /root/boulder-repo/backend
docker build -t boulder-api .
docker stop boulder-api boulder-celery
docker rm boulder-api boulder-celery
docker run -d --name boulder-api --env-file .env --network host boulder-api
docker run -d --name boulder-celery --env-file .env --network host boulder-api celery -A app.celery_app worker --loglevel=info
```

---

## File Paths

| File | Purpose |
|------|---------|
| `/Users/gabetemp/curahee/BoulderRollers-v2/backend/app/services/ride_parser.py` | ParsedRide dataclass |
| `/Users/gabetemp/curahee/BoulderRollers-v2/web/portal/src/hooks/useRides.ts` | Upload hook |
| `/Users/gabetemp/curahee/BoulderRollers-v2/web/portal/src/components/HomeTab.tsx` | Upload button |
| `/Users/gabetemp/curahee/BoulderRollers-v2/web/portal/src/components/RideUploadModal.tsx` | Correct upload modal |
