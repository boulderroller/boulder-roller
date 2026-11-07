"""Canonical client-facing protocol DTOs.

These models are the stable seam between Boulder Rollers protocol truth and
client surfaces. Backend storage tables, indexer rows, and compatibility routes
may retain older names during migration, but mobile, portal, and BoulderScan
should depend on these concepts.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, List, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator


CLIENT_CONTRACT_VERSION = "client.v1"


class TruthSource(str, Enum):
    """Where a DTO's economic truth comes from."""

    onchain = "onchain"
    attested = "attested"
    projected = "projected"
    compatibility = "compatibility"


class ClientContractModel(BaseModel):
    """Base config for client DTOs.

    The backend emits snake_case JSON today; web/mobile clients normalize to
    camelCase at their API boundary. Aliases are accepted so tests and future
    generated clients can instantiate these models in either casing.
    """

    model_config = ConfigDict(populate_by_name=True)


class CarryBuckets(ClientContractModel):
    """Undistributed DUNG carry by settlement bucket."""

    record_royalty: str = "0"
    record_royalty_base_units: str = "0"
    stakers: str = "0"
    stakers_base_units: str = "0"
    local_legend: str = "0"
    local_legend_base_units: str = "0"
    pol: str = "0"
    pol_base_units: str = "0"
    treasury: str = "0"
    treasury_base_units: str = "0"
    total: str = "0"
    total_base_units: str = "0"


class VaultEconomy(ClientContractModel):
    """Optional economic wrapper around a Climb.

    Climb is the canonical geographic object. VaultEconomy is present when the
    climb has an on-chain economic wrapper.
    """

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.projected
    has_vault: bool = False
    vault_id: Optional[int] = None
    vault_signature: Optional[str] = None
    total_staked: str = "0"
    total_staked_base_units: str = "0"
    total_cal_staked: str = "0"
    total_cal_staked_base_units: str = "0"
    total_completions: int = 0
    current_carry: Optional[CarryBuckets] = None


class VaultCreationAvailability(ClientContractModel):
    """Whether this exact immutable Climb revision can receive a Vault."""

    state: Literal["available", "reserved", "active", "unavailable"] = "unavailable"
    payment_methods: List[Literal["dung", "cal_usdc"]] = Field(default_factory=list)


class ClimbElevationPoint(ClientContractModel):
    """One real sample from the immutable canonical elevation profile."""

    distance_m: float = Field(ge=0)
    elevation_m: float


class ClimbSummary(ClientContractModel):
    """Canonical summary of a geographic climb."""

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.projected
    id: str
    canon_id: Optional[UUID] = None
    version: Optional[int] = Field(default=None, ge=1, le=65535)
    revision_state: Optional[Literal["current", "retired"]] = None
    name: Optional[str] = None
    length_m: Optional[float] = None
    elev_gain_m: Optional[float] = None
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    avg_gradient_pct: Optional[float] = None
    category: Optional[str] = None
    region: Optional[str] = None
    vault_economy: VaultEconomy = Field(default_factory=VaultEconomy)
    vault_creation: VaultCreationAvailability = Field(
        default_factory=VaultCreationAvailability
    )
    # Flat compatibility fields retained until client migration finishes.
    vault_id: Optional[int] = None
    vault_signature: Optional[str] = None
    has_vault: bool = False
    total_staked: str = "0"
    total_staked_base_units: str = "0"
    total_cal_staked: str = "0"
    total_cal_staked_base_units: str = "0"
    total_completions: int = 0
    route_preview: Optional[dict[str, Any]] = None
    elevation_profile: List[ClimbElevationPoint] = Field(default_factory=list)

    @model_validator(mode="after")
    def mirror_vault_economy(self) -> "ClimbSummary":
        if self.vault_economy.has_vault or self.vault_economy.vault_id is not None:
            if self.vault_id is None:
                self.vault_id = self.vault_economy.vault_id
            if self.vault_signature is None:
                self.vault_signature = self.vault_economy.vault_signature
            self.has_vault = self.vault_economy.has_vault
            self.total_staked = self.vault_economy.total_staked
            self.total_staked_base_units = self.vault_economy.total_staked_base_units
            self.total_cal_staked = self.vault_economy.total_cal_staked
            self.total_cal_staked_base_units = self.vault_economy.total_cal_staked_base_units
            self.total_completions = self.vault_economy.total_completions
        elif self.has_vault or self.vault_id is not None:
            self.vault_economy = VaultEconomy(
                has_vault=self.has_vault,
                vault_id=self.vault_id,
                vault_signature=self.vault_signature,
                total_staked=self.total_staked,
                total_staked_base_units=self.total_staked_base_units,
                total_cal_staked=self.total_cal_staked,
                total_cal_staked_base_units=self.total_cal_staked_base_units,
                total_completions=self.total_completions,
            )
        return self


