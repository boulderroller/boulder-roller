#!/usr/bin/env python3
"""Generate the frozen, privacy-bounded cross-rider canon evidence snapshot.

Eligibility is computed from directional gate crossings and an intermediate
timed GPS sample before D11 acceptance or rejection is inspected.  Pairing then
excludes same-rider and byte-identical sources.  Raw ride, rider, object-path,
and content identifiers are used only in memory and never enter the report.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, uuid5


MODEL = "canon_cross_rider_evidence_v2"
EXPECTED_REVIEW_SHA256 = (
    "77fbdcc691de9d82124f3d848035f103e5433c6ef2bbe3d8bd64782041c4fdd9"
)
EXPECTED_ALL_OBJECTS_SHA256 = (
    "b714f82e043c58599ad248f00c7f01b92c6ed4f42983ec8306bbe9260cf83f68"
)
DOGFOOD_CUTOFF = datetime.fromisoformat("2026-06-12T21:43:26.751280+00:00")
EXPECTED_DOGFOOD_MANIFEST_SHA256 = (
    "5900f60f1f3831c301e4c9da6b0bc93f7858bd2d26201e283405ce2dcbc3054d"
)
EXPECTED_NATIVE_PARSER_SHA256 = (
    "9f2915020fe49af36880f09a132da81d92910d85824a9329b6b7eb65f7f1e31d"
)
EXPECTED_PARSER_INIT_SHA256 = (
    "fccce6af7dc6ef239204de5105a360d394e3bdd4019ffce6ac4db291bcb7e78b"
)
EXPECTED_PARSER_ADAPTER_SHA256 = (
    "67736a2634112e04c7a0cc884909b7e815cebbc3fdca5e32e7894b124ac35dd7"
)
EXPECTED_TRAVERSAL_ENGINE_SHA256 = (
    "869b69c26f86d7d2229cd14b5d048e5dc24a5ca53113f18de4fbdd819ef05106"
)
EXPECTED_PARSE_ERRORS = {"fit_timestamp_regression": 1, "gpx_no_trackpoints": 3}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SENSITIVE_KEYS = {
    "activity_id",
    "ride_id",
    "ride_ids",
    "user_id",
    "user_ids",
    "raw_file_path",
    "raw_sha256",
    "rider_hash",
    "rider_id",
    "rider_ids",
}


class EvidenceError(RuntimeError):
    """A frozen source, runtime, denominator, or privacy contract drifted."""


@dataclass
class SourceObject:
    ordinal: int
    source_key: str
    rider_key: str
    storage_path: str
    file_type: str
    uploaded_at: datetime
    raw_sha256: str = ""
    byte_count: int = 0

    @property
    def dogfood(self) -> bool:
        return is_dogfood_source(self.file_type, self.uploaded_at)


@dataclass(frozen=True)
class AttemptEvidence:
    source_key: str
    rider_key: str
    raw_sha256: str
    decision_id: str
    start_s: float
    finish_s: float
    accepted: bool
    rejection: str

    @property
    def token(self) -> str:
        return (
            f"{self.raw_sha256}:{self.start_s:.9f}:{self.finish_s:.9f}"
        )


@dataclass
class RideEvidence:
    source: SourceObject
    parse_error: str | None = None
    corridor_fingerprints: set[str] = field(default_factory=set)
    attempts: list[AttemptEvidence] = field(default_factory=list)
    accepted_passes: int = 0
    rejections: Counter[str] = field(default_factory=Counter)


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
    if datetime.fromisoformat(value[:-1] + "+00:00").tzinfo != timezone.utc:
        raise EvidenceError("generated_at must be UTC")
    return value


def canonical_json_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def digest_text_lines(lines: Iterable[str], *, unique: bool = False) -> str:
    values = list(lines)
    if unique:
        values = list(set(values))
    payload = "".join(f"{line}\n" for line in sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def object_line(source: SourceObject) -> str:
    require_sha256(source.raw_sha256, "raw object content")
    return f"{source.raw_sha256}\t{source.file_type.lower()}\t{source.byte_count}"


def assert_privacy_bounded(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).lower()
            if normalized in SENSITIVE_KEYS:
                raise EvidenceError(f"privacy-sensitive output key at {'.'.join(path + (str(key),))}")
            assert_privacy_bounded(child, path + (str(key),))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            assert_privacy_bounded(child, path + (str(index),))
    elif isinstance(value, str) and (value.startswith("/") or "rides/" in value):
        raise EvidenceError(f"privacy-sensitive path value at {'.'.join(path)}")


def set_read_only(connection: Any) -> None:
    connection.set_session(readonly=True, autocommit=False)


def is_dogfood_source(file_type: str, uploaded_at: datetime) -> bool:
    """Outcome-independent source selection; the later 22:01 upload is excluded."""

    if uploaded_at.tzinfo is None:
        raise EvidenceError("source uploaded_at must be timezone-aware")
    return file_type.lower() == "tcx" and uploaded_at.astimezone(timezone.utc) <= DOGFOOD_CUTOFF


def _load_environment(path: Path) -> None:
    from dotenv import load_dotenv

    if not path.is_file():
        raise EvidenceError(f"database environment file does not exist: {path}")
    load_dotenv(path, override=False)


def _fetch_sources(connection: Any) -> list[SourceObject]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id::text,
                   user_id::text,
                   raw_file_path,
                   lower(file_type),
                   uploaded_at
              FROM public.rides
             WHERE raw_file_path IS NOT NULL
             ORDER BY id
            """
        )
        rows = cursor.fetchall()
    result: list[SourceObject] = []
    for ordinal, (source_key, rider_key, path, file_type, uploaded_at) in enumerate(
        rows, start=1
    ):
        if not source_key or not rider_key or not path or not file_type:
            raise EvidenceError("frozen source row is missing identity, rider, path, or type")
        result.append(
            SourceObject(
                ordinal=ordinal,
                source_key=str(source_key),
                rider_key=str(rider_key),
                storage_path=str(path),
                file_type=str(file_type).lower(),
                uploaded_at=uploaded_at,
            )
        )
    return result


