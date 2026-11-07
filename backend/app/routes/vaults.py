"""
Vaults API Routes

Core vault operations: discovery, matching, completions, staking ("claiming territory").
"""

from ..services.privacy_logging import scrub_log_text
import base64
import hashlib
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    field_validator,
    model_validator,
)
from solders.hash import Hash
from solders.transaction import Transaction

from ..generated_program_version import PROGRAM_VERSION_FAMILY
from ..avatar_media_contracts import with_signed_avatar_url
from ..dependencies import AuthenticatedUser, get_current_user, get_optional_current_user, get_repository, get_user_repository
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository, UserRepository
from ..repositories.vault import VaultRepository
from ..repositories.climb_effort import ClimbEffortRepository
from ..services.climb_effort_reads import admitted_kom, enrich_board
from ..client_contracts import RecordBoard, RecordBoardEntry, TruthSource
from .. import solana_direct
from ..services.tx_builder import (
    BuildTxResult,
    SubmittedTransactionExpired,
    SubmittedTransactionFailed,
    SubmittedTransactionPending,
    get_tx_builder,
)
from ..services.canon_vault_activation import (
    CanonVaultActivationError,
    confirm_canon_vault_activation,
    load_canon_climb_runtime_states,
    load_canon_vault_preparation,
    load_canon_vault_release_candidate,
    release_canon_vault_activation_after_absence,
    require_generated_canon_runtime_program,
    reserve_canon_vault_activation,
    resolve_canon_vault_source,
)
from ..services.balance_route_adapters import (
    VaultBalanceRouteScope,
    collect_dung_intent,
    create_vault_intent,
    deposit_cal_intent,
    withdraw_cal_intent,
)
from ..services.balance_transaction_coordinator import (
    BalanceActionBudgetExceeded,
    BalanceOperationError,
    BalanceTransactionCoordinator,
    BalanceOperationRecord,
    SupabaseBalanceOperationSink,
    prepared_message_hash,
)
from ..services.balance_transaction_submission import (
    BalanceSubmissionError,
    submit_confirmed_balance_transaction,
)
from ..services.balance_production_rollout import is_balance_action_enabled
from ..services.public_record_board_privacy import (
    PublicRecordBoardPrivacyUnavailable,
    PublicRecordBoardProjection,
    project_public_record_board,
)
from ..services.vault_reward_identity import (
    VaultRewardIdentityAmbiguous,
    VaultRewardIdentityIncomplete,
    VaultRewardIdentityMissing,
    VaultRewardIdentityUnavailable,
    resolve_reward_grade_vault_identity,
)
from ..services.vault_activation_policy import is_reward_authoritative_vault
from ..token_amounts import (
    ExactTokenAmount,
    TokenAmountError,
    exact_token_amount,
    fee_split_base_units,
    parse_base_units,
    require_base_units_string,
)
from .admin import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vaults", tags=["vaults"])

def _require_balance_rollout_action(action: str) -> None:
    if is_balance_action_enabled(action):
        return
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="This Balance action is not open yet.",
    )


def _require_reward_authoritative_vault(vault: Dict[str, Any]) -> None:
    if is_reward_authoritative_vault(vault):
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "Deposits are closed for this vault. You can still Withdraw CAL "
            "and Collect DUNG that is already available."
        ),
    )


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================


class VaultSummary(BaseModel):
    """Vault summary for list views."""
    id: int
    signature_hex: str
    name: str
    vert_m: float
    distance_m: int
    avg_gradient_pct: float
    total_completions: int
    total_staked: str
    total_staked_base_units: str
    total_cal_staked: str
    total_cal_staked_base_units: str
    kom_holder: Optional[str] = None
    kom_time_s: Optional[int] = None
    minter: str
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    on_chain_active: bool = False
    on_chain_seeding_status: Optional[str] = None


class LeaderboardEntryResponse(RecordBoardEntry):
    """Leaderboard entry in API responses."""
    best_time_seconds: int


class LocalLegendResponse(BaseModel):
    """Local Legend entry in API responses."""
    id: Optional[str] = None
    vault_signature: Optional[str] = None
    wallet: str
    elected_at: Optional[str] = None
    term_ends_at: Optional[str] = None
    completions_count: Optional[int] = None
    is_active: Optional[bool] = None
    is_bootstrap: Optional[bool] = None
    seat_status: Optional[str] = None


class VaultDetail(BaseModel):
    """Full vault detail with leaderboard and stakes."""
    id: int
    signature_hex: str
    signature_hash_hex: str
    name: str
    vert_m: float
    distance_m: int
    avg_gradient_pct: float
    total_completions: int
    total_staked: str
    total_staked_base_units: str
    kom_holder: Optional[str] = None
    kom_time_s: Optional[int] = None
    minter: str
    pda: str
    leaderboard: List[LeaderboardEntryResponse]
    total_cal_staked: str
    total_cal_staked_base_units: str
    total_lp_tokens: str
    total_lp_tokens_base_units: str
    local_legend: Optional[LocalLegendResponse] = None
    on_chain_active: bool = False
    on_chain_seeding_status: Optional[str] = None


class VaultListResponse(BaseModel):
    """Response for vault list endpoint."""
    vaults: List[VaultSummary]
    total: int
    offset: int
    limit: int


class SignatureMatchRequest(BaseModel):
    """Request to match ride signatures against vaults."""
    signatures: List[str] = Field(..., description="List of 64-byte signature hashes (SHA256)")
    activity_id: Optional[str] = Field(None, description="Activity ID for context")


class SignatureMatch(BaseModel):
    """A matched vault for a signature."""
    signature_hash: str
    vault_id: int
    vault_name: str
    vert_m: float
    similarity: float = 1.0  # Exact match for now, fuzzy later


class SignatureMatchResponse(BaseModel):
    """Response for signature matching."""
    matches: List[SignatureMatch]
    unmatched_count: int
    discovery_only: Literal[True] = True
    economic_authority: Literal["none"] = "none"


class RecordCompletionRequest(BaseModel):
    """Request to record a vault completion."""
    activity_id: str
    time_seconds: Optional[int] = None
    avg_power_w: Optional[int] = None


class CompletionResponse(BaseModel):
    """Response after recording a completion."""
    vault_signature: str
    vault_name: str
    time_seconds: Optional[int]
    leaderboard_rank: Optional[int] = None
    is_new_pr: bool = False


class WalletSubmissionContext(BaseModel):
    """Preparation identity echoed when submitting signed transaction bytes."""

    last_valid_block_height: Optional[int] = Field(default=None, gt=0)
    client_request_id: Optional[str] = Field(default=None, min_length=1, max_length=120)


class StakeRequest(WalletSubmissionContext):
    """Request to stake CAL in a vault."""
    cal_amount: StrictInt = Field(..., ge=100, description="Whole CAL to stake (minimum 100)")
    signed_transaction: Optional[str] = Field(
        default=None,
        description="Base64-encoded signed Solana transaction for wallet flows",
    )


class VaultStakeInfo(BaseModel):
    """Vault stake record from database.

    Carries the vault id and climb identity next to the signature so clients
    can join positions to vault/climb objects without signature heuristics.
    """
    id: Optional[str] = None
    vault_signature: str
    # Numeric vault id (indexed_vaults.id / on-chain Vault.id).
    vault_id: Optional[int] = None
    vault_name: Optional[str] = None
    # Canon registry climb UUID where the vault is canon-bound.
    climb_id: Optional[str] = None
    wallet: str
    cal_staked: str
    cal_staked_base_units: str
    lp_tokens: str
    lp_tokens_base_units: str
    staked_at: Optional[str] = None
    unstaked_at: Optional[str] = None
    converted_at: Optional[str] = None


class MyStakesResponse(BaseModel):
    """Response for user's stakes across all vaults."""
    stakes: List[VaultStakeInfo]
    total_cal_staked: str
    total_cal_staked_base_units: str
    total_lp_tokens: str
    total_lp_tokens_base_units: str
    vault_count: int


def _project_vault_amounts(
    vault: Dict[str, Any],
    *,
    total_cal_staked: Any,
    total_lp_tokens: Any = 0,
) -> Dict[str, Any]:
    """Replace deprecated Vault counters with exact active stake projections."""
    cal = exact_token_amount(total_cal_staked, field_name="total_cal_staked")
    lp = exact_token_amount(total_lp_tokens, field_name="total_lp_tokens")
    return {
        **vault,
        "total_staked": cal.units,
        "total_staked_base_units": cal.base_units,
        "total_cal_staked": cal.units,
        "total_cal_staked_base_units": cal.base_units,
        "total_lp_tokens": lp.units,
        "total_lp_tokens_base_units": lp.base_units,
    }


def _build_vault_stake_info(stake: Dict[str, Any]) -> VaultStakeInfo:
    cal = exact_token_amount(stake.get("cal_staked") or 0, field_name="cal_staked")
    lp = exact_token_amount(stake.get("lp_tokens") or 0, field_name="lp_tokens")
    raw_vault_id = stake.get("vault_id")
    return VaultStakeInfo(
        id=stake.get("id"),
        vault_signature=stake.get("vault_signature", ""),
        vault_id=int(raw_vault_id) if raw_vault_id is not None else None,
        vault_name=stake.get("vault_name"),
        climb_id=stake.get("climb_id"),
        wallet=stake.get("wallet", ""),
        cal_staked=cal.units,
        cal_staked_base_units=cal.base_units,
        lp_tokens=lp.units,
        lp_tokens_base_units=lp.base_units,
        staked_at=stake.get("staked_at"),
        unstaked_at=stake.get("unstaked_at"),
        converted_at=stake.get("converted_at"),
    )


class StakeResponse(BaseModel):
    """Response after staking."""
    vault_signature: str
    cal_staked: str
    cal_staked_base_units: str
    lp_tokens_received: Optional[str] = None
    lp_tokens_received_base_units: Optional[str] = None
    total_position: Optional[str] = None
    total_position_base_units: Optional[str] = None
    tx_signature: Optional[str] = None
    stake: Optional[VaultStakeInfo] = None
    new_total_staked: Optional[str] = None
    new_total_staked_base_units: Optional[str] = None
    projection_status: str = "recorded"
    confirmation_status: Optional[str] = None
    rider_state: Optional[str] = None
    operation_id: Optional[str] = None
    message: Optional[str] = None


class UnstakeRequest(WalletSubmissionContext):
    """Request to unstake from a vault."""
    lp_amount_base_units: Optional[str] = Field(
        default=None,
        description="Exact LP base units to burn as a decimal string",
    )
    withdraw_all: StrictBool = Field(
        default=False,
        description="Read and burn the complete on-chain VaultStake LP balance",
    )
    signed_transaction: Optional[str] = Field(
        default=None,
        description="Base64-encoded signed Solana transaction for wallet flows",
    )

    @field_validator("lp_amount_base_units", mode="before")
    @classmethod
    def validate_lp_amount_base_units(cls, value: object) -> Optional[str]:
        if value is None:
            return None
        try:
            return require_base_units_string(
                value,
                field_name="lp_amount_base_units",
                allow_zero=False,
            )
        except TokenAmountError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def validate_withdrawal_mode(self) -> "UnstakeRequest":
        has_exact_amount = self.lp_amount_base_units is not None
        if has_exact_amount == self.withdraw_all:
            raise ValueError(
                "Provide exactly one of lp_amount_base_units or withdraw_all=true"
            )
        return self


class UnstakeResponse(BaseModel):
    """Response after unstaking.

    Withdraw composes collect-before-unstake: when the position carried
    unclaimed DUNG, the same atomic transaction collected it first. The
    ``dung_collected*`` fields report that collect; all None means nothing was
    pending when the withdraw was prepared.
    """
    vault_signature: str
    lp_burned: str
    lp_burned_base_units: str
    cal_returned: Optional[str] = None
    cal_returned_base_units: Optional[str] = None
    dung_collected_total_base_units: Optional[str] = None
    dung_collect_fee_base_units: Optional[str] = None
    dung_collected: Optional[str] = None
    dung_collected_base_units: Optional[str] = None
    tx_signature: Optional[str] = None
    projection_status: str = "recorded"
    confirmation_status: Optional[str] = None
    rider_state: Optional[str] = None
    operation_id: Optional[str] = None
    message: Optional[str] = None


