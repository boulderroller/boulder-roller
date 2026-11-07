"""Public canon geometry checked against published aggregate spot positions."""
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely import from_wkb, from_wkt
from shapely.geometry import LineString, Point
from shapely.ops import substring

from tools.stop_map.stop_map import TO_XY, angle, check_gate_inventory


def xy_line(geom):
    p = np.asarray(geom.coords)
    return LineString(np.column_stack(TO_XY.transform(p[:, 0], p[:, 1])))


def relation(xy, heading, line_xy):
    line = LineString(line_xy)
    point = Point(xy)
    s = line.project(point)
    a, b = line.interpolate(max(0, s-1)), line.interpolate(min(line.length, s+1))
    tangent = np.array([b.x-a.x, b.y-a.y])
    norm = np.linalg.norm(tangent)
    if norm == 0:
        return None
    tangent /= norm
    projected = line.interpolate(s)
    delta = np.array([point.x-projected.x, point.y-projected.y])
    if s == 0 or s == line.length:
        s += float(delta @ tangent)
    lateral = abs(float(delta[0]*tangent[1]-delta[1]*tangent[0]))
    direction = math.degrees(math.atan2(tangent[0], tangent[1])) % 360
    if lateral > 12 or angle(heading, direction) > 45:
        return None
    return s, lateral, line.length


def same_gate_approach(way_id, source_ways, topology, spot_xy=None):
    if way_id in source_ways:
        return True
    from tools.stop_map.graph_context import same_layer
    ways = {int(k): v for k, v in topology["ways"].items()}
    members = topology.get("_members")
    if members is None:
        members = defaultdict(set)
        for way, row in ways.items():
            for node in row["nodes"]:
                members[node].add(way)
        topology["_members"] = members
    line = LineString(ways[way_id]["geometry"])
    s = line.project(Point(spot_xy)) if spot_xy is not None else line.length/2
    queue = [(way_id, ways[way_id]["nodes"][0], s), (way_id, ways[way_id]["nodes"][-1], line.length-s)]
    seen = {way_id}
    while queue:
        current, node, distance = queue.pop()
        if distance > 40:
            continue
        local = [w for w in members[node] if same_layer(ways[current]["tags"], ways[w]["tags"])]
        arms = set()
        for w in local:
            nodes = ways[w]["nodes"]
            for i, n in enumerate(nodes):
                if n == node:
                    arms.update(nodes[max(0, i-1):i] + nodes[i+1:i+2])
        choices = [w for w in local if w not in seen and node in (ways[w]["nodes"][0], ways[w]["nodes"][-1])]
        if len(arms) != 2 or len(choices) != 1:
            continue
        nxt = choices[0]
        if nxt in source_ways:
            return True
        seen.add(nxt)
        nodes = ways[nxt]["nodes"]
        far = nodes[-1] if nodes[0] == node else nodes[0]
        queue.append((nxt, far, distance+LineString(ways[nxt]["geometry"]).length))
    return False


