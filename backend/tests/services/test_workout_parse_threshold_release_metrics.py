from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import workout_parse_adapter


def test_release_tss_delegates_to_the_authoritative_rust_scalar(monkeypatch) -> None:
    calls: list[tuple[int, float, int]] = []

    def calculate_tss_from_power(duration_s: int, normalized_power_w: float, ftp_w: int):
        calls.append((duration_s, normalized_power_w, ftp_w))
        return 64.000003

    monkeypatch.setattr(
        workout_parse_adapter,
        "_get_workout_parse",
        lambda: SimpleNamespace(calculate_tss_from_power=calculate_tss_from_power),
    )

    assert workout_parse_adapter.calculate_threshold_release_tss(
        normalized_power_raw_w=200.0,
        normalized_power_duration_s=3600,
        threshold_w=250,
    ) == 64.0
    assert calls == [(3600, 200.0, 250)]


@pytest.mark.parametrize(
    ("duration_s", "normalized_power_w", "threshold_w"),
    ((0, 200.0, 250), (3600, 0.0, 250), (3600, 200.0, 0)),
)
def test_release_tss_rejects_nonpositive_frozen_inputs(
    duration_s: int,
    normalized_power_w: float,
    threshold_w: int,
) -> None:
    with pytest.raises(ValueError):
        workout_parse_adapter.calculate_threshold_release_tss(
            normalized_power_raw_w=normalized_power_w,
            normalized_power_duration_s=duration_s,
            threshold_w=threshold_w,
        )
