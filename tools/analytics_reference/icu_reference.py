"""Reference implementation of intervals.icu's ride arithmetic, as reconstructed on 8 Oct 2026.

Validated against intervals.icu's stored values for 30 rides analysed in February 2025: moving
time, recording time, normalized power and load matched exactly (30/30) with gap_fill_s=8.
intervals.icu has used gap_fill_s=30 since August 2025. Pure Python, no data. The Rust training
engine must agree with this module on every synthetic case.

Inputs are per-sample arrays from one ride: t_s are whole seconds from the first sample
(monotonic), power is watts or None for a missing reading, speed is metres per second.
"""
from __future__ import annotations

import math
from typing import Optional, Sequence

WINDOW_S = 30
MOVING_MIN_SPEED_MPS = 0.05
LONG_GAP_S = 30


def half_up(x: float) -> int:
    return int(math.floor(x + 0.5))


def timeline(
    t_s: Sequence[int],
    power: Sequence[Optional[int]],
    speed: Optional[Sequence[Optional[float]]],
    gap_fill_s: int = 30,
    cadence: Optional[Sequence[Optional[int]]] = None,
) -> tuple[list[float], list[bool]]:
    """1 s power and moving flags from the first to the last sample.

    A recorded second is moving when its speed is at least 0.05 m/s. Missing power counts as 0.
    A gap of up to gap_fill_s seconds is filled by linear interpolation of power, and its
    seconds are moving when both bounding samples are moving. Longer gaps are 0 W and stopped.
    """
    n = t_s[-1] + 1
    pw = [0.0] * n
    mv = [False] * n
    for i, k in enumerate(t_s):
        pw[k] = 0.0 if power[i] is None else float(power[i])
        mv[k] = (speed is not None and speed[i] is not None and math.isfinite(speed[i])
                 and speed[i] >= MOVING_MIN_SPEED_MPS)
    for i in range(len(t_s) - 1):
        a, b = t_s[i], t_s[i + 1]
        g = b - a
        if g <= 1:
            continue
        for k in range(a + 1, b):
            if g <= gap_fill_s:
                pw[k] = pw[a] + (pw[b] - pw[a]) * (k - a) / g
                mv[k] = mv[a] and mv[b]
            else:
                pw[k] = 0.0
                mv[k] = False
    if speed is None or not any(s is not None and math.isfinite(s) and s >= 0 for s in speed):
        mv = speedless_moving(t_s, cadence, gap_fill_s)
    return pw, mv


