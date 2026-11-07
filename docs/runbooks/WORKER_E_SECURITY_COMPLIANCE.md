# Worker E: Security & Compliance

> **Priority:** P5
> **Scope:** GDPR compliance, rate limiting, emergency pause, audit logging
> **Dependencies:** None (can run in parallel)

---

## Overview

This runbook covers all security and compliance features required for production launch:

| Item | Description | Effort |
|------|-------------|--------|
| SECURITY-501 | GDPR data export & deletion | Medium |
| SECURITY-502 | Per-user rate limiting | Medium |
| SECURITY-503 | Emergency pause (kill switch) | Medium |
| SECURITY-504 | Audit logging | Medium |

---

## SECURITY-501: GDPR Compliance

### Requirements (GDPR Articles 15, 17, 20)

1. **Right of Access (Art. 15):** User can request all their data
2. **Right to Erasure (Art. 17):** User can delete their account
3. **Right to Portability (Art. 20):** Data in machine-readable format

### Database Schema

```sql
-- File: backend/sql/016_compliance.sql

-- Audit log for all significant operations
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    target_type VARCHAR(50),  -- 'user', 'ride', 'stake', 'token'
    target_id UUID,
    metadata JSONB DEFAULT '{}',
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_action ON audit_log(action);
CREATE INDEX idx_audit_log_created ON audit_log(created_at);

-- Data deletion requests (for compliance tracking)
CREATE TABLE deletion_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    wallet_address VARCHAR(44) NOT NULL,
    requested_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'processing', 'completed', 'failed'
    error_message TEXT
);

CREATE INDEX idx_deletion_requests_status ON deletion_requests(status);

-- Data export requests
CREATE TABLE export_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    requested_at TIMESTAMPTZ DEFAULT now(),
    completed_at TIMESTAMPTZ,
    download_url TEXT,
    expires_at TIMESTAMPTZ,
    status VARCHAR(20) DEFAULT 'pending'
);
```

### Repository Implementation