def road_distance_to_gate(way_id, direction, xy, gate_xy, gate_heading, source_ways, topology, travel):
    """Actual public-road distance, walking with (+1) or against (-1) rider travel.

    No tangent extrapolation around bends. Crossing a branch or incompatible
    layer is ambiguous and stops the walk; unique way splits are traversed.
    """
    from tools.stop_map.graph_context import same_layer
    if math.dist(xy, gate_xy) > 42:
        return None
    if "_ways" not in topology:
        topology["_ways"] = {int(k): v for k, v in topology["ways"].items()}
    ways = topology["_ways"]
    if "_members" not in topology:
        members = defaultdict(set)
        for way, row in ways.items():
            for node in row["nodes"]:
                members[node].add(way)
        topology["_members"] = members
    members = topology["_members"]
    current, sign, travelled = way_id, direction*travel, 0.0
    line = LineString(ways[current]["geometry"])
    position = line.project(Point(xy))
    seen = set()
    while current not in seen and travelled <= 40:
        seen.add(current)
        row = ways[current]
        line = LineString(row["geometry"])
        remaining = line.length-position if sign == 1 else position
        # Respect interior branches as well as branches at way boundaries.
        chainage, barrier, target_is_shared_gate = 0.0, False, False
        for i, node in enumerate(row["nodes"]):
            if i:
                chainage += math.dist(row["geometry"][i-1], row["geometry"][i])
            ahead = (chainage-position)*sign
            if ahead < -.01 or ahead > remaining+.01 or travelled+ahead > 40:
                continue
            # The gate itself may sit on a shared junction node. Reaching that
            # node does not cross an intervening junction. Require an incident
            # canon way on the same layer and compatible travel at the gate.
            if math.dist(row["geometry"][i], gate_xy) <= .05 and any(
                other in source_ways and same_layer(row["tags"], ways[other]["tags"])
                for other in members[node]
            ):
                target_is_shared_gate = True
            arms = set()
            for other in members[node]:
                if not same_layer(row["tags"], ways[other]["tags"]):
                    continue
                nodes = ways[other]["nodes"]
                for j, n in enumerate(nodes):
                    if n == node:
                        arms.update(nodes[max(0, j-1):j]+nodes[j+1:j+2])
            if len(arms) > 2:
                remaining, barrier = min(remaining, max(0, ahead)), True
        target = Point(gate_xy)
        g = line.project(target)
        delta = (g-position)*sign
        if (current in source_ways or target_is_shared_gate) and line.distance(target) <= 3 and -.01 <= delta <= remaining+.01:
            a, b = line.interpolate(max(0, g-1)), line.interpolate(min(line.length, g+1))
            heading = (math.degrees(math.atan2(b.x-a.x, b.y-a.y)) + (180 if sign*travel == -1 else 0)) % 360
            if angle(heading, gate_heading) <= 45 and travelled+max(0, delta) <= 40:
                return travelled+max(0, delta)
        if barrier:
            return None
        travelled += remaining
        node = row["nodes"][-1 if sign == 1 else 0]
        local = [w for w in members[node] if same_layer(row["tags"], ways[w]["tags"])]
        arms = set()
        for way in local:
            nodes = ways[way]["nodes"]
            for i, n in enumerate(nodes):
                if n == node:
                    arms.update(nodes[max(0, i-1):i]+nodes[i+1:i+2])
        choices = [w for w in local if w not in seen and node in (ways[w]["nodes"][0], ways[w]["nodes"][-1])]
        if len(arms) != 2 or len(choices) != 1:
            return None
        current = choices[0]
        sign = 1 if ways[current]["nodes"][0] == node else -1
        position = 0.0 if sign == 1 else LineString(ways[current]["geometry"]).length
    return None


