# Boulder Rollers Telegram Bot

Lightweight bot to interact with the Boulder Rollers backend (upload rides, view balances, leaderboard, claims) without storing private keys. Reuses the same FastAPI endpoints and wallet-sign auth flow, with optional background notifications.

## Features
- Link/unlink a wallet (wallet-sign flow via `/auth/nonce` + `/auth/verify`; `/link <wallet>` shortcut).
- Upload FIT/GPX/TCX via Telegram and forward to `/rides/upload`; polls status and shows matched segments, DUNG minted, and Solscan links when available.
- Query DUNG/kCAL balances, staking claims, pending staking rewards, and leaderboard.
- kCAL airdrop timing surfaced in responses.
- Optional background notifications: ride processed, kCAL airdrop ready, pending staking rewards (enable with `/notify on`).
- Polling (default) or webhook mode for Telegram delivery.
- Structured JSON logging for production.

## Structure
- `main.py` – aiogram bot entrypoint (polling mode by default).
- `backend_client.py` – async HTTP client wrapping backend endpoints (auth, upload, balances, claims, leaderboard).
- `storage.py` – simple Postgres/Supabase storage for chat ↔ wallet/tokens mapping (optional; if `DATABASE_URL` unset, state is ephemeral).
- `requirements.txt` – bot-only deps.
- `.env.example` – config template.

## Requirements
- Python 3.11+
- A Telegram bot token (BotFather)
- Backend API reachable (e.g., https://api.boulderroller.org)
- Optional: Postgres/Supabase table `bot_links(chat_id bigint primary key, wallet text, access_token text, refresh_token text, notify bool)`

## Setup
```bash
cd bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with TELEGRAM_BOT_TOKEN and BACKEND_API_URL; optionally DATABASE_URL
python main.py
```
By default, the bot runs in polling mode (`USE_POLLING=true`). Webhook mode is supported (set `USE_POLLING=false`, `WEBHOOK_URL`, `WEBHOOK_SECRET_TOKEN`).

## Commands
- `/start` `/help` – help text
- `/link` or `/link <wallet>` – ask for wallet, fetch nonce, expect signature, store access/refresh tokens
- `/unlink` – remove stored link
- `/dung` – show token balances via `/mint`
- `/kcal` – show kCAL via `/cal/balance` (with airdrop timer)
- `/claims` – show staking claims and pending rewards
- **Upload** – send a FIT/GPX/TCX file; bot posts to `/rides/upload`, polls status, then fetches matched segments
- `/notify on|off` – toggle notify flag for background pushes

### Signing helper
- Use `bot/signer.html` locally: open the file in a browser with Phantom/Solflare installed, paste the message from `/link`, click “Connect Wallet” then “Sign Message”, and copy the base58 signature back to the bot.

## Config
- `TELEGRAM_BOT_TOKEN` – required
- `BACKEND_API_URL` – required (e.g., https://api.boulderroller.org)
- `DATABASE_URL` – optional Postgres DSN for persistent chat links (e.g., from Supabase)
- `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` – only if you adapt storage to Supabase directly
- `USE_POLLING` – default true; set false to use webhook server
- `WEBHOOK_URL`, `WEBHOOK_SECRET_TOKEN` – for webhook mode (Telegram secret token)
- `HOST`, `PORT` – webhook server bind (default 0.0.0.0:8081)
- `NOTIFY_INTERVAL_SECONDS` – background notification sweep cadence (default 180); set to 0 to disable
- `SOLSCAN_BASE` – override Solscan host if needed

## Safety
- Bot never stores private keys.
- Uses the same backend auth flow as the app (wallet signature) to obtain per-user access/refresh tokens.
- Validate file types and size; current code accepts FIT/GPX/TCX from Telegram (subject to Telegram limits).