def _verify_source_shape(sources: Sequence[SourceObject], args: argparse.Namespace) -> None:
    riders = {source.rider_key for source in sources}
    types = Counter(source.file_type for source in sources)
    expected_types = {"fit": args.expected_fit, "gpx": args.expected_gpx, "tcx": args.expected_tcx}
    if len(sources) != args.expected_objects:
        raise EvidenceError(
            f"source object count drifted: expected {args.expected_objects}, got {len(sources)}"
        )
    if len(riders) != args.expected_riders:
        raise EvidenceError(
            f"source rider count drifted: expected {args.expected_riders}, got {len(riders)}"
        )
    if dict(sorted(types.items())) != expected_types:
        raise EvidenceError(
            f"source file-type census drifted: expected {expected_types}, got {dict(types)}"
        )


def _classify_parse_error(file_type: str, error: BaseException) -> str:
    message = str(error).lower()
    if file_type == "gpx" and any(
        fragment in message
        for fragment in ("trackpoint", "track point", "no points", "empty activity")
    ):
        return "gpx_no_trackpoints"
    if file_type == "fit" and "timestamp" in message and any(
        fragment in message for fragment in ("regress", "monotonic", "order")
    ):
        return "fit_timestamp_regression"
    return f"{file_type}_unclassified_parse_error"


def _parse_worker(file_type: str) -> int:
    """Parse exactly one object in a clean process and emit no source identity."""

    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    raw = sys.stdin.buffer.read()
    try:
        import h3
        from app.services.workout_parse_adapter import parse_ride_file_bytes_rust

        parsed = parse_ride_file_bytes_rust(raw, file_type)
        if not parsed.records:
            raise ValueError("empty activity has no trackpoints")
        origin = min(record.timestamp for record in parsed.records)
        samples: list[dict[str, Any]] = []
        for source_index, record in enumerate(parsed.records):
            sample: dict[str, Any] = {
                "source_index": source_index,
                "t": (record.timestamp - origin).total_seconds(),
                "lat": record.lat,
                "lon": record.lon,
                "power_w": record.power_w,
                "hr_bpm": record.heart_rate_bpm,
            }
            if record.lat is not None and record.lon is not None:
                sample["tile_id"] = h3.latlng_to_cell(float(record.lat), float(record.lon), 10)
            samples.append(sample)
        payload = {"ok": True, "samples": samples}
    except BaseException as exc:  # native parser failures must become data, not a parent crash
        payload = {"ok": False, "error": _classify_parse_error(file_type, exc)}
    sys.stdout.write(json.dumps(payload, separators=(",", ":"), allow_nan=False))
    return 0


