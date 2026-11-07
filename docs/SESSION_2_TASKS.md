# Session 2 Tasks - Exhaustive Todo List

**Date:** 2024-11-28
**Prerequisites:** User has completed `/docs/USER_ACTION_REQUIRED.md`
**Goal:** Deploy all components and achieve end-to-end MVP functionality

---

## Task Priority Legend

- **P0** = Critical blocking task (must complete first)
- **P1** = High priority (needed for integration)
- **P2** = Medium priority (polish/optimization)
- **P3** = Low priority (nice to have)

---

## 👤 USER Pre-Session Tasks

**Before resuming workers, verify:**

- [ ] DigitalOcean account created + API token generated
- [ ] Terraform + doctl installed via Homebrew
- [ ] SSH key generated and uploaded to DO (ID noted)
- [ ] terraform.tfvars file created with credentials
- [ ] Xcode project created at ios/BoulderRollers.xcodeproj
- [ ] (Optional) Supabase project created
- [ ] (Optional) Mapbox token obtained

---

## Worker 1: Solana Programs - 12 Tasks

### Phase 1: Deployment Preparation (P0)

**Task 1.1:** Verify Test Suite Status
- Run: `cd protocol/anchor && anchor test`
- Confirm all 13 tests passing
- Document any warnings (SPL token-2022 clock warnings are OK)
- **Time:** 5 minutes
- **Blocker:** None

**Task 1.2:** Decision on Token-2022 Feature
- Review anchor-spl Cargo.toml configuration
- Decision: Keep or remove `token_2022` feature
- If keeping: Document that warnings are expected
- If removing: Update Cargo.toml, rebuild, retest
- **Time:** 10 minutes
- **Blocker:** None

**Task 1.3:** Configure Anchor for Devnet
- Check Anchor.toml cluster settings
- Verify program IDs are declared
- Set Solana CLI to devnet: `solana config set --url https://api.devnet.solana.com`
- **Time:** 5 minutes
- **Blocker:** None

### Phase 2: Devnet Deployment (P0)

**Task 1.4:** Airdrop SOL for Deployment
- Check balance: `solana balance`
- If < 5 SOL: `solana airdrop 2`  (repeat 2-3 times)
- Verify sufficient balance for deployment
- **Time:** 5 minutes
- **Blocker:** None

**Task 1.5:** Deploy proof_verifier Program
- Run: `anchor deploy --program-name proof_verifier --provider.cluster devnet`
- Note program ID from output
- Verify deployment: `solana program show <PROGRAM_ID>`
- **Time:** 10 minutes
- **Blocker:** Task 1.4 (needs SOL)

**Task 1.6:** Deploy dung_mint Program
- Run: `anchor deploy --program-name dung_mint --provider.cluster devnet`
- Note program ID from output
- Verify deployment
- **Time:** 10 minutes
- **Blocker:** Task 1.5 (depends on proof_verifier)

**Task 1.7:** Deploy boulder_rollers Program
- Run: `anchor deploy --program-name boulder_rollers --provider.cluster devnet`
- Note program ID from output
- Verify deployment
- **Time:** 10 minutes
- **Blocker:** Task 1.4 (needs SOL)

### Phase 3: Token Setup (P0)

**Task 1.8:** Create DUNG SPL Token Mint
- Run: `spl-token create-token --decimals 9`
- Save mint address
- Verify: `spl-token display <MINT_ADDRESS>`
- **Time:** 5 minutes
- **Blocker:** Task 1.4 (needs SOL)

**Task 1.9:** Set DUNG Mint Authority
- Calculate dung_mint PDA (use anchor test helper or manual calculation)
- Run: `spl-token authorize <MINT_ADDRESS> mint <PDA_ADDRESS>`
- Verify authority changed
- **Time:** 15 minutes
- **Blocker:** Task 1.6, 1.8

**Task 1.10:** Create Treasury Account
- Determine treasury address from boulder_rollers code
- If PDA: Document seeds
- If keypair: Generate and save securely
- **Time:** 10 minutes
- **Blocker:** None

### Phase 4: Documentation (P1)

**Task 1.11:** Update Integration Registry
- Edit `/docs/INTEGRATION_REGISTRY.md`
- Update Solana Programs section with:
  - proof_verifier program ID
  - dung_mint program ID
  - boulder_rollers program ID
  - DUNG mint address
  - Treasury account address
- Change status to ✅ Deployed
- Commit and push
- **Time:** 10 minutes
- **Blocker:** Tasks 1.5, 1.6, 1.7, 1.8, 1.10

