//! D7.5 finish setbacks. Offline OSM topology, never a spatial guess about a
//! sign on a crossing road. Applied after ratified boundaries and gate widths.

use super::*;
use std::collections::BTreeMap;
use std::path::Path;

const AT_JUNCTION_M: f64 = 12.0; // Same gate-at-junction window as the ratified census.
const ADJACENT_M: f64 = 30.0;
const SETBACK_M: f64 = 27.0;
const CONTROL_CLEARANCE_M: f64 = 15.0;
const SNAP_LAST_SEGMENT_M: f64 = 1.0;
const DECISIONS_PATH: &str = "workout-parse/resources/philly_finish_gate_decisions_v1.json";

#[derive(Deserialize)]
struct FinishDecisions {
    authority: String,
    approved_by: String,
    approved_on: String,
    approval_quote: String,
    position_approval_authority: String,
    clearance_interpretation: Value,
    decisions: Vec<FinishDecision>,
}

#[derive(Deserialize)]
struct FinishDecision {
    candidate_fingerprint: String,
    display_name: String,
    unknown_direction_stop_node_ids: Vec<i64>,
    junction_node_id: i64,
    approved_position: ApprovedPosition,
    covering_note: Option<CoveringNote>,
    start_gate_revision: Option<Value>,
    stop_evidence_amendment: Option<StopEvidenceAmendment>,
}

#[derive(Deserialize, Serialize)]
struct StopEvidenceAmendment {
    approved_by: String,
    approved_on: String,
    approval_quote: String,
    authority: String,
    requested_setback_m: f64,
    previous_approved_position: ApprovedPosition,
    source: Value,
    spot: StopSpot,
    clearance_note: String,
}

#[derive(Deserialize, Serialize)]
struct StopSpot {
    osm_way_id: i64,
    position: StopPosition,
    #[serde(flatten)]
    aggregate: BTreeMap<String, Value>,
}

#[derive(Deserialize, Serialize)]
struct StopPosition {
    lat: f64,
    lon: f64,
}

#[derive(Deserialize, Serialize)]
struct ApprovedPosition {
    lat: f64,
    lon: f64,
    setback_from_junction_m: f64,
}

#[derive(Deserialize, Serialize)]
struct CoveringNote {
    authority: String,
    note: String,
    position: ApprovedPosition,
}

fn decisions() -> &'static FinishDecisions {
    static VALUE: std::sync::OnceLock<FinishDecisions> = std::sync::OnceLock::new();
    VALUE.get_or_init(|| {
        serde_json::from_str(include_str!(
            "../../resources/philly_finish_gate_decisions_v1.json"
        ))
        .expect("tracked finish decisions must be valid")
    })
}

fn admitted(c: &CanonCandidate) -> Option<&'static FinishDecision> {
    decisions().decisions.iter().find(|d| {
        d.candidate_fingerprint == c.candidate_fingerprint && d.display_name == c.display_name
    })
}

fn approved_finish(d: &FinishDecision, junction: i64, point: &CanonProfilePoint) -> bool {
    let near = |p: &ApprovedPosition| haversine_m(p.lat, p.lon, point.lat, point.lon) <= 0.5;
    d.junction_node_id == junction
        && (near(&d.approved_position)
            || d.covering_note
                .as_ref()
                .is_some_and(|n| !n.note.trim().is_empty() && near(&n.position)))
}

fn unchanged_for_review(c: &CanonCandidate, reason: &str) -> CanonCandidate {
    let mut out = c.clone();
    out.low_confidence_flags
        .push("finish_rule_unresolved".into());
    out.low_confidence_flags.sort();
    out.low_confidence_flags.dedup();
    out.confidence = "needs_review".into();
    out.provenance["finish_rule_unresolved"] = json!({
        "status":"finish rule unresolved", "reason":format!("finish rule: {}: {reason}", c.display_name),
        "geometry_unchanged":true,
    });
    out
}

type Tags = BTreeMap<String, String>;

#[derive(Debug, Clone)]
struct Node {
    lat: f64,
    lon: f64,
    tags: Tags,
}

#[derive(Debug, Clone)]
struct Way {
    id: i64,
    nodes: Vec<i64>,
    tags: Tags,
}

#[derive(Debug, Default)]
pub struct FinishControlGraph {
    nodes: BTreeMap<i64, Node>,
    ways: BTreeMap<i64, Way>,
    junctions: BTreeSet<i64>,
    stop_lines: Vec<Way>,
}

fn tag<'a>(tags: &'a Tags, key: &str) -> &'a str {
    tags.get(key).map(String::as_str).unwrap_or("")
}

fn stop_line(tags: &Tags) -> bool {
    matches!(tag(tags, "road_marking"), "stop_line" | "solid_stop_line")
        || tag(tags, "highway") == "stop_line"
}

fn road(tags: &Tags) -> bool {
    matches!(
        tag(tags, "highway"),
        "primary"
            | "primary_link"
            | "secondary"
            | "secondary_link"
            | "tertiary"
            | "tertiary_link"
            | "unclassified"
            | "residential"
            | "living_street"
            | "service"
            | "road"
            | "trunk"
            | "trunk_link"
            | "cycleway"
    ) || !tag(tags, "railway").is_empty()
}

