"""Decode the pinned compiler's public Debug graph, not OSM/PBF.

Only public map data are read here. The strict transport accepts the compiler's
Node/Way schema and checks the entire file, retaining only requested map IDs.
"""
from collections import defaultdict
import json
import math
import mmap
import re

TOKEN = re.compile(rb'\s*("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z_0-9]*|[{}\[\]:,])')
STRING = rb'"(?:[^"\\]|\\.)*"'
NUMBER = rb'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?'
TAGS = rb'\{\s*(?:' + STRING + rb'\s*:\s*' + STRING + rb'(?:\s*,\s*' + STRING + rb'\s*:\s*' + STRING + rb')*)?\s*\}'
BODIES = {
    b"Node": re.compile(rb'\s*\{\s*lat:\s*' + NUMBER + rb',\s*lon:\s*' + NUMBER + rb',\s*tags:\s*' + TAGS + rb'\s*\}'),
    b"Way": re.compile(rb'\s*\{\s*id:\s*-?\d+,\s*nodes:\s*\[\s*(?:-?\d+(?:,\s*-?\d+)*)?\s*\],\s*tags:\s*' + TAGS + rb'\s*\}'),
}


class DebugReader:
    def __init__(self, data):
        self.data, self.pos, self.cached = data, 0, None

    def peek(self):
        if self.cached is None:
            match = TOKEN.match(self.data, self.pos)
            if match is None:
                if self.data[self.pos:].strip():
                    raise ValueError("unsupported compiler Debug syntax")
                return b""
            self.cached = match.group(1)
            self.pos = match.end()
        return self.cached

    def pop(self, expected=None):
        token = self.peek()
        if expected is not None and token != expected:
            raise ValueError(f"compiler Debug schema changed; expected {expected!r}")
        self.cached = None
        return token

    def value(self):
        token = self.pop()
        if token in {b"Node", b"Way"}:
            value = self.mapping()
            fields = {"lat", "lon", "tags"} if token == b"Node" else {"id", "nodes", "tags"}
            if set(value) != fields:
                raise ValueError("compiler graph object schema changed")
            return value
        if token == b"{":
            return dict(self.entries(opened=True))
        if token == b"[":
            values = []
            while self.peek() != b"]":
                values.append(self.value())
                if self.peek() != b"]":
                    self.pop(b",")
            self.pop(b"]")
            return values
        if token.startswith(b'"'):
            # Rust Debug emits Unicode scalars as \u{...} for some controls.
            def escape(match):
                value = match[0]
                if value == b"\\0":
                    return b"\\u0000"
                if value.startswith(b"\\u{"):
                    return json.dumps(chr(int(value[3:-1], 16)))[1:-1].encode()
                return value
            raw = re.sub(rb'\\(?:\\|"|n|r|t|0|u\{[0-9a-fA-F]+\})', escape, token)
            return json.loads(raw)
        if re.fullmatch(rb'-?\d+', token):
            return int(token)
        if re.fullmatch(rb'-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', token):
            value = float(token)
            if not math.isfinite(value):
                raise ValueError("nonfinite compiler coordinate")
            return value
        if token in {b"lat", b"lon", b"tags", b"id", b"nodes"}:
            return token.decode()
        raise ValueError("unsupported compiler Debug value")

    def entries(self, opened=False):
        if not opened:
            self.pop(b"{")
        while self.peek() != b"}":
            key = self.value()
            self.pop(b":")
            yield key, self.value()
            if self.peek() != b"}":
                self.pop(b",")
        self.pop(b"}")

    def mapping(self):
        entries = list(self.entries())
        if len(dict(entries)) != len(entries):
            raise ValueError("duplicate compiler fields")
        return dict(entries)

    def selected_entries(self, ids, kind):
        self.pop(b"{")
        while self.peek() != b"}":
            key = self.value()
            self.pop(b":"); self.pop(kind)
            match = BODIES[kind].match(self.data, self.pos)
            if match is None:
                raise ValueError("compiler graph object syntax/schema changed")
            if key in ids:
                # Decode only retained public-map objects. Every skipped body
                # still matches the full pinned grammar, including quoted tags.
                yield key, DebugReader(kind + match[0]).value()
            self.pos = match.end()
            if self.peek() != b"}":
                self.pop(b",")
        self.pop(b"}")


