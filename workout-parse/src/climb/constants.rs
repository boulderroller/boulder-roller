//! Climb detection constants.
//!
//! These values are ported from backend/app/services/patterns/climb.py
//! to ensure algorithm parity.

// ============================================================================
// Core Detection Thresholds
// ============================================================================

/// Minimum vertical gain to qualify as a climb (meters)
pub const VERT_MIN_M: f64 = 50.0;

/// Maximum allowed descent within a climb window (meters)
pub const DROP_TOLERANCE_M: f64 = 30.0;

/// Minimum duration for a climb (seconds)
pub const TIME_MIN_S: u32 = 120;

/// Maximum duration for a climb (seconds)
pub const TIME_MAX_S: u32 = 3600;

/// Number of samples for elevation smoothing
pub const SMOOTHING_WINDOW: usize = 5;

// ============================================================================
// Gradient Thresholds
// ============================================================================

/// Minimum gradient to be considered "climbing" (percent)
pub const MIN_CLIMB_GRADIENT_PCT: f64 = 4.0;

/// Samples to average for gradient calculation
pub const GRADIENT_WINDOW: usize = 5;

/// Allow trimming up to 70% of segment
pub const MAX_TRIM_RATIO: f64 = 0.7;

/// Minimum VAM (Vertical Ascent Meters per hour) to qualify
/// 300 VAM ≈ 2.5% sustained gradient at ~12 km/h
pub const MIN_CLIMB_VAM: f64 = 300.0;

// ============================================================================
// Gradient Calculation
// ============================================================================

/// Samples for gradient smoothing in detection
pub const GRADIENT_CALC_WINDOW: usize = 15;

// ============================================================================
// Signature Generation
// ============================================================================

/// Number of bins for gradient profile
pub const GRADIENT_BINS: usize = 32;

/// Gradient range for binning: minimum (descending)
pub const SIGNATURE_GRADIENT_MIN: f64 = -10.0;

/// Gradient range for binning: maximum (steep climbing)
pub const SIGNATURE_GRADIENT_MAX: f64 = 20.0;

// ============================================================================
// Distance Estimation
// ============================================================================

/// Earth radius in meters (for Haversine)
pub const EARTH_RADIUS_M: f64 = 6_371_000.0;

/// Fallback cycling speed for distance estimation (m/s)
pub const ESTIMATED_CYCLING_SPEED_MPS: f64 = 5.0;
