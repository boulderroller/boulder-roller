# Boulder Rollers: Master Context Document

> **Read this first.** You will be assigned a Worker ID (A, B, C, D, or E). Find your runbook and execute it.

---

## Your Assignment

When spawned, you will be told: "You are Worker X"

| Worker | Runbook | Domain |
|--------|---------|--------|
| **A** | `WORKER_A_DEFI_TOKENOMICS.md` | Vesting, harvesting, transaction history |
| **B** | `WORKER_B_SOCIAL_BACKEND.md` | Follows, feed, notifications, comments |
| **C** | `WORKER_C_IOS_FEATURES.md` | Achievements UI, DUNG celebration, ride history |
| **D** | `WORKER_D_TRAINING_ANALYTICS.md` | CTL/ATL/TSB, power zones, trends |
| **E** | `WORKER_E_SECURITY_COMPLIANCE.md` | GDPR, rate limiting, emergency pause |

**Your task:** Read your assigned runbook and implement everything in it.

---

## Project Structure

```
BoulderRollers-v2/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, router registration
│   │   ├── dependencies.py      # get_db, get_current_user_id
│   │   ├── repositories.py      # Existing repo classes
│   │   ├── schemas.py           # Pydantic models
│   │   ├── routes/
│   │   │   ├── auth.py          # SIWS authentication
│   │   │   ├── cal.py           # CAL minting
│   │   │   ├── rides.py         # Ride upload/processing
│   │   │   ├── staking.py       # Stake/unstake DUNG
│   │   │   ├── users.py         # User profiles
│   │   │   └── segments.py      # Segment leaderboards
│   │   └── services/
│   │       ├── token_mint.py    # DUNG minting logic
│   │       ├── ride_parser.py   # FIT/GPX parsing
│   │       └── ride_metrics.py  # TSS calculation
│   ├── sql/                     # Migration files (numbered)
│   └── tests/                   # Pytest tests
├── ios/
│   └── BoulderRollers/
│       ├── BoulderRollersApp.swift    # App entry, tab bar
│       ├── Services/
│       │   └── APIClient.swift        # HTTP client
│       ├── Utilities/
│       │   ├── AppState.swift         # Global state
│       │   └── DesignSystem.swift     # UI components
│       ├── Models/                    # Codable structs
│       └── Views/
│           ├── Auth/SignInView.swift
│           ├── CAL/CALView.swift
│           ├── Map/MapView.swift
│           ├── Profile/ProfileView.swift
│           └── Rides/RideUploadView.swift
└── web/
    └── portal/
        └── src/
            ├── lib/api.ts             # API client
            ├── contexts/AppContext.tsx
            └── components/            # React components
```

---

## Shared Database Connection

All backend code uses the same database pattern:

```python
# Dependency injection
from backend.app.dependencies import get_db, get_current_user_id

@router.get("/example")
async def example(
    user_id: str = Depends(get_current_user_id),
    db = Depends(get_db)
):
    # db is asyncpg connection
    row = await db.fetchrow("SELECT * FROM users WHERE id = $1", UUID(user_id))
```

---

## SQL Migration Numbering

**CRITICAL: Check existing migrations before creating new ones.**

Current highest: `010_user_profiles.sql`

| Worker | Reserved Range |
|--------|----------------|
| A | 011-013 |
| B | 014-016 |
| C | N/A (iOS only) |
| D | 017-019 |
| E | 020-022 |

Before creating a migration:
```bash
ls backend/sql/*.sql | tail -5
```

---

## API Route Registration

New routers must be registered in `backend/app/main.py`:

```python
# In main.py
from backend.app.routes import your_new_router

app.include_router(your_new_router.router, prefix="/api/v1")
```

---

## iOS APIClient Pattern

All iOS API calls go through `APIClient.swift`:

```swift
// Add new endpoint method
func getExample() async throws -> ExampleResponse {
    return try await request(
        endpoint: "/example",
        method: "GET",
        responseType: ExampleResponse.self
    )
}
```

---

## Coordination Rules

### DO NOT TOUCH (Owned by other workers)

| File/Table | Owner | Reason |
|------------|-------|--------|
| `token_balances` table | Worker A | Vesting changes |
| `follows` table | Worker B | Social graph |
| `achievements` table | Worker C | iOS display |
| `rides` table columns | Worker D | Analytics fields |
| `audit_log` table | Worker E | Compliance |

