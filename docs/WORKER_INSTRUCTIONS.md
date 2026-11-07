# BoulderRollers V1 - Worker Instructions

## Worker 1: Solana Programs Engineer

### Current Status
You've implemented all account structures and 8 core instructions successfully. However, compilation is blocked by a BPF stack overflow error.

### BLOCKER: Fix BPF Stack Overflow (Critical - Do This First)

**Problem**: The `anchor-spl` dependency is pulling in `spl-token-2022` confidential transfer features that exceed the BPF 4096-byte stack limit.

**Error Message**:
```
Function _ZN14spl_token_20229extension21confidential_transfer12verify_proof30verify_transfer_with_fee_proof17hff37adf197d14a78E Stack offset of 4392 exceeded max offset of 4096 by 296 bytes
```

**Solution**: Disable default features and only enable what you need.

#### Step-by-Step Fix

1. **Navigate to your Cargo.toml**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/protocol/anchor
   ```

2. **Open the programs Cargo.toml**:
   ```bash
   # File: programs/boulder_rollers/Cargo.toml
   ```

3. **Locate line 17** (should currently say):
   ```toml
   anchor-spl = { version = "0.29.0" }
   ```

4. **Replace with this exact line**:
   ```toml
   anchor-spl = { version = "0.29.0", default-features = false, features = ["token"] }
   ```

5. **Save the file**

6. **Clean and rebuild**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/protocol/anchor
   cargo clean
   anchor build
   ```

7. **Verify it compiles**:
   ```bash
   # You should see:
   # Compiling boulder_rollers v0.1.0 (/Users/gabetemp/curahee/BoulderRollers-v2/protocol/anchor/programs/boulder_rollers)
   # Finished release [optimized] target(s)
   ```

### After Fix: Generate IDL and Get Program ID

Once compilation succeeds:

1. **Generate the IDL**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/protocol/anchor
   anchor build -- --features idl-build
   ```

2. **The IDL will be at**:
   ```
   target/idl/boulder_rollers.json
   ```

3. **Get your program ID**:
   ```bash
   solana address -k target/deploy/boulder_rollers-keypair.json
   ```

4. **Update Anchor.toml** with your program ID:
   ```bash
   # File: Anchor.toml
   # Replace the [programs.localnet] section with your actual program ID
   ```

5. **Update lib.rs** with the same program ID:
   ```rust
   // File: programs/boulder_rollers/src/lib.rs
   // Line 1: Replace the declare_id!() with your program ID
   declare_id!("YourProgramIdHere...");
   ```

### Testing Your Programs

1. **Start local validator** (if not already running):
   ```bash
   solana-test-validator --reset
   ```

2. **In another terminal, run Anchor tests**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/protocol/anchor
   anchor test --skip-local-validator
   ```

3. **Write tests for each instruction** in `tests/boulder_rollers.ts`:
   - initialize_user
   - mint_daily_cal
   - burn_cal_for_segment
   - create_segment
   - stake_in_segment
   - unstake_from_segment
   - And others

### Deploy to Devnet (Once Tests Pass)

1. **Set config to devnet**:
   ```bash
   solana config set --url https://api.devnet.solana.com
   ```

2. **Airdrop SOL for deployment** (if needed):
   ```bash
   solana airdrop 2
   ```

3. **Deploy**:
   ```bash
   anchor deploy --provider.cluster devnet
   ```

4. **Share the deployed program ID with Worker 2** (they need it for backend integration)

### Communication to Main Thread

Once you've fixed the Cargo.toml and programs compile, report back with:
- ✅ Compilation status
- 📄 Path to generated IDL (target/idl/boulder_rollers.json)
- 🔑 Program ID (from solana address -k command)
- 🧪 Test results (how many passing)

---

## Worker 2: Backend API Engineer

### Current Status
You've created database migrations, new routes (cal.py, staking.py), and repository methods. Now you need to apply migrations and integrate with Solana programs.

### Step 1: Apply Database Migration

**Prerequisite**: You need a running PostgreSQL database with PostGIS extension.