class HarvestRequest(WalletSubmissionContext):
    """Request to harvest pending rewards from a vault."""
    signed_transaction: Optional[str] = Field(
        default=None,
        description="Base64-encoded signed Solana transaction for wallet flows",
    )


class PendingRewardEntry(BaseModel):
    """A pending reward entry."""
    epoch: int
    receipt_type: str
    amount: str
    amount_base_units: str
    rank: Optional[int] = None


class HarvestResponse(BaseModel):
    """Response after harvesting rewards."""
    vault_signature: str
    vault_name: str
    total_harvested: str
    total_harvested_base_units: str
    fee_amount: str
    fee_amount_base_units: str
    net_received: str
    net_received_base_units: str
    destination_token_account: str
    destination_type: str = "spl_wallet_ata"
    receipts_count: int
    tx_signature: Optional[str] = None
    projection_status: str = "recorded"
    confirmation_status: Optional[str] = None
    rider_state: Optional[str] = None
    operation_id: Optional[str] = None
    message: Optional[str] = None


SPL_CAL_DECIMALS_MULTIPLIER = 1_000_000_000


class PendingRewardsResponse(BaseModel):
    """Response for pending rewards query."""
    vault_signature: str
    vault_name: str
    pending_rewards: List[PendingRewardEntry]
    total_pending: str
    total_pending_base_units: str
    fee_estimate: str
    fee_estimate_base_units: str
    net_estimate: str
    net_estimate_base_units: str
    harvest_fee_bps: str
    exit_fee_bps: str
    lp_tokens_base_units: Optional[str] = None
    withdrawal_amount_base_units: Optional[str] = None
    withdrawal_fee_base_units: Optional[str] = None
    withdrawal_net_base_units: Optional[str] = None


class CreateVaultRequest(WalletSubmissionContext):
    """Request to create a new vault from a climb signature."""
    signature_hex: str = Field(..., description="64-byte climb signature as 128 hex chars")
    name: str = Field(..., min_length=3, max_length=64, description="Vault name")
    vert_m: float = Field(..., gt=0, description="Vertical gain in meters")
    distance_m: int = Field(..., ge=100, description="Distance in meters")
    avg_gradient_pct: float = Field(..., ge=1, le=50, description="Average gradient %")
    payment_method: str = Field(
        default="dung",
        description="Payment method: 'dung' (100 DUNG burned) or 'cal_usdc' (1000 CAL + $2 USDC)"
    )
    signed_transaction: Optional[str] = Field(
        default=None,
        description="Base64-encoded signed Solana transaction for wallet-based vault creation",
    )
    prepared_vault_id: Optional[int] = Field(
        default=None,
        description="Vault ID returned by /vaults/create/prepare for wallet-signed creation",
    )


class CanonVaultPrepareRequest(BaseModel):
    """Prepare from one exact immutable registry row; identity is server-owned."""

    model_config = ConfigDict(extra="forbid")

    climb_id: UUID
    payment_method: Literal["dung", "cal_usdc"] = "dung"
    client_request_id: str = Field(min_length=1, max_length=120)


class CanonVaultSubmitRequest(BaseModel):
    """Submit only the signed bytes for one wallet-scoped preparation."""

    model_config = ConfigDict(extra="forbid")

    preparation_id: UUID
    signed_transaction: str = Field(min_length=1)


class CanonVaultPreparedResponse(BaseModel):
    """Wallet-signable bytes reserved against one exact ratified Climb."""

    preparation_id: UUID
    climb_id: UUID
    canon_commitment_hex: str
    transaction: str
    blockhash: str
    last_valid_block_height: int
    message: str
    vault_id: int
    pda: str


class CanonVaultSubmitResponse(BaseModel):
    """A canonical activation is either exact-finalized active or pending."""

    preparation_id: UUID
    climb_id: UUID
    vault_id: int
    pda: str
    tx_signature: str
    activation_state: Literal["active", "pending"]
    projection_status: Literal["active", "pending"]
    confirmation_status: Literal["finalized", "confirmed", "pending"]
    message: str


class CreateVaultResponse(BaseModel):
    """Response after creating a vault."""
    vault_id: int
    name: str
    signature_hex: str
    pda: str
    tx_signature: str
    minter: str
    message: str
    projection_status: str = "recorded"
    confirmation_status: Optional[str] = None
    rider_state: Optional[str] = None
    operation_id: Optional[str] = None


class PreparedTransactionResponse(BaseModel):
    """Prepared Solana transaction for wallet signature."""
    transaction: str
    blockhash: str
    last_valid_block_height: int
    message: str
    vault_id: Optional[int] = None
    pda: Optional[str] = None


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_vault_repo(repo: DatabaseRepository = Depends(get_repository)) -> VaultRepository:
    """Get vault repository from database repository."""
    return VaultRepository(repo.client)


def signature_to_hash(signature_hex: str) -> str:
    """Convert 64-byte signature to SHA256 hash for lookup."""
    sig_bytes = bytes.fromhex(signature_hex)
    return hashlib.sha256(sig_bytes).hexdigest()


async def _resolve_reward_grade_vault_source(
    *,
    repo: DatabaseRepository,
    wallet: str,
    signature_hex: str,
) -> Dict[str, Any]:
    """Resolve one unambiguous stored v2 identity for a new on-chain vault."""
    try:
        identity = resolve_reward_grade_vault_identity(
            client=repo.client,
            signature_hex=signature_hex,
            required_wallet=wallet,
        )
    except VaultRewardIdentityAmbiguous as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This legacy climb signature maps to more than one location. "
                "Reprocess the selected ride before creating a vault."
            ),
        ) from exc
    except (VaultRewardIdentityIncomplete, VaultRewardIdentityMissing) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "The selected climb lacks canonical v2 location evidence. "
                "Reprocess the ride before creating a vault."
            ),
        ) from exc
    except VaultRewardIdentityUnavailable as exc:
        logger.error("[VaultCreate] Failed to load canonical climb evidence: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify the selected climb. Please try again.",
        ) from exc
    return identity.as_source_dict()


def _prepared_transaction_response(result: BuildTxResult) -> PreparedTransactionResponse:
    """Convert a tx-builder result into an API response model."""
    return PreparedTransactionResponse(
        transaction=result.transaction,
        blockhash=result.blockhash,
        last_valid_block_height=result.last_valid_block_height,
        message=result.message,
        vault_id=result.vault_id,
        pda=result.pda,
    )


def _decode_signed_transaction_or_400(signed_transaction: str) -> Transaction:
    """Decode a signed transaction or raise a 400 with a clean message."""
    try:
        return get_tx_builder().decode_signed_transaction(signed_transaction)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signed transaction payload.",
        ) from exc


def _assert_signed_transaction_matches(
    signed_tx: Transaction,
    expected_result: BuildTxResult,
) -> None:
    """Ensure the submitted signed tx matches the server-built message bytes."""
    expected_tx = Transaction.from_bytes(base64.b64decode(expected_result.transaction))
    if signed_tx.message_data() != expected_tx.message_data():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signed transaction does not match the prepared transaction.",
        )


def _require_last_valid_block_height(value: Optional[int]) -> int:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prepared transaction expiry is required.",
        )
    return value


def _signed_transaction_signature(signed_tx: Transaction) -> str:
    signatures = getattr(signed_tx, "signatures", None)
    if not signatures:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signed transaction has no transaction signature.",
        )
    return str(signatures[0])


def _balance_coordinator(repo: DatabaseRepository) -> BalanceTransactionCoordinator:
    client = getattr(repo, "client", None)
    sink = SupabaseBalanceOperationSink(client) if client is not None else None
    return BalanceTransactionCoordinator(sink=sink, budget_store=sink)


def _balance_operation_http_exception(exc: BalanceOperationError) -> HTTPException:
    if isinstance(exc, BalanceActionBudgetExceeded):
        return HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=exc.rider_message,
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Boulder Roller could not prepare this action. Please try again.",
    )


def _builder_fee_payer(builder) -> Optional[str]:
    fee_payer = getattr(builder, "fee_payer", None)
    pubkey = getattr(fee_payer, "pubkey", None)
    return str(pubkey()) if callable(pubkey) else None


async def _record_balance_operation(
    coordinator: BalanceTransactionCoordinator,
    record: BalanceOperationRecord,
) -> None:
    # The coordinator writes through its sink during prepare/update. Keep this
    # awaitable shim so route code can mark the persistence checkpoint clearly.
    return None


def _operation_projection_status(operation: Optional[BalanceOperationRecord]) -> str:
    return operation.projection_status if operation else "pending"


def _operation_confirmation_status(operation: Optional[BalanceOperationRecord]) -> Optional[str]:
    return operation.confirmation_status if operation else None


def _operation_rider_state(
    operation: Optional[BalanceOperationRecord],
    fallback: Optional[str] = "Pending",
) -> Optional[str]:
    return operation.rider_state if operation else fallback


async def _enrich_leaderboard_public_identity(
    entries: List[dict],
    user_repo: UserRepository,
) -> List[dict]:
    """Attach public rider identity fields to leaderboard rows when available."""
    profile_cache: dict[str, Optional[dict]] = {}
    enriched: List[dict] = []

    for entry in entries:
        row = dict(entry)
        wallet = str(row.get("wallet") or "")

        if wallet:
            if wallet not in profile_cache:
                try:
                    profile_cache[wallet] = await user_repo.get_public_user_identity(wallet)
                except Exception as exc:
                    logger.warning(
                        "[VaultLeaderboard] Failed to load public identity for wallet %s: %s",
                        "[redacted]",
                        scrub_log_text(exc),
                    )
                    profile_cache[wallet] = None

            profile = profile_cache[wallet]
            if profile and profile.get("is_public", True):
                profile = await with_signed_avatar_url(profile) or profile
                row["user_id"] = profile.get("id")
                row["username"] = profile.get("username")
                row["display_name"] = profile.get("display_name")
                row["avatar_url"] = profile.get("avatar_url")

        enriched.append(row)

    return enriched


def _public_board_unavailable_http_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Public Record Board privacy projection is temporarily unavailable",
    )


async def _project_public_vault_board(
    vault_repo: VaultRepository,
    vault: dict[str, Any],
) -> PublicRecordBoardProjection:
    """Resolve a legacy Vault Board through the strict public privacy gate."""
    client = getattr(vault_repo, "client", None)
    raw_reader = getattr(vault_repo, "get_vault_record_board_entries", None)
    if client is None or raw_reader is None:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )

    try:
        raw_entries = await raw_reader(int(vault["id"]))
        return project_public_record_board(
            client,
            vault_row=vault,
            raw_entries=raw_entries,
        )
    except PublicRecordBoardPrivacyUnavailable:
        raise
    except Exception as exc:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        ) from exc


def _leaderboard_rows_from_public_projection(
    vault_signature: str,
    projection: PublicRecordBoardProjection,
) -> list[dict[str, Any]]:
    """Map eligible raw seats without promoting or refilling any position."""
    def achieved_at(entry: dict[str, Any]) -> Optional[str]:
        recorded_at = entry.get("recorded_at")
        if recorded_at in (None, "") or isinstance(recorded_at, bool):
            return None
        try:
            return datetime.fromtimestamp(
                int(recorded_at),
                tz=timezone.utc,
            ).isoformat()
        except (OSError, OverflowError, TypeError, ValueError):
            return None

    return [
        {
            "vault_signature": vault_signature,
            "position": int(entry["position"]),
            # Legacy consumers read rank as the occupied Board seat.  Keep the
            # standard-competition rank separately, matching the repository.
            "rank": int(entry["position"]),
            "competition_rank": int(entry["rank"]),
            "tie_size": int(entry["tie_size"]),
            "is_tied": bool(entry["is_tied"]),
            "wallet": str(entry.get("user") or ""),
            "best_time_seconds": int(entry.get("time_s") or 0),
            "avg_power_w": None,
            "completion_id": None,
            "achieved_at": achieved_at(entry),
        }
        for entry in projection.entries
    ]


