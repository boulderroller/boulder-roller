"""Canonical integer policy for measured climb-TSS Vault tribute."""

from __future__ import annotations

from collections.abc import Iterable

from .protocol_ints import U16_MAX, U32_MAX, U64_MAX, exact_positive_uint, exact_uint


CAL_BASE_UNITS_PER_CAL = 1_000_000_000
MILLIWATTS_PER_WATT = 1_000
TSS_PERCENT_SCALE = 100
SECONDS_PER_HOUR = 3_600
CAL_TRIBUTE_POLICY_VERSION = "cal_tribute_segment_tss_v2"
CAL_TRIBUTE_POWER_METRICS_VERSION = "workout_parse_metrics_v1"
MIN_SEGMENT_POWER_SAMPLE_COUNT = 30
MIN_SEGMENT_POWER_COVERAGE_BPS = 5_000


def calculate_segment_tss_base_units(
    *,
    segment_np_duration_s: int,
    segment_np_milliwatts: int | None,
    reward_ftp_w: int,
) -> int:
    """Return one climb window's TSS as exact CAL base units.

    The integer form is equivalent to:

        duration_hours * (segment_np / reward_ftp) ** 2 * 100 CAL

    NP is frozen in milliwatts so every verifier uses the same rational value.
    Each climb is floored independently to one CAL base unit.
    """
    duration_s = exact_uint(
        segment_np_duration_s,
        field="segment_np_duration_s",
        maximum=U32_MAX,
    )
    ftp_w = exact_positive_uint(
        reward_ftp_w,
        field="reward_ftp_w",
        maximum=U16_MAX,
    )
    if segment_np_milliwatts is None:
        return 0
    np_mw = exact_uint(
        segment_np_milliwatts,
        field="segment_np_milliwatts",
        maximum=U16_MAX * MILLIWATTS_PER_WATT,
    )
    if duration_s == 0 or np_mw == 0:
        return 0
    numerator = (
        duration_s
        * np_mw
        * np_mw
        * TSS_PERCENT_SCALE
        * CAL_BASE_UNITS_PER_CAL
    )
    denominator = (
        ftp_w
        * ftp_w
        * MILLIWATTS_PER_WATT
        * MILLIWATTS_PER_WATT
        * SECONDS_PER_HOUR
    )
    return exact_uint(
        numerator // denominator,
        field="segment_tss_base_units",
        maximum=U64_MAX,
    )


def calculate_ride_tribute_budget(
    exact_cal_base_units: int,
    segment_tss_base_units: Iterable[int],
) -> int:
    """Return the sum of measured climb TSS, bounded by attested ride CAL."""
    cal_base_units = exact_uint(
        exact_cal_base_units,
        field="exact_cal_base_units",
        maximum=U64_MAX,
    )
    budget = 0
    for value in segment_tss_base_units:
        budget += exact_uint(
            value,
            field="segment_tss_base_units",
            maximum=U64_MAX,
        )
        if budget > U64_MAX:
            raise ValueError("exact_tribute_budget_base_units exceeds u64")
    if budget > cal_base_units:
        raise ValueError("measured climb TSS exceeds full attested CAL")
    return budget


def calculate_intensity_bps(
    *, segment_np_milliwatts: int | None, reward_ftp_w: int
) -> int:
    """Return evidence-only IF basis points from the frozen reward FTP."""
    ftp_w = exact_positive_uint(
        reward_ftp_w,
        field="reward_ftp_w",
        maximum=U16_MAX,
    )
    if segment_np_milliwatts is None:
        return 0
    np_mw = exact_uint(
        segment_np_milliwatts,
        field="segment_np_milliwatts",
        maximum=U16_MAX * MILLIWATTS_PER_WATT,
    )
    return np_mw * 10_000 // (ftp_w * MILLIWATTS_PER_WATT)
