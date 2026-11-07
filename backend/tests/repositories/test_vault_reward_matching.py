from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.repositories.vault import VaultRepository
from app.services.patterns.climb_signature import (
    AmbiguousRewardGradeVaultMatch,
    InvalidRewardGradeQuery,
    RewardGradeMatchEvidence,
    RewardGradeMatcherUnavailable,
)


V2_SIGNATURE_HEX = (
    "0208012901ef0258000000000000000062030000800000008000000000008000"
    "80008000000080008000800000008000e9105ad1a189212e4aaad7873984334a"
)
AUTHORITATIVE_ACTIVATION = {
    "activation_status": "active",
    "chain_activation_active": True,
    "chain_activation_seed_generation": 2,
}


@pytest.fixture(autouse=True)
def _stub_native_query_validation():
    with patch(
        "app.services.patterns.climb_signature.validate_reward_grade_v2_native"
    ):
        yield


class _CappedRestQuery:
    def __init__(self, rows):
        self.rows = rows
        self.requested_ranges = []
        self.current_range = None
        self.not_ = self

    def select(self, _columns):
        return self

    def gte(self, _column, _value):
        return self

    def eq(self, _column, _value):
        return self

    def lte(self, _column, _value):
        return self

    def is_(self, _column, _value):
        return self

    def order(self, _column):
        return self

    def range(self, start, end):
        self.current_range = (start, end)
        self.requested_ranges.append((start, end))
        return self

    def execute(self):
        start, end = self.current_range or (0, 999)
        return SimpleNamespace(data=self.rows[start:end + 1])


@pytest.mark.asyncio
async def test_reward_grade_vault_search_requires_v2_and_both_endpoints(monkeypatch):
    import app.repositories.vault as vault_module

    captured = {}

    async def fake_fetch(query, *args):
        captured["query"] = query
        captured["args"] = args
        return [
            {
                "id": 9,
                "name": "Near climb",
                "vert_m": 120.0,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                **AUTHORITATIVE_ACTIVATION,
            }
        ]

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", fake_fetch)
    repo = VaultRepository(MagicMock())
    evidence = RewardGradeMatchEvidence(
        result="match",
        similarity=0.99,
        confidence=0.8,
        dct_distance=0.01,
        start_distance_m=4.0,
        end_distance_m=6.0,
    )

    with patch(
        "app.services.patterns.climb_signature.match_reward_grade_v2",
        return_value=evidence,
    ) as matcher:
        matches = await repo.find_reward_grade_vault_matches(
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=39.9500,
            start_lon=-75.1600,
            end_lat=39.9550,
            end_lon=-75.1600,
            limit=3,
        )

    assert "signature_v2_hex IS NOT NULL" in captured["query"]
    assert "end_lat IS NOT NULL" in captured["query"]
    assert "vert_m >=" not in captured["query"]
    assert "JOIN indexed_vault_activations" in captured["query"]
    assert captured["args"] == (2,)
    assert [match["id"] for match in matches] == [9]
    assert matches[0]["_similarity"] == 0.99
    assert matches[0]["_match_evidence"]["end_distance_m"] == 6.0
    matcher.assert_called_once_with(
        query_signature_v2_hex=V2_SIGNATURE_HEX,
        candidate_signature_v2_hex=V2_SIGNATURE_HEX,
        query_start=(39.9500, -75.1600),
        query_end=(39.9550, -75.1600),
        candidate_start=(39.9500, -75.1600),
        candidate_end=(39.9550, -75.1600),
    )


@pytest.mark.asyncio
async def test_reward_grade_vault_search_propagates_missing_rust_matcher(monkeypatch):
    import app.repositories.vault as vault_module

    async def fake_fetch(_query, *_args):
        return [
            {
                "id": 9,
                "name": "Near climb",
                "vert_m": 120.0,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                **AUTHORITATIVE_ACTIVATION,
            }
        ]

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", fake_fetch)
    repo = VaultRepository(MagicMock())

    with patch(
        "app.services.patterns.climb_signature.match_reward_grade_v2",
        side_effect=RewardGradeMatcherUnavailable("workout_parse unavailable"),
    ):
        with pytest.raises(RewardGradeMatcherUnavailable, match="workout_parse"):
            await repo.find_reward_grade_vault_matches(
                signature_v2_hex=V2_SIGNATURE_HEX,
                start_lat=39.9500,
                start_lon=-75.1600,
                end_lat=39.9550,
                end_lon=-75.1600,
            )