#### If Using Supabase:

1. **Get your database URL from Supabase dashboard**:
   - Go to Settings → Database
   - Copy the "Connection string" (URI mode)
   - Should look like: `postgresql://postgres:[YOUR-PASSWORD]@db.[YOUR-PROJECT-REF].supabase.co:5432/postgres`

2. **Set environment variable**:
   ```bash
   export DATABASE_URL="postgresql://postgres:[PASSWORD]@db.[PROJECT].supabase.co:5432/postgres"
   ```

3. **Apply the migration**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/backend
   psql $DATABASE_URL < sql/007_v1_features.sql
   ```

4. **Verify tables were created**:
   ```bash
   psql $DATABASE_URL -c "\dt public.*"
   ```

   You should see:
   - user_state
   - claims
   - swanny_seats
   - epochs
   - leaderboard_entries

#### If Using Local PostgreSQL:

1. **Start PostgreSQL** (if using Docker):
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2
   docker compose up -d postgres
   ```

2. **Wait for it to be ready** (check logs):
   ```bash
   docker compose logs postgres
   ```

3. **Apply migration**:
   ```bash
   cd backend
   export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/boulderrollers"
   psql $DATABASE_URL < sql/007_v1_features.sql
   ```

### Step 2: Install Solana Python SDK

You'll need the Solana SDK to interact with Worker 1's deployed programs.

1. **Add to requirements.txt**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/backend
   echo "solana>=0.30.0" >> requirements.txt
   echo "anchorpy>=0.18.0" >> requirements.txt
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

### Step 3: Create Solana Client Module

1. **Create new file** `app/solana_client.py`:
   ```python
   """
   Solana blockchain client for Boulder Rollers program interactions.
   """
   import os
   from typing import Optional
   from solana.rpc.async_api import AsyncClient
   from solana.keypair import Keypair
   from solana.publickey import PublicKey
   from anchorpy import Provider, Wallet, Program, Idl
   import json

   # Load from environment
   SOLANA_RPC_URL = os.getenv("SOLANA_RPC_URL", "https://api.devnet.solana.com")
   BOULDER_ROLLERS_PROGRAM_ID = os.getenv("BOULDER_ROLLERS_PROGRAM_ID", "PLACEHOLDER")

   class BoulderRollersClient:
       def __init__(self):
           self.client = AsyncClient(SOLANA_RPC_URL)
           # Load the IDL (you'll get this from Worker 1)
           with open("program_idl.json") as f:
               idl = json.load(f)
           self.program_id = PublicKey(BOULDER_ROLLERS_PROGRAM_ID)
           # TODO: Initialize anchorpy Program instance

       async def initialize_user(self, user_pubkey: str) -> str:
           """
           Call initialize_user instruction on-chain.
           Returns transaction signature.
           """
           # TODO: Implement using anchorpy
           pass

       async def mint_daily_cal(self, user_pubkey: str) -> dict:
           """
           Call mint_daily_cal instruction on-chain.
           Returns transaction signature and cal_balance.
           """
           # TODO: Implement using anchorpy
           pass

       async def burn_cal_for_segment(
           self,
           user_pubkey: str,
           segment_id: int,
           cal_amount: int
       ) -> str:
           """
           Call burn_cal_for_segment instruction on-chain.
           Returns transaction signature.
           """
           # TODO: Implement using anchorpy
           pass

       async def stake_in_segment(
           self,
           user_pubkey: str,
           segment_id: int,
           dung_amount: int
       ) -> str:
           """
           Call stake_in_segment instruction on-chain.
           Returns transaction signature.
           """
           # TODO: Implement using anchorpy
           pass

       async def get_user_state(self, user_pubkey: str) -> dict:
           """
           Fetch UserState account from chain.
           Returns cal_balance, total_rides, etc.
           """
           # TODO: Implement account fetch
           pass

   # Singleton instance
   solana_client = BoulderRollersClient()
   ```

2. **Save the file**

### Step 4: Update Routes to Call Solana

Once Worker 1 provides the program ID and IDL:

1. **Get the IDL from Worker 1**:
   - They'll provide `target/idl/boulder_rollers.json`
   - Copy it to `/Users/gabetemp/curahee/BoulderRollers-v2/backend/program_idl.json`

2. **Set environment variables**:
   ```bash
   export BOULDER_ROLLERS_PROGRAM_ID="[Program ID from Worker 1]"
   export SOLANA_RPC_URL="https://api.devnet.solana.com"
   ```

3. **Update `app/routes/cal.py`** to call Solana:
   ```python
   from ..solana_client import solana_client

   @router.post("/mint")
   async def mint_daily_cal(request: Request):
       user = request.state.user
       pubkey = user["pubkey"]

       # Call on-chain instruction
       result = await solana_client.mint_daily_cal(pubkey)

       # Also update local database for caching/querying
       await repositories.update_cal_balance(user["id"], result["cal_balance"])

       return result
   ```

4. **Update `app/routes/staking.py`** similarly for stake/unstake operations

### Step 5: Test Your API

1. **Run the API locally**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/backend
   export DATABASE_URL="[your db url]"
   export BOULDER_ROLLERS_PROGRAM_ID="[program id from worker 1]"
   uvicorn app.main:app --reload --port 8080
   ```

2. **Test health endpoint**:
   ```bash
   curl http://localhost:8080/health/db
   # Should return: {"status": "healthy"}
   ```

3. **Test new routes**:
   ```bash
   # Get CAL balance
   curl -H "Authorization: Bearer [your-jwt]" http://localhost:8080/cal/balance

   # Mint daily CAL
   curl -X POST -H "Authorization: Bearer [your-jwt]" http://localhost:8080/cal/mint
   ```

### Communication to Main Thread

Report back with:
- ✅ Migration applied successfully (show table list)
- 🔌 Solana client module created
- 🧪 Test results for new endpoints
- ❓ Waiting for: Program ID and IDL from Worker 1

---

## Worker 3: iOS App Engineer

### Current Status
You've implemented wallet import (BIP39), Mapbox integration with conditional compilation, improved API error handling, and ride upload file type restrictions. Excellent work! Now you need to add dependencies and configure external services.

### Step 1: Add Swift Package Dependencies

1. **Open Xcode**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/ios
   open BoulderRollers.xcodeproj
   ```

2. **Add Solana.Swift package**:
   - File → Add Package Dependencies
   - Enter URL: `https://github.com/portto/solana-web3.swift`
   - Version: 1.0.0 or latest
   - Add to target: BoulderRollers

3. **Add MapboxMaps package**:
   - File → Add Package Dependencies
   - Enter URL: `https://github.com/mapbox/mapbox-maps-ios`
   - Version: 10.18.0 or latest
   - Add to target: BoulderRollers
   - **Important**: Only add if you want Mapbox (app works without it due to conditional compilation)

4. **Add Kingfisher for image loading** (for segment cover photos):
   - File → Add Package Dependencies
   - Enter URL: `https://github.com/onevcat/Kingfisher`
   - Version: 7.10.0 or latest
   - Add to target: BoulderRollers

5. **Verify packages resolved**:
   - Look at Project Navigator → under "Package Dependencies"
   - Should see: Solana, MapboxMaps (if added), Kingfisher

### Step 2: Configure Mapbox (Optional)

**Note**: Your app works without this due to conditional compilation. Only do this if you want map features enabled.

1. **Get Mapbox Access Token**:
   - Go to https://account.mapbox.com/
   - Create account (free tier is fine for development)
   - Copy your "Default public token"

2. **Add token to Info.plist**:
   ```bash
   # In Xcode, select Info.plist in the navigator
   ```

   - Right-click in the editor → Add Row
   - Key: `MBXAccessToken`
   - Type: String
   - Value: `[paste your Mapbox token here]`

3. **Or skip Mapbox** and use the placeholder view:
   - Your code already handles this gracefully
   - Users will see "Add MBXAccessToken to Info.plist to enable Mapbox map."

### Step 3: Configure API Endpoints

