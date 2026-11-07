//! Road feature definitions for geographic attribution.

use std::collections::HashSet;

/// Road classification based on OSM highway tag.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RoadClass {
    /// Major roads: primary, trunk
    Primary,
    /// Secondary roads
    Secondary,
    /// Tertiary roads
    Tertiary,
    /// Residential streets
    Residential,
    /// Unclassified roads
    Unclassified,
    /// Dedicated cycling infrastructure
    Cycleway,
    /// Paths and trails
    Path,
    /// Unpaved tracks
    Track,
    /// Service roads
    Service,
}

impl RoadClass {
    /// Parse from OSM highway tag value.
    pub fn from_osm_highway(highway: &str) -> Option<Self> {
        match highway {
            "primary" | "trunk" | "primary_link" | "trunk_link" => Some(Self::Primary),
            "secondary" | "secondary_link" => Some(Self::Secondary),
            "tertiary" | "tertiary_link" => Some(Self::Tertiary),
            "residential" | "living_street" => Some(Self::Residential),
            "unclassified" => Some(Self::Unclassified),
            "cycleway" => Some(Self::Cycleway),
            "path" | "footway" | "bridleway" => Some(Self::Path),
            "track" => Some(Self::Track),
            "service" => Some(Self::Service),
            _ => None,
        }
    }

    /// Check if this road class is suitable for cycling.
    pub fn is_cyclable(&self) -> bool {
        matches!(
            self,
            Self::Primary
                | Self::Secondary
                | Self::Tertiary
                | Self::Residential
                | Self::Unclassified
                | Self::Cycleway
                | Self::Path
                | Self::Track
        )
    }
}

/// A road segment extracted from OSM.
#[derive(Debug, Clone)]
pub struct RoadFeature {
    /// OSM way ID (unique identifier).
    pub osm_way_id: i64,

    /// Raw OSM highway tag used to build the road class.
    pub highway_tag: Option<String>,

    /// Road name (if available).
    pub name: Option<String>,

    /// Road classification.
    pub road_class: RoadClass,

    /// Grade as decimal (0.12 = 12%). None if unknown.
    pub grade: Option<f32>,

    /// Length in meters.
    pub length_m: f32,

    /// Geometry as coordinate pairs [(lon, lat), ...].
    pub geometry: Vec<(f64, f64)>,

    /// OSM node IDs aligned with `geometry`. Empty for synthetic features.
    pub osm_node_ids: Vec<i64>,

    /// H3 cell indexes that this road passes through.
    pub h3_cells: HashSet<String>,

    /// Whether this road has dedicated cycling infrastructure.
    pub has_bike_infra: bool,

    /// Surface type (if known).
    pub surface: Option<String>,
}

impl RoadFeature {
    /// Create a new road feature.
    pub fn new(osm_way_id: i64, road_class: RoadClass) -> Self {
        Self {
            osm_way_id,
            highway_tag: None,
            name: None,
            road_class,
            grade: None,
            length_m: 0.0,
            geometry: Vec::new(),
            osm_node_ids: Vec::new(),
            h3_cells: HashSet::new(),
            has_bike_infra: false,
            surface: None,
        }
    }

    /// Check if this road is a potential climb (has grade or named).
    pub fn is_climb_candidate(&self) -> bool {
        // Has known grade >= 3%
        if let Some(grade) = self.grade {
            if grade >= 0.03 {
                return true;
            }
        }

        // Has a name (named roads are more likely to be significant climbs)
        self.name.is_some()
    }

    /// Calculate the number of H3 cells this road covers.
    pub fn cell_count(&self) -> usize {
        self.h3_cells.len()
    }
}

/// Builder for constructing RoadFeature from OSM data.
#[derive(Default)]
pub struct RoadFeatureBuilder {
    osm_way_id: i64,
    name: Option<String>,
    highway: Option<String>,
    incline: Option<String>,
    surface: Option<String>,
    cycleway: Option<String>,
    geometry: Vec<(f64, f64)>,
    osm_node_ids: Vec<i64>,
}

impl RoadFeatureBuilder {
    pub fn new(osm_way_id: i64) -> Self {
        Self {
            osm_way_id,
            ..Default::default()
        }
    }

    pub fn name(mut self, name: impl Into<String>) -> Self {
        self.name = Some(name.into());
        self
    }

    pub fn highway(mut self, highway: impl Into<String>) -> Self {
        self.highway = Some(highway.into());
        self
    }

    pub fn incline(mut self, incline: impl Into<String>) -> Self {
        self.incline = Some(incline.into());
        self
    }

    pub fn surface(mut self, surface: impl Into<String>) -> Self {
        self.surface = Some(surface.into());
        self
    }

    pub fn cycleway(mut self, cycleway: impl Into<String>) -> Self {
        self.cycleway = Some(cycleway.into());
        self
    }

    pub fn geometry(mut self, coords: Vec<(f64, f64)>) -> Self {
        self.geometry = coords;
        self
    }