def assess(spots, registry, diff, candidates, topology):
    check_gate_inventory(diff, registry)
    by_id = {r["id"]: r for r in registry}
    by_fp = {c["candidate_fingerprint"]: c for c in candidates}
    rows = []
    for gate in diff["climbs"]:
        reg = by_id[gate["registry_id"]]
        source = by_fp[reg["candidate_fingerprint"]]
        original = xy_line(from_wkb(bytes.fromhex(reg["centerline_geom"])))
        for version in (["original", "moved"] if gate["finish_moved"] else ["original"]):
            line = original
            if version == "moved":
                centre = from_wkt(gate["new"]["gate_end_wkt"]).interpolate(.5, normalized=True)
                target = Point(TO_XY.transform(centre.x, centre.y))
                assert original.distance(target) < 1, "moved finish not on source centreline"
                line = substring(original, 0, original.project(target))
            row = {"registry_id": reg["id"], "canon_id": reg["canon_id"], "name": gate["name"],
                   "version": version, "line_xy": line, "starts": [], "finishes": [], "interior": [],
                   "nearby_other_way": [], "rounding_boundary": [], "downstream": []}
            start_xy, end_xy = line.coords[0], line.coords[-1]
            a, b = line.interpolate(0), line.interpolate(min(1, line.length))
            start_heading = math.degrees(math.atan2(b.x-a.x, b.y-a.y)) % 360
            a, b = line.interpolate(max(0, line.length-1)), line.interpolate(line.length)
            end_heading = math.degrees(math.atan2(b.x-a.x, b.y-a.y)) % 360
            source_ways = set(source["osm_way_refs"])
            for spot in spots:
                xy = TO_XY.transform(spot["position"]["lon"], spot["position"]["lat"])
                found = relation(xy, spot["direction"]["bearing_deg"], line.coords)
                s, lateral, length = found if found is not None else (None, None, line.length)
                item = {"spot_id": spot["spot_id"], "class": spot["class"],
                        "from_start_m": round(s, 1) if s is not None else None,
                        "past_finish_m": round(s-length, 1) if s is not None else None,
                        "lateral_m": round(lateral, 1) if lateral is not None else None}
                way = spot["osm_way_id"]
                direction = 1 if spot["direction"]["along_osm_way"] == "forward" else -1
                if found is not None and 0 < s < length and way in source_ways:
                    row["interior"].append(item.copy())
                past = road_distance_to_gate(way, direction, xy, end_xy, end_heading, source_ways, topology, -1)
                if found is not None and -16 <= s <= length+16 and past is None and way not in source_ways and not same_gate_approach(way, source_ways, topology, xy):
                    row["nearby_other_way"].append(item)
                if past is not None:
                    finish = dict(item, past_finish_m=round(past, 1))
                    row["downstream"].append(finish)
                    if past <= 15:
                        row["finishes"].append(finish)
                    if min(abs(past), abs(past-15)) <= .8:
                        row["rounding_boundary"].append(dict(finish, boundary="finish"))
                if version == "original":
                    before = road_distance_to_gate(way, direction, xy, start_xy, start_heading, source_ways, topology, 1)
                    after = road_distance_to_gate(way, direction, xy, start_xy, start_heading, source_ways, topology, -1)
                    delta = -before if before is not None else after
                    if delta is not None:
                        start = dict(item, from_start_m=round(delta, 1))
                        if abs(delta) <= 15:
                            row["starts"].append(start)
                        if abs(abs(delta)-15) <= .8:
                            row["rounding_boundary"].append(dict(start, boundary="start"))
            rows.append(row)
    assert len(rows) == 72 and sum(r["version"] == "original" for r in rows) == 57
    return rows


def load_assessment(results_path, registry_path, diff_path, candidates_path, topology_path, include_control_points=False):
    results = json.loads(Path(results_path).read_text())
    registry = json.loads(Path(registry_path).read_text())
    diff = json.loads(Path(diff_path).read_text())
    candidates = json.loads(Path(candidates_path).read_text())["candidates"]
    topology = json.loads(Path(topology_path).read_text())
    rows = assess(results["spots"], registry, diff, candidates, topology)
    if include_control_points:
        wanted = {s["matched_control"]["osm_node_id"] for s in results["spots"] if s["matched_control"]}
        points = {node: xy for way in topology["ways"].values() for node, xy in zip(way["nodes"], way["geometry"]) if node in wanted}
        return results, registry, diff, rows, points
    return results, registry, diff, rows


def summary(rows):
    return {
        "original_starts_checked": 57, "original_finishes_checked": 57, "moved_finishes_checked": 15,
        "original_start_flags": sum(bool(r["starts"]) for r in rows),
        "original_finish_flags": sum(bool(r["finishes"]) for r in rows if r["version"] == "original"),
        "moved_finish_flags": sum(bool(r["finishes"]) for r in rows if r["version"] == "moved"),
        "original_interior_spot_climb_pairs": sum(len(r["interior"]) for r in rows if r["version"] == "original"),
        "moved_span_interior_spot_climb_pairs": sum(len(r["interior"]) for r in rows if r["version"] == "moved"),
        "nearby_other_way_pairs": sum(len(r["nearby_other_way"]) for r in rows),
        "rounding_boundary_pairs": sum(len(r["rounding_boundary"]) for r in rows),
    }