class ClimbDetail(ClimbSummary):
    """Full client-facing climb detail."""

    record_board: Optional["RecordBoard"] = None
    local_legend: Optional["LocalLegendStatus"] = None
    settlement_status: Optional["SettlementStatus"] = None


class RecordBoardEntry(ClientContractModel):
    """All-time competitive truth for one Record Board row."""

    # Additive client.v1 metadata. Old cached payloads remain valid; current
    # server responses always project concrete values.
    position: Optional[int] = None
    rank: int
    competition_rank: Optional[int] = None
    tie_size: Optional[int] = None
    is_tied: bool = False
    wallet: str
    best_time_seconds: Optional[int] = None
    avg_power_w: Optional[float] = None
    power_kind: Optional[Literal["measured", "estimated"]] = None
    estimated_power_w: Optional[float] = None
    estimated_power_range_w: Optional[list[float]] = Field(default=None, min_length=2, max_length=2)
    effort_id: Optional[str] = None
    # Present only after the effort audience/span check for this viewer.
    ride_id: Optional[str] = None
    w_per_kg: Optional[float] = None
    place_source: Optional[Literal["onchain", "offchain_completions", "rides"]] = None
    completion_id: Optional[str] = None
    achieved_at: Optional[Union[datetime, str]] = None
    vault_signature: Optional[str] = None
    # Optional public profile metadata for display only. Rank, wallet, time, and
    # projection/on-chain rows remain the competitive truth.
    user_id: Optional[str] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None

    @model_serializer(mode="wrap")
    def omit_unshared_wkg(self, handler):
        result = handler(self)
        if self.w_per_kg is None:
            result.pop("w_per_kg", None)
        return result


class RecordBoard(ClientContractModel):
    """All-time top riders for a Climb."""

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.onchain
    source: Literal["onchain", "rides"] = "onchain"
    earlier_version_id: Optional[str] = None
    climb_id: str
    climb_name: Optional[str] = None
    # Back-compat aliases for segment-era clients. New clients should read
    # climb_id / climb_name.
    segment_id: Optional[str] = None
    segment_name: Optional[str] = None
    vault_id: Optional[int] = None
    entries: list[RecordBoardEntry] = Field(default_factory=list)
    # Back-compat alias used by existing portal/mobile code.
    leaderboard: list[RecordBoardEntry] = Field(default_factory=list)
    kom_holder: Optional[str] = None
    kom_time_s: Optional[int] = None
    viewer_entry: Optional[RecordBoardEntry] = None

    @model_validator(mode="after")
    def mirror_leaderboard_alias(self) -> "RecordBoard":
        if self.entries and not self.leaderboard:
            self.leaderboard = self.entries
        if self.leaderboard and not self.entries:
            self.entries = self.leaderboard
        if self.segment_id is None:
            self.segment_id = self.climb_id
        if self.segment_name is None:
            self.segment_name = self.climb_name
        return self


class EffortThreshold(ClientContractModel):
    value: float
    estimate: bool = False
    basis: Optional[str] = None


class EffortStopCost(ClientContractModel):
    estimate: Literal[True] = True
    basis: Literal["adjacent_pace_replacement"] = "adjacent_pace_replacement"
    seconds: float
    range_s: list[float] = Field(min_length=2, max_length=2)


class EffortStop(ClientContractModel):
    start_s: float
    end_s: float
    duration_s: float
    start_m: Optional[float] = None
    end_m: Optional[float] = None
    cost: Optional[EffortStopCost] = None


