from solders.pubkey import Pubkey

from app.services.vault_activation_service import SeedCompletion, VaultActivationService


def _completion(index: int, *, rider_byte: int, time_s: int, completed_at: int):
    return SeedCompletion(
        wallet=f"wallet-{rider_byte}",
        user_pubkey=Pubkey.from_bytes(bytes([rider_byte]) * 32),
        activity_id=f"ride-{index}",
        completed_at=completed_at,
        time_s=time_s,
    )


def test_historical_seed_tie_at_cutoff_is_not_upload_order_dependent():
    completions = [
        _completion(i, rider_byte=i, time_s=i, completed_at=i)
        for i in range(1, 10)
    ]
    # The later ride is supplied first. Original ride time, not processing
    # order, decides bounded-seat membership for an otherwise equal effort.
    completions.extend([
        _completion(10, rider_byte=10, time_s=10, completed_at=11),
        _completion(11, rider_byte=20, time_s=10, completed_at=10),
    ])

    entries = VaultActivationService._leaderboard_entries_from_seed(completions)

    assert len(entries) == 10
    assert entries[-1][0] == Pubkey.from_bytes(bytes([20]) * 32)
