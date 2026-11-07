from types import SimpleNamespace

from tests.validation import render_climb_review


def test_compute_canonical_result_uses_canonical_v2_with_persistence_samples(monkeypatch):
    calls = []

    def fake_detect(samples, **kwargs):
        calls.append({"samples": samples, "kwargs": kwargs})
        return [
            SimpleNamespace(
                start_time_offset_s=10,
                end_time_offset_s=70,
                vert_m=42.0,
                time_s=60,
                distance_m=700.0,
                avg_gradient_pct=6.0,
                signature_hex="abc123",
                detector_mode="canonical_v2:momentum:urban_hills",
            )
        ]

    monkeypatch.setattr(render_climb_review, "detect_climbs_with_rust", fake_detect)

    result = render_climb_review.compute_canonical_result(
        samples=[{"t": 10}],
        persistence_candidate_samples=[{"t": 9}],
        weight_kg=75.0,
        min_vert_m=20.0,
    )

    assert calls == [
        {
            "samples": [{"t": 10}],
            "kwargs": {
                "user_weight_kg": 75.0,
                "algorithm": "canonical_v2",
                "persistence_candidate_samples": [{"t": 9}],
                "generate_signatures": True,
            },
        }
    ]
    assert result["label"] == "canonical_v2 (urban_hills)"
    assert result["shown"][0]["signature_hex"] == "abc123"
