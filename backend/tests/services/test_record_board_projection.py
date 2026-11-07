from solders.pubkey import Pubkey

from app.services.record_board_projection import project_competition_entries


def test_wallet_fallback_uses_solana_raw_pubkey_order() -> None:
    raw_first = Pubkey.from_bytes(
        bytes.fromhex("00341eaf882fa09abe06880fd0c4a5bc7c57b63d9d3a0916de54a1499e14e4e6")
    )
    raw_second = Pubkey.from_bytes(
        bytes.fromhex("0079dd89640ca0e316e84b59ba660aea23e2305fa3c2734ab5cf1f7bdcd122e4")
    )
    assert str(raw_second) < str(raw_first)
    assert bytes(raw_first) < bytes(raw_second)

    projected = project_competition_entries(
        [
            {"user": str(raw_second), "time_s": 120, "recorded_at": 10},
            {"user": str(raw_first), "time_s": 120, "recorded_at": 10},
        ]
    )

    assert [entry["user"] for entry in projected] == [str(raw_first), str(raw_second)]