    pub fn osm_node_ids(mut self, node_ids: Vec<i64>) -> Self {
        self.osm_node_ids = node_ids;
        self
    }

    /// Build the RoadFeature. Returns None if highway tag is missing or invalid.
    pub fn build(self) -> Option<RoadFeature> {
        let highway = self.highway?;
        let road_class = RoadClass::from_osm_highway(&highway)?;
        if !self.osm_node_ids.is_empty() && self.osm_node_ids.len() != self.geometry.len() {
            return None;
        }

        let mut feature = RoadFeature::new(self.osm_way_id, road_class);
        feature.highway_tag = Some(highway);
        feature.name = self.name;
        feature.surface = self.surface;
        feature.has_bike_infra = self.cycleway.is_some();
        feature.geometry = self.geometry;
        feature.osm_node_ids = self.osm_node_ids;

        // Parse grade from incline tag
        if let Some(incline) = self.incline {
            feature.grade = parse_incline(&incline);
        }

        // Calculate length
        feature.length_m = calculate_length(&feature.geometry);

        Some(feature)
    }
}

/// Parse OSM incline tag to decimal grade.
fn parse_incline(incline: &str) -> Option<f32> {
    let s = incline.trim().to_lowercase();

    // Handle percentage format: "12%", "-5%"
    if let Some(stripped) = s.strip_suffix('%') {
        return stripped.parse::<f32>().ok().map(|v| v / 100.0);
    }

    // Handle degree format: "6°"
    if let Some(stripped) = s.strip_suffix('°') {
        return stripped
            .parse::<f32>()
            .ok()
            .map(|deg| (deg.to_radians()).tan() as f32);
    }

    // Handle descriptive tags
    match s.as_str() {
        "steep" => Some(0.12),
        "moderate" => Some(0.06),
        "gentle" => Some(0.03),
        "up" => Some(0.05),
        "down" => Some(-0.05),
        _ => None,
    }
}

/// Calculate geodesic length of a coordinate sequence in meters.
fn calculate_length(coords: &[(f64, f64)]) -> f32 {
    if coords.len() < 2 {
        return 0.0;
    }

    let mut total = 0.0f64;
    for window in coords.windows(2) {
        let (lon1, lat1) = window[0];
        let (lon2, lat2) = window[1];
        total += haversine_distance(lat1, lon1, lat2, lon2);
    }

    total as f32
}

/// Haversine distance between two points in meters.
fn haversine_distance(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    const EARTH_RADIUS_M: f64 = 6_371_000.0;

    let lat1_rad = lat1.to_radians();
    let lat2_rad = lat2.to_radians();
    let dlat = (lat2 - lat1).to_radians();
    let dlon = (lon2 - lon1).to_radians();

    let a =
        (dlat / 2.0).sin().powi(2) + lat1_rad.cos() * lat2_rad.cos() * (dlon / 2.0).sin().powi(2);
    let c = 2.0 * a.sqrt().asin();

    EARTH_RADIUS_M * c
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_road_class_from_osm() {
        assert_eq!(
            RoadClass::from_osm_highway("primary"),
            Some(RoadClass::Primary)
        );
        assert_eq!(
            RoadClass::from_osm_highway("cycleway"),
            Some(RoadClass::Cycleway)
        );
        assert_eq!(RoadClass::from_osm_highway("motorway"), None);
    }

    #[test]
    fn test_parse_incline_percentage() {
        assert!((parse_incline("12%").unwrap() - 0.12).abs() < 0.001);
        assert!((parse_incline("-5%").unwrap() - (-0.05)).abs() < 0.001);
    }

    #[test]
    fn test_parse_incline_descriptive() {
        assert_eq!(parse_incline("steep"), Some(0.12));
        assert_eq!(parse_incline("gentle"), Some(0.03));
    }

    #[test]
    fn test_haversine_distance() {
        // NYC to LA is roughly 3940 km
        let dist = haversine_distance(40.7128, -74.0060, 34.0522, -118.2437);
        assert!(dist > 3_900_000.0 && dist < 4_000_000.0);
    }

    #[test]
    fn test_road_feature_builder() {
        let feature = RoadFeatureBuilder::new(123456)
            .name("Manayunk Wall")
            .highway("residential")
            .incline("17%")
            .geometry(vec![(-75.21, 40.03), (-75.22, 40.04)])
            .osm_node_ids(vec![11, 12])
            .build();

        let feature = feature.expect("Should build");
        assert_eq!(feature.name, Some("Manayunk Wall".to_string()));
        assert_eq!(feature.road_class, RoadClass::Residential);
        assert!((feature.grade.unwrap() - 0.17).abs() < 0.001);
        assert!(feature.length_m > 0.0);
        assert_eq!(feature.osm_node_ids, vec![11, 12]);

        assert!(RoadFeatureBuilder::new(123457)
            .highway("residential")
            .geometry(vec![(-75.21, 40.03), (-75.22, 40.04)])
            .osm_node_ids(vec![11])
            .build()
            .is_none());
    }
}
