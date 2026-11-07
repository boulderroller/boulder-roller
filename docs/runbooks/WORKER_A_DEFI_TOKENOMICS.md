# Worker A: DeFi & Tokenomics

> **Priority:** P2
> **Estimated Scope:** 7 tasks
> **Dependencies:** None (independent workstream)
> **Branch:** `feat/defi-tokenomics-v2`

---

## Overview

Fix critical DeFi/tokenomics issues that undermine economic integrity. These issues affect user trust and token value.

---

## Tasks

### DEFI-201: Remove Fake Transaction Signatures

**File:** `backend/app/services/token_mint.py:33`

**Current (DANGEROUS):**
```python
tx_hash = tx.get("signature") or f"0x{secrets.token_hex(16)}"
```

**Problem:** Generates fake tx hash if Solana call fails silently. Cannot verify mints on-chain.

**Fix:**
```python
tx_hash = tx.get("signature")
if not tx_hash:
    raise MintError("Solana transaction failed - no signature returned")
```

**Files to modify:**
- `backend/app/services/token_mint.py`
- Add `MintError` exception class

---

### DEFI-204: Vesting/Unlock Schedules

**Current:** All DUNG instantly liquid after earning

**Required:** Implement vesting for large rewards

**Database Schema:**
```sql
-- backend/sql/016_vesting.sql
CREATE TABLE vesting_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    token_type VARCHAR(10) NOT NULL,  -- 'DUNG' or 'CAL'
    total_amount NUMERIC NOT NULL,
    vested_amount NUMERIC NOT NULL DEFAULT 0,
    start_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    end_date TIMESTAMPTZ NOT NULL,
    cliff_date TIMESTAMPTZ,
    source_type VARCHAR(50),  -- 'ride', 'stake_reward', 'referral'
    source_id UUID,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_vesting_user ON vesting_schedules(user_id);
CREATE INDEX idx_vesting_end ON vesting_schedules(end_date);
```

**Backend Implementation:**
```python
# backend/app/services/vesting.py
from datetime import datetime, timedelta

class VestingService:
    DEFAULT_VESTING_DAYS = 30
    LARGE_REWARD_THRESHOLD = 500  # DUNG

    async def create_vesting_schedule(
        self, user_id: str, amount: int, source_type: str, source_id: str
    ) -> dict:
        """Create vesting schedule for rewards above threshold."""
        if amount <= self.LARGE_REWARD_THRESHOLD:
            # Small rewards are instant
            return {"vested": amount, "locked": 0}

        # Large rewards vest over 30 days
        end_date = datetime.utcnow() + timedelta(days=self.DEFAULT_VESTING_DAYS)

        schedule = await self.repo.create_vesting_schedule(
            user_id=user_id,
            token_type="DUNG",
            total_amount=amount,
            end_date=end_date,
            source_type=source_type,
            source_id=source_id
        )

        return {"vested": 0, "locked": amount, "schedule_id": schedule["id"]}

    async def get_vested_balance(self, user_id: str) -> dict:
        """Calculate currently vested vs locked amounts."""
        schedules = await self.repo.get_user_vesting_schedules(user_id)

        now = datetime.utcnow()
        total_vested = 0
        total_locked = 0

        for schedule in schedules:
            if now >= schedule["end_date"]:
                # Fully vested
                total_vested += schedule["total_amount"]
            elif schedule["cliff_date"] and now < schedule["cliff_date"]:
                # Still in cliff period
                total_locked += schedule["total_amount"]
            else:
                # Linear vesting
                elapsed = (now - schedule["start_date"]).total_seconds()
                total_duration = (schedule["end_date"] - schedule["start_date"]).total_seconds()
                vested_ratio = min(elapsed / total_duration, 1.0)
                vested = int(schedule["total_amount"] * vested_ratio)
                total_vested += vested
                total_locked += schedule["total_amount"] - vested

        return {"vested": total_vested, "locked": total_locked}
```

**API Endpoints:**
```python
# backend/app/routes/vesting.py
@router.get("/vesting/balance")
async def get_vesting_balance(current_user: AuthenticatedUser = Depends(get_current_user)):
    """Get user's vested vs locked token balance."""
    balance = await vesting_service.get_vested_balance(current_user.user_id)
    return balance

@router.get("/vesting/schedules")
async def get_vesting_schedules(current_user: AuthenticatedUser = Depends(get_current_user)):
    """List all vesting schedules for user."""
    schedules = await repo.get_user_vesting_schedules(current_user.user_id)
    return {"schedules": schedules}
```