**Task 1.12:** Re-generate IDLs (P2)
- Run: `anchor build --idl`
- Verify IDL files updated in `target/idl/`
- Commit updated IDL files
- **Time:** 5 minutes
- **Blocker:** Tasks 1.5, 1.6, 1.7

**Total Estimated Time: 1.5-2 hours**

---

## Worker 2: Backend API - 18 Tasks

### Phase 1: Database Setup (P0)

**Task 2.1:** Choose Database Option
- Decision: Supabase (free) or DO Managed DB (paid)
- If Supabase: Use connection string from user
- If DO Managed DB: Wait for Worker 4 to provision
- **Time:** 5 minutes
- **Blocker:** User decision

**Task 2.2:** Apply Database Migrations
- Export DATABASE_URL environment variable
- Run: `cd backend && psql $DATABASE_URL < sql/007_v1_features.sql`
- Verify tables created: `psql $DATABASE_URL -c "\dt public.*"`
- **Time:** 10 minutes
- **Blocker:** Task 2.1

**Task 2.3:** Verify PostGIS Extension
- Run: `psql $DATABASE_URL -c "SELECT PostGIS_version();"`
- If not enabled: `psql $DATABASE_URL -c "CREATE EXTENSION postgis;"`
- **Time:** 5 minutes
- **Blocker:** Task 2.2

**Task 2.4:** Create Backend .env File
- Copy `.env.example` to `.env` (if exists)
- Set DATABASE_URL
- Set JWT_SECRET (generate: `openssl rand -hex 32`)
- Set SOLANA_RPC_URL=https://api.devnet.solana.com
- Set placeholder program IDs (will update from Worker 1)
- **Time:** 10 minutes
- **Blocker:** Task 2.1

### Phase 2: Solana Integration (P1)

**Task 2.5:** Wait for Worker 1 Program IDs
- Monitor `/docs/INTEGRATION_REGISTRY.md` for updates
- Once available, note all 3 program IDs + DUNG mint
- **Time:** 0 minutes (waiting)
- **Blocker:** Worker 1 Task 1.11

**Task 2.6:** Configure Solana Environment Variables
- Update `.env` file with real program IDs:
  - BOULDER_ROLLERS_PROGRAM_ID=...
  - DUNG_MINT_PROGRAM_ID=...
  - PROOF_VERIFIER_PROGRAM_ID=...
  - DUNG_MINT_ADDRESS=...
- **Time:** 5 minutes
- **Blocker:** Task 2.5

**Task 2.7:** Copy IDL Files
- Copy from Worker 1's commit:
  - protocol/anchor/target/idl/boulder_rollers.json → backend/idls/
  - protocol/anchor/target/idl/dung_mint.json → backend/idls/
  - protocol/anchor/target/idl/proof_verifier.json → backend/idls/
- Create backend/idls/ directory if needed
- **Time:** 5 minutes
- **Blocker:** Worker 1 Task 1.12

**Task 2.8:** Test Solana Client Initialization
- Run: `cd backend && python3 -c "from app.solana_client import solana_client; print('OK')"`
- Should initialize without errors
- If stub mode: Check SOLANA_STUB=false in .env
- **Time:** 10 minutes
- **Blocker:** Tasks 2.6, 2.7

**Task 2.9:** Test Real Solana Call
- Create test script: `backend/test_solana.py`
- Try initializing a test user account
- Try minting CAL
- Verify transaction on devnet explorer
- **Time:** 20 minutes
- **Blocker:** Task 2.8

### Phase 3: API Testing (P1)

**Task 2.10:** Run Backend Tests Locally
- Run: `cd backend && pytest -v`
- Verify all 14 tests pass
- Fix any failures
- **Time:** 10 minutes
- **Blocker:** Task 2.4

**Task 2.11:** Start Local API Server
- Run: `cd backend && uvicorn app.main:app --reload --port 8080`
- Verify health check: `curl http://localhost:8080/health/db`
- Should return: `{"status":"healthy"}`
- **Time:** 5 minutes
- **Blocker:** Task 2.2, 2.4

**Task 2.12:** Test Auth Flow Locally
- POST /auth/nonce (get nonce)
- Sign nonce with test wallet
- POST /auth/verify (verify signature)
- Should receive JWT tokens
- **Time:** 15 minutes
- **Blocker:** Task 2.11

**Task 2.13:** Test CAL Endpoints
- GET /cal/balance (with JWT)
- POST /cal/mint (with JWT)
- Verify transaction on devnet
- Check database for updated balance
- **Time:** 15 minutes
- **Blocker:** Tasks 2.9, 2.12

### Phase 4: Deployment (P1)