```python
# File: backend/app/repositories/compliance.py

from typing import Optional, Dict, Any, List
from uuid import UUID
from datetime import datetime, timedelta
import json

class ComplianceRepository:
    def __init__(self, db):
        self.db = db

    async def log_audit_event(
        self,
        action: str,
        user_id: Optional[UUID] = None,
        target_type: Optional[str] = None,
        target_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> UUID:
        """Log an audit event."""
        result = await self.db.fetchrow("""
            INSERT INTO audit_log (user_id, action, target_type, target_id, metadata, ip_address, user_agent)
            VALUES ($1, $2, $3, $4, $5, $6::inet, $7)
            RETURNING id
        """, user_id, action, target_type, target_id,
            json.dumps(metadata or {}), ip_address, user_agent)
        return result["id"]

    async def get_user_audit_log(self, user_id: UUID, limit: int = 100) -> List[Dict]:
        """Get audit log for a specific user."""
        rows = await self.db.fetch("""
            SELECT id, action, target_type, target_id, metadata, ip_address, created_at
            FROM audit_log
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
        """, user_id, limit)
        return [dict(r) for r in rows]

    async def export_user_data(self, user_id: UUID) -> Dict[str, Any]:
        """Export all user data for GDPR compliance."""
        data = {}

        # User profile
        user = await self.db.fetchrow("""
            SELECT id, wallet_address, display_name, avatar_url, bio,
                   ftp_watts, weight_kg, created_at, updated_at
            FROM users WHERE id = $1
        """, user_id)
        data["profile"] = dict(user) if user else None

        # Rides
        rides = await self.db.fetch("""
            SELECT id, file_hash, file_type, status, started_at,
                   distance_m, elevation_gain_m, duration_sec,
                   avg_power_w, max_power_w, avg_hr_bpm, max_hr_bpm,
                   tss, normalized_power_w, intensity_factor,
                   dung_minted, created_at
            FROM rides WHERE user_id = $1
            ORDER BY created_at DESC
        """, user_id)
        data["rides"] = [dict(r) for r in rides]

        # Token balances
        balances = await self.db.fetchrow("""
            SELECT dung_balance, cal_balance, lp_balance, last_cal_mint
            FROM token_balances WHERE user_id = $1
        """, user_id)
        data["token_balances"] = dict(balances) if balances else None

        # Staking history
        stakes = await self.db.fetch("""
            SELECT pool_id, amount, lp_received, staked_at
            FROM user_stakes WHERE user_id = $1
            ORDER BY staked_at DESC
        """, user_id)
        data["staking_history"] = [dict(s) for s in stakes]

        # Achievements
        achievements = await self.db.fetch("""
            SELECT type, name, description, earned_at, ride_id, metadata
            FROM achievements WHERE user_id = $1
            ORDER BY earned_at DESC
        """, user_id)
        data["achievements"] = [dict(a) for a in achievements]

        # Sessions
        sessions = await self.db.fetch("""
            SELECT id, device_info, ip_address, created_at, last_active_at, is_current
            FROM user_sessions WHERE user_id = $1
            ORDER BY created_at DESC
        """, user_id)
        data["sessions"] = [dict(s) for s in sessions]

        # Audit log
        audit = await self.get_user_audit_log(user_id, limit=1000)
        data["audit_log"] = audit

        return data

    async def delete_user_data(self, user_id: UUID) -> Dict[str, int]:
        """
        Delete all user data for GDPR compliance.
        Returns count of deleted records per table.
        """
        counts = {}

        # Delete in order to respect foreign keys
        tables_to_clear = [
            ("user_sessions", "user_id"),
            ("achievements", "user_id"),
            ("user_stakes", "user_id"),
            ("rides", "user_id"),
            ("token_balances", "user_id"),
            ("follows", "follower_id"),
            ("follows", "following_id"),
            ("activities", "user_id"),
            ("notifications", "user_id"),
            ("comments", "user_id"),
            ("kudos", "user_id"),
        ]

        for table, column in tables_to_clear:
            try:
                result = await self.db.execute(f"""
                    DELETE FROM {table} WHERE {column} = $1
                """, user_id)
                # Parse "DELETE X" result
                count = int(result.split()[-1]) if result else 0
                counts[table] = counts.get(table, 0) + count
            except Exception:
                # Table might not exist yet
                pass

        # Anonymize audit log (keep for compliance, but remove PII)
        await self.db.execute("""
            UPDATE audit_log
            SET user_id = NULL, ip_address = NULL, user_agent = NULL
            WHERE user_id = $1
        """, user_id)

        # Finally delete the user
        result = await self.db.execute("""
            DELETE FROM users WHERE id = $1
        """, user_id)
        counts["users"] = 1 if "DELETE 1" in result else 0

        return counts

    async def create_deletion_request(self, user_id: UUID, wallet_address: str) -> UUID:
        """Create a deletion request record."""
        result = await self.db.fetchrow("""
            INSERT INTO deletion_requests (user_id, wallet_address)
            VALUES ($1, $2)
            RETURNING id
        """, user_id, wallet_address)
        return result["id"]

    async def complete_deletion_request(
        self,
        request_id: UUID,
        success: bool,
        error: Optional[str] = None
    ):
        """Mark a deletion request as completed."""
        await self.db.execute("""
            UPDATE deletion_requests
            SET completed_at = now(),
                status = $2,
                error_message = $3
            WHERE id = $1
        """, request_id, "completed" if success else "failed", error)
```

### API Endpoints