/// Read the same PBF as the compiler. Keep only selected ways, their junctions,
/// and mapped stop lines. Both ordinary and dense PBF nodes are supported.
pub fn read_finish_control_graph(
    pbf: &Path,
    candidates: &[CanonCandidate],
) -> Result<FinishControlGraph, String> {
    use osmpbf::{Element, ElementReader};
    let wanted: BTreeSet<_> = candidates
        .iter()
        .flat_map(|c| c.osm_way_refs.iter().copied())
        .collect();
    let mut graph = FinishControlGraph::default();
    let mut others = Vec::new();
    ElementReader::from_path(pbf)
        .map_err(|e| e.to_string())?
        .for_each(|element| {
            if let Element::Way(w) = element {
                let tags: Tags = w.tags().map(|(k, v)| (k.into(), v.into())).collect();
                if wanted.contains(&w.id()) || road(&tags) || stop_line(&tags) {
                    let way = Way {
                        id: w.id(),
                        nodes: w.refs().collect(),
                        tags,
                    };
                    if wanted.contains(&way.id) {
                        graph.ways.insert(way.id, way);
                    } else if stop_line(&way.tags) {
                        graph.stop_lines.push(way);
                    } else {
                        others.push(way);
                    }
                }
            }
        })
        .map_err(|e| e.to_string())?;
    for id in &wanted {
        if !graph.ways.contains_key(id) {
            return Err(format!("finish rule: OSM way {id} missing from extract"));
        }
    }
    let mut memberships: BTreeMap<i64, Vec<&Way>> = BTreeMap::new();
    for way in graph.ways.values() {
        for id in &way.nodes {
            memberships.entry(*id).or_default().push(way);
        }
    }
    for way in graph.ways.values().chain(others.iter()) {
        for id in &way.nodes {
            if let Some(own) = memberships.get(id) {
                if own.iter().any(|o| {
                    o.id != way.id
                        && same_layer(&o.tags, &way.tags)
                        && tag(&o.tags, "name").trim().to_lowercase()
                            != tag(&way.tags, "name").trim().to_lowercase()
                }) {
                    graph.junctions.insert(*id);
                }
            }
        }
    }
    let needed: BTreeSet<_> = memberships
        .keys()
        .copied()
        .chain(
            graph
                .stop_lines
                .iter()
                .flat_map(|w| w.nodes.iter().copied()),
        )
        .collect();
    drop(others);
    ElementReader::from_path(pbf)
        .map_err(|e| e.to_string())?
        .for_each(|element| {
            let item = match element {
                Element::Node(n) if needed.contains(&n.id()) => Some((
                    n.id(),
                    Node {
                        lat: n.lat(),
                        lon: n.lon(),
                        tags: n.tags().map(|(k, v)| (k.into(), v.into())).collect(),
                    },
                )),
                Element::DenseNode(n) if needed.contains(&n.id) => Some((
                    n.id,
                    Node {
                        lat: n.lat(),
                        lon: n.lon(),
                        tags: n.tags().map(|(k, v)| (k.into(), v.into())).collect(),
                    },
                )),
                _ => None,
            };
            if let Some((id, node)) = item {
                graph.nodes.insert(id, node);
            }
        })
        .map_err(|e| e.to_string())?;
    for id in needed {
        if !graph.nodes.contains_key(&id) {
            return Err(format!("finish rule: OSM node {id} missing from extract"));
        }
    }
    Ok(graph)
}

fn layer(tags: &Tags) -> i32 {
    tags.get("layer")
        .and_then(|v| v.parse::<i32>().ok())
        .unwrap_or(0)
}

fn same_layer(a: &Tags, b: &Tags) -> bool {
    layer(a) == layer(b)
        && tag(a, "bridge") == tag(b, "bridge")
        && tag(a, "tunnel") == tag(b, "tunnel")
}

/// Atomic: if a setback cannot produce a valid climb, no candidate is changed.
pub fn apply_finish_gate_rule(
    candidates: &mut Vec<CanonCandidate>,
    graph: &FinishControlGraph,
) -> Result<(), String> {
    let updated = candidates
        .iter()
        .map(|c| match adjust(c, graph) {
            Ok(out) => Ok(out),
            Err(error) if error.contains("ambiguous") => Ok(unchanged_for_review(c, &error)),
            Err(error) => Err(format!("finish rule: {}: {error}", c.display_name)),
        })
        .collect::<Result<Vec<_>, _>>()?;
    validate_candidate_fingerprint_ownership(&updated)?;
    *candidates = updated;
    Ok(())
}

fn locate(node: &Node, points: &[CanonProfilePoint]) -> Result<(f64, f64), String> {
    // Distance alone is unambiguous even on a loop. Ignore off-span controls
    // before asking which progress value they belong to. Include only the
    // straight continuation needed by controls up to 30m beyond a qualifying
    // junction. The junction itself still has its separate 12m span bound.
    let x_scale = 111_320.0 * node.lat.to_radians().cos().abs().max(0.1);
    let offset = points
        .windows(2)
        .enumerate()
        .map(|(i, segment)| {
            let a = &segment[0];
            let b = &segment[1];
            let x = (a.lon - node.lon) * x_scale;
            let y = (a.lat - node.lat) * 111_320.0;
            let dx = (b.lon - a.lon) * x_scale;
            let dy = (b.lat - a.lat) * 111_320.0;
            let norm = dx.hypot(dy);
            if norm <= f64::EPSILON {
                return x.hypot(y);
            }
            let max_ratio = if i + 2 == points.len() {
                1.0 + (AT_JUNCTION_M + ADJACENT_M) / norm
            } else {
                1.0
            };
            let t = (-(x * dx + y * dy) / norm.powi(2)).clamp(0.0, max_ratio);
            (x + t * dx).hypot(y + t * dy)
        })
        .fold(f64::INFINITY, f64::min);
    if offset > 1.0 {
        return Ok((0.0, offset));
    }
    let anchor = RatifiedBoundaryAnchor {
        label: String::new(),
        osm_node_id: None,
        lat: node.lat,
        lon: node.lon,
        max_offset_m: ADJACENT_M,
        exact_gate: None,
    };
    let p = project_anchor_onto_profile(&anchor, points)
        .map_err(|_| "finish rule: ambiguous control projection")?
        .ok_or("finish rule: empty centerline")?;
    // Permit an OSM junction just beyond a sampled endpoint, without treating
    // the clamped projection as the junction centre.
    let last = points.last().unwrap();
    if (p.along_m - last.dist_m).abs() < 0.001 {
        let prior = &points[points.len() - 2];
        let x = 111_320.0 * last.lat.to_radians().cos();
        let dx = (last.lon - prior.lon) * x;
        let dy = (last.lat - prior.lat) * 111_320.0;
        let nx = (node.lon - last.lon) * x;
        let ny = (node.lat - last.lat) * 111_320.0;
        let norm = dx.hypot(dy);
        if norm > 0.0 {
            let along = (nx * dx + ny * dy) / norm;
            if along > 0.0 {
                return Ok((last.dist_m + along, (nx * dy - ny * dx).abs() / norm));
            }
        }
    }
    Ok((p.along_m, p.offset_m))
}