---

### DEFI-205: Reward Distribution/Harvesting

**Current:** `last_harvest` column exists but never used. No yield distribution.

**Required:** Implement epoch-based staking rewards

**Database Updates:**
```sql
-- Update epochs table usage
ALTER TABLE epochs ADD COLUMN IF NOT EXISTS rewards_per_lp NUMERIC;

-- Track harvest history
CREATE TABLE harvest_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    segment_id UUID NOT NULL REFERENCES segments(id),
    epoch_number BIGINT NOT NULL,
    lp_tokens_held NUMERIC NOT NULL,
    dung_harvested NUMERIC NOT NULL,
    tx_signature VARCHAR(128),
    harvested_at TIMESTAMPTZ DEFAULT now()
);
```

**Backend Implementation:**
```python
# backend/app/services/rewards.py
class RewardService:
    EPOCH_DURATION_DAYS = 7
    REWARD_POOL_PERCENTAGE = 0.10  # 10% of segment fees go to stakers

    async def calculate_epoch_rewards(self, segment_id: str, epoch_number: int) -> dict:
        """Calculate rewards for an epoch based on segment activity."""
        # Get segment activity for the epoch
        activity = await self.repo.get_segment_epoch_activity(segment_id, epoch_number)

        # Total fees collected during epoch
        total_fees = activity.get("total_fees", 0)
        reward_pool = int(total_fees * self.REWARD_POOL_PERCENTAGE)

        # Get total LP tokens staked
        pool = await self.repo.get_segment_pool(segment_id)
        total_lp = pool.get("total_lp", 0)

        if total_lp <= 0:
            return {"rewards_per_lp": 0, "total_pool": reward_pool}

        rewards_per_lp = reward_pool / total_lp
        return {"rewards_per_lp": rewards_per_lp, "total_pool": reward_pool}

    async def harvest_rewards(self, user_id: str, segment_id: str) -> dict:
        """Harvest accumulated rewards for user's stake in segment."""
        # Get user's claim
        claim = await self.repo.get_user_claim(user_id, segment_id)
        if not claim:
            raise HTTPException(404, "No stake found for this segment")

        lp_tokens = claim.get("lp_tokens", 0)
        last_harvest_epoch = claim.get("last_harvest_epoch", 0)

        # Get current epoch
        current_epoch = await self.repo.get_current_epoch(segment_id)

        # Calculate rewards for unharvested epochs
        total_rewards = 0
        for epoch in range(last_harvest_epoch + 1, current_epoch):
            epoch_data = await self.repo.get_epoch(segment_id, epoch)
            if epoch_data and epoch_data.get("distributed"):
                rewards_per_lp = epoch_data.get("rewards_per_lp", 0)
                total_rewards += int(lp_tokens * rewards_per_lp)

        if total_rewards <= 0:
            return {"harvested": 0, "message": "No rewards to harvest"}

        # Update last harvest epoch
        await self.repo.update_claim_harvest(user_id, segment_id, current_epoch - 1)

        # Record harvest event
        await self.repo.create_harvest_event(
            user_id=user_id,
            segment_id=segment_id,
            epoch_number=current_epoch - 1,
            lp_tokens_held=lp_tokens,
            dung_harvested=total_rewards
        )

        return {"harvested": total_rewards, "epochs_processed": current_epoch - last_harvest_epoch - 1}
```

**API Endpoint:**
```python
@router.post("/staking/harvest")
async def harvest_staking_rewards(
    segment_id: UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Harvest accumulated staking rewards for a segment."""
    result = await reward_service.harvest_rewards(current_user.user_id, str(segment_id))
    return result

@router.get("/staking/pending-rewards")
async def get_pending_rewards(
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Get pending rewards across all staked segments."""
    claims = await repo.get_user_claims(current_user.user_id)
    pending = []
    for claim in claims:
        rewards = await reward_service.calculate_pending(
            current_user.user_id,
            claim["segment_id"]
        )
        if rewards > 0:
            pending.append({
                "segment_id": claim["segment_id"],
                "pending_dung": rewards
            })
    return {"pending_rewards": pending}
```

