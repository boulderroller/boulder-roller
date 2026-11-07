"""Submit and validate ride-economic chain writes (BACKEND_TRUTHS §5.2)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from solders.pubkey import Pubkey

from ..solana_direct import (
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_vault_pda,
    derive_ride_attestation_pda,
    load_default_config,
    send_credit_cal,
    send_record_climb_completion,
    send_record_ride,
)
from .chain_receipt_execution import (
    ChainReceiptExecution,
    PdaMismatchError,
    authoritative_chain_clock as _authoritative_chain_clock,
    execution_from_reference as _execution_from_reference,
    to_unix_seconds as _to_unix_seconds,
)
from .ride_attester import OnchainRideIdentity
from .protocol_ints import (
    U8_MAX,
    U16_MAX,
    U32_MAX,
    U64_MAX,
    exact_positive_uint,
    exact_uint,
)
from .ride_chain_accounts import (
    AccountReader,
    LegacyCompletionEvidenceError,
    decode_cal_mint_receipt,
    decode_climb_completion_receipt,
    decode_ride_attestation,
    read_chain_account,
    read_owned_account,
    validate_cal_mint_receipt,
    validate_climb_completion_receipt,
    validate_ride_attestation,
)
from .vault_completion_evidence import build_climb_completion_evidence_v2


ConfigLoader = Callable[[], Any]
RecordRideFn = Callable[..., Awaitable[str]]
CreditCalFn = Callable[..., Awaitable[str]]
RecordClimbCompletionFn = Callable[..., Awaitable[str]]
DeriveRideAttestationPdaFn = Callable[[Pubkey, bytes, Pubkey], tuple[Pubkey, int]]
DeriveCalReceiptPdaFn = Callable[[Pubkey, Pubkey, Pubkey], tuple[Pubkey, int]]
DeriveClimbReceiptPdaFn = Callable[[Pubkey, Pubkey, Pubkey], tuple[Pubkey, int]]
DeriveVaultPdaFn = Callable[[int, Pubkey], tuple[Pubkey, int]]


RideAttestationExecution = ChainReceiptExecution


class RideExecutor:
    """Executor role: submit chain writes for already-attested ride data.

    This class intentionally loads `ProgramConfig` through the Solana direct
    path for each transaction. It must not consult Supabase/indexer state for
    authoritative transaction fields (BACKEND_TRUTHS §10.2).
    """

    def __init__(
        self,
        *,
        config_loader: ConfigLoader = load_default_config,
        record_ride_fn: RecordRideFn = send_record_ride,
        credit_cal_fn: CreditCalFn = send_credit_cal,
        record_climb_completion_fn: RecordClimbCompletionFn = (
            send_record_climb_completion
        ),
        derive_ride_attestation_pda_fn: DeriveRideAttestationPdaFn = (
            derive_ride_attestation_pda
        ),
        derive_cal_receipt_pda_fn: DeriveCalReceiptPdaFn = (
            _derive_cal_mint_receipt_pda
        ),
        derive_climb_receipt_pda_fn: DeriveClimbReceiptPdaFn = (
            _derive_climb_completion_receipt_pda
        ),
        derive_vault_pda_fn: DeriveVaultPdaFn = _derive_vault_pda,
        account_reader: AccountReader = read_chain_account,
        finalization_attempts: int = 20,
        finalization_poll_seconds: float = 0.5,
    ) -> None:
        self._config_loader = config_loader
        self._record_ride = record_ride_fn
        self._credit_cal = credit_cal_fn
        self._record_climb_completion = record_climb_completion_fn
        self._derive_ride_attestation_pda = derive_ride_attestation_pda_fn
        self._derive_cal_receipt_pda = derive_cal_receipt_pda_fn
        self._derive_climb_receipt_pda = derive_climb_receipt_pda_fn
        self._derive_vault_pda = derive_vault_pda_fn
        self._account_reader = account_reader
        self._finalization_attempts = max(1, int(finalization_attempts))
        self._finalization_poll_seconds = max(0.0, float(finalization_poll_seconds))

    def derive_attestation_pda(self, *, rider_wallet: str, ride_hash: bytes) -> str:
        config = self._config_loader()
        pda, _ = self._derive_ride_attestation_pda(
            Pubkey.from_string(rider_wallet),
            ride_hash,
            config.program_id,
        )
        return str(pda)

    def derive_cal_receipt_pda(self, *, rider_wallet: str, ride_hash: bytes) -> str:
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider,
            ride_hash,
            config.program_id,
        )
        receipt, _ = self._derive_cal_receipt_pda(
            attestation,
            rider,
            config.program_id,
        )
        return str(receipt)

    def derive_completion_receipt_pda(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        vault_id: int,
    ) -> str:
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider,
            ride_hash,
            config.program_id,
        )
        vault_id = exact_uint(vault_id, field="vault_id", maximum=U64_MAX)
        vault, _ = self._derive_vault_pda(vault_id, config.program_id)
        receipt, _ = self._derive_climb_receipt_pda(
            attestation,
            vault,
            config.program_id,
        )
        return str(receipt)

    def build_completion_evidence_v2(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        vault_id: int,
        completion_time_s: int,
        cal_tribute: int,
    ) -> bytes:
        """Build V2 evidence from the same PDAs used by the chain instruction."""
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider,
            ride_hash,
            config.program_id,
        )
        vault, _ = self._derive_vault_pda(vault_id, config.program_id)
        return build_climb_completion_evidence_v2(
            ride_attestation=attestation,
            vault=vault,
            completion_time_s=completion_time_s,
            cal_tribute=cal_tribute,
        )

    async def record_ride_attestation(
        self,
        *,
        rider_wallet: str,
        identity: OnchainRideIdentity,
        completed_at: datetime,
        started_at: datetime,
        total_tss: int,
        total_distance_m: int,
        total_vert_m: int,
        cal_earned: int,
        climbs_crossed: int,
        expected_pda: Optional[str] = None,
    ) -> RideAttestationExecution:
        """Commit or resolve the RideAttestation PDA for a parsed ride."""
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        if len(identity.ride_hash) != 32 or len(identity.attestation_commitment) != 32:
            raise ValueError("ride hash and attestation commitment must be 32 bytes")
        parser_version = exact_uint(
            identity.parser_version, field="parser_version", maximum=U32_MAX
        )
        source_kind = exact_uint(
            identity.source_kind, field="source_kind", maximum=U8_MAX
        )
        total_tss = exact_uint(total_tss, field="total_tss", maximum=U32_MAX)
        total_distance_m = exact_uint(
            total_distance_m, field="total_distance_m", maximum=U32_MAX
        )
        total_vert_m = exact_uint(
            total_vert_m, field="total_vert_m", maximum=U32_MAX
        )
        cal_earned = exact_uint(cal_earned, field="cal_earned", maximum=U64_MAX)
        climbs_crossed = exact_uint(
            climbs_crossed, field="climbs_crossed", maximum=U16_MAX
        )
        ride_event_time = _to_unix_seconds(completed_at)
        ride_start_time = _to_unix_seconds(started_at)
        derived_attestation_pda, derived_bump = self._derive_ride_attestation_pda(
            rider,
            identity.ride_hash,
            config.program_id,
        )
        derived_pda = str(derived_attestation_pda)
        if expected_pda is not None and expected_pda != derived_pda:
            raise PdaMismatchError(
                f"frozen attestation PDA {expected_pda} does not match expected PDA "
                f"{derived_pda}"
            )
        reference = await self._record_ride(
            config=config,
            rider_wallet=rider_wallet,
            ride_hash=identity.ride_hash,
            attestation_commitment=identity.attestation_commitment,
            parser_version=parser_version,
            source_kind=source_kind,
            completed_at=ride_event_time,
            started_at=ride_start_time,
            total_tss=total_tss,
            total_distance_m=total_distance_m,
            total_vert_m=total_vert_m,
            cal_earned=cal_earned,
            climbs_crossed=climbs_crossed,
        )

        async def validate_existing() -> Optional[str]:
            raw = await read_owned_account(
                reader=self._account_reader,
                rpc_url=config.rpc_url,
                address=derived_attestation_pda,
                program_id=config.program_id,
            )
            account = decode_ride_attestation(raw.data)
            validate_ride_attestation(
                account,
                rider=rider,
                ride_hash=identity.ride_hash,
                attestation_commitment=identity.attestation_commitment,
                parser_version=parser_version,
                source_kind=source_kind,
                completed_at=ride_event_time,
                started_at=ride_start_time,
                total_tss=total_tss,
                total_distance_m=total_distance_m,
                total_vert_m=total_vert_m,
                cal_earned=cal_earned,
                climbs_crossed=climbs_crossed,
                bump=derived_bump,
            )
            return _authoritative_chain_clock(
                account.settled_at, field="RideAttestation.settled_at"
            )

        return await _execution_from_reference(
            reference=reference,
            expected_pda=derived_pda,
            validate_existing=validate_existing,
            finalization_attempts=self._finalization_attempts,
            finalization_poll_seconds=self._finalization_poll_seconds,
            require_authoritative_confirmed_at=True,
        )

    async def credit_cal_receipt(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        amount: int,
        expected_pda: Optional[str] = None,
    ) -> ChainReceiptExecution:
        """Credit CAL and return validated receipt identity."""
        amount = exact_uint(amount, field="amount", maximum=U64_MAX)
        derived_pda = self.derive_cal_receipt_pda(
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
        )
        if expected_pda is not None and expected_pda != derived_pda:
            raise PdaMismatchError(
                f"frozen CAL receipt PDA {expected_pda} does not match expected PDA "
                f"{derived_pda}"
            )
        config = self._config_loader()
        reference = await self._credit_cal(
            config=config,
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
            amount=amount,
        )
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider, ride_hash, config.program_id
        )
        receipt, bump = self._derive_cal_receipt_pda(
            attestation, rider, config.program_id
        )

        async def validate_existing() -> None:
            raw = await read_owned_account(
                reader=self._account_reader,
                rpc_url=config.rpc_url,
                address=receipt,
                program_id=config.program_id,
            )
            validate_cal_mint_receipt(
                decode_cal_mint_receipt(raw.data),
                ride_attestation=attestation,
                rider=rider,
                amount=amount,
                bump=bump,
            )

        return await _execution_from_reference(
            reference=reference,
            expected_pda=derived_pda,
            validate_existing=validate_existing,
            finalization_attempts=self._finalization_attempts,
            finalization_poll_seconds=self._finalization_poll_seconds,
        )

    async def credit_cal(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        amount: int,
    ) -> str:
        """Credit CAL from an already-recorded RideAttestation."""
        execution = await self.credit_cal_receipt(
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
            amount=amount,
        )
        return execution.reference

    async def record_climb_completion_receipt(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        vault_id: int,
        completion_time_s: int,
        cal_tribute: int,
        completion_evidence_version: int,
        completion_evidence_hash: bytes,
        expected_pda: Optional[str] = None,
    ) -> ChainReceiptExecution:
        """Record a climb completion and return validated receipt identity."""
        if completion_evidence_version != 2:
            raise LegacyCompletionEvidenceError(
                "frozen V1 completion evidence requires manual chain review"
            )
        if len(completion_evidence_hash) != 32:
            raise ValueError("completion_evidence_hash must be 32 bytes")
        vault_id = exact_uint(vault_id, field="vault_id", maximum=U64_MAX)
        completion_time_s = exact_positive_uint(
            completion_time_s, field="completion_time_s", maximum=U32_MAX
        )
        cal_tribute = exact_uint(
            cal_tribute, field="cal_tribute", maximum=U64_MAX
        )
        derived_pda = self.derive_completion_receipt_pda(
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
            vault_id=vault_id,
        )
        if expected_pda is not None and expected_pda != derived_pda:
            raise PdaMismatchError(
                f"frozen completion receipt PDA {expected_pda} does not match "
                f"expected PDA {derived_pda}"
            )
        config = self._config_loader()
        reference = await self._record_climb_completion(
            config=config,
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
            vault_id=vault_id,
            completion_time_s=completion_time_s,
            cal_tribute=cal_tribute,
            completion_evidence_version=completion_evidence_version,
            completion_evidence_hash=completion_evidence_hash,
        )
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider, ride_hash, config.program_id
        )
        vault, _ = self._derive_vault_pda(vault_id, config.program_id)
        receipt, bump = self._derive_climb_receipt_pda(
            attestation, vault, config.program_id
        )

        async def validate_existing() -> None:
            raw = await read_owned_account(
                reader=self._account_reader,
                rpc_url=config.rpc_url,
                address=receipt,
                program_id=config.program_id,
            )
            validate_climb_completion_receipt(
                decode_climb_completion_receipt(raw.data),
                ride_attestation=attestation,
                vault=vault,
                evidence_version=completion_evidence_version,
                cal_tribute=cal_tribute,
                completion_evidence_hash=completion_evidence_hash,
                bump=bump,
            )

        return await _execution_from_reference(
            reference=reference,
            expected_pda=derived_pda,
            validate_existing=validate_existing,
            finalization_attempts=self._finalization_attempts,
            finalization_poll_seconds=self._finalization_poll_seconds,
        )

    async def record_climb_completion(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        vault_id: int,
        completion_time_s: int,
        cal_tribute: int,
        completion_evidence_version: int,
        completion_evidence_hash: bytes,
    ) -> str:
        """Record one climb/vault completion receipt against the attestation."""
        execution = await self.record_climb_completion_receipt(
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
            vault_id=vault_id,
            completion_time_s=completion_time_s,
            cal_tribute=cal_tribute,
            completion_evidence_version=completion_evidence_version,
            completion_evidence_hash=completion_evidence_hash,
        )
        return execution.reference