fn control_kind(
    c: &CanonCandidate,
    graph: &FinishControlGraph,
    way: &Way,
    id: i64,
    junction: i64,
    points: &[CanonProfilePoint],
    pos: f64,
) -> Option<&'static str> {
    let node = &graph.nodes[&id];
    if tag(&node.tags, "highway") == "traffic_signals" {
        return Some("traffic_signals");
    }
    if tag(&node.tags, "crossing") == "traffic_signals" {
        return Some("crossing=traffic_signals");
    }
    if matches!(
        tag(&node.tags, "railway"),
        "level_crossing" | "crossing" | "tram_level_crossing"
    ) {
        return Some("rail_crossing");
    }
    let kind = tag(&node.tags, "highway");
    if !matches!(kind, "stop" | "give_way") {
        return None;
    }
    if kind == "stop" && tag(&node.tags, "stop") == "all" {
        return Some("all_way_stop");
    }
    // A missing direction needs an exact tracked decision; it never inherits
    // the way's default direction or another candidate's approval.
    if kind == "stop"
        && id == junction
        && admitted(c).is_some_and(|d| d.unknown_direction_stop_node_ids.contains(&id))
        && ["direction", "stop:direction", "stop"]
            .iter()
            .all(|k| tag(&node.tags, k).is_empty())
    {
        return Some("stop_ratified_direction_unknown");
    }
    let direction = node
        .tags
        .get("direction")
        .or_else(|| node.tags.get("stop:direction"))
        .or_else(|| node.tags.get("give_way:direction"))
        .map(String::as_str)
        .unwrap_or("");
    if direction == "both" {
        return Some(if kind == "stop" { "stop" } else { "give_way" });
    }
    if !matches!(direction, "forward" | "backward") {
        return None;
    }
    let i = way.nodes.iter().position(|n| *n == id)?;
    let a = &graph.nodes[&way.nodes[i.saturating_sub(1)]];
    let b = &graph.nodes[&way.nodes[(i + 1).min(way.nodes.len() - 1)]];
    let k = points
        .partition_point(|p| p.dist_m < pos)
        .clamp(1, points.len() - 1);
    let ca = &points[k - 1];
    let cb = &points[k];
    let cos = node.lat.to_radians().cos();
    let dot = (b.lon - a.lon) * (cb.lon - ca.lon) * cos * cos + (b.lat - a.lat) * (cb.lat - ca.lat);
    if dot.abs() <= f64::EPSILON {
        return None;
    }
    if (dot > 0.0) == (direction == "forward") {
        Some(if kind == "stop" { "stop" } else { "give_way" })
    } else {
        None
    }
}

fn is_control(tags: &Tags) -> bool {
    matches!(
        tag(tags, "highway"),
        "traffic_signals" | "stop" | "give_way"
    ) || tag(tags, "crossing") == "traffic_signals"
        || matches!(
            tag(tags, "railway"),
            "level_crossing" | "crossing" | "tram_level_crossing"
        )
}

fn source_points(c: &CanonCandidate) -> Result<Vec<CanonProfilePoint>, String> {
    let Some(value) = c.provenance.get("compiler_profile_points") else {
        return Err(
            "unrounded compiler profile is unavailable; rebuild the local source profile".into(),
        );
    };
    let mut points: Vec<CanonProfilePoint> = serde_json::from_value(value.clone())
        .map_err(|e| format!("invalid unrounded compiler profile: {e}"))?;
    if points.len() != c.canonical_profile.len()
        || points.len() < 2
        || line_string_wkt(&points) != c.centerline_wkt
        || points.iter().zip(&c.canonical_profile).any(|(p, s)| {
            !p.lat.is_finite()
                || !p.lon.is_finite()
                || !p.elev_m.is_finite()
                || round2(p.elev_m) != s.elev_m
        })
    {
        return Err("unaligned unrounded centerline/profile".into());
    }
    rebase_distances(&mut points);
    Ok(points)
}

