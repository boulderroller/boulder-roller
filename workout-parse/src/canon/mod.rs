//! Offline climb canon compiler primitives.
//!
//! This module is intentionally local-file only. The compiler consumes OSM road
//! features plus locally-produced elevation profiles; it never reaches out to a
//! public elevation API.

use std::collections::{BTreeSet, HashMap, HashSet};

use blake3::Hasher;
use h3o::{LatLng, Resolution};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use crate::climb::persistence::{compute_persistence, find_essential, NOISE_GATE_M};
use crate::climb::utils::{bearing_degrees, haversine_m, smooth_elevations};
use crate::geo_features::{OsmParserConfig, RoadClass, RoadFeature};
use crate::polyline::encode_polyline;

pub mod finish_gates;

pub const CANON_COMPILER_VERSION: &str = "canon-compile-v0.2.10";
pub const CANON_H3_RESOLUTION: u8 = 10;
const DEFAULT_MIN_VERT_M: f64 = 8.0;
const DEFAULT_MIN_LENGTH_M: f64 = 90.0;
const DEFAULT_GATE_HALF_WIDTH_M: f64 = 25.0;
const DEFAULT_BOUNDARY_SNAP_M: f64 = 150.0;
const TARGET_PROFILE_SPACING_M: f64 = 10.0;
const SPARSE_PROFILE_SPACING_M: f64 = 15.0;
const CHAIN_ENDPOINT_TOLERANCE_M: f64 = 30.0;
const CHAIN_MAX_ELEVATION_SEAM_M: f64 = 8.0;
const CHAIN_SAME_NAME_MAX_TURN_DEG: f64 = 85.0;
const CHAIN_CONTINUATION_MAX_TURN_DEG: f64 = 45.0;
const CHAIN_MAX_SEGMENTS: usize = 12;
const BOUNDARY_EXTENSION_MIN_GRADE_PCT: f64 = 1.0;
const RATIFIED_BOUNDARY_MODEL: &str = "canon_ratified_boundaries_v1";
const CAPTURE_TOLERANCE_MODEL: &str = "canon_capture_tolerance_overrides_v1";
const MAX_CAPTURE_GATE_HALF_EXTENT_M: f64 = 40.0;
const MAX_CAPTURE_CORRIDOR_HALF_WIDTH_M: f64 = 35.0;
const CAPTURE_RECORD_CONTINUITY_POLICY: &str = "carry_forward_same_canon_id_and_record_board";
const RATIFIED_BOUNDARY_MAX_ANCHOR_OFFSET_M: f64 = 40.0;
const RATIFIED_BOUNDARY_AMBIGUITY_M: f64 = 0.5;
const RATIFIED_OSM_NODE_COORD_TOLERANCE_M: f64 = 0.5;
const INTERSECTION_KEY_SCALE: f64 = 10_000_000.0;
const INTERSECTION_PROFILE_MATCH_TOLERANCE_M: f64 = 25.0;
const MIN_GRADIENT_SEGMENT_DISTANCE_M: f64 = 1.0;
const FINGERPRINT_GEOMETRY_SAMPLES: usize = 17;
const FINGERPRINT_COORD_GRID_SCALE: f64 = 20_000.0;

/// Compiler knobs that do not reopen the ratified canon decisions.
#[derive(Debug, Clone)]
pub struct CanonCompileConfig {
    pub min_vert_m: f64,
    pub min_length_m: f64,
    pub boundary_snap_m: f64,
    pub gate_half_width_m: f64,
    pub dem_source: String,
    pub odbl_extract_at: Option<String>,
    pub compiler_version: String,
}

impl Default for CanonCompileConfig {
    fn default() -> Self {
        Self {
            min_vert_m: DEFAULT_MIN_VERT_M,
            min_length_m: DEFAULT_MIN_LENGTH_M,
            boundary_snap_m: DEFAULT_BOUNDARY_SNAP_M,
            gate_half_width_m: DEFAULT_GATE_HALF_WIDTH_M,
            dem_source: "USGS 3DEP 10m local profile export".to_string(),
            odbl_extract_at: None,
            compiler_version: CANON_COMPILER_VERSION.to_string(),
        }
    }
}

/// A locally-draped profile sample. Coordinates are decimal degrees.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CanonProfilePoint {
    #[serde(default)]
    pub dist_m: f64,
    pub lat: f64,
    pub lon: f64,
    #[serde(alias = "elevation_m")]
    pub elev_m: f64,
}

/// The compact JSONB profile shape stored on canon rows.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CanonProfileSample {
    pub dist_m: f64,
    pub elev_m: f64,
}

/// Local elevation samples keyed to an OSM way.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalElevationProfile {
    pub osm_way_id: i64,
    #[serde(default)]
    pub points: Vec<CanonProfilePoint>,
}

/// Versioned boundary requirements and their pinned source-data translations.
/// Each decision replaces exactly one known candidate and carries its prior
/// fingerprints forward as identity lineage.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RatifiedBoundaryDecisionSet {
    pub model: String,
    pub decisions: Vec<RatifiedBoundaryDecision>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RatifiedBoundaryDecision {
    pub decision_id: String,
    pub display_name: String,
    pub route_name: Option<String>,
    pub osm_way_refs: Vec<i64>,
    pub start: RatifiedBoundaryAnchor,
    pub end: RatifiedBoundaryAnchor,
    pub replaces_candidate_fingerprint: String,
    #[serde(default)]
    pub legacy_candidate_fingerprints: Vec<String>,
    pub evidence: RatifiedBoundaryEvidence,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub finish_decision: Option<RatifiedFinishDecision>,
}

