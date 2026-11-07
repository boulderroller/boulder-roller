"""Canonical, versioned Settlement Week conversion.

The on-chain ProgramConfig is the authority for the immutable cutover. This
module contains the pure conversion used by workers, routes, scripts, and SQL
golden-vector tests; callers that can move value must construct the clock from
the decoded ProgramConfig instead of assuming a deployment date.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


LEGACY_SETTLEMENT_WEEK_ANCHOR = 1_704_020_400
SETTLEMENT_WEEK_V2_ANCHOR = 1_704_110_400
SETTLEMENT_WEEK_DURATION_SECONDS = 604_800
SETTLEMENT_FINALIZATION_GRACE_SECONDS = 86_400
SETTLEMENT_CLOCK_VERSION_V2 = 2
SETTLEMENT_CLOCK_PHASE_SHIFT_SECONDS = (
    SETTLEMENT_WEEK_V2_ANCHOR - LEGACY_SETTLEMENT_WEEK_ANCHOR
)
SETTLEMENT_CLOCK_MIN_CUTOVER_LEAD_SECONDS = 86_400


class SettlementClockError(ValueError):
    """The configured clock is absent, mutable, or mathematically invalid."""


@dataclass(frozen=True)
class SettlementWindow:
    settlement_week: int
    starts_at: int
    ends_at: int
    finalizes_at: int
    duration_seconds: int
    clock_version: int
    is_transition_week: bool


@dataclass(frozen=True)
class SettlementClock:
    v2_starts_at: int

    @classmethod
    def v2_only(cls) -> "SettlementClock":
        return cls(v2_starts_at=SETTLEMENT_WEEK_V2_ANCHOR)

    @classmethod
    def with_legacy_cutover(cls, v2_starts_at: int) -> "SettlementClock":
        if v2_starts_at <= SETTLEMENT_WEEK_V2_ANCHOR:
            raise SettlementClockError("legacy cutover must follow the v2 anchor")
        if (
            v2_starts_at - SETTLEMENT_WEEK_V2_ANCHOR
        ) % SETTLEMENT_WEEK_DURATION_SECONDS:
            raise SettlementClockError("cutover must be a Monday 12:00 UTC boundary")

        clock = cls(v2_starts_at=v2_starts_at)
        transition_week = clock.transition_week
        if transition_week is None or clock._week_from_anchor(
            v2_starts_at - 1, LEGACY_SETTLEMENT_WEEK_ANCHOR
        ) != transition_week:
            raise SettlementClockError("cutover would renumber the transition week")
        return clock

    @classmethod
    def validate_migration_cutover(
        cls, v2_starts_at: int, current_time: int
    ) -> "SettlementClock":
        clock = cls.with_legacy_cutover(v2_starts_at)
        if v2_starts_at < current_time + SETTLEMENT_CLOCK_MIN_CUTOVER_LEAD_SECONDS:
            raise SettlementClockError("cutover requires at least 24 hours lead time")
        return clock

    @classmethod
    def from_program_config(cls, program_config: Mapping[str, Any]) -> "SettlementClock":
        try:
            version = int(program_config["settlement_clock_version"])
            v2_starts_at = int(program_config["settlement_clock_v2_starts_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SettlementClockError(
                "ProgramConfig does not contain a settlement clock"
            ) from exc

        if version != SETTLEMENT_CLOCK_VERSION_V2:
            raise SettlementClockError(
                f"unsupported settlement clock version {version}"
            )
        if v2_starts_at == SETTLEMENT_WEEK_V2_ANCHOR:
            return cls.v2_only()
        return cls.with_legacy_cutover(v2_starts_at)

    @property
    def transition_week(self) -> Optional[int]:
        if self.v2_starts_at == SETTLEMENT_WEEK_V2_ANCHOR:
            return None
        if self.v2_starts_at < SETTLEMENT_WEEK_V2_ANCHOR or (
            self.v2_starts_at - SETTLEMENT_WEEK_V2_ANCHOR
        ) % SETTLEMENT_WEEK_DURATION_SECONDS:
            raise SettlementClockError("invalid settlement clock cutover")
        return self._week_from_anchor(
            self.v2_starts_at, SETTLEMENT_WEEK_V2_ANCHOR
        )

    def require_same_cutover(self, v2_starts_at: int) -> None:
        if self.v2_starts_at != v2_starts_at:
            raise SettlementClockError("settlement clock cutover is immutable")

    def week_at(self, timestamp: int) -> int:
        if self.transition_week is not None and timestamp < self.v2_starts_at:
            return self._week_from_anchor(timestamp, LEGACY_SETTLEMENT_WEEK_ANCHOR)
        return self._week_from_anchor(timestamp, SETTLEMENT_WEEK_V2_ANCHOR)

    def week_start(self, settlement_week: int) -> int:
        self._require_week(settlement_week)
        transition_week = self.transition_week
        anchor = (
            LEGACY_SETTLEMENT_WEEK_ANCHOR
            if transition_week is not None and settlement_week <= transition_week
            else SETTLEMENT_WEEK_V2_ANCHOR
        )
        return anchor + settlement_week * SETTLEMENT_WEEK_DURATION_SECONDS

    def week_end(self, settlement_week: int) -> int:
        self._require_week(settlement_week)
        if self.transition_week == settlement_week:
            return SETTLEMENT_WEEK_V2_ANCHOR + (
                settlement_week + 1
            ) * SETTLEMENT_WEEK_DURATION_SECONDS
        return self.week_start(settlement_week) + SETTLEMENT_WEEK_DURATION_SECONDS

    def week_finalization_time(self, settlement_week: int) -> int:
        return self.week_end(settlement_week) + SETTLEMENT_FINALIZATION_GRACE_SECONDS

    def week_duration(self, settlement_week: int) -> int:
        return self.week_end(settlement_week) - self.week_start(settlement_week)

    def anchor_version_at(self, timestamp: int) -> int:
        if self.transition_week is not None and timestamp < self.v2_starts_at:
            return 1
        return SETTLEMENT_CLOCK_VERSION_V2

    def latest_finalizable_week(self, timestamp: int) -> int:
        candidate = self.week_at(timestamp)
        while candidate > 0 and self.week_finalization_time(candidate) > timestamp:
            candidate -= 1
        return candidate

    def window_at(self, timestamp: int) -> SettlementWindow:
        settlement_week = self.week_at(timestamp)
        starts_at = self.week_start(settlement_week)
        ends_at = self.week_end(settlement_week)
        return SettlementWindow(
            settlement_week=settlement_week,
            starts_at=starts_at,
            ends_at=ends_at,
            finalizes_at=ends_at + SETTLEMENT_FINALIZATION_GRACE_SECONDS,
            duration_seconds=ends_at - starts_at,
            clock_version=self.anchor_version_at(timestamp),
            is_transition_week=self.transition_week == settlement_week,
        )

    @staticmethod
    def _week_from_anchor(timestamp: int, anchor: int) -> int:
        if timestamp < anchor:
            return 0
        return (timestamp - anchor) // SETTLEMENT_WEEK_DURATION_SECONDS

    @staticmethod
    def _require_week(settlement_week: int) -> None:
        if settlement_week < 0:
            raise SettlementClockError("settlement week must be non-negative")
