"""Versioned canonical-effort reads. Never used for pay or traversal admission."""

from __future__ import annotations

import math
from bisect import bisect_left
from datetime import datetime, timedelta
from itertools import accumulate

EFFORT_ENGINE_VERSION = 3


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def _half_up(value):
    return math.floor(value + 0.5)


def _rolling(values, seconds):
    prefix = [0.0, *accumulate(values)]
    return [(prefix[i + 1] - prefix[max(0, i + 1 - seconds)]) / min(i + 1, seconds)
            for i in range(len(values))]


def effort_timeline(activity):
    """Use the native Training v3 cleaner once, over the entire ride."""
    import workout_parse as wp

    timeline = dict(wp.training_timeline(activity))
    timeline["np_30s_w"] = _rolling(timeline["np_power_w"], 30)
    timeline["zone_5s_w"] = _rolling(timeline["power_w"], 5)
    # Stop evidence belongs to this read engine. Shared Training moving/NP
    # remains exactly as exported, including its treatment of long gaps.
    speed = timeline["speed_mps"]
    times = timeline["recording_sample_s"]
    raw_speed, raw_distance = timeline["recording_speed_mps"], timeline["recording_distance_m"]
    timeline["stop_gap_indexes"] = set()
    for j in range(len(times) - 1):
        a, b = times[j:j + 2]
        # Ordinary sparse sampling retains the cleaner's interpolation. Only
        # gaps beyond its 30-second bound need separate pause evidence.
        if b - a <= 30:
            continue
        slow_edge = any(v is not None and v < 1 for v in raw_speed[j:j + 2])
        da, db = raw_distance[j:j + 2]
        continuous = _same_distance_component(timeline, a, b)
        barely_advanced = continuous and da is not None and db is not None and 0 <= db - da < b - a
        if slow_edge or barely_advanced:
            timeline["stop_gap_indexes"].add(j)
            # The last sample before a GPS-only gap has no speed of its own; fill it too,
            # so an iOS auto-pause (slow samples, then no samples) stays one stop.
            first = math.floor(a) + (speed[math.floor(a)] is not None)
            for i in range(first, math.floor(b)):
                speed[i] = (db - da) / (b - a) if barely_advanced else 0.0
    if all(d is None for d in timeline["distance_m"]):
        distance = [0.0]
        for speed in timeline["speed_mps"][:-1]:
            distance.append(distance[-1] + speed
                            if distance[-1] is not None and speed is not None else None)
        timeline["distance_m"] = distance
    return timeline


def canonical_span(pattern):
    """The accepted raw D11 crossings, not rounded detector offsets."""
    from .canon_traversal import authoritative_canon_climb_id

    if authoritative_canon_climb_id(pattern) is None:
        raise ValueError("canonical effort requires an authoritative D11 traversal")
    trace = pattern["match_trace"]
    gates = trace.get("gate_crossings") or {}
    start = _number(gates.get("start_time_s_raw"))
    end = _number(gates.get("finish_time_s_raw"))
    if start is None or end is None or not 0 <= start < end:
        raise ValueError("canonical effort requires exact gate crossings")
    return start, end


def _at(values, time):
    lo = math.floor(time)
    if lo >= len(values) or values[lo] is None:
        return None
    if time == lo:
        return values[lo]
    if lo + 1 >= len(values) or values[lo + 1] is None:
        return None
    return values[lo] + (values[lo + 1] - values[lo]) * (time - lo)


def _distance_at(timeline, time):
    raw = timeline.get("distance_samples_m")
    if raw and any(d is not None for d in raw):
        times = timeline["distance_sample_s"]
        i = bisect_left(times, time)
        if i < len(times) and times[i] == time:
            return raw[i]
        if (0 < i < len(times) and _same_distance_component(timeline, times[i - 1], times[i])
                and (times[i] - times[i - 1] <= 30 or i - 1 in timeline.get("stop_gap_indexes", set()))):
            a, b = raw[i - 1], raw[i]
            if a is not None and b is not None:
                return a + (b - a) * (time - times[i - 1]) / (times[i] - times[i - 1])
        return None
    distance = _at(timeline["distance_m"], time)
    if distance is None and math.floor(time) == len(timeline["distance_m"]) - 1:
        last, speed = timeline["distance_m"][-1], timeline["speed_mps"][-1]
        if last is not None and speed is not None and time <= timeline["duration_s"]:
            return last + (time - math.floor(time)) * speed
    return distance


def _same_distance_component(timeline, start, end):
    components = timeline.get("distance_components")
    if not components or not any(c is not None for c in components):
        return True  # no distance channel; the speed-integrated fallback may still be usable
    times = timeline["distance_sample_s"]
    index = bisect_left(times, start)
    first = index if index < len(times) and times[index] == start else max(0, index - 1)
    last = min(bisect_left(times, end), len(times) - 1)
    return components[first] is not None and components[first] == components[last]


