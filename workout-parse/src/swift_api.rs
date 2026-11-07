//! Swift-facing bindings (UniFFI).
//!
//! Spike surface for bead boulderroller-v2-8mp46: prove the native iOS lane
//! can call the *same* Rust parse/canonicalize/metrics/tile code the backend
//! uses, killing the TypeScript-reimplementation drift risk.
//!
//! Design rules:
//! - Existing identity, metrics, and tiles are produced by the exact pure-Rust
//!   functions the PyO3 bindings wrap (`parse_file_bytes_for_version`,
//!   `hash_canonical_ride`, `compute_activity_metrics`, `project_to_h3` +
//!   `unique_cells` + `cells_to_strings`).
//! - No new hashing. `canonical_hash` is `canonicalize::hash_canonical_ride`,
//!   the identical bytes the backend derives in
//!   `compute_ride_identity_bytes_rust`.
//! - Numeric types mirror `PyComputedMetrics` getters exactly (f32 stays f32)
//!   so parity checks compare bit-identical values, not rounded ones.

use crate::canonicalize::{hash_canonical_ride, CURRENT_PARSER_VERSION};
use crate::error::WpError;
use crate::metrics::METRICS_VERSION;
use crate::tiles::{cells_to_strings, project_to_h3, unique_cells};
use crate::{compute_activity_metrics, parse_file_bytes_for_version, ParsedActivity};
use h3o::Resolution;

/// Error surface for Swift callers. Mirrors the PyO3 exception mapping:
/// decompression/duration limits stay distinguishable, everything else is a
/// parse error with the original message.
#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum WorkoutParseError {
    #[error("parse error: {message}")]
    Parse { message: String },
    #[error("decompression limit exceeded: {message}")]
    DecompressionLimitExceeded { message: String },
    #[error("duration limit exceeded: {message}")]
    DurationLimitExceeded { message: String },
}

impl From<WpError> for WorkoutParseError {
    fn from(error: WpError) -> Self {
        match error {
            WpError::DecompressionLimitExceeded(message) => {
                WorkoutParseError::DecompressionLimitExceeded { message }
            }
            WpError::DurationLimitExceeded(message) => {
                WorkoutParseError::DurationLimitExceeded { message }
            }
            other => WorkoutParseError::Parse {
                message: other.to_string(),
            },
        }
    }
}

/// A display-only point in the ride's distance coordinate system.
/// Matches the owner rides list's compact `elevation_profile` shape.
#[derive(Debug, Clone, PartialEq, uniffi::Record)]
pub struct ElevationProfilePoint {
    pub distance_m: f64,
    pub elevation_m: f64,
}

/// One parsed ride, summarized for the device.
///
/// Field-for-field parity contract with the backend Python path:
/// - `canonical_hash_hex` == `workout_parse.hash_canonical_ride(activity)`
/// - metrics fields      == `workout_parse.compute_metrics(activity, ftp)`
/// - `tile_ids_res10`    == `workout_parse.get_h3_strings(lat_e7, lon_e7, 10)`
#[derive(Debug, Clone, uniffi::Record)]
pub struct RideSummary {
    // --- Attestation identity ---
    pub parser_version: u32,
    /// 32 raw SHA-256 bytes of the canonical ride encoding.
    pub canonical_hash: Vec<u8>,
    /// Lowercase hex of `canonical_hash` (backend representation).
    pub canonical_hash_hex: String,

    // --- Activity header ---
    pub sport: String,
    pub started_at_ms: i64,
    pub total_elapsed_s: u32,
    pub sample_count: u64,

    // --- Metrics (same math as `workout_parse.compute_metrics`) ---
    pub duration_s: u32,
    pub moving_time_s: u32,
    pub distance_m: f32,
    pub elevation_gain_m: f32,
    pub normalized_power_w: Option<u16>,
    pub avg_power_w: Option<u16>,
    pub max_power_w: Option<u16>,
    pub power_sample_count: u32,
    pub power_sample_coverage_bps: u16,
    pub tss: Option<f32>,
    pub intensity_factor: Option<f32>,
    pub kcals: Option<u32>,
    pub avg_hr_bpm: Option<u8>,
    pub max_hr_bpm: Option<u8>,
    pub heart_rate_sample_count: u32,
    pub heart_rate_sample_coverage_bps: u16,
    pub avg_speed_mps: Option<f32>,
    pub max_speed_mps: Option<f32>,
    pub avg_cadence_rpm: Option<u8>,
    pub metrics_version: String,

