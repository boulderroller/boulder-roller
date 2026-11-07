# Boulder Rollers Backend (FastAPI)

FastAPI app powering auth, rides, staking, analytics, comments/kudos, leaderboard, notifications, portfolio, and waitlist flows. Supabase is the primary data store.

## Run locally
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export SUPABASE_URL=... SUPABASE_SERVICE_KEY=...
export ACCESS_TOKEN_SECRET=... REFRESH_TOKEN_SECRET=... AUTH_AUDIENCE=...
uvicorn app.main:app --app-dir app --reload
```

## Key routes
- `/auth/*` – wallet-based auth/refresh/logout.
- `/rides/*` – upload/status/streams/comments/kudos.
- `/segments/*` – list/nearby segments.
- `/staking/*` – stake/claims/unstake.
- `/analytics/*` – fitness metrics, history, training load, recommendations.
- `/leaderboard/{segment_id}` – leaderboard per segment/epoch.
- `/portfolio` – claim totals + positions.
- `/notifications/*`, `/social/*`, `/feed/*`, `/cal/*`, `/mint/*`, `/proofs/*`, `/waitlist`.

## CORS
Configured in `app/main.py`. Ensure your canonical portal origins (`https://app.boulderroller.xyz`, `https://boulderroller.xyz`, previews, localhost) are allowed.

## Testing
```bash
cd backend
pytest
```
`EmergencyCheckMiddleware` fails open in test mode or if Supabase creds are missing; set real env vars for integrated runs.

## Notes
- Repository layer is Supabase-backed; env vars must be present in non-test environments.
- Additional config lives in `app/config.py` and env variables.
