//! Shared displayed-climb boundary refinement and contract checks.
//!
//! Candidate generators can disagree about where a climb "exists", but the
//! product should only expose segments that satisfy the same display contract.
//! This module owns that contract and the boundary trimming pass used before
//! final metrics are computed.

use super::types::TileSample;
use super::utils::{calculate_segment_distance, haversine_m, is_valid_gps};

/// Boundary trimming config shared across candidate generators.
#[derive(Debug, Clone, Copy)]
pub struct BoundaryRefinementConfig {
    /// Minimum local gradient (%) required to anchor a displayable boundary.
    pub trim_gradient_pct: f64,
    /// Window size in samples for local gradient estimation.
    pub gradient_window: usize,
    /// Maximum fraction of the original candidate span that can be trimmed away.
    pub max_trim_ratio: f64,
}

impl BoundaryRefinementConfig {
    pub const fn new(trim_gradient_pct: f64, gradient_window: usize, max_trim_ratio: f64) -> Self {
        Self {
            trim_gradient_pct,
            gradient_window,
            max_trim_ratio,
        }
    }
}

/// Hard product invariants for a displayed climb.
#[derive(Debug, Clone, Copy)]
pub struct DisplayClimbContract {
    /// Minimum net rise across displayed start/end boundaries.
    pub min_boundary_rise_m: f64,
    /// Displayed start/end rise must explain at least this fraction of total ascent.
    pub min_boundary_rise_ratio: f64,
    /// Descending inside the displayed window is tolerated, but bounded.
    pub max_downhill_contamination_ratio: f64,
}

impl DisplayClimbContract {
    pub const fn new(
        min_boundary_rise_m: f64,
        min_boundary_rise_ratio: f64,
        max_downhill_contamination_ratio: f64,
    ) -> Self {
        Self {
            min_boundary_rise_m,
            min_boundary_rise_ratio,
            max_downhill_contamination_ratio,
        }
    }
}

impl Default for DisplayClimbContract {
    fn default() -> Self {
        Self::new(8.0, 0.35, 0.5)
    }
}

/// Metrics for a refined displayed climb window.
#[derive(Debug, Clone, Copy)]
pub struct DisplaySegmentMetrics {
    pub time_s: u32,
    pub distance_m: f64,
    pub ascent_m: f64,
    pub descent_m: f64,
    pub boundary_rise_m: f64,
    pub avg_gradient_pct: f64,
    pub boundary_gradient_pct: f64,
    pub downhill_contamination_ratio: f64,
}

/// Maximum sample distance to search for a nearby turn when snapping boundaries.
/// ~25 samples at 1Hz cycling ≈ 125m of road. Needs to be generous because the
/// gradient walk often stops 15-25 samples from the nearest physical turn.
const BOUNDARY_SNAP_WINDOW: usize = 25;

/// Trim flat run-in/run-out and return the refined display window.
///
/// If `turn_indices` are provided, after the gradient walk finds the trim point,
/// it checks for a nearby GPS heading change (turn) and snaps the boundary there
/// instead. This makes climb boundaries align with road turns and intersections
/// — where riders intuitively feel climbs start and end.
pub fn refine_display_bounds(
    samples: &[TileSample],
    smoothed: &[f64],
    candidate_start: usize,
    candidate_end: usize,
    config: BoundaryRefinementConfig,
    turn_indices: Option<&[usize]>,
) -> (usize, usize) {
    let lo = candidate_start.min(candidate_end);
    let hi = candidate_start.max(candidate_end);
    let length = hi.saturating_sub(lo);

    let gradient_window = config.gradient_window.max(2);
    if length < gradient_window * 2 {
        return (lo, hi);
    }

    let max_trim = ((length as f64) * config.max_trim_ratio) as usize;

    // --- Forward walk: find start boundary ---
    let mut refined_start = lo;
    for idx in lo..(lo + max_trim).min(hi.saturating_sub(gradient_window)) {
        let gradient = local_gradient_forward(smoothed, samples, idx, gradient_window);
        if gradient >= config.trim_gradient_pct {
            refined_start = idx;
            break;
        }
    }

    // Snap start to nearby turn if one exists.
    // Use the snap window centered on the gradient-walk result — no additional
    // range constraint, because the gradient walk already ensured the result is
    // within reasonable bounds. The snap just nudges to a landmark.
    if let Some(turns) = turn_indices {
        if let Some(snapped) = snap_to_nearest_turn(
            turns,
            refined_start,
            refined_start.saturating_sub(BOUNDARY_SNAP_WINDOW),
            refined_start + BOUNDARY_SNAP_WINDOW,
        ) {
            refined_start = snapped;
        }
    }

    // --- Backward walk: find end boundary ---
    let mut refined_end = hi;
    let min_end = hi
        .saturating_sub(max_trim)
        .max(refined_start + gradient_window);
    for idx in (min_end..=hi).rev() {
        let gradient = local_gradient_backward(smoothed, samples, idx, gradient_window);
        if gradient >= config.trim_gradient_pct {
            refined_end = idx;
            break;
        }
    }

    // Snap end to nearby turn
    if let Some(turns) = turn_indices {
        if let Some(snapped) = snap_to_nearest_turn(
            turns,
            refined_end,
            refined_end.saturating_sub(BOUNDARY_SNAP_WINDOW),
            refined_end + BOUNDARY_SNAP_WINDOW,
        ) {
            refined_end = snapped;
        }
    }

    if refined_end <= refined_start + gradient_window {
        return (lo, hi);
    }

    (refined_start, refined_end)
}

