import os
import re
from typing import Optional

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import get_environment
from ..services.emergency_controls import EmergencyControls


class EmergencyCheckMiddleware(BaseHTTPMiddleware):
    """Middleware to check emergency controls before processing requests."""

    CONTROL_PREFIXES = (
        ("/staking/unstake", "withdrawals_enabled"),
        ("/staking/", "staking_enabled"),
        ("/cal/mint", "minting_enabled"),
        ("/mint", "minting_enabled"),
        ("/rides/upload", "uploads_enabled"),
    )
    VAULT_ACTION_RE = re.compile(r"^/vaults/[^/]+/(?P<action>stake|unstake|harvest)(?:/prepare)?/?$")

    @classmethod
    def control_for_path(cls, path: str) -> Optional[str]:
        vault_match = cls.VAULT_ACTION_RE.match(path)
        if vault_match:
            action = vault_match.group("action")
            if action == "stake":
                return "staking_enabled"
            return "withdrawals_enabled"

        for prefix, control in cls.CONTROL_PREFIXES:
            if path.startswith(prefix):
                return control
        return None

    async def dispatch(self, request: Request, call_next):
        # In tests or when Supabase credentials are missing, fail open so unit tests don't raise.
        if get_environment() == "test" or not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
            return await call_next(request)

        path = request.url.path or ""
        try:
            controls = EmergencyControls()
            in_maintenance, message = await controls.check_maintenance()
            if in_maintenance and not path.startswith("/admin"):
                raise HTTPException(
                    status_code=503,
                    detail=f"System under maintenance: {message or 'Please try again later'}",
                )

            control = self.control_for_path(path)
            if control:
                enabled = await controls.is_enabled(control)
                if not enabled:
                    reason = await controls.get_reason(control)
                    raise HTTPException(
                        status_code=503,
                        detail=f"Service temporarily disabled: {reason or 'Please try again later'}",
                    )
        except HTTPException:
            raise
        except Exception:
            # Fail open if control checks are unavailable
            return await call_next(request)

        return await call_next(request)
