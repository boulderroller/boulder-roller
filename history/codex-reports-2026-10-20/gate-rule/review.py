#!/usr/bin/env python3
"""Offline gate-rule review, using retained inputs and the real traversal engine.

No connection factory or publisher is called. SQLite is immutable/read-only.
The research census and stop-analysis helpers are reused without modifying them.
No rider coordinates or source activity IDs are written to the review pack.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import multiprocessing
import os
import sqlite3
import statistics
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5


ROOT = Path(__file__).resolve().parents[3]
METRICS_COMMIT = "8993e19996ce5c8c2bb050845e03bf5b13d9fa22"
METRICS_SHA256 = "ffb7e47bed3f8f779e50dad911c8555d6dc815a4245345669dd58dbf1016fad1"
ROUND2_COMMIT = "711af0615"
ROUND3_NAMES = {"Wises Mill Road", "Centennial Road"}
REPLAY_PHASES = ("before", "after", "round2")
sys.path[:0] = [str(ROOT / "backend"), str(ROOT)]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value, *, compact=False):
    Path(path).write_text(json.dumps(value, indent=None if compact else 2,
                                    sort_keys=True, allow_nan=False) + "\n")


def hydrate_before(args):
    """Recover full-precision inputs by identity, never from rounded output."""
    source = read(args.source_report)
    retained = {r["candidate_fingerprint"] for r in read(args.snapshot / "registry-geography.json")}
    full = read(args.full_report)
    points = {}
    for c in full["candidates"]:
        rule = c["provenance"].get("finish_gate_rule")
        fp = rule["predecessor_fingerprint"] if rule else c["candidate_fingerprint"]
        points[fp] = (rule["predecessor_profile_points"] if rule else
                      c["provenance"]["compiler_profile_points"])
    before = {k: v for k, v in source.items() if k not in ("candidates", "skipped_roads")}
    before["skipped_roads"] = []
    before["ratified_boundaries"]["mode"] = "finish_rule_review"
    before["candidates"] = [c for c in source["candidates"] if c["candidate_fingerprint"] in retained]
    assert len(before["candidates"]) == 57
    for c in before["candidates"]:
        c["provenance"]["compiler_profile_points"] = points[c["candidate_fingerprint"]]
    write(args.before, before)


def trim_provenance(value):
    if isinstance(value, dict):
        return {k: trim_provenance(v) for k, v in value.items()
                if k not in ("compiler_profile_points", "predecessor_profile_points")}
    if isinstance(value, list):
        return [trim_provenance(v) for v in value]
    return value


def report_summary(report, path):
    fields = ("candidate_fingerprint", "display_name", "length_m", "vert_m", "avg_gradient_pct",
              "max_gradient_pct", "gate_start_wkt", "gate_end_wkt", "compiler_version")
    return {
        "artifact_kind": "review_summary_not_compiler_input",
        "ratified_boundaries": {"mode": "review_only"},
        "compiler_version": report["compiler_version"],
        "full_local_source": {"path": str(path), "sha256": digest(path)},
        "candidates": [{**{k: c[k] for k in fields},
                        "finish_gate_rule": trim_provenance(c["provenance"].get("finish_gate_rule"))}
                       for c in report["candidates"]],
    }


class SnapshotCursor:
    """Only the resolver's two SELECT shapes, evaluated against retained rows."""

    def __init__(self, rows):
        self.rows = rows
        self.result = []

    def execute(self, query, params):
        query = " ".join(query.split())
        if not query.startswith("SELECT id, candidate_fingerprint, canon_id, version, status FROM public.canon_climbs"):
            raise AssertionError("Not a lineage resolver SELECT")
        if "WHERE candidate_fingerprint = ANY(%s)" in query:
            selected = [r for r in self.rows if r["candidate_fingerprint"] in params[0]]
        elif "WHERE canon_id = %s ORDER BY version DESC LIMIT 1" in query:
            selected = sorted((r for r in self.rows if r["canon_id"] == params[0]),
                              key=lambda r: r["version"], reverse=True)[:1]
        else:
            raise AssertionError("Unexpected lineage query")
        self.result = [(r["id"], r["candidate_fingerprint"], r["canon_id"],
                        r["version"], r["status"]) for r in selected]

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result[0] if self.result else None


