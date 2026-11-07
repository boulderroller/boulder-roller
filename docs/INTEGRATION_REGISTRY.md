# Integration Registry - Live Configuration

**Last Updated**: 2026-04-20
**Note:** Legacy programs (`proof_verifier`, `dung_mint`) are archived. Current protocol work uses `boulder_rollers` only.

---

## Solana Programs (Worker 1)

### Deployed Program IDs (Devnet)
- **boulder_rollers**: `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH`
- *(archived)* **proof_verifier**: `Bd3oT5xavVXpYTwYQ8ZbE6VphGt8Pg48aD4sojTwiiaC`
- *(archived)* **dung_mint**: `A1pDYofjye4TUYNLvM3T6rBaDygQasqKmXmgVLjvLCkZ`

### Token Addresses
- **CAL Mint**: `4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh`
- **CAL Mint Authority (PDA)**: `9zepBY6pQ5vzUkRszV22kwLcJPkC5wRiuPkfHv9Y8JNV`
- **DUNG Mint**: `CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk`
- **Treasury Account**: `tU573Uwg8WSB1Sopwb1h2UCFXQAchiqZ6aCtmtK1JkR` (devnet deployer)

### IDL Locations
- **boulder_rollers**: `/protocol/anchor/idl/boulder_rollers.json`
- *(archived)* **dung_mint**: `/archive/legacy/protocol/anchor/idl/dung_mint.json`
- *(archived)* **proof_verifier**: `/archive/legacy/protocol/anchor/idl/proof_verifier.json`

### Current Status
- Programs compile: ✅
- Tests written: ✅ (15 Anchor tests)
- Deployed to devnet: ✅

---

## Backend API (Worker 2)

### Environment Configuration
- **Dev API URL**: `http://[STAGING_LB_IP]` (load balancer port 80 → droplet port 8080)
- **Droplet Direct URL**: `http://[STAGING_IP]:8080` (for SSH debugging)
- **RPC URL**: `https://api.devnet.solana.com`
- **Database URL**: `postgresql://postgres:***@db.qzkqjevawthyboymqrle.supabase.co:5432/postgres` ✅ (Supabase)

### Current Status
- Database migrations applied: ✅ (Supabase)
- Solana client integrated: ✅ (client + token mint wired with IDL loading)
- API deployed: ✅ (Docker on droplet)
- Tests passing: ✅ (14 tests)
- Backend .env configured: ✅

---

## iOS App (Worker 3)

### Configuration
- **Dev API URL**: `http://[STAGING_LB_IP]` (via load balancer port 80)
- **Mapbox Token**: `[MAPBOX_TOKEN]`

### Current Status
- Xcode project created: ✅ (at `ios/BoulderRollers/BoulderRollers.xcodeproj`)
- Dependencies added: ✅ (Kingfisher, TweetNacl via SPM; Solana package removed)
- Auth flow updated: ✅ Implemented nonce/verify JWT flow with token refresh in `ios/BoulderRollers/Services/APIClient.swift`
- Info.plist configured: ✅ (Mapbox token, location permissions, local networking)
- App builds: ✅ (Debug build succeeds via `xcodebuild`, SPM deps resolved; Swift 6 compatible)

---

## Infrastructure (Worker 4)

### Prerequisites (User)
- **DigitalOcean token**: ✅ Provided (in terraform.tfvars)
- **SSH key**: ✅ Uploaded (ID: 52280993)
- **Terraform**: ✅ Installed (v1.14.0)
- **doctl**: ✅ Installed (v1.147.0) and authenticated
- **terraform.tfvars**: ✅ Created in `infrastructure/terraform/dev/`

### Provisioned Resources
- **Dev Droplet IP**: `[STAGING_IP]`
- **Load Balancer IP**: `[STAGING_LB_IP]`
- **Database URL**: `postgresql://postgres:<DB_PASSWORD>@db.qzkqjevawthyboymqrle.supabase.co:5432/postgres`

### Current Status
- Prerequisites complete: ✅
- Infrastructure provisioned: ✅ (dev VPC + droplet + load balancer live)
- Backend deployed: ✅ (container running, env set)
- CI/CD configured: ⏳ PENDING
- Health checks passing: ✅ (`/health/db` via LB 200)

---

## Backend API Contract (FINAL SPEC)

### Authentication
- `POST /auth/nonce` - Get challenge nonce for wallet signature
  - Request: `{ "wallet_address": "string" }`
  - Response: `{ "nonce": "string" }`

- `POST /auth/verify` - Verify wallet signature and issue JWT
  - Request: `{ "wallet_address": "string", "signature": "string", "nonce": "string" }`
  - Response: `{ "access_token": "string", "refresh_token": "string", "user": {...} }`

