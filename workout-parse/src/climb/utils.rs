//! Climb detection utility functions.

use super::constants::*;
use super::types::TileSample;

/// Calculate distance in meters between two lat/lon points using Haversine formula.
pub fn haversine_m(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let phi1 = lat1.to_radians();
    let phi2 = lat2.to_radians();
    let dphi = (lat2 - lat1).to_radians();
    let dlambda = (lon2 - lon1).to_radians();

    let a = (dphi / 2.0).sin().powi(2) + phi1.cos() * phi2.cos() * (dlambda / 2.0).sin().powi(2);

    EARTH_RADIUS_M * 2.0 * a.sqrt().atan2((1.0 - a).sqrt())
}

/// Initial bearing (forward azimuth) in degrees from point 1 to point 2.
/// Returns 0..360 where 0=North, 90=East, 180=South, 270=West.
pub fn bearing_degrees(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    let phi1 = lat1.to_radians();
    let phi2 = lat2.to_radians();
    let dlambda = (lon2 - lon1).to_radians();

    let x = dlambda.sin() * phi2.cos();
    let y = phi1.cos() * phi2.sin() - phi1.sin() * phi2.cos() * dlambda.cos();

    let theta = x.atan2(y).to_degrees();
    (theta + 360.0) % 360.0
}

/// Absolute angular difference between two bearings, accounting for 360° wraparound.
/// Always returns a value in 0..180.
fn angular_diff(a: f64, b: f64) -> f64 {
    let diff = (a - b).abs() % 360.0;
    if diff > 180.0 {
        360.0 - diff
    } else {
        diff
    }
}

// ---------------------------------------------------------------------------
// Junction Detection (Menger Curvature)
// ---------------------------------------------------------------------------

/// Maximum circumradius (meters) to classify as a junction.
/// Road engineering: junction turning radii are 5-25m, road curves are 50-500m+.
/// At 1Hz GPS with a 5-sample window (~25m per triangle side), the measured
/// circumradius is larger than the physical road curb radius because GPS samples
/// straddle the turn arc. Empirically, genuine T-intersections in Philly produce
/// R=30-55m at this sampling rate. 60m captures the top ~20 sharpest turns per
/// ride while filtering 500+ gentle curves (R > 80m).
const JUNCTION_MAX_RADIUS_M: f64 = 60.0;

/// Minimum heading change (degrees) required in addition to small radius.
/// Prevents collinear GPS jitter from triggering false junctions.
const JUNCTION_MIN_ANGLE_DEG: f64 = 25.0;

/// Number of samples on each side of the candidate point for curvature computation.
/// 5 samples at 1Hz ≈ 25m of road at cycling speed — enough to capture the turn
/// geometry without averaging it away.
const JUNCTION_WINDOW: usize = 5;

/// Minimum speed (m/s) to consider a point. Below this, GPS jitter dominates
/// bearing and curvature calculations.
const JUNCTION_MIN_SPEED_MPS: f64 = 1.5;

/// Deduplication window: junctions within this many samples of each other
/// are merged, keeping the one with the smallest radius (tightest turn).
const JUNCTION_DEDUP_WINDOW: usize = 15;

/// Classification of a detected junction point.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum JunctionType {
    /// R < 30m AND speed dip > 40% — very likely a road intersection
    Strong,
    /// R < 30m AND no significant speed dip — sharp curve or switchback
    SharpCurve,
    /// R < 50m AND speed dip > 60% — probable intersection (light/stop sign)
    Probable,
}

/// Information about a detected junction/turn point.
#[derive(Debug, Clone)]
pub struct JunctionInfo {
    /// Sample index in the ride
    pub sample_idx: usize,
    /// Menger curvature circumradius in meters (smaller = sharper)
    pub radius_m: f64,
    /// Heading change in degrees
    pub angle_deg: f64,
    /// Speed at junction / average speed in context (0-1, lower = more deceleration)
    pub speed_ratio: f64,
    /// Classification based on radius + speed
    pub junction_type: JunctionType,
}

