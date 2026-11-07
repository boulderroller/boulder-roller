//! OSM PBF file parsing for road feature extraction.
//!
//! This module provides tools to extract cycling-relevant road features
//! from OpenStreetMap PBF files.

use std::collections::{HashMap, HashSet};
use std::path::Path;

use h3o::{LatLng, Resolution};
use osmpbf::{Element, ElementReader};

use super::roads::{RoadClass, RoadFeature, RoadFeatureBuilder};

/// Configuration for OSM parsing.
#[derive(Debug, Clone)]
pub struct OsmParserConfig {
    /// H3 resolution for tile generation.
    pub h3_resolution: Resolution,

    /// Minimum road length to include (meters).
    pub min_length_m: f32,

    /// Only include roads with names.
    pub require_name: bool,

    /// Only include roads with known grade.
    pub require_grade: bool,

    /// Road classes to include.
    pub include_classes: HashSet<RoadClass>,
}

impl Default for OsmParserConfig {
    fn default() -> Self {
        let mut include_classes = HashSet::new();
        include_classes.insert(RoadClass::Primary);
        include_classes.insert(RoadClass::Secondary);
        include_classes.insert(RoadClass::Tertiary);
        include_classes.insert(RoadClass::Residential);
        include_classes.insert(RoadClass::Unclassified);
        include_classes.insert(RoadClass::Cycleway);
        include_classes.insert(RoadClass::Path);
        include_classes.insert(RoadClass::Track);

        Self {
            h3_resolution: Resolution::Ten,
            min_length_m: 50.0,
            require_name: false,
            require_grade: false,
            include_classes,
        }
    }
}

/// Parser for OSM PBF files.
pub struct OsmParser {
    config: OsmParserConfig,
}

impl OsmParser {
    /// Create a new parser with default configuration.
    pub fn new() -> Self {
        Self {
            config: OsmParserConfig::default(),
        }
    }

    /// Create a parser with custom configuration.
    pub fn with_config(config: OsmParserConfig) -> Self {
        Self { config }
    }

    /// Extract road features from a PBF file.
    ///
    /// This is a two-pass algorithm:
    /// 1. First pass: collect all node coordinates
    /// 2. Second pass: build road features from ways
    pub fn extract_roads<P: AsRef<Path>>(&self, pbf_path: P) -> Result<Vec<RoadFeature>, OsmError> {
        let path = pbf_path.as_ref();

        if !path.exists() {
            return Err(OsmError::FileNotFound(path.display().to_string()));
        }

        // First pass: collect node coordinates
        eprintln!("Pass 1: Collecting node coordinates...");
        let node_coords = self.collect_nodes(path)?;
        eprintln!("  Found {} nodes", node_coords.len());

        // Second pass: build road features
        eprintln!("Pass 2: Extracting road features...");
        let roads = self.build_roads(path, &node_coords)?;
        eprintln!("  Found {} roads", roads.len());

        Ok(roads)
    }

    /// First pass: collect all node coordinates into a map.
    fn collect_nodes<P: AsRef<Path>>(
        &self,
        pbf_path: P,
    ) -> Result<HashMap<i64, (f64, f64)>, OsmError> {
        let reader =
            ElementReader::from_path(pbf_path).map_err(|e| OsmError::ParseError(e.to_string()))?;

        let mut nodes: HashMap<i64, (f64, f64)> = HashMap::new();

        reader
            .for_each(|element| {
                if let Element::DenseNode(node) = element {
                    nodes.insert(node.id, (node.lon(), node.lat()));
                } else if let Element::Node(node) = element {
                    nodes.insert(node.id(), (node.lon(), node.lat()));
                }
            })
            .map_err(|e| OsmError::ParseError(e.to_string()))?;

        Ok(nodes)
    }

    /// Second pass: build road features from ways.
    fn build_roads<P: AsRef<Path>>(
        &self,
        pbf_path: P,
        node_coords: &HashMap<i64, (f64, f64)>,
    ) -> Result<Vec<RoadFeature>, OsmError> {
        let reader =
            ElementReader::from_path(pbf_path).map_err(|e| OsmError::ParseError(e.to_string()))?;

        let mut roads: Vec<RoadFeature> = Vec::new();

        reader
            .for_each(|element| {
                if let Element::Way(way) = element {
                    if let Some(road) = self.process_way(&way, node_coords) {
                        roads.push(road);
                    }
                }
            })
            .map_err(|e| OsmError::ParseError(e.to_string()))?;

        Ok(roads)
    }

