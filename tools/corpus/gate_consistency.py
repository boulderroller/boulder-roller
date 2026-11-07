"""Offline D13 research. Never changes compiler, traversal engine or registry.

Private input/checkpoint directories must be outside the checkout. Only the
explicit aggregate summary and bounded crossing-point PNGs may be committed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import sqlite3
import statistics
import sys
import textwrap
from uuid import UUID, NAMESPACE_URL, uuid5

import numpy as np
from shapely import wkb, wkt
from shapely.geometry import LineString, Point
from shapely.ops import substring, transform

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "backend"), str(ROOT / "tools/corpus")]


def legacy_progress(crossing):
    """Exactly the existing replay's interpolation of direction evidence."""
    return crossing.before_progress_m + crossing.interpolation_u * (
        crossing.after_progress_m - crossing.before_progress_m
    )


def crossing_progress(projected, crossing):
    """Project the observed intersection itself, in the engine's metric CRS."""
    xy = projected.forward.transform(crossing.lon, crossing.lat)
    return float(projected.centerline.project(Point(*xy)))


def p95(values):
    values = sorted(values)
    return values[max(0, math.ceil(.95 * len(values)) - 1)] if values else None


def spread(values):
    if not values:
        return {"n": 0, "p95_m": None, "max_m": None, "over_10m": 0}
    median = statistics.median(values)
    deviations = [abs(v - median) for v in values]
    return {"n": len(values), "median_m": median, "p95_m": p95(deviations),
            "max_m": max(deviations), "over_10m": sum(v > 10 for v in deviations)}