```python
# File: backend/app/routes/compliance.py

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from typing import Optional
import json
from datetime import datetime, timedelta

router = APIRouter(prefix="/compliance", tags=["compliance"])

class ExportResponse(BaseModel):
    status: str
    message: str
    download_url: Optional[str] = None

class DeletionResponse(BaseModel):
    status: str
    message: str
    request_id: str

@router.get("/export", response_model=ExportResponse)
async def export_user_data(
    request: Request,
    user_id: str = Depends(get_current_user_id),
    db = Depends(get_db)
):
    """
    Export all user data (GDPR Art. 15 & 20).
    Returns JSON with all user data.
    """
    from uuid import UUID

    repo = ComplianceRepository(db)

    # Log the export request
    await repo.log_audit_event(
        action="data_export_requested",
        user_id=UUID(user_id),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    # Export data
    data = await repo.export_user_data(UUID(user_id))

    # Convert dates to ISO format for JSON serialization
    def serialize(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        return obj

    # In production, you'd upload to S3 and return a signed URL
    # For now, return data directly
    return ExportResponse(
        status="completed",
        message="Data export completed. Download will begin shortly.",
        download_url=f"data:application/json;base64,{json.dumps(data, default=serialize)}"
    )

@router.delete("/account", response_model=DeletionResponse)
async def delete_account(
    request: Request,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    db = Depends(get_db)
):
    """
    Delete user account and all associated data (GDPR Art. 17).
    This action is IRREVERSIBLE.
    """
    from uuid import UUID

    repo = ComplianceRepository(db)
    uid = UUID(user_id)

    # Get user info for deletion record
    user = await db.fetchrow("SELECT wallet_address FROM users WHERE id = $1", uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Create deletion request record
    request_id = await repo.create_deletion_request(uid, user["wallet_address"])

    # Log the deletion request
    await repo.log_audit_event(
        action="account_deletion_requested",
        user_id=uid,
        target_type="user",
        target_id=uid,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )

    # Perform deletion in background
    async def perform_deletion():
        try:
            counts = await repo.delete_user_data(uid)
            await repo.complete_deletion_request(request_id, success=True)
            print(f"Account deletion completed: {counts}")
        except Exception as e:
            await repo.complete_deletion_request(request_id, success=False, error=str(e))
            print(f"Account deletion failed: {e}")

    background_tasks.add_task(perform_deletion)

    return DeletionResponse(
        status="processing",
        message="Account deletion initiated. All data will be removed within 24 hours.",
        request_id=str(request_id)
    )

@router.get("/deletion-status/{request_id}")
async def get_deletion_status(
    request_id: str,
    db = Depends(get_db)
):
    """Check status of a deletion request."""
    from uuid import UUID

    row = await db.fetchrow("""
        SELECT status, requested_at, completed_at, error_message
        FROM deletion_requests
        WHERE id = $1
    """, UUID(request_id))

    if not row:
        raise HTTPException(status_code=404, detail="Deletion request not found")

    return {
        "status": row["status"],
        "requested_at": row["requested_at"].isoformat(),
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        "error": row["error_message"]
    }
```

---

## SECURITY-502: Per-User Rate Limiting

### Configuration

```python
# File: backend/app/config/rate_limits.py

from dataclasses import dataclass
from typing import Dict

@dataclass
class RateLimitConfig:
    """Rate limit configuration per endpoint category."""
    requests_per_minute: int
    requests_per_hour: int
    burst_limit: int  # Max requests in 1 second

# Default limits by endpoint category
RATE_LIMITS: Dict[str, RateLimitConfig] = {
    # Auth endpoints (prevent brute force)
    "auth": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=60,
        burst_limit=3
    ),

    # Token operations (prevent spam)
    "token_mint": RateLimitConfig(
        requests_per_minute=5,
        requests_per_hour=30,
        burst_limit=2
    ),

    # Staking operations (prevent manipulation)
    "staking": RateLimitConfig(
        requests_per_minute=10,
        requests_per_hour=100,
        burst_limit=3
    ),

    # Ride uploads (prevent abuse)
    "ride_upload": RateLimitConfig(
        requests_per_minute=5,
        requests_per_hour=50,
        burst_limit=2
    ),

    # General API (normal usage)
    "general": RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        burst_limit=10
    ),

    # Social actions (prevent spam)
    "social": RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=500,
        burst_limit=5
    ),
}
```

### Redis-Based Rate Limiter