def _record_board_entry_from_leaderboard_row(
    row: dict,
    *,
    vault_signature: Optional[str],
    fallback_rank: int,
) -> RecordBoardEntry:
    """Convert a projected leaderboard row into a typed record-board entry."""
    rank = row.get("rank") if row.get("rank") is not None else fallback_rank
    return RecordBoardEntry(
        position=int(row.get("position") or fallback_rank),
        rank=int(rank),
        competition_rank=int(row.get("competition_rank") or rank),
        tie_size=int(row.get("tie_size") or 1),
        is_tied=bool(row.get("is_tied", False)),
        wallet=str(row.get("wallet") or ""),
        best_time_seconds=row.get("best_time_seconds"),
        avg_power_w=row.get("avg_power_w"),
        power_kind=row.get("power_kind"),
        estimated_power_w=row.get("estimated_power_w"),
        estimated_power_range_w=row.get("estimated_power_range_w"),
        effort_id=row.get("effort_id"),
        ride_id=row.get("ride_id"),
        w_per_kg=row.get("w_per_kg"),
        place_source=row.get("place_source"),
        completion_id=row.get("completion_id"),
        achieved_at=row.get("achieved_at"),
        vault_signature=row.get("vault_signature") or vault_signature,
        user_id=row.get("user_id"),
        username=row.get("username"),
        display_name=row.get("display_name"),
        avatar_url=row.get("avatar_url"),
    )


def _vault_record_board_response(
    vault_id: int,
    vault: dict,
    leaderboard: List[dict],
) -> RecordBoard:
    """Build the client contract for a vault's projected record board."""
    vault_signature = vault.get("signature_hex")
    entries = [
        _record_board_entry_from_leaderboard_row(
            row,
            vault_signature=vault_signature,
            fallback_rank=index + 1,
        )
        for index, row in enumerate(leaderboard)
    ]

    return RecordBoard(
        truth_source=TruthSource.projected,
        climb_id=str(vault_id),
        climb_name=vault.get("name"),
        vault_id=vault_id,
        entries=entries,
        kom_holder=vault.get("kom_holder"),
        kom_time_s=vault.get("kom_time_s"),
    )


async def _get_onchain_vault_position(
    vault_id: int,
    wallet: str,
) -> tuple[
    solana_direct.DirectConfig,
    dict,
    dict,
    solana_direct.VaultLpCustodyObservation,
]:
    """Load canonical vault + active stake state for rider-facing action quotes."""
    try:
        config = solana_direct.load_default_config()
        snapshot = await solana_direct.get_vault_position_quote_snapshot(
            config,
            vault_id,
            wallet,
        )
        stake = snapshot.stake if snapshot is not None else None
        if stake is None or int(stake.get("lp_tokens") or 0) <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No active LP position exists for this vault.",
            )

        return config, snapshot.vault, stake, snapshot.custody
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[VaultHarvest] Failed to load on-chain stake state for vault %s wallet %s: %s",
            vault_id,
            "[redacted]",
            scrub_log_text(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not load on-chain staking rewards.",
        ) from exc


async def _get_onchain_claimable_stake_rewards(
    vault_id: int,
    wallet: str,
) -> tuple[dict, dict]:
    """Load canonical vault + stake state for claimable on-chain staking rewards."""
    _, vault, stake, _ = await _get_onchain_vault_position(vault_id, wallet)
    if int(stake.get("rewards_earned") or 0) <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No pending staking rewards to harvest",
        )
    return vault, stake


# =============================================================================
# USER'S VAULT ACTIVITY (must come before /{vault_id} routes)
# =============================================================================


@router.get("/my/completions")
async def get_my_completions(
    limit: int = Query(50, le=100),
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
):
    """Get current user's vault completions."""
    completions = await vault_repo.get_completions_for_wallet(
        current_user.wallet,
        limit=limit,
    )

    return {"completions": completions}


@router.get("/my/stakes", response_model=MyStakesResponse)
async def get_my_stakes(
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
):
    """Get current user's active stakes across all vaults."""
    stakes = await vault_repo.get_wallet_stakes(current_user.wallet)

    typed_stakes = [_build_vault_stake_info(stake) for stake in stakes]
    total_staked_base_units = sum(
        parse_base_units(stake.cal_staked_base_units, field_name="cal_staked")
        for stake in typed_stakes
    )
    total_lp_base_units = sum(
        parse_base_units(stake.lp_tokens_base_units, field_name="lp_tokens")
        for stake in typed_stakes
    )
    total_staked = exact_token_amount(
        total_staked_base_units,
        field_name="total_cal_staked",
    )
    total_lp = exact_token_amount(
        total_lp_base_units,
        field_name="total_lp_tokens",
    )

    return MyStakesResponse(
        stakes=typed_stakes,
        total_cal_staked=total_staked.units,
        total_cal_staked_base_units=total_staked.base_units,
        total_lp_tokens=total_lp.units,
        total_lp_tokens_base_units=total_lp.base_units,
        vault_count=len(stakes),
    )


# =============================================================================
# USER EFFORT HISTORY
# =============================================================================


class UserEffortHistoryEntry(BaseModel):
    """A single effort in user's history for a vault."""
    id: str
    rideId: Optional[str] = None
    timeSeconds: int
    avgPowerW: Optional[int] = None
    achievedAt: Optional[str] = None
    isPR: bool
    improvement: Optional[int] = None  # Seconds faster than previous PR


class UserEffortHistoryResponse(BaseModel):
    """Response for user's effort history on a vault."""
    vaultId: int
    vaultName: str
    efforts: List[UserEffortHistoryEntry]
    totalCount: int
    bestTimeSeconds: Optional[int] = None
    totalPrs: int


