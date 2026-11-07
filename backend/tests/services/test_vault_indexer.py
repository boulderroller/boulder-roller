"""
Tests for the read-only VaultSignatureCache.

Coverage:
- Vault signature cache loading
- Signature matching with similarity threshold
- Vault lookup by ID and signature hash
- Cache invalidation
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.services.vault_indexer as vault_indexer_module
from app.services.vault_indexer import (
    IndexedVault,
    VaultSignatureCache,
)
from app.services.patterns.climb_signature import ClimbSignature


def test_legacy_chain_writer_is_retired() -> None:
    assert not hasattr(vault_indexer_module, "VaultIndexer")
    assert not hasattr(vault_indexer_module, "start_background_sync")


@pytest.fixture
def sample_vaults() -> List[IndexedVault]:
    """Create sample indexed vaults for testing."""
    return [
        IndexedVault(
            id=0,
            signature_hex="a" * 128,  # 64 bytes in hex
            signature_hash_hex="b" * 64,
            minter="minter-1",
            name="Col du Galibier",
            vert_m=500.0,
            distance_m=6666,
            avg_gradient_pct=7.5,
            total_completions=100,
            total_staked=50000,
            kom_holder="kom-holder-1",
            kom_time_s=1800,
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            pda="vault-pda-0",
        ),
        IndexedVault(
            id=1,
            signature_hex="c" * 128,
            signature_hash_hex="d" * 64,
            minter="minter-2",
            name="Alpe d'Huez",
            vert_m=1100.0,
            distance_m=13800,
            avg_gradient_pct=8.0,
            total_completions=250,
            total_staked=100000,
            kom_holder="kom-holder-2",
            kom_time_s=3600,
            created_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            pda="vault-pda-1",
        ),
    ]


@pytest.fixture
def vault_cache() -> VaultSignatureCache:
    """Create empty vault cache."""
    return VaultSignatureCache()


def mock_rest_pages(
    pages: dict[int, list[dict]],
    activation_pages: dict[int, list[dict]] | None = None,
) -> tuple[MagicMock, MagicMock]:
    def build_query(query_pages: dict[int, list[dict]]) -> MagicMock:
        query = MagicMock()
        for method_name in ("eq", "gte", "order"):
            getattr(query, method_name).return_value = query

        def page_builder(start: int, _end: int) -> MagicMock:
            builder = MagicMock()
            builder.execute.return_value = MagicMock(
                data=query_pages.get(start, [])
            )
            return builder

        query.range.side_effect = page_builder
        return query

    vault_query = build_query(pages)
    activation_query = build_query(activation_pages or {0: []})
    vault_table = MagicMock()
    vault_table.select.return_value = vault_query
    activation_table = MagicMock()
    activation_table.select.return_value = activation_query
    client = MagicMock()
    client.from_.side_effect = lambda table: (
        activation_table if table == "indexed_vault_activations" else vault_table
    )
    return client, vault_query


@pytest.fixture(autouse=True)
def disable_direct_postgres_pool():
    """Keep cache-load tests on their mocked Supabase client."""
    with patch("app.db_pool.get_pool", new_callable=AsyncMock) as mock_get_pool:
        mock_get_pool.side_effect = RuntimeError("No test pool configured")
        yield


class TestVaultSignatureCache:
    """Tests for VaultSignatureCache."""

    def test_cache_starts_empty(self, vault_cache):
        """New cache should be empty and not loaded."""
        assert vault_cache.count == 0
        assert not vault_cache.is_loaded

    def test_get_vault_nonexistent(self, vault_cache):
        """Getting nonexistent vault returns None."""
        assert vault_cache.get_vault(999) is None

    def test_find_matches_when_not_loaded(self, vault_cache):
        """Find matches returns empty when cache not loaded."""
        mock_signature = MagicMock(spec=ClimbSignature)

        matches = vault_cache.find_matches(mock_signature, min_similarity=0.90)

        assert matches == []

    @pytest.mark.asyncio
    async def test_load_from_database(self, vault_cache):
        """Test loading vaults from database."""
        mock_supabase, _query = mock_rest_pages(
            {
                0: [
                    {
                        "id": 0,
                        "signature_hex": "a" * 128,
                        "signature_hash_hex": "b" * 64,
                        "minter": "minter-1",
                        "name": "Test Vault",
                        "vert_m": 500.0,
                        "distance_m": 5000,
                        "avg_gradient_pct": 7.0,
                        "total_completions": 50,
                        "total_staked": 10000,
                        "kom_holder": None,
                        "kom_time_s": 0,
                        "created_at": "2024-01-01T00:00:00Z",
                        "pda": "vault-pda-0",
                    },
                ]
            }
        )

        count = await vault_cache.load(mock_supabase)

        assert count == 1
        assert vault_cache.is_loaded
        assert vault_cache.count == 1
        assert vault_cache.get_vault(0).name == "Test Vault"

    @pytest.mark.asyncio
    async def test_rest_fallback_loads_every_vault_page(self, vault_cache):
        def vault_row(vault_id: int) -> dict:
            return {
                "id": vault_id,
                "signature_hex": "a" * 128,
                "signature_hash_hex": f"{vault_id:064x}",
                "minter": "minter-1",
                "name": f"Vault {vault_id}",
                "vert_m": 50.0,
                "distance_m": 500,
                "avg_gradient_pct": 10.0,
                "total_completions": 0,
                "total_staked": 0,
                "kom_holder": None,
                "kom_time_s": 0,
                "created_at": "2024-01-01T00:00:00Z",
                "pda": f"vault-pda-{vault_id}",
            }

        pages = {
            0: [vault_row(vault_id) for vault_id in range(1000)],
            1000: [vault_row(1000)],
        }
        mock_supabase, query = mock_rest_pages(pages)

        count = await vault_cache.load(mock_supabase)

        assert count == 1001
        assert query.range.call_count == 2
        assert vault_cache.get_vault(1000).name == "Vault 1000"

    @pytest.mark.asyncio
    async def test_load_preserves_valid_equator_coordinates(self, vault_cache):
        mock_supabase, _query = mock_rest_pages(
            {
                0: [
                    {
                        "id": 0,
                        "signature_hex": "a" * 128,
                        "signature_hash_hex": "b" * 64,
                        "minter": "minter-1",
                        "name": "Equator Vault",
                        "vert_m": 50.0,
                        "distance_m": 500,
                        "avg_gradient_pct": 10.0,
                        "total_completions": 0,
                        "total_staked": 0,
                        "kom_holder": None,
                        "kom_time_s": 0,
                        "created_at": "2024-01-01T00:00:00Z",
                        "pda": "vault-pda-0",
                        "start_lat": 0.0,
                        "start_lon": -78.0,
                        "end_lat": 0.001,
                        "end_lon": -78.0,
                    }
                ]
            }
        )

        await vault_cache.load(mock_supabase)

        vault = vault_cache.get_vault(0)
        assert vault.start_lat == 0.0
        assert vault.start_lon == -78.0
        assert vault.end_lon == -78.0

    @pytest.mark.asyncio
    async def test_load_clears_existing_cache(self, vault_cache, sample_vaults):
        """Loading cache should clear existing entries."""
        # Pre-populate cache
        vault_cache._vaults[sample_vaults[0].id] = sample_vaults[0]
        vault_cache._vaults[sample_vaults[1].id] = sample_vaults[1]
        assert vault_cache.count == 2

        # Load from empty database
        mock_supabase, _query = mock_rest_pages({0: []})

        count = await vault_cache.load(mock_supabase)

        assert count == 0
        assert vault_cache.count == 0

    @pytest.mark.asyncio
    async def test_load_handles_database_error(self, vault_cache):
        """Load should handle database errors gracefully."""
        mock_supabase = MagicMock()
        query = mock_supabase.from_.return_value.select.return_value
        query.order.return_value = query
        query.range.return_value.execute.side_effect = Exception("Database error")

        count = await vault_cache.load(mock_supabase)

        assert count == 0
        # Cache should not be marked as loaded on error
        assert not vault_cache.is_loaded


class TestIndexedVault:
    """Tests for IndexedVault dataclass."""

    def test_signature_property(self, sample_vaults):
        """Signature property parses hex to ClimbSignature."""
        vault = sample_vaults[0]

        sig = vault.signature

        assert isinstance(sig, ClimbSignature)
        assert sig.vert_m == 500.0
        assert sig.avg_gradient_pct == 7.5
        assert sig.distance_m == 6666.0

    def test_vault_attributes(self, sample_vaults):
        """Verify all vault attributes are accessible."""
        vault = sample_vaults[1]

        assert vault.id == 1
        assert vault.minter == "minter-2"
        assert vault.name == "Alpe d'Huez"
        assert vault.vert_m == 1100.0
        assert vault.distance_m == 13800
        assert vault.avg_gradient_pct == 8.0
        assert vault.total_completions == 250
        assert vault.total_staked == 100000
        assert vault.kom_holder == "kom-holder-2"
        assert vault.kom_time_s == 3600
        assert vault.pda == "vault-pda-1"


class TestSignatureMatching:
    """Tests for signature similarity matching."""

    def test_find_matches_filters_by_similarity(self, vault_cache, sample_vaults):
        """Find matches should filter below threshold."""
        vault_cache._loaded = True
        for vault in sample_vaults:
            vault_cache._vaults[vault.id] = vault

        # Create mock user signature that returns controlled similarities
        mock_user_sig = MagicMock(spec=ClimbSignature)
        # When user_sig.similarity(vault_sig) is called, return different values
        mock_user_sig.similarity.side_effect = [0.95, 0.80]

        matches = vault_cache.find_matches(mock_user_sig, min_similarity=0.90)

        # Only first vault should match (0.95 >= 0.90)
        assert len(matches) == 1
        assert matches[0][0].id == 0
        assert matches[0][1] == 0.95

    def test_find_matches_sorts_by_similarity(self, vault_cache, sample_vaults):
        """Matches should be sorted by similarity descending."""
        vault_cache._loaded = True
        for vault in sample_vaults:
            vault_cache._vaults[vault.id] = vault

        mock_user_sig = MagicMock(spec=ClimbSignature)
        # Both match but with different similarities
        mock_user_sig.similarity.side_effect = [0.92, 0.98]

        matches = vault_cache.find_matches(mock_user_sig, min_similarity=0.90)

        assert len(matches) == 2
        # Higher similarity first
        assert matches[0][1] == 0.98
        assert matches[1][1] == 0.92