def parse_in_clean_process(raw: bytes, file_type: str, timeout_s: int) -> dict[str, Any]:
    process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--parse-worker", file_type],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout_s,
    )
    if process.returncode != 0:
        raise EvidenceError(
            f"isolated parser process exited {process.returncode} for a {file_type} source"
        )
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise EvidenceError("isolated parser emitted invalid JSON") from exc
    if not isinstance(payload, Mapping) or "ok" not in payload:
        raise EvidenceError("isolated parser emitted an invalid contract")
    return dict(payload)


def _runtime_contract(root: Path, harness: Any) -> dict[str, Any]:
    observed = harness.verify_runtime_dependencies()
    backend = root / "backend"
    import workout_parse

    package_init = Path(workout_parse.__file__).resolve()
    native = sorted(package_init.parent.glob("workout_parse*.so"))
    if len(native) != 1:
        raise EvidenceError("expected exactly one native workout_parse module")
    checks = {
        "native_parser_sha256": (sha256_file(native[0]), EXPECTED_NATIVE_PARSER_SHA256),
        "parser_init_sha256": (sha256_file(package_init), EXPECTED_PARSER_INIT_SHA256),
        "parser_adapter_sha256": (
            sha256_file(backend / "app/services/workout_parse_adapter.py"),
            EXPECTED_PARSER_ADAPTER_SHA256,
        ),
        "traversal_engine_sha256": (
            sha256_file(backend / "app/services/canon_traversal.py"),
            EXPECTED_TRAVERSAL_ENGINE_SHA256,
        ),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise EvidenceError(f"runtime dependency {label} drifted: expected {expected}, got {actual}")
    if observed.get("native_parser_sha256") != EXPECTED_NATIVE_PARSER_SHA256:
        raise EvidenceError("replay harness and cross-rider native runtime pins disagree")
    return {
        "execution_model": "one_clean_subprocess_per_ride",
        "native_parser_sha256": checks["native_parser_sha256"][0],
        "parser_adapter_sha256": checks["parser_adapter_sha256"][0],
        "parser_contract_version": int(getattr(workout_parse, "CURRENT_PARSER_VERSION")),
        "parser_init_sha256": checks["parser_init_sha256"][0],
        "parser_package_version": str(getattr(workout_parse, "__version__", "unknown")),
        "sample_contract": (
            "relative_time_lat_lon_power_hr_preserve_source_index_and_malformed_rows"
        ),
        "traversal_engine_sha256": checks["traversal_engine_sha256"][0],
    }


def _candidate_corridor_manifest(
    selected: Sequence[Mapping[str, Any]], rows: Sequence[Mapping[str, Any]]
) -> str:
    selected_by_fingerprint = {
        str(item["candidate_fingerprint"]): item for item in selected
    }
    lines = []
    for row in rows:
        fingerprint = str(row["fingerprint"])
        item = selected_by_fingerprint[fingerprint]
        lines.append(
            "\t".join(
                (
                    str(item["_launch_decision_id"]),
                    str(item["_launch_authority"]),
                    fingerprint,
                    hashlib.sha256(bytes(row["wkb"])).hexdigest(),
                )
            )
        )
    return digest_text_lines(lines)


def _authoritative_candidates(local: Sequence[Any], rows: Sequence[Mapping[str, Any]]) -> list[Any]:
    from shapely import wkb

    geometries = {str(row["fingerprint"]): wkb.loads(row["wkb"]) for row in rows}
    return [
        replace(
            candidate,
            runtime=replace(candidate.runtime, corridor=geometries[candidate.fingerprint]),
            exact_corridor=geometries[candidate.fingerprint],
        )
        for candidate in local
    ]


def _replay_ride(
    source: SourceObject,
    samples: Sequence[Mapping[str, Any]],
    candidates: Sequence[Any],
) -> RideEvidence:
    from app.services.canon_traversal import CanonTraversalEngine, _normalize_samples
    from shapely.geometry import LineString

    evidence = RideEvidence(source=source)
    valid_points = [
        (float(sample["lon"]), float(sample["lat"]))
        for sample in samples
        if sample.get("lat") is not None and sample.get("lon") is not None
    ]
    if len(valid_points) < 2:
        return evidence
    trace = LineString(valid_points)
    corridor_hits = [
        candidate for candidate in candidates if trace.intersects(candidate.exact_corridor)
    ]
    evidence.corridor_fingerprints = {
        candidate.fingerprint for candidate in corridor_hits
    }

    engine = CanonTraversalEngine()
    evaluation = engine.evaluate(
        activity_id=uuid5(NAMESPACE_URL, f"cross-rider-source:{source.ordinal}"),
        wallet="offline-cross-rider-evidence",
        candidates=[candidate.runtime for candidate in candidates],
        raw_samples=samples,
        user_weight_kg=75.0,
    )
    evidence.accepted_passes = len(evaluation.climb_patterns)
    evidence.rejections.update(evaluation.rejections)
    normalized, _, _ = _normalize_samples(samples)
    by_canon = {str(candidate.runtime.canon_id): candidate for candidate in candidates}
    for attempt in evaluation.attempts:
        if attempt.start is None or attempt.finish is None:
            continue
        if not any(attempt.start.time_s < sample.t_s < attempt.finish.time_s for sample in normalized):
            continue
        candidate = by_canon.get(str(attempt.canon_id))
        if candidate is None:
            raise EvidenceError("D11 emitted an attempt for an unknown launch candidate")
        evidence.attempts.append(
            AttemptEvidence(
                source_key=source.source_key,
                rider_key=source.rider_key,
                raw_sha256=source.raw_sha256,
                decision_id=candidate.decision_id,
                start_s=float(attempt.start.time_s),
                finish_s=float(attempt.finish.time_s),
                accepted=bool(attempt.accepted),
                rejection=str(attempt.rejection_code or ""),
            )
        )
    return evidence


def build_pair_metrics(
    attempts: Sequence[AttemptEvidence],
) -> tuple[dict[str, Any], str, str]:
    """Apply same-rider and exact-content exclusions after pre-outcome eligibility."""

    grouped: dict[str, list[AttemptEvidence]] = defaultdict(list)
    for attempt in attempts:
        grouped[attempt.decision_id].append(attempt)
    same_rider_excluded = 0
    raw_cross_rider_pairs = 0
    duplicate_excluded = 0
    eligible_pair_lines: list[str] = []
    scored_pair_lines: list[str] = []
    agreements = 0
    supported: set[str] = set()
    for decision_id, group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda item: (item.token, item.source_key, item.rider_key))
        for left, right in combinations(ordered, 2):
            if left.source_key == right.source_key or left.rider_key == right.rider_key:
                same_rider_excluded += 1
                continue
            raw_cross_rider_pairs += 1
            if left.raw_sha256 == right.raw_sha256:
                duplicate_excluded += 1
                continue
            agreement = bool(left.accepted and right.accepted)
            agreements += int(agreement)
            supported.add(decision_id)
            token_a, token_b = sorted((left.token, right.token))
            eligible_line = f"{decision_id}\t{token_a}\t{token_b}"
            eligible_pair_lines.append(eligible_line)
            scored_pair_lines.append(f"{eligible_line}\t{int(agreement)}")
    pair_count = len(eligible_pair_lines)
    return (
        {
            "agreements": agreements,
            "exact_duplicate_cross_rider_pairs_excluded": duplicate_excluded,
            "pairs": pair_count,
            "raw_cross_rider_pairs": raw_cross_rider_pairs,
            "same_rider_pairs_excluded": same_rider_excluded,
            "supported_candidate_decision_ids": sorted(supported),
            "supported_candidates": len(supported),
            "value": agreements / pair_count if pair_count else None,
        },
        digest_text_lines(eligible_pair_lines),
        digest_text_lines(scored_pair_lines),
    )


