//! Terrain classification for adaptive climb detection.
//!
//! This module analyzes elevation profiles to classify terrain type,
//! enabling automatic threshold adaptation for different riding conditions.
//!
//! # Terrain Classes
//!
//! - **Flat**: < 200m total gain, gentle grades (Netherlands, Florida)
//! - **Rolling**: 200-600m gain, moderate hills (Philadelphia, UK)
//! - **Hilly**: 600-1500m gain, sustained climbs (foothills, modest mountains)
//! - **Mountainous**: > 1500m gain or very steep sustained grades (Alps, Pyrenees)
//!
//! # Example
//!
//! ```ignore
//! use workout_parse::climb::terrain::{TerrainClassifier, TerrainClass};
//!
//! let classifier = TerrainClassifier::default();
//! let classification = classifier.classify(&samples).unwrap();
//!
//! match classification.class {
//!     TerrainClass::Flat => println!("Using sensitive detection"),
//!     TerrainClass::Mountainous => println!("Using strict detection"),
//!     _ => println!("Using moderate detection"),
//! }
//! ```

use super::types::TileSample;
use super::utils::{haversine_m, smooth_elevations};

// ============================================================================
// Terrain Classification Types
// ============================================================================

/// Terrain classification based on elevation profile analysis.
///
/// Each class corresponds to a set of optimized detection thresholds
/// that capture meaningful climbs for that terrain type.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum TerrainClass {
    /// Minimal elevation change (< 200m gain, < 3% max sustained)
    /// Examples: Netherlands, Florida, Central Valley
    Flat = 0,

    /// Moderate rolling terrain (200-600m gain, 3-5% peaks)
    /// Examples: Philadelphia, UK, most of Eastern US
    Rolling = 1,

    /// Significant hills and climbs (600-1500m gain, 5-8% peaks)
    /// Examples: Bay Area, Appalachians, UK Peak District
    Hilly = 2,

    /// Major mountain terrain (> 1500m gain or > 8% sustained)
    /// Examples: Alps, Pyrenees, Dolomites, Colorado Rockies
    Mountainous = 3,
}

impl TerrainClass {
    /// Convert from string representation (for Python bindings).
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "flat" => Some(Self::Flat),
            "rolling" => Some(Self::Rolling),
            "hilly" => Some(Self::Hilly),
            "mountainous" | "mountain" => Some(Self::Mountainous),
            _ => None,
        }
    }

    /// Convert to string representation.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Flat => "flat",
            Self::Rolling => "rolling",
            Self::Hilly => "hilly",
            Self::Mountainous => "mountainous",
        }
    }

    /// Get numeric representation (useful for serialization).
    pub fn as_u8(&self) -> u8 {
        *self as u8
    }
}

impl std::fmt::Display for TerrainClass {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Metrics computed during terrain analysis.
///
/// These values are used both for classification and for reporting
/// to downstream consumers who may want the raw data.
#[derive(Debug, Clone)]
pub struct TerrainMetrics {
    /// Total elevation gained (sum of positive deltas), in meters
    pub total_gain_m: f64,

    /// Total elevation lost (sum of negative deltas), in meters
    pub total_loss_m: f64,

    /// Highest elevation point in meters
    pub max_elevation_m: f64,

    /// Lowest elevation point in meters
    pub min_elevation_m: f64,

    /// Elevation range (max - min) in meters
    pub elevation_range_m: f64,

    /// Maximum sustained gradient over window (percent)
    pub max_sustained_gradient_pct: f64,

    /// Average gradient of positive sections (percent)
    pub avg_climbing_gradient_pct: f64,

    /// Standard deviation of gradient values
    pub gradient_std_dev: f64,

    /// Total distance analyzed in meters (if GPS available)
    pub total_distance_m: Option<f64>,

    /// Duration of analyzed samples in seconds
    pub duration_s: u32,

    /// Number of samples analyzed
    pub sample_count: usize,
}

impl TerrainMetrics {
    /// Compute difficulty score (higher = harder terrain).
    ///
    /// Combines elevation gain, gradient intensity, and duration
    /// into a single comparable value.
    pub fn difficulty_score(&self) -> f64 {
        let gain_factor = self.total_gain_m / 100.0;
        let gradient_factor = self.max_sustained_gradient_pct.max(1.0);
        let range_factor = self.elevation_range_m / 500.0;

        (gain_factor * gradient_factor.sqrt() + range_factor).max(0.0)
    }
}

/// Complete result of terrain classification.
#[derive(Debug, Clone)]
pub struct TerrainClassification {
    /// The determined terrain class
    pub class: TerrainClass,

