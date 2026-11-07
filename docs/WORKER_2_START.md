# Worker 2: Backend API Engineer - START HERE

## Your Role
You are the Backend API Engineer for Boulder Rollers V2.

## Your Mission
Complete the FastAPI backend with Solana integration and deploy to dev server.

---

## MVP SCOPE - What to Focus On

Focus on these core features:
- ✅ Authentication (SIWS with nonce-challenge flow)
- ✅ CAL balance tracking and minting
- ✅ Staking claims management
- ✅ Segment discovery and nearby search
- ✅ Ride upload
- ✅ Solana program integration (real transactions)

You do NOT need to implement:
- ❌ Swanny Seats API endpoints
- ❌ Epochs and leaderboard endpoints
- ❌ Reward distribution endpoints
- ❌ Advanced ride processing (GPS matching, TSS calculation) - use simple upload for MVP

---

## Quick Start - Your First 3 Tasks

### Task 1: Read Your Documentation (10 minutes)
1. Read `/docs/WORKER_2_BACKEND_API.md` - Your detailed task breakdown
2. Read `/docs/INTEGRATION_REGISTRY.md` - Coordination document (UPDATE THIS as you work)
3. Read `/docs/schemas.md` - Database schema reference

### Task 2: Verify Current State & Setup Database (30 minutes)
```bash
cd /Users/gabetemp/curahee/BoulderRollers-v2/backend

# Check existing code
ls app/routes/
# You should see: auth.py, cal.py, staking.py, rides.py, segments.py, health.py

# Install dependencies
pip install -r requirements.txt

# Set up database (Supabase or local PostgreSQL)
# Option A: Use Supabase (recommended for dev)
export DATABASE_URL="postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres"

# Option B: Use local PostgreSQL via Docker
docker compose up -d postgres
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/boulderrollers"

# Apply migrations
psql $DATABASE_URL < sql/007_v1_features.sql

# Verify tables created
psql $DATABASE_URL -c "\dt public.*"
# Should see: user_state, claims, swanny_seats, epochs, leaderboard_entries, etc.
```

### Task 3: Run Tests & Start Local API (20 minutes)
```bash
# Run tests
pytest

# Start API locally
uvicorn app.main:app --reload --port 8080

# Test health endpoint
curl http://localhost:8080/health/db
# Should return: {"status": "healthy"}
```

---

## Your Complete Task List

### Phase 1: Foundation (Days 1-2)

**Priority 1 - Database & Dependencies**:
1. Apply database migrations (sql/007_v1_features.sql)
2. Add Solana Python SDK to requirements.txt:
   ```
   solana>=0.30.0
   anchorpy>=0.18.0
   ```
3. Install dependencies and verify tests pass

**Priority 2 - Missing API Endpoints**:
4. Add `GET /auth/me` endpoint - returns current user profile
5. Add `GET /segments/nearby?lat={lat}&lon={lon}&radius_km={r}` - wrapper around existing /segments/list
6. Test both endpoints locally

**Priority 3 - Solana Integration**:
7. Create `app/solana_client.py` module:
   - Load program IDs from environment (use placeholders initially)
   - Load IDLs from `/protocol/anchor/target/idl/*.json`
   - Implement functions:
     - `mint_daily_cal(user_pubkey)` → calls boulder_rollers program
     - `stake_in_segment(user_pubkey, segment_id, amount)` → calls boulder_rollers
     - `unstake_from_segment(user_pubkey, segment_id, lp_amount)` → calls boulder_rollers
8. Replace `StubTokenMintClient` in `app/services/token_mint.py` with real Solana client
9. Update routes to call real Solana client

### Phase 2: Testing & Deployment (Days 3-4)

10. Test all endpoints locally with mock/placeholder program IDs
11. Once Worker 1 publishes program IDs:
    - Update environment variables with real program IDs
    - Update IDL files from Worker 1's commit
    - Test real on-chain transactions to devnet
12. Deploy to Worker 4's dev droplet (get IP from integration registry)
13. Verify deployed API health checks pass
14. Update integration registry with live API URL

---

## Success Criteria

By end of your work, you should have:
- [ ] Database migrations applied successfully
- [ ] All pytest tests passing
- [ ] Solana Python SDK integrated
- [ ] Real Solana transactions working (or graceful errors with good messages)
- [ ] Missing endpoints added (/auth/me, /segments/nearby)
- [ ] API deployed to dev environment
- [ ] Health checks returning 200 OK
- [ ] Integration registry updated with API URL
- [ ] API accessible from public internet

---

## Coordination with Other Workers

### You DEPEND on:
- **Worker 1 (Solana)**: Program IDs and IDL files (soft blocker - you can use placeholders initially)
- **Worker 4 (DevOps)**: Dev droplet IP and database URL (needed for deployment)

### You UNBLOCK:
- **Worker 3 (iOS)**: They need your live API URL to test against