def build_attempt_manifests(attempts: Sequence[AttemptEvidence]) -> tuple[str, str]:
    """Hash pre-outcome eligibility separately from scored D11 outcomes."""

    eligible_lines: list[str] = []
    scored_lines: list[str] = []
    for attempt in attempts:
        eligible_line = "\t".join(
            (
                attempt.decision_id,
                attempt.raw_sha256,
                f"{attempt.start_s:.9f}",
                f"{attempt.finish_s:.9f}",
            )
        )
        eligible_lines.append(eligible_line)
        scored_lines.append(
            "\t".join(
                (
                    eligible_line,
                    str(int(attempt.accepted)),
                    attempt.rejection,
                )
            )
        )
    return digest_text_lines(eligible_lines), digest_text_lines(scored_lines)


def _manifest_summary(
    rides: Sequence[RideEvidence],
    candidate_manifest: str,
    authoritative_wkb_manifest: str,
    eligible_pair_manifest: str,
    scored_pair_outcomes: str,
) -> dict[str, Any]:
    all_sources = [ride.source for ride in rides]
    corridor = [ride.source for ride in rides if ride.corridor_fingerprints]
    eligible = [ride.source for ride in rides if ride.attempts]
    accepted = [ride.source for ride in rides if ride.accepted_passes]
    attempts = [attempt for ride in rides for attempt in ride.attempts]

    def lines(sources: Sequence[SourceObject]) -> list[str]:
        return [object_line(source) for source in sources]

    eligible_attempts, scored_attempt_outcomes = build_attempt_manifests(attempts)
    return {
        "accepted_objects": len(accepted),
        "accepted_objects_multiset_sha256": digest_text_lines(lines(accepted)),
        "accepted_unique_content_hashes": len({source.raw_sha256 for source in accepted}),
        "accepted_unique_objects_sha256": digest_text_lines(lines(accepted), unique=True),
        "all_objects": len(all_sources),
        "all_objects_sha256": digest_text_lines(lines(all_sources)),
        "all_unique_content_hashes": len({source.raw_sha256 for source in all_sources}),
        "authoritative_wkb_manifest_sha256": authoritative_wkb_manifest,
        "candidate_corridor_manifest_line_model": (
            "decision_id_tab_launch_authority_tab_candidate_fingerprint_tab_"
            "sha256_of_postgis_st_asbinary_corridor_sorted_utf8_final_newline"
        ),
        "candidate_corridor_manifest_sha256": candidate_manifest,
        "corridor_hit_bytes": sum(source.byte_count for source in corridor),
        "corridor_hit_objects": len(corridor),
        "corridor_hit_objects_sha256": digest_text_lines(lines(corridor)),
        "corridor_hit_unique_content_hashes": len({source.raw_sha256 for source in corridor}),
        "eligible_attempt_line_model": (
            "decision_id_tab_raw_byte_sha256_tab_start_s_tab_finish_s_"
            "sorted_utf8_final_newline"
        ),
        "eligible_attempts_sha256": eligible_attempts,
        "eligible_objects": len(eligible),
        "eligible_objects_multiset_sha256": digest_text_lines(lines(eligible)),
        "eligible_pair_line_model": (
            "decision_id_tab_lexically_ordered_raw_sha_colon_start_fixed_9dp_"
            "colon_finish_fixed_9dp_attempts_sorted_utf8_final_newline"
        ),
        "eligible_pair_manifest_sha256": eligible_pair_manifest,
        "eligible_unique_content_hashes": len({source.raw_sha256 for source in eligible}),
        "eligible_unique_objects_sha256": digest_text_lines(lines(eligible), unique=True),
        "eligible_unique_sources_sha256": digest_text_lines(lines(eligible), unique=True),
        "line_model": (
            "raw_byte_sha256_tab_lower_file_type_tab_byte_count_sorted_with_"
            "duplicates_final_newline"
        ),
        "scored_attempt_outcome_line_model": (
            "eligible_attempt_line_tab_accepted_tab_rejection_"
            "sorted_utf8_final_newline"
        ),
        "scored_attempt_outcomes_sha256": scored_attempt_outcomes,
        "scored_pair_outcome_line_model": (
            "eligible_pair_line_tab_agreement_bit_sorted_utf8_final_newline"
        ),
        "scored_pair_outcomes_sha256": scored_pair_outcomes,
    }