    /// Detailed metrics used for classification
    pub metrics: TerrainMetrics,

    /// Confidence score (0.0 - 1.0)
    /// Lower confidence when data is sparse or edge cases
    pub confidence: f64,

    /// Human-readable explanation of classification decision
    pub reason: String,
}

// ============================================================================
// Classification Thresholds
// ============================================================================

/// Thresholds for terrain classification decisions.
///
/// These are the boundaries between terrain classes.
#[derive(Debug, Clone)]
pub struct ClassificationThresholds {
    /// Gain threshold: Flat → Rolling (meters)
    pub flat_rolling_gain_m: f64,

    /// Gain threshold: Rolling → Hilly (meters)
    pub rolling_hilly_gain_m: f64,

    /// Gain threshold: Hilly → Mountainous (meters)
    pub hilly_mountainous_gain_m: f64,

    /// Gradient threshold: triggers upgrade if exceeded (percent)
    pub steep_gradient_pct: f64,

    /// Minimum samples for valid classification
    pub min_samples: usize,

    /// Minimum duration for valid classification (seconds)
    pub min_duration_s: u32,
}

impl Default for ClassificationThresholds {
    fn default() -> Self {
        Self {
            flat_rolling_gain_m: 200.0,
            rolling_hilly_gain_m: 600.0,
            hilly_mountainous_gain_m: 1500.0,
            steep_gradient_pct: 8.0,
            min_samples: 10,
            min_duration_s: 300, // 5 minutes minimum
        }
    }
}

// ============================================================================
// Terrain Classifier
// ============================================================================

/// Terrain classifier with configurable thresholds.
///
/// Analyzes elevation profiles to determine terrain type for
/// adaptive climb detection thresholds.
pub struct TerrainClassifier {
    /// Classification thresholds
    thresholds: ClassificationThresholds,

    /// Window for smoothing elevation data
    smoothing_window: usize,

    /// Window for sustained gradient calculation (in samples)
    gradient_window_samples: usize,
}

impl Default for TerrainClassifier {
    fn default() -> Self {
        Self {
            thresholds: ClassificationThresholds::default(),
            smoothing_window: 5,
            gradient_window_samples: 30, // ~30 seconds at 1Hz
        }
    }
}

impl TerrainClassifier {
    /// Create a classifier with custom thresholds.
    pub fn with_thresholds(thresholds: ClassificationThresholds) -> Self {
        Self {
            thresholds,
            ..Default::default()
        }
    }

    /// Classify terrain from tile samples.
    ///
    /// Returns `None` if insufficient data for classification.
    pub fn classify(&self, samples: &[TileSample]) -> Option<TerrainClassification> {
        // Filter to samples with elevation
        let elev_samples: Vec<&TileSample> = samples.iter().filter(|s| s.has_elevation()).collect();

        if elev_samples.len() < self.thresholds.min_samples {
            return None;
        }

        // Check duration
        let duration_s = if elev_samples.len() >= 2 {
            (elev_samples.last().unwrap().t - elev_samples.first().unwrap().t) as u32
        } else {
            0
        };

        if duration_s < self.thresholds.min_duration_s {
            return None;
        }

        // Compute metrics
        let metrics = self.compute_metrics(&elev_samples)?;

        // Classify based on metrics
        let (class, confidence, reason) = self.classify_from_metrics(&metrics);

        Some(TerrainClassification {
            class,
            metrics,
            confidence,
            reason,
        })
    }

    /// Classify terrain from raw elevation data (simpler interface).
    ///
    /// Useful when you don't have full TileSample data.
    pub fn classify_from_elevations(
        &self,
        elevations: &[f64],
        timestamps: &[i64],
    ) -> Option<TerrainClassification> {
        if elevations.len() != timestamps.len() || elevations.len() < self.thresholds.min_samples {
            return None;
        }

        // Create synthetic samples
        let samples: Vec<TileSample> = elevations
            .iter()
            .zip(timestamps.iter())
            .map(|(&elev, &t)| TileSample {
                t,
                tile_id: None,
                elevation_m: Some(elev),
                power_w: None,
                hr_bpm: None,
                lat: None,
                lon: None,
            })
            .collect();

        self.classify(&samples)
    }

