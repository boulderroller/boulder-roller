# 🎯 BOULDER ROLLERS V2 - PROJECT AUDIT & MVP ROADMAP

**Date:** November 26, 2024
**Status:** Pre-Launch Development
**Target MVP:** 9 Weeks from Start Date

---

## 📊 EXECUTIVE SUMMARY

This document provides a comprehensive audit of the Boulder Rollers v2 project and outlines an exhaustive task list to reach Minimum Viable Product (MVP). The project has **strong foundational code** across all components but requires focused execution to connect the systems and deploy to production.

**Key Findings:**
- ✅ Solana programs compile and implement 8/13 core instructions
- ✅ Backend API has route structure and database schema
- ✅ iOS app has MVVM architecture and core services
- ✅ Infrastructure configurations exist but not deployed
- ❌ Critical gaps: No tests, no integration between systems, no live environments

---

## ✅ CURRENT STATE ASSESSMENT

### **Solana Programs (Worker 1)** - 60% Complete

#### **Working Components**
- ✅ **All 3 programs COMPILE successfully**
  - `proof_verifier` - TSS validation from trusted attesters
  - `dung_mint` - Mints DUNG from verified rides
  - `boulder_rollers` - Segments, staking, epochs, Swannys

- ✅ **Core Account Structures Defined**
  - `UserState` - CAL balance, total rides, TSS, bio_score
  - `SegmentCounter` - Global segment ID generator
  - `Segment` - Geographic data, staking info, metadata
  - `Claim` - User stakes with LP token tracking
  - `SwannySeat` - Curator positions (3 per segment)
  - `Epoch` - Weekly distribution periods with leaderboards
  - `LeaderboardEntry` - Top 10 rider tracking

- ✅ **8 Core Instructions Implemented**
  1. `initialize_user` - Creates UserState PDA with defaults
  2. `mint_daily_cal` - Mints 2500 CAL once per UTC day
  3. `burn_cal_for_segment` - Burns 100 CAL, accumulates to mint DUNG
  4. `initialize_counter` - Creates global segment counter
  5. `create_segment` - Burns 100 DUNG + 0.02 SOL, creates segment
  6. `initialize_segment_lp_mint` - Creates LP token mint per segment
  7. `stake_in_segment` - Stakes DUNG, mints LP tokens pro-rata
  8. `unstake_from_segment` - Burns LP tokens, returns DUNG

#### **Missing Components**
- ❌ No test suite (anchor test empty)
- ❌ Not deployed to devnet/mainnet
- ❌ Missing `record_ride` instruction (leaderboard updates)
- ❌ Missing `close_epoch` instruction (weekly distributions)
- ❌ Missing Swanny seat instructions (claim/release/renew)
- ❌ Missing `harvest_rewards` instruction (claim earnings)
- ❌ Program IDs not finalized

---

### **Backend API (Worker 2)** - 50% Complete

#### **Working Components**
- ✅ **FastAPI Application Structure**
  - Routes: auth, cal, staking, rides, segments, proofs, mint, health
  - Clean separation of concerns with route modules

- ✅ **Database Schema v007 Complete**
  - `user_state` - CAL balance cache
  - `claims` - Staking positions cache
  - `swanny_seats` - Curator positions cache
  - `epochs` - Weekly period tracking
  - `leaderboard_entries` - Top performer cache
  - PostGIS enabled for geographic queries

- ✅ **Core Services**
  - Repository pattern for database access
  - JWT authentication infrastructure
  - Wallet signature verification (SIWS)

- ✅ **API Endpoints Scaffolded**
  - `/cal/balance` - Get user CAL balance
  - `/cal/mint` - Mint daily CAL
  - `/staking/stake` - Stake in segment
  - `/staking/unstake` - Unstake from segment
  - `/staking/claims` - Get user claims

#### **Missing Components**
- ❌ Database migrations NOT APPLIED (no live database)
- ❌ NO SOLANA INTEGRATION (no solana.py client)
- ❌ Ride processing incomplete
  - GPX/FIT parsing not implemented
  - Segment matching algorithm not built
  - TSS calculation missing
- ❌ No background workers for async processing
- ❌ No event listeners for on-chain events
- ❌ Tests failing or incomplete
- ❌ No Solana RPC calls to programs

---

### **iOS App (Worker 3)** - 40% Complete

#### **Working Components**
- ✅ **SwiftUI Project with MVVM Architecture**
  - Clean separation: Views, ViewModels, Services, Models
  - Swift 5.9+, iOS 17+ target

- ✅ **Core Services Implemented**
  - `WalletManager` - Keychain storage, wallet creation
  - `APIClient` - HTTP client with JWT auth
  - `LocationManager` - GPS permissions and tracking

- ✅ **Views Created**
  - `OnboardingView` - Welcome flow
  - `SignInView` - Wallet authentication
  - `ProfileView` - User stats and beetle card placeholder
  - `MapView` - Mapbox integration scaffold
  - `RideUploadView` - File picker scaffold

- ✅ **Design System**
  - Colors: VoidBlack, InternationalOrange, BrushedAluminum, Stucco
  - Typography: Monospace, Body, Title fonts
  - Reusable components: PrimaryButton, OrangeAccentButton, StatCard

- ✅ **Wallet Features**
  - BIP39 seed phrase import capability
  - Keychain secure storage
  - Wallet creation and signing