/// Find the nearest turn index within BOUNDARY_SNAP_WINDOW of `target`,
/// constrained to `[range_lo, range_hi]`. Returns None if no turn is nearby.
fn snap_to_nearest_turn(
    turn_indices: &[usize],
    target: usize,
    range_lo: usize,
    range_hi: usize,
) -> Option<usize> {
    let snap_lo = target.saturating_sub(BOUNDARY_SNAP_WINDOW).max(range_lo);
    let snap_hi = (target + BOUNDARY_SNAP_WINDOW).min(range_hi);

    let mut best: Option<usize> = None;
    let mut best_dist = usize::MAX;

    for &turn in turn_indices {
        if turn >= snap_lo && turn <= snap_hi {
            let dist = if turn >= target {
                turn - target
            } else {
                target - turn
            };
            if dist < best_dist {
                best_dist = dist;
                best = Some(turn);
            }
        }
    }

    best
}

/// Find the gradient energy minimum in the zone between candidate_start and gradient_walk result.
/// This is the "onset backtracking" point -- the flattest spot in the trimmed-away approach zone.
/// Returns None if the zone is too small (<10 samples) or no clear minimum exists.
pub fn find_onset_minimum(
    smoothed: &[f64],
    samples: &[TileSample],
    candidate_bound: usize,      // persistence birth_idx (for start) or death_idx (for end)
    gradient_walk_result: usize,  // effort_start_idx or effort_end_idx from refine_display_bounds
    gradient_window: usize,       // same window used in gradient walk (7)
    is_start: bool,               // true = looking for start onset, false = end onset
) -> Option<usize> {
    // The zone is always between the two bounds, regardless of ordering.
    // For reversed pairs, birth_idx can be > effort_start_idx; for normal pairs,
    // death_idx can be < effort_end_idx. We just need the trimmed-away interval.
    let zone_lo = candidate_bound.min(gradient_walk_result);
    let zone_hi = candidate_bound.max(gradient_walk_result);

    // Zone must be at least 10 samples to be meaningful
    if zone_hi <= zone_lo || zone_hi - zone_lo < 10 {
        return None;
    }

    // Bounds check against smoothed/samples arrays
    if zone_hi >= smoothed.len() || zone_hi >= samples.len() {
        return None;
    }

    let mut min_energy = f64::MAX;
    let mut min_idx: Option<usize> = None;

    for idx in zone_lo..=zone_hi {
        let gradient_energy = if is_start {
            local_gradient_forward(smoothed, samples, idx, gradient_window).abs()
        } else {
            local_gradient_backward(smoothed, samples, idx, gradient_window).abs()
        };

        if gradient_energy < min_energy {
            min_energy = gradient_energy;
            min_idx = Some(idx);
        }
    }

    // Only return if the minimum is genuinely flat (< 0.8% gradient)
    if min_energy < 0.8 {
        min_idx
    } else {
        None
    }
}

/// Compute display metrics for a candidate window.
pub fn measure_display_segment(
    samples: &[TileSample],
    smoothed: &[f64],
    start_idx: usize,
    end_idx: usize,
) -> DisplaySegmentMetrics {
    let lo = start_idx.min(end_idx);
    let hi = start_idx.max(end_idx);
    if hi <= lo || hi >= samples.len() || hi >= smoothed.len() {
        return DisplaySegmentMetrics {
            time_s: 0,
            distance_m: 0.0,
            ascent_m: 0.0,
            descent_m: 0.0,
            boundary_rise_m: 0.0,
            avg_gradient_pct: 0.0,
            boundary_gradient_pct: 0.0,
            downhill_contamination_ratio: f64::INFINITY,
        };
    }

    let segment_samples = &samples[lo..=hi];
    let time_s = (samples[hi].t - samples[lo].t).max(0) as u32;
    let distance_m = calculate_segment_distance(segment_samples).unwrap_or(0.0);

    let mut ascent_m = 0.0;
    let mut descent_m = 0.0;
    for idx in (lo + 1)..=hi {
        let delta = smoothed[idx] - smoothed[idx - 1];
        if delta >= 0.0 {
            ascent_m += delta;
        } else {
            descent_m += -delta;
        }
    }

    let boundary_rise_m = smoothed[hi] - smoothed[lo];
    let avg_gradient_pct = if distance_m > 0.0 {
        (ascent_m / distance_m) * 100.0
    } else {
        0.0
    };
    let boundary_gradient_pct = if distance_m > 0.0 {
        (boundary_rise_m.max(0.0) / distance_m) * 100.0
    } else {
        0.0
    };
    let downhill_contamination_ratio = if ascent_m > 0.0 {
        descent_m / ascent_m
    } else if descent_m > 0.0 {
        f64::INFINITY
    } else {
        0.0
    };

    DisplaySegmentMetrics {
        time_s,
        distance_m,
        ascent_m,
        descent_m,
        boundary_rise_m,
        avg_gradient_pct,
        boundary_gradient_pct,
        downhill_contamination_ratio,
    }
}