    /// Compute terrain metrics from samples.
    fn compute_metrics(&self, samples: &[&TileSample]) -> Option<TerrainMetrics> {
        if samples.len() < 2 {
            return None;
        }

        // Extract and smooth elevations
        let raw_elevations: Vec<f64> = samples.iter().filter_map(|s| s.elevation_m).collect();

        if raw_elevations.len() < 2 {
            return None;
        }

        let elevations = smooth_elevations(&raw_elevations, self.smoothing_window);

        // Basic elevation stats
        let max_elevation_m = elevations.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let min_elevation_m = elevations.iter().cloned().fold(f64::INFINITY, f64::min);
        let elevation_range_m = max_elevation_m - min_elevation_m;

        // Calculate gain, loss, and gradients
        let mut total_gain_m = 0.0;
        let mut total_loss_m = 0.0;
        let mut gradients: Vec<f64> = Vec::with_capacity(elevations.len());
        let mut climbing_gradients: Vec<f64> = Vec::new();

        for i in 1..elevations.len() {
            let delta = elevations[i] - elevations[i - 1];
            if delta > 0.0 {
                total_gain_m += delta;
            } else {
                total_loss_m += delta.abs();
            }

            // Calculate gradient if we have GPS or time
            if i < samples.len() {
                let s_prev = samples[i - 1];
                let s_curr = samples[i];

                let dist_m = match (s_prev.lat, s_prev.lon, s_curr.lat, s_curr.lon) {
                    (Some(lat1), Some(lon1), Some(lat2), Some(lon2)) => {
                        haversine_m(lat1, lon1, lat2, lon2)
                    }
                    _ => {
                        // Estimate from time (~5 m/s cycling speed)
                        let dt = (s_curr.t - s_prev.t).max(1) as f64;
                        dt * 5.0
                    }
                };

                if dist_m > 1.0 {
                    let gradient_pct = (delta / dist_m) * 100.0;
                    gradients.push(gradient_pct);
                    if gradient_pct > 0.5 {
                        climbing_gradients.push(gradient_pct);
                    }
                }
            }
        }

        // Calculate max sustained gradient (rolling window)
        let max_sustained_gradient_pct = self.compute_max_sustained_gradient(&gradients);

        // Calculate average climbing gradient
        let avg_climbing_gradient_pct = if climbing_gradients.is_empty() {
            0.0
        } else {
            climbing_gradients.iter().sum::<f64>() / climbing_gradients.len() as f64
        };

        // Calculate gradient standard deviation
        let gradient_std_dev = if gradients.len() > 1 {
            let mean = gradients.iter().sum::<f64>() / gradients.len() as f64;
            let variance = gradients.iter().map(|g| (g - mean).powi(2)).sum::<f64>()
                / (gradients.len() - 1) as f64;
            variance.sqrt()
        } else {
            0.0
        };

        // Calculate total distance if GPS available
        let total_distance_m = self.compute_total_distance(samples);

        // Duration
        let duration_s = (samples.last().unwrap().t - samples.first().unwrap().t) as u32;

        Some(TerrainMetrics {
            total_gain_m,
            total_loss_m,
            max_elevation_m,
            min_elevation_m,
            elevation_range_m,
            max_sustained_gradient_pct,
            avg_climbing_gradient_pct,
            gradient_std_dev,
            total_distance_m,
            duration_s,
            sample_count: samples.len(),
        })
    }

    /// Compute maximum sustained gradient over rolling window.
    fn compute_max_sustained_gradient(&self, gradients: &[f64]) -> f64 {
        if gradients.len() < self.gradient_window_samples {
            // Not enough data for sustained gradient
            return gradients.iter().cloned().fold(0.0, f64::max);
        }

        let mut max_sustained = 0.0;

        for i in 0..=(gradients.len() - self.gradient_window_samples) {
            let window = &gradients[i..i + self.gradient_window_samples];
            let avg = window.iter().sum::<f64>() / window.len() as f64;
            if avg > max_sustained {
                max_sustained = avg;
            }
        }

        max_sustained
    }

    /// Compute total distance from GPS coordinates.
    fn compute_total_distance(&self, samples: &[&TileSample]) -> Option<f64> {
        let mut total = 0.0;
        let mut has_gps = false;

        for i in 1..samples.len() {
            let prev = samples[i - 1];
            let curr = samples[i];

            if let (Some(lat1), Some(lon1), Some(lat2), Some(lon2)) =
                (prev.lat, prev.lon, curr.lat, curr.lon)
            {
                total += haversine_m(lat1, lon1, lat2, lon2);
                has_gps = true;
            }
        }

        if has_gps && total > 0.0 {
            Some(total)
        } else {
            None
        }
    }