def _stops(timeline, start, end, canon_distance_m):
    speed = timeline["speed_mps"]
    origin = _distance_at(timeline, start)
    finish_distance = _distance_at(timeline, end)
    scale = (canon_distance_m / (finish_distance - origin)
             if origin is not None and finish_distance is not None and finish_distance > origin
             and _same_distance_component(timeline, start, end) else None)
    stops = []
    run_start = None
    for i in range(math.floor(start), math.ceil(end) + 1):
        low = i < math.ceil(end) and speed[i] is not None and speed[i] < 1
        if low and run_start is None:
            run_start = max(start, i)
        if not low and run_start is not None:
            finish = min(end, i)
            duration = finish - run_start
            if duration >= 3:
                a, b = _distance_at(timeline, run_start), _distance_at(timeline, finish)
                stop = {"start_s": run_start - start, "end_s": finish - start,
                        "duration_s": duration}
                if scale is not None and a is not None and b is not None:
                    stop.update(start_m=min(canon_distance_m, max(0, a - origin) * scale),
                                end_m=min(canon_distance_m, max(0, b - origin) * scale))
                if a is not None and b is not None and _same_distance_component(timeline, run_start, finish):
                    # Up to ten immediately adjacent moving seconds each side.
                    # Do not bridge another stop or an unobserved recording gap.
                    sides = []
                    for lo, hi, reverse in (
                        (max(start, run_start - 10), run_start, True),
                        (finish, min(end, finish + 10), False),
                    ):
                        values = []
                        indexes = list(range(math.floor(lo), math.ceil(hi)))
                        if reverse:
                            indexes.reverse()
                        for k in indexes:
                            if speed[k] is None or speed[k] < 1:
                                break
                            dt = min(hi, k + 1) - max(lo, k)
                            if dt > 0:
                                values.append((speed[k], dt))
                        if values:
                            sides.append(sum(v * dt for v, dt in values) / sum(dt for _, dt in values))
                    if sides:
                        costs = [max(0, duration - max(0, b - a) / pace) for pace in sides]
                        estimate = sum(costs) / len(costs)
                        bounds = [min(costs), max(costs)] if len(sides) == 2 else [
                            max(0, estimate - duration * 0.2), min(duration, estimate + duration * 0.2)]
                        stop["cost"] = {
                            "estimate": True, "basis": "adjacent_pace_replacement",
                            "seconds": estimate,
                            "range_s": bounds,
                        }
                stops.append(stop)
            run_start = None
    return stops