@pytest.mark.asyncio
async def test_reward_grade_vault_search_classifies_invalid_query_geography(monkeypatch):
    import app.repositories.vault as vault_module

    async def no_candidates(_query, *_args):
        return []

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", no_candidates)
    repo = VaultRepository(MagicMock())

    with pytest.raises(InvalidRewardGradeQuery, match="no-fix"):
        await repo.find_reward_grade_vault_matches(
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=0.0,
            start_lon=0.0,
            end_lat=39.9550,
            end_lon=-75.1600,
        )


@pytest.mark.asyncio
async def test_reward_grade_vault_search_ignores_inactive_better_match(monkeypatch):
    import app.repositories.vault as vault_module

    async def fake_fetch(_query, *_args):
        return [
            {
                "id": 1,
                "name": "Inactive exact climb",
                "vert_m": 120.0,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                "activation_status": "pending",
            },
            {
                "id": 2,
                "name": "Active climb",
                "vert_m": 120.0,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                **AUTHORITATIVE_ACTIVATION,
            },
        ]

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", fake_fetch)
    repo = VaultRepository(MagicMock())
    evidence = RewardGradeMatchEvidence(
        result="match",
        similarity=1.0,
        confidence=1.0,
        dct_distance=0.0,
        start_distance_m=0.0,
        end_distance_m=0.0,
    )

    with patch(
        "app.services.patterns.climb_signature.match_reward_grade_v2",
        return_value=evidence,
    ):
        matches = await repo.find_reward_grade_vault_matches(
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=39.9500,
            start_lon=-75.1600,
            end_lat=39.9550,
            end_lon=-75.1600,
        )

    assert [match["id"] for match in matches] == [2]


@pytest.mark.asyncio
async def test_reward_grade_vault_search_propagates_corrupt_query(monkeypatch):
    import app.repositories.vault as vault_module

    async def fake_fetch(_query, *_args):
        return [
            {
                "id": 2,
                "name": "Active climb",
                "vert_m": 120.0,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                **AUTHORITATIVE_ACTIVATION,
            }
        ]

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", fake_fetch)
    repo = VaultRepository(MagicMock())

    with patch(
        "app.services.patterns.climb_signature.match_reward_grade_v2",
        side_effect=ValueError("query v2 signature checksum is invalid"),
    ):
        with pytest.raises(ValueError, match="query.*checksum"):
            await repo.find_reward_grade_vault_matches(
                signature_v2_hex=V2_SIGNATURE_HEX,
                start_lat=39.9500,
                start_lon=-75.1600,
                end_lat=39.9550,
                end_lon=-75.1600,
            )


@pytest.mark.asyncio
async def test_reward_grade_vault_search_abstains_on_two_active_matches(monkeypatch):
    import app.repositories.vault as vault_module

    async def fake_fetch(_query, *_args):
        return [
            {
                "id": vault_id,
                "name": f"Active climb {vault_id}",
                "vert_m": 120.0,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                **AUTHORITATIVE_ACTIVATION,
            }
            for vault_id in (2, 3)
        ]

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", fake_fetch)
    repo = VaultRepository(MagicMock())
    evidence = RewardGradeMatchEvidence(
        result="match",
        similarity=1.0,
        confidence=1.0,
        dct_distance=0.0,
        start_distance_m=0.0,
        end_distance_m=0.0,
    )

    with patch(
        "app.services.patterns.climb_signature.match_reward_grade_v2",
        return_value=evidence,
    ):
        with pytest.raises(AmbiguousRewardGradeVaultMatch):
            await repo.find_reward_grade_vault_matches(
                signature_v2_hex=V2_SIGNATURE_HEX,
                start_lat=39.9500,
                start_lon=-75.1600,
                end_lat=39.9550,
                end_lon=-75.1600,
            )