class ClimbPatternPower(ClientContractModel):
    """Audience-filtered power on a ride pattern; unknown provenance is absent."""

    avg_power_w: Optional[float] = None
    estimated_power_w: Optional[float] = None
    estimated_power_range_w: Optional[list[float]] = Field(default=None, min_length=2, max_length=2)
    power_kind: Optional[Literal["measured", "estimated"]] = None
    power_estimate_basis: Optional[str] = None
    np_w: Optional[int] = None
    intensity_factor: Optional[float] = None
    load: Optional[int] = None
    threshold: Optional[EffortThreshold] = None
    variability_index: Optional[float] = None
    max_power_w: Optional[float] = None
    best_30s_w: Optional[float] = None
    best_60s_w: Optional[float] = None
    power_zone_s: Optional[list[float]] = None
    power_zone_tops_w: Optional[list[int]] = None
    w_per_kg: Optional[float] = None


class ClimbEffortMetrics(ClimbPatternPower):
    """Allowlist: neither numeric mass nor arbitrary stored JSON is transport."""

    engine_version: int
    time_s: int
    power_kind: Literal["measured", "estimated"]
    moving_s: Optional[float] = None
    distance_m: Optional[float] = None
    net_gain_m: Optional[float] = None
    vam_m_per_hour: Optional[float] = None
    avg_cadence_rpm: Optional[float] = None
    max_cadence_rpm: Optional[float] = None
    avg_torque_nm: Optional[float] = None
    max_torque_nm: Optional[float] = None
    avg_speed_mps: Optional[float] = None
    avg_hr_bpm: Optional[float] = None
    max_hr_bpm: Optional[float] = None
    stops: list[EffortStop] = Field(default_factory=list)


class ClimbEffort(ClientContractModel):
    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    effort_id: str
    climb_id: str
    ride_id: str
    canon_version: int
    achieved_at: Union[datetime, str]
    metrics: ClimbEffortMetrics


class LocalLegendStatus(ClientContractModel):
    """Recent stewardship state for a Climb."""

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.onchain
    climb_id: str
    vault_id: Optional[int] = None
    wallet: Optional[str] = None
    attempts_in_window: int = 0
    elected_at: Optional[Union[datetime, str]] = None
    is_bootstrap: bool = False
    seat_status: Literal["bootstrap", "elected", "inactive", "none"] = "none"
    founder_wallet: Optional[str] = None
    founder_residual_recipient: Optional[str] = None


class SettlementStatus(ClientContractModel):
    """Economic finality for a settlement window."""

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.onchain
    settlement_week: int
    finalized_at: Optional[Union[datetime, str]] = None
    distributed_at: Optional[Union[datetime, str]] = None
    vault_id: Optional[int] = None
    vault_signature: Optional[str] = None
    total_amount: str = "0"
    total_amount_base_units: str = "0"
    record_royalty_amount: str = "0"
    record_royalty_amount_base_units: str = "0"
    staker_amount: str = "0"
    staker_amount_base_units: str = "0"
    local_legend_amount: str = "0"
    local_legend_amount_base_units: str = "0"
    pol_amount: str = "0"
    pol_amount_base_units: str = "0"
    treasury_amount: str = "0"
    treasury_amount_base_units: str = "0"
    current_carry: CarryBuckets = Field(default_factory=CarryBuckets)
    # Compatibility with legacy epoch wording during client rollout.
    epoch: Optional[int] = None

    @model_validator(mode="after")
    def mirror_epoch_alias(self) -> "SettlementStatus":
        if self.epoch is None:
            self.epoch = self.settlement_week
        return self


class RideAttestationStatus(ClientContractModel):
    """Proof state for a ride's canonical attestation."""

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.attested
    ride_id: str
    status: str
    attestation_status: str = "pending"
    ride_hash_hex: Optional[str] = None
    attestation_commitment_hex: Optional[str] = None
    parser_version: Optional[int] = None
    preliminary_ride_hash_hex: Optional[str] = None
    preliminary_parser_version: Optional[int] = None
    canonical_match: Optional[bool] = None
    review_reason: Optional[str] = None
    ride_attestation_pda: Optional[str] = None
    ride_attestation_tx_signature: Optional[str] = None
    ride_attested_at: Optional[Union[datetime, str]] = None
    finalized_at: Optional[Union[datetime, str]] = None
    import_source: Optional[str] = None
    import_source_id: Optional[str] = None
    import_diagnostics: Optional[dict[str, Any]] = None


