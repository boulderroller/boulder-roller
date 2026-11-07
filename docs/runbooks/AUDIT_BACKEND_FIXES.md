# Backend API Audit - Fix Instructions

## Overview
This document contains all flagged issues from the backend audit with detailed fix instructions. Backend is Python/FastAPI with Supabase.

**Base Path:** `/Users/gabetemp/curahee/BoulderRollers-v2/backend`

---

## CRITICAL PRIORITY (Security & Core)

### 1. AUTH_SIGNATURE_BYPASS Can Disable Signature Verification
**File:** `backend/app/config.py:113`
**Risk:** Production could have signature verification disabled

**Current State:**
```python
signature_bypass = _parse_bool(os.getenv("AUTH_SIGNATURE_BYPASS"))
```

**Solution:**
```python
# Only allow bypass in explicit development mode
signature_bypass = (
    _parse_bool(os.getenv("AUTH_SIGNATURE_BYPASS"))
    and os.getenv("ENVIRONMENT", "production") == "development"
)
```

Also add startup warning:
```python
# In main.py startup
if settings.signature_bypass:
    import warnings
    warnings.warn("⚠️ AUTH_SIGNATURE_BYPASS is enabled! This should NEVER be used in production.")
```

**Verify on deployed server:**
```bash
ssh root@STAGING_IP "grep AUTH_SIGNATURE_BYPASS /root/boulder-repo/backend/.env"
```

---

### 2. Effort Score is Placeholder
**File:** `backend/app/routes/proofs.py:21`
**Current State:**
```python
effort_score = float(len(payload.signature))  # MEANINGLESS
```

**Solution:**
Calculate real effort score from ride metrics:
```python
def calculate_effort_score(tss: float, duration_sec: int, elevation_m: float) -> float:
    """
    Effort score based on:
    - TSS (Training Stress Score) - weighted heavily
    - Duration - longer rides = more effort
    - Elevation - climbing is hard
    """
    tss_component = tss * 1.0  # TSS is already normalized
    duration_component = (duration_sec / 3600) * 10  # 10 points per hour
    elevation_component = (elevation_m / 100) * 5  # 5 points per 100m climbed

    return tss_component + duration_component + elevation_component
```

Update the route:
```python
@router.post("/proofs")
async def create_proof(payload: ProofPayload, ...):
    # Fetch ride data to calculate real effort
    ride = await repo.get_ride(payload.ride_id)
    effort_score = calculate_effort_score(
        tss=ride.tss,
        duration_sec=ride.duration_sec,
        elevation_m=ride.elevation_gain or 0
    )
    # ... rest of proof creation
```

---

### 3. DUNG Mint Status Always "confirmed"
**File:** `backend/app/routes/rides.py:115`
**Current State:**
```python
status="confirmed"  # Always confirmed, even if tx pending
```

**Solution:**
Track actual transaction status:
```python
# Define status enum
class MintStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    FAILED = "failed"

# In the mint flow:
initial_status = MintStatus.SUBMITTED if tx_result.get("signature") else MintStatus.FAILED

# Record with real status
await repo.record_mint_event(
    user_id=current_user.user_id,
    ride_id=ride_id,
    dung_amount=dung_to_mint,
    tx_signature=tx_result.get("signature"),
    status=initial_status
)

# Add background job to verify confirmation (optional enhancement)
```

---

### 4. No Proof Validation Before Mint
**File:** `backend/app/routes/mint.py:35`
**Current State:** Can mint for non-existent proofs

**Solution:**
```python
@router.post("/mint/issue")
async def issue_mint(request: MintRequest, ...):
    # Validate proof exists
    proof = await repo.get_proof(request.proof_id)
    if not proof:
        raise HTTPException(status_code=404, detail="Proof not found")

    # Check proof hasn't already been minted
    if proof.minted:
        raise HTTPException(status_code=400, detail="Proof already minted")

    # Check proof belongs to requesting user
    if proof.user_id != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your proof")

    # Proceed with mint...
```

---

### 5. No CAL Rollback on Failure
**File:** `backend/app/routes/rides.py:82-88`
**Current State:** If CAL deduction succeeds but ride creation fails, CAL is lost

**Solution:**
Implement compensation pattern:
```python
async def upload_ride(...):
    ride_id = None
    cal_deducted = False

    try:
        # 1. Create ride record first (can be rolled back)
        ride = await repo.create_ride(...)
        ride_id = ride.id

        # 2. Deduct CAL
        await repo.deduct_cal(current_user.user_id, cal_cost)
        cal_deducted = True

        # 3. Mint DUNG
        tx_result = await solana.mint_dung(...)

        return RideUploadResponse(...)

    except Exception as e:
        # Rollback: refund CAL if it was deducted
        if cal_deducted:
            await repo.refund_cal(current_user.user_id, cal_cost)

        # Rollback: delete ride if it was created
        if ride_id:
            await repo.delete_ride(ride_id)

        raise HTTPException(status_code=500, detail=str(e))
```

---

### 6. No Rate Limiting on Auth Endpoints
**File:** `backend/app/routes/auth.py:44-137`
**Risk:** DoS vulnerability, brute force attacks

