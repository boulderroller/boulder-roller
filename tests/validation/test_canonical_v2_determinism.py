from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from compare_candidate_generators import (
    DEFAULT_WEIGHT_KG,
    MANIFEST_PATH,
    display_climbs,
    parse_fit_to_sample_views,
)
from app.services.patterns.climb import detect_climbs_with_rust


def _serialize_climb_facts(climbs) -> list[dict]:
    return [
        {
            "start_time_offset_s": climb.start_time_offset_s,
            "end_time_offset_s": climb.end_time_offset_s,
            "vert_m": round(float(climb.vert_m), 6),
            "time_s": climb.time_s,
            "avg_gradient_pct": round(float(climb.avg_gradient_pct or 0.0), 6),
            "distance_m": round(float(climb.distance_m or 0.0), 6),
            "detector_mode": climb.detector_mode,
            "proposal_sources": list(climb.proposal_sources or []),
            "confidence": round(float(climb.confidence or 0.0), 6),
            "confidence_reasons": list(climb.confidence_reasons or []),
        }
        for climb in display_climbs(climbs)
    ]


def _detect_canonical_v2_facts(fit_file: str) -> list[dict]:
    raw_tile_samples, tile_runs = parse_fit_to_sample_views(Path(MANIFEST_PATH.parent / fit_file))
    climbs = detect_climbs_with_rust(
        deepcopy(tile_runs),
        persistence_candidate_samples=deepcopy(raw_tile_samples),
        algorithm="canonical_v2",
        user_weight_kg=DEFAULT_WEIGHT_KG,
    )
    return _serialize_climb_facts(climbs)


@pytest.mark.parametrize("fit_file", ["t_h_e_w_a_l_l.fit", "in_the_bag_.fit"])
def test_canonical_v2_is_deterministic_for_duplicate_uploads(fit_file: str) -> None:
    """Duplicate uploads of the same workout must produce the same climb facts.

    Duplicate detection can reject the second upload economically, but the
    evidence replay itself must remain byte-for-byte stable at the climb-fact
    layer so protocol proofs and user-facing summaries do not drift.
    """
    first_pass = _detect_canonical_v2_facts(fit_file)
    second_pass = _detect_canonical_v2_facts(fit_file)

    assert first_pass == second_pass