Your app currently points to:
- **Debug**: `https://dev-api.boulderrollers.com`
- **Release**: `https://api.boulderrollers.com`

These domains don't exist yet. Update to point to local backend for testing:

1. **Open** `Services/APIClient.swift`

2. **Change the init() method** (around line 12-18):
   ```swift
   init() {
       #if DEBUG
       // Point to local backend or Worker 4's dev server when available
       baseURL = "http://localhost:8080"  // For simulator testing
       // OR use ngrok/tunneling for device testing:
       // baseURL = "https://your-ngrok-url.ngrok.io"
       #else
       baseURL = "https://api.boulderrollers.com"
       #endif
   }
   ```

3. **For testing on physical device**, you'll need:
   - Worker 2's API running and accessible (not localhost)
   - Either use ngrok tunnel or wait for Worker 4's dev deployment

### Step 4: Build and Test

1. **Build the app**:
   - Select iOS Simulator (iPhone 15 Pro or similar)
   - Product → Build (Cmd+B)
   - Fix any compilation errors

2. **Run the app**:
   - Product → Run (Cmd+R)

3. **Test wallet creation flow**:
   - Tap "Create New Wallet"
   - Should generate a new Solana keypair
   - Note: Wallet is stored in Keychain (persists across app launches)

4. **Test wallet import flow**:
   - Tap "Import Wallet"
   - Enter a valid 12 or 24 word BIP39 seed phrase
   - Should accept and store keypair
   - Invalid phrases should show error: "Seed phrase must be 12 or 24 words."

5. **Test map view** (if Mapbox configured):
   - Should show Boulder, CO area
   - If no token: Shows placeholder message
   - If token present: Shows Mapbox outdoors style

6. **Test ride upload**:
   - Requires backend API to be running
   - Tap upload button
   - Should filter to only .gpx and .fit files
   - Selecting a file should show improved error messages if API call fails

### Step 5: Test Against Live Backend

Once Worker 2 has the API running:

1. **Update baseURL** to point to Worker 2's endpoint (or Worker 4's dev server)

2. **Test full auth flow**:
   ```swift
   // In your onboarding:
   // 1. Create wallet
   // 2. Sign authentication message
   // 3. Send to /auth/wallet endpoint
   // 4. Receive JWT
   // 5. Store JWT in APIClient
   ```

3. **Test CAL features** (once Solana programs deployed):
   - View CAL balance on profile
   - Mint daily CAL (should hit /cal/mint endpoint)
   - Burn CAL for segment rides

4. **Test segment features**:
   - View nearby segments on map
   - Tap segment card to see details
   - Stake DUNG in segment (future work)

### Known Issues to Watch For

1. **Location permissions**: Make sure Info.plist has:
   ```xml
   <key>NSLocationWhenInUseUsageDescription</key>
   <string>We need your location to show nearby cycling segments</string>
   ```

2. **Network permissions** (for local testing):
   ```xml
   <key>NSAppTransportSecurity</key>
   <dict>
       <key>NSAllowsLocalNetworking</key>
       <true/>
   </dict>
   ```

3. **Mapbox download size**: MapboxMaps SDK is ~80MB. Consider making it truly optional if app size is a concern.

### Communication to Main Thread

Report back with:
- ✅ Swift packages added (Solana.Swift, Kingfisher, MapboxMaps if applicable)
- ✅ App compiles and runs
- 🗺️ Mapbox status (configured or using placeholder)
- 🔌 API endpoint configured (local, ngrok, or waiting for deployment)
- 🧪 Test results (wallet creation, import, UI flows)
- ❓ Waiting for: Live backend API from Worker 2/4

---

## Worker 4: DevOps Engineer

### Current Status
You've created comprehensive Terraform configurations for dev/prod environments, monitoring setup, GitHub Actions workflows, and Docker Compose for local dev. Now you need to provision the actual infrastructure.

### Step 1: Gather Prerequisites

Before running Terraform, collect these:

1. **DigitalOcean API Token**:
   - Go to https://cloud.digitalocean.com/account/api/tokens
   - Generate New Token
   - Name: "BoulderRollers Terraform"
   - Scopes: Read + Write
   - Copy the token (you won't see it again)
   - **Store securely** (not in git)

2. **SSH Key ID**:
   ```bash
   # If you don't have DO CLI installed:
   brew install doctl

   # Authenticate:
   doctl auth init
   # Paste your API token when prompted

   # List SSH keys:
   doctl compute ssh-key list
   # Note the ID (numeric) of your SSH key

   # If you don't have an SSH key uploaded:
   ssh-keygen -t ed25519 -C "your-email@example.com"
   doctl compute ssh-key import boulder-key --public-key-file ~/.ssh/id_ed25519.pub
   ```

3. **Domain Names** (optional for dev, required for prod):
   - Dev: Can skip or use IP
   - Prod: Need `api.boulderrollers.com` pointed to your DO account
   - If using domain: Configure DNS before terraform apply

### Step 2: Configure Terraform Variables

1. **Navigate to dev environment**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/infrastructure/terraform/dev
   ```

2. **Copy the example tfvars**:
   ```bash
   cp ../terraform.tfvars.example ./terraform.tfvars
   ```

3. **Edit terraform.tfvars**:
   ```bash
   # Use your preferred editor
   vim terraform.tfvars
   # or
   code terraform.tfvars
   ```

4. **Fill in the values**:
   ```hcl
   do_token = "[REDACTED_DO_TOKEN]"  # Your DO token
   ssh_key_ids = [12345678]  # Your SSH key ID from step 1
   region = "nyc3"  # Or sfo3, tor1, etc.
   vpc_cidr = "10.0.0.0/16"  # Default is fine for dev
   domain = ""  # Leave empty for dev, or set if you have one

   # Database options
   enable_database = false  # Set true if NOT using Supabase
   enable_redis = false     # Set true if you need Redis (for caching, rate limiting)
   ```

5. **Save the file**

6. **IMPORTANT**: Add to .gitignore if not already:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2
   echo "infrastructure/terraform/**/*.tfvars" >> .gitignore
   echo "infrastructure/terraform/**/.terraform/" >> .gitignore
   echo "infrastructure/terraform/**/.terraform.lock.hcl" >> .gitignore
   echo "infrastructure/terraform/**/terraform.tfstate*" >> .gitignore
   ```

### Step 3: Initialize and Apply Terraform (Dev Environment)

1. **Initialize Terraform**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/infrastructure/terraform/dev
   terraform init
   ```

   Expected output:
   ```
   Initializing modules...
   Initializing the backend...
   Initializing provider plugins...
   - Finding digitalocean/digitalocean versions matching "~> 2.0"...
   Terraform has been successfully initialized!
   ```

2. **Plan the infrastructure**:
   ```bash
   terraform plan
   ```

   Review the output carefully. You should see:
   - 1 VPC to be created
   - 1 Droplet (dev environment)
   - 1 Load Balancer
   - 0 or 2 managed services (Postgres + Redis, if enabled)

   Total resources: ~3-5 depending on your enable_database/enable_redis settings

3. **Apply the infrastructure**:
   ```bash
   terraform apply
   ```

   - Type `yes` when prompted
   - Wait 3-5 minutes for resources to provision

4. **Save the outputs**:
   ```bash
   terraform output > outputs.txt
   ```

   This will contain:
   - Droplet IP addresses
   - Load balancer IP
   - Database connection strings (if enabled)

### Step 4: Configure Droplets

Once droplets are created, you need to deploy the API:

1. **SSH into the dev droplet**:
   ```bash
   # Get the IP from terraform output
   terraform output api_droplet_ips

   # SSH in
   ssh root@[DROPLET_IP]
   ```

2. **Verify Docker is installed**:
   ```bash
   docker --version
   # Should show Docker version 24.x or later
   ```

3. **Set up environment variables** on the droplet:
   ```bash
   # Create .env file
   cat > /root/.env.api << 'EOF'
   DATABASE_URL=postgresql://user:pass@host:5432/db
   JWT_SECRET=your-secure-random-secret-here
   BOULDER_ROLLERS_PROGRAM_ID=placeholder-until-worker-1-deploys
   SOLANA_RPC_URL=https://api.devnet.solana.com
   EOF

   chmod 600 /root/.env.api
   ```

4. **Pull and run the API container**:
   ```bash
   # If you've built and pushed the image:
   docker pull your-registry/boulderrollers-api:dev

   docker run -d \
     --name boulder-api \
     --restart unless-stopped \
     -p 8080:8080 \
     --env-file /root/.env.api \
     your-registry/boulderrollers-api:dev

   # Check logs
   docker logs -f boulder-api
   ```

5. **Or build on the droplet** (if not using registry):
   ```bash
   # Clone repo on droplet
   cd /root
   git clone [your-repo-url] boulder-repo
   cd boulder-repo/backend

   # Build
   docker build -t boulder-api:dev .

   # Run
   docker run -d \
     --name boulder-api \
     --restart unless-stopped \
     -p 8080:8080 \
     --env-file /root/.env.api \
     boulder-api:dev
   ```

### Step 5: Verify API is Accessible

1. **Test from your local machine**:
   ```bash
   # Get load balancer IP
   cd /Users/gabetemp/curahee/BoulderRollers-v2/infrastructure/terraform/dev
   LB_IP=$(terraform output -raw load_balancer_ip)

   # Test health endpoint
   curl http://$LB_IP/health/db
   ```

2. **Expected response**:
   ```json
   {"status": "healthy"}
   ```

3. **If unhealthy**, check:
   - Droplet is running: `doctl compute droplet list`
   - API container is running: SSH in and `docker ps`
   - Database connection: Check DATABASE_URL in .env.api
   - Load balancer health checks: DO console → Networking → Load Balancers

### Step 6: Set Up GitHub Actions Secrets

For CI/CD to work, add these secrets to your GitHub repo:

1. **Go to your GitHub repo**:
   - Settings → Secrets and variables → Actions → New repository secret

2. **Add these secrets**:
   ```
   DO_TOKEN: [Your DigitalOcean API token]
   DO_SSH_KEY: [Contents of your private SSH key for deployment]
   DEV_DROPLET_IP: [IP from terraform output]
   PROD_DROPLET_IP: [Will add later when prod is provisioned]
   DOCKER_USERNAME: [If using Docker Hub]
   DOCKER_PASSWORD: [If using Docker Hub]
   ```

3. **Test the backend workflow**:
   ```bash
   # Make a small change to backend
   cd /Users/gabetemp/curahee/BoulderRollers-v2/backend
   echo "# Test" >> README.md
   git add README.md
   git commit -m "Test CI/CD pipeline"
   git push

   # Check GitHub Actions tab
   # Should see "Backend CI/CD" workflow running
   ```

### Step 7: Set Up Monitoring (Optional for MVP)

1. **Deploy Prometheus on a droplet** (or use managed monitoring):
   ```bash
   ssh root@[DROPLET_IP]

   docker run -d \
     --name prometheus \
     -p 9090:9090 \
     -v /root/prometheus.yml:/etc/prometheus/prometheus.yml \
     prom/prometheus
   ```

2. **Configure scrape targets** in prometheus.yml:
   ```yaml
   scrape_configs:
     - job_name: 'boulder-api'
       static_configs:
         - targets: ['localhost:8080']
   ```

3. **Deploy Grafana**:
   ```bash
   docker run -d \
     --name grafana \
     -p 3000:3000 \
     grafana/grafana-oss
   ```

4. **Access Grafana**:
   - http://[DROPLET_IP]:3000
   - Default login: admin/admin
   - Add Prometheus data source
   - Import dashboard for FastAPI metrics

### Step 8: Production Environment (When Ready)

When ready to deploy production:

1. **Navigate to prod terraform**:
   ```bash
   cd /Users/gabetemp/curahee/BoulderRollers-v2/infrastructure/terraform/prod
   ```

2. **Copy and configure tfvars**:
   ```bash
   cp ../terraform.tfvars.example ./terraform.tfvars
   vim terraform.tfvars
   ```

3. **Set production values**:
   ```hcl
   do_token = "same-token-as-dev"
   ssh_key_ids = [12345678]
   region = "nyc3"  # Or choose different region for geo-redundancy
   vpc_cidr = "10.1.0.0/16"  # Different from dev
   domain = "api.boulderrollers.com"  # Your production domain

   enable_database = true   # Consider managed DB for prod
   enable_redis = true      # Enable caching/rate limiting
   ```

4. **Configure DNS** BEFORE applying:
   - Add A record: `api.boulderrollers.com` → Will be load balancer IP
   - Or use DO's managed DNS

5. **Apply terraform**:
   ```bash
   terraform init
   terraform plan  # Review carefully
   terraform apply  # Creates 3 droplets + LB + DB + Redis
   ```

6. **Production has**:
   - 3 API droplets (high availability)
   - Managed PostgreSQL (daily backups)
   - Managed Redis (failover)
   - Load balancer with HTTPS (Let's Encrypt)

### Communication to Main Thread

Report back with:
- ✅ Terraform applied successfully (show `terraform output`)
- 🌐 Load balancer IP address
- 🔌 API health check passing
- 🔒 GitHub Actions secrets configured
- 📊 Monitoring status (deployed or skipped for MVP)
- 📝 Outputs saved securely

### Troubleshooting Common Issues

**Issue**: Terraform times out creating load balancer
- **Fix**: Check DO account limits, ensure droplets are healthy

**Issue**: Health checks failing
- **Fix**: Verify API is listening on port 8080, check /health/db endpoint logs

**Issue**: Can't SSH into droplet
- **Fix**: Verify SSH key ID is correct, check DO firewall rules

**Issue**: Database connection failed
- **Fix**: If using Supabase, ensure DATABASE_URL is correct. If using DO managed DB, get connection string from terraform output

---

## Coordination Notes for All Workers

### Dependencies Between Workers

- **Worker 1** is blocking **Worker 2**: Backend needs program ID and IDL
- **Worker 2** is blocking **Worker 3**: iOS needs live API to test against
- **Worker 4** is independent but provides infrastructure for **Worker 2**

### Recommended Order of Execution

1. **Worker 1**: Fix Cargo.toml IMMEDIATELY (5 minutes)
2. **Worker 4**: Provision dev infrastructure (1-2 hours)
3. **Worker 2**: Apply migrations, wait for Worker 1's program ID (1 hour)
4. **Worker 1**: Deploy to devnet, share program ID (30 minutes)
5. **Worker 2**: Integrate Solana client, deploy to Worker 4's droplet (2 hours)
6. **Worker 3**: Configure API endpoint, test full stack (1-2 hours)

### Communication Protocol

Each worker should report status in this format:

```
Worker [N] Status Update:

✅ Completed:
- [task 1]
- [task 2]

🚧 In Progress:
- [current task]

⏸️ Blocked By:
- Waiting for [specific item] from Worker [N]

📊 Metrics:
- [relevant numbers: lines of code, tests passing, response times, etc.]

❓ Questions:
- [any clarifications needed]
```

---

## Emergency Contacts & Resources

- **Anchor Docs**: https://www.anchor-lang.com/docs
- **Solana Cookbook**: https://solanacookbook.com/
- **FastAPI Docs**: https://fastapi.tiangolo.com/
- **SwiftUI + Solana**: https://github.com/portto/solana-web3.swift
- **DigitalOcean Docs**: https://docs.digitalocean.com/
- **Terraform DO Provider**: https://registry.terraform.io/providers/digitalocean/digitalocean/latest/docs

## Recommended Communication Cadence

- **Daily standup**: Each worker posts status update
- **Blocker alerts**: Post immediately when blocked
- **Integration points**: Sync explicitly when handoffs occur (Worker 1 → Worker 2, Worker 2/4 → Worker 3)

Let's ship this! 🚀
