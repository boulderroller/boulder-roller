"""Submit and validate receipt-backed held-ride release writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from solders.pubkey import Pubkey

from ..solana_direct import (
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_held_ride_release_pda,
    _derive_vault_pda,
    derive_ride_attestation_pda,
    get_vault_account,
    load_default_config,
    send_authorize_held_ride_release,
    send_credit_released_cal,
    send_record_released_climb_completion,
)
from .chain_receipt_execution import (
    ChainReceiptExecution,
    PdaMismatchError,
    authoritative_chain_clock,
    execution_from_reference,
    to_unix_seconds,
)
from .protocol_ints import (
    U16_MAX,
    U32_MAX,
    U64_MAX,
    exact_positive_uint,
    exact_uint,
)
from .reward_ftp import REWARD_FTP_POLICY_VERSION
from .ride_chain_accounts import (
    AccountReader,
    decode_held_ride_release_authority,
    decode_released_cal_mint_receipt,
    decode_released_climb_completion_receipt,
    read_chain_account,
    read_owned_account,
    validate_held_ride_release_authority,
    validate_held_ride_release_credit_authority,
    validate_released_cal_mint_receipt,
    validate_released_climb_completion_receipt,
)
from .threshold_release_week import (
    ThresholdReleaseFlowNotOpen,
    VaultAccountReader,
    require_frozen_release_week,
)
from .vault_completion_evidence import build_released_climb_completion_evidence_v3


ConfigLoader = Callable[[], Any]
ChainSender = Callable[..., Awaitable[str]]
DeriveRideAttestationPdaFn = Callable[[Pubkey, bytes, Pubkey], tuple[Pubkey, int]]
DeriveCalReceiptPdaFn = Callable[[Pubkey, Pubkey, Pubkey], tuple[Pubkey, int]]
DeriveClimbReceiptPdaFn = Callable[[Pubkey, Pubkey, Pubkey], tuple[Pubkey, int]]
DeriveHeldRideReleasePdaFn = Callable[[Pubkey, Pubkey], tuple[Pubkey, int]]
DeriveVaultPdaFn = Callable[[int, Pubkey], tuple[Pubkey, int]]

HELD_RIDE_RELEASE_POLICY_VERSION = 1
HELD_RIDE_ELIGIBILITY_WINDOW_SECONDS = 16 * 7 * 24 * 60 * 60


class ThresholdReleaseExecutor:
    """Execute the one-time child authority for provisional ride economics."""

    def __init__(
        self,
        *,
        config_loader: ConfigLoader = load_default_config,
        authorize_held_ride_release_fn: ChainSender = (
            send_authorize_held_ride_release
        ),
        credit_released_cal_fn: ChainSender = send_credit_released_cal,
        record_released_climb_completion_fn: ChainSender = (
            send_record_released_climb_completion
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
        derive_held_ride_release_pda_fn: DeriveHeldRideReleasePdaFn = (
            _derive_held_ride_release_pda
        ),
        derive_vault_pda_fn: DeriveVaultPdaFn = _derive_vault_pda,
        vault_account_reader: VaultAccountReader = get_vault_account,
        account_reader: AccountReader = read_chain_account,
        finalization_attempts: int = 20,
        finalization_poll_seconds: float = 0.5,
    ) -> None:
        self._config_loader = config_loader
        self._authorize_held_ride_release = authorize_held_ride_release_fn
        self._credit_released_cal = credit_released_cal_fn
        self._record_released_climb_completion = (
            record_released_climb_completion_fn
        )
        self._derive_ride_attestation_pda = derive_ride_attestation_pda_fn
        self._derive_cal_receipt_pda = derive_cal_receipt_pda_fn
        self._derive_climb_receipt_pda = derive_climb_receipt_pda_fn
        self._derive_held_ride_release_pda = derive_held_ride_release_pda_fn
        self._derive_vault_pda = derive_vault_pda_fn
        self._vault_account_reader = vault_account_reader
        self._account_reader = account_reader
        self._finalization_attempts = max(1, int(finalization_attempts))
        self._finalization_poll_seconds = max(0.0, float(finalization_poll_seconds))

    def derive_held_ride_release_pda(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
    ) -> str:
        """Derive the stable child authority PDA frozen by release planning."""
        if len(ride_hash) != 32:
            raise ValueError("ride_hash must be 32 bytes")
        config = self._config_loader()
        attestation, _ = self._derive_ride_attestation_pda(
            Pubkey.from_string(rider_wallet), ride_hash, config.program_id
        )
        release, _ = self._derive_held_ride_release_pda(
            attestation, config.program_id
        )
        return str(release)

    derive_release_authority_pda = derive_held_ride_release_pda

    def derive_cal_receipt_pda(
        self, *, rider_wallet: str, ride_hash: bytes
    ) -> str:
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider, ride_hash, config.program_id
        )
        receipt, _ = self._derive_cal_receipt_pda(
            attestation, rider, config.program_id
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
            rider, ride_hash, config.program_id
        )
        vault_id = exact_uint(vault_id, field="vault_id", maximum=U64_MAX)
        vault, _ = self._derive_vault_pda(vault_id, config.program_id)
        receipt, _ = self._derive_climb_receipt_pda(
            attestation, vault, config.program_id
        )
        return str(receipt)

    def build_released_completion_evidence_v3(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        vault_id: int,
        completion_time_s: int,
        cal_tribute: int,
        expected_release_authority_pda: Optional[str] = None,
    ) -> bytes:
        """Build V3 evidence from the exact release, ride, and Vault PDAs."""
        if len(ride_hash) != 32:
            raise ValueError("ride_hash must be 32 bytes")
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider, ride_hash, config.program_id
        )
        release, _ = self._derive_held_ride_release_pda(
            attestation, config.program_id
        )
        if (
            expected_release_authority_pda is not None
            and expected_release_authority_pda != str(release)
        ):
            raise PdaMismatchError(
                "frozen held-ride release PDA does not match expected PDA "
                f"{release}"
            )
        vault_id = exact_uint(vault_id, field="vault_id", maximum=U64_MAX)
        completion_time_s = exact_positive_uint(
            completion_time_s, field="completion_time_s", maximum=U32_MAX
        )
        cal_tribute = exact_uint(
            cal_tribute, field="cal_tribute", maximum=U64_MAX
        )
        vault, _ = self._derive_vault_pda(vault_id, config.program_id)
        return build_released_climb_completion_evidence_v3(
            release_authority=release,
            ride_attestation=attestation,
            vault=vault,
            completion_time_s=completion_time_s,
            cal_tribute=cal_tribute,
        )

    async def authorize_held_ride_release_receipt(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        reward_ftp_authority_id: UUID,
        reward_ftp_authority_evidence_hash: bytes,
        reward_ftp_policy_version: str,
        reward_ftp_w: int,
        admitted_at: datetime,
        established_at: datetime,
        total_tss: int,
        exact_cal_base_units: int,
        exact_tribute_budget_base_units: int,
        release_plan_evidence_hash: bytes,
        expected_pda: Optional[str] = None,
    ) -> ChainReceiptExecution:
        """Create or validate the immutable authority for held economics."""
        if len(ride_hash) != 32:
            raise ValueError("ride_hash must be 32 bytes")
        authority_id = UUID(str(reward_ftp_authority_id))
        if authority_id.int == 0:
            raise ValueError("reward_ftp_authority_id must be non-zero")
        if (
            len(reward_ftp_authority_evidence_hash) != 32
            or reward_ftp_authority_evidence_hash == b"\x00" * 32
        ):
            raise ValueError(
                "reward_ftp_authority_evidence_hash must be 32 non-zero bytes"
            )
        if reward_ftp_policy_version != REWARD_FTP_POLICY_VERSION:
            raise ValueError(
                f"unsupported held-ride Threshold policy: {reward_ftp_policy_version}"
            )
        if (
            len(release_plan_evidence_hash) != 32
            or release_plan_evidence_hash == b"\x00" * 32
        ):
            raise ValueError("release_plan_evidence_hash must be 32 non-zero bytes")
        threshold_w = exact_uint(
            reward_ftp_w, field="reward_ftp_w", maximum=U16_MAX
        )
        if threshold_w < 50 or threshold_w > 500:
            raise ValueError("reward_ftp_w must be within the protocol 50-500 W bounds")
        economic_tss = exact_uint(total_tss, field="total_tss", maximum=U32_MAX)
        cal_earned = exact_uint(
            exact_cal_base_units,
            field="exact_cal_base_units",
            maximum=U64_MAX,
        )
        cal_tribute_budget = exact_uint(
            exact_tribute_budget_base_units,
            field="exact_tribute_budget_base_units",
            maximum=U64_MAX,
        )
        admitted_timestamp = to_unix_seconds(admitted_at)
        threshold_effective_at = to_unix_seconds(established_at)
        if max(0, threshold_effective_at - admitted_timestamp) > (
            HELD_RIDE_ELIGIBILITY_WINDOW_SECONDS
        ):
            raise ValueError("held ride is outside the inclusive 16-week window")

        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider, ride_hash, config.program_id
        )
        release, release_bump = self._derive_held_ride_release_pda(
            attestation, config.program_id
        )
        derived_pda = str(release)
        if expected_pda is not None and expected_pda != derived_pda:
            raise PdaMismatchError(
                f"frozen held-ride release PDA {expected_pda} does not match "
                f"expected PDA {derived_pda}"
            )
        reference = await self._authorize_held_ride_release(
            config=config,
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
            threshold_authority_id=authority_id.bytes,
            threshold_authority_commitment=reward_ftp_authority_evidence_hash,
            threshold_effective_at=threshold_effective_at,
            threshold_w=threshold_w,
            threshold_policy_version=HELD_RIDE_RELEASE_POLICY_VERSION,
            economic_tss=economic_tss,
            cal_earned=cal_earned,
            cal_tribute_budget=cal_tribute_budget,
            release_plan_hash=release_plan_evidence_hash,
        )

        async def validate_existing() -> Optional[str]:
            raw = await read_owned_account(
                reader=self._account_reader,
                rpc_url=config.rpc_url,
                address=release,
                program_id=config.program_id,
            )
            account = decode_held_ride_release_authority(raw.data)
            validate_held_ride_release_authority(
                account,
                ride_attestation=attestation,
                rider=rider,
                threshold_authority_id=authority_id.bytes,
                threshold_authority_commitment=reward_ftp_authority_evidence_hash,
                threshold_effective_at=threshold_effective_at,
                threshold_w=threshold_w,
                threshold_policy_version=HELD_RIDE_RELEASE_POLICY_VERSION,
                economic_tss=economic_tss,
                cal_earned=cal_earned,
                cal_tribute_budget=cal_tribute_budget,
                release_plan_hash=release_plan_evidence_hash,
                bump=release_bump,
            )
            return authoritative_chain_clock(
                account.released_at,
                field="HeldRideReleaseAuthority.released_at",
            )

        return await execution_from_reference(
            reference=reference,
            expected_pda=derived_pda,
            validate_existing=validate_existing,
            finalization_attempts=self._finalization_attempts,
            finalization_poll_seconds=self._finalization_poll_seconds,
            require_authoritative_confirmed_at=True,
        )

    async def credit_released_cal_receipt(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        amount: int,
        expected_release_authority_pda: str,
        expected_pda: Optional[str] = None,
    ) -> ChainReceiptExecution:
        """Credit only the amount already frozen in the release authority."""
        if len(ride_hash) != 32:
            raise ValueError("ride_hash must be 32 bytes")
        amount = exact_positive_uint(amount, field="amount", maximum=U64_MAX)
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider, ride_hash, config.program_id
        )
        release, release_bump = self._derive_held_ride_release_pda(
            attestation, config.program_id
        )
        if expected_release_authority_pda != str(release):
            raise PdaMismatchError(
                f"frozen held-ride release PDA {expected_release_authority_pda} "
                f"does not match expected PDA {release}"
            )
        receipt, receipt_bump = self._derive_cal_receipt_pda(
            attestation, rider, config.program_id
        )
        derived_pda = str(receipt)
        if expected_pda is not None and expected_pda != derived_pda:
            raise PdaMismatchError(
                f"frozen released CAL receipt PDA {expected_pda} does not match "
                f"expected PDA {derived_pda}"
            )

        release_raw = await read_owned_account(
            reader=self._account_reader,
            rpc_url=config.rpc_url,
            address=release,
            program_id=config.program_id,
        )
        release_account = decode_held_ride_release_authority(release_raw.data)
        validate_held_ride_release_credit_authority(
            release_account,
            ride_attestation=attestation,
            rider=rider,
            cal_earned=amount,
            bump=release_bump,
        )
        reference = await self._credit_released_cal(
            config=config,
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
        )

        async def validate_existing() -> Optional[str]:
            raw = await read_owned_account(
                reader=self._account_reader,
                rpc_url=config.rpc_url,
                address=receipt,
                program_id=config.program_id,
            )
            validate_released_cal_mint_receipt(
                decode_released_cal_mint_receipt(raw.data),
                ride_attestation=attestation,
                release_authority=release,
                rider=rider,
                amount=amount,
                release_settlement_week=release_account.release_settlement_week,
                bump=receipt_bump,
            )
            return authoritative_chain_clock(
                release_account.released_at,
                field="HeldRideReleaseAuthority.released_at",
            )

        return await execution_from_reference(
            reference=reference,
            expected_pda=derived_pda,
            validate_existing=validate_existing,
            finalization_attempts=self._finalization_attempts,
            finalization_poll_seconds=self._finalization_poll_seconds,
            require_authoritative_confirmed_at=True,
        )

    async def record_released_climb_completion_receipt(
        self,
        *,
        rider_wallet: str,
        ride_hash: bytes,
        vault_id: int,
        completion_time_s: int,
        cal_tribute: int,
        completion_evidence_version: int,
        completion_evidence_hash: bytes,
        expected_release_authority_pda: str,
        expected_pda: Optional[str] = None,
    ) -> ChainReceiptExecution:
        """Record and validate one release-bound V3 climb receipt."""
        if completion_evidence_version != 3:
            raise ValueError("released climb completion requires V3 evidence")
        if len(ride_hash) != 32:
            raise ValueError("ride_hash must be 32 bytes")
        if (
            len(completion_evidence_hash) != 32
            or completion_evidence_hash == b"\x00" * 32
        ):
            raise ValueError("completion_evidence_hash must be 32 non-zero bytes")
        vault_id = exact_uint(vault_id, field="vault_id", maximum=U64_MAX)
        completion_time_s = exact_positive_uint(
            completion_time_s, field="completion_time_s", maximum=U32_MAX
        )
        cal_tribute = exact_uint(
            cal_tribute, field="cal_tribute", maximum=U64_MAX
        )
        config = self._config_loader()
        rider = Pubkey.from_string(rider_wallet)
        attestation, _ = self._derive_ride_attestation_pda(
            rider, ride_hash, config.program_id
        )
        release, _ = self._derive_held_ride_release_pda(
            attestation, config.program_id
        )
        if expected_release_authority_pda != str(release):
            raise PdaMismatchError(
                f"frozen held-ride release PDA {expected_release_authority_pda} "
                f"does not match expected PDA {release}"
            )
        vault, _ = self._derive_vault_pda(vault_id, config.program_id)
        receipt, receipt_bump = self._derive_climb_receipt_pda(
            attestation, vault, config.program_id
        )
        derived_pda = str(receipt)
        if expected_pda is not None and expected_pda != derived_pda:
            raise PdaMismatchError(
                f"frozen released completion receipt PDA {expected_pda} does not "
                f"match expected PDA {derived_pda}"
            )
        expected_evidence_hash = build_released_climb_completion_evidence_v3(
            release_authority=release,
            ride_attestation=attestation,
            vault=vault,
            completion_time_s=completion_time_s,
            cal_tribute=cal_tribute,
        )
        if completion_evidence_hash != expected_evidence_hash:
            raise ValueError(
                "V3 released completion evidence hash does not match exact tribute"
            )
        release_confirmed_at, release_week = await require_frozen_release_week(
            config=config,
            release=release,
            ride_attestation=attestation,
            rider=rider,
            vault_id=vault_id,
            account_reader=self._account_reader,
            vault_account_reader=self._vault_account_reader,
        )
        reference = await self._record_released_climb_completion(
            config=config,
            rider_wallet=rider_wallet,
            ride_hash=ride_hash,
            vault_id=vault_id,
            completion_time_s=completion_time_s,
            cal_tribute=cal_tribute,
            completion_evidence_version=completion_evidence_version,
            completion_evidence_hash=completion_evidence_hash,
        )

        async def validate_existing() -> Optional[str]:
            raw = await read_owned_account(
                reader=self._account_reader,
                rpc_url=config.rpc_url,
                address=receipt,
                program_id=config.program_id,
            )
            validate_released_climb_completion_receipt(
                decode_released_climb_completion_receipt(raw.data),
                ride_attestation=attestation,
                release_authority=release,
                vault=vault,
                evidence_version=completion_evidence_version,
                cal_tribute=cal_tribute,
                completion_evidence_hash=completion_evidence_hash,
                credited_settlement_week=release_week,
                bump=receipt_bump,
            )
            return release_confirmed_at

        return await execution_from_reference(
            reference=reference,
            expected_pda=derived_pda,
            validate_existing=validate_existing,
            finalization_attempts=self._finalization_attempts,
            finalization_poll_seconds=self._finalization_poll_seconds,
            require_authoritative_confirmed_at=True,
        )
