from __future__ import annotations

import importlib.util
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest


HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


corridor = _load("generate_canon_corridor_equivalence", "generate_canon_corridor_equivalence.py")
cross_rider = _load("generate_canon_cross_rider_evidence", "generate_canon_cross_rider_evidence.py")


class FakeConnection:
    def __init__(self) -> None:
        self.calls = []

    def set_session(self, **kwargs) -> None:
        self.calls.append(kwargs)


@pytest.mark.parametrize("module", [corridor, cross_rider])
def test_database_sessions_are_explicitly_read_only(module) -> None:
    connection = FakeConnection()
    module.set_read_only(connection)
    assert connection.calls == [{"readonly": True, "autocommit": False}]


def test_launch_snapshot_uses_actual_compiler_report_schema() -> None:
    selected = [
        {"candidate_fingerprint": f"{index:064x}"} for index in range(57)
    ]
    report = {
        "compiler_version": "canon-compile-v0.2.4",
        "ratified_boundaries": {
            "mode": "applied",
            "model": "canon_ratified_boundaries_v1",
            "applied_decisions": 15,
            "retained_decisions": 15,
        },
    }
    corridor.validate_launch_snapshot(
        report,
        selected,
        {"resolved_candidates": 57},
        expected_candidates=57,
        expected_boundaries=15,
    )

    with pytest.raises(corridor.EvidenceError, match="boundary registry drifted"):
        corridor.validate_launch_snapshot(
            {"boundary_ratification": {"applied_decisions": 15}},
            selected,
            {"resolved_candidates": 57},
            expected_candidates=57,
            expected_boundaries=15,
        )


def test_authoritative_manifest_hashes_raw_ewkb_not_hex_text() -> None:
    rows = [
        {"fingerprint": "b" * 64, "ewkb": b"\x01\x02"},
        {"fingerprint": "a" * 64, "ewkb": b"\x00\xff"},
    ]
    expected = corridor.digest_sorted_lines(
        [
            b"b" * 64 + b"\0\x01\x02",
            b"a" * 64 + b"\0\x00\xff",
        ]
    )
    assert corridor.authoritative_wkb_manifest(rows) == expected
    assert corridor.authoritative_wkb_manifest(list(reversed(rows))) == expected


@pytest.mark.parametrize("module", [corridor, cross_rider])
@pytest.mark.parametrize("key", ["ride_id", "activity_id", "user_id", "raw_file_path", "rider_hash"])
def test_privacy_scan_rejects_identifiers_and_paths(module, key: str) -> None:
    with pytest.raises(module.EvidenceError, match="privacy-sensitive"):
        module.assert_privacy_bounded({"outer": {key: "secret"}})


@pytest.mark.parametrize("module", [corridor, cross_rider])
def test_privacy_scan_rejects_storage_path_values(module) -> None:
    with pytest.raises(module.EvidenceError, match="privacy-sensitive path"):
        module.assert_privacy_bounded({"innocent_key": "rides/private/object.fit"})


def test_database_identity_is_read_from_the_authoritative_connection() -> None:
    class Cursor:
        query = None

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query):
            self.query = query

        def fetchone(self):
            assert "server_version" in self.query
            assert "PostGIS_Full_Version" in self.query
            return ("17.5", "POSTGIS=3.5.2")

    class Connection:
        def cursor(self):
            return Cursor()

    assert corridor.fetch_postgis_identity(Connection()) == {
        "postgresql_server_version": "17.5",
        "postgis_full_version": "POSTGIS=3.5.2",
    }


@pytest.mark.parametrize("module", [corridor, cross_rider])
def test_generated_at_is_explicit_and_canonical(module) -> None:
    assert module.validate_generated_at("2026-07-21T20:00:00Z") == "2026-07-21T20:00:00Z"
    with pytest.raises(module.EvidenceError):
        module.validate_generated_at("2026-07-21T16:00:00-04:00")
    with pytest.raises(module.EvidenceError):
        module.validate_generated_at("")


def test_dogfood_selection_is_source_only_and_excludes_later_upload() -> None:
    cutoff = cross_rider.DOGFOOD_CUTOFF
    assert cross_rider.is_dogfood_source("TCX", cutoff)
    assert not cross_rider.is_dogfood_source("tcx", cutoff + timedelta(microseconds=1))
    assert not cross_rider.is_dogfood_source("gpx", cutoff)
    with pytest.raises(cross_rider.EvidenceError, match="timezone-aware"):
        cross_rider.is_dogfood_source("tcx", cutoff.replace(tzinfo=None))


def _attempt(source: str, rider: str, digest_char: str, *, accepted: bool):
    return cross_rider.AttemptEvidence(
        source_key=source,
        rider_key=rider,
        raw_sha256=digest_char * 64,
        decision_id="canon-decision",
        start_s=10.0,
        finish_s=20.0,
        accepted=accepted,
        rejection="" if accepted else "partial_traversal",
    )