#### **Missing Components**
- ❌ Mapbox not fully configured (needs access token)
- ❌ Solana.swift NOT INTEGRATED (can't sign blockchain transactions)
- ❌ API calls not tested against live backend
- ❌ No ride recording functionality
- ❌ Segment display on map not working
- ❌ Staking UI not connected to blockchain
- ❌ Beetle card system not implemented (ranks, accessories)
- ❌ No leaderboard display
- ❌ No epoch/distribution UI

---

### **Infrastructure (Worker 4)** - 30% Complete

#### **Working Components**
- ✅ **GitHub Actions Workflows**
  - `backend-ci.yml` - Build, test, deploy backend
  - `ios-ci.yml` - Build and test iOS app
  - `solana-ci.yml` - Build and test Solana programs

- ✅ **Terraform Configurations**
  - Dev environment: 1 API server, managed DB, Redis
  - Prod environment: 3 API servers, DB replica, Redis cluster
  - VPC, load balancer, SSL certificates configured

- ✅ **Docker Compose for Local Dev**
  - PostgreSQL with PostGIS
  - Redis
  - NATS JetStream
  - API service

- ✅ **Monitoring Configs**
  - Prometheus scrape configs
  - Grafana dashboard JSON
  - Loki log aggregation setup
  - Alert rules for API health

#### **Missing Components**
- ❌ NO CLOUD RESOURCES PROVISIONED (everything local only)
- ❌ No dev/staging environment live
- ❌ No monitoring actually deployed
- ❌ CI/CD pipelines not tested
- ❌ No secrets management (Vault/AWS Secrets Manager)
- ❌ No backups configured
- ❌ No CDN setup (Cloudflare)
- ❌ No load testing performed
- ❌ No runbooks documented

---

## ❌ CRITICAL GAPS TO MVP

### **Integration Gaps**
1. **No System Integration** - Backend cannot call Solana programs
2. **No Live Database** - Migrations exist but not applied
3. **No iOS → Backend Connection** - API calls not tested
4. **No iOS → Solana Connection** - Can't sign transactions
5. **No Live Infrastructure** - Everything runs locally only

### **Missing Core Features**
6. **Ride Processing** - No GPS parsing or segment matching
7. **Leaderboards** - No on-chain recording of efforts
8. **Epochs** - No weekly distribution system
9. **Swanny Seats** - Curator system not implemented
10. **Testing** - Zero test coverage on Solana programs

### **Deployment Blockers**
11. **No Devnet Deployment** - Programs not tested on-chain
12. **No Dev Environment** - Can't test full stack remotely
13. **No Monitoring** - Can't observe system health
14. **No CI/CD** - Manual deployment only

---

## 🎯 EXHAUSTIVE TASK LIST TO MVP

**Total Tasks: 167 to MVP + 13 Optional**
**Estimated Timeline: 9 Weeks**

---

## **PHASE 1: FOUNDATION (Week 1-2)**
### Make Core Systems Work

### **P0 - CRITICAL PATH** (Must Do First)

#### **Solana Programs - Deploy & Test**

**Task 1:** Fix any remaining compilation issues
- Status: ✅ Already compiling
- Owner: Solana Engineer
- Estimate: 0 days

**Task 2:** Write comprehensive Anchor tests
- Create `tests/boulder_rollers.ts`
- Test all 8 existing instructions
- Mock token accounts and PDAs
- Owner: Solana Engineer
- Estimate: 2-3 days

**Task 3:** Test CAL minting daily limit
- Verify can mint 2500 CAL once per day
- Verify error when minting twice same day
- Test rollover at UTC midnight
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 4:** Test segment creation with DUNG burning
- Verify 100 DUNG burned from creator
- Verify 0.02 SOL sent to treasury
- Verify segment counter increments
- Test duplicate prevention
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 5:** Test staking LP token math
- Verify 1:1 on first stake
- Verify pro-rata on subsequent stakes
- Test unstaking returns correct DUNG amount
- Owner: Solana Engineer
- Estimate: 1 day

**Task 6:** Generate and verify IDLs
- Run `anchor build -- --features idl-build`
- Verify `target/idl/boulder_rollers.json` created
- Check all instructions present in IDL
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 7:** Deploy to devnet
- Configure Anchor.toml for devnet
- Run `anchor deploy --provider.cluster devnet`
- Document deployed program IDs
- Owner: Solana Engineer
- Estimate: 1 day

**Task 8:** Document program IDs and share with team
- Update README with program IDs
- Share in Slack/Discord
- Update backend .env.example
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 9:** Verify all instructions work on devnet
- Test via Solana Explorer
- Call each instruction manually
- Verify account state changes
- Owner: Solana Engineer
- Estimate: 1 day

---

#### **Backend - Database & Core API**

**Task 10:** Set up PostgreSQL database
- Choose Supabase (recommended) or local PostgreSQL
- Create project and get connection string
- Test connection with psql
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 11:** Apply all 7 SQL migrations
- Run migrations 001-007 in order
- Verify no errors
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 12:** Verify tables created
- Run `\dt public.*` to list tables
- Verify: users, segments, rides, user_state, claims, swanny_seats, epochs, leaderboard_entries
- Check indexes created
- Owner: Backend Engineer
- Estimate: 0.25 days

**Task 13:** Install solana-py and anchorpy
- Add to requirements.txt
- `pip install solana>=0.30.0 anchorpy>=0.18.0`
- Verify imports work
- Owner: Backend Engineer
- Estimate: 0.25 days

**Task 14:** Create SolanaClient service
- Create `app/services/solana_client.py`
- Initialize AsyncClient with RPC URL
- Load wallet keypair from env
- Owner: Backend Engineer
- Estimate: 1 day

**Task 15:** Load IDLs from Worker 1
- Copy `boulder_rollers.json` IDL to backend
- Parse IDL with anchorpy
- Create Program instance
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 16:** Test CAL mint endpoint calling on-chain
- Update `/cal/mint` route
- Build transaction with anchorpy
- Sign and send to devnet
- Parse response and update database cache
- Owner: Backend Engineer
- Estimate: 1 day

**Task 17:** Test staking endpoint
- Update `/staking/stake` route
- Call `stake_in_segment` instruction
- Handle transaction errors
- Update claims table
- Owner: Backend Engineer
- Estimate: 1 day

**Task 18:** Fix failing tests
- Run `pytest`
- Fix any broken tests
- Add new tests for Solana integration
- Owner: Backend Engineer
- Estimate: 1 day

**Task 19:** Run backend locally and verify health
- `uvicorn app.main:app --reload`
- Test `/health` and `/health/db` endpoints
- Verify all routes accessible
- Owner: Backend Engineer
- Estimate: 0.5 days

---

#### **iOS - Connect to Backend**

**Task 20:** Add Solana.Swift package dependency
- File → Add Package Dependencies
- URL: `https://github.com/solana-mobile/Solana.Swift`
- Version: 1.0+
- Owner: iOS Engineer
- Estimate: 0.25 days

**Task 21:** Configure APIClient baseURL
- Point to local backend: `http://localhost:8080`
- Or use ngrok for device testing
- Owner: iOS Engineer
- Estimate: 0.25 days

**Task 22:** Test wallet creation and keychain
- Create new wallet in onboarding
- Verify stored in Keychain
- Restart app and verify persists
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 23:** Test sign-in flow
- Sign authentication message
- Call `/auth/wallet` endpoint
- Store returned JWT
- Verify subsequent API calls include JWT
- Owner: iOS Engineer
- Estimate: 1 day

**Task 24:** Test profile view loading from API
- Call `/users/me` endpoint
- Display user stats (rides, TSS)
- Handle loading and error states
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 25:** Add proper error handling
- Show user-friendly error messages
- Add retry logic for network failures
- Log errors for debugging
- Owner: iOS Engineer
- Estimate: 1 day

---

#### **Infrastructure - Local Dev Environment**

**Task 26:** Document docker-compose setup
- Update README with setup instructions
- Document each service (postgres, redis, nats, api)
- Add troubleshooting section
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 27:** Test full stack locally
- Start Solana localnet validator
- Start docker-compose services
- Run backend API
- Launch iOS simulator
- Test end-to-end flow: create wallet → sign in → mint CAL
- Owner: All Engineers
- Estimate: 1 day

**Task 28:** Create .env.example files
- Backend: DATABASE_URL, JWT_SECRET, SOLANA_RPC_URL, PROGRAM_IDS
- iOS: API_BASE_URL, MAPBOX_TOKEN
- Document all required variables
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 29:** Write setup guide in README
- Prerequisites (Docker, Node, Rust, Xcode)
- Step-by-step setup instructions
- Common issues and solutions
- Owner: DevOps Engineer
- Estimate: 1 day

---

## **PHASE 2: CORE FEATURES (Week 3-5)**
### Build V1 Features

### **P1 - HIGH PRIORITY**

#### **Solana Programs - Epochs & Leaderboards**

**Task 30:** Implement create_epoch instruction
- Create Epoch PDA with segment_id and epoch_number seeds
- Calculate Sunday 00:00 UTC boundaries
- Initialize empty leaderboard Vec
- Owner: Solana Engineer
- Estimate: 1 day

**Task 31:** Implement record_ride instruction
- Accept user, segment_id, time_seconds, tss
- Load current epoch for segment
- Insert into leaderboard (sorted by time_seconds)
- Keep only top 10 entries
- Emit RideRecorded event
- Owner: Solana Engineer
- Estimate: 2 days

**Task 32:** Implement close_epoch instruction
- Check epoch end_time has passed
- Check not already distributed
- Calculate 70% leaderboard distribution (graduated split)
- Calculate 30% claim holder distribution (pro-rata)
- Calculate 10% Swanny distribution (3-way split)
- Emit distribution events (LeaderboardReward, ClaimantPotReady, SwannyReward)
- Set distributed = true
- Owner: Solana Engineer
- Estimate: 2 days

**Task 33:** Add emission events for rewards
- Define event structs
- Emit from close_epoch
- Include: epoch_number, segment_id, user, rank, amount
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 34:** Implement harvest_rewards instruction
- Pull model: user claims their rewards
- Check user in leaderboard or has claims
- Transfer DUNG from segment pot to user
- Mark as harvested to prevent double claim
- Owner: Solana Engineer
- Estimate: 1.5 days

**Task 35:** Write tests for epoch lifecycle
- Test create_epoch
- Test record_ride (multiple entries, sorting, top 10 limit)
- Test close_epoch (distribution math)
- Test harvest_rewards
- Owner: Solana Engineer
- Estimate: 2 days

**Task 36:** Deploy updated programs to devnet
- Build and deploy
- Test on devnet via Explorer
- Document new program IDs
- Owner: Solana Engineer
- Estimate: 1 day

---

#### **Solana Programs - Swanny Seats**

**Task 37:** Implement claim_swanny_seat instruction
- Check seat_index (0, 1, or 2)
- Check seat vacant or expired
- Lock 1000 DUNG from user
- Set holder, locked_at, unlock_at (+ 30 days)
- Transfer DUNG to segment pot
- Owner: Solana Engineer
- Estimate: 1.5 days

**Task 38:** Implement release_swanny_seat instruction
- Check unlock_at has passed
- Transfer 1000 DUNG back to holder
- Set holder = None
- Owner: Solana Engineer
- Estimate: 1 day

**Task 39:** Implement renew_swanny_seat instruction
- Check caller is current holder
- Extend unlock_at by 30 days
- No additional payment required
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 40:** Add Swanny reward distribution to close_epoch
- Check 3 Swanny seats for segment
- Calculate 10% of pot / 3 = reward per Swanny
- Emit SwannyReward events
- Owner: Solana Engineer
- Estimate: 1 day

**Task 41:** Write tests for Swanny mechanics
- Test claiming seat (lock DUNG)
- Test seat expiration
- Test release (unlock DUNG)
- Test renew (extend 30 days)
- Test rewards in close_epoch
- Owner: Solana Engineer
- Estimate: 1.5 days

**Task 42:** Deploy to devnet
- Build and deploy
- Test Swanny flow on devnet
- Owner: Solana Engineer
- Estimate: 0.5 days

---

#### **Backend - Ride Processing**

**Task 43:** Install GPX/FIT parsing libraries
- `pip install gpxpy fitparse shapely`
- Update requirements.txt
- Owner: Backend Engineer
- Estimate: 0.25 days

**Task 44:** Implement GPX file upload and parsing
- Add `/rides/upload` endpoint accepting multipart/form-data
- Parse GPX with gpxpy library
- Extract: lat/lon points, timestamps, elevation
- Calculate distance and elevation gain
- Owner: Backend Engineer
- Estimate: 1 day

**Task 45:** Implement FIT file upload and parsing
- Parse FIT with fitparse library
- Extract: GPS points, HR, power, cadence
- Handle Garmin/Wahoo format differences
- Owner: Backend Engineer
- Estimate: 1 day

**Task 46:** Build segment matcher (GPS polyline intersection)
- Create `app/services/segment_matcher.py`
- Use Shapely LineString for ride polyline
- Query nearby segments with PostGIS (bounding box)
- Check if ride passes within 50m of segment start/end
- Find closest points and calculate time difference
- Owner: Backend Engineer
- Estimate: 3 days

**Task 47:** Calculate ride TSS from power/HR data
- If power data: TSS = (duration * NP * IF) / (FTP * 3600) * 100
- If HR only: estimate from HR zones
- Default to 0 if no sensor data
- Owner: Backend Engineer
- Estimate: 1 day

**Task 48:** Create background worker for ride processing
- Set up NATS JetStream consumer
- Listen for RideUploaded events
- Process ride asynchronously
- Owner: Backend Engineer
- Estimate: 1.5 days

**Task 49:** Implement segment effort detection
- For each matched segment:
  - Create segment_effort record
  - Store: ride_id, segment_id, time_seconds, avg_power, avg_hr
- Owner: Backend Engineer
- Estimate: 1 day

**Task 50:** Call record_ride on-chain for matched segments
- Build transaction with anchorpy
- Call `record_ride` instruction
- Handle errors (epoch not created, etc.)
- Owner: Backend Engineer
- Estimate: 1.5 days

**Task 51:** Update leaderboard cache in database
- Listen to RideRecorded events from blockchain
- Update leaderboard_entries table
- Maintain top 100 in database for fast queries
- Owner: Backend Engineer
- Estimate: 1 day

**Task 52:** Add ride processing status endpoints
- GET `/rides/{ride_id}/status` - Returns: uploaded, processing, completed, failed
- GET `/rides/{ride_id}/segments` - Returns matched segments and times
- Owner: Backend Engineer
- Estimate: 0.5 days

---

#### **Backend - Epochs & Distribution**

**Task 53:** Create cron job for close_epoch
- Set up scheduler (APScheduler or systemd timer)
- Run every Sunday at 00:00 UTC
- For each active segment, call close_epoch
- Owner: Backend Engineer
- Estimate: 1.5 days

**Task 54:** Listen to on-chain distribution events
- Set up WebSocket connection to Solana
- Listen for LeaderboardReward, ClaimantPotReady, SwannyReward events
- Parse event data
- Owner: Backend Engineer
- Estimate: 2 days

**Task 55:** Update leaderboard_entries table
- When close_epoch completes, cache final leaderboard
- Store: segment_id, epoch_number, user_id, rank, time_seconds, reward_amount
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 56:** Cache distribution results
- Update epochs table: distributed = true, total_pot
- Create distributions table for reward tracking
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 57:** Create epoch endpoints
- GET `/epochs/{segment_id}/current` - Returns current epoch info
- GET `/epochs/{segment_id}/{epoch_number}` - Returns past epoch
- GET `/leaderboard/{segment_id}/{epoch_number}` - Returns top 100
- Owner: Backend Engineer
- Estimate: 1 day

---

#### **iOS - Map & Segments**

**Task 58:** Configure Mapbox with access token
- Get token from mapbox.com (free tier)
- Add to Info.plist: MBXAccessToken
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 59:** Display user location on map
- Request location permissions
- Show blue dot on map
- Center map on user location
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 60:** Load nearby segments from API
- Call `/segments/nearby?lat={lat}&lon={lon}&radius_km=10`
- Store in MapViewModel
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 61:** Display segments as polylines on map
- Convert segment start/end to polyline
- Draw on Mapbox layer
- Color by tier (Bronze/Silver/Gold/Platinum/Diamond)
- Owner: iOS Engineer
- Estimate: 1 day

**Task 62:** Implement segment detail sheet
- Tap on segment to show sheet
- Display: name, distance, elevation, total rides
- Owner: iOS Engineer
- Estimate: 1 day

**Task 63:** Show leaderboard in segment detail
- Call `/leaderboard/{segment_id}/current`
- Display top 10 with ranks, usernames, times
- Highlight current user if on board
- Owner: iOS Engineer
- Estimate: 1 day

**Task 64:** Show staking info
- Display: total DUNG staked, user's stake, estimated APY
- Call `/segments/{segment_id}/stats`
- Owner: iOS Engineer
- Estimate: 0.5 days

---

#### **iOS - Ride Recording**

**Task 65:** Implement basic GPS recorder
- Create RideRecordingViewModel
- Start/stop/pause buttons
- Track GPS points with timestamps
- Calculate distance and elevation in real-time
- Owner: iOS Engineer
- Estimate: 2 days

**Task 66:** Save GPX file locally
- Generate GPX XML from recorded points
- Save to app Documents directory
- Owner: iOS Engineer
- Estimate: 1 day

**Task 67:** Upload GPX to backend
- Multipart form upload to `/rides/upload`
- Show upload progress
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 68:** Show upload progress
- Progress bar during upload
- Cancel button
- Error handling
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 69:** Display ride processing status
- Poll `/rides/{ride_id}/status` every 5 seconds
- Show: "Processing... finding segments"
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 70:** Show notification when ride processed
- Use UNUserNotificationCenter
- Notify: "Your ride crossed 3 segments! Tap to view."
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 71:** Display matched segments and times
- Call `/rides/{ride_id}/segments`
- Show list: segment name, your time, rank, delta to leader
- Owner: iOS Engineer
- Estimate: 1 day

---

#### **iOS - Staking UI**

**Task 72:** Build staking interface in segment detail
- Input: amount of DUNG to stake
- Show: LP tokens you'll receive, your new ownership %
- "Stake" button
- Owner: iOS Engineer
- Estimate: 1 day

**Task 73:** Call Solana.swift to build stake transaction
- Create transaction with proper accounts
- Add compute budget instruction
- Owner: iOS Engineer
- Estimate: 1.5 days

**Task 74:** Sign transaction with wallet
- Load keypair from Keychain
- Sign transaction
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 75:** Submit to blockchain
- Send transaction to Solana RPC
- Wait for confirmation
- Handle errors (insufficient funds, slippage)
- Owner: iOS Engineer
- Estimate: 1 day

**Task 76:** Show confirmation and update UI
- Success screen: "Staked X DUNG, received Y LP tokens"
- Refresh segment detail
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 77:** Display user's claims in profile
- Call `/staking/claims`
- Show list: segment name, staked amount, LP tokens, yield
- Owner: iOS Engineer
- Estimate: 1 day

**Task 78:** Build unstaking interface
- Select claim to unstake
- Input: amount of LP tokens to burn
- Show: DUNG you'll receive
- "Unstake" button (similar flow to staking)
- Owner: iOS Engineer
- Estimate: 1 day

---

## **PHASE 3: POLISH & DEPLOY (Week 6-8)**
### Production Ready

### **P2 - MEDIUM PRIORITY**

#### **Solana Programs - Security & Optimization**

**Task 79:** Security audit prep - Add invariant checks
- Check: total distributions == pot amount
- Check: LP token supply == total staked DUNG
- Check: CAL balance never negative
- Owner: Solana Engineer
- Estimate: 1 day

**Task 80:** Use checked_* arithmetic everywhere
- Replace all + - * / with checked_add, checked_sub, checked_mul, checked_div
- Return Overflow/Underflow errors
- Owner: Solana Engineer
- Estimate: 1 day

**Task 81:** Add reentrancy guards
- Ensure no external calls before state updates
- Use checks-effects-interactions pattern
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 82:** Optimize compute units
- Measure with `solana program compute-budget`
- Target <200k CU per instruction
- Optimize: reduce account fetches, use references
- Owner: Solana Engineer
- Estimate: 1.5 days

**Task 83:** Add comprehensive error messages
- Every require!() has descriptive message
- Document all ErrorCode enum variants
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 84:** Document all PDAs and seeds
- Comment each account with derivation
- Create SCHEMAS.md with all PDA derivations
- Owner: Solana Engineer
- Estimate: 0.5 days

**Task 85:** Deploy to mainnet (after audit)
- Generate mainnet deployer keypair
- Fund with SOL
- Deploy all 3 programs
- Initialize global state (counter, config)
- Document mainnet program IDs
- Owner: Solana Engineer + DevOps Engineer
- Estimate: 1 day

---

#### **Backend - Performance & Scaling**

**Task 86:** Add Redis caching for leaderboards
- Cache top 100 leaderboard per segment
- TTL: 1 minute
- Invalidate on new ride recorded
- Owner: Backend Engineer
- Estimate: 1 day

**Task 87:** Add rate limiting
- 100 requests/minute per IP
- Use Redis for distributed rate limit state
- Return 429 Too Many Requests
- Owner: Backend Engineer
- Estimate: 1 day

**Task 88:** Implement connection pooling (PgBouncer)
- Deploy PgBouncer in docker-compose
- Configure transaction mode, max 25 connections
- Update DATABASE_URL to point to PgBouncer
- Owner: Backend Engineer + DevOps Engineer
- Estimate: 0.5 days

**Task 89:** Add database indexes for common queries
- Index: (segment_id, epoch_number, rank) on leaderboard_entries
- Index: (user_id) on claims, rides
- Index: (created_at DESC) on rides
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 90:** Implement segment search (Meilisearch)
- Deploy Meilisearch container
- Index segments by name, location
- Add GET `/segments/search?q={query}` endpoint
- Owner: Backend Engineer
- Estimate: 1.5 days

**Task 91:** Add API response compression
- Enable gzip compression in FastAPI
- Reduce payload size for large lists
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 92:** Load test with k6 (1000 concurrent users)
- Write k6 test script
- Simulate: get segments, upload ride, check leaderboard
- Target: P95 latency <500ms
- Owner: DevOps Engineer + Backend Engineer
- Estimate: 1 day

**Task 93:** Profile slow queries and optimize
- Enable PostgreSQL slow query log (>100ms)
- Analyze with EXPLAIN ANALYZE
- Add indexes or rewrite queries
- Owner: Backend Engineer
- Estimate: 1 day

---

#### **Backend - Anti-Cheat**

**Task 94:** Implement speed cap validation
- Calculate speed between GPS points
- Reject segments if >80 km/h sustained
- Owner: Backend Engineer
- Estimate: 1 day

**Task 95:** Require HR/power data or flag for review
- If no sensor data, mark effort as "unverified"
- Don't award DUNG for unverified efforts
- Owner: Backend Engineer
- Estimate: 0.5 days

**Task 96:** Device fingerprinting
- Extract Garmin device serial from FIT file
- Track device per user
- Flag if device changes frequently
- Owner: Backend Engineer
- Estimate: 1 day

**Task 97:** Segment matching tolerance
- Require ride within 50m of start/end
- Check ride actually traverses segment (not just nearby)
- Owner: Backend Engineer
- Estimate: 0.5 days

---

#### **iOS - Polish**

**Task 98:** Add animations and transitions
- Fade in/out for views
- Slide transitions for sheets
- Smooth map animations
- Owner: iOS Engineer
- Estimate: 1.5 days

**Task 99:** Implement offline mode
- Cache segments in Core Data
- Allow viewing cached segments when offline
- Queue uploads for when online
- Owner: iOS Engineer
- Estimate: 2 days

**Task 100:** Add pull-to-refresh on profile
- Refresh user stats
- Refresh claims
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 101:** Improve error messages
- User-friendly text for all errors
- "Something went wrong" → "Couldn't connect to server"
- Owner: iOS Engineer
- Estimate: 1 day

**Task 102:** Add loading skeletons
- Shimmer effect while loading segments
- Placeholder cards for leaderboard
- Owner: iOS Engineer
- Estimate: 1 day

**Task 103:** Implement segment creation flow
- Draw on map by tapping start and end points
- Enter: name, description, upload photo
- Call `/segments/create` endpoint
- Owner: iOS Engineer
- Estimate: 2 days

**Task 104:** Add search segments by name
- Search bar in map view
- Call `/segments/search?q={query}`
- Display results list
- Owner: iOS Engineer
- Estimate: 1 day

**Task 105:** Build beetle card display
- SVG or PNG beetle asset
- Display rank badge (C/B/A/S/SS)
- Placeholder accessories
- Owner: iOS Engineer
- Estimate: 2 days

**Task 106:** Show CAL balance in header
- Display: "CAL: 2500 / 2500"
- Update in real-time after burn
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 107:** Add daily CAL mint button
- Big orange button in profile: "Claim Today's CAL"
- Disabled if already minted
- Show countdown to next mint
- Owner: iOS Engineer
- Estimate: 1 day

---

#### **iOS - Testing & Deployment**

**Task 108:** Write unit tests for ViewModels
- Test MapViewModel segment loading
- Test ProfileViewModel state management
- Test WalletManager keychain operations
- Owner: iOS Engineer
- Estimate: 2 days

**Task 109:** Write UI tests for critical flows
- Test: onboarding → wallet creation → sign in
- Test: map → segment detail → stake
- Test: ride recording → upload
- Owner: iOS Engineer
- Estimate: 2 days

**Task 110:** Test on physical devices
- iPhone 13, 14, 15 (different screen sizes)
- Test GPS accuracy
- Test background recording
- Owner: iOS Engineer
- Estimate: 1 day

**Task 111:** Create App Store screenshots
- 6.7", 6.5", 5.5" screen sizes
- Show: map, segment detail, profile, ride recording
- Owner: iOS Engineer + Designer
- Estimate: 0.5 days

**Task 112:** Write App Store description
- Title: "Boulder Rollers - Cycling Segments"
- Subtitle: "Compete, stake, earn on your favorite climbs"
- Description with features
- Owner: iOS Engineer + Product
- Estimate: 0.5 days

**Task 113:** Submit to TestFlight
- Create App Store Connect listing
- Upload build via Xcode
- Invite internal testers
- Owner: iOS Engineer
- Estimate: 0.5 days

**Task 114:** Beta test with 10-20 users
- Send TestFlight invites
- Collect feedback via form
- Monitor crashes in App Store Connect
- Owner: iOS Engineer + Product
- Estimate: 1 week (parallel with other tasks)

**Task 115:** Fix critical bugs from beta
- Prioritize crashes and blockers
- Update TestFlight build
- Owner: iOS Engineer
- Estimate: 2 days

**Task 116:** Submit to App Store
- Request App Review
- Fill privacy questionnaire
- Submit for review
- Owner: iOS Engineer
- Estimate: 0.5 days

---

#### **Infrastructure - Production Deployment**

**Task 117:** Choose cloud provider
- Recommended: DigitalOcean (simplicity, cost)
- Alternatives: AWS (enterprise), GCP (scaling)
- Owner: DevOps Engineer
- Estimate: 0.25 days

**Task 118:** Create DigitalOcean account and API token
- Sign up at digitalocean.com
- Add payment method
- Generate API token (read + write)
- Store securely (1Password, env variable)
- Owner: DevOps Engineer
- Estimate: 0.25 days

**Task 119:** Provision dev environment (Terraform)
- cd infrastructure/terraform/dev
- terraform init
- terraform plan (review resources)
- terraform apply
- Resources: 1 API droplet, 1 managed Postgres DB, 1 Redis, 1 load balancer
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 120:** Configure DNS (dev-api.boulderrollers.com)
- Add A record pointing to load balancer IP
- Or use DigitalOcean DNS
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 121:** Set up SSL certificates (Let's Encrypt)
- Use DigitalOcean managed certificates
- Or Certbot on load balancer
- Verify HTTPS working
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 122:** Deploy backend to dev environment
- SSH into droplet
- Clone repo or pull Docker image
- Create .env file with production secrets
- docker-compose up -d
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 123:** Configure secrets
- JWT_SECRET (generate with openssl rand -base64 32)
- DATABASE_URL from Terraform output
- SOLANA_RPC_URL (devnet or mainnet)
- PROGRAM_IDS from Worker 1
- Owner: DevOps Engineer + Backend Engineer
- Estimate: 0.5 days

**Task 124:** Test dev environment thoroughly
- curl https://dev-api.boulderrollers.com/health
- Test all endpoints
- Upload ride, create segment, stake
- Owner: DevOps Engineer + Backend Engineer
- Estimate: 1 day

---

**Task 125:** Provision prod environment (Terraform)
- cd infrastructure/terraform/prod
- terraform init && terraform plan
- terraform apply
- Resources: 3 API droplets, managed Postgres (with replica), Redis cluster, load balancer
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 126:** Configure DNS (api.boulderrollers.com)
- Add A record to load balancer
- Enable Cloudflare proxy (orange cloud)
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 127:** Set up load balancer with health checks
- Health check: GET /health every 10s
- Remove unhealthy droplets from pool
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 128:** Configure backups (daily DB dumps to S3)
- Create S3 bucket or DigitalOcean Spaces
- Write backup script (pg_dump, gzip, upload)
- Cron: 0 2 * * * (2 AM daily)
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 129:** Deploy backend to prod
- SSH into each of 3 droplets
- Deploy with docker-compose
- Verify all 3 servers healthy
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 130:** Run smoke tests
- curl https://api.boulderrollers.com/health
- Test key endpoints
- Verify database connectivity
- Check logs for errors
- Owner: DevOps Engineer + Backend Engineer
- Estimate: 0.5 days

---

#### **Infrastructure - Monitoring**

**Task 131:** Deploy Prometheus on monitoring server
- Create separate droplet or container
- Configure scrape targets (3 API servers, Postgres, Redis)
- Expose on port 9090
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 132:** Deploy Grafana with dashboards
- Deploy Grafana container
- Add Prometheus data source
- Import Boulder Rollers dashboard JSON
- Create panels: request rate, error rate, latency, DB query time
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 133:** Deploy Loki for log aggregation
- Deploy Loki container
- Deploy Promtail on each API server
- Configure log shipping from /var/log/boulder/*.log
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 134:** Set up alerts
- Alert rules: API down, high error rate (>5%), high latency (P95 >1s), DB down
- Configure alert routing
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 135:** Configure PagerDuty for on-call
- Create PagerDuty account
- Add integration with Prometheus Alertmanager
- Set up escalation policy
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 136:** Document runbooks
- Runbook: API server down (symptoms, diagnosis, resolution)
- Runbook: Database failure (promote replica, restore backup)
- Runbook: High latency (check logs, scale up, rollback)
- Owner: DevOps Engineer
- Estimate: 1 day

**Task 137:** Test disaster recovery procedure
- Simulate: API server crash, database failure
- Follow runbooks to recover
- Measure RTO (Recovery Time Objective)
- Owner: DevOps Engineer
- Estimate: 0.5 days

---

#### **Infrastructure - CI/CD**

**Task 138:** Configure GitHub Actions secrets
- Add to repo secrets: DO_TOKEN, DO_SSH_KEY, DEV_DROPLET_IP, PROD_DROPLET_IP
- Add: DOCKER_USERNAME, DOCKER_PASSWORD (if using Docker Hub)
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 139:** Test backend CI/CD pipeline
- Push commit to backend/
- Verify: tests run, Docker image built, deployed to dev
- Owner: DevOps Engineer + Backend Engineer
- Estimate: 0.5 days

**Task 140:** Test Solana CI/CD pipeline
- Push commit to protocol/anchor/
- Verify: programs build, tests run, deploy to devnet
- Owner: DevOps Engineer + Solana Engineer
- Estimate: 0.5 days

**Task 141:** Test iOS CI pipeline
- Push commit to ios/
- Verify: Xcode build succeeds, tests run
- Owner: DevOps Engineer + iOS Engineer
- Estimate: 0.5 days

**Task 142:** Implement automated deployments to dev
- On push to main: auto-deploy backend to dev
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 143:** Implement manual deployments to prod
- Use workflow_dispatch trigger
- Require manual approval
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 144:** Add deployment notifications
- Post to Slack/Discord when deployment completes
- Include: commit SHA, deployer, environment
- Owner: DevOps Engineer
- Estimate: 0.5 days

---

## **PHASE 4: LAUNCH (Week 9)**
### Go Live

### **P3 - LAUNCH CHECKLIST**

#### **Pre-Launch (1 week before)**

**Task 145:** All tests passing
- Solana: anchor test (all green)
- Backend: pytest (all green)
- iOS: XCTest (all green)
- Owner: All Engineers
- Estimate: Ongoing

**Task 146:** Load testing complete
- k6 test with 1000 concurrent users
- Sustained for 10 minutes
- P95 latency <500ms, error rate <1%
- Owner: DevOps Engineer + Backend Engineer
- Estimate: 1 day

**Task 147:** Security scan clean
- Run OWASP ZAP against API
- Fix any critical/high vulnerabilities
- Owner: Backend Engineer + DevOps Engineer
- Estimate: 1 day

**Task 148:** Backups configured and tested
- Verify daily backups running
- Test restore procedure
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 149:** Monitoring and alerts working
- Verify all dashboards show data
- Test alerts (manually trigger, verify PagerDuty fires)
- Owner: DevOps Engineer
- Estimate: 0.5 days

**Task 150:** DNS configured
- api.boulderrollers.com resolves
- dev-api.boulderrollers.com resolves
- Owner: DevOps Engineer
- Estimate: 0.25 days

**Task 151:** SSL certificates valid
- HTTPS working on both domains
- A+ rating on ssllabs.com
- Owner: DevOps Engineer
- Estimate: 0.25 days

**Task 152:** Prepare marketing materials
- Twitter announcement thread
- Discord welcome message
- Website landing page (optional)
- Owner: Product Manager
- Estimate: 1 day

---

#### **Launch Day**

**Task 153:** Deploy programs to mainnet
- anchor deploy --provider.cluster mainnet
- Initialize global state (counter, configs)
- Verify via Solana Explorer
- Owner: Solana Engineer
- Estimate: 2 hours

**Task 154:** Deploy backend to production
- Pull latest Docker image
- docker-compose up -d on all 3 servers
- Verify health checks
- Owner: DevOps Engineer
- Estimate: 1 hour

**Task 155:** Submit iOS app (or release TestFlight)
- If App Store approved: release to public
- If not: release TestFlight to broader beta
- Owner: iOS Engineer
- Estimate: 0.5 hours

**Task 156:** Smoke test all endpoints
- Test auth, ride upload, segment creation, staking
- Owner: All Engineers
- Estimate: 1 hour

**Task 157:** Monitor dashboards for 2 hours
- Watch request rate, error rate, latency
- Check logs for errors
- Have rollback plan ready
- Owner: All Engineers
- Estimate: 2 hours

**Task 158:** Execute initial airdrop
- Script to airdrop 5000 DUNG to 1000 early users
- Owner: Solana Engineer + Product Manager
- Estimate: 1 hour

**Task 159:** Create first 20 segments (iconic climbs)
- Manually create: Alpe d'Huez, Mont Ventoux, etc.
- Or script it
- Owner: Product Manager + Backend Engineer
- Estimate: 2 hours

**Task 160:** Announce on Twitter/Discord
- "Boulder Rollers is live! 🪲"
- Link to TestFlight or App Store
- Owner: Product Manager
- Estimate: 0.5 hours

**Task 161:** Monitor error logs closely
- tail -f /var/log/boulder/api.log
- Watch for crashes, exceptions
- Owner: All Engineers
- Estimate: 4 hours (rest of day)

---

#### **Post-Launch (1 week after)**

**Task 162:** Review error logs daily
- Check for patterns
- Fix critical bugs
- Owner: All Engineers
- Estimate: 1 hour/day

**Task 163:** Check performance metrics
- Review Grafana dashboards
- Identify bottlenecks
- Owner: Backend Engineer + DevOps Engineer
- Estimate: 0.5 hours/day

**Task 164:** Address user-reported issues
- Triage GitHub issues or support tickets
- Fix high-priority bugs
- Owner: All Engineers
- Estimate: 2 hours/day

**Task 165:** Scale up if needed
- If CPU >80%: add more API servers (terraform apply -var="api_count=5")
- If DB slow: add read replicas
- Owner: DevOps Engineer
- Estimate: As needed

**Task 166:** Collect user feedback
- Survey beta users
- Monitor Discord/Twitter for complaints/suggestions
- Owner: Product Manager
- Estimate: 1 hour/day

**Task 167:** Plan V2 features based on usage
- Analyze: which features used most, which ignored
- Prioritize roadmap
- Owner: Product Manager + All Engineers
- Estimate: 1 day (end of week)

---

## **OPTIONAL ENHANCEMENTS (Post-MVP)**

### **P4 - NICE TO HAVE**

#### **Advanced Features**

**Task 168:** Beetle card accessory system
- 8 categories: Boulder, Legs, Trail, Claims/Flags, Headgear, Background, Aura, Scars
- Earn via achievements (hidden triggers)
- Owner: Backend Engineer + iOS Engineer
- Estimate: 2 weeks

**Task 169:** Coherence algorithm for ranking
- Calculate rank (C/B/A/S/SS) based on accessory coherence
- Algorithm: thematic match, achievement progression, rarity balance
- Owner: Backend Engineer
- Estimate: 1 week

**Task 170:** Bio-Passport anti-cheat
- Build Critical Power model from user's ride history
- Flag anomalies (impossible power, inconsistent with CP curve)
- Owner: Backend Engineer
- Estimate: 2 weeks

**Task 171:** Tribunal system
- Swannys vote Clean/Doped on flagged rides
- 2/3 majority required
- Owner: Backend Engineer + Solana Engineer
- Estimate: 1 week

**Task 172:** Harberger tax on Swanny seats
- Allow anyone to "buy out" a Swanny by paying 2x locked amount
- Previous holder gets 1.5x back
- Owner: Solana Engineer
- Estimate: 1 week

**Task 173:** User-created challenges
- Create custom competitions (e.g., "Most elevation in July")
- Entry fee in DUNG, winner takes pot
- Owner: Backend Engineer + Solana Engineer
- Estimate: 2 weeks

**Task 174:** Social features
- Follow riders, comment on efforts, like rides
- Activity feed
- Owner: Backend Engineer + iOS Engineer
- Estimate: 2 weeks

**Task 175:** Segment discovery
- AI-suggested routes based on user's past rides
- "You might like this climb..."
- Owner: Backend Engineer
- Estimate: 1 week

**Task 176:** Strava OAuth integration
- Import rides automatically from Strava
- Owner: Backend Engineer + iOS Engineer
- Estimate: 1 week

**Task 177:** Training plans
- AI-generated plans based on user's goal (e.g., "FTP +20w in 8 weeks")
- Owner: Backend Engineer + iOS Engineer
- Estimate: 3 weeks

**Task 178:** Coaching marketplace
- Coaches offer services in DUNG
- Owner: Backend Engineer + iOS Engineer + Solana Engineer
- Estimate: 3 weeks

**Task 179:** Team/club features
- Create clubs, group leaderboards, club challenges
- Owner: Backend Engineer + iOS Engineer + Solana Engineer
- Estimate: 2 weeks

**Task 180:** Virtual rides (Zwift integration)
- Support indoor rides on virtual segments
- Owner: Backend Engineer + iOS Engineer
- Estimate: 3 weeks

---

## 📋 WORK BREAKDOWN BY ROLE

### **Solana Engineer (Blockchain Developer)**
**Tasks:** 1-9, 30-42, 79-85, 153, 158
**Total:** 45 tasks
**Estimated Duration:** 6-8 weeks
**Critical Path Items:** 1-9, 30-36

**Key Deliverables:**
- All instructions implemented and tested
- Programs deployed to devnet and mainnet
- IDLs published and shared with team
- Comprehensive test suite (>80% coverage)

---

### **Backend Engineer (API Developer)**
**Tasks:** 10-19, 43-57, 86-97, 122-124, 129-130, 154, 156, 159, 162-164
**Total:** 50 tasks
**Estimated Duration:** 7-9 weeks
**Critical Path Items:** 10-19, 43-52

**Key Deliverables:**
- Database migrations applied
- Solana integration working
- Ride processing pipeline functional
- All API endpoints tested and documented
- Performance benchmarks met

---

### **iOS Engineer (Mobile Developer)**
**Tasks:** 20-25, 58-78, 98-118, 155, 161
**Total:** 55 tasks
**Estimated Duration:** 8-10 weeks
**Critical Path Items:** 20-25, 58-71

**Key Deliverables:**
- App submitted to App Store
- Core flows working: onboarding, ride recording, staking
- TestFlight beta completed
- 100% crash-free rate

---

### **DevOps Engineer (Infrastructure)**
**Tasks:** 26-29, 88, 92, 117-151, 157, 160, 165
**Total:** 30 tasks
**Estimated Duration:** 5-7 weeks
**Critical Path Items:** 26-29, 119-124

**Key Deliverables:**
- Dev and prod environments provisioned
- CI/CD pipelines operational
- Monitoring and alerting configured
- Disaster recovery tested
- Infrastructure as code (Terraform)

---

### **Product Manager / All Hands**
**Tasks:** 145-152, 160, 166-167, 168-180 (optional)
**Total:** 20 launch tasks + 13 optional enhancements
**Estimated Duration:** Launch week coordination + ongoing feature planning

**Key Deliverables:**
- Launch checklist completed
- Marketing materials ready
- User feedback collected
- V2 roadmap prioritized

---

## 🚀 RECOMMENDED EXECUTION STRATEGY

### **Critical Path (Must Complete in Order)**
1. **Week 1-2:** Solana tests + Backend database setup + iOS-backend connection
2. **Week 3-4:** Epochs & leaderboards + Ride processing + Map UI
3. **Week 5-6:** Swanny seats + Performance optimization + Polish
4. **Week 7-8:** Production deployment + Security hardening + Beta testing
5. **Week 9:** Launch preparation + Go live + Monitor

### **Parallel Work Streams**
- **Solana Engineer** can work independently on instructions and tests
- **Backend Engineer** can start ride processing while waiting for Solana devnet deployment
- **iOS Engineer** can build UI while backend builds API (use mock data)
- **DevOps Engineer** can provision infrastructure in parallel with dev work

### **Integration Points (Synchronization Required)**
1. **Week 2:** Solana deploys to devnet → Backend integrates → iOS tests
2. **Week 5:** Backend API stable → iOS connects → End-to-end testing
3. **Week 7:** All components ready → Deploy to staging → Full system test
4. **Week 9:** Final integration → Deploy to production → Launch

### **Risk Mitigation**
- **Blocker:** Solana programs don't deploy to devnet
  - **Mitigation:** Use localnet validator, mock blockchain responses in backend
- **Blocker:** Ride matching algorithm inaccurate
  - **Mitigation:** Start with simple bounding box, iterate with user feedback
- **Blocker:** iOS App Store rejection
  - **Mitigation:** Start TestFlight early, have beta ready as backup
- **Blocker:** Infrastructure costs exceed budget
  - **Mitigation:** Start with minimal resources, scale only as needed

---

## 📊 SUCCESS METRICS

### **Week 1 (Launch)**
- ✅ 100 users onboarded
- ✅ 50 segments created
- ✅ 200 rides uploaded
- ✅ 0 critical bugs (P0)
- ✅ <1% error rate
- ✅ P95 latency <500ms

### **Month 1**
- 🎯 1,000 active users (WAU)
- 🎯 500 segments
- 🎯 5,000 rides
- 🎯 10,000 DUNG staked
- 🎯 50% retention (Day 30)

### **Month 3**
- 🎯 10,000 active users
- 🎯 2,000 segments
- 🎯 50,000 rides
- 🎯 100,000 DUNG staked
- 🎯 First epoch distributions completed
- 🎯 Swanny seats filled on top segments

### **Month 6**
- 🎯 50,000 active users
- 🎯 10,000 segments
- 🎯 500,000 rides
- 🎯 1M DUNG staked
- 🎯 $0.01+ DUNG price
- 🎯 $500k+ market cap

---

## 💰 BUDGET ESTIMATE (First 6 Months)

### **Infrastructure**
- DigitalOcean (Dev): $50/month × 6 = $300
- DigitalOcean (Prod): $200/month × 6 = $1,200
- Domain/DNS: $20/year = $20
- SSL Certificates: $0 (Let's Encrypt)
- Monitoring (Grafana Cloud): $0-50/month = $300
- **Subtotal:** $1,820

### **Third-Party Services**
- Solana RPC (Helius/QuickNode): $50/month × 6 = $300
- Mapbox (free tier): $0
- Apple Developer: $99/year = $99
- **Subtotal:** $399

### **Initial Token Supply**
- Airdrop (1000 users × 5000 DUNG): Minted on-chain
- Initial LP (5 SOL + 1M DUNG): ~$1,000
- **Subtotal:** $1,000

### **Total Budget:** ~$3,200 for 6 months

---

## 🎯 NEXT STEPS (Start Today)

### **Immediate Actions (This Week)**

1. **Solana Engineer:**
   - Start writing Anchor tests (Task 2)
   - Target: 15 test cases by end of week

2. **Backend Engineer:**
   - Set up Supabase or local PostgreSQL (Task 10)
   - Apply migrations (Task 11)
   - Start Solana client skeleton (Task 14)

3. **iOS Engineer:**
   - Add Solana.Swift dependency (Task 20)
   - Test wallet creation flow (Task 22)
   - Configure API client for localhost (Task 21)

4. **DevOps Engineer:**
   - Document docker-compose setup (Task 26)
   - Test full local stack (Task 27)
   - Create .env.example files (Task 28)

5. **Product Manager:**
   - Review this roadmap with team
   - Create project board (GitHub Projects or Jira)
   - Schedule daily standups (15 min, async OK)

### **Communication**
- Create shared Slack/Discord channel
- Daily updates: "What I did, what I'm doing, blockers"
- Weekly sync: Friday 4pm - review progress, plan next week
- Document decisions in GitHub Discussions

### **Decision Points**
- **Week 2:** Go/No-Go on devnet deployment
- **Week 5:** Go/No-Go on production deployment
- **Week 8:** Go/No-Go on public launch (vs. extended beta)

---

## 📚 APPENDIX

### **Key Documents**
- `/docs/BOULDER_ROLLERS_V1_SPEC.md` - Product specification
- `/docs/schemas.md` - On-chain account schemas
- `/docs/WORKER_INSTRUCTIONS.md` - Original task breakdown
- `/protocol/anchor/README.md` - Solana program docs
- `/backend/README.md` - API documentation
- `/ios/README.md` - iOS app setup

### **Reference Links**
- Anchor Framework: https://www.anchor-lang.com/
- Solana Cookbook: https://solanacookbook.com/
- FastAPI: https://fastapi.tiangolo.com/
- SwiftUI: https://developer.apple.com/xcode/swiftui/
- Terraform: https://www.terraform.io/docs
- Grafana: https://grafana.com/docs/

### **Contact**
- GitHub: https://github.com/boulderrollers/boulderrollers-v2
- Discord: https://discord.gg/boulderrollers
- Twitter: @BoulderRollers

---

**End of Document**
**Version:** 1.0
**Last Updated:** November 26, 2024
**Next Review:** Weekly during development