@router.get("/{vault_id}/my-completions", response_model=UserEffortHistoryResponse)
async def get_my_vault_effort_history(
    vault_id: int,
    limit: int = Query(50, le=100, description="Max efforts to return"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
):
    """
    Get the current user's completion history for a specific vault.

    Returns all completions sorted by date (newest first), with:
    - isPR: Was this the best time at the moment it was achieved?
    - improvement: Seconds faster than the previous PR (if applicable)

    Use this for:
    - Showing user's personal progress on a vault
    - PR progression tracking
    - Effort history visualization
    """
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    efforts = await vault_repo.get_user_vault_effort_history(
        vault["signature_hex"],
        current_user.wallet,
        limit=limit,
    )

    # The repository repeats the full confirmed-attempt count on every row so
    # a bounded history response never turns six attempts into one merely
    # because the client requested or the index can currently return one row.
    total_count = max(
        [len(efforts)]
        + [int(effort.get("attemptCount") or 0) for effort in efforts]
    )

    # Calculate aggregates
    best_time = None
    total_prs = 0
    for effort in efforts:
        if effort.get("isPR"):
            total_prs += 1
        time_s = effort.get("timeSeconds")
        if time_s is not None and (best_time is None or time_s < best_time):
            best_time = time_s

    return UserEffortHistoryResponse(
        vaultId=vault_id,
        vaultName=vault["name"],
        efforts=[UserEffortHistoryEntry(**e) for e in efforts],
        totalCount=total_count,
        bestTimeSeconds=best_time,
        totalPrs=total_prs,
    )


# =============================================================================
# VAULT DISCOVERY
# =============================================================================


@router.get("", response_model=VaultListResponse)
async def list_vaults(
    limit: int = Query(50, le=100, description="Max vaults to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    min_vert: Optional[float] = Query(None, description="Minimum vertical gain (meters)"),
    minter: Optional[str] = Query(None, description="Filter by minter wallet"),
    search: Optional[str] = Query(None, description="Search vault names"),
    order_by: str = Query("total_completions", description="Sort field"),
    vault_repo: VaultRepository = Depends(get_vault_repo),
):
    """
    List available vaults for staking and competition.

    Vaults are on-chain climb records that users can stake in and compete on.
    """
    # Get total count with same filters (for pagination)
    total_count = await vault_repo.count_vaults(
        min_vert_m=min_vert,
        minter=minter,
        search=search,
    )

    vaults = await vault_repo.list_vaults(
        limit=limit,
        offset=offset,
        min_vert_m=min_vert,
        minter=minter,
        search=search,
        order_by=order_by,
    )

    totals_by_vault = await vault_repo.get_vault_stake_totals(
        [int(vault["id"]) for vault in vaults]
    )
    vaults = [
        _project_vault_amounts(
            vault,
            total_cal_staked=totals_by_vault[int(vault["id"])]["total_cal_staked"],
            total_lp_tokens=totals_by_vault[int(vault["id"])]["total_lp_tokens"],
        )
        for vault in vaults
    ]

    # The list does not load exact ride/span evidence for every Board seat.
    # Omit the KOM summary instead of exposing an unverified private winner or
    # issuing hundreds of privacy projection queries for one browse request.
    for v in vaults:
        v["kom_holder"] = None
        v["kom_time_s"] = None
        seeding_status = v.get("on_chain_seeding_status")
        v["on_chain_active"] = seeding_status == "active"
        v["on_chain_seeding_status"] = seeding_status

    return VaultListResponse(
        vaults=[VaultSummary(**v) for v in vaults],
        total=total_count,
        offset=offset,
        limit=limit,
    )


@router.get("/{vault_id}", response_model=VaultDetail)
async def get_vault(
    vault_id: int,
    vault_repo: VaultRepository = Depends(get_vault_repo),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Get detailed vault information including leaderboard and staking stats.
    """
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    detail = await vault_repo.get_vault_detail(vault["signature_hex"])
    detail = _project_vault_amounts(
        detail,
        total_cal_staked=detail.get("total_cal_staked") or 0,
        total_lp_tokens=detail.get("total_lp_tokens") or 0,
    )
    try:
        public_projection = await _project_public_vault_board(vault_repo, vault)
    except PublicRecordBoardPrivacyUnavailable as exc:
        raise _public_board_unavailable_http_exception() from exc
    entries, _ = await enrich_board(
        ClimbEffortRepository(vault_repo.client), public_projection,
        vault_signature=str(vault.get("signature_hex") or ""), viewer=None,
    )
    detail["leaderboard"] = await _enrich_leaderboard_public_identity(
        [entry.model_dump(exclude_none=True) for entry in entries], user_repo)
    detail["kom_holder"], detail["kom_time_s"] = admitted_kom(public_projection, entries)
    seeding_status = detail.get("on_chain_seeding_status")
    detail["on_chain_active"] = seeding_status == "active"
    detail["on_chain_seeding_status"] = seeding_status
    return VaultDetail(**detail)


# =============================================================================
# SIGNATURE MATCHING
# =============================================================================


@router.post("/match", response_model=SignatureMatchResponse)
@rate_limit(category="general")
async def match_signatures(
    match_request: SignatureMatchRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
):
    """
    Match ride climb signatures against indexed vaults.

    This is the core matching endpoint used after ride processing.
    Returns vaults that match any of the provided signature hashes.

    Currently uses exact matching. Fuzzy matching with trajectory context
    is planned for future versions.
    """
    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy detector-signature Vault matching is disabled for V4-B; "
                "canon traversal is the sole economic authority."
            ),
        )
    if not match_request.signatures:
        return SignatureMatchResponse(matches=[], unmatched_count=0)

    # Find vaults by signature hash
    vaults = await vault_repo.find_vaults_by_signatures(match_request.signatures)

    # Build lookup of found signatures
    found_hashes = {v["signature_hash_hex"] for v in vaults}
    unmatched = [s for s in match_request.signatures if s not in found_hashes]

    matches = [
        SignatureMatch(
            signature_hash=v["signature_hash_hex"],
            vault_id=v["id"],
            vault_name=v["name"],
            vert_m=v["vert_m"],
            similarity=1.0,  # Exact match
        )
        for v in vaults
    ]

    logger.info(
        f"[VaultMatch] Matched {len(matches)}/{len(match_request.signatures)} signatures"
        f" (activity={match_request.activity_id})"
    )

    return SignatureMatchResponse(
        matches=matches,
        unmatched_count=len(unmatched),
    )


# =============================================================================
# VAULT CREATION
# =============================================================================


async def _build_canon_vault_transaction(
    *,
    source,
    creator_wallet: str,
    payment_method: str,
    blockhash=None,
    last_valid_block_height: Optional[int] = None,
    vault_id: Optional[int] = None,
) -> BuildTxResult:
    builder = get_tx_builder()
    kwargs = {
        "user_wallet": creator_wallet,
        "climb_pda": source.climb_pda,
        "display_name": source.name,
        "blockhash": blockhash,
        "last_valid_block_height": last_valid_block_height,
        "vault_id": vault_id,
    }
    if payment_method == "cal_usdc":
        return await builder.build_create_vault_with_usdc_tx(**kwargs)
    if payment_method == "dung":
        return await builder.build_create_vault_tx(**kwargs)
    raise CanonVaultActivationError("unsupported canonical Vault payment method")


def _require_exact_preparation_source(preparation, source) -> None:
    if (
        str(preparation.get("canon_climb_id")) != str(source.climb_id)
        or str(preparation.get("canon_commitment_hex") or "").lower()
        != source.commitment_hex
        or str(preparation.get("commitment_hash_hex") or "").lower()
        != source.commitment_hash_hex
        or str(preparation.get("climb_pda") or "") != source.climb_pda
    ):
        raise CanonVaultActivationError(
            "canonical Vault preparation no longer matches the exact Climb"
        )


@router.post("/create/canon/prepare", response_model=CanonVaultPreparedResponse)
@rate_limit(category="vault_creation")
async def prepare_canon_vault(
    vault_request: CanonVaultPrepareRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Reserve and return wallet-signable bytes for one exact canon Climb."""
    del request
    try:
        require_generated_canon_runtime_program()
        if vault_request.payment_method == "cal_usdc":
            _require_balance_rollout_action("create_vault_usdc")
        source = resolve_canon_vault_source(
            client=repo.client,
            climb_id=vault_request.climb_id,
        )
        result = await _build_canon_vault_transaction(
            source=source,
            creator_wallet=current_user.wallet,
            payment_method=vault_request.payment_method,
        )
        if (
            result.vault_id is None
            or result.pda is None
            or result.activation_pda is None
        ):
            raise CanonVaultActivationError("canonical Vault builder omitted an exact PDA")
        builder = get_tx_builder()
        candidate = load_canon_vault_release_candidate(
            client=repo.client,
            vault_id=result.vault_id,
        )
        if candidate is not None:
            candidate_expiry = int(candidate["last_valid_block_height"])
            finalized_height = await builder.get_finalized_block_height()
            if finalized_height <= candidate_expiry:
                candidate_matches_request = (
                    str(candidate["canon_climb_id"]) == str(source.climb_id)
                    and str(candidate["creator_wallet"]) == current_user.wallet
                    and str(candidate["client_request_id"])
                    == vault_request.client_request_id
                    and str(candidate["payment_method"])
                    == vault_request.payment_method
                    and str(candidate["canon_commitment_hex"]).lower()
                    == source.commitment_hex
                    and str(candidate["commitment_hash_hex"]).lower()
                    == source.commitment_hash_hex
                    and str(candidate["climb_pda"]) == source.climb_pda
                )
                if not candidate_matches_request:
                    raise CanonVaultActivationError(
                        "the current VaultCounter id has a live canonical reservation"
                    )
                result = await _build_canon_vault_transaction(
                    source=source,
                    creator_wallet=current_user.wallet,
                    payment_method=vault_request.payment_method,
                    blockhash=Hash.from_string(str(candidate["prepared_blockhash"])),
                    last_valid_block_height=candidate_expiry,
                    vault_id=int(candidate["vault_id"]),
                )
                if (
                    result.pda != str(candidate["vault_pda"])
                    or result.activation_pda
                    != str(candidate["vault_activation_pda"])
                ):
                    raise CanonVaultActivationError(
                        "live canonical reservation PDAs do not match the counter"
                    )
            else:
                observation = (
                    await builder.observe_finalized_canon_reservation_absence(
                        climb_pda=str(candidate["climb_pda"]),
                        vault_pda=str(candidate["vault_pda"]),
                        vault_activation_pda=str(candidate["vault_activation_pda"]),
                        canon_commitment_hex=str(candidate["canon_commitment_hex"]),
                        commitment_hash_hex=str(candidate["commitment_hash_hex"]),
                    )
                )
                if observation.block_height <= candidate_expiry:
                    raise CanonVaultActivationError(
                        "canonical reservation expiry is not finalized"
                    )
                released = release_canon_vault_activation_after_absence(
                    client=repo.client,
                    preparation_id=UUID(str(candidate["preparation_id"])),
                    creator_wallet=str(candidate["creator_wallet"]),
                    observed_finalized_slot=observation.slot,
                    observed_finalized_block_height=observation.block_height,
                    reason=(
                        "prepared constructor expired; exact source Climb remained "
                        "unbound and reserved Vault accounts were absent at finalized"
                    ),
                )
                if not released:
                    raise CanonVaultActivationError(
                        "canonical reservation changed during finalized absence proof"
                    )
        preparation_id = reserve_canon_vault_activation(
            client=repo.client,
            source=source,
            creator_wallet=current_user.wallet,
            payment_method=vault_request.payment_method,
            client_request_id=vault_request.client_request_id,
            vault_id=result.vault_id,
            vault_pda=result.pda,
            vault_activation_pda=result.activation_pda,
            blockhash=result.blockhash,
            last_valid_block_height=result.last_valid_block_height,
        )
    except HTTPException:
        raise
    except (CanonVaultActivationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("[CanonVaultPrepare] exact preparation failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canonical Vault preparation is temporarily unavailable.",
        ) from exc

    return CanonVaultPreparedResponse(
        preparation_id=preparation_id,
        climb_id=source.climb_id,
        canon_commitment_hex=source.commitment_hex,
        transaction=result.transaction,
        blockhash=result.blockhash,
        last_valid_block_height=result.last_valid_block_height,
        message=result.message,
        vault_id=result.vault_id,
        pda=result.pda,
    )


@router.post("/create/canon/submit", response_model=CanonVaultSubmitResponse)
@rate_limit(category="vault_creation")
async def submit_canon_vault(
    vault_request: CanonVaultSubmitRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Submit exact prepared bytes; active means finalized indexer projection."""
    del request
    try:
        require_generated_canon_runtime_program()
        preparation = load_canon_vault_preparation(
            client=repo.client,
            preparation_id=vault_request.preparation_id,
            creator_wallet=current_user.wallet,
        )
        source = resolve_canon_vault_source(
            client=repo.client,
            climb_id=UUID(str(preparation["canon_climb_id"])),
        )
        _require_exact_preparation_source(preparation, source)
        signed_tx = _decode_signed_transaction_or_400(
            vault_request.signed_transaction
        )
        expected = await _build_canon_vault_transaction(
            source=source,
            creator_wallet=current_user.wallet,
            payment_method=str(preparation["payment_method"]),
            blockhash=signed_tx.message.recent_blockhash,
            last_valid_block_height=int(preparation["last_valid_block_height"]),
            vault_id=int(preparation["vault_id"]),
        )
        if (
            expected.pda != str(preparation["vault_pda"])
            or expected.activation_pda
            != str(preparation["vault_activation_pda"])
            or expected.blockhash != str(preparation["prepared_blockhash"])
            or expected.last_valid_block_height
            != int(preparation["last_valid_block_height"])
        ):
            raise CanonVaultActivationError(
                "signed bytes do not match the reserved canonical Vault"
            )
        _assert_signed_transaction_matches(signed_tx, expected)
        tx_signature = _signed_transaction_signature(signed_tx)
        message_hash = prepared_message_hash(expected.transaction)
        submission_pending = False
        builder = get_tx_builder()
        try:
            observed_signature = await builder.submit_signed_transaction(
                vault_request.signed_transaction,
                last_valid_block_height=int(preparation["last_valid_block_height"]),
            )
            if observed_signature != tx_signature:
                raise CanonVaultActivationError(
                    "submitted signature does not match signed canonical bytes"
                )
        except SubmittedTransactionPending as exc:
            if exc.signature != tx_signature:
                raise CanonVaultActivationError(
                    "pending signature does not match signed canonical bytes"
                ) from exc
            submission_pending = True
        except SubmittedTransactionExpired as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Prepared canonical Vault transaction expired without confirmation.",
            ) from exc
        except SubmittedTransactionFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Canonical Vault transaction failed on-chain.",
            ) from exc

        confirm_canon_vault_activation(
            client=repo.client,
            preparation_id=vault_request.preparation_id,
            creator_wallet=current_user.wallet,
            tx_signature=tx_signature,
            prepared_message_hash=message_hash,
        )
        runtime_state = load_canon_climb_runtime_states(
            client=repo.client,
            climb_ids=[source.climb_id],
        ).get(str(source.climb_id))
        is_active = runtime_state == "active"
        if runtime_state not in {"active", "reserved"}:
            raise CanonVaultActivationError(
                "canonical Vault projection is not in an exact runtime state"
            )
    except HTTPException:
        raise
    except (CanonVaultActivationError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("[CanonVaultSubmit] exact submission failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Canonical Vault submission is pending reconciliation.",
        ) from exc

    activation_state = "active" if is_active else "pending"
    confirmation_status = (
        "finalized"
        if is_active
        else "pending" if submission_pending else "confirmed"
    )
    return CanonVaultSubmitResponse(
        preparation_id=vault_request.preparation_id,
        climb_id=source.climb_id,
        vault_id=int(preparation["vault_id"]),
        pda=str(preparation["vault_pda"]),
        tx_signature=tx_signature,
        activation_state=activation_state,
        projection_status=activation_state,
        confirmation_status=confirmation_status,
        message=(
            f"Vault for {source.name} is active."
            if is_active
            else f"Vault for {source.name} is being attached to the climb; do not retry."
        ),
    )


@router.post("/create/prepare", response_model=PreparedTransactionResponse)
@rate_limit(category="vault_creation")
async def prepare_create_vault(
    vault_request: CreateVaultRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Prepare a vault-creation transaction for wallet signing."""
    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy arbitrary-signature Vault creation is disabled for V4-B; "
                "use /vaults/create/canon/prepare."
            ),
        )
    if len(vault_request.signature_hex) != 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Signature must be 128 hex characters, got {len(vault_request.signature_hex)}",
        )

    try:
        bytes.fromhex(vault_request.signature_hex)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hex signature",
        )

    existing = await vault_repo.get_vault_by_signature(vault_request.signature_hex)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vault already exists for this climb: {existing.get('name')} (ID: {existing.get('id')})",
        )

    if vault_request.payment_method not in ("dung", "cal_usdc"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wallet-signed vault creation is currently only available for 'dung' or 'cal_usdc' payments.",
        )
    if vault_request.payment_method == "cal_usdc":
        _require_balance_rollout_action("create_vault_usdc")

    source_climb = await _resolve_reward_grade_vault_source(
        repo=repo,
        wallet=current_user.wallet,
        signature_hex=vault_request.signature_hex,
    )

    try:
        builder = get_tx_builder()
        build_kwargs = dict(
            user_wallet=current_user.wallet,
            signature_hex=vault_request.signature_hex,
            name=vault_request.name,
            vert_m=int(float(source_climb["vert_m"]) * 10),
            distance_m=int(round(float(source_climb["distance_m"]))),
            avg_gradient_pct=int(float(source_climb["avg_gradient_pct"]) * 100),
        )
        if vault_request.payment_method == "cal_usdc":
            result = await builder.build_create_vault_with_usdc_tx(**build_kwargs)
        else:
            result = await builder.build_create_vault_tx(**build_kwargs)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(f"[VaultCreatePrepare] Failed to build transaction: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare vault creation transaction.",
        ) from exc

    return _prepared_transaction_response(result)