def test_pairs_exclude_same_rider_and_byte_identical_sources_before_scoring() -> None:
    attempts = [
        _attempt("ride-1", "rider-a", "a", accepted=True),
        _attempt("ride-2", "rider-a", "b", accepted=True),
        _attempt("ride-3", "rider-b", "a", accepted=True),
        _attempt("ride-4", "rider-b", "c", accepted=False),
    ]
    metric, eligibility_manifest, outcome_manifest = cross_rider.build_pair_metrics(attempts)
    assert metric == {
        "agreements": 1,
        "exact_duplicate_cross_rider_pairs_excluded": 1,
        "pairs": 3,
        "raw_cross_rider_pairs": 4,
        "same_rider_pairs_excluded": 2,
        "supported_candidate_decision_ids": ["canon-decision"],
        "supported_candidates": 1,
        "value": 1 / 3,
    }
    reversed_result = cross_rider.build_pair_metrics(list(reversed(attempts)))
    assert reversed_result[1] == eligibility_manifest
    assert reversed_result[2] == outcome_manifest

    flipped_outcome = [
        cross_rider.AttemptEvidence(
            **{
                **attempt.__dict__,
                "accepted": not attempt.accepted,
                "rejection": "" if not attempt.accepted else "partial_traversal",
            }
        )
        for attempt in attempts
    ]
    flipped_metric, flipped_eligibility, flipped_outcomes = (
        cross_rider.build_pair_metrics(flipped_outcome)
    )
    assert flipped_metric["pairs"] == metric["pairs"]
    assert flipped_eligibility == eligibility_manifest
    assert flipped_outcomes != outcome_manifest


def test_eligible_attempt_manifest_is_outcome_independent() -> None:
    attempts = [
        _attempt("ride-1", "rider-a", "a", accepted=True),
        _attempt("ride-2", "rider-b", "b", accepted=False),
    ]
    eligibility_manifest, outcome_manifest = cross_rider.build_attempt_manifests(attempts)

    flipped = [
        cross_rider.AttemptEvidence(
            **{
                **attempt.__dict__,
                "accepted": not attempt.accepted,
                "rejection": "" if not attempt.accepted else "partial_traversal",
            }
        )
        for attempt in attempts
    ]
    flipped_eligibility, flipped_outcomes = cross_rider.build_attempt_manifests(flipped)

    assert flipped_eligibility == eligibility_manifest
    assert flipped_outcomes != outcome_manifest


def test_gate_eligible_attempt_outside_narrower_corridor_is_not_prefiltered() -> None:
    backend = HERE.parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.models.canon import CanonClimb
    from shapely.geometry import LineString, MultiPolygon, Polygon

    corridor_shape = MultiPolygon(
        [
            Polygon(
                [
                    (-75.00005, 39.9999),
                    (-74.99995, 39.9999),
                    (-74.99995, 40.0011),
                    (-75.00005, 40.0011),
                    (-75.00005, 39.9999),
                ]
            )
        ]
    )
    runtime = CanonClimb(
        registry_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        canon_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        version=1,
        display_name="Widened gate test",
        route_name="Widened gate test",
        centerline=LineString([(-75.0, 40.0), (-75.0, 40.001)]),
        corridor=corridor_shape,
        gate_start=LineString([(-75.0003, 40.0001), (-74.9997, 40.0001)]),
        gate_end=LineString([(-75.0003, 40.0009), (-74.9997, 40.0009)]),
        canonical_profile=(
            {"dist_m": 0.0, "elev_m": 10.0},
            {"dist_m": 100.0, "elev_m": 30.0},
        ),
        length_m=100.0,
        vert_m=20.0,
        avg_gradient_pct=20.0,
        compiler_version="test",
        profile_hash_algorithm="test",
        profile_hash="ab" * 32,
        odbl_source="OpenStreetMap contributors",
        corridor_tile_ids=(),
    )
    candidate = SimpleNamespace(
        decision_id="widened-gate-decision",
        fingerprint="f" * 64,
        runtime=runtime,
        exact_corridor=corridor_shape,
    )
    source = cross_rider.SourceObject(
        ordinal=1,
        source_key="source-1",
        rider_key="rider-1",
        storage_path="private-object",
        file_type="gpx",
        uploaded_at=cross_rider.DOGFOOD_CUTOFF,
        raw_sha256="a" * 64,
        byte_count=123,
    )
    samples = [
        {"t": index * 5.0, "lat": 40.0 + index * 0.0002, "lon": -75.0002}
        for index in range(6)
    ]

    evidence = cross_rider._replay_ride(source, samples, [candidate])

    assert evidence.corridor_fingerprints == set()
    assert len(evidence.attempts) == 1
    assert evidence.attempts[0].accepted is False


def test_object_manifests_preserve_duplicates_and_final_newline() -> None:
    line = f"{'a' * 64}\ttcx\t123"
    assert cross_rider.digest_text_lines([line, line]) != cross_rider.digest_text_lines(
        [line], unique=True
    )


def test_evaluation_signature_orders_partial_and_complete_attempts() -> None:
    complete = SimpleNamespace(
        canon_id="canon-a",
        start=SimpleNamespace(time_s=10.0),
        finish=SimpleNamespace(time_s=20.0),
        accepted=True,
        rejection_code=None,
    )
    partial = SimpleNamespace(
        canon_id="canon-a",
        start=SimpleNamespace(time_s=10.0),
        finish=None,
        accepted=False,
        rejection_code="partial_traversal",
    )
    evaluation = SimpleNamespace(
        climb_patterns=[],
        attempts=[complete, partial],
        rejections={"partial_traversal": 1},
    )

    signature = corridor._evaluation_signature(evaluation)

    assert len(signature[1]) == 2
    reversed_evaluation = SimpleNamespace(
        climb_patterns=[],
        attempts=[partial, complete],
        rejections={"partial_traversal": 1},
    )
    assert corridor._evaluation_signature(reversed_evaluation) == signature