def prepare(args):
    from shapely import wkb, wkt
    from app.services.climb_lab import (
        build_canon_climb_publish_payload, build_climb_lab_compiler_candidate_summary,
        build_climb_lab_review_candidate_map_detail,
    )
    from app.services.canon_climb_publisher import _validated_publish_parts, _resolve_canon_publication_target

    rows = read(args.snapshot / "registry-geography.json")
    manifest = read(args.snapshot / "registration-manifest.json")
    before = read(args.before)
    proposed = read(args.proposed)
    source = read(args.source_report)
    census = read(args.research / "out/gate_census.json")
    raw = {c["id"][:8]: c for c in read(args.research / "out/gate_census_raw.json")}
    assert len(rows) == len(before["candidates"]) == len(proposed["candidates"]) == 57
    source_by_fp = {c["candidate_fingerprint"]: c for c in source["candidates"]}
    old = {c["candidate_fingerprint"]: c for c in before["candidates"]}
    by_fp = {r["candidate_fingerprint"]: r for r in rows}
    for fp, c in old.items():
        retained = copy.deepcopy(c)
        retained["provenance"].pop("compiler_profile_points")
        assert retained == source_by_fp[fp], "before differs beyond added unrounded source points"
        r = by_fp[fp]
        for key in ("canonical_profile", "length_m", "vert_m", "avg_gradient_pct"):
            assert c[key] == r[key], (r["display_name"], key)
        for ck, rk in (("centerline_wkt", "centerline_geom"),
                       ("gate_start_wkt", "gate_start_line"), ("gate_end_wkt", "gate_end_line")):
            assert wkt.loads(c[ck]).equals_exact(wkb.loads(bytes.fromhex(r[rk])), 1e-10)
    admitted = {c["id"] for c in census if c["end_cat"] == "gate_at_junction" and c["end_must_stop"]}
    assert len(admitted) == 15
    registrations = {r["registry_id"]: r for r in manifest["records"]}
    after = copy.deepcopy(before)
    after["compiler_version"] = proposed["compiler_version"]
    after["candidates"] = []
    moved, extra, successors, pairs, all_diff = [], [], [], [], []
    for new in proposed["candidates"]:
        rule = new["provenance"].get("finish_gate_rule")
        fp = rule["predecessor_fingerprint"] if rule else new["candidate_fingerprint"]
        r, previous = by_fp[fp], old[fp]
        authorized = r["id"][:8] in admitted
        if authorized and (not rule or rule["admission"] != "founder_admitted"):
            raise AssertionError(f"Admitted finish was missed: {r['display_name']}")
        if rule and not authorized:
            extra.append({"name": r["display_name"], "registry_id": r["id"], "rule": rule,
                          "candidate_fingerprint": new["candidate_fingerprint"],
                          "status": "compiler_proposal_only_not_admitted_not_prepared"})
            selected = previous
        else:
            selected = new
        after["candidates"].append(selected)
        row_diff = {
            "name": r["display_name"], "registry_id": r["id"], "canon_id": r["canon_id"],
            "tim_named_boundary": bool(previous["provenance"].get("ratified_boundary")),
            "finish_moved": authorized,
            "old": {k: previous[k] for k in ("length_m", "vert_m", "avg_gradient_pct", "max_gradient_pct", "gate_end_wkt")},
            "new": {k: selected[k] for k in ("length_m", "vert_m", "avg_gradient_pct", "max_gradient_pct", "gate_end_wkt")},
        }
        assert previous["gate_start_wkt"] == selected["gate_start_wkt"]
        if not authorized:
            assert trim_provenance(previous) == trim_provenance(selected), r["display_name"]
            # Rust/Python JSON parsing may differ by one ULP in the newly
            # carried raw points. All retained candidate fields stay exact.
            old_points = previous["provenance"]["compiler_profile_points"]
            new_points = selected["provenance"]["compiler_profile_points"]
            assert len(old_points) == len(new_points)
            assert all(abs(a[k] - b[k]) < 1e-10 for a, b in zip(old_points, new_points) for k in a)
            after["candidates"][-1] = previous
            all_diff.append(row_diff)
            continue
        registration = registrations[r["id"]]
        if registration["status"] != "index_record_absent" or registration["indexed_registration"] is not None:
            raise RuntimeError(f"STOP: moved climb has retained registration evidence: {r['display_name']}")
        gate = wkt.loads(new["gate_end_wkt"])
        coords = list(gate.coords)
        row_diff.update({
            "metres_moved": rule["metres_moved"], "control_types": sorted({c["kind"] for c in rule["controls"]}),
            "new_gate_center": {"lat": sum(c[1] for c in coords) / 2, "lon": sum(c[0] for c in coords) / 2},
            "new_gate_endpoints_lon_lat": coords, "rule": trim_provenance(rule),
        })
        moved.append(row_diff)
        all_diff.append(row_diff)
        candidate = {**new, "compiler_run_mode": "applied"}
        payload = build_canon_climb_publish_payload(candidate, ratified_by=None,
                                                    ratified_at="2026-10-20T00:00:00+00:00")
        climb, _ = _validated_publish_parts(payload)
        identity, version, predecessor = _resolve_canon_publication_target(
            SnapshotCursor(rows), climb, explicit_successor=True)
        assert (identity, version, predecessor) == (r["canon_id"], r["version"] + 1, r["id"])
        # A preparation date is not a review ratification. Publication must
        # replace these with Tim's actual review authority and timestamp.
        payload["climb"]["ratified_at"] = None
        payload["compiler_run_mode"] = "review_only"
        payload = trim_provenance(payload)
        successors.append({
            "status": "prepared_not_ratified_not_published", "canon_id": identity,
            "version": version, "supersedes_climb_id": predecessor,
            "record_continuity_policy": "new_record_board", "explicit_successor": True,
            "placement_approval": "history/codex-reports-2026-10-20/gate-rule/APPROVALS.json",
            "required_before_publication": [
                "field checks: Black Rock, Youngs Ford, Port Royal and Centennial paint",
                "passing founder 20 Oct scorecard bars; see corrected boundary/timing evidence in REPLAY.json",
                "fresh registry and registration check",
                "actual ratification actor/time"],
            "publish_payload": payload,
        })
        for label, candidate in (("BEFORE", previous), ("PROPOSED", new)):
            fields = ("candidate_fingerprint", "legacy_candidate_fingerprints", "display_name",
                      "route_name", "from_intersection", "to_intersection", "osm_way_refs", "length_m",
                      "vert_m", "avg_gradient_pct", "max_gradient_pct", "worthiness_score", "confidence",
                      "low_confidence_flags", "compiler_version", "dem_source", "canonical_profile",
                      "centerline_polyline", "gate_start_wkt", "gate_end_wkt", "odbl_source",
                      "corridor_cells")
            item = {k: copy.deepcopy(candidate[k]) for k in fields if k in candidate}
            item["canonical_profile_hash"] = candidate["provenance"]["canonical_profile_hash"]["value"]
            item["display_name"] = f"{r['display_name']} — {label}"
            item["from_intersection"] = "Start unchanged"
            item["to_intersection"] = (
                "Retained finish" if label == "BEFORE" else
                f"Finish moved {rule['metres_moved']:.2f} m; review DIFF.md")
            pairs.append(item)
    assert len(moved) == len(successors) == 15
    assert not extra, "The 57 retained climbs must have exactly the 15 admitted moves"
    after["finish_gate_review_scope"] = {
        "authority": "history/codex-briefs-2026-10-20/gate-rule.md",
        "admitted_successors": 15, "extra_compiler_proposals_withheld": extra,
        "note": "Scoped preparation, not the unfiltered compiler output; see COMPILER-PROPOSED.json.",
    }
    t_junctions = []
    for c in census:
        if c["end_cat"] != "gate_at_junction" or c["end_must_stop"]:
            continue
        original = raw[c["id"]]
        own_names = {(n or "").lower() for n in original["own_names"] if n}
        near = [j for j in original["junctions"] if abs(j["s"] - original["L_centerline_m"]) <= 12]
        continues = any((o["name"] or "").lower() in own_names and o["name"]
                        for j in near for o in j["others"])
        if not continues:
            t_junctions.append({"name": c["name"], "cross_roads": c["end_j"]["names"],
                                "classification": "research terminates_or_turns; field check"})
    assert len(t_junctions) == 10, t_junctions
    interior = [{"name": c["name"], "controls": c["inner_ctrl_detail"],
                 "standalone_flags": c["lone_flags"], "rail_crossings": c["inner_rail"]}
                for c in census if c["inner_ctrl_detail"] or c["lone_flags"] or c["inner_rail"]]
    for item in interior:
        if item["name"] == "Black Rock Road":
            item["retained_research_labels_superseded"] = item["controls"]
            item["controls"] = [
                [547.1, ["unnamed connector road"], ["not a control"]],
                [559.55, ["climber-facing stop sign"], ["stop"]],
            ]
    near_start = [{"name": c["name"], "registry_id_prefix": c["id"],
                   "controls": [j for j in c["inner_ctrl_detail"] if j[0] <= 100]}
                  for c in census if c["name"] in ("Conshohocken State Road", "Shurs Lane", "Green Lane")
                  and any(j[0] <= 100 for j in c["inner_ctrl_detail"])]
    assert len(near_start) == 3
    registered = [r for r in manifest["records"] if r["status"] != "index_record_absent"]
    assert len(registered) == 1
    registered_name = next(r["display_name"] for r in rows if r["id"] == registered[0]["registry_id"])
    assert registered_name == "Shawmont Avenue"
    diff = {"evidence_class": "offline_retained_2026_09_10_snapshot", "climbs": all_diff,
            "moved_count": len(moved), "unchanged_count": 42, "extra_proposals": extra,
            "unmapped_t_junction_field_checks": t_junctions, "interior_controls_unchanged": interior,
            "near_start_controls_unchanged": near_start,
            "registration_check": {"evidence_class": "retained_index_snapshot_not_fresh_chain_read",
                "registered_name": registered_name, "moved_registered": 0,
                "status_counts": dict(Counter(r["status"] for r in manifest["records"]))}}
    inputs = {"registry": args.snapshot / "registry-geography.json",
              "registration_manifest": args.snapshot / "registration-manifest.json",
              "retained_compiler_report": args.source_report, "pbf": args.pbf, "corpus": args.corpus,
              "research_census": args.research / "out/gate_census.json",
              "research_raw_census": args.research / "out/gate_census_raw.json",
              "research_stop_analysis": args.research / "scripts/corpus_stops.py",
              "research_geo": args.research / "scripts/geo.py",
              "unrounded_full_compile": args.full_report,
              "hydrated_before": args.before, "offline_proposed": args.proposed,
              "local_profiles": args.profiles,
              "finish_decisions": ROOT / "workout-parse/resources/philly_finish_gate_decisions_v1.json",
              "placement_approvals": args.output / "APPROVALS.json",
              "engine": ROOT / "backend/app/services/canon_traversal.py",
              "scorecard_definitions": args.metric_module,
              "round2_admitted_after": args.previous_round_report,
              "stop_map_results": args.stop_map_results}
    assert digest(args.metric_module) == METRICS_SHA256, "Use the pinned gate-consistency definitions"
    previous_summary = json.loads(subprocess.check_output([
        "git", "show", f"{ROUND2_COMMIT}:history/codex-reports-2026-10-20/gate-rule/ADMITTED-AFTER.json"], cwd=ROOT))
    assert digest(args.previous_round_report) == previous_summary["full_local_source"]["sha256"]
    amendments = read(ROOT / "workout-parse/resources/philly_finish_gate_decisions_v1.json")["decisions"]
    assert all(digest(args.stop_map_results) == d["stop_evidence_amendment"]["source"]["sha256"]
               for d in amendments if "stop_evidence_amendment" in d)
    hashes = {name: {"path": str(path), "sha256": digest(path)} for name, path in inputs.items()}
    assert hashes["corpus"]["sha256"] == "64b15790bed2628b3e7e8371657b408ec5e96305db84bfe050507b14860b98ee"
    assert hashes["retained_compiler_report"]["sha256"] == "de67892dc600affd97e0a5158f3a369ca29777b214ecce41be0e47060736bf0e"
    pack = {"compiler_version": proposed["compiler_version"], "ratified_boundaries": {"mode": "review_only"},
            "candidates": pairs}
    summary = build_climb_lab_compiler_candidate_summary(pack)
    assert len(summary["candidates"]) == 30
    assert summary["totals"]["publish_ready_candidates"] == 0
    for c in summary["candidates"]:
        detail = build_climb_lab_review_candidate_map_detail(c)
        assert detail["geometry"]["status"] == detail["profile"]["status"] == "ready"
    after["ratified_boundaries"]["mode"] = "review_only"
    full_after = args.proposed.with_name("admitted-after.json")
    write(full_after, after)
    hashes["admitted_after"] = {"path": str(full_after), "sha256": digest(full_after)}
    write(args.output / "COMPILER-BEFORE.json", report_summary(before, args.before))
    write(args.output / "COMPILER-PROPOSED.json", report_summary(proposed, args.proposed))
    write(args.output / "ADMITTED-AFTER.json", report_summary(after, full_after))
    write(args.output / "DIFF.json", diff)
    write(args.output / "SUCCESSORS.json", successors, compact=True)
    write(args.output / "CLIMBLAB.json", pack, compact=True)
    write(args.output / "INPUTS.json", hashes)
    diff_markdown(args.output, diff)
    return rows, before, after, moved, hashes


