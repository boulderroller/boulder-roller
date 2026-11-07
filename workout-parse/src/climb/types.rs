//! Climb detection data types.

/// Input sample for climb detection.
/// Matches the Python dict structure from tile_service.
#[derive(Debug, Clone)]
pub struct TileSample {
    /// Seconds since ride start
    pub t: i64,
    /// H3 tile index (optional)
    pub tile_id: Option<String>,
    /// Elevation in meters
    pub elevation_m: Option<f64>,
    /// Power in watts
    pub power_w: Option<u16>,
    /// Heart rate in BPM
    pub hr_bpm: Option<u8>,
    /// Latitude for distance calculation
    pub lat: Option<f64>,
    /// Longitude for distance calculation
    pub lon: Option<f64>,
}

impl TileSample {
    /// Check if this sample has valid elevation data.
    /// NaN is the V2+ parser's missing-elevation representation and must not
    /// reach detection math.
    #[inline]
    pub fn has_elevation(&self) -> bool {
        self.elevation_m.is_some_and(f64::is_finite)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_with_elevation(elevation_m: Option<f64>) -> TileSample {
        TileSample {
            t: 0,
            tile_id: None,
            elevation_m,
            power_w: None,
            hr_bpm: None,
            lat: None,
            lon: None,
        }
    }

    #[test]
    fn has_elevation_rejects_non_finite_values() {
        assert!(sample_with_elevation(Some(12.0)).has_elevation());
        assert!(sample_with_elevation(Some(0.0)).has_elevation());
        assert!(!sample_with_elevation(None).has_elevation());
        assert!(!sample_with_elevation(Some(f64::NAN)).has_elevation());
        assert!(!sample_with_elevation(Some(f64::INFINITY)).has_elevation());
    }
}

/// A detected climb pattern.
#[derive(Debug, Clone)]
pub struct ClimbPattern {
    /// Total vertical gain in meters
    pub vert_m: f64,
    /// Duration in seconds
    pub time_s: u32,
    /// Average power during climb (watts)
    pub avg_power_w: Option<f64>,
    /// Watts per kilogram
    pub w_per_kg: Option<f64>,
    /// Average heart rate
    pub avg_hr: Option<u8>,
    /// Offset from activity start (seconds)
    pub start_time_offset_s: u32,
    /// Offset from activity start (seconds)
    pub end_time_offset_s: u32,
    /// Arena identifier (optional)
    pub arena_id: Option<String>,
    /// H3 tile IDs traversed during climb
    pub tile_ids: Option<Vec<String>>,
    /// Average gradient percentage
    pub avg_gradient_pct: Option<f64>,
    /// Horizontal distance in meters
    pub distance_m: Option<f64>,
    /// 64-byte signature as hex string
    pub signature_hex: Option<String>,
    /// Canonical v2 signature generated from these exact detector bounds.
    pub signature_v2_hex: Option<String>,
    pub start_lat: Option<f64>,
    pub start_lon: Option<f64>,
    pub end_lat: Option<f64>,
    pub end_lon: Option<f64>,
}

impl ClimbPattern {
    /// Calculate UCI-style climb category.
    pub fn calculate_uci_category(&self) -> &'static str {
        let gain = self.vert_m;
        let gradient = self.avg_gradient_pct.unwrap_or(0.0);
        let distance_km = self.distance_m.unwrap_or(0.0) / 1000.0;
        let difficulty = gain * (1.0 + gradient / 10.0);

        if gain >= 1000.0 || (distance_km >= 7.0 && gradient >= 8.0) || difficulty >= 1500.0 {
            "HC"
        } else if gain >= 500.0 || (distance_km >= 5.0 && gradient >= 6.0) || difficulty >= 800.0 {
            "1"
        } else if gain >= 300.0 || (distance_km >= 3.0 && gradient >= 5.0) || difficulty >= 450.0 {
            "2"
        } else if gain >= 150.0 || (distance_km >= 2.0 && gradient >= 4.0) || difficulty >= 200.0 {
            "3"
        } else if (gain >= 50.0 && gradient >= 3.0) || difficulty >= 75.0 {
            "4"
        } else {
            "UC"
        }
    }