@router.post("/create", response_model=CreateVaultResponse)
@rate_limit(category="vault_creation")
async def create_vault(
    vault_request: CreateVaultRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Create a new vault from a climb signature.

    Payment options:
    - 'dung': 100 DUNG (burned on-chain)
    - 'cal_usdc': 1,000 CAL + $2 USDC

    Requirements:
    - Signature must be 128 hex characters (64 bytes)
    - Name must be 3-64 characters
    - Positive vertical gain (detection algorithm is the quality gate)
    - Signature must not already exist as a vault
    - Requires a prepared wallet-signed transaction
    """
    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy arbitrary-signature Vault creation is disabled for V4-B; "
                "use /vaults/create/canon/submit."
            ),
        )

    # Validate signature format
    if len(vault_request.signature_hex) != 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Signature must be 128 hex characters, got {len(vault_request.signature_hex)}",
        )

    try:
        bytes.fromhex(vault_request.signature_hex)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid hex signature",
        )

    # Check if vault already exists with this signature
    existing = await vault_repo.get_vault_by_signature(vault_request.signature_hex)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Vault already exists for this climb: {existing.get('name')} (ID: {existing.get('id')})",
        )

    signature_hash = hashlib.sha256(bytes.fromhex(vault_request.signature_hex)).hexdigest()

    # On-chain vault creation
    # Two payment options per TOKENOMICS_PARAMETERS.md:
    # - dung: 100 DUNG burn
    # - cal_usdc: 1,000 CAL burn + $2 USDC transfer

    DUNG_COST = 100  # 100 DUNG (per TOKENOMICS_PARAMETERS.md)

    if vault_request.payment_method not in ("dung", "cal_usdc"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid payment method: {vault_request.payment_method}. Use 'dung' or 'cal_usdc'.",
        )
    if vault_request.payment_method == "cal_usdc":
        _require_balance_rollout_action("create_vault_usdc")

    source_climb = await _resolve_reward_grade_vault_source(
        repo=repo,
        wallet=current_user.wallet,
        signature_hex=vault_request.signature_hex,
    )

    config = solana_direct.load_default_config()

    if not vault_request.signed_transaction:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vault creation requires a prepared wallet-signed transaction.",
        )

    if vault_request.prepared_vault_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="prepared_vault_id is required when submitting a signed vault-creation transaction.",
        )

    builder = get_tx_builder()
    signed_tx = _decode_signed_transaction_or_400(vault_request.signed_transaction)
    last_valid_block_height = _require_last_valid_block_height(
        vault_request.last_valid_block_height
    )
    coordinator = _balance_coordinator(repo)
    operation: Optional[BalanceOperationRecord] = None

    try:
        build_kwargs = dict(
            user_wallet=current_user.wallet,
            signature_hex=vault_request.signature_hex,
            name=vault_request.name,
            vert_m=int(float(source_climb["vert_m"]) * 10),
            distance_m=int(round(float(source_climb["distance_m"]))),
            avg_gradient_pct=int(float(source_climb["avg_gradient_pct"]) * 100),
            blockhash=signed_tx.message.recent_blockhash,
            vault_id=vault_request.prepared_vault_id,
        )
        if vault_request.payment_method == "cal_usdc":
            expected_result = await builder.build_create_vault_with_usdc_tx(**build_kwargs)
            payment_msg = "CAL+USDC (1000 CAL burned, $2 USDC transferred)"
        else:
            expected_result = await builder.build_create_vault_tx(**build_kwargs)
            payment_msg = f"DUNG ({DUNG_COST} DUNG burned)"

        _assert_signed_transaction_matches(signed_tx, expected_result)
        operation_scope = VaultBalanceRouteScope(
            rider_account_id=current_user.user_id,
            protocol_wallet=current_user.wallet,
            vault_id=vault_request.prepared_vault_id,
            prepared_message_hash=prepared_message_hash(expected_result.transaction),
            tx_signature=_signed_transaction_signature(signed_tx),
            client_request_id=vault_request.client_request_id,
            metadata={
                "payment_method": vault_request.payment_method,
                "signature_hash": signature_hash,
                "last_valid_block_height": str(last_valid_block_height),
            },
        )
        operation = coordinator.prepare_operation(
            create_vault_intent(
                scope=operation_scope,
                amount="1000" if vault_request.payment_method == "cal_usdc" else str(DUNG_COST),
                payment_method=vault_request.payment_method,
                destination=expected_result.pda,
            )
        )
        await _record_balance_operation(coordinator, operation)
        submission = await submit_confirmed_balance_transaction(
            builder=builder,
            coordinator=coordinator,
            operation=operation,
            transaction_b64=vault_request.signed_transaction,
            last_valid_block_height=last_valid_block_height,
        )
        tx_signature = submission.signature
        operation = submission.operation
        await _record_balance_operation(coordinator, operation)
        result = {
            "vault_id": vault_request.prepared_vault_id,
            "pda": expected_result.pda,
            "tx_signature": tx_signature,
        }
    except HTTPException:
        raise
    except BalanceOperationError as e:
        raise _balance_operation_http_exception(e) from e
    except BalanceSubmissionError as e:
        logger.error(
            "[VaultCreate] Wallet transaction did not confirm: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="On-chain operation failed. Please try again.",
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        logger.error(f"[VaultCreate] Wallet-signed vault creation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="On-chain operation failed. Please try again.",
        ) from e

    projection_status = "pending"
    replay_job_id = None
    try:
        handoff = await vault_repo.stage_confirmed_vault_creation(
            vault_id=result["vault_id"],
            signature_hex=vault_request.signature_hex,
            signature_hash_hex=signature_hash,
            pda=result["pda"],
            signature_v2_hex=source_climb["signature_v2_hex"],
            start_lat=float(source_climb["start_lat"]),
            start_lon=float(source_climb["start_lon"]),
            end_lat=float(source_climb["end_lat"]),
            end_lon=float(source_climb["end_lon"]),
            creator_wallet=current_user.wallet,
            create_tx_signature=result["tx_signature"],
            source_climb_id=str(source_climb["id"]),
            operation_id=operation.operation_id if operation else None,
        )
        replay_job_id = handoff["job_id"]
        projection_status = (
            "recorded"
            if handoff["projection_ready"]
            else "pending"
        )
    except Exception as exc:
        if operation:
            operation = coordinator.mark_projection_delayed(operation, failure_reason=str(exc))
            await _record_balance_operation(coordinator, operation)
        projection_status = _operation_projection_status(operation)
        logger.error(
            "[VaultCreate] On-chain create tx=%s submitted but local persistence failed "
            "for vault_id=%s signature=%s: %s",
            result["tx_signature"],
            result["vault_id"],
            vault_request.signature_hex[:16],
            exc,
            exc_info=True,
        )

    logger.info(
        f"[VaultCreate] {current_user.user_id} created vault '{vault_request.name}' "
        f"(ID: {result['vault_id']}, tx: {result['tx_signature'][:16]}..., payment: {payment_msg})"
    )

    replay_suffix = " Historical replay queued." if replay_job_id else ""
    if projection_status in {"delayed", "needs_review"}:
        rider_state = _operation_rider_state(operation, "Pending")
        message = (
            f"Create Vault is {rider_state}. Payment: {payment_msg}. "
            "Boulder Roller is reconciling the local vault record; do not retry."
        )
    else:
        rider_state = (
            "Pending"
            if projection_status == "pending"
            else None
        )
        message = (
            f"Vault '{vault_request.name}' created! Payment: {payment_msg}."
            f"{replay_suffix} You are now the Local Legend."
        )

    return CreateVaultResponse(
        vault_id=result["vault_id"],
        name=vault_request.name,
        signature_hex=vault_request.signature_hex,
        pda=result["pda"],
        tx_signature=result["tx_signature"],
        minter=current_user.wallet,
        message=message,
        projection_status=projection_status,
        confirmation_status=_operation_confirmation_status(operation),
        rider_state=rider_state,
        operation_id=operation.operation_id if operation else None,
    )


# =============================================================================
# COMPLETIONS
# =============================================================================


@router.post("/{vault_id}/complete", response_model=CompletionResponse)
async def record_completion(
    vault_id: int,
    request: RecordCompletionRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Direct completion writes are retired; ride processing is canonical."""
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Direct vault completion recording is retired. "
            "Vault completions now come from canonical ride processing, replay, "
            "and on-chain activation flows."
        ),
    )


@router.get("/{vault_id}/leaderboard", response_model=RecordBoard)
async def get_vault_leaderboard(
    vault_id: int,
    vault_repo: VaultRepository = Depends(get_vault_repo),
    user_repo: UserRepository = Depends(get_user_repository),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
):
    """Get top 10 leaderboard for a vault."""
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    try:
        public_projection = await _project_public_vault_board(vault_repo, vault)
    except PublicRecordBoardPrivacyUnavailable as exc:
        raise _public_board_unavailable_http_exception() from exc
    entries, viewer_entry = await enrich_board(
        ClimbEffortRepository(vault_repo.client), public_projection,
        vault_signature=str(vault.get("signature_hex") or ""), viewer=current_user,
    )
    leaderboard = await _enrich_leaderboard_public_identity(
        [entry.model_dump(exclude_none=True) for entry in entries], user_repo)
    kom_holder, kom_time_s = admitted_kom(public_projection, entries)
    public_vault = {
        **vault,
        "kom_holder": kom_holder,
        "kom_time_s": kom_time_s,
    }
    board = _vault_record_board_response(vault_id, public_vault, leaderboard)
    board.viewer_entry = viewer_entry
    return board


# =============================================================================
# STAKING ("Claiming Territory")
# =============================================================================