class RideStatusMetrics(ClientContractModel):
    """Ride reading metric block exposed by the ride status endpoint."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    tss: Optional[float] = None
    threshold_training_state: Optional[Literal["pending"]] = None
    training_metrics: Optional[dict[str, Any]] = None
    moving_time_sec: Optional[float] = None
    recording_time_sec: Optional[float] = None
    kcals: Optional[float] = None
    distance_m: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    duration_sec: Optional[int] = None
    avg_power_w: Optional[float] = None
    normalized_power_w: Optional[float] = None


class RideEarnings(ClientContractModel):
    """Client-facing earned-token and settlement state for a ride."""

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.onchain
    ride_id: str
    cal_earned: Optional[int] = None
    dung_earned: Optional[int] = None
    finalized_at: Optional[Union[datetime, str]] = None
    settlement_status: Optional[SettlementStatus] = None


class RideEffortEconomy(ClientContractModel):
    """Ride-level effort evidence and economy policy.

    ``estimated_cal`` may exist for route-only rides, but only
    ``rewardable_cal`` and ``tributable_cal`` are allowed to move value.
    """

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.projected
    effort_evidence_tier: Optional[
        Literal["route_only", "sensor_supported", "power_verified", "manual_review"]
    ] = None
    reward_policy: Optional[
        Literal[
            "rewardable",
            "estimated_only",
            "manual_review",
            "not_counted",
            "threshold_provisional_hold_v1",
        ]
    ] = None
    threshold_economy_state: Optional[
        Literal["held", "counted", "lapsed", "review", "not_counted"]
    ] = None
    estimated_cal: Optional[int] = None
    rewardable_cal: Optional[int] = None
    tributable_cal: Optional[int] = None
    threshold_release_status: Optional[
        Literal[
            "held", "lapsed", "planning", "not_counted",
            "under_review", "releasing", "released",
        ]
    ] = None


class RideClimbEarning(ClientContractModel):
    """One climb-level economic consequence from a processed ride.

    This powers the post-ride cascade without forcing clients to infer
    protocol facts from generic ride metrics. Rows are populated from backend
    read projections of chain-backed completions; ``truth_source`` is explicit
    because older/dev rows may exist before the on-chain tx mirror lands.
    """

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.attested
    ride_id: str
    climb_id: str
    climb_name: Optional[str] = None
    # Frozen economic plan pattern id (== climb pattern id on the ride's
    # patterns endpoint). Join key so clients never need signature heuristics.
    pattern_id: Optional[str] = None
    vault_id: Optional[int] = None
    vault_signature: Optional[str] = None
    cal_tribute: Optional[int] = None
    tribute_truth_source: TruthSource = TruthSource.projected
    completion_evidence_version: Optional[int] = None
    tribute_bound: bool = False
    completion_time_s: Optional[int] = None
    record_board_rank: Optional[int] = None
    record_board_best_time_s: Optional[int] = None
    is_new_personal_best: Optional[bool] = None
    is_new_kom: Optional[bool] = None
    tx_signature: Optional[str] = None
    completed_at: Optional[Union[datetime, str]] = None


class RideProgression(ClientContractModel):
    """Owner training read carried by status. tss_delta is the frozen training
    load (power or HRSS), never economic TSS; unavailable scores stay absent.
    """

    contract_version: Literal["client.v1"] = CLIENT_CONTRACT_VERSION
    truth_source: TruthSource = TruthSource.projected
    ride_id: str
    tss_delta: Optional[float] = None
    total_tss_after: Optional[float] = None
    level_delta: Optional[int] = None
    level_after: Optional[int] = None


class RideProcessingFailure(ClientContractModel):
    """Readable failure state for a ride lifecycle.

    Clients should not scrape phase-specific error fields to decide whether a
    rider can retry. The raw phase fields remain for diagnostics; this object
    is the rider-facing contract.
    """

    phase: Literal[
        "upload",
        "queue",
        "metrics",
        "enrichment",
        "settlement",
        "processing",
        "unknown",
    ] = "unknown"
    message: str
    retryable: bool = False
    code: Optional[str] = None


class RideInputQuality(ClientContractModel):
    """Ride source quality summarized for clients.

    This deliberately separates "sensor absent" from "sensor bad". A rider
    without a power meter should see honest absence, not a fake zero or a
    hidden degradation.
    """

    status: Literal["unknown", "clean", "degraded", "invalid"] = "unknown"
    sensor_data_state: Literal["unknown", "absent", "partial", "present"] = "unknown"
    integrity_score: Optional[float] = None
    sample_count: Optional[int] = None
    flags: list[str] = Field(default_factory=list)
    degradation_reasons: list[str] = Field(default_factory=list)
    gps_coverage: Optional[float] = None
    elevation_coverage: Optional[float] = None
    sampling_regularity: Optional[float] = None
    max_gap_s: Optional[int] = None
    power_coverage: Optional[float] = None
    heart_rate_coverage: Optional[float] = None
    speed_coverage: Optional[float] = None
    import_quality_tier: Optional[str] = None


class RideStatusResponse(RideAttestationStatus):
    """Full progressive ride-processing status response.

    This model is the executable contract for ``GET /rides/{id}/status``.
    Keeping the whole route response here prevents the status endpoint from
    drifting into a fourth, route-local truth shape.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # Tim S3: caption empty; these facts do not authorize numeric rider copy.
    effort_seconds: Optional[int] = Field(default=None, alias="effortSeconds")
    covered_effort_seconds: Optional[int] = Field(default=None, alias="coveredEffortSeconds")
    paid_effort_seconds: Optional[int] = Field(default=None, alias="paidEffortSeconds")
    subject_states: dict[str, dict[str, str | None]] = Field(default_factory=dict)
    error_message: Optional[str] = None
    processing_stage: Literal[
        "uploading",
        "queued",
        "processing",
        "metrics_ready",
        "enriched",
        "under_review",
        "completed",
        "failed",
        "unknown",
    ] = "unknown"
    can_retry_processing: bool = False
    failure: Optional[RideProcessingFailure] = None
    input_quality: RideInputQuality = Field(default_factory=RideInputQuality)
    phase1_error: Optional[str] = None
    phase2_error: Optional[str] = None
    phase3_error: Optional[str] = None
    phase1_completed_at: Optional[Union[datetime, str]] = None
    phase2_completed_at: Optional[Union[datetime, str]] = None
    phase3_completed_at: Optional[Union[datetime, str]] = None
    phase1_duration_ms: Optional[int] = None
    phase2_duration_ms: Optional[int] = None
    phase3_duration_ms: Optional[int] = None
    metrics: Optional[RideStatusMetrics] = None
    has_gps: bool = False
    has_patterns: bool = False
    has_leaderboards: bool = False
    has_achievements: bool = False
    cal_earned: Optional[int] = None
    dung_minted: Optional[int] = None
    tx_signature: Optional[str] = None
    earnings: Optional[RideEarnings] = None
    effort_policy: Optional[RideEffortEconomy] = None
    climb_earnings: list[RideClimbEarning] = Field(default_factory=list)
    progression: Optional[RideProgression] = None


