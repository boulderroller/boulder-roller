"""Paged reads stay complete through the pinned postgrest-py client.

Each read runs through the real client, whose ``range()`` is end-exclusive and
whose chained ``order()`` calls PostgREST reduces to the first, against the
in-memory PostgREST in tests.pinned_postgrest. Before the fix, every one of
these reads stopped after a short first page.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from tests.pinned_postgrest import PinnedPostgrest


def _at(seconds: int) -> str:
    return (datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds)).isoformat()


@pytest.mark.asyncio
async def test_training_read_returns_every_counted_ride():
    from app.repositories.ride import RideRepository
    from app.services.training_eligibility import COUNTED_STATUSES

    user_id = str(UUID(int=7))
    status = sorted(COUNTED_STATUSES)[0]
    # Pairs share a start time, so only the id tie-breaker orders the pages.
    rides = [{"id": str(UUID(int=10_000 + i)), "user_id": user_id,
              "processing_status": status, "started_at": _at(i // 2 * 60)}
             for i in range(1500)]
    server = PinnedPostgrest({"rides": rides})

    rows = await RideRepository(server.client).list_threshold_training_rides(user_id)

    assert len(rows) == 1500
    assert {row["id"] for row in rows} == {ride["id"] for ride in rides}


@pytest.mark.asyncio
async def test_ride_log_pages_hold_exactly_the_requested_rides():
    from app.repositories.ride import RideRepository

    user_id = str(UUID(int=8))
    rides = [{"id": str(UUID(int=20_000 + i)), "user_id": user_id, "started_at": _at(i * 60)}
             for i in range(250)]
    repo = RideRepository(PinnedPostgrest({"rides": rides}).client)

    # The portal and iOS stop paging on a page shorter than its limit.
    pages = [await repo.list_rides_for_user(user_id, limit=100, offset=offset)
             for offset in (0, 100, 200)]

    assert [len(page) for page in pages] == [100, 100, 50]
    assert len({row["id"] for page in pages for row in page}) == 250


def test_vault_seed_material_includes_every_validated_completion():
    from solders.keypair import Keypair
    from solders.pubkey import Pubkey

    from app.services.vault_activation_service import VaultActivationService

    wallet = str(Keypair().pubkey())
    completions = [{"id": f"completion-{i:05d}", "vault_signature": "sig", "validated": True,
                    "wallet": wallet, "activity_id": str(UUID(int=i + 1)),
                    "time_seconds": 300 + i % 50, "completed_at": _at(i // 3)}
                   for i in range(1500)]
    server = PinnedPostgrest({"vault_completions": completions})
    service = VaultActivationService(server.client, Keypair(), None, Pubkey.default())

    seeds = service._get_seed_completions("sig")

    assert len(seeds) == 1500
    assert {seed.activity_id for seed in seeds} == {row["activity_id"] for row in completions}


@pytest.mark.asyncio
async def test_territory_reads_every_tile_and_keeps_its_limit():
    from app.repositories.territory import TerritoryRepository

    tiles = [{"wallet": "w", "tile_id": f"tile-{i:05d}", "visit_count": i % 7,
              "first_visited_at": _at(i), "last_visited_at": _at(i)} for i in range(2500)]
    repo = TerritoryRepository(PinnedPostgrest({"wallet_tile_history": tiles}).client)

    assert len({row["tile_id"] for row in await repo.get_user_tiles("w")}) == 2500
    assert len(await repo.get_user_tiles("w", limit=1)) == 1
    top = await repo.get_user_tiles("w", limit=1001)
    assert len({row["tile_id"] for row in top}) == 1001
    assert [row["visit_count"] for row in top] == sorted((row["visit_count"] for row in top), reverse=True)


def test_reward_identity_reconciliation_reads_every_vault_and_keeps_its_limit(monkeypatch):
    from app.services import vault_reward_identity

    vaults = [{"id": i, "signature_hex": f"{i:064x}"} for i in range(1, 1501)]
    server = PinnedPostgrest({"indexed_vaults": vaults})
    seen = []
    monkeypatch.setattr(vault_reward_identity, "reconcile_indexed_vault_reward_identity",
                        lambda *, client, vault, apply: seen.append(vault["id"]))

    report = vault_reward_identity.reconcile_vault_reward_identities(client=server.client, apply=False)
    assert report.scanned == 1500 and sorted(seen) == list(range(1, 1501))

    for limit in (1, 5, 1001):
        seen.clear()
        report = vault_reward_identity.reconcile_vault_reward_identities(
            client=server.client, apply=False, limit=limit,
        )
        assert report.scanned == limit and seen == list(range(1, limit + 1))


@pytest.mark.asyncio
async def test_ridden_climbs_count_every_confirmed_attempt():
    from app.repositories.vault import VaultRepository

    completions = [{"id": f"completion-{i:05d}", "wallet": "w", "vault_signature": "sig",
                    "validated": True, "chain_confirmation_status": "confirmed",
                    "time_seconds": 500 if i == 1199 else 600, "completed_at": _at(i // 2)}
                   for i in range(1200)]
    server = PinnedPostgrest({
        "vault_completions": completions,
        "indexed_vaults": [{"id": 1, "name": "Test Hill", "signature_hex": "sig",
                            "canon_climb_id": None, "canon_binding_status": None}],
    })

    climbs = await VaultRepository(server.client).get_user_ridden_climbs("w")

    assert [(climb["attempts"], climb["best_time_seconds"]) for climb in climbs] == [(1200, 500)]


def test_page_cursor_ends_every_read_whatever_the_server_returns():
    from unittest.mock import MagicMock

    from app.utils.postgrest_paging import MAX_PAGES, PageCursor, PagingRunaway

    # Full pages: size - 1 rows from the pinned client, size from newer ones.
    cursor = PageCursor(1000)
    assert cursor.advance([{}] * 999) and cursor.advance([{}] * 1000)
    assert cursor.offset == 1999
    # A shorter page, an empty one, or a mocked response without rows ends it.
    assert not cursor.advance([{}] * 998)
    assert not PageCursor(1000).advance([])
    assert not PageCursor(1000).advance(MagicMock())
    # A server that ignores the window returns full pages forever; the read
    # raises at its bound instead of growing without one.
    runaway = PageCursor(500)
    with pytest.raises(PagingRunaway):
        while runaway.advance([{}] * 500):
            pass
    assert runaway.pages == MAX_PAGES
