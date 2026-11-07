"""
Ride Attester: Ingest + canonicalize + hash + RideAttestation evaluation.

Role: BACKEND_TRUTHS §5.1 Attester — "the role that ingests rides,
canonicalizes them, and commits attestations. Attestation is
cryptographically committed (FIX_PLAN P13). The backend is not a
trusted issuer — it is an attester whose output is independently
verifiable."

This module is the canonical home for the Attester role in the
backend. The `RideProcessor` orchestration shell
(`services/ride_processor.py`) consumes this module to stamp a
`RideAttestation` for every ride before any economic consequence flows.
The Executor role (`send_record_ride` / `send_credit_cal` /
`send_record_climb_completion` in `solana_direct.py`) acts on the
attestation the Attester produces; the Projector role
(`services/projection_writer.py`) mirrors on-chain state into the
indexer downstream of all of it. Attester → Executor → Projector is the
§5 arrow of truth.

Per BACKEND_TRUTHS §1 (North Star):
  "The backend is the attester. Its job is to receive rides, interpret
  them under a versioned canonical form, and commit their economic
  consequences to the protocol with cryptographic evidence — so that
  every CAL credited, every climb completion recorded, every DUNG
  distributed can be independently verified by any observer who holds
  the original ride file."

Per BACKEND_TRUTHS §2.2 (Ride Attestation):
  Every ride is stamped with a `RideAttestation` that binds
  `(ride_hash, attestation_commitment, parser_version, source_kind,
  rider_wallet)`. Every downstream economic call — CAL credit, climb
  completion, epoch roll-up — must reference this attestation. Without
  it, the economic effect has no provenance.

Per BACKEND_TRUTHS §6 (The Ingest Pipeline Truths):
  - §6.1 Parser Version Binding — the Attester owns parser-version
    stamping. Every attestation carries the parser_version used to
    produce it, binding the ride file to the exact canonical form
    that generated its hash. A rider with the original file + the
    stamped parser_version can recompute and verify.
  - §6.2 Canonical Hash Is Deterministic — the ride_hash is a pure
    function of `(canonicalized_trace, parser_version)`. No RNG, no
    wall-clock, no network state leaks into canonicalization.
  - §6.3 Hash Compare Is the Attestation Gate — when mobile stamps a
    preliminary ride hash on-device, the backend re-canonicalizes and
    compares. Mismatch is surfaced (via `requires_review` /
    `review_reason`) and gates economic consequences, not laundered.
    The `evaluate_preliminary_attestation` function below IS that gate.
  - §6.4 Economic Consequences Derived Once — the attestation
    produced here is the single handoff to the Executor. CAL credit,
    climb completion, distribution — all derive from the same
    attestation object; we do not re-canonicalize downstream.
  - §6.5 Abstention Preserves Provenance — when the Attester flags
    `requires_review`, the Executor abstains (no on-chain write). The
    absence is itself provenance: the ride is still recorded, but
    marked under_review so the original file stays available for
    re-evaluation without silent economic state leakage.

Per BACKEND_TRUTHS §8 (Attester vs Authority):
  The backend signs, it does not decree. What the backend signs is
  cryptographically committed; a rider with the original ride file
  can recompute the canonical hash and verify. This module never
  decides economic outcomes by fiat — every stamp is verifiable.

Citations:
  - BACKEND_TRUTHS §1, §2.1, §2.2, §5.1, §6.1, §6.2, §6.3, §6.4, §6.5, §8
  - PROTOCOL_TRUTHS §2.3 (RideAttestation)
  - docs/design/WWPTD_DISPATCHER_PLAYBOOK.md (role separation in code
    organization)
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .ride_metrics import RideMetrics, calculate_metrics
from .reward_ftp import DEFAULT_REWARD_FTP_W, validate_reward_ftp_w
from .ride_provenance_policy import (
    MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON,
    trusted_provider_review_reason,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonicalization entrypoint (Rust workout_parse adapter).
#
# Imported lazily from the same adapter that the ride parser uses. The
# Attester owns the parser-version-binding per §6.1 — the canonical
# hash and parser_version both flow from this call.
# ---------------------------------------------------------------------------
compute_ride_identity_bytes = None  # populated below
parse_ride_file_bytes = None  # populated below
calculate_metrics_rust = None  # populated below

_rust_mode = os.getenv("USE_RUST_PARSER", "auto").strip().lower()
_rust_enabled = _rust_mode in ("1", "true", "yes", "on")
_rust_disabled = _rust_mode in ("0", "false", "no", "off")

if _rust_disabled:
    from .ride_parser import ParsedRide, parse_ride_file
    logger.info("Using Python ride_parser in RideAttester (USE_RUST_PARSER disabled)")
else:
    try:
        from .workout_parse_adapter import (
            ParsedRideCompat as ParsedRide,
            calculate_metrics_rust,
            compute_ride_identity_bytes_rust as compute_ride_identity_bytes,
            parse_ride_file_bytes_rust as parse_ride_file_bytes,
            parse_ride_file_rust as parse_ride_file,
        )
        logger.info("Using Rust workout_parse parser in RideAttester")
    except ImportError:  # pragma: no cover - Rust parser optional
        from .ride_parser import ParsedRide, parse_ride_file
        compute_ride_identity_bytes = None
        parse_ride_file_bytes = None
        if _rust_enabled:
            logger.warning(
                "Rust parser explicitly enabled but not available in RideAttester; "
                "falling back to Python"
            )
        else:
            logger.info("Rust parser not available in RideAttester; falling back to Python")


def _source_kind_from_file_type(file_type: str) -> int:
    """Canonical enum for the ride file's origin format.

    The value is bound into the on-chain `RideAttestation` account so a
    verifier knows which canonical parser path produced the hash. This
    enum is part of the attestation commitment (§6.1, §6.2); changing
    it is a parser-version event.
    """
    normalized = (file_type or "").strip().lower()
    if normalized == "fit":
        return 1
    if normalized == "gpx":
        return 2
    if normalized == "tcx":
        return 3
    return 0


@dataclass
class OnchainRideIdentity:
    """The attestation payload the Attester produces for every ride.

    BACKEND_TRUTHS §2.2: every ride carries a RideAttestation binding
    `(ride_hash, attestation_commitment, parser_version, source_kind)`.
    Each field here corresponds to an on-chain attestation field and
    must be stamped before any economic consequence flows (§6.4).

    - `ride_hash`: SHA-like digest over the canonicalized trace under
      `parser_version`. Deterministic (§6.2).
    - `attestation_commitment`: what the backend signs on-chain. Today
      it equals `ride_hash`; the field is kept distinct so future
      signed commitment envelopes can evolve without a wire break.
    - `parser_version`: the version of the canonicalization pipeline
      used to produce the hash (§6.1). A verifier re-runs this version
      to reproduce the hash.
    - `source_kind`: FIT / GPX / TCX enum (see
      `_source_kind_from_file_type`).
    """

    ride_hash: bytes
    attestation_commitment: bytes
    parser_version: int
    source_kind: int


@dataclass
class PreliminaryAttestationCheck:
    """The outcome of comparing a mobile-side preliminary hash against
    the backend-side canonical hash (§6.3).

    `requires_review=True` means the Executor abstains from on-chain
    writes (§6.5). The ride is still recorded, but flagged
    `under_review` with a named `review_reason` so operators can audit
    without silent economic drift.
    """

    preliminary_ride_hash_hex: Optional[str]
    preliminary_parser_version: Optional[int]
    canonical_match: Optional[bool]
    review_reason: Optional[str]
    requires_review: bool


@dataclass
class RideAttestationPreparation:
    """Prepared attested truth for a ride before execution/projection.

    The coordinator receives this object and passes its fields downstream.
    The object intentionally contains no chain transaction references and no
    projection writes: those belong to Executor and Projector respectively.
    """

    onchain_identity: OnchainRideIdentity
    preliminary_check: PreliminaryAttestationCheck
    parsed_ride: ParsedRide
    metrics: RideMetrics
    economic_metrics: RideMetrics | None = None
    reward_ftp_w: int = DEFAULT_REWARD_FTP_W


def evaluate_preliminary_attestation(
    ride_row: Optional[Dict[str, Any]],
    onchain_ride_identity: OnchainRideIdentity,
    file_type: str,
) -> PreliminaryAttestationCheck:
    """Compare a mobile-stamped preliminary hash against the backend's
    canonical `OnchainRideIdentity`.

    THIS IS THE BACKEND_TRUTHS §6.3 ATTESTATION GATE. A mismatch here
    MUST surface as `requires_review=True` with a named `review_reason`,
    never as a silent pass. Downstream callers in the orchestrator
    (`RideProcessor.process_ride`) gate on `requires_review` and skip
    on-chain Executor writes when it is set (§6.5).

    Behavior:
      - No ride_row → no preliminary stamp to compare → pass-through.
      - Legacy rows (no preliminary fields and no requirement marker) →
        pass-through, for backward compatibility with pre-handshake uploads.
      - First-party recorder rows marked as requiring a preliminary attestation
        must carry both fields; missing fields require review instead of
        silently passing into economics.
      - Trusted-provider and manual-file rows are not expected to carry the BR
        recorder stamp; they pass this compare gate and are later governed by
        timestamp, effort, integrity, duplicate/replay, and provenance policy.
      - Any stamped upload: both `preliminary_ride_hash_hex` and
        `preliminary_parser_version` must be present, the hash must be
        64 hex chars, parser_version must match, and the hash must
        match. Any failure returns `requires_review=True` with a
        specific `review_reason`.

    Review reasons (named, not generic):
      - `invalid_preliminary_parser_version`
      - `missing_preliminary_attestation`
      - `incomplete_preliminary_attestation`
      - `invalid_preliminary_hash_length`
      - `parser_version_mismatch`
      - `preliminary_hash_mismatch`
    """
    if not ride_row:
        return PreliminaryAttestationCheck(None, None, None, None, False)

    preliminary_hash_hex_raw = ride_row.get("preliminary_ride_hash_hex")
    preliminary_parser_version_raw = ride_row.get("preliminary_parser_version")
    diagnostics = ride_row.get("import_diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}
    preliminary_required = diagnostics.get("preliminary_attestation_required") is True
    provenance_review_reason = trusted_provider_review_reason(ride_row, diagnostics)
    if provenance_review_reason:
        return PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=None,
            preliminary_parser_version=None,
            canonical_match=False,
            review_reason=provenance_review_reason,
            requires_review=True,
        )

    preliminary_hash_hex = (
        str(preliminary_hash_hex_raw).strip().lower()
        if preliminary_hash_hex_raw
        else None
    )
    preliminary_parser_version = None
    if preliminary_parser_version_raw is not None:
        try:
            preliminary_parser_version = int(preliminary_parser_version_raw)
        except (TypeError, ValueError):
            return PreliminaryAttestationCheck(
                preliminary_ride_hash_hex=preliminary_hash_hex,
                preliminary_parser_version=None,
                canonical_match=False,
                review_reason="invalid_preliminary_parser_version",
                requires_review=True,
            )

    if preliminary_hash_hex is None and preliminary_parser_version is None:
        if preliminary_required:
            return PreliminaryAttestationCheck(
                preliminary_ride_hash_hex=None,
                preliminary_parser_version=None,
                canonical_match=False,
                review_reason=MISSING_PRELIMINARY_ATTESTATION_REVIEW_REASON,
                requires_review=True,
            )
        return PreliminaryAttestationCheck(None, None, None, None, False)

    if not preliminary_hash_hex or preliminary_parser_version is None:
        return PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=preliminary_hash_hex,
            preliminary_parser_version=preliminary_parser_version,
            canonical_match=False,
            review_reason="incomplete_preliminary_attestation",
            requires_review=True,
        )

    if len(preliminary_hash_hex) != 64:
        return PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=preliminary_hash_hex,
            preliminary_parser_version=preliminary_parser_version,
            canonical_match=False,
            review_reason="invalid_preliminary_hash_length",
            requires_review=True,
        )

    expected_hash_hex = onchain_ride_identity.ride_hash.hex()
    if preliminary_parser_version != onchain_ride_identity.parser_version:
        return PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=preliminary_hash_hex,
            preliminary_parser_version=preliminary_parser_version,
            canonical_match=False,
            review_reason="parser_version_mismatch",
            requires_review=True,
        )

    if preliminary_hash_hex != expected_hash_hex:
        return PreliminaryAttestationCheck(
            preliminary_ride_hash_hex=preliminary_hash_hex,
            preliminary_parser_version=preliminary_parser_version,
            canonical_match=False,
            review_reason="preliminary_hash_mismatch",
            requires_review=True,
        )

    return PreliminaryAttestationCheck(
        preliminary_ride_hash_hex=preliminary_hash_hex,
        preliminary_parser_version=preliminary_parser_version,
        canonical_match=True,
        review_reason=None,
        requires_review=False,
    )


def build_onchain_ride_identity(
    file_data_b64: str,
    file_type: str,
    file_bytes: Optional[bytes],
) -> OnchainRideIdentity:
    """Canonicalize a raw ride file to its `OnchainRideIdentity`.

    This is the Attester's §6.1 + §6.2 entrypoint: the caller hands us
    raw bytes (or a base64 envelope), we run the versioned
    canonicalization pipeline, and we return the deterministic
    attestation payload. Every field of the returned
    `OnchainRideIdentity` is independently verifiable by a rider who
    holds the original file and runs the same parser_version.

    The orchestration shell (`RideProcessor.process_ride`) calls this
    before any economic path and passes the result through to the
    Executor (`send_record_ride`) unchanged (§6.4 Economic Consequences
    Derived Once).
    """
    if compute_ride_identity_bytes is None:
        raise RuntimeError(
            "workout_parse canonicalization helpers are not available"
        )

    raw_bytes = (
        file_bytes if file_bytes is not None else base64.b64decode(file_data_b64)
    )
    ride_hash, parser_version = compute_ride_identity_bytes(raw_bytes, file_type)
    return OnchainRideIdentity(
        ride_hash=ride_hash,
        attestation_commitment=ride_hash,
        parser_version=parser_version,
        source_kind=_source_kind_from_file_type(file_type),
    )


class RideAttester:
    """Canonicalization + preliminary-hash handshake entry point.

    This class is the thin role-scoped façade over
    `build_onchain_ride_identity` and `evaluate_preliminary_attestation`.
    The orchestrator (`RideProcessor`) composes it alongside the
    Executor and Projector.

    Not a source of economic truth — `RideAttester` does not sign
    on-chain. It produces the attestation payload the Executor signs
    and gates that signing via `evaluate_preliminary_attestation`
    (§6.3). Per §8 (Attester vs Authority), every output is
    cryptographically committed and independently verifiable.
    """

    def build_onchain_ride_identity(
        self,
        file_data_b64: str,
        file_type: str,
        file_bytes: Optional[bytes],
    ) -> OnchainRideIdentity:
        return build_onchain_ride_identity(
            file_data_b64=file_data_b64,
            file_type=file_type,
            file_bytes=file_bytes,
        )

    def parse_ride(
        self,
        file_data_b64: str,
        file_type: str,
        file_bytes: Optional[bytes],
    ) -> ParsedRide:
        """Parse raw ride material into the canonical backend ride shape."""
        if file_bytes is not None and parse_ride_file_bytes is not None:
            logger.info(
                "[RideAttester] Parsing from raw bytes "
                f"(type={file_type}, size={len(file_bytes)} bytes)"
            )
            return parse_ride_file_bytes(file_bytes, file_type)

        logger.info(
            "[RideAttester] Parsing from base64 "
            f"(type={file_type}, size={len(file_data_b64)} b64 chars)"
        )
        return parse_ride_file(file_data_b64, file_type)

    def calculate_metrics(
        self,
        parsed_ride: ParsedRide,
        user_weight_kg: float,
        user_ftp_w: int,
    ) -> RideMetrics:
        """Compute metrics from parsed records under the active parser version."""
        if (
            calculate_metrics_rust is not None
            and getattr(parsed_ride, "_native_activity", None) is not None
        ):
            return calculate_metrics_rust(
                parsed_ride,
                user_weight_kg=user_weight_kg,
                user_ftp_w=user_ftp_w,
            )
        return calculate_metrics(
            records=parsed_ride.records,
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
        )

    def evaluate_preliminary_attestation(
        self,
        ride_row: Optional[Dict[str, Any]],
        onchain_ride_identity: OnchainRideIdentity,
        file_type: str,
    ) -> PreliminaryAttestationCheck:
        return evaluate_preliminary_attestation(
            ride_row=ride_row,
            onchain_ride_identity=onchain_ride_identity,
            file_type=file_type,
        )

    def prepare_ride(
        self,
        *,
        file_data_b64: str,
        file_type: str,
        file_bytes: Optional[bytes],
        ride_row: Optional[Dict[str, Any]],
        user_weight_kg: float,
        user_ftp_w: int,
        reward_ftp_w: int = DEFAULT_REWARD_FTP_W,
    ) -> RideAttestationPreparation:
        """Build all attested truth needed before execution/projection.

        This is the boundary `RideProcessor` should call before it stores
        read models or submits chain transactions. The returned identity and
        preliminary check are consumed unchanged by Executor gates.
        """
        onchain_identity = self.build_onchain_ride_identity(
            file_data_b64=file_data_b64,
            file_type=file_type,
            file_bytes=file_bytes,
        )
        preliminary_check = self.evaluate_preliminary_attestation(
            ride_row=ride_row,
            onchain_ride_identity=onchain_identity,
            file_type=file_type,
        )
        parsed_ride = self.parse_ride(
            file_data_b64=file_data_b64,
            file_type=file_type,
            file_bytes=file_bytes,
        )
        if not parsed_ride.records:
            raise ValueError("No valid records found in file")
        user_ftp_w = validate_reward_ftp_w(user_ftp_w)
        metrics = self.calculate_metrics(
            parsed_ride=parsed_ride,
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
        )
        reward_ftp_w = validate_reward_ftp_w(reward_ftp_w)
        economic_metrics = metrics
        if reward_ftp_w != user_ftp_w:
            economic_metrics = self.calculate_metrics(
                parsed_ride=parsed_ride,
                user_weight_kg=user_weight_kg,
                user_ftp_w=reward_ftp_w,
            )
        return RideAttestationPreparation(
            onchain_identity=onchain_identity,
            preliminary_check=preliminary_check,
            parsed_ride=parsed_ride,
            metrics=metrics,
            economic_metrics=economic_metrics,
            reward_ftp_w=reward_ftp_w,
        )