- `POST /auth/refresh` - Refresh JWT token
  - Request: `{ "refresh_token": "string" }`
  - Response: `{ "access_token": "string", "refresh_token": "string" }`

- `GET /auth/me` - Get current user profile (**NEW - Worker 2 to implement**)
  - Headers: `Authorization: Bearer {token}`
  - Response: `{ "id": "uuid", "wallet_address": "string", "created_at": "timestamp", ... }`

### CAL System
- `GET /cal/balance` - Get user CAL balance and daily mint status
  - Headers: `Authorization: Bearer {token}`
  - Response: `{ "cal_balance": 2500, "can_mint_today": false, "last_mint": "2024-11-27T00:00:00Z", ... }`

- `POST /cal/mint` - Mint 2500 CAL (once per calendar day UTC)
  - Headers: `Authorization: Bearer {token}`
  - Response: `{ "cal_balance": 2500, "transaction_signature": "string", ... }`

### Staking
- `POST /staking/stake` - Stake DUNG in a segment
  - Headers: `Authorization: Bearer {token}`
  - Request: `{ "segment_id": 1, "amount": 1000000000 }`
  - Response: `{ "claim_id": "uuid", "lp_tokens": 1000000000, "transaction_signature": "string", ... }`

- `POST /staking/unstake` - Unstake from a segment
  - Headers: `Authorization: Bearer {token}`
  - Request: `{ "segment_id": 1, "lp_amount": 1000000000 }`
  - Response: `{ "dung_returned": 1000000000, "transaction_signature": "string", ... }`

- `GET /staking/claims` - List user's staking claims
  - Headers: `Authorization: Bearer {token}`
  - Response: `{ "claims": [{ "segment_id": 1, "amount": 1000000000, "lp_tokens": 1000000000, ... }] }`

### Segments
- `GET /segments/list?bbox={minLon},{minLat},{maxLon},{maxLat}` - List segments by bounding box
  - Optional query params: `bbox`, `search`, `limit`, `offset`
  - Response: `{ "segments": [{ "id": 1, "name": "...", "distance_meters": 5000, ... }] }`

- `GET /segments/nearby?lat={lat}&lon={lon}&radius_km={r}` - Get nearby segments (**NEW - Worker 2 to implement as convenience wrapper**)
  - Query params: `lat`, `lon`, `radius_km`
  - Response: `{ "segments": [{ "id": 1, "name": "...", "distance_meters": 5000, "distance_from_user_km": 2.5, ... }] }`

### Rides
- `POST /rides/upload` - Upload ride data (GPX/FIT file or JSON)
  - Headers: `Authorization: Bearer {token}`
  - Request: Multipart form data or JSON with ride details
  - Response: `{ "ride_id": "uuid", "tss": 150, "kcals": 500, ... }`

- `GET /rides` - List user's rides
  - Headers: `Authorization: Bearer {token}`
  - Response: `{ "rides": [{ "id": "uuid", "date": "2024-11-27", "tss": 150, ... }] }`

### Health
- `GET /health/db` - Database connectivity check
  - Response: `{ "status": "healthy" }` or `{ "status": "unhealthy", "error": "..." }`

---

## Integration Checkpoints

### Checkpoint 1: End of Day 1
**Target Date**: TBD

**Worker 1**: Program deployment status
**Worker 2**: Database setup status, local API running
**Worker 3**: Xcode project created, dependencies added
**Worker 4**: Terraform applied, droplet IPs obtained

### Checkpoint 2: End of Day 2
**Target Date**: TBD

**Worker 1**: Program IDs published (CRITICAL - unblocks others)
**Worker 2**: Solana client skeleton ready
**Worker 3**: Mock API layer working, UI tests passing
**Worker 4**: Backend deployed to dev droplet

### Checkpoint 3: End of Day 3
**Target Date**: TBD

**Integration testing begins**:
- Worker 2: Real Solana calls working
- Worker 3: Testing against live backend API
- Full stack flow: iOS → Backend → Solana → Backend → iOS

---

## Update Instructions

**To update this document**:
1. Pull latest from git: `git pull origin main`
2. Edit your worker's section only
3. Update "Last Updated" timestamp at top
4. Commit with message: `chore(integration): Worker [N] updates [what changed]`
5. Push: `git push origin main`

**If merge conflict**:
- Pull latest
- Re-apply your changes
- Commit and push again

**Status Emoji Key**:
- ✅ Complete
- ⏳ In Progress
- ❌ Blocked
- 🔄 Testing