async def _collect_rides(
    sources: Sequence[SourceObject],
    candidates: Sequence[Any],
    *,
    parser_timeout_s: int,
) -> list[RideEvidence]:
    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.services.file_storage import create_file_storage_service

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("app.services.file_storage").setLevel(logging.WARNING)
    storage = create_file_storage_service()
    results: list[RideEvidence] = []
    for source in sources:
        raw = await storage.download_ride_file(source.storage_path)
        source.byte_count = len(raw)
        source.raw_sha256 = hashlib.sha256(raw).hexdigest()
        parsed = await asyncio.to_thread(
            parse_in_clean_process, raw, source.file_type, parser_timeout_s
        )
        if not bool(parsed.get("ok")):
            results.append(
                RideEvidence(source=source, parse_error=str(parsed.get("error") or "unknown"))
            )
            continue
        samples = parsed.get("samples")
        if not isinstance(samples, list):
            raise EvidenceError("isolated parser omitted its samples")
        results.append(_replay_ride(source, samples, candidates))
    return results


def _dogfood_summary(rides: Sequence[RideEvidence], args: argparse.Namespace) -> dict[str, Any]:
    dogfood = [ride for ride in rides if ride.source.dogfood]
    riders = {ride.source.rider_key for ride in dogfood}
    digest = digest_text_lines(object_line(ride.source) for ride in dogfood)
    summary = {
        "accepted_passes": sum(ride.accepted_passes for ride in dogfood),
        "attempts": sum(len(ride.attempts) for ride in dogfood),
        "content_manifest_sha256": digest,
        "corridor_hits": sum(bool(ride.corridor_fingerprints) for ride in dogfood),
        "riders": len(riders),
        "rides": len(dogfood),
        "source_bytes": sum(ride.source.byte_count for ride in dogfood),
        "source_selection": (
            "lower(file_type)=tcx and uploaded_at<=2026-06-12T21:43:26.751280Z"
        ),
    }
    expected = (
        args.expected_dogfood_objects,
        args.expected_dogfood_riders,
        args.expected_dogfood_bytes,
        args.expected_dogfood_manifest,
    )
    observed = (summary["rides"], summary["riders"], summary["source_bytes"], digest)
    if observed != expected:
        raise EvidenceError(f"dogfood source manifest drifted: expected {expected}, got {observed}")
    if summary["corridor_hits"] or summary["attempts"] or summary["accepted_passes"]:
        raise EvidenceError("dogfood negative control unexpectedly intersects or passes canon")
    return summary