/// A natural top is an explicit boundary decision, not a D7.5 junction setback.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(tag = "type", deny_unknown_fields)]
pub enum RatifiedFinishDecision {
    #[serde(rename = "crest finish (founder-approved)")]
    Crest {
        decision: String,
        finish_at: String,
        finish_m_past_current: f64,
        reason: String,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RatifiedBoundaryAnchor {
    pub label: String,
    pub osm_node_id: Option<i64>,
    pub lat: f64,
    pub lon: f64,
    pub max_offset_m: f64,
    #[serde(default)]
    pub exact_gate: Option<RatifiedBoundaryGate>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RatifiedBoundaryGate {
    pub a_lat: f64,
    pub a_lon: f64,
    pub b_lat: f64,
    pub b_lon: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RatifiedBoundaryEvidence {
    pub requirement: RatifiedBoundaryApprovalEvidence,
    pub geometry_translation: RatifiedBoundaryGeometryEvidence,
    #[serde(default)]
    pub visual_approval: Option<RatifiedBoundaryApprovalEvidence>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RatifiedBoundaryApprovalEvidence {
    pub approved_at: String,
    pub approved_by: String,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RatifiedBoundaryGeometryEvidence {
    pub resolved_at: String,
    pub resolved_by: String,
    pub source: String,
}

/// Explicit D10 minor-revision registry. These entries change only symmetric
/// capture extent after candidate identity and any ratified boundary
/// replacement have already been resolved.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CanonCaptureToleranceOverrideSet {
    pub model: String,
    pub overrides: Vec<CanonCaptureToleranceOverride>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CanonCaptureToleranceOverride {
    pub revision_id: String,
    pub candidate_fingerprint: String,
    pub display_name: String,
    pub gate_start_half_extent_m: f64,
    pub gate_end_half_extent_m: f64,
    pub corridor_half_width_m: f64,
    pub prior_geometry_policy: CanonCapturePriorGeometryPolicy,
    pub record_continuity_policy: String,
    pub evidence: CanonCaptureToleranceEvidence,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CanonCapturePriorGeometryPolicy {
    pub gate_start_half_extent_m: f64,
    pub gate_end_half_extent_m: f64,
    pub corridor_half_width_m: f64,
    pub source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct CanonCaptureToleranceEvidence {
    pub approved_at: String,
    pub approved_by: String,
    pub policy_source: String,
    pub replay_source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CorridorCell {
    pub h3_resolution: u8,
    pub tile_id: String,
    pub coverage_role: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CanonCandidate {
    pub candidate_fingerprint: String,
    pub legacy_candidate_fingerprints: Vec<String>,
    pub display_name: String,
    pub route_name: Option<String>,
    pub direction: String,
    pub centerline_polyline: String,
    pub centerline_wkt: String,
    pub corridor_wkt: String,
    pub corridor_half_width_m: f64,
    pub gate_start_wkt: String,
    pub gate_end_wkt: String,
    pub canonical_profile: Vec<CanonProfileSample>,
    pub length_m: f64,
    pub vert_m: f64,
    pub avg_gradient_pct: f64,
    pub max_gradient_pct: f64,
    pub worthiness_score: f64,
    pub confidence: String,
    pub dem_source: String,
    pub compiler_version: String,
    pub osm_way_refs: Vec<i64>,
    pub odbl_source: String,
    pub odbl_extract_at: Option<String>,
    pub provenance: Value,
    pub low_confidence_flags: Vec<String>,
    pub corridor_cells: Vec<CorridorCell>,
}

#[derive(Debug, Clone, Serialize)]
pub struct SkippedRoad {
    pub osm_way_id: i64,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct CanonCompileStats {
    pub input_roads: usize,
    pub profiles_loaded: usize,
    pub launch_scope_roads: usize,
    pub emitted_candidates: usize,
    pub skipped_roads: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct CanonCompileReport {
    pub compiler_version: String,
    pub dem_source: String,
    pub ratified_boundaries: Option<RatifiedBoundaryRunMetadata>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub capture_tolerance_overrides: Option<CanonCaptureToleranceRunMetadata>,
    pub candidates: Vec<CanonCandidate>,
    pub skipped_roads: Vec<SkippedRoad>,
    pub warnings: Vec<String>,
    pub stats: CanonCompileStats,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct RatifiedBoundaryResourceDigest {
    pub source: String,
    pub blake3: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct RatifiedBoundaryRunMetadata {
    pub mode: String,
    pub model: Option<String>,
    pub registry: Option<RatifiedBoundaryResourceDigest>,
    pub road_graph: Option<RatifiedBoundaryResourceDigest>,
    pub profile_bundles: Vec<RatifiedBoundaryResourceDigest>,
    pub applied_decisions: usize,
    pub retained_decisions: usize,
    pub embedded_profiles_added: usize,
    pub embedded_profiles_replaced: usize,
    pub custom_profiles_added: usize,
    pub custom_profiles_replaced: usize,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct CanonCaptureToleranceRunMetadata {
    pub mode: String,
    pub model: String,
    pub registry: RatifiedBoundaryResourceDigest,
    pub expected: usize,
    pub applied: usize,
    pub retained: usize,
}

#[derive(Debug, Clone)]
struct BoundarySnap {
    index: usize,
    reason: &'static str,
}

#[derive(Debug, Clone)]
struct ProfiledRoad {
    road: RoadFeature,
    profile: LocalElevationProfile,
    intersection_indices: BTreeSet<usize>,
}

#[derive(Debug, Clone)]
struct WayChainSegment {
    segment_id: usize,
    road: RoadFeature,
    points: Vec<CanonProfilePoint>,
    intersection_indices: BTreeSet<usize>,
    route_key: Option<String>,
    persistence_m: f64,
    start_boundary_reason: &'static str,
    end_boundary_reason: &'static str,
    source_reversed: bool,
    is_opposite_span: bool,
}

#[derive(Debug, Clone, Copy)]
struct ChainContinuation {
    from: usize,
    to: usize,
    score: f64,
}

#[derive(Debug, Clone)]
struct WayChain {
    segments: Vec<WayChainSegment>,
    directional_extraction: bool,
}

#[derive(Debug, Clone)]
struct ChainProfile {
    points: Vec<CanonProfilePoint>,
    intersection_indices: BTreeSet<usize>,
}

#[derive(Debug, Clone)]
struct DirectionalAscentSpan {
    points: Vec<CanonProfilePoint>,
    intersection_indices: BTreeSet<usize>,
    persistence_m: f64,
    start_boundary_reason: &'static str,
    end_boundary_reason: &'static str,
    source_reversed: bool,
}

#[derive(Debug, Default)]
struct CandidateProvenance {
    way_chain: Option<Value>,
    directional_extraction: Option<Value>,
    ratified_boundary: Option<Value>,
}

#[derive(Debug, Clone)]
struct RatifiedProfile {
    points: Vec<CanonProfilePoint>,
    reversed_way_refs: Vec<i64>,
    seam_gaps_m: Vec<f64>,
    seam_elevation_deltas_m: Vec<f64>,
    start_offset_m: f64,
    end_offset_m: f64,
    fit_score_m: f64,
}

#[derive(Debug, Clone, Copy)]
struct RatifiedProfileSeam {
    left_index: usize,
    right_index: usize,
    gap_m: f64,
    elevation_delta_m: f64,
}

#[derive(Debug, Clone)]
struct AnchorProjection {
    segment_index: usize,
    along_m: f64,
    offset_m: f64,
    point: CanonProfilePoint,
}

/// OSM parser config for the launch canon paved-road scope.
pub fn launch_canon_osm_config(min_length_m: f32) -> OsmParserConfig {
    let mut include_classes = HashSet::new();
    include_classes.insert(RoadClass::Primary);
    include_classes.insert(RoadClass::Secondary);
    include_classes.insert(RoadClass::Tertiary);
    include_classes.insert(RoadClass::Residential);
    include_classes.insert(RoadClass::Unclassified);
    include_classes.insert(RoadClass::Cycleway);
    include_classes.insert(RoadClass::Service);

    OsmParserConfig {
        h3_resolution: Resolution::Ten,
        min_length_m,
        require_name: false,
        require_grade: false,
        include_classes,
    }
}

/// Final launch-scope filter after the OSM parser has built road features.
pub fn is_launch_scope_road(feature: &RoadFeature) -> bool {
    if matches!(feature.road_class, RoadClass::Path | RoadClass::Track) {
        return false;
    }

    if feature.road_class == RoadClass::Service && feature.name.is_none() {
        return false;
    }

    let highway = feature.highway_tag.as_deref().unwrap_or_default();
    if matches!(
        highway,
        "trunk" | "trunk_link" | "motorway" | "motorway_link"
    ) {
        return false;
    }

    matches!(
        feature.road_class,
        RoadClass::Primary
            | RoadClass::Secondary
            | RoadClass::Tertiary
            | RoadClass::Residential
            | RoadClass::Unclassified
            | RoadClass::Cycleway
            | RoadClass::Service
    )
}

fn annotate_profiled_road_intersections(profiled_roads: &mut [ProfiledRoad]) {
    let shared_keys = shared_geometry_keys(profiled_roads);
    if shared_keys.is_empty() {
        return;
    }

    for profiled in profiled_roads {
        let mut indices = BTreeSet::new();
        for (lon, lat) in &profiled.road.geometry {
            if !shared_keys.contains(&geometry_key(*lon, *lat)) {
                continue;
            }
            if let Some(index) =
                nearest_profile_index_to_coord(&profiled.profile.points, *lat, *lon)
            {
                indices.insert(index);
            }
        }
        profiled.intersection_indices = indices;
    }
}

fn shared_geometry_keys(profiled_roads: &[ProfiledRoad]) -> HashSet<(i64, i64)> {
    let mut counts: HashMap<(i64, i64), usize> = HashMap::new();
    for profiled in profiled_roads {
        let mut local_keys = HashSet::new();
        for (lon, lat) in &profiled.road.geometry {
            local_keys.insert(geometry_key(*lon, *lat));
        }
        for key in local_keys {
            *counts.entry(key).or_default() += 1;
        }
    }
    counts
        .into_iter()
        .filter_map(|(key, count)| if count >= 2 { Some(key) } else { None })
        .collect()
}

fn geometry_key(lon: f64, lat: f64) -> (i64, i64) {
    (
        (lat * INTERSECTION_KEY_SCALE).round() as i64,
        (lon * INTERSECTION_KEY_SCALE).round() as i64,
    )
}

fn nearest_profile_index_to_coord(
    points: &[CanonProfilePoint],
    lat: f64,
    lon: f64,
) -> Option<usize> {
    points
        .iter()
        .enumerate()
        .filter_map(|(index, point)| {
            let distance_m = haversine_m(point.lat, point.lon, lat, lon);
            if distance_m <= INTERSECTION_PROFILE_MATCH_TOLERANCE_M {
                Some((index, distance_m))
            } else {
                None
            }
        })
        .min_by(|(_, left), (_, right)| {
            left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal)
        })
        .map(|(index, _)| index)
}

/// Load local elevation profiles from either the new list shape or the legacy
/// `philly_climbs_with_elevation.json` map shape.
pub fn local_profiles_from_json(
    value: Value,
) -> Result<HashMap<i64, LocalElevationProfile>, String> {
    let mut profiles = HashMap::new();

    match value {
        Value::Array(items) => {
            for item in items {
                if let Some(profile) = profile_from_value(&item)? {
                    profiles.insert(profile.osm_way_id, profile);
                }
            }
        }
        Value::Object(map) => {
            if let Some(Value::Array(items)) = map.get("roads") {
                for item in items {
                    if let Some(profile) = profile_from_value(item)? {
                        profiles.insert(profile.osm_way_id, profile);
                    }
                }
            } else {
                for item in map.values() {
                    if let Some(profile) = profile_from_value(item)? {
                        profiles.insert(profile.osm_way_id, profile);
                    }
                }
            }
        }
        _ => return Err("elevation JSON must be an array or object".to_string()),
    }

    Ok(profiles)
}

fn profile_from_value(value: &Value) -> Result<Option<LocalElevationProfile>, String> {
    let Some(osm_way_id) = value.get("osm_way_id").and_then(Value::as_i64) else {
        return Ok(None);
    };

    let samples = value
        .get("points")
        .or_else(|| value.get("elevation_profile"))
        .or_else(|| value.get("profile"))
        .ok_or_else(|| format!("profile for OSM way {} has no points", osm_way_id))?
        .clone();

    let mut points: Vec<CanonProfilePoint> = serde_json::from_value(samples)
        .map_err(|err| format!("profile for OSM way {} is invalid: {}", osm_way_id, err))?;
    rebase_distances(&mut points);

    Ok(Some(LocalElevationProfile { osm_way_id, points }))
}

/// Compile schema-shaped canon candidates from OSM road features plus local
/// elevation profiles.
pub fn compile_canon_candidates(
    roads: &[RoadFeature],
    profiles: &HashMap<i64, LocalElevationProfile>,
    config: &CanonCompileConfig,
) -> CanonCompileReport {
    let mut candidates = Vec::new();
    let mut skipped_roads = Vec::new();
    let mut launch_scope_roads = 0usize;
    let mut profiled_roads = Vec::new();

    for road in roads {
        if !is_launch_scope_road(road) {
            skipped_roads.push(SkippedRoad {
                osm_way_id: road.osm_way_id,
                reason: "outside_launch_road_scope".to_string(),
            });
            continue;
        }
        launch_scope_roads += 1;

        let Some(profile) = profiles.get(&road.osm_way_id) else {
            skipped_roads.push(SkippedRoad {
                osm_way_id: road.osm_way_id,
                reason: "missing_local_dem_profile".to_string(),
            });
            continue;
        };

        profiled_roads.push(ProfiledRoad {
            road: road.clone(),
            profile: profile.clone(),
            intersection_indices: BTreeSet::new(),
        });
    }
    annotate_profiled_road_intersections(&mut profiled_roads);

    let mut chained_way_ids = HashSet::new();
    for chain in build_legacy_way_chains(&profiled_roads) {
        if let Some(candidate) = compile_way_chain(&chain, config) {
            for segment in &chain.segments {
                chained_way_ids.insert(segment.road.osm_way_id);
            }
            candidates.push(candidate);
        }
    }

    for profiled in &profiled_roads {
        if chained_way_ids.contains(&profiled.road.osm_way_id) {
            continue;
        }

        match compile_single_road(
            &profiled.road,
            &profiled.profile,
            &profiled.intersection_indices,
            config,
        ) {
            Some(candidate) => candidates.push(candidate),
            None => skipped_roads.push(SkippedRoad {
                osm_way_id: profiled.road.osm_way_id,
                reason: "profile_did_not_meet_climb_thresholds".to_string(),
            }),
        }
    }

    let mut seen_fingerprints = candidates
        .iter()
        .map(|candidate| candidate.candidate_fingerprint.clone())
        .collect::<HashSet<_>>();
    let directional_segments = directional_way_segments(&profiled_roads, config);
    let mut chained_segment_ids = HashSet::new();
    let mut directionally_emitted_way_ids = HashSet::new();
    for chain in build_directional_way_chains(&directional_segments) {
        if !chain
            .segments
            .iter()
            .any(|segment| segment.is_opposite_span)
        {
            continue;
        }
        if let Some(candidate) = compile_way_chain(&chain, config) {
            push_unique_directional_chain_candidate(
                candidate,
                &chain,
                &mut seen_fingerprints,
                &mut chained_segment_ids,
                &mut directionally_emitted_way_ids,
                &mut candidates,
            );
        }
    }

    for segment in &directional_segments {
        if !segment.is_opposite_span || chained_segment_ids.contains(&segment.segment_id) {
            continue;
        }
        if let Some(candidate) = compile_way_segment(segment, config) {
            if seen_fingerprints.insert(candidate.candidate_fingerprint.clone()) {
                directionally_emitted_way_ids.insert(segment.road.osm_way_id);
                candidates.push(candidate);
            }
        }
    }

    skipped_roads.retain(|skipped| {
        skipped.reason != "profile_did_not_meet_climb_thresholds"
            || !directionally_emitted_way_ids.contains(&skipped.osm_way_id)
    });

    let stats = CanonCompileStats {
        input_roads: roads.len(),
        profiles_loaded: profiles.len(),
        launch_scope_roads,
        emitted_candidates: candidates.len(),
        skipped_roads: skipped_roads.len(),
    };

    CanonCompileReport {
        compiler_version: config.compiler_version.clone(),
        dem_source: config.dem_source.clone(),
        ratified_boundaries: None,
        capture_tolerance_overrides: None,
        candidates,
        skipped_roads,
        warnings: vec![
            "canon-compile consumes local DEM profile exports; use canon-export-profiles to produce them from local USGS 3DEP GeoTIFFs".to_string(),
            "the compiler snaps candidate gates to shared road geometry, route endpoints, or gradient inflections inside the configured boundary window".to_string(),
        ],
        stats,
    }
}

/// Parse the tracked boundary-decision artifact used by the launch compiler.
pub fn ratified_boundary_decisions_from_json(
    value: Value,
) -> Result<RatifiedBoundaryDecisionSet, String> {
    // Include the named climb even when a way ID is absent or malformed,
    // before deserializing the enclosing registry.
    if let Some(rows) = value["decisions"].as_array() {
        for row in rows {
            serde_json::from_value::<RatifiedBoundaryDecision>(row.clone()).map_err(|error| {
                format!(
                    "ratified boundary {} is invalid: {error}",
                    row["display_name"].as_str().unwrap_or("unnamed climb")
                )
            })?;
        }
    }
    let decisions = serde_json::from_value(value)
        .map_err(|error| format!("ratified boundary decisions are invalid: {error}"))?;
    validate_ratified_boundary_decisions(&decisions)?;
    Ok(decisions)
}

/// Replace generic candidates with tracked ratified boundaries. The operation
/// is atomic: any stale target, unavailable profile, bad seam, or ambiguous
/// anchor rejects the complete decision set.
pub fn apply_ratified_boundary_decisions(
    mut report: CanonCompileReport,
    roads: &[RoadFeature],
    profiles: &HashMap<i64, LocalElevationProfile>,
    decisions: &RatifiedBoundaryDecisionSet,
    config: &CanonCompileConfig,
) -> Result<CanonCompileReport, String> {
    validate_ratified_boundary_decisions(decisions)?;
    if decisions.decisions.is_empty() {
        return Ok(report);
    }

    let mut road_by_id = HashMap::new();
    for road in roads {
        if road_by_id.insert(road.osm_way_id, road).is_some() {
            return Err(format!(
                "ratified boundaries: OSM way {} appears more than once",
                road.osm_way_id
            ));
        }
    }

    let mut replacement_indices = HashSet::new();
    let mut replacement_fingerprints = HashSet::new();
    let mut replacements = Vec::with_capacity(decisions.decisions.len());

    for decision in &decisions.decisions {
        let target_indices = report
            .candidates
            .iter()
            .enumerate()
            .filter_map(|(index, candidate)| {
                (candidate.candidate_fingerprint == decision.replaces_candidate_fingerprint)
                    .then_some(index)
            })
            .collect::<Vec<_>>();
        if target_indices.len() != 1 {
            return Err(format!(
                "ratified boundary {} expected exactly one replacement target {}, found {}",
                decision.decision_id,
                decision.replaces_candidate_fingerprint,
                target_indices.len()
            ));
        }
        let target_index = target_indices[0];
        if !replacement_indices.insert(target_index) {
            return Err(format!(
                "ratified boundary {} reuses another decision's replacement target",
                decision.decision_id
            ));
        }

        let target_fingerprint = report.candidates[target_index]
            .candidate_fingerprint
            .clone();
        let target_lineage = report.candidates[target_index]
            .legacy_candidate_fingerprints
            .clone();
        let ratified_profile = build_ratified_profile(decision, profiles, &road_by_id)
            .map_err(|error| format!("{}: {error}", decision.display_name))?;
        let ratified_road =
            build_ratified_road_feature(decision, &ratified_profile.points, &road_by_id)?;
        let persistence_m = net_rise_m(&ratified_profile.points).ok_or_else(|| {
            format!(
                "ratified boundary {} produced an empty profile",
                decision.decision_id
            )
        })?;
        let mut ratified_provenance = json!({
            "algorithm": RATIFIED_BOUNDARY_MODEL,
            "decision_id": decision.decision_id,
            "ordered_osm_way_refs": decision.osm_way_refs,
            "replaces_candidate_fingerprint": decision.replaces_candidate_fingerprint,
            "anchors": {
                "start": {
                    "label": decision.start.label,
                    "osm_node_id": decision.start.osm_node_id,
                    "lat": decision.start.lat,
                    "lon": decision.start.lon,
                    "resolved_offset_m": round2(ratified_profile.start_offset_m),
                    "exact_gate": decision.start.exact_gate
                },
                "end": {
                    "label": decision.end.label,
                    "osm_node_id": decision.end.osm_node_id,
                    "lat": decision.end.lat,
                    "lon": decision.end.lon,
                    "resolved_offset_m": round2(ratified_profile.end_offset_m),
                    "exact_gate": decision.end.exact_gate
                }
            },
            "reversed_way_refs": ratified_profile.reversed_way_refs,
            "seam_gaps_m": ratified_profile.seam_gaps_m
                .iter()
                .map(|value| round2(*value))
                .collect::<Vec<_>>(),
            "seam_elevation_deltas_m": ratified_profile.seam_elevation_deltas_m
                .iter()
                .map(|value| round2(*value))
                .collect::<Vec<_>>(),
            "evidence": &decision.evidence
        });
        if let Some(finish) = &decision.finish_decision {
            ratified_provenance["finish_decision"] = json!(finish);
            ratified_provenance["record_continuity_policy"] = json!("new_record_board");
            ratified_provenance["publication_status"] = json!("review_only");
        }
        let ratified_point_count = ratified_profile.points.len();
        let mut candidate = compile_selected_candidate(
            &ratified_road,
            ratified_profile.points,
            config,
            &decision.osm_way_refs,
            &[],
            CandidateProvenance {
                ratified_boundary: Some(ratified_provenance),
                ..CandidateProvenance::default()
            },
            persistence_m,
            BoundarySnap {
                index: 0,
                reason: "ratified_boundary",
            },
            BoundarySnap {
                index: ratified_point_count - 1,
                reason: "ratified_boundary",
            },
        )
        .ok_or_else(|| {
            format!(
                "ratified boundary {} does not meet the configured climb thresholds",
                decision.decision_id
            )
        })?;
        candidate.display_name = decision.display_name.clone();
        candidate.route_name = decision.route_name.clone();
        if let Some(gate) = &decision.start.exact_gate {
            candidate.gate_start_wkt = ratified_gate_wkt(gate);
        }
        if let Some(gate) = &decision.end.exact_gate {
            candidate.gate_end_wkt = ratified_gate_wkt(gate);
        }
        apply_ratified_exact_gate_identity(&mut candidate, decision);

        let mut lineage = candidate.legacy_candidate_fingerprints.clone();
        push_fingerprint_lineage(
            &mut lineage,
            &candidate.candidate_fingerprint,
            target_fingerprint,
        );
        for fingerprint in target_lineage
            .into_iter()
            .chain(decision.legacy_candidate_fingerprints.iter().cloned())
        {
            push_fingerprint_lineage(&mut lineage, &candidate.candidate_fingerprint, fingerprint);
        }
        candidate.legacy_candidate_fingerprints = lineage;

        let duplicate_index = report
            .candidates
            .iter()
            .enumerate()
            .find_map(|(index, existing)| {
                (index != target_index
                    && existing.candidate_fingerprint == candidate.candidate_fingerprint)
                    .then_some(index)
            });
        if duplicate_index.is_some()
            || !replacement_fingerprints.insert(candidate.candidate_fingerprint.clone())
        {
            return Err(format!(
                "ratified boundary {} would create duplicate candidate fingerprint {}",
                decision.decision_id, candidate.candidate_fingerprint
            ));
        }
        replacements.push((target_index, candidate));
    }

    for (index, candidate) in replacements {
        report.candidates[index] = candidate;
    }
    validate_candidate_fingerprint_ownership(&report.candidates)?;
    report.stats.emitted_candidates = report.candidates.len();
    report.ratified_boundaries = Some(RatifiedBoundaryRunMetadata {
        mode: "applied".to_string(),
        model: Some(decisions.model.clone()),
        registry: None,
        road_graph: None,
        profile_bundles: Vec::new(),
        applied_decisions: decisions.decisions.len(),
        retained_decisions: decisions.decisions.len(),
        embedded_profiles_added: 0,
        embedded_profiles_replaced: 0,
        custom_profiles_added: 0,
        custom_profiles_replaced: 0,
    });
    report.warnings.push(format!(
        "applied {} tracked ratified boundary decisions with exact target replacement",
        decisions.decisions.len()
    ));
    Ok(report)
}

/// Parse and validate the deterministic per-candidate D10 capture registry.
pub fn capture_tolerance_overrides_from_json(
    value: Value,
) -> Result<CanonCaptureToleranceOverrideSet, String> {
    let overrides = serde_json::from_value(value)
        .map_err(|error| format!("capture tolerance overrides are invalid: {error}"))?;
    validate_capture_tolerance_overrides(&overrides)?;
    Ok(overrides)
}

/// Apply D10 minor revisions only after candidate identity and ratified
/// boundary replacement are final. Fingerprints, centerlines, profiles, spans,
/// and record continuity deliberately do not participate in this rewrite.
pub fn apply_capture_tolerance_overrides(
    mut report: CanonCompileReport,
    overrides: &CanonCaptureToleranceOverrideSet,
    resource: &RatifiedBoundaryResourceDigest,
) -> Result<CanonCompileReport, String> {
    validate_capture_tolerance_overrides(overrides)?;
    if report
        .ratified_boundaries
        .as_ref()
        .is_none_or(|metadata| metadata.mode != "applied")
    {
        return Err("capture tolerance overrides require applied ratified boundaries".to_string());
    }
    if report.capture_tolerance_overrides.is_some() {
        return Err("capture tolerance overrides were already applied".to_string());
    }
    if resource.source.trim().is_empty() || !is_candidate_fingerprint(&resource.blake3) {
        return Err("capture tolerance registry digest is incomplete".to_string());
    }

    let mut target_indices = HashSet::new();
    for entry in &overrides.overrides {
        let matches = report
            .candidates
            .iter()
            .enumerate()
            .filter_map(|(index, candidate)| {
                (candidate.candidate_fingerprint == entry.candidate_fingerprint).then_some(index)
            })
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(format!(
                "capture tolerance {} expected exactly one target {}, found {}",
                entry.revision_id,
                entry.candidate_fingerprint,
                matches.len()
            ));
        }
        let index = matches[0];
        if !target_indices.insert(index) {
            return Err(format!(
                "capture tolerance {} duplicates another target",
                entry.revision_id
            ));
        }

        let candidate = &mut report.candidates[index];
        if candidate.display_name != entry.display_name {
            return Err(format!(
                "capture tolerance {} expected display name {:?}, got {:?}",
                entry.revision_id, entry.display_name, candidate.display_name
            ));
        }
        if candidate
            .provenance
            .get("capture_tolerance_revision")
            .is_some()
        {
            return Err(format!(
                "capture tolerance {} target is already revised",
                entry.revision_id
            ));
        }

        let prior_start_m = symmetric_gate_half_extent_m(&candidate.gate_start_wkt)?;
        let prior_end_m = symmetric_gate_half_extent_m(&candidate.gate_end_wkt)?;
        let prior = &entry.prior_geometry_policy;
        if (prior_start_m - prior.gate_start_half_extent_m).abs() > 0.5
            || (prior_end_m - prior.gate_end_half_extent_m).abs() > 0.5
            || (candidate.corridor_half_width_m - prior.corridor_half_width_m).abs() > f64::EPSILON
        {
            return Err(format!(
                "capture tolerance {} prior geometry policy does not match target",
                entry.revision_id
            ));
        }

        if entry.gate_start_half_extent_m != prior.gate_start_half_extent_m {
            candidate.gate_start_wkt =
                resize_symmetric_gate(&candidate.gate_start_wkt, entry.gate_start_half_extent_m)?;
        }
        if entry.gate_end_half_extent_m != prior.gate_end_half_extent_m {
            candidate.gate_end_wkt =
                resize_symmetric_gate(&candidate.gate_end_wkt, entry.gate_end_half_extent_m)?;
        }
        if entry.corridor_half_width_m != prior.corridor_half_width_m {
            let centerline_points = line_string_profile_points(&candidate.centerline_wkt)?;
            candidate.corridor_wkt =
                corridor_envelope_wkt(&centerline_points, entry.corridor_half_width_m);
            candidate.corridor_cells =
                corridor_cells(&centerline_points, entry.corridor_half_width_m);
            candidate.corridor_half_width_m = round2(entry.corridor_half_width_m);
            candidate.provenance["corridor"]["half_width_m"] =
                json!(round2(entry.corridor_half_width_m));
        }
        let revision = json!({
            "model": CAPTURE_TOLERANCE_MODEL,
            "revision_id": entry.revision_id,
            "candidate_fingerprint": entry.candidate_fingerprint,
            "registry": resource,
            "prior_geometry_policy": entry.prior_geometry_policy,
            "revised_geometry_policy": {
                "gate_start_half_extent_m": round2(entry.gate_start_half_extent_m),
                "gate_end_half_extent_m": round2(entry.gate_end_half_extent_m),
                "corridor_half_width_m": round2(entry.corridor_half_width_m)
            },
            "record_continuity_policy": entry.record_continuity_policy,
            "unchanged_identity_fields": [
                "candidate_fingerprint",
                "legacy_candidate_fingerprints",
                "centerline",
                "canonical_profile",
                "measured_span",
                "ordered_osm_way_refs"
            ],
            "evidence": entry.evidence
        });
        candidate.provenance["capture_tolerance_revision"] = revision;
    }

    report.capture_tolerance_overrides = Some(CanonCaptureToleranceRunMetadata {
        mode: "applied_exact_fingerprint".to_string(),
        model: overrides.model.clone(),
        registry: resource.clone(),
        expected: overrides.overrides.len(),
        applied: overrides.overrides.len(),
        retained: overrides.overrides.len(),
    });
    report.warnings.push(format!(
        "applied {} provenance-bound per-candidate D10 capture tolerance revisions",
        overrides.overrides.len()
    ));
    Ok(report)
}

fn validate_capture_tolerance_overrides(
    overrides: &CanonCaptureToleranceOverrideSet,
) -> Result<(), String> {
    if overrides.model != CAPTURE_TOLERANCE_MODEL {
        return Err(format!(
            "capture tolerance model must be {CAPTURE_TOLERANCE_MODEL}, got {}",
            overrides.model
        ));
    }
    if overrides.overrides.is_empty() {
        return Err("capture tolerance registry must not be empty".to_string());
    }

    let mut revision_ids = HashSet::new();
    let mut fingerprints = HashSet::new();
    for entry in &overrides.overrides {
        if entry.revision_id.trim().is_empty() || !revision_ids.insert(&entry.revision_id) {
            return Err(format!(
                "capture tolerance revision id is empty or duplicated: {}",
                entry.revision_id
            ));
        }
        if !is_candidate_fingerprint(&entry.candidate_fingerprint)
            || !fingerprints.insert(&entry.candidate_fingerprint)
        {
            return Err(format!(
                "capture tolerance {} has an invalid or duplicate fingerprint",
                entry.revision_id
            ));
        }
        if entry.display_name.trim().is_empty() {
            return Err(format!(
                "capture tolerance {} has no display name",
                entry.revision_id
            ));
        }
        for (label, value, maximum) in [
            (
                "start gate half-extent",
                entry.gate_start_half_extent_m,
                MAX_CAPTURE_GATE_HALF_EXTENT_M,
            ),
            (
                "finish gate half-extent",
                entry.gate_end_half_extent_m,
                MAX_CAPTURE_GATE_HALF_EXTENT_M,
            ),
            (
                "corridor half-width",
                entry.corridor_half_width_m,
                MAX_CAPTURE_CORRIDOR_HALF_WIDTH_M,
            ),
        ] {
            if !value.is_finite() || value < DEFAULT_GATE_HALF_WIDTH_M || value > maximum {
                return Err(format!(
                    "capture tolerance {} {label} must be within {}..={maximum}m",
                    entry.revision_id, DEFAULT_GATE_HALF_WIDTH_M
                ));
            }
        }
        let prior = &entry.prior_geometry_policy;
        if prior.gate_start_half_extent_m != DEFAULT_GATE_HALF_WIDTH_M
            || prior.gate_end_half_extent_m != DEFAULT_GATE_HALF_WIDTH_M
            || prior.corridor_half_width_m != DEFAULT_GATE_HALF_WIDTH_M
            || prior.source.trim().is_empty()
        {
            return Err(format!(
                "capture tolerance {} must pin the prior 25/25/25 D10 policy",
                entry.revision_id
            ));
        }
        if entry.gate_start_half_extent_m == prior.gate_start_half_extent_m
            && entry.gate_end_half_extent_m == prior.gate_end_half_extent_m
            && entry.corridor_half_width_m == prior.corridor_half_width_m
        {
            return Err(format!(
                "capture tolerance {} does not change capture geometry",
                entry.revision_id
            ));
        }
        if entry.record_continuity_policy != CAPTURE_RECORD_CONTINUITY_POLICY {
            return Err(format!(
                "capture tolerance {} must preserve canon id and Record Board",
                entry.revision_id
            ));
        }
        let evidence = &entry.evidence;
        if evidence.approved_at.trim().is_empty()
            || evidence.approved_by != "Tim"
            || evidence.policy_source.trim().is_empty()
            || evidence.replay_source.trim().is_empty()
        {
            return Err(format!(
                "capture tolerance {} has incomplete ratification/replay evidence",
                entry.revision_id
            ));
        }
    }
    Ok(())
}

fn line_string_coordinates(wkt: &str) -> Result<Vec<(f64, f64)>, String> {
    let body = wkt
        .strip_prefix("LINESTRING(")
        .and_then(|value| value.strip_suffix(')'))
        .ok_or_else(|| format!("expected LINESTRING WKT, got {wkt}"))?;
    let mut coordinates = Vec::new();
    for token in body.split(',') {
        let values = token
            .split_whitespace()
            .map(str::parse::<f64>)
            .collect::<Result<Vec<_>, _>>()
            .map_err(|error| format!("invalid LINESTRING coordinate: {error}"))?;
        if values.len() != 2 || values.iter().any(|value| !value.is_finite()) {
            return Err("LINESTRING coordinates must be finite lon/lat pairs".to_string());
        }
        coordinates.push((values[0], values[1]));
    }
    if coordinates.len() < 2 {
        return Err("LINESTRING must contain at least two coordinates".to_string());
    }
    Ok(coordinates)
}

fn line_string_profile_points(wkt: &str) -> Result<Vec<CanonProfilePoint>, String> {
    Ok(line_string_coordinates(wkt)?
        .into_iter()
        .map(|(lon, lat)| CanonProfilePoint {
            dist_m: 0.0,
            lat,
            lon,
            elev_m: 0.0,
        })
        .collect())
}

fn symmetric_gate_half_extent_m(wkt: &str) -> Result<f64, String> {
    let coordinates = line_string_coordinates(wkt)?;
    if coordinates.len() != 2 {
        return Err("gate LINESTRING must contain exactly two coordinates".to_string());
    }
    let a = coordinates[0];
    let b = coordinates[1];
    let midpoint = ((a.0 + b.0) / 2.0, (a.1 + b.1) / 2.0);
    let a_m = haversine_m(midpoint.1, midpoint.0, a.1, a.0);
    let b_m = haversine_m(midpoint.1, midpoint.0, b.1, b.0);
    if (a_m - b_m).abs() > 0.5 || a_m <= 0.0 || b_m <= 0.0 {
        return Err("gate is not a non-zero symmetric line".to_string());
    }
    Ok((a_m + b_m) / 2.0)
}

fn resize_symmetric_gate(wkt: &str, half_extent_m: f64) -> Result<String, String> {
    let coordinates = line_string_coordinates(wkt)?;
    if coordinates.len() != 2 {
        return Err("gate LINESTRING must contain exactly two coordinates".to_string());
    }
    let a = coordinates[0];
    let b = coordinates[1];
    let midpoint = ((a.0 + b.0) / 2.0, (a.1 + b.1) / 2.0);
    let current_m = symmetric_gate_half_extent_m(wkt)?;
    let scale = half_extent_m / current_m;
    let resized_a = (
        midpoint.0 + (a.0 - midpoint.0) * scale,
        midpoint.1 + (a.1 - midpoint.1) * scale,
    );
    let resized_b = (
        midpoint.0 + (b.0 - midpoint.0) * scale,
        midpoint.1 + (b.1 - midpoint.1) * scale,
    );
    let resized = format!(
        "LINESTRING({}, {})",
        format_coord(resized_a.0, resized_a.1),
        format_coord(resized_b.0, resized_b.1)
    );
    if (symmetric_gate_half_extent_m(&resized)? - half_extent_m).abs() > 0.5 {
        return Err("resized gate did not reach the requested half-extent".to_string());
    }
    Ok(resized)
}

fn validate_ratified_boundary_decisions(
    decisions: &RatifiedBoundaryDecisionSet,
) -> Result<(), String> {
    if decisions.model != RATIFIED_BOUNDARY_MODEL {
        return Err(format!(
            "ratified boundary model must be {RATIFIED_BOUNDARY_MODEL}, got {}",
            decisions.model
        ));
    }

    let mut ids = HashSet::new();
    let mut targets = HashSet::new();
    let mut lineage_owners = HashMap::new();
    for decision in &decisions.decisions {
        if decision.decision_id.trim().is_empty() || !ids.insert(&decision.decision_id) {
            return Err(format!(
                "ratified boundary decision id is empty or duplicated: {}",
                decision.decision_id
            ));
        }
        if decision.display_name.trim().is_empty() {
            return Err(format!(
                "ratified boundary {} has no display name",
                decision.decision_id
            ));
        }
        if decision.osm_way_refs.is_empty() || decision.osm_way_refs.len() > CHAIN_MAX_SEGMENTS {
            return Err(format!(
                "ratified boundary {} ({}) must contain 1..={} ordered OSM ways",
                decision.decision_id, decision.display_name, CHAIN_MAX_SEGMENTS
            ));
        }
        if let Some(RatifiedFinishDecision::Crest {
            decision: choice,
            finish_at,
            finish_m_past_current,
            reason,
        }) = &decision.finish_decision
        {
            if choice != "extend_crest"
                || finish_at.trim().is_empty()
                || reason.trim().is_empty()
                || !finish_m_past_current.is_finite()
                || *finish_m_past_current <= 0.0
                || decision.end.osm_node_id.is_some()
                || decision.start.exact_gate.is_none()
                || decision.end.exact_gate.is_some()
            {
                return Err(format!("{}: crest finish needs founder approval, an unchanged exact start and a natural-top anchor without a junction or gate override", decision.display_name));
            }
        }
        let unique_refs = decision
            .osm_way_refs
            .iter()
            .copied()
            .collect::<HashSet<_>>();
        if unique_refs.len() != decision.osm_way_refs.len() {
            return Err(format!(
                "ratified boundary {} repeats an OSM way",
                decision.decision_id
            ));
        }
        if !is_candidate_fingerprint(&decision.replaces_candidate_fingerprint)
            || !targets.insert(&decision.replaces_candidate_fingerprint)
        {
            return Err(format!(
                "ratified boundary {} has an invalid or duplicated replacement fingerprint",
                decision.decision_id
            ));
        }
        claim_fingerprint_lineage(
            &mut lineage_owners,
            &decision.replaces_candidate_fingerprint,
            &decision.decision_id,
        )?;
        for fingerprint in &decision.legacy_candidate_fingerprints {
            if !is_candidate_fingerprint(fingerprint) {
                return Err(format!(
                    "ratified boundary {} has invalid legacy fingerprint {}",
                    decision.decision_id, fingerprint
                ));
            }
            claim_fingerprint_lineage(&mut lineage_owners, fingerprint, &decision.decision_id)?;
        }
        validate_ratified_anchor(&decision.decision_id, "start", &decision.start)?;
        validate_ratified_anchor(&decision.decision_id, "end", &decision.end)?;
        if !has_complete_approval_evidence(&decision.evidence.requirement)
            || decision
                .evidence
                .geometry_translation
                .resolved_at
                .trim()
                .is_empty()
            || decision
                .evidence
                .geometry_translation
                .resolved_by
                .trim()
                .is_empty()
            || decision
                .evidence
                .geometry_translation
                .source
                .trim()
                .is_empty()
            || decision
                .evidence
                .visual_approval
                .as_ref()
                .is_some_and(|evidence| !has_complete_approval_evidence(evidence))
        {
            return Err(format!(
                "ratified boundary {} has incomplete approval evidence",
                decision.decision_id
            ));
        }
    }
    Ok(())
}

fn claim_fingerprint_lineage<'a>(
    owners: &mut HashMap<&'a str, &'a str>,
    fingerprint: &'a str,
    decision_id: &'a str,
) -> Result<(), String> {
    if let Some(existing_owner) = owners.insert(fingerprint, decision_id) {
        return Err(format!(
            "ratified boundary fingerprint lineage {fingerprint} is claimed by both {existing_owner} and {decision_id}"
        ));
    }
    Ok(())
}

fn validate_candidate_fingerprint_ownership(candidates: &[CanonCandidate]) -> Result<(), String> {
    let mut owners: HashMap<&str, &str> = HashMap::new();
    for candidate in candidates {
        for fingerprint in std::iter::once(&candidate.candidate_fingerprint)
            .chain(candidate.legacy_candidate_fingerprints.iter())
        {
            if let Some(existing_owner) =
                owners.insert(fingerprint, &candidate.candidate_fingerprint)
            {
                return Err(format!(
                    "canon fingerprint lineage {fingerprint} belongs to both {existing_owner} and {}",
                    candidate.candidate_fingerprint
                ));
            }
        }
    }
    Ok(())
}

fn has_complete_approval_evidence(evidence: &RatifiedBoundaryApprovalEvidence) -> bool {
    !evidence.approved_at.trim().is_empty()
        && !evidence.approved_by.trim().is_empty()
        && !evidence.source.trim().is_empty()
}

fn validate_ratified_anchor(
    decision_id: &str,
    side: &str,
    anchor: &RatifiedBoundaryAnchor,
) -> Result<(), String> {
    if anchor.label.trim().is_empty()
        || !anchor.lat.is_finite()
        || !anchor.lon.is_finite()
        || !(-90.0..=90.0).contains(&anchor.lat)
        || !(-180.0..=180.0).contains(&anchor.lon)
        || !anchor.max_offset_m.is_finite()
        || anchor.max_offset_m <= 0.0
        || anchor.max_offset_m > RATIFIED_BOUNDARY_MAX_ANCHOR_OFFSET_M
    {
        return Err(format!(
            "ratified boundary {decision_id} has invalid {side} anchor"
        ));
    }
    if let Some(gate) = &anchor.exact_gate {
        let coordinates = [gate.a_lat, gate.a_lon, gate.b_lat, gate.b_lon];
        if coordinates.iter().any(|value| !value.is_finite())
            || !(-90.0..=90.0).contains(&gate.a_lat)
            || !(-90.0..=90.0).contains(&gate.b_lat)
            || !(-180.0..=180.0).contains(&gate.a_lon)
            || !(-180.0..=180.0).contains(&gate.b_lon)
        {
            return Err(format!(
                "ratified boundary {decision_id} has invalid {side} gate coordinates"
            ));
        }
        let a_m = haversine_m(anchor.lat, anchor.lon, gate.a_lat, gate.a_lon);
        let b_m = haversine_m(anchor.lat, anchor.lon, gate.b_lat, gate.b_lon);
        let midpoint_lat = (gate.a_lat + gate.b_lat) / 2.0;
        let midpoint_lon = (gate.a_lon + gate.b_lon) / 2.0;
        let midpoint_offset_m = haversine_m(anchor.lat, anchor.lon, midpoint_lat, midpoint_lon);
        if (a_m - DEFAULT_GATE_HALF_WIDTH_M).abs() > 0.5
            || (b_m - DEFAULT_GATE_HALF_WIDTH_M).abs() > 0.5
            || midpoint_offset_m > 0.25
        {
            return Err(format!(
                "ratified boundary {decision_id} {side} gate must be centered on its anchor with 25 m half-width"
            ));
        }
    }
    Ok(())
}

fn ratified_gate_wkt(gate: &RatifiedBoundaryGate) -> String {
    format!(
        "LINESTRING({}, {})",
        format_coord(gate.a_lon, gate.a_lat),
        format_coord(gate.b_lon, gate.b_lat)
    )
}

fn apply_ratified_exact_gate_identity(
    candidate: &mut CanonCandidate,
    decision: &RatifiedBoundaryDecision,
) {
    apply_exact_gate_identity(
        candidate,
        decision.start.exact_gate.as_ref(),
        decision.end.exact_gate.as_ref(),
    );
}

fn apply_exact_gate_identity(
    candidate: &mut CanonCandidate,
    start: Option<&RatifiedBoundaryGate>,
    end: Option<&RatifiedBoundaryGate>,
) {
    if start.is_none() && end.is_none() {
        return;
    }

    let base_fingerprint = candidate.candidate_fingerprint.clone();
    let mut hasher = Hasher::new();
    hasher.update(b"boulderroller-canon-ratified-exact-gates-v1");
    hasher.update(base_fingerprint.as_bytes());
    hash_optional_ratified_gate(&mut hasher, start);
    hash_optional_ratified_gate(&mut hasher, end);
    candidate.candidate_fingerprint = hasher.finalize().to_hex().to_string();

    let legacy_v2_value = candidate.provenance["candidate_fingerprint"]["legacy_v2_value"]
        .as_str()
        .map(str::to_string);
    candidate.provenance["candidate_fingerprint"] = json!({
        "algorithm": "blake3_ratified_exact_gates_v1",
        "base_algorithm": "blake3_way_refs_geometry_sketch_v3",
        "base_value": base_fingerprint,
        "exact_gate_start": start,
        "exact_gate_end": end,
        "legacy_v2_value": legacy_v2_value
    });
}

fn hash_optional_ratified_gate(hasher: &mut Hasher, gate: Option<&RatifiedBoundaryGate>) {
    let Some(gate) = gate else {
        hasher.update(b"none");
        return;
    };
    hasher.update(b"exact");
    let mut endpoints = [(gate.a_lon, gate.a_lat), (gate.b_lon, gate.b_lat)];
    endpoints.sort_by(|left, right| {
        left.0
            .total_cmp(&right.0)
            .then_with(|| left.1.total_cmp(&right.1))
    });
    for (lon, lat) in endpoints {
        hasher.update(format_coord(lon, lat).as_bytes());
        hasher.update(b";");
    }
}

fn is_candidate_fingerprint(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn push_fingerprint_lineage(lineage: &mut Vec<String>, current: &str, fingerprint: String) {
    if fingerprint != current && !lineage.contains(&fingerprint) {
        lineage.push(fingerprint);
    }
}

fn build_ratified_road_feature(
    decision: &RatifiedBoundaryDecision,
    points: &[CanonProfilePoint],
    road_by_id: &HashMap<i64, &RoadFeature>,
) -> Result<RoadFeature, String> {
    let mut source_roads = Vec::with_capacity(decision.osm_way_refs.len());
    for way_ref in &decision.osm_way_refs {
        let road = road_by_id.get(way_ref).copied().ok_or_else(|| {
            format!(
                "ratified boundary {} is missing OSM way {}",
                decision.decision_id, way_ref
            )
        })?;
        if !is_launch_scope_road(road) {
            return Err(format!(
                "ratified boundary {} uses out-of-scope OSM way {}",
                decision.decision_id, way_ref
            ));
        }
        source_roads.push(road);
    }

    let first = source_roads[0];
    let mut road = RoadFeature::new(first.osm_way_id, first.road_class);
    road.highway_tag = first.highway_tag.clone();
    road.name = decision
        .route_name
        .clone()
        .or_else(|| Some(decision.display_name.clone()));
    road.length_m = points.last().map(|point| point.dist_m).unwrap_or(0.0) as f32;
    road.geometry = points.iter().map(|point| (point.lon, point.lat)).collect();
    road.h3_cells = source_roads
        .iter()
        .flat_map(|source| source.h3_cells.iter().cloned())
        .collect();
    road.has_bike_infra = source_roads.iter().any(|source| source.has_bike_infra);
    road.surface = source_roads
        .iter()
        .find_map(|source| source.surface.clone());
    Ok(road)
}

fn build_ratified_profile(
    decision: &RatifiedBoundaryDecision,
    profiles: &HashMap<i64, LocalElevationProfile>,
    road_by_id: &HashMap<i64, &RoadFeature>,
) -> Result<RatifiedProfile, String> {
    let mut source_profiles = Vec::with_capacity(decision.osm_way_refs.len());
    let mut source_roads = Vec::with_capacity(decision.osm_way_refs.len());
    for way_ref in &decision.osm_way_refs {
        let road = road_by_id.get(way_ref).copied().ok_or_else(|| {
            format!(
                "ratified boundary {} is missing OSM way {}",
                decision.decision_id, way_ref
            )
        })?;
        let profile = profiles.get(way_ref).ok_or_else(|| {
            format!(
                "ratified boundary {} is missing local DEM profile for OSM way {}",
                decision.decision_id, way_ref
            )
        })?;
        if profile.points.len() < 2 {
            return Err(format!(
                "ratified boundary {} has fewer than two profile points for OSM way {}",
                decision.decision_id, way_ref
            ));
        }
        source_roads.push(road);
        source_profiles.push(profile.points.clone());
    }

    validate_ratified_osm_anchor(
        &decision.decision_id,
        "start",
        &decision.start,
        &source_roads,
    )?;
    validate_ratified_osm_anchor(&decision.decision_id, "end", &decision.end, &source_roads)?;

    let mut source_seams = Vec::with_capacity(source_profiles.len().saturating_sub(1));
    for index in 0..source_profiles.len().saturating_sub(1) {
        source_seams.push(ratified_profile_seam_at_shared_node(
            &decision.decision_id,
            source_roads[index],
            source_roads[index + 1],
            &source_profiles[index],
            &source_profiles[index + 1],
        )?);
    }

    let orientation_count = 1usize << source_profiles.len();
    let mut valid_profiles = Vec::new();
    for mask in 0..orientation_count {
        let mut oriented_profiles = Vec::with_capacity(source_profiles.len());
        let mut reversed_way_refs = Vec::new();
        for (index, source) in source_profiles.iter().enumerate() {
            let mut points = source.clone();
            if mask & (1usize << index) != 0 {
                points.reverse();
                reversed_way_refs.push(decision.osm_way_refs[index]);
            }
            rebase_distances(&mut points);
            oriented_profiles.push(points);
        }

        let oriented_seams = source_seams
            .iter()
            .enumerate()
            .map(|(index, seam)| RatifiedProfileSeam {
                left_index: oriented_profile_index(
                    seam.left_index,
                    source_profiles[index].len(),
                    mask & (1usize << index) != 0,
                ),
                right_index: oriented_profile_index(
                    seam.right_index,
                    source_profiles[index + 1].len(),
                    mask & (1usize << (index + 1)) != 0,
                ),
                gap_m: seam.gap_m,
                elevation_delta_m: seam.elevation_delta_m,
            })
            .collect::<Vec<_>>();

        let mut stitched = Vec::new();
        let mut ordered = true;
        for (index, points) in oriented_profiles.into_iter().enumerate() {
            let start_index = if index == 0 {
                0
            } else {
                oriented_seams[index - 1].right_index
            };
            let end_index = if index + 1 == source_profiles.len() {
                points.len() - 1
            } else {
                oriented_seams[index].left_index
            };
            if start_index > end_index {
                ordered = false;
                break;
            }
            for point in points[start_index..=end_index].iter().cloned() {
                push_distinct_profile_point(&mut stitched, point);
            }
        }
        if !ordered {
            continue;
        }
        rebase_distances(&mut stitched);
        let Some(start_projection) = project_ratified_anchor_onto_profile(
            &decision.decision_id,
            "start",
            &decision.start,
            &stitched,
        )?
        else {
            continue;
        };
        let Some(end_projection) = project_ratified_anchor_onto_profile(
            &decision.decision_id,
            "end",
            &decision.end,
            &stitched,
        )?
        else {
            continue;
        };
        if start_projection.offset_m > decision.start.max_offset_m
            || end_projection.offset_m > decision.end.max_offset_m
            || end_projection.along_m - start_projection.along_m < MIN_GRADIENT_SEGMENT_DISTANCE_M
        {
            continue;
        }
        let points =
            trim_profile_to_anchor_projections(&stitched, &start_projection, &end_projection);
        if points.len() < 2 {
            continue;
        }
        let seam_gaps_m = oriented_seams
            .iter()
            .map(|seam| seam.gap_m)
            .collect::<Vec<_>>();
        let seam_elevation_deltas_m = oriented_seams
            .iter()
            .map(|seam| seam.elevation_delta_m)
            .collect::<Vec<_>>();
        let fit_score_m =
            seam_gaps_m.iter().sum::<f64>() + start_projection.offset_m + end_projection.offset_m;
        valid_profiles.push(RatifiedProfile {
            points,
            reversed_way_refs,
            seam_gaps_m,
            seam_elevation_deltas_m,
            start_offset_m: start_projection.offset_m,
            end_offset_m: end_projection.offset_m,
            fit_score_m,
        });
    }

    valid_profiles.sort_by(|left, right| {
        left.fit_score_m
            .partial_cmp(&right.fit_score_m)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.reversed_way_refs.cmp(&right.reversed_way_refs))
    });
    let Some(best) = valid_profiles.first().cloned() else {
        return Err(format!(
            "ratified boundary {} cannot form an ordered profile with exact anchors and bounded seams",
            decision.decision_id
        ));
    };
    if let Some(second) = valid_profiles.get(1) {
        if second.fit_score_m - best.fit_score_m <= RATIFIED_BOUNDARY_AMBIGUITY_M
            && second.reversed_way_refs != best.reversed_way_refs
        {
            return Err(format!(
                "ratified boundary {} has ambiguous way orientation",
                decision.decision_id
            ));
        }
    }
    Ok(best)
}

fn ratified_profile_seam_at_shared_node(
    decision_id: &str,
    left_road: &RoadFeature,
    right_road: &RoadFeature,
    left: &[CanonProfilePoint],
    right: &[CanonProfilePoint],
) -> Result<RatifiedProfileSeam, String> {
    let shared_nodes = shared_osm_nodes(left_road, right_road)?;
    if shared_nodes.len() != 1 {
        return Err(format!(
            "ratified boundary {decision_id} requires exactly one shared OSM node between ways {} and {}, found {}",
            left_road.osm_way_id,
            right_road.osm_way_id,
            shared_nodes.len()
        ));
    }
    let (node_id, lon, lat) = shared_nodes[0];
    let left_index = unambiguous_profile_node_index(left, lon, lat).map_err(|reason| {
        format!(
            "ratified boundary {decision_id} cannot resolve shared OSM node {node_id} on way {}: {reason}",
            left_road.osm_way_id
        )
    })?;
    let right_index = unambiguous_profile_node_index(right, lon, lat).map_err(|reason| {
        format!(
            "ratified boundary {decision_id} cannot resolve shared OSM node {node_id} on way {}: {reason}",
            right_road.osm_way_id
        )
    })?;
    let left_point = &left[left_index];
    let right_point = &right[right_index];
    let gap_m = haversine_m(
        left_point.lat,
        left_point.lon,
        right_point.lat,
        right_point.lon,
    );
    let elevation_delta_m = right_point.elev_m - left_point.elev_m;
    if gap_m > RATIFIED_OSM_NODE_COORD_TOLERANCE_M
        || elevation_delta_m.abs() > CHAIN_MAX_ELEVATION_SEAM_M
    {
        return Err(format!(
            "ratified boundary {decision_id} shared OSM node {node_id} has profile seam gap {gap_m:.2}m and elevation delta {elevation_delta_m:.2}m"
        ));
    }
    Ok(RatifiedProfileSeam {
        left_index,
        right_index,
        gap_m,
        elevation_delta_m,
    })
}

fn shared_osm_nodes(
    left: &RoadFeature,
    right: &RoadFeature,
) -> Result<Vec<(i64, f64, f64)>, String> {
    let left_nodes = road_osm_node_coordinates(left)?;
    let right_nodes = road_osm_node_coordinates(right)?;
    let mut shared = Vec::new();
    for (node_id, (left_lon, left_lat)) in left_nodes {
        let Some((right_lon, right_lat)) = right_nodes.get(&node_id).copied() else {
            continue;
        };
        let coordinate_gap_m = haversine_m(left_lat, left_lon, right_lat, right_lon);
        if coordinate_gap_m > RATIFIED_OSM_NODE_COORD_TOLERANCE_M {
            return Err(format!(
                "shared OSM node {node_id} has inconsistent coordinates on ways {} and {}",
                left.osm_way_id, right.osm_way_id
            ));
        }
        shared.push((node_id, left_lon, left_lat));
    }
    shared.sort_by_key(|(node_id, _, _)| *node_id);
    Ok(shared)
}

fn road_osm_node_coordinates(road: &RoadFeature) -> Result<HashMap<i64, (f64, f64)>, String> {
    if road.osm_node_ids.len() != road.geometry.len() {
        return Err(format!(
            "OSM way {} has no node-ID-aligned road graph geometry",
            road.osm_way_id
        ));
    }
    let mut nodes = HashMap::new();
    for (node_id, coordinate) in road
        .osm_node_ids
        .iter()
        .copied()
        .zip(road.geometry.iter().copied())
    {
        if node_id == 0 {
            continue;
        }
        if let Some(previous) = nodes.insert(node_id, coordinate) {
            let gap_m = haversine_m(previous.1, previous.0, coordinate.1, coordinate.0);
            if gap_m > RATIFIED_OSM_NODE_COORD_TOLERANCE_M {
                return Err(format!(
                    "OSM way {} repeats node {} at inconsistent coordinates",
                    road.osm_way_id, node_id
                ));
            }
        }
    }
    Ok(nodes)
}

fn unambiguous_profile_node_index(
    points: &[CanonProfilePoint],
    lon: f64,
    lat: f64,
) -> Result<usize, &'static str> {
    let mut matches = points
        .iter()
        .enumerate()
        .filter_map(|(index, point)| {
            let offset_m = haversine_m(lat, lon, point.lat, point.lon);
            (offset_m <= RATIFIED_OSM_NODE_COORD_TOLERANCE_M).then_some((index, offset_m))
        })
        .collect::<Vec<_>>();
    matches.sort_by(|left, right| {
        left.1
            .total_cmp(&right.1)
            .then_with(|| left.0.cmp(&right.0))
    });
    let Some((best_index, best_offset_m)) = matches.first().copied() else {
        return Err("profile does not contain the shared node coordinate");
    };
    if matches.iter().skip(1).any(|(index, offset_m)| {
        *offset_m - best_offset_m <= RATIFIED_BOUNDARY_AMBIGUITY_M
            && (points[*index].dist_m - points[best_index].dist_m).abs()
                > RATIFIED_BOUNDARY_AMBIGUITY_M
    }) {
        return Err("profile contains ambiguous occurrences of the shared node");
    }
    Ok(best_index)
}

fn validate_ratified_osm_anchor(
    decision_id: &str,
    side: &str,
    anchor: &RatifiedBoundaryAnchor,
    roads: &[&RoadFeature],
) -> Result<(), String> {
    let Some(node_id) = anchor.osm_node_id else {
        return Ok(());
    };
    let mut coordinates = Vec::new();
    for road in roads {
        if let Some(coordinate) = road_osm_node_coordinates(road)?.get(&node_id).copied() {
            coordinates.push(coordinate);
        }
    }
    let Some((node_lon, node_lat)) = coordinates.first().copied() else {
        return Err(format!(
            "ratified boundary {decision_id} {side} OSM node {node_id} is not present on its selected ways"
        ));
    };
    for (lon, lat) in coordinates.iter().copied().skip(1) {
        if haversine_m(node_lat, node_lon, lat, lon) > RATIFIED_OSM_NODE_COORD_TOLERANCE_M {
            return Err(format!(
                "ratified boundary {decision_id} {side} OSM node {node_id} has inconsistent selected-way coordinates"
            ));
        }
    }
    let anchor_offset_m = haversine_m(anchor.lat, anchor.lon, node_lat, node_lon);
    if anchor_offset_m > RATIFIED_OSM_NODE_COORD_TOLERANCE_M {
        return Err(format!(
            "ratified boundary {decision_id} {side} OSM node {node_id} is {anchor_offset_m:.2}m from its declared anchor"
        ));
    }
    Ok(())
}

fn oriented_profile_index(index: usize, len: usize, reversed: bool) -> usize {
    if reversed {
        len - 1 - index
    } else {
        index
    }
}

fn push_distinct_profile_point(points: &mut Vec<CanonProfilePoint>, point: CanonProfilePoint) {
    if let Some(previous) = points.last() {
        if haversine_m(previous.lat, previous.lon, point.lat, point.lon) <= 0.05 {
            return;
        }
    }
    points.push(point);
}

fn project_anchor_onto_profile(
    anchor: &RatifiedBoundaryAnchor,
    points: &[CanonProfilePoint],
) -> Result<Option<AnchorProjection>, ()> {
    project_anchor_onto_profile_with_max_offset(anchor, points, None)
}

fn project_anchor_onto_profile_with_max_offset(
    anchor: &RatifiedBoundaryAnchor,
    points: &[CanonProfilePoint],
    max_offset_m: Option<f64>,
) -> Result<Option<AnchorProjection>, ()> {
    if points.len() < 2 {
        return Ok(None);
    }

    let lat_scale = 111_320.0;
    let lon_scale = 111_320.0 * anchor.lat.to_radians().cos().abs().max(0.1);
    let mut along_m = 0.0;
    let mut projections = Vec::with_capacity(points.len() - 1);
    for (segment_index, window) in points.windows(2).enumerate() {
        let start = &window[0];
        let end = &window[1];
        let start_x = (start.lon - anchor.lon) * lon_scale;
        let start_y = (start.lat - anchor.lat) * lat_scale;
        let delta_x = (end.lon - start.lon) * lon_scale;
        let delta_y = (end.lat - start.lat) * lat_scale;
        let norm_sq = delta_x * delta_x + delta_y * delta_y;
        if norm_sq <= f64::EPSILON {
            continue;
        }
        let ratio = (-(start_x * delta_x + start_y * delta_y) / norm_sq).clamp(0.0, 1.0);
        let projected_x = start_x + ratio * delta_x;
        let projected_y = start_y + ratio * delta_y;
        let offset_m = (projected_x * projected_x + projected_y * projected_y).sqrt();
        let segment_m = haversine_m(start.lat, start.lon, end.lat, end.lon);
        let projection = AnchorProjection {
            segment_index,
            along_m: along_m + segment_m * ratio,
            offset_m,
            point: CanonProfilePoint {
                dist_m: 0.0,
                lat: anchor.lat,
                lon: anchor.lon,
                elev_m: start.elev_m + (end.elev_m - start.elev_m) * ratio,
            },
        };
        projections.push(projection);
        along_m += segment_m;
    }
    projections.sort_by(|left, right| {
        left.offset_m
            .total_cmp(&right.offset_m)
            .then_with(|| left.along_m.total_cmp(&right.along_m))
    });
    let Some(best) = projections.first().cloned() else {
        return Ok(None);
    };
    // An orientation that does not reach this anchor is not an ambiguous fit.
    // In particular, a short connector can otherwise reject the valid reverse
    // orientation before the complete ordered route is considered.
    if max_offset_m.is_some_and(|limit| best.offset_m > limit) {
        return Ok(None);
    }
    if projections.iter().skip(1).any(|alternate| {
        alternate.offset_m - best.offset_m <= RATIFIED_BOUNDARY_AMBIGUITY_M
            && (alternate.along_m - best.along_m).abs() > RATIFIED_BOUNDARY_AMBIGUITY_M
    }) {
        return Err(());
    }
    Ok(Some(best))
}

fn project_ratified_anchor_onto_profile(
    decision_id: &str,
    side: &str,
    anchor: &RatifiedBoundaryAnchor,
    points: &[CanonProfilePoint],
) -> Result<Option<AnchorProjection>, String> {
    if anchor.osm_node_id.is_none() {
        return project_anchor_onto_profile_with_max_offset(anchor, points, Some(anchor.max_offset_m)).map_err(|_| {
            format!("ratified boundary {decision_id} has ambiguous {side} anchor projection")
        });
    }
    if points.len() < 2 {
        return Ok(None);
    }
    let index = match unambiguous_profile_node_index(points, anchor.lon, anchor.lat) {
        Ok(index) => index,
        Err("profile does not contain the shared node coordinate") => return Ok(None),
        Err(reason) => {
            return Err(format!(
                "ratified boundary {decision_id} cannot resolve {side} OSM-node anchor in its stitched profile: {reason}"
            ));
        }
    };
    let source = &points[index];
    let segment_index = if side == "end" {
        index.saturating_sub(1)
    } else {
        index.min(points.len() - 2)
    };
    Ok(Some(AnchorProjection {
        segment_index,
        along_m: source.dist_m,
        offset_m: haversine_m(anchor.lat, anchor.lon, source.lat, source.lon),
        point: CanonProfilePoint {
            dist_m: 0.0,
            lat: anchor.lat,
            lon: anchor.lon,
            elev_m: source.elev_m,
        },
    }))
}

fn trim_profile_to_anchor_projections(
    points: &[CanonProfilePoint],
    start: &AnchorProjection,
    end: &AnchorProjection,
) -> Vec<CanonProfilePoint> {
    let mut selected = vec![start.point.clone()];
    for point in points
        .iter()
        .take(end.segment_index + 1)
        .skip(start.segment_index + 1)
    {
        push_distinct_profile_point(&mut selected, point.clone());
    }
    push_distinct_profile_point(&mut selected, end.point.clone());
    rebase_distances(&mut selected);
    selected
}

fn push_unique_directional_chain_candidate(
    candidate: CanonCandidate,
    chain: &WayChain,
    seen_fingerprints: &mut HashSet<String>,
    chained_segment_ids: &mut HashSet<usize>,
    directionally_emitted_way_ids: &mut HashSet<i64>,
    candidates: &mut Vec<CanonCandidate>,
) -> bool {
    if !seen_fingerprints.insert(candidate.candidate_fingerprint.clone()) {
        return false;
    }

    chained_segment_ids.extend(chain.segments.iter().map(|segment| segment.segment_id));
    directionally_emitted_way_ids
        .extend(chain.segments.iter().map(|segment| segment.road.osm_way_id));
    candidates.push(candidate);
    true
}

fn compile_single_road(
    road: &RoadFeature,
    profile: &LocalElevationProfile,
    intersection_indices: &BTreeSet<usize>,
    config: &CanonCompileConfig,
) -> Option<CanonCandidate> {
    let osm_way_refs = [road.osm_way_id];
    compile_candidate(
        road,
        profile,
        config,
        &osm_way_refs,
        intersection_indices,
        &[],
        CandidateProvenance::default(),
    )
}

fn compile_way_segment(
    segment: &WayChainSegment,
    config: &CanonCompileConfig,
) -> Option<CanonCandidate> {
    let osm_way_refs = [segment.road.osm_way_id];
    compile_selected_candidate(
        &segment.road,
        segment.points.clone(),
        config,
        &osm_way_refs,
        &[],
        CandidateProvenance {
            directional_extraction: Some(json!({
                "algorithm": "bidirectional_maximal_ascent_v1",
                "source_profile_reversed": segment.source_reversed,
                "opposite_to_v020_primary_orientation": true,
                "chain_stage": "pre_chain"
            })),
            ..CandidateProvenance::default()
        },
        segment.persistence_m,
        BoundarySnap {
            index: 0,
            reason: segment.start_boundary_reason,
        },
        BoundarySnap {
            index: segment.points.len().saturating_sub(1),
            reason: segment.end_boundary_reason,
        },
    )
}

fn compile_candidate(
    road: &RoadFeature,
    profile: &LocalElevationProfile,
    config: &CanonCompileConfig,
    osm_way_refs: &[i64],
    intersection_indices: &BTreeSet<usize>,
    extra_low_confidence_flags: &[String],
    provenance: CandidateProvenance,
) -> Option<CanonCandidate> {
    if profile.points.len() < 2 {
        return None;
    }

    let oriented = orient_uphill(&profile.points);
    let oriented_intersections =
        oriented_intersection_indices(&profile.points, intersection_indices);
    compile_oriented_candidate(
        road,
        &LocalElevationProfile {
            osm_way_id: profile.osm_way_id,
            points: oriented,
        },
        config,
        osm_way_refs,
        &oriented_intersections,
        extra_low_confidence_flags,
        provenance,
    )
}

fn compile_oriented_candidate(
    road: &RoadFeature,
    profile: &LocalElevationProfile,
    config: &CanonCompileConfig,
    osm_way_refs: &[i64],
    intersection_indices: &BTreeSet<usize>,
    extra_low_confidence_flags: &[String],
    provenance: CandidateProvenance,
) -> Option<CanonCandidate> {
    if profile.points.len() < 2 {
        return None;
    }
    let mut oriented = profile.points.clone();
    rebase_distances(&mut oriented);
    let (span_start, span_end, persistence_m) = select_ascent_span(&oriented)?;

    let start_snap = snap_start_boundary(
        &oriented,
        span_start,
        config.boundary_snap_m,
        intersection_indices,
    );
    let end_snap = snap_end_boundary(
        &oriented,
        span_end,
        config.boundary_snap_m,
        intersection_indices,
    );
    if end_snap.index <= start_snap.index {
        return None;
    }

    let mut selected = oriented[start_snap.index..=end_snap.index].to_vec();
    rebase_distances(&mut selected);

    compile_selected_candidate(
        road,
        selected,
        config,
        osm_way_refs,
        extra_low_confidence_flags,
        provenance,
        persistence_m,
        BoundarySnap {
            index: 0,
            reason: start_snap.reason,
        },
        BoundarySnap {
            index: end_snap.index - start_snap.index,
            reason: end_snap.reason,
        },
    )
}

#[allow(clippy::too_many_arguments)]
fn compile_selected_candidate(
    road: &RoadFeature,
    mut selected: Vec<CanonProfilePoint>,
    config: &CanonCompileConfig,
    osm_way_refs: &[i64],
    extra_low_confidence_flags: &[String],
    candidate_provenance: CandidateProvenance,
    persistence_m: f64,
    start_snap: BoundarySnap,
    end_snap: BoundarySnap,
) -> Option<CanonCandidate> {
    if selected.len() < 2 {
        return None;
    }
    rebase_distances(&mut selected);

    let length_m = selected.last()?.dist_m - selected.first()?.dist_m;
    let vert_m = net_rise_m(&selected)?;
    if vert_m < config.min_vert_m || length_m < config.min_length_m {
        return None;
    }

    let avg_gradient_pct = if length_m > 0.0 {
        vert_m / length_m * 100.0
    } else {
        0.0
    };
    let max_gradient_pct = max_gradient_pct(&selected);
    let spacing = profile_spacing_stats(&selected);

    let mut low_confidence_flags = Vec::new();
    if spacing.max_m > SPARSE_PROFILE_SPACING_M {
        low_confidence_flags.push(format!(
            "profile_spacing_exceeds_{}m",
            SPARSE_PROFILE_SPACING_M as u32
        ));
    }
    if !config.dem_source.to_lowercase().contains("3dep") {
        low_confidence_flags.push("dem_source_not_3dep_declared".to_string());
    }
    low_confidence_flags.extend(extra_low_confidence_flags.iter().cloned());
    low_confidence_flags.push("topographic_isolation_not_scored_v0".to_string());

    let worthiness_score = segment_worthiness_score(
        road,
        &selected,
        vert_m,
        avg_gradient_pct,
        max_gradient_pct,
        &start_snap,
        &end_snap,
    );
    let confidence = confidence_tier(worthiness_score, &low_confidence_flags);

    let canonical_profile = selected
        .iter()
        .map(|point| CanonProfileSample {
            dist_m: round2(point.dist_m),
            elev_m: round2(point.elev_m),
        })
        .collect::<Vec<_>>();
    let centerline_points = selected
        .iter()
        .map(|point| (point.lat, point.lon))
        .collect::<Vec<_>>();
    let centerline_polyline = encode_polyline(&centerline_points, 5);
    let centerline_wkt = line_string_wkt(&selected);
    let corridor_wkt = corridor_envelope_wkt(&selected, config.gate_half_width_m);
    let gate_start_wkt = gate_wkt(&selected, 0, config.gate_half_width_m);
    let gate_end_wkt = gate_wkt(&selected, selected.len() - 1, config.gate_half_width_m);
    let corridor_cells = corridor_cells(&selected, config.gate_half_width_m);

    let candidate_fingerprint = candidate_fingerprint(osm_way_refs, &selected);
    let legacy_candidate_fingerprint = legacy_candidate_fingerprint_v2(osm_way_refs, &selected);
    let canonical_profile_hash = canonical_profile_hash(&canonical_profile);
    let route_name = road.name.clone();
    let display_name = route_name
        .clone()
        .unwrap_or_else(|| format!("OSM way {}", road.osm_way_id));

    let mut provenance = json!({
        "compile_method": "osm_pbf_plus_local_dem_profile_v2",
        // Preserve the actual compiler inputs for later boundary changes.
        // WKT coordinates and the published profile are rounded projections.
        "compiler_profile_points": selected,
        "road_class": format!("{:?}", road.road_class),
        "highway_tag": road.highway_tag,
        "profile_spacing": {
            "target_m": TARGET_PROFILE_SPACING_M,
            "avg_m": round2(spacing.avg_m),
            "max_m": round2(spacing.max_m)
        },
        "persistence_m": round2(persistence_m),
        "canonical_profile_hash": {
            "algorithm": "blake3_canonical_profile_v1",
            "value": canonical_profile_hash
        },
        "candidate_fingerprint": {
            "algorithm": "blake3_way_refs_geometry_sketch_v3",
            "geometry_samples": FINGERPRINT_GEOMETRY_SAMPLES,
            "coordinate_grid_degrees": 1.0 / FINGERPRINT_COORD_GRID_SCALE,
            "legacy_v2_value": legacy_candidate_fingerprint
        },
        "vertical_semantics": "net_rise_finish_minus_start_v1",
        "corridor": {
            "half_width_m": round2(config.gate_half_width_m),
            "h3_cover": "centerline_grid_disk_by_buffer_width_v1",
            "publish_geometry": "postgis_geography_buffer_v1",
            "compiler_preview_geometry": "conservative_envelope_v0"
        },
        "boundary_snap": {
            "start": start_snap.reason,
            "end": end_snap.reason,
            "snap_window_m": config.boundary_snap_m
        }
    });
    if let Some(object) = provenance.as_object_mut() {
        if let Some(way_chain) = candidate_provenance.way_chain {
            object.insert("way_chain".to_string(), way_chain);
        }
        if let Some(directional_extraction) = candidate_provenance.directional_extraction {
            object.insert("directional_extraction".to_string(), directional_extraction);
        }
        if let Some(ratified_boundary) = candidate_provenance.ratified_boundary {
            object.insert("ratified_boundary".to_string(), ratified_boundary);
        }
    }

    Some(CanonCandidate {
        candidate_fingerprint,
        legacy_candidate_fingerprints: vec![legacy_candidate_fingerprint],
        display_name,
        route_name,
        direction: "ascending".to_string(),
        centerline_polyline,
        centerline_wkt,
        corridor_wkt,
        corridor_half_width_m: round2(config.gate_half_width_m),
        gate_start_wkt,
        gate_end_wkt,
        canonical_profile,
        length_m: round2(length_m),
        vert_m: round2(vert_m),
        avg_gradient_pct: round3(avg_gradient_pct),
        max_gradient_pct: round3(max_gradient_pct),
        worthiness_score: round4(worthiness_score),
        confidence,
        dem_source: config.dem_source.clone(),
        compiler_version: config.compiler_version.clone(),
        osm_way_refs: osm_way_refs.to_vec(),
        odbl_source: "OpenStreetMap contributors".to_string(),
        odbl_extract_at: config.odbl_extract_at.clone(),
        provenance,
        low_confidence_flags,
        corridor_cells,
    })
}

fn directional_way_segments(
    profiled_roads: &[ProfiledRoad],
    config: &CanonCompileConfig,
) -> Vec<WayChainSegment> {
    let mut segments = Vec::new();
    for profiled in profiled_roads {
        let legacy_reversed = should_reverse_uphill(&profiled.profile.points);
        for span in directional_ascent_spans(
            &profiled.profile.points,
            &profiled.intersection_indices,
            config.boundary_snap_m,
        ) {
            segments.push(WayChainSegment {
                segment_id: segments.len(),
                road: profiled.road.clone(),
                points: span.points,
                intersection_indices: span.intersection_indices,
                route_key: normalized_route_key(&profiled.road.name),
                persistence_m: span.persistence_m,
                start_boundary_reason: span.start_boundary_reason,
                end_boundary_reason: span.end_boundary_reason,
                source_reversed: span.source_reversed,
                is_opposite_span: span.source_reversed != legacy_reversed,
            });
        }
    }
    segments
}

fn directional_ascent_spans(
    source_points: &[CanonProfilePoint],
    source_intersection_indices: &BTreeSet<usize>,
    boundary_snap_m: f64,
) -> Vec<DirectionalAscentSpan> {
    if source_points.len() < 2 {
        return Vec::new();
    }

    let mut spans = Vec::new();
    let mut seen_source_ranges = HashSet::new();
    for source_reversed in [false, true] {
        let mut oriented = source_points.to_vec();
        if source_reversed {
            oriented.reverse();
        }
        rebase_distances(&mut oriented);
        let oriented_intersections = reoriented_intersection_indices(
            source_points.len(),
            source_intersection_indices,
            source_reversed,
        );
        let Some((span_start, span_end, persistence_m)) = select_directional_ascent_span(&oriented)
        else {
            continue;
        };
        let start_snap = snap_start_boundary(
            &oriented,
            span_start,
            boundary_snap_m,
            &oriented_intersections,
        );
        let end_snap = snap_end_boundary(
            &oriented,
            span_end,
            boundary_snap_m,
            &oriented_intersections,
        );
        if end_snap.index <= start_snap.index {
            continue;
        }

        let mut selected = oriented[start_snap.index..=end_snap.index].to_vec();
        rebase_distances(&mut selected);
        if net_rise_m(&selected).map(|rise| rise > 0.0) != Some(true) {
            continue;
        }

        let source_start =
            source_index_for_orientation(start_snap.index, source_points.len(), source_reversed);
        let source_end =
            source_index_for_orientation(end_snap.index, source_points.len(), source_reversed);
        let source_range = (source_start.min(source_end), source_start.max(source_end));
        if !seen_source_ranges.insert(source_range) {
            continue;
        }

        let selected_intersections = oriented_intersections
            .range(start_snap.index..=end_snap.index)
            .map(|index| *index - start_snap.index)
            .collect();
        spans.push(DirectionalAscentSpan {
            points: selected,
            intersection_indices: selected_intersections,
            persistence_m,
            start_boundary_reason: start_snap.reason,
            end_boundary_reason: end_snap.reason,
            source_reversed,
        });
    }
    spans
}

fn source_index_for_orientation(index: usize, len: usize, reversed: bool) -> usize {
    if reversed {
        len.saturating_sub(1).saturating_sub(index)
    } else {
        index
    }
}

fn reoriented_intersection_indices(
    source_len: usize,
    intersection_indices: &BTreeSet<usize>,
    reversed: bool,
) -> BTreeSet<usize> {
    let last_index = source_len.saturating_sub(1);
    intersection_indices
        .iter()
        .filter_map(|index| {
            if *index > last_index {
                None
            } else if reversed {
                Some(last_index - *index)
            } else {
                Some(*index)
            }
        })
        .collect()
}

fn build_legacy_way_chains(profiled_roads: &[ProfiledRoad]) -> Vec<WayChain> {
    let segments = profiled_roads
        .iter()
        .enumerate()
        .filter_map(|(segment_id, profiled)| legacy_way_chain_segment(segment_id, profiled))
        .collect::<Vec<_>>();
    if segments.len() < 2 {
        return Vec::new();
    }

    let mut best_successor = HashMap::new();
    for from in 0..segments.len() {
        let best = (0..segments.len())
            .filter(|to| *to != from)
            .filter_map(|to| continuation_between(from, to, &segments[from], &segments[to]))
            .min_by(|a, b| {
                a.score
                    .partial_cmp(&b.score)
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
        if let Some(continuation) = best {
            best_successor.insert(from, continuation);
        }
    }

    let mut best_predecessor: HashMap<usize, ChainContinuation> = HashMap::new();
    for continuation in best_successor.values() {
        let replace = best_predecessor
            .get(&continuation.to)
            .map(|current| continuation.score < current.score)
            .unwrap_or(true);
        if replace {
            best_predecessor.insert(continuation.to, *continuation);
        }
    }

    let mut successor = HashMap::new();
    for (from, continuation) in &best_successor {
        let accepted = best_predecessor
            .get(&continuation.to)
            .map(|best| best.from == *from)
            .unwrap_or(false);
        if accepted {
            successor.insert(*from, continuation.to);
        }
    }

    let predecessors = successor.values().copied().collect::<HashSet<_>>();
    let mut chains = Vec::new();
    let mut covered = HashSet::new();

    for start in 0..segments.len() {
        if predecessors.contains(&start) || covered.contains(&start) {
            continue;
        }
        if let Some(chain) = collect_way_chain(start, &segments, &successor, &mut covered, false) {
            chains.push(chain);
        }
    }

    for start in 0..segments.len() {
        if covered.contains(&start) {
            continue;
        }
        if let Some(chain) = collect_way_chain(start, &segments, &successor, &mut covered, false) {
            chains.push(chain);
        }
    }

    chains
}

fn legacy_way_chain_segment(segment_id: usize, profiled: &ProfiledRoad) -> Option<WayChainSegment> {
    if profiled.profile.points.len() < 2 {
        return None;
    }
    let source_reversed = should_reverse_uphill(&profiled.profile.points);
    let points = orient_uphill(&profiled.profile.points);
    let intersection_indices =
        oriented_intersection_indices(&profiled.profile.points, &profiled.intersection_indices);

    Some(WayChainSegment {
        segment_id,
        road: profiled.road.clone(),
        points,
        intersection_indices,
        route_key: normalized_route_key(&profiled.road.name),
        persistence_m: 0.0,
        start_boundary_reason: "persistence_boundary",
        end_boundary_reason: "persistence_boundary",
        source_reversed,
        is_opposite_span: false,
    })
}

fn build_directional_way_chains(segments: &[WayChainSegment]) -> Vec<WayChain> {
    if segments.len() < 2 {
        return Vec::new();
    }

    let mut stable_indices = (0..segments.len()).collect::<Vec<_>>();
    stable_indices.sort_by_key(|index| directional_segment_key(&segments[*index]));

    let mut best_successors = Vec::new();
    for &from in &stable_indices {
        let best = (0..segments.len())
            .filter(|to| *to != from)
            .filter(|to| segments[from].road.osm_way_id != segments[*to].road.osm_way_id)
            .filter_map(|to| continuation_between(from, to, &segments[from], &segments[to]))
            .min_by(|a, b| directional_continuation_cmp(a, b, segments));
        if let Some(continuation) = best {
            best_successors.push(continuation);
        }
    }

    let mut best_predecessor: HashMap<usize, ChainContinuation> = HashMap::new();
    for continuation in &best_successors {
        let replace = best_predecessor
            .get(&continuation.to)
            .map(|current| {
                directional_continuation_cmp(continuation, current, segments)
                    == std::cmp::Ordering::Less
            })
            .unwrap_or(true);
        if replace {
            best_predecessor.insert(continuation.to, *continuation);
        }
    }

    let mut successor = HashMap::new();
    for continuation in &best_successors {
        let accepted = best_predecessor
            .get(&continuation.to)
            .map(|best| best.from == continuation.from)
            .unwrap_or(false);
        if accepted {
            successor.insert(continuation.from, continuation.to);
        }
    }

    let predecessors = successor.values().copied().collect::<HashSet<_>>();
    let mut chains = Vec::new();
    let mut covered = HashSet::new();

    for &start in &stable_indices {
        if predecessors.contains(&start) || covered.contains(&start) {
            continue;
        }
        if let Some(chain) = collect_way_chain(start, segments, &successor, &mut covered, true) {
            chains.push(chain);
        }
    }

    for &start in &stable_indices {
        if covered.contains(&start) {
            continue;
        }
        if let Some(chain) = collect_way_chain(start, segments, &successor, &mut covered, true) {
            chains.push(chain);
        }
    }

    chains
}

fn directional_continuation_cmp(
    left: &ChainContinuation,
    right: &ChainContinuation,
    segments: &[WayChainSegment],
) -> std::cmp::Ordering {
    left.score
        .partial_cmp(&right.score)
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| {
            directional_segment_key(&segments[left.from])
                .cmp(&directional_segment_key(&segments[right.from]))
        })
        .then_with(|| {
            directional_segment_key(&segments[left.to])
                .cmp(&directional_segment_key(&segments[right.to]))
        })
}

fn directional_segment_key(
    segment: &WayChainSegment,
) -> (i64, bool, i64, i64, i64, i64, i64, i64, usize) {
    let start = segment.points.first();
    let end = segment.points.last();
    (
        segment.road.osm_way_id,
        segment.source_reversed,
        quantized_directional_value(start.map(|point| point.lat).unwrap_or(0.0), 10_000_000.0),
        quantized_directional_value(start.map(|point| point.lon).unwrap_or(0.0), 10_000_000.0),
        quantized_directional_value(start.map(|point| point.elev_m).unwrap_or(0.0), 1_000.0),
        quantized_directional_value(end.map(|point| point.lat).unwrap_or(0.0), 10_000_000.0),
        quantized_directional_value(end.map(|point| point.lon).unwrap_or(0.0), 10_000_000.0),
        quantized_directional_value(end.map(|point| point.elev_m).unwrap_or(0.0), 1_000.0),
        segment.points.len(),
    )
}

fn quantized_directional_value(value: f64, scale: f64) -> i64 {
    if value.is_finite() {
        (value * scale).round() as i64
    } else {
        0
    }
}

fn continuation_between(
    from: usize,
    to: usize,
    current: &WayChainSegment,
    next: &WayChainSegment,
) -> Option<ChainContinuation> {
    let current_end = current.points.last()?;
    let next_start = next.points.first()?;
    let next_end = next.points.last()?;
    let endpoint_gap_m = haversine_m(
        current_end.lat,
        current_end.lon,
        next_start.lat,
        next_start.lon,
    );
    if endpoint_gap_m > CHAIN_ENDPOINT_TOLERANCE_M {
        return None;
    }

    let elevation_seam_m = next_start.elev_m - current_end.elev_m;
    if elevation_seam_m.abs() > CHAIN_MAX_ELEVATION_SEAM_M {
        return None;
    }
    if next_end.elev_m <= next_start.elev_m {
        return None;
    }

    let turn_angle_deg = angular_diff(segment_end_bearing(current)?, segment_start_bearing(next)?);
    let same_route = current.route_key.is_some() && current.route_key == next.route_key;
    let turn_limit = if same_route {
        CHAIN_SAME_NAME_MAX_TURN_DEG
    } else {
        CHAIN_CONTINUATION_MAX_TURN_DEG
    };
    if turn_angle_deg > turn_limit {
        return None;
    }

    let name_bonus = if same_route { 30.0 } else { 0.0 };
    let score =
        endpoint_gap_m + (turn_angle_deg * 2.0) + (elevation_seam_m.abs() * 5.0) - name_bonus;

    Some(ChainContinuation { from, to, score })
}

fn collect_way_chain(
    start: usize,
    segments: &[WayChainSegment],
    successor: &HashMap<usize, usize>,
    covered: &mut HashSet<usize>,
    directional_extraction: bool,
) -> Option<WayChain> {
    let mut indices = Vec::new();
    let mut seen = HashSet::new();
    let mut cursor = start;

    loop {
        if seen.contains(&cursor)
            || covered.contains(&cursor)
            || indices.len() >= CHAIN_MAX_SEGMENTS
        {
            break;
        }
        seen.insert(cursor);
        indices.push(cursor);

        let Some(next) = successor.get(&cursor).copied() else {
            break;
        };
        cursor = next;
    }

    if indices.len() < 2 {
        return None;
    }
    for index in &indices {
        covered.insert(*index);
    }

    Some(WayChain {
        segments: indices
            .into_iter()
            .map(|index| segments[index].clone())
            .collect(),
        directional_extraction,
    })
}

fn compile_way_chain(chain: &WayChain, config: &CanonCompileConfig) -> Option<CanonCandidate> {
    let chain_profile = chain_profile_points(&chain.segments);
    if chain_profile.points.len() < 2 {
        return None;
    }

    let road = chain_road_feature(&chain.segments, &chain_profile.points);
    let profile = LocalElevationProfile {
        osm_way_id: road.osm_way_id,
        points: chain_profile.points.clone(),
    };
    let osm_way_refs = chain
        .segments
        .iter()
        .map(|segment| segment.road.osm_way_id)
        .collect::<Vec<_>>();
    let way_chain = way_chain_provenance(chain);
    if !chain.directional_extraction {
        return compile_candidate(
            &road,
            &profile,
            config,
            &osm_way_refs,
            &chain_profile.intersection_indices,
            &[],
            CandidateProvenance {
                way_chain: Some(way_chain),
                ..CandidateProvenance::default()
            },
        );
    }

    let persistence_m = select_directional_ascent_span(&chain_profile.points)
        .map(|(_, _, persistence_m)| persistence_m)
        .or_else(|| net_rise_m(&chain_profile.points))?;
    let start_reason = chain.segments.first()?.start_boundary_reason;
    let end_reason = chain.segments.last()?.end_boundary_reason;
    compile_selected_candidate(
        &road,
        chain_profile.points,
        config,
        &osm_way_refs,
        &[],
        CandidateProvenance {
            way_chain: Some(way_chain),
            directional_extraction: Some(json!({
                "algorithm": "bidirectional_maximal_ascent_v1",
                "chain_stage": "pre_chain",
                "opposite_to_v020_primary_orientation": true,
                "opposite_way_refs": chain
                    .segments
                    .iter()
                    .filter(|segment| segment.is_opposite_span)
                    .map(|segment| segment.road.osm_way_id)
                    .collect::<Vec<_>>()
            })),
            ..CandidateProvenance::default()
        },
        persistence_m,
        BoundarySnap {
            index: 0,
            reason: start_reason,
        },
        BoundarySnap {
            index: profile.points.len().saturating_sub(1),
            reason: end_reason,
        },
    )
}

fn chain_profile_points(segments: &[WayChainSegment]) -> ChainProfile {
    let mut points: Vec<CanonProfilePoint> = Vec::new();
    let mut intersection_indices = BTreeSet::new();
    for segment in segments {
        for (index, point) in segment.points.iter().enumerate() {
            let mut target_index = points.len();
            if index == 0 {
                if let Some(previous) = points.last() {
                    let gap_m = haversine_m(previous.lat, previous.lon, point.lat, point.lon);
                    if gap_m <= 1.0 {
                        if !points.is_empty() {
                            target_index = points.len() - 1;
                        }
                        if segment.intersection_indices.contains(&index) {
                            intersection_indices.insert(target_index);
                        }
                        continue;
                    }
                }
            }
            if segment.intersection_indices.contains(&index) {
                intersection_indices.insert(target_index);
            }
            points.push(point.clone());
        }
    }
    rebase_distances(&mut points);
    ChainProfile {
        points,
        intersection_indices,
    }
}

fn chain_road_feature(segments: &[WayChainSegment], points: &[CanonProfilePoint]) -> RoadFeature {
    let first = &segments[0].road;
    let mut road = RoadFeature::new(first.osm_way_id, first.road_class);
    road.highway_tag = first.highway_tag.clone();
    road.name = chain_route_name(segments);
    road.length_m = points.last().map(|point| point.dist_m).unwrap_or(0.0) as f32;
    road.geometry = points.iter().map(|point| (point.lon, point.lat)).collect();
    road.h3_cells = segments
        .iter()
        .flat_map(|segment| segment.road.h3_cells.iter().cloned())
        .collect();
    road.has_bike_infra = segments.iter().any(|segment| segment.road.has_bike_infra);
    road.surface = segments
        .iter()
        .find_map(|segment| segment.road.surface.clone());
    road
}

fn chain_route_name(segments: &[WayChainSegment]) -> Option<String> {
    let names = unique_route_names(segments);
    if names.is_empty() {
        None
    } else {
        Some(names.join(" / "))
    }
}

fn way_chain_provenance(chain: &WayChain) -> Value {
    let edges = chain
        .segments
        .windows(2)
        .filter_map(|window| {
            let current = &window[0];
            let next = &window[1];
            let current_end = current.points.last()?;
            let next_start = next.points.first()?;
            Some(json!({
                "from_way": current.road.osm_way_id,
                "to_way": next.road.osm_way_id,
                "endpoint_gap_m": round2(haversine_m(
                    current_end.lat,
                    current_end.lon,
                    next_start.lat,
                    next_start.lon,
                )),
                "turn_angle_deg": round2(angular_diff(
                    segment_end_bearing(current)?,
                    segment_start_bearing(next)?,
                )),
                "elevation_seam_m": round2(next_start.elev_m - current_end.elev_m)
            }))
        })
        .collect::<Vec<_>>();

    json!({
        "algorithm": "shared_endpoint_turn_gated_v2",
        "osm_way_refs": chain
            .segments
            .iter()
            .map(|segment| segment.road.osm_way_id)
            .collect::<Vec<_>>(),
        "road_names": unique_route_names(&chain.segments),
        "endpoint_tolerance_m": CHAIN_ENDPOINT_TOLERANCE_M,
        "max_abs_elevation_seam_m": CHAIN_MAX_ELEVATION_SEAM_M,
        "max_turn_deg": {
            "same_name": CHAIN_SAME_NAME_MAX_TURN_DEG,
            "continuation": CHAIN_CONTINUATION_MAX_TURN_DEG
        },
        "edges": edges
    })
}

fn unique_route_names(segments: &[WayChainSegment]) -> Vec<String> {
    let mut names = Vec::new();
    let mut seen = HashSet::new();
    for segment in segments {
        let Some(name) = segment.road.name.as_ref() else {
            continue;
        };
        let key = name.trim().to_ascii_lowercase();
        if key.is_empty() || !seen.insert(key) {
            continue;
        }
        names.push(name.clone());
    }
    names
}

fn normalized_route_key(name: &Option<String>) -> Option<String> {
    name.as_ref()
        .map(|value| value.trim().to_ascii_lowercase())
        .filter(|value| !value.is_empty())
}

fn segment_start_bearing(segment: &WayChainSegment) -> Option<f64> {
    let first = segment.points.first()?;
    let second = segment.points.get(1)?;
    Some(bearing_degrees(
        first.lat, first.lon, second.lat, second.lon,
    ))
}

fn segment_end_bearing(segment: &WayChainSegment) -> Option<f64> {
    if segment.points.len() < 2 {
        return None;
    }
    let last_index = segment.points.len() - 1;
    let previous = segment.points.get(last_index - 1)?;
    let last = segment.points.get(last_index)?;
    Some(bearing_degrees(
        previous.lat,
        previous.lon,
        last.lat,
        last.lon,
    ))
}

fn angular_diff(a: f64, b: f64) -> f64 {
    let diff = (a - b).abs() % 360.0;
    if diff > 180.0 {
        360.0 - diff
    } else {
        diff
    }
}

fn orient_uphill(points: &[CanonProfilePoint]) -> Vec<CanonProfilePoint> {
    let mut oriented = points.to_vec();
    if let (Some(first), Some(last)) = (oriented.first(), oriented.last()) {
        if last.elev_m < first.elev_m {
            oriented.reverse();
        }
    }
    rebase_distances(&mut oriented);
    oriented
}

fn select_ascent_span(points: &[CanonProfilePoint]) -> Option<(usize, usize, f64)> {
    let elevations = points.iter().map(|point| point.elev_m).collect::<Vec<_>>();
    let smoothed = smooth_elevations(&elevations, 3);

    let best_pair = compute_persistence(&smoothed, NOISE_GATE_M)
        .into_iter()
        .filter(|pair| pair.death_idx > pair.birth_idx)
        .max_by(|a, b| {
            a.persistence
                .partial_cmp(&b.persistence)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

    if let Some(pair) = best_pair {
        return Some((pair.birth_idx, pair.death_idx, pair.persistence));
    }

    let (min_idx, max_idx) = find_essential(&smoothed)?;
    if max_idx > min_idx {
        let persistence = smoothed[max_idx] - smoothed[min_idx];
        return Some((min_idx, max_idx, persistence));
    }

    None
}

fn oriented_intersection_indices(
    source_points: &[CanonProfilePoint],
    intersection_indices: &BTreeSet<usize>,
) -> BTreeSet<usize> {
    if source_points.len() < 2 {
        return BTreeSet::new();
    }
    let reversed = source_points
        .last()
        .zip(source_points.first())
        .map(|(last, first)| last.elev_m < first.elev_m)
        .unwrap_or(false);
    let last_index = source_points.len() - 1;
    intersection_indices
        .iter()
        .filter_map(|index| {
            if *index > last_index {
                None
            } else if reversed {
                Some(last_index - *index)
            } else {
                Some(*index)
            }
        })
        .collect()
}

fn should_reverse_uphill(points: &[CanonProfilePoint]) -> bool {
    points
        .last()
        .zip(points.first())
        .map(|(last, first)| last.elev_m < first.elev_m)
        .unwrap_or(false)
}

fn select_directional_ascent_span(points: &[CanonProfilePoint]) -> Option<(usize, usize, f64)> {
    let elevations = points.iter().map(|point| point.elev_m).collect::<Vec<_>>();
    let smoothed = smooth_elevations(&elevations, 3);

    let best_pair = compute_persistence(&smoothed, NOISE_GATE_M)
        .into_iter()
        .filter(|pair| pair.death_idx > pair.birth_idx)
        .max_by(|a, b| {
            a.persistence
                .partial_cmp(&b.persistence)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| (a.death_idx - a.birth_idx).cmp(&(b.death_idx - b.birth_idx)))
                .then_with(|| b.birth_idx.cmp(&a.birth_idx))
        });

    if let Some(pair) = best_pair {
        return Some((pair.birth_idx, pair.death_idx, pair.persistence));
    }

    let (min_idx, max_idx) = find_essential(&smoothed)?;
    if max_idx > min_idx {
        let persistence = smoothed[max_idx] - smoothed[min_idx];
        return Some((min_idx, max_idx, persistence));
    }

    None
}

fn snap_start_boundary(
    points: &[CanonProfilePoint],
    index: usize,
    snap_m: f64,
    intersection_indices: &BTreeSet<usize>,
) -> BoundarySnap {
    if let Some(intersection) =
        nearest_outward_intersection(points, index, snap_m, intersection_indices, true)
    {
        return BoundarySnap {
            index: intersection,
            reason: "shared_road_geometry",
        };
    }

    if points.get(index).map(|p| p.dist_m).unwrap_or(0.0) <= snap_m
        && extension_grade_floor_met(points, 0, index)
    {
        return BoundarySnap {
            index: 0,
            reason: "route_endpoint",
        };
    }

    if let Some(inflection) = nearest_inflection(points, index, snap_m, true) {
        return BoundarySnap {
            index: inflection,
            reason: "gradient_inflection",
        };
    }

    BoundarySnap {
        index,
        reason: "persistence_boundary",
    }
}

fn snap_end_boundary(
    points: &[CanonProfilePoint],
    index: usize,
    snap_m: f64,
    intersection_indices: &BTreeSet<usize>,
) -> BoundarySnap {
    let last_idx = points.len().saturating_sub(1);
    let end_dist = points.last().map(|p| p.dist_m).unwrap_or(0.0);
    let point_dist = points.get(index).map(|p| p.dist_m).unwrap_or(end_dist);
    if let Some(intersection) =
        nearest_outward_intersection(points, index, snap_m, intersection_indices, false)
    {
        return BoundarySnap {
            index: intersection,
            reason: "shared_road_geometry",
        };
    }

    if end_dist - point_dist <= snap_m && extension_grade_floor_met(points, index, last_idx) {
        return BoundarySnap {
            index: last_idx,
            reason: "route_endpoint",
        };
    }

    if let Some(inflection) = nearest_inflection(points, index, snap_m, false) {
        return BoundarySnap {
            index: inflection,
            reason: "gradient_inflection",
        };
    }

    BoundarySnap {
        index,
        reason: "persistence_boundary",
    }
}

fn nearest_outward_intersection(
    points: &[CanonProfilePoint],
    index: usize,
    snap_m: f64,
    intersection_indices: &BTreeSet<usize>,
    start_boundary: bool,
) -> Option<usize> {
    let anchor_dist = points.get(index)?.dist_m;
    let mut best: Option<(usize, f64)> = None;
    for candidate in intersection_indices {
        if *candidate >= points.len() {
            continue;
        }
        if start_boundary && *candidate > index {
            continue;
        }
        if !start_boundary && *candidate < index {
            continue;
        }
        let candidate_dist = points[*candidate].dist_m;
        let distance_from_anchor = (candidate_dist - anchor_dist).abs();
        if distance_from_anchor > snap_m {
            continue;
        }
        let grade_ok = if start_boundary {
            extension_grade_floor_met(points, *candidate, index)
        } else {
            extension_grade_floor_met(points, index, *candidate)
        };
        if !grade_ok {
            continue;
        }
        if best
            .map(|(_, best_distance)| distance_from_anchor < best_distance)
            .unwrap_or(true)
        {
            best = Some((*candidate, distance_from_anchor));
        }
    }
    best.map(|(candidate, _)| candidate)
}

fn extension_grade_floor_met(
    points: &[CanonProfilePoint],
    lower_index: usize,
    upper_index: usize,
) -> bool {
    if lower_index == upper_index {
        return true;
    }
    let Some(lower) = points.get(lower_index) else {
        return false;
    };
    let Some(upper) = points.get(upper_index) else {
        return false;
    };
    let distance_m = (upper.dist_m - lower.dist_m).abs();
    if distance_m <= 1.0 {
        return true;
    }
    ((upper.elev_m - lower.elev_m) / distance_m * 100.0) >= BOUNDARY_EXTENSION_MIN_GRADE_PCT
}

fn nearest_inflection(
    points: &[CanonProfilePoint],
    index: usize,
    snap_m: f64,
    start_boundary: bool,
) -> Option<usize> {
    let anchor_dist = points.get(index)?.dist_m;
    let min_dist = (anchor_dist - snap_m).max(0.0);
    let max_dist = anchor_dist + snap_m;

    let mut best: Option<(usize, f64)> = None;
    for i in 1..points.len().saturating_sub(1) {
        let dist = points[i].dist_m;
        if dist < min_dist || dist > max_dist {
            continue;
        }
        let prev_grade = segment_gradient_pct(&points[i - 1], &points[i]);
        let next_grade = segment_gradient_pct(&points[i], &points[i + 1]);
        let is_inflection = if start_boundary {
            prev_grade <= 1.5 && next_grade >= 2.0
        } else {
            prev_grade >= 2.0 && next_grade <= 1.5
        };
        if !is_inflection {
            continue;
        }
        let distance_from_anchor = (dist - anchor_dist).abs();
        if best
            .map(|(_, best_distance)| distance_from_anchor < best_distance)
            .unwrap_or(true)
        {
            best = Some((i, distance_from_anchor));
        }
    }
    best.map(|(i, _)| i)
}

fn segment_worthiness_score(
    road: &RoadFeature,
    points: &[CanonProfilePoint],
    vert_m: f64,
    avg_gradient_pct: f64,
    max_gradient_pct: f64,
    start_snap: &BoundarySnap,
    end_snap: &BoundarySnap,
) -> f64 {
    let length_m = points.last().map(|point| point.dist_m).unwrap_or(0.0);
    let mut score =
        calibrated_metric_worthiness_score(length_m, vert_m, avg_gradient_pct, max_gradient_pct);

    let onset = onset_steepness_pct_per_100m(points);
    score += if onset >= 3.0 {
        4.0
    } else if onset >= 2.0 {
        3.0
    } else if onset >= 1.0 {
        1.5
    } else if onset >= 0.5 {
        0.75
    } else {
        0.0
    };

    if avg_gradient_pct >= 4.0 && vert_m >= 20.0 && gradient_stddev(points) <= 3.0 {
        score += 2.0;
    }

    if road.name.is_some() {
        score += 2.0;
    }
    if !matches!(road.road_class, RoadClass::Path | RoadClass::Track) {
        score += 1.0;
    }
    if matches!(
        road.road_class,
        RoadClass::Primary | RoadClass::Secondary | RoadClass::Tertiary | RoadClass::Residential
    ) {
        score += 1.5;
    }
    if matches!(
        (start_snap.reason, end_snap.reason),
        ("route_endpoint", "route_endpoint")
            | ("gradient_inflection", "gradient_inflection")
            | ("shared_road_geometry", "shared_road_geometry")
    ) {
        score += 3.0;
    }

    score.clamp(0.0, 100.0)
}

fn calibrated_metric_worthiness_score(
    length_m: f64,
    vert_m: f64,
    avg_gradient_pct: f64,
    max_gradient_pct: f64,
) -> f64 {
    let intensity = (length_m / 1000.0) * avg_gradient_pct.powi(2);
    let max_grade_punch = (max_gradient_pct - 12.0).max(0.0);
    let long_grinder_bonus = ((length_m - 500.0) / 100.0).max(0.0).min(12.0);

    (8.0 + (0.50 * vert_m)
        + (0.20 * intensity)
        + (0.50 * max_grade_punch)
        + (2.0 * long_grinder_bonus))
        .clamp(0.0, 100.0)
}

fn confidence_tier(score: f64, flags: &[String]) -> String {
    let material_flags = flags
        .iter()
        .filter(|flag| !is_informational_confidence_flag(flag))
        .count();
    if score >= 75.0 && material_flags == 0 {
        "high".to_string()
    } else if score >= 55.0 && material_flags == 0 {
        "medium".to_string()
    } else if score >= 35.0 && material_flags <= 1 {
        "needs_review".to_string()
    } else {
        "low".to_string()
    }
}

fn is_informational_confidence_flag(flag: &str) -> bool {
    matches!(flag, "topographic_isolation_not_scored_v0")
}

fn onset_steepness_pct_per_100m(points: &[CanonProfilePoint]) -> f64 {
    if points.len() < 2 {
        return 0.0;
    }
    let start = &points[0];
    let end = points
        .iter()
        .find(|point| point.dist_m >= 100.0)
        .unwrap_or_else(|| points.last().unwrap());
    let dist = (end.dist_m - start.dist_m).max(1.0);
    let grade = (end.elev_m - start.elev_m) / dist * 100.0;
    grade.max(0.0)
}

fn gradient_stddev(points: &[CanonProfilePoint]) -> f64 {
    let gradients = segment_gradients(points);
    if gradients.is_empty() {
        return 0.0;
    }
    let mean = gradients.iter().sum::<f64>() / gradients.len() as f64;
    let variance = gradients
        .iter()
        .map(|grade| (grade - mean).powi(2))
        .sum::<f64>()
        / gradients.len() as f64;
    variance.sqrt()
}

fn max_gradient_pct(points: &[CanonProfilePoint]) -> f64 {
    segment_gradients(points)
        .into_iter()
        .fold(0.0_f64, |max_grade, grade| max_grade.max(grade))
}

fn segment_gradients(points: &[CanonProfilePoint]) -> Vec<f64> {
    points
        .windows(2)
        .map(|window| segment_gradient_pct(&window[0], &window[1]))
        .filter(|grade| grade.is_finite())
        .collect()
}

fn segment_gradient_pct(start: &CanonProfilePoint, end: &CanonProfilePoint) -> f64 {
    let distance = (end.dist_m - start.dist_m).abs();
    if distance < MIN_GRADIENT_SEGMENT_DISTANCE_M {
        return f64::NAN;
    }
    (end.elev_m - start.elev_m) / distance * 100.0
}

fn net_rise_m(points: &[CanonProfilePoint]) -> Option<f64> {
    Some(points.last()?.elev_m - points.first()?.elev_m)
}

#[derive(Debug, Clone, Copy)]
struct SpacingStats {
    avg_m: f64,
    max_m: f64,
}

fn profile_spacing_stats(points: &[CanonProfilePoint]) -> SpacingStats {
    if points.len() < 2 {
        return SpacingStats {
            avg_m: 0.0,
            max_m: 0.0,
        };
    }

    let mut total = 0.0;
    let mut max_m = 0.0;
    for window in points.windows(2) {
        let gap = (window[1].dist_m - window[0].dist_m).abs();
        total += gap;
        if gap > max_m {
            max_m = gap;
        }
    }

    SpacingStats {
        avg_m: total / (points.len() - 1) as f64,
        max_m,
    }
}

fn rebase_distances(points: &mut [CanonProfilePoint]) {
    if points.is_empty() {
        return;
    }

    points[0].dist_m = 0.0;
    for i in 1..points.len() {
        let previous = &points[i - 1];
        let step = haversine_m(previous.lat, previous.lon, points[i].lat, points[i].lon);
        points[i].dist_m = points[i - 1].dist_m + step;
    }
}

fn line_string_wkt(points: &[CanonProfilePoint]) -> String {
    let coords = points
        .iter()
        .map(|point| format_coord(point.lon, point.lat))
        .collect::<Vec<_>>()
        .join(", ");
    format!("LINESTRING({})", coords)
}

fn corridor_envelope_wkt(points: &[CanonProfilePoint], half_width_m: f64) -> String {
    let min_lat = points.iter().map(|p| p.lat).fold(f64::INFINITY, f64::min);
    let max_lat = points
        .iter()
        .map(|p| p.lat)
        .fold(f64::NEG_INFINITY, f64::max);
    let min_lon = points.iter().map(|p| p.lon).fold(f64::INFINITY, f64::min);
    let max_lon = points
        .iter()
        .map(|p| p.lon)
        .fold(f64::NEG_INFINITY, f64::max);
    let center_lat = (min_lat + max_lat) / 2.0;
    let lat_pad = meters_to_lat_degrees(half_width_m);
    let lon_pad = meters_to_lon_degrees(half_width_m, center_lat);
    let left = min_lon - lon_pad;
    let right = max_lon + lon_pad;
    let bottom = min_lat - lat_pad;
    let top = max_lat + lat_pad;

    format!(
        "MULTIPOLYGON((({left} {bottom}, {right} {bottom}, {right} {top}, {left} {top}, {left} {bottom})))",
        left = round_coord(left),
        right = round_coord(right),
        bottom = round_coord(bottom),
        top = round_coord(top)
    )
}

/// Sub-meter boundary vertex spacing must never set a gate's direction
/// baseline: normalizing by a clamped norm used to scale the arm by the
/// spacing itself, silently emitting gates narrower than the configured
/// half-width (and point gates for duplicate vertices).
const MIN_GATE_DIRECTION_BASELINE_M: f64 = 1.0;

fn gate_wkt(points: &[CanonProfilePoint], index: usize, half_width_m: f64) -> String {
    let point = &points[index];

    let lat_scale = 111_320.0;
    let lon_scale = 111_320.0 * point.lat.to_radians().cos().abs().max(0.1);
    let metric_delta = |other: &CanonProfilePoint| {
        let dx = (other.lon - point.lon) * lon_scale;
        let dy = (other.lat - point.lat) * lat_scale;
        let norm = (dx * dx + dy * dy).sqrt();
        (dx, dy, norm)
    };

    // Preserve the historical adjacent-neighbor direction whenever its
    // baseline is at least one meter. Otherwise walk inward until direction
    // is stable; a nonzero shorter vector remains the last-resort fallback.
    let mut chosen = None;
    let mut fallback = None;
    let walk: Box<dyn Iterator<Item = &CanonProfilePoint>> = if index == 0 {
        Box::new(points.iter().skip(1))
    } else {
        Box::new(points[..index].iter().rev())
    };
    for other in walk {
        let (dx, dy, norm) = metric_delta(other);
        if norm > 0.0 && fallback.is_none() {
            fallback = Some((dx, dy, norm));
        }
        if norm >= MIN_GATE_DIRECTION_BASELINE_M {
            chosen = Some((dx, dy, norm));
            break;
        }
    }
    let (px, py) = match chosen.or(fallback) {
        Some((dx, dy, norm)) => (-dy / norm, dx / norm),
        // A fully degenerate span has no defensible direction. Such a span
        // cannot become a climb candidate; retain the historical point gate.
        None => (0.0, 0.0),
    };

    let a_lon = point.lon + (px * half_width_m) / lon_scale;
    let a_lat = point.lat + (py * half_width_m) / lat_scale;
    let b_lon = point.lon - (px * half_width_m) / lon_scale;
    let b_lat = point.lat - (py * half_width_m) / lat_scale;

    format!(
        "LINESTRING({}, {})",
        format_coord(a_lon, a_lat),
        format_coord(b_lon, b_lat)
    )
}

fn corridor_cells(points: &[CanonProfilePoint], half_width_m: f64) -> Vec<CorridorCell> {
    let mut cells = BTreeSet::new();
    let ring_k = corridor_grid_disk_radius(half_width_m);
    for latlng in sampled_centerline_latlngs(points) {
        for cell in latlng.to_cell(Resolution::Ten).grid_disk::<Vec<_>>(ring_k) {
            cells.insert(("corridor".to_string(), cell.to_string()));
        }
    }

    if let Some(first) = points.first() {
        if let Ok(latlng) = LatLng::new(first.lat, first.lon) {
            for cell in latlng.to_cell(Resolution::Ten).grid_disk::<Vec<_>>(ring_k) {
                cells.insert(("gate_start".to_string(), cell.to_string()));
            }
        }
    }
    if let Some(last) = points.last() {
        if let Ok(latlng) = LatLng::new(last.lat, last.lon) {
            for cell in latlng.to_cell(Resolution::Ten).grid_disk::<Vec<_>>(ring_k) {
                cells.insert(("gate_end".to_string(), cell.to_string()));
            }
        }
    }

    cells
        .into_iter()
        .map(|(coverage_role, tile_id)| CorridorCell {
            h3_resolution: CANON_H3_RESOLUTION,
            tile_id,
            coverage_role,
        })
        .collect()
}

fn corridor_grid_disk_radius(half_width_m: f64) -> u32 {
    if !half_width_m.is_finite() || half_width_m <= 0.0 {
        return 0;
    }
    (half_width_m / Resolution::Ten.edge_length_m())
        .ceil()
        .max(1.0) as u32
}

fn sampled_centerline_latlngs(points: &[CanonProfilePoint]) -> Vec<LatLng> {
    let mut samples = Vec::new();
    for window in points.windows(2) {
        let start = &window[0];
        let end = &window[1];
        let distance_m = haversine_m(start.lat, start.lon, end.lat, end.lon);
        let steps = (distance_m / TARGET_PROFILE_SPACING_M).ceil().max(1.0) as usize;
        for step in 0..steps {
            let ratio = step as f64 / steps as f64;
            if let Ok(latlng) = LatLng::new(
                start.lat + ((end.lat - start.lat) * ratio),
                start.lon + ((end.lon - start.lon) * ratio),
            ) {
                samples.push(latlng);
            }
        }
    }
    if let Some(last) = points.last() {
        if let Ok(latlng) = LatLng::new(last.lat, last.lon) {
            samples.push(latlng);
        }
    }
    samples
}

fn candidate_fingerprint(osm_way_refs: &[i64], points: &[CanonProfilePoint]) -> String {
    let mut hasher = Hasher::new();
    hasher.update(b"boulderroller-canon-candidate-v3-geometry-sketch");
    hasher.update(&(osm_way_refs.len() as u32).to_be_bytes());
    for way_ref in osm_way_refs {
        hasher.update(&way_ref.to_be_bytes());
    }
    for (lat, lon) in geometry_fingerprint_samples(points) {
        hasher.update(&lat.to_be_bytes());
        hasher.update(&lon.to_be_bytes());
    }
    hasher.finalize().to_hex().to_string()
}

fn legacy_candidate_fingerprint_v2(osm_way_refs: &[i64], points: &[CanonProfilePoint]) -> String {
    let mut hasher = Hasher::new();
    hasher.update(b"boulderroller-canon-candidate-v2-stable-geometry");
    for way_ref in osm_way_refs {
        hasher.update(&way_ref.to_be_bytes());
        hasher.update(b";");
    }
    if let Some(first) = points.first() {
        hasher.update(format!("{:.7},{:.7}", first.lat, first.lon).as_bytes());
    }
    if let Some(last) = points.last() {
        hasher.update(format!("{:.7},{:.7}", last.lat, last.lon).as_bytes());
    }
    hasher.finalize().to_hex().to_string()
}

fn geometry_fingerprint_samples(points: &[CanonProfilePoint]) -> Vec<(i64, i64)> {
    let Some(first) = points.first() else {
        return Vec::new();
    };
    if points.len() == 1 {
        return vec![quantized_fingerprint_coord(first.lat, first.lon)];
    }

    let mut cumulative_m = Vec::with_capacity(points.len());
    cumulative_m.push(0.0);
    for window in points.windows(2) {
        let distance = haversine_m(window[0].lat, window[0].lon, window[1].lat, window[1].lon);
        cumulative_m.push(cumulative_m.last().copied().unwrap_or(0.0) + distance);
    }
    let total_m = cumulative_m.last().copied().unwrap_or(0.0);
    if total_m <= f64::EPSILON {
        return vec![quantized_fingerprint_coord(first.lat, first.lon)];
    }

    (0..FINGERPRINT_GEOMETRY_SAMPLES)
        .map(|sample_index| {
            let target_m =
                total_m * sample_index as f64 / (FINGERPRINT_GEOMETRY_SAMPLES - 1) as f64;
            let segment_index = cumulative_m
                .partition_point(|distance| *distance < target_m)
                .saturating_sub(1)
                .min(points.len() - 2);
            let segment_start_m = cumulative_m[segment_index];
            let segment_end_m = cumulative_m[segment_index + 1];
            let segment_m = segment_end_m - segment_start_m;
            let ratio = if segment_m <= f64::EPSILON {
                0.0
            } else {
                ((target_m - segment_start_m) / segment_m).clamp(0.0, 1.0)
            };
            let start = &points[segment_index];
            let end = &points[segment_index + 1];
            quantized_fingerprint_coord(
                start.lat + ((end.lat - start.lat) * ratio),
                start.lon + ((end.lon - start.lon) * ratio),
            )
        })
        .collect()
}

fn quantized_fingerprint_coord(lat: f64, lon: f64) -> (i64, i64) {
    (
        (lat * FINGERPRINT_COORD_GRID_SCALE).round() as i64,
        (lon * FINGERPRINT_COORD_GRID_SCALE).round() as i64,
    )
}

fn canonical_profile_hash(profile: &[CanonProfileSample]) -> String {
    let mut hasher = Hasher::new();
    hasher.update(b"boulderroller-canon-profile-v1");
    for sample in profile {
        hasher.update(format!("{:.2}:{:.2};", sample.dist_m, sample.elev_m).as_bytes());
    }
    hasher.finalize().to_hex().to_string()
}

pub fn candidate_insert_sql(candidate: &CanonCandidate) -> String {
    let profile_json = serde_json::to_string(&candidate.canonical_profile).unwrap_or_default();
    let provenance_json = serde_json::to_string(&candidate.provenance).unwrap_or_default();
    let way_refs = candidate
        .osm_way_refs
        .iter()
        .map(i64::to_string)
        .collect::<Vec<_>>()
        .join(", ");
    let flags = candidate
        .low_confidence_flags
        .iter()
        .map(|flag| sql_literal(flag))
        .collect::<Vec<_>>()
        .join(", ");
    let cell_values = candidate
        .corridor_cells
        .iter()
        .map(|cell| {
            format!(
                "({}, {}, {})",
                sql_literal(&cell.tile_id),
                cell.h3_resolution,
                sql_literal(&cell.coverage_role)
            )
        })
        .collect::<Vec<_>>()
        .join(", ");

    format!(
        "WITH upserted AS (INSERT INTO public.canon_climbs (candidate_fingerprint, display_name, route_name, direction, centerline_polyline, centerline_geom, corridor_geom, gate_start_line, gate_end_line, canonical_profile, length_m, vert_m, avg_gradient_pct, max_gradient_pct, worthiness_score, confidence, dem_source, compiler_version, osm_way_refs, odbl_source, odbl_extract_at, provenance, low_confidence_flags) VALUES ({fingerprint}, {display_name}, {route_name}, 'ascending', {polyline}, ST_GeomFromText({centerline}, 4326), ST_Multi(ST_Buffer(ST_GeomFromText({centerline}, 4326)::geography, {corridor_half_width_m:.2})::geometry), ST_GeomFromText({gate_start}, 4326), ST_GeomFromText({gate_end}, 4326), {profile}::jsonb, {length:.2}, {vert:.2}, {avg:.3}, {max:.3}, {worthiness:.4}, {confidence}, {dem_source}, {compiler_version}, ARRAY[{way_refs}]::bigint[], 'OpenStreetMap contributors', {odbl_extract_at}, {provenance}::jsonb, ARRAY[{flags}]::text[]) ON CONFLICT (candidate_fingerprint) DO UPDATE SET display_name = EXCLUDED.display_name, route_name = EXCLUDED.route_name, centerline_polyline = EXCLUDED.centerline_polyline, centerline_geom = EXCLUDED.centerline_geom, corridor_geom = EXCLUDED.corridor_geom, gate_start_line = EXCLUDED.gate_start_line, gate_end_line = EXCLUDED.gate_end_line, canonical_profile = EXCLUDED.canonical_profile, length_m = EXCLUDED.length_m, vert_m = EXCLUDED.vert_m, avg_gradient_pct = EXCLUDED.avg_gradient_pct, max_gradient_pct = EXCLUDED.max_gradient_pct, worthiness_score = EXCLUDED.worthiness_score, confidence = EXCLUDED.confidence, dem_source = EXCLUDED.dem_source, compiler_version = EXCLUDED.compiler_version, osm_way_refs = EXCLUDED.osm_way_refs, odbl_extract_at = EXCLUDED.odbl_extract_at, provenance = EXCLUDED.provenance, low_confidence_flags = EXCLUDED.low_confidence_flags, updated_at = now() RETURNING id), deleted_cells AS (DELETE FROM public.canon_corridor_cells WHERE canon_climb_id IN (SELECT id FROM upserted) RETURNING canon_climb_id), deletion_barrier AS (SELECT count(*) AS deleted_count FROM deleted_cells) INSERT INTO public.canon_corridor_cells (canon_climb_id, h3_resolution, tile_id, coverage_role) SELECT upserted.id, cells.h3_resolution, cells.tile_id, cells.coverage_role FROM upserted CROSS JOIN deletion_barrier JOIN (VALUES {cell_values}) AS cells(tile_id, h3_resolution, coverage_role) ON true ON CONFLICT DO NOTHING;",
        fingerprint = sql_literal(&candidate.candidate_fingerprint),
        display_name = sql_literal(&candidate.display_name),
        route_name = candidate
            .route_name
            .as_ref()
            .map(|name| sql_literal(name))
            .unwrap_or_else(|| "NULL".to_string()),
        polyline = sql_literal(&candidate.centerline_polyline),
        centerline = sql_literal(&candidate.centerline_wkt),
        corridor_half_width_m = candidate.corridor_half_width_m,
        gate_start = sql_literal(&candidate.gate_start_wkt),
        gate_end = sql_literal(&candidate.gate_end_wkt),
        profile = sql_literal(&profile_json),
        length = candidate.length_m,
        vert = candidate.vert_m,
        avg = candidate.avg_gradient_pct,
        max = candidate.max_gradient_pct,
        worthiness = candidate.worthiness_score,
        confidence = sql_literal(&candidate.confidence),
        dem_source = sql_literal(&candidate.dem_source),
        compiler_version = sql_literal(&candidate.compiler_version),
        way_refs = way_refs,
        odbl_extract_at = candidate
            .odbl_extract_at
            .as_ref()
            .map(|value| format!("{}::timestamptz", sql_literal(value)))
            .unwrap_or_else(|| "NULL".to_string()),
        provenance = sql_literal(&provenance_json),
        flags = flags,
        cell_values = cell_values
    )
}

fn sql_literal(value: &str) -> String {
    format!("'{}'", value.replace('\'', "''"))
}

fn meters_to_lat_degrees(meters: f64) -> f64 {
    meters / 111_320.0
}

fn meters_to_lon_degrees(meters: f64, lat: f64) -> f64 {
    meters / (111_320.0 * lat.to_radians().cos().abs().max(0.1))
}

fn format_coord(lon: f64, lat: f64) -> String {
    format!("{} {}", round_coord(lon), round_coord(lat))
}

fn round_coord(value: f64) -> f64 {
    (value * 10_000_000.0).round() / 10_000_000.0
}

fn round2(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

fn round3(value: f64) -> f64 {
    (value * 1000.0).round() / 1000.0
}

fn round4(value: f64) -> f64 {
    (value * 10000.0).round() / 10000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::geo_features::RoadFeatureBuilder;

    #[test]
    fn launch_scope_excludes_trunk_and_unnamed_service() {
        let trunk = RoadFeatureBuilder::new(1)
            .highway("trunk")
            .name("Expressway")
            .geometry(vec![(-75.2, 40.0), (-75.2, 40.01)])
            .build()
            .unwrap();
        let unnamed_service = RoadFeatureBuilder::new(2)
            .highway("service")
            .geometry(vec![(-75.2, 40.0), (-75.2, 40.01)])
            .build()
            .unwrap();
        let named_service = RoadFeatureBuilder::new(3)
            .highway("service")
            .name("Back Drive")
            .geometry(vec![(-75.2, 40.0), (-75.2, 40.01)])
            .build()
            .unwrap();

        assert!(!is_launch_scope_road(&trunk));
        assert!(!is_launch_scope_road(&unnamed_service));
        assert!(is_launch_scope_road(&named_service));
    }

    #[test]
    fn compiles_descending_fixture_as_ascending_candidate() {
        let road = RoadFeatureBuilder::new(695599067)
            .highway("residential")
            .name("Manayunk Wall")
            .geometry(vec![(-75.2220, 40.0240), (-75.2190, 40.0282)])
            .build()
            .unwrap();
        let profile = LocalElevationProfile {
            osm_way_id: road.osm_way_id,
            points: vec![
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0282,
                    lon: -75.2190,
                    elev_m: 92.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0270,
                    lon: -75.2200,
                    elev_m: 70.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0255,
                    lon: -75.2210,
                    elev_m: 44.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0240,
                    lon: -75.2220,
                    elev_m: 25.0,
                },
            ],
        };
        let report = compile_canon_candidates(
            &[road],
            &HashMap::from([(profile.osm_way_id, profile)]),
            &CanonCompileConfig::default(),
        );

        assert_eq!(report.candidates.len(), 1);
        let candidate = &report.candidates[0];
        assert_eq!(candidate.direction, "ascending");
        assert_eq!(candidate.display_name, "Manayunk Wall");
        assert!(candidate.vert_m > 60.0);
        assert!(candidate.length_m > 400.0);
        assert_eq!(candidate.candidate_fingerprint.len(), 64);
        assert_eq!(candidate.legacy_candidate_fingerprints.len(), 1);
        assert_eq!(
            candidate.legacy_candidate_fingerprints[0],
            candidate.provenance["candidate_fingerprint"]["legacy_v2_value"]
                .as_str()
                .unwrap()
        );
        assert!(candidate.centerline_wkt.starts_with("LINESTRING("));
        assert!(candidate.corridor_wkt.starts_with("MULTIPOLYGON((("));
        assert!(candidate.gate_start_wkt.starts_with("LINESTRING("));
        assert_eq!(candidate.canonical_profile.first().unwrap().dist_m, 0.0);
        assert!(
            candidate.canonical_profile.first().unwrap().elev_m
                < candidate.canonical_profile.last().unwrap().elev_m
        );
        assert!(candidate
            .corridor_cells
            .iter()
            .all(|cell| cell.h3_resolution == 10));
    }

    #[test]
    fn crest_road_emits_each_qualifying_ascent_direction_once() {
        let road = RoadFeatureBuilder::new(700)
            .highway("residential")
            .name("Two Sides Road")
            .geometry(vec![(-75.0, 40.0000), (-75.0, 40.0080)])
            .build()
            .unwrap();
        let profile = profile(
            road.osm_way_id,
            vec![
                profile_point(40.0000, -75.0, 20.0),
                profile_point(40.0010, -75.0, 35.0),
                profile_point(40.0020, -75.0, 52.0),
                profile_point(40.0030, -75.0, 74.0),
                profile_point(40.0040, -75.0, 100.0),
                profile_point(40.0050, -75.0, 82.0),
                profile_point(40.0060, -75.0, 65.0),
                profile_point(40.0070, -75.0, 48.0),
                profile_point(40.0080, -75.0, 32.0),
            ],
        );

        let report = compile_canon_candidates(
            &[road],
            &HashMap::from([(profile.osm_way_id, profile)]),
            &CanonCompileConfig::default(),
        );

        assert_eq!(
            report.candidates.len(),
            2,
            "both roadsides rise far enough to be separate D8 candidates"
        );
        let fingerprints = report
            .candidates
            .iter()
            .map(|candidate| candidate.candidate_fingerprint.as_str())
            .collect::<HashSet<_>>();
        assert_eq!(
            fingerprints.len(),
            2,
            "each direction needs its own identity"
        );
        let mut verticals = report
            .candidates
            .iter()
            .map(|candidate| candidate.vert_m)
            .collect::<Vec<_>>();
        verticals.sort_by(|left, right| left.partial_cmp(right).unwrap());
        assert_eq!(verticals, vec![68.0, 80.0], "unequal sides stay distinct");
        for candidate in &report.candidates {
            assert!(candidate.vert_m > 0.0);
            assert!(
                candidate.canonical_profile.first().unwrap().elev_m
                    < candidate.canonical_profile.last().unwrap().elev_m
            );
            assert_coord_close(centerline_end(candidate), (-75.0, 40.0040));
        }
        let supplemental = report
            .candidates
            .iter()
            .filter(|candidate| candidate.provenance.get("directional_extraction").is_some())
            .collect::<Vec<_>>();
        assert_eq!(supplemental.len(), 1);
        assert_eq!(
            supplemental[0].provenance["directional_extraction"]
                ["opposite_to_v020_primary_orientation"],
            true
        );
    }

    #[test]
    fn crest_span_can_join_distinct_way_chains_in_each_direction() {
        let south = RoadFeatureBuilder::new(701)
            .highway("residential")
            .name("Chained Crest Road")
            .geometry(vec![(-75.1, 40.0000), (-75.1, 40.0010)])
            .build()
            .unwrap();
        let summit = RoadFeatureBuilder::new(702)
            .highway("residential")
            .name("Chained Crest Road")
            .geometry(vec![(-75.1, 40.0010), (-75.1, 40.0030)])
            .build()
            .unwrap();
        let north = RoadFeatureBuilder::new(703)
            .highway("residential")
            .name("Chained Crest Road")
            .geometry(vec![(-75.1, 40.0030), (-75.1, 40.0040)])
            .build()
            .unwrap();
        let profiles = HashMap::from([
            (
                south.osm_way_id,
                profile(
                    south.osm_way_id,
                    vec![
                        profile_point(40.0000, -75.1, 20.0),
                        profile_point(40.0005, -75.1, 30.0),
                        profile_point(40.0010, -75.1, 40.0),
                    ],
                ),
            ),
            (
                summit.osm_way_id,
                profile(
                    summit.osm_way_id,
                    vec![
                        profile_point(40.0010, -75.1, 40.0),
                        profile_point(40.0015, -75.1, 70.0),
                        profile_point(40.0020, -75.1, 100.0),
                        profile_point(40.0025, -75.1, 75.0),
                        profile_point(40.0030, -75.1, 50.0),
                    ],
                ),
            ),
            (
                north.osm_way_id,
                profile(
                    north.osm_way_id,
                    vec![
                        profile_point(40.0030, -75.1, 50.0),
                        profile_point(40.0035, -75.1, 47.5),
                        profile_point(40.0040, -75.1, 45.0),
                    ],
                ),
            ),
        ]);

        let report = compile_canon_candidates(
            &[south, summit, north],
            &profiles,
            &CanonCompileConfig::default(),
        );

        assert_eq!(
            report.candidates.len(),
            2,
            "the summit way must remain available to both directional chains"
        );
        let starts = report
            .candidates
            .iter()
            .map(centerline_start)
            .collect::<Vec<_>>();
        assert!(starts
            .iter()
            .any(|start| (start.1 - 40.0000).abs() < 0.00002));
        assert!(starts
            .iter()
            .any(|start| (start.1 - 40.0040).abs() < 0.00002));
        let way_refs = report
            .candidates
            .iter()
            .map(|candidate| candidate.osm_way_refs.clone())
            .collect::<HashSet<_>>();
        assert!(way_refs.contains(&vec![701, 702]));
        assert!(way_refs.contains(&vec![703, 702]));
        for candidate in &report.candidates {
            assert_coord_close(centerline_end(candidate), (-75.1, 40.0020));
            assert!(candidate.vert_m > 0.0);
        }
        let supplemental_chain = report
            .candidates
            .iter()
            .find(|candidate| candidate.provenance.get("directional_extraction").is_some())
            .unwrap();
        assert_eq!(supplemental_chain.osm_way_refs, vec![703, 702]);
        assert_eq!(
            supplemental_chain.provenance["directional_extraction"]["opposite_way_refs"],
            json!([702])
        );
    }

    #[test]
    fn crest_road_drops_a_side_below_candidate_vertical_threshold() {
        let road = RoadFeatureBuilder::new(704)
            .highway("residential")
            .name("One Side Road")
            .geometry(vec![(-75.2, 40.0000), (-75.2, 40.0060)])
            .build()
            .unwrap();
        let profile = profile(
            road.osm_way_id,
            vec![
                profile_point(40.0000, -75.2, 20.0),
                profile_point(40.0010, -75.2, 45.0),
                profile_point(40.0020, -75.2, 72.0),
                profile_point(40.0030, -75.2, 100.0),
                profile_point(40.0040, -75.2, 97.0),
                profile_point(40.0050, -75.2, 95.0),
                profile_point(40.0060, -75.2, 93.0),
            ],
        );

        let report = compile_canon_candidates(
            &[road],
            &HashMap::from([(profile.osm_way_id, profile)]),
            &CanonCompileConfig::default(),
        );

        assert_eq!(report.candidates.len(), 1);
        assert_coord_close(centerline_start(&report.candidates[0]), (-75.2, 40.0000));
        assert_coord_close(centerline_end(&report.candidates[0]), (-75.2, 40.0030));
        assert_eq!(report.candidates[0].vert_m, 80.0);
    }

    #[test]
    fn flat_noisy_crest_emits_two_maximal_spans_without_nested_duplicates() {
        let road = RoadFeatureBuilder::new(705)
            .highway("residential")
            .name("Noisy Crest Road")
            .geometry(vec![(-75.3, 40.0000), (-75.3, 40.0120)])
            .build()
            .unwrap();
        let profile = profile(
            road.osm_way_id,
            vec![
                profile_point(40.0000, -75.3, 20.0),
                profile_point(40.0010, -75.3, 38.0),
                profile_point(40.0020, -75.3, 57.0),
                profile_point(40.0030, -75.3, 77.0),
                profile_point(40.0040, -75.3, 97.8),
                profile_point(40.0050, -75.3, 100.0),
                profile_point(40.0060, -75.3, 99.2),
                profile_point(40.0070, -75.3, 100.4),
                profile_point(40.0080, -75.3, 98.1),
                profile_point(40.0090, -75.3, 80.0),
                profile_point(40.0100, -75.3, 61.0),
                profile_point(40.0110, -75.3, 43.0),
                profile_point(40.0120, -75.3, 25.0),
            ],
        );

        let report = compile_canon_candidates(
            &[road],
            &HashMap::from([(profile.osm_way_id, profile)]),
            &CanonCompileConfig::default(),
        );

        assert_eq!(report.candidates.len(), 2);
        let directed_spans = report
            .candidates
            .iter()
            .map(|candidate| candidate.centerline_wkt.clone())
            .collect::<HashSet<_>>();
        assert_eq!(
            directed_spans.len(),
            2,
            "no nested or repeated span survives"
        );
        assert!(report
            .candidates
            .iter()
            .all(|candidate| candidate.vert_m > 70.0));
    }

    #[test]
    fn directional_crest_fingerprints_survive_harmless_profile_resampling() {
        let road = RoadFeatureBuilder::new(706)
            .highway("residential")
            .name("Resampled Crest Road")
            .geometry(vec![(-75.4, 40.0000), (-75.4, 40.0080)])
            .build()
            .unwrap();
        let sparse = profile(
            road.osm_way_id,
            vec![
                profile_point(40.0000, -75.4, 20.0),
                profile_point(40.0010, -75.4, 40.0),
                profile_point(40.0020, -75.4, 60.0),
                profile_point(40.0030, -75.4, 80.0),
                profile_point(40.0040, -75.4, 100.0),
                profile_point(40.0050, -75.4, 82.5),
                profile_point(40.0060, -75.4, 65.0),
                profile_point(40.0070, -75.4, 47.5),
                profile_point(40.0080, -75.4, 30.0),
            ],
        );
        let resampled = profile(
            road.osm_way_id,
            vec![
                profile_point(40.0000, -75.4, 20.0),
                profile_point(40.0005, -75.4, 30.0),
                profile_point(40.0010, -75.4, 40.0),
                profile_point(40.0015, -75.4, 50.0),
                profile_point(40.0020, -75.4, 60.0),
                profile_point(40.0025, -75.4, 70.0),
                profile_point(40.0030, -75.4, 80.0),
                profile_point(40.0035, -75.4, 90.0),
                profile_point(40.0040, -75.4, 100.0),
                profile_point(40.0045, -75.4, 91.25),
                profile_point(40.0050, -75.4, 82.5),
                profile_point(40.0055, -75.4, 73.75),
                profile_point(40.0060, -75.4, 65.0),
                profile_point(40.0065, -75.4, 56.25),
                profile_point(40.0070, -75.4, 47.5),
                profile_point(40.0075, -75.4, 38.75),
                profile_point(40.0080, -75.4, 30.0),
            ],
        );

        let sparse_report = compile_canon_candidates(
            &[road.clone()],
            &HashMap::from([(road.osm_way_id, sparse)]),
            &CanonCompileConfig::default(),
        );
        let resampled_report = compile_canon_candidates(
            &[road],
            &HashMap::from([(706, resampled)]),
            &CanonCompileConfig::default(),
        );
        let fingerprints = |report: &CanonCompileReport| {
            let mut values = report
                .candidates
                .iter()
                .map(|candidate| candidate.candidate_fingerprint.clone())
                .collect::<Vec<_>>();
            values.sort();
            values
        };

        assert_eq!(sparse_report.candidates.len(), 2);
        assert_eq!(resampled_report.candidates.len(), 2);
        assert_eq!(
            fingerprints(&sparse_report),
            fingerprints(&resampled_report)
        );
    }

    #[test]
    fn equal_score_directional_chain_identity_is_permutation_stable() {
        let segment = |segment_id,
                       osm_way_id,
                       start_lat,
                       start_lon,
                       end_lat,
                       end_lon,
                       start_elev,
                       end_elev,
                       is_opposite_span| WayChainSegment {
            segment_id,
            road: RoadFeatureBuilder::new(osm_way_id)
                .highway("residential")
                .name("Permutation Road")
                .geometry(vec![(start_lon, start_lat), (end_lon, end_lat)])
                .build()
                .unwrap(),
            points: vec![
                profile_point(start_lat, start_lon, start_elev),
                profile_point(end_lat, end_lon, end_elev),
            ],
            intersection_indices: BTreeSet::new(),
            route_key: Some("permutation road".to_string()),
            persistence_m: end_elev - start_elev,
            start_boundary_reason: "route_endpoint",
            end_boundary_reason: "route_endpoint",
            source_reversed: is_opposite_span,
            is_opposite_span,
        };
        let west = segment(
            0, 710, 39.9990, -75.0010, 40.0000, -75.0000, 20.0, 40.0, true,
        );
        let east = segment(
            1, 711, 39.9990, -74.9990, 40.0000, -75.0000, 20.0, 40.0, true,
        );
        let upper = segment(
            2, 712, 40.0000, -75.0000, 40.0010, -75.0000, 40.0, 65.0, false,
        );
        let west_score = continuation_between(0, 2, &west, &upper).unwrap().score;
        let east_score = continuation_between(1, 2, &east, &upper).unwrap().score;
        assert_eq!(west_score.to_bits(), east_score.to_bits());

        let identities = |segments: Vec<WayChainSegment>| {
            let mut candidates = build_directional_way_chains(&segments)
                .into_iter()
                .filter(|chain| chain.segments.iter().any(|item| item.is_opposite_span))
                .filter_map(|chain| compile_way_chain(&chain, &CanonCompileConfig::default()))
                .map(|candidate| {
                    (
                        candidate.candidate_fingerprint,
                        candidate.osm_way_refs,
                        candidate.centerline_wkt,
                    )
                })
                .collect::<Vec<_>>();
            candidates.sort();
            candidates
        };

        let original = identities(vec![west.clone(), east.clone(), upper.clone()]);
        let permuted = identities(vec![upper, east, west]);
        assert_eq!(original, permuted);
        assert_eq!(original.len(), 1);
        assert_eq!(original[0].1, vec![710, 712]);
    }

    #[test]
    fn duplicate_directional_chain_keeps_opposite_standalone_fallback_available() {
        let road = RoadFeatureBuilder::new(713)
            .highway("residential")
            .name("Fallback Crest Road")
            .geometry(vec![(-75.5, 40.0000), (-75.5, 40.0080)])
            .build()
            .unwrap();
        let profile = profile(
            road.osm_way_id,
            vec![
                profile_point(40.0000, -75.5, 20.0),
                profile_point(40.0020, -75.5, 60.0),
                profile_point(40.0040, -75.5, 100.0),
                profile_point(40.0060, -75.5, 65.0),
                profile_point(40.0080, -75.5, 30.0),
            ],
        );
        let config = CanonCompileConfig::default();
        let report = compile_canon_candidates(
            &[road.clone()],
            &HashMap::from([(road.osm_way_id, profile.clone())]),
            &config,
        );
        let primary = report
            .candidates
            .iter()
            .find(|candidate| candidate.provenance.get("directional_extraction").is_none())
            .unwrap()
            .clone();
        let expected_supplemental = report
            .candidates
            .iter()
            .find(|candidate| candidate.provenance.get("directional_extraction").is_some())
            .unwrap();
        let segments = directional_way_segments(
            &[ProfiledRoad {
                road,
                profile,
                intersection_indices: BTreeSet::new(),
            }],
            &config,
        );
        let opposite = segments
            .into_iter()
            .find(|segment| segment.is_opposite_span)
            .unwrap();
        let simulated_duplicate_chain = WayChain {
            segments: vec![opposite.clone()],
            directional_extraction: true,
        };

        // A full opposite-bearing chain cannot naturally share the primary v3
        // identity without identical ordered geometry. Inject that collision at
        // the acceptance boundary to freeze the segment-consumption invariant.
        let mut seen_fingerprints = HashSet::from([primary.candidate_fingerprint.clone()]);
        let mut chained_segment_ids = HashSet::new();
        let mut directionally_emitted_way_ids = HashSet::new();
        let mut candidates = vec![primary.clone()];
        assert!(!push_unique_directional_chain_candidate(
            primary,
            &simulated_duplicate_chain,
            &mut seen_fingerprints,
            &mut chained_segment_ids,
            &mut directionally_emitted_way_ids,
            &mut candidates,
        ));
        assert!(!chained_segment_ids.contains(&opposite.segment_id));
        assert!(directionally_emitted_way_ids.is_empty());
        assert_eq!(candidates.len(), 1);

        let standalone = compile_way_segment(&opposite, &config).unwrap();
        assert_eq!(
            standalone.candidate_fingerprint,
            expected_supplemental.candidate_fingerprint
        );
        assert!(seen_fingerprints.insert(standalone.candidate_fingerprint.clone()));
        candidates.push(standalone);
        assert_eq!(candidates.len(), 2);
    }

    #[test]
    fn parses_legacy_profile_map_shape() {
        let value = json!({
            "rose glen": {
                "osm_way_id": 42,
                "elevation_profile": [
                    {"lat": 40.0, "lon": -75.0, "elevation_m": 10.0, "dist_m": 0.0},
                    {"lat": 40.001, "lon": -75.0, "elevation_m": 20.0, "dist_m": 111.0}
                ]
            }
        });

        let profiles = local_profiles_from_json(value).unwrap();
        assert_eq!(profiles.len(), 1);
        assert_eq!(profiles[&42].points[1].elev_m, 20.0);
    }

    #[test]
    fn candidate_fingerprint_is_stable_when_profile_changes() {
        let road = RoadFeatureBuilder::new(99)
            .highway("residential")
            .name("Stable Hill")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.01)])
            .build()
            .unwrap();
        let profile_a = LocalElevationProfile {
            osm_way_id: road.osm_way_id,
            points: vec![
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0,
                    lon: -75.0,
                    elev_m: 10.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.005,
                    lon: -75.0,
                    elev_m: 42.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.01,
                    lon: -75.0,
                    elev_m: 70.0,
                },
            ],
        };
        let profile_b = LocalElevationProfile {
            osm_way_id: road.osm_way_id,
            points: vec![
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0,
                    lon: -75.0,
                    elev_m: 12.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.003,
                    lon: -75.0,
                    elev_m: 31.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.006,
                    lon: -75.0,
                    elev_m: 50.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.01,
                    lon: -75.0,
                    elev_m: 72.0,
                },
            ],
        };

        let report_a = compile_canon_candidates(
            &[road.clone()],
            &HashMap::from([(road.osm_way_id, profile_a)]),
            &CanonCompileConfig::default(),
        );
        let report_b = compile_canon_candidates(
            &[road],
            &HashMap::from([(99, profile_b)]),
            &CanonCompileConfig::default(),
        );

        let candidate_a = &report_a.candidates[0];
        let candidate_b = &report_b.candidates[0];
        let profile_hash_a = candidate_a.provenance["canonical_profile_hash"]["value"]
            .as_str()
            .unwrap();
        let profile_hash_b = candidate_b.provenance["canonical_profile_hash"]["value"]
            .as_str()
            .unwrap();

        assert_eq!(
            candidate_a.candidate_fingerprint,
            candidate_b.candidate_fingerprint
        );
        assert_ne!(profile_hash_a, profile_hash_b);
    }

    #[test]
    fn candidate_fingerprint_changes_when_centerline_geometry_changes() {
        let straight = vec![
            profile_point(40.0000, -75.0000, 10.0),
            profile_point(40.0050, -75.0000, 40.0),
            profile_point(40.0100, -75.0000, 70.0),
        ];
        let curved = vec![
            profile_point(40.0000, -75.0000, 10.0),
            profile_point(40.0050, -74.9980, 40.0),
            profile_point(40.0100, -75.0000, 70.0),
        ];

        assert_ne!(
            candidate_fingerprint(&[99], &straight),
            candidate_fingerprint(&[99], &curved),
            "same way refs and endpoints must not hide a materially different centerline"
        );
        assert_eq!(
            legacy_candidate_fingerprint_v2(&[99], &straight),
            legacy_candidate_fingerprint_v2(&[99], &curved),
            "the lineage key must reproduce the endpoint-only v2 fingerprint exactly"
        );
    }

    #[test]
    fn candidate_fingerprint_is_stable_across_centerline_resampling() {
        let sparse = vec![
            profile_point(40.0000, -75.0000, 10.0),
            profile_point(40.0050, -74.9980, 40.0),
            profile_point(40.0100, -75.0000, 70.0),
        ];
        let resampled = vec![
            profile_point(40.0000, -75.0000, 10.0),
            profile_point(40.0025, -74.9990, 25.0),
            profile_point(40.0050, -74.9980, 40.0),
            profile_point(40.0075, -74.9990, 55.0),
            profile_point(40.0100, -75.0000, 70.0),
        ];

        assert_eq!(
            candidate_fingerprint(&[99], &sparse),
            candidate_fingerprint(&[99], &resampled),
            "adding collinear samples must not mint a new canon candidate"
        );
    }

    #[test]
    fn candidate_fingerprint_ignores_noise_within_coordinate_grid_cells() {
        let baseline = vec![
            profile_point(40.0000, -75.0000, 10.0),
            profile_point(40.0040, -75.0000, 40.0),
            profile_point(40.0080, -75.0000, 70.0),
        ];
        let noisy = vec![
            profile_point(40.000001, -74.999999, 10.0),
            profile_point(40.004001, -74.999999, 40.0),
            profile_point(40.008001, -74.999999, 70.0),
        ];

        assert_eq!(
            candidate_fingerprint(&[99], &baseline),
            candidate_fingerprint(&[99], &noisy),
            "sub-meter coordinate noise within grid cells must not mint a candidate"
        );
    }

    #[test]
    fn canonical_vertical_is_finish_minus_start_not_cumulative_gain() {
        let points = vec![
            profile_point(40.0000, -75.0000, 100.0),
            profile_point(40.0010, -75.0000, 130.0),
            profile_point(40.0020, -75.0000, 120.0),
            profile_point(40.0030, -75.0000, 140.0),
        ];

        assert_eq!(net_rise_m(&points), Some(40.0));
    }

    #[test]
    fn confidence_tiers_distinguish_informational_and_material_flags() {
        let informational = ["topographic_isolation_not_scored_v0".to_string()];
        let one_material = ["profile_spacing_exceeds_15m".to_string()];
        let two_material = [
            "profile_spacing_exceeds_15m".to_string(),
            "dem_source_not_3dep_declared".to_string(),
        ];

        assert_eq!(confidence_tier(75.0, &informational), "high");
        assert_eq!(confidence_tier(74.99, &informational), "medium");
        assert_eq!(confidence_tier(80.0, &one_material), "needs_review");
        assert_eq!(confidence_tier(35.0, &one_material), "needs_review");
        assert_eq!(confidence_tier(35.0, &two_material), "low");
        assert_eq!(confidence_tier(34.99, &[]), "low");
    }

    #[test]
    fn corridor_cells_cover_buffer_and_gate_neighbors() {
        let mut points = vec![
            profile_point(40.0240, -75.2220, 25.0),
            profile_point(40.0282, -75.2190, 92.0),
        ];
        rebase_distances(&mut points);
        let cells = corridor_cells(&points, DEFAULT_GATE_HALF_WIDTH_M);
        let start = LatLng::new(points[0].lat, points[0].lon)
            .unwrap()
            .to_cell(Resolution::Ten);
        let neighbor = start
            .grid_disk::<Vec<_>>(1)
            .into_iter()
            .find(|cell| *cell != start)
            .unwrap()
            .to_string();

        assert!(cells
            .iter()
            .any(|cell| { cell.coverage_role == "corridor" && cell.tile_id == neighbor }));
        assert!(cells
            .iter()
            .any(|cell| { cell.coverage_role == "gate_start" && cell.tile_id == neighbor }));
    }

    #[test]
    fn duplicate_coordinates_do_not_inflate_max_gradient() {
        let mut points = vec![
            profile_point(40.0000, -75.0000, 10.0),
            profile_point(40.0000, -75.0000, 90.0),
            profile_point(40.0001, -75.0000, 91.0),
        ];
        rebase_distances(&mut points);

        assert!(
            max_gradient_pct(&points) < 20.0,
            "zero-distance DEM samples must not become an 8,000% grade"
        );
    }

    #[derive(Debug, Deserialize)]
    struct ReviewLabelFixture {
        labels: Vec<ReviewLabel>,
    }

    #[derive(Debug, Deserialize)]
    struct ReviewLabel {
        decision: String,
        distance_m: f64,
        gain_m: f64,
        avg_grade_pct: f64,
        max_gradient_pct: f64,
    }

    #[test]
    fn calibrated_worthiness_replays_tim_review_fixture() {
        let fixture: ReviewLabelFixture = serde_json::from_str(include_str!(
            "../../../backend/tests/fixtures/canon_review_labels_2026-07-05.json"
        ))
        .unwrap();
        let labels = fixture.labels;
        let approve_count = decision_count(&labels, "approve");
        let needs_work_count = decision_count(&labels, "needs_work");
        let suppress_count = decision_count(&labels, "suppress");
        assert_eq!(
            labels.len(),
            approve_count + needs_work_count + suppress_count
        );
        assert!(approve_count > 0, "fixture must include approved labels");
        assert!(
            needs_work_count > 0,
            "fixture must include boundary-work labels"
        );
        assert!(suppress_count > 0, "fixture must include suppressed labels");

        let mut scored = labels
            .iter()
            .map(|label| {
                (
                    calibrated_metric_worthiness_score(
                        label.distance_m,
                        label.gain_m,
                        label.avg_grade_pct,
                        label.max_gradient_pct,
                    ),
                    label,
                )
            })
            .collect::<Vec<_>>();
        scored.sort_by(|left, right| {
            right
                .0
                .partial_cmp(&left.0)
                .unwrap_or(std::cmp::Ordering::Equal)
        });

        let approve_scores = decision_scores(&scored, "approve");
        let suppress_scores = decision_scores(&scored, "suppress");
        let auc = pairwise_auc(&approve_scores, &suppress_scores);
        let top_32_approves = scored
            .iter()
            .take(32)
            .filter(|(_, label)| label.decision == "approve")
            .count();

        assert!(auc >= 0.78, "pairwise AUC was {auc}");
        assert!(
            median(approve_scores.clone()) > median(suppress_scores.clone()) + 20.0,
            "approved median should materially exceed suppressed median"
        );
        assert!(
            top_32_approves >= 18,
            "top 32 should recover most approved labels, got {top_32_approves}"
        );
    }

    #[test]
    fn chains_adjacent_way_profiles_into_single_candidate() {
        let lower = RoadFeatureBuilder::new(101)
            .highway("residential")
            .name("Lower Chain")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.001)])
            .build()
            .unwrap();
        let upper = RoadFeatureBuilder::new(102)
            .highway("residential")
            .name("Upper Chain")
            .geometry(vec![(-75.0, 40.001), (-75.0, 40.002)])
            .build()
            .unwrap();
        let lower_profile = LocalElevationProfile {
            osm_way_id: lower.osm_way_id,
            points: vec![
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0,
                    lon: -75.0,
                    elev_m: 10.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.001,
                    lon: -75.0,
                    elev_m: 24.0,
                },
            ],
        };
        let upper_profile = LocalElevationProfile {
            osm_way_id: upper.osm_way_id,
            points: vec![
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.001,
                    lon: -75.0,
                    elev_m: 23.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.002,
                    lon: -75.0,
                    elev_m: 42.0,
                },
            ],
        };

        let report = compile_canon_candidates(
            &[lower, upper],
            &HashMap::from([
                (lower_profile.osm_way_id, lower_profile),
                (upper_profile.osm_way_id, upper_profile),
            ]),
            &CanonCompileConfig::default(),
        );

        assert_eq!(report.candidates.len(), 1);
        let candidate = &report.candidates[0];
        assert_eq!(candidate.osm_way_refs, vec![101, 102]);
        assert_eq!(
            candidate.route_name.as_deref(),
            Some("Lower Chain / Upper Chain")
        );
        assert!(candidate.length_m > 200.0);
        assert!(candidate.vert_m > 30.0);
        assert_eq!(
            candidate.provenance["way_chain"]["algorithm"],
            "shared_endpoint_turn_gated_v2"
        );
    }

    #[test]
    fn parker_avenue_snaps_start_outward_to_umbria_shared_geometry() {
        let mut points = vec![
            profile_point(40.0000, -75.0000, 100.0),
            profile_point(40.0005, -75.0000, 101.0),
            profile_point(40.0010, -75.0000, 104.0),
            profile_point(40.0015, -75.0000, 116.0),
            profile_point(40.0020, -75.0000, 128.0),
        ];
        rebase_distances(&mut points);
        let snap = snap_start_boundary(&points, 2, 150.0, &BTreeSet::from([0]));

        assert_eq!(snap.index, 0);
        assert_eq!(snap.reason, "shared_road_geometry");
    }

    #[test]
    fn conshohocken_state_road_chains_woodmont_to_spring_mill() {
        let lower = RoadFeatureBuilder::new(201)
            .highway("secondary")
            .name("Conshohocken State Road")
            .geometry(vec![(-75.2500, 40.0000), (-75.2500, 40.0010)])
            .build()
            .unwrap();
        let upper = RoadFeatureBuilder::new(202)
            .highway("secondary")
            .name("Conshohocken State Road")
            .geometry(vec![(-75.2500, 40.0010), (-75.2500, 40.0020)])
            .build()
            .unwrap();
        let report = compile_canon_candidates(
            &[lower.clone(), upper.clone()],
            &HashMap::from([
                (
                    lower.osm_way_id,
                    profile(
                        lower.osm_way_id,
                        vec![
                            profile_point(40.0000, -75.2500, 80.0),
                            profile_point(40.0010, -75.2500, 96.0),
                        ],
                    ),
                ),
                (
                    upper.osm_way_id,
                    profile(
                        upper.osm_way_id,
                        vec![
                            profile_point(40.0010, -75.2500, 95.0),
                            profile_point(40.0020, -75.2500, 112.0),
                        ],
                    ),
                ),
            ]),
            &CanonCompileConfig::default(),
        );

        assert_eq!(report.candidates.len(), 1);
        let candidate = &report.candidates[0];
        assert_eq!(candidate.osm_way_refs, vec![201, 202]);
        assert_coord_close(centerline_start(candidate), (-75.2500, 40.0000));
        assert_coord_close(centerline_end(candidate), (-75.2500, 40.0020));
    }

    #[test]
    fn spring_garden_lane_does_not_use_unnamed_service_connector() {
        let spring_garden = RoadFeatureBuilder::new(301)
            .highway("residential")
            .name("Spring Garden Lane")
            .geometry(vec![(-75.2600, 40.0000), (-75.2600, 40.0010)])
            .build()
            .unwrap();
        let cutout = RoadFeatureBuilder::new(302)
            .highway("service")
            .geometry(vec![(-75.2600, 40.0010), (-75.25955, 40.00105)])
            .build()
            .unwrap();
        let rene = RoadFeatureBuilder::new(303)
            .highway("residential")
            .name("Rene Road")
            .geometry(vec![(-75.25955, 40.00105), (-75.25955, 40.00205)])
            .build()
            .unwrap();
        let report = compile_canon_candidates(
            &[spring_garden.clone(), cutout.clone(), rene.clone()],
            &HashMap::from([
                (
                    spring_garden.osm_way_id,
                    profile(
                        spring_garden.osm_way_id,
                        vec![
                            profile_point(40.0000, -75.2600, 90.0),
                            profile_point(40.0010, -75.2600, 104.0),
                        ],
                    ),
                ),
                (
                    cutout.osm_way_id,
                    profile(
                        cutout.osm_way_id,
                        vec![
                            profile_point(40.0010, -75.2600, 104.0),
                            profile_point(40.00105, -75.25955, 104.2),
                        ],
                    ),
                ),
                (
                    rene.osm_way_id,
                    profile(
                        rene.osm_way_id,
                        vec![
                            profile_point(40.00105, -75.25955, 104.0),
                            profile_point(40.00205, -75.25955, 122.0),
                        ],
                    ),
                ),
            ]),
            &CanonCompileConfig::default(),
        );

        assert!(report
            .candidates
            .iter()
            .all(|candidate| !candidate.osm_way_refs.contains(&302)));
    }

    #[test]
    fn ratified_falls_boundary_replaces_target_without_moving_other_candidates() {
        let lower_curve = RoadFeatureBuilder::new(12148403)
            .highway("secondary")
            .name("Falls Road")
            .geometry(vec![(-75.1990102, 40.0072221), (-75.2001250, 40.0067994)])
            .osm_node_ids(vec![110113531, 8_001])
            .build()
            .unwrap();
        let approach = RoadFeatureBuilder::new(1203287388)
            .highway("secondary")
            .name("Falls Road")
            .geometry(vec![(-75.2001250, 40.0067994), (-75.2020107, 40.0075044)])
            .osm_node_ids(vec![8_001, 8_002])
            .build()
            .unwrap();
        let current_lower = RoadFeatureBuilder::new(12148420)
            .highway("secondary")
            .name("Falls Road")
            .geometry(vec![(-75.2020107, 40.0075044), (-75.2020840, 40.0046810)])
            .osm_node_ids(vec![8_002, 8_003])
            .build()
            .unwrap();
        let current_upper = RoadFeatureBuilder::new(12149602)
            .highway("secondary")
            .name("Conshohocken Avenue")
            .geometry(vec![(-75.2020840, 40.0046810), (-75.2111438, 40.0021387)])
            .osm_node_ids(vec![8_003, 8_004])
            .build()
            .unwrap();
        let unrelated = RoadFeatureBuilder::new(9001)
            .highway("residential")
            .name("Unrelated Hill")
            .geometry(vec![(-75.4, 40.1), (-75.4, 40.102)])
            .build()
            .unwrap();

        let profiles = HashMap::from([
            (
                lower_curve.osm_way_id,
                profile(
                    lower_curve.osm_way_id,
                    vec![
                        profile_point(40.0072221, -75.1990102, 13.044047),
                        profile_point(40.00715782148951, -75.19909231509038, 13.503555),
                        profile_point(40.0067994, -75.2001250, 19.887707),
                    ],
                ),
            ),
            (
                approach.osm_way_id,
                profile(
                    approach.osm_way_id,
                    vec![
                        profile_point(40.0067994, -75.2001250, 19.887707),
                        profile_point(40.0071538, -75.2010555, 24.680745),
                        profile_point(40.0075044, -75.2020107, 29.551049),
                    ],
                ),
            ),
            (
                current_lower.osm_way_id,
                profile(
                    current_lower.osm_way_id,
                    vec![
                        profile_point(40.0075044, -75.2020107, 29.551049),
                        profile_point(40.0064726, -75.2014657, 36.468413),
                        profile_point(40.0046810, -75.2020840, 52.539130),
                    ],
                ),
            ),
            (
                current_upper.osm_way_id,
                profile(
                    current_upper.osm_way_id,
                    vec![
                        profile_point(40.0046810, -75.2020840, 52.539130),
                        profile_point(40.0031306, -75.2049827, 65.050993),
                        profile_point(40.0021387, -75.2111438, 68.945393),
                    ],
                ),
            ),
            (
                unrelated.osm_way_id,
                profile(
                    unrelated.osm_way_id,
                    vec![
                        profile_point(40.1000, -75.4, 20.0),
                        profile_point(40.1020, -75.4, 50.0),
                    ],
                ),
            ),
        ]);
        let config = CanonCompileConfig::default();
        let baseline = compile_canon_candidates(
            &[
                current_lower.clone(),
                current_upper.clone(),
                unrelated.clone(),
            ],
            &profiles,
            &config,
        );
        let target = baseline
            .candidates
            .iter()
            .find(|candidate| candidate.osm_way_refs == vec![12148420, 12149602])
            .expect("the pre-ratification Falls target should exist");
        let target_fingerprint = target.candidate_fingerprint.clone();
        let unrelated_before = serde_json::to_value(
            baseline
                .candidates
                .iter()
                .find(|candidate| candidate.osm_way_refs == vec![9001])
                .unwrap(),
        )
        .unwrap();
        let decisions = RatifiedBoundaryDecisionSet {
            model: "canon_ratified_boundaries_v1".to_string(),
            decisions: vec![RatifiedBoundaryDecision {
                decision_id: "falls-road-first-curve".to_string(),
                display_name: "Falls Road / Conshohocken Avenue".to_string(),
                route_name: Some("Falls Road / Conshohocken Avenue".to_string()),
                osm_way_refs: vec![12148403, 1203287388, 12148420, 12149602],
                start: RatifiedBoundaryAnchor {
                    label: "First curve off Falls Bridge".to_string(),
                    osm_node_id: Some(110113531),
                    lat: 40.0072221,
                    lon: -75.1990102,
                    max_offset_m: 2.0,
                    exact_gate: Some(RatifiedBoundaryGate {
                        a_lat: 40.0073808,
                        a_lon: -75.1992190,
                        b_lat: 40.0070634,
                        b_lon: -75.1988014,
                    }),
                },
                end: RatifiedBoundaryAnchor {
                    label: "Current Conshohocken Avenue finish".to_string(),
                    osm_node_id: None,
                    lat: 40.0021387,
                    lon: -75.2111438,
                    max_offset_m: 2.0,
                    exact_gate: None,
                },
                replaces_candidate_fingerprint: target_fingerprint.clone(),
                legacy_candidate_fingerprints: vec!["a".repeat(64)],
                evidence: RatifiedBoundaryEvidence {
                    requirement: RatifiedBoundaryApprovalEvidence {
                        approved_at: "2026-07-18".to_string(),
                        approved_by: "Tim".to_string(),
                        source: "test".to_string(),
                    },
                    geometry_translation: RatifiedBoundaryGeometryEvidence {
                        resolved_at: "2026-07-19".to_string(),
                        resolved_by: "Codex".to_string(),
                        source: "test".to_string(),
                    },
                    visual_approval: Some(RatifiedBoundaryApprovalEvidence {
                        approved_at: "2026-07-19".to_string(),
                        approved_by: "Tim".to_string(),
                        source: "history/canon-boundary-ratification-2026-07-18/falls-road-gate-review.png".to_string(),
                    }),
                },
                finish_decision: None,
            }],
        };

        let source_roads = [
            lower_curve.clone(),
            approach.clone(),
            current_lower.clone(),
            current_upper.clone(),
            unrelated.clone(),
        ];
        let report = apply_ratified_boundary_decisions(
            baseline.clone(),
            &source_roads,
            &profiles,
            &decisions,
            &config,
        )
        .expect("the approved boundary must compile");

        assert_eq!(report.candidates.len(), 2);
        assert!(report
            .candidates
            .iter()
            .all(|candidate| candidate.candidate_fingerprint != target_fingerprint));
        let falls = report
            .candidates
            .iter()
            .find(|candidate| candidate.osm_way_refs.len() == 4)
            .unwrap();
        assert_eq!(
            falls.osm_way_refs,
            vec![12148403, 1203287388, 12148420, 12149602]
        );
        assert_coord_close(centerline_start(falls), (-75.1990102, 40.0072221));
        assert_eq!(
            falls.gate_start_wkt,
            "LINESTRING(-75.199219 40.0073808, -75.1988014 40.0070634)"
        );
        assert!(falls
            .legacy_candidate_fingerprints
            .contains(&target_fingerprint));
        assert!(falls
            .legacy_candidate_fingerprints
            .contains(&"a".repeat(64)));
        assert_eq!(
            falls.provenance["ratified_boundary"]["decision_id"],
            "falls-road-first-curve"
        );
        assert_eq!(
            serde_json::to_value(
                report
                    .candidates
                    .iter()
                    .find(|candidate| candidate.osm_way_refs == vec![9001])
                    .unwrap(),
            )
            .unwrap(),
            unrelated_before,
            "ratification may replace its target but must not drift other candidates"
        );

        let mut rotated_gate_decisions = decisions.clone();
        rotated_gate_decisions.decisions[0].start.exact_gate = Some(RatifiedBoundaryGate {
            a_lat: 40.0074467,
            a_lon: -75.1990102,
            b_lat: 40.0069975,
            b_lon: -75.1990102,
        });
        let rotated_report = apply_ratified_boundary_decisions(
            baseline.clone(),
            &source_roads,
            &profiles,
            &rotated_gate_decisions,
            &config,
        )
        .expect("a distinct valid exact gate must compile");
        let rotated_falls = rotated_report
            .candidates
            .iter()
            .find(|candidate| candidate.osm_way_refs.len() == 4)
            .unwrap();
        assert_ne!(
            falls.candidate_fingerprint, rotated_falls.candidate_fingerprint,
            "changing an exact timing gate must change canon identity"
        );
        assert_eq!(falls.canonical_profile, rotated_falls.canonical_profile);
        assert_eq!(falls.length_m, rotated_falls.length_m);
        assert_eq!(falls.vert_m, rotated_falls.vert_m);

        let mut reversed_gate_decisions = decisions.clone();
        let gate = reversed_gate_decisions.decisions[0]
            .start
            .exact_gate
            .as_mut()
            .unwrap();
        std::mem::swap(&mut gate.a_lat, &mut gate.b_lat);
        std::mem::swap(&mut gate.a_lon, &mut gate.b_lon);
        let reversed_gate_report = apply_ratified_boundary_decisions(
            baseline.clone(),
            &source_roads,
            &profiles,
            &reversed_gate_decisions,
            &config,
        )
        .expect("reversing the same gate line must compile");
        let reversed_gate_falls = reversed_gate_report
            .candidates
            .iter()
            .find(|candidate| candidate.osm_way_refs.len() == 4)
            .unwrap();
        assert_eq!(
            falls.candidate_fingerprint, reversed_gate_falls.candidate_fingerprint,
            "gate endpoint order must not change canon identity"
        );

        let mut wrong_node_decisions = decisions.clone();
        wrong_node_decisions.decisions[0].start.osm_node_id = Some(999_999_999);
        let node_error = apply_ratified_boundary_decisions(
            baseline,
            &source_roads,
            &profiles,
            &wrong_node_decisions,
            &config,
        )
        .unwrap_err();
        assert!(node_error.contains("OSM node"));
    }

    #[test]
    fn ratified_route_can_join_next_way_at_shared_interior_node() {
        let first_road = RoadFeatureBuilder::new(7001)
            .highway("residential")
            .name("Interior Way Junction")
            .geometry(vec![(-75.0000, 40.0000), (-75.0000, 40.0010)])
            .osm_node_ids(vec![70_001, 70_002])
            .build()
            .unwrap();
        let second_road = RoadFeatureBuilder::new(7002)
            .highway("residential")
            .name("Interior Way Junction")
            .geometry(vec![
                (-75.0010, 40.0030),
                (-75.0000, 40.0010),
                (-74.9990, 40.0015),
            ])
            .osm_node_ids(vec![70_003, 70_002, 70_004])
            .build()
            .unwrap();
        let roads = HashMap::from([(7001, &first_road), (7002, &second_road)]);
        let profiles = HashMap::from([
            (
                7001,
                profile(
                    7001,
                    vec![
                        profile_point(40.0000, -75.0000, 10.0),
                        profile_point(40.0010, -75.0000, 30.0),
                    ],
                ),
            ),
            (
                7002,
                profile(
                    7002,
                    vec![
                        profile_point(40.0030, -75.0010, 45.0),
                        profile_point(40.0010, -75.0000, 30.0),
                        profile_point(40.0015, -74.9990, 36.0),
                    ],
                ),
            ),
        ]);
        let decision = RatifiedBoundaryDecision {
            finish_decision: None,
            decision_id: "interior-way-junction".to_string(),
            display_name: "Interior Way Junction".to_string(),
            route_name: Some("Interior Way Junction".to_string()),
            osm_way_refs: vec![7001, 7002],
            start: RatifiedBoundaryAnchor {
                label: "start".to_string(),
                osm_node_id: None,
                lat: 40.0000,
                lon: -75.0000,
                max_offset_m: 1.0,
                exact_gate: None,
            },
            end: RatifiedBoundaryAnchor {
                label: "end".to_string(),
                osm_node_id: None,
                lat: 40.0015,
                lon: -74.9990,
                max_offset_m: 1.0,
                exact_gate: None,
            },
            replaces_candidate_fingerprint: "b".repeat(64),
            legacy_candidate_fingerprints: Vec::new(),
            evidence: RatifiedBoundaryEvidence {
                requirement: RatifiedBoundaryApprovalEvidence {
                    approved_at: "2026-07-19".to_string(),
                    approved_by: "Tim".to_string(),
                    source: "test".to_string(),
                },
                geometry_translation: RatifiedBoundaryGeometryEvidence {
                    resolved_at: "2026-07-19".to_string(),
                    resolved_by: "Codex".to_string(),
                    source: "test".to_string(),
                },
                visual_approval: None,
            },
        };

        let stitched = build_ratified_profile(&decision, &profiles, &roads)
            .expect("an exact shared interior node must be a usable ordered seam");

        assert_eq!(stitched.points.len(), 3);
        assert_coord_close(
            (stitched.points[0].lon, stitched.points[0].lat),
            (-75.0000, 40.0000),
        );
        assert_coord_close(
            (stitched.points[1].lon, stitched.points[1].lat),
            (-75.0000, 40.0010),
        );
        assert_coord_close(
            (stitched.points[2].lon, stitched.points[2].lat),
            (-74.9990, 40.0015),
        );
    }

    #[test]
    fn ratified_profile_rejects_coordinate_only_seam_without_road_graph_join() {
        let decision = test_ratified_decision(
            "coordinate-only-seam",
            vec![7051, 7052],
            (40.0000, -75.0000),
            (40.0020, -75.0000),
            "9".repeat(64),
        );
        let profiles = HashMap::from([
            (
                7051,
                profile(
                    7051,
                    vec![
                        profile_point(40.0000, -75.0000, 10.0),
                        profile_point(40.0010, -75.0000, 20.0),
                    ],
                ),
            ),
            (
                7052,
                profile(
                    7052,
                    vec![
                        profile_point(40.0010, -75.0000, 20.0),
                        profile_point(40.0020, -75.0000, 35.0),
                    ],
                ),
            ),
        ]);
        let first_road = RoadFeatureBuilder::new(7051)
            .highway("residential")
            .geometry(vec![(-75.0000, 40.0000), (-75.0000, 40.0010)])
            .osm_node_ids(vec![70_051, 70_052])
            .build()
            .unwrap();
        let second_road = RoadFeatureBuilder::new(7052)
            .highway("residential")
            .geometry(vec![(-75.0000, 40.0010), (-75.0000, 40.0020)])
            .osm_node_ids(vec![70_053, 70_054])
            .build()
            .unwrap();
        let roads = HashMap::from([(7051, &first_road), (7052, &second_road)]);

        let error = build_ratified_profile(&decision, &profiles, &roads).unwrap_err();
        assert!(error.contains("shared OSM node"));
    }

    #[test]
    fn ratified_anchor_projection_rejects_distinct_near_equal_matches() {
        let anchor = RatifiedBoundaryAnchor {
            label: "ambiguous loop crossing".to_string(),
            osm_node_id: None,
            lat: 40.001,
            lon: -75.0,
            max_offset_m: 2.0,
            exact_gate: None,
        };
        let points = vec![
            profile_point(40.0000, -75.0010, 10.0),
            profile_point(40.0020, -74.9990, 20.0),
            profile_point(40.0020, -75.0010, 30.0),
            profile_point(40.0000, -74.9990, 40.0),
        ];

        assert!(project_anchor_onto_profile(&anchor, &points).is_err());
    }

    #[test]
    fn empty_ratified_boundary_set_is_an_exact_noop() {
        let road = RoadFeatureBuilder::new(7101)
            .highway("residential")
            .name("No-op Hill")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.002)])
            .build()
            .unwrap();
        let profiles = HashMap::from([(
            road.osm_way_id,
            profile(
                road.osm_way_id,
                vec![
                    profile_point(40.0000, -75.0000, 10.0),
                    profile_point(40.0020, -75.0000, 35.0),
                ],
            ),
        )]);
        let report = compile_canon_candidates(
            std::slice::from_ref(&road),
            &profiles,
            &CanonCompileConfig::default(),
        );
        let before = serde_json::to_value(&report).unwrap();

        let after = apply_ratified_boundary_decisions(
            report,
            &[],
            &HashMap::new(),
            &RatifiedBoundaryDecisionSet {
                model: RATIFIED_BOUNDARY_MODEL.to_string(),
                decisions: Vec::new(),
            },
            &CanonCompileConfig::default(),
        )
        .unwrap();

        assert_eq!(serde_json::to_value(after).unwrap(), before);
    }