/// Compute the area of a triangle defined by three GPS points, in square meters.
///
/// Uses the cross-product formula in a local Cartesian approximation.
/// Accurate for small triangles (< 1km sides) which is always the case
/// for cycling GPS at 5-sample spacing.
fn triangle_area_m(lat1: f64, lon1: f64, lat2: f64, lon2: f64, lat3: f64, lon3: f64) -> f64 {
    // Convert to local meters using the midpoint latitude for scale
    let mid_lat = ((lat1 + lat2 + lat3) / 3.0).to_radians();
    let m_per_deg_lat = 111_320.0; // meters per degree latitude (approximate)
    let m_per_deg_lon = 111_320.0 * mid_lat.cos(); // meters per degree longitude

    let x1 = 0.0;
    let y1 = 0.0;
    let x2 = (lon2 - lon1) * m_per_deg_lon;
    let y2 = (lat2 - lat1) * m_per_deg_lat;
    let x3 = (lon3 - lon1) * m_per_deg_lon;
    let y3 = (lat3 - lat1) * m_per_deg_lat;

    // Area via cross product: 0.5 * |v1 × v2|
    (0.5 * ((x2 - x1) * (y3 - y1) - (y2 - y1) * (x3 - x1))).abs()
}

/// Extract valid GPS coordinates from a sample, or return None.
fn extract_gps(sample: &TileSample) -> Option<(f64, f64)> {
    match (sample.lat, sample.lon) {
        (Some(lat), Some(lon)) if is_valid_gps(lat, lon) => Some((lat, lon)),
        _ => None,
    }
}

/// Detect road junctions using Menger curvature radius.
///
/// The Menger curvature of three points is 1/R where R is the circumradius
/// of the triangle they form. A tight junction (T-intersection, sharp corner)
/// has R < 30m. A gentle road curve has R > 50m. This cleanly separates
/// junctions from curves, unlike angular thresholds which fire on both.
///
/// Returns a Vec of `JunctionInfo` sorted by sample index, deduplicated
/// within `JUNCTION_DEDUP_WINDOW` samples (keeping the tightest turn).
pub fn detect_junctions(samples: &[TileSample]) -> Vec<JunctionInfo> {
    let n = samples.len();
    if n < JUNCTION_WINDOW * 2 + 1 {
        return vec![];
    }

    // Pre-compute per-step speeds for speed-ratio classification
    let speeds: Vec<f64> = (0..n)
        .map(|i| {
            if i == 0 {
                return 0.0;
            }
            match (extract_gps(&samples[i - 1]), extract_gps(&samples[i])) {
                (Some((la1, lo1)), Some((la2, lo2))) => {
                    let dt = (samples[i].t - samples[i - 1].t) as f64;
                    if dt > 0.0 {
                        haversine_m(la1, lo1, la2, lo2) / dt
                    } else {
                        0.0
                    }
                }
                _ => 0.0,
            }
        })
        .collect();

    let mut candidates: Vec<JunctionInfo> = Vec::new();

    for i in JUNCTION_WINDOW..n.saturating_sub(JUNCTION_WINDOW) {
        // Extract GPS for the three anchor points
        let (lat1, lon1) = match extract_gps(&samples[i - JUNCTION_WINDOW]) {
            Some(p) => p,
            None => continue,
        };
        let (lat2, lon2) = match extract_gps(&samples[i]) {
            Some(p) => p,
            None => continue,
        };
        let (lat3, lon3) = match extract_gps(&samples[i + JUNCTION_WINDOW]) {
            Some(p) => p,
            None => continue,
        };

        // Check minimum speed over the window (skip stationary GPS jitter)
        let dt = (samples[i + JUNCTION_WINDOW].t - samples[i - JUNCTION_WINDOW].t) as f64;
        let span_dist = haversine_m(lat1, lon1, lat3, lon3);
        if dt <= 0.0 || span_dist / dt < JUNCTION_MIN_SPEED_MPS {
            continue;
        }

        // Compute triangle side lengths
        let a = haversine_m(lat1, lon1, lat2, lon2);
        let b = haversine_m(lat2, lon2, lat3, lon3);
        let c = haversine_m(lat1, lon1, lat3, lon3);

        // Compute triangle area
        let area = triangle_area_m(lat1, lon1, lat2, lon2, lat3, lon3);

        // Skip near-collinear points (straight road)
        if area < 0.5 {
            continue;
        }

        // Menger curvature circumradius: R = (a * b * c) / (4 * area)
        let radius = (a * b * c) / (4.0 * area);

        // Also compute heading change for the angle threshold
        let approach = bearing_degrees(lat1, lon1, lat2, lon2);
        let departure = bearing_degrees(lat2, lon2, lat3, lon3);
        let angle = angular_diff(approach, departure);

        // Primary filter: small radius AND meaningful angle
        if radius > JUNCTION_MAX_RADIUS_M || angle < JUNCTION_MIN_ANGLE_DEG {
            continue;
        }

        // Compute speed ratio: speed at junction vs context speed
        // Context = average speed over ±15 samples (excluding the junction zone)
        let context_start = i.saturating_sub(15);
        let context_end = (i + 15).min(n - 1);
        let context_speeds: Vec<f64> = speeds[context_start..=context_end]
            .iter()
            .enumerate()
            .filter(|(j, _)| {
                let idx = context_start + j;
                idx < i.saturating_sub(3) || idx > i + 3
            })
            .map(|(_, &s)| s)
            .filter(|&s| s > 0.5)
            .collect();

        let context_avg = if context_speeds.is_empty() {
            5.0 // default cycling speed
        } else {
            context_speeds.iter().sum::<f64>() / context_speeds.len() as f64
        };

        let junction_speed = speeds[i.saturating_sub(2)..=(i + 2).min(n - 1)]
            .iter()
            .cloned()
            .fold(f64::MAX, f64::min); // minimum speed in the junction zone

        let speed_ratio = if context_avg > 0.5 {
            junction_speed / context_avg
        } else {
            1.0
        };

        // Classify
        let junction_type = if radius < JUNCTION_MAX_RADIUS_M && speed_ratio < 0.6 {
            JunctionType::Strong
        } else if radius < JUNCTION_MAX_RADIUS_M {
            JunctionType::SharpCurve
        } else {
            continue;
        };

        candidates.push(JunctionInfo {
            sample_idx: i,
            radius_m: radius,
            angle_deg: angle,
            speed_ratio,
            junction_type,
        });
    }

    // Deduplicate: within JUNCTION_DEDUP_WINDOW, keep the tightest turn (smallest radius)
    let mut result: Vec<JunctionInfo> = Vec::new();
    for candidate in candidates {
        if let Some(last) = result.last() {
            if candidate.sample_idx.saturating_sub(last.sample_idx) < JUNCTION_DEDUP_WINDOW {
                if candidate.radius_m < last.radius_m {
                    *result.last_mut().unwrap() = candidate;
                }
                continue;
            }
        }
        result.push(candidate);
    }

    result
}