    /// Process a single OSM way into a RoadFeature (if applicable).
    fn process_way(
        &self,
        way: &osmpbf::Way,
        node_coords: &HashMap<i64, (f64, f64)>,
    ) -> Option<RoadFeature> {
        let tags: HashMap<&str, &str> = way.tags().collect();

        // Must have highway tag
        let highway = tags.get("highway")?;

        // Check if road class is included
        let road_class = RoadClass::from_osm_highway(highway)?;
        if !self.config.include_classes.contains(&road_class) {
            return None;
        }

        // Keep node IDs aligned with geometry so ratified boundaries can prove
        // that named OSM-node anchors belong to the selected road graph.
        let geometry_nodes: Vec<(i64, (f64, f64))> = way
            .refs()
            .filter_map(|node_id| {
                node_coords
                    .get(&node_id)
                    .copied()
                    .map(|coordinate| (node_id, coordinate))
            })
            .collect();

        if geometry_nodes.len() < 2 {
            return None;
        }
        let node_ids = geometry_nodes.iter().map(|(node_id, _)| *node_id).collect();
        let geometry = geometry_nodes
            .into_iter()
            .map(|(_, coordinate)| coordinate)
            .collect();

        // Build the feature
        let mut builder = RoadFeatureBuilder::new(way.id())
            .highway(highway.to_string())
            .geometry(geometry)
            .osm_node_ids(node_ids);

        if let Some(name) = tags.get("name") {
            builder = builder.name(name.to_string());
        }

        if let Some(incline) = tags.get("incline") {
            builder = builder.incline(incline.to_string());
        }

        if let Some(surface) = tags.get("surface") {
            builder = builder.surface(surface.to_string());
        }

        if tags.contains_key("cycleway") || tags.contains_key("bicycle") {
            builder = builder.cycleway("yes".to_string());
        }

        let mut feature = builder.build()?;

        // Apply filters
        if feature.length_m < self.config.min_length_m {
            return None;
        }

        if self.config.require_name && feature.name.is_none() {
            return None;
        }

        if self.config.require_grade && feature.grade.is_none() {
            return None;
        }

        // Generate H3 cells
        feature.h3_cells = self.geometry_to_h3_cells(&feature.geometry);

        Some(feature)
    }

    /// Convert a geometry to H3 cells.
    fn geometry_to_h3_cells(&self, coords: &[(f64, f64)]) -> HashSet<String> {
        let mut cells = HashSet::new();

        for &(lon, lat) in coords {
            if let Ok(ll) = LatLng::new(lat, lon) {
                let cell = ll.to_cell(self.config.h3_resolution);
                cells.insert(cell.to_string());
            }
        }

        cells
    }
}

impl Default for OsmParser {
    fn default() -> Self {
        Self::new()
    }
}

/// Errors that can occur during OSM parsing.
#[derive(Debug, Clone)]
pub enum OsmError {
    FileNotFound(String),
    ParseError(String),
    IoError(String),
}

impl std::fmt::Display for OsmError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::FileNotFound(path) => write!(f, "OSM file not found: {}", path),
            Self::ParseError(msg) => write!(f, "OSM parse error: {}", msg),
            Self::IoError(msg) => write!(f, "IO error: {}", msg),
        }
    }
}

impl std::error::Error for OsmError {}

/// Output format for preprocessed road data.
#[derive(Debug, Clone)]
#[cfg(feature = "osm")]
pub struct PreprocessedRoads {
    /// All road features.
    pub roads: Vec<RoadFeature>,

    /// Tile to road name mapping for quick lookup.
    pub tile_to_roads: HashMap<String, Vec<String>>,

    /// Statistics.
    pub stats: PreprocessStats,
}

#[derive(Debug, Clone, Default)]
#[cfg(feature = "osm")]
pub struct PreprocessStats {
    pub total_roads: usize,
    pub named_roads: usize,
    pub roads_with_grade: usize,
    pub total_tiles: usize,
    pub avg_tiles_per_road: f32,
}

#[cfg(feature = "osm")]
impl PreprocessedRoads {
    /// Build from a list of road features.
    pub fn from_roads(roads: Vec<RoadFeature>) -> Self {
        let mut tile_to_roads: HashMap<String, Vec<String>> = HashMap::new();
        let mut stats = PreprocessStats::default();

        stats.total_roads = roads.len();

        for road in &roads {
            if road.name.is_some() {
                stats.named_roads += 1;
            }
            if road.grade.is_some() {
                stats.roads_with_grade += 1;
            }

            // Build tile mapping
            if let Some(ref name) = road.name {
                for tile_id in &road.h3_cells {
                    tile_to_roads
                        .entry(tile_id.clone())
                        .or_default()
                        .push(name.clone());
                }
            }
        }

        stats.total_tiles = tile_to_roads.len();
        stats.avg_tiles_per_road = if stats.total_roads > 0 {
            roads.iter().map(|r| r.h3_cells.len()).sum::<usize>() as f32 / stats.total_roads as f32
        } else {
            0.0
        };

        Self {
            roads,
            tile_to_roads,
            stats,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parser_config_default() {
        let config = OsmParserConfig::default();
        assert_eq!(config.h3_resolution, Resolution::Ten);
        assert!(config.include_classes.contains(&RoadClass::Residential));
        assert!(!config.require_name);
    }

    #[test]
    fn test_geometry_to_h3() {
        let parser = OsmParser::new();
        let coords = vec![
            (-75.16, 39.95), // Philly
            (-75.17, 39.96),
        ];

        let cells = parser.geometry_to_h3_cells(&coords);
        assert!(!cells.is_empty());

        // All cells should be resolution 10
        for cell in &cells {
            assert!(cell.starts_with("8a"), "Expected res 10, got: {}", cell);
        }
    }
}
