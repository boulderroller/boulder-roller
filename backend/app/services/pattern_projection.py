"""Small read-model helpers shared by pattern projection services."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from typing import Any, Dict
from uuid import UUID


def pattern_from_row(model: Any, row: Dict[str, Any]) -> Any:
    """Reconstruct one stored pattern using only fields admitted by its model."""
    allowed = {field.name for field in fields(model)}
    payload = {key: value for key, value in row.items() if key in allowed}
    for key in ("id", "activity_id", "arena_id"):
        if payload.get(key):
            payload[key] = UUID(str(payload[key]))
    if payload.get("created_at") and isinstance(payload["created_at"], str):
        payload["created_at"] = datetime.fromisoformat(
            payload["created_at"].replace("Z", "+00:00")
        )
    return model(**payload)