```python
# File: backend/app/middleware/rate_limiter.py

import time
from typing import Optional, Tuple
from fastapi import Request, HTTPException
from functools import wraps
import redis.asyncio as redis
import os

# Redis connection
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

class RateLimiter:
    def __init__(self):
        self.redis: Optional[redis.Redis] = None

    async def connect(self):
        if not self.redis:
            self.redis = await redis.from_url(REDIS_URL)

    async def check_rate_limit(
        self,
        key: str,
        limit: int,
        window_seconds: int
    ) -> Tuple[bool, int, int]:
        """
        Check if request is within rate limit.
        Returns: (allowed, remaining, reset_time)
        """
        await self.connect()

        now = int(time.time())
        window_start = now - window_seconds

        pipe = self.redis.pipeline()

        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)

        # Add current request
        pipe.zadd(key, {str(now): now})

        # Count requests in window
        pipe.zcard(key)

        # Set expiry
        pipe.expire(key, window_seconds)

        results = await pipe.execute()
        request_count = results[2]

        allowed = request_count <= limit
        remaining = max(0, limit - request_count)
        reset_time = now + window_seconds

        return allowed, remaining, reset_time

    async def check_burst(self, key: str, burst_limit: int) -> bool:
        """Check burst limit (requests per second)."""
        await self.connect()

        burst_key = f"{key}:burst"
        count = await self.redis.incr(burst_key)

        if count == 1:
            await self.redis.expire(burst_key, 1)

        return count <= burst_limit

rate_limiter = RateLimiter()

def rate_limit(category: str = "general"):
    """Decorator for rate-limited endpoints."""
    from backend.app.config.rate_limits import RATE_LIMITS

    config = RATE_LIMITS.get(category, RATE_LIMITS["general"])

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = kwargs.get("request")
            if not request:
                for arg in args:
                    if isinstance(arg, Request):
                        request = arg
                        break

            if not request:
                return await func(*args, **kwargs)

            # Get user ID or IP for rate limiting
            user_id = getattr(request.state, "user_id", None)
            client_ip = request.client.host if request.client else "unknown"

            # Use user ID if authenticated, otherwise IP
            identifier = f"user:{user_id}" if user_id else f"ip:{client_ip}"
            base_key = f"ratelimit:{category}:{identifier}"

            # Check burst limit
            if not await rate_limiter.check_burst(base_key, config.burst_limit):
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down.",
                    headers={"Retry-After": "1"}
                )

            # Check per-minute limit
            allowed, remaining, reset = await rate_limiter.check_rate_limit(
                f"{base_key}:minute",
                config.requests_per_minute,
                60
            )

            if not allowed:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Try again in {reset - int(time.time())} seconds.",
                    headers={
                        "X-RateLimit-Limit": str(config.requests_per_minute),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset),
                        "Retry-After": str(reset - int(time.time()))
                    }
                )

            # Check per-hour limit
            allowed_hour, remaining_hour, reset_hour = await rate_limiter.check_rate_limit(
                f"{base_key}:hour",
                config.requests_per_hour,
                3600
            )

            if not allowed_hour:
                raise HTTPException(
                    status_code=429,
                    detail="Hourly rate limit exceeded. Please try again later.",
                    headers={
                        "X-RateLimit-Limit": str(config.requests_per_hour),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset_hour),
                        "Retry-After": str(reset_hour - int(time.time()))
                    }
                )

            # Execute the function
            response = await func(*args, **kwargs)

            return response

        return wrapper
    return decorator
```

### Usage Example

```python
# File: backend/app/routes/staking.py (updated)

from backend.app.middleware.rate_limiter import rate_limit

@router.post("/stake")
@rate_limit(category="staking")
async def stake_dung(
    request: Request,
    stake_request: StakeRequest,
    user_id: str = Depends(get_current_user_id),
    db = Depends(get_db)
):
    # ... existing implementation
    pass

@router.post("/unstake")
@rate_limit(category="staking")
async def unstake_dung(
    request: Request,
    unstake_request: UnstakeRequest,
    user_id: str = Depends(get_current_user_id),
    db = Depends(get_db)
):
    # ... existing implementation
    pass
```

---

## SECURITY-503: Emergency Pause (Kill Switch)

### Configuration Table

```sql
-- File: backend/sql/017_emergency_controls.sql

CREATE TABLE system_controls (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now(),
    updated_by UUID REFERENCES users(id)
);

-- Insert default controls
INSERT INTO system_controls (key, value) VALUES
    ('staking_enabled', '{"enabled": true, "reason": null}'::jsonb),
    ('minting_enabled', '{"enabled": true, "reason": null}'::jsonb),
    ('uploads_enabled', '{"enabled": true, "reason": null}'::jsonb),
    ('withdrawals_enabled', '{"enabled": true, "reason": null}'::jsonb),
    ('maintenance_mode', '{"enabled": false, "message": null}'::jsonb);

-- Admin users table
CREATE TABLE admin_users (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    role VARCHAR(50) NOT NULL DEFAULT 'admin',  -- 'admin', 'super_admin'
    granted_at TIMESTAMPTZ DEFAULT now(),
    granted_by UUID REFERENCES users(id)
);

CREATE INDEX idx_admin_users_role ON admin_users(role);
```

### Emergency Control Service

