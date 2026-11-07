"""
Tests for VaultRepository reads from chain-indexed tables.

Indexed tables (indexed_completions, indexed_leaderboards, indexed_stakes,
indexed_legends) are the only read source. These tests verify:
1. Queries go to the correct indexed tables
2. Schema mapping to legacy API shape works correctly
3. Empty/missing data is handled gracefully

Note: asyncpg helpers are patched to return None so the Supabase REST
fallback path is exercised (the mock client asserts table access).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.repositories.vault import VaultRepository


# Disable asyncpg for all tests in this module so the REST fallback
# path (which uses the mock Supabase client) is always exercised.
@pytest.fixture(autouse=True)
def _disable_asyncpg(monkeypatch):
    """Force all asyncpg helpers to return None so REST fallback is tested."""
    import app.repositories.vault as vault_mod

    async def _noop_fetch(query, *args):
        return None

    async def _noop_fetchrow(query, *args):
        return None

    async def _noop_fetchval(query, *args):
        return None

    monkeypatch.setattr(vault_mod, "_asyncpg_fetch", _noop_fetch)
    monkeypatch.setattr(vault_mod, "_asyncpg_fetchrow", _noop_fetchrow)
    monkeypatch.setattr(vault_mod, "_asyncpg_fetchval", _noop_fetchval)


def _make_builder():
    """Create a chainable query builder mock."""
    builder = MagicMock()
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.gt.return_value = builder
    builder.gte.return_value = builder
    builder.lte.return_value = builder
    builder.is_.return_value = builder
    builder.not_ = MagicMock()
    builder.not_.is_.return_value = builder
    builder.order.return_value = builder
    builder.limit.return_value = builder
    builder.range.return_value = builder
    builder.in_.return_value = builder
    builder.ilike.return_value = builder
    builder.insert.return_value = builder

    # Default execute returns empty
    result = MagicMock()
    result.data = []
    result.count = 0
    builder.execute.return_value = result
    return builder


def _mock_client():
    """Create a mock Supabase client that returns stable per-table builders."""
    client = MagicMock()
    _table_builders = {}

    def _get_builder(table_name):
        if table_name not in _table_builders:
            _table_builders[table_name] = _make_builder()
        return _table_builders[table_name]

    client.from_ = MagicMock(side_effect=_get_builder)
    client.table = MagicMock(side_effect=_get_builder)
    client._table_builders = _table_builders
    return client


def _set_table_data(client, table_name, data):
    """Configure what data a table returns from execute()."""
    builder = client.from_(table_name)
    result = MagicMock()
    result.data = data
    result.count = len(data) if data else 0
    builder.execute.return_value = result


class TestConfirmedVaultCreationHandoff:
    """Confirmed creates stage metadata without creating a chain projection."""

    @pytest.mark.asyncio
    async def test_handoff_never_writes_indexed_vaults(self):
        client = _mock_client()
        rpc_result = MagicMock()
        rpc_result.data = [{
            "job_id": "7c6e43b7-e194-4ef6-b3d2-ea33570a3f79",
            "projection_ready": False,
            "chain_slot": None,
        }]
        client.rpc.return_value.execute.return_value = rpc_result
        repo = VaultRepository(client)

        result = await repo.stage_confirmed_vault_creation(
            vault_id=17,
            signature_hex="aa" * 64,
            signature_hash_hex="bb" * 32,
            pda="vault-pda",
            signature_v2_hex="cc" * 64,
            start_lat=39.95,
            start_lon=-75.16,
            end_lat=39.96,
            end_lon=-75.15,
            creator_wallet="rider-wallet",
            create_tx_signature="create-tx-17",
            source_climb_id="1c4ac5c5-7e39-41cf-b70d-965df0208471",
            operation_id="br-op-vault-17",
        )

        assert result == {
            "job_id": "7c6e43b7-e194-4ef6-b3d2-ea33570a3f79",
            "projection_ready": False,
            "chain_slot": None,
        }
        assert "indexed_vaults" not in client._table_builders
        client.rpc.assert_called_once_with(
            "stage_confirmed_vault_creation",
            {
                "p_vault_id": 17,
                "p_vault_pda": "vault-pda",
                "p_signature_hex": "aa" * 64,
                "p_signature_hash_hex": "bb" * 32,
                "p_signature_v2_hex": "cc" * 64,
                "p_start_lat": 39.95,
                "p_start_lon": -75.16,
                "p_end_lat": 39.96,
                "p_end_lon": -75.15,
                "p_creator_wallet": "rider-wallet",
                "p_create_tx_signature": "create-tx-17",
                "p_source_climb_id": "1c4ac5c5-7e39-41cf-b70d-965df0208471",
                "p_operation_id": "br-op-vault-17",
                "p_priority": 100,
            },
        )


class TestIndexedPath:
    """Test that read paths query indexed tables."""

    def _repo_with_vault(self, vault_id=1, vault_signature="aabb" * 32):
        """Create a repo mock where get_vault_by_signature returns a vault."""
        client = _mock_client()
        repo = VaultRepository(client)

        vault_data = {
            "id": vault_id,
            "signature_hex": vault_signature,
            "name": "Test Vault",
            "staker_count": 5,
        }

        async def _get_vault(sig):
            return vault_data

        repo.get_vault_by_signature = _get_vault
        return repo, client

    @pytest.mark.asyncio
    async def test_get_completions_for_wallet_uses_indexed(self):
        """Queries indexed_completions by user_pubkey."""
        repo, client = self._repo_with_vault()
        await repo.get_completions_for_wallet("wallet123")
        client.from_.assert_any_call("indexed_completions")

    @pytest.mark.asyncio
    async def test_get_vault_leaderboard_uses_indexed(self):
        """Queries indexed_leaderboards and maps entries."""
        repo, client = self._repo_with_vault()

        _set_table_data(client, "indexed_leaderboards", [{
            "entries": [
                {"user": "fast_rider", "time_s": 120, "recorded_at": 1700000000},
                {"user": "second_rider", "time_s": 150, "recorded_at": 1700000100},
            ]
        }])

        leaderboard = await repo.get_vault_leaderboard("aabb" * 32)
        assert len(leaderboard) == 2
        assert leaderboard[0]["rank"] == 1
        assert leaderboard[0]["wallet"] == "fast_rider"
        assert leaderboard[0]["best_time_seconds"] == 120
        assert leaderboard[1]["rank"] == 2
        assert leaderboard[1]["wallet"] == "second_rider"

    @pytest.mark.asyncio
    async def test_get_vault_leaderboard_derives_standard_competition_ties(self):
        """Legacy raw index rows still project pooled-tie ranks deterministically."""
        repo, client = self._repo_with_vault()

        _set_table_data(client, "indexed_leaderboards", [{
            "entries": [
                {"user": "first", "time_s": 100, "recorded_at": 1700000000},
                {"user": "tied_a", "time_s": 120, "recorded_at": 1700000100},
                {"user": "tied_b", "time_s": 120, "recorded_at": 1700000200},
                {"user": "fourth", "time_s": 140, "recorded_at": 1700000300},
            ]
        }])

        leaderboard = await repo.get_vault_leaderboard("aabb" * 32)

        assert [entry["rank"] for entry in leaderboard] == [1, 2, 3, 4]
        assert [entry["competition_rank"] for entry in leaderboard] == [1, 2, 2, 4]
        assert [entry["position"] for entry in leaderboard] == [1, 2, 3, 4]
        assert [entry["tie_size"] for entry in leaderboard] == [1, 2, 2, 1]
        assert [entry["is_tied"] for entry in leaderboard] == [False, True, True, False]

    @pytest.mark.asyncio
    async def test_get_vault_leaderboard_empty(self):
        """Returns empty list when no leaderboard data."""
        repo, client = self._repo_with_vault()
        leaderboard = await repo.get_vault_leaderboard("aabb" * 32)
        assert leaderboard == []

    @pytest.mark.asyncio
    async def test_get_vault_stakes_uses_indexed(self):
        """Queries indexed_stakes."""
        repo, client = self._repo_with_vault()
        await repo.get_vault_stakes("aabb" * 32)
        client.from_.assert_any_call("indexed_stakes")

    @pytest.mark.asyncio
    async def test_get_vault_stakes_maps_schema(self):
        """Maps indexed_stakes schema to VaultStakeDict shape."""
        repo, client = self._repo_with_vault()

        _set_table_data(client, "indexed_stakes", [{
            "user_pubkey": "staker_wallet",
            "vault_id": 1,
            "cal_staked": 1000,
            "lp_tokens": 1000,
            "staked_at": 1700000000,
        }])

        stakes = await repo.get_vault_stakes("aabb" * 32)
        assert len(stakes) == 1
        s = stakes[0]
        assert s["wallet"] == "staker_wallet"
        assert s["cal_staked"] == 1000
        assert s["lp_tokens"] == 1000
        assert s["unstaked_at"] is None

    @pytest.mark.asyncio
    async def test_get_wallet_stakes_uses_indexed(self):
        """Queries indexed_stakes by user_pubkey."""
        repo, client = self._repo_with_vault()
        await repo.get_wallet_stakes("wallet123")
        client.from_.assert_any_call("indexed_stakes")

    @pytest.mark.asyncio
    async def test_get_wallet_stakes_projects_vault_signature_for_api_contract(self):
        """Wallet positions include the Vault signature required by MyStakesResponse."""
        repo, client = self._repo_with_vault()
        vault_signature = "aabb" * 32
        _set_table_data(client, "indexed_stakes", [{
            "user_pubkey": "wallet123",
            "vault_id": 1,
            "cal_staked": 500,
            "lp_tokens": 500,
            "staked_at": 1700000000,
        }])
        _set_table_data(client, "indexed_vaults", [{
            "id": 1,
            "signature_hex": vault_signature,
        }])

        stakes = await repo.get_wallet_stakes("wallet123")

        assert stakes[0]["vault_signature"] == vault_signature
        client.from_.assert_any_call("indexed_vaults")

    @pytest.mark.asyncio
    async def test_get_wallet_stakes_carries_vault_and_climb_identity(self):
        """Stake rows carry vault id, name, and canon climb id so clients can
        join positions to vault/climb objects without signature heuristics
        (boulderroller-v2-71o2v)."""
        repo, client = self._repo_with_vault()
        vault_signature = "aabb" * 32
        _set_table_data(client, "indexed_stakes", [{
            "user_pubkey": "wallet123",
            "vault_id": 7,
            "cal_staked": 500,
            "lp_tokens": 500,
            "staked_at": 1700000000,
        }])
        _set_table_data(client, "indexed_vaults", [{
            "id": 7,
            "signature_hex": vault_signature,
            "name": "Manayunk Wall",
            "canon_climb_id": "33333333-3333-3333-3333-333333333333",
        }])

        stakes = await repo.get_wallet_stakes("wallet123")

        assert stakes[0]["vault_id"] == 7
        assert stakes[0]["vault_name"] == "Manayunk Wall"
        assert stakes[0]["climb_id"] == "33333333-3333-3333-3333-333333333333"

    def test_stake_info_route_model_exposes_vault_and_climb_identity(self):
        from app.routes.vaults import _build_vault_stake_info

        info = _build_vault_stake_info({
            "id": "wallet123:7",
            "vault_signature": "aabb" * 32,
            "vault_id": 7,
            "vault_name": "Manayunk Wall",
            "climb_id": "33333333-3333-3333-3333-333333333333",
            "wallet": "wallet123",
            "cal_staked": 500,
            "lp_tokens": 500,
            "staked_at": "2026-08-01T12:00:00",
        })

        assert info.vault_id == 7
        assert info.vault_name == "Manayunk Wall"
        assert info.climb_id == "33333333-3333-3333-3333-333333333333"

        legacy = _build_vault_stake_info({
            "vault_signature": "aabb" * 32,
            "wallet": "wallet123",
            "cal_staked": 500,
            "lp_tokens": 500,
        })
        assert legacy.vault_id is None
        assert legacy.vault_name is None
        assert legacy.climb_id is None

    @pytest.mark.asyncio
    async def test_get_wallet_stakes_direct_postgres_joins_indexed_vaults(self, monkeypatch):
        """The direct Postgres path projects the same Vault signature contract."""
        import app.repositories.vault as vault_mod

        captured_query = ""

        async def _joined_stakes(query, *args):
            nonlocal captured_query
            captured_query = query
            return [{
                "user_pubkey": args[0],
                "vault_id": 1,
                "vault_signature": "aabb" * 32,
                "cal_staked": 500,
                "lp_tokens": 500,
                "staked_at": 1700000000,
            }]

        monkeypatch.setattr(vault_mod, "_asyncpg_fetch", _joined_stakes)
        repo, client = self._repo_with_vault()

        stakes = await repo.get_wallet_stakes("wallet123")

        assert "JOIN indexed_vaults AS vault ON vault.id = stake.vault_id" in captured_query
        assert stakes[0]["vault_signature"] == "aabb" * 32
        client.from_.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_wallet_stake_uses_indexed(self):
        """Queries indexed_stakes for single wallet+vault."""
        repo, client = self._repo_with_vault()

        _set_table_data(client, "indexed_stakes", [{
            "user_pubkey": "wallet123",
            "vault_id": 1,
            "cal_staked": 500,
            "lp_tokens": 500,
            "staked_at": 1700000000,
        }])

        stake = await repo.get_wallet_stake("aabb" * 32, "wallet123")
        assert stake is not None
        assert stake["wallet"] == "wallet123"
        assert stake["cal_staked"] == 500

    @pytest.mark.asyncio
    async def test_zero_principal_lp_position_remains_active_across_reads(self):
        """Redeemable LP, not rounded principal, defines a current position."""
        repo, client = self._repo_with_vault()
        _set_table_data(client, "indexed_stakes", [{
            "user_pubkey": "dust_wallet",
            "vault_id": 1,
            "cal_staked": "0",
            "lp_tokens": "2",
            "staked_at": 1700000000,
        }])
        builder = client.from_("indexed_stakes")

        vault_stakes = await repo.get_vault_stakes("aabb" * 32)
        assert [stake["lp_tokens"] for stake in vault_stakes] == ["2"]
        builder.gt.assert_called_with("lp_tokens", 0)

        builder.gt.reset_mock()
        wallet_stake = await repo.get_wallet_stake("aabb" * 32, "dust_wallet")
        assert wallet_stake is not None
        assert wallet_stake["lp_tokens"] == "2"
        builder.gt.assert_called_with("lp_tokens", 0)

        builder.gt.reset_mock()
        _set_table_data(client, "indexed_vaults", [{
            "id": 1,
            "signature_hex": "aabb" * 32,
        }])
        wallet_stakes = await repo.get_wallet_stakes("dust_wallet")
        assert [stake["lp_tokens"] for stake in wallet_stakes] == ["2"]
        builder.gt.assert_called_with("lp_tokens", 0)

    @pytest.mark.asyncio
    async def test_get_unique_staker_count_from_vault(self):
        """Reads staker_count from indexed_vaults."""
        repo, _ = self._repo_with_vault()
        count = await repo.get_unique_staker_count("aabb" * 32)
        assert count == 5  # Set in _repo_with_vault fixture

    @pytest.mark.asyncio
    async def test_get_local_legend_uses_indexed(self):
        """Queries indexed_legends."""
        repo, client = self._repo_with_vault()

        _set_table_data(client, "indexed_legends", [{
            "vault_id": 1,
            "holder": "legend_wallet",
            "term_start_epoch": 100,
            "term_end_epoch": 108,
            "term_start_at": "2025-12-01T12:00:00+00:00",
            "term_end_at": "2026-01-26T12:00:00+00:00",
            "completions_at_election": 50,
            "is_active": True,
        }])

        legend = await repo.get_local_legend("aabb" * 32)
        assert legend is not None
        assert legend["wallet"] == "legend_wallet"
        assert legend["vault_signature"] == "aabb" * 32
        assert legend["completions_count"] == 50
        assert legend["elected_at"] == "2025-12-01T12:00:00+00:00"
        assert legend["term_ends_at"] == "2026-01-26T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_get_local_legend_none_when_inactive(self):
        """Returns None when no active legend."""
        repo, client = self._repo_with_vault()
        legend = await repo.get_local_legend("aabb" * 32)
        assert legend is None

    @pytest.mark.asyncio
    async def test_get_vault_total_stake_uses_indexed(self):
        """Queries indexed_stakes and aggregates."""
        repo, client = self._repo_with_vault()

        _set_table_data(client, "indexed_stakes", [
            {"vault_id": 1, "cal_staked": 500, "lp_tokens": 500},
            {"vault_id": 1, "cal_staked": 300, "lp_tokens": 300},
        ])

        total = await repo.get_vault_total_stake("aabb" * 32)
        assert total["total_cal_staked"] == 800
        assert total["total_lp_tokens"] == 800

    @pytest.mark.asyncio
    async def test_get_vault_stake_totals_batches_exact_active_positions(self):
        client = _mock_client()
        repo = VaultRepository(client)
        _set_table_data(client, "indexed_stakes", [
            {
                "vault_id": 1,
                "cal_staked": "9007199254740993",
                "lp_tokens": "9007199254740993",
            },
            {
                "vault_id": 1,
                "cal_staked": "7",
                "lp_tokens": "5",
            },
            {
                "vault_id": 2,
                "cal_staked": "1250000000000",
                "lp_tokens": "1000000000000",
            },
            {
                "vault_id": 2,
                "cal_staked": "0",
                "lp_tokens": "9999999999999",
            },
        ])

        totals = await repo.get_vault_stake_totals([1, 2, 3])

        assert totals[1]["total_cal_staked"] == 9_007_199_254_741_000
        assert totals[1]["total_lp_tokens"] == 9_007_199_254_740_998
        assert totals[2]["total_cal_staked"] == 1_250_000_000_000
        assert totals[2]["total_lp_tokens"] == 10_999_999_999_999
        assert totals[3]["total_cal_staked"] == 0

    @pytest.mark.asyncio
    async def test_get_vault_stake_totals_pages_rest_fallback(self):
        client = _mock_client()
        builder = client.from_("indexed_stakes")

        first_page = MagicMock()
        first_page.data = [
            {"vault_id": 1, "cal_staked": "1", "lp_tokens": "2"}
            for _ in range(1000)
        ]
        final_page = MagicMock()
        final_page.data = [
            {"vault_id": 1, "cal_staked": "7", "lp_tokens": "11"}
        ]
        builder.execute.side_effect = [first_page, final_page]

        totals = await VaultRepository(client).get_vault_stake_totals([1])

        assert totals[1]["total_cal_staked"] == 1007
        assert totals[1]["total_lp_tokens"] == 2011
        assert builder.range.call_args_list == [
            ((0, 999),),
            ((1000, 1999),),
        ]

    @pytest.mark.asyncio
    async def test_batched_stake_total_accepts_full_u64_numeric_aggregate(self, monkeypatch):
        import app.repositories.vault as vault_mod

        async def _numeric_aggregate(_query, *_args):
            return [
                {
                    "vault_id": 1,
                    "total_cal": Decimal("18446744073709551615"),
                    "total_lp": Decimal("18446744073709551615"),
                }
            ]

        monkeypatch.setattr(vault_mod, "_asyncpg_fetch", _numeric_aggregate)
        repo = VaultRepository(_mock_client())

        totals = await repo.get_vault_stake_totals([1])

        assert totals[1]["total_cal_staked"] == 18_446_744_073_709_551_615
        assert totals[1]["total_lp_tokens"] == 18_446_744_073_709_551_615

    @pytest.mark.asyncio
    async def test_batched_stake_total_sql_keys_active_inventory_to_lp(self, monkeypatch):
        import app.repositories.vault as vault_mod

        queries = []

        async def _capture_query(query, *_args):
            queries.append(query)
            return [{"vault_id": 1, "total_cal": 0, "total_lp": 2}]

        monkeypatch.setattr(vault_mod, "_asyncpg_fetch", _capture_query)

        totals = await VaultRepository(_mock_client()).get_vault_stake_totals([1])

        assert totals[1] == {"total_cal_staked": 0, "total_lp_tokens": 2}
        assert len(queries) == 1
        assert "lp_tokens > 0" in queries[0]
        assert "cal_staked > 0" not in queries[0]

    @pytest.mark.asyncio
    async def test_vault_not_found_returns_empty(self):
        """When vault is not found, methods return empty/zero/None."""
        client = _mock_client()
        repo = VaultRepository(client)

        async def _no_vault(sig):
            return None

        repo.get_vault_by_signature = _no_vault

        assert await repo.get_vault_leaderboard("dead" * 32) == []
        assert await repo.get_vault_stakes("dead" * 32) == []
        assert await repo.get_wallet_stake("dead" * 32, "w") is None
        assert await repo.get_unique_staker_count("dead" * 32) == 0
        assert await repo.get_local_legend("dead" * 32) is None
        total = await repo.get_vault_total_stake("dead" * 32)
        assert total["total_cal_staked"] == 0


class TestEffortHistoryIndexed:
    """Test effort history with indexed tables."""

    @pytest.mark.asyncio
    async def test_effort_history_returns_summary(self):
        """Returns single best-time summary instead of per-effort detail."""
        client = _mock_client()
        repo = VaultRepository(client)

        vault_data = {"id": 1, "signature_hex": "aabb" * 32, "name": "Test"}

        async def _get_vault(sig):
            return vault_data

        repo.get_vault_by_signature = _get_vault

        _set_table_data(client, "indexed_completions", [{
            "best_time_s": 245,
            "completions": 12,
            "last_completed_at": 1700000000,
        }])

        efforts = await repo.get_user_vault_effort_history(
            "aabb" * 32, "wallet123"
        )
        assert len(efforts) == 1
        assert efforts[0]["timeSeconds"] == 245
        assert efforts[0]["isPR"] is True

    @pytest.mark.asyncio
    async def test_effort_history_empty_when_no_data(self):
        """Returns empty when user has no completions."""
        client = _mock_client()
        repo = VaultRepository(client)

        vault_data = {"id": 1, "signature_hex": "aabb" * 32, "name": "Test"}

        async def _get_vault(sig):
            return vault_data

        repo.get_vault_by_signature = _get_vault

        efforts = await repo.get_user_vault_effort_history(
            "aabb" * 32, "wallet123"
        )
        assert efforts == []
