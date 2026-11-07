"""Resolve and persist the geographic v2 identity behind an on-chain vault."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from supabase import Client

from ..utils.postgrest_paging import PageCursor, order_by, window
from .patterns.climb_signature import (
    REWARD_GRADE_MIN_SIMILARITY,
    InvalidRewardGradeEvidence,
    RewardGradeMatcherError,
    match_reward_grade_v2,
    validate_reward_grade_climb_evidence,
)


VAULT_IDENTITY_PAGE_SIZE = 1000


class VaultRewardIdentityError(RuntimeError):
    """Base failure for reward-grade vault identity resolution."""


class VaultRewardIdentityUnavailable(VaultRewardIdentityError):
    """The database or native matcher could not complete identity resolution."""


class VaultRewardIdentityMissing(VaultRewardIdentityError):
    """No eligible canonical source exists for the requested vault identity."""


class VaultRewardIdentityIncomplete(VaultRewardIdentityError):
    """Eligible legacy evidence lacks enough v2/location data to be authoritative."""


class VaultRewardIdentityAmbiguous(VaultRewardIdentityError):
    """One legacy v1 key maps to more than one geographic v2 identity."""


@dataclass(frozen=True)
class VaultRewardIdentity:
    """One stored climb row that can authoritatively identify a vault."""

    pattern_id: str
    wallet: str
    signature_hex: str
    signature_v2_hex: str
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    vert_m: float
    distance_m: float
    avg_gradient_pct: float
    economic_eligible: bool

    def as_source_dict(self) -> Dict[str, Any]:
        source = asdict(self)
        source["id"] = source.pop("pattern_id")
        return source

    def as_indexed_vault_patch(self) -> Dict[str, Any]:
        return {
            "signature_v2_hex": self.signature_v2_hex,
            "signature_version": 2,
            "start_lat": self.start_lat,
            "start_lon": self.start_lon,
            "end_lat": self.end_lat,
            "end_lon": self.end_lon,
        }


@dataclass(frozen=True)
class VaultRewardIdentityReconciliation:
    """Bounded report from a dry-run or applied identity reconciliation."""

    scanned: int
    resolved: int
    updated: int
    failures: List[Dict[str, Any]]


def _positive_finite(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed <= 0.0:
        return None
    return parsed


def _candidate_identity(row: Dict[str, Any]) -> Optional[VaultRewardIdentity]:
    signature_v2_hex = row.get("signature_v2_hex")
    start = (row.get("start_lat"), row.get("start_lon"))
    end = (row.get("end_lat"), row.get("end_lon"))
    try:
        validate_reward_grade_climb_evidence(
            signature_v2_hex=signature_v2_hex,
            start=start,
            end=end,
            label=f"pattern {row.get('id')}",
        )
        self_evidence = match_reward_grade_v2(
            query_signature_v2_hex=signature_v2_hex,
            candidate_signature_v2_hex=signature_v2_hex,
            query_start=start,
            query_end=end,
            candidate_start=start,
            candidate_end=end,
        )
    except (InvalidRewardGradeEvidence, ValueError):
        return None

    if (
        self_evidence is None
        or self_evidence.similarity < REWARD_GRADE_MIN_SIMILARITY
    ):
        return None

    vert_m = _positive_finite(row.get("vert_m"))
    distance_m = _positive_finite(row.get("distance_m"))
    avg_gradient_pct = _positive_finite(row.get("avg_gradient_pct"))
    if vert_m is None or distance_m is None or avg_gradient_pct is None:
        return None

    return VaultRewardIdentity(
        pattern_id=str(row.get("id") or ""),
        wallet=str(row.get("wallet") or ""),
        signature_hex=str(row.get("signature_hex") or ""),
        signature_v2_hex=str(signature_v2_hex),
        start_lat=float(start[0]),
        start_lon=float(start[1]),
        end_lat=float(end[0]),
        end_lon=float(end[1]),
        vert_m=vert_m,
        distance_m=distance_m,
        avg_gradient_pct=avg_gradient_pct,
        economic_eligible=row.get("economic_eligible") is True,
    )


def _load_legacy_identity_rows(
    client: Client,
    signature_hex: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    pages = PageCursor(VAULT_IDENTITY_PAGE_SIZE)
    try:
        while True:
            page = (
                order_by(
                    client.table("patterns_climb")
                    .select(
                        "id, wallet, signature_hex, signature_v2_hex, start_lat, "
                        "start_lon, end_lat, end_lon, vert_m, distance_m, "
                        "avg_gradient_pct, economic_eligible, created_at"
                    )
                    .eq("signature_hex", signature_hex),
                    "created_at",
                    "id",
                )
                .range(
                    pages.offset,
                    pages.offset + VAULT_IDENTITY_PAGE_SIZE - 1,
                )
                .execute()
                .data
                or []
            )
            rows.extend(page)
            if not pages.advance(page):  # range() is end-exclusive; see postgrest_paging.
                return rows
    except Exception as exc:
        raise VaultRewardIdentityUnavailable(
            "failed to load stored climb identity evidence"
        ) from exc


def resolve_reward_grade_vault_identity(
    *,
    client: Client,
    signature_hex: str,
    required_wallet: Optional[str] = None,
) -> VaultRewardIdentity:
    """Resolve one globally unambiguous v2 identity for a legacy v1 vault key."""
    rows = _load_legacy_identity_rows(client, signature_hex)
    if not rows:
        raise VaultRewardIdentityMissing("no stored climb evidence uses this signature")

    valid: List[VaultRewardIdentity] = []
    incomplete_eligible_ids: List[str] = []
    try:
        for row in rows:
            identity = _candidate_identity(row)
            if identity is not None:
                valid.append(identity)
            elif row.get("economic_eligible") is True:
                incomplete_eligible_ids.append(str(row.get("id") or "unknown"))
    except RewardGradeMatcherError as exc:
        raise VaultRewardIdentityUnavailable(
            "reward-grade matcher could not verify stored climb evidence"
        ) from exc

    if incomplete_eligible_ids:
        raise VaultRewardIdentityIncomplete(
            "eligible legacy evidence lacks canonical v2/location data: "
            + ", ".join(incomplete_eligible_ids[:5])
        )

    selectable = [
        identity
        for identity in valid
        if identity.economic_eligible
        and (required_wallet is None or identity.wallet == required_wallet)
    ]
    if not selectable:
        qualifier = " for the vault creator" if required_wallet else ""
        raise VaultRewardIdentityMissing(
            f"no eligible canonical climb source exists{qualifier}"
        )

    source = selectable[0]
    try:
        for query_index, query_identity in enumerate(valid):
            for candidate in valid[query_index + 1 :]:
                evidence = match_reward_grade_v2(
                    query_signature_v2_hex=query_identity.signature_v2_hex,
                    candidate_signature_v2_hex=candidate.signature_v2_hex,
                    query_start=(query_identity.start_lat, query_identity.start_lon),
                    query_end=(query_identity.end_lat, query_identity.end_lon),
                    candidate_start=(candidate.start_lat, candidate.start_lon),
                    candidate_end=(candidate.end_lat, candidate.end_lon),
                )
                if (
                    evidence is None
                    or evidence.similarity < REWARD_GRADE_MIN_SIMILARITY
                ):
                    raise VaultRewardIdentityAmbiguous(
                        "legacy v1 signature maps to more than one geographic v2 identity"
                    )
    except InvalidRewardGradeEvidence as exc:
        raise VaultRewardIdentityIncomplete(
            "stored climb evidence became invalid during comparison"
        ) from exc
    except RewardGradeMatcherError as exc:
        raise VaultRewardIdentityUnavailable(
            "reward-grade matcher could not compare stored climb evidence"
        ) from exc

    return source


def reconcile_indexed_vault_reward_identity(
    *,
    client: Client,
    vault: Dict[str, Any],
    apply: bool,
) -> VaultRewardIdentity:
    """Resolve a vault's v2 identity and optionally persist the verified result."""
    vault_id = vault.get("id")
    signature_hex = str(vault.get("signature_hex") or "")
    if vault_id is None or not signature_hex:
        raise VaultRewardIdentityMissing("indexed vault lacks its legacy identity key")

    identity = resolve_reward_grade_vault_identity(
        client=client,
        signature_hex=signature_hex,
        required_wallet=str(vault.get("minter") or "") or None,
    )

    current_signature = vault.get("signature_v2_hex")
    current_points = (
        vault.get("start_lat"),
        vault.get("start_lon"),
        vault.get("end_lat"),
        vault.get("end_lon"),
    )
    if current_signature and all(value is not None for value in current_points):
        try:
            evidence = match_reward_grade_v2(
                query_signature_v2_hex=identity.signature_v2_hex,
                candidate_signature_v2_hex=current_signature,
                query_start=(identity.start_lat, identity.start_lon),
                query_end=(identity.end_lat, identity.end_lon),
                candidate_start=(current_points[0], current_points[1]),
                candidate_end=(current_points[2], current_points[3]),
            )
        except InvalidRewardGradeEvidence as exc:
            raise VaultRewardIdentityIncomplete(
                "indexed vault contains invalid v2/location evidence"
            ) from exc
        except RewardGradeMatcherError as exc:
            raise VaultRewardIdentityUnavailable(
                "reward-grade matcher could not verify indexed vault evidence"
            ) from exc
        if evidence is None or evidence.similarity < REWARD_GRADE_MIN_SIMILARITY:
            raise VaultRewardIdentityAmbiguous(
                "indexed vault v2 identity conflicts with stored climb evidence"
            )

    if apply:
        patch = identity.as_indexed_vault_patch()
        try:
            (
                client.table("indexed_vaults")
                .update(patch)
                .eq("id", vault_id)
                .execute()
            )
            verified = (
                client.table("indexed_vaults")
                .select(
                    "id, signature_v2_hex, signature_version, start_lat, "
                    "start_lon, end_lat, end_lon"
                )
                .eq("id", vault_id)
                .limit(1)
                .execute()
                .data
                or []
            )
        except Exception as exc:
            raise VaultRewardIdentityUnavailable(
                "failed to persist indexed vault reward identity"
            ) from exc
        if not verified or any(
            verified[0].get(field) != value for field, value in patch.items()
        ):
            raise VaultRewardIdentityUnavailable(
                "indexed vault reward identity update did not persist"
            )

    return identity