```python
# File: backend/app/services/emergency_controls.py

from typing import Optional, Dict, Any
from uuid import UUID
from functools import lru_cache
import asyncio

class EmergencyControls:
    """Service for managing emergency system controls."""

    def __init__(self, db):
        self.db = db
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 10  # Refresh cache every 10 seconds
        self._last_refresh = 0

    async def _refresh_cache(self):
        """Refresh the controls cache from database."""
        import time
        now = time.time()

        if now - self._last_refresh < self._cache_ttl:
            return

        rows = await self.db.fetch("SELECT key, value FROM system_controls")
        self._cache = {row["key"]: row["value"] for row in rows}
        self._last_refresh = now

    async def is_enabled(self, control: str) -> bool:
        """Check if a control is enabled."""
        await self._refresh_cache()
        value = self._cache.get(control, {"enabled": True})
        return value.get("enabled", True)

    async def get_reason(self, control: str) -> Optional[str]:
        """Get the reason for a disabled control."""
        await self._refresh_cache()
        value = self._cache.get(control, {})
        return value.get("reason")

    async def set_control(
        self,
        control: str,
        enabled: bool,
        reason: Optional[str] = None,
        admin_id: Optional[UUID] = None
    ):
        """Set a control value."""
        value = {"enabled": enabled, "reason": reason}

        await self.db.execute("""
            INSERT INTO system_controls (key, value, updated_at, updated_by)
            VALUES ($1, $2, now(), $3)
            ON CONFLICT (key) DO UPDATE
            SET value = $2, updated_at = now(), updated_by = $3
        """, control, value, admin_id)

        # Invalidate cache
        self._last_refresh = 0

    async def check_staking(self) -> tuple[bool, Optional[str]]:
        """Check if staking is enabled."""
        enabled = await self.is_enabled("staking_enabled")
        reason = await self.get_reason("staking_enabled") if not enabled else None
        return enabled, reason

    async def check_minting(self) -> tuple[bool, Optional[str]]:
        """Check if token minting is enabled."""
        enabled = await self.is_enabled("minting_enabled")
        reason = await self.get_reason("minting_enabled") if not enabled else None
        return enabled, reason

    async def check_uploads(self) -> tuple[bool, Optional[str]]:
        """Check if ride uploads are enabled."""
        enabled = await self.is_enabled("uploads_enabled")
        reason = await self.get_reason("uploads_enabled") if not enabled else None
        return enabled, reason

    async def check_maintenance(self) -> tuple[bool, Optional[str]]:
        """Check if system is in maintenance mode."""
        await self._refresh_cache()
        value = self._cache.get("maintenance_mode", {"enabled": False})
        return value.get("enabled", False), value.get("message")

# Dependency for FastAPI
async def get_emergency_controls(db = Depends(get_db)) -> EmergencyControls:
    return EmergencyControls(db)
```

### Admin API Endpoints