def diff_markdown(output, diff):
    lines = [
        "# Finish-gate diff — 20 October 2026", "",
        "Offline comparison against the sealed 10 September registry: 57 climbs, "
        "15 admitted finish changes, 42 unchanged, every start unchanged. "
        "Falls Road / Neill Drive stays unchanged: a same-name road split is not a junction. "
        "All 15 moves cite Tim's 20 October “yes all 15” approval; Wises Mill and Centennial also cite his later “yes shift both back” amendment. No registry or chain writes.", "",
        "| Climb | Tim named | Control | Moved m | Length m old → new | Rise m old → new | Grade % old → new | New centre lat, lon |",
        "|---|---|---|---:|---|---|---|---|",
    ]
    for c in diff["climbs"]:
        if not c["finish_moved"]:
            continue
        old, new, g = c["old"], c["new"], c["new_gate_center"]
        lines.append(f"| {c['name']} | {'yes' if c['tim_named_boundary'] else 'no'} | "
                     f"{', '.join(c['control_types'])} | {c['metres_moved']:.2f} | "
                     f"{old['length_m']:.2f} → {new['length_m']:.2f} | {old['vert_m']:.2f} → {new['vert_m']:.2f} | "
                     f"{old['avg_gradient_pct']:.3f} → {new['avg_gradient_pct']:.3f} | {g['lat']:.7f}, {g['lon']:.7f} |")
    lines += ["", "Metres moved uses the unrounded centreline calculation; old/new length fields "
              "are independently rounded, so their subtraction can differ by a centimetre.",
              "", "Claude's fix-round-1 call under D7.5 gives every control at least 15 m clearance, "
              "including when this extends the default setback band. Black Rock retains 32.14 m; "
              "West School House's 32.89 m clearance cut snaps a further 0.90 m upstream under M1 "
              "to avoid a sub-metre final segment: total 33.79 m, with 15.90 m signal clearance. "
              "Black Rock's end half-width is reset to 25 m "
              "under D10; its 35 m override is superseded and its 30 m start half-width is unchanged. "
              "Youngs Ford's directionless stop is authorized only for its exact predecessor/node by "
              "the brief's “yes all 15”; the OSM direction remains unknown.", "",
              "## Ten unmapped terminating/turning finishes for field check", "",
              "These are the research's terminates/turns subset, not ten independently surveyed T junctions.", ""]
    lines += [f"- {c['name']} — {', '.join(c['cross_roads'])}." for c in diff["unmapped_t_junction_field_checks"]]
    lines += ["", "## Near-start controls retained", ""]
    for c in diff["near_start_controls_unchanged"]:
        lines.append(f"- {c['name']}: " + "; ".join(f"{j[0]:.1f} m: {', '.join(j[1])} ({', '.join(j[2])})" for j in c["controls"]))
    lines += ["", "## Research interior-control census", "",
              "Interior timing remains elapsed time. These are the research labels with the reviewed Black Rock correction: "
              "Black Rock's research label at 547.1 m is an unnamed connector road, not a control. "
              "Its climber-facing stop sign is at 559.55 m; the new finish is 15 m before it. "
              "No stopped time is subtracted.", ""]
    for c in diff["interior_controls_unchanged"]:
        details = [f"{j[0]:.2f} m: {', '.join(j[1])} ({', '.join(j[2])})" for j in c["controls"]]
        if c["standalone_flags"]:
            details.append("standalone: " + ", ".join(c["standalone_flags"]))
        if c["rail_crossings"]:
            details.append(f"{c['rail_crossings']} interior rail crossing(s)")
        lines.append(f"- {c['name']}: " + "; ".join(details))
    lines += ["", "All 57 old/new rows, precise gate endpoints and control-node tags are in DIFF.json. "
              "The September registration manifest has only Shawmont Avenue registered; its candidate "
              "is byte-equivalent and unaffected. This is retained indexed evidence, not a current chain check.", ""]
    (output / "DIFF.md").write_text("\n".join(lines))


def replay_worker_inputs(rows, candidates, stop_climbs):
    global _REPLAY_INPUTS
    _REPLAY_INPUTS = rows, candidates, stop_climbs