/// Detect junctions and return just the sample indices.
///
/// This is the drop-in replacement for the old `detect_turns()` function,
/// maintaining the same return type for compatibility with the boundary
/// snap infrastructure in `refine_display_bounds`.
pub fn detect_turns(samples: &[TileSample]) -> Vec<usize> {
    detect_junctions(samples)
        .into_iter()
        .map(|j| j.sample_idx)
        .collect()
}

/// Apply simple moving average smoothing to elevation data.
///
/// Uses a centered window to reduce GPS noise while preserving climb shape.
pub fn smooth_elevations(elevations: &[f64], window: usize) -> Vec<f64> {
    if elevations.len() < window {
        return elevations.to_vec();
    }

    let half_window = window / 2;
    elevations
        .iter()
        .enumerate()
        .map(|(i, _)| {
            let start = i.saturating_sub(half_window);
            let end = (i + half_window + 1).min(elevations.len());
            let slice = &elevations[start..end];
            slice.iter().sum::<f64>() / slice.len() as f64
        })
        .collect()
}

/// Build cumulative ascent array for O(1) vertical gain queries.
///
/// This is critical for performance - allows any range query in constant time.
pub fn build_cumulative_ascent(smoothed_elevations: &[f64]) -> Vec<f64> {
    let mut cumulative = vec![0.0; smoothed_elevations.len()];
    for i in 1..smoothed_elevations.len() {
        let delta = smoothed_elevations[i] - smoothed_elevations[i - 1];
        cumulative[i] = cumulative[i - 1] + delta.max(0.0);
    }
    cumulative
}

/// Get vertical gain for a segment in O(1) time.
#[inline]
pub fn vert_gain(cumulative: &[f64], start: usize, end: usize) -> f64 {
    if end <= start || end >= cumulative.len() {
        return 0.0;
    }
    cumulative[end] - cumulative[start]
}

