# Phase 2: Master Coordinator Guide

## Overview

Phase 2 transforms Boulder Rollers into a Strava-like platform with server-side ride processing, activity streams, segment matching, achievements, and enhanced Solana integration.

---

## Phase 1 Recap: What Was Accomplished

### iOS Worker (95% Complete)
- ✅ RideFileParser.swift - GPX/TCX parsing (FIT deferred)
- ✅ StakingSheet.swift - Full staking UI
- ✅ Error alerts in EditProfileView, FitnessSettingsView
- ✅ FTP info button with explanation
- ✅ Debug prints removed, proper logging added
- ✅ "Coming Soon" alert for ride recording

### Backend Worker (100% Complete)
- ✅ Rate limiting on auth endpoints (slowapi)
- ✅ AUTH_SIGNATURE_BYPASS restricted to dev only
- ✅ Real effort score calculation (TSS + duration + elevation)
- ✅ CAL rollback on failure
- ✅ device_id in AuthenticatedUser
- ✅ ride_parser.py (280 lines) - FIT/GPX parsing
- ✅ ride_metrics.py (315 lines) - TSS, NP, calories calculation
- ✅ users.py routes - profile, sessions, username check

### Web Portal Worker (100%+ Complete)
- ✅ CreatePileModal with Mapbox drawing
- ✅ uploadRide function working
- ✅ "Your Piles" filter fixed
- ✅ Mock data replaced with API calls
- ✅ Real Mapbox integration
- ✅ 29+ new components added
- ✅ 13+ new API methods

---

## Phase 2: Strava-like Architecture

### The Transformation

| Aspect | Phase 1 (Current) | Phase 2 (Target) |
|--------|-------------------|------------------|
| File Parsing | Client-side | Server-side (source of truth) |
| Processing | Synchronous | Async (Celery/Redis) |
| Activity Data | Metrics only | Full time-series streams |
| GPS Track | Not utilized | Stored for segment matching |
| Segments | Manual entries | Auto-matched from GPS |
| Achievements | Limited | KOM, PR, milestones, streaks |
| Data Integrity | Low (client can fake) | High (server validates) |

---

## Runbook Files Created

| File | Assigned To | FLAGs |
|------|-------------|-------|
| `PHASE2_BACKEND_INFRASTRUCTURE.md` | Worker 1 | 1, 2, 9 |
| `PHASE2_BACKEND_PROCESSING.md` | Worker 2 | 3, 4, 5, 6 |
| `PHASE2_CLIENT_UPDATES.md` | Worker 3 | 7, 8, 10 |

---

## FLAG Summary

### Backend Infrastructure (Worker 1)
| FLAG | Description | Deliverables |
|------|-------------|--------------|
| 1 | Async Processing | celery_app.py, tasks.py, Redis setup |
| 2 | Activity Streams | activity_streams table, gps_points table |
| 9 | Database Migrations | 011-015.sql migration files |

### Backend Processing (Worker 2)
| FLAG | Description | Deliverables |
|------|-------------|--------------|
| 3 | Ride Processor | ride_processor.py orchestrator |
| 4 | Segment Matching | segment_matcher.py with GPS algo |
| 5 | Achievement Detection | achievement_detector.py |
| 6 | Solana Proofs | proof_builder.py |

### Client Updates (Worker 3)
| FLAG | Description | Deliverables |
|------|-------------|--------------|
| 7 | iOS Raw Upload | Updated APIClient, RideUploadView |
| 8 | Web Raw Upload | Updated RideUploadModal, ActivityChart |
| 10 | New Endpoints | /streams, /gps, /segments, /achievements |

---

## Execution Order

```
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 2A: Backend Infrastructure (Worker 1)                     │
│ - Must complete first                                           │
│ - Creates tables and async infrastructure                       │
│ - ~2-3 hours                                                    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 2B: Backend Processing (Worker 2)                         │
│ - Depends on infrastructure                                     │
│ - Builds processing pipeline                                    │
│ - ~3-4 hours                                                    │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ PHASE 2C: Client Updates (Worker 3)                             │
│ - Depends on backend being complete                             │
│ - Updates iOS and Web                                           │
│ - ~2-3 hours                                                    │
└─────────────────────────────────────────────────────────────────┘
```

**Note:** Workers 1 and 2 could potentially run in parallel if Worker 2 mocks the database calls during development.

---

## Worker Prompts

### Worker 1: Backend Infrastructure

