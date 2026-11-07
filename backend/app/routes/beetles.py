"""
Beetle Cards Routes: Soulbound effort NFT endpoints.

Beetle Cards are non-transferable NFTs that track cumulative effort:
- ClimbBeetle: Per-arena climbing progress
- SteadyBeetle: Global steady-state endurance
- ExplorerBeetle: Global exploration coverage

Cards accumulate effort from detected patterns during rides (automatic attribution).
Upgrades require DUNG burn per the formula: 25 * 2^(level-1) DUNG.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository

router = APIRouter(prefix="/beetles", tags=["beetles"])


# Level thresholds (DEPRECATED - old effort-based system)
# NOTE: The spec uses DUNG burn upgrades with formula 25 * 2^(level-1)
# These thresholds are kept for backwards compatibility with existing cards
LEVEL_THRESHOLDS = [100, 500, 1500, 5000, 15000, 50000, 150000, 500000, 1500000, 5000000]

# Upgrade costs per TOKENOMICS_V2 spec: 25 * 2^(level-1) DUNG
# L0->1: 25, L1->2: 25, L2->3: 50, L3->4: 100, etc.
UPGRADE_COSTS = [25, 25, 50, 100, 200, 400, 800, 1600, 3200, 6400]  # DUNG to reach each level


def get_upgrade_cost(current_level: int) -> int:
    """
    Calculate DUNG cost to upgrade from current_level to next level.
    Formula: 25 * 2^(level-1) for level >= 1, 25 for level 0
    Returns 0 if already at max level (10).
    """
    if current_level >= 10:
        return 0
    if current_level == 0:
        return 25
    return 25 * (2 ** (current_level - 1))

# Global scope constant
GLOBAL_SCOPE = "00000000-0000-0000-0000-000000000000"
WORLD_ARENA = "00000000-0000-0000-0000-000000000001"


class BeetleCardResponse(BaseModel):
    """Response model for a Beetle Card."""
    id: str
    wallet: str
    card_type: str
    scope_id: str
    scope_name: Optional[str] = None  # Arena name for climb cards
    score: int
    level: int
    patterns_scored: int
    next_level_threshold: Optional[int] = None  # DEPRECATED: old effort-based system
    progress_to_next: Optional[float] = None  # DEPRECATED: old effort-based system
    upgrade_cost_dung: Optional[int] = None  # DUNG cost to upgrade to next level
    created_at: str
    updated_at: str


class BeetleLeaderboardEntry(BaseModel):
    """Leaderboard entry for Beetle Cards."""
    rank: int
    wallet: str
    score: int
    level: int
    patterns_scored: int
    scope_name: Optional[str] = None


# =====================================================
# USER'S BEETLE CARDS
# =====================================================

@router.get("/my-cards")
async def get_my_beetle_cards(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> List[BeetleCardResponse]:
    """
    Get all Beetle Cards owned by the current user.

    Returns cards for all types (Climb, Steady, Explorer) with level progress.
    """
    response = await repo._run(
        lambda: repo._client.table("beetle_cards")
        .select("*")
        .eq("wallet", current_user.wallet)
        .order("card_type")
        .execute()
    )
    cards = getattr(response, "data", None) or []

    # Get arena names for climb cards
    arena_ids = [c["scope_id"] for c in cards if c["card_type"] == "CLIMB"]
    arena_names = {}
    if arena_ids:
        arenas_response = await repo._run(
            lambda: repo._client.table("arenas")
            .select("id, name")
            .in_("id", arena_ids)
            .execute()
        )
        arenas_data = getattr(arenas_response, "data", None) or []
        arena_names = {str(a["id"]): a["name"] for a in arenas_data}

    result = []
    for card in cards:
        # Calculate progress to next level
        next_threshold = None
        progress = None
        if card["level"] < 10:
            next_threshold = LEVEL_THRESHOLDS[card["level"]]
            if card["level"] == 0:
                prev_threshold = 0
            else:
                prev_threshold = LEVEL_THRESHOLDS[card["level"] - 1]
            range_size = next_threshold - prev_threshold
            progress_in_range = card["score"] - prev_threshold
            progress = progress_in_range / range_size if range_size > 0 else 1.0

        scope_name = None
        if card["card_type"] == "CLIMB":
            scope_name = arena_names.get(card["scope_id"], "World Arena")
        elif card["card_type"] == "STEADY":
            scope_name = "Global"
        elif card["card_type"] == "EXPLORATION":
            scope_name = "Global"

        result.append(BeetleCardResponse(
            id=card["id"],
            wallet=card["wallet"],
            card_type=card["card_type"],
            scope_id=card["scope_id"],
            scope_name=scope_name,
            score=card["score"],
            level=card["level"],
            patterns_scored=card["patterns_scored"],
            next_level_threshold=next_threshold,
            progress_to_next=progress,
            upgrade_cost_dung=get_upgrade_cost(card["level"]),
            created_at=card["created_at"],
            updated_at=card["updated_at"],
        ))

    return result


@router.get("/my-cards/{card_type}")
async def get_my_beetle_card_by_type(
    card_type: str,
    scope_id: Optional[str] = Query(None, description="Arena ID for CLIMB cards"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> BeetleCardResponse:
    """
    Get a specific Beetle Card by type.

    For CLIMB cards, optionally specify scope_id (arena ID).
    For STEADY/EXPLORATION, scope_id is always GLOBAL_SCOPE.
    """
    card_type_upper = card_type.upper()
    if card_type_upper not in ["CLIMB", "STEADY", "EXPLORATION"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid card type: {card_type}. Valid: CLIMB, STEADY, EXPLORATION"
        )

    # Determine scope
    if card_type_upper == "CLIMB":
        final_scope = scope_id if scope_id else WORLD_ARENA
    else:
        final_scope = GLOBAL_SCOPE

    response = await repo._run(
        lambda: repo._client.table("beetle_cards")
        .select("*")
        .eq("wallet", current_user.wallet)
        .eq("card_type", card_type_upper)
        .eq("scope_id", final_scope)
        .limit(1)
        .execute()
    )
    cards = getattr(response, "data", None) or []

    if not cards:
        raise HTTPException(status_code=404, detail="Beetle Card not found")

    card = cards[0]

    # Get arena name if climb card
    scope_name = None
    if card_type_upper == "CLIMB":
        arena_response = await repo._run(
            lambda: repo._client.table("arenas")
            .select("name")
            .eq("id", final_scope)
            .limit(1)
            .execute()
        )
        arena_data = getattr(arena_response, "data", None) or []
        scope_name = arena_data[0]["name"] if arena_data else "World Arena"
    else:
        scope_name = "Global"

    # Calculate progress
    next_threshold = None
    progress = None
    if card["level"] < 10:
        next_threshold = LEVEL_THRESHOLDS[card["level"]]
        prev_threshold = LEVEL_THRESHOLDS[card["level"] - 1] if card["level"] > 0 else 0
        range_size = next_threshold - prev_threshold
        progress_in_range = card["score"] - prev_threshold
        progress = progress_in_range / range_size if range_size > 0 else 1.0

    return BeetleCardResponse(
        id=card["id"],
        wallet=card["wallet"],
        card_type=card["card_type"],
        scope_id=card["scope_id"],
        scope_name=scope_name,
        score=card["score"],
        level=card["level"],
        patterns_scored=card["patterns_scored"],
        next_level_threshold=next_threshold,
        progress_to_next=progress,
        upgrade_cost_dung=get_upgrade_cost(card["level"]),
        created_at=card["created_at"],
        updated_at=card["updated_at"],
    )


# =====================================================
# LEADERBOARDS
# =====================================================

@router.get("/leaderboard/{card_type}")
async def get_beetle_leaderboard(
    card_type: str,
    scope_id: Optional[str] = Query(None, description="Arena ID for CLIMB (default: World Arena)"),
    limit: int = Query(50, le=100),
    offset: int = Query(0, ge=0),
    repo: DatabaseRepository = Depends(get_repository),
) -> dict:
    """
    Get Beetle Card leaderboard by card type.

    Rankings are based on level first, then score.
    """
    card_type_upper = card_type.upper()
    if card_type_upper not in ["CLIMB", "STEADY", "EXPLORATION"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid card type: {card_type}. Valid: CLIMB, STEADY, EXPLORATION"
        )

    # Determine scope
    if card_type_upper == "CLIMB":
        final_scope = scope_id if scope_id else WORLD_ARENA
    else:
        final_scope = GLOBAL_SCOPE

    # Query leaderboard
    query = repo._client.table("beetle_cards") \
        .select("wallet, score, level, patterns_scored") \
        .eq("card_type", card_type_upper) \
        .eq("scope_id", final_scope) \
        .order("level", desc=True) \
        .order("score", desc=True) \
        .range(offset, offset + limit - 1)

    response = await repo._run(lambda: query.execute())
    entries = getattr(response, "data", None) or []

    # Get scope name
    scope_name = None
    if card_type_upper == "CLIMB":
        arena_response = await repo._run(
            lambda: repo._client.table("arenas")
            .select("name")
            .eq("id", final_scope)
            .limit(1)
            .execute()
        )
        arena_data = getattr(arena_response, "data", None) or []
        scope_name = arena_data[0]["name"] if arena_data else "World Arena"
    else:
        scope_name = "Global"

    # Build leaderboard with ranks
    leaderboard = []
    for i, entry in enumerate(entries):
        leaderboard.append(BeetleLeaderboardEntry(
            rank=offset + i + 1,
            wallet=entry["wallet"],
            score=entry["score"],
            level=entry["level"],
            patterns_scored=entry["patterns_scored"],
            scope_name=scope_name,
        ))

    return {
        "card_type": card_type_upper,
        "scope_id": final_scope,
        "scope_name": scope_name,
        "entries": leaderboard,
        "count": len(leaderboard),
        "offset": offset,
    }


# =====================================================
# LEVEL INFO
# =====================================================

@router.get("/levels")
async def get_level_info() -> dict:
    """
    Get information about Beetle Card levels, upgrade costs, and thresholds.

    Upgrade costs follow TOKENOMICS_V2 spec: 25 * 2^(level-1) DUNG
    """
    return {
        "max_level": 10,
        "upgrade_costs": [
            {
                "from_level": i,
                "to_level": i + 1,
                "dung_cost": get_upgrade_cost(i),
                "formula": f"25 * 2^({i}-1)" if i > 0 else "25 (base cost)",
            }
            for i in range(10)
        ],
        "thresholds_deprecated": [
            {"level": i, "score_required": threshold, "note": "DEPRECATED: old effort-based system"}
            for i, threshold in enumerate(LEVEL_THRESHOLDS, start=1)
        ],
        "level_names": [
            "Novice",      # 0
            "Apprentice",  # 1
            "Journeyman",  # 2
            "Adept",       # 3
            "Expert",      # 4
            "Master",      # 5
            "Grandmaster", # 6
            "Champion",    # 7
            "Legend",      # 8
            "Mythic",      # 9
            "Transcendent" # 10
        ],
    }