/// Calculate local gradient (%) at a specific index using forward-looking window.
pub fn calculate_local_gradient(samples: &[TileSample], smoothed: &[f64], idx: usize) -> f64 {
    let n = samples.len();
    if idx >= n - 1 {
        return 0.0;
    }

    let end_idx = (idx + GRADIENT_CALC_WINDOW).min(n - 1);
    if end_idx <= idx {
        return 0.0;
    }

    let elev_delta = smoothed[end_idx] - smoothed[idx];
    let time_delta = (samples[end_idx].t - samples[idx].t) as f64;

    if time_delta <= 0.0 {
        return 0.0;
    }

    // Estimate horizontal distance (~5m/s average cycling speed)
    let horiz_dist_m = time_delta * ESTIMATED_CYCLING_SPEED_MPS;
    if horiz_dist_m <= 0.0 {
        return 0.0;
    }

    (elev_delta / horiz_dist_m) * 100.0
}

/// Calculate gradient at a specific index using centered window with Haversine distance.
pub fn calculate_gradient_at(samples: &[TileSample], smoothed: &[f64], idx: usize) -> f64 {
    if idx < 1 || idx >= samples.len() {
        return 0.0;
    }

    let window_start = idx.saturating_sub(GRADIENT_WINDOW / 2);
    let window_end = (idx + GRADIENT_WINDOW / 2).min(samples.len() - 1);

    if window_end <= window_start {
        return 0.0;
    }

    let s_start = &samples[window_start];
    let s_end = &samples[window_end];

    // Calculate distance - prefer Haversine if GPS available
    let dist_m = match (s_start.lat, s_start.lon, s_end.lat, s_end.lon) {
        (Some(lat1), Some(lon1), Some(lat2), Some(lon2)) => haversine_m(lat1, lon1, lat2, lon2),
        _ => {
            // Fallback: estimate from time at ~5 m/s
            let time_delta = (s_end.t - s_start.t).abs() as f64;
            time_delta * ESTIMATED_CYCLING_SPEED_MPS
        }
    };

    if dist_m < 1.0 {
        return 0.0;
    }

    let elev_delta = smoothed[window_end] - smoothed[window_start];
    (elev_delta / dist_m) * 100.0
}

/// Check if GPS coordinates are valid (not sentinel values).
/// Rejects out-of-range coords and Null Island (0,0) which is a common
/// GPS-no-fix sentinel in cycling devices.
pub(crate) fn is_valid_gps(lat: f64, lon: f64) -> bool {
    lat.abs() <= 90.0 && lon.abs() <= 180.0 && !(lat == 0.0 && lon == 0.0)
}

/// Maximum single-step distance in meters (~180 km/h max cycling speed).
const MAX_STEP_DISTANCE_M: f64 = 500.0;

/// Calculate horizontal distance for a segment of samples.
/// Uses Haversine if GPS available, otherwise estimates from time.
/// Validates GPS coordinates and caps per-step distance to prevent
/// GPS spikes from inflating totals.
pub fn calculate_segment_distance(samples: &[TileSample]) -> Option<f64> {
    if samples.len() < 2 {
        return None;
    }

    let mut total_dist = 0.0;

    for i in 1..samples.len() {
        let prev = &samples[i - 1];
        let curr = &samples[i];

        let delta = match (prev.lat, prev.lon, curr.lat, curr.lon) {
            (Some(lat1), Some(lon1), Some(lat2), Some(lon2))
                if is_valid_gps(lat1, lon1) && is_valid_gps(lat2, lon2) =>
            {
                let d = haversine_m(lat1, lon1, lat2, lon2);
                d.min(MAX_STEP_DISTANCE_M)
            }
            _ => {
                // Fallback: estimate from time at ~5 m/s, capped to prevent
                // massive time gaps (device left on) from inflating distances.
                let time_delta = (curr.t - prev.t).abs() as f64;
                (time_delta * ESTIMATED_CYCLING_SPEED_MPS).min(MAX_STEP_DISTANCE_M)
            }
        };
        total_dist += delta;
    }

    if total_dist > 0.0 {
        Some(total_dist)
    } else {
        None
    }
}

/// Calculate average value for an optional field across samples.
pub fn calculate_average_power(samples: &[TileSample]) -> Option<f64> {
    let values: Vec<u16> = samples
        .iter()
        .filter_map(|s| s.power_w)
        .filter(|&p| p > 0)
        .collect();

    if values.is_empty() {
        return None;
    }

    Some(values.iter().map(|&p| p as f64).sum::<f64>() / values.len() as f64)
}