---

### DEFI-206: DUNG Earning Cap Improvements

**Current:** `DUNG = min(TSS, 500)` - hard cap

**Required:** Tiered earning with streak bonuses

**File:** `backend/app/services/proof_builder.py`

```python
async def calculate_dung_reward(
    tss: float,
    user_id: str,
    repo: DatabaseRepository
) -> int:
    """
    Calculate DUNG reward with tiered earning and streak bonus.

    Tiers:
    - 0-500 TSS: 1:1 (100%)
    - 500-1000 TSS: 0.5:1 (50% of excess)
    - 1000+ TSS: 0.2:1 (20% of excess)

    Streak Bonus:
    - 3 days: 1.1x
    - 7 days: 1.25x
    - 14 days: 1.4x
    - 30 days: 1.5x (max)
    """
    # Base calculation with tiers
    if tss <= 500:
        base = int(tss)
    elif tss <= 1000:
        base = 500 + int((tss - 500) * 0.5)
    else:
        base = 500 + 250 + int((tss - 1000) * 0.2)

    # Get user streak
    streak = await repo.get_user_ride_streak(user_id)

    # Calculate streak multiplier
    if streak >= 30:
        multiplier = 1.5
    elif streak >= 14:
        multiplier = 1.4
    elif streak >= 7:
        multiplier = 1.25
    elif streak >= 3:
        multiplier = 1.1
    else:
        multiplier = 1.0

    final = int(base * multiplier)

    # Absolute cap to prevent abuse
    return min(final, 1500)
```

---

### DEFI-207: Transaction History

**Required:** Complete audit trail for all token operations

**Database Schema:**
```sql
CREATE TABLE token_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    tx_type VARCHAR(50) NOT NULL,  -- 'earn', 'stake', 'unstake', 'harvest', 'transfer', 'burn'
    token_type VARCHAR(10) NOT NULL,  -- 'DUNG', 'CAL', 'LP'
    amount NUMERIC NOT NULL,
    balance_after NUMERIC,
    reference_type VARCHAR(50),  -- 'ride', 'segment', 'epoch'
    reference_id UUID,
    tx_signature VARCHAR(128),
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_tx_user ON token_transactions(user_id);
CREATE INDEX idx_tx_created ON token_transactions(created_at DESC);
CREATE INDEX idx_tx_type ON token_transactions(tx_type);
```

**API Endpoint:**
```python
@router.get("/transactions")
async def get_transaction_history(
    limit: int = 50,
    offset: int = 0,
    tx_type: Optional[str] = None,
    token_type: Optional[str] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Get user's token transaction history with filters."""
    transactions = await repo.get_user_transactions(
        user_id=current_user.user_id,
        limit=limit,
        offset=offset,
        tx_type=tx_type,
        token_type=token_type
    )
    return {"transactions": transactions, "limit": limit, "offset": offset}

@router.get("/transactions/export")
async def export_transactions(
    format: str = "csv",  # csv or json
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Export full transaction history for user."""
    transactions = await repo.get_all_user_transactions(current_user.user_id)

    if format == "csv":
        # Return CSV file
        csv_content = generate_csv(transactions)
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=transactions.csv"}
        )

    return {"transactions": transactions}
```

---

## Testing Instructions

### Unit Tests

Create `backend/tests/test_defi.py`:

```python
import pytest
from decimal import Decimal
from datetime import datetime, timedelta

from app.services.vesting import VestingService
from app.services.rewards import RewardService


class TestVesting:
    @pytest.fixture
    def vesting_service(self, mock_repo):
        return VestingService(repo=mock_repo)

    async def test_small_reward_no_vesting(self, vesting_service):
        """Rewards <= 500 DUNG should be instant (no vesting)."""
        result = await vesting_service.create_vesting_schedule(
            user_id="user-123",
            amount=400,
            source_type="ride",
            source_id="ride-456"
        )
        assert result["vested"] == 400
        assert result["locked"] == 0

    async def test_large_reward_creates_vesting(self, vesting_service):
        """Rewards > 500 DUNG should create vesting schedule."""
        result = await vesting_service.create_vesting_schedule(
            user_id="user-123",
            amount=1000,
            source_type="ride",
            source_id="ride-456"
        )
        assert result["vested"] == 0
        assert result["locked"] == 1000
        assert "schedule_id" in result

    async def test_linear_vesting_calculation(self, vesting_service, mock_repo):
        """Test linear vesting over time."""
        # Create schedule that's 50% complete
        mock_repo.get_user_vesting_schedules.return_value = [{
            "id": "sched-1",
            "total_amount": 1000,
            "start_date": datetime.utcnow() - timedelta(days=15),
            "end_date": datetime.utcnow() + timedelta(days=15),
            "cliff_date": None
        }]

        balance = await vesting_service.get_vested_balance("user-123")
        assert balance["vested"] == 500  # 50% vested
        assert balance["locked"] == 500  # 50% locked


class TestRewards:
    @pytest.fixture
    def reward_service(self, mock_repo):
        return RewardService(repo=mock_repo)

    async def test_harvest_with_no_stake(self, reward_service, mock_repo):
        """Harvesting without stake should raise 404."""
        mock_repo.get_user_claim.return_value = None

        with pytest.raises(HTTPException) as exc:
            await reward_service.harvest_rewards("user-123", "segment-456")
        assert exc.value.status_code == 404

    async def test_harvest_calculates_correct_rewards(self, reward_service, mock_repo):
        """Test reward calculation across multiple epochs."""
        mock_repo.get_user_claim.return_value = {
            "lp_tokens": 100,
            "last_harvest_epoch": 5
        }
        mock_repo.get_current_epoch.return_value = 8
        mock_repo.get_epoch.side_effect = [
            {"distributed": True, "rewards_per_lp": 0.5},  # epoch 6
            {"distributed": True, "rewards_per_lp": 0.75}, # epoch 7
            None  # epoch 8 not complete
        ]

        result = await reward_service.harvest_rewards("user-123", "segment-456")
        # 100 LP * (0.5 + 0.75) = 125 DUNG
        assert result["harvested"] == 125
        assert result["epochs_processed"] == 2


class TestDungCalculation:
    async def test_tiered_earning(self, mock_repo):
        """Test DUNG earning tiers."""
        mock_repo.get_user_ride_streak.return_value = 0

        # Tier 1: 0-500 TSS = 100%
        assert await calculate_dung_reward(300, "user-1", mock_repo) == 300
        assert await calculate_dung_reward(500, "user-1", mock_repo) == 500

        # Tier 2: 500-1000 TSS = 50% of excess
        # 750 TSS = 500 + (250 * 0.5) = 625
        assert await calculate_dung_reward(750, "user-1", mock_repo) == 625

        # Tier 3: 1000+ TSS = 20% of excess
        # 1200 TSS = 500 + 250 + (200 * 0.2) = 790
        assert await calculate_dung_reward(1200, "user-1", mock_repo) == 790

    async def test_streak_bonus(self, mock_repo):
        """Test streak multipliers."""
        base_tss = 400  # Simple tier 1 amount

        mock_repo.get_user_ride_streak.return_value = 0
        assert await calculate_dung_reward(base_tss, "user-1", mock_repo) == 400

        mock_repo.get_user_ride_streak.return_value = 7
        assert await calculate_dung_reward(base_tss, "user-1", mock_repo) == 500  # 1.25x

        mock_repo.get_user_ride_streak.return_value = 30
        assert await calculate_dung_reward(base_tss, "user-1", mock_repo) == 600  # 1.5x


class TestTransactionHistory:
    async def test_record_transaction(self, mock_repo):
        """Verify transactions are recorded correctly."""
        await record_token_transaction(
            repo=mock_repo,
            user_id="user-123",
            tx_type="earn",
            token_type="DUNG",
            amount=500,
            reference_type="ride",
            reference_id="ride-456"
        )

        mock_repo.create_token_transaction.assert_called_once()
        call_args = mock_repo.create_token_transaction.call_args
        assert call_args.kwargs["amount"] == 500
        assert call_args.kwargs["tx_type"] == "earn"
```

### Integration Tests

