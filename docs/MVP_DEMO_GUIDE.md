# MVP Demo Guide (Boulder Rollers)

## 1) Quick Setup
- API base: `http://[STAGING_LB_IP]` (LB → droplet 8080)
- Database: Supabase Postgres `db.qzkqjevawthyboymqrle.supabase.co`
- Solana: Devnet (programs live; not stubbed)
- Required secrets (already on droplet `/root/.env`): `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `JWT_SECRET` (also used for access/refresh), `SOLANA_RPC_URL=https://api.devnet.solana.com`, `BOULDER_ROLLERS_PROGRAM_ID`, `DUNG_MINT_PROGRAM_ID`, `PROOF_VERIFIER_PROGRAM_ID`, `DUNG_MINT_ADDRESS`
- Docker commands (if you need to restart):
  ```bash
  ssh root@[STAGING_IP]
  docker stop boulder-api || true
  docker rm boulder-api || true
  cd /root/boulder-repo/backend
  docker build -t boulder-api:dev .
  docker run -d --name boulder-api --restart unless-stopped -p 8080:8080 --env-file /root/.env boulder-api:dev
  ```

## 2) Demo Script (API-first or iOS-first)
### Option A: API (curl/Postman)
1. Health check: `curl http://[STAGING_LB_IP]/health/db` → expect `200`.
2. Nonce: `POST /auth/nonce` with `{"wallet_address":"<wallet>"}`.
3. Sign & verify: `POST /auth/verify` with wallet signature + nonce → get access/refresh JWTs.
4. CAL:
   - `GET /cal/balance` (Bearer token)
   - `POST /cal/mint` (Bearer token) → should hit Solana devnet (direct RPC).
5. Segments: `GET /segments/nearby?lat=40.7&lon=-74&radius_km=5`.
6. Staking (if wallet funded on devnet):
   - `POST /staking/stake` with segment + amount
   - `POST /staking/unstake` to unwind

### Option B: iOS
1. Point app API base to `http://[STAGING_LB_IP]` (already set in integration registry).
2. Build/run (Swift 6, deps: Kingfisher + TweetNacl + Base58).
3. Flow:
   - Launch app, create/import wallet.
   - Auth: triggers `/auth/nonce` → sign → `/auth/verify`.
   - Mint CAL: invoke `/cal/mint`, confirm balance updates.
   - Browse segments: ensure `/segments/nearby` loads.
   - (Optional) Stake flow if devnet funds available.

## 3) Architecture (text overview)
- **Clients**: iOS app (native), Web portal (React components in `web/portal-figma/`, pending API wiring).
- **API**: FastAPI service in Docker on DO droplet (`boulder-api`), fronted by DO LB.
- **Data**: Supabase Postgres (managed), Supabase service key for server-side.
- **Solana**: Devnet programs (boulder_rollers, dung_mint, proof_verifier) accessed via direct RPC (`solana_direct.py`).
- **Infra**: DigitalOcean VPC + droplet + load balancer; dockerized API; env file on droplet.
- **Auth**: Wallet-based nonce/signature → JWT (access/refresh).

## 4) Key Features to Highlight
- Wallet-based auth and JWT issuance.
- CAL minting hitting live Solana devnet (not stubbed).
- Segments/nearby lookup and staking endpoints.
- Stable infra: LB + droplet; quick redeploy via Docker.
- iOS app build now Swift-6 compatible without Solana.Swift.

## 5) Roadmap / Next Steps
- Wire web portal components to live API and add env-based base URL.
- Add GitHub Actions CI/CD with secrets (`DO_TOKEN`, `DO_SSH_KEY`, `DEV_DROPLET_IP`, `DATABASE_URL`, JWT/program IDs).
- Monitoring/alerts on DO (CPU/disk/LB health) and optional Prometheus/Grafana.
- TestFlight distribution for iOS; smoke tests on real device.
- SSL + domain for API (optional for dev), plus WAF/rate limits if exposed broadly.