**Solution:**
Add slowapi rate limiting:
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@router.post("/nonce")
@limiter.limit("5/minute")  # 5 nonce requests per minute per IP
async def get_nonce(request: Request, ...):
    ...

@router.post("/verify")
@limiter.limit("10/minute")  # 10 verify attempts per minute per IP
async def verify(request: Request, ...):
    ...
```

Add to `main.py`:
```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
```

**Install:** `pip install slowapi`

---

## HIGH PRIORITY

### 7. Silent Solana Stubbing
**File:** `backend/app/solana_client.py:76-82`
**Problem:** Falls back to stubs without warning

**Solution:**
Log errors and fail loudly in production:
```python
def _stub_response(self, operation: str) -> dict:
    if os.getenv("ENVIRONMENT") == "production":
        raise RuntimeError(f"Solana client attempted to stub {operation} in production!")

    logger.warning(f"⚠️ Solana {operation} returning stub response (dev mode)")
    return {"status": "stubbed", "signature": None}
```

---

### 8. Username Enumeration Vulnerability
**File:** `backend/app/routes/users.py:177`
**Problem:** Public endpoint allows checking if usernames exist

**Solution:**
Add rate limiting (same as auth):
```python
@router.post("/check-username")
@limiter.limit("10/minute")
async def check_username(request: Request, ...):
    ...
```

Or require authentication for this endpoint.

---

### 9. Missing device_id in AuthenticatedUser
**File:** `backend/app/dependencies.py:36-73`
**Problem:** Session endpoints reference `current_user.device_id` which doesn't exist

**Solution:**
Add device_id to the dataclass:
```python
@dataclass
class AuthenticatedUser:
    wallet: str
    user_id: str
    device_id: str  # Add this
```

Update `get_current_user()` to extract device_id from JWT:
```python
async def get_current_user(...) -> AuthenticatedUser:
    # ... existing token validation ...

    device_id = payload.get("device_id", "unknown")

    return AuthenticatedUser(
        wallet=wallet,
        user_id=user_id,
        device_id=device_id
    )
```

---

### 10. Verify Migrations Applied
**Files:** `backend/sql/008_cal_deduction.sql`, `009_ride_metrics.sql`, `010_user_profiles.sql`

**Action:**
```bash
# SSH to server and check
ssh root@STAGING_IP

# List applied migrations in Supabase
# Or manually verify tables exist:
psql $DATABASE_URL -c "\dt"
psql $DATABASE_URL -c "SELECT * FROM information_schema.columns WHERE table_name = 'rides';"
```

Create migration tracking if not exists:
```sql
CREATE TABLE IF NOT EXISTS _migrations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    applied_at TIMESTAMP DEFAULT NOW()
);
```

---

## MEDIUM PRIORITY

### 11. LP Token Formula Placeholder
**File:** `backend/app/routes/staking.py:44`
**Current:** `lp_tokens = request.amount  # 1:1 placeholder`

**Solution:**
Implement bonding curve or simple pool formula:
```python
async def calculate_lp_tokens(segment_id: int, dung_amount: int, repo: DatabaseRepository) -> int:
    """
    LP tokens based on share of pool.
    Formula: lp_tokens = (dung_amount / total_pool_dung) * total_lp_supply
    For new pools: 1:1 ratio as base
    """
    pool = await repo.get_segment_pool(segment_id)

    if pool.total_dung == 0:
        # First staker gets 1:1
        return dung_amount

    # Proportional share
    share = dung_amount / (pool.total_dung + dung_amount)
    new_lp = int(pool.total_lp * share / (1 - share))

    return new_lp
```

---

### 12. Mock Transaction Signatures
**File:** `backend/app/routes/staking.py:57,78`
**Current:** Returns "mock_signature" on failure

**Solution:**
Return null and proper status:
```python
return StakeResponse(
    claim_id=claim.id,
    lp_tokens=lp_amount,
    tx_signature=tx_result.get("signature"),  # Will be None if failed
    status="confirmed" if tx_result.get("signature") else "pending"
)
```

---

### 13. Session Token Hash Missing
**File:** `backend/app/routes/users.py:248-259`
**Problem:** Can't identify which session is "current"

**Solution:**
Pass token hash from request:
```python
@router.get("/me/sessions")
async def list_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user),
    authorization: str = Header(...),
    repo: DatabaseRepository = Depends(get_repository),
):
    # Extract and hash current token
    token = authorization.replace("Bearer ", "")
    current_hash = hashlib.sha256(token.encode()).hexdigest()[:16]

    sessions = await repo.list_user_sessions(current_user.user_id)

    return {
        "sessions": [
            {**s, "is_current": s["token_hash"] == current_hash}
            for s in sessions
        ]
    }
```

---

## Testing Checklist
After implementing fixes:
- [ ] AUTH_SIGNATURE_BYPASS doesn't work in production
- [ ] Effort score calculated from actual ride data
- [ ] Mint status reflects real transaction state
- [ ] Cannot mint without valid proof
- [ ] CAL refunded if ride creation fails
- [ ] Rate limiting active on auth endpoints
- [ ] All SQL migrations applied
- [ ] No mock signatures in responses