    // --- H3 tiles (resolution 10, backend storage representation) ---
    pub tile_count_res10: u32,
    pub tile_ids_res10: Vec<String>,

    /// Preliminary file elevation, not backend-corrected elevation or authority.
    /// At most 64 distance-binned points; empty when no honest axis is available.
    pub elevation_profile: Vec<ElevationProfilePoint>,
}

/// The crate's current canonicalization version (backend default).
#[uniffi::export]
pub fn current_parser_version() -> u32 {
    CURRENT_PARSER_VERSION
}

/// The crate's metrics formula version string.
#[uniffi::export]
pub fn metrics_version() -> String {
    METRICS_VERSION.to_string()
}

/// Parse a ride file and produce the device-side summary.
///
/// * `data` - raw file bytes (FIT/GPX/TCX; gzip/zip handled automatically)
/// * `file_type` - "fit" | "gpx" | "tcx" | "auto"
/// * `ftp_watts` - rider FTP used for IF/TSS (backend default is 200)
/// * `parser_version` - canonicalization version; `None` = current
#[uniffi::export]
pub fn parse_ride_summary(
    data: Vec<u8>,
    file_type: String,
    ftp_watts: u16,
    parser_version: Option<u32>,
) -> Result<RideSummary, WorkoutParseError> {
    let version = parser_version.unwrap_or(CURRENT_PARSER_VERSION);
    let activity = parse_file_bytes_for_version(&data, &file_type, version)?;

    summarize_activity(&activity, version, ftp_watts)
}

/// Produce the existing canonical empty-ride stamp for a recorder that stopped
/// before accepting a sample. This is deliberately separate from file parsing:
/// an empty GPX remains invalid and must never be uploaded as a parseable ride.
#[uniffi::export]
pub fn summarize_empty_recording(
    started_at_ms: i64,
    parser_version: Option<u32>,
) -> Result<RideSummary, WorkoutParseError> {
    let version = parser_version.unwrap_or(CURRENT_PARSER_VERSION);
    let activity = ParsedActivity {
        started_at_ms,
        ..ParsedActivity::default()
    };
    // No power samples exist, so no rider FTP testimony is needed or inferred.
    summarize_activity(&activity, version, 0)
}

fn summarize_activity(
    activity: &ParsedActivity,
    version: u32,
    ftp_watts: u16,
) -> Result<RideSummary, WorkoutParseError> {
    let canonical_hash = hash_canonical_ride(&activity, version)?;
    let canonical_hash_hex = hex::encode(canonical_hash);

    let metrics = compute_activity_metrics(&activity, ftp_watts)?;

    let tile_ids_res10 = match (&activity.lat_e7, &activity.lon_e7) {
        (Some(lat), Some(lon)) => {
            let cells = project_to_h3(lat, lon, Resolution::Ten);
            cells_to_strings(&unique_cells(&cells))
        }
        _ => Vec::new(),
    };

    Ok(RideSummary {
        parser_version: version,
        canonical_hash: canonical_hash.to_vec(),
        canonical_hash_hex,
        sport: activity.sport.clone(),
        started_at_ms: activity.started_at_ms,
        total_elapsed_s: activity.total_elapsed_s,
        sample_count: activity.time_ms.len() as u64,
        duration_s: metrics.duration_s,
        moving_time_s: metrics.moving_time_s,
        distance_m: metrics.distance_m,
        elevation_gain_m: metrics.elevation_gain_m,
        normalized_power_w: metrics.normalized_power_w,
        avg_power_w: metrics.avg_power_w,
        max_power_w: metrics.max_power_w,
        power_sample_count: metrics.power_sample_count,
        power_sample_coverage_bps: metrics.power_sample_coverage_bps,
        tss: metrics.tss,
        intensity_factor: metrics.intensity_factor,
        kcals: metrics.kcals,
        avg_hr_bpm: metrics.avg_hr_bpm,
        max_hr_bpm: metrics.max_hr_bpm,
        heart_rate_sample_count: metrics.heart_rate_sample_count,
        heart_rate_sample_coverage_bps: metrics.heart_rate_sample_coverage_bps,
        avg_speed_mps: metrics.avg_speed_mps,
        max_speed_mps: metrics.max_speed_mps,
        avg_cadence_rpm: metrics.avg_cadence_rpm,
        metrics_version: METRICS_VERSION.to_string(),
        tile_count_res10: tile_ids_res10.len() as u32,
        tile_ids_res10,
        elevation_profile: compact_elevation_profile(activity),
    })
}