async def generate(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = validate_generated_at(args.generated_at)
    expected_canon = require_sha256(args.expected_canon_sha256, "canon report")
    actual_canon = sha256_file(args.canon_report)
    if actual_canon != expected_canon:
        raise EvidenceError(
            f"canon report SHA-256 mismatch: expected {expected_canon}, got {actual_canon}"
        )
    if sha256_file(args.review_labels) != args.expected_review_sha256:
        raise EvidenceError("review-label fixture SHA-256 drifted")

    root = Path(__file__).resolve().parents[2]
    backend = root / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    import canon_traversal_replay as harness
    import generate_canon_corridor_equivalence as corridor_generator

    runtime = _runtime_contract(root, harness)
    report = json.loads(args.canon_report.read_text())
    review = json.loads(args.review_labels.read_text())
    selected, audit = harness.resolve_launch_canon_candidates(report, review)
    corridor_generator.validate_launch_snapshot(
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
        sources = _fetch_sources(connection)
        _verify_source_shape(sources, args)
        corridor_rows = corridor_generator.fetch_authoritative_corridors(connection, selected)
        connection.rollback()
    finally:
        connection.close()
    candidates = _authoritative_candidates(local_candidates, corridor_rows)
    candidate_manifest = _candidate_corridor_manifest(selected, corridor_rows)
    authoritative_wkb_manifest = corridor_generator.authoritative_wkb_manifest(
        corridor_rows
    )
    rides = await _collect_rides(
        sources,
        candidates,
        parser_timeout_s=args.parser_timeout_seconds,
    )

    source_bytes = sum(ride.source.byte_count for ride in rides)
    if source_bytes != args.expected_source_bytes:
        raise EvidenceError(
            f"source byte count drifted: expected {args.expected_source_bytes}, got {source_bytes}"
        )
    all_manifest = digest_text_lines(object_line(ride.source) for ride in rides)
    if all_manifest != args.expected_source_manifest:
        raise EvidenceError(
            f"source content manifest drifted: expected {args.expected_source_manifest}, got {all_manifest}"
        )
    parse_errors = Counter(
        ride.parse_error for ride in rides if ride.parse_error is not None
    )
    if dict(sorted(parse_errors.items())) != EXPECTED_PARSE_ERRORS:
        raise EvidenceError(
            f"parser error taxonomy drifted: expected {EXPECTED_PARSE_ERRORS}, got {dict(parse_errors)}"
        )

    attempts = [attempt for ride in rides for attempt in ride.attempts]
    pair_metrics, eligible_pair_manifest, scored_pair_outcomes = build_pair_metrics(attempts)
    manifest = _manifest_summary(
        rides,
        candidate_manifest,
        authoritative_wkb_manifest,
        eligible_pair_manifest,
        scored_pair_outcomes,
    )
    dogfood = _dogfood_summary(rides, args)
    eligible_rides = [ride for ride in rides if ride.attempts]
    corridor_rides = [ride for ride in rides if ride.corridor_fingerprints]
    accepted_rides = [ride for ride in rides if ride.accepted_passes]
    accepted_decisions = {
        attempt.decision_id for attempt in attempts if attempt.accepted
    }
    eligible_decisions = {attempt.decision_id for attempt in attempts}
    corridor_candidates = {
        fingerprint for ride in corridor_rides for fingerprint in ride.corridor_fingerprints
    }
    fingerprint_to_decision = {candidate.fingerprint: candidate.decision_id for candidate in candidates}
    corridor_candidate_rider_pairs = {
        (fingerprint_to_decision[fingerprint], ride.source.rider_key)
        for ride in corridor_rides
        for fingerprint in ride.corridor_fingerprints
    }
    replay_rejections: Counter[str] = Counter()
    for ride in rides:
        replay_rejections.update(ride.rejections)

    agreement = {
        "definition": (
            "distinct-rider, distinct-byte-source pairs independently eligible on the same "
            "candidate before D11 outcome"
        ),
        "eligibility": (
            "raw trace crosses the candidate start gate then finish gate in canon direction "
            "with at least one valid timed GPS sample strictly between; no corridor-coverage, "
            "monotonicity, rejection, or acceptance result enters eligibility"
        ),
        "eligible_attempts": len(attempts),
        "eligible_candidates": len(eligible_decisions),
        "eligible_distinct_riders": len({ride.source.rider_key for ride in eligible_rides}),
        "eligible_rides": len(eligible_rides),
        "eligible_unique_sources": len({ride.source.raw_sha256 for ride in eligible_rides}),
        **pair_metrics,
        "finding": (
            f"{pair_metrics['agreements']} of {pair_metrics['pairs']} independently eligible, "
            "same-canon cross-rider pairs were accepted by D11."
        ),
    }
    document = {
        "canon_report_sha256": actual_canon,
        "corridor_authority": "postgis_geography_buffer_v1",
        "dogfood_negative_control": dogfood,
        "generated_at": generated_at,
        "geographic_census": {
            "corridor_file_types": dict(
                sorted(Counter(ride.source.file_type for ride in corridor_rides).items())
            ),
            "corridor_intersecting_candidate_rider_pairs": len(corridor_candidate_rider_pairs),
            "corridor_intersecting_candidates": len(corridor_candidates),
            "corridor_intersecting_riders": len({ride.source.rider_key for ride in corridor_rides}),
            "corridor_intersecting_rides": len(corridor_rides),
            "launch_candidates": len(candidates),
        },
        "model": MODEL,
        "privacy_mode": "aggregate_counts_and_content_digests_no_rider_or_ride_ids",
        "replay": {
            "accepted_candidates": len(accepted_decisions),
            "accepted_distinct_riders": len({ride.source.rider_key for ride in accepted_rides}),
            "accepted_passes": sum(ride.accepted_passes for ride in rides),
            "accepted_rides": len(accepted_rides),
            "parseable_source_rides": len(rides) - sum(parse_errors.values()),
            "parser_error_taxonomy": dict(sorted(parse_errors.items())),
            "parser_errors": sum(parse_errors.values()),
            "rejections": dict(sorted(replay_rejections.items())),
        },
        "replay_runtime": runtime,
        "same_canon_cross_rider_agreement": agreement,
        "source": {
            "file_types": {
                "fit": args.expected_fit,
                "gpx": args.expected_gpx,
                "tcx": args.expected_tcx,
            },
            "project_ref": args.project_ref,
            "raw_uploads": len(rides),
            "source_bytes": source_bytes,
            "source_riders": len({ride.source.rider_key for ride in rides}),
            "storage_bucket": args.storage_bucket,
        },
        "source_manifest": manifest,
        "limitations": [
            (
                f"Cross-rider agreement is measured on {pair_metrics['pairs']} independent "
                f"pairs from {pair_metrics['supported_candidates']} supported candidates."
            ),
            (
                f"{sum(parse_errors.values())} of {len(rides)} frozen source objects fail "
                "under the pinned parser runtime."
            ),
            (
                "The eleven outcome-independently selected agent dogfood rides are outside "
                "Philadelphia and serve only as negative controls."
            ),
        ],
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
    parser.add_argument("--database-env", type=Path, required=True)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--expected-candidates", type=int, default=57)
    parser.add_argument("--expected-boundaries", type=int, default=15)
    parser.add_argument("--expected-objects", type=int, default=177)
    parser.add_argument("--expected-riders", type=int, default=29)
    parser.add_argument("--expected-source-bytes", type=int, default=67244165)
    parser.add_argument("--expected-fit", type=int, default=14)
    parser.add_argument("--expected-gpx", type=int, default=151)
    parser.add_argument("--expected-tcx", type=int, default=12)
    parser.add_argument("--expected-source-manifest", default=EXPECTED_ALL_OBJECTS_SHA256)
    parser.add_argument("--expected-dogfood-objects", type=int, default=11)
    parser.add_argument("--expected-dogfood-riders", type=int, default=1)
    parser.add_argument("--expected-dogfood-bytes", type=int, default=4013161)
    parser.add_argument(
        "--expected-dogfood-manifest", default=EXPECTED_DOGFOOD_MANIFEST_SHA256
    )
    parser.add_argument("--parser-timeout-seconds", type=int, default=120)
    parser.add_argument("--project-ref", default="qzkqjevawthyboymqrle")
    parser.add_argument("--storage-bucket", default="ride-uploads")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        document = asyncio.run(generate(args))
        payload = canonical_json_bytes(document)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
    except (EvidenceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"cross-rider evidence generation failed: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "agreement_pairs": document["same_canon_cross_rider_agreement"]["pairs"],
                "output_sha256": hashlib.sha256(payload).hexdigest(),
                "source_objects": document["source"]["raw_uploads"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--parse-worker":
        raise SystemExit(_parse_worker(sys.argv[2]))
    raise SystemExit(main())
