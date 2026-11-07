"""Achievement repository - user achievements and badges."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import BaseRepository


class AchievementRepository(BaseRepository):
    """Repository for user achievements and badges."""

    async def create_achievement(
        self,
        user_id: uuid.UUID,
        ride_id: uuid.UUID,
        achievement_type: str,
        title: str,
        description: str,
        value: Optional[float],
        rank: Optional[int],
        pattern_type: Optional[str],
        metadata: Dict[str, Any],
    ) -> uuid.UUID:
        """Create a new achievement for a user.

        Args:
            user_id: The user who earned the achievement
            ride_id: The ride that triggered the achievement
            achievement_type: Type of achievement (e.g., 'pr', 'kom', 'milestone')
            title: Display title for the achievement
            description: Detailed description
            value: Numeric value associated (e.g., power, time)
            rank: Ranking if applicable
            pattern_type: Type of pattern that triggered this (climb, steady, explorer)
            metadata: Additional structured data

        Returns:
            The UUID of the created achievement
        """
        achievement_id = str(uuid.uuid4())

        # Include pattern_type in metadata (DB column is segment_id for legacy)
        enriched_metadata = (
            {**metadata, "pattern_type": pattern_type} if pattern_type else metadata
        )

        payload = {
            "id": achievement_id,
            "user_id": str(user_id),
            "ride_id": str(ride_id),
            "achievement_type": achievement_type,
            "title": title,
            "description": description,
            "value": value,
            "rank": rank,
            "metadata": enriched_metadata,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}

        await self._run(
            lambda: self._client.table("achievements").insert(payload).execute()
        )
        return uuid.UUID(achievement_id)

    async def get_user_achievements(
        self, user_id: uuid.UUID, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get achievements for a user, most recent first.

        Args:
            user_id: The user to fetch achievements for
            limit: Maximum number of achievements to return

        Returns:
            List of achievement records
        """
        response = await self._run(
            lambda: self._client.table("achievements")
            .select("*")
            .eq("user_id", str(user_id))
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]