    /// Classify terrain from computed metrics.
    fn classify_from_metrics(&self, metrics: &TerrainMetrics) -> (TerrainClass, f64, String) {
        let gain = metrics.total_gain_m;
        let max_grad = metrics.max_sustained_gradient_pct;
        let t = &self.thresholds;

        // Primary classification by total gain
        let (base_class, base_reason) = if gain < t.flat_rolling_gain_m {
            (
                TerrainClass::Flat,
                format!(
                    "{:.0}m gain < {:.0}m threshold",
                    gain, t.flat_rolling_gain_m
                ),
            )
        } else if gain < t.rolling_hilly_gain_m {
            (
                TerrainClass::Rolling,
                format!("{:.0}m gain in rolling range", gain),
            )
        } else if gain < t.hilly_mountainous_gain_m {
            (
                TerrainClass::Hilly,
                format!("{:.0}m gain in hilly range", gain),
            )
        } else {
            (
                TerrainClass::Mountainous,
                format!("{:.0}m gain exceeds mountainous threshold", gain),
            )
        };

        // Check for gradient-based upgrade
        // Very steep sustained gradients can upgrade classification
        let (final_class, upgrade_reason) = if max_grad >= t.steep_gradient_pct {
            match base_class {
                TerrainClass::Flat => (
                    TerrainClass::Rolling,
                    format!(" (upgraded: {:.1}% sustained gradient)", max_grad),
                ),
                TerrainClass::Rolling => (
                    TerrainClass::Hilly,
                    format!(" (upgraded: {:.1}% sustained gradient)", max_grad),
                ),
                TerrainClass::Hilly if max_grad >= 10.0 => (
                    TerrainClass::Mountainous,
                    format!(" (upgraded: {:.1}% sustained gradient)", max_grad),
                ),
                _ => (base_class, String::new()),
            }
        } else {
            (base_class, String::new())
        };

        // Calculate confidence based on data quality
        let mut confidence: f64 = 1.0;

        // Reduce confidence for edge cases (near thresholds)
        let gain_from_threshold = match final_class {
            TerrainClass::Flat => t.flat_rolling_gain_m - gain,
            TerrainClass::Rolling => {
                (gain - t.flat_rolling_gain_m).min(t.rolling_hilly_gain_m - gain)
            }
            TerrainClass::Hilly => {
                (gain - t.rolling_hilly_gain_m).min(t.hilly_mountainous_gain_m - gain)
            }
            TerrainClass::Mountainous => gain - t.hilly_mountainous_gain_m,
        };

        // Near-threshold reduces confidence
        if gain_from_threshold.abs() < 50.0 {
            confidence *= 0.7;
        }

        // Short duration reduces confidence
        if metrics.duration_s < 1800 {
            // < 30 min
            confidence *= 0.8;
        }

        // Few samples reduces confidence
        if metrics.sample_count < 100 {
            confidence *= 0.9;
        }

        let reason = format!("{}{}", base_reason, upgrade_reason);
        (final_class, confidence.clamp(0.3, 1.0), reason)
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn make_sample(t: i64, elev: f64) -> TileSample {
        TileSample {
            t,
            tile_id: None,
            elevation_m: Some(elev),
            power_w: None,
            hr_bpm: None,
            lat: None,
            lon: None,
        }
    }

    fn make_gps_sample(t: i64, elev: f64, lat: f64, lon: f64) -> TileSample {
        TileSample {
            t,
            tile_id: None,
            elevation_m: Some(elev),
            power_w: None,
            hr_bpm: None,
            lat: Some(lat),
            lon: Some(lon),
        }
    }

    #[test]
    fn test_flat_terrain() {
        // 1 hour ride with 100m total gain
        let samples: Vec<TileSample> = (0..3600)
            .map(|t| {
                let elev = 100.0 + (t as f64 * 0.03); // ~100m gain over 1h
                make_sample(t, elev)
            })
            .collect();

        let classifier = TerrainClassifier::default();
        let result = classifier.classify(&samples).unwrap();

        assert_eq!(result.class, TerrainClass::Flat);
        assert!(result.metrics.total_gain_m < 200.0);
    }

    #[test]
    fn test_rolling_terrain() {
        // 1 hour ride with 400m total gain (rolling hills)
        let samples: Vec<TileSample> = (0..3600)
            .map(|t| {
                // Sinusoidal hills averaging ~400m gain
                let base = 100.0 + (t as f64 * 0.11); // Steady rise
                let wave = 20.0 * ((t as f64 / 300.0).sin()); // Rolling
                make_sample(t, base + wave)
            })
            .collect();

        let classifier = TerrainClassifier::default();
        let result = classifier.classify(&samples).unwrap();

        assert_eq!(result.class, TerrainClass::Rolling);
        assert!(result.metrics.total_gain_m >= 200.0);
        assert!(result.metrics.total_gain_m < 600.0);
    }

    #[test]
    fn test_hilly_terrain() {
        // 2 hour ride with 1000m total gain
        let samples: Vec<TileSample> = (0..7200)
            .map(|t| {
                let elev = 100.0 + (t as f64 * 0.14); // ~1000m gain
                make_sample(t, elev)
            })
            .collect();

        let classifier = TerrainClassifier::default();
        let result = classifier.classify(&samples).unwrap();

        assert_eq!(result.class, TerrainClass::Hilly);
    }

    #[test]
    fn test_mountainous_terrain() {
        // 3 hour ride with 2000m total gain
        let samples: Vec<TileSample> = (0..10800)
            .map(|t| {
                let elev = 500.0 + (t as f64 * 0.19); // ~2000m gain
                make_sample(t, elev)
            })
            .collect();

        let classifier = TerrainClassifier::default();
        let result = classifier.classify(&samples).unwrap();

        assert_eq!(result.class, TerrainClass::Mountainous);
    }

    #[test]
    fn test_steep_gradient_upgrade() {
        // Short but very steep climb should upgrade classification
        // 10 min ride with sustained 10% grade
        // At 5 m/s speed: 10% grade = 0.5m elevation per second
        // 600 seconds * 0.5 = 300m gain over 3000m distance
        let samples: Vec<TileSample> = (0..600)
            .map(|t| {
                // 10% grade = 0.5m per second at 5m/s cycling speed
                let elev = 100.0 + (t as f64 * 0.5);
                make_sample(t, elev)
            })
            .collect();

        let classifier = TerrainClassifier::default();
        let result = classifier.classify(&samples).unwrap();

        // Should be at least Rolling due to steep 10% sustained gradient
        assert!(
            result.class != TerrainClass::Flat,
            "Steep 10% gradient should upgrade from Flat to at least Rolling"
        );
    }

    #[test]
    fn test_insufficient_data() {
        let samples: Vec<TileSample> = (0..5).map(|t| make_sample(t, 100.0)).collect();

        let classifier = TerrainClassifier::default();
        let result = classifier.classify(&samples);

        assert!(
            result.is_none(),
            "Should return None for insufficient samples"
        );
    }

    #[test]
    fn test_terrain_class_string_conversion() {
        assert_eq!(TerrainClass::Flat.as_str(), "flat");
        assert_eq!(TerrainClass::Rolling.as_str(), "rolling");
        assert_eq!(TerrainClass::Hilly.as_str(), "hilly");
        assert_eq!(TerrainClass::Mountainous.as_str(), "mountainous");

        assert_eq!(TerrainClass::from_str("flat"), Some(TerrainClass::Flat));
        assert_eq!(
            TerrainClass::from_str("ROLLING"),
            Some(TerrainClass::Rolling)
        );
        assert_eq!(
            TerrainClass::from_str("mountain"),
            Some(TerrainClass::Mountainous)
        );
        assert_eq!(TerrainClass::from_str("invalid"), None);
    }

    #[test]
    fn test_difficulty_score() {
        let flat_metrics = TerrainMetrics {
            total_gain_m: 100.0,
            total_loss_m: 100.0,
            max_elevation_m: 150.0,
            min_elevation_m: 100.0,
            elevation_range_m: 50.0,
            max_sustained_gradient_pct: 2.0,
            avg_climbing_gradient_pct: 1.5,
            gradient_std_dev: 0.5,
            total_distance_m: Some(30000.0),
            duration_s: 3600,
            sample_count: 3600,
        };

        let mountain_metrics = TerrainMetrics {
            total_gain_m: 2000.0,
            total_loss_m: 500.0,
            max_elevation_m: 2500.0,
            min_elevation_m: 500.0,
            elevation_range_m: 2000.0,
            max_sustained_gradient_pct: 8.0,
            avg_climbing_gradient_pct: 6.0,
            gradient_std_dev: 3.0,
            total_distance_m: Some(60000.0),
            duration_s: 14400,
            sample_count: 14400,
        };

        assert!(
            mountain_metrics.difficulty_score() > flat_metrics.difficulty_score(),
            "Mountainous should have higher difficulty score"
        );
    }
}
