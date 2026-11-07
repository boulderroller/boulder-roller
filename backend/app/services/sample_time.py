"""Utilities for normalizing ride sample timestamps to seconds."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional


def parse_sample_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def datetime_delta_seconds(value: datetime, base_time: datetime) -> float:
    if value.tzinfo is None and base_time.tzinfo is not None:
        value = value.replace(tzinfo=base_time.tzinfo)
    elif value.tzinfo is not None and base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=value.tzinfo)
    return (value - base_time).total_seconds()


def infer_sample_time_base(samples: Iterable[Mapping[str, Any]], key: str = "t") -> Optional[datetime]:
    for sample in samples:
        parsed = parse_sample_datetime(sample.get(key))
        if parsed is not None:
            return parsed
    return None


def sample_time_seconds(value: Any, *, base_time: Any = None) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, timedelta):
        return value.total_seconds()

    parsed_value = parse_sample_datetime(value)
    if parsed_value is None:
        return None

    parsed_base = parse_sample_datetime(base_time)
    if parsed_base is not None:
        return datetime_delta_seconds(parsed_value, parsed_base)
    return parsed_value.timestamp()


def sample_in_time_window(
    sample: Mapping[str, Any],
    start_time: Any,
    end_time: Any,
    *,
    base_time: Any = None,
    key: str = "t",
) -> bool:
    sample_seconds = sample_time_seconds(sample.get(key), base_time=base_time)
    start_seconds = sample_time_seconds(start_time, base_time=base_time)
    end_seconds = sample_time_seconds(end_time, base_time=base_time)
    if sample_seconds is None or start_seconds is None or end_seconds is None:
        return False

    lo = min(start_seconds, end_seconds)
    hi = max(start_seconds, end_seconds)
    return lo <= sample_seconds <= hi


def normalize_sample_times_to_seconds(
    samples: Iterable[Mapping[str, Any]],
    *,
    key: str = "t",
    base_time: Any = None,
    drop_untimed: bool = True,
    sort: bool = False,
) -> list[dict[str, Any]]:
    """Return sample copies with timestamp values normalized to numeric seconds."""
    materialized = list(samples)
    resolved_base = parse_sample_datetime(base_time) or infer_sample_time_base(
        materialized,
        key=key,
    )
    normalized: list[dict[str, Any]] = []
    for sample in materialized:
        seconds = sample_time_seconds(sample.get(key), base_time=resolved_base)
        if seconds is None:
            if drop_untimed:
                continue
            normalized.append(dict(sample))
            continue
        next_sample = dict(sample)
        next_sample[key] = seconds
        normalized.append(next_sample)

    if sort:
        normalized.sort(key=lambda sample: sample_time_seconds(sample.get(key)) or 0.0)
    return normalized