```python
# File: backend/app/routes/admin.py

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
from uuid import UUID

router = APIRouter(prefix="/admin", tags=["admin"])

class ControlUpdate(BaseModel):
    enabled: bool
    reason: Optional[str] = None

class AdminResponse(BaseModel):
    success: bool
    message: str

async def require_admin(
    user_id: str = Depends(get_current_user_id),
    db = Depends(get_db)
) -> UUID:
    """Dependency that requires admin privileges."""
    uid = UUID(user_id)

    admin = await db.fetchrow("""
        SELECT role FROM admin_users WHERE user_id = $1
    """, uid)

    if not admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    return uid

@router.get("/controls")
async def get_all_controls(
    admin_id: UUID = Depends(require_admin),
    db = Depends(get_db)
):
    """Get all system controls."""
    rows = await db.fetch("""
        SELECT key, value, updated_at, updated_by
        FROM system_controls
        ORDER BY key
    """)

    return {
        "controls": [
            {
                "key": row["key"],
                "value": row["value"],
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                "updated_by": str(row["updated_by"]) if row["updated_by"] else None
            }
            for row in rows
        ]
    }

@router.put("/controls/{control_key}")
async def update_control(
    control_key: str,
    update: ControlUpdate,
    request: Request,
    admin_id: UUID = Depends(require_admin),
    db = Depends(get_db)
):
    """Update a system control (emergency pause/resume)."""
    from backend.app.services.emergency_controls import EmergencyControls
    from backend.app.repositories.compliance import ComplianceRepository

    valid_controls = [
        "staking_enabled",
        "minting_enabled",
        "uploads_enabled",
        "withdrawals_enabled",
        "maintenance_mode"
    ]

    if control_key not in valid_controls:
        raise HTTPException(status_code=400, detail=f"Invalid control key. Valid: {valid_controls}")

    controls = EmergencyControls(db)
    await controls.set_control(
        control=control_key,
        enabled=update.enabled,
        reason=update.reason,
        admin_id=admin_id
    )

    # Audit log
    compliance = ComplianceRepository(db)
    await compliance.log_audit_event(
        action=f"system_control_{'enabled' if update.enabled else 'disabled'}",
        user_id=admin_id,
        target_type="system_control",
        metadata={
            "control": control_key,
            "enabled": update.enabled,
            "reason": update.reason
        },
        ip_address=request.client.host if request.client else None
    )

    action = "enabled" if update.enabled else "disabled"
    return AdminResponse(
        success=True,
        message=f"{control_key} has been {action}"
    )

@router.post("/emergency/pause-all")
async def emergency_pause_all(
    request: Request,
    reason: str,
    admin_id: UUID = Depends(require_admin),
    db = Depends(get_db)
):
    """Emergency pause ALL operations."""
    from backend.app.services.emergency_controls import EmergencyControls
    from backend.app.repositories.compliance import ComplianceRepository

    controls = EmergencyControls(db)

    # Disable all critical operations
    for control in ["staking_enabled", "minting_enabled", "uploads_enabled", "withdrawals_enabled"]:
        await controls.set_control(control, enabled=False, reason=reason, admin_id=admin_id)

    # Enable maintenance mode
    await db.execute("""
        UPDATE system_controls
        SET value = $1, updated_at = now(), updated_by = $2
        WHERE key = 'maintenance_mode'
    """, {"enabled": True, "message": reason}, admin_id)

    # Audit log
    compliance = ComplianceRepository(db)
    await compliance.log_audit_event(
        action="emergency_pause_all",
        user_id=admin_id,
        metadata={"reason": reason},
        ip_address=request.client.host if request.client else None
    )

    return AdminResponse(
        success=True,
        message=f"EMERGENCY PAUSE ACTIVATED: {reason}"
    )

@router.post("/emergency/resume-all")
async def emergency_resume_all(
    request: Request,
    admin_id: UUID = Depends(require_admin),
    db = Depends(get_db)
):
    """Resume all operations after emergency pause."""
    from backend.app.services.emergency_controls import EmergencyControls
    from backend.app.repositories.compliance import ComplianceRepository

    # Check for super_admin role
    admin = await db.fetchrow("SELECT role FROM admin_users WHERE user_id = $1", admin_id)
    if admin["role"] != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin required to resume after emergency")

    controls = EmergencyControls(db)

    for control in ["staking_enabled", "minting_enabled", "uploads_enabled", "withdrawals_enabled"]:
        await controls.set_control(control, enabled=True, reason=None, admin_id=admin_id)

    # Disable maintenance mode
    await db.execute("""
        UPDATE system_controls
        SET value = $1, updated_at = now(), updated_by = $2
        WHERE key = 'maintenance_mode'
    """, {"enabled": False, "message": None}, admin_id)

    # Audit log
    compliance = ComplianceRepository(db)
    await compliance.log_audit_event(
        action="emergency_resume_all",
        user_id=admin_id,
        ip_address=request.client.host if request.client else None
    )

    return AdminResponse(
        success=True,
        message="All operations resumed"
    )
```

### Middleware for Checking Controls

```python
# File: backend/app/middleware/emergency_check.py

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

class EmergencyCheckMiddleware(BaseHTTPMiddleware):
    """Middleware to check emergency controls before processing requests."""

    # Endpoints that require specific controls
    CONTROL_MAP = {
        "/api/v1/staking/": "staking_enabled",
        "/api/v1/cal/mint": "minting_enabled",
        "/api/v1/rides/upload": "uploads_enabled",
        "/api/v1/staking/unstake": "withdrawals_enabled",
    }

    async def dispatch(self, request: Request, call_next):
        from backend.app.services.emergency_controls import EmergencyControls

        path = request.url.path

        # Check maintenance mode first
        db = request.state.db if hasattr(request.state, "db") else None
        if db:
            controls = EmergencyControls(db)
            in_maintenance, message = await controls.check_maintenance()

            if in_maintenance:
                # Allow admin endpoints
                if not path.startswith("/api/v1/admin"):
                    raise HTTPException(
                        status_code=503,
                        detail=f"System under maintenance: {message or 'Please try again later'}"
                    )

        # Check specific controls
        for prefix, control in self.CONTROL_MAP.items():
            if path.startswith(prefix):
                if db:
                    controls = EmergencyControls(db)
                    enabled, reason = await controls.is_enabled(control), await controls.get_reason(control)

                    if not enabled:
                        raise HTTPException(
                            status_code=503,
                            detail=f"Service temporarily disabled: {reason or 'Please try again later'}"
                        )
                break

        return await call_next(request)
```