@router.post("/{vault_id}/stake/prepare", response_model=PreparedTransactionResponse)
@rate_limit(category="staking")
async def prepare_stake_in_vault(
    vault_id: int,
    stake_request: StakeRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Prepare a vault stake transaction for wallet signing."""
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )
    _require_reward_authoritative_vault(vault)

    cal_amount_int = int(stake_request.cal_amount)
    if cal_amount_int != stake_request.cal_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CAL amount must be a whole number for on-chain staking",
        )
    cal_amount_on_chain = cal_amount_int * SPL_CAL_DECIMALS_MULTIPLIER

    try:
        result = await get_tx_builder().build_stake_tx(
            user_wallet=current_user.wallet,
            vault_id=int(vault["id"]),
            amount=cal_amount_on_chain,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(f"[VaultStakePrepare] Failed to build transaction: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare stake transaction.",
        ) from exc

    return _prepared_transaction_response(result)


@router.post("/{vault_id}/stake", response_model=StakeResponse)
@rate_limit(category="staking")
async def stake_in_vault(
    vault_id: int,
    stake_request: StakeRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Stake CAL in a vault to earn from distributions.

    Staking is framed as "claiming territory" - you're backing a climb
    you believe in and earning a share of the activity on that climb.

    Minimum stake: 100 CAL
    """
    _require_balance_rollout_action("deposit_cal")

    # Get vault
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )
    _require_reward_authoritative_vault(vault)

    # Check user has enough SPL CAL on-chain
    try:
        on_chain_cal = await solana_direct.get_cal_balance(current_user.wallet)
    except Exception as e:
        logger.warning(f"Failed to read SPL CAL for {current_user.user_id}: {scrub_log_text(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify SPL CAL balance right now.",
        ) from e

    if on_chain_cal < stake_request.cal_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Insufficient CAL: have {on_chain_cal}, need {int(stake_request.cal_amount)}",
        )

    tx_signature = None

    cal_amount_int = int(stake_request.cal_amount)
    if cal_amount_int != stake_request.cal_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CAL amount must be a whole number for on-chain staking",
        )
    cal_amount_on_chain = cal_amount_int * SPL_CAL_DECIMALS_MULTIPLIER
    deposited_cal = exact_token_amount(
        cal_amount_on_chain,
        field_name="cal_staked",
    )
    coordinator = _balance_coordinator(repo)
    operation: Optional[BalanceOperationRecord] = None

    if stake_request.signed_transaction:
        builder = get_tx_builder()
        signed_tx = _decode_signed_transaction_or_400(stake_request.signed_transaction)
        last_valid_block_height = _require_last_valid_block_height(
            stake_request.last_valid_block_height
        )
        try:
            expected_result = await builder.build_stake_tx(
                user_wallet=current_user.wallet,
                vault_id=int(vault["id"]),
                amount=cal_amount_on_chain,
                blockhash=signed_tx.message.recent_blockhash,
            )
            _assert_signed_transaction_matches(signed_tx, expected_result)
            operation_scope = VaultBalanceRouteScope(
                rider_account_id=current_user.user_id,
                protocol_wallet=current_user.wallet,
                vault_id=int(vault["id"]),
                vault_signature=vault["signature_hex"],
                prepared_message_hash=prepared_message_hash(expected_result.transaction),
                tx_signature=_signed_transaction_signature(signed_tx),
                client_request_id=stake_request.client_request_id,
                metadata={
                    "cal_amount": str(stake_request.cal_amount),
                    "last_valid_block_height": str(last_valid_block_height),
                },
            )
            operation = coordinator.prepare_operation(
                deposit_cal_intent(scope=operation_scope, amount=str(cal_amount_on_chain))
            )
            await _record_balance_operation(coordinator, operation)
            submission = await submit_confirmed_balance_transaction(
                builder=builder,
                coordinator=coordinator,
                operation=operation,
                transaction_b64=stake_request.signed_transaction,
                last_valid_block_height=last_valid_block_height,
            )
            tx_signature = submission.signature
            operation = submission.operation
            await _record_balance_operation(coordinator, operation)
        except HTTPException:
            raise
        except BalanceOperationError as e:
            raise _balance_operation_http_exception(e) from e
        except BalanceSubmissionError as e:
            logger.error(
                "[VaultStake] Wallet transaction did not confirm: %s",
                e,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="On-chain operation failed. Please try again.",
            ) from e
        except Exception as e:
            logger.error(f"[VaultStake] Wallet-signed staking failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="On-chain operation failed. Please try again.",
            ) from e
    else:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Staking requires a prepared wallet-signed transaction.",
        )

    if tx_signature:
        logger.info(
            f"[VaultStake] On-chain stake tx={tx_signature[:16]}... "
            f"for {current_user.user_id} in vault {vault['id']}"
        )

    # Execute stake atomically
    try:
        stake_result = repo.client.rpc(
            "stake_cal_with_cap",
            {
                "p_vault_signature": vault["signature_hex"],
                "p_wallet": current_user.wallet,
                "p_cal_amount": cal_amount_int,
                "p_per_vault_cap": None,
                "p_global_cap": None,
            }
        ).execute()

        if not stake_result.data:
            raise ValueError("Failed to stake - no result returned")

    except Exception as e:
        if tx_signature:
            if operation:
                operation = coordinator.mark_projection_delayed(operation, failure_reason=str(e))
                await _record_balance_operation(coordinator, operation)
            logger.error(
                "[VaultStake] On-chain stake tx=%s submitted but local projection failed "
                "for wallet=%s vault=%s: %s",
                tx_signature,
                current_user.user_id,
                vault["id"],
                scrub_log_text(e),
                exc_info=True,
            )
            return StakeResponse(
                vault_signature=vault["signature_hex"],
                cal_staked=deposited_cal.units,
                cal_staked_base_units=deposited_cal.base_units,
                lp_tokens_received=None,
                lp_tokens_received_base_units=None,
                total_position=None,
                total_position_base_units=None,
                tx_signature=tx_signature,
                stake=None,
                new_total_staked=None,
                new_total_staked_base_units=None,
                projection_status=_operation_projection_status(operation),
                confirmation_status=_operation_confirmation_status(operation),
                rider_state=_operation_rider_state(operation, "Pending"),
                operation_id=operation.operation_id if operation else None,
                message=(
                    "Deposit CAL is "
                    f"{_operation_rider_state(operation, 'Pending')}. "
                    "Boulder Roller is reconciling your position; do not retry."
                ),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e) if isinstance(e, ValueError) else "Staking failed. Please try again.",
        )

    # Only the indexed projection carries on-chain base units. A legacy shadow
    # row uses human-unit NUMERIC values and cannot stand in for this response.
    stake = await vault_repo.get_wallet_stake(vault["signature_hex"], current_user.wallet)
    stake_info = _build_vault_stake_info(stake) if stake else None
    total_position = (
        exact_token_amount(stake.get("cal_staked") or 0, field_name="total_position")
        if stake
        else None
    )
    total_stake = (
        await vault_repo.get_vault_total_stake(vault["signature_hex"])
        if stake
        else None
    )
    new_total_staked = (
        exact_token_amount(
            total_stake["total_cal_staked"],
            field_name="new_total_staked",
        )
        if total_stake is not None
        else None
    )

    logger.info(
        "[VaultStake] %s staked %s CAL in %s; indexed_position=%s",
        current_user.user_id,
        deposited_cal.units,
        vault["name"],
        stake_info.cal_staked if stake_info else "pending",
    )
    if operation:
        operation = coordinator.mark_projection_recorded(operation)
        await _record_balance_operation(coordinator, operation)

    return StakeResponse(
        vault_signature=vault["signature_hex"],
        cal_staked=deposited_cal.units,
        cal_staked_base_units=deposited_cal.base_units,
        lp_tokens_received=None,
        lp_tokens_received_base_units=None,
        total_position=total_position.units if total_position else None,
        total_position_base_units=total_position.base_units if total_position else None,
        tx_signature=tx_signature,
        stake=stake_info,
        new_total_staked=new_total_staked.units if new_total_staked else None,
        new_total_staked_base_units=(
            new_total_staked.base_units if new_total_staked else None
        ),
        confirmation_status=_operation_confirmation_status(operation),
        rider_state=_operation_rider_state(operation, None),
        operation_id=operation.operation_id if operation else None,
    )


def _pending_rewards_base_units(stake: Optional[dict]) -> int:
    """Exact unclaimed DUNG on a VaultStake; 0 for absent/invalid state."""
    if not stake:
        return 0
    try:
        return parse_base_units(
            stake.get("rewards_earned") or 0,
            field_name="rewards_earned",
        )
    except TokenAmountError:
        return 0


async def _resolve_exact_unstake_amount(
    *,
    vault_id: int,
    wallet: str,
    unstake_request: UnstakeRequest,
) -> tuple[ExactTokenAmount, dict]:
    """Resolve an exact requested amount against the canonical VaultStake account.

    Returns the exact LP amount together with the decoded on-chain stake so
    callers can compose collect-before-unstake without a second chain read.
    """
    try:
        config = solana_direct.load_readonly_config()
        stake = await solana_direct.get_vault_stake_account(config, vault_id, wallet)
    except Exception as exc:
        logger.error(
            "[VaultUnstake] Failed to load on-chain LP position for vault=%s wallet=%s: %s",
            vault_id,
            "[redacted]",
            scrub_log_text(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not load on-chain LP position.",
        ) from exc

    if stake is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active LP position exists for this vault.",
        )

    try:
        available_base_units = parse_base_units(
            stake.get("lp_tokens"),
            field_name="VaultStake.lp_tokens",
        )
    except TokenAmountError as exc:
        logger.error(
            "[VaultUnstake] Invalid on-chain LP position for vault=%s wallet=%s: %s",
            vault_id,
            "[redacted]",
            scrub_log_text(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not load on-chain LP position.",
        ) from exc

    if available_base_units == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active LP position exists for this vault.",
        )

    try:
        custody = await solana_direct.get_vault_lp_custody_observation(
            config,
            vault_id,
            wallet,
            available_base_units,
        )
    except Exception as exc:
        logger.error(
            "[VaultUnstake] Failed to verify LP custody for vault=%s wallet=%s: %s",
            vault_id,
            "[redacted]",
            scrub_log_text(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify the on-chain position.",
        ) from exc

    if not custody.sealed:
        logger.warning(
            "[VaultUnstake] Refusing unsealed LP position vault=%s wallet=%s "
            "status=%s recorded=%s observed=%s account=%s",
            vault_id,
            "[redacted]",
            custody.status,
            custody.recorded_lp_tokens,
            custody.amount_base_units,
            custody.token_account,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This position needs review before withdrawal.",
        )

    requested_base_units = (
        available_base_units
        if unstake_request.withdraw_all
        else parse_base_units(
            unstake_request.lp_amount_base_units,
            field_name="lp_amount_base_units",
            allow_zero=False,
        )
    )
    if requested_base_units > available_base_units:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Insufficient LP tokens: "
                f"have {available_base_units} base units, "
                f"requested {requested_base_units}."
            ),
        )

    return (
        exact_token_amount(requested_base_units, field_name="lp_amount_base_units"),
        stake,
    )