def metric(efforts, method):
    """All accepted observations, each gate eligible on >=2 distinct rides."""
    groups = defaultdict(list)
    for effort in efforts:
        for gate in ("start", "finish"):
            groups[(effort["climb"], gate)].append(
                (effort["ride"], effort[gate][method]))
    pool, rides, summaries, per_climb = [], set(), [], defaultdict(list)
    for (climb, gate), observations in sorted(groups.items()):
        distinct = {ride for ride, _ in observations}
        if len(distinct) < 2:
            continue
        values = [value for _, value in observations]
        med = statistics.median(values)
        deviations = [abs(value - med) for value in values]
        pool.extend(deviations)
        per_climb[climb].extend(deviations)
        rides.update(distinct)
        summaries.append({"climb": climb, "gate": gate, "rides": len(distinct),
                          **spread(values)})
    def summarize(deviations):
        return {"n": len(deviations), "p95_m": p95(deviations),
                "max_m": max(deviations) if deviations else None,
                "over_10m": sum(v > 10 for v in deviations)}
    return {**summarize(pool), "eligible_groups": len(summaries),
            "distinct_rides": len(rides), "groups": summaries,
            "per_climb": {c: summarize(d) for c, d in sorted(per_climb.items())}}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value, private=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if private and path.resolve().is_relative_to(ROOT):
        raise ValueError("Private observations must stay outside the checkout")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    with os.fdopen(os.open(path, flags, 0o600 if private else 0o644), "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def build_candidates(inputs):
    from app.models.canon import CanonClimb
    source = read(inputs / "INPUTS.json")
    rows = read(source["registry"]["path"])
    old = {c["candidate_fingerprint"]: c
           for c in read(inputs / "COMPILER-BEFORE.json")["candidates"]}
    new = {c["provenance"].get("finish_gate_rule", {}).get(
        "predecessor_fingerprint", c["candidate_fingerprint"]): c
        for c in read(inputs / "ADMITTED-AFTER.json")["candidates"]}
    phases = {"before": {}, "after": {}}
    moved = []
    for row in rows:
        rid, fp = row["id"], row["candidate_fingerprint"]
        before, after = old[fp], new[fp]
        base = CanonClimb(
            registry_id=UUID(rid), canon_id=UUID(row["canon_id"]), version=row["version"],
            display_name=row["display_name"], route_name=row.get("route_name"),
            centerline=wkb.loads(bytes.fromhex(row["centerline_geom"])),
            corridor=wkb.loads(bytes.fromhex(row["corridor_geom"])),
            gate_start=wkb.loads(bytes.fromhex(row["gate_start_line"])),
            gate_end=wkb.loads(bytes.fromhex(row["gate_end_line"])),
            canonical_profile=tuple(row["canonical_profile"]), length_m=row["length_m"],
            vert_m=row["vert_m"], avg_gradient_pct=row["avg_gradient_pct"],
            compiler_version=row["compiler_version"],
            profile_hash_algorithm="blake3_canonical_profile_v1",
            profile_hash=row["provenance"]["canonical_profile_hash"]["value"],
            odbl_source=row["odbl_source"], corridor_tile_ids=(),
            candidate_fingerprint=fp, provenance=before["provenance"])
        phases["before"][rid] = base
        changed = after["candidate_fingerprint"] != fp
        if changed:
            moved.append(rid)
            current = replace(
                base, version=base.version + 1,
                centerline=wkt.loads(after["centerline_wkt"]),
                gate_end=wkt.loads(after["gate_end_wkt"]),
                canonical_profile=tuple(after["canonical_profile"]),
                length_m=after["length_m"], vert_m=after["vert_m"],
                avg_gradient_pct=after["avg_gradient_pct"],
                compiler_version=after["compiler_version"],
                profile_hash=after["provenance"]["canonical_profile_hash"]["value"],
                candidate_fingerprint=after["candidate_fingerprint"],
                provenance=after["provenance"])
        else:
            current = base
        phases["after"][rid] = current
    assert len(rows) == 57 and len(moved) == 15
    return source, rows, phases, moved


def tolerance(candidate, gate_half_extent=40., corridor_half_width=35.):
    """D10-only counterfactual: unchanged centreline, anchor and orientation."""
    from app.services.canon_traversal import _project_candidate
    if not 25 <= gate_half_extent <= 40 or not 25 <= corridor_half_width <= 35:
        raise ValueError("Outside the ratified D10 bounds")
    p = _project_candidate(candidate)
    def widen(gate):
        a, b = np.asarray(gate.coords[0]), np.asarray(gate.coords[-1])
        midpoint, direction = (a + b) / 2, (b - a) / np.linalg.norm(b - a)
        return transform(p.inverse.transform, LineString([
            midpoint - gate_half_extent * direction,
            midpoint + gate_half_extent * direction]))
    return replace(candidate, gate_start=widen(p.gate_start), gate_end=widen(p.gate_end),
                   corridor=transform(p.inverse.transform,
                                      p.centerline.buffer(corridor_half_width)))


def boundary(candidate, start_inset=0., finish_inset=0.):
    """Research-only span trim: new version; never a publishable compiler row."""
    from app.services.canon_traversal import _project_candidate
    p = _project_candidate(candidate)
    end = p.centerline.length - finish_inset
    if start_inset < 0 or finish_inset < 0 or end <= start_inset:
        raise ValueError("Invalid retained span")
    line = substring(p.centerline, start_inset, end)
    def gate_at(distance, old_gate):
        anchor = p.centerline.interpolate(distance)
        a = p.centerline.interpolate(max(0, distance - .5))
        b = p.centerline.interpolate(min(p.centerline.length, distance + .5))
        dx, dy = b.x - a.x, b.y - a.y
        scale = old_gate.length / (2 * math.hypot(dx, dy))
        gate = LineString([(anchor.x - dy * scale, anchor.y + dx * scale),
                           (anchor.x + dy * scale, anchor.y - dx * scale)])
        return transform(p.inverse.transform, gate)
    # Profile interpolation keeps the research traversal's elevation coherent;
    # this is not an identity fingerprint/profile-hash generation path.
    profile = candidate.canonical_profile
    distances = [x["dist_m"] for x in profile]
    elevations = [x["elev_m"] for x in profile]
    scale = candidate.length_m / p.centerline.length
    low, high = start_inset * scale, end * scale
    cuts = [low] + [d for d in distances if low < d < high] + [high]
    new_profile = tuple({"dist_m": d - low,
                         "elev_m": float(np.interp(d, distances, elevations))}
                        for d in cuts)
    vert = new_profile[-1]["elev_m"] - new_profile[0]["elev_m"]
    return replace(
        candidate, version=candidate.version + 1,
        centerline=transform(p.inverse.transform, line),
        gate_start=gate_at(start_inset, p.gate_start) if start_inset else candidate.gate_start,
        gate_end=gate_at(end, p.gate_end) if finish_inset else candidate.gate_end,
        corridor=transform(p.inverse.transform, line.buffer(25)),
        length_m=high - low, vert_m=vert, avg_gradient_pct=100 * vert / (high - low),
        canonical_profile=new_profile)


def make_options(phases):
    after = phases["after"]
    def find(name, prefix=""):
        return next(rid for rid, c in after.items()
                    if c.display_name == name and rid.startswith(prefix))
    srt = find("Schuylkill River Trail")
    consh = find("Conshohocken State Road", "9a9b1cb6")
    laf = find("Lafayette Road")
    options = {}
    for key, rid in [("d10_srt", srt), ("d10_conshohocken_start", consh),
                     ("d10_lafayette", laf)]:
        options[key] = {rid: tolerance(after[rid])}
    for key, rid, start, finish in [
        ("boundary_srt_inset30", srt, 30., 30.),
        ("boundary_conshohocken_start30", consh, 30., 0.),
        ("boundary_lafayette_finish30", laf, 0., 30.),
    ]:
        options[key] = {rid: boundary(after[rid], start, finish)}
    return options


def init_worker(phases, options):
    global PHASES, OPTIONS
    PHASES, OPTIONS = phases, options


def endpoint_record(crossing, projected):
    a = Point(*projected.forward.transform(crossing.segment_start_lon,
                                          crossing.segment_start_lat))
    b = Point(*projected.forward.transform(crossing.segment_end_lon,
                                          crossing.segment_end_lat))
    actual = Point(*projected.forward.transform(crossing.lon, crossing.lat))
    gate = projected.gate_start if crossing.gate == "start" else projected.gate_end
    dt = crossing.segment_end_time_s - crossing.segment_start_time_s
    # Bracket-only interpolation isolates direction look-ahead from clipping.
    bracket = projected.centerline.project(a) + crossing.interpolation_u * (
        projected.centerline.project(b) - projected.centerline.project(a))
    return {
        "legacy": legacy_progress(crossing), "direct": crossing_progress(projected, crossing),
        "bracket_only": float(bracket), "lon": crossing.lon, "lat": crossing.lat,
        "gap_s": dt, "bracket_length_m": float(a.distance(b)),
        "speed_mps": float(a.distance(b) / dt),
        "direction_expanded": (
            crossing.direction_before_source_index != crossing.segment_start_source_index
            or crossing.direction_after_source_index != crossing.segment_end_source_index),
        "gate_residual_m": float(actual.distance(gate)),
        "gate_offset_m": float(gate.project(actual) - gate.length / 2),
        "gate_half_extent_m": float(gate.length / 2),
        "off_centerline_m": float(actual.distance(projected.centerline)),
        "clipped_bracket": bool(
            projected.centerline.project(a) <= 1e-6
            or projected.centerline.project(b) >= projected.centerline.length - 1e-6),
    }


def replay_ride(record):
    from app.services.canon_traversal import CanonTraversalEngine, _project_candidate
    aid, sj = record
    streams = {s["type"]: s["data"] for s in json.loads(sj)}
    if not all(k in streams for k in ("latlng", "time", "distance")):
        raise ValueError("Missing required corpus streams")
    ll, times = np.asarray(streams["latlng"], dtype=float), np.asarray(streams["time"], dtype=float)
    if ll.shape != (len(times), 2) or len(times) < 2 or not np.isfinite(ll).all():
        raise ValueError("Malformed corpus stream")
    result = {k: [] for k in [*PHASES, *OPTIONS]}
    rejections = {k: Counter() for k in result}
    pairs = 0
    engine = CanonTraversalEngine()
    for rid, base in PHASES["before"].items():
        candidates = {phase: values[rid] for phase, values in PHASES.items()}
        candidates.update({name: values[rid] for name, values in OPTIONS.items() if rid in values})
        # Original conservative bbox plus a union of all scenario start gates.
        minx, miny, maxx, maxy = base.corridor.bounds
        idx = np.flatnonzero((ll[:, 1] >= minx - .01) & (ll[:, 1] <= maxx + .01)
                            & (ll[:, 0] >= miny - .01) & (ll[:, 0] <= maxy + .01))
        if len(idx) < 2:
            continue
        lo, hi = max(0, int(idx[0]) - 1), min(len(times), int(idx[-1]) + 2)
        route = LineString([(lon, lat) for lat, lon in ll[lo:hi]])
        if not any(route.intersects(c.gate_start) for c in candidates.values()):
            continue
        pairs += 1
        raw = [{"t": float(times[i]), "lat": float(ll[i, 0]),
                "lon": float(ll[i, 1]), "source_index": i} for i in range(lo, hi)]
        cache = {}
        for phase, candidate in candidates.items():
            key = (candidate.centerline.wkb, candidate.corridor.wkb,
                   candidate.gate_start.wkb, candidate.gate_end.wkb)
            if key not in cache:
                ev = engine.evaluate(
                    activity_id=uuid5(NAMESPACE_URL, f"offline-corpus:{aid}"),
                    wallet="offline", candidates=[candidate], raw_samples=raw)
                projected = _project_candidate(candidate)
                efforts = []
                for attempt in ev.attempts:
                    if not attempt.accepted:
                        continue
                    assert attempt.start is not None and attempt.finish is not None
                    efforts.append({
                        "ride": str(aid), "climb": rid,
                        "start_s": attempt.start.time_s, "finish_s": attempt.finish.time_s,
                        "start": endpoint_record(attempt.start, projected),
                        "finish": endpoint_record(attempt.finish, projected)})
                cache[key] = efforts, ev.rejections
            efforts, rejected = cache[key]
            result[phase].extend(efforts)
            rejections[phase].update(rejected)
    return result, rejections, pairs


def freeze_references(connection, phases):
    import canon_traversal_replay as cr
    from app.services.canon_traversal import _project_candidate
    candidates = []
    for rid, c in phases["before"].items():
        p = _project_candidate(c)
        candidates.append(cr.RatifiedCandidate(
            rid, c.candidate_fingerprint, c.display_name, c, c.corridor,
            p.centerline, p.forward))
    templates, counts = cr.map_reference_templates(connection, candidates)
    expected = cr.load_expected_passes(connection, templates)
    return [vars(r) for r in expected], counts


def recall(efforts, references):
    import canon_traversal_replay as cr
    matched = sum(any(
        e["ride"] == r["activity_id"] and e["climb"] == r["decision_id"]
        and cr.reference_contains_observed(r["start_s"], r["end_s"],
                                           e["start_s"], e["finish_s"])
        for e in efforts) for r in references)
    return {"matched": matched, "expected": len(references),
            "fraction": matched / len(references) if references else None}


def changes(before, after):
    """Greedy matching of non-overlapping engine efforts on the same ride/climb.

    Each paired window must overlap; one-to-one and deterministic. No private
    identity, raw timestamp or per-effort row leaves this function.
    """
    unmatched = set(range(len(after)))
    paired, lost, elapsed_deltas, lost_elapsed = 0, 0, [], []
    for old in sorted(before, key=lambda e: (e["climb"], e["ride"], e["start_s"])):
        choices = [i for i in unmatched
                   if after[i]["climb"] == old["climb"] and after[i]["ride"] == old["ride"]
                   and max(old["start_s"], after[i]["start_s"])
                   < min(old["finish_s"], after[i]["finish_s"])]
        if not choices:
            lost += 1
            lost_elapsed.append(old["finish_s"] - old["start_s"])
            continue
        index = min(choices, key=lambda i: abs(old["start_s"] - after[i]["start_s"])
                    + abs(old["finish_s"] - after[i]["finish_s"]))
        unmatched.remove(index)
        paired += 1
        elapsed_deltas.append((after[index]["finish_s"] - after[index]["start_s"])
                              - (old["finish_s"] - old["start_s"]))
    def duration_summary(values):
        return {"min": min(values) if values else None,
                "median": statistics.median(values) if values else None,
                "max": max(values) if values else None}
    return {"retained": paired, "new": len(unmatched), "lost": lost,
            "retention": paired / len(before) if before else None,
            "paired_elapsed_delta_s": duration_summary(elapsed_deltas),
            "new_effort_duration_s": duration_summary([
                after[i]["finish_s"] - after[i]["start_s"] for i in unmatched]),
            "lost_effort_duration_s": duration_summary(lost_elapsed)}


def aggregate_diagnostics(efforts, rid, gate):
    records = [e[gate] for e in efforts if e["climb"] == rid]
    if not records:
        return {"n": 0}
    med = statistics.median(e["legacy"] for e in records)
    outliers = [e for e in records if abs(e["legacy"] - med) > 10]
    def stats(values):
        return {"min": min(values), "median": statistics.median(values),
                "p95": p95(values), "max": max(values)}
    return {
        "n": len(records), "legacy_outliers": len(outliers),
        "all": {k: stats([e[k] for e in records]) for k in (
            "gap_s", "bracket_length_m", "speed_mps", "gate_offset_m",
            "off_centerline_m", "gate_residual_m")},
        "outliers": {k: stats([e[k] for e in outliers]) for k in (
            "gap_s", "bracket_length_m", "speed_mps")} if outliers else {},
        "clipped_brackets": sum(e["clipped_bracket"] for e in records),
        "direction_expanded": sum(e["direction_expanded"] for e in records),
        "legacy_vs_direct_max_m": max(abs(e["legacy"] - e["direct"]) for e in records),
        "legacy_vs_bracket_only_max_m": max(abs(e["legacy"] - e["bracket_only"]) for e in records),
        "near_arm_end_within_1m": sum(abs(e["gate_offset_m"]) > e["gate_half_extent_m"] - 1
                                    for e in records),
    }


def private_safe_points(points, gate):
    """No ride track or ride endpoint is rendered; bound crossing points too."""
    return [point for point in points if point.distance(gate) <= 60.]


def render(data, result, phases, osm_path, output):
    """Static requested deliverable: local OSM roads, canon, crossing points."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from shapely.geometry import box
    from app.services.canon_traversal import _project_candidate

    osm = read(osm_path)
    nodes = {n["id"]: (n["lon"], n["lat"]) for n in osm["nodes"]}
    roads = []
    for way in osm["ways"]:
        tags = way["tags"]
        if not tags.get("highway"):
            continue
        coords = [nodes[n] for n in way["refs"] if n in nodes]
        if len(coords) >= 2:
            roads.append((LineString(coords), tags, way["id"]))
    del osm, nodes
    output.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.size": 10, "font.family": "DejaVu Sans",
                         "axes.spines.top": False, "axes.spines.right": False})
    all_metadata = []
    for failure in result["failing_gates"]:
        rid, gate = failure["climb"], failure["gate"]
        before = _project_candidate(phases["before"][rid])
        anchor = (before.gate_start if gate == "start" else before.gate_end).centroid
        area = box(anchor.x - 75, anchor.y - 75, anchor.x + 75, anchor.y + 75)
        geographic = transform(before.inverse.transform, area)
        nearby = [(transform(before.forward.transform, line), tags, wid)
                  for line, tags, wid in roads if line.intersects(geographic)]
        nearby.sort(key=lambda item: (item[0].distance(anchor), item[2]))
        fig, axes = plt.subplots(1, 3, figsize=(15, 5.4),
                                 gridspec_kw={"width_ratios": [1, 1, 1.1]})
        fig.suptitle(f"{failure['name']} · {gate} gate",
                     x=.055, ha="left", fontsize=17, fontweight="bold")
        meta = {"climb": rid, "gate": gate, "phases": {},
                "osm_roads": [{"way_id": wid, "name": tags.get("name"),
                               "highway": tags["highway"],
                               "layer": tags.get("layer"),
                               "bridge": tags.get("bridge"), "tunnel": tags.get("tunnel")}
                              for _, tags, wid in nearby]}
        for axis, phase in zip(axes[:2], ("before", "after")):
            candidate = phases[phase][rid]
            centerline = transform(before.forward.transform, candidate.centerline)
            line = transform(before.forward.transform,
                             candidate.gate_start if gate == "start" else candidate.gate_end)
            labelled = set()
            for road, tags, wid in nearby:
                visible = road.intersection(area)
                parts = list(visible.geoms) if hasattr(visible, "geoms") else [visible]
                for part in parts:
                    if part.geom_type != "LineString":
                        continue
                    x, y = part.xy
                    axis.plot(np.asarray(x) - anchor.x, np.asarray(y) - anchor.y,
                              color="#c7c7c7", lw=4 if tags["highway"] not in
                              ("footway", "path", "cycleway") else 2, zorder=1)
                name = tags.get("name")
                if name and name not in labelled and len(labelled) < 3:
                    labelled.add(name)
            context_names = []
            for _, tags, _ in nearby:
                name = tags.get("name")
                if name in labelled and name not in context_names:
                    context_names.append(name)
            axis.text(.02, .98, "\n".join(textwrap.fill(name, 27) for name in context_names),
                      transform=axis.transAxes, va="top", fontsize=7.5, color="#555555",
                      bbox={"facecolor": "white", "edgecolor": "none", "alpha": .8, "pad": 2})
            x, y = centerline.xy
            axis.plot(np.asarray(x) - anchor.x, np.asarray(y) - anchor.y,
                      color="#2463a2", lw=2, zorder=2)
            x, y = line.xy
            axis.plot(np.asarray(x) - anchor.x, np.asarray(y) - anchor.y,
                      color="#222222", lw=1.8, zorder=3)
            records = [e[gate] for e in data["efforts"][phase] if e["climb"] == rid]
            med = statistics.median(e["legacy"] for e in records) if records else 0
            points = [Point(*before.forward.transform(e["lon"], e["lat"])) for e in records]
            shown = private_safe_points(points, line)
            assert len(shown) == len(points), "Expected every intersection to lie on the gate"
            for outlier, marker, color, label in [
                (False, "o", "#2463a2", "≤10 m legacy deviation"),
                (True, "x", "#c45c19", ">10 m legacy deviation"),
            ]:
                chosen = [point for point, record in zip(points, records)
                          if (abs(record["legacy"] - med) > 10) == outlier]
                if chosen:
                    axis.scatter([pt.x - anchor.x for pt in chosen],
                                 [pt.y - anchor.y for pt in chosen], marker=marker,
                                 c=color, s=34, linewidths=1.3, alpha=.75, zorder=4)
            axis.set(xlim=(-75, 75), ylim=(-75, 75),
                     xlabel="East of original gate centre (m)",
                     ylabel="North of original gate centre (m)",
                     title=f"{phase.capitalize()} · {len(records)} crossings")
            axis.set_aspect("equal")
            axis.grid(alpha=.12)
            axis.annotate("N", (64, 63), ha="center", fontsize=11,
                          xytext=(64, 48), arrowprops={"arrowstyle": "->"})
            meta["phases"][phase] = {"crossings_shown": len(shown),
                                     "crossings_excluded": len(points) - len(shown)}
        axis = axes[2]
        for phase, linestyle in [("before", "--"), ("after", "-")]:
            selected = [e for e in data["efforts"][phase] if e["climb"] == rid]
            records = [e[gate] for e in selected]
            eligible = len({e["ride"] for e in selected}) >= 2
            for method, color in [("legacy", "#c45c19"), ("direct", "#2463a2")]:
                vals = [e[method] for e in records]
                if not vals:
                    continue
                med = statistics.median(vals)
                deviations = sorted(abs(v - med) for v in vals)
                label = (f"{phase} {method} · p95 {p95(deviations):.3f} m" if eligible else
                         f"{phase} {method} · ineligible (one ride)")
                if not eligible:
                    axis.plot([], [], color=color, linestyle=linestyle, label=label)
                    continue
                axis.step(deviations, np.arange(1, len(vals) + 1) / len(vals) * 100,
                          where="post", color=color, linestyle=linestyle,
                          label=label)
        axis.axvline(10, color="#333333", linewidth=1)
        axis.axhline(95, color="#777777", linewidth=1, linestyle=":")
        axis.set(xlim=(0, 21), ylim=(0, 103), xlabel="Absolute deviation from gate median (m)",
                 ylabel="Cumulative observations (%)", title="Same crossings · two calculations")
        axis.legend(loc="lower right", fontsize=8, frameon=False)
        axis.grid(alpha=.12)
        fig.legend(handles=[
            Line2D([0], [0], color="#c7c7c7", lw=4, label="OSM roads / paths"),
            Line2D([0], [0], color="#2463a2", lw=2, label="Canonical centreline"),
            Line2D([0], [0], color="#222222", lw=2, label="Gate"),
            Line2D([0], [0], marker="o", lw=0, color="#2463a2", label="Legacy deviation ≤10 m"),
            Line2D([0], [0], marker="x", lw=0, color="#c45c19", label="Legacy deviation >10 m"),
        ], loc="lower center", bbox_to_anchor=(.5, .07), ncol=5, frameon=False)
        fig.text(.055, .025,
                 "Local offline evidence. Crossing points only, within 60 m of each gate; no ride tracks or identifiers. "
                 "© OpenStreetMap contributors · ODbL · openstreetmap.org/copyright", fontsize=8, color="#555555")
        fig.subplots_adjust(left=.055, right=.98, bottom=.25, top=.82, wspace=.34)
        name = f"{rid[:8]}-{gate}.png"
        fig.savefig(output / name, dpi=145, facecolor="white",
                    metadata={"Title": f"{failure['name']} {gate} crossing geometry"})
        plt.close(fig)
        meta["file"] = name
        all_metadata.append(meta)
    return {"osm_sha256": digest(osm_path), "source": "local extract of the pinned Pennsylvania PBF",
            "files": all_metadata}


def summarize(data, phases, options):
    efforts, refs = data["efforts"], data["references"]
    result = {"evidence_class": "local offline real-corpus replay; proposals only",
              "inputs": data["inputs"], "rides_scanned": data["rides_scanned"],
              "evaluated_pairs_union_prefilter": data["pairs"],
              "reference_mapping": data["reference_mapping"],
              "phases": {}, "options": {}, "failing_gates": []}
    result["frozen_observation_sets"] = {
        phase: {"accepted_efforts": len(efforts[phase]),
                "sha256": hashlib.sha256(json.dumps(efforts[phase], sort_keys=True,
                                                    separators=(",", ":")).encode()).hexdigest()}
        for phase in ("before", "after")
    }
    result["reference_set_sha256"] = hashlib.sha256(
        json.dumps(refs, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result["summary_code_sha256"] = digest(__file__)
    for phase in ("before", "after"):
        result["phases"][phase] = {
            "accepted": len(efforts[phase]), "reference_recall": recall(efforts[phase], refs),
            "legacy": metric(efforts[phase], "legacy"),
            "direct": metric(efforts[phase], "direct"),
            "rejections": data["rejections"][phase]}
    result["finish_rule_changes"] = changes(efforts["before"], efforts["after"])
    failing = sorted({(g["climb"], g["gate"]) for phase in ("before", "after")
                      for g in result["phases"][phase]["legacy"]["groups"] if g["over_10m"]})
    affected = {rid for rid, _ in failing}
    result["affected_climbs"] = {}
    for rid in sorted(affected):
        result["affected_climbs"][rid] = {
            "name": phases["before"][rid].display_name,
            **{phase: {
                "accepted": sum(e["climb"] == rid for e in efforts[phase]),
                "reference_recall": recall(
                    [e for e in efforts[phase] if e["climb"] == rid],
                    [r for r in refs if r["decision_id"] == rid]),
                "legacy": result["phases"][phase]["legacy"]["per_climb"].get(rid),
                "direct": result["phases"][phase]["direct"]["per_climb"].get(rid)}
               for phase in ("before", "after")}}
    srt = {rid for rid, c in phases["before"].items() if c.display_name == "Schuylkill River Trail"}
    unmoved = {rid for rid, c in phases["before"].items()
               if c.candidate_fingerprint == phases["after"][rid].candidate_fingerprint}
    result["diagnostic_subsets_not_alternative_pass_rules"] = {
        label: {phase: metric([e for e in efforts[phase] if e["climb"] in ids], "legacy")
                for phase in ("before", "after")}
        for label, ids in [("without_srt", set(phases["before"]) - srt),
                           ("unchanged_42", unmoved),
                           ("unchanged_without_neill_41",
                            {rid for rid in unmoved if phases["before"][rid].display_name
                             != "Falls Road / Neill Drive"})]}
    for rid, gate in failing:
        result["failing_gates"].append({
            "climb": rid, "name": phases["before"][rid].display_name, "gate": gate,
            "diagnostics": {p: aggregate_diagnostics(efforts[p], rid, gate)
                            for p in ("before", "after")}})
    for name, replacements in options.items():
        original = efforts["after"]
        selected = [e for e in original if e["climb"] in replacements]
        updated = [e for e in original if e["climb"] not in replacements] + efforts[name]
        per_climb = {}
        for rid in replacements:
            reference_slice = [r for r in refs if r["decision_id"] == rid]
            b = [e for e in selected if e["climb"] == rid]
            a = [e for e in efforts[name] if e["climb"] == rid]
            per_climb[rid] = {
                "name": phases["after"][rid].display_name,
                "before_accepted": len(b), "after_accepted": len(a),
                "before_reference_recall": recall(b, reference_slice),
                "after_reference_recall": recall(a, reference_slice),
                "effort_changes": changes(b, a),
                "before_legacy": metric(b, "legacy"), "after_legacy": metric(a, "legacy"),
                "before_direct": metric(b, "direct"), "after_direct": metric(a, "direct"),
                "proposed_centerline_wkt": replacements[rid].centerline.wkt,
                "proposed_gate_start_wkt": replacements[rid].gate_start.wkt,
                "proposed_gate_end_wkt": replacements[rid].gate_end.wkt}
        result["options"][name] = {
            "authority": "D10 per-candidate evidence review" if name.startswith("d10") else
                         "founder boundary approval; new version and fresh leaderboard",
            "parameters": (
                {"both_gate_half_extents_m": 40, "corridor_half_width_m": 35,
                 "prior_gate_half_extent_nominal_m": 25, "prior_corridor_half_width_m": 25,
                 "anchor_orientation_centerline_span_unchanged": True}
                if name.startswith("d10") else
                {"start_inset_m": 30 if "srt" in name or "conshohocken" in name else 0,
                 "finish_inset_m": 30 if "srt" in name or "lafayette" in name else 0,
                 "corridor_half_width_m": 25, "distance_crs": "engine local AEQD",
                 "orientation": "perpendicular to +/-0.5 m local tangent at new anchor",
                 "gate_half_extent": "retained measured extent",
                 "publication_payload": False}),
            "accepted": len(updated), "reference_recall": recall(updated, refs),
            "changed_climb_rejections": data["rejections"][name],
            "effort_changes": changes(original, updated),
            "legacy": metric(updated, "legacy"), "direct": metric(updated, "direct"),
            "affected_climbs": per_climb}
    result["options"]["metric_projection"] = {
        "authority": "Founder reviews metric correction proposal; existing cutover gate remains failing",
        "geometry_change": False, "timing_change": False, "threshold_m": 10,
        "accepted": len(efforts["after"]), "reference_recall": recall(efforts["after"], refs),
        "effort_changes": changes(efforts["after"], efforts["after"]),
        "legacy": result["phases"]["after"]["legacy"],
        "direct": result["phases"]["after"]["direct"]}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--private-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--reuse", action="store_true")
    parser.add_argument("--osm", type=Path)
    parser.add_argument("--renders", type=Path)
    args = parser.parse_args()
    if args.private_cache.resolve().is_relative_to(ROOT):
        parser.error("Private cache must be outside the checkout")
    source, rows, phases, moved = build_candidates(args.inputs)
    options = make_options(phases)
    inputs = {key: {"path": item["path"], "sha256": item["sha256"]}
              for key, item in source.items() if key in ("corpus", "registry", "pbf")}
    for key in ("corpus", "registry", "pbf"):
        if digest(inputs[key]["path"]) != inputs[key]["sha256"]:
            raise ValueError(f"Input changed: {key}")
    for name in ("COMPILER-BEFORE.json", "ADMITTED-AFTER.json", "INPUTS.json"):
        inputs[name] = {"sha256": digest(args.inputs / name)}
    inputs["engine"] = {"sha256": digest(ROOT / "backend/app/services/canon_traversal.py")}
    if inputs["engine"]["sha256"] != source["engine"]["sha256"]:
        raise ValueError("Traversal engine changed")
    inputs["gate_rule_commit"] = (args.inputs / "COMMIT").read_text().strip()
    inputs["research_code_sha256"] = digest(__file__)
    # Pin the corpus, geometry, scenarios and reference set before scoring.
    if args.reuse:
        data = read(args.private_cache)
        for key in inputs:
            if key != "research_code_sha256" and inputs[key] != data["inputs"][key]:
                raise ValueError(f"Private replay cache input mismatch: {key}")
    else:
        con = sqlite3.connect(Path(inputs["corpus"]["path"]).as_uri()
                              + "?mode=ro&immutable=1", uri=True)
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        refs, counts = freeze_references(con, phases)
        print(f"Frozen {len(refs)} reference efforts; 57 climbs; 15 moved finishes", flush=True)
        records = list(con.execute(
            "SELECT activity_id, streams_json FROM activity_streams ORDER BY CAST(activity_id AS INTEGER)"))
        con.close()
        data = {"inputs": inputs, "references": refs, "reference_mapping": counts,
                "rides_scanned": len(records), "pairs": 0,
                "efforts": {p: [] for p in [*phases, *options]},
                "rejections": {p: Counter() for p in [*phases, *options]}}
        with ProcessPoolExecutor(max_workers=args.workers,
                                 mp_context=multiprocessing.get_context("spawn"),
                                 initializer=init_worker, initargs=(phases, options)) as pool:
            for count, (efforts, rejections, pairs) in enumerate(
                    pool.map(replay_ride, records, chunksize=4), 1):
                for phase in efforts:
                    data["efforts"][phase].extend(efforts[phase])
                    data["rejections"][phase].update(rejections[phase])
                data["pairs"] += pairs
                if count % 100 == 0:
                    print(f"Replayed {count}/{len(records)} rides", flush=True)
        write(args.private_cache, data, private=True)
    result = summarize(data, phases, options)
    if args.renders:
        if not args.osm:
            parser.error("--renders requires --osm")
        result["renders"] = render(data, result, phases, args.osm, args.renders)
    write(args.output, result)
    print(json.dumps({p: {k: s[k] for k in ("accepted", "reference_recall")}
                      for p, s in result["phases"].items()}), flush=True)


if __name__ == "__main__":
    main()