fn adjust(c: &CanonCandidate, graph: &FinishControlGraph) -> Result<CanonCandidate, String> {
    let mut points = source_points(c)?;
    let old_points = points.clone();
    let end = points.last().unwrap();
    let own: Vec<_> = c
        .osm_way_refs
        .iter()
        .map(|id| {
            graph
                .ways
                .get(id)
                .ok_or_else(|| format!("missing way {id}"))
        })
        .collect::<Result<_, _>>()?;
    let mut junctions: Vec<_> = own
        .iter()
        .flat_map(|w| w.nodes.iter())
        .copied()
        .filter(|id| graph.junctions.contains(id))
        // Cheap search bound only. The 12m admission window is along the
        // actual span below; a nearby unused arm cannot qualify.
        .filter(|id| {
            let n = &graph.nodes[id];
            haversine_m(n.lat, n.lon, end.lat, end.lon) <= ADJACENT_M
        })
        .collect();
    junctions.sort_by(|a, b| {
        let distance = |id| {
            let n = &graph.nodes[id];
            haversine_m(n.lat, n.lon, end.lat, end.lon)
        };
        distance(a).total_cmp(&distance(b)).then(a.cmp(b))
    });
    junctions.dedup();
    let mut chosen = None;
    for junction in junctions {
        let j = &graph.nodes[&junction];
        let mut nearby = Vec::new();
        for way in &own {
            let Some(ji) = way.nodes.iter().position(|id| *id == junction) else {
                continue;
            };
            for (i, id) in way.nodes.iter().enumerate() {
                let n = &graph.nodes[id];
                // Tags first: projecting an untagged cul-de-sac vertex can
                // be ambiguous even though it has no timing significance.
                if !is_control(&n.tags) && !stop_line(&n.tags) {
                    continue;
                }
                let distance: f64 = way.nodes[i.min(ji)..=i.max(ji)]
                    .windows(2)
                    .map(|pair| {
                        let a = &graph.nodes[&pair[0]];
                        let b = &graph.nodes[&pair[1]];
                        haversine_m(a.lat, a.lon, b.lat, b.lon)
                    })
                    .sum();
                if distance > ADJACENT_M {
                    continue;
                }
                nearby.push((*way, *id));
            }
        }
        if nearby.is_empty() {
            continue;
        }
        let (junction_s, lateral) = locate(j, &points)?;
        if lateral > 1.0 || junction_s > end.dist_m + AT_JUNCTION_M {
            continue;
        }
        if end.dist_m - junction_s > AT_JUNCTION_M {
            continue;
        }
        let mut controls = BTreeMap::new();
        let mut stop_positions = BTreeMap::new();
        for (way, id) in nearby {
            let n = &graph.nodes[&id];
            let (s, lateral) = locate(n, &points)?;
            if lateral > 1.0 {
                continue;
            }
            if let Some(kind) = control_kind(c, graph, way, id, junction, &points, s) {
                controls.insert(
                    id,
                    json!({"node_id":id,"kind":kind,"lat":n.lat,
                    "lon":n.lon,"along_m":s,"tags":n.tags}),
                );
                if tag(&n.tags, "highway") == "stop" && s < junction_s - 1.0 {
                    stop_positions.insert(format!("node/{id}"), s);
                }
            }
            if stop_line(&n.tags) && s <= junction_s {
                stop_positions.insert(format!("node/{id}"), s);
            }
        }
        if !controls.is_empty() {
            chosen = Some((junction, junction_s, controls, stop_positions));
            break;
        }
    }
    let Some((junction, junction_s, mut controls, mut stop_positions)) = chosen else {
        return Ok(c.clone());
    };
    let j = &graph.nodes[&junction];
    // Paint is usually a separate way crossing the approach. Require a real
    // intersection with its centreline, not mere proximity to another arm.
    for line in &graph.stop_lines {
        if !own
            .iter()
            .any(|way| way.nodes.contains(&junction) && layer(&way.tags) == layer(&line.tags))
        {
            continue;
        }
        for ids in line.nodes.windows(2) {
            let a = &graph.nodes[&ids[0]];
            let b = &graph.nodes[&ids[1]];
            for seg in points.windows(2) {
                let ax = a.lon - seg[0].lon;
                let ay = a.lat - seg[0].lat;
                let bx = b.lon - a.lon;
                let by = b.lat - a.lat;
                let cx = seg[1].lon - seg[0].lon;
                let cy = seg[1].lat - seg[0].lat;
                let det = cx * by - cy * bx;
                if det.abs() < 1e-18 {
                    continue;
                }
                let u = (ax * by - ay * bx) / det;
                let v = (ax * cy - ay * cx) / det;
                if (0.0..=1.0).contains(&u) && (0.0..=1.0).contains(&v) {
                    let s = seg[0].dist_m + u * (seg[1].dist_m - seg[0].dist_m);
                    stop_positions.insert(format!("way/{}/segment/{}", line.id, ids[0]), s);
                }
            }
        }
    }
    let mut target = stop_positions
        .values()
        .filter(|s| (0.0..=ADJACENT_M).contains(&(junction_s - **s)))
        .fold(junction_s - SETBACK_M, |s, stop| {
            s.min(stop - CONTROL_CLEARANCE_M)
        });
    target = controls.values().fold(target, |s, control| {
        s.min(control["along_m"].as_f64().unwrap() - CONTROL_CLEARANCE_M)
    });
    // Only the exact admitted predecessor/junction can use its consented
    // aggregate stop. It is additional clearance evidence, not an OSM tag.
    let stop_evidence = admitted(c)
        .filter(|d| d.junction_node_id == junction)
        .and_then(|d| d.stop_evidence_amendment.as_ref());
    let mut observed_stop_s = None;
    if let Some(amendment) = stop_evidence {
        let spot = &amendment.spot;
        let (s, lateral) = locate(
            &Node {
                lat: spot.position.lat,
                lon: spot.position.lon,
                tags: Tags::new(),
            },
            &points,
        )?;
        if !c.osm_way_refs.contains(&spot.osm_way_id)
            || lateral > 1.0
            || !(0.0..=ADJACENT_M).contains(&(junction_s - s))
            || !amendment.requested_setback_m.is_finite()
            || amendment.requested_setback_m < SETBACK_M
        {
            return Ok(unchanged_for_review(
                c,
                "approved aggregate stop is not on its junction approach",
            ));
        }
        target = target
            .min(junction_s - amendment.requested_setback_m)
            .min(s - CONTROL_CLEARANCE_M);
        observed_stop_s = Some(s);
    }
    // Retesting the cut must include own-span controls outside the initial
    // junction's 30m trigger window (e.g. Rising Sun Avenue).
    let mut along_controls = BTreeMap::new();
    for way in &own {
        for id in &way.nodes {
            let n = &graph.nodes[id];
            if !is_control(&n.tags) && !stop_line(&n.tags) {
                continue;
            }
            let (s, lateral) = locate(n, &points)?;
            if lateral > 1.0 || s > end.dist_m + 0.001 {
                continue;
            }
            if let Some(kind) = control_kind(c, graph, way, *id, junction, &points, s) {
                along_controls.insert(
                    *id,
                    json!({"node_id":id,"kind":kind,"lat":n.lat,
                    "lon":n.lon,"along_m":s,"tags":n.tags}),
                );
            }
            if stop_line(&n.tags) {
                stop_positions.insert(format!("node/{id}"), s);
            }
        }
    }
    loop {
        let prior = target;
        for (id, control) in &along_controls {
            let s = control["along_m"].as_f64().unwrap();
            if (s - target).abs() <= CONTROL_CLEARANCE_M + 1e-7 {
                target = target.min(s - CONTROL_CLEARANCE_M);
                controls.insert(*id, control.clone());
            }
        }
        for s in stop_positions.values() {
            if (s - target).abs() <= CONTROL_CLEARANCE_M + 1e-7 {
                target = target.min(s - CONTROL_CLEARANCE_M);
            }
        }
        // Only a kept upstream vertex can remove a tiny final segment
        // without moving the gate back into its required clearance.
        // A run of short vertices must not leave the gate tangent on a
        // different segment after snapping to the nearest upstream vertex.
        while let Some(p) = points.iter().rev().find(|p| p.dist_m < target - 1e-9) {
            if target - p.dist_m >= SNAP_LAST_SEGMENT_M {
                break;
            }
            target = p.dist_m;
        }
        if prior - target < 1e-9 {
            break;
        }
    }
    if target >= end.dist_m {
        return Ok(c.clone());
    }
    if target < DEFAULT_MIN_LENGTH_M {
        return Ok(unchanged_for_review(
            c,
            "finish rule would leave climb below minimums",
        ));
    }
    let k = points
        .partition_point(|p| p.dist_m < target)
        .clamp(1, points.len() - 1);
    let (a, b) = (&points[k - 1], &points[k]);
    let ratio = (target - a.dist_m) / (b.dist_m - a.dist_m);
    let endpoint = CanonProfilePoint {
        dist_m: target,
        lat: a.lat + (b.lat - a.lat) * ratio,
        lon: a.lon + (b.lon - a.lon) * ratio,
        elev_m: a.elev_m + (b.elev_m - a.elev_m) * ratio,
    };
    let old_length = end.dist_m;
    points.truncate(k);
    points.push(endpoint);
    rebase_distances(&mut points);
    let length = points.last().unwrap().dist_m;
    let rise = net_rise_m(&points).unwrap();
    if length < DEFAULT_MIN_LENGTH_M || rise < DEFAULT_MIN_VERT_M {
        return Ok(unchanged_for_review(
            c,
            "finish rule would leave climb below minimums",
        ));
    }
    let mut out = c.clone();
    let half_width = DEFAULT_GATE_HALF_WIDTH_M;
    out.gate_end_wkt = gate_wkt(&points, points.len() - 1, DEFAULT_GATE_HALF_WIDTH_M);
    out.gate_end_wkt = resize_symmetric_gate(&out.gate_end_wkt, half_width)?;
    out.centerline_wkt = line_string_wkt(&points);
    out.centerline_polyline = encode_polyline(
        &points.iter().map(|p| (p.lat, p.lon)).collect::<Vec<_>>(),
        5,
    );
    out.corridor_wkt = corridor_envelope_wkt(&points, c.corridor_half_width_m);
    out.corridor_cells = corridor_cells(&points, c.corridor_half_width_m);
    out.canonical_profile = points
        .iter()
        .map(|p| CanonProfileSample {
            dist_m: round2(p.dist_m),
            elev_m: round2(p.elev_m),
        })
        .collect();
    out.length_m = round2(length);
    out.vert_m = round2(rise);
    out.avg_gradient_pct = round3(100.0 * rise / length);
    out.max_gradient_pct = round3(max_gradient_pct(&points));
    out.provenance["compiler_profile_points"] = json!(points);
    out.candidate_fingerprint = candidate_fingerprint(&c.osm_way_refs, &points);
    out.provenance["candidate_fingerprint"] = json!({
        "algorithm": "blake3_way_refs_geometry_sketch_v3",
        "geometry_samples": FINGERPRINT_GEOMETRY_SAMPLES,
        "coordinate_grid_degrees": 1.0 / FINGERPRINT_COORD_GRID_SCALE,
        "legacy_v2_value": legacy_candidate_fingerprint_v2(&c.osm_way_refs, &points)
    });
    let exact_start: Option<RatifiedBoundaryGate> =
        serde_json::from_value(c.provenance["candidate_fingerprint"]["exact_gate_start"].clone())
            .map_err(|e| format!("finish rule: invalid exact start gate: {e}"))?;
    apply_exact_gate_identity(&mut out, exact_start.as_ref(), None);
    if out.candidate_fingerprint == c.candidate_fingerprint {
        return Err(format!(
            "finish rule: {} boundary changed without new fingerprint",
            c.display_name
        ));
    }
    out.legacy_candidate_fingerprints
        .push(c.candidate_fingerprint.clone());
    out.legacy_candidate_fingerprints.sort();
    out.legacy_candidate_fingerprints.dedup();
    out.compiler_version = CANON_COMPILER_VERSION.into();
    out.provenance["canonical_profile_hash"]["value"] =
        json!(canonical_profile_hash(&out.canonical_profile));
    out.provenance["boundary_snap"]["end"] = json!("finish_control_setback");
    let approval = admitted(c).filter(|d| approved_finish(d, junction, points.last().unwrap()));
    out.provenance["finish_gate_rule"] = json!({
        "model": "finish_before_traffic_control_v1",
        "decision_resource": DECISIONS_PATH,
        "admission": if approval.is_some() {"founder_admitted"} else {"proposed by rule, not admitted"},
        "founder_approval": approval.map(|d| json!({"by":decisions().approved_by,
            "on":decisions().approved_on,"quote":d.stop_evidence_amendment.as_ref()
                .map_or(decisions().approval_quote.as_str(), |a| a.approval_quote.as_str()),
            "authority":decisions().position_approval_authority,
            "initial_authority":decisions().authority,"approved_position":d.approved_position,
            "covering_note":d.covering_note,"position_tolerance_m":0.5})),
        "clearance_interpretation": decisions().clearance_interpretation,
        "predecessor_profile_points": old_points,
        "predecessor_fingerprint": c.candidate_fingerprint,
        "record_continuity_policy": "new_record_board",
        "junction": {"node_id":junction,"lat":j.lat,"lon":j.lon,"along_m":junction_s},
        "controls": controls.values().collect::<Vec<_>>(),
        "mapped_stop_positions_m": stop_positions,
        "default_setback_m": SETBACK_M, "stop_line_clearance_m": CONTROL_CLEARANCE_M,
        "setback_from_junction_m": junction_s-length, "metres_moved": old_length-length,
        "old_gate_end_wkt":c.gate_end_wkt,
        "clearance_extends_default_setback": junction_s-length > 30.0,
        "prior_ratified_end_anchor_is_historical": c.provenance.get("ratified_boundary").is_some()
    });
    if let Some(amendment) = stop_evidence {
        out.provenance["finish_gate_rule"]["stop_evidence_amendment"] = json!(amendment);
        out.provenance["finish_gate_rule"]["observed_stop_along_m"] = json!(observed_stop_s);
        out.provenance["finish_gate_rule"]["observed_stop_clearance_m"] =
            json!(observed_stop_s.unwrap() - length);
    }
    if let Some(revision) = out
        .provenance
        .as_object_mut()
        .unwrap()
        .remove("capture_tolerance_revision")
    {
        out.provenance["superseded_capture_tolerance_revision"] = json!({
            "status":"end_gate_override_superseded_by_boundary_change",
            "revision":revision,"successor_end_half_extent_m":DEFAULT_GATE_HALF_WIDTH_M,
            "start_gate_unchanged":true,"record_continuity_policy":"new_record_board",
            "authority":"docs/design/CANON_BUILD_DECISIONS.md#d10-revisions-and-identity"
        });
    }
    if let Some(revision) = admitted(c).and_then(|d| d.start_gate_revision.as_ref()) {
        if revision["gate_start_wkt"].as_str() == Some(c.gate_start_wkt.as_str())
            && revision["predecessor_revision_id"]
                == out.provenance["superseded_capture_tolerance_revision"]["revision"]
                    ["revision_id"]
        {
            let mut active = revision.clone();
            active["candidate_fingerprint"] = json!(out.candidate_fingerprint);
            active["decision_resource"] = json!(DECISIONS_PATH);
            out.provenance["capture_tolerance_revision"] = active;
        }
    }
    if approval.is_none() {
        out.low_confidence_flags
            .push("finish_rule_proposed_not_admitted".into());
        out.confidence = "needs_review".into();
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    pub(super) fn fixture() -> (CanonCandidate, FinishControlGraph) {
        let points: Vec<_> = (0..=30)
            .map(|i| CanonProfilePoint {
                dist_m: 0.0,
                lat: 40.0 + i as f64 * 10.0 / 111_195.0,
                lon: -75.0,
                elev_m: 50.0 + i as f64,
            })
            .collect();
        let mut road = RoadFeature::new(1, RoadClass::Residential);
        road.name = Some("Test hill".into());
        let candidate = compile_selected_candidate(
            &road,
            points.clone(),
            &CanonCompileConfig::default(),
            &[1],
            &[],
            CandidateProvenance::default(),
            30.0,
            BoundarySnap {
                index: 0,
                reason: "route_endpoint",
            },
            BoundarySnap {
                index: 30,
                reason: "shared_road_geometry",
            },
        )
        .unwrap();
        let nodes = points
            .iter()
            .enumerate()
            .map(|(i, p)| {
                (
                    i as i64,
                    Node {
                        lat: p.lat,
                        lon: p.lon,
                        tags: Tags::new(),
                    },
                )
            })
            .collect();
        let way = Way {
            id: 1,
            nodes: (0..=30).collect(),
            tags: Tags::new(),
        };
        (
            candidate,
            FinishControlGraph {
                nodes,
                ways: BTreeMap::from([(1, way)]),
                junctions: BTreeSet::from([30]),
                stop_lines: vec![],
            },
        )
    }

    #[test]
    fn signal_finish_moves_27m_and_preserves_start() {
        let (candidate, mut graph) = fixture();
        graph
            .nodes
            .get_mut(&30)
            .unwrap()
            .tags
            .insert("highway".into(), "traffic_signals".into());
        let mut result = vec![candidate.clone()];
        apply_finish_gate_rule(&mut result, &graph).unwrap();
        assert!((candidate.length_m - result[0].length_m - SETBACK_M).abs() < 0.02);
        assert_eq!(candidate.gate_start_wkt, result[0].gate_start_wkt);
        assert_ne!(
            candidate.candidate_fingerprint,
            result[0].candidate_fingerprint
        );
    }

    pub(super) fn set_tags(graph: &mut FinishControlGraph, id: i64, tags: &[(&str, &str)]) {
        graph.nodes.get_mut(&id).unwrap().tags = tags
            .iter()
            .map(|(k, v)| ((*k).into(), (*v).into()))
            .collect();
    }

    pub(super) fn run(c: &CanonCandidate, g: &FinishControlGraph) -> CanonCandidate {
        let mut candidates = vec![c.clone()];
        apply_finish_gate_rule(&mut candidates, g).unwrap();
        candidates.remove(0)
    }

    #[test]
    fn all_way_stop_at_junction() {
        let (c, mut g) = fixture();
        set_tags(&mut g, 30, &[("highway", "stop"), ("stop", "all")]);
        assert!((c.length_m - run(&c, &g).length_m - 27.0).abs() < 0.02);
    }

    #[test]
    fn serialized_finish_is_before_upstream_signal_and_crossing() {
        for tags in [
            vec![("highway", "traffic_signals")],
            vec![("crossing", "traffic_signals")],
        ] {
            for upstream_m in [29.0, 29.99] {
                let (c, mut g) = fixture();
                // Move the existing 30m-upstream node inside the adjacency
                // boundary, leaving all way nodes in their original order.
                g.nodes.get_mut(&27).unwrap().lat = g.nodes[&30].lat - upstream_m / 111_195.0;
                set_tags(&mut g, 27, &tags);
                let out = run(&c, &g);
                let endpoints = line_string_profile_points(&out.gate_end_wkt).unwrap();
                let center_lat = (endpoints[0].lat + endpoints[1].lat) / 2.0;
                assert!(center_lat < g.nodes[&27].lat, "gate must precede control");
                assert!(
                    haversine_m(center_lat, -75.0, g.nodes[&27].lat, -75.0) > 14.98,
                    "clearance must survive serialized coordinate rounding"
                );
                assert_eq!(
                    out.provenance["finish_gate_rule"]["clearance_extends_default_setback"],
                    true
                );
            }
        }
    }

    #[test]
    fn directional_stop_and_opposite_direction() {
        let (c, mut g) = fixture();
        set_tags(&mut g, 29, &[("highway", "stop"), ("direction", "forward")]);
        assert!(run(&c, &g).length_m < c.length_m);
        set_tags(
            &mut g,
            29,
            &[("highway", "stop"), ("direction", "backward")],
        );
        assert_eq!(
            serde_json::to_vec(&c).unwrap(),
            serde_json::to_vec(&run(&c, &g)).unwrap()
        );
        g.ways.get_mut(&1).unwrap().nodes.reverse();
        assert!(run(&c, &g).length_m < c.length_m);
    }

    #[test]
    fn cross_traffic_only_stop_does_not_move_finish() {
        let (c, mut g) = fixture();
        g.nodes.insert(
            31,
            Node {
                lat: g.nodes[&30].lat,
                lon: -74.9999,
                tags: Tags::from([
                    ("highway".into(), "stop".into()),
                    ("direction".into(), "forward".into()),
                ]),
            },
        );
        g.ways.insert(
            2,
            Way {
                id: 2,
                nodes: vec![31, 30],
                tags: Tags::new(),
            },
        );
        assert_eq!(
            serde_json::to_vec(&c).unwrap(),
            serde_json::to_vec(&run(&c, &g)).unwrap()
        );
    }

    #[test]
    fn uncontrolled_finish_and_unmapped_t_junction_are_unchanged() {
        let (c, mut g) = fixture();
        assert_eq!(
            serde_json::to_vec(&c).unwrap(),
            serde_json::to_vec(&run(&c, &g)).unwrap()
        );
        g.junctions.clear();
        assert_eq!(
            serde_json::to_vec(&c).unwrap(),
            serde_json::to_vec(&run(&c, &g)).unwrap()
        );
    }

    #[test]
    fn mapped_stopping_point_clearance_takes_precedence_over_default_band() {
        let (c, mut g) = fixture();
        set_tags(
            &mut g,
            28,
            &[("highway", "stop"), ("stop:direction", "forward")],
        );
        let out = run(&c, &g);
        assert!((c.length_m - out.length_m - 35.0).abs() < 0.03);
        assert_eq!(
            out.provenance["finish_gate_rule"]["clearance_extends_default_setback"],
            true
        );
    }

    #[test]
    fn painted_stop_line_way_has_15m_clearance() {
        let (c, mut g) = fixture();
        set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
        let lat = g.nodes[&28].lat;
        g.nodes.insert(
            100,
            Node {
                lat,
                lon: -75.0001,
                tags: Tags::new(),
            },
        );
        g.nodes.insert(
            101,
            Node {
                lat,
                lon: -74.9999,
                tags: Tags::new(),
            },
        );
        g.stop_lines.push(Way {
            id: 9,
            nodes: vec![100, 101],
            tags: Tags::from([("road_marking".into(), "stop_line".into())]),
        });
        assert!((c.length_m - run(&c, &g).length_m - 35.0).abs() < 0.03);
        g.stop_lines[0].tags.insert("layer".into(), "1".into());
        assert!(
            (c.length_m - run(&c, &g).length_m - 27.0).abs() < 0.03,
            "a painted line on another level cannot constrain this approach"
        );
    }

    #[test]
    fn give_way_crossing_signal_and_rail_crossing() {
        for tags in [
            vec![("highway", "give_way"), ("direction", "forward")],
            vec![("crossing", "traffic_signals")],
            vec![("railway", "level_crossing")],
        ] {
            let (c, mut g) = fixture();
            set_tags(&mut g, 30, &tags);
            assert!(run(&c, &g).length_m < c.length_m);
        }
    }

    #[test]
    fn interior_and_start_controls_do_not_move_any_gate() {
        let (c, mut g) = fixture();
        for id in [0, 4, 20] {
            set_tags(&mut g, id, &[("highway", "traffic_signals")]);
            g.junctions.insert(id);
        }
        assert_eq!(
            serde_json::to_vec(&c).unwrap(),
            serde_json::to_vec(&run(&c, &g)).unwrap()
        );
    }

    #[test]
    fn deterministic_bytes_and_idempotent() {
        let (c, mut g) = fixture();
        set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
        let first = run(&c, &g);
        let bytes = serde_json::to_vec(&first).unwrap();
        assert_eq!(bytes, serde_json::to_vec(&run(&c, &g)).unwrap());
        assert_eq!(bytes, serde_json::to_vec(&run(&first, &g)).unwrap());
    }

    #[test]
    fn profile_rise_hash_lineage_and_gate_width_recomputed() {
        let (mut c, mut g) = fixture();
        c.gate_end_wkt = resize_symmetric_gate(&c.gate_end_wkt, 35.0).unwrap();
        set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
        let out = run(&c, &g);
        assert!((out.vert_m - 27.3).abs() < 0.02);
        assert!((out.avg_gradient_pct - 10.0).abs() < 0.01);
        assert_eq!(out.canonical_profile.last().unwrap().dist_m, out.length_m);
        assert_eq!(
            out.provenance["canonical_profile_hash"]["value"],
            canonical_profile_hash(&out.canonical_profile)
        );
        assert!(out
            .legacy_candidate_fingerprints
            .contains(&c.candidate_fingerprint));
        assert!((symmetric_gate_half_extent_m(&out.gate_end_wkt).unwrap() - 25.0).abs() < 0.01);
    }

    #[test]
    fn youngs_approval_is_bounded_to_fingerprint_node_and_unknown_direction() {
        let (mut c, mut g) = fixture();
        c.candidate_fingerprint =
            "c1b072c5dcb791b534b6ba287a71e605c2b5a42bffe63c94a697bccb653d6ce6".into();
        c.display_name = "Youngs Ford Road".into();
        let node = g.nodes.remove(&30).unwrap();
        g.nodes.insert(111663714, node);
        g.ways.get_mut(&1).unwrap().nodes[30] = 111663714;
        g.junctions = BTreeSet::from([111663714]);
        set_tags(&mut g, 111663714, &[("highway", "stop")]);
        assert!(run(&c, &g).length_m < c.length_m);
        set_tags(
            &mut g,
            111663714,
            &[("highway", "stop"), ("direction", "backward")],
        );
        assert_eq!(run(&c, &g).length_m, c.length_m);
        set_tags(&mut g, 111663714, &[("highway", "stop")]);
        c.candidate_fingerprint = "another-candidate".into();
        assert_eq!(run(&c, &g).length_m, c.length_m);
        let (c, mut g) = fixture();
        set_tags(&mut g, 30, &[("highway", "stop")]);
        assert_eq!(run(&c, &g).length_m, c.length_m);
    }

    #[test]
    fn adjacent_control_must_be_within_30m_along_own_way() {
        let (c, mut g) = fixture();
        set_tags(&mut g, 26, &[("highway", "stop"), ("direction", "forward")]);
        assert_eq!(run(&c, &g).length_m, c.length_m);
        set_tags(&mut g, 28, &[("highway", "stop"), ("direction", "forward")]);
        assert!(run(&c, &g).length_m < c.length_m);
    }

    #[test]
    fn invalid_profile_fails_atomically() {
        let (c, mut g) = fixture();
        set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
        let mut broken = c.clone();
        broken.canonical_profile.pop();
        let mut candidates = vec![c, broken];
        let before = serde_json::to_vec(&candidates).unwrap();
        assert!(apply_finish_gate_rule(&mut candidates, &g).is_err());
        assert_eq!(before, serde_json::to_vec(&candidates).unwrap());
    }

    #[test]
    fn exact_start_gate_remains_part_of_successor_identity() {
        let (mut c, mut g) = fixture();
        set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
        let mut exact = RatifiedBoundaryGate {
            a_lat: 40.0,
            a_lon: -75.0003,
            b_lat: 40.0,
            b_lon: -74.9997,
        };
        apply_exact_gate_identity(&mut c, Some(&exact), None);
        c.gate_start_wkt = ratified_gate_wkt(&exact);
        let first = run(&c, &g);
        exact.a_lat += 0.00001;
        c.provenance["candidate_fingerprint"]["exact_gate_start"] = json!(exact);
        c.gate_start_wkt = ratified_gate_wkt(&exact);
        let second = run(&c, &g);
        assert_ne!(first.candidate_fingerprint, second.candidate_fingerprint);
        assert_eq!(second.gate_start_wkt, c.gate_start_wkt);
        assert_eq!(
            second.provenance["candidate_fingerprint"]["algorithm"],
            "blake3_ratified_exact_gates_v1"
        );
        assert!(second.provenance["candidate_fingerprint"]["exact_gate_end"].is_null());
    }

    #[test]
    fn duplicate_successor_lineage_fails_atomically() {
        let (c, mut g) = fixture();
        set_tags(&mut g, 30, &[("highway", "traffic_signals")]);
        let mut candidates = vec![c.clone(), c];
        let bytes = serde_json::to_vec(&candidates).unwrap();
        assert!(apply_finish_gate_rule(&mut candidates, &g).is_err());
        assert_eq!(bytes, serde_json::to_vec(&candidates).unwrap());
    }

    #[test]
    fn cycleways_are_junction_roads_and_layers_must_match() {
        let cycleway = Tags::from([("highway".into(), "cycleway".into())]);
        assert!(road(&cycleway));
        assert!(same_layer(&cycleway, &Tags::new()));
        assert!(!same_layer(
            &cycleway,
            &Tags::from([("layer".into(), "1".into())])
        ));
        assert!(!same_layer(
            &cycleway,
            &Tags::from([("bridge".into(), "yes".into())])
        ));
    }
}

#[cfg(test)]
#[path = "finish_gate_regressions.rs"]
mod regressions;