/// Display projection only: never mutates samples, totals, canonical bytes,
/// detector inputs, or tiles. Mirrors build_ride_list_shape's relief sampling.
fn compact_elevation_profile(activity: &ParsedActivity) -> Vec<ElevationProfilePoint> {
    let Some(elevations) = &activity.elevation_m else {
        return Vec::new();
    };
    let distances: Vec<f64> = if let Some(distances) = activity
        .dist_m
        .as_ref()
        .filter(|ds| ds.iter().any(|d| d.is_finite() && *d > 0.0))
    {
        distances.iter().map(|d| f64::from(*d)).collect()
    } else {
        let (Some(lat), Some(lon)) = (&activity.lat_e7, &activity.lon_e7) else {
            return Vec::new();
        };
        if lat.len() != elevations.len() || lon.len() != elevations.len() {
            return Vec::new();
        }
        let mut distance = 0.0;
        let mut previous = None;
        let mut axis = Vec::with_capacity(lat.len());
        for (&lat, &lon) in lat.iter().zip(lon) {
            let (lat, lon) = (f64::from(lat) / 1e7, f64::from(lon) / 1e7);
            if lat.abs() > 90.0 || lon.abs() > 180.0 {
                return Vec::new();
            }
            if let Some((prev_lat, prev_lon)) = previous {
                distance += crate::haversine_m(prev_lat, prev_lon, lat, lon);
            }
            axis.push(distance);
            previous = Some((lat, lon));
        }
        axis
    };
    let mut samples: Vec<(f64, f64)> = Vec::new();
    for (distance, &elevation) in distances.into_iter().zip(elevations) {
        if !distance.is_finite() || distance < 0.0 || !elevation.is_finite() {
            continue;
        }
        if let Some(&(last, _)) = samples.last() {
            if distance < last {
                return Vec::new();
            }
            if distance == last {
                continue;
            }
        }
        samples.push((distance, f64::from(elevation)));
    }
    if samples.len() < 2 || samples.last().unwrap().0 <= 0.0 {
        return Vec::new();
    }
    let count = samples.len().min(64);
    let start = samples[0].0;
    let end = samples.last().unwrap().0;
    let mut segment = 0;
    (0..count)
        .map(|index| {
            let distance = start + (end - start) * index as f64 / (count - 1) as f64;
            while segment + 2 < samples.len() && samples[segment + 1].0 <= distance {
                segment += 1;
            }
            let (x0, y0) = samples[segment];
            let (x1, y1) = samples[segment + 1];
            let elevation = y0 + (distance - x0) / (x1 - x0) * (y1 - y0);
            ElevationProfilePoint {
                distance_m: distance,
                elevation_m: (elevation * 10.0).round_ties_even() / 10.0,
            }
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn summary_exposes_distance_binned_elevation_without_changing_identity() {
        let activity = ParsedActivity {
            time_ms: (0..100).map(|i| i * 1000).collect(),
            dist_m: Some((0..100).map(|i| i as f32 * 10.0).collect()),
            elevation_m: Some((0..100).map(|i| 100.0 + i as f32).collect()),
            ..ParsedActivity::default()
        };
        let summary = summarize_activity(&activity, CURRENT_PARSER_VERSION, 200).unwrap();
        assert_eq!(summary.elevation_profile.len(), 64);
        assert_eq!(summary.elevation_profile[0].distance_m, 0.0);
        assert_eq!(summary.elevation_profile[63].distance_m, 990.0);
        assert_eq!(summary.elevation_profile[63].elevation_m, 199.0);
        assert_eq!(summary.elevation_profile[1].elevation_m, 101.6);
        assert_eq!(
            summary.canonical_hash,
            hash_canonical_ride(&activity, CURRENT_PARSER_VERSION).unwrap()
        );
        assert_eq!(
            summary.distance_m,
            compute_activity_metrics(&activity, 200).unwrap().distance_m
        );
    }

    #[test]
    fn profile_omits_missing_elevation_and_reset_distance() {
        for (distance, elevation) in [
            (vec![0.0, 10.0, 5.0], vec![10.0, 20.0, 30.0]),
            (vec![0.0, 10.0, 20.0], vec![f32::NAN; 3]),
            (vec![0.0, 0.0, 0.0], vec![10.0, 20.0, 30.0]),
        ] {
            let activity = ParsedActivity {
                time_ms: vec![0, 1000, 2000],
                dist_m: Some(distance),
                elevation_m: Some(elevation),
                ..ParsedActivity::default()
            };
            assert!(summarize_activity(&activity, CURRENT_PARSER_VERSION, 200)
                .unwrap()
                .elevation_profile
                .is_empty());
        }
    }

    #[test]
    fn profile_skips_duplicate_distances_and_missing_samples() {
        let activity = ParsedActivity {
            time_ms: vec![0, 1000, 2000, 3000, 4000],
            dist_m: Some(vec![0.0, 0.0, 10.0, 20.0, 30.0]),
            elevation_m: Some(vec![10.0, 99.0, f32::NAN, 30.0, 40.0]),
            ..ParsedActivity::default()
        };
        let profile = summarize_activity(&activity, CURRENT_PARSER_VERSION, 200)
            .unwrap()
            .elevation_profile;
        assert_eq!(profile.len(), 3);
        assert_eq!(profile[0].elevation_m, 10.0);
        assert_eq!(profile[1].distance_m, 15.0);
        assert_eq!(profile[1].elevation_m, 25.0);
    }

    #[test]
    fn profile_uses_gps_distance_when_device_distance_is_absent() {
        let activity = ParsedActivity {
            time_ms: vec![0, 1000],
            lat_e7: Some(vec![400000000, 400010000]),
            lon_e7: Some(vec![-750000000, -750000000]),
            elevation_m: Some(vec![10.0, 20.0]),
            ..ParsedActivity::default()
        };
        let profile = summarize_activity(&activity, CURRENT_PARSER_VERSION, 200)
            .unwrap()
            .elevation_profile;
        assert_eq!(profile.len(), 2);
        assert!((profile[1].distance_m - 111.1949).abs() < 0.001);
    }

    #[test]
    fn empty_recording_summary_matches_the_existing_canonicalizer() {
        let started_at_ms = 1_800_000_000_000;
        let summary = summarize_empty_recording(started_at_ms, None).unwrap();
        let activity = ParsedActivity {
            started_at_ms,
            ..ParsedActivity::default()
        };

        assert_eq!(summary.parser_version, CURRENT_PARSER_VERSION);
        assert_eq!(
            summary.canonical_hash,
            hash_canonical_ride(&activity, CURRENT_PARSER_VERSION,).unwrap()
        );
        assert_eq!(
            summary.canonical_hash_hex,
            "fa1a9ed56658039448abbaf137468252d3b39514ed5223de946950ac6f76f0f5"
        );
        assert_eq!(summary.started_at_ms, started_at_ms);
        assert_eq!(summary.sample_count, 0);
        assert_eq!(summary.duration_s, 0);
        assert_eq!(summary.moving_time_s, 0);
        assert_eq!(summary.tile_count_res10, 0);
    }

    #[test]
    fn empty_gpx_remains_a_parse_error() {
        let empty_gpx = br#"<?xml version="1.0"?><gpx><trk><trkseg/></trk></gpx>"#;
        let result = parse_ride_summary(empty_gpx.to_vec(), "gpx".to_string(), 200, None);
        assert!(matches!(result, Err(WorkoutParseError::Parse { .. })));
    }
}
