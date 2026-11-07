"""BoulderScan scan.v1 target contracts."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from .link_contracts import scan_origin


SCAN_CONTRACT_VERSION = "scan.v1"


class ScanState(str, Enum):
    pending = "pending"
    recorded = "recorded"
    finalized = "finalized"
    missing = "missing"
    failed = "failed"
    off_chain_only = "off_chain_only"
    private = "private"


class ScanTargetType(str, Enum):
    transaction = "transaction"
    account = "account"
    vault = "vault"
    proof = "proof"
    wallet = "wallet"


def boulderscan_url(target_type: ScanTargetType, identifier: str) -> str:
    base = scan_origin()
    if target_type == ScanTargetType.transaction:
        return f"{base}/tx/{identifier}"
    if target_type == ScanTargetType.account:
        return f"{base}/account/{identifier}"
    if target_type == ScanTargetType.wallet:
        return f"{base}/account/{identifier}"
    if target_type == ScanTargetType.vault:
        return f"{base}/vault/{identifier}"
    if target_type == ScanTargetType.proof:
        return f"{base}/proof/{identifier}"
    raise ValueError(f"Unsupported scan target type: {target_type}")


def build_scan_target(
    *,
    target_type: ScanTargetType,
    identifier: str,
    state: ScanState,
    label: str,
    source: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return {
        "contractVersion": SCAN_CONTRACT_VERSION,
        "type": target_type.value,
        "id": identifier,
        "state": state.value,
        "label": label,
        "url": boulderscan_url(target_type, identifier),
        "source": source,
        "metadata": metadata or {},
    }


def summarize_scan_state(targets: list[dict[str, Any]], fallback: ScanState = ScanState.missing) -> ScanState:
    if not targets:
        return fallback
    states = {target.get("state") for target in targets}
    if ScanState.finalized.value in states:
        return ScanState.finalized
    if ScanState.recorded.value in states:
        return ScanState.recorded
    if ScanState.pending.value in states:
        return ScanState.pending
    if ScanState.failed.value in states:
        return ScanState.failed
    if ScanState.off_chain_only.value in states:
        return ScanState.off_chain_only
    if ScanState.private.value in states:
        return ScanState.private
    return fallback


def scan_targets_for_profile(user: dict[str, Any]) -> tuple[ScanState, list[dict[str, Any]]]:
    wallet = user.get("wallet")
    if not wallet:
        return ScanState.missing, []
    targets = [
        build_scan_target(
            target_type=ScanTargetType.wallet,
            identifier=str(wallet),
            state=ScanState.recorded,
            label="Wallet account",
            source="user.wallet",
        )
    ]
    return ScanState.recorded, targets


def scan_targets_for_ride(ride: dict[str, Any], *, can_view: bool) -> tuple[ScanState, list[dict[str, Any]]]:
    if not can_view:
        return ScanState.private, []

    status = str(ride.get("processing_status") or "").lower()
    if status == "failed":
        return ScanState.failed, []

    targets: list[dict[str, Any]] = []
    tx_signature = (
        ride.get("ride_attestation_tx_signature")
        or ride.get("tx_signature")
        or ride.get("transaction_signature")
    )
    if tx_signature:
        tx_state = ScanState.finalized if ride.get("finalized_at") or ride.get("ride_attested_at") else ScanState.recorded
        targets.append(
            build_scan_target(
                target_type=ScanTargetType.transaction,
                identifier=str(tx_signature),
                state=tx_state,
                label="Ride attestation transaction",
                source="ride.attestation_tx",
            )
        )

    attestation_pda = ride.get("ride_attestation_pda")
    if attestation_pda:
        targets.append(
            build_scan_target(
                target_type=ScanTargetType.account,
                identifier=str(attestation_pda),
                state=ScanState.recorded,
                label="Ride attestation account",
                source="ride.attestation_pda",
            )
        )

    proof_id = ride.get("attestation_commitment_hex") or ride.get("ride_hash_hex")
    if proof_id:
        targets.append(
            build_scan_target(
                target_type=ScanTargetType.proof,
                identifier=str(proof_id),
                state=ScanState.recorded,
                label="Ride proof",
                source="ride.proof",
            )
        )

    if targets:
        return summarize_scan_state(targets), targets
    if status in {"pending", "uploading", "processing", "metrics_ready", "enriched", "under_review"}:
        return ScanState.pending, []
    return ScanState.off_chain_only, []


def scan_targets_for_climb(climb: dict[str, Any]) -> tuple[ScanState, list[dict[str, Any]]]:
    vault_id = climb.get("vault_id")
    if vault_id is None and str(climb.get("id") or "").isdigit():
        vault_id = climb.get("id")
    vault_signature = climb.get("vault_signature") or climb.get("signature_hex")
    if vault_id is None and not vault_signature:
        return ScanState.missing, []
    if vault_id is None:
        return ScanState.off_chain_only, []

    identifier = str(vault_id)
    targets = [
        build_scan_target(
            target_type=ScanTargetType.vault,
            identifier=identifier,
            state=ScanState.recorded,
            label="Boulder Roller vault",
            source="climb.vault",
            metadata={"vaultSignature": vault_signature},
        )
    ]
    return ScanState.recorded, targets


def scan_targets_for_protocol(target_type: str, target_id: str) -> tuple[ScanState, list[dict[str, Any]]]:
    if target_type == "scan_tx":
        scan_type = ScanTargetType.transaction
        label = "Transaction"
    elif target_type == "scan_account":
        scan_type = ScanTargetType.account
        label = "Account"
    elif target_type == "proof":
        scan_type = ScanTargetType.proof
        label = "Proof"
    else:
        return ScanState.missing, []
    return ScanState.recorded, [
        build_scan_target(
            target_type=scan_type,
            identifier=target_id,
            state=ScanState.recorded,
            label=label,
            source=f"{target_type}.direct",
        )
    ]
