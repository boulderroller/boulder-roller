import pytest

from app.client_contracts import TruthSource
from app.routes.vaults import _enrich_leaderboard_public_identity, _vault_record_board_response


class FakeUserRepo:
    async def get_public_user_identity(self, wallet: str):
        if wallet == "public-wallet":
            return {
                "id": "user-1",
                "wallet": wallet,
                "username": "tim",
                "display_name": "Tim Trail",
                "avatar_url": "https://example.test/tim.png",
                "is_public": True,
            }
        if wallet == "private-wallet":
            return {
                "id": "user-2",
                "wallet": wallet,
                "username": "private",
                "display_name": "Private Rider",
                "avatar_url": None,
                "is_public": False,
            }
        return None


@pytest.mark.asyncio
async def test_enrich_leaderboard_public_identity_attaches_public_profile_fields():
    rows = [
        {"rank": 1, "wallet": "public-wallet", "best_time_seconds": 590, "avg_power_w": 321},
        {"rank": 2, "wallet": "private-wallet", "best_time_seconds": 610, "avg_power_w": 300},
        {"rank": 3, "wallet": "unknown-wallet", "best_time_seconds": 628, "avg_power_w": 287},
    ]
    original_rows = [dict(row) for row in rows]

    enriched = await _enrich_leaderboard_public_identity(rows, FakeUserRepo())

    assert rows == original_rows
    assert enriched[0] is not rows[0]
    assert enriched[0]["username"] == "tim"
    assert enriched[0]["display_name"] == "Tim Trail"
    assert "username" not in rows[0]
    assert enriched[0]["avatar_url"] == "https://example.test/tim.png"
    assert enriched[0]["user_id"] == "user-1"
    assert enriched[0]["rank"] == 1
    assert enriched[0]["wallet"] == "public-wallet"
    assert enriched[0]["best_time_seconds"] == 590
    assert enriched[0]["avg_power_w"] == 321

    assert "username" not in enriched[1]
    assert "display_name" not in enriched[1]
    assert "avatar_url" not in enriched[1]
    assert "user_id" not in enriched[1]
    assert "username" not in enriched[2]
    assert "display_name" not in enriched[2]
    assert "avatar_url" not in enriched[2]
    assert "user_id" not in enriched[2]


def test_vault_record_board_response_keeps_profile_metadata_display_only():
    vault = {
        "name": "Hollow Woods",
        "signature_hex": "vault-signature",
        "kom_holder": "public-wallet",
        "kom_time_s": 590,
    }
    leaderboard = [
        {
            "rank": 2,
            "wallet": "public-wallet",
            "best_time_seconds": 590,
            "avg_power_w": 321,
            "completion_id": "completion-1",
            "achieved_at": "2026-05-13T18:00:00Z",
            "username": "tim",
            "display_name": "Tim Trail",
            "avatar_url": "https://example.test/tim.png",
            "user_id": "user-1",
        }
    ]
    original_row = dict(leaderboard[0])

    board = _vault_record_board_response(42, vault, leaderboard)
    entry = board.entries[0]

    assert leaderboard[0] == original_row
    assert board.truth_source == TruthSource.projected
    assert board.climb_id == "42"
    assert board.climb_name == "Hollow Woods"
    assert board.vault_id == 42
    assert board.kom_holder == "public-wallet"
    assert board.kom_time_s == 590
    assert board.leaderboard == board.entries

    assert entry.rank == 2
    assert entry.wallet == "public-wallet"
    assert entry.best_time_seconds == 590
    assert entry.avg_power_w == 321
    assert entry.completion_id == "completion-1"
    assert entry.vault_signature == "vault-signature"
    assert entry.username == "tim"
    assert entry.display_name == "Tim Trail"
    assert entry.avatar_url == "https://example.test/tim.png"
    assert entry.user_id == "user-1"
