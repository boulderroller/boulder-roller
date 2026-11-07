"""Repository exports.

This module provides domain-specific repositories for database operations.
During migration from the monolithic repositories.py, services can gradually
adopt specific repositories while maintaining backwards compatibility.

Usage:
    # New style - import specific repository
    from app.repositories import AchievementRepository, get_supabase_client

    client = get_supabase_client()
    achievements = AchievementRepository(client)
    await achievements.create_achievement(...)

    # Or use the factory
    from app.repositories import create_achievement_repository

    achievements = create_achievement_repository()
    await achievements.get_user_achievements(user_id)

    # Legacy - still supported for backwards compatibility
    from app.repositories import DatabaseRepository, create_supabase_repository
    repo = create_supabase_repository()
"""
from .base import BaseRepository, get_supabase_client, _build_supabase_client
from .achievement import AchievementRepository
from .auth import AuthRepository
from .canon import CanonRegistryError, CanonRepository
from .fitness import FitnessRepository
from .leaderboard import (
    LeaderboardRepository,
    GlobalKomEntryDict,
    GlobalEarningsEntryDict,
    UserGlobalKomRankDict,
    UserGlobalEarningsRankDict,
)
from .notification import (
    NotificationRepository,
    NotificationDict,
    LeaderboardUpdateResult,
)
from .pattern import PatternRepository
from .ride import RideRepository
from .ride_economic import (
    ConfirmedCompletionCandidateUnavailable,
    ConfirmedCompletionCandidateProvider,
    RideEconomicRepository,
    is_authoritative_completion,
    is_authoritative_tribute,
)
from .segment import SegmentRepository
from .territory import TerritoryRepository
from .tile import TileRepository
from .token import TokenRepository
from .user import UserRepository
from .vault import (
    VaultRepository,
    VaultStakeDict,
    VaultTotalStakeDict,
    LeaderboardEntryDict,
    VaultCompletionDict,
    LocalLegendDict,
)

# Legacy re-exports for backwards compatibility
from ..repositories_legacy import (
    DatabaseRepository,
    SupabaseRepository,
    create_supabase_repository,
)

__all__ = [
    # Base
    "BaseRepository",
    "get_supabase_client",
    "_build_supabase_client",
    # Domain repositories
    "AchievementRepository",
    "AuthRepository",
    "CanonRepository",
    "CanonRegistryError",
    "FitnessRepository",
    "LeaderboardRepository",
    "NotificationRepository",
    "PatternRepository",
    "RideRepository",
    "RideEconomicRepository",
    "ConfirmedCompletionCandidateUnavailable",
    "ConfirmedCompletionCandidateProvider",
    "is_authoritative_completion",
    "is_authoritative_tribute",
    "SegmentRepository",
    "TerritoryRepository",
    "TileRepository",
    "TokenRepository",
    "UserRepository",
    "VaultRepository",
    # Leaderboard TypedDicts
    "GlobalKomEntryDict",
    "GlobalEarningsEntryDict",
    "UserGlobalKomRankDict",
    "UserGlobalEarningsRankDict",
    # Notification TypedDicts
    "NotificationDict",
    "LeaderboardUpdateResult",
    # Vault TypedDicts
    "VaultStakeDict",
    "VaultTotalStakeDict",
    "LeaderboardEntryDict",
    "VaultCompletionDict",
    "LocalLegendDict",
    # Legacy (deprecated)
    "DatabaseRepository",
    "SupabaseRepository",
    "create_supabase_repository",
    # Factories
    "create_achievement_repository",
    "create_auth_repository",
    "create_canon_repository",
    "create_fitness_repository",
    "create_leaderboard_repository",
    "create_notification_repository",
    "create_pattern_repository",
    "create_ride_repository",
    "create_ride_economic_repository",
    "create_segment_repository",
    "create_territory_repository",
    "create_tile_repository",
    "create_token_repository",
    "create_user_repository",
    "create_vault_repository",
]


def create_achievement_repository() -> AchievementRepository:
    """Create an AchievementRepository with the shared client."""
    return AchievementRepository(get_supabase_client())


def create_auth_repository() -> AuthRepository:
    """Create an AuthRepository with the shared client."""
    return AuthRepository(get_supabase_client())


def create_canon_repository() -> CanonRepository:
    """Create a private service-role CanonRepository with the shared client."""
    return CanonRepository(get_supabase_client())


def create_fitness_repository() -> FitnessRepository:
    """Create a FitnessRepository with the shared client."""
    return FitnessRepository(get_supabase_client())


def create_pattern_repository() -> PatternRepository:
    """Create a PatternRepository with the shared client."""
    return PatternRepository(get_supabase_client())


def create_ride_repository() -> RideRepository:
    """Create a RideRepository with the shared client."""
    return RideRepository(get_supabase_client())


def create_ride_economic_repository() -> RideEconomicRepository:
    """Create the durable ride-economic repository with the shared client."""
    return RideEconomicRepository(get_supabase_client())


def create_segment_repository() -> SegmentRepository:
    """Create a SegmentRepository with the shared client."""
    return SegmentRepository(get_supabase_client())


def create_territory_repository() -> TerritoryRepository:
    """Create a TerritoryRepository with the shared client."""
    return TerritoryRepository(get_supabase_client())


def create_tile_repository() -> TileRepository:
    """Create a TileRepository with the shared client."""
    return TileRepository(get_supabase_client())


def create_token_repository() -> TokenRepository:
    """Create a TokenRepository with the shared client."""
    return TokenRepository(get_supabase_client())


def create_user_repository() -> UserRepository:
    """Create a UserRepository with the shared client."""
    return UserRepository(get_supabase_client())


def create_notification_repository() -> NotificationRepository:
    """Create a NotificationRepository with the shared client."""
    return NotificationRepository(get_supabase_client())


def create_vault_repository() -> VaultRepository:
    """Create a VaultRepository with the shared client."""
    return VaultRepository(get_supabase_client())


def create_leaderboard_repository() -> LeaderboardRepository:
    """Create a LeaderboardRepository with the shared client."""
    return LeaderboardRepository(get_supabase_client())