**Task 2.14:** Wait for Worker 4 Infrastructure
- Monitor integration registry for droplet IP
- Once available, note IP and SSH access
- **Time:** 0 minutes (waiting)
- **Blocker:** Worker 4 Task 4.6

**Task 2.15:** Build Docker Image
- Run: `cd backend && docker build -t boulder-api:dev .`
- Verify image built successfully
- Test locally: `docker run -p 8080:8080 --env-file .env boulder-api:dev`
- **Time:** 10 minutes
- **Blocker:** None

**Task 2.16:** Deploy to Droplet
- SSH to droplet: `ssh root@<DROPLET_IP>`
- Clone repo or copy files
- Copy .env file with proper values
- Run Docker container
- **Time:** 20 minutes
- **Blocker:** Task 2.14, 2.15

**Task 2.17:** Verify Deployment
- Test health check: `curl http://<DROPLET_IP>:8080/health/db`
- Test auth flow from external client
- Verify logs: `docker logs -f boulder-api`
- **Time:** 10 minutes
- **Blocker:** Task 2.16

**Task 2.18:** Update Integration Registry
- Edit `/docs/INTEGRATION_REGISTRY.md`
- Update Backend API section with:
  - Dev API URL: http://<DROPLET_IP>:8080
  - Status: ✅ Deployed
  - Tests passing: ✅ (14 tests)
- Commit and push
- **Time:** 5 minutes
- **Blocker:** Task 2.17

**Total Estimated Time: 2.5-3 hours**

---

## Worker 3: iOS App - 14 Tasks

### Phase 1: Xcode Setup (P0)

**Task 3.1:** Verify Xcode Project Created
- Check: `ls ios/BoulderRollers.xcodeproj`
- Open in Xcode
- Verify all Swift files added to target
- **Time:** 5 minutes
- **Blocker:** User manual creation

**Task 3.2:** Add Swift Package Dependencies
- File → Add Package Dependencies
- Add Solana.swift: `https://github.com/portto/solana-web3.swift`
- Add Kingfisher: `https://github.com/onevcat/Kingfisher`
- (Optional) Add Mapbox: `https://github.com/mapbox/mapbox-maps-ios`
- Resolve packages
- **Time:** 10 minutes
- **Blocker:** Task 3.1

**Task 3.3:** Fix Build Errors
- Build project (Cmd+B)
- Fix any import errors
- Fix any missing file references
- Verify clean build
- **Time:** 15 minutes
- **Blocker:** Task 3.2

**Task 3.4:** Configure Info.plist
- Add location permission description
- (Optional) Add Mapbox token
- Add NSAllowsLocalNetworking for dev
- **Time:** 5 minutes
- **Blocker:** Task 3.1

### Phase 2: Backend Integration (P1)

**Task 3.5:** Wait for Worker 2 API URL
- Monitor integration registry for backend URL
- Note the dev API URL from Worker 2
- **Time:** 0 minutes (waiting)
- **Blocker:** Worker 2 Task 2.18

**Task 3.6:** Configure API Base URL
- Edit Services/APIClient.swift
- Update DEBUG baseURL to Worker 2's URL
- Build and verify no compile errors
- **Time:** 5 minutes
- **Blocker:** Task 3.5

**Task 3.7:** Test on Simulator
- Run app in simulator (Cmd+R)
- Test onboarding flow (create wallet)
- Test wallet import flow
- Verify no crashes
- **Time:** 15 minutes
- **Blocker:** Task 3.3, 3.6

**Task 3.8:** Test Authentication Flow
- Create wallet in app
- Attempt sign in
- Should call /auth/nonce
- Should sign message
- Should call /auth/verify
- Should receive JWT and navigate to main screen
- **Time:** 20 minutes
- **Blocker:** Task 3.7, Worker 2 deployed

### Phase 3: Feature Testing (P1)

**Task 3.9:** Test CAL Balance Display
- Navigate to Profile tab
- Should fetch CAL balance via GET /cal/balance
- Display balance on screen
- **Time:** 15 minutes
- **Blocker:** Task 3.8

**Task 3.10:** Test CAL Minting
- Tap "Mint Daily CAL" button
- Should call POST /cal/mint
- Should show loading state
- Should update balance on success
- Should show error if already minted today
- **Time:** 20 minutes
- **Blocker:** Task 3.9

**Task 3.11:** Test Segments Loading
- Navigate to Map tab
- Should request location permission
- Should call GET /segments/nearby with user's location
- Should display segments on map (or placeholder)
- **Time:** 20 minutes
- **Blocker:** Task 3.8