### Your Integration Registry Updates:
Update `/docs/INTEGRATION_REGISTRY.md`:

```markdown
## Backend API (Worker 2)

### Environment Configuration
- **Dev API URL**: `http://[IP]:8080` or `https://dev-api.boulderrollers.com` ← YOUR UPDATE
- **RPC URL**: `https://api.devnet.solana.com`
- **Database URL**: `postgresql://...` ← YOUR UPDATE

### Current Status
- Database migrations applied: ✅ ← YOUR UPDATE
- Solana client integrated: ✅ ← YOUR UPDATE
- API deployed: ✅ ← YOUR UPDATE
- Tests passing: ✅ (X tests) ← YOUR UPDATE
```

Commit with: `git commit -m "chore(integration): Worker 2 - API deployed to dev"`

---

## API Contract - What iOS Expects

Make sure these endpoints work exactly as specified in `/docs/INTEGRATION_REGISTRY.md`:

### Authentication Flow
```
1. iOS: POST /auth/nonce { "wallet_address": "..." }
2. Backend: Return { "nonce": "..." }
3. iOS: Sign nonce with wallet
4. iOS: POST /auth/verify { "wallet_address": "...", "signature": "...", "nonce": "..." }
5. Backend: Return { "access_token": "...", "refresh_token": "...", "user": {...} }
```

### NEW Endpoints You Must Add
- `GET /auth/me` - User profile (iOS expects this)
- `GET /segments/nearby?lat={}&lon={}&radius_km={}` - Convenience wrapper (iOS expects this)

---

## Solana Integration Pattern

### Environment Variables
```bash
# .env file
DATABASE_URL=postgresql://...
JWT_SECRET=your-secret-here
SOLANA_RPC_URL=https://api.devnet.solana.com

# Program IDs (from Worker 1)
BOULDER_ROLLERS_PROGRAM_ID=ABC123...
DUNG_MINT_PROGRAM_ID=DEF456...
PROOF_VERIFIER_PROGRAM_ID=GHI789...

# Token addresses
DUNG_MINT_ADDRESS=JKL012...
```

### Solana Client Skeleton
```python
# app/solana_client.py
import os
import json
from solana.rpc.async_api import AsyncClient
from solana.publickey import PublicKey
from anchorpy import Provider, Wallet, Program

class BoulderRollersClient:
    def __init__(self):
        self.rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
        self.client = AsyncClient(self.rpc_url)

        # Load program ID
        self.program_id = PublicKey(os.getenv("BOULDER_ROLLERS_PROGRAM_ID", "11111111111111111111111111111111"))

        # Load IDL
        idl_path = "../protocol/anchor/target/idl/boulder_rollers.json"
        with open(idl_path) as f:
            self.idl = json.load(f)

    async def mint_daily_cal(self, user_pubkey: str) -> dict:
        # TODO: Construct and send mint_daily_cal transaction
        pass

    async def stake_in_segment(self, user_pubkey: str, segment_id: int, amount: int) -> dict:
        # TODO: Construct and send stake transaction
        pass

# Singleton
solana_client = BoulderRollersClient()
```

---

## Key Commands Reference

### Development
```bash
# Start local API
uvicorn app.main:app --reload --port 8080

# Run tests
pytest
pytest -v  # verbose
pytest tests/test_routes.py::test_mint_daily_cal  # specific test

# Format code
black app/
ruff check app/
```

### Deployment to Worker 4's Droplet
```bash
# Get droplet IP from integration registry
# SSH in
ssh root@[DROPLET_IP]

# Pull latest code
cd /root/boulder-repo
git pull

# Rebuild and restart
cd backend
docker build -t boulder-api:dev .
docker stop boulder-api
docker rm boulder-api
docker run -d --name boulder-api --restart unless-stopped -p 8080:8080 --env-file .env boulder-api:dev

# Check logs
docker logs -f boulder-api
```

---

## Need Help?

### Documentation Resources:
- FastAPI Docs: https://fastapi.tiangolo.com/
- Solana Python: https://michaelhly.com/solana-py/
- Anchorpy: https://kevinheavey.github.io/anchorpy/
- PostgreSQL + PostGIS: https://postgis.net/

### Debug Issues:
- Check `pytest` output for failing tests
- Use `docker logs` to view API logs
- Test endpoints with `curl` or Postman
- Check database connection with `psql`

---

## Communication Protocol

**Daily Update** - Post to integration registry:
```
Worker 2 Status:
✅ Completed: [list]
⏳ In Progress: [current task]
❌ Blocked By: [waiting for Worker 1 program IDs / Worker 4 droplet]
```

**When you deploy API** - Alert in integration registry:
```
🚨 WORKER 2: API deployed at http://[IP]:8080 - iOS can now test!
```

---

**Ready? Start with Task 1: Read your documentation. Good luck! 🚀**