/// Apply the shared hard contract for displayed climbs.
pub fn satisfies_display_contract(
    metrics: &DisplaySegmentMetrics,
    contract: DisplayClimbContract,
) -> bool {
    if metrics.time_s == 0 || metrics.distance_m <= 0.0 {
        return false;
    }
    if metrics.boundary_rise_m < contract.min_boundary_rise_m {
        return false;
    }
    if metrics.ascent_m <= 0.0 {
        return false;
    }
    if metrics.boundary_rise_m < metrics.ascent_m * contract.min_boundary_rise_ratio {
        return false;
    }
    if metrics.downhill_contamination_ratio > contract.max_downhill_contamination_ratio {
        return false;
    }
    true
}

fn local_gradient_forward(
    smoothed: &[f64],
    samples: &[TileSample],
    idx: usize,
    window: usize,
) -> f64 {
    let end = (idx + window).min(smoothed.len() - 1);
    if end <= idx {
        return 0.0;
    }
    let elev_delta = smoothed[end] - smoothed[idx];
    segment_gradient_pct(samples, idx, end, elev_delta)
}

fn local_gradient_backward(
    smoothed: &[f64],
    samples: &[TileSample],
    idx: usize,
    window: usize,
) -> f64 {
    let start = idx.saturating_sub(window);
    if idx <= start {
        return 0.0;
    }
    let elev_delta = smoothed[idx] - smoothed[start];
    segment_gradient_pct(samples, start, idx, elev_delta)
}

fn segment_gradient_pct(
    samples: &[TileSample],
    start_idx: usize,
    end_idx: usize,
    elev_delta: f64,
) -> f64 {
    if end_idx <= start_idx {
        return 0.0;
    }
    let time_delta = (samples[end_idx].t - samples[start_idx].t) as f64;
    if time_delta <= 0.0 {
        return 0.0;
    }

    let dist_m = match (
        samples[start_idx].lat,
        samples[start_idx].lon,
        samples[end_idx].lat,
        samples[end_idx].lon,
    ) {
        (Some(lat1), Some(lon1), Some(lat2), Some(lon2))
            if is_valid_gps(lat1, lon1) && is_valid_gps(lat2, lon2) =>
        {
            haversine_m(lat1, lon1, lat2, lon2)
        }
        _ => time_delta * 5.0,
    };

    if dist_m < 1.0 {
        return 0.0;
    }
    (elev_delta / dist_m) * 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample(t: i64, elevation_m: f64) -> TileSample {
        TileSample {
            t,
            tile_id: None,
            elevation_m: Some(elevation_m),
            power_w: None,
            hr_bpm: None,
            lat: None,
            lon: None,
        }
    }

    #[test]
    fn test_refine_display_bounds_trims_flat_run_in_out() {
        let samples = vec![
            sample(0, 100.0),
            sample(10, 100.0),
            sample(20, 100.5),
            sample(30, 105.0),
            sample(40, 112.0),
            sample(50, 118.0),
            sample(60, 121.0),
            sample(70, 121.2),
            sample(80, 121.2),
            sample(90, 121.1),
        ];
        let smoothed: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();

        let (start, end) = refine_display_bounds(
            &samples,
            &smoothed,
            0,
            samples.len() - 1,
            BoundaryRefinementConfig::new(2.0, 2, 0.5),
            None,
        );

        assert!(start > 0, "flat run-in should be trimmed");
        assert!(end < samples.len() - 1, "flat run-out should be trimmed");
        assert!(end > start);
    }

    #[test]
    fn test_display_contract_accepts_clean_climb() {
        let samples = vec![
            sample(0, 100.0),
            sample(10, 103.0),
            sample(20, 108.0),
            sample(30, 115.0),
            sample(40, 123.0),
        ];
        let smoothed: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let metrics = measure_display_segment(&samples, &smoothed, 0, samples.len() - 1);

        assert!(satisfies_display_contract(
            &metrics,
            DisplayClimbContract::default()
        ));
    }

    #[test]
    fn test_display_contract_rejects_weak_boundary_rise() {
        let samples = vec![
            sample(0, 100.0),
            sample(10, 120.0),
            sample(20, 112.0),
            sample(30, 121.0),
            sample(40, 108.0),
        ];
        let smoothed: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let metrics = measure_display_segment(&samples, &smoothed, 0, samples.len() - 1);

        assert!(metrics.ascent_m > 20.0);
        assert!(metrics.boundary_rise_m < 10.0);
        assert!(!satisfies_display_contract(
            &metrics,
            DisplayClimbContract::default()
        ));
    }
}