---

## Testing

### Unit Tests

```python
# File: backend/tests/test_compliance.py

import pytest
from uuid import uuid4
from backend.app.repositories.compliance import ComplianceRepository

@pytest.fixture
async def compliance_repo(test_db):
    return ComplianceRepository(test_db)

@pytest.fixture
async def test_user(test_db):
    """Create a test user."""
    user_id = uuid4()
    await test_db.execute("""
        INSERT INTO users (id, wallet_address, display_name)
        VALUES ($1, $2, $3)
    """, user_id, "TestWallet123", "Test User")
    return user_id

class TestAuditLogging:
    async def test_log_audit_event(self, compliance_repo, test_user):
        """Test creating audit log entries."""
        event_id = await compliance_repo.log_audit_event(
            action="test_action",
            user_id=test_user,
            target_type="user",
            target_id=test_user,
            metadata={"key": "value"}
        )

        assert event_id is not None

    async def test_get_user_audit_log(self, compliance_repo, test_user):
        """Test retrieving user audit log."""
        # Create some events
        for i in range(5):
            await compliance_repo.log_audit_event(
                action=f"action_{i}",
                user_id=test_user
            )

        log = await compliance_repo.get_user_audit_log(test_user)

        assert len(log) == 5
        assert log[0]["action"] == "action_4"  # Most recent first

class TestDataExport:
    async def test_export_user_data(self, compliance_repo, test_user, test_db):
        """Test exporting all user data."""
        # Create some token balance
        await test_db.execute("""
            INSERT INTO token_balances (user_id, dung_balance, cal_balance)
            VALUES ($1, 1000, 500)
        """, test_user)

        data = await compliance_repo.export_user_data(test_user)

        assert data["profile"] is not None
        assert data["profile"]["wallet_address"] == "TestWallet123"
        assert data["token_balances"]["dung_balance"] == 1000
        assert "rides" in data
        assert "achievements" in data

class TestDataDeletion:
    async def test_delete_user_data(self, compliance_repo, test_user, test_db):
        """Test deleting all user data."""
        # Create some related data
        await test_db.execute("""
            INSERT INTO token_balances (user_id, dung_balance)
            VALUES ($1, 1000)
        """, test_user)

        counts = await compliance_repo.delete_user_data(test_user)

        assert counts["users"] == 1

        # Verify user is deleted
        user = await test_db.fetchrow("SELECT * FROM users WHERE id = $1", test_user)
        assert user is None

class TestRateLimiting:
    async def test_rate_limit_allows_normal_usage(self, test_client):
        """Test that normal usage is allowed."""
        # Make 5 requests (under limit)
        for _ in range(5):
            response = await test_client.get("/api/v1/users/me")
            assert response.status_code != 429

    async def test_rate_limit_blocks_excessive_requests(self, test_client):
        """Test that excessive requests are blocked."""
        # Make many requests rapidly
        for i in range(100):
            response = await test_client.get("/api/v1/users/me")
            if response.status_code == 429:
                # Rate limit triggered as expected
                assert "Retry-After" in response.headers
                return

        pytest.fail("Rate limit should have been triggered")

class TestEmergencyControls:
    async def test_pause_staking(self, test_db, admin_client):
        """Test pausing staking operations."""
        response = await admin_client.put(
            "/api/v1/admin/controls/staking_enabled",
            json={"enabled": False, "reason": "Emergency maintenance"}
        )

        assert response.status_code == 200

        # Verify staking is blocked
        response = await test_client.post("/api/v1/staking/stake", json={"amount": 100})
        assert response.status_code == 503

    async def test_emergency_pause_all(self, admin_client):
        """Test emergency pause all operations."""
        response = await admin_client.post(
            "/api/v1/admin/emergency/pause-all",
            params={"reason": "Critical security issue"}
        )

        assert response.status_code == 200
        assert "EMERGENCY PAUSE ACTIVATED" in response.json()["message"]
```

### Integration Tests

