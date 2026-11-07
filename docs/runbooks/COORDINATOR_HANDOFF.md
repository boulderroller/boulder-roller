# Coordinator Handoff: Parallel Worker Supervision

> **You are the coordinator.** 5 parallel workers are executing runbooks. Your job is to check on them, resolve conflicts, and integrate their work.

---

## Current State

**Started:** December 5, 2024
**Workers Spawned:** 5 (A, B, C, D, E) - running in parallel CLI windows

### Worker Status Tracker

| Worker | Domain | Status | Last Check |
|--------|--------|--------|------------|
| A | DeFi/Tokenomics | 🟡 In Progress | - |
| B | Social/Backend | 🟡 In Progress | - |
| C | iOS Features | 🟡 In Progress | - |
| D | Training Analytics | 🟡 In Progress | - |
| E | Security/Compliance | 🟡 In Progress | - |

Update this table as you check in.

---

## Your Responsibilities

### 1. Periodic Check-Ins

Ask the user for status updates on each worker. Look for:
- Completion percentage
- Any errors or blockers
- Files they've created/modified

### 2. Conflict Resolution

Workers have reserved SQL migration ranges, but conflicts may occur in:
- `backend/app/main.py` - Multiple routers being added
- `backend/app/schemas.py` - Multiple Pydantic models
- `ios/BoulderRollers/Services/APIClient.swift` - Multiple new endpoints

**Resolution pattern:**
```python
# If multiple workers edited main.py, merge their router imports:
from backend.app.routes import feed, compliance, analytics  # Merge all
app.include_router(feed.router, prefix="/api/v1")
app.include_router(compliance.router, prefix="/api/v1")
app.include_router(analytics.router, prefix="/api/v1")
```

### 3. Integration Testing

Once workers complete, run:

```bash
# Backend tests
cd /Users/gabetemp/curahee/BoulderRollers-v2/backend
python -m pytest -v

# Check all imports work
python -c "from backend.app.main import app; print('OK')"

# iOS build
cd /Users/gabetemp/curahee/BoulderRollers-v2/ios
xcodebuild -scheme BoulderRollers build

# Run SQL migrations on server
ssh root@STAGING_IP "cd /root/boulder-repo && ls backend/sql/*.sql | sort | tail -10"
```

### 4. Final Assembly

When all workers complete:

1. **Merge any conflicts** in shared files
2. **Run full test suite**
3. **Deploy to server:**
   ```bash
   ssh root@STAGING_IP "cd /root/boulder-repo && git pull && docker restart boulder-api"
   ```
4. **Run migrations:**
   ```bash
   ssh root@STAGING_IP "docker exec boulder-api python -c 'from backend.app.main import app'"
   ```

---

## Runbook Locations

All in `/Users/gabetemp/curahee/BoulderRollers-v2/docs/runbooks/`:

| File | Purpose |
|------|---------|
| `MASTER_CONTEXT.md` | Shared context all workers read |
| `WORKER_A_DEFI_TOKENOMICS.md` | Vesting, harvesting, tx history |
| `WORKER_B_SOCIAL_BACKEND.md` | Follows, feed, notifications |
| `WORKER_C_IOS_FEATURES.md` | Achievements, celebration, history |
| `WORKER_D_TRAINING_ANALYTICS.md` | CTL/ATL/TSB, zones, trends |
| `WORKER_E_SECURITY_COMPLIANCE.md` | GDPR, rate limits, kill switch |

---

## SQL Migration Final Order

After all workers complete, migrations should run in this order:

```
011_vesting.sql          (Worker A)
012_transaction_history.sql (Worker A)
013_epochs.sql           (Worker A)
014_social.sql           (Worker B)
015_notifications.sql    (Worker B)
016_comments.sql         (Worker B)
017_fitness_metrics.sql  (Worker D)
018_power_zones.sql      (Worker D)
019_training_trends.sql  (Worker D)
020_compliance.sql       (Worker E)
021_rate_limits.sql      (Worker E)
022_emergency.sql        (Worker E)
```

Worker C (iOS) has no SQL migrations.

---

## Known Dependencies

Some features depend on others:

```
Worker B (notifications) → Worker A (harvest events trigger notifications)
Worker C (achievements UI) → Backend achievements table (already exists)
Worker D (analytics) → rides table (already exists)
Worker E (audit log) → All other workers (logs their actions)
```

If a worker is blocked on another, they should stub the dependency and move on.

---

## Expected Deliverables Per Worker

### Worker A - DeFi/Tokenomics
- [ ] `backend/app/routes/vesting.py`
- [ ] `backend/app/routes/harvest.py`
- [ ] `backend/app/routes/transactions.py`
- [ ] `backend/sql/011_vesting.sql`
- [ ] `backend/sql/012_transaction_history.sql`
- [ ] Tests passing

### Worker B - Social/Backend
- [ ] `backend/app/routes/feed.py`
- [ ] `backend/app/routes/follows.py`
- [ ] `backend/app/routes/notifications.py`
- [ ] `backend/sql/014_social.sql`
- [ ] `backend/sql/015_notifications.sql`
- [ ] Tests passing

### Worker C - iOS Features
- [ ] `ios/.../Views/Profile/AchievementsView.swift`
- [ ] `ios/.../Views/Rides/DungCelebrationView.swift`
- [ ] `ios/.../Views/Rides/RidesHistoryView.swift`
- [ ] Updated `APIClient.swift`
- [ ] iOS builds successfully

### Worker D - Training Analytics
- [ ] `backend/app/services/fitness_metrics.py`
- [ ] `backend/app/routes/analytics.py`
- [ ] `backend/sql/017_fitness_metrics.sql`
- [ ] Tests passing

### Worker E - Security/Compliance
- [ ] `backend/app/routes/compliance.py`
- [ ] `backend/app/routes/admin.py`
- [ ] `backend/app/middleware/rate_limiter.py`
- [ ] `backend/sql/020_compliance.sql`
- [ ] Tests passing

---

## Completion Criteria

All workers done when:

1. ✅ All expected files created
2. ✅ `python -m pytest` passes
3. ✅ `xcodebuild` succeeds
4. ✅ No merge conflicts in shared files
5. ✅ All SQL migrations run without error

---

## Escalation

If workers are stuck or conflicting badly:
- Review the specific runbook they're working from
- Check `MASTER_CONTEXT.md` for coordination rules
- The comprehensive plan is at: `/Users/gabetemp/.claude/plans/velvety-leaping-cupcake.md`

---

## Quick Commands

```bash
# Check git status for all changes
cd /Users/gabetemp/curahee/BoulderRollers-v2 && git status

# See what files were created
git status --porcelain | grep "^??"

# See what files were modified
git status --porcelain | grep "^ M"

# Backend health check
curl -s http://STAGING_IP:8000/health | jq

# View recent backend logs
ssh root@STAGING_IP "docker logs boulder-api --tail 20"
```

---

Good luck, coordinator. You've got this. 🫡