@router.post("/{vault_id}/unstake", response_model=UnstakeResponse)
@rate_limit(category="staking")
async def unstake_from_vault(
    vault_id: int,
    unstake_request: UnstakeRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Unstake LP tokens from a vault and receive CAL back.

    CAL is returned proportionally based on your LP share of the pool.

    Withdraw is a composed Balance action: when the on-chain VaultStake still
    carries unclaimed DUNG, the same atomic transaction collects those rewards
    before burning LP (protocol rule: collect first), so a withdraw can never
    forfeit pending DUNG.
    """
    _require_balance_rollout_action("withdraw_cal")

    # Get vault
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    if not unstake_request.signed_transaction:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unstaking requires a prepared wallet-signed transaction.",
        )

    withdrawn_lp, onchain_stake = await _resolve_exact_unstake_amount(
        vault_id=int(vault["id"]),
        wallet=current_user.wallet,
        unstake_request=unstake_request,
    )
    lp_amount_on_chain = int(withdrawn_lp.base_units)
    pending_rewards_base_units = _pending_rewards_base_units(onchain_stake)
    collect_rewards = pending_rewards_base_units > 0
    collect_fee_base_units = 0
    collect_net_base_units = 0
    if collect_rewards:
        harvest_fee_bps = await _get_harvest_fee_bps()
        collect_fee_base_units, collect_net_base_units = fee_split_base_units(
            pending_rewards_base_units,
            harvest_fee_bps,
        )
    collect_fields: dict = {}
    if collect_rewards:
        collected_net = exact_token_amount(
            collect_net_base_units, field_name="dung_collected"
        )
        collect_fields = {
            "dung_collected_total_base_units": str(pending_rewards_base_units),
            "dung_collect_fee_base_units": str(collect_fee_base_units),
            "dung_collected": collected_net.units,
            "dung_collected_base_units": collected_net.base_units,
        }
    tx_signature = None
    coordinator = _balance_coordinator(repo)
    operation: Optional[BalanceOperationRecord] = None

    if unstake_request.signed_transaction:
        builder = get_tx_builder()
        signed_tx = _decode_signed_transaction_or_400(unstake_request.signed_transaction)
        last_valid_block_height = _require_last_valid_block_height(
            unstake_request.last_valid_block_height
        )
        try:
            expected_result = await builder.build_unstake_tx(
                user_wallet=current_user.wallet,
                vault_id=int(vault["id"]),
                lp_amount=lp_amount_on_chain,
                blockhash=signed_tx.message.recent_blockhash,
                collect_rewards=collect_rewards,
            )
            _assert_signed_transaction_matches(signed_tx, expected_result)
            operation_scope = VaultBalanceRouteScope(
                rider_account_id=current_user.user_id,
                protocol_wallet=current_user.wallet,
                vault_id=int(vault["id"]),
                vault_signature=vault["signature_hex"],
                prepared_message_hash=prepared_message_hash(expected_result.transaction),
                tx_signature=_signed_transaction_signature(signed_tx),
                client_request_id=unstake_request.client_request_id,
                metadata={
                    "lp_amount_base_units": withdrawn_lp.base_units,
                    "withdraw_all": str(unstake_request.withdraw_all).lower(),
                    "last_valid_block_height": str(last_valid_block_height),
                    "composed_collect_dung": str(collect_rewards).lower(),
                    "collect_dung_total_base_units": str(pending_rewards_base_units),
                    "collect_dung_net_base_units": str(collect_net_base_units),
                },
            )
            operation = coordinator.prepare_operation(
                withdraw_cal_intent(scope=operation_scope, amount=str(lp_amount_on_chain))
            )
            await _record_balance_operation(coordinator, operation)
            submission = await submit_confirmed_balance_transaction(
                builder=builder,
                coordinator=coordinator,
                operation=operation,
                transaction_b64=unstake_request.signed_transaction,
                last_valid_block_height=last_valid_block_height,
            )
            tx_signature = submission.signature
            operation = submission.operation
            await _record_balance_operation(coordinator, operation)
        except HTTPException:
            raise
        except BalanceOperationError as e:
            raise _balance_operation_http_exception(e) from e
        except BalanceSubmissionError as e:
            logger.error(
                "[VaultUnstake] Wallet transaction did not confirm: %s",
                e,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="On-chain operation failed. Please try again.",
            ) from e
        except Exception as e:
            logger.error(f"[VaultUnstake] Wallet-signed unstaking failed: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="On-chain operation failed. Please try again.",
            ) from e
    if tx_signature:
        logger.info(
            f"[VaultUnstake] On-chain unstake tx={tx_signature[:16]}... "
            f"for {current_user.user_id} in vault {vault['id']}"
        )

    try:
        result = await vault_repo.unstake_cal(
            vault_signature=vault["signature_hex"],
            wallet=current_user.wallet,
            lp_amount=withdrawn_lp.units,
        )
    except ValueError as e:
        if tx_signature:
            if operation:
                operation = coordinator.mark_projection_delayed(operation, failure_reason=str(e))
                await _record_balance_operation(coordinator, operation)
            logger.error(
                "[VaultUnstake] On-chain unstake tx=%s submitted but local projection failed for user_id=%s vault=%s: %s",
                tx_signature,
                current_user.user_id,
                vault["id"],
                scrub_log_text(e),
                exc_info=True,
            )
            return UnstakeResponse(
                vault_signature=vault["signature_hex"],
                lp_burned=withdrawn_lp.units,
                lp_burned_base_units=withdrawn_lp.base_units,
                cal_returned=None,
                cal_returned_base_units=None,
                tx_signature=tx_signature,
                projection_status=_operation_projection_status(operation),
                confirmation_status=_operation_confirmation_status(operation),
                rider_state=_operation_rider_state(operation, "Pending"),
                operation_id=operation.operation_id if operation else None,
                message=(
                    "Withdraw CAL is "
                    f"{_operation_rider_state(operation, 'Pending')}. "
                    "Boulder Roller is reconciling your position; do not retry."
                ),
                **collect_fields,
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        if tx_signature:
            if operation:
                operation = coordinator.mark_projection_delayed(operation, failure_reason=str(e))
                await _record_balance_operation(coordinator, operation)
            logger.error(
                "[VaultUnstake] On-chain unstake tx=%s submitted but local projection failed for user_id=%s vault=%s: %s",
                tx_signature,
                current_user.user_id,
                vault["id"],
                scrub_log_text(e),
                exc_info=True,
            )
            return UnstakeResponse(
                vault_signature=vault["signature_hex"],
                lp_burned=withdrawn_lp.units,
                lp_burned_base_units=withdrawn_lp.base_units,
                cal_returned=None,
                cal_returned_base_units=None,
                tx_signature=tx_signature,
                projection_status=_operation_projection_status(operation),
                confirmation_status=_operation_confirmation_status(operation),
                rider_state=_operation_rider_state(operation, "Pending"),
                operation_id=operation.operation_id if operation else None,
                message=(
                    "Withdraw CAL is "
                    f"{_operation_rider_state(operation, 'Pending')}. "
                    "Boulder Roller is reconciling your position; do not retry."
                ),
                **collect_fields,
            )
        raise

    logger.info(
        "[VaultUnstake] %s unstaked %s LP (%s base units) from %s; "
        "local projection returned %s CAL",
        current_user.user_id,
        withdrawn_lp.units,
        withdrawn_lp.base_units,
        vault["name"],
        result.get("cal_returned"),
    )
    if operation:
        operation = coordinator.mark_projection_recorded(operation)
        await _record_balance_operation(coordinator, operation)

    return UnstakeResponse(
        vault_signature=vault["signature_hex"],
        lp_burned=withdrawn_lp.units,
        lp_burned_base_units=withdrawn_lp.base_units,
        cal_returned=None,
        cal_returned_base_units=None,
        tx_signature=tx_signature,
        confirmation_status=_operation_confirmation_status(operation),
        rider_state=_operation_rider_state(operation, None),
        operation_id=operation.operation_id if operation else None,
        **collect_fields,
    )


# =============================================================================
# HARVEST REWARDS
# =============================================================================

async def _get_harvest_fee_bps() -> Decimal:
    """Read the live harvest fee from ProgramConfig, falling back to launch default."""
    try:
        program_config = await solana_direct.get_program_config_account(
            solana_direct.load_default_config()
        )
    except Exception as exc:
        logger.warning("[VaultHarvest] Failed to read ProgramConfig harvest fee: %s", exc)
        program_config = None

    if not program_config:
        return Decimal(solana_direct.HARVEST_FEE_BPS)

    fee_bps = program_config.get("harvest_fee_bps")
    if fee_bps is None:
        return Decimal(solana_direct.HARVEST_FEE_BPS)
    return Decimal(str(fee_bps))


async def _get_exit_fee_bps() -> Decimal:
    """Read the immutable Anchor exit fee through the ProgramConfig projection."""
    try:
        program_config = await solana_direct.get_program_config_account(
            solana_direct.load_default_config()
        )
    except Exception as exc:
        logger.warning("[VaultUnstake] Failed to read ProgramConfig exit fee: %s", exc)
        program_config = None

    if not program_config:
        return Decimal(solana_direct.EXIT_FEE_BPS)

    fee_bps = program_config.get("exit_fee_bps")
    if fee_bps is None:
        return Decimal(solana_direct.EXIT_FEE_BPS)
    return Decimal(str(fee_bps))


def _get_full_withdrawal_quote_base_units(
    *,
    vault: dict,
    stake: dict,
    custody: solana_direct.VaultLpCustodyObservation,
    exit_fee_bps: Decimal,
) -> tuple[int, int, int]:
    """Mirror Anchor's full-LP redemption and exit-fee floor from live state."""
    lp_amount = parse_base_units(
        stake.get("lp_tokens"),
        field_name="VaultStake.lp_tokens",
        allow_zero=False,
    )
    total_cal_staked = parse_base_units(
        vault.get("total_cal_staked"),
        field_name="Vault.total_cal_staked",
        allow_zero=False,
    )
    total_lp_supply = custody.lp_supply_base_units
    if not custody.sealed or total_lp_supply is None or total_lp_supply <= 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify the on-chain position.",
        )

    withdrawal_amount = lp_amount * total_cal_staked // total_lp_supply
    fee_amount, net_amount = fee_split_base_units(
        withdrawal_amount,
        exit_fee_bps,
    )
    return withdrawal_amount, fee_amount, net_amount