### SAFE TO READ (Shared dependencies)

- `users` table - All workers can SELECT
- `rides` table - All workers can SELECT existing columns
- `token_balances` - Workers B, C, D can SELECT

### NOTIFY IF CHANGING

If you need to modify a shared file, add a comment at the top:

```python
# MODIFIED BY WORKER X: Added field Y for Z reason
```

---

## Testing Requirements

Before marking complete, each worker must:

1. **Unit tests pass**: `cd backend && python -m pytest tests/test_your_module.py -v`
2. **No import errors**: `python -c "from backend.app.routes.your_module import router"`
3. **Migration runs**: `psql $DATABASE_URL < backend/sql/0XX_your_migration.sql`
4. **iOS builds** (Worker C only): `xcodebuild -scheme BoulderRollers build`

---

## Environment & Secrets

```bash
# Backend .env (already configured on server)
DATABASE_URL=postgresql://...
SOLANA_RPC_URL=https://api.devnet.solana.com
REDIS_URL=redis://localhost:6379

# Server access
SSH: ssh root@STAGING_IP
DB on server: docker exec -it boulder-db psql -U boulder -d boulder
```

---

## Existing Schemas You'll Need

### Users Table
```sql
CREATE TABLE users (
    id UUID PRIMARY KEY,
    wallet_address VARCHAR(44) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    avatar_url TEXT,
    bio TEXT,
    ftp_watts INTEGER,
    weight_kg NUMERIC(5,2),
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Token Balances Table
```sql
CREATE TABLE token_balances (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    dung_balance BIGINT DEFAULT 0,
    cal_balance BIGINT DEFAULT 0,
    lp_balance BIGINT DEFAULT 0,
    last_cal_mint TIMESTAMPTZ
);
```

### Rides Table
```sql
CREATE TABLE rides (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    file_hash VARCHAR(64),
    status VARCHAR(20),  -- 'pending', 'processing', 'completed', 'failed'
    started_at TIMESTAMPTZ,
    distance_m NUMERIC,
    elevation_gain_m NUMERIC,
    duration_sec INTEGER,
    avg_power_w NUMERIC,
    max_power_w NUMERIC,
    tss NUMERIC,
    normalized_power_w NUMERIC,
    dung_minted BIGINT,
    created_at TIMESTAMPTZ DEFAULT now()
);
```

### Achievements Table
```sql
CREATE TABLE achievements (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    type VARCHAR(50),  -- 'kom', 'pr', 'podium', 'distance_milestone', etc.
    name VARCHAR(100),
    description TEXT,
    ride_id UUID REFERENCES rides(id),
    metadata JSONB,
    earned_at TIMESTAMPTZ DEFAULT now()
);
```

---

## Communication Protocol

Since you're working in parallel:

1. **Don't wait** - If you need something from another worker's domain, stub it and move on
2. **Document stubs** - Mark any placeholder code clearly:
   ```python
   # TODO(WORKER_B): Replace with real follow count query
   follow_count = 0
   ```
3. **Report blockers** - If truly blocked, note it in your final summary

---

## Completion Checklist

When done, report:

```
## Worker X Complete

### Files Created
- backend/app/routes/xxx.py
- backend/sql/0XX_xxx.sql
- ios/BoulderRollers/Views/Xxx.swift (if applicable)

### Files Modified
- backend/app/main.py (added router)
- backend/app/schemas.py (added models)

### Tests
- Unit: X passing
- Integration: X passing

### Manual Testing Needed
- [ ] Item 1
- [ ] Item 2

### Blockers/Notes
- None / List any issues
```

---

## Quick Reference

| Action | Command |
|--------|---------|
| Run backend tests | `cd backend && python -m pytest -v` |
| Run specific test | `python -m pytest tests/test_file.py::test_name -v` |
| Check SQL syntax | `psql -f backend/sql/0XX_file.sql --echo-errors` |
| iOS build check | `cd ios && xcodebuild -scheme BoulderRollers build` |
| Restart backend | `ssh root@STAGING_IP "docker restart boulder-api"` |
| View backend logs | `ssh root@STAGING_IP "docker logs boulder-api --tail 50"` |

---

## Now Go Execute

1. Read this document fully
2. Find your worker runbook: `WORKER_X_*.md`
3. Execute all items in order
4. Run tests
5. Report completion status

Good luck!