    /// Calculate VAM (Vertical Ascent Meters per hour).
    pub fn vam(&self) -> f64 {
        if self.time_s > 0 {
            (self.vert_m / self.time_s as f64) * 3600.0
        } else {
            0.0
        }
    }
}

/// Detection algorithm choice.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DetectionAlgorithm {
    /// Gradient start + drop tolerance end
    Legacy,
    /// Physics-based momentum accumulation
    Momentum,
}

/// Configuration for the climb detector.
///
/// All thresholds are configurable to support different terrain types.
/// Use the terrain preset constructors for optimized settings:
///
/// - `ClimbDetectorConfig::for_flat()` - Sensitive detection for flat terrain
/// - `ClimbDetectorConfig::for_rolling()` - Moderate thresholds for rolling hills
/// - `ClimbDetectorConfig::for_hilly()` - Standard thresholds (default)
/// - `ClimbDetectorConfig::for_mountainous()` - Strict thresholds for mountains
#[derive(Debug, Clone)]
pub struct ClimbDetectorConfig {
    // ========================================================================
    // Core Climb Validation Thresholds
    // ========================================================================
    /// Minimum vertical gain to qualify as a climb (meters)
    pub vert_min_m: f64,

    /// Maximum allowed descent within climb window (meters)
    pub drop_tolerance_m: f64,

    /// Minimum duration for a climb (seconds)
    pub time_min_s: u32,

    /// Maximum duration for a climb (seconds)
    pub time_max_s: u32,

    /// Minimum VAM (Vertical Ascent Meters per hour) to qualify
    pub vam_min: f64,

    // ========================================================================
    // Gradient Thresholds
    // ========================================================================
    /// Minimum gradient to be considered "climbing" for trimming (percent)
    pub gradient_min_pct: f64,

    /// Gradient threshold to START detecting a climb (percent)
    pub gradient_start_threshold: f64,

    /// Gradient threshold to END a climb (percent, usually negative)
    pub gradient_end_threshold: f64,

    // ========================================================================
    // Momentum Model Parameters
    // ========================================================================
    /// Momentum level to trigger climb START
    pub momentum_start_threshold: f64,

    /// Momentum level to trigger climb END
    pub momentum_end_threshold: f64,

    /// How fast momentum builds when climbing (per sample)
    pub momentum_climb_rate: f64,

    /// How fast momentum drains when descending (per sample)
    pub momentum_drain_rate: f64,

    /// Passive decay multiplier on flat terrain
    pub momentum_decay_rate: f64,

    /// Maximum momentum cap
    pub momentum_max: f64,

    /// Gradient considered "neutral" (slow decay)
    pub momentum_gradient_neutral: f64,

    // ========================================================================
    // Processing Parameters
    // ========================================================================
    /// Number of samples for elevation smoothing
    pub smoothing_window: usize,

    /// Samples for gradient calculation window
    pub gradient_window: usize,

    /// Maximum trim ratio (0.0 - 1.0)
    pub max_trim_ratio: f64,

    /// Which detection algorithm to use
    pub algorithm: DetectionAlgorithm,

    /// Generate 64-byte signatures for vault matching
    pub generate_signatures: bool,
}

impl ClimbDetectorConfig {
    // ========================================================================
    // Terrain Preset Constructors
    // ========================================================================

    /// Create config optimized for FLAT terrain.
    ///
    /// Very sensitive thresholds to capture small hills and rollers.
    /// Use for: Netherlands, Florida, Central Valley, flat coastal rides.
    ///
    /// - 15m minimum vert (vs 50m default)
    /// - 2% minimum gradient (vs 4% default)
    /// - 150 VAM minimum (vs 300 default)
    /// - 60s minimum duration (vs 120s default)
    pub fn for_flat() -> Self {
        Self {
            vert_min_m: 15.0,
            drop_tolerance_m: 15.0,
            time_min_s: 60,
            time_max_s: 1800,
            vam_min: 150.0,
            gradient_min_pct: 2.0,
            gradient_start_threshold: 1.5,
            gradient_end_threshold: -0.5,
            momentum_start_threshold: 1.0,
            momentum_end_threshold: 0.2,
            momentum_climb_rate: 0.20,
            momentum_drain_rate: 0.20,
            momentum_decay_rate: 0.990,
            momentum_max: 8.0,
            momentum_gradient_neutral: 1.0,
            smoothing_window: 5,
            gradient_window: 5,
            max_trim_ratio: 0.5,
            algorithm: DetectionAlgorithm::Momentum,
            generate_signatures: true,
        }
    }