@router.post("/{vault_id}/unstake/prepare", response_model=PreparedTransactionResponse)
@rate_limit(category="staking")
async def prepare_unstake_from_vault(
    vault_id: int,
    unstake_request: UnstakeRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Prepare a vault unstake transaction for wallet signing.

    Withdraw composes collect-before-unstake: when the on-chain position still
    carries unclaimed DUNG, the prepared transaction collects it atomically
    before burning LP, so a withdraw can never forfeit pending DUNG.
    """
    _require_balance_rollout_action("withdraw_cal")

    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    withdrawn_lp, onchain_stake = await _resolve_exact_unstake_amount(
        vault_id=int(vault["id"]),
        wallet=current_user.wallet,
        unstake_request=unstake_request,
    )
    collect_rewards = _pending_rewards_base_units(onchain_stake) > 0

    try:
        result = await get_tx_builder().build_unstake_tx(
            user_wallet=current_user.wallet,
            vault_id=int(vault["id"]),
            lp_amount=int(withdrawn_lp.base_units),
            collect_rewards=collect_rewards,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(f"[VaultUnstakePrepare] Failed to build transaction: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare unstake transaction.",
        ) from exc

    return _prepared_transaction_response(result)


@router.get("/{vault_id}/pending-rewards", response_model=PendingRewardsResponse)
async def get_vault_pending_rewards(
    vault_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
):
    """
    Get claimable on-chain staking rewards for the current user in a vault.

    Record Royalty and Local Legend rewards mint immediately at settlement and
    never appear here. This endpoint only surfaces unharvested VaultStake
    rewards_earned balance.
    """
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    harvest_fee_bps = await _get_harvest_fee_bps()
    exit_fee_bps = await _get_exit_fee_bps()

    try:
        _, onchain_vault, stake, custody = await _get_onchain_vault_position(
            vault_id,
            current_user.wallet,
        )
    except HTTPException as exc:
        if exc.status_code != status.HTTP_400_BAD_REQUEST:
            raise
        return PendingRewardsResponse(
            vault_signature=vault["signature_hex"],
            vault_name=vault["name"],
            pending_rewards=[],
            total_pending="0",
            total_pending_base_units="0",
            fee_estimate="0",
            fee_estimate_base_units="0",
            net_estimate="0",
            net_estimate_base_units="0",
            harvest_fee_bps=str(harvest_fee_bps),
            exit_fee_bps=str(exit_fee_bps),
        )

    withdrawal_amount, withdrawal_fee, withdrawal_net = (
        _get_full_withdrawal_quote_base_units(
            vault=onchain_vault,
            stake=stake,
            custody=custody,
            exit_fee_bps=exit_fee_bps,
        )
    )

    total_pending_base_units = parse_base_units(
        stake.get("rewards_earned") or 0,
        field_name="rewards_earned",
    )
    total_pending = exact_token_amount(
        total_pending_base_units,
        field_name="rewards_earned",
    )
    pending_rewards = (
        [
            PendingRewardEntry(
                epoch=int(vault.get("last_distribution_epoch") or 0),
                receipt_type="STAKE_CLAIMABLE",
                amount=total_pending.units,
                amount_base_units=total_pending.base_units,
                rank=None,
            )
        ]
        if total_pending_base_units > 0
        else []
    )

    fee_base_units, net_base_units = fee_split_base_units(
        total_pending_base_units,
        harvest_fee_bps,
    )
    fee_estimate = exact_token_amount(fee_base_units, field_name="fee_estimate")
    net_estimate = exact_token_amount(net_base_units, field_name="net_estimate")

    return PendingRewardsResponse(
        vault_signature=vault["signature_hex"],
        vault_name=vault["name"],
        pending_rewards=pending_rewards,
        total_pending=total_pending.units,
        total_pending_base_units=total_pending.base_units,
        fee_estimate=fee_estimate.units,
        fee_estimate_base_units=fee_estimate.base_units,
        net_estimate=net_estimate.units,
        net_estimate_base_units=net_estimate.base_units,
        harvest_fee_bps=str(harvest_fee_bps),
        exit_fee_bps=str(exit_fee_bps),
        lp_tokens_base_units=str(stake.get("lp_tokens")),
        withdrawal_amount_base_units=str(withdrawal_amount),
        withdrawal_fee_base_units=str(withdrawal_fee),
        withdrawal_net_base_units=str(withdrawal_net),
    )


@router.post("/{vault_id}/harvest/prepare", response_model=PreparedTransactionResponse)
@rate_limit(category="staking")
async def prepare_harvest_vault_rewards(
    vault_id: int,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
):
    """Prepare a harvest transaction for wallet signing."""
    _require_balance_rollout_action("collect_dung")

    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    await _get_onchain_claimable_stake_rewards(vault_id, current_user.wallet)

    try:
        result = await get_tx_builder().build_harvest_tx(
            user_wallet=current_user.wallet,
            vault_id=int(vault["id"]),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error(f"[VaultHarvestPrepare] Failed to build transaction: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to prepare harvest transaction.",
        ) from exc

    return _prepared_transaction_response(result)


@router.post("/{vault_id}/harvest", response_model=HarvestResponse)
@rate_limit(category="staking")
async def harvest_vault_rewards(
    vault_id: int,
    request: Request,
    harvest_request: Optional[HarvestRequest] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    vault_repo: VaultRepository = Depends(get_vault_repo),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Harvest pending rewards from a vault.

    This claims all unharvested on-chain VaultStake rewards for the user.
    The live ProgramConfig harvest fee is taken.

    On-chain harvest_rewards instruction mints DUNG to user.
    Harvest fee goes to protocol treasury.
    """
    _require_balance_rollout_action("collect_dung")

    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vault not found",
        )

    vault_signature = vault["signature_hex"]

    _, stake = await _get_onchain_claimable_stake_rewards(vault_id, current_user.wallet)

    total_harvested_base_units = parse_base_units(
        stake.get("rewards_earned") or 0,
        field_name="rewards_earned",
    )

    harvest_fee_bps = await _get_harvest_fee_bps()
    fee_amount_base_units, net_received_base_units = fee_split_base_units(
        total_harvested_base_units,
        harvest_fee_bps,
    )
    total_harvested = exact_token_amount(
        total_harvested_base_units,
        field_name="total_harvested",
    )
    fee_amount = exact_token_amount(fee_amount_base_units, field_name="fee_amount")
    net_received = exact_token_amount(net_received_base_units, field_name="net_received")

    builder = get_tx_builder()
    coordinator = _balance_coordinator(repo)
    operation: Optional[BalanceOperationRecord] = None

    try:
        if harvest_request and harvest_request.signed_transaction:
            signed_tx = _decode_signed_transaction_or_400(harvest_request.signed_transaction)
            last_valid_block_height = _require_last_valid_block_height(
                harvest_request.last_valid_block_height
            )
            expected_result = await builder.build_harvest_tx(
                user_wallet=current_user.wallet,
                vault_id=int(vault["id"]),
                blockhash=signed_tx.message.recent_blockhash,
            )
            _assert_signed_transaction_matches(signed_tx, expected_result)
            submission_payload = harvest_request.signed_transaction
            prepared_tx_signature = _signed_transaction_signature(signed_tx)
            client_request_id = harvest_request.client_request_id
        else:
            expected_result = await builder.build_harvest_tx(
                user_wallet=current_user.wallet,
                vault_id=int(vault["id"]),
            )
            submission_payload = expected_result.transaction
            last_valid_block_height = expected_result.last_valid_block_height
            prepared_tx_signature = None
            client_request_id = harvest_request.client_request_id if harvest_request else None

        operation_scope = VaultBalanceRouteScope(
            rider_account_id=current_user.user_id,
            protocol_wallet=current_user.wallet,
            vault_id=int(vault["id"]),
            vault_signature=vault_signature,
            prepared_message_hash=prepared_message_hash(expected_result.transaction),
            tx_signature=prepared_tx_signature,
            client_request_id=client_request_id,
            metadata={
                "last_valid_block_height": str(last_valid_block_height),
            },
        )
        if not expected_result.pda:
            raise RuntimeError("Collect DUNG transaction is missing its destination token account")
        operation = coordinator.prepare_operation(
            collect_dung_intent(
                scope=operation_scope,
                amount=net_received.base_units,
                destination=expected_result.pda,
                fee_payer=_builder_fee_payer(builder),
            )
        )
        await _record_balance_operation(coordinator, operation)
        submission = await submit_confirmed_balance_transaction(
            builder=builder,
            coordinator=coordinator,
            operation=operation,
            transaction_b64=submission_payload,
            last_valid_block_height=last_valid_block_height,
        )
        tx_signature = submission.signature
        operation = submission.operation
        await _record_balance_operation(coordinator, operation)
        operation = coordinator.mark_projection_recorded(operation)
        await _record_balance_operation(coordinator, operation)

        logger.info(
            f"[VaultHarvest] {current_user.user_id} harvested "
            f"{net_received.units} DUNG from {vault['name']} "
            f"(fee: {fee_amount.units}, tx: {tx_signature[:16] if tx_signature else 'N/A'})"
        )

    except HTTPException:
        raise
    except BalanceOperationError as e:
        raise _balance_operation_http_exception(e) from e
    except BalanceSubmissionError as e:
        logger.error(
            "[VaultHarvest] Wallet transaction did not confirm: %s",
            e,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="On-chain operation failed. Please try again.",
        ) from e
    except Exception as e:
        if operation:
            operation = coordinator.mark_failed(operation, reason=str(e))
            await _record_balance_operation(coordinator, operation)
        logger.error(f"[VaultHarvest] On-chain harvest failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="On-chain operation failed. Please try again.",
        ) from e

    return HarvestResponse(
        vault_signature=vault_signature,
        vault_name=vault["name"],
        total_harvested=total_harvested.units,
        total_harvested_base_units=total_harvested.base_units,
        fee_amount=fee_amount.units,
        fee_amount_base_units=fee_amount.base_units,
        net_received=net_received.units,
        net_received_base_units=net_received.base_units,
        destination_token_account=expected_result.pda,
        receipts_count=1,
        tx_signature=tx_signature,
        confirmation_status=_operation_confirmation_status(operation),
        rider_state=_operation_rider_state(operation, "Collected"),
        operation_id=operation.operation_id if operation else None,
        message="Collect DUNG complete.",
    )


# =============================================================================
# ADMIN: VAULT ACTIVATION (on-chain seeding)
# =============================================================================


class SeedActivateResponse(BaseModel):
    """Response for single vault seed+activate."""
    vault_id: int
    vault_name: str
    success: bool
    seed_tx: Optional[str] = None
    leaderboard_tx: Optional[str] = None
    activate_tx: Optional[str] = None
    error: Optional[str] = None
    duration_ms: int = 0


class ActivationStatusResponse(BaseModel):
    """Response for vault activation status query."""
    vault_id: int
    vault_name: Optional[str] = None
    on_chain_seeding_status: Optional[str] = None
    on_chain_seed_tx: Optional[str] = None
    on_chain_leaderboard_tx: Optional[str] = None
    on_chain_activate_tx: Optional[str] = None
    on_chain_seeded_at: Optional[str] = None
    on_chain_activated_at: Optional[str] = None
    on_chain_seeding_error: Optional[str] = None


class BatchSeedActivateResponse(BaseModel):
    """Response for batch seed+activate."""
    total_processed: int
    succeeded: int
    failed: int
    results: List[SeedActivateResponse]


def _get_activation_service(db_client):
    """
    Build a VaultActivationService from environment config.

    Raises ValueError if the Solana keypair is not configured.
    """
    from solders.pubkey import Pubkey

    from ..solana_direct import load_backend_authority_keypair, load_default_config
    from ..solana_env import boulder_rollers_program_id
    from ..services.vault_activation_service import VaultActivationService

    try:
        authority = load_backend_authority_keypair()
        fee_payer = load_default_config().payer
        program_id = Pubkey.from_string(boulder_rollers_program_id())
    except Exception as exc:
        raise ValueError(
            "Solana backend authority / payer not configured - cannot inspect activation authority"
        ) from exc

    return VaultActivationService(
        supabase_client=db_client,
        authority_keypair=authority,
        fee_payer_keypair=fee_payer,
        program_id=program_id,
    )


@router.post("/{vault_id}/seed-activate", response_model=SeedActivateResponse)
@rate_limit(category="general")
async def admin_seed_activate_vault(
    vault_id: int,
    request: Request,
    admin_ctx=Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Verify that a single vault already has sealed generation-2 activation evidence.

    This compatibility endpoint cannot write historical seed state or activate a
    vault. Legacy and incomplete evidence fail closed.
    """
    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy seed/activate is disabled for V4-B; exact canon "
                "Climb/Vault finalization is the only activation path."
            ),
        )
    try:
        activation_service = _get_activation_service(repo.client)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # Look up vault to get signature_hex
    vault_repo = VaultRepository(repo.client)
    vault = await vault_repo.get_vault_by_id(vault_id)
    if not vault:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vault {vault_id} not found",
        )

    result = await activation_service.seed_and_activate_vault(
        vault_id=vault_id,
        vault_signature_hex=vault["signature_hex"],
    )

    return SeedActivateResponse(
        vault_id=result.vault_id,
        vault_name=result.vault_name,
        success=result.success,
        seed_tx=result.seed_tx,
        leaderboard_tx=result.leaderboard_tx,
        activate_tx=result.activate_tx,
        error=result.error,
        duration_ms=result.duration_ms,
    )


@router.get("/{vault_id}/activation-status", response_model=ActivationStatusResponse)
@rate_limit(category="general")
async def get_vault_activation_status(
    vault_id: int,
    request: Request,
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get on-chain seeding/activation status for a vault.

    No admin auth required — status is informational.
    """
    status_data = repo.client.from_("indexed_vaults") \
        .select(
            "id, name, on_chain_seeding_status, "
            "on_chain_seed_tx, on_chain_leaderboard_tx, on_chain_activate_tx, "
            "on_chain_seeded_at, on_chain_activated_at, on_chain_seeding_error"
        ) \
        .eq("id", vault_id) \
        .execute()

    if not status_data.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vault {vault_id} not found",
        )

    row = status_data.data[0]
    return ActivationStatusResponse(
        vault_id=row["id"],
        vault_name=row.get("name"),
        on_chain_seeding_status=row.get("on_chain_seeding_status", "pending"),
        on_chain_seed_tx=row.get("on_chain_seed_tx"),
        on_chain_leaderboard_tx=row.get("on_chain_leaderboard_tx"),
        on_chain_activate_tx=row.get("on_chain_activate_tx"),
        on_chain_seeded_at=row.get("on_chain_seeded_at"),
        on_chain_activated_at=row.get("on_chain_activated_at"),
        on_chain_seeding_error=row.get("on_chain_seeding_error"),
    )


@router.post("/seed-activate-all", response_model=BatchSeedActivateResponse)
@rate_limit(category="general")
async def admin_seed_activate_all(
    request: Request,
    admin_ctx=Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Batch-check vaults selected by the legacy operational queue.

    This compatibility endpoint can verify sealed generation-2 activations but
    cannot write seed state or perform one-way activation.
    """
    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy seed/activate is disabled for V4-B; exact canon "
                "Climb/Vault finalization is the only activation path."
            ),
        )
    try:
        activation_service = _get_activation_service(repo.client)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    results = await activation_service.seed_and_activate_all_pending()

    succeeded = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    return BatchSeedActivateResponse(
        total_processed=len(results),
        succeeded=succeeded,
        failed=failed,
        results=[
            SeedActivateResponse(
                vault_id=r.vault_id,
                vault_name=r.vault_name,
                success=r.success,
                seed_tx=r.seed_tx,
                leaderboard_tx=r.leaderboard_tx,
                activate_tx=r.activate_tx,
                error=r.error,
                duration_ms=r.duration_ms,
            )
            for r in results
        ],
    )
