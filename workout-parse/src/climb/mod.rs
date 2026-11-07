//! Climb detection and signature generation.
//!
//! This module provides high-performance climb pattern detection for cycling activities.
//! It includes:
//!
//! - **Terrain Classification**: Automatic detection of terrain type for adaptive thresholds
//! - **Momentum Algorithm** (default): Physics-based accumulation model
//! - **Legacy Algorithm**: Simple gradient threshold with drop tolerance
//!
//! # Terrain-Adaptive Detection
//!
//! The detector automatically adapts to different terrain types:
//!
//! | Terrain     | Min Vert | Min Gradient | Min VAM | Example Regions        |
//! |-------------|----------|--------------|---------|------------------------|
//! | Flat        | 15m      | 2.0%         | 150     | Netherlands, Florida   |
//! | Rolling     | 25m      | 2.5%         | 200     | Philadelphia, UK       |
//! | Hilly       | 50m      | 4.0%         | 300     | Bay Area, Appalachians |
//! | Mountainous | 100m     | 5.0%         | 400     | Alps, Pyrenees         |
//!
//! # Example
//!
//! ```ignore
//! use workout_parse::climb::{
//!     ClimbPatternDetector, ClimbDetectorConfig,
//!     TerrainClassifier, TileSample
//! };
//!
//! // Option 1: Auto-detect terrain and adapt
//! let classifier = TerrainClassifier::default();
//! let terrain = classifier.classify(&samples).unwrap();
//! let config = ClimbDetectorConfig::for_terrain_str(terrain.class.as_str()).unwrap();
//! let detector = ClimbPatternDetector::new(config);
//!
//! // Option 2: Explicit terrain preset
//! let detector = ClimbPatternDetector::new(ClimbDetectorConfig::for_rolling());
//!
//! // Option 3: Default (hilly terrain thresholds)
//! let detector = ClimbPatternDetector::with_defaults();
//!
//! let climbs = detector.detect_all(&samples, None, Some(75.0));
//! ```

pub mod constants;
pub mod detector;
pub mod persistence;
pub mod refinement;
pub mod signature;
pub mod signature_v2;
pub mod terrain;
pub mod types;
pub mod utils;

// Re-export public API
pub use detector::ClimbPatternDetector;
pub use persistence::{detect_climbs_v2, ClimbV2, PersistencePair};
pub use refinement::{
    measure_display_segment, refine_display_bounds, satisfies_display_contract,
    BoundaryRefinementConfig, DisplayClimbContract, DisplaySegmentMetrics,
};
pub use signature::{generate_signature, ClimbSignature};
pub use signature_v2::{generate_signature_v2, MatchResult, SignatureV2};
pub use terrain::{TerrainClass, TerrainClassification, TerrainClassifier, TerrainMetrics};
pub use types::{ClimbDetectorConfig, ClimbPattern, DetectionAlgorithm, TileSample};
