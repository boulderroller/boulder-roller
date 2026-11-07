# Mainnet Deployment Procedure

**Document:** P0 Blocker #13
**Last updated:** 2026-03-07
**Owner:** Infrastructure / Protocol Ops
**Status:** DRAFT — requires sign-off after all P0 blockers resolved

This document describes the complete procedure for deploying Boulder Rollers to Solana mainnet-beta and transitioning the backend from devnet to live production operations.

---

## Table of Contents

1. [Pre-Flight Checklist](#1-pre-flight-checklist)
2. [Infrastructure Setup](#2-infrastructure-setup)
3. [Key Management](#3-key-management)
4. [Solana Program Deployment](#4-solana-program-deployment)
5. [Database Migrations](#5-database-migrations)
6. [Application Deployment](#6-application-deployment)
7. [Post-Deploy Validation](#7-post-deploy-validation)
8. [Failure Drills](#8-failure-drills)
9. [Rollback Procedure](#9-rollback-procedure)
10. [Monitoring & Alerts](#10-monitoring--alerts)

---

## 1. Pre-Flight Checklist

Every item must be verified and signed off before proceeding. The sign-off column is filled in during the actual deployment event.

### P0 Blockers (from A4 — Architecture Sprint 2026-03-06)

| # | Blocker | File / Evidence | Sign-off |
|---|---------|-----------------|----------|
| 1 | Priority fees on every transaction | `backend/app/services/solana_submit.py` — `DEFAULT_PRIORITY_FEE_MICRO_LAMPORTS = 50_000` | [ ] |
| 2 | Transaction retry with blockhash expiry detection | `solana_submit.py` — `_BlockhashExpiredError`, `BACKOFF_SCHEDULE`, `DEFAULT_MAX_RETRIES = 3` | [ ] |
| 3 | `tx_lifecycle` table wired to all submission paths | Migration `20260306_075_tx_lifecycle.sql`; all 13 `send_*` functions in `backend/app/solana_direct.py` use `submit_and_confirm()` | [ ] |
| 4 | DB state updates gated on `confirmed` commitment | `submit_and_confirm()` default commitment = `confirmed`; epoch distribute + admin mint use `finalized` | [ ] |
| 5 | Upgrade authority moved to hardware wallet (Ledger) | See [Section 3](#3-key-management) — must be completed before deploy | [ ] |
| 6 | Treasury wallet separated from upgrade authority | See [Section 3](#3-key-management) — Squads multisig | [ ] |
| 7 | Payer/admin key separation verified in ProgramConfig | ProgramConfig PDA initialized with distinct payer vs admin pubkeys | [ ] |
| 8 | On-chain program security audit completed | External audit report attached | [ ] |
| 9 | Alertmanager receivers configured with real endpoints | `infrastructure/monitoring/prometheus/alertmanager.yml` — replace placeholder URLs | [ ] |
| 10 | SOL balance monitoring with alerts | `backend/app/routes/health.py` — `/health/sol-balance`; alert rules in `infrastructure/monitoring/prometheus/alert_rules.yml` (`PayerSolBalanceLow`, `PayerSolBalanceCritical`) | [ ] |
| 11 | Epoch processor singleton lock | DBOS advisory lock on epoch processor; prevents double execution across replicas | [ ] |
| 12 | Atomic financial ops migration (073) applied | `backend/supabase/migrations/20260303_073_atomic_financial_ops.sql` — `unstake_cal_atomic`, `claim_vault_slot_atomic`, `stake_cal_with_cap` | [ ] |
| 13 | Mainnet deployment procedure documented | This document | [ ] |
| 14 | RPC provider with staked connections | Helius Growth plan ($39/mo) with staked RPC endpoints | [ ] |

### Test Suite Gates

| Gate | Command | Expected | Sign-off |
|------|---------|----------|----------|
| Backend tests | `cd backend && pytest -v` | 168 passing | [ ] |
| Anchor tests | `cd protocol/anchor && anchor test` | 15 passing | [ ] |
| Climb regression | `.claude/hooks/climb-regression` | No signature changes vs `.claude/climb-baseline.json` | [ ] |
| V4-B canon identity | Shared D12 codec tests plus Climb-to-Vault binding tests | Exact vector and fail-closed attachment gates pass | [ ] |
| H3 resolution guard | `.claude/hooks/h3-resolution-guard` | Resolution locked at 10 | [ ] |

### Staging Validation

| Check | How | Sign-off |
|-------|-----|----------|
| Staging health green | `curl https://[STAGING_IP]:8080/health` | [ ] |
| Staging DB health green | `curl https://[STAGING_IP]:8080/health/db` | [ ] |
| Staging SOL balance | `curl https://[STAGING_IP]:8080/health/sol-balance` (must show > 0.5 SOL) | [ ] |
| End-to-end ride upload on staging | Upload FIT file, verify CAL earned, vault matching, tile storage | [ ] |
| Economic simulation reviewed | Settlement Week finalization tested on devnet; per-bucket splits verified at 55/27/3/5/10 bps | [ ] |
| Economic ledger consistency | `GET /dev/ledger/consistency?wallet=<test_wallet>` shows zero drift | [ ] |
| Hash chain integrity | `GET /dev/ledger/verify-chain?wallet=<test_wallet>&denomination=CAL` passes | [ ] |

---

## 2. Infrastructure Setup

### 2.1 Production API Nodes

Production uses a 3-node API cluster behind a DigitalOcean load balancer, defined in Terraform.

**Terraform apply:**
```bash
cd infrastructure/terraform/prod
cp ../terraform.tfvars.example ./terraform.tfvars
# Fill in: do_token, ssh_key_ids, domain, vpc_cidr, enable_database, enable_redis
terraform init
terraform plan    # review carefully
terraform apply
```

**Prod Terraform config** (`infrastructure/terraform/prod/main.tf`):
- `api_count = 3`
- `api_droplet_size = "c-4"` (4 vCPU dedicated)
- `healthcheck_path = "/health/db"`
- `create_load_balancer = true`
- LetsEncrypt TLS via `digitalocean_certificate`

**Post-apply checklist:**
- [ ] Record load balancer IP, update DNS for `api.boulderroller.org`
- [ ] Verify all 3 droplets are accessible via SSH
- [ ] Install Docker on each droplet if not in base image
- [ ] Create `boulder-net` Docker network on each node: `docker network create boulder-net`

### 2.2 Database

**Provider:** Supabase Pro plan (existing `db.qzkqjevawthyboymqrle.supabase.co`)

**Connection pooling config:**
- Use Supabase's PgBouncer on port 6543 for application connections (transaction mode)
- Use direct connection on port 5432 for migrations and DBOS advisory locks
- Set `SUPABASE_URL` to pooled endpoint for API, direct endpoint for migration scripts

**Backup:**
```bash
# Automated daily backup — add to cron on one API node
0 2 * * * /opt/boulder/infrastructure/scripts/backup-db.sh
```
Requires `DATABASE_URL` and optionally `SPACES_BUCKET` for off-site storage.

### 2.3 RPC Providers

| Provider | Plan | Cost | Role | Endpoint |
|----------|------|------|------|----------|
| Helius | Growth | $39/mo | Primary | `https://mainnet.helius-rpc.com/?api-key=<KEY>` |
| QuickNode | Build | $49/mo | Failover | `https://<endpoint>.solana-mainnet.quiknode.pro/<TOKEN>` |

**Configuration:**
```bash
# Primary
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=<HELIUS_API_KEY>
# Failover (used by indexer or manual recovery)
SOLANA_RPC_FAILOVER_URL=https://<endpoint>.solana-mainnet.quiknode.pro/<TOKEN>
```

Helius Growth provides staked connections with higher landing rates. QuickNode Build provides WebSocket subscriptions for the indexer's `programSubscribe` stream mode.

**Total new monthly cost:** $88/mo

### 2.4 NATS

Self-hosted NATS with JetStream, running as a Docker service on each API node.

**Config** (from `docker-compose.yml`):
```yaml
nats:
  image: nats:2.10-alpine
  command: ["-js", "-sd", "/data"]
  volumes:
    - nats_data:/data
```

- JetStream persistent storage enabled (`-sd /data`)
- RIDES stream with 7-day retention (configured in `backend/app/services/nats_client.py`)
- Deduplication window for idempotent ride event publishing

### 2.5 Redis

Redis is retained for Celery task queue (until Phase 6 NATS migration completes) and response caching.

```yaml
redis:
  image: redis:7-alpine
```

Post-NATS migration, Redis can be removed entirely if caching moves to application-level or NATS KV.

---

## 3. Key Management

### 3.1 Five-Key Architecture

Production requires 5 distinct keys with separated responsibilities (per A4 decision D10).

| Key | Purpose | Storage | Pubkey Source |
|-----|---------|---------|---------------|
| **Upgrade Authority** | Program upgrades only | Ledger hardware wallet | Ledger-derived |
| **Treasury** | Token reserves, fee collection | Squads multisig (2-of-3) | Squads program |
| **POL** | Protocol-owned liquidity | Squads multisig (2-of-3) | Squads program |
| **Payer** | Signs all runtime transactions (ride proofs, vault ops) | Hot wallet (encrypted env var on API nodes) | From `SOLANA_PAYER_SECRET` |
| **Admin** | ProgramConfig admin operations, epoch trigger | Hot wallet (separate from payer) | Set in ProgramConfig PDA |

### 3.2 Upgrade Authority Migration

**CRITICAL:** The upgrade authority MUST move to a hardware wallet before mainnet deploy.

**Current state (devnet):**
- Upgrade authority: `~/.config/solana/boulderroller-admin-upgrade-authority.json`
  (`G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH`)
- This is intentionally separate from the backend authority and fee payer, but
  it is still a single local key. That is unacceptable for mainnet.

**Migration procedure:**
1. Connect Ledger, install Solana app
2. Derive a key: `solana-keygen pubkey usb://ledger`
3. Transfer upgrade authority:
   ```bash
   solana program set-upgrade-authority 6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X \
     --new-upgrade-authority <LEDGER_PUBKEY> \
     --keypair ~/.config/solana/boulderroller-admin-upgrade-authority.json \
     --url mainnet-beta
   ```
4. Verify: `solana program show 6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X --url mainnet-beta`
5. Store the Ledger in a secure location with the seed phrase backed up offline

### 3.3 Treasury & POL Multisig

**Provider:** Squads Protocol (https://squads.so)

**Setup:**
1. Create a Squads multisig with 2-of-3 threshold
2. Signers: founder wallet + 2 trusted team members
3. Create Associated Token Accounts (ATAs) for DUNG under the multisig vault
4. Record the multisig vault pubkey as the Treasury/POL owner
5. Update ProgramConfig with the new Treasury and POL ATAs

**Current devnet references (to be replaced):**
- Treasury DUNG ATA: `Ag6YsS8GTTDYF2DUWuet1SBu3ZcoThjK8Dym7BoWdZfx` (owner: `3boUdo.../id.json`)
- POL DUNG ATA: `5kwC6G8zqoTnWJqFyH59ABsVnniFYJxm9Wn8Y6XpadjF` (owner: `Ch8uwu.../pol-wallet.json`)

### 3.4 Payer Hot Wallet

The payer signs all runtime transactions. It needs SOL for fees but holds no token value.

**Setup:**
1. Generate a fresh keypair: `solana-keygen new -o payer-mainnet.json`
2. Fund with 2 SOL initially (enough for ~200,000 transactions at current fee levels)
3. Store the JSON array in `SOLANA_PAYER_SECRET` env var on each API node
4. Set up SOL balance monitoring (see [Section 10](#10-monitoring--alerts))

**SOL budget estimate:**
- Priority fee per tx: `(50,000 micro-lamports * 200,000 CU) / 1,000,000 = 10,000 lamports = 0.00001 SOL`
- Base fee per tx: `5,000 lamports = 0.000005 SOL`
- Total per tx: ~0.000015 SOL
- 2 SOL supports ~130,000 transactions

**Auto-refill trigger:** Alert at 0.5 SOL, critical at 0.1 SOL. Manual refill from treasury.

### 3.5 Key Rotation Procedure

1. Generate new keypair
2. For Payer: update `SOLANA_PAYER_SECRET` on all API nodes, rolling restart
3. For Admin: call `update_admin` on ProgramConfig with old admin signing, new admin pubkey
4. For Upgrade Authority: `solana program set-upgrade-authority` signed by current authority (Ledger)
5. For Treasury/POL: Squads multisig member rotation through Squads UI
6. Invalidate/destroy old keys after confirming new keys are operational

---

## 4. Solana Program Deployment

### 4.1 Build from Tagged Release

```bash
# Tag the release
git tag -a v1.0.0-mainnet -m "Mainnet deployment release"
git push origin v1.0.0-mainnet

# Clean build from tag
git checkout v1.0.0-mainnet
cd protocol/anchor
anchor build
python3 scripts/check-deployable-artifact.py target/deploy/boulder_rollers.so
```

**Reproducible build verification:**
```bash
# Record the program hash
sha256sum target/deploy/boulder_rollers.so
# Store this hash — it must match what is deployed
```

### 4.2 Deploy Program

**IMPORTANT:** Use `solana program deploy` directly, NOT `anchor deploy`. The `target/deploy/boulder_rollers-keypair.json` contains a wrong keypair (`J7BF7...`) that does not match the program ID. This is a known issue documented in project memory.

```bash
# Set CLI to mainnet
solana config set --url mainnet-beta

# Deploy using the correct keypair (Ledger for upgrade authority)
solana program deploy target/deploy/boulder_rollers.so \
  --program-id 6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X \
  --keypair usb://ledger \
  --url mainnet-beta \
  --with-compute-unit-price 50000 \
  --max-sign-attempts 5
```

**NOTE:** If deploying to a fresh program ID on mainnet (new address), omit `--program-id` and record the new address. Update `backend/app/solana_env.py` and `protocol/anchor/Anchor.toml` accordingly.

### 4.3 Verify Deployment

```bash
solana program show 6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X --url mainnet-beta
```

Expected output:
- Program Id matches
- Owner: `BPFLoaderUpgradeab1e11111111111111111111111`
- Authority: `<LEDGER_PUBKEY>` (hardware wallet)
- Data Length: matches .so file size
- Executable: Yes

### 4.4 Initialize ProgramConfig

The ProgramConfig PDA stores authorities and global parameters. This is a one-time initialization.

```bash
# Run the initialization script (uses submit_and_confirm internally)
# This must be called by the admin key
python -c "
import asyncio
from app.solana_direct import DirectConfig, send_initialize_config
# ... set up config with mainnet RPC, payer, admin pubkey, treasury ATA, POL ATA
"
```

**ProgramConfig fields to set:**
- `admin`: Admin hot wallet pubkey (separate from payer)
- `treasury_dung_ata`: Squads multisig treasury ATA
- `pol_dung_ata`: Squads multisig POL ATA
- `cal_mint`: CAL SPL token mint address
- `dung_mint`: DUNG SPL token mint address
- `settlement_clock_v2_starts_at`: the explicitly approved Monday 12:00 UTC
  cutover aligned to `1704110400 + K * 604800`
- `settlement_clock_version`: `2`

For an upgrade of deployed history, follow
`docs/design/SETTLEMENT_CLOCK_V2_CUTOVER_RUNBOOK.md`. Do not initialize or
migrate the clock from a local fallback timestamp.

### 4.5 Create Mint Accounts

**CAL mint** (9 decimals):
```bash
spl-token create-token --decimals 9 --mint-authority <CAL_MINT_AUTH_PDA> --url mainnet-beta
```

**DUNG mint** (9 decimals, 1B max supply enforced by DungMintState):
```bash
spl-token create-token --decimals 9 --mint-authority <DUNG_MINT_AUTH_PDA> --url mainnet-beta
```

**Devnet reference values (will differ on mainnet):**
- CAL mint: `B9u8L5pkWTce2SXJCKvNSKTrSukvWoajEdzy9STLNh6K`
- DUNG mint: `AnPJmvr1HK36DwWNQpdwW2vBd7Qq7AtAerU9kuqA9Sfn`
- CAL_MINT_AUTH PDA: `6QyEhQtK4UM7yuJuL5yweFKeE4Wri6D39dHuPriM1dxn` (bump 255)
- DUNG_MINT_AUTH PDA: `HpKUWpWndNY5MYoYZU3MP223SqAmMhvkY4afFV49vaJo` (bump 254)

### 4.6 Create Treasury and POL ATAs

```bash
# Treasury ATA (owned by Squads multisig vault)
spl-token create-account <DUNG_MINT> --owner <SQUADS_VAULT_PUBKEY> --url mainnet-beta

# POL ATA (owned by Squads multisig vault or separate POL multisig)
spl-token create-account <DUNG_MINT> --owner <POL_VAULT_PUBKEY> --url mainnet-beta
```

Record the ATA addresses and update ProgramConfig.

### 4.7 Initialize DungMintState

```bash
# One-time: create DungMintState PDA with supply caps
# max_supply = 1,000,000,000 DUNG
# community_cap = 400,000,000, treasury_cap = 250,000,000
# team_cap = 200,000,000, investor_cap = 100,000,000
```

A fresh deployment initializes the current 130-byte reservation-policy state.
An existing deployment must not rerun initialization or use an ad hoc account
resize. Follow [`DUNG_RESERVATION_MIGRATION.md`](runbooks/DUNG_RESERVATION_MIGRATION.md),
including the writer pause, complete liability census, simulation, reviewed
plan hash, finalized-slot verification, and distinct fee payer. The checked-in
script is approved keypair transport for devnet; mainnet execution requires
the separately reviewed Squads/external-signer transport before this gate can
be signed off.

---

## 5. Database Migrations

### 5.1 Migration Inventory

All migrations from 073 through 081 must be applied to the production database before go-live.

| Migration | File | Purpose | Reversible |
|-----------|------|---------|------------|
| 073 | `20260303_073_atomic_financial_ops.sql` | `unstake_cal_atomic`, `claim_vault_slot_atomic`, `stake_cal_with_cap` functions | Yes (drop functions) |
| 074 | `20260306_074_pipeline_versions.sql` | `detector_configs` + `pipeline_versions` tables, FK on rides/patterns_climb | Yes (drop tables + FK) |
| 075 | `20260306_075_tx_lifecycle.sql` | Transaction lifecycle tracking with 5 indexes, status state machine | Yes (drop table) |
| 076 | `20260306_076_atomic_cal_allocation.sql` | `mark_staging_allocated_atomic` RPC function | Yes (drop function) |
| 077 | `20260306_077_economic_events.sql` | Append-only economic ledger with hash chain, immutability triggers, `wallet_balance_at()` | **No** (immutability triggers must not be dropped in production) |
| 078 | `20260306_078_user_profile_snapshots.sql` | User profile snapshots at processing time | Yes (drop table) |
| 079 | `20260306_079_replay_system.sql` | Replay batches, ride results staging, ride diffs | Yes (drop tables) |
| 080 | `20260306_080_indexer_tables.sql` | Indexed account tables for TS indexer (11 account types) | Yes (drop tables) |
| 081 | `20260307_081_numeric_token_columns.sql` | Numeric precision for token amount columns | Caution (data type changes) |

### 5.2 Migration Procedure

```bash
# 1. Take a database backup FIRST
DATABASE_URL="<prod_direct_connection>" ./infrastructure/scripts/backup-db.sh

# 2. Apply migrations in order using direct connection (NOT pooled)
# Use Supabase Dashboard > SQL Editor, or:
psql "$DATABASE_URL" -f backend/supabase/migrations/20260303_073_atomic_financial_ops.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260306_074_pipeline_versions.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260306_075_tx_lifecycle.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260306_076_atomic_cal_allocation.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260306_077_economic_events.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260306_078_user_profile_snapshots.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260306_079_replay_system.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260306_080_indexer_tables.sql
psql "$DATABASE_URL" -f backend/supabase/migrations/20260307_081_numeric_token_columns.sql

# 3. Verify each migration applied cleanly (check for errors in output)
```

### 5.3 Post-Migration Verification

```sql
-- Verify economic_events immutability triggers exist
SELECT tgname, tgrelid::regclass FROM pg_trigger
WHERE tgname LIKE '%economic_events%';

-- Verify atomic financial ops functions exist
SELECT proname FROM pg_proc
WHERE proname IN ('unstake_cal_atomic', 'claim_vault_slot_atomic', 'stake_cal_with_cap', 'mark_staging_allocated_atomic');

-- Verify wallet_balance_at function
SELECT wallet_balance_at('test_wallet', 'CAL', NOW());

-- Verify tx_lifecycle table structure
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'tx_lifecycle' ORDER BY ordinal_position;

-- Verify hash chain on economic_events (should return 0 rows if empty, or valid chain)
SELECT COUNT(*) FROM economic_events WHERE prev_hash IS NULL AND id > 1;
```

---

## 6. Application Deployment

### 6.1 Docker Image Build

```bash
# From repo root, build from tagged release
git checkout v1.0.0-mainnet

# Build with version tag
docker build \
  -t boulderrollers/api:v1.0.0 \
  -t boulderrollers/api:latest \
  -f backend/Dockerfile \
  .

# Push to container registry
docker push boulderrollers/api:v1.0.0
docker push boulderrollers/api:latest
```

The Dockerfile (`backend/Dockerfile`) is a two-stage build:
1. **Stage 1 (rust-builder):** Builds the `workout-parse` Rust module with PyO3 bindings via maturin
2. **Stage 2 (runtime):** Python 3.11-slim with the compiled wheel, requirements.txt, and application code

Threshold releases must build and install the `workout-parse` wheel before, or
atomically with, the Python application that consumes it. If an older wheel is
briefly present, Threshold anchor extraction abstains for that ride; ingest must
remain available and the image must not be promoted until the matched wheel is
verified.

Runtime runs as `appuser` (non-root) on port 8080 via uvicorn.

### 6.2 Environment Variables (Production)

Set these in the `.env` file on each API node or in your deployment orchestration:

```bash
# --- Core ---
ENVIRONMENT=production
APP_VERSION=v1.0.0

# --- Database ---
SUPABASE_URL=https://qzkqjevawthyboymqrle.supabase.co
SUPABASE_SERVICE_KEY=<PROD_SERVICE_KEY>

# --- Auth ---
ACCESS_TOKEN_SECRET=<GENERATE_STRONG_SECRET>
REFRESH_TOKEN_SECRET=<GENERATE_STRONG_SECRET>
AUTH_AUDIENCE=boulderrollers
AUTH_ACCESS_TOKEN_MINUTES=15
AUTH_REFRESH_TOKEN_DAYS=14
AUTH_NONCE_TTL_SECONDS=300

# --- Solana ---
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=<HELIUS_KEY>
SOLANA_PAYER_SECRET=<JSON_ARRAY_OF_PAYER_KEYPAIR_BYTES>
BOULDER_ROLLERS_PROGRAM_ID=<MAINNET_PROGRAM_ID>
DUNG_MINT_ADDRESS=<MAINNET_DUNG_MINT>
CAL_MINT_ADDRESS=<MAINNET_CAL_MINT>
SOLANA_PRIORITY_FEE_MICRO_LAMPORTS=50000

# --- Feature Flags ---
CLIMB_ALGORITHM=persistence
USE_RUST_PARSER=true
CAL_ALLOCATION_MODE=live          # Live on-chain CAL allocation
USE_ASYNCPG_BULK=true             # asyncpg COPY for tile samples
ENABLE_DEV_ROUTES=false           # MUST be false in production

# --- NATS ---
NATS_URL=nats://nats:4222

# --- Strava (optional) ---
STRAVA_CLIENT_ID=<ID>
STRAVA_CLIENT_SECRET=<SECRET>
STRAVA_REDIRECT_URI=https://api.boulderroller.org/strava/callback
STRAVA_WEBHOOK_VERIFY_TOKEN=<TOKEN>
STRAVA_WEBHOOK_CALLBACK_URL=https://api.boulderroller.org/strava/webhook

# --- Monitoring ---
SENTRY_DSN=<SENTRY_DSN>
```

**CRITICAL environment variable changes from staging:**
- `SOLANA_RPC_URL`: devnet -> mainnet Helius endpoint
- `CAL_ALLOCATION_MODE`: `legacy` -> `live` (activates real on-chain CAL allocation)
- `ENABLE_DEV_ROUTES`: `true` -> `false` (admin/dev endpoints must not be exposed)
- `ENVIRONMENT`: `staging` -> `production` (affects Sentry sample rates, logging)

### 6.3 Deploy to Production Nodes

**Using the deploy script:**
```bash
# Deploy to each node (or use LB hostname for rolling deploy)
./infrastructure/scripts/deploy.sh <NODE_1_IP> v1.0.0
./infrastructure/scripts/deploy.sh <NODE_2_IP> v1.0.0
./infrastructure/scripts/deploy.sh <NODE_3_IP> v1.0.0
```

**Or with docker-compose on each node:**
```bash
ssh root@<NODE_IP>
cd /opt/boulder
docker compose pull api
docker compose up -d api
```

**IMPORTANT:** Do NOT use `docker compose up -d --force-recreate api` — this can leave the container missing. Use `docker compose up -d api` which handles recreation safely.

### 6.4 Health Check Sequence

After deploying each node, verify health in this order:

```bash
NODE=<NODE_IP>

# 1. Liveness (no dependencies)
curl -f http://$NODE:8080/health
# Expected: {"status":"ok"}

# 2. Database connectivity
curl -f http://$NODE:8080/health/db
# Expected: {"status":"ok"}

# 3. SOL balance (Solana RPC connectivity + payer wallet)
curl -f http://$NODE:8080/health/sol-balance
# Expected: {"balance_sol":X.XXXX,"alert":false,"wallet":"<PAYER_PUBKEY>","cached":false}

# 4. System status (feature flags)
curl -f http://$NODE:8080/status
# Expected: {"environment":"production","solana_stub_mode":false,"version":"v1.0.0"}

# 5. Prometheus metrics (verify scraping works)
curl -f http://$NODE:8080/metrics | head -20
```

Only proceed to the next node after all 5 checks pass on the current node.

### 6.5 Feature Flag Configuration

| Flag | Production Value | Purpose |
|------|-----------------|---------|
| `CLIMB_ALGORITHM` | `persistence` | Use v2 persistence homology climb detection |
| `USE_RUST_PARSER` | `true` | Use Rust workout-parse via PyO3 |
| `CAL_ALLOCATION_MODE` | `live` | Real on-chain CAL allocation (was `legacy` on staging) |
| `USE_ASYNCPG_BULK` | `true` | asyncpg COPY for bulk tile sample inserts |
| `ENABLE_DEV_ROUTES` | `false` | Admin/dev endpoints disabled |
| `SOLANA_STUB` | `false` (or unset) | Real Solana transactions (not stub mode) |
| `AUTH_SIGNATURE_BYPASS` | `false` | Require real wallet signatures |

### 6.6 Rollback (Quick Reference)

If any health check fails, immediately roll back:

```bash
# Roll back to previous image tag
./infrastructure/scripts/deploy.sh <NODE_IP> <PREVIOUS_TAG>
```

See [Section 9](#9-rollback-procedure) for full rollback procedure.

---

## 7. Post-Deploy Validation

Perform these validations after all 3 nodes are deployed and healthy.

### 7.1 Smoke Tests

| Test | Procedure | Expected | Sign-off |
|------|-----------|----------|----------|
| Health endpoints | Hit all 4 health endpoints via LB | All return 200 | [ ] |
| Auth flow | Login with test wallet via Privy | JWT issued, user created | [ ] |
| Ride upload (end-to-end) | Upload a test FIT file | Parsed, CAL earned, tiles stored, canon traversals matched; off-canon efforts remain discovery nominations only | [ ] |
| CAL balance | `GET /cal/onchain` | Reflects CAL from uploaded ride | [ ] |
| Vault matching | Upload ride crossing a canon climb with an active vault | Exact canon-bound Vault completion recorded | [ ] |
| Vault creation | Open an unactivated current ratified Climb and create its Vault | Exact Climb commitment copied, Vault indexed, activation finalized, PDA initialized | [ ] |
| Staking flow | Stake CAL in a vault | `vault_stakes` record created, effective_from_epoch set | [ ] |
| Unstaking flow | Unstake from vault | Atomic unstake succeeds, principal returned | [ ] |
| Settlement Week finalization | Wait for wall-clock week end + 24h grace window, then trigger finalize_settlement_week | Per-bucket direct allocation verified (55/27/3/5/10) | [ ] |
| tx_lifecycle tracking | Check `tx_lifecycle` table after any on-chain action | Rows present with correct status progression | [ ] |

### 7.2 Economic Ledger Verification

```bash
# After processing a test ride, verify dual-write consistency
curl "https://api.boulderroller.org/dev/ledger/consistency?wallet=<TEST_WALLET>"
# Expected: zero drift in economic_events ledger

# Verify hash chain integrity
curl "https://api.boulderroller.org/dev/ledger/verify-chain?wallet=<TEST_WALLET>&denomination=CAL"
# Expected: valid chain
```

**Note:** Dev routes must be temporarily enabled for these checks (set `ENABLE_DEV_ROUTES=true` on one node, then disable after verification).

### 7.3 Transaction Lifecycle Monitoring

```sql
-- Check for any failed transactions
SELECT tx_type, status, error_message, created_at
FROM tx_lifecycle
WHERE status IN ('failed', 'expired')
ORDER BY created_at DESC
LIMIT 20;

-- Verify confirmation rates
SELECT tx_type,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE status = 'confirmed') AS confirmed,
       COUNT(*) FILTER (WHERE status = 'finalized') AS finalized,
       COUNT(*) FILTER (WHERE status = 'failed') AS failed
FROM tx_lifecycle
GROUP BY tx_type;
```

### 7.4 Performance Baseline

After 1 hour of production traffic, capture baseline metrics:

```
solana_rpc_latency_seconds (p50, p95, p99)
solana_rpc_errors_total / solana_rpc_calls_total (error rate)
ride_phase_duration_seconds by phase
supabase_request_duration_seconds by operation
solana_payer_balance_sol
```

Store these as the production baseline for alerting threshold calibration.

---

## 8. Failure Drills

These 6 scenarios must be executed on devnet before mainnet go-live, and periodically (quarterly) thereafter. Each drill validates a specific failure mode and the system's response.

### Drill 1: Duplicate Transaction Submission

**Scenario:** Two API nodes simultaneously attempt to submit the same vault creation transaction.

**Setup:**
1. Configure two API instances pointing at the same payer wallet
2. Craft a vault creation request and send it to both simultaneously

**Expected outcome:**
- `tx_lifecycle` records two `pending` rows
- One succeeds (status: `confirmed`), one fails with "already processed" or similar
- Vault is created exactly once (no double-creation)
- `economic_events` shows exactly one vault creation event

**Success criteria:** No duplicate on-chain state. Failed tx is recorded in `tx_lifecycle` with clear error.

### Drill 2: Stale Indexer (>5 min lag)

**Scenario:** The TypeScript indexer falls behind by more than 5 minutes.

**Setup:**
1. Pause the indexer service
2. Submit several on-chain transactions (vault create, stake, distribute)
3. Wait 5+ minutes, then resume the indexer

**Expected outcome:**
- Indexer detects gap via `sync_state` table
- Triggers Replay mode to backfill missed slots
- All transactions eventually appear in indexed tables
- `SolanaIndexerLag` alert fires when lag exceeds threshold

**Success criteria:** Zero data loss after indexer recovery. All account states match on-chain.

### Drill 3: Expired Blockhash Under Load

**Scenario:** Network congestion causes blockhash to expire before transaction lands.

**Setup:**
1. Set `SOLANA_PRIORITY_FEE_MICRO_LAMPORTS=1` (minimum fee, likely to be outbid)
2. Submit a batch of 10 transactions rapidly

**Expected outcome:**
- `submit_and_confirm()` detects `_BlockhashExpiredError`
- Retries with exponential backoff (2s, 4s, 8s per `BACKOFF_SCHEDULE`)
- Up to `DEFAULT_MAX_RETRIES=3` attempts per transaction
- `tx_lifecycle` shows `expired` -> `submitted` -> `confirmed` status progression
- Prometheus counter `solana_rpc_errors_total` incremented

**Success criteria:** Transactions eventually land after retry. No silent failures.

### Drill 4: Partial Settlement (tx landed but DB update failed)

**Scenario:** A Solana transaction confirms on-chain, but the subsequent database update fails (e.g., Supabase timeout).

**Setup:**
1. Submit a stake transaction
2. Simulate DB failure immediately after `submit_and_confirm()` returns success (e.g., revoke Supabase service key temporarily)

**Expected outcome:**
- `tx_lifecycle` shows `confirmed` status (on-chain succeeded)
- Database state is inconsistent (stake not recorded in `vault_stakes`)
- Reconciliation via indexer detects the mismatch: on-chain VaultStake exists but DB row is missing
- Operator manually or automatically reconciles

**Success criteria:** The inconsistency is detectable via `tx_lifecycle` + indexer reconciliation. Recovery procedure restores consistency.

### Drill 5: Replay Mismatch Detection

**Scenario:** A ride is reprocessed with a newer pipeline version and produces different economic outcomes.

**Setup:**
1. Process a ride with pipeline version V1
2. Update climb detection parameters (new `detector_configs` row)
3. Replay the ride via `POST /dev/replay/ride/<ride_id>`

**Expected outcome:**
- `replay_ride_results` staging table shows new metrics alongside original
- `ride_diffs` table contains structured diff (JSONB) with changes highlighted
- Explanation generated in plain English
- Economic outcomes are NOT applied until human review and promotion

**Success criteria:** Diff is accurate and human-readable. No automatic economic changes from replay.

### Drill 6: Key Compromise Response

**Scenario:** The payer hot wallet private key is exposed.

**Response procedure:**
1. **Immediate (< 5 minutes):**
   - Generate new payer keypair
   - Update `SOLANA_PAYER_SECRET` on all 3 API nodes
   - Rolling restart of API services
   - Drain SOL from compromised wallet to new wallet
2. **Assessment (< 1 hour):**
   - Review `tx_lifecycle` for any unauthorized transactions
   - Check on-chain accounts for unexpected state changes
   - Verify ProgramConfig admin has not been changed
3. **Communication:**
   - Internal incident channel notification
   - If user funds affected: public disclosure per incident template (see [Section 9.4](#94-communication-template))
4. **Post-incident:**
   - Root cause analysis
   - Key rotation for any keys that may have been co-located

**Success criteria:** New payer operational within 15 minutes. No unauthorized on-chain state changes possible (payer cannot modify program or mint tokens — only admin/upgrade authority can).

---

## 9. Rollback Procedure

### 9.1 API Rollback

```bash
# Identify the previous working tag
docker image ls boulderrollers/api --format "{{.Tag}}" | head -5

# Roll back each node
./infrastructure/scripts/deploy.sh <NODE_1_IP> <PREVIOUS_TAG>
./infrastructure/scripts/deploy.sh <NODE_2_IP> <PREVIOUS_TAG>
./infrastructure/scripts/deploy.sh <NODE_3_IP> <PREVIOUS_TAG>

# Verify health on each node
for NODE in <NODE_1_IP> <NODE_2_IP> <NODE_3_IP>; do
  curl -f http://$NODE:8080/health && echo " OK: $NODE" || echo " FAIL: $NODE"
done
```

The deploy script tags each deployed image as `boulderrollers/api:current` on the host, so the previous tag is always recoverable from the registry.

### 9.2 Database Rollback

**Migration reversibility notes:**

| Migration | Rollback SQL | Risk |
|-----------|-------------|------|
| 073 | `DROP FUNCTION unstake_cal_atomic, claim_vault_slot_atomic, stake_cal_with_cap;` | Low — functions only |
| 074 | `ALTER TABLE rides DROP COLUMN pipeline_version_id; ALTER TABLE patterns_climb DROP COLUMN pipeline_version_id; DROP TABLE pipeline_versions, detector_configs;` | Medium — lose version tracking |
| 075 | `DROP TABLE tx_lifecycle;` | Medium — lose transaction history |
| 076 | `DROP FUNCTION mark_staging_allocated_atomic;` | Low — function only |
| 077 | **DO NOT ROLL BACK** — `economic_events` is append-only with immutability triggers. Rolling back destroys audit trail. | **CRITICAL** |
| 078 | `DROP TABLE user_profile_snapshots;` | Low |
| 079 | `DROP TABLE replay_batches, replay_ride_results, ride_diffs;` | Low |
| 080 | Drop all 11 `indexed_*` tables | Medium — indexer stops working |
| 081 | Reverse column type changes (check migration for specifics) | Medium — precision loss risk |

**General rule:** Only roll back migrations if the API version being rolled back to does not reference the new tables/functions. Otherwise, leave migrations in place — they are additive.

### 9.3 On-Chain Program Rollback

If the mainnet program has a critical bug:

```bash
# Deploy previous .so binary (must have been saved from previous build)
solana program deploy target/deploy/boulder_rollers_PREVIOUS.so \
  --program-id 6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X \
  --keypair usb://ledger \
  --url mainnet-beta

# Verify
solana program show 6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X --url mainnet-beta
```

**IMPORTANT:** Always keep tagged builds of every deployed `.so` file. Store them alongside their git tag:
```
releases/
  v1.0.0/boulder_rollers.so
  v1.0.0/sha256sum.txt
  v1.0.1/boulder_rollers.so
  v1.0.1/sha256sum.txt
```

**On-chain state considerations:**
- Program upgrades do NOT reset account data
- If the new program changed account layouts, rolling back may cause deserialization failures
- In that case: deploy a hotfix .so that handles both old and new layouts, or freeze the program until resolved

### 9.4 Communication Template

For user-facing incidents:

```
Subject: [Boulder Rollers] Service Update — <DATE>

We experienced an issue with <BRIEF_DESCRIPTION> starting at <TIME UTC>.

Impact: <WHAT USERS SAW — e.g., "ride uploads were delayed", "staking was temporarily unavailable">

Current status: <RESOLVED / INVESTIGATING / MITIGATED>

Actions taken:
- <SPECIFIC ACTION 1>
- <SPECIFIC ACTION 2>

Your data: <REASSURANCE — e.g., "No ride data was lost. Token balances are accurate.">

We apologize for the inconvenience. If you notice any discrepancies,
please contact support@boulderroller.org.
```

---

## 10. Monitoring & Alerts

### 10.1 Prometheus Metrics Endpoints

| Endpoint | Source | Scrape Interval |
|----------|--------|-----------------|
| `http://<API_NODE>:8080/metrics` | FastAPI app (`backend/app/routes/health.py`) | 15s |
| `http://<NODE_EXPORTER>:9100/metrics` | node_exporter (CPU, memory, disk) | 15s |
| `http://<CADVISOR>:8080/metrics` | cAdvisor (container metrics) | 15s |

**Key Prometheus metrics** (defined in `backend/app/metrics.py`):

| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| `solana_payer_balance_sol` | Gauge | — | Payer wallet SOL balance |
| `solana_rpc_calls_total` | Counter | `method` | RPC call volume by tx type |
| `solana_rpc_errors_total` | Counter | `method` | RPC failures by tx type |
| `solana_rpc_latency_seconds` | Histogram | `method` | RPC latency distribution |
| `ride_phase_runs_total` | Counter | `phase`, `status` | Ride processing pipeline |
| `ride_phase_duration_seconds` | Histogram | `phase` | Processing time per phase |
| `kpi_ride_uploads_total` | Counter | `status` | Upload success/failure |
| `kpi_stakes_total` | Counter | `status` | Staking events |
| `kpi_unstakes_total` | Counter | `status` | Unstake events |
| `kpi_dung_minted_total` | Counter | `source` | DUNG minting volume |
| `supabase_request_duration_seconds` | Histogram | `operation` | DB call latency |
| `supabase_request_errors_total` | Counter | `operation` | DB failures |

### 10.2 Alert Rules

Alert rules are defined in `infrastructure/monitoring/prometheus/alert_rules.yml`. Current groups:

**boulder-api group:**
- `APIDown` — API unreachable for 2 minutes (CRITICAL)
- `HighErrorRate` — >5% 5xx responses over 5 minutes (WARNING)
- `HighLatency` — p95 latency >1s over 5 minutes (WARNING)

**infrastructure group:**
- `HighCPUUsage` — >80% CPU for 10 minutes (WARNING)
- `HighMemoryUsage` — >85% memory for 5 minutes (WARNING)
- `LowDiskSpace` — <15% disk remaining (WARNING)
- `ContainerDown` — Critical container missing for 2 minutes (CRITICAL)
- `ContainerHighCPU` — Container >80% CPU for 10 minutes (WARNING)
- `ContainerRestarting` — >3 restarts in 1 hour (WARNING)

**solana-ops group:**
- `PayerSolBalanceLow` — <0.5 SOL for 5 minutes (WARNING)
- `PayerSolBalanceCritical` — <0.1 SOL for 1 minute (CRITICAL)
- `SolanaRPCErrorRateHigh` — >20% RPC errors over 5 minutes (WARNING)

**auth-entry group:**
- `AuthVerifyFailureRateHigh` — >25% auth verify failures (WARNING)
- `AuthRefreshFailureRateHigh` — >15% refresh failures (WARNING)
- `InviteValidationFailuresHigh` — >50% invite failures (WARNING)
- `CorsPreflightFailuresHigh` — OPTIONS failures detected (WARNING)

### 10.3 Alertmanager Configuration

**File:** `infrastructure/monitoring/prometheus/alertmanager.yml`

**BEFORE MAINNET:** Replace placeholder webhook URLs with real notification endpoints:

```yaml
receivers:
  - name: 'default-receiver'
    webhook_configs:
      - url: 'https://hooks.slack.com/services/T.../B.../xxx'  # Real Slack webhook
        send_resolved: true

  - name: 'critical-receiver'
    # PagerDuty for critical alerts
    pagerduty_configs:
      - service_key: '<PAGERDUTY_SERVICE_KEY>'
        severity: critical
    # Also notify Slack
    webhook_configs:
      - url: 'https://hooks.slack.com/services/T.../B.../xxx'
        send_resolved: true
```

**Routing:**
- `severity: critical` -> `critical-receiver` (PagerDuty + Slack, repeat every 1 hour)
- Everything else -> `default-receiver` (Slack only, repeat every 4 hours)

### 10.4 SOL Balance Auto-Refill

The system monitors SOL balance via the `/health/sol-balance` endpoint (60-second cache, Prometheus gauge updated on each call).

**Alert thresholds:**
- **0.5 SOL** — `PayerSolBalanceLow` warning fires. Operator should refill within 24 hours.
- **0.1 SOL** — `PayerSolBalanceCritical` critical fires. Immediate action required.

**Manual refill procedure:**
```bash
# From a funded wallet (treasury or personal)
solana transfer <PAYER_PUBKEY> 2.0 \
  --keypair <FUNDED_WALLET> \
  --url mainnet-beta \
  --allow-unfunded-recipient
```

**Automated refill (future):**
If transaction volume warrants it, implement a cron job or DBOS workflow that:
1. Checks payer balance every 5 minutes
2. If below 1.0 SOL, transfers 2.0 SOL from a refill wallet
3. Logs the refill event to `economic_events` for audit trail
4. Alerts on refill failure

### 10.5 Dashboard Recommendations

Set up Grafana dashboards for:

1. **Operations Overview** — ride uploads, processing times, error rates, active users
2. **Solana Health** — RPC latency, error rate, payer balance, tx_lifecycle status distribution
3. **Economic Activity** — CAL earned, stakes/unstakes, vault distributions, DUNG minted
4. **Infrastructure** — CPU, memory, disk, container health across 3 nodes

---

## Appendix A: Program Constants Reference

From `protocol/anchor/programs/boulder_rollers/src/lib.rs`:

```rust
CAL_BURN_PER_SEGMENT: 100
CAL_TO_DUNG_THRESHOLD: 1,000
DUNG_DECIMALS_MULTIPLIER: 1,000,000,000  // 9 decimals
MINIMUM_STAKE: 10 DUNG (with decimals)
VAULT_CREATION_DUNG: 100 DUNG
VAULT_CREATION_CAL: 1,000 CAL
VAULT_CREATION_USDC: $2 (6 decimals)
CAL_DECIMALS: 9
CAL_MIN_STAKE: 100 CAL (with decimals)
MINTER_RIGHTS_EPOCHS: 12
EPOCH_DURATION_SECONDS: 604,800  // 7 days
HARVEST_FEE_BPS: 500  // 5%
EXIT_FEE_BPS: 50  // 0.5%
SETTLEMENT_WEEK_V2_ANCHOR: 1704110400  // Mon Jan 1 2024 12:00:00 UTC
SETTLEMENT_CLOCK_VERSION: 2
```

## Appendix B: File Reference

| File | Purpose |
|------|---------|
| `backend/app/services/solana_submit.py` | Unified `submit_and_confirm()` framework |
| `backend/app/solana_direct.py` | All `send_*` functions (vault create, stake, distribute, etc.) |
| `backend/app/solana_env.py` | Program IDs and RPC URL from environment |
| `backend/app/routes/health.py` | Health check endpoints including `/health/sol-balance` |
| `backend/app/metrics.py` | All Prometheus metric definitions |
| `backend/app/services/economic_ledger.py` | Append-only economic ledger service |
| ~~`backend/app/services/points_service.py`~~ | ~~Points award~~ (removed April 2026) |
| `backend/app/services/cal_allocator.py` | Atomic CAL allocation |
| `protocol/anchor/Anchor.toml` | Program ID, cluster config, toolchain version |
| `protocol/anchor/programs/boulder_rollers/src/lib.rs` | On-chain constants and seeds |
| `infrastructure/terraform/prod/main.tf` | Production Terraform (3 nodes, LB) |
| `infrastructure/monitoring/prometheus/alert_rules.yml` | Prometheus alert rules |
| `infrastructure/monitoring/prometheus/alertmanager.yml` | Alert notification routing |
| `infrastructure/scripts/deploy.sh` | Deployment helper script |
| `infrastructure/scripts/backup-db.sh` | Database backup script |
| `docker-compose.yml` | Service definitions (API, Redis, Celery, NATS, Caddy) |
| `backend/Dockerfile` | Two-stage Docker build (Rust + Python) |

## Appendix C: Go/No-Go Checklist

Final sign-off before flipping to mainnet. All items must be checked.

- [ ] All 14 P0 blockers resolved and verified
- [ ] Backend test suite: 168 passing
- [ ] Anchor test suite: 15 passing
- [ ] Staging end-to-end validation: ride upload -> CAL earned -> vault match -> stake
- [ ] Upgrade authority on hardware wallet
- [ ] Treasury on Squads multisig
- [ ] Payer funded with >= 2 SOL
- [ ] Alertmanager receivers configured with real Slack/PagerDuty endpoints
- [ ] All migrations 073-081 applied and verified
- [ ] Economic ledger hash chain valid
- [ ] All 6 failure drills completed on devnet
- [ ] Security audit report reviewed and findings addressed
- [ ] Database backup verified and restorable
- [ ] Rollback procedure tested (deploy previous tag, verify health)
- [ ] Communication channels ready (status page, Slack, support email)
- [ ] DNS updated for production domain
- [ ] `ENABLE_DEV_ROUTES=false` on all production nodes
- [ ] `CAL_ALLOCATION_MODE=live` confirmed

Stage 1 localnet tests use `scripts/build-stage1-localnet.py --test`, a separate
program ID and `.anchor/stage1-localnet` artifacts. Never deploy that binary.
Run the artifact guard from `protocol/anchor` on the exact binary being
deployed; `scripts/preflight.sh` refuses localnet-feature binaries before RPC
or upgrade-authority access. The draft Stage 1 branch must not merge until
Tim signs the devnet upgrade: its 0x4D clients reject the deployed 0x4C ABI.