    #[test]
    fn ratified_boundaries_reject_stale_target_before_geometry() {
        let road = RoadFeatureBuilder::new(7201)
            .highway("residential")
            .name("Stale Target Hill")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.002)])
            .build()
            .unwrap();
        let profiles = HashMap::from([(
            road.osm_way_id,
            profile(
                road.osm_way_id,
                vec![
                    profile_point(40.0000, -75.0000, 10.0),
                    profile_point(40.0020, -75.0000, 35.0),
                ],
            ),
        )]);
        let report = compile_canon_candidates(
            std::slice::from_ref(&road),
            &profiles,
            &CanonCompileConfig::default(),
        );
        let decision = test_ratified_decision(
            "stale-target",
            vec![road.osm_way_id],
            (40.0000, -75.0000),
            (40.0020, -75.0000),
            "c".repeat(64),
        );

        let error = apply_ratified_boundary_decisions(
            report,
            &[road],
            &profiles,
            &RatifiedBoundaryDecisionSet {
                model: RATIFIED_BOUNDARY_MODEL.to_string(),
                decisions: vec![decision],
            },
            &CanonCompileConfig::default(),
        )
        .unwrap_err();

        assert!(error.contains("expected exactly one replacement target"));
        assert!(error.ends_with("found 0"));
    }

    #[test]
    fn ratified_profiles_fail_closed_on_missing_data_bad_seam_and_distant_anchor() {
        let first_road = RoadFeatureBuilder::new(7301)
            .highway("residential")
            .geometry(vec![(-75.0000, 40.0000), (-75.0000, 40.0010)])
            .osm_node_ids(vec![73_001, 73_002])
            .build()
            .unwrap();
        let second_road = RoadFeatureBuilder::new(7302)
            .highway("residential")
            .geometry(vec![(-75.0000, 40.0010), (-75.0000, 40.0020)])
            .osm_node_ids(vec![73_002, 73_003])
            .build()
            .unwrap();
        let first_road_only = HashMap::from([(7301, &first_road)]);
        let seam_roads = HashMap::from([(7301, &first_road), (7302, &second_road)]);
        let decision = test_ratified_decision(
            "missing-profile",
            vec![7301],
            (40.0000, -75.0000),
            (40.0020, -75.0000),
            "d".repeat(64),
        );
        let missing_error =
            build_ratified_profile(&decision, &HashMap::new(), &first_road_only).unwrap_err();
        assert!(missing_error.contains("missing local DEM profile"));

        let seam_decision = test_ratified_decision(
            "bad-seam",
            vec![7301, 7302],
            (40.0000, -75.0000),
            (40.0020, -75.0000),
            "e".repeat(64),
        );
        let seam_profiles = HashMap::from([
            (
                7301,
                profile(
                    7301,
                    vec![
                        profile_point(40.0000, -75.0000, 10.0),
                        profile_point(40.0010, -75.0000, 20.0),
                    ],
                ),
            ),
            (
                7302,
                profile(
                    7302,
                    vec![
                        profile_point(40.0010, -75.0000, 40.0),
                        profile_point(40.0020, -75.0000, 50.0),
                    ],
                ),
            ),
        ]);
        let seam_error =
            build_ratified_profile(&seam_decision, &seam_profiles, &seam_roads).unwrap_err();
        assert!(seam_error.contains("profile seam"));

        let distant_decision = test_ratified_decision(
            "distant-anchor",
            vec![7301],
            (41.0000, -76.0000),
            (41.0020, -76.0000),
            "f".repeat(64),
        );
        let distant_profiles = HashMap::from([(
            7301,
            profile(
                7301,
                vec![
                    profile_point(40.0000, -75.0000, 10.0),
                    profile_point(40.0020, -75.0000, 35.0),
                ],
            ),
        )]);
        let anchor_error =
            build_ratified_profile(&distant_decision, &distant_profiles, &first_road_only)
                .unwrap_err();
        assert!(anchor_error.contains("exact anchors"));
    }

    #[test]
    fn ratified_boundaries_reject_out_of_scope_roads_and_duplicate_targets() {
        let unnamed_service = RoadFeatureBuilder::new(7401)
            .highway("service")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.002)])
            .build()
            .unwrap();
        let decision = test_ratified_decision(
            "out-of-scope",
            vec![unnamed_service.osm_way_id],
            (40.0000, -75.0000),
            (40.0020, -75.0000),
            "1".repeat(64),
        );
        let road_by_id = HashMap::from([(unnamed_service.osm_way_id, &unnamed_service)]);
        let points = vec![
            profile_point(40.0000, -75.0000, 10.0),
            profile_point(40.0020, -75.0000, 35.0),
        ];

        let scope_error = build_ratified_road_feature(&decision, &points, &road_by_id).unwrap_err();
        assert!(scope_error.contains("out-of-scope OSM way"));

        let mut duplicate = decision.clone();
        duplicate.decision_id = "duplicate-target".to_string();
        let validation_error = validate_ratified_boundary_decisions(&RatifiedBoundaryDecisionSet {
            model: RATIFIED_BOUNDARY_MODEL.to_string(),
            decisions: vec![decision, duplicate],
        })
        .unwrap_err();
        assert!(validation_error.contains("invalid or duplicated replacement fingerprint"));

        let mut first = test_ratified_decision(
            "first-lineage-owner",
            vec![7402],
            (40.0000, -75.0000),
            (40.0020, -75.0000),
            "2".repeat(64),
        );
        first.legacy_candidate_fingerprints = vec!["4".repeat(64)];
        let mut second = test_ratified_decision(
            "second-lineage-owner",
            vec![7403],
            (40.0000, -75.0000),
            (40.0020, -75.0000),
            "3".repeat(64),
        );
        second.legacy_candidate_fingerprints = first.legacy_candidate_fingerprints.clone();
        let lineage_error = validate_ratified_boundary_decisions(&RatifiedBoundaryDecisionSet {
            model: RATIFIED_BOUNDARY_MODEL.to_string(),
            decisions: vec![first, second],
        })
        .unwrap_err();
        assert!(lineage_error.contains("fingerprint lineage"));
    }

    #[test]
    fn ratified_profile_assembly_ignores_profile_map_insertion_order() {
        let decision = test_ratified_decision(
            "deterministic-profile-map",
            vec![7501, 7502],
            (40.0000, -75.0000),
            (40.0020, -74.9990),
            "2".repeat(64),
        );
        let first = profile(
            7501,
            vec![
                profile_point(40.0000, -75.0000, 10.0),
                profile_point(40.0010, -75.0000, 25.0),
            ],
        );
        let second = profile(
            7502,
            vec![
                profile_point(40.0010, -75.0000, 25.0),
                profile_point(40.0020, -74.9990, 40.0),
            ],
        );
        let mut forward = HashMap::new();
        forward.insert(7501, first.clone());
        forward.insert(7502, second.clone());
        let mut reverse = HashMap::new();
        reverse.insert(7502, second);
        reverse.insert(7501, first);

        let first_road = RoadFeatureBuilder::new(7501)
            .highway("residential")
            .geometry(vec![(-75.0000, 40.0000), (-75.0000, 40.0010)])
            .osm_node_ids(vec![75_001, 75_002])
            .build()
            .unwrap();
        let second_road = RoadFeatureBuilder::new(7502)
            .highway("residential")
            .geometry(vec![(-75.0000, 40.0010), (-74.9990, 40.0020)])
            .osm_node_ids(vec![75_002, 75_003])
            .build()
            .unwrap();
        let roads = HashMap::from([(7501, &first_road), (7502, &second_road)]);

        let forward_profile = build_ratified_profile(&decision, &forward, &roads).unwrap();
        let reverse_profile = build_ratified_profile(&decision, &reverse, &roads).unwrap();

        assert_eq!(forward_profile.points, reverse_profile.points);
        assert_eq!(
            forward_profile.reversed_way_refs,
            reverse_profile.reversed_way_refs
        );
        assert_eq!(forward_profile.seam_gaps_m, reverse_profile.seam_gaps_m);
        assert_eq!(
            forward_profile.seam_elevation_deltas_m,
            reverse_profile.seam_elevation_deltas_m
        );
    }

    fn crest_finish_fixture() -> (
        RatifiedBoundaryDecisionSet,
        Vec<RoadFeature>,
        HashMap<i64, LocalElevationProfile>,
        CanonCompileReport,
    ) {
        let mut decisions = ratified_boundary_decisions_from_json(
            serde_json::from_str(include_str!(
                "../../resources/philly_ratified_boundaries_v1.json"
            ))
            .unwrap(),
        )
        .unwrap();
        decisions
            .decisions
            .retain(|d| d.decision_id == "lafayette-lump-crest");
        assert_eq!(
            decisions.decisions.len(),
            1,
            "Lafayette Road needs its tracked crest decision"
        );
        let profiles = local_profiles_from_json(
            serde_json::from_str(include_str!(
                "../../resources/philly_ratified_boundary_3dep_profiles_v1.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let roads = ratified_fixture_roads();
        let seed = RoadFeatureBuilder::new(7601)
            .highway("residential")
            .name("Unrelated Control Hill")
            .geometry(vec![(-75.5, 40.1), (-75.5, 40.102)])
            .build()
            .unwrap();
        let mut report = compile_canon_candidates(
            &[seed],
            &HashMap::from([(
                7601,
                profile(
                    7601,
                    vec![
                        profile_point(40.1, -75.5, 10.0),
                        profile_point(40.102, -75.5, 40.0),
                    ],
                ),
            )]),
            &CanonCompileConfig::default(),
        );
        let mut target = report.candidates[0].clone();
        target.candidate_fingerprint = decisions.decisions[0]
            .replaces_candidate_fingerprint
            .clone();
        target.legacy_candidate_fingerprints.clear();
        target.gate_start_wkt = "LINESTRING(-75.2743164 40.0591552, -75.2738812 40.0594566)".into();
        report.candidates.push(target);
        (decisions, roads, profiles, report)
    }

    #[test]
    fn crest_finish_decision_extends_only_its_target_deterministically() {
        let (decisions, roads, profiles, report) = crest_finish_fixture();
        let config = CanonCompileConfig::default();
        let first = apply_ratified_boundary_decisions(
            report.clone(),
            &roads,
            &profiles,
            &decisions,
            &config,
        )
        .unwrap();
        let again = apply_ratified_boundary_decisions(
            report.clone(),
            &roads,
            &profiles,
            &decisions,
            &config,
        )
        .unwrap();
        assert_eq!(
            serde_json::to_vec(&first).unwrap(),
            serde_json::to_vec(&again).unwrap()
        );
        assert_eq!(
            serde_json::to_value(&first.candidates[0]).unwrap(),
            serde_json::to_value(&report.candidates[0]).unwrap()
        );
        let crest = &first.candidates[1];
        assert_eq!(crest.gate_start_wkt, report.candidates[1].gate_start_wkt);
        assert!((crest.length_m - 2244.4).abs() < 0.1);
        assert!((crest.vert_m - 101.3).abs() < 0.15);
        assert_eq!(
            crest.osm_way_refs,
            vec![12370459, 12329089, 594346758, 12370452]
        );
        assert!(crest
            .legacy_candidate_fingerprints
            .contains(&report.candidates[1].candidate_fingerprint));
        assert_eq!(
            crest.provenance["ratified_boundary"]["finish_decision"]["type"],
            "crest finish (founder-approved)"
        );
        assert_eq!(
            crest.provenance["ratified_boundary"]["evidence"]["requirement"]["approved_at"],
            "2026-10-21T00:13:00Z"
        );
        assert!(
            crest.provenance.get("finish_gate_rule").is_none(),
            "D7.5 junction setback is not a crest decision"
        );
        let end = centerline_end(crest);
        assert!((end.0 + 75.29571220380879).abs() < 1e-7);
        assert!((end.1 - 40.05129374835202).abs() < 1e-7);
        let gate = parse_gate_wkt(&crest.gate_end_wkt);
        for arm in [gate.0, gate.1] {
            // gate_wkt uses 111,320 m/degree; allow its known 0.12%
            // spherical-scale difference plus seven-decimal WKT rounding.
            assert!((haversine_m(end.1, end.0, arm.1, arm.0) - 25.0).abs() < 0.05);
        }
    }

    #[test]
    fn crest_finish_missing_or_unknown_way_names_the_climb() {
        let (decisions, roads, profiles, report) = crest_finish_fixture();
        let config = CanonCompileConfig::default();
        for way in [12370459, 12329089, 594346758, 12370452] {
            let missing_roads: Vec<_> = roads
                .iter()
                .filter(|r| r.osm_way_id != way)
                .cloned()
                .collect();
            let error = apply_ratified_boundary_decisions(
                report.clone(),
                &missing_roads,
                &profiles,
                &decisions,
                &config,
            )
            .unwrap_err();
            assert!(
                error.contains("Lafayette Road") && error.contains(&way.to_string()),
                "{error}"
            );
            let mut missing_profiles = profiles.clone();
            missing_profiles.remove(&way);
            let error = apply_ratified_boundary_decisions(
                report.clone(),
                &roads,
                &missing_profiles,
                &decisions,
                &config,
            )
            .unwrap_err();
            assert!(
                error.contains("Lafayette Road") && error.contains(&way.to_string()),
                "{error}"
            );
        }
        let mut invalid = decisions.clone();
        invalid.decisions[0].osm_way_refs[1] = i64::MAX;
        let error =
            apply_ratified_boundary_decisions(report.clone(), &roads, &profiles, &invalid, &config)
                .unwrap_err();
        assert!(
            error.contains("Lafayette Road") && error.contains(&i64::MAX.to_string()),
            "{error}"
        );
        let mut omitted = decisions;
        omitted.decisions[0].osm_way_refs.remove(1);
        let error = apply_ratified_boundary_decisions(report, &roads, &profiles, &omitted, &config)
            .unwrap_err();
        assert!(error.contains("Lafayette Road"), "{error}");
    }

    #[test]
    fn crest_finish_malformed_way_decision_names_the_climb() {
        let source: Value = serde_json::from_str(include_str!(
            "../../resources/philly_ratified_boundaries_v1.json"
        ))
        .unwrap();
        for missing_field in [false, true] {
            let mut value = source.clone();
            let crest = value["decisions"]
                .as_array_mut()
                .unwrap()
                .iter_mut()
                .find(|d| d["decision_id"] == "lafayette-lump-crest")
                .unwrap();
            if missing_field {
                crest.as_object_mut().unwrap().remove("osm_way_refs");
            } else {
                crest["osm_way_refs"][1] = Value::Null;
            }
            let error = ratified_boundary_decisions_from_json(value).unwrap_err();
            assert!(error.contains("Lafayette Road"), "{error}");
        }
    }

    #[test]
    fn embedded_philadelphia_boundaries_compile_exactly_and_deterministically() {
        let decisions = ratified_boundary_decisions_from_json(
            serde_json::from_str(include_str!(
                "../../resources/philly_ratified_boundaries_v1.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let profiles = local_profiles_from_json(
            serde_json::from_str(include_str!(
                "../../resources/philly_ratified_boundary_3dep_profiles_v1.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let roads = ratified_fixture_roads();
        assert_eq!(roads.len(), 65);

        let seed_road = RoadFeatureBuilder::new(7601)
            .highway("residential")
            .name("Unrelated Control Hill")
            .geometry(vec![(-75.5, 40.1), (-75.5, 40.102)])
            .build()
            .unwrap();
        let seed_profiles = HashMap::from([(
            seed_road.osm_way_id,
            profile(
                seed_road.osm_way_id,
                vec![
                    profile_point(40.1000, -75.5000, 10.0),
                    profile_point(40.1020, -75.5000, 40.0),
                ],
            ),
        )]);
        let mut baseline =
            compile_canon_candidates(&[seed_road], &seed_profiles, &CanonCompileConfig::default());
        assert_eq!(baseline.candidates.len(), 1);
        let control = baseline.candidates[0].clone();
        baseline.candidates = decisions
            .decisions
            .iter()
            .map(|decision| {
                let mut target = control.clone();
                target.candidate_fingerprint = decision.replaces_candidate_fingerprint.clone();
                target.legacy_candidate_fingerprints.clear();
                target
            })
            .chain(std::iter::once(control.clone()))
            .collect();
        baseline.stats.emitted_candidates = baseline.candidates.len();

        let forward = apply_ratified_boundary_decisions(
            baseline.clone(),
            &roads,
            &profiles,
            &decisions,
            &CanonCompileConfig::default(),
        )
        .unwrap();
        let mut reversed_decisions = decisions.clone();
        reversed_decisions.decisions.reverse();
        let mut reversed_roads = roads.clone();
        reversed_roads.reverse();
        let reversed = apply_ratified_boundary_decisions(
            baseline,
            &reversed_roads,
            &profiles,
            &reversed_decisions,
            &CanonCompileConfig::default(),
        )
        .unwrap();

        assert_eq!(forward.candidates.len(), 17);
        assert_eq!(reversed.candidates.len(), 17);
        let unique_fingerprints = forward
            .candidates
            .iter()
            .map(|candidate| &candidate.candidate_fingerprint)
            .collect::<HashSet<_>>();
        assert_eq!(unique_fingerprints.len(), forward.candidates.len());
        assert_eq!(
            serde_json::to_value(
                forward
                    .candidates
                    .iter()
                    .find(|candidate| {
                        candidate.candidate_fingerprint == control.candidate_fingerprint
                    })
                    .unwrap()
            )
            .unwrap(),
            serde_json::to_value(&control).unwrap()
        );

        for decision in &decisions.decisions {
            assert!(forward.candidates.iter().all(|candidate| {
                candidate.candidate_fingerprint != decision.replaces_candidate_fingerprint
            }));
            let candidate = forward
                .candidates
                .iter()
                .find(|candidate| {
                    candidate.provenance["ratified_boundary"]["decision_id"] == decision.decision_id
                })
                .unwrap();
            let reversed_candidate = reversed
                .candidates
                .iter()
                .find(|candidate| {
                    candidate.provenance["ratified_boundary"]["decision_id"] == decision.decision_id
                })
                .unwrap();

            assert_coord_close(
                centerline_start(candidate),
                (decision.start.lon, decision.start.lat),
            );
            assert_coord_close(
                centerline_end(candidate),
                (decision.end.lon, decision.end.lat),
            );
            assert_eq!(candidate.osm_way_refs, decision.osm_way_refs);
            assert!(candidate.length_m > 0.0);
            assert!(candidate.vert_m > 0.0);
            assert!(candidate
                .legacy_candidate_fingerprints
                .contains(&decision.replaces_candidate_fingerprint));
            for legacy in &decision.legacy_candidate_fingerprints {
                assert!(candidate.legacy_candidate_fingerprints.contains(legacy));
            }
            if let Some(gate) = &decision.start.exact_gate {
                assert_eq!(candidate.gate_start_wkt, ratified_gate_wkt(gate));
            }
            if let Some(gate) = &decision.end.exact_gate {
                assert_eq!(candidate.gate_end_wkt, ratified_gate_wkt(gate));
            }
            assert_eq!(
                serde_json::to_value(candidate).unwrap(),
                serde_json::to_value(reversed_candidate).unwrap(),
                "{} changed when decision and road input order reversed",
                decision.decision_id
            );
        }
    }

    #[test]
    fn embedded_legacy_approvals_preserve_exact_full_route_contract() {
        let decisions = ratified_boundary_decisions_from_json(
            serde_json::from_str(include_str!(
                "../../resources/philly_ratified_boundaries_v1.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let expected = [
            (
                "conshohocken-state-approved-full-route",
                "a36d85c200c9ec31af48fe5224537eeaf56468682947babd74c330d6fe183d5d",
                "55112c8ee3d7c1ad5e84a857aa8d91eac74cc4a55c937e90664f6d2001a7dc46",
                &[423_971_318][..],
                (1_495_634_351, 40.0316212, -75.2697678),
                (5_667_775_462, 40.0377946, -75.2783306),
                "2026-07-05T23:38:04.636581+00:00",
            ),
            (
                "port-royal-approved-full-route",
                "859a5b9efb2e48bc5d02727d762e9f4043972c13a8d612d4ea3d6bc60b1adbe1",
                "7145571fe31a69534ed2bf0fb4ac03866afc0c1d185c637ce32f2529943f8747",
                &[688_421_782, 108_593_573, 1_426_407_796][..],
                (11_001_942_645, 40.0480230, -75.2540423),
                (110_443_757, 40.0575078, -75.2414777),
                "2026-07-05T23:37:19.410338+00:00",
            ),
            (
                "rockland-approved-full-route",
                "7bb2c4f8956e84ddaa9b02e97b6bbbb8ec66a312604f4a71f570de1a61d33c13",
                "af392156a21ce7388c4689cb62ce78f77b72a0a2761d260e9cdf3164e796fbab",
                &[43_293_682][..],
                (543_978_934, 40.0274446, -75.2352021),
                (111_872_181, 40.0269487, -75.2374318),
                "2026-07-05T23:35:01.457498+00:00",
            ),
            (
                "waverly-approved-full-route",
                "b014bdc0bd619442d50e7893cef3363829317d2923423080631e8880c1555c60",
                "bc6fb610615e777951c8111df96ff99204f738b86d05ea4f23a928ec351a07ab",
                &[12_373_553, 1_352_630_700, 1_352_630_701][..],
                (248_557_643, 40.0578978, -75.2712560),
                (112_062_193, 40.0499632, -75.2733195),
                "2026-07-05T23:27:33.475157+00:00",
            ),
        ];

        assert_eq!(decisions.decisions.len(), 16);
        for (decision_id, target, approved, ways, start, end, approved_at) in expected {
            let decision = decisions
                .decisions
                .iter()
                .find(|decision| decision.decision_id == decision_id)
                .unwrap_or_else(|| panic!("missing restored boundary {decision_id}"));
            assert_eq!(decision.replaces_candidate_fingerprint, target);
            assert_eq!(decision.legacy_candidate_fingerprints, [approved]);
            assert_eq!(decision.osm_way_refs, ways);
            assert_eq!(
                (
                    decision.start.osm_node_id.unwrap(),
                    decision.start.lat,
                    decision.start.lon
                ),
                start
            );
            assert_eq!(
                (
                    decision.end.osm_node_id.unwrap(),
                    decision.end.lat,
                    decision.end.lon
                ),
                end
            );
            assert_eq!(decision.evidence.requirement.approved_at, approved_at);
        }
    }

    #[test]
    fn mary_waters_ford_snaps_curve_start_and_named_finish() {
        let mut points = vec![
            profile_point(40.0100, -75.2700, 60.0),
            profile_point(40.0105, -75.2700, 61.0),
            profile_point(40.0110, -75.2700, 64.0),
            profile_point(40.0115, -75.2700, 75.0),
            profile_point(40.0120, -75.2700, 86.0),
            profile_point(40.0125, -75.2700, 88.0),
            profile_point(40.0130, -75.2700, 89.0),
        ];
        rebase_distances(&mut points);
        let intersections = BTreeSet::from([0, 6]);

        let start = snap_start_boundary(&points, 2, 150.0, &intersections);
        let end = snap_end_boundary(&points, 4, 150.0, &intersections);

        assert_eq!(start.index, 0);
        assert_eq!(start.reason, "shared_road_geometry");
        assert_eq!(end.index, 6);
        assert_eq!(end.reason, "shared_road_geometry");
    }

    #[test]
    fn flat_rock_road_accepts_hidden_river_continuation_after_small_dip() {
        let current = WayChainSegment {
            segment_id: 0,
            road: RoadFeatureBuilder::new(401)
                .highway("residential")
                .name("Flat Rock Road")
                .geometry(vec![(-75.2800, 40.0000), (-75.2800, 40.0010)])
                .build()
                .unwrap(),
            points: vec![
                profile_point(40.0000, -75.2800, 100.0),
                profile_point(40.0010, -75.2800, 130.0),
            ],
            intersection_indices: BTreeSet::new(),
            route_key: Some("flat rock road".to_string()),
            persistence_m: 30.0,
            start_boundary_reason: "route_endpoint",
            end_boundary_reason: "route_endpoint",
            source_reversed: false,
            is_opposite_span: false,
        };
        let next = WayChainSegment {
            segment_id: 1,
            road: RoadFeatureBuilder::new(402)
                .highway("residential")
                .name("Flat Rock Road")
                .geometry(vec![(-75.2800, 40.0010), (-75.2800, 40.0020)])
                .build()
                .unwrap(),
            points: vec![
                profile_point(40.0010, -75.2800, 123.0),
                profile_point(40.0020, -75.2800, 129.0),
            ],
            intersection_indices: BTreeSet::new(),
            route_key: Some("flat rock road".to_string()),
            persistence_m: 6.0,
            start_boundary_reason: "route_endpoint",
            end_boundary_reason: "route_endpoint",
            source_reversed: false,
            is_opposite_span: false,
        };

        let continuation = continuation_between(0, 1, &current, &next);

        assert!(continuation.is_some());
    }

    #[test]
    fn way_chain_rejects_implausible_upward_dem_seam() {
        let current = WayChainSegment {
            segment_id: 0,
            road: RoadFeatureBuilder::new(501)
                .highway("residential")
                .name("Seam Road")
                .geometry(vec![(-75.2900, 40.0000), (-75.2900, 40.0010)])
                .build()
                .unwrap(),
            points: vec![
                profile_point(40.0000, -75.2900, 100.0),
                profile_point(40.0010, -75.2900, 110.0),
            ],
            intersection_indices: BTreeSet::new(),
            route_key: Some("seam road".to_string()),
            persistence_m: 10.0,
            start_boundary_reason: "route_endpoint",
            end_boundary_reason: "route_endpoint",
            source_reversed: false,
            is_opposite_span: false,
        };
        let next = WayChainSegment {
            segment_id: 1,
            road: RoadFeatureBuilder::new(502)
                .highway("residential")
                .name("Seam Road")
                .geometry(vec![(-75.2900, 40.0010), (-75.2900, 40.0020)])
                .build()
                .unwrap(),
            points: vec![
                profile_point(40.0010, -75.2900, 130.0),
                profile_point(40.0020, -75.2900, 145.0),
            ],
            intersection_indices: BTreeSet::new(),
            route_key: Some("seam road".to_string()),
            persistence_m: 15.0,
            start_boundary_reason: "route_endpoint",
            end_boundary_reason: "route_endpoint",
            source_reversed: false,
            is_opposite_span: false,
        };

        assert!(continuation_between(0, 1, &current, &next).is_none());
    }

    #[test]
    fn unnamed_service_does_not_bridge_launch_scope_roads() {
        let lower = RoadFeatureBuilder::new(601)
            .highway("residential")
            .name("Lower Road")
            .geometry(vec![(-75.3000, 40.0000), (-75.3000, 40.0010)])
            .build()
            .unwrap();
        let service = RoadFeatureBuilder::new(602)
            .highway("service")
            .geometry(vec![(-75.3000, 40.0010), (-75.2996, 40.0010)])
            .build()
            .unwrap();
        let upper = RoadFeatureBuilder::new(603)
            .highway("residential")
            .name("Upper Road")
            .geometry(vec![(-75.2996, 40.0010), (-75.2996, 40.0020)])
            .build()
            .unwrap();
        let profiles = HashMap::from([
            (
                601,
                profile(
                    601,
                    vec![
                        profile_point(40.0000, -75.3000, 80.0),
                        profile_point(40.0010, -75.3000, 96.0),
                    ],
                ),
            ),
            (
                602,
                profile(
                    602,
                    vec![
                        profile_point(40.0010, -75.3000, 96.0),
                        profile_point(40.0010, -75.2996, 96.2),
                    ],
                ),
            ),
            (
                603,
                profile(
                    603,
                    vec![
                        profile_point(40.0010, -75.2996, 96.2),
                        profile_point(40.0020, -75.2996, 114.0),
                    ],
                ),
            ),
        ]);

        let report = compile_canon_candidates(
            &[lower, service, upper],
            &profiles,
            &CanonCompileConfig::default(),
        );

        assert!(report
            .candidates
            .iter()
            .all(|candidate| !candidate.osm_way_refs.contains(&602)));
    }

    #[test]
    fn sql_insert_targets_canon_schema() {
        let road = RoadFeatureBuilder::new(7)
            .highway("residential")
            .name("Test Hill")
            .geometry(vec![(-75.0, 40.0), (-75.0, 40.01)])
            .build()
            .unwrap();
        let profile = LocalElevationProfile {
            osm_way_id: 7,
            points: vec![
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.0,
                    lon: -75.0,
                    elev_m: 10.0,
                },
                CanonProfilePoint {
                    dist_m: 0.0,
                    lat: 40.01,
                    lon: -75.0,
                    elev_m: 70.0,
                },
            ],
        };
        let report = compile_canon_candidates(
            &[road],
            &HashMap::from([(7, profile)]),
            &CanonCompileConfig::default(),
        );
        let sql = candidate_insert_sql(&report.candidates[0]);
        assert!(sql.contains("INSERT INTO public.canon_climbs"));
        assert!(sql.contains("INSERT INTO public.canon_corridor_cells"));
        assert!(sql.contains("DELETE FROM public.canon_corridor_cells"));
        assert!(sql.contains("RETURNING canon_climb_id"));
        assert!(sql.contains("CROSS JOIN deletion_barrier"));
        assert!(sql.contains("ST_Buffer"));
        assert!(sql.contains("::geography"));
        assert!(sql.contains("ST_GeomFromText"));
        assert!(sql.contains("ON CONFLICT (candidate_fingerprint) DO UPDATE"));
    }

    fn profile(osm_way_id: i64, mut points: Vec<CanonProfilePoint>) -> LocalElevationProfile {
        rebase_distances(&mut points);
        LocalElevationProfile { osm_way_id, points }
    }

    fn test_ratified_decision(
        decision_id: &str,
        osm_way_refs: Vec<i64>,
        start: (f64, f64),
        end: (f64, f64),
        replaces_candidate_fingerprint: String,
    ) -> RatifiedBoundaryDecision {
        RatifiedBoundaryDecision {
            decision_id: decision_id.to_string(),
            display_name: "Ratified Test Hill".to_string(),
            route_name: Some("Ratified Test Hill".to_string()),
            osm_way_refs,
            start: RatifiedBoundaryAnchor {
                label: "start".to_string(),
                osm_node_id: None,
                lat: start.0,
                lon: start.1,
                max_offset_m: 2.0,
                exact_gate: None,
            },
            end: RatifiedBoundaryAnchor {
                label: "end".to_string(),
                osm_node_id: None,
                lat: end.0,
                lon: end.1,
                max_offset_m: 2.0,
                exact_gate: None,
            },
            replaces_candidate_fingerprint,
            legacy_candidate_fingerprints: Vec::new(),
            evidence: RatifiedBoundaryEvidence {
                requirement: RatifiedBoundaryApprovalEvidence {
                    approved_at: "2026-07-19".to_string(),
                    approved_by: "Tim".to_string(),
                    source: "test".to_string(),
                },
                geometry_translation: RatifiedBoundaryGeometryEvidence {
                    resolved_at: "2026-07-19".to_string(),
                    resolved_by: "Codex".to_string(),
                    source: "test".to_string(),
                },
                visual_approval: None,
            },
            finish_decision: None,
        }
    }

    fn ratified_fixture_roads() -> Vec<RoadFeature> {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../resources/philly_ratified_boundary_osm_ways_v1.json"
        ))
        .unwrap();
        fixture["roads"]
            .as_array()
            .unwrap()
            .iter()
            .map(|value| {
                let geometry = value["geometry"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|coordinate| {
                        let pair = coordinate.as_array().unwrap();
                        (pair[0].as_f64().unwrap(), pair[1].as_f64().unwrap())
                    })
                    .collect::<Vec<_>>();
                let osm_node_ids = value["osm_node_ids"]
                    .as_array()
                    .unwrap()
                    .iter()
                    .map(|node_id| node_id.as_i64().unwrap())
                    .collect::<Vec<_>>();
                let mut builder = RoadFeatureBuilder::new(value["osm_way_id"].as_i64().unwrap())
                    .highway(value["road_class"].as_str().unwrap())
                    .geometry(geometry)
                    .osm_node_ids(osm_node_ids);
                if let Some(name) = value["name"].as_str() {
                    builder = builder.name(name);
                }
                builder.build().unwrap()
            })
            .collect()
    }

    fn profile_point(lat: f64, lon: f64, elev_m: f64) -> CanonProfilePoint {
        CanonProfilePoint {
            dist_m: 0.0,
            lat,
            lon,
            elev_m,
        }
    }

    fn parse_gate_wkt(wkt: &str) -> ((f64, f64), (f64, f64)) {
        let inner = wkt.trim_start_matches("LINESTRING(").trim_end_matches(')');
        let mut pairs = inner.split(", ").map(|token| {
            let mut parts = token.split_whitespace();
            let lon: f64 = parts.next().unwrap().parse().unwrap();
            let lat: f64 = parts.next().unwrap().parse().unwrap();
            (lon, lat)
        });
        (pairs.next().unwrap(), pairs.next().unwrap())
    }

    #[test]
    fn gate_arms_survive_submeter_and_duplicate_boundary_vertices() {
        let start_cases = [
            (
                "submeter-start",
                vec![
                    profile_point(40.0000000, -75.25, 20.0),
                    profile_point(40.0000045, -75.25, 20.1),
                    profile_point(40.0010000, -75.25, 45.0),
                ],
            ),
            (
                "duplicate-start",
                vec![
                    profile_point(40.0000000, -75.25, 20.0),
                    profile_point(40.0000000, -75.25, 20.0),
                    profile_point(40.0010000, -75.25, 45.0),
                ],
            ),
        ];
        for (label, points) in start_cases {
            for half_width_m in [25.0, 40.0] {
                assert_gate_has_configured_arms(label, &points, 0, half_width_m);
            }
        }

        let end_cases = [
            (
                "submeter-end",
                vec![
                    profile_point(40.0000000, -75.25, 20.0),
                    profile_point(40.0009955, -75.25, 44.9),
                    profile_point(40.0010000, -75.25, 45.0),
                ],
            ),
            (
                "duplicate-end",
                vec![
                    profile_point(40.0000000, -75.25, 20.0),
                    profile_point(40.0010000, -75.25, 45.0),
                    profile_point(40.0010000, -75.25, 45.0),
                ],
            ),
        ];
        for (label, points) in end_cases {
            for half_width_m in [25.0, 40.0] {
                assert_gate_has_configured_arms(label, &points, points.len() - 1, half_width_m);
            }
        }
    }

    fn assert_gate_has_configured_arms(
        label: &str,
        points: &[CanonProfilePoint],
        index: usize,
        half_width_m: f64,
    ) {
        let wkt = gate_wkt(points, index, half_width_m);
        let (a, b) = parse_gate_wkt(&wkt);
        let boundary = (points[index].lon, points[index].lat);
        for endpoint in [a, b] {
            let arm_m = haversine_m(boundary.1, boundary.0, endpoint.1, endpoint.0);
            assert!(
                (arm_m - half_width_m).abs() < 0.5,
                "{label}: gate arm {arm_m}m must match configured {half_width_m}m"
            );
        }
        let midpoint = ((a.0 + b.0) / 2.0, (a.1 + b.1) / 2.0);
        assert!(
            haversine_m(boundary.1, boundary.0, midpoint.1, midpoint.0) < 0.01,
            "{label}: gate must remain centered on the boundary"
        );
    }

    #[test]
    fn gate_direction_is_unchanged_for_meter_scale_boundary_spacing() {
        let points = vec![
            profile_point(40.0000, -75.25, 20.0),
            profile_point(40.0001, -75.25, 22.0),
            profile_point(40.0010, -75.25, 45.0),
        ];
        let wkt = gate_wkt(&points, 0, 25.0);
        let (a, b) = parse_gate_wkt(&wkt);
        assert!(
            (a.1 - 40.0).abs() < 1e-6 && (b.1 - 40.0).abs() < 1e-6,
            "north-south road must keep its east-west gate direction"
        );
        let arm_m = haversine_m(40.0, -75.25, a.1, a.0);
        assert!((arm_m - 25.0).abs() < 0.5);
    }

    fn centerline_start(candidate: &CanonCandidate) -> (f64, f64) {
        centerline_endpoint(candidate, true)
    }

    fn centerline_end(candidate: &CanonCandidate) -> (f64, f64) {
        centerline_endpoint(candidate, false)
    }

    fn centerline_endpoint(candidate: &CanonCandidate, start: bool) -> (f64, f64) {
        let body = candidate
            .centerline_wkt
            .strip_prefix("LINESTRING(")
            .and_then(|value| value.strip_suffix(')'))
            .unwrap();
        let coords = body.split(", ").collect::<Vec<_>>();
        let coord = if start {
            coords.first().unwrap()
        } else {
            coords.last().unwrap()
        };
        let pair = coord
            .split_whitespace()
            .map(|value| value.parse::<f64>().unwrap())
            .collect::<Vec<_>>();
        (pair[0], pair[1])
    }

    fn assert_coord_close(actual: (f64, f64), expected: (f64, f64)) {
        assert!((actual.0 - expected.0).abs() < 0.00002, "{actual:?}");
        assert!((actual.1 - expected.1).abs() < 0.00002, "{actual:?}");
    }

    fn decision_count(labels: &[ReviewLabel], decision: &str) -> usize {
        labels
            .iter()
            .filter(|label| label.decision == decision)
            .count()
    }

    fn decision_scores(scored: &[(f64, &ReviewLabel)], decision: &str) -> Vec<f64> {
        scored
            .iter()
            .filter_map(|(score, label)| {
                if label.decision == decision {
                    Some(*score)
                } else {
                    None
                }
            })
            .collect()
    }

    fn pairwise_auc(positive: &[f64], negative: &[f64]) -> f64 {
        let mut wins = 0.0;
        let mut total = 0.0;
        for pos in positive {
            for neg in negative {
                total += 1.0;
                if pos > neg {
                    wins += 1.0;
                } else if (pos - neg).abs() < f64::EPSILON {
                    wins += 0.5;
                }
            }
        }
        wins / total
    }

    fn median(mut values: Vec<f64>) -> f64 {
        values.sort_by(|left, right| left.partial_cmp(right).unwrap_or(std::cmp::Ordering::Equal));
        let mid = values.len() / 2;
        if values.len() % 2 == 0 {
            (values[mid - 1] + values[mid]) / 2.0
        } else {
            values[mid]
        }
    }

    fn capture_tolerance_fixture_report(
        overrides: &CanonCaptureToleranceOverrideSet,
    ) -> CanonCompileReport {
        let road = RoadFeatureBuilder::new(9901)
            .highway("residential")
            .name("Capture Fixture Road")
            .geometry(vec![(-75.25, 40.0000), (-75.25, 40.0040)])
            .build()
            .unwrap();
        let profile = LocalElevationProfile {
            osm_way_id: road.osm_way_id,
            points: vec![
                profile_point(40.0000, -75.25, 20.0),
                profile_point(40.0010, -75.25, 35.0),
                profile_point(40.0020, -75.25, 50.0),
                profile_point(40.0030, -75.25, 65.0),
                profile_point(40.0040, -75.25, 80.0),
            ],
        };
        let mut report = compile_canon_candidates(
            &[road],
            &HashMap::from([(profile.osm_way_id, profile)]),
            &CanonCompileConfig::default(),
        );
        let seed = report.candidates.pop().unwrap();
        report.candidates = overrides
            .overrides
            .iter()
            .map(|entry| {
                let mut candidate = seed.clone();
                candidate.candidate_fingerprint = entry.candidate_fingerprint.clone();
                candidate.display_name = entry.display_name.clone();
                candidate.route_name = Some(entry.display_name.clone());
                candidate
            })
            .collect();
        report.stats.emitted_candidates = report.candidates.len();
        report.ratified_boundaries = Some(RatifiedBoundaryRunMetadata {
            mode: "applied".to_string(),
            model: Some(RATIFIED_BOUNDARY_MODEL.to_string()),
            registry: None,
            road_graph: None,
            profile_bundles: Vec::new(),
            applied_decisions: 1,
            retained_decisions: 1,
            embedded_profiles_added: 0,
            embedded_profiles_replaced: 0,
            custom_profiles_added: 0,
            custom_profiles_replaced: 0,
        });
        report
    }

    fn gate_half_extent_m(wkt: &str) -> f64 {
        let (a, b) = parse_gate_wkt(wkt);
        let midpoint = ((a.0 + b.0) / 2.0, (a.1 + b.1) / 2.0);
        (haversine_m(midpoint.1, midpoint.0, a.1, a.0)
            + haversine_m(midpoint.1, midpoint.0, b.1, b.0))
            / 2.0
    }

    fn gate_midpoint_and_direction(wkt: &str) -> ((f64, f64), (f64, f64)) {
        let (a, b) = parse_gate_wkt(wkt);
        (
            ((a.0 + b.0) / 2.0, (a.1 + b.1) / 2.0),
            (b.0 - a.0, b.1 - a.1),
        )
    }

    fn assert_gate_midpoint_and_orientation_unchanged(before: &str, after: &str) {
        let (before_midpoint, before_direction) = gate_midpoint_and_direction(before);
        let (after_midpoint, after_direction) = gate_midpoint_and_direction(after);
        assert!(
            haversine_m(
                before_midpoint.1,
                before_midpoint.0,
                after_midpoint.1,
                after_midpoint.0,
            ) < 0.01
        );
        let cross = before_direction.0 * after_direction.1 - before_direction.1 * after_direction.0;
        let dot = before_direction.0 * after_direction.0 + before_direction.1 * after_direction.1;
        assert!(cross.abs() < 1e-12, "gate orientation rotated");
        assert!(dot > 0.0, "gate endpoint direction reversed");
    }

    #[test]
    fn ratified_capture_tolerances_are_independent_minor_revisions() {
        let overrides = capture_tolerance_overrides_from_json(
            serde_json::from_str(include_str!(
                "../../resources/philly_capture_tolerance_overrides_v1.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let report = capture_tolerance_fixture_report(&overrides);
        let before = report.candidates.clone();
        let resource = RatifiedBoundaryResourceDigest {
            source: "embedded:philly_capture_tolerance_overrides_v1.json".to_string(),
            blake3: "a".repeat(64),
        };

        let applied = apply_capture_tolerance_overrides(report, &overrides, &resource).unwrap();

        assert_eq!(applied.candidates.len(), 4);
        let metadata = applied.capture_tolerance_overrides.as_ref().unwrap();
        assert_eq!(metadata.expected, 4);
        assert_eq!(metadata.applied, 4);
        assert_eq!(metadata.retained, 4);
        for (baseline, revised) in before.iter().zip(&applied.candidates) {
            let entry = overrides
                .overrides
                .iter()
                .find(|entry| entry.candidate_fingerprint == revised.candidate_fingerprint)
                .unwrap();
            assert_eq!(
                baseline.candidate_fingerprint,
                revised.candidate_fingerprint
            );
            assert_eq!(
                baseline.legacy_candidate_fingerprints,
                revised.legacy_candidate_fingerprints
            );
            assert_eq!(baseline.centerline_polyline, revised.centerline_polyline);
            assert_eq!(baseline.centerline_wkt, revised.centerline_wkt);
            assert_eq!(baseline.canonical_profile, revised.canonical_profile);
            assert_eq!(baseline.length_m, revised.length_m);
            assert_eq!(baseline.vert_m, revised.vert_m);
            assert_eq!(baseline.avg_gradient_pct, revised.avg_gradient_pct);
            assert_eq!(baseline.max_gradient_pct, revised.max_gradient_pct);
            assert_eq!(baseline.osm_way_refs, revised.osm_way_refs);
            assert_gate_midpoint_and_orientation_unchanged(
                &baseline.gate_start_wkt,
                &revised.gate_start_wkt,
            );
            assert_gate_midpoint_and_orientation_unchanged(
                &baseline.gate_end_wkt,
                &revised.gate_end_wkt,
            );
            assert!(
                (gate_half_extent_m(&revised.gate_start_wkt) - entry.gate_start_half_extent_m)
                    .abs()
                    < 0.5
            );
            assert!(
                (gate_half_extent_m(&revised.gate_end_wkt) - entry.gate_end_half_extent_m).abs()
                    < 0.5
            );
            assert_eq!(revised.corridor_half_width_m, entry.corridor_half_width_m);
            let start_changed = entry.gate_start_half_extent_m
                != entry.prior_geometry_policy.gate_start_half_extent_m;
            let end_changed =
                entry.gate_end_half_extent_m != entry.prior_geometry_policy.gate_end_half_extent_m;
            let corridor_changed =
                entry.corridor_half_width_m != entry.prior_geometry_policy.corridor_half_width_m;
            assert_eq!(
                baseline.gate_start_wkt == revised.gate_start_wkt,
                !start_changed,
                "{} start-gate byte continuity drifted",
                entry.display_name
            );
            assert_eq!(
                baseline.gate_end_wkt == revised.gate_end_wkt,
                !end_changed,
                "{} finish-gate byte continuity drifted",
                entry.display_name
            );
            if corridor_changed {
                assert_ne!(
                    baseline.corridor_wkt, revised.corridor_wkt,
                    "{} corridor geometry did not change",
                    entry.display_name
                );
            } else {
                assert_eq!(
                    baseline.corridor_wkt, revised.corridor_wkt,
                    "{} corridor byte continuity drifted",
                    entry.display_name
                );
                assert_eq!(
                    baseline.corridor_cells, revised.corridor_cells,
                    "{} corridor-cell continuity drifted",
                    entry.display_name
                );
            }
            assert_eq!(
                revised.provenance["capture_tolerance_revision"]["registry"]["blake3"],
                json!(resource.blake3)
            );
            assert_eq!(
                revised.provenance["capture_tolerance_revision"]["record_continuity_policy"],
                json!("carry_forward_same_canon_id_and_record_board")
            );
        }
    }

    #[test]
    fn capture_tolerance_registry_fails_closed_on_stale_or_duplicate_targets() {
        let overrides = capture_tolerance_overrides_from_json(
            serde_json::from_str(include_str!(
                "../../resources/philly_capture_tolerance_overrides_v1.json"
            ))
            .unwrap(),
        )
        .unwrap();
        let resource = RatifiedBoundaryResourceDigest {
            source: "test".to_string(),
            blake3: "b".repeat(64),
        };

        let mut stale_report = capture_tolerance_fixture_report(&overrides);
        stale_report.candidates.pop();
        assert!(
            apply_capture_tolerance_overrides(stale_report, &overrides, &resource)
                .unwrap_err()
                .contains("expected exactly one target")
        );

        let mut duplicate_report = capture_tolerance_fixture_report(&overrides);
        duplicate_report
            .candidates
            .push(duplicate_report.candidates[0].clone());
        assert!(
            apply_capture_tolerance_overrides(duplicate_report, &overrides, &resource)
                .unwrap_err()
                .contains("expected exactly one target")
        );

        let mut unapplied_report = capture_tolerance_fixture_report(&overrides);
        unapplied_report.ratified_boundaries = None;
        assert!(
            apply_capture_tolerance_overrides(unapplied_report, &overrides, &resource)
                .unwrap_err()
                .contains("require applied ratified boundaries")
        );

        let mut unknown_field_value: Value = serde_json::from_str(include_str!(
            "../../resources/philly_capture_tolerance_overrides_v1.json"
        ))
        .unwrap();
        unknown_field_value["overrides"][0]["gate_start_half_width_typo"] = json!(30.0);
        assert!(capture_tolerance_overrides_from_json(unknown_field_value)
            .unwrap_err()
            .contains("unknown field"));
    }
}