def reconcile_vault_reward_identities(
    *,
    client: Client,
    apply: bool,
    vault_id: Optional[int] = None,
    limit: Optional[int] = None,
) -> VaultRewardIdentityReconciliation:
    """Dry-run or apply reward identity reconciliation across indexed vaults."""
    if limit is not None and limit <= 0:
        raise ValueError("reconciliation limit must be positive")

    vaults: List[Dict[str, Any]] = []
    pages = PageCursor(VAULT_IDENTITY_PAGE_SIZE)
    try:
        while limit is None or len(vaults) < limit:
            page_size = VAULT_IDENTITY_PAGE_SIZE
            if limit is not None:
                page_size = min(page_size, limit - len(vaults))
            query = client.table("indexed_vaults").select(
                "id, signature_hex, minter, signature_version, "
                "signature_v2_hex, start_lat, start_lon, end_lat, end_lon"
            )
            if vault_id is not None:
                query = query.eq("id", vault_id)
            # An exact window keeps the limit.
            page = window(query.order("id"), pages.offset, page_size).execute().data or []
            vaults.extend(page)
            if vault_id is not None or not pages.advance(page):
                break
    except Exception as exc:
        raise VaultRewardIdentityUnavailable(
            "failed to load indexed vaults for reward identity reconciliation"
        ) from exc

    failures: List[Dict[str, Any]] = []
    resolved = 0
    for vault in vaults:
        try:
            reconcile_indexed_vault_reward_identity(
                client=client,
                vault=vault,
                apply=apply,
            )
            resolved += 1
        except VaultRewardIdentityError as exc:
            failures.append(
                {
                    "vault_id": vault.get("id"),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    return VaultRewardIdentityReconciliation(
        scanned=len(vaults),
        resolved=resolved,
        updated=resolved if apply else 0,
        failures=failures,
    )
