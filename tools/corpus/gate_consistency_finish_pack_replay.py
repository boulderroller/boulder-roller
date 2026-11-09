"""Read-only replay of the approved finish pack through the amended D13 code.

Inputs are the full, hash-checked local files referenced by the gate-rule pack
at --inputs/COMMIT. Private observations stay outside the checkout, mode 0600.
Only pooled/per-gate aggregates enter the output. No boundary is modified.
"""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
import json
import multiprocessing
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid5

import numpy as np
from shapely.geometry import LineString

import canon_traversal_replay as cr
import gate_consistency as research


def init_worker(phases):
    global PHASES
    PHASES = phases


def replay_ride(record):
    from app.services.canon_traversal import CanonTraversalEngine

    aid, encoded = record
    streams = {s["type"]: s["data"] for s in json.loads(encoded)}
    ll, times = np.asarray(streams["latlng"], dtype=float), np.asarray(streams["time"], dtype=float)
    if ll.shape != (len(times), 2) or not np.isfinite(ll).all() or not np.isfinite(times).all():
        raise ValueError("Malformed corpus stream")
    observations = {phase: [] for phase in PHASES}
    rejected = {phase: Counter() for phase in PHASES}
    pairs = 0
    engine = CanonTraversalEngine()
    for rid, base in PHASES["before"].items():
        minx, miny, maxx, maxy = base.runtime.corridor.bounds
        indices = np.flatnonzero((ll[:, 1] >= minx - .01) & (ll[:, 1] <= maxx + .01)
                                 & (ll[:, 0] >= miny - .01) & (ll[:, 0] <= maxy + .01))
        if len(indices) < 2:
            continue
        lo, hi = max(0, int(indices[0]) - 1), min(len(times), int(indices[-1]) + 2)
        # Same conservative buffered screen as fix1; acceptance is the engine's.
        if not LineString([(lon, lat) for lat, lon in ll[lo:hi]]).intersects(
                base.runtime.gate_start.buffer(.0005)):
            continue
        pairs += 1
        raw = [{"t": float(times[i]), "lat": float(ll[i, 0]), "lon": float(ll[i, 1]),
                "source_index": i} for i in range(lo, hi)]
        for phase, candidates in PHASES.items():
            candidate = candidates[rid]
            result = engine.evaluate(activity_id=uuid5(NAMESPACE_URL, f"offline-corpus:{aid}"),
                                     wallet="offline", candidates=[candidate.runtime], raw_samples=raw)
            rejected[phase].update(result.rejections)
            for pattern in result.climb_patterns:
                obs = cr.observed_pass_from_pattern(str(aid), candidate, pattern, raw)
                crosses = pattern.match_trace["gate_crossings"]
                observations[phase].append({
                    "observation": asdict(obs),
                    "legacy_start_progress_m": cr.crossing_progress_m(
                        candidate, obs.start_lon, obs.start_lat, crosses["start"], legacy_clipped_projection=True),
                    "legacy_finish_progress_m": cr.crossing_progress_m(
                        candidate, obs.finish_lon, obs.finish_lat, crosses["finish"], legacy_clipped_projection=True)})
    return observations, rejected, pairs


def recall(observed, references):
    used = set()
    matches = 0
    for ref in references:
        for i, obs in enumerate(observed):
            if i not in used and obs.activity_id == ref["activity_id"] and obs.decision_id == ref["decision_id"] \
                    and cr.reference_contains_observed(ref["start_s"], ref["end_s"], obs.start_s, obs.end_s):
                used.add(i)
                matches += 1
                break
    return {"matched": matches, "expected": len(references),
            "fraction": matches / len(references) if references else None}


def summarize(data, phases):
    result = {"evidence_class": "local_offline_read_only_corpus_replay",
              "inputs": data["inputs"], "rides_scanned": data["rides_scanned"],
              "ride_climb_pairs": data["pairs"], "phases": {}}
    for phase, rows in data["observations"].items():
        observations = [cr.ObservedPass(**row["observation"]) for row in rows]
        candidates = list(phases[phase].values())
        hashes = {"corpus_sha256": data["inputs"]["corpus"]["sha256"],
                  "canon_report_sha256": data["inputs"][
                      "COMPILER-BEFORE.json" if phase == "before" else "ADMITTED-AFTER.json"]["sha256"],
                  "review_labels_sha256": data["inputs"]["APPROVALS.json"]["sha256"]}
        boundary = cr.boundary_repeat_metrics(observations, candidates, source_hashes=hashes)
        legacy = cr.boundary_repeat_metrics([
            replace(obs, start_progress_m=row["legacy_start_progress_m"],
                    finish_progress_m=row["legacy_finish_progress_m"])
            for obs, row in zip(observations, rows)], candidates, source_hashes=hashes,
            legacy_clipped_projection=True)
        timing = cr.timing_agreement_metrics(observations, candidates, source_hashes=hashes)
        reference = recall(observations, data["references"])
        frozen = boundary["frozen_input"]
        # Exercise the production cutover builder. Other historical cutover bars
        # are deliberately unmeasured here; this task admits only the two bars
        # below plus frozen reference recall, not a new full-cutover claim.
        scorecard = cr.build_cutover_scorecard(
            corpus_integrity_ok=True, replay_errors=0,
            reference_passes=reference["expected"], reference_h3_hits=0,
            traversal_matches=reference["matched"],
            boundary_eligible_climb_gate_groups=boundary["eligible_climb_gate_groups"],
            boundary_eligible_distinct_rides=boundary["eligible_distinct_rides"],
            repeat_boundary_endpoints=boundary["repeat_endpoints"],
            boundary_p95_error_m=boundary["_p95_error_m_raw"],
            boundary_strict_max_error_m=boundary["_max_error_m_raw"],
            boundary_candidate_manifest_sha256=frozen["candidate_manifest_sha256"],
            boundary_observation_manifest_sha256=frozen["observation_manifest_sha256"],
            boundary_input_manifest_sha256=frozen["input_manifest_sha256"],
            boundary_metric_ratified=True, timing_metrics=timing,
            cross_rider_pairs=0, cross_rider_agreements=0, cross_rider_supported_candidates=0,
            unclassified_disagreements=0)
        geometry = cr.gate_geometry_metrics(candidates)
        counts = Counter(obs.decision_id for obs in observations)
        for row in geometry:
            row["accepted_efforts"] = counts[row["decision_id"]]
        result["phases"][phase] = {
            "accepted_efforts": len(observations), "reference_recall": reference,
            "rejections": data["rejections"][phase],
            "boundary": boundary, "legacy_historical_only": legacy, "timing": timing,
            "geometry_scan": geometry,
            "geometry_flags": [row for row in geometry if row["geometry_flag"]],
            "bars": {key: scorecard["gates"][key] for key in ("boundary_agreement", "timing_agreement")}}
    return result


