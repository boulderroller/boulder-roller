from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.settlement_clock import (
    LEGACY_SETTLEMENT_WEEK_ANCHOR,
    SETTLEMENT_CLOCK_VERSION_V2,
    SETTLEMENT_WEEK_DURATION_SECONDS,
    SETTLEMENT_WEEK_V2_ANCHOR,
    SettlementClock,
    SettlementClockError,
)


TRANSITION_WEEK = 200
CUTOVER = SETTLEMENT_WEEK_V2_ANCHOR + (
    TRANSITION_WEEK * SETTLEMENT_WEEK_DURATION_SECONDS
)


def test_cutover_preserves_numeric_week_and_history() -> None:
    clock = SettlementClock.with_legacy_cutover(CUTOVER)

    assert clock.week_at(CUTOVER - 1) == TRANSITION_WEEK
    assert clock.week_at(CUTOVER) == TRANSITION_WEEK
    assert clock.anchor_version_at(CUTOVER - 1) == 1
    assert clock.anchor_version_at(CUTOVER) == SETTLEMENT_CLOCK_VERSION_V2


def test_transition_week_is_eight_days_and_one_hour() -> None:
    clock = SettlementClock.with_legacy_cutover(CUTOVER)

    assert clock.week_start(TRANSITION_WEEK) == (
        LEGACY_SETTLEMENT_WEEK_ANCHOR
        + TRANSITION_WEEK * SETTLEMENT_WEEK_DURATION_SECONDS
    )
    assert clock.week_end(TRANSITION_WEEK) == (
        CUTOVER + SETTLEMENT_WEEK_DURATION_SECONDS
    )
    assert clock.week_duration(TRANSITION_WEEK) == 694_800


def test_normal_v2_week_is_monday_to_monday_and_keeps_sunday() -> None:
    clock = SettlementClock.with_legacy_cutover(CUTOVER)
    week = TRANSITION_WEEK + 1
    start = clock.week_start(week)
    end = clock.week_end(week)

    assert end - start == SETTLEMENT_WEEK_DURATION_SECONDS
    assert datetime.fromtimestamp(start, timezone.utc).strftime("%A %H:%M") == "Monday 12:00"
    assert datetime.fromtimestamp(end, timezone.utc).strftime("%A %H:%M") == "Monday 12:00"
    assert clock.week_at(start + 6 * 86_400) == week


def test_latest_finalizable_does_not_regress_at_cutover() -> None:
    clock = SettlementClock.with_legacy_cutover(CUTOVER)

    assert clock.latest_finalizable_week(CUTOVER) == TRANSITION_WEEK - 1
    assert (
        clock.latest_finalizable_week(CUTOVER + SETTLEMENT_WEEK_DURATION_SECONDS + 86_399)
        == TRANSITION_WEEK - 1
    )
    assert (
        clock.latest_finalizable_week(CUTOVER + SETTLEMENT_WEEK_DURATION_SECONDS + 86_400)
        == TRANSITION_WEEK
    )


def test_dst_transitions_do_not_change_utc_week_length() -> None:
    clock = SettlementClock.v2_only()
    new_york = ZoneInfo("America/New_York")

    for timestamp in (
        int(datetime(2026, 3, 9, 12, tzinfo=timezone.utc).timestamp()),
        int(datetime(2026, 11, 2, 12, tzinfo=timezone.utc).timestamp()),
    ):
        week = clock.week_at(timestamp)
        start = datetime.fromtimestamp(clock.week_start(week), timezone.utc)
        end = datetime.fromtimestamp(clock.week_end(week), timezone.utc)
        assert start.hour == end.hour == 12
        assert (end - start).total_seconds() == SETTLEMENT_WEEK_DURATION_SECONDS
        assert start.astimezone(new_york).tzinfo is not None


def test_program_config_clock_fails_closed() -> None:
    with pytest.raises(SettlementClockError):
        SettlementClock.from_program_config({})
    with pytest.raises(SettlementClockError):
        SettlementClock.from_program_config(
            {
                "settlement_clock_version": 1,
                "settlement_clock_v2_starts_at": CUTOVER,
            }
        )

    assert SettlementClock.from_program_config(
        {
            "settlement_clock_version": SETTLEMENT_CLOCK_VERSION_V2,
            "settlement_clock_v2_starts_at": CUTOVER,
        }
    ) == SettlementClock.with_legacy_cutover(CUTOVER)


@pytest.mark.parametrize(
    "cutover",
    [
        SETTLEMENT_WEEK_V2_ANCHOR - 1,
        SETTLEMENT_WEEK_V2_ANCHOR + 1,
        CUTOVER + 1,
    ],
)
def test_invalid_cutovers_are_rejected(cutover: int) -> None:
    with pytest.raises(SettlementClockError):
        SettlementClock.with_legacy_cutover(cutover)
