from __future__ import annotations

from app.scan_contracts import (
    ScanState,
    ScanTargetType,
    boulderscan_url,
    scan_targets_for_climb,
    scan_targets_for_profile,
    scan_targets_for_protocol,
    scan_targets_for_ride,
)


def test_boulderscan_url_builders_are_centralized() -> None:
    assert boulderscan_url(ScanTargetType.transaction, "sig").endswith("/tx/sig")
    assert boulderscan_url(ScanTargetType.account, "acct").endswith("/account/acct")
    assert boulderscan_url(ScanTargetType.vault, "42").endswith("/vault/42")
    assert boulderscan_url(ScanTargetType.proof, "proof").endswith("/proof/proof")


def test_ride_scan_targets_cover_finalized_pending_failed_private_and_off_chain() -> None:
    finalized_state, finalized_targets = scan_targets_for_ride(
        {
            "ride_attestation_tx_signature": "tx-1",
            "ride_attestation_pda": "pda-1",
            "attestation_commitment_hex": "proof-1",
            "finalized_at": "2026-04-30T12:00:00+00:00",
            "processing_status": "completed",
        },
        can_view=True,
    )
    pending_state, pending_targets = scan_targets_for_ride({"processing_status": "processing"}, can_view=True)
    failed_state, failed_targets = scan_targets_for_ride({"processing_status": "failed"}, can_view=True)
    private_state, private_targets = scan_targets_for_ride({"ride_attestation_tx_signature": "tx-1"}, can_view=False)
    off_chain_state, off_chain_targets = scan_targets_for_ride({"processing_status": "completed"}, can_view=True)

    assert finalized_state == ScanState.finalized
    assert [target["type"] for target in finalized_targets] == ["transaction", "account", "proof"]
    assert pending_state == ScanState.pending
    assert pending_targets == []
    assert failed_state == ScanState.failed
    assert failed_targets == []
    assert private_state == ScanState.private
    assert private_targets == []
    assert off_chain_state == ScanState.off_chain_only
    assert off_chain_targets == []


def test_climb_profile_and_protocol_scan_targets() -> None:
    profile_state, profile_targets = scan_targets_for_profile({"wallet": "wallet-1"})
    climb_state, climb_targets = scan_targets_for_climb({"id": 12, "signature_hex": "vaultsig"})
    canonical_state, canonical_targets = scan_targets_for_climb({
        "id": "11111111-1111-1111-1111-111111111111",
        "signature_hex": "vaultsig",
    })
    enriched_state, enriched_targets = scan_targets_for_climb({
        "id": "11111111-1111-1111-1111-111111111111",
        "vault_id": 42,
        "signature_hex": "vaultsig",
    })
    tx_state, tx_targets = scan_targets_for_protocol("scan_tx", "tx-1")

    assert profile_state == ScanState.recorded
    assert profile_targets[0]["type"] == "wallet"
    assert climb_state == ScanState.recorded
    assert climb_targets[0]["url"].endswith("/vault/12")
    assert canonical_state == ScanState.off_chain_only
    assert canonical_targets == []
    assert enriched_state == ScanState.recorded
    assert enriched_targets[0]["url"].endswith("/vault/42")
    assert tx_state == ScanState.recorded
    assert tx_targets[0]["type"] == "transaction"