def previous_proposal_comparison(args, rows, candidates, current_efforts):
    """Account for M5 against the previous proposal as well as the registry.

    Re-evaluate each lost prior proposal effort with both exact candidate
    geometries. Emit GateCrossing.to_trace(), never coordinates or source IDs.
    """
    import numpy as np
    from shapely import wkt
    from app.services.canon_traversal import CanonTraversalEngine

    commit = subprocess.check_output(
        ["git", "rev-parse", args.previous_commit], cwd=ROOT, text=True).strip()
    def prior(name):
        return json.loads(subprocess.check_output(
            ["git", "show", f"{commit}:history/codex-reports-2026-10-20/gate-rule/{name}"], cwd=ROOT))
    previous = prior("REPLAY.json")
    old_report = prior("ADMITTED-AFTER.json")
    old_candidates = {
        c["provenance"].get("finish_gate_rule", {}).get("predecessor_fingerprint", c["candidate_fingerprint"]): c
        for c in old_report["candidates"]
    }
    old_efforts = [
        {**e, "finish_s": e["start_s"] + e["after_elapsed_s"]}
        for e in previous["effort_changes"]
    ] + previous["new_traversals"]
    def same(a, b):
        return (a["registry_id"] == b["registry_id"] and a["ride_ordinal"] == b["ride_ordinal"]
                and abs(a["start_s"] - b["start_s"]) < .01)
    missing = [e for e in old_efforts if not any(same(e, n) for n in current_efforts)]
    newly_accepted = [e for e in current_efforts if not any(same(e, o) for o in old_efforts)]
    by_id = {r["id"]: r for r in rows}
    connection = sqlite3.connect(args.corpus.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    diagnostics = []
    for lost in missing:
        rid = lost["registry_id"]
        current = candidates["after"][rid].runtime
        source = old_candidates[by_id[rid]["candidate_fingerprint"]]
        old = replace(
            current, centerline=wkt.loads(source["centerline_wkt"]),
            gate_end=wkt.loads(source["gate_end_wkt"]),
            canonical_profile=tuple(source["canonical_profile"]), length_m=source["length_m"],
            vert_m=source["vert_m"], avg_gradient_pct=source["avg_gradient_pct"],
            compiler_version=source["compiler_version"], candidate_fingerprint=source["candidate_fingerprint"],
            profile_hash=source["provenance"]["canonical_profile_hash"]["value"], provenance=source["provenance"])
        aid, sj = connection.execute(
            "SELECT activity_id, streams_json FROM activity_streams ORDER BY CAST(activity_id AS INTEGER) LIMIT 1 OFFSET ?",
            (lost["ride_ordinal"] - 1,)).fetchone()
        streams = {s["type"]: s["data"] for s in json.loads(sj)}
        ll, times = np.asarray(streams["latlng"], dtype=float), np.asarray(streams["time"], dtype=float)
        minx, miny, maxx, maxy = current.corridor.bounds
        idx = np.flatnonzero((ll[:, 1] >= minx - .01) & (ll[:, 1] <= maxx + .01)
                            & (ll[:, 0] >= miny - .01) & (ll[:, 0] <= maxy + .01))
        lo, hi = max(0, int(idx[0]) - 1), min(len(times), int(idx[-1]) + 2)
        raw = [{"t": float(times[i]), "lat": float(ll[i, 0]), "lon": float(ll[i, 1]),
                "source_index": i} for i in range(lo, hi)]
        item = {k: lost[k] for k in ("name", "registry_id", "ride_ordinal", "start_s", "finish_s")}
        item["previous_finish_gate_wkt"] = source["gate_end_wkt"]
        item["current_finish_gate_wkt"] = next(
            c for c in read(args.proposed)["candidates"] if c["candidate_fingerprint"] == current.candidate_fingerprint
        )["gate_end_wkt"]
        for phase, runtime in (("previous_proposal", old), ("current_proposal", current)):
            evaluated = CanonTraversalEngine().evaluate(
                activity_id=uuid5(NAMESPACE_URL, f"offline-corpus:{aid}"), wallet="offline",
                candidates=[runtime], raw_samples=raw)
            selected = [a for a in evaluated.attempts if a.start and abs(a.start.time_s - lost["start_s"]) < .01]
            assert selected, (phase, lost["name"], lost["ride_ordinal"])
            item[phase] = [{
                "start": a.start.to_trace(), "finish": a.finish.to_trace() if a.finish else None,
                "accepted": a.accepted, "rejection_code": a.rejection_code,
                "coverage_ratio": a.coverage_ratio, "max_backtrack_m": a.max_backtrack_m,
            } for a in selected]
        accepted = next(a for a in item["previous_proposal"] if a["accepted"])
        assert abs(accepted["finish"]["time_s_raw"] - lost["finish_s"]) < 1e-5
        assert not any(a["accepted"] for a in item["current_proposal"])
        diagnostics.append(item)
    connection.close()
    return {
        "source_commit": commit, "evidence_class": "local_read_only_previous_proposal_comparison",
        "previous_accepted_traversals": len(old_efforts), "current_accepted_traversals": len(current_efforts),
        "lost_traversals": diagnostics,
        "new_traversals": [{k: e[k] for k in ("name", "registry_id", "ride_ordinal", "start_s", "finish_s")}
                           for e in newly_accepted],
    }


def replay_ride(record):
    """One ride, unchanged engine calls; results are gathered in corpus order."""
    import numpy as np
    from shapely.geometry import LineString
    from app.services.canon_traversal import CanonTraversalEngine
    import canon_traversal_replay as cr
    import corpus_stops as stops
    rows, candidates, stop_climbs = _REPLAY_INPUTS
    ordinal, aid, sj = record
    observations = {p: [] for p in REPLAY_PHASES}
    efforts = {p: [] for p in REPLAY_PHASES}
    attempts = {p: [] for p in REPLAY_PHASES}
    rejection_counts = {p: Counter() for p in REPLAY_PHASES}
    evaluated_pairs = 0
    engine = CanonTraversalEngine()
    streams = {s["type"]: s["data"] for s in json.loads(sj)}
    if "latlng" not in streams or "time" not in streams or "distance" not in streams:
        raise AssertionError(f"Missing required streams at ordinal {ordinal}")
    ll, times, dist = (np.asarray(streams[k], dtype=float) for k in ("latlng", "time", "distance"))
    for r in rows:
        rid = r["id"]
        old_candidate = candidates["before"][rid]
        minx, miny, maxx, maxy = old_candidate.runtime.corridor.bounds
        idx = np.flatnonzero((ll[:, 1] >= minx - .01) & (ll[:, 1] <= maxx + .01)
                            & (ll[:, 0] >= miny - .01) & (ll[:, 0] <= maxy + .01))
        if len(idx) < 2:
            continue
        lo, hi = max(0, int(idx[0]) - 1), min(len(times), int(idx[-1]) + 2)
        # Reuse Claude's buffered prefilter; avoid projection discrepancies
        # around start-gate endpoints in the geographic screening geometry.
        if not LineString([(p[1], p[0]) for p in ll[lo:hi]]).intersects(
                old_candidate.runtime.gate_start.buffer(0.0005)):
            continue
        evaluated_pairs += 1
        raw = [{"t": float(times[i]), "lat": float(ll[i, 0]), "lon": float(ll[i, 1]),
                "source_index": i} for i in range(lo, hi)]
        for phase in REPLAY_PHASES:
            if rid not in candidates[phase]:
                continue
            candidate = candidates[phase][rid]
            evaluation = engine.evaluate(
                activity_id=uuid5(NAMESPACE_URL, f"offline-corpus:{aid}"), wallet="offline",
                candidates=[candidate.runtime], raw_samples=raw)
            rejection_counts[phase].update(evaluation.rejections)
            for a in evaluation.attempts:
                attempts[phase].append({
                    "ride_ordinal": ordinal, "registry_id": rid,
                    "start": a.start.to_trace() if a.start else None,
                    "finish": a.finish.to_trace() if a.finish else None,
                    "accepted": a.accepted, "rejection_code": a.rejection_code,
                    "coverage_ratio": a.coverage_ratio, "max_backtrack_m": a.max_backtrack_m,
                })
            for p in evaluation.climb_patterns:
                crossing = p.match_trace["gate_crossings"]
                # Preserve old bracket progress solely for explicitly legacy
                # diagnostics; the corrected scorer reprojects the intersections.
                obs = cr.observed_pass_from_pattern(str(aid), candidate, p, raw,
                                                    legacy_clipped_projection=True)
                observations[phase].append(obs)
                climb = stop_climbs[phase][rid]
                xy = climb.xy(ll[:, 1], ll[:, 0])
                mid = np.flatnonzero((times > obs.start_s) & (times < obs.end_s))
                along, _ = climb.locate(xy[mid])
                analysis = stops.analyse_stops(climb, aid, None, times, dist, xy, None, None,
                                              obs.start_s, obs.end_s, mid, along)
                efforts[phase].append({
                    "ride_ordinal": ordinal, "registry_id": rid, "name": r["display_name"],
                    "start_s": obs.start_s, "finish_s": obs.end_s,
                    "elapsed_s": obs.end_s - obs.start_s,
                    "whole_seconds": p.match_trace["duration_s_whole"],
                    "start_crossing": crossing["start"], "finish_crossing": crossing["finish"],
                    "last_100m_stops": [s for s in analysis["stops"] if s["where"] == "last100"],
                })
    return ordinal, str(aid), evaluated_pairs, observations, efforts, rejection_counts, attempts


def replay(args, rows, before, after, moved, hashes):
    from shapely import wkb, wkt
    from app.models.canon import CanonClimb
    sys.path.insert(0, str(args.metric_module.parent))
    import canon_traversal_replay as cr
    assert Path(cr.__file__).resolve() == args.metric_module.resolve()

    sys.path.insert(0, str(args.research / "scripts"))
    import corpus_stops as stops

    moved_ids = {c["registry_id"] for c in moved}
    old_by_fp = {c["candidate_fingerprint"]: c for c in before["candidates"]}
    after_by_old = {c["provenance"].get("finish_gate_rule", {}).get("predecessor_fingerprint",
                   c["candidate_fingerprint"]): c for c in after["candidates"]}
    round2_by_old = {c["provenance"].get("finish_gate_rule", {}).get("predecessor_fingerprint",
                     c["candidate_fingerprint"]): c for c in read(args.previous_round_report)["candidates"]}
    candidates, stop_climbs = {}, {}
    for phase in REPLAY_PHASES:
        candidates[phase], stop_climbs[phase] = {}, {}
        for r in rows:
            if phase == "round2" and r["display_name"] not in ROUND3_NAMES:
                continue
            c = {"before": old_by_fp, "after": after_by_old, "round2": round2_by_old}[phase][r["candidate_fingerprint"]]
            geometry = wkb.loads(bytes.fromhex(r["centerline_geom"]))
            corridor = wkb.loads(bytes.fromhex(r["corridor_geom"]))
            runtime = CanonClimb(
                registry_id=UUID(r["id"]), canon_id=UUID(r["canon_id"]), version=r["version"],
                display_name=r["display_name"], route_name=r.get("route_name"), centerline=geometry,
                corridor=corridor, gate_start=wkb.loads(bytes.fromhex(r["gate_start_line"])),
                gate_end=wkb.loads(bytes.fromhex(r["gate_end_line"])), canonical_profile=tuple(r["canonical_profile"]),
                length_m=r["length_m"], vert_m=r["vert_m"], avg_gradient_pct=r["avg_gradient_pct"],
                compiler_version=r["compiler_version"], profile_hash_algorithm="blake3_canonical_profile_v1",
                profile_hash=r["provenance"]["canonical_profile_hash"]["value"], odbl_source=r["odbl_source"],
                corridor_tile_ids=(), candidate_fingerprint=c["candidate_fingerprint"], provenance=c["provenance"])
            sr = copy.deepcopy(r)
            if phase != "before" and r["id"] in moved_ids:
                runtime = replace(runtime, version=r["version"] + 1,
                    centerline=wkt.loads(c["centerline_wkt"]), gate_end=wkt.loads(c["gate_end_wkt"]),
                    canonical_profile=tuple(c["canonical_profile"]), length_m=c["length_m"], vert_m=c["vert_m"],
                    avg_gradient_pct=c["avg_gradient_pct"], compiler_version=c["compiler_version"],
                    profile_hash=c["provenance"]["canonical_profile_hash"]["value"])
                sr.update(centerline_geom=runtime.centerline.wkb_hex, gate_end_line=runtime.gate_end.wkb_hex)
            _, projected, forward = cr._exact_metric_corridor(runtime.centerline, c["corridor_half_width_m"])
            candidates[phase][r["id"]] = cr.RatifiedCandidate(
                r["id"], c["candidate_fingerprint"], r["display_name"], runtime, corridor, projected, forward)
            stop_climbs[phase][r["id"]] = stops.Climb(sr)
    con = sqlite3.connect(args.corpus.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    checkpoint_inputs = {k: v["sha256"] for k, v in hashes.items()}
    checkpoint_inputs.update(scan_model="gate_rule_fix3_all_rides_corrected_timing_v4",
                             before=hashes["hydrated_before"]["sha256"],
                             after=hashes["admitted_after"]["sha256"])
    if args.checkpoint and args.checkpoint.exists():
        cached = read(args.checkpoint)
        assert cached["inputs"] == checkpoint_inputs, "Checkpoint input mismatch"
        templates = [cr.ReferenceTemplate(**x) for x in cached["templates"]]
        expected = [cr.ExpectedPass(**x) for x in cached["expected"]]
        template_counts = cached["template_counts"]
        observations = {p: [cr.ObservedPass(**x) for x in cached["observations"][p]] for p in REPLAY_PHASES}
        efforts, rejection_counts = cached["efforts"], cached["rejection_counts"]
        attempts = cached["attempts"]
        ride_ordinals, evaluated_pairs = cached["ride_ordinals"], cached["evaluated_pairs"]
        print(f"Loaded private checkpoint: {len(ride_ordinals)} rides", flush=True)
    else:
        templates, template_counts = cr.map_reference_templates(con, list(candidates["before"].values()))
        expected = cr.load_expected_passes(con, templates)  # Freeze before after outcomes.
        observations = {p: [] for p in REPLAY_PHASES}
        efforts = {p: [] for p in REPLAY_PHASES}
        attempts = {p: [] for p in REPLAY_PHASES}
        rejection_counts = {p: Counter() for p in REPLAY_PHASES}
        ride_ordinals, evaluated_pairs = {}, 0
        records = ((ordinal, aid, sj) for ordinal, (aid, sj) in enumerate(con.execute(
            "SELECT activity_id, streams_json FROM activity_streams ORDER BY CAST(activity_id AS INTEGER)"), 1))
        with ProcessPoolExecutor(max_workers=args.workers, mp_context=multiprocessing.get_context("spawn"),
                initializer=replay_worker_inputs, initargs=(rows, candidates, stop_climbs)) as pool:
            for ordinal, aid, pairs, obs, effort, rejected, attempted in pool.map(replay_ride, records, chunksize=4):
                ride_ordinals[aid] = ordinal
                evaluated_pairs += pairs
                for phase in REPLAY_PHASES:
                    observations[phase].extend(obs[phase])
                    efforts[phase].extend(effort[phase])
                    attempts[phase].extend(attempted[phase])
                    rejection_counts[phase].update(rejected[phase])
                if ordinal % 100 == 0:
                    print(f"Replayed {ordinal} rides; accepted {len(efforts['before'])}/{len(efforts['after'])}", flush=True)
        if args.checkpoint:
            # This private scratch file contains source IDs and crossing coordinates.
            # It is never part of the review pack or committed output.
            cached = {"inputs": checkpoint_inputs, "templates": [asdict(x) for x in templates],
                      "expected": [asdict(x) for x in expected], "template_counts": template_counts,
                      "observations": {p: [asdict(x) for x in observations[p]] for p in REPLAY_PHASES},
                      "efforts": efforts, "rejection_counts": rejection_counts, "attempts": attempts,
                      "ride_ordinals": ride_ordinals, "evaluated_pairs": evaluated_pairs}
            with os.fdopen(os.open(args.checkpoint, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as handle:
                json.dump(cached, handle, allow_nan=False)
    con.close()
    assert digest(args.corpus) == hashes["corpus"]["sha256"], "Corpus changed during replay"
    scores = {}
    source_hashes = {k: v["sha256"] for k, v in hashes.items()}
    for phase in ("before", "after"):
        phase_hashes = {
            "corpus_sha256": source_hashes["corpus"],
            "canon_report_sha256": hashes["hydrated_before" if phase == "before" else "admitted_after"]["sha256"],
            # Approval amendments bind the current review; all source hashes
            # remain in INPUTS.json. The helper requires exactly these three keys.
            "review_labels_sha256": hashes["placement_approvals"]["sha256"],
        }
        boundary = cr.boundary_repeat_metrics(observations[phase], list(candidates[phase].values()),
                                             source_hashes=phase_hashes, legacy_clipped_projection=True)
        moved_boundary = cr.boundary_repeat_metrics(
            [o for o in observations[phase] if o.decision_id in moved_ids],
            [c for rid, c in candidates[phase].items() if rid in moved_ids], source_hashes=phase_hashes, legacy_clipped_projection=True)
        per_climb = {
            r["id"]: {"name": r["display_name"], "moved": r["id"] in moved_ids,
                      "boundary_agreement": cr.boundary_repeat_metrics(
                          [o for o in observations[phase] if o.decision_id == r["id"]],
                          [candidates[phase][r["id"]]], source_hashes=phase_hashes, legacy_clipped_projection=True)}
            for r in rows
        }
        unmatched = []
        used = set()
        for ref in expected:
            matches = [(i, o) for i, o in enumerate(observations[phase])
                       if i not in used and o.activity_id == ref.activity_id and o.decision_id == ref.decision_id
                       and cr.reference_contains_observed(ref.start_s, ref.end_s, o.start_s, o.end_s)]
            if matches:
                used.add(matches[0][0])
            else:
                unmatched.append({"ride_ordinal": ride_ordinals[ref.activity_id], "registry_id": ref.decision_id,
                                  "reference_start_s": ref.start_s, "reference_finish_s": ref.end_s})
        selected = [e for e in efforts[phase] if e["registry_id"] in moved_ids]
        scores[phase] = {
            "accepted_traversals": len(efforts[phase]), "boundary_agreement": boundary,
            "corrected_boundary_agreement": cr.boundary_repeat_metrics(
                observations[phase], list(candidates[phase].values()), source_hashes=phase_hashes),
            "timing_agreement": cr.timing_agreement_metrics(
                observations[phase], list(candidates[phase].values()), source_hashes=phase_hashes),
            "moved_set_boundary_agreement": moved_boundary, "per_climb": per_climb,
            "legacy_moved_set_10m_pass": (moved_boundary["_p95_error_m_raw"] is not None
                                             and moved_boundary["_p95_error_m_raw"] <= 10),
            "legacy_overall_10m_pass": boundary["_p95_error_m_raw"] is not None and boundary["_p95_error_m_raw"] <= 10,
            "frozen_reference_expected": len(expected), "reference_matches": len(expected) - len(unmatched),
            "reference_recall": (len(expected) - len(unmatched)) / len(expected),
            "reference_misses": unmatched, "moved_climb_efforts": len(selected),
            "moved_climb_last100_stopped_efforts": sum(bool(e["last_100m_stops"]) for e in selected),
            "moved_climb_last100_stop_rate": sum(bool(e["last_100m_stops"]) for e in selected) / len(selected),
            "rejections": dict(rejection_counts[phase]),
        }
    remaining = list(efforts["after"])
    changes, lost = [], []
    for old in efforts["before"]:
        match = next((e for e in remaining if e["registry_id"] == old["registry_id"]
                      and e["ride_ordinal"] == old["ride_ordinal"] and abs(e["start_s"] - old["start_s"]) < .01), None)
        if match is None:
            lost.append({**old, "after_attempts": [
                a for a in attempts["after"] if a["registry_id"] == old["registry_id"]
                and a["ride_ordinal"] == old["ride_ordinal"] and a["start"]
                and abs(a["start"]["time_s_raw"] - old["start_s"]) < .01]})
        else:
            remaining.remove(match)
            changes.append({"ride_ordinal": old["ride_ordinal"], "registry_id": old["registry_id"], "name": old["name"],
                            "start_s": old["start_s"], "before_elapsed_s": old["elapsed_s"],
                            "after_elapsed_s": match["elapsed_s"], "delta_seconds": match["elapsed_s"] - old["elapsed_s"],
                            "before_whole_seconds": old["whole_seconds"], "after_whole_seconds": match["whole_seconds"],
                            "before_last100_stops": old["last_100m_stops"], "after_last100_stops": match["last_100m_stops"]})
    result = {
        "evidence_class": "local_offline_read_only_corpus",
        "publication_scorecard": {"status": "local_boundary_and_timing_measured_other_gates_remain",
            "authority": "history/codex-briefs-2026-10-20/gate-rule-fix-3.md",
            "metrics_commit": METRICS_COMMIT, "metrics_sha256": METRICS_SHA256,
            "note": "Corrected boundary and timing use the pinned gate-consistency definitions; legacy pooled diagnostics are not publication acceptance. Field checks and remaining cutover gates still apply."},
        "corridor_policy": "Retained exact September PostGIS corridors in both phases; only admitted spans/profiles/finishes change.",
        "note": "This isolates finish movement; it does not claim newly published PostGIS successor-corridor evidence.",
        "rides_scanned": len(ride_ordinals), "evaluated_ride_climb_pairs": evaluated_pairs,
        "frozen_template_mapping": template_counts, "template_count": len(templates),
        "before": scores["before"], "after": scores["after"],
        "round3": round3_comparison(rows, candidates, observations, efforts, hashes, cr),
        "baseline_retention": len(changes) / len(efforts["before"]),
        "lost_traversals": lost, "new_traversals": remaining, "effort_changes": changes,
        "previous_proposal_comparison": previous_proposal_comparison(args, rows, candidates, efforts["after"]),
        "black_rock_start_revision_evidence": [
            {"ride_ordinal": e["ride_ordinal"], "start_s": e["start_s"],
             "start_offset_from_centre_m": abs(e["start_crossing"]["direction_evidence"]["gate_position_m"]
                                               - e["start_crossing"]["direction_evidence"]["gate_length_m"] / 2),
             "start_crossing": e["start_crossing"]}
            for e in efforts["after"] if e["name"] == "Black Rock Road"
            and abs(e["start_crossing"]["direction_evidence"]["gate_position_m"]
                    - e["start_crossing"]["direction_evidence"]["gate_length_m"] / 2) > 25
        ],
        "corpus_sha256_unchanged": source_hashes["corpus"],
    }
    write(args.output / "REPLAY.json", result, compact=True)
    replay_markdown(args.output, result, moved)
    print(json.dumps({k: {n: v for n, v in scores[k].items()
                         if n not in ("boundary_agreement", "moved_set_boundary_agreement", "per_climb",
                                      "corrected_boundary_agreement", "timing_agreement",
                                      "reference_misses", "rejections")} for k in scores}), flush=True)
    return result


def round3_comparison(rows, candidates, observations, efforts, hashes, cr):
    """Rescore both approved shifts against their exact round-2 geometries."""
    from pyproj import Transformer
    from shapely.geometry import LineString, Point
    from shapely.ops import transform

    result = {"source_commit": subprocess.check_output(["git", "rev-parse", ROUND2_COMMIT], cwd=ROOT, text=True).strip(),
              "metrics_commit": METRICS_COMMIT, "metrics_sha256": METRICS_SHA256,
              "evidence_class": "local_read_only_corpus_and_published_aggregate_spots",
              "boundary_threshold_m": 10.0, "timing_threshold_s": 2.0, "climbs": []}
    for row in rows:
        if row["display_name"] not in ROUND3_NAMES:
            continue
        rid = row["id"]
        item = {"name": row["display_name"], "registry_id": rid}
        for phase in REPLAY_PHASES:
            obs = [o for o in observations[phase] if o.decision_id == rid]
            accepted = [e for e in efforts[phase] if e["registry_id"] == rid]
            inputs = {"corpus_sha256": hashes["corpus"]["sha256"],
                      "canon_report_sha256": hashes[{"before": "hydrated_before", "after": "admitted_after",
                                                     "round2": "round2_admitted_after"}[phase]]["sha256"],
                      "review_labels_sha256": hashes["placement_approvals"]["sha256"]}
            selected = [candidates[phase][rid]]
            boundary = cr.boundary_repeat_metrics(obs, selected, source_hashes=inputs)
            timing = cr.timing_agreement_metrics(obs, selected, source_hashes=inputs)
            item[phase] = {"accepted_traversals": len(accepted),
                           "last100_stopped_efforts": sum(bool(e["last_100m_stops"]) for e in accepted),
                           "last100_stop_events": sum(len(e["last_100m_stops"]) for e in accepted),
                           "corrected_boundary": boundary, "timing_agreement": timing}
        remaining = [e for e in efforts["after"] if e["registry_id"] == rid]
        changes, lost = [], []
        for previous in (e for e in efforts["round2"] if e["registry_id"] == rid):
            current = next((e for e in remaining if e["ride_ordinal"] == previous["ride_ordinal"]
                            and abs(e["start_s"] - previous["start_s"]) < .01), None)
            if current is None:
                lost.append(previous)
                continue
            remaining.remove(current)
            changes.append({"ride_ordinal": previous["ride_ordinal"], "start_s": previous["start_s"],
                            "round2_elapsed_s": previous["elapsed_s"], "after_elapsed_s": current["elapsed_s"],
                            "delta_seconds": current["elapsed_s"] - previous["elapsed_s"],
                            "round2_whole_seconds": previous["whole_seconds"], "after_whole_seconds": current["whole_seconds"],
                            "round2_last100_stops": previous["last_100m_stops"], "after_last100_stops": current["last_100m_stops"]})
        item.update(effort_changes=changes, lost_traversals=lost, new_traversals=remaining)
        current = candidates["after"][rid].runtime
        prior = candidates["round2"][rid].runtime
        rule = current.provenance["finish_gate_rule"]
        amendment = rule["stop_evidence_amendment"]
        spot = amendment["spot"]["position"]
        source = rule["predecessor_profile_points"]
        # An independent metric projection checks the actual serialized gate,
        # not the rounded length or the unrounded intended cut.
        project = Transformer.from_crs("EPSG:4326", "EPSG:32618", always_xy=True).transform
        line = transform(project, LineString([(p["lon"], p["lat"]) for p in source]))
        position = Point(spot["lon"], spot["lat"])
        clearance = line.project(transform(project, position)) - line.project(transform(project, current.gate_end.centroid))
        assert clearance >= 15.0, (row["display_name"], clearance)
        approved = rule["founder_approval"]["approved_position"]
        displacement = transform(project, current.gate_end.centroid).distance(
            Point(*project(approved["lon"], approved["lat"])))
        assert displacement <= .5, (row["display_name"], displacement)
        item["geometry"] = {"approved_setback_m": amendment["requested_setback_m"],
                            "round2_setback_m": prior.provenance["finish_gate_rule"]["setback_from_junction_m"],
                            "emitted_setback_m": rule["setback_from_junction_m"],
                            "additional_shift_m": rule["setback_from_junction_m"] - prior.provenance["finish_gate_rule"]["setback_from_junction_m"],
                            "native_stop_clearance_m": rule["observed_stop_clearance_m"],
                            "serialized_gate_stop_clearance_utm18n_m": clearance,
                            "serialized_gate_approved_position_offset_m": displacement,
                            "published_aggregate_spot": amendment["spot"], "stop_map_source": amendment["source"],
                            "note": "Clearance from the published five-decimal aggregate, not surveyed paint. No M1 snap or >0.5 m covering note was needed."}
        result["climbs"].append(item)
    return result


def round3_markdown(result):
    def number(value):
        return "absent" if value is None else f"{value:.3f}"
    lines = ["", "## Round 3: Wises Mill and Centennial", "",
             "Fresh replay compares the two amended finishes with their exact round-2 predecessors. "
             "The registry baseline is also retained in REPLAY.json. The corrected boundary metric projects each "
             "actual intersection onto the centreline and uses every crossing in groups with at least two distinct rides. "
             "Timing thins 1 s brackets to every eighth sample across all eight offsets; recording pauses and edges "
             "are counted but unscored, and lost/ambiguous crossings remain in p95 as infinity. "
             "The full-population timing p95 is used, never the measured-only diagnostic.", "",
             f"Definitions: gate-consistency `{result['metrics_commit']}`; SHA-256 `{result['metrics_sha256']}`. "
             "Neither lane nor the traversal engine was edited. Thresholds: corrected boundary p95 ≤10 m; timing p95 ≤2 s. "
             "These local metrics do not replace field checks or other cutover gates.", "",
             "| Climb | Accepted round 2 → 3 | Last-100 m stopped efforts | Extra shift m | Native / serialized UTM stop clearance m |",
             "|---|---:|---:|---:|---:|"]
    for c in result["climbs"]:
        b, a, g = c["round2"], c["after"], c["geometry"]
        lines.append(f"| {c['name']} | {b['accepted_traversals']} → {a['accepted_traversals']} | "
                     f"{b['last100_stopped_efforts']} → {a['last100_stopped_efforts']} | {g['additional_shift_m']:.3f} | "
                     f"{g['native_stop_clearance_m']:.3f} / {g['serialized_gate_stop_clearance_utm18n_m']:.3f} |")
    lines += ["", "| Climb, both gates pooled | Corrected boundary p95 m, round 2 → 3 | Timing p95 s, round 2 → 3 |",
              "|---|---:|---:|"]
    for c in result["climbs"]:
        b, a = c["round2"], c["after"]
        lines.append(f"| {c['name']} | {number(b['corrected_boundary']['p95_error_m'])} → "
                     f"{number(a['corrected_boundary']['p95_error_m'])} | "
                     f"{number(b['timing_agreement']['p95_error_s'])} → {number(a['timing_agreement']['p95_error_s'])} |")
    lines += ["", "| Climb / gate | Corrected boundary p95 m, round 2 → 3 | Timing p95 s, round 2 → 3 | "
              "Round 3 measured / failed / pause offsets |", "|---|---:|---:|---:|"]
    for c in result["climbs"]:
        for gate in ("start", "finish"):
            boundaries = [next((g for g in c[p]["corrected_boundary"]["groups"] if g["gate"] == gate), None)
                          for p in ("round2", "after")]
            timings = [next(g for g in c[p]["timing_agreement"]["groups"] if g["gate"] == gate)
                       for p in ("round2", "after")]
            b = [number(g["p95_error_m"]) if g else "ineligible" for g in boundaries]
            t = [("unbounded" if g["p95_unbounded"] else number(g["p95_error_s"])) if g["eligible"] else "ineligible" for g in timings]
            a = timings[1]
            lines.append(f"| {c['name']} / {gate} | {' → '.join(b)} | {' → '.join(t)} | "
                         f"{a['measured_offsets']} / {a['unmeasurable_offsets']} / {a['pause_guarded_offsets']} |")
    for c in result["climbs"]:
        lines += ["", f"### {c['name']}: every paired effort", "",
                  f"{len(c['lost_traversals'])} losses; {len(c['new_traversals'])} newly accepted. "
                  "Negative deltas mean shorter elapsed time. Ordinals refer only to this frozen corpus.", "",
                  "| Ride ordinal | Start s | Round 2 elapsed s | Round 3 elapsed s | Delta s | Whole seconds round 2 → 3 |",
                  "|---:|---:|---:|---:|---:|---:|"]
        for e in c["effort_changes"]:
            lines.append(f"| {e['ride_ordinal']} | {e['start_s']:.3f} | {e['round2_elapsed_s']:.6f} | "
                         f"{e['after_elapsed_s']:.6f} | {e['delta_seconds']:.6f} | "
                         f"{e['round2_whole_seconds']} → {e['after_whole_seconds']} |")
    lines.append("")
    return lines


def replay_markdown(output, result, moved):
    before, after = result["before"], result["after"]
    lines = [
        "# Read-only corpus replay", "",
        "Local/offline evidence from the repo's unchanged CanonTraversalEngine. "
        "The same retained September PostGIS corridors are used before and after; "
        "only the admitted 15 finishes, spans and profiles change.", "",
        f"Scanned **{result['rides_scanned']:,} rides**, evaluating "
        f"**{result['evaluated_ride_climb_pairs']:,}** ride/climb pairs after a conservative "
        "bounding-box and buffered unchanged-start intersection prefilter (Claude's review method).", "",
        "| Metric | Before | After |", "|---|---:|---:|",
        f"| Accepted traversals | {before['accepted_traversals']} | {after['accepted_traversals']} |",
        f"| Frozen segment-template reference recall | "
        f"{before['reference_matches']}/{before['frozen_reference_expected']} "
        f"({before['reference_recall']:.2%}) | "
        f"{after['reference_matches']}/{after['frozen_reference_expected']} "
        f"({after['reference_recall']:.2%}) |",
        f"| Corrected D13 pooled boundary p95 | {before['corrected_boundary_agreement']['p95_error_m']:.3f} m | "
        f"{after['corrected_boundary_agreement']['p95_error_m']:.3f} m |",
        f"| Full-population pooled timing p95 | {before['timing_agreement']['p95_error_s']:.3f} s | "
        f"{after['timing_agreement']['p95_error_s']:.3f} s |",
        f"| Legacy D13 pooled repeat-boundary p95 | {before['boundary_agreement']['p95_error_m']:.3f} m | "
        f"{after['boundary_agreement']['p95_error_m']:.3f} m |",
        f"| Legacy D13 moved-set pooled p95 | {before['moved_set_boundary_agreement']['p95_error_m']:.3f} m | "
        f"{after['moved_set_boundary_agreement']['p95_error_m']:.3f} m |",
        f"| Moved-climb last-100 m stopped efforts | "
        f"{before['moved_climb_last100_stopped_efforts']}/{before['moved_climb_efforts']} "
        f"({before['moved_climb_last100_stop_rate']:.2%}) | "
        f"{after['moved_climb_last100_stopped_efforts']}/{after['moved_climb_efforts']} "
        f"({after['moved_climb_last100_stop_rate']:.2%}) |", "",
        "**Corrected boundary and timing metrics are measured locally using the pinned "
        "gate-consistency definitions. Current full-corpus pooled boundary: "
        + ("passes" if after['corrected_boundary_agreement']['_p95_error_m_raw'] is not None
           and after['corrected_boundary_agreement']['_p95_error_m_raw'] <= 10 else "does not pass")
        + "; pooled timing: "
        + ("passes" if after['timing_agreement']['p95_error_s'] is not None
           and after['timing_agreement']['p95_error_s'] <= 2 else "does not pass")
        + ". Other publication gates still apply.** The historical overall 10 m check "
        + ("passes" if all(result[p]["legacy_overall_10m_pass"] for p in ("before", "after")) else "fails")
        + "; it is retained as a legacy diagnostic, not the current publication bar. "
        "See [fix round 2 authority](../../codex-briefs-2026-10-20/gate-rule-fix-2.md).", "",
        f"Baseline traversal retention: **{result['baseline_retention']:.2%}**. "
        f"**{len(result['lost_traversals'])} lost**, **{len(result['new_traversals'])} newly accepted**. "
        "Every paired effort's fractional and whole-second change, each lost/new effort, "
        "and every frozen-reference miss is retained in [REPLAY.json](REPLAY.json). "
        "Ride ordinals replace source activity identifiers; no raw rider coordinates are emitted.", "",
        "## Method", "",
        "Reference templates are mapped once on the before geometry with the existing "
        "`map_reference_templates` and `load_expected_passes` helpers. Their denominator is "
        "frozen before scoring the after geometry. Matching is one-to-one using the existing "
        "`reference_contains_observed` predicate. This measures agreement with independently "
        "mappable recorded segment efforts; it is separate from retention of baseline canon traversals.", "",
        "The legacy D13 diagnostic uses `boundary_repeat_metrics`, preserving every accepted observation. A climb/gate "
        "group is eligible only with at least two distinct rides. Error is bracket-interpolated "
        "canonical progress relative to the group median, pooled at p95, with its former 10 m comparison retained. "
        "It interpolates clipped bracketing-sample centreline projections; corrected scoring projects "
        "the intersection itself. Neither measures physical surveyed accuracy.", "",
        "Stop classification reuses the research's unmodified `corpus_stops.analyse_stops`: "
        "speed below 1 m/s for at least 3 seconds within the timed interval, located in that "
        "phase's last 100 m. No stop time is subtracted. The brief's approximate 17% came from "
        "a different research traversal set; use the measured before denominator above for this comparison.", "",
        "## Admitted climbs", "",
        "| Climb | Accepted before → after | Last-100 m stopped before → after | "
        "Paired efforts | Median elapsed reduction |", "|---|---:|---:|---:|---:|",
    ]
    for climb in moved:
        rid = climb["registry_id"]
        paired = [e for e in result["effort_changes"] if e["registry_id"] == rid]
        lost = [e for e in result["lost_traversals"] if e["registry_id"] == rid]
        new = [e for e in result["new_traversals"] if e["registry_id"] == rid]
        bstop = sum(bool(e["before_last100_stops"]) for e in paired) + sum(bool(e["last_100m_stops"]) for e in lost)
        astop = sum(bool(e["after_last100_stops"]) for e in paired) + sum(bool(e["last_100m_stops"]) for e in new)
        reduction = f"{statistics.median(-e['delta_seconds'] for e in paired):.2f} s" if paired else "no paired efforts"
        lines.append(f"| {climb['name']} | {len(paired) + len(lost)} → {len(paired) + len(new)} | "
                     f"{bstop} → {astop} | {len(paired)} | {reduction} |")
    lines += ["", "## Legacy D13 per climb", "",
              "No eligible repeats means absent p95, not zero. Duplicate road names remain separate registry identities.",
              "", "| Climb (registry prefix) | p95 before m | p95 after m | Eligible endpoints before / after |",
              "|---|---:|---:|---:|"]
    for rid, item in before["per_climb"].items():
        b, a = item["boundary_agreement"], after["per_climb"][rid]["boundary_agreement"]
        def metric(x):
            return "no eligible repeats" if x is None else f"{x:.3f}"
        lines.append(f"| {item['name']} ({rid[:8]}) | {metric(b['p95_error_m'])} | "
                     f"{metric(a['p95_error_m'])} | {b['repeat_endpoints']} / "
                     f"{a['repeat_endpoints']} |")
    comparison = result["previous_proposal_comparison"]
    lines += ["", "## Black Rock start revision", "",
              "The unchanged 30 m start half-extent is active and re-evidenced under Claude's D10 call "
              "in fix round 2. The finish remains 25 m. Accepted starts outside the default 25 m extent:", ""]
    for effort in result["black_rock_start_revision_evidence"]:
        lines.append(f"- Ride ordinal {effort['ride_ordinal']}, start {effort['start_s']:.3f} s: "
                     f"{effort['start_offset_from_centre_m']:.3f} m from the start-gate centre.")
    lines += ["", "## Compared with the previous proposal", "",
              f"Commit `{comparison['source_commit'][:9]}` had {comparison['previous_accepted_traversals']} "
              f"accepted traversals; the current proposal has {comparison['current_accepted_traversals']}. "
              f"{len(comparison['lost_traversals'])} prior-proposal effort(s) no longer qualify. "
              "This comparison is separate from retention of the 425 registry-baseline traversals.", ""]
    for lost in comparison["lost_traversals"]:
        before_attempt = next(a for a in lost["previous_proposal"] if a["accepted"])
        gate = before_attempt["finish"]["direction_evidence"]
        offset = abs(gate["gate_position_m"] - gate["gate_length_m"] / 2)
        lines.append(f"- {lost['name']}, ride ordinal {lost['ride_ordinal']}: prior start "
                     f"{lost['start_s']:.3f} s, finish {lost['finish_s']:.3f} s. The prior finish "
                     f"crossing is {offset:.3f} m from the gate centre. Current attempt: "
                     + "; ".join(str(a["rejection_code"]) + ("; no finish crossing" if not a["finish"] else "")
                                 for a in lost["current_proposal"]) + ".")
    lines += ["", "Each loss was re-evaluated using both exact proposal geometries. Sanitized "
              "crossing times, bracket indices, gate positions/lengths and rejection reasons are in REPLAY.json.", ""]
    lines += ["", "The original corpus passed SQLite integrity checking and its SHA-256 "
              f"remained `{result['corpus_sha256_unchanged']}`. No database/provider/chain writes occurred.", ""]
    lines += round3_markdown(result["round3"])
    (output / "REPLAY.md").write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "research", "source-report", "before", "proposed", "pbf", "corpus", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--metric-module", type=Path, required=True,
                        help="Unmodified canon_traversal_replay.py from the pinned gate-consistency commit")
    parser.add_argument("--previous-round-report", type=Path, required=True)
    parser.add_argument("--stop-map-results", type=Path, required=True)
    parser.add_argument("--skip-replay", action="store_true")
    parser.add_argument("--full-report", type=Path, required=True)
    parser.add_argument("--profiles", type=Path, required=True)
    parser.add_argument("--hydrate-only", action="store_true",
                        help="Write the 57 retained candidates plus verified full-precision source profiles")
    parser.add_argument("--previous-commit", default="b93e09ea4",
                        help="Prior reviewed proposal, used to account for Black Rock override losses")
    parser.add_argument("--workers", type=int, default=4, choices=range(1, 5))
    parser.add_argument("--checkpoint", type=Path,
                        help="Private temporary scan cache; contains source IDs/coordinates, never commit")
    args = parser.parse_args()
    if args.checkpoint and args.checkpoint.resolve().is_relative_to(ROOT):
        parser.error("Private replay checkpoints must be outside the worktree")
    args.output.mkdir(parents=True, exist_ok=True)
    if args.hydrate_only:
        hydrate_before(args)
        return
    rows, before, after, moved, hashes = prepare(args)
    if not args.skip_replay:
        replay(args, rows, before, after, moved, hashes)


if __name__ == "__main__":
    main()