/// Calculate average heart rate across samples.
pub fn calculate_average_hr(samples: &[TileSample]) -> Option<u8> {
    let values: Vec<u8> = samples
        .iter()
        .filter_map(|s| s.hr_bpm)
        .filter(|&hr| hr > 0)
        .collect();

    if values.is_empty() {
        return None;
    }

    Some((values.iter().map(|&hr| hr as u32).sum::<u32>() / values.len() as u32) as u8)
}

/// Minimum GPS distance (meters) a rider must cover before barometric elevation
/// is trusted. Below this, the altimeter may still be calibrating.
const STARTUP_MIN_DISTANCE_M: f64 = 100.0;

/// Only examine the first N seconds for startup calibration drift.
const STARTUP_MAX_WINDOW_S: i64 = 180;

/// Find the sample index where the rider has moved far enough from the start
/// for the barometric altimeter to be trustworthy. Returns 0 if no startup
/// trim is needed (rider was already moving or no GPS available).
pub fn find_startup_end(samples: &[TileSample]) -> usize {
    if samples.len() < 10 {
        return 0;
    }

    let t_start = samples[0].t;
    let mut cumulative_dist = 0.0;

    for i in 1..samples.len() {
        // Only check within the startup window
        if samples[i].t - t_start > STARTUP_MAX_WINDOW_S {
            break;
        }

        // Compute step distance from GPS
        let step = match (
            samples[i - 1].lat,
            samples[i - 1].lon,
            samples[i].lat,
            samples[i].lon,
        ) {
            (Some(lat1), Some(lon1), Some(lat2), Some(lon2))
                if is_valid_gps(lat1, lon1) && is_valid_gps(lat2, lon2) =>
            {
                haversine_m(lat1, lon1, lat2, lon2).min(MAX_STEP_DISTANCE_M)
            }
            _ => continue, // No GPS — can't determine if moving, skip sample
        };

        cumulative_dist += step;
        if cumulative_dist >= STARTUP_MIN_DISTANCE_M {
            return i;
        }
    }

    // If we never reached the distance threshold within the window,
    // the rider may have been stationary the whole time. Only trim if
    // we checked at least some samples and the rider barely moved.
    if cumulative_dist < 30.0 {
        // Find the first sample past the startup window as fallback
        for i in 1..samples.len() {
            if samples[i].t - t_start > STARTUP_MAX_WINDOW_S {
                return i;
            }
        }
    }

    0 // No trim needed
}