**Task 3.12:** Test Staking UI (Basic)
- Tap on a segment card
- Should show segment details
- Add basic staking amount input
- Test POST /staking/stake call
- Display result
- **Time:** 30 minutes
- **Blocker:** Task 3.11

### Phase 4: Polish & Device Testing (P2)

**Task 3.13:** Test on Physical Device
- Connect iPhone/iPad
- Select device in Xcode
- Build and run
- Test all flows
- Verify network requests work (not localhost)
- **Time:** 20 minutes
- **Blocker:** Task 3.12

**Task 3.14:** Update Integration Registry
- Edit `/docs/INTEGRATION_REGISTRY.md`
- Update iOS App section:
  - Xcode project created: ✅
  - Dependencies added: ✅
  - Auth flow tested: ✅
  - App builds: ✅
- Commit and push
- **Time:** 5 minutes
- **Blocker:** Task 3.13

**Total Estimated Time: 3-3.5 hours**

---

## Worker 4: DevOps - 15 Tasks

### Phase 1: Prerequisites Verification (P0)

**Task 4.1:** Verify User Completed Prerequisites
- Check terraform installed: `terraform --version`
- Check doctl installed: `doctl version`
- Check DO token available
- Check SSH key uploaded to DO account
- **Time:** 5 minutes
- **Blocker:** User actions

**Task 4.2:** Verify terraform.tfvars Created
- Check file exists: `infrastructure/terraform/dev/terraform.tfvars`
- Verify contains: do_token, ssh_key_ids, region
- Verify NOT committed to git
- **Time:** 5 minutes
- **Blocker:** Task 4.1

### Phase 2: Infrastructure Provisioning (P0)

**Task 4.3:** Initialize Terraform
- Run: `cd infrastructure/terraform/dev && terraform init`
- Should download DigitalOcean provider
- Verify successful initialization
- **Time:** 5 minutes
- **Blocker:** Task 4.2

**Task 4.4:** Plan Infrastructure
- Run: `terraform plan`
- Review planned resources (should see ~3-5 resources)
- Verify: 1 VPC, 1 droplet, 1 load balancer
- Save plan: `terraform plan -out=tfplan`
- **Time:** 5 minutes
- **Blocker:** Task 4.3

**Task 4.5:** Apply Infrastructure
- Run: `terraform apply tfplan`
- Type `yes` to confirm
- Wait 3-5 minutes for provisioning
- **Time:** 10 minutes
- **Blocker:** Task 4.4

**Task 4.6:** Save Terraform Outputs
- Run: `terraform output -json > outputs.json`
- Note droplet IP: `terraform output -raw api_droplet_ips`
- Note load balancer IP: `terraform output -raw load_balancer_ip`
- Note database URL (if using DO managed DB)
- **Time:** 5 minutes
- **Blocker:** Task 4.5

**Task 4.7:** Verify Droplet Access
- SSH to droplet: `ssh root@<DROPLET_IP>`
- Verify Docker installed: `docker --version`
- Verify firewall rules allow 8080
- Exit SSH
- **Time:** 5 minutes
- **Blocker:** Task 4.6

### Phase 3: Backend Deployment (P1)

**Task 4.8:** Wait for Worker 2 Backend Ready
- Monitor for Docker image built
- Wait for Worker 2 to complete testing
- **Time:** 0 minutes (waiting)
- **Blocker:** Worker 2 Task 2.15

**Task 4.9:** Prepare Environment File on Droplet
- SSH to droplet
- Create `/root/.env.api` with:
  - DATABASE_URL (from user or DO managed DB)
  - JWT_SECRET
  - SOLANA_RPC_URL
  - Program IDs from Worker 1
- Set permissions: `chmod 600 /root/.env.api`
- **Time:** 10 minutes
- **Blocker:** Task 4.7, Worker 1 Task 1.11, Task 2.1

**Task 4.10:** Deploy Backend Container
- SSH to droplet
- Clone repo: `git clone <REPO_URL> /root/boulder-repo`
- Build: `cd /root/boulder-repo/backend && docker build -t boulder-api:dev .`
- Run: `docker run -d --name boulder-api --restart unless-stopped -p 8080:8080 --env-file /root/.env.api boulder-api:dev`
- **Time:** 15 minutes
- **Blocker:** Task 4.9

**Task 4.11:** Verify Backend Health
- Check logs: `docker logs boulder-api`
- Test locally: `curl localhost:8080/health/db`
- Test from external: `curl http://<DROPLET_IP>:8080/health/db`
- Should return `{"status":"healthy"}`
- **Time:** 10 minutes
- **Blocker:** Task 4.10

### Phase 4: Load Balancer Configuration (P1)

