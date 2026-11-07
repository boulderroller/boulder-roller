#!/usr/bin/env python3
"""Offline stop-map research. Raw observations stay in memory, never in outputs.

Reads an existing geo_features::OsmParser / osm-preprocess road export. This is
not an OSM parser, a new canon stage, or a production stop-evidence input.
The founder confirmed ownership and consent on 20 October 2026. Publication
requires three distinct rides on three distinct local calendar days.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
from zoneinfo import ZoneInfo

import ijson
import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely import from_wkb, from_wkt
from shapely.strtree import STRtree

R = 6371008.8
TO_XY = Transformer.from_crs(4326, 32618, always_xy=True)
TO_LL = Transformer.from_crs(32618, 4326, always_xy=True)
POLICY = {
    "stop_below_mps": 1, "stop_at_least_s": 3, "max_observed_gap_s": 30,
    "own_endpoint_radius_m": 300, "repeated_endpoint_radius_m": 150,
    "endpoint_repeat_radius_m": 50, "endpoint_repeat_min_distinct_rides": 2,
    "minimum_distinct_rides": 3, "minimum_distinct_days": 3,
    "calendar_timezone": "America/New_York", "snap_radius_m": 30,
    "snap_heading_tolerance_deg": 45, "parallel_road_tie_m": 3,
    "max_stop_position_radius_m": 20, "max_cluster_diameter_m": 20,
    "control_radius_m": 40, "position_decimals": 5,
}


@dataclass
class Stop:
    ride: str
    rider: str | None
    first: int
    last: int
    duration_s: float
    samples: list
    position: tuple  # lat, lon
    heading_deg: float | None
    turnaround: bool


@dataclass
class Endpoint:
    position: tuple
    ride: str
    rider: str | None


@dataclass
class SnappedStop:
    way_id: int
    direction: int
    along_m: float
    duration_s: float
    rider: str | None
    ride: str
    xy: tuple
    heading_deg: float
    turnaround: bool = False
    own_endpoints: tuple = ()
    day: str | None = None  # Internal only: never serialized.


@dataclass
class Control:
    control_id: int
    way_id: int
    along_m: float
    kind: str
    direction: int | None


def valid_ll(p):
    return (len(p) == 2 and all(math.isfinite(float(x)) for x in p)
            and -90 <= p[0] <= 90 and -180 <= p[1] <= 180
            and tuple(p) != (0, 0))


def distances(p, positions):
    """Great-circle metres, including endpoint masks outside Pennsylvania."""
    if not len(positions):
        return np.array([])
    a = np.radians(np.asarray(positions, dtype=float))
    lat, lon = np.radians(p)
    h = np.sin((a[:, 0] - lat) / 2)**2 + np.cos(lat) * np.cos(a[:, 0]) * np.sin((a[:, 1] - lon) / 2)**2
    return 2 * R * np.arcsin(np.sqrt(np.clip(h, 0, 1)))


def bearing(a, b):
    lat1, lon1 = np.radians(a)
    lat2, lon2 = np.radians(b)
    y = math.sin(lon2-lon1)*math.cos(lat2)
    x = math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(lon2-lon1)
    return math.degrees(math.atan2(y, x)) % 360


def angle(a, b):
    return abs((a-b+180) % 360-180)


def detect_stops(times, distance, latlon, ride, rider=None):
    """Contiguous recorded intervals: delta-distance / delta-time <1 for >=3s.

    For integer timestamps this equals the derivative of linearly resampled
    1s distance. Invalid deltas and gaps >30s break runs, never imply a stop.
    GPS coordinates are only used for location/direction, not speed smoothing.
    """
    t, d, p = (np.asarray(v, dtype=float) for v in (times, distance, latlon))
    if t.ndim != 1 or d.shape != t.shape or p.shape != (len(t), 2):
        raise ValueError("unaligned time, distance and coordinate streams")
    if len(t) < 2:
        return []
    valid = np.isfinite(p).all(axis=1) & (abs(p[:, 0]) <= 90) & (abs(p[:, 1]) <= 180)
    # Null Island is rejected by the corpus adapter; equatorial fixtures remain valid.
    dt, dd = np.diff(t), np.diff(d)
    good = (np.isfinite(dt) & np.isfinite(dd) & (dt > 0) & (dt <= 30)
            & (dd >= 0) & (dd < dt) & valid[:-1] & valid[1:])
    edges = np.diff(np.r_[False, good, False].astype(int))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    events = []
    for first, last in zip(starts, ends):
        duration = t[last] - t[first]
        if duration < 3:
            continue
        samples = p[first:last+1]
        position = tuple(np.median(samples, axis=0))
        incoming = outgoing = None
        for i in range(first-1, -1, -1):
            if not np.isfinite(t[i]) or t[first]-t[i] > 30:
                break
            if valid[i] and distances(position, [p[i]])[0] >= 10:
                incoming = bearing(p[i], position)
                break
        for i in range(last+1, len(t)):
            if not np.isfinite(t[i]) or t[i]-t[last] > 30:
                break
            if valid[i] and distances(position, [p[i]])[0] >= 10:
                outgoing = bearing(position, p[i])
                break
        events.append(Stop(ride, rider, int(first), int(last), float(duration),
                           samples.tolist(), position, incoming,
                           incoming is not None and outgoing is not None and angle(incoming, outgoing) >= 135))
    return events


def repeated_endpoints(points):
    """Union of recurrent endpoint observations; never an averaged home point.

    Recurrence is <=50m on >=2 distinct rides for the same known rider. Missing
    identities pool conservatively with every rider, over-excluding if needed.
    Two ends of the same loop do not count as two rides.
    """
    if not points:
        return []
    positions = np.asarray([p.position for p in points])
    mask = []
    for i, point in enumerate(points):
        near = np.flatnonzero(distances(point.position, positions) <= 50)
        if any(points[j].ride != point.ride and
               (point.rider is None or points[j].rider is None or point.rider == points[j].rider)
               for j in near):
            mask.append(tuple(positions[i]))
    return sorted(set(mask))


def endpoint_exclusion(event, own_endpoints, repeated):
    for name, points, radius in [("own_endpoint", own_endpoints, 300),
                                  ("repeated_endpoint", repeated, 150)]:
        if not len(points):
            continue
        # Fast median screen plus full sample check. Long, drifting stops still
        # protect all their samples, rather than only the representative point.
        reach = max(distances(event.position, event.samples), default=0)
        near = np.asarray(points)[distances(event.position, points) <= radius+reach+1]
        if any(np.any(distances(p, near) <= radius) for p in event.samples):
            return name
    return None


class RoadIndex:
    """Read compiler-exported geometries. No OSM tag or PBF parsing here."""
    def __init__(self, rows):
        self.rows = rows
        self.lines = [LineString(r["geometry"]) for r in rows]
        self.tree = STRtree(self.lines)

    @classmethod
    def from_xy(cls, rows):
        return cls(rows)

    @classmethod
    def from_export(cls, path, positions, required_ways=()):
        # Retain only source ways whose expanded bbox overlaps an observation
        # cell. This is an in-memory I/O optimization; every road is examined.
        cells = {(math.floor(p[1]*100), math.floor(p[0]*100)) for p in positions}
        rows, total = [], 0
        with open(path, "rb") as f:
            for row in ijson.items(f, "item", use_float=True):
                total += 1
                geom = np.asarray(row["geometry"], dtype=float)
                if len(geom) < 2 or not np.isfinite(geom).all():
                    continue
                lo, hi = geom.min(axis=0)-0.001, geom.max(axis=0)+0.001
                if row["osm_way_id"] not in required_ways and not any((x, y) in cells
                           for x in range(math.floor(lo[0]*100), math.floor(hi[0]*100)+1)
                           for y in range(math.floor(lo[1]*100), math.floor(hi[1]*100)+1)):
                    continue
                x, y = TO_XY.transform(geom[:, 0], geom[:, 1])
                if len(set(zip(x, y))) < 2:
                    continue
                rows.append({"osm_way_id": row["osm_way_id"], "geometry": list(zip(x, y)),
                             "osm_node_ids": row.get("osm_node_ids", []),
                             "name": row.get("name"), "road_class": row.get("road_class")})
        return cls(rows), total

    def snap_xy(self, xy, heading):
        if heading is None:
            return None, "missing_direction"
        point = Point(xy)
        if not all(math.isfinite(v) for v in xy):
            return None, "outside_snap_radius"
        candidates = self.tree.query(point.buffer(30))
        if not len(candidates):
            return None, "outside_snap_radius"
        matches = []
        for i in candidates:
            line = self.lines[i]
            lateral = line.distance(point)
            if lateral > 30:
                continue
            s = line.project(point)
            a, b = line.interpolate(max(0, s-3)), line.interpolate(min(line.length, s+3))
            tangent = math.degrees(math.atan2(b.x-a.x, b.y-a.y)) % 360
            forward, reverse = angle(heading, tangent), angle(heading, (tangent+180) % 360)
            if min(forward, reverse) > 45:
                continue
            projected = line.interpolate(s)
            matches.append({"way_id": self.rows[i]["osm_way_id"], "direction": 1 if forward <= reverse else -1,
                            "along_m": s, "lateral_m": lateral, "xy": (projected.x, projected.y),
                            "heading_deg": tangent if forward <= reverse else (tangent+180) % 360})
        if not matches:
            return None, "outside_snap_radius_or_heading"
        matches.sort(key=lambda x: (x["lateral_m"], x["way_id"]))
        if len(matches) > 1 and matches[1]["lateral_m"]-matches[0]["lateral_m"] <= 3:
            return None, "ambiguous_road"
        return matches[0], None


def cluster_stops(stops):
    groups = defaultdict(list)
    for event in stops:
        groups[event.way_id, event.direction].append(event)
    clusters = []
    for key in sorted(groups):
        current = []
        for event in sorted(groups[key], key=lambda s: s.along_m):
            if current and event.along_m-current[0].along_m > 20:
                clusters.append(current)
                current = []
            current.append(event)
        if current:
            clusters.append(current)
    return clusters


def match_control(spot, controls, intervening_junctions=()):
    eligible = []
    for control in controls:
        if control.way_id != spot.way_id or abs(control.along_m-spot.along_m) > 40:
            continue
        if control.kind not in {"traffic_signals", "stop", "all_way_stop", "give_way", "signalled_crossing", "rail"}:
            continue
        if control.direction is not None and control.direction != spot.direction:
            continue
        if control.direction is None and control.kind in {"stop", "give_way"}:
            continue
        # A control at the junction itself is allowed; one beyond a different
        # junction is not on this approach. At most 5m downstream GPS/map drift.
        if (control.along_m-spot.along_m)*spot.direction < -5:
            continue
        if any(min(spot.along_m, control.along_m) < s < max(spot.along_m, control.along_m)
               for s in intervening_junctions):
            continue
        eligible.append(control)
    return min(eligible, key=lambda c: (abs(c.along_m-spot.along_m), c.control_id), default=None)


def classify_spot(cluster, matched, downstream_junction_m, ambiguous_control=False):
    durations = [s.duration_s for s in cluster]
    if matched is not None:
        return "mapped control", "medium", "applicable control within 40 m on the connected approach; cause is inferred"
    if ambiguous_control:
        return "unresolved", "low", "mapped control nearby has unresolved facing; not evidence of an OSM omission"
    if np.mean([s.turnaround for s in cluster]) >= 0.5:
        return "not a control", "low", "majority turnarounds; a traffic cause is still possible"
    if downstream_junction_m is not None and 0 <= downstream_junction_m <= 40 and np.median(durations) <= 90 and np.percentile(durations, 90) <= 180:
        return "likely unmapped control", "low", "short pauses before a junction; map omission is unconfirmed"
    if downstream_junction_m is None and np.median(durations) >= 120:
        return "not a control", "low", "long pauses away from a known junction; cafe/viewpoint/regroup subtype unknown"
    return "unresolved", "low", "duration and geometry do not separate traffic from a discretionary pause"


def independent_day_witnesses(cluster):
    days = defaultdict(set)
    for s in cluster:
        if s.day:
            days[s.ride].add(s.day)
    owners = {}
    def assign(ride, visited):
        for day in sorted(days[ride]):
            if day in visited:
                continue
            visited.add(day)
            if day not in owners or assign(owners[day], visited):
                owners[day] = ride
                return True
        return False
    for ride in sorted(days):
        assign(ride, set())
        if len(owners) >= 3:
            return True
    return False


def publish_spots(clusters, controls, protected_points=(), junctions_by_way=None, context=None, counts=None):
    """Aggregate only consenting observations recurring across rides and days."""
    output = []
    for original in clusters:
        cluster = [s for s in original if isinstance(s.rider, str) and s.rider.strip() and s.day]
        riders = {s.rider for s in cluster}
        if len({s.ride for s in cluster}) < 3 or len({s.day for s in cluster}) < 3 or not independent_day_witnesses(cluster):
            if counts is not None:
                counts["clusters_below_ride_day_threshold"] += 1
            continue
        along = [s.along_m for s in cluster]
        ordered = sorted(cluster, key=lambda s: s.along_m)
        middle = [ordered[(len(ordered)-1)//2], ordered[len(ordered)//2]]
        representative = replace(middle[0], along_m=float(np.median(along)))
        xy = np.mean([s.xy for s in middle], axis=0)
        if context is not None:
            line = context.lines[representative.way_id]
            point = line.interpolate(representative.along_m)
            xy = (point.x, point.y)
            a = line.interpolate(max(0, representative.along_m-3))
            b = line.interpolate(min(line.length, representative.along_m+3))
            representative.heading_deg = (math.degrees(math.atan2(b.x-a.x, b.y-a.y)) + (180 if representative.direction == -1 else 0)) % 360
        lon, lat = TO_LL.transform(*xy)
        position = [round(lat, POLICY["position_decimals"]), round(lon, POLICY["position_decimals"])]
        own = [p for s in cluster for p in s.own_endpoints]
        if any((len(points) and (np.any(distances(position, points) <= radius)
                                or np.any(distances((lat, lon), points) <= radius)))
               for points, radius in [(own, 300), (protected_points, 150)]):
            if counts is not None:
                counts["clusters_excluded_aggregate_privacy_recheck"] += 1
            continue
        junctions = (junctions_by_way or {}).get(representative.way_id, [])
        nearby_controls, ambiguous = controls, False
        if context is not None:
            nearby_controls, junctions, ambiguous = context.approach(representative)
        matched = match_control(representative, nearby_controls, junctions)
        downstream = [(s-representative.along_m)*representative.direction for s in junctions
                      if (s-representative.along_m)*representative.direction >= 0]
        kind, confidence, reason = classify_spot(cluster, matched, min(downstream, default=None), ambiguous)
        output.append({
            "spot_id": f"spot-{len(output)+1:04d}", "position": {"lat": position[0], "lon": position[1]},
            "osm_way_id": representative.way_id,
            "direction": {"along_osm_way": "forward" if representative.direction == 1 else "backward",
                          "bearing_deg": int(round(representative.heading_deg)) % 360},
            "rider_count": len(riders), "ride_count": len({s.ride for s in cluster}), "stop_count": len(cluster),
            "day_count": len({s.day for s in cluster}),
            "median_length_s": round(float(np.median([s.duration_s for s in cluster])), 1),
            "position_spread_m": {"iqr": round(float(np.percentile(along, 75)-np.percentile(along, 25)), 1),
                                  "p90_minus_p10": round(float(np.percentile(along, 90)-np.percentile(along, 10)), 1)},
            "class": kind, "confidence": confidence, "reason": reason,
            "matched_control": None if matched is None else {"osm_node_id": matched.control_id, "kind": matched.kind},
        })
    return output


def gate_flags(xy, heading, line_xy):
    """Synthetic-tested local gate relation, with <=12m lateral tolerance."""
    line = LineString(line_xy)
    p = Point(xy)
    s = line.project(p)
    a, b = line.interpolate(max(0, s-1)), line.interpolate(min(line.length, s+1))
    tangent = np.array([b.x-a.x, b.y-a.y])
    tangent /= np.linalg.norm(tangent)
    projected = line.interpolate(s)
    delta = np.array([p.x-projected.x, p.y-projected.y])
    if s == 0 or s == line.length:
        s += float(delta @ tangent)
    lateral = abs(float(delta[0]*tangent[1]-delta[1]*tangent[0]))
    direction = math.degrees(math.atan2(tangent[0], tangent[1])) % 360
    if lateral > 12 or angle(heading, direction) > 45:
        return []
    flags = []
    if 0 <= s-line.length <= 15:
        flags.append("finish_0_15m_past")
    if abs(s) <= 15:
        flags.append("start_within_15m")
    if 0 < s < line.length:
        flags.append("interior_information")
    return flags


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def calendar_day(start_date, elapsed_s):
    start = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if start.tzinfo is None:
        raise ValueError("corpus start timestamp lacks timezone")
    return (start + timedelta(seconds=float(elapsed_s))).astimezone(ZoneInfo(POLICY["calendar_timezone"])).date().isoformat()


def check_gate_inventory(gates, registry):
    baseline = {r["id"]: r for r in registry}
    assert len(baseline) == 57 and {r["registry_id"] for r in gates["climbs"]} == set(baseline)
    assert sum(r["finish_moved"] for r in gates["climbs"]) == 15
    for r in gates["climbs"]:
        original = from_wkb(bytes.fromhex(baseline[r["registry_id"]]["gate_end_line"]))
        retained = from_wkt(r["old"]["gate_end_wkt"])
        # Retained WKT uses 7 decimal places; registry EWKB keeps full precision.
        assert original.hausdorff_distance(retained) < 0.0000002


def analyze(corpus, roads, controls_path, gate_diff, gate_branch_sha, registry, candidates_path, topology_output):
    from tools.stop_map.graph_context import GraphContext, read_control_graph
    gates = json.loads(gate_diff.read_text())
    registry_rows = json.loads(registry.read_text())
    check_gate_inventory(gates, registry_rows)
    candidates = json.loads(candidates_path.read_text())["candidates"]
    source = {c["candidate_fingerprint"]: c for c in candidates}
    assert len(source) == 57 and set(source) == {r["candidate_fingerprint"] for r in registry_rows}
    for row in registry_rows:
        assert from_wkb(bytes.fromhex(row["centerline_geom"])).hausdorff_distance(from_wkt(source[row["candidate_fingerprint"]]["centerline_wkt"])) < 2e-7
    counts = Counter()
    corpus_digest = sha256(corpus)
    if corpus_digest != "64b15790bed2628b3e7e8371657b408ec5e96305db84bfe050507b14860b98ee":
        raise ValueError("corpus differs from the founder-consented snapshot; review ownership binding")
    pending, endpoints = [], []
    before = (corpus.stat().st_size, corpus.stat().st_mtime_ns)
    con = sqlite3.connect(corpus.resolve().as_uri()+"?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    con.execute("BEGIN")
    counts["rides_in_database"] = con.execute("SELECT count(*) FROM rides").fetchone()[0]
    counts["streams_in_database"] = con.execute("SELECT count(*) FROM activity_streams").fetchone()[0]
    dates = con.execute("SELECT min(start_date), max(start_date) FROM rides").fetchone()
    owner = "consenting-corpus-owner"  # User-confirmed binding, never an inferred activity owner.
    counts["consenting_riders"] = 1
    columns = [row[1] for row in con.execute("PRAGMA table_info(rides)")]
    if any(x in columns for x in ["rider_id", "athlete_id", "user_id"]):
        raise ValueError("identity schema changed: review provenance before using this adapter")
    sql = """SELECT start_lat,start_lon,end_lat,end_lon,streams_json,start_date FROM rides
             LEFT JOIN activity_streams USING(activity_id) ORDER BY rides.activity_id"""
    for ordinal, (a, b, c, d, raw, start_date) in enumerate(con.execute(sql)):
        counts["rides_examined"] += 1
        own = [tuple(p) for p in [(a, b), (c, d)] if None not in p and valid_ll(p)]
        if raw is None:
            counts["rides_missing_streams"] += 1
            endpoints.extend(Endpoint(p, str(ordinal), owner) for p in own)
            continue
        stream = {v["type"]: v["data"] for v in json.loads(raw)}
        if not all(k in stream for k in ["time", "distance", "latlng"]):
            counts["rides_missing_required_channels"] += 1
            endpoints.extend(Endpoint(p, str(ordinal), owner) for p in own)
            continue
        t, dist, p = (np.asarray(stream[k], dtype=float) for k in ["time", "distance", "latlng"])
        if t.ndim != 1 or dist.shape != t.shape or p.shape != (len(t), 2) or len(t) < 2:
            counts["rides_invalid_stream_shapes"] += 1
            endpoints.extend(Endpoint(p, str(ordinal), owner) for p in own)
            continue
        own += [tuple(point) for point in [p[0], p[-1]] if valid_ll(point)]
        endpoints.extend(Endpoint(point, str(ordinal), owner) for point in set(own))
        p[np.all(p == 0, axis=1)] = np.nan
        counts["rides_analyzable"] += 1
        counts["samples_examined"] += len(t)
        dt, dd = np.diff(t), np.diff(dist)
        counts["intervals_over_30s"] += int(np.sum(dt > 30))
        counts["low_average_speed_gaps_over_30s"] += int(np.sum((dt > 30) & (dd >= 0) & (dd < dt)))
        counts["negative_distance_intervals"] += int(np.sum(dd < 0))
        counts["nonincreasing_time_intervals"] += int(np.sum(dt <= 0))
        events = detect_stops(t, dist, p, str(ordinal), owner)
        counts["detected_stop_candidates"] += len(events)
        for event in events:
            event.day = calendar_day(start_date, t[event.first])
            if endpoint_exclusion(event, own, []):
                counts["excluded_own_endpoint"] += 1
            else:
                pending.append((event, own))
        if (ordinal+1) % 250 == 0:
            print(f"Scanned {ordinal+1} rides; raw observations remain in memory", flush=True)
    con.close()
    repeated = repeated_endpoints(endpoints)
    counts["recurrent_endpoint_observations_unique"] = len(repeated)
    eligible = []
    for event, own in pending:
        if endpoint_exclusion(event, [], repeated):
            counts["excluded_repeated_endpoint"] += 1
        else:
            eligible.append((event, own))
    counts["after_endpoint_filters"] = len(eligible)
    print("Indexing complete compiler road export", flush=True)
    required_ways = {w for c in candidates for w in c["osm_way_refs"]}
    index, count = RoadIndex.from_export(roads, [event.position for event, _ in eligible], required_ways)
    counts["compiler_export_roads_examined"] = count
    counts["compiler_export_roads_indexed"] = len(index.rows)
    snapped = []
    for event, own in eligible:
        if max(distances(event.position, event.samples), default=0) > 20:
            counts["excluded_spatially_diffuse_stop"] += 1
            continue
        xy = TO_XY.transform(event.position[1], event.position[0])
        match, reason = index.snap_xy(xy, event.heading_deg)
        if reason:
            counts["snap_rejected_"+reason] += 1
            continue
        lon, lat = TO_LL.transform(*match["xy"])
        projected = Stop(event.ride, owner, 0, 0, event.duration_s, [(lat, lon)], (lat, lon), event.heading_deg, event.turnaround)
        if endpoint_exclusion(projected, own, repeated):
            counts["excluded_after_snap_privacy_recheck"] += 1
            continue
        snapped.append(SnappedStop(match["way_id"], match["direction"], match["along_m"],
                                   event.duration_s, owner, event.ride, match["xy"], match["heading_deg"], event.turnaround, tuple(own), event.day))
    counts["snapped_stops"] = len(snapped)
    clusters = cluster_stops(snapped)
    counts["directional_clusters_before_recurrence_gate"] = len(clusters)
    print("Reading public compiler control graph; private observations remain in memory", flush=True)
    wanted_ways = {r["osm_way_id"] for r in index.rows}
    wanted_nodes = {n for r in index.rows for n in r["osm_node_ids"]}
    graph = read_control_graph(controls_path, wanted_ways, wanted_nodes)
    context = GraphContext(graph, index)
    counts["local_graph_nodes"] = len(graph["nodes"])
    counts["local_graph_junctions"] = len(graph["junctions"])
    spots = publish_spots(clusters, [], repeated, context=context, counts=counts)
    # Reusable public OSM context in scratch space, never rider observations.
    topology_output.write_text(json.dumps(context.public_topology(), separators=(",", ":"))+"\n")
    counts["publishable_spots"] = len(spots)
    assert before == (corpus.stat().st_size, corpus.stat().st_mtime_ns), "corpus changed during run"
    return {
        "schema_version": "stop-map-research-v2", "evidence_class": "local offline corpus analysis; not live or physical validation",
        "status": "consenting_single_rider_recurrence_analysis",
        "rider_identity": {"verified_distinct_riders": 1, "database_has_identity_mapping": False,
                           "authority": "Founder confirmed ownership and consent on 20 October 2026; all corpus rides are his own athlete/activities history"},
        "corpus_period": {"first_month": dates[0][:7], "last_month": dates[1][:7]},
        "counts": dict(sorted(counts.items())), "policy": POLICY,
        "classification_counts": {k: sum(s["class"] == k for s in spots) for k in ["mapped control", "likely unmapped control", "not a control", "unresolved"]},
        "spots": spots,
        "inputs": {"corpus_sha256": corpus_digest, "roads_export_sha256": sha256(roads),
                   "compiler_control_graph_sha256": sha256(controls_path),
                   "candidate_source_sha256": sha256(candidates_path),
                   "gate_diff_sha256": sha256(gate_diff), "gate_branch_sha": gate_branch_sha,
                   "registry_sha256": sha256(registry)},
        "limits": ["One consenting rider: recurrence is not independent population corroboration.",
                   "Only the Pennsylvania PBF is available; unmatched and ambiguous stops remain absent.",
                   "OSM and historical rides have different observation times; unmapped does not mean no physical control.",
                   "Published position uses five decimal places; gate checks use this rounded position, not private observations.",
                   "No-stop evidence cannot establish gate safety or lack of a control."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--roads", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    parser.add_argument("--pbf", type=Path, required=True)
    parser.add_argument("--finder-branch-sha", required=True)
    parser.add_argument("--gate-diff", type=Path, required=True)
    parser.add_argument("--gate-branch-sha", required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--topology-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    committed = subprocess.check_output(["git", "show", args.gate_branch_sha+":history/codex-reports-2026-10-20/gate-rule/DIFF.json"])
    if committed != args.gate_diff.read_bytes():
        raise ValueError("gate source does not match the pinned branch commit")
    result = analyze(args.corpus, args.roads, args.controls, args.gate_diff, args.gate_branch_sha, args.registry, args.candidates, args.topology_output)
    from tools.stop_map.gate_checks import assess, summary
    rows = assess(result["spots"], json.loads(args.registry.read_text()), json.loads(args.gate_diff.read_text()),
                  json.loads(args.candidates.read_text())["candidates"], json.loads(args.topology_output.read_text()))
    result["gate_assessment"] = summary(rows)
    result["inputs"].update(osm_pbf_sha256=sha256(args.pbf), public_topology_sha256=sha256(args.topology_output),
                            climb_finder_read_sha=args.finder_branch_sha)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n")
    print(json.dumps({"status": result["status"], "counts": result["counts"]}, sort_keys=True))


if __name__ == "__main__":
    main()