/// Flatten elevation data in the startup calibration window by replacing
/// drifting samples with the anchor elevation at the first "moving" sample.
pub fn flatten_startup_calibration(samples: &mut [TileSample]) {
    let startup_end = find_startup_end(samples);
    if startup_end == 0 {
        return;
    }

    // Use the elevation at the startup_end as the anchor
    let anchor_elev = match samples[startup_end].elevation_m {
        Some(e) => e,
        None => return,
    };

    for sample in samples[..startup_end].iter_mut() {
        if sample.elevation_m.is_some() {
            sample.elevation_m = Some(anchor_elev);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_gps_sample(t: i64, lat: f64, lon: f64) -> TileSample {
        TileSample {
            t,
            tile_id: None,
            elevation_m: Some(100.0),
            power_w: None,
            hr_bpm: None,
            lat: Some(lat),
            lon: Some(lon),
        }
    }

    #[test]
    fn test_bearing_degrees() {
        // Due north
        let b = bearing_degrees(39.0, -75.0, 40.0, -75.0);
        assert!((b - 0.0).abs() < 1.0, "North bearing should be ~0, got {}", b);

        // Due east
        let b = bearing_degrees(39.0, -75.0, 39.0, -74.0);
        assert!((b - 90.0).abs() < 2.0, "East bearing should be ~90, got {}", b);

        // Due south
        let b = bearing_degrees(40.0, -75.0, 39.0, -75.0);
        assert!((b - 180.0).abs() < 1.0, "South bearing should be ~180, got {}", b);
    }

    #[test]
    fn test_angular_diff() {
        assert!((angular_diff(10.0, 350.0) - 20.0).abs() < 0.1);
        assert!((angular_diff(0.0, 180.0) - 180.0).abs() < 0.1);
        assert!((angular_diff(90.0, 270.0) - 180.0).abs() < 0.1);
        assert!((angular_diff(45.0, 45.0) - 0.0).abs() < 0.1);
    }

    #[test]
    fn test_triangle_area_nonzero() {
        // Three points forming a right triangle ~100m on each side
        let area = triangle_area_m(39.0, -75.0, 39.001, -75.0, 39.0, -75.001);
        assert!(area > 1000.0, "Triangle area should be >1000 sq m, got {}", area);
    }

    #[test]
    fn test_detect_junctions_straight_road() {
        // Ride going due north in a straight line — should detect zero junctions
        let samples: Vec<TileSample> = (0..100)
            .map(|i| make_gps_sample(i, 39.95 + (i as f64) * 0.00005, -75.16))
            .collect();
        let junctions = detect_junctions(&samples);
        assert_eq!(junctions.len(), 0, "Straight road should have no junctions");
    }

    #[test]
    fn test_detect_junctions_sharp_turn() {
        // Ride going north for 20 samples, then sharp 90° turn east for 20 samples
        let mut samples: Vec<TileSample> = Vec::new();
        let step = 0.00005; // ~5m per step

        // Going north
        for i in 0..20 {
            samples.push(make_gps_sample(i, 39.95 + (i as f64) * step, -75.16));
        }
        // Sharp turn: now going east
        let turn_lat = 39.95 + 20.0 * step;
        for i in 0..20 {
            samples.push(make_gps_sample(
                20 + i,
                turn_lat,
                -75.16 + (i as f64) * step,
            ));
        }

        let junctions = detect_junctions(&samples);
        assert!(
            !junctions.is_empty(),
            "Should detect at least one junction at the 90° turn"
        );

        // The junction should be near index 20 (the turn point)
        let turn_junction = &junctions[0];
        assert!(
            (turn_junction.sample_idx as i32 - 20).abs() <= JUNCTION_WINDOW as i32 + 2,
            "Junction should be near index 20, got {}",
            turn_junction.sample_idx
        );
        assert!(
            turn_junction.radius_m < JUNCTION_MAX_RADIUS_M + 10.0,
            "Junction radius should be < ~{}m, got {}",
            JUNCTION_MAX_RADIUS_M,
            turn_junction.radius_m
        );
    }

    #[test]
    fn test_detect_junctions_gentle_curve_ignored() {
        // Ride curving gently — large radius, should NOT be detected as junction
        let mut samples: Vec<TileSample> = Vec::new();
        let center_lat = 39.95;
        let center_lon = -75.16;
        let radius_deg = 0.005; // ~500m radius curve

        for i in 0..60 {
            let angle = (i as f64) * 1.5_f64.to_radians(); // 1.5 degrees per sample = gentle
            let lat = center_lat + radius_deg * angle.cos();
            let lon = center_lon + radius_deg * angle.sin();
            samples.push(make_gps_sample(i, lat, lon));
        }

        let junctions = detect_junctions(&samples);
        assert_eq!(
            junctions.len(),
            0,
            "Gentle curve (R~500m) should not produce junctions, got {}",
            junctions.len()
        );
    }

    #[test]
    fn test_haversine() {
        // Philly to NYC ~130km
        let dist = haversine_m(39.95, -75.16, 40.71, -74.00);
        assert!(
            (dist - 130_000.0).abs() < 15_000.0,
            "Expected ~130km, got {}",
            dist
        );
    }

    #[test]
    fn test_smooth_elevations() {
        let elevations = vec![100.0, 105.0, 103.0, 107.0, 110.0];
        let smoothed = smooth_elevations(&elevations, 3);
        assert_eq!(smoothed.len(), 5);
        // Middle values should be close to local averages
        assert!((smoothed[2] - 105.0).abs() < 2.0);
    }

    #[test]
    fn test_cumulative_ascent() {
        let elevations = vec![100.0, 110.0, 105.0, 115.0];
        let cumulative = build_cumulative_ascent(&elevations);
        // Should count: +10 (100→110), +0 (105→115 net), +10 (105→115) = 20m total
        assert!((cumulative[3] - 20.0).abs() < 0.1);
    }

    #[test]
    fn test_vert_gain() {
        let cumulative = vec![0.0, 10.0, 10.0, 20.0, 25.0];
        assert!((vert_gain(&cumulative, 0, 4) - 25.0).abs() < 0.1);
        assert!((vert_gain(&cumulative, 1, 3) - 10.0).abs() < 0.1);
    }
}