@pytest.mark.asyncio
async def test_reward_grade_rest_fallback_reads_active_match_after_page_one(monkeypatch):
    import app.repositories.vault as vault_module

    inactive_rows = [
        {
            "id": vault_id,
            "name": f"Inactive climb {vault_id}",
            "vert_m": 120.0,
            "signature_v2_hex": V2_SIGNATURE_HEX,
            "start_lat": 39.9500,
            "start_lon": -75.1600,
            "end_lat": 39.9550,
            "end_lon": -75.1600,
            "activation_status": "pending",
        }
        for vault_id in range(1, 1001)
    ]
    active = {
        **inactive_rows[0],
        "id": 1001,
        "name": "Active page-two climb",
        **AUTHORITATIVE_ACTIVATION,
    }
    query = _CappedRestQuery([*inactive_rows, active])
    activation_query = _CappedRestQuery(
        [{"vault_id": 1001, "is_active": True, "seed_generation": 2}]
    )
    client = MagicMock()
    client.from_.side_effect = lambda table: (
        activation_query if table == "indexed_vault_activations" else query
    )

    async def no_asyncpg(_query, *_args):
        return None

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", no_asyncpg)
    repo = VaultRepository(client)
    evidence = RewardGradeMatchEvidence(
        result="match",
        similarity=1.0,
        confidence=1.0,
        dct_distance=0.0,
        start_distance_m=0.0,
        end_distance_m=0.0,
    )

    with patch(
        "app.services.patterns.climb_signature.match_reward_grade_v2",
        return_value=evidence,
    ):
        matches = await repo.find_reward_grade_vault_matches(
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=39.9500,
            start_lon=-75.1600,
            end_lat=39.9550,
            end_lon=-75.1600,
        )

    assert [match["id"] for match in matches] == [1001]
    assert query.requested_ranges == [(0, 999), (1000, 1999)]
    assert activation_query.requested_ranges == [(0, 999)]


@pytest.mark.asyncio
async def test_reward_grade_query_is_native_validated_with_zero_candidates(monkeypatch):
    import app.repositories.vault as vault_module

    async def no_candidates(_query, *_args):
        return []

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", no_candidates)
    repo = VaultRepository(MagicMock())

    with patch(
        "app.services.patterns.climb_signature.validate_reward_grade_v2_native",
        side_effect=InvalidRewardGradeQuery("query v2 signature checksum is invalid"),
    ):
        with pytest.raises(InvalidRewardGradeQuery, match="query.*checksum"):
            await repo.find_reward_grade_vault_matches(
                signature_v2_hex=V2_SIGNATURE_HEX,
                start_lat=39.9500,
                start_lon=-75.1600,
                end_lat=39.9550,
                end_lon=-75.1600,
            )


@pytest.mark.asyncio
async def test_legacy_active_generation_cannot_authorize_reward_match(monkeypatch):
    import app.repositories.vault as vault_module

    async def fake_fetch(_query, *_args):
        return [
            {
                "id": 19,
                "name": "Legacy active climb",
                "vert_m": 120.0,
                "signature_v2_hex": V2_SIGNATURE_HEX,
                "start_lat": 39.9500,
                "start_lon": -75.1600,
                "end_lat": 39.9550,
                "end_lon": -75.1600,
                **AUTHORITATIVE_ACTIVATION,
                "chain_activation_active": True,
                "chain_activation_seed_generation": 1,
            }
        ]

    monkeypatch.setattr(vault_module, "_asyncpg_fetch", fake_fetch)
    repo = VaultRepository(MagicMock())
    evidence = RewardGradeMatchEvidence(
        result="match",
        similarity=1.0,
        confidence=1.0,
        dct_distance=0.0,
        start_distance_m=0.0,
        end_distance_m=0.0,
    )

    with patch(
        "app.services.patterns.climb_signature.match_reward_grade_v2",
        return_value=evidence,
    ):
        matches = await repo.find_reward_grade_vault_matches(
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=39.9500,
            start_lon=-75.1600,
            end_lat=39.9550,
            end_lon=-75.1600,
        )

    assert matches == []