def read_control_graph(path, wanted_ways, wanted_nodes):
    result = {}
    with open(path, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        reader = DebugReader(data)
        reader.pop(b"FinishControlGraph"); reader.pop(b"{")
        for name, ids in [("nodes", wanted_nodes), ("ways", wanted_ways)]:
            reader.pop(name.encode()); reader.pop(b":")
            result[name] = dict(reader.selected_entries(ids, b"Node" if name == "nodes" else b"Way"))
            reader.pop(b",")
        reader.pop(b"junctions"); reader.pop(b":"); reader.pop(b"{")
        result["junctions"] = set()
        while reader.peek() != b"}":
            node_id = reader.value()
            if node_id in wanted_nodes:
                result["junctions"].add(node_id)
            if reader.peek() != b"}":
                reader.pop(b",")
        reader.pop(b"}"); reader.pop(b",")
        reader.pop(b"stop_lines"); reader.pop(b":")
        result["stop_lines"] = reader.value()
        reader.pop(b"}")
        if reader.peek():
            raise ValueError("trailing compiler Debug content")
    if set(result["ways"]) != wanted_ways or set(result["nodes"]) != wanted_nodes:
        raise ValueError("compiler graph missing requested road/node IDs")
    return result


def control_kind(tags):
    if tags.get("highway") == "traffic_signals":
        return "traffic_signals"
    if tags.get("crossing") == "traffic_signals" or tags.get("crossing:signals") == "yes":
        return "signalled_crossing"
    if tags.get("railway") in {"level_crossing", "crossing", "tram_level_crossing"}:
        return "rail"
    if tags.get("highway") == "stop":
        return "all_way_stop" if tags.get("stop") == "all" else "stop"
    if tags.get("highway") == "give_way":
        return "give_way"
    return None


def control_direction(tags, kind):
    value = next((tags[k] for k in ["direction", "stop:direction", "give_way:direction", "traffic_signals:direction"] if k in tags), "")
    if value == "forward":
        return 1, False
    if value == "backward":
        return -1, False
    if value == "both" or kind == "all_way_stop":
        return 0, False
    if not value and kind in {"traffic_signals", "signalled_crossing", "rail"}:
        return 0, False
    return None, True


def same_layer(a, b):
    return all(a.get(k, "0" if k == "layer" else "") == b.get(k, "0" if k == "layer" else "")
               for k in ["layer", "bridge", "tunnel"])


class GraphContext:
    def __init__(self, graph, index):
        self.graph = graph
        self.rows = {r["osm_way_id"]: r for r in index.rows}
        self.lines = dict(zip(self.rows, index.lines))
        self.memberships = defaultdict(set)
        self.chainages = {}
        self.arms = defaultdict(dict)
        for way, row in self.rows.items():
            points = row["geometry"]
            along = [0.0]
            for a, b in zip(points, points[1:]):
                along.append(along[-1] + math.dist(a, b))
            self.chainages[way] = list(zip(row["osm_node_ids"], along))
            for i, node in enumerate(row["osm_node_ids"]):
                self.memberships[node].add(way)
                self.arms[node][way] = set(row["osm_node_ids"][max(0, i-1):i] + row["osm_node_ids"][i+1:i+2])

    def junction_ids_for_way(self, way):
        result = set(self.graph["junctions"])
        for node, _ in self.chainages[way]:
            arms = set().union(*(neighbors for other, neighbors in self.arms[node].items()
                                 if same_layer(self.graph["ways"][way]["tags"], self.graph["ways"][other]["tags"])))
            if len(arms) >= 3:
                result.add(node)
        return result

    def junctions_for_way(self, way):
        ids = self.junction_ids_for_way(way)
        return [s for node, s in self.chainages[way] if node in ids]

    def public_topology(self):
        return {"ways": {str(way): {"nodes": row["osm_node_ids"], "geometry": row["geometry"],
                                    "tags": self.graph["ways"][way]["tags"]}
                         for way, row in self.rows.items()}}

    def approach(self, spot):
        """Linearized local chain: same way plus unique same-layer continuations.

        Stop at real junctions/branches. Controls on the junction itself count;
        controls on a crossing road or beyond the junction do not.
        """
        from tools.stop_map.stop_map import Control
        controls, junctions, ambiguous = [], [], []
        origin = spot.way_id
        segments = [(origin, 1, 0.0)]  # origin chainage = sign * local + offset
        seen = {origin}
        for travel in [-1, 1]:
            current, sign, offset = origin, 1, 0.0
            for _ in range(12):
                nodes = self.chainages[current]
                forward = travel * sign > 0
                node, s = nodes[-1] if forward else nodes[0]
                at = sign * s + offset
                if abs(at - spot.along_m) > 40 or node in self.junction_ids_for_way(current):
                    break
                choices = [w for w in self.memberships[node] if w not in seen
                           and same_layer(self.graph["ways"][current]["tags"], self.graph["ways"][w]["tags"])
                           and node in (self.chainages[w][0][0], self.chainages[w][-1][0])]
                if len(choices) != 1:
                    break
                nxt = choices[0]
                local = self.chainages[nxt]
                entry = 0.0 if local[0][0] == node else local[-1][1]
                sign = travel if entry == 0 else -travel
                offset = at - sign * entry
                segments.append((nxt, sign, offset)); seen.add(nxt); current = nxt
        for way, sign, offset in segments:
            junction_ids = self.junction_ids_for_way(way)
            for node, local in self.chainages[way]:
                s = sign * local + offset
                if abs(s - spot.along_m) > 40:
                    continue
                if node in junction_ids:
                    junctions.append(s)
                tags = self.graph["nodes"][node]["tags"]
                kind = control_kind(tags)
                if kind is None:
                    continue
                direction, uncertain = control_direction(tags, kind)
                if uncertain:
                    ambiguous.append(s)
                else:
                    # 0 means applicable to both directions, already resolved.
                    facing = spot.direction if direction == 0 else direction * sign
                    controls.append(Control(node, origin, s, kind, facing))
        junctions = sorted(set(junctions))
        ambiguous = [s for s in ambiguous if (s-spot.along_m)*spot.direction >= -5
                     and not any(min(s, spot.along_m) < j < max(s, spot.along_m) for j in junctions)]
        return controls, junctions, bool(ambiguous)
