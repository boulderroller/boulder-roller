//! Geographic feature attribution for tile-based attestation.
//!
//! This module provides:
//! - OSM data parsing and preprocessing (`osm`)
//! - Road feature extraction and storage (`roads`)
//! - Tile-to-feature lookup for ride attribution (`lookup`)
//!
//! ## Architecture
//!
//! ```text
//! OSM PBF file ──▶ osm::parse() ──▶ RoadFeature[] ──▶ Database
//!                                                        │
//! Ride tiles ──▶ lookup::attribute_tiles() ◀────────────┘
//!                       │
//!                       ▼
//!               TileAttribution (e.g., "85% on Manayunk Wall")
//! ```
//!
//! ## Usage
//!
//! **Preprocessing (one-time batch job):**
//! ```ignore
//! use workout_parse::geo_features::osm::OsmParser;
//! use workout_parse::geo_features::roads::RoadFeature;
//!
//! let parser = OsmParser::new("philadelphia.osm.pbf")?;
//! let roads: Vec<RoadFeature> = parser.extract_roads()?;
//! // Insert into database...
//! ```
//!
//! **Ride attribution (per-ride):**
//! ```ignore
//! use workout_parse::geo_features::lookup::TileLookup;
//!
//! let lookup = TileLookup::new(db_pool);
//! let attribution = lookup.attribute_tiles(&ride_tiles)?;
//! // attribution.features = [("Manayunk Wall", 0.85), ...]
//! ```

pub mod lookup;
pub mod roads;

// OSM parsing requires osmpbf crate - enabled via feature flag
#[cfg(feature = "osm")]
pub mod osm;

pub use lookup::{TileAttribution, TileLookup};
pub use roads::{RoadClass, RoadFeature, RoadFeatureBuilder};

#[cfg(feature = "osm")]
pub use osm::{OsmError, OsmParser, OsmParserConfig, PreprocessStats, PreprocessedRoads};