CLIENT_CONTRACT_MODELS: dict[str, type[ClientContractModel]] = {
    "CarryBuckets": CarryBuckets,
    "VaultEconomy": VaultEconomy,
    "ClimbSummary": ClimbSummary,
    "ClimbDetail": ClimbDetail,
    "RecordBoardEntry": RecordBoardEntry,
    "RecordBoard": RecordBoard,
    "ClimbEffort": ClimbEffort,
    "ClimbEffortMetrics": ClimbEffortMetrics,
    "ClimbPatternPower": ClimbPatternPower,
    "LocalLegendStatus": LocalLegendStatus,
    "SettlementStatus": SettlementStatus,
    "RideAttestationStatus": RideAttestationStatus,
    "RideStatusMetrics": RideStatusMetrics,
    "RideEarnings": RideEarnings,
    "RideEffortEconomy": RideEffortEconomy,
    "RideClimbEarning": RideClimbEarning,
    "RideProgression": RideProgression,
    "RideProcessingFailure": RideProcessingFailure,
    "RideInputQuality": RideInputQuality,
    "RideStatusResponse": RideStatusResponse,
}


def client_contract_json_schema() -> dict[str, Any]:
    """Return the canonical JSON Schema bundle for client.v1 DTOs.

    Tests validate golden payloads against this bundle so mobile, portal, and
    BoulderScan have one executable contract instead of hand-maintained shape
    assumptions.
    """

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Boulder Roller client.v1 contract",
        "contract_version": CLIENT_CONTRACT_VERSION,
        "schemas": {
            name: model.model_json_schema(ref_template=f"#/schemas/{name}/$defs/{{model}}")
            for name, model in CLIENT_CONTRACT_MODELS.items()
        },
    }