```
You are a backend engineer implementing async processing infrastructure for Boulder Rollers.

Your runbook is at: docs/runbooks/PHASE2_BACKEND_INFRASTRUCTURE.md

Key context:
- Python FastAPI backend at /Users/gabetemp/curahee/BoulderRollers-v2/backend
- Supabase PostgreSQL database (PostGIS enabled)
- Need Redis for Celery job queue
- Existing services: ride_parser.py, ride_metrics.py

Your deliverables (FLAGS 1, 2, 9):
1. Celery configuration (celery_app.py, tasks.py)
2. Modify /rides/upload to queue async job
3. Add /rides/{id}/status endpoint
4. Create activity_streams table
5. Create gps_points table with PostGIS
6. Create segment_efforts and achievements tables
7. Add repository methods for all new tables

Test that:
- Celery worker starts without errors
- Tasks are queued to Redis
- Tables accept data correctly

Do NOT modify client code - that's Worker 3's job.
```

### Worker 2: Backend Processing

```
You are a backend engineer implementing the ride processing pipeline for Boulder Rollers.

Your runbook is at: docs/runbooks/PHASE2_BACKEND_PROCESSING.md

Prerequisites: Worker 1's infrastructure must be complete.

Key context:
- Existing: ride_parser.py (parses FIT/GPX), ride_metrics.py (calculates TSS/NP)
- Need to orchestrate these into a complete pipeline
- Segment matching requires GPS track comparison
- DUNG reward = floor(TSS), max 500

Your deliverables (FLAGS 3, 4, 5, 6):
1. ride_processor.py - Orchestrates full pipeline
2. segment_matcher.py - GPS-based segment matching
3. achievement_detector.py - KOM, PR, milestone detection
4. proof_builder.py - Solana proof creation

The pipeline should:
1. Parse file → extract records
2. Calculate metrics → TSS, NP, calories
3. Store activity streams → power, HR, cadence
4. Store GPS points
5. Match segments → create efforts
6. Detect achievements
7. Deduct CAL, mint DUNG
8. Update ride status to completed

Test with a real GPX file.
```

### Worker 3: Client Updates

```
You are a full-stack engineer updating iOS and Web clients for Boulder Rollers.

Your runbook is at: docs/runbooks/PHASE2_CLIENT_UPDATES.md

Prerequisites: Backend Workers 1 & 2 must be complete.

Key context:
- iOS: /Users/gabetemp/curahee/BoulderRollers-v2/ios
- Web: /Users/gabetemp/curahee/BoulderRollers-v2/web/portal
- Backend now expects raw file upload, not pre-calculated metrics
- Backend processes async - client must poll for status

Your deliverables (FLAGS 7, 8, 10):
1. iOS: Update APIClient.uploadRide() to send base64 file
2. iOS: Update RideUploadView with processing status UI
3. iOS: Add getRideStatus(), getActivityStream(), getAchievements()
4. Web: Update RideUploadModal for async upload
5. Web: Add ActivityChart component for stream visualization
6. Backend: Add endpoint implementations

Key changes:
- Old: Client parses file → sends metrics
- New: Client sends raw file → polls status → displays results

Test full flow: upload file → see processing → view results.
```

---

## Deployment Checklist

### Pre-Deployment
- [ ] Redis instance provisioned
- [ ] PostGIS extension enabled in Supabase
- [ ] All migrations tested locally
- [ ] Celery worker tested locally

### Backend Deployment
```bash
ssh root@STAGING_IP
cd /root/boulder-repo

# Pull latest
git pull

# Install new dependencies
pip install celery redis

# Apply migrations
# (run against Supabase)

# Start Celery worker (in new screen/tmux)
celery -A app.celery_app worker --loglevel=info &

# Restart API
docker restart boulder-api
```

### Client Deployment
- iOS: Build → TestFlight → App Store
- Web: npm run build → Deploy to hosting

---

## Progress Tracking

### Phase 2A: Infrastructure
- [ ] Redis configured
- [ ] Celery app created
- [ ] Tasks defined
- [ ] /rides/upload returns immediately
- [ ] /rides/{id}/status works
- [ ] activity_streams table created
- [ ] gps_points table created
- [ ] segment_efforts table created
- [ ] achievements table created

### Phase 2B: Processing
- [ ] RideProcessor orchestrator works
- [ ] Activity streams stored
- [ ] GPS points stored
- [ ] Segment matching implemented
- [ ] Achievement detection works
- [ ] DUNG minting works
- [ ] Full pipeline end-to-end

### Phase 2C: Clients
- [ ] iOS sends raw file
- [ ] iOS polls for status
- [ ] iOS displays results
- [ ] Web sends raw file
- [ ] Web polls for status
- [ ] Web displays results
- [ ] Activity charts work

---

## Success Criteria

Phase 2 is complete when:
1. User uploads ride file (iOS or Web)
2. Backend processes asynchronously
3. Activity streams are stored and retrievable
4. Segments are auto-matched from GPS
5. Achievements are detected and awarded
6. DUNG is minted based on real TSS
7. User can view all data in app
