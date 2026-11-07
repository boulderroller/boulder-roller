"""Verified chain inspection and fenced ride-economic review resolution."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from solders.pubkey import Pubkey

from ..repositories.ride_economic import RideEconomicRepository
from ..solana_direct import (
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_vault_pda,
    derive_ride_attestation_pda,
    load_default_config,
)
from .ride_chain_accounts import (
    ChainAccount,
    ChainAccountMismatchError,
    ChainAccountUnavailableError,
    FinalizedSnapshotReader,
    LegacyCompletionEvidenceError,
    decode_cal_mint_receipt,
    decode_climb_completion_receipt,
    decode_ride_attestation,
    read_finalized_chain_snapshot,
    validate_cal_mint_receipt,
    validate_climb_completion_receipt,
    validate_legacy_climb_completion_receipt,
    validate_ride_attestation,
)


ConfigLoader = Callable[[], Any]
NowFactory = Callable[[], datetime]


def _unix_seconds(value: Any, *, field: str) -> int:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ChainAccountMismatchError(f"frozen {field} is invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def _cluster_label(rpc_url: str, configured: Any) -> str:
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    lowered = rpc_url.lower()
    for cluster in ("devnet", "testnet", "mainnet"):
        if cluster in lowered:
            return cluster
    return "configured-finalized-rpc"


def _owned_data(account: ChainAccount, *, program_id: Pubkey, pda: str) -> bytes:
    owner = Pubkey.from_string(str(account.owner))
    if owner != program_id:
        raise ChainAccountMismatchError(
            f"account owner {owner} does not match program {program_id} for {pda}"
        )
    return bytes(account.data)


def _observation(
    *,
    account: Optional[ChainAccount],
    program_id: Pubkey,
    pda: str,
    slot: int,
    confirmed_at: str,
    fields: Dict[str, Any],
) -> tuple[Dict[str, Any], Optional[bytes]]:
    evidence: Dict[str, Any] = {
        "status": "absent" if account is None else "finalized",
        "pda": pda,
        "observed_slot": str(slot),
        **fields,
    }
    if account is None:
        return evidence, None
    data = _owned_data(account, program_id=program_id, pda=pda)
    evidence["account_data_hash_hex"] = hashlib.sha256(data).hexdigest()
    evidence["confirmed_at"] = confirmed_at
    return evidence, data


class FinalizedRideEconomicEvidenceCollector:
    """Construct chain evidence from one strict finalized account snapshot.

    Raw operator input never reaches this boundary. The collector derives every
    account from frozen plan facts, reads all accounts in one finalized RPC
    context, validates owner/layout/content, and hashes the exact account bytes.
    """

    def __init__(
        self,
        *,
        config_loader: ConfigLoader = load_default_config,
        snapshot_reader: FinalizedSnapshotReader = read_finalized_chain_snapshot,
        now: NowFactory = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._config_loader = config_loader
        self._snapshot_reader = snapshot_reader
        self._now = now

    async def collect(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        config = self._config_loader()
        program_id = Pubkey.from_string(str(config.program_id))
        rpc_url = str(config.rpc_url)
        rider = Pubkey.from_string(str(plan["wallet"]))
        ride_hash = bytes.fromhex(str(plan["ride_hash_hex"]))
        commitment = bytes.fromhex(str(plan["attestation_commitment_hex"]))
        if len(ride_hash) != 32 or len(commitment) != 32:
            raise ChainAccountMismatchError(
                "frozen ride hash and attestation commitment must be 32 bytes"
            )

        attestation, attestation_bump = derive_ride_attestation_pda(
            rider,
            ride_hash,
            program_id,
        )
        if str(attestation) != str(plan["expected_attestation_pda"]):
            raise ChainAccountMismatchError(
                "derived attestation PDA does not match frozen plan"
            )

        step_targets = []
        addresses = [attestation]
        for step in sorted(
            list(plan.get("steps") or []),
            key=lambda row: int(row["step_index"]),
        ):
            vault_id = int(step["vault_id"])
            vault, _ = _derive_vault_pda(vault_id, program_id)
            receipt, bump = _derive_climb_completion_receipt_pda(
                attestation,
                vault,
                program_id,
            )
            if str(receipt) != str(step["expected_receipt_pda"]):
                raise ChainAccountMismatchError(
                    f"derived completion PDA does not match frozen step {step['step_index']}"
                )
            step_targets.append((step, vault, receipt, bump))
            addresses.append(receipt)

        cal_receipt, cal_bump = _derive_cal_mint_receipt_pda(
            attestation,
            rider,
            program_id,
        )
        if str(cal_receipt) != str(plan["expected_cal_receipt_pda"]):
            raise ChainAccountMismatchError(
                "derived CAL receipt PDA does not match frozen plan"
            )
        addresses.append(cal_receipt)
        if len(addresses) > 100:
            raise ChainAccountUnavailableError(
                "ride economic review requires "
                f"{len(addresses)} accounts, exceeding the 100-account "
                "atomic finalized RPC limit"
            )

        snapshot = await self._snapshot_reader(rpc_url, tuple(addresses))
        if snapshot.slot <= 0 or len(snapshot.accounts) != len(addresses):
            raise ChainAccountUnavailableError(
                "finalized ride economic account snapshot is incomplete"
            )
        verified_at = self._now()
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=timezone.utc)
        verified_at_iso = verified_at.isoformat()

        attestation_evidence, attestation_data = _observation(
            account=snapshot.accounts[0],
            program_id=program_id,
            pda=str(attestation),
            slot=snapshot.slot,
            confirmed_at=verified_at_iso,
            fields={
                "ride_hash_hex": ride_hash.hex(),
                "attestation_commitment_hex": commitment.hex(),
            },
        )
        if attestation_data is not None:
            validate_ride_attestation(
                decode_ride_attestation(attestation_data),
                rider=rider,
                ride_hash=ride_hash,
                attestation_commitment=commitment,
                parser_version=int(plan["parser_version"]),
                source_kind=int(plan["source_kind"]),
                completed_at=_unix_seconds(
                    plan["completed_at"], field="completed_at"
                ),
                started_at=_unix_seconds(plan["started_at"], field="started_at"),
                total_tss=int(plan["total_tss"]),
                total_distance_m=int(plan["total_distance_m"]),
                total_vert_m=int(plan["total_vert_m"]),
                cal_earned=int(plan["exact_cal_base_units"]),
                climbs_crossed=int(plan["climbs_crossed"]),
                bump=attestation_bump,
            )

        completion_evidence = []
        for offset, (step, vault, receipt, bump) in enumerate(
            step_targets,
            start=1,
        ):
            frozen_hash = bytes.fromhex(
                str(step["completion_evidence_hash_hex"])
            )
            evidence_version = int(step.get("completion_evidence_version") or 1)
            if evidence_version not in {1, 2}:
                raise ChainAccountMismatchError(
                    f"frozen completion evidence version is invalid for step {step['step_index']}"
                )
            observation, data = _observation(
                account=snapshot.accounts[offset],
                program_id=program_id,
                pda=str(receipt),
                slot=snapshot.slot,
                confirmed_at=verified_at_iso,
                fields={
                    "step_index": int(step["step_index"]),
                    "vault_id": str(int(step["vault_id"])),
                    "exact_tribute_base_units": str(
                        int(step["exact_tribute_base_units"])
                    ),
                    "completion_evidence_version": evidence_version,
                    "tribute_bound": evidence_version == 2,
                    "completion_evidence_hash_hex": frozen_hash.hex(),
                },
            )
            if data is not None:
                decoded = decode_climb_completion_receipt(data)
                if evidence_version == 2:
                    validate_climb_completion_receipt(
                        decoded,
                        ride_attestation=attestation,
                        vault=vault,
                        evidence_version=evidence_version,
                        cal_tribute=int(step["exact_tribute_base_units"]),
                        completion_evidence_hash=frozen_hash,
                        bump=bump,
                    )
                else:
                    validate_legacy_climb_completion_receipt(
                        decoded,
                        ride_attestation=attestation,
                        vault=vault,
                        completion_evidence_hash=frozen_hash,
                        bump=bump,
                    )
            completion_evidence.append(observation)

        cal_evidence, cal_data = _observation(
            account=snapshot.accounts[-1],
            program_id=program_id,
            pda=str(cal_receipt),
            slot=snapshot.slot,
            confirmed_at=verified_at_iso,
            fields={
                "ride_hash_hex": ride_hash.hex(),
                "amount_base_units": str(int(plan["exact_cal_base_units"])),
            },
        )
        if cal_data is not None:
            validate_cal_mint_receipt(
                decode_cal_mint_receipt(cal_data),
                ride_attestation=attestation,
                rider=rider,
                amount=int(plan["exact_cal_base_units"]),
                bump=cal_bump,
            )

        return {
            "version": 1,
            "commitment": "finalized",
            "cluster": _cluster_label(
                rpc_url,
                getattr(config, "cluster", None),
            ),
            "finalized_slot": str(snapshot.slot),
            "verified_at": verified_at_iso,
            "attestation": attestation_evidence,
            "completions": completion_evidence,
            "cal": cal_evidence,
        }


class RideEconomicReviewResolutionService:
    """Resolve one review using evidence collected from finalized chain state."""

    def __init__(
        self,
        *,
        repository: RideEconomicRepository,
        evidence_collector: FinalizedRideEconomicEvidenceCollector,
    ) -> None:
        self.repository = repository
        self.evidence_collector = evidence_collector

    async def resolve(
        self,
        *,
        ride_id: UUID,
        expected_review_version: int,
        request_id: UUID,
        actor_id: UUID,
        outcome: str,
        selected_checkpoint: Optional[str],
        reason: str,
        liability_disposition: Optional[str],
        effects_disposition: Optional[str],
    ) -> Dict[str, Any]:
        selected_checkpoint = (
            selected_checkpoint.strip() if selected_checkpoint else None
        )
        reason = reason.strip()
        liability_disposition = (
            liability_disposition.strip() if liability_disposition else None
        )
        effects_disposition = (
            effects_disposition.strip() if effects_disposition else None
        )
        inspection = await self.repository.get_review(ride_id)
        if inspection is None or not isinstance(inspection.get("plan"), dict):
            raise RuntimeError("ride economic plan does not exist")
        plan = inspection["plan"]
        existing = inspection.get("resolution")
        if isinstance(existing, dict):
            same_request = str(existing.get("request_id")) == str(request_id)
            same_intent = (
                int(existing.get("review_version") or 0)
                == expected_review_version
                and str(existing.get("actor_id")) == str(actor_id)
                and existing.get("outcome") == outcome
                and existing.get("selected_checkpoint") == selected_checkpoint
                and existing.get("reason") == reason
                and existing.get("liability_disposition")
                == liability_disposition
                and existing.get("effects_disposition") == effects_disposition
            )
            if same_request and same_intent:
                return {**existing, "replayed": True}
            if same_request:
                raise RuntimeError(
                    "ride economic review request_id payload conflict"
                )
            raise RuntimeError(
                "ride economic review already resolved by request "
                f"{existing.get('request_id')}"
            )
        if (
            plan.get("state") != "review"
            or int(plan.get("review_version") or 0) != expected_review_version
        ):
            raise RuntimeError("ride economic review version fence failed")

        verified_evidence = await self.evidence_collector.collect(plan)
        if outcome != "reject" and any(
            int(observation.get("completion_evidence_version") or 0) != 2
            or observation.get("tribute_bound") is not True
            for observation in verified_evidence.get("completions") or []
        ):
            raise LegacyCompletionEvidenceError(
                "V1 completion evidence cannot authorize a non-reject review resolution"
            )
        return await self.repository.resolve_review(
            ride_id=ride_id,
            expected_review_version=expected_review_version,
            request_id=request_id,
            actor_id=actor_id,
            outcome=outcome,
            selected_checkpoint=selected_checkpoint,
            reason=reason,
            chain_evidence=verified_evidence,
            liability_disposition=liability_disposition,
            effects_disposition=effects_disposition,
        )