def compute_effort(timeline, *, start_s, end_s, time_s, distance_m, net_gain_m,
                   threshold_w=None, weight_kg=None, average_start_s=None):
    """Left-constant 1 s cells, clipped exactly to [start crossing, finish).

    NP uses the full-ride un-repaired NP series, as the house Training engine
    does. Average, curve and zones use its bounded dropout-repaired series.
    """
    n = len(timeline["power_w"])
    if not (0 <= start_s < end_s <= timeline["duration_s"]) or time_s <= 0:
        raise ValueError("effort outside the retained ride timeline")
    cells = [(i, min(end_s, i + 1) - max(start_s, i))
             for i in range(math.floor(start_s), math.ceil(end_s))]
    duration = end_s - start_s
    moving = [(i, dt) for i, dt in cells if timeline["moving"][i]]
    moving_s = sum(dt for _, dt in moving)
    result = {
        "engine_version": EFFORT_ENGINE_VERSION, "time_s": time_s,
        "moving_s": moving_s, "distance_m": distance_m, "net_gain_m": net_gain_m,
        "avg_speed_mps": distance_m / time_s,
        "vam_m_per_hour": net_gain_m * 3600 / time_s,
        "stops": _stops(timeline, start_s, end_s, distance_m),
    }
    observed = timeline["power_observed_s"]
    # Power must bracket the effort.
    # Interior missing readings/gaps follow the whole-ride cleaner (zero for
    # long gaps); a power meter used elsewhere on the ride is not coverage.
    span_has_power = any(math.floor(start_s) <= t < end_s for t in observed) or any(
        b - a <= 30 and a <= start_s < end_s <= b for a, b in zip(observed, observed[1:])
    )
    measured = bool(observed and observed[0] <= start_s
                    and observed[-1] >= math.ceil(end_s) - 1 and span_has_power
                    and moving_s > 0 and sum(dt for i, dt in moving if timeline["power_covered"][i]) >= 0.95 * moving_s)
    if measured:
        power = timeline["power_w"]
        avg_start = round(start_s) if average_start_s is None else average_start_s
        avg_end = avg_start + time_s
        if not 0 <= avg_start < avg_end <= n:
            raise ValueError("official average window outside retained timeline")
        average = sum(power[avg_start:avg_end]) / time_s
        result.update(avg_power_w=average, power_kind="measured",
                      max_power_w=max(power[i] for i, _ in cells))
        if moving_s:
            np_w = _half_up((sum(timeline["np_30s_w"][i]**4 * dt for i, dt in moving)
                             / moving_s) ** 0.25)
            result["np_w"] = np_w
            if _half_up(average) > 0:
                result["variability_index"] = np_w / _half_up(average)
            if threshold_w is not None and threshold_w > 0:
                intensity = np_w / threshold_w
                result.update(intensity_factor=intensity,
                              load=_half_up(intensity**2 * moving_s / 3600 * 100))
        if threshold_w is not None and threshold_w > 0:
            tops = [math.floor(threshold_w * p / 100) for p in (55, 75, 90, 105, 120, 150)]
            zones = [0.0] * 7
            for i, dt in moving:
                watts = _half_up(timeline["zone_5s_w"][i])
                zones[next((z for z, top in enumerate(tops) if watts <= top), 6)] += dt
            result.update(power_zone_tops_w=tops, power_zone_s=zones)
        if weight_kg is not None and weight_kg > 0:
            result["w_per_kg"] = average / weight_kg
        # Best complete windows fully inside the effort; no approach power.
        prefix = [0.0, *accumulate(power)]
        def joules(t):
            i = math.floor(t)
            return prefix[i] + (t - i) * power[i]

        for seconds in (30, 60):
            if duration >= seconds:
                candidates = [start_s, end_s - seconds, *range(
                    math.ceil(start_s), math.floor(end_s - seconds) + 1)]
                values = [(joules(t + seconds) - joules(t)) / seconds for t in candidates]
                result[f"best_{seconds}s_w"] = max(values)
    else:
        watts, bounds = estimate_power(distance_m, net_gain_m, time_s)
        result.update(estimated_power_w=watts, estimated_power_range_w=bounds, power_kind="estimated",
                      power_estimate_basis="canon_profile_standard_mass_75_plus_8")
    for field, avg_key, max_key in (
        ("cadence_rpm", "avg_cadence_rpm", "max_cadence_rpm"),
        ("hr_bpm", "avg_hr_bpm", "max_hr_bpm"),
    ):
        values = [(timeline[field][i], dt) for i, dt in cells
                  if timeline[field][i] is not None and timeline[field][i] > 0]
        if values:
            result[avg_key] = sum(v * dt for v, dt in values) / sum(dt for _, dt in values)
            result[max_key] = max(v for v, _ in values)
    if measured:
        torques = [(timeline["power_w"][i] / (2 * math.pi * timeline["cadence_rpm"][i] / 60), dt)
                   for i, dt in cells
                   if timeline["cadence_rpm"][i] is not None and timeline["cadence_rpm"][i] >= 20]
        if torques:
            result["avg_torque_nm"] = sum(t * dt for t, dt in torques) / sum(dt for _, dt in torques)
            result["max_torque_nm"] = max(t for t, _ in torques)
    return result


def estimate_power(distance_m, net_gain_m, time_s):
    """Same steady-state function as portal estimatedPower.ts; fixed mass."""
    speed = distance_m / time_s
    angle = math.atan2(net_gain_m, distance_m)
    def watts(cda, crr):
        return max(0, ((75 + 8) * 9.80665 * (math.sin(angle) + crr * math.cos(angle)) * speed
                      + 0.5 * 1.225 * cda * speed**3) / 0.975)
    return watts(0.32, 0.005), [watts(0.28, 0.004), watts(0.36, 0.006)]


def build_effort_rows(activity, patterns, inputs):
    from .canon_traversal import authoritative_canon_climb_id

    canonical = [p for p in patterns if authoritative_canon_climb_id(p)]
    if not canonical:
        return []
    timeline = effort_timeline(activity)
    rows = []
    for pattern in canonical:
        start, end = canonical_span(pattern)
        trace = pattern["match_trace"]
        profile = trace["canonical_metrics"]
        # This retained denominator is owner-only input, never emitted/stored
        # as mass and never used for the fixed-mass physics estimate.
        old_power, old_wkg = _number(pattern.get("avg_power_w")), _number(pattern.get("w_per_kg"))
        weight = old_power / old_wkg if old_power and old_wkg and old_power > 0 and old_wkg > 0 else None
        metrics = compute_effort(
            timeline, start_s=start, end_s=end, time_s=pattern["time_s"],
            distance_m=profile["distance_m"], net_gain_m=profile["vert_m"],
            threshold_w=(inputs.get("threshold") or {}).get("value"), weight_kg=weight,
            average_start_s=pattern.get("start_offset_s", round(start)),
        )
        if inputs.get("threshold") and metrics["power_kind"] == "measured":
            metrics["threshold"] = inputs["threshold"]
        started = datetime.fromisoformat(str(inputs["started_at"]).replace("Z", "+00:00"))
        rows.append({
            "id": str(pattern["id"]), "climb_id": authoritative_canon_climb_id(pattern),
            "canon_version": trace["canon_version"],
            "start_offset_s": start, "end_offset_s": end,
            "achieved_at": (started + timedelta(seconds=end)).isoformat(),
            "metrics": metrics,
        })
    return rows