**Task 4.12:** Configure Load Balancer Health Checks
- Via DO console or doctl
- Set health check path: `/health/db`
- Set interval: 10s, timeout: 5s
- Verify droplet shows as healthy
- **Time:** 10 minutes
- **Blocker:** Task 4.11

**Task 4.13:** Test Load Balancer
- Get LB IP: `terraform output -raw load_balancer_ip`
- Test: `curl http://<LB_IP>:8080/health/db`
- Should route to backend successfully
- **Time:** 5 minutes
- **Blocker:** Task 4.12

### Phase 5: CI/CD & Monitoring (P2)

**Task 4.14:** Configure GitHub Actions Secrets
- Go to repo Settings → Secrets
- Add: DO_TOKEN, DO_SSH_KEY, DEV_DROPLET_IP, DATABASE_URL
- Add Solana program IDs (from Worker 1)
- Add JWT_SECRET
- **Time:** 10 minutes
- **Blocker:** None

**Task 4.15:** Update Integration Registry
- Edit `/docs/INTEGRATION_REGISTRY.md`
- Update Infrastructure section:
  - Dev Droplet IP: <IP>
  - Load Balancer IP: <IP>
  - Database URL: <URL>
  - Dev API URL: http://<LB_IP>:8080
  - Status: ✅ Provisioned
  - Backend deployed: ✅
  - Health checks passing: ✅
- Commit and push
- **Time:** 5 minutes
- **Blocker:** Task 4.13

**Total Estimated Time: 1.5-2 hours**

---

## Integration Testing (All Workers)

### End-to-End Flow Tests

**Test 1:** Full User Registration Flow
1. Open iOS app
2. Create new wallet
3. Sign in (nonce/verify flow)
4. View profile (should show 0 CAL)
5. Mint daily CAL
6. Verify 2500 CAL in profile
7. Check backend database for user record
8. Check Solana devnet for on-chain user account

**Test 2:** Segment Discovery
1. Navigate to Map tab in iOS
2. Grant location permission
3. Verify segments load from backend
4. Verify segments display on map
5. Check backend logs for /segments/nearby call
6. Verify database has segment records

**Test 3:** Staking Flow
1. Select a segment
2. Enter stake amount (min 10 DUNG)
3. Confirm stake
4. Verify transaction submitted to Solana
5. Verify claim record in backend database
6. Verify claim shows in iOS app

**Test 4:** Backend to Solana Integration
1. Use curl to call POST /cal/mint
2. Verify backend calls Solana program
3. Check Solana devnet explorer for transaction
4. Verify backend database updated with new balance
5. Verify no stub signatures used

---

## Success Criteria

By end of Session 2, you should have:

### Infrastructure
- [ ] Droplet provisioned and accessible
- [ ] Load balancer configured and healthy
- [ ] Database provisioned (Supabase or DO managed)
- [ ] Backend API deployed and responding

### Solana
- [ ] All 3 programs deployed to devnet
- [ ] DUNG token mint created
- [ ] Program IDs published to integration registry
- [ ] Tests passing on devnet

### Backend
- [ ] Database migrations applied
- [ ] Real Solana transactions working
- [ ] All endpoints functional
- [ ] Deployed to dev server

### iOS
- [ ] App builds successfully
- [ ] Authentication works with live backend
- [ ] CAL balance displays correctly
- [ ] Segments load from backend
- [ ] Basic staking UI functional

### Integration
- [ ] End-to-end user flow works
- [ ] iOS → Backend → Solana → Backend → iOS
- [ ] All data syncs correctly
- [ ] No stub/mock responses in production flow

---

## Estimated Total Time

- **Worker 1:** 1.5-2 hours
- **Worker 2:** 2.5-3 hours
- **Worker 3:** 3-3.5 hours
- **Worker 4:** 1.5-2 hours
- **Integration Testing:** 1 hour

**Total: 10-12 hours of AI work time**
**With 4 workers in parallel: 3-4 hours wall clock time**

---

## Dependencies Graph

```
User Actions
    ↓
Worker 4: Provision Infrastructure
    ↓
Worker 1: Deploy Solana Programs → Publish Program IDs
    ↓
Worker 2: Configure Solana Client → Deploy Backend
    ↓
Worker 3: Configure API URL → Test iOS App
    ↓
Integration Testing
```

---

## Next Steps After Session 2

If all goes well, Session 3 will focus on:
1. Mainnet deployment planning
2. Production infrastructure
3. Security audits
4. App Store submission prep
5. Additional features (Swanny Seats, Epochs)

---

**Ready to resume?** Ensure user actions are complete, then spin up your 4 Codex workers! 🚀