```python
# File: backend/tests/integration/test_compliance_flow.py

import pytest

class TestGDPRFlow:
    async def test_full_gdpr_export_flow(self, authenticated_client):
        """Test complete GDPR data export flow."""
        # Request export
        response = await authenticated_client.get("/api/v1/compliance/export")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["download_url"] is not None

    async def test_full_gdpr_deletion_flow(self, authenticated_client, test_db):
        """Test complete GDPR account deletion flow."""
        # Get user ID before deletion
        me_response = await authenticated_client.get("/api/v1/users/me")
        user_id = me_response.json()["id"]

        # Request deletion
        response = await authenticated_client.delete("/api/v1/compliance/account")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "processing"
        request_id = data["request_id"]

        # Wait for background task
        import asyncio
        await asyncio.sleep(1)

        # Check deletion status
        status_response = await authenticated_client.get(
            f"/api/v1/compliance/deletion-status/{request_id}"
        )

        # Verify user is deleted
        user = await test_db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        assert user is None

class TestEmergencyFlow:
    async def test_emergency_pause_resume_flow(self, super_admin_client, test_client):
        """Test full emergency pause and resume flow."""
        # Pause all
        pause_response = await super_admin_client.post(
            "/api/v1/admin/emergency/pause-all",
            params={"reason": "Test emergency"}
        )
        assert pause_response.status_code == 200

        # Verify operations blocked
        stake_response = await test_client.post("/api/v1/staking/stake", json={"amount": 100})
        assert stake_response.status_code == 503

        # Resume all
        resume_response = await super_admin_client.post("/api/v1/admin/emergency/resume-all")
        assert resume_response.status_code == 200

        # Verify operations restored
        # (Would need valid auth for actual stake test)
```

---

## Manual Testing Checklist

### GDPR Compliance

- [ ] User can request data export from profile settings
- [ ] Export includes all user data (profile, rides, tokens, achievements)
- [ ] Export is in machine-readable JSON format
- [ ] User can request account deletion
- [ ] Deletion confirmation modal explains consequences
- [ ] All user data is removed after deletion
- [ ] Audit log entries are anonymized (not deleted)
- [ ] Deletion request status can be checked

### Rate Limiting

- [ ] Normal usage is not affected
- [ ] Rapid requests trigger 429 response
- [ ] 429 response includes Retry-After header
- [ ] Per-user limits work correctly
- [ ] Per-IP limits work for unauthenticated requests
- [ ] Staking endpoints have stricter limits
- [ ] Auth endpoints have stricter limits

### Emergency Controls

- [ ] Admin can view all system controls
- [ ] Admin can pause staking operations
- [ ] Admin can pause minting operations
- [ ] Admin can pause uploads
- [ ] Paused operations return 503 with message
- [ ] Super admin can trigger emergency pause all
- [ ] Super admin can resume operations
- [ ] All control changes are audit logged
- [ ] Maintenance mode blocks all non-admin endpoints

### Audit Logging

- [ ] All token operations are logged
- [ ] All auth events are logged
- [ ] All admin actions are logged
- [ ] Logs include IP address and user agent
- [ ] Logs are queryable by user ID
- [ ] Logs are retained after user deletion (anonymized)

---

## Deployment Notes

### Environment Variables

```bash
# Redis for rate limiting
REDIS_URL=redis://localhost:6379

# Admin wallet addresses (comma-separated)
ADMIN_WALLETS=wallet1,wallet2

# Rate limit overrides (optional)
RATE_LIMIT_MULTIPLIER=1.0  # Increase/decrease all limits
```

### Database Migrations

```bash
# Run migrations
cd backend
alembic upgrade head

# Or manual SQL
psql $DATABASE_URL < sql/016_compliance.sql
psql $DATABASE_URL < sql/017_emergency_controls.sql
```

### Redis Setup

```bash
# Local development
docker run -d -p 6379:6379 redis:alpine

# Production: Use managed Redis (AWS ElastiCache, etc.)
```

---

## Completion Checklist

- [ ] Database schemas created (016, 017)
- [ ] ComplianceRepository implemented
- [ ] Compliance API endpoints working
- [ ] Rate limiter middleware implemented
- [ ] Emergency controls service implemented
- [ ] Admin API endpoints working
- [ ] Emergency check middleware integrated
- [ ] Unit tests passing
- [ ] Integration tests passing
- [ ] Manual testing complete
- [ ] Documentation updated
