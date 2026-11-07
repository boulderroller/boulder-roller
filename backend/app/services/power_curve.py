"""Rider power curve: mean-maximal power over a duration ladder.

Reading surface (two-layer truth): best honest arithmetic across the rider's
completed rides, never an economic input. The per-ride arithmetic is the
workout-parse mean-max routine — the same one that produces the Threshold
anchors — so the 3/7/15-minute points on the curve are, by construction,
the values the Threshold authority read.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Iterable, Optional

# Standard mean-max ladder; 180/420/900 are the Threshold anchors and must
# stay present so the overlay sits on the curve exactly.
DURATION_LADDER_S: tuple[int, ...] = (
    1, 5, 15, 30, 60, 120, 180, 300, 420, 600, 900, 1200, 1800, 2700, 3600,
)
THRESHOLD_ANCHORS_S: tuple[int, ...] = (180, 420, 900)

MeanMax = Callable[[list[int], list[int], list[int]], list[Optional[float]]]


def default_mean_max() -> MeanMax:
    """The workout-parse binding, imported lazily like the adapter does."""
    import workout_parse as wp  # type: ignore

    return wp.compute_mean_max_power_series


def power_stream_to_arrays(stream: dict[str, Any]) -> tuple[list[int], list[int]]:
    """activity_streams row (ISO timestamps + float watts) -> ms + u16 watts."""
    timestamps = stream.get("timestamps") or []
    values = stream.get("values") or []
    time_ms: list[int] = []
    power_w: list[int] = []
    for raw_ts, raw_value in zip(timestamps, values):
        if raw_value is None:
            continue
        ts = raw_ts if isinstance(raw_ts, datetime) else datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        watts = int(round(float(raw_value)))
        if watts < 0:
            continue
        time_ms.append(int(ts.timestamp() * 1000))
        power_w.append(min(watts, 65535))
    return time_ms, power_w


def aggregate_rider_power_curve(
    streams: Iterable[dict[str, Any]],
    *,
    mean_max: MeanMax,
    durations_s: tuple[int, ...] = DURATION_LADDER_S,
) -> dict[str, Any]:
    """Elementwise maximum of per-ride mean-max across the rider's rides."""
    ladder = list(durations_s)
    best: list[Optional[float]] = [None] * len(ladder)
    sampled = 0
    for stream in streams:
        time_ms, power_w = power_stream_to_arrays(stream)
        if len(time_ms) < 2:
            continue
        values = mean_max(time_ms, power_w, ladder)
        sampled += 1
        for index, value in enumerate(values):
            if value is None:
                continue
            current = best[index]
            best[index] = value if current is None or value > current else current
    available = any(value is not None for value in best)
    return {
        "durationsS": ladder,
        "bestW": [None if v is None else round(v, 1) for v in best],
        "sampledRides": sampled,
        "available": available,
    }