def speedless_moving(t_s, cadence=None, gap_fill_s=30):
    """PROVISIONAL: no speedless rides are represented in the local scorer.

    Cadence > 0 supplies motion when that stream exists (an extrapolation of the
    documented slow-sport rule). Otherwise count all recorded ticks, even at zero
    power, and fill gaps no greater than twice the median positive sample spacing.
    The inclusive tick convention matches the speed-based timeline above.
    https://forum.intervals.icu/t/better-moving-time-for-trail-runs-hikes-etc/7076
    https://forum.intervals.icu/t/intervals-miss-calculating-load/7823/13
    """
    mv = [False] * (t_s[-1] + 1)
    has_cadence = cadence is not None and any(c is not None for c in cadence)
    if has_cadence:
        limit = gap_fill_s
    else:
        gaps = sorted(b - a for a, b in zip(t_s, t_s[1:]) if b > a)
        limit = gaps[(len(gaps) - 1) // 2] + gaps[len(gaps) // 2] if gaps else 0
    for i, k in enumerate(t_s):
        mv[k] = not has_cadence or (cadence[i] is not None and cadence[i] > 0)
    for a, b in zip(t_s, t_s[1:]):
        if b - a <= limit:
            mv[a + 1:b] = [mv[a] and mv[b]] * max(0, b - a - 1)
    return mv


def elapsed_time(t_s: Sequence[int]) -> int:
    return t_s[-1]


def recording_time(t_s: Sequence[int]) -> int:
    """Elapsed minus 1, minus every gap longer than 30 s (reproduced 30/30)."""
    gaps = [b - a for a, b in zip(t_s, t_s[1:])]
    return t_s[-1] - 1 - sum(g for g in gaps if g > LONG_GAP_S)


def moving_time(moving: Sequence[bool]) -> int:
    return sum(1 for m in moving if m)


def normalized_power(pw: Sequence[float], moving: Sequence[bool]) -> Optional[float]:
    """30 s trailing mean over the whole timeline, partial windows from the first second,
    mean of 4th powers over moving seconds only, 4th root. Unrounded."""
    acc = 0.0
    total = 0.0
    count = 0
    for k, p in enumerate(pw):
        acc += p
        if k >= WINDOW_S:
            acc -= pw[k - WINDOW_S]
        if moving[k]:
            avg = acc / min(k + 1, WINDOW_S)
            total += avg ** 4
            count += 1
    return (total / count) ** 0.25 if count else None


def load(np_w: int, ftp_w: int, moving_s: int) -> int:
    """(whole-watt NP / FTP)^2 x moving hours x 100, rounded half up."""
    return half_up((np_w / ftp_w) ** 2 * moving_s / 3600 * 100)


def intensity_pct(np_w: int, ftp_w: int) -> float:
    return np_w * 100 / ftp_w


def summarize(t_s, power, speed, ftp_w: int, gap_fill_s: int = 30) -> dict:
    pw, mv = timeline(t_s, power, speed, gap_fill_s)
    mov = moving_time(mv)
    np_raw = normalized_power(pw, mv)
    np_w = half_up(np_raw) if np_raw is not None else None
    return {
        "elapsed_s": elapsed_time(t_s),
        "recording_s": recording_time(t_s),
        "moving_s": mov,
        "np_raw_w": np_raw,
        "np_w": np_w,
        "load": load(np_w, ftp_w, mov) if np_w is not None else None,
        "intensity_pct": intensity_pct(np_w, ftp_w) if np_w is not None else None,
    }


def repair_power_samples(t_s, power, cadence=None, gap_fill_s=30):
    """Conservative work/zone repair; does not change the phase-1 NP stream.

    Bounded missing runs carry the previous power into their first five points,
    except at recorded zero cadence. Missing readings also count as zeros when
    measuring zero-run length, so a long stop is never
    split into apparently short dropouts by a missing reading. Zero runs shorter
    than ten points may carry the last power when the preceding five readings are
    positive and within 10% of that last reading. A recorded zero cadence protects
    that point. Never bridge a recording gap. Model-curve spike repair remains
    unresolved: FTP alone does not supply that curve. Do not invent a watt cap.

    The short-zero rule follows the developer's description at
    https://forum.intervals.icu/t/significant-paused-time-inflates-activity-load/1303/13
    Its exact stability predicate remains a conformance limitation.
    """
    result = [0.0 if p is None else float(p) for p in power]
    for missing in (True, False):
        i = 0
        while i < len(power):
            bad = lambda k: power[k] is None if missing else power[k] in (None, 0)
            if not bad(i):
                i += 1
                continue
            a = i
            while i < len(power) and bad(i):
                i += 1
            b = i
            if a == 0 or b == len(power) or (not missing and b - a > 9):
                continue
            if any(t_s[k + 1] - t_s[k] > gap_fill_s for k in range(a - 1, b)):
                continue
            if missing:
                for k in range(a, min(b, a + 5)):
                    if cadence is None or cadence[k] != 0:
                        result[k] = result[a - 1]
            elif a >= 5:
                last = result[a - 1]
                if last > 0 and all(p > 0 and abs(p - last) <= last * 0.1 for p in result[a - 5:a]):
                    for k in range(a, b):
                        if power[k] == 0 and (cadence is None or cadence[k] != 0):
                            result[k] = last
    return result


def power_zone_times(power, moving, ftp_w, tops_pct=None, sweet_spot_pct=None):
    """Rounded, trailing five-second means; inclusive whole-watt zone tops.

    Z1..Z7 are disjoint. Sweet Spot overlaps them. Stopped seconds stay in the
    averaging window but do not contribute zone time. Input is the repaired stream.
    """
    tops = [math.floor(ftp_w * p / 100) for p in (tops_pct or [55, 75, 90, 105, 120, 150])[:6]]
    low, high = [math.floor(ftp_w * p / 100) for p in (sweet_spot_pct or [84, 97])]
    counts = [0] * 8
    for k, is_moving in enumerate(moving):
        if is_moving:
            window = power[max(0, k - 4):k + 1]
            p = half_up(sum(window) / len(window))
            counts[next((z for z, top in enumerate(tops) if p <= top), 6)] += 1
            counts[7] += low <= p <= high
    return counts


def hr_zone_times(heart_rate, moving, tops_bpm):
    """Inclusive bpm tops over the independently prepared HR timeline."""
    counts = [0] * len(tops_bpm)
    for h, m in zip(heart_rate, moving):
        if m and h is not None and h > 0:
            counts[next((z for z, top in enumerate(tops_bpm) if h <= top), len(counts) - 1)] += 1
    return counts


def hr_zone_timeline(t_s, heart_rate, moving, gap_fill_s=30, has_speed=True):
    """Hold HR over gaps <= 30 s, with both endpoints moving when speed exists.

    Bounded missing/zero HR runs carry the prior HR into their first five recorded
    points, including at a stop. Never bridge a clock gap longer than gap_fill_s
    for that carry. Full endpoint conformance remains unresolved. No smoothing.
    Speedless inputs retain their provisional cadence/recording movement mask.
    """
    samples = [0] * (t_s[-1] + 1)
    active = list(moving)
    for k, h in zip(t_s, heart_rate):
        samples[k] = h or 0
    for a, b in zip(t_s, t_s[1:]):
        if 1 < b - a <= 30:
            samples[a + 1:b] = [samples[a]] * (b - a - 1)
            if has_speed:
                active[a + 1:b] = [active[a] and active[b]] * (b - a - 1)
    i = 0
    while i < len(heart_rate):
        if heart_rate[i]:
            i += 1
            continue
        a = i
        while i < len(heart_rate) and not heart_rate[i]:
            i += 1
        b = i
        if a == 0 or b == len(heart_rate):
            continue
        if any(t_s[k + 1] - t_s[k] > gap_fill_s for k in range(a - 1, b)):
            continue
        for k in range(a, min(b, a + 5)):
            if t_s[k] < t_s[k + 1]:
                samples[t_s[k]] = heart_rate[a - 1]
                active[t_s[k]] = True
    return samples, active


def rounded_ratio(np_w, average):
    """VI and EF use the whole-watt / whole-bpm denominator."""
    denominator = half_up(average)
    return np_w / denominator if denominator > 0 else None


def calories(work_j=None, device_kcal=None):
    """Device first; otherwise a PROVISIONAL 24% gross-efficiency estimate.

    Work-based estimates do not establish ICU's device/provider calorie method.
    This assumption improves each scored residual over the prior 22% fallback.
    """
    return device_kcal if device_kcal is not None else (
        work_j / 1000 / 4.184 / 0.24 if work_j is not None else None
    )


def sensor_summary(samples, device_avg=None, device_max=None):
    """HR prefers session average/max; cadence averages positive recorded samples.

    Missing readings are None. Recorded zeros are excluded from these summaries.
    """
    valid = [v for v in samples if v is not None and v > 0]
    average = sum(valid) / len(valid) if valid else None
    maximum = max(valid) if valid else None
    return (device_avg if device_avg is not None else average,
            device_max if device_max is not None else maximum)


def distance_and_gain(distance, elevation, device_distance=None, device_gain=None):
    """Session totals first; otherwise maximum distance and positive ascent deltas.

    The stream ascent fallback is provisional; no device total is synthesized.
    """
    distance = [v for v in distance if v is not None and math.isfinite(v) and v >= 0]
    elevation = [v for v in elevation if v is not None and math.isfinite(v)]
    raw_distance = max(distance) if distance else None
    raw_gain = sum(max(0, b - a) for a, b in zip(elevation, elevation[1:])) if len(elevation) >= 2 else None
    return (device_distance if device_distance is not None else raw_distance,
            device_gain if device_gain is not None else raw_gain)