def main():
    from app.services.canon_traversal import _project_candidate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--private-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--reuse", action="store_true")
    args = parser.parse_args()
    if args.private_cache.resolve().is_relative_to(research.ROOT):
        parser.error("Private cache must be outside the checkout")
    source, rows, runtime_phases, moved = research.build_candidates(args.inputs)
    inputs = {key: source[key] for key in ("corpus", "registry", "pbf")}
    for key, record in inputs.items():
        if research.digest(record["path"]) != record["sha256"]:
            raise ValueError(f"Changed input: {key}")
    for name in ("COMPILER-BEFORE.json", "ADMITTED-AFTER.json", "INPUTS.json", "APPROVALS.json"):
        inputs[name] = {"sha256": research.digest(args.inputs / name)}
    for name, key in (("COMPILER-BEFORE.json", "hydrated_before"), ("ADMITTED-AFTER.json", "admitted_after")):
        if inputs[name]["sha256"] != source[key]["sha256"]:
            raise ValueError(f"Not the gate-rule pack's pinned full geometry: {name}")
    inputs["engine"] = {"sha256": research.digest(research.ROOT / "backend/app/services/canon_traversal.py")}
    if inputs["engine"]["sha256"] != source["engine"]["sha256"]:
        raise ValueError("Traversal engine differs from the approved geometry replay")
    inputs["gate_rule_commit"] = (args.inputs / "COMMIT").read_text().strip()
    inputs["scorecard_code_sha256"] = research.digest(cr.__file__)
    inputs["runner_code_sha256"] = research.digest(__file__)
    phases = {}
    for phase, candidates in runtime_phases.items():
        phases[phase] = {}
        for rid, c in candidates.items():
            p = _project_candidate(c)
            phases[phase][rid] = cr.RatifiedCandidate(rid, c.candidate_fingerprint, c.display_name,
                                                     c, c.corridor, p.centerline, p.forward)
    if args.reuse:
        data = research.read(args.private_cache)
        if data["inputs"] != inputs:
            raise ValueError("Private cache inputs/code differ; run a fresh replay")
    else:
        con = sqlite3.connect(Path(inputs["corpus"]["path"]).as_uri() + "?mode=ro&immutable=1", uri=True)
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Corpus integrity check failed")
        refs, mapping = research.freeze_references(con, runtime_phases)
        records = list(con.execute("SELECT activity_id, streams_json FROM activity_streams ORDER BY CAST(activity_id AS INTEGER)"))
        con.close()
        data = {"inputs": inputs, "references": refs, "reference_mapping": mapping,
                "rides_scanned": len(records), "pairs": 0,
                "observations": {p: [] for p in phases}, "rejections": {p: Counter() for p in phases}}
        print(f"Frozen {len(refs)} references; {len(rows)} climbs; {len(moved)} approved finishes", flush=True)
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                                 initializer=init_worker, initargs=(phases,)) as pool:
            for n, (obs, rejected, pairs) in enumerate(pool.map(replay_ride, records, chunksize=4), 1):
                for phase in phases:
                    data["observations"][phase].extend(obs[phase])
                    data["rejections"][phase].update(rejected[phase])
                data["pairs"] += pairs
                if n % 100 == 0:
                    print(f"Replayed {n}/{len(records)} rides", flush=True)
        if research.digest(inputs["corpus"]["path"]) != inputs["corpus"]["sha256"]:
            raise ValueError("Corpus changed during replay")
        research.write(args.private_cache, data, private=True)
    result = summarize(data, phases)
    research.write(args.output, result)
    print(json.dumps({phase: {"efforts": value["accepted_efforts"],
                             "recall": value["reference_recall"],
                             "boundary_p95_m": value["boundary"]["_p95_error_m_raw"],
                             "timing_p95_s": value["timing"]["_p95_error_s_raw"],
                             "bars": {k: v["pass"] for k, v in value["bars"].items()}}
                      for phase, value in result["phases"].items()}), flush=True)


if __name__ == "__main__":
    main()