    /// Create config optimized for ROLLING terrain.
    ///
    /// Moderate thresholds for rolling hills and modest climbs.
    /// Use for: Philadelphia, UK, Eastern US, typical suburban riding.
    ///
    /// - 25m minimum vert
    /// - 2.5% minimum gradient
    /// - 200 VAM minimum
    /// - 60s minimum duration, 600s max
    /// - 16m drop tolerance
    pub fn for_rolling() -> Self {
        Self {
            vert_min_m: 25.0,
            drop_tolerance_m: 16.0,
            time_min_s: 60,
            time_max_s: 600,
            vam_min: 200.0,
            gradient_min_pct: 2.5,
            gradient_start_threshold: 2.0,
            gradient_end_threshold: -0.5,
            momentum_start_threshold: 1.5,
            momentum_end_threshold: 0.25,
            momentum_climb_rate: 0.18,
            momentum_drain_rate: 0.22,
            momentum_decay_rate: 0.988,
            momentum_max: 10.0,
            momentum_gradient_neutral: 1.2,
            smoothing_window: 5,
            gradient_window: 5,
            max_trim_ratio: 0.6,
            algorithm: DetectionAlgorithm::Momentum,
            generate_signatures: true,
        }
    }

    /// Create config optimized for HILLY terrain.
    ///
    /// Standard thresholds for significant climbs.
    /// Use for: Bay Area, Appalachians, UK Peak District, foothills.
    ///
    /// This is equivalent to the current default settings.
    pub fn for_hilly() -> Self {
        Self::default()
    }

    /// Create config optimized for MOUNTAINOUS terrain.
    ///
    /// Strict thresholds to filter noise and capture only major climbs.
    /// Use for: Alps, Pyrenees, Dolomites, Colorado Rockies.
    ///
    /// - 100m minimum vert
    /// - 5% minimum gradient
    /// - 400 VAM minimum
    /// - 180s minimum duration
    pub fn for_mountainous() -> Self {
        Self {
            vert_min_m: 100.0,
            drop_tolerance_m: 50.0,
            time_min_s: 180,
            time_max_s: 7200,
            vam_min: 400.0,
            gradient_min_pct: 5.0,
            gradient_start_threshold: 4.0,
            gradient_end_threshold: -1.5,
            momentum_start_threshold: 3.5,
            momentum_end_threshold: 0.5,
            momentum_climb_rate: 0.12,
            momentum_drain_rate: 0.30,
            momentum_decay_rate: 0.980,
            momentum_max: 15.0,
            momentum_gradient_neutral: 2.0,
            smoothing_window: 7,
            gradient_window: 7,
            max_trim_ratio: 0.7,
            algorithm: DetectionAlgorithm::Momentum,
            generate_signatures: true,
        }
    }

    /// Create config optimized for URBAN HILLS terrain.
    ///
    /// Tuned for short, steep, isolated "wall" climbs typical of older cities.
    /// Use for: Philadelphia, Pittsburgh, San Francisco, Bristol UK, Cincinnati.
    ///
    /// Key characteristics:
    /// - Short duration (1-5 min typical)
    /// - Steep gradient (8-15% common)
    /// - Clean start/end (flat → climb → flat)
    /// - No false flats or switchbacks
    ///
    /// - 20m minimum vert (catch shorter climbs)
    /// - 10m drop tolerance (tight - flat means done)
    /// - 60s minimum duration
    /// - Responsive momentum for quick climbs
    pub fn for_urban_hills() -> Self {
        Self {
            // Core thresholds (tuned for Philly-style walls)
            vert_min_m: 20.0,
            drop_tolerance_m: 10.0,
            time_min_s: 60,
            time_max_s: 600,
            vam_min: 200.0,

            // Gradient thresholds
            gradient_min_pct: 3.0,
            gradient_start_threshold: 2.5,
            gradient_end_threshold: 0.0, // End at flat, not descent

            // Momentum model (responsive for short climbs)
            momentum_start_threshold: 1.5,
            momentum_end_threshold: 0.25,
            momentum_climb_rate: 0.20,
            momentum_drain_rate: 0.22,
            momentum_decay_rate: 0.990,
            momentum_max: 8.0,
            momentum_gradient_neutral: 1.0,

            // Processing (less smoothing = sharper boundaries)
            smoothing_window: 3,
            gradient_window: 5,
            max_trim_ratio: 0.5,
            algorithm: DetectionAlgorithm::Momentum,
            generate_signatures: true,
        }
    }

