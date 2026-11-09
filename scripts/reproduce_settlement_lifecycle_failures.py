#!/usr/bin/env python3
"""Reproduce lifecycle failures found by the July 2026 Phase 2 math audit."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


DUNG_BASE_UNITS = 1_000_000_000
WEEKLY_STAKER_BUCKET = 27 * DUNG_BASE_UNITS
POSTGRES_INTEGER_MAX = (2**31) - 1


@dataclass(frozen=True)
class Diagnostic:
    name: str
    observed: str
    expected: str


def staker_carry_reunlock(weeks: int = 52, unlock_pct: int = 1) -> Diagnostic:
    carry = 0
    paid = 0
    for _ in range(weeks):
        staker_total = WEEKLY_STAKER_BUCKET + carry
        unlocked = staker_total * unlock_pct // 100
        paid += unlocked
        carry = staker_total - unlocked

    input_total = weeks * WEEKLY_STAKER_BUCKET
    effective_pct = 100 * paid / input_total
    return Diagnostic(
        name="staker carry is re-unlocked every week",
        observed=(
            f"one staker receives {paid / DUNG_BASE_UNITS:.9f} DUNG after {weeks} weeks "
            f"({effective_pct:.3f}% of the cumulative 27% bucket); "
            f"carry={carry / DUNG_BASE_UNITS:.9f} DUNG"
        ),
        expected="a one-staker vault remains on the published 1% unlock curve",
    )


def unreserved_staker_liability() -> Diagnostic:
    community_cap_remaining = 60 * DUNG_BASE_UNITS
    immediate_mints = 58 * DUNG_BASE_UNITS
    deferred_staker_claim = 27 * DUNG_BASE_UNITS
    cap_after_settlement = community_cap_remaining - immediate_mints
    shortfall = max(0, deferred_staker_claim - cap_after_settlement)
    return Diagnostic(
        name="settlement credits an unreserved DUNG liability",
        observed=(
            f"settlement succeeds with {cap_after_settlement / DUNG_BASE_UNITS:.0f} DUNG "
            f"of cap left, but creates a {deferred_staker_claim / DUNG_BASE_UNITS:.0f} DUNG "
            f"claim; immediate shortfall={shortfall / DUNG_BASE_UNITS:.0f} DUNG"
        ),
        expected="every credited staker claim is mintable or backed by a reserved liability",
    )


def queue_integer_capacity() -> Diagnostic:
    max_dung = POSTGRES_INTEGER_MAX / DUNG_BASE_UNITS
    max_cal_tribute = POSTGRES_INTEGER_MAX * 1_000 / DUNG_BASE_UNITS
    return Diagnostic(
        name="epoch queue stores DUNG base units in signed INTEGER",
        observed=(
            f"dung_to_mint overflows above {max_dung:.9f} DUNG, reached at about "
            f"{max_cal_tribute:.6f} CAL of weekly tribute"
        ),
        expected="queue amount columns hold the full on-chain u64 range as exact integers",
    )


def quiet_week_roll_deadlock() -> Diagnostic:
    current_week_value = 0
    next_week_value = 1
    backend_queues_current = current_week_value != 0 or next_week_value != 0
    chain_advances_before_check = current_week_value == 0
    fails_week_equality = backend_queues_current and chain_advances_before_check
    assert fails_week_equality
    return Diagnostic(
        name="quiet current week with staged next-week value deadlocks",
        observed=(
            "backend queues week N because N+1 has value; chain advances the empty N to N+1 "
            "before checking the argument, so the week-N transaction fails"
        ),
        expected="the crank and chain agree on which week is being finalized and can retry it",
    )


def delayed_halving() -> Diagnostic:
    current_rate_bps = 10_000
    elapsed_intervals = 2
    current_code_rate = current_rate_bps // 2
    schedule_rate = current_rate_bps // (2**elapsed_intervals)
    return Diagnostic(
        name="late halving calls lose elapsed intervals",
        observed=(
            f"after two elapsed intervals, one late call sets {current_code_rate} bps and "
            f"moves the anchor to now"
        ),
        expected=f"deterministic schedule rate is {schedule_rate} bps after two intervals",
    )


def epoch_anchor() -> Diagnostic:
    configured = datetime.fromtimestamp(1_704_020_400, tz=timezone.utc)
    return Diagnostic(
        name="canonical epoch anchor comment is one hour wrong",
        observed=f"1704020400 is {configured.isoformat()}",
        expected="the documented anchor is Sunday 2023-12-31T12:00:00+00:00",
    )


def main() -> None:
    diagnostics = (
        staker_carry_reunlock(),
        unreserved_staker_liability(),
        queue_integer_capacity(),
        quiet_week_roll_deadlock(),
        delayed_halving(),
        epoch_anchor(),
    )
    for diagnostic in diagnostics:
        print(f"FAIL: {diagnostic.name}")
        print(f"  observed: {diagnostic.observed}")
        print(f"  policy:   {diagnostic.expected}")

    print(f"\n{len(diagnostics)} reproducible Phase 2 policy failures.")


if __name__ == "__main__":
    main()
