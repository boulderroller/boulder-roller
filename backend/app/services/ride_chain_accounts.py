"""RPC reader and strict decoders for ride-economic Anchor accounts."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Sequence, Union

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from solders.pubkey import Pubkey


class ChainAccountUnavailableError(RuntimeError):
    """An existing account could not be fetched or decoded yet."""


class ChainAccountMismatchError(ValueError):
    """A readable account conflicts with the frozen economic plan."""


class LegacyCompletionEvidenceError(ChainAccountMismatchError):
    """A V1 receipt proves identity but cannot prove the exact tribute amount."""


@dataclass(frozen=True)
class ChainAccount:
    owner: Pubkey
    data: bytes


@dataclass(frozen=True)
class FinalizedChainSnapshot:
    """One atomic finalized-slot observation across all economic PDAs."""

    slot: int
    accounts: tuple[Optional[ChainAccount], ...]


@dataclass(frozen=True)
class RideAttestationAccount:
    rider: Pubkey
    ride_hash: bytes
    attestation_commitment: bytes
    parser_version: int
    source_kind: int
    completed_at: int
    started_at: int
    total_tss: int
    total_distance_m: int
    total_vert_m: int
    cal_earned: int
    climbs_crossed: int
    attester: Pubkey
    settled_at: int
    settled_slot: int
    economic_epoch: int
    finalized: bool
    bump: int


@dataclass(frozen=True)
class HeldRideReleaseAuthorityAccount:
    ride_attestation: Pubkey
    rider: Pubkey
    threshold_authority_id: bytes
    threshold_authority_commitment: bytes
    threshold_effective_at: int
    threshold_w: int
    threshold_policy_version: int
    economic_tss: int
    cal_earned: int
    cal_tribute_budget: int
    release_plan_hash: bytes
    released_at: int
    released_slot: int
    release_settlement_week: int
    attester: Pubkey
    bump: int


@dataclass(frozen=True)
class CalMintReceiptAccount:
    ride_attestation: Pubkey
    rider: Pubkey
    amount: int
    bump: int


@dataclass(frozen=True)
class ReleasedCalMintReceiptAccount:
    ride_attestation: Pubkey
    release_authority: Pubkey
    rider: Pubkey
    amount: int
    release_settlement_week: int
    bump: int


@dataclass(frozen=True)
class ClimbCompletionReceiptAccount:
    ride_attestation: Pubkey
    vault: Pubkey
    completion_evidence_hash: bytes
    bump: int


@dataclass(frozen=True)
class ClimbCompletionReceiptV2Account:
    ride_attestation: Pubkey
    vault: Pubkey
    evidence_version: int
    cal_tributed: int
    completion_evidence_hash: bytes
    bump: int


@dataclass(frozen=True)
class ReleasedClimbCompletionReceiptAccount:
    ride_attestation: Pubkey
    release_authority: Pubkey
    vault: Pubkey
    evidence_version: int
    cal_tributed: int
    completion_evidence_hash: bytes
    credited_settlement_week: int
    bump: int


ClimbCompletionReceipt = Union[
    ClimbCompletionReceiptAccount,
    ClimbCompletionReceiptV2Account,
]


AccountReader = Callable[[str, Pubkey], Awaitable[Optional[ChainAccount]]]
FinalizedSnapshotReader = Callable[
    [str, Sequence[Pubkey]], Awaitable[FinalizedChainSnapshot]
]


async def read_finalized_chain_snapshot(
    rpc_url: str,
    addresses: Sequence[Pubkey],
) -> FinalizedChainSnapshot:
    """Fetch every address in one finalized RPC context."""
    requested = tuple(addresses)
    try:
        async with AsyncClient(rpc_url, commitment=Finalized) as client:
            response = await client.get_multiple_accounts(list(requested))
    except Exception as exc:
        raise ChainAccountUnavailableError(
            f"finalized ride economic account snapshot is unavailable: {exc}"
        ) from exc

    values = tuple(response.value)
    if len(values) != len(requested):
        raise ChainAccountUnavailableError(
            "finalized ride economic account snapshot is incomplete"
        )
    accounts = tuple(
        None
        if value is None
        else ChainAccount(
            owner=Pubkey.from_string(str(value.owner)),
            data=bytes(value.data),
        )
        for value in values
    )
    return FinalizedChainSnapshot(
        slot=int(response.context.slot),
        accounts=accounts,
    )


async def read_chain_account(rpc_url: str, address: Pubkey) -> Optional[ChainAccount]:
    """Fetch one finalized account; RPC failures and missing data are retryable."""
    try:
        async with AsyncClient(rpc_url, commitment=Finalized) as client:
            response = await client.get_account_info(address)
    except Exception as exc:
        raise ChainAccountUnavailableError(
            f"chain account {address} is unavailable: {exc}"
        ) from exc
    if response.value is None:
        return None
    return ChainAccount(
        owner=Pubkey.from_string(str(response.value.owner)),
        data=bytes(response.value.data),
    )


def _discriminator(name: str) -> bytes:
    return hashlib.sha256(f"account:{name}".encode("utf-8")).digest()[:8]


def _validated_layout(data: bytes, *, name: str, size: int) -> memoryview:
    if len(data) != size:
        raise ChainAccountMismatchError(
            f"{name} account layout mismatch: expected {size} bytes, got {len(data)}"
        )
    if data[:8] != _discriminator(name):
        raise ChainAccountMismatchError(
            f"{name} account discriminator does not match"
        )
    return memoryview(data)


def decode_ride_attestation(data: bytes) -> RideAttestationAccount:
    view = _validated_layout(data, name="RideAttestation", size=205)
    offset = 8

    def take(size: int) -> bytes:
        nonlocal offset
        value = bytes(view[offset : offset + size])
        offset += size
        return value

    rider = Pubkey.from_bytes(take(32))
    ride_hash = take(32)
    commitment = take(32)
    parser_version = struct.unpack("<I", take(4))[0]
    source_kind = struct.unpack("<B", take(1))[0]
    completed_at = struct.unpack("<q", take(8))[0]
    started_at = struct.unpack("<q", take(8))[0]
    total_tss = struct.unpack("<I", take(4))[0]
    total_distance_m = struct.unpack("<I", take(4))[0]
    total_vert_m = struct.unpack("<I", take(4))[0]
    cal_earned = struct.unpack("<Q", take(8))[0]
    climbs_crossed = struct.unpack("<H", take(2))[0]
    attester = Pubkey.from_bytes(take(32))
    settled_at = struct.unpack("<q", take(8))[0]
    settled_slot = struct.unpack("<Q", take(8))[0]
    economic_epoch = struct.unpack("<Q", take(8))[0]
    finalized = struct.unpack("<?", take(1))[0]
    bump = struct.unpack("<B", take(1))[0]
    return RideAttestationAccount(
        rider=rider,
        ride_hash=ride_hash,
        attestation_commitment=commitment,
        parser_version=parser_version,
        source_kind=source_kind,
        completed_at=completed_at,
        started_at=started_at,
        total_tss=total_tss,
        total_distance_m=total_distance_m,
        total_vert_m=total_vert_m,
        cal_earned=cal_earned,
        climbs_crossed=climbs_crossed,
        attester=attester,
        settled_at=settled_at,
        settled_slot=settled_slot,
        economic_epoch=economic_epoch,
        finalized=finalized,
        bump=bump,
    )


def decode_held_ride_release_authority(
    data: bytes,
) -> HeldRideReleaseAuthorityAccount:
    view = _validated_layout(data, name="HeldRideReleaseAuthority", size=240)
    offset = 8

    def take(size: int) -> bytes:
        nonlocal offset
        value = bytes(view[offset : offset + size])
        offset += size
        return value

    return HeldRideReleaseAuthorityAccount(
        ride_attestation=Pubkey.from_bytes(take(32)),
        rider=Pubkey.from_bytes(take(32)),
        threshold_authority_id=take(16),
        threshold_authority_commitment=take(32),
        threshold_effective_at=struct.unpack("<q", take(8))[0],
        threshold_w=struct.unpack("<H", take(2))[0],
        threshold_policy_version=struct.unpack("<B", take(1))[0],
        economic_tss=struct.unpack("<I", take(4))[0],
        cal_earned=struct.unpack("<Q", take(8))[0],
        cal_tribute_budget=struct.unpack("<Q", take(8))[0],
        release_plan_hash=take(32),
        released_at=struct.unpack("<q", take(8))[0],
        released_slot=struct.unpack("<Q", take(8))[0],
        release_settlement_week=struct.unpack("<Q", take(8))[0],
        attester=Pubkey.from_bytes(take(32)),
        bump=struct.unpack("<B", take(1))[0],
    )


def decode_cal_mint_receipt(data: bytes) -> CalMintReceiptAccount:
    view = _validated_layout(data, name="CalMintReceipt", size=81)
    return CalMintReceiptAccount(
        ride_attestation=Pubkey.from_bytes(bytes(view[8:40])),
        rider=Pubkey.from_bytes(bytes(view[40:72])),
        amount=struct.unpack("<Q", view[72:80])[0],
        bump=struct.unpack("<B", view[80:81])[0],
    )


def decode_released_cal_mint_receipt(data: bytes) -> ReleasedCalMintReceiptAccount:
    view = _validated_layout(data, name="ReleasedCalMintReceipt", size=121)
    return ReleasedCalMintReceiptAccount(
        ride_attestation=Pubkey.from_bytes(bytes(view[8:40])),
        release_authority=Pubkey.from_bytes(bytes(view[40:72])),
        rider=Pubkey.from_bytes(bytes(view[72:104])),
        amount=struct.unpack("<Q", view[104:112])[0],
        release_settlement_week=struct.unpack("<Q", view[112:120])[0],
        bump=struct.unpack("<B", view[120:121])[0],
    )


def decode_climb_completion_receipt(data: bytes) -> ClimbCompletionReceipt:
    if data[:8] == _discriminator("ClimbCompletionReceipt"):
        view = _validated_layout(data, name="ClimbCompletionReceipt", size=105)
        return ClimbCompletionReceiptAccount(
            ride_attestation=Pubkey.from_bytes(bytes(view[8:40])),
            vault=Pubkey.from_bytes(bytes(view[40:72])),
            completion_evidence_hash=bytes(view[72:104]),
            bump=struct.unpack("<B", view[104:105])[0],
        )
    if data[:8] == _discriminator("ClimbCompletionReceiptV2"):
        view = _validated_layout(data, name="ClimbCompletionReceiptV2", size=114)
        return ClimbCompletionReceiptV2Account(
            ride_attestation=Pubkey.from_bytes(bytes(view[8:40])),
            vault=Pubkey.from_bytes(bytes(view[40:72])),
            evidence_version=struct.unpack("<B", view[72:73])[0],
            cal_tributed=struct.unpack("<Q", view[73:81])[0],
            completion_evidence_hash=bytes(view[81:113]),
            bump=struct.unpack("<B", view[113:114])[0],
        )
    raise ChainAccountMismatchError(
        "climb completion receipt discriminator does not match V1 or V2"
    )


def decode_released_climb_completion_receipt(
    data: bytes,
) -> ReleasedClimbCompletionReceiptAccount:
    view = _validated_layout(
        data,
        name="ReleasedClimbCompletionReceipt",
        size=154,
    )
    return ReleasedClimbCompletionReceiptAccount(
        ride_attestation=Pubkey.from_bytes(bytes(view[8:40])),
        release_authority=Pubkey.from_bytes(bytes(view[40:72])),
        vault=Pubkey.from_bytes(bytes(view[72:104])),
        evidence_version=struct.unpack("<B", view[104:105])[0],
        cal_tributed=struct.unpack("<Q", view[105:113])[0],
        completion_evidence_hash=bytes(view[113:145]),
        credited_settlement_week=struct.unpack("<Q", view[145:153])[0],
        bump=struct.unpack("<B", view[153:154])[0],
    )


async def read_owned_account(
    *,
    reader: AccountReader,
    rpc_url: str,
    address: Pubkey,
    program_id: Pubkey,
) -> ChainAccount:
    account = await reader(rpc_url, address)
    if account is None:
        raise ChainAccountUnavailableError(f"chain account {address} is unavailable")
    owner = Pubkey.from_string(str(account.owner))
    if owner != program_id:
        raise ChainAccountMismatchError(
            f"account owner {owner} does not match program {program_id}"
        )
    return ChainAccount(owner=owner, data=bytes(account.data))


def _require_fields(
    *, account_name: str, actual: object, expected: dict[str, object]
) -> None:
    for field, expected_value in expected.items():
        actual_value = getattr(actual, field)
        if actual_value != expected_value:
            raise ChainAccountMismatchError(
                f"{account_name}.{field} does not match frozen value"
            )


def validate_ride_attestation(
    account: RideAttestationAccount,
    *,
    rider: Pubkey,
    ride_hash: bytes,
    attestation_commitment: bytes,
    parser_version: int,
    source_kind: int,
    completed_at: int,
    started_at: int,
    total_tss: int,
    total_distance_m: int,
    total_vert_m: int,
    cal_earned: int,
    climbs_crossed: int,
    bump: int,
) -> None:
    # `attester` is historical chain state. Program authorization at creation
    # remains authoritative across backend-authority rotation.
    _require_fields(
        account_name="RideAttestation",
        actual=account,
        expected={
            "rider": rider,
            "ride_hash": ride_hash,
            "attestation_commitment": attestation_commitment,
            "parser_version": parser_version,
            "source_kind": source_kind,
            "completed_at": completed_at,
            "started_at": started_at,
            "total_tss": total_tss,
            "total_distance_m": total_distance_m,
            "total_vert_m": total_vert_m,
            "cal_earned": cal_earned,
            "climbs_crossed": climbs_crossed,
            "bump": bump,
        },
    )


def validate_held_ride_release_authority(
    account: HeldRideReleaseAuthorityAccount,
    *,
    ride_attestation: Pubkey,
    rider: Pubkey,
    threshold_authority_id: bytes,
    threshold_authority_commitment: bytes,
    threshold_effective_at: int,
    threshold_w: int,
    threshold_policy_version: int,
    economic_tss: int,
    cal_earned: int,
    cal_tribute_budget: int,
    release_plan_hash: bytes,
    bump: int,
) -> None:
    # Release time, slot, week, and attester are historical chain state. The
    # planned authority fields remain immutable across retries and rotations.
    _require_fields(
        account_name="HeldRideReleaseAuthority",
        actual=account,
        expected={
            "ride_attestation": ride_attestation,
            "rider": rider,
            "threshold_authority_id": threshold_authority_id,
            "threshold_authority_commitment": threshold_authority_commitment,
            "threshold_effective_at": threshold_effective_at,
            "threshold_w": threshold_w,
            "threshold_policy_version": threshold_policy_version,
            "economic_tss": economic_tss,
            "cal_earned": cal_earned,
            "cal_tribute_budget": cal_tribute_budget,
            "release_plan_hash": release_plan_hash,
            "bump": bump,
        },
    )


def validate_held_ride_release_credit_authority(
    account: HeldRideReleaseAuthorityAccount,
    *,
    ride_attestation: Pubkey,
    rider: Pubkey,
    cal_earned: int,
    bump: int,
) -> None:
    """Validate the authority fields needed before an amount-less CAL mint."""
    _require_fields(
        account_name="HeldRideReleaseAuthority",
        actual=account,
        expected={
            "ride_attestation": ride_attestation,
            "rider": rider,
            "cal_earned": cal_earned,
            "bump": bump,
        },
    )


def validate_cal_mint_receipt(
    account: CalMintReceiptAccount,
    *,
    ride_attestation: Pubkey,
    rider: Pubkey,
    amount: int,
    bump: int,
) -> None:
    _require_fields(
        account_name="CalMintReceipt",
        actual=account,
        expected={
            "ride_attestation": ride_attestation,
            "rider": rider,
            "amount": amount,
            "bump": bump,
        },
    )


def validate_released_cal_mint_receipt(
    account: ReleasedCalMintReceiptAccount,
    *,
    ride_attestation: Pubkey,
    release_authority: Pubkey,
    rider: Pubkey,
    amount: int,
    release_settlement_week: int,
    bump: int,
) -> None:
    _require_fields(
        account_name="ReleasedCalMintReceipt",
        actual=account,
        expected={
            "ride_attestation": ride_attestation,
            "release_authority": release_authority,
            "rider": rider,
            "amount": amount,
            "release_settlement_week": release_settlement_week,
            "bump": bump,
        },
    )


def validate_climb_completion_receipt(
    account: ClimbCompletionReceipt,
    *,
    ride_attestation: Pubkey,
    vault: Pubkey,
    evidence_version: int,
    cal_tribute: int,
    completion_evidence_hash: bytes,
    bump: int,
) -> None:
    if evidence_version != 2 or not isinstance(
        account, ClimbCompletionReceiptV2Account
    ):
        raise LegacyCompletionEvidenceError(
            "V1 climb completion receipt does not bind exact tribute"
        )
    _require_fields(
        account_name="ClimbCompletionReceiptV2",
        actual=account,
        expected={
            "ride_attestation": ride_attestation,
            "vault": vault,
            "evidence_version": 2,
            "cal_tributed": cal_tribute,
            "completion_evidence_hash": completion_evidence_hash,
            "bump": bump,
        },
    )


def validate_released_climb_completion_receipt(
    account: ReleasedClimbCompletionReceiptAccount,
    *,
    ride_attestation: Pubkey,
    release_authority: Pubkey,
    vault: Pubkey,
    evidence_version: int,
    cal_tribute: int,
    completion_evidence_hash: bytes,
    credited_settlement_week: int,
    bump: int,
) -> None:
    if evidence_version != 3 or account.evidence_version != 3:
        raise ChainAccountMismatchError(
            "released climb completion receipt requires V3 evidence"
        )
    _require_fields(
        account_name="ReleasedClimbCompletionReceipt",
        actual=account,
        expected={
            "ride_attestation": ride_attestation,
            "release_authority": release_authority,
            "vault": vault,
            "evidence_version": 3,
            "cal_tributed": cal_tribute,
            "completion_evidence_hash": completion_evidence_hash,
            "credited_settlement_week": credited_settlement_week,
            "bump": bump,
        },
    )


def validate_legacy_climb_completion_receipt(
    account: ClimbCompletionReceipt,
    *,
    ride_attestation: Pubkey,
    vault: Pubkey,
    completion_evidence_hash: bytes,
    bump: int,
) -> None:
    """Validate frozen V1 identity without treating it as amount evidence."""
    if not isinstance(account, ClimbCompletionReceiptAccount):
        raise ChainAccountMismatchError(
            "expected historical ClimbCompletionReceipt V1 account"
        )
    _require_fields(
        account_name="ClimbCompletionReceipt",
        actual=account,
        expected={
            "ride_attestation": ride_attestation,
            "vault": vault,
            "completion_evidence_hash": completion_evidence_hash,
            "bump": bump,
        },
    )