    /// Create config for a specific terrain class.
    ///
    /// This is the primary way to get terrain-adaptive thresholds.
    pub fn for_terrain(terrain: super::terrain::TerrainClass) -> Self {
        use super::terrain::TerrainClass;
        match terrain {
            TerrainClass::Flat => Self::for_flat(),
            TerrainClass::Rolling => Self::for_rolling(),
            TerrainClass::Hilly => Self::for_hilly(),
            TerrainClass::Mountainous => Self::for_mountainous(),
        }
    }

    /// Create config from terrain string (for Python bindings).
    ///
    /// Supports both auto-classified terrain types and manual profile names:
    /// - "flat", "rolling", "hilly", "mountainous" - standard terrain presets
    /// - "urban_hills" - short punchy climbs (Philly, SF, Pittsburgh)
    pub fn for_terrain_str(terrain: &str) -> Option<Self> {
        match terrain.to_lowercase().as_str() {
            "flat" => Some(Self::for_flat()),
            "rolling" => Some(Self::for_rolling()),
            "hilly" => Some(Self::for_hilly()),
            "mountainous" | "mountain" => Some(Self::for_mountainous()),
            "urban_hills" | "urban" => Some(Self::for_urban_hills()),
            _ => None,
        }
    }

    // ========================================================================
    // Builder-style Methods
    // ========================================================================

    /// Set minimum vertical gain threshold.
    pub fn with_vert_min(mut self, meters: f64) -> Self {
        self.vert_min_m = meters;
        self
    }

    /// Set minimum VAM threshold.
    pub fn with_vam_min(mut self, vam: f64) -> Self {
        self.vam_min = vam;
        self
    }

    /// Set minimum duration.
    pub fn with_time_min(mut self, seconds: u32) -> Self {
        self.time_min_s = seconds;
        self
    }

    /// Set minimum gradient threshold.
    pub fn with_gradient_min(mut self, percent: f64) -> Self {
        self.gradient_min_pct = percent;
        self
    }

    /// Set detection algorithm.
    pub fn with_algorithm(mut self, algo: DetectionAlgorithm) -> Self {
        self.algorithm = algo;
        self
    }

    /// Enable or disable signature generation.
    pub fn with_signatures(mut self, enabled: bool) -> Self {
        self.generate_signatures = enabled;
        self
    }
}

impl Default for ClimbDetectorConfig {
    /// Default configuration (optimized for Hilly terrain).
    fn default() -> Self {
        Self {
            // Core thresholds
            vert_min_m: 50.0,
            drop_tolerance_m: 30.0,
            time_min_s: 120,
            time_max_s: 3600,
            vam_min: 300.0,

            // Gradient thresholds
            gradient_min_pct: 4.0,
            gradient_start_threshold: 3.0,
            gradient_end_threshold: -1.0,

            // Momentum model
            momentum_start_threshold: 2.5,
            momentum_end_threshold: 0.3,
            momentum_climb_rate: 0.15,
            momentum_drain_rate: 0.25,
            momentum_decay_rate: 0.985,
            momentum_max: 12.0,
            momentum_gradient_neutral: 1.5,

            // Processing
            smoothing_window: 5,
            gradient_window: 5,
            max_trim_ratio: 0.7,
            algorithm: DetectionAlgorithm::Momentum,
            generate_signatures: true,
        }
    }
}

/// Internal segment representation during detection.
#[derive(Debug, Clone)]
pub(crate) struct ClimbSegment {
    pub start_idx: usize,
    pub end_idx: usize,
}
