from __future__ import annotations

import run_holdout_eval


def test_run_detector_defaults_persistence_to_bridge_processed_samples(monkeypatch) -> None:
    calls = {}

    def fake_bridge_preprocessing(samples):
        samples[0]["elevation_m"] = 123.0
        return samples

    def fake_detect_climbs(tile_samples, **kwargs):
        calls["tile_samples"] = tile_samples
        calls["persistence_candidate_samples"] = kwargs["persistence_candidate_samples"]
        return []

    monkeypatch.setattr(
        run_holdout_eval,
        "_apply_bridge_preprocessing",
        fake_bridge_preprocessing,
    )
    monkeypatch.setattr(
        run_holdout_eval,
        "detect_climbs_with_rust",
        fake_detect_climbs,
    )

    samples = [
        {"t": 0, "elevation_m": 10.0},
        {"t": 1, "elevation_m": 12.0},
    ]

    detections = run_holdout_eval.run_detector(
        samples,
        use_bridge_preprocessing=True,
    )

    assert detections == []
    assert calls["tile_samples"][0]["elevation_m"] == 123.0
    assert calls["persistence_candidate_samples"][0]["elevation_m"] == 123.0
    assert calls["persistence_candidate_samples"] is calls["tile_samples"]


def test_run_detector_can_preserve_pre_bridge_samples_for_persistence(monkeypatch) -> None:
    calls = {}

    def fake_bridge_preprocessing(samples):
        samples[0]["elevation_m"] = 123.0
        return samples

    def fake_detect_climbs(tile_samples, **kwargs):
        calls["tile_samples"] = tile_samples
        calls["persistence_candidate_samples"] = kwargs["persistence_candidate_samples"]
        return []

    monkeypatch.setattr(
        run_holdout_eval,
        "_apply_bridge_preprocessing",
        fake_bridge_preprocessing,
    )
    monkeypatch.setattr(
        run_holdout_eval,
        "detect_climbs_with_rust",
        fake_detect_climbs,
    )

    samples = [
        {"t": 0, "elevation_m": 10.0},
        {"t": 1, "elevation_m": 12.0},
    ]

    detections = run_holdout_eval.run_detector(
        samples,
        use_bridge_preprocessing=True,
        preserve_pre_bridge_persistence=True,
    )

    assert detections == []
    assert calls["tile_samples"][0]["elevation_m"] == 123.0
    assert calls["persistence_candidate_samples"][0]["elevation_m"] == 10.0
    assert calls["persistence_candidate_samples"] is not calls["tile_samples"]
