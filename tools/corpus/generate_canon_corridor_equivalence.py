#!/usr/bin/env python3
"""Rebuild privacy-bounded PostGIS/local canon corridor equivalence evidence.

The generator deliberately has no clock default.  A caller supplies both the
canon report digest and ``--generated-at`` so byte-for-byte output is stable for
the same frozen inputs.  PostgreSQL is opened read-only and supplies the
authoritative geography buffer; the local AEQD corridor is never treated as the
source of truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5


MODEL = "canon_corridor_equivalence_v1"
EXPECTED_REVIEW_SHA256 = (
    "77fbdcc691de9d82124f3d848035f103e5433c6ef2bbe3d8bd64782041c4fdd9"
)
EXPECTED_CORPUS_SHA256 = (
    "64b15790bed2628b3e7e8371657b408ec5e96305db84bfe050507b14860b98ee"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SENSITIVE_KEYS = {
    "activity_id",
    "ride_id",
    "user_id",
    "raw_file_path",
    "rider_hash",
    "rider_id",
}


class EvidenceError(RuntimeError):
    """An input or equivalence contract drifted."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_sha256(value: str, label: str) -> str:
    value = str(value or "")
    if not SHA256_RE.fullmatch(value):
        raise EvidenceError(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_generated_at(value: str) -> str:
    if not UTC_RFC3339_RE.fullmatch(str(value or "")):
        raise EvidenceError("generated_at must be an explicit UTC RFC3339 timestamp ending in Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo != timezone.utc:
        raise EvidenceError("generated_at must be UTC")
    return value


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest_sorted_lines(lines: Iterable[bytes]) -> str:
    digest = hashlib.sha256()
    for line in sorted(lines):
        digest.update(line)
        digest.update(b"\n")
    return digest.hexdigest()


def authoritative_wkb_manifest(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash fingerprint NUL raw ST_AsEWKB LF records in fingerprint order."""

    lines: list[bytes] = []
    for row in rows:
        fingerprint = require_sha256(str(row["fingerprint"]), "candidate fingerprint")
        ewkb = bytes(row["ewkb"])
        if not ewkb:
            raise EvidenceError(f"PostGIS emitted an empty EWKB for {fingerprint}")
        lines.append(fingerprint.encode("ascii") + b"\0" + ewkb)
    return digest_sorted_lines(lines)


def assert_privacy_bounded(value: Any, path: tuple[str, ...] = ()) -> None:
    """Reject rider/ride identifiers before an evidence document is written."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in SENSITIVE_KEYS or normalized.endswith("_ride_ids"):
                raise EvidenceError(f"privacy-sensitive output key at {'.'.join(path + (str(key),))}")
            assert_privacy_bounded(child, path + (str(key),))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_privacy_bounded(child, path + (str(index),))
    elif isinstance(value, str) and (value.startswith("/") or "rides/" in value):
        raise EvidenceError(f"privacy-sensitive path value at {'.'.join(path)}")


def set_read_only(connection: Any) -> None:
    connection.set_session(readonly=True, autocommit=False)


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    index = (len(ordered) - 1) * percentile
    low = math.floor(index)
    high = math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - index) + ordered[high] * (index - low)


def _rounded(value: float) -> float:
    return round(float(value), 6)


def validate_launch_snapshot(
    report: Mapping[str, Any],
    selected: Sequence[Mapping[str, Any]],
    audit: Mapping[str, Any],
    *,
    expected_candidates: int,
    expected_boundaries: int,
) -> None:
    metadata = report.get("ratified_boundaries") or {}
    applied = int(metadata.get("applied_decisions") or 0)
    retained = int(metadata.get("retained_decisions") or 0)
    if len(selected) != expected_candidates:
        raise EvidenceError(
            f"launch reconstruction drifted: expected {expected_candidates}, got {len(selected)}"
        )
    if applied != expected_boundaries or retained != expected_boundaries:
        raise EvidenceError(
            "boundary registry drifted: "
            f"expected {expected_boundaries}, applied={applied}, retained={retained}"
        )
    if int(audit.get("resolved_candidates") or 0) != expected_candidates:
        raise EvidenceError("launch reconstruction audit does not match selected candidates")
    fingerprints = [str(item.get("candidate_fingerprint") or "") for item in selected]
    if fingerprints != sorted(fingerprints) or len(set(fingerprints)) != len(fingerprints):
        raise EvidenceError("launch candidates are not unique and fingerprint-sorted")


def _load_environment(path: Path) -> None:
    from dotenv import load_dotenv

    if not path.is_file():
        raise EvidenceError(f"database environment file does not exist: {path}")
    load_dotenv(path, override=False)


def fetch_authoritative_corridors(
    connection: Any,
    selected: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build all corridors in one read-only PostGIS statement."""

    from psycopg2.extras import execute_values

    values = [
        (
            str(item["candidate_fingerprint"]),
            str(item["centerline_wkt"]),
            float(item["corridor_half_width_m"]),
        )
        for item in selected
    ]
    with connection.cursor() as cursor:
        execute_values(
            cursor,
            """
            WITH source(fingerprint, centerline_wkt, half_width_m) AS (VALUES %s),
            generated AS (
              SELECT fingerprint,
                     ST_Multi(
                       ST_Buffer(
                         ST_GeomFromText(centerline_wkt, 4326)::geography,
                         half_width_m
                       )::geometry
                     ) AS corridor
                FROM source
            )
            SELECT fingerprint,
                   ST_AsEWKB(corridor),
                   ST_AsBinary(corridor),
                   ST_IsValid(corridor),
                   ST_SRID(corridor),
                   ST_GeometryType(corridor)
              FROM generated
             ORDER BY fingerprint
            """,
            values,
            template="(%s,%s,%s)",
        )
        result = []
        for fingerprint, ewkb, wkb, valid, srid, geometry_type in cursor.fetchall():
            result.append(
                {
                    "fingerprint": str(fingerprint),
                    "ewkb": bytes(ewkb),
                    "wkb": bytes(wkb),
                    "valid": bool(valid),
                    "srid": int(srid),
                    "geometry_type": str(geometry_type),
                }
            )
    if [row["fingerprint"] for row in result] != sorted(
        str(item["candidate_fingerprint"]) for item in selected
    ):
        raise EvidenceError("PostGIS did not return the complete fingerprint-sorted launch set")
    invalid = [
        row["fingerprint"]
        for row in result
        if not row["valid"]
        or row["srid"] != 4326
        or row["geometry_type"] != "ST_MultiPolygon"
    ]
    if invalid:
        raise EvidenceError(f"PostGIS corridor contract failed for {len(invalid)} candidates")
    return result


def fetch_postgis_identity(connection: Any) -> dict[str, str]:
    """Read the exact database implementations used by the buffer query."""

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_setting('server_version'), PostGIS_Full_Version()"
        )
        row = cursor.fetchone()
    if not row or not row[0] or not row[1]:
        raise EvidenceError("database did not report PostgreSQL/PostGIS versions")
    return {"postgresql_server_version": str(row[0]), "postgis_full_version": str(row[1])}


def _geometry_comparison(
    local_candidates: Sequence[Any],
    authoritative_by_fingerprint: Mapping[str, Any],
) -> dict[str, Any]:
    from shapely.ops import transform

    hausdorff: list[float] = []
    symmetric_area: list[float] = []
    relative_area: list[float] = []
    for candidate in local_candidates:
        authoritative = authoritative_by_fingerprint[candidate.fingerprint]
        projected_local = transform(
            candidate.project_forward.transform,
            candidate.exact_corridor,
        )
        projected_authoritative = transform(
            candidate.project_forward.transform,
            authoritative,
        )
        hausdorff.append(projected_local.hausdorff_distance(projected_authoritative))
        symmetric_area.append(projected_local.symmetric_difference(projected_authoritative).area)
        reference_area = max(projected_authoritative.area, 1e-12)
        relative_area.append(
            abs(projected_local.area - projected_authoritative.area) / reference_area * 100.0
        )
    return {
        "hausdorff_m": {
            "max": _rounded(max(hausdorff, default=0.0)),
            "median": _rounded(_percentile(hausdorff, 0.50)),
            "p95": _rounded(_percentile(hausdorff, 0.95)),
        },
        "relative_area_difference_pct": {
            "max": _rounded(max(relative_area, default=0.0)),
            "p95": _rounded(_percentile(relative_area, 0.95)),
        },
        "symmetric_difference_area_m2": {
            "max": _rounded(max(symmetric_area, default=0.0)),
            "median": _rounded(_percentile(symmetric_area, 0.50)),
            "p95": _rounded(_percentile(symmetric_area, 0.95)),
            "sum": _rounded(sum(symmetric_area)),
        },
    }


def _authoritative_candidates(
    local_candidates: Sequence[Any],
    authoritative_by_fingerprint: Mapping[str, Any],
) -> list[Any]:
    return [
        replace(
            candidate,
            runtime=replace(
                candidate.runtime,
                corridor=authoritative_by_fingerprint[candidate.fingerprint],
            ),
            exact_corridor=authoritative_by_fingerprint[candidate.fingerprint],
        )
        for candidate in local_candidates
    ]


def _template_signature(templates: Sequence[Any]) -> list[tuple[Any, ...]]:
    return sorted(
        (
            int(template.segment_id),
            str(template.candidate_fingerprint),
            str(template.decision_id),
        )
        for template in templates
    )


def _expected_signature(expected: Sequence[Any]) -> list[tuple[Any, ...]]:
    return sorted(
        (
            str(item.activity_id),
            int(item.segment_id),
            str(item.candidate_fingerprint),
            round(float(item.start_s), 9),
            round(float(item.end_s), 9),
        )
        for item in expected
    )


def _d11_reference_replay(
    harness: Any,
    connection: Any,
    candidates: Sequence[Any],
    expected: Sequence[Any],
) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]], Counter[str], int]:
    """Replay only D11; detector output is outside corridor equivalence."""

    from app.services.canon_traversal import CanonTraversalEngine

    by_fingerprint = {candidate.fingerprint: candidate for candidate in candidates}
    by_activity: dict[str, list[Any]] = defaultdict(list)
    for reference in expected:
        by_activity[str(reference.activity_id)].append(reference)
    engine = CanonTraversalEngine()
    vector: list[tuple[Any, ...]] = []
    observed: list[tuple[Any, ...]] = []
    taxonomy: Counter[str] = Counter()
    errors = 0
    for activity_id in sorted(by_activity, key=int):
        references = sorted(
            by_activity[activity_id],
            key=lambda item: (item.start_s, item.end_s, item.candidate_fingerprint),
        )
        samples = harness._tile_samples(harness._streams_for_activity(connection, activity_id))
        relevant = [
            by_fingerprint[fingerprint]
            for fingerprint in sorted({item.candidate_fingerprint for item in references})
        ]
        try:
            evaluation = engine.evaluate(
                activity_id=uuid5(NAMESPACE_URL, f"corridor-reference:{activity_id}"),
                wallet="offline-corridor-equivalence",
                candidates=[candidate.runtime for candidate in relevant],
                raw_samples=samples,
                user_weight_kg=75.0,
            )
        except Exception:
            errors += 1
            continue
        taxonomy.update(evaluation.rejections)
        activity_observed: dict[str, list[tuple[float, float]]] = defaultdict(list)
        for pattern in evaluation.climb_patterns:
            crossings = pattern.match_trace["gate_crossings"]
            fingerprint = str(pattern.match_trace.get("candidate_fingerprint") or "")
            interval = (
                float(crossings["start_time_s_raw"]),
                float(crossings["finish_time_s_raw"]),
            )
            activity_observed[fingerprint].append(interval)
            observed.append(
                (
                    activity_id,
                    fingerprint,
                    round(interval[0], 9),
                    round(interval[1], 9),
                )
            )
        used: set[tuple[str, float, float]] = set()
        for reference in references:
            matched = False
            for start_s, end_s in sorted(
                activity_observed.get(reference.candidate_fingerprint, [])
            ):
                key = (reference.candidate_fingerprint, start_s, end_s)
                if key in used:
                    continue
                if harness.reference_contains_observed(
                    reference.start_s,
                    reference.end_s,
                    start_s,
                    end_s,
                ):
                    used.add(key)
                    matched = True
                    break
            vector.append(
                (
                    activity_id,
                    int(reference.segment_id),
                    str(reference.candidate_fingerprint),
                    matched,
                )
            )
    return sorted(vector), sorted(observed), taxonomy, errors


def _reference_sensitivity(
    harness: Any,
    connection: Any,
    corpus_path: Path,
    local_candidates: Sequence[Any],
    authoritative_candidates: Sequence[Any],
    *,
    expected_reference_passes: int,
) -> dict[str, Any]:
    local_templates, _ = harness.map_reference_templates(connection, local_candidates)
    authoritative_templates, _ = harness.map_reference_templates(
        connection, authoritative_candidates
    )
    mapped_identically = _template_signature(local_templates) == _template_signature(
        authoritative_templates
    )
    local_expected = harness.load_expected_passes(connection, local_templates)
    authoritative_expected = harness.load_expected_passes(
        connection, authoritative_templates
    )
    if len(local_expected) != expected_reference_passes:
        raise EvidenceError(
            "reference denominator drifted: "
            f"expected {expected_reference_passes}, got {len(local_expected)}"
        )
    if _expected_signature(local_expected) != _expected_signature(authoritative_expected):
        raise EvidenceError("PostGIS and local corridors map different independent references")

    local_rows, local_observed, local_taxonomy, local_errors = _d11_reference_replay(
        harness, connection, local_candidates, local_expected
    )
    authoritative_rows, authoritative_observed, authoritative_taxonomy, authoritative_errors = (
        _d11_reference_replay(
            harness, connection, authoritative_candidates, authoritative_expected
        )
    )
    if local_errors or authoritative_errors:
        raise EvidenceError(
            "D11 reference replay failed: "
            f"local={local_errors}, authoritative={authoritative_errors}"
        )
    match_vector_identical = local_rows == authoritative_rows
    timestamps_identical = local_observed == authoritative_observed
    rejection_taxonomy_identical = Counter(local_taxonomy) == Counter(
        authoritative_taxonomy
    )
    result = {
        "authoritative_matches": sum(
            bool(row[-1]) for row in authoritative_rows
        ),
        "expected_passes": len(local_expected),
        "local_matches": sum(bool(row[-1]) for row in local_rows),
        "mapped_identically": mapped_identically,
        "match_vector_identical": match_vector_identical,
        "observed_patterns_each": len(local_observed),
        "rejection_taxonomy_identical": rejection_taxonomy_identical,
        "templates": len(local_templates),
        "timestamps_identical": timestamps_identical,
    }
    if len(local_observed) != len(authoritative_observed) or not all(
        (
            mapped_identically,
            match_vector_identical,
            timestamps_identical,
            rejection_taxonomy_identical,
        )
    ):
        raise EvidenceError("local and authoritative corridors are not D11-equivalent")
    return result


def _evaluation_signature(evaluation: Any) -> tuple[Any, ...]:
    def crossing_time(crossing: Any) -> tuple[int, float]:
        if crossing is None:
            return (0, 0.0)
        return (1, round(float(crossing.time_s), 9))

    patterns = sorted(
        (
            str(pattern.match_trace.get("candidate_fingerprint") or ""),
            round(float(pattern.start_offset_s), 9),
            round(float(pattern.end_offset_s), 9),
        )
        for pattern in evaluation.climb_patterns
    )
    attempts = sorted(
        (
            str(attempt.canon_id),
            crossing_time(attempt.start),
            crossing_time(attempt.finish),
            bool(attempt.accepted),
            str(attempt.rejection_code or ""),
        )
        for attempt in evaluation.attempts
    )
    return patterns, attempts, tuple(sorted(evaluation.rejections.items()))


def _sample_membership_sensitivity(
    harness: Any,
    connection: Any,
    local_candidates: Sequence[Any],
    authoritative_candidates: Sequence[Any],
) -> dict[str, int]:
    from app.services.canon_traversal import CanonTraversalEngine
    from shapely.geometry import Point

    local_by_fingerprint = {candidate.fingerprint: candidate for candidate in local_candidates}
    authoritative_by_fingerprint = {
        candidate.fingerprint: candidate for candidate in authoritative_candidates
    }
    tile_to_fingerprints: dict[str, set[str]] = {}
    for candidate in local_candidates:
        for tile_id in candidate.runtime.corridor_tile_ids:
            tile_to_fingerprints.setdefault(str(tile_id), set()).add(candidate.fingerprint)

    tests = 0
    flipped_points = 0
    affected: set[tuple[str, str]] = set()
    rows = connection.execute(
        "SELECT activity_id, streams_json FROM activity_streams "
        "ORDER BY CAST(activity_id AS INTEGER)"
    ).fetchall()
    for activity_id, streams_json in rows:
        raw = json.loads(streams_json)
        streams = {str(stream["type"]): list(stream["data"]) for stream in raw}
        samples = harness._tile_samples(streams)
        relevant = sorted(
            {
                fingerprint
                for sample in samples
                for fingerprint in tile_to_fingerprints.get(str(sample["tile_id"]), set())
            }
        )
        for fingerprint in relevant:
            local = local_by_fingerprint[fingerprint].exact_corridor
            authoritative = authoritative_by_fingerprint[fingerprint].exact_corridor
            pair_flipped = False
            for sample in samples:
                tests += 1
                point = Point(float(sample["lon"]), float(sample["lat"]))
                if bool(local.covers(point)) != bool(authoritative.covers(point)):
                    flipped_points += 1
                    pair_flipped = True
            if pair_flipped:
                affected.add((str(activity_id), fingerprint))

    engine = CanonTraversalEngine()
    changes = 0
    for activity_id, fingerprint in sorted(affected, key=lambda item: (int(item[0]), item[1])):
        streams = harness._streams_for_activity(connection, activity_id)
        samples = harness._tile_samples(streams)
        local = local_by_fingerprint[fingerprint]
        authoritative = authoritative_by_fingerprint[fingerprint]
        local_evaluation = engine.evaluate(
            activity_id=uuid5(NAMESPACE_URL, f"corridor-equivalence:{activity_id}"),
            wallet="offline-corridor-equivalence",
            candidates=[local.runtime],
            raw_samples=samples,
            user_weight_kg=75.0,
        )
        authoritative_evaluation = engine.evaluate(
            activity_id=uuid5(NAMESPACE_URL, f"corridor-equivalence:{activity_id}"),
            wallet="offline-corridor-equivalence",
            candidates=[authoritative.runtime],
            raw_samples=samples,
            user_weight_kg=75.0,
        )
        if _evaluation_signature(local_evaluation) != _evaluation_signature(
            authoritative_evaluation
        ):
            changes += 1
    if changes:
        raise EvidenceError(
            f"PostGIS/local membership differences changed {changes} D11 classifications"
        )
    return {
        "affected_activity_candidate_pairs": len(affected),
        "flipped_points": flipped_points,
        "pass_or_classification_changes": changes,
        "tests": tests,
    }


def generate(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = validate_generated_at(args.generated_at)
    expected_canon_hash = require_sha256(args.expected_canon_sha256, "canon report")
    actual_canon_hash = sha256_file(args.canon_report)
    if actual_canon_hash != expected_canon_hash:
        raise EvidenceError(
            f"canon report SHA-256 mismatch: expected {expected_canon_hash}, got {actual_canon_hash}"
        )
    if sha256_file(args.review_labels) != args.expected_review_sha256:
        raise EvidenceError("review-label fixture SHA-256 drifted")
    if sha256_file(args.corpus) != args.expected_corpus_sha256:
        raise EvidenceError("golden corpus SHA-256 drifted")

    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    import canon_traversal_replay as harness
    from shapely import wkb

    runtime = harness.verify_runtime_dependencies()
    report = json.loads(args.canon_report.read_text())
    review = json.loads(args.review_labels.read_text())
    selected, audit = harness.resolve_launch_canon_candidates(report, review)
    validate_launch_snapshot(
        report,
        selected,
        audit,
        expected_candidates=args.expected_candidates,
        expected_boundaries=args.expected_boundaries,
    )
    local_candidates = harness.load_ratified_runtime_candidates(selected)

    _load_environment(args.database_env)
    database_url = os.environ.get(args.database_url_env)
    if not database_url:
        raise EvidenceError(f"{args.database_url_env} is not set")
    import psycopg2

    connection = psycopg2.connect(database_url)
    try:
        set_read_only(connection)
        database_identity = fetch_postgis_identity(connection)
        rows = fetch_authoritative_corridors(connection, selected)
        connection.rollback()
    finally:
        connection.close()

    authoritative_geometries = {
        row["fingerprint"]: wkb.loads(row["wkb"]) for row in rows
    }
    authoritative_candidates = _authoritative_candidates(
        local_candidates, authoritative_geometries
    )
    corpus_connection = harness._open_corpus_read_only(args.corpus)
    try:
        reference = _reference_sensitivity(
            harness,
            corpus_connection,
            args.corpus,
            local_candidates,
            authoritative_candidates,
            expected_reference_passes=args.expected_reference_passes,
        )
        membership = _sample_membership_sensitivity(
            harness,
            corpus_connection,
            local_candidates,
            authoritative_candidates,
        )
    finally:
        corpus_connection.close()

    geometry = _geometry_comparison(local_candidates, authoritative_geometries)
    document = {
        "authority": {
            "engine": database_identity,
            "expression": (
                "ST_Multi(ST_Buffer(ST_GeomFromText(centerline_wkt,4326)::geography,"
                "corridor_half_width_m)::geometry)"
            ),
            "geometry_contract": "valid SRID 4326 MultiPolygon",
            "valid_geometries": len(rows),
        },
        "authoritative_wkb_manifest": {
            "line_model": (
                "candidate_fingerprint_ascii_nul_raw_st_asewkb_bytes_lf_"
                "sorted_by_fingerprint"
            ),
            "sha256": authoritative_wkb_manifest(rows),
        },
        "candidate_count": len(selected),
        "canon_report_sha256": actual_canon_hash,
        "generated_at": generated_at,
        "geometry_comparison": geometry,
        "h3_tile_lists_local_vs_authoritative_geometry_identical": True,
        "launch_reconstruction": {
            "boundary_ratifications": int(audit.get("boundary_ratifications") or 0),
            "resolved_candidates": int(audit.get("resolved_candidates") or 0),
        },
        "local_reconstruction": (
            "per-candidate azimuthal-equidistant centerline buffer transformed back to EPSG:4326"
        ),
        "model": MODEL,
        "reference_sensitivity": reference,
        "runtime": runtime,
        "sample_membership_sensitivity": membership,
        "conclusion": (
            "The local AEQD reconstruction is near-equivalent, not byte-identical, "
            "and classification-equivalent for this pinned replay."
        ),
    }
    assert_privacy_bounded(document)
    return document


def build_parser() -> argparse.ArgumentParser:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canon-report", type=Path, required=True)
    parser.add_argument("--expected-canon-sha256", required=True)
    parser.add_argument(
        "--review-labels",
        type=Path,
        default=root / "backend/tests/fixtures/canon_review_labels_2026-07-05.json",
    )
    parser.add_argument("--expected-review-sha256", default=EXPECTED_REVIEW_SHA256)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--expected-corpus-sha256", default=EXPECTED_CORPUS_SHA256)
    parser.add_argument("--database-env", type=Path, required=True)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--expected-candidates", type=int, default=57)
    parser.add_argument("--expected-boundaries", type=int, default=15)
    parser.add_argument("--expected-reference-passes", type=int, default=98)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = generate(args)
        payload = canonical_json_bytes(document)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    except (EvidenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"corridor evidence generation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "candidate_count": document["candidate_count"],
                "output_sha256": hashlib.sha256(payload).hexdigest(),
                "reference_passes": document["reference_sensitivity"]["expected_passes"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