```python
# backend/tests/integration/test_defi_flow.py

class TestStakingFlow:
    """End-to-end staking flow tests."""

    async def test_full_staking_cycle(self, test_client, auth_headers, test_segment):
        """Test stake -> earn rewards -> harvest -> unstake flow."""

        # 1. Stake DUNG
        stake_response = await test_client.post(
            "/staking/stake",
            json={"segment_id": str(test_segment.id), "amount": 100_000_000_000},
            headers=auth_headers
        )
        assert stake_response.status_code == 200
        stake_data = stake_response.json()
        assert stake_data["lp_tokens_received"] > 0

        # 2. Simulate epoch completion (admin/cron would do this)
        await complete_epoch(test_segment.id, rewards_per_lp=0.1)

        # 3. Check pending rewards
        pending_response = await test_client.get(
            "/staking/pending-rewards",
            headers=auth_headers
        )
        assert pending_response.status_code == 200
        pending = pending_response.json()
        assert len(pending["pending_rewards"]) > 0

        # 4. Harvest rewards
        harvest_response = await test_client.post(
            "/staking/harvest",
            json={"segment_id": str(test_segment.id)},
            headers=auth_headers
        )
        assert harvest_response.status_code == 200
        harvest_data = harvest_response.json()
        assert harvest_data["harvested"] > 0

        # 5. Verify transaction recorded
        tx_response = await test_client.get(
            "/transactions?tx_type=harvest",
            headers=auth_headers
        )
        assert tx_response.status_code == 200
        transactions = tx_response.json()["transactions"]
        assert any(tx["tx_type"] == "harvest" for tx in transactions)

        # 6. Unstake
        unstake_response = await test_client.post(
            "/staking/unstake",
            json={
                "segment_id": str(test_segment.id),
                "lp_amount": stake_data["lp_tokens_received"]
            },
            headers=auth_headers
        )
        assert unstake_response.status_code == 200
        assert unstake_response.json()["dung_returned"] > 0
```

### Manual Testing Checklist

```markdown
## DeFi Manual Testing Checklist

### Vesting
- [ ] Upload a ride earning < 500 DUNG → Verify instant availability
- [ ] Upload a ride earning > 500 DUNG → Verify vesting schedule created
- [ ] Wait for partial vest period → Verify correct vested amount
- [ ] Check /vesting/balance endpoint returns correct split
- [ ] Check /vesting/schedules shows all active schedules

### Staking & Rewards
- [ ] Stake DUNG on a segment → Verify LP tokens received
- [ ] Wait for epoch to complete → Verify pending rewards show
- [ ] Harvest rewards → Verify DUNG credited
- [ ] Partial unstake → Verify proportional DUNG returned
- [ ] Full unstake → Verify all DUNG returned
- [ ] Slippage protection: stake with low min_lp_out → Verify rejection

### Transaction History
- [ ] Complete various actions (stake, unstake, harvest, earn)
- [ ] GET /transactions → Verify all actions recorded
- [ ] Filter by tx_type → Verify correct filtering
- [ ] Filter by token_type → Verify correct filtering
- [ ] Export as CSV → Verify file downloads correctly
- [ ] Verify all transactions have correct amounts and timestamps

### Edge Cases
- [ ] Stake in empty pool → Verify 1:1 LP ratio
- [ ] Unstake entire pool → Verify no division errors
- [ ] Harvest with no pending rewards → Verify graceful message
- [ ] Very large stake amount → Verify no overflow
- [ ] Very small stake amount → Verify minimum enforced
```

---

## Success Criteria

- [ ] No fake transaction signatures generated
- [ ] Vesting schedules created for large rewards
- [ ] Rewards can be harvested after epoch completion
- [ ] All token operations recorded in transaction history
- [ ] Streak bonuses apply correctly to DUNG earnings
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Manual testing checklist complete

---

## Files Modified

| File | Change |
|------|--------|
| `backend/app/services/token_mint.py` | Remove fake tx signature |
| `backend/app/services/vesting.py` | NEW - Vesting service |
| `backend/app/services/rewards.py` | NEW - Reward distribution |
| `backend/app/services/proof_builder.py` | Update DUNG calculation |
| `backend/app/routes/vesting.py` | NEW - Vesting endpoints |
| `backend/app/routes/staking.py` | Add harvest endpoint |
| `backend/app/routes/transactions.py` | NEW - Transaction history |
| `backend/sql/016_vesting.sql` | NEW - Vesting schema |
| `backend/sql/017_transactions.sql` | NEW - Transaction schema |
| `backend/app/main.py` | Register new routers |
