"""Immutable FTP authority used by rewardable ride math."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


DEFAULT_REWARD_FTP_W = 200
MIN_REWARD_FTP_W = 50
MAX_REWARD_FTP_W = 500
LEGACY_REWARD_FTP_POLICY_VERSION = "reward_ftp_policy_2026_07_14"
REWARD_FTP_POLICY_VERSION = "reward_ftp_policy_2026_08_24_threshold_v1"
SUPPORTED_REWARD_FTP_POLICY_VERSIONS = frozenset(
    {LEGACY_REWARD_FTP_POLICY_VERSION, REWARD_FTP_POLICY_VERSION}
)
NETWORK_DEFAULT_REWARD_FTP_SOURCE = "network_default"
HISTORICAL_REWARD_FTP_SOURCES = frozenset(
    {
        "operator_verified",
        "trusted_provider",
        "verified_power_test",
    }
)
POST_CUTOVER_WRITABLE_REWARD_FTP_SOURCES = frozenset({"derived_eftp"})
READABLE_REWARD_FTP_AUTHORITY_SOURCES = frozenset(
    {
        *HISTORICAL_REWARD_FTP_SOURCES,
        *POST_CUTOVER_WRITABLE_REWARD_FTP_SOURCES,
    }
)
REWARD_FTP_SOURCES = frozenset(
    {NETWORK_DEFAULT_REWARD_FTP_SOURCE, *READABLE_REWARD_FTP_AUTHORITY_SOURCES}
)


def validate_reward_ftp_w(value: Any) -> int:
    """Return an exact, bounded reward FTP or reject the authority row."""
    if isinstance(value, bool):
        raise ValueError("reward_ftp_w must be an integer")
    try:
        ftp_w = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("reward_ftp_w must be an integer") from exc
    if ftp_w != value and not (isinstance(value, str) and str(ftp_w) == value.strip()):
        raise ValueError("reward_ftp_w must be an exact integer")
    if not MIN_REWARD_FTP_W <= ftp_w <= MAX_REWARD_FTP_W:
        raise ValueError(
            f"reward_ftp_w must be between {MIN_REWARD_FTP_W} and {MAX_REWARD_FTP_W}"
        )
    return ftp_w


@dataclass(frozen=True)
class RewardFtpSnapshot:
    """Service-bound reward FTP provenance frozen onto one ride."""

    ftp_w: int
    source: str
    policy_version: str
    authority_id: str | None = None

    @classmethod
    def network_default(cls) -> "RewardFtpSnapshot":
        return cls(
            ftp_w=DEFAULT_REWARD_FTP_W,
            source=NETWORK_DEFAULT_REWARD_FTP_SOURCE,
            policy_version=REWARD_FTP_POLICY_VERSION,
            authority_id=None,
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "RewardFtpSnapshot":
        try:
            ftp_w = validate_reward_ftp_w(row["reward_ftp_w"])
            source = str(row["reward_ftp_source"])
            policy_version = str(row["reward_ftp_policy_version"])
        except KeyError as exc:
            raise ValueError(f"ride is missing immutable reward FTP field {exc.args[0]}") from exc

        if source not in REWARD_FTP_SOURCES:
            raise ValueError(f"unsupported reward FTP source: {source}")
        if policy_version not in SUPPORTED_REWARD_FTP_POLICY_VERSIONS:
            raise ValueError(f"unsupported reward FTP policy: {policy_version}")
        authority_raw = row.get("reward_ftp_authority_id")
        authority_id = str(authority_raw) if authority_raw else None
        if source == NETWORK_DEFAULT_REWARD_FTP_SOURCE:
            if ftp_w != DEFAULT_REWARD_FTP_W or authority_id is not None:
                raise ValueError("network-default reward FTP provenance is inconsistent")
        elif authority_id is None:
            raise ValueError("verified reward FTP provenance requires an authority id")

        return cls(
            ftp_w=ftp_w,
            source=source,
            policy_version=policy_version,
            authority_id=authority_id,
        )
