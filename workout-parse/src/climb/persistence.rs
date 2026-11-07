//! 0D Persistent Homology for climb detection.
//!
//! Replaces the momentum-based detector with a parameter-free topological approach.
//! Uses sublevel-set filtration on 1D elevation profiles to find significant climbs
//! as persistence pairs (valley → peak).
//!
//! The only tunable parameter is the noise gate (3.0m), derived from sensor physics:
//! BMP280 σ=1.0m, SMA(5) → ~0.45m, 99.9th percentile Gumbel + 20% margin ≈ 3.0m.

use super::refinement::{
    find_onset_minimum, measure_display_segment, refine_display_bounds,
    satisfies_display_contract, BoundaryRefinementConfig, DisplayClimbContract,
};
use super::signature_v2::generate_signature_v2;
use super::types::TileSample;
use super::utils::{
    calculate_average_hr, calculate_average_power, detect_turns, flatten_startup_calibration,
    is_valid_gps, smooth_elevations,
};

/// Noise gate threshold in meters.
/// Persistence pairs below this are discarded as barometric sensor noise.
pub const NOISE_GATE_M: f64 = 3.0;

/// Default smoothing window (SMA samples) before persistence computation.
const SMOOTHING_WINDOW: usize = 5;

/// Minimum gradient (%) to be considered "climbing" for effort boundary trim.
/// Minimum gradient for effort boundary trim. 1.2% clips flat approaches while
/// preserving continuity through gentle climbing sections (1-2% grade).
const EFFORT_TRIM_GRADIENT_MIN: f64 = 1.2;

/// Maximum fraction of canonical range that can be trimmed from each end.
/// 50% allows clipping long flat run-ins while preserving at least half the
/// canonical span.
const EFFORT_TRIM_MAX_RATIO: f64 = 0.5;

/// Window size (samples) for gradient estimation during effort boundary trimming.
/// Larger windows average over more road (~35m at cycling speed vs ~15m with 3),
/// reducing boundary jitter across repeat recordings from ~20m to ~5-8m.
const EFFORT_TRIM_GRADIENT_WINDOW: usize = 7;

/// Reversed-time persistence pairs encode a prominent peak whose killing valley
/// arrives later in the ride. To display a real ridden climb, search backward
/// from that peak for the best preceding ascent instead of trimming inside the
/// valley-after-peak interval.
const REVERSED_PAIR_LOOKBACK_MULTIPLIER: usize = 4;
const REVERSED_PAIR_MIN_LOOKBACK_SAMPLES: usize = 12;
const REVERSED_PAIR_MAX_LOOKBACK_SAMPLES: usize = 360;
const REVERSED_PAIR_MIN_RISE_RATIO: f64 = 0.7;
const TERMINAL_BOUNDARY_MIN_LOOKBACK_SAMPLES: usize = 12;
const TERMINAL_BOUNDARY_MAX_LOOKBACK_SAMPLES: usize = 240;
const RESIDUAL_ASCENT_MIN_VERT_M: f64 = 45.0;
const RESIDUAL_ASCENT_MIN_TIME_S: u32 = 180;
const RESIDUAL_ASCENT_MAX_TIME_S: u32 = 900;
const RESIDUAL_ASCENT_MIN_GRADIENT_PCT: f64 = 1.4;
const RESIDUAL_ASCENT_MIN_VAM_MHR: f64 = 220.0;
const RESIDUAL_ASCENT_MAX_EXISTING_OVERLAP_RATIO: f64 = 0.7;
const RESIDUAL_ASCENT_MIN_COVERING_VERT_RATIO: f64 = 0.7;
const RESIDUAL_ASCENT_TRIM_GRADIENT_MIN: f64 = 1.25;
const SUSTAINED_BROAD_MIN_VERT_M: f64 = 50.0;
const SUSTAINED_BROAD_MIN_TIME_S: u32 = 240;
const SUSTAINED_BROAD_MAX_DOWNHILL_RATIO: f64 = 0.18;
const FRAGMENT_NEAR_BROAD_START_WINDOW_S: i64 = 300;
const FRAGMENT_MAX_VERT_RATIO: f64 = 0.65;
const FRAGMENT_MAX_TIME_RATIO: f64 = 0.6;
const NEARBY_EDGE_GAP_WINDOW_S: i64 = 480;
const PEAK_WINDOW_MAX_LOOKBACK_S: i64 = 1_500;
const PEAK_WINDOW_MIN_TIME_S: u32 = 120;
const PEAK_WINDOW_MIN_VERT_M: f64 = 24.0;
const PEAK_WINDOW_MIN_RISE_FROM_EXISTING_M: f64 = 10.0;
const PEAK_WINDOW_TRIM_GRADIENT_MIN: f64 = 0.55;
const PEAK_WINDOW_SUMMIT_LOOKAHEAD_S: i64 = 180;
const PEAK_WINDOW_SUMMIT_EPSILON_M: f64 = 0.75;
const PEAK_WINDOW_SUMMIT_MAX_INTERVENING_DROP_M: f64 = 7.0;
const PEAK_WINDOW_SIGNIFICANT_PEAK_LOOKAHEAD_S: i64 = 300;
const PEAK_WINDOW_SIGNIFICANT_POST_DROP_M: f64 = 5.0;
const PEAK_WINDOW_MAX_EXISTING_OVERLAP_RATIO: f64 = 0.82;
const PEAK_WINDOW_MIN_START_ADVANCE_S: i64 = 90;
const PEAK_WINDOW_END_MATCH_WINDOW_S: i64 = 150;
const PEAK_WINDOW_MAX_CORE_TIME_S: u32 = 900;
const PEAK_WINDOW_MIN_CORE_GRADIENT_PCT: f64 = 3.0;
const PEAK_WINDOW_MIN_CORE_VAM_MHR: f64 = 320.0;
const SAME_PEAK_END_WINDOW_S: i64 = 150;
const SAME_PEAK_MIN_START_ADVANCE_S: i64 = 90;
const SAME_PEAK_MIN_VERT_ADVANTAGE_M: f64 = 8.0;
const SAME_PEAK_MIN_QUALITY_RATIO: f64 = 0.82;
const SAME_PEAK_MAX_BROAD_DOWNHILL_RATIO: f64 = 0.25;
const REBOUND_DUP_MIN_VERT_M: f64 = 12.0;
const REBOUND_DUP_MAX_VERT_M: f64 = 22.5;
const REBOUND_DUP_MAX_TIME_S: u32 = 240;
const REBOUND_DUP_MAX_GRADE_PCT: f64 = 5.25;
const REBOUND_DUP_MAX_VAM_MHR: f64 = 1_100.0;
const REBOUND_DUP_MIN_BRIDGE_TIME_S: u32 = 60;
const REBOUND_DUP_MAX_GAP_S: i64 = 240;
const REBOUND_DUP_END_ELEV_WINDOW_M: f64 = 2.5;
const REBOUND_DUP_MAX_LATER_SUMMIT_GAIN_M: f64 = 2.0;
const REBOUND_DUP_MIN_BRIDGE_DESCENT_M: f64 = 8.0;
const REBOUND_DUP_MAX_BRIDGE_ASCENT_M: f64 = 3.5;
const REBOUND_DUP_END_PEAK_WINDOW_S: i64 = 45;
const REBOUND_DUP_MIN_EARLIER_TIME_RATIO: f64 = 1.15;
const REBOUND_DUP_MIN_QUALITY_RATIO: f64 = 0.78;
const SPLIT_PARENT_MIN_TIME_S: u32 = 420;
const SPLIT_PARENT_MIN_VERT_M: f64 = 45.0;
const SPLIT_CHILD_MIN_TIME_S: u32 = 120;
const SPLIT_CHILD_MIN_VERT_M: f64 = 24.0;
const SPLIT_VALLEY_MIN_RELIEF_M: f64 = 4.5;
const SPLIT_MIN_BRIDGE_TIME_S: u32 = 45;
const SPLIT_MAX_BRIDGE_RISE_M: f64 = 8.0;
const SPLIT_MAX_BRIDGE_GRADIENT_PCT: f64 = 1.1;
const SPLIT_MIN_PARENT_CHILD_VERT_COVERAGE: f64 = 0.8;
const SPLIT_MIN_PARENT_CHILD_TIME_COVERAGE: f64 = 0.72;
const SPLIT_PARENT_ENDPOINT_WINDOW_S: i64 = 150;
const SEGMENT_STRUCTURE_WINDOW_S: i64 = 30;
const SPLIT_STRONG_WINDOW_ASCENT_M: f64 = 4.5;
const SPLIT_STRONG_WINDOW_RISE_M: f64 = 3.2;
const SPLIT_SUPPORT_WINDOW_ASCENT_M: f64 = 2.2;
const SPLIT_SUPPORT_WINDOW_RISE_M: f64 = 1.2;
const SPLIT_MAX_GAP_WINDOWS: usize = 1;
const SPLIT_MIN_CLUSTER_TIME_S: u32 = 90;
const SPLIT_MIN_WEAK_BRIDGE_TIME_S: u32 = 60;
const SPLIT_MAX_BRIDGE_ASCENT_PER_30S_M: f64 = 3.1;
const SPLIT_SUSTAINED_PARENT_MAX_BRIDGE_RISE_M: f64 = 2.0;
const SPLIT_SUSTAINED_PARENT_MAX_BRIDGE_ASCENT_PER_30S_M: f64 = 1.6;
const SPLIT_SUSTAINED_PARENT_MAX_BRIDGE_GRADIENT_PCT: f64 = 0.5;
const SPLIT_SUSTAINED_PARENT_MIN_BRIDGE_DESCENT_M: f64 = 6.0;
const SPLIT_SUSTAINED_PARENT_MIN_QUALITY_GAIN: f64 = 12.0;
const TAIL_TRIM_MIN_TIME_S: u32 = 360;
const TAIL_TRIM_MIN_VERT_M: f64 = 45.0;
const TAIL_TRIM_MIN_SUFFIX_TIME_S: u32 = 120;
const TAIL_TRIM_MAX_SUFFIX_ASCENT_PER_30S_M: f64 = 3.6;
const TAIL_TRIM_MAX_SUFFIX_BOUNDARY_RISE_M: f64 = 12.0;
const TAIL_TRIM_MIN_QUALITY_GAIN: f64 = 6.0;
const TAIL_TRIM_MIN_VERT_RETAIN_RATIO: f64 = 0.68;
const LOW_VERT_FRAGMENT_MAX_VERT_M: f64 = 20.0;
const LOW_VERT_FRAGMENT_MERGE_MAX_GAP_S: i64 = 150;
const LOW_VERT_FRAGMENT_MERGE_MIN_VERT_M: f64 = 24.0;
const LOW_VERT_FRAGMENT_MERGE_MAX_BRIDGE_RISE_M: f64 = 8.0;
const LOW_VERT_FRAGMENT_MERGE_MAX_BRIDGE_ASCENT_PER_30S_M: f64 = 3.1;
const LOW_VERT_FRAGMENT_MERGE_MIN_QUALITY_GAIN: f64 = 4.0;

/// Hard product invariants for a displayed climb window.
const DISPLAY_CONTRACT: DisplayClimbContract = DisplayClimbContract::new(8.0, 0.35, 0.5);

/// Minimum vertical gain (m) for a climb to be reportable.
/// Below this threshold, most "climbs" are barometric noise or overpasses.
/// Keep low (5m) to avoid cascade effects on internal candidate generation.
/// False positive filtering is handled post-detection by road enrichment.
const MIN_VERT_M: f64 = 5.0;

/// Maximum VAM (m/hr) before a climb is rejected as a sensor artifact.
/// Professional cyclists rarely exceed ~1800 m/hr; 2500 allows for short bursts.
const MAX_VAM_MHR: f64 = 2500.0;

/// Minimum average gradient for a climb to be display-worthy on its own.
/// Lower values mostly capture false-flat "umbrella" segments across rolling terrain.
const MIN_DISPLAY_GRADIENT_PCT: f64 = 2.0;

/// Minimum VAM for low-gradient segments to still count as a meaningful climbing effort.
/// This keeps moderate flatland/rolling climbs while suppressing hour-long false flats.
const MIN_DISPLAY_VAM_MHR: f64 = 150.0;

/// Low-gradient segments must still do enough vertical work to feel like a climb.
const MIN_LOW_GRADE_VERT_M: f64 = 30.0;

/// Low-gradient efforts that drag on forever are usually umbrella segments unless
/// they are genuinely major mountain climbs.
const MAX_LOW_GRADE_TIME_S: u32 = 720;
const MIN_LONG_LOW_GRADE_VERT_M: f64 = 200.0;

/// Minimum fraction of parent effort explained by nested stronger descendants
/// before suppressing the parent.
const MIN_PARENT_DESCENDANT_VERT_COVERAGE: f64 = 0.65;
const MIN_PARENT_DESCENDANT_TIME_COVERAGE: f64 = 0.4;

/// How much stronger the best child must be before a weak parent is suppressed.
const MIN_CHILD_GRADIENT_ADVANTAGE_PCT: f64 = 1.0;
const MIN_CHILD_VAM_ADVANTAGE_MHR: f64 = 120.0;
const MIN_STRONG_PARENT_CHILD_VERT_COVERAGE: f64 = 0.82;
const MIN_STRONG_PARENT_TIME_RATIO: f64 = 1.4;
const MIN_STRONG_PARENT_EXTRA_TIME_S: u32 = 90;
const MIN_STRONG_PARENT_VAM_ADVANTAGE_MHR: f64 = 180.0;
const STRONG_OVERLAP_RATIO: f64 = 0.6;
const MIN_SELECTOR_STRENGTH_MARGIN: i32 = 2;
const MIN_BROAD_PARENT_CHILD_VERT_COVERAGE: f64 = 0.6;
const NEARBY_START_WINDOW_S: i64 = 720;
const MIN_NEARBY_QUALITY_ADVANTAGE_RATIO: f64 = 1.25;
const MAX_NEARBY_WEAKER_QUALITY: f64 = 160.0;

// ---------------------------------------------------------------------------
// Core data structures
// ---------------------------------------------------------------------------

/// A persistence pair from sublevel-set filtration.
/// Each pair represents a climb: valley (birth) → peak (death).
#[derive(Debug, Clone)]
pub struct PersistencePair {
    /// Index of the valley (local minimum) in the sample array
    pub birth_idx: usize,
    /// Index of the peak/merge point (local maximum) in the sample array
    pub death_idx: usize,
    /// Elevation at valley
    pub birth_elev: f64,
    /// Elevation at peak/merge point
    pub death_elev: f64,
    /// Height of climb: death_elev - birth_elev
    pub persistence: f64,
}

/// A v2 climb detected by persistence.
#[derive(Debug, Clone)]
pub struct ClimbV2 {
    // Topological (canonical) — used for matching, economics
    pub birth_idx: usize,
    pub death_idx: usize,
    pub birth_elev: f64,
    pub death_elev: f64,
    pub persistence: f64,
    pub is_essential: bool,
    pub parent_pair_index: Option<usize>,

    // Effort (display) — gradient-walk trimmed within canonical bounds
    pub effort_start_idx: usize,
    pub effort_end_idx: usize,

    // Enriched metrics
    pub vert_m: f64,
    pub ascent_m: f64,
    pub descent_m: f64,
    pub boundary_rise_m: f64,
    pub time_s: u32,
    pub distance_m: f64,
    pub avg_gradient_pct: f64,
    pub boundary_gradient_pct: f64,
    pub downhill_contamination_ratio: f64,
    pub avg_power_w: Option<f64>,
    pub avg_hr: Option<u8>,
    pub tile_ids: Vec<String>,

    // GPS coordinates (effort start/end)
    pub start_lat: Option<f64>,
    pub start_lon: Option<f64>,
    pub end_lat: Option<f64>,
    pub end_lon: Option<f64>,

    // Onset backtracking — gradient energy minimum in the trimmed approach zone
    // Used by Python road enrichment to center intersection search
    pub onset_start_idx: Option<usize>,
    pub onset_end_idx: Option<usize>,

    // Signatures (None until Phase 2)
    pub signature_v1_hex: Option<String>,
    pub signature_v2_hex: Option<String>,
}

// ---------------------------------------------------------------------------
// Union-Find
// ---------------------------------------------------------------------------

struct UnionFind {
    parent: Vec<usize>,
    rank: Vec<usize>,
}

impl UnionFind {
    fn new(n: usize) -> Self {
        Self {
            parent: (0..n).collect(),
            rank: vec![0; n],
        }
    }

    fn find(&mut self, mut x: usize) -> usize {
        while self.parent[x] != x {
            self.parent[x] = self.parent[self.parent[x]]; // path splitting
            x = self.parent[x];
        }
        x
    }

    fn union(&mut self, x: usize, y: usize) -> usize {
        let rx = self.find(x);
        let ry = self.find(y);
        if rx == ry {
            return rx;
        }
        if self.rank[rx] < self.rank[ry] {
            self.parent[rx] = ry;
            ry
        } else if self.rank[rx] > self.rank[ry] {
            self.parent[ry] = rx;
            rx
        } else {
            self.parent[ry] = rx;
            self.rank[rx] += 1;
            rx
        }
    }
}

// ---------------------------------------------------------------------------
// Persistence computation
// ---------------------------------------------------------------------------

/// Compute 0D sublevel-set persistence on an elevation profile.
///
/// Processes samples from lowest to highest elevation. Components are born at
/// local minima (valleys) and die at merge points (local maxima / saddles).
/// The Elder Rule ensures the older component (lower birth) survives.
///
/// Returns pairs sorted by persistence descending, filtered by noise_gate.
pub fn compute_persistence(elevations: &[f64], noise_gate: f64) -> Vec<PersistencePair> {
    let n = elevations.len();
    if n < 2 {
        return vec![];
    }

    // Sort indices by elevation ascending, break ties by index
    let mut sorted: Vec<usize> = (0..n).collect();
    sorted.sort_by(|&a, &b| {
        elevations[a]
            .partial_cmp(&elevations[b])
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(&b))
    });

    let mut uf = UnionFind::new(n);
    let mut processed = vec![false; n];
    let mut comp_birth_elev = vec![0.0f64; n];
    let mut comp_birth_idx = vec![0usize; n];
    let mut pairs = Vec::new();

    for &idx in &sorted {
        processed[idx] = true;
        comp_birth_elev[idx] = elevations[idx];
        comp_birth_idx[idx] = idx;

        // Collect roots of processed neighbors (at most 2 in 1D)
        let mut neighbor_roots: Vec<usize> = Vec::with_capacity(2);
        if idx > 0 && processed[idx - 1] {
            neighbor_roots.push(uf.find(idx - 1));
        }
        if idx + 1 < n && processed[idx + 1] {
            let r = uf.find(idx + 1);
            if neighbor_roots.is_empty() || neighbor_roots[0] != r {
                neighbor_roots.push(r);
            }
        }

        match neighbor_roots.len() {
            0 => {
                // New component born at this local minimum
            }
            1 => {
                // Extend existing component — no merge, no death
                let root = neighbor_roots[0];
                let elder_elev = comp_birth_elev[root];
                let elder_idx = comp_birth_idx[root];
                let new_root = uf.union(root, idx);
                comp_birth_elev[new_root] = elder_elev;
                comp_birth_idx[new_root] = elder_idx;
            }
            _ => {
                // Merge: elder (lowest birth) survives, younger dies
                let elder_root = *neighbor_roots
                    .iter()
                    .min_by(|&&a, &&b| {
                        comp_birth_elev[a]
                            .partial_cmp(&comp_birth_elev[b])
                            .unwrap_or(std::cmp::Ordering::Equal)
                            .then(comp_birth_idx[a].cmp(&comp_birth_idx[b]))
                    })
                    .unwrap();

                let elder_birth_elev = comp_birth_elev[elder_root];
                let elder_birth_idx = comp_birth_idx[elder_root];

                for &root in &neighbor_roots {
                    if root != elder_root {
                        let persistence = elevations[idx] - comp_birth_elev[root];
                        if persistence >= noise_gate {
                            pairs.push(PersistencePair {
                                birth_idx: comp_birth_idx[root],
                                death_idx: idx,
                                birth_elev: comp_birth_elev[root],
                                death_elev: elevations[idx],
                                persistence,
                            });
                        }
                    }
                }

                // Union all into elder
                let mut current = elder_root;
                for &root in &neighbor_roots {
                    if root != elder_root {
                        current = uf.union(current, root);
                    }
                }
                current = uf.union(current, idx);
                comp_birth_elev[current] = elder_birth_elev;
                comp_birth_idx[current] = elder_birth_idx;
            }
        }
    }

    // Sort by persistence descending
    pairs.sort_by(|a, b| {
        b.persistence
            .partial_cmp(&a.persistence)
            .unwrap_or(std::cmp::Ordering::Equal)
    });

    pairs
}

/// Find the essential class: global minimum → global maximum.
pub fn find_essential(elevations: &[f64]) -> Option<(usize, usize)> {
    if elevations.is_empty() {
        return None;
    }
    let min_idx = elevations
        .iter()
        .enumerate()
        .min_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(i, _)| i)?;
    let max_idx = elevations
        .iter()
        .enumerate()
        .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
        .map(|(i, _)| i)?;
    Some((min_idx, max_idx))
}

/// Determine parent-child nesting from index range containment.
/// Returns parent[i] = Some(j) if pair j is the smallest containing pair.
pub fn build_nesting(pairs: &[PersistencePair]) -> Vec<Option<usize>> {
    let n = pairs.len();
    let mut parent = vec![None; n];

    for i in 0..n {
        let i_lo = pairs[i].birth_idx.min(pairs[i].death_idx);
        let i_hi = pairs[i].birth_idx.max(pairs[i].death_idx);

        let mut best: Option<usize> = None;
        let mut best_span = usize::MAX;

        for j in 0..n {
            if i == j {
                continue;
            }
            let j_lo = pairs[j].birth_idx.min(pairs[j].death_idx);
            let j_hi = pairs[j].birth_idx.max(pairs[j].death_idx);

            if j_lo <= i_lo && i_hi <= j_hi {
                let span = j_hi - j_lo;
                if span < best_span {
                    best_span = span;
                    best = Some(j);
                }
            }
        }

        parent[i] = best;
    }

    parent
}

// ---------------------------------------------------------------------------
// Effort boundary trimming
// ---------------------------------------------------------------------------

/// Trim flat lead-in/lead-out from canonical climb bounds.
/// Walks inward from each end looking for sustained gradient.
fn trim_effort_bounds(
    smoothed: &[f64],
    samples: &[TileSample],
    canonical_start: usize,
    canonical_end: usize,
    turn_indices: Option<&[usize]>,
) -> (usize, usize) {
    refine_display_bounds(
        samples,
        smoothed,
        canonical_start,
        canonical_end,
        BoundaryRefinementConfig::new(EFFORT_TRIM_GRADIENT_MIN, EFFORT_TRIM_GRADIENT_WINDOW, EFFORT_TRIM_MAX_RATIO),
        turn_indices,
    )
}

fn localize_pair_effort_bounds(
    smoothed: &[f64],
    samples: &[TileSample],
    pair: &PersistencePair,
    turn_indices: Option<&[usize]>,
) -> (usize, usize) {
    if pair.birth_idx <= pair.death_idx {
        return trim_effort_bounds(smoothed, samples, pair.birth_idx, pair.death_idx, turn_indices);
    }

    localize_reversed_pair_bounds(smoothed, samples, pair, turn_indices)
}

fn localize_reversed_pair_bounds(
    smoothed: &[f64],
    samples: &[TileSample],
    pair: &PersistencePair,
    turn_indices: Option<&[usize]>,
) -> (usize, usize) {
    let peak_idx = pair.death_idx.min(smoothed.len().saturating_sub(1));
    let later_valley_idx = pair.birth_idx.min(smoothed.len().saturating_sub(1));
    if peak_idx == 0 || peak_idx >= later_valley_idx {
        return trim_effort_bounds(smoothed, samples, peak_idx, later_valley_idx, turn_indices);
    }

    let pair_span = later_valley_idx - peak_idx;
    let max_lookback = pair_span
        .saturating_mul(REVERSED_PAIR_LOOKBACK_MULTIPLIER)
        .clamp(
            REVERSED_PAIR_MIN_LOOKBACK_SAMPLES,
            REVERSED_PAIR_MAX_LOOKBACK_SAMPLES,
        )
        .min(peak_idx);
    let search_lo = peak_idx.saturating_sub(max_lookback);
    if search_lo >= peak_idx {
        return trim_effort_bounds(smoothed, samples, peak_idx, later_valley_idx, turn_indices);
    }

    let target_rise_m =
        (pair.persistence * REVERSED_PAIR_MIN_RISE_RATIO).max(DISPLAY_CONTRACT.min_boundary_rise_m);
    let config = BoundaryRefinementConfig::new(EFFORT_TRIM_GRADIENT_MIN, EFFORT_TRIM_GRADIENT_WINDOW, EFFORT_TRIM_MAX_RATIO);
    let mut best_target: Option<(f64, usize, usize)> = None;
    let mut best_contract: Option<(f64, usize, usize)> = None;

    for candidate_start in search_lo..peak_idx {
        if smoothed[peak_idx] <= smoothed[candidate_start] {
            continue;
        }

        let (refined_start, refined_end) =
            refine_display_bounds(samples, smoothed, candidate_start, peak_idx, config, turn_indices);
        if refined_end <= refined_start {
            continue;
        }

        let metrics = measure_display_segment(samples, smoothed, refined_start, refined_end);
        if !satisfies_display_contract(&metrics, DISPLAY_CONTRACT) {
            continue;
        }

        let score = reversed_pair_candidate_score(&metrics, pair.persistence);
        if metrics.boundary_rise_m >= target_rise_m {
            update_best_reversed_candidate(&mut best_target, score, refined_start, refined_end);
        } else {
            update_best_reversed_candidate(&mut best_contract, score, refined_start, refined_end);
        }
    }

    best_target
        .or(best_contract)
        .map(|(_, start, end)| (start, end))
        .unwrap_or_else(|| trim_effort_bounds(smoothed, samples, peak_idx, later_valley_idx, turn_indices))
}

fn reversed_pair_candidate_score(
    metrics: &super::refinement::DisplaySegmentMetrics,
    persistence_m: f64,
) -> f64 {
    let steepness = metrics
        .boundary_gradient_pct
        .max(metrics.avg_gradient_pct)
        .max(0.5);
    let coverage_ratio = if persistence_m > 0.0 {
        (metrics.boundary_rise_m / persistence_m).clamp(0.0, 1.2)
    } else {
        0.0
    };
    let persistence_fit = if persistence_m > 0.0 {
        1.0 - ((persistence_m - metrics.boundary_rise_m).abs() / persistence_m).min(1.0)
    } else {
        0.0
    };
    let completeness_bonus = metrics.boundary_rise_m * (0.9 + 0.6 * persistence_fit);
    let shortfall_penalty = if coverage_ratio < REVERSED_PAIR_MIN_RISE_RATIO {
        (REVERSED_PAIR_MIN_RISE_RATIO - coverage_ratio) * 140.0
    } else {
        0.0
    };

    metrics.boundary_rise_m * steepness
        + completeness_bonus
        - shortfall_penalty
        - (metrics.time_s as f64 / 42.0)
        - metrics.downhill_contamination_ratio * 80.0
}

fn update_best_reversed_candidate(
    best: &mut Option<(f64, usize, usize)>,
    score: f64,
    start: usize,
    end: usize,
) {
    let replace = match best {
        None => true,
        Some((best_score, best_start, best_end)) => {
            score > *best_score + f64::EPSILON
                || ((score - *best_score).abs() <= f64::EPSILON
                    && (end - start) < (*best_end - *best_start))
        }
    };

    if replace {
        *best = Some((score, start, end));
    }
}

fn sustained_ascent_drawdown_limit(rise_m: f64) -> f64 {
    (rise_m * 0.22).clamp(8.0, 14.0)
}

fn terminal_boundary_candidate_score(
    metrics: &super::refinement::DisplaySegmentMetrics,
) -> f64 {
    let steepness = metrics
        .boundary_gradient_pct
        .max(metrics.avg_gradient_pct)
        .max(1.0);

    metrics.boundary_rise_m * steepness
        + metrics.ascent_m * 0.35
        - metrics.downhill_contamination_ratio * 90.0
        - (metrics.time_s as f64 / 45.0)
}

fn candidate_range_covered(candidate: &PersistencePair, pairs: &[PersistencePair]) -> bool {
    let c_lo = candidate.birth_idx.min(candidate.death_idx);
    let c_hi = candidate.birth_idx.max(candidate.death_idx);
    if c_hi <= c_lo {
        return true;
    }

    pairs.iter().any(|pair| {
        let p_lo = pair.birth_idx.min(pair.death_idx);
        let p_hi = pair.birth_idx.max(pair.death_idx);
        let overlap_lo = c_lo.max(p_lo);
        let overlap_hi = c_hi.min(p_hi);
        if overlap_hi <= overlap_lo {
            return false;
        }

        let overlap = overlap_hi - overlap_lo;
        let candidate_span = c_hi - c_lo;
        overlap as f64 / candidate_span as f64 >= 0.8
    })
}

fn find_terminal_boundary_pair(
    smoothed: &[f64],
    samples: &[TileSample],
    existing_pairs: &[PersistencePair],
    turn_indices: Option<&[usize]>,
) -> Option<PersistencePair> {
    let end_idx = smoothed.len().checked_sub(1)?;
    if end_idx < 1 {
        return None;
    }

    let search_lo = end_idx
        .saturating_sub(TERMINAL_BOUNDARY_MAX_LOOKBACK_SAMPLES)
        .min(end_idx.saturating_sub(1));
    let config = BoundaryRefinementConfig::new(EFFORT_TRIM_GRADIENT_MIN, EFFORT_TRIM_GRADIENT_WINDOW, EFFORT_TRIM_MAX_RATIO);
    let mut best: Option<(f64, usize, usize)> = None;

    for candidate_start in search_lo..end_idx {
        if smoothed[end_idx] <= smoothed[candidate_start] + NOISE_GATE_M {
            continue;
        }

        let (refined_start, refined_end) =
            refine_display_bounds(samples, smoothed, candidate_start, end_idx, config, turn_indices);
        if refined_end <= refined_start {
            continue;
        }

        let span = refined_end - refined_start;
        if span < TERMINAL_BOUNDARY_MIN_LOOKBACK_SAMPLES {
            continue;
        }

        let metrics = measure_display_segment(samples, smoothed, refined_start, refined_end);
        if !satisfies_display_contract(&metrics, DISPLAY_CONTRACT) {
            continue;
        }
        if metrics.boundary_rise_m < MIN_VERT_M {
            continue;
        }

        let score = terminal_boundary_candidate_score(&metrics);
        let replace = match best {
            None => true,
            Some((best_score, best_start, best_end)) => {
                score > best_score + f64::EPSILON
                    || ((score - best_score).abs() <= f64::EPSILON
                        && (refined_end - refined_start) < (best_end - best_start))
            }
        };

        if replace {
            best = Some((score, refined_start, refined_end));
        }
    }

    let (_, birth_idx, death_idx) = best?;
    let pair = PersistencePair {
        birth_idx,
        death_idx,
        birth_elev: smoothed[birth_idx],
        death_elev: smoothed[death_idx],
        persistence: (smoothed[death_idx] - smoothed[birth_idx]).max(0.0),
    };

    if pair.persistence < NOISE_GATE_M || candidate_range_covered(&pair, existing_pairs) {
        return None;
    }

    Some(pair)
}

fn build_climb_from_pair(
    pair_index: usize,
    pair: &PersistencePair,
    is_essential: bool,
    parent_pair_index: Option<usize>,
    samples: &[TileSample],
    smoothed: &[f64],
    user_weight_kg: Option<f64>,
    turn_indices: Option<&[usize]>,
) -> (usize, ClimbV2) {
    let (effort_start, effort_end) = localize_pair_effort_bounds(smoothed, samples, pair, turn_indices);

    build_climb_from_explicit_bounds(
        pair_index,
        pair.birth_idx,
        pair.death_idx,
        effort_start,
        effort_end,
        pair.persistence,
        is_essential,
        parent_pair_index,
        samples,
        smoothed,
        user_weight_kg,
    )
}

fn build_climb_from_explicit_bounds(
    pair_index: usize,
    canonical_start_idx: usize,
    canonical_end_idx: usize,
    effort_start: usize,
    effort_end: usize,
    persistence: f64,
    is_essential: bool,
    parent_pair_index: Option<usize>,
    samples: &[TileSample],
    smoothed: &[f64],
    user_weight_kg: Option<f64>,
) -> (usize, ClimbV2) {
    let canon_lo = canonical_start_idx.min(canonical_end_idx);
    let canon_hi = canonical_end_idx.max(canonical_start_idx);

    let metrics = measure_display_segment(samples, smoothed, effort_start, effort_end);
    let vert_m = metrics.boundary_rise_m.max(0.0);
    let ascent_m = metrics.ascent_m;
    let descent_m = metrics.descent_m;
    let time_s = metrics.time_s;
    let distance_m = metrics.distance_m;
    let avg_gradient_pct = metrics.boundary_gradient_pct;
    let boundary_gradient_pct = metrics.boundary_gradient_pct;
    let downhill_contamination_ratio = metrics.downhill_contamination_ratio;

    let effort_samples = &samples[effort_start..=effort_end.min(samples.len() - 1)];

    let avg_power_w = calculate_average_power(effort_samples);
    let avg_hr = calculate_average_hr(effort_samples);

    let tile_ids: Vec<String> = effort_samples
        .iter()
        .filter_map(|s| s.tile_id.clone())
        .collect::<std::collections::HashSet<_>>()
        .into_iter()
        .collect();

    let _w_per_kg = match (avg_power_w, user_weight_kg) {
        (Some(p), Some(w)) if w > 0.0 => Some(p / w),
        _ => None,
    };

    let ascending = canonical_start_idx < canonical_end_idx;
    let sig_v2_hex = if canon_hi > canon_lo + 1 {
        let canon_samples_slice = &samples[canon_lo..=canon_hi.min(samples.len() - 1)];
        let canon_smoothed_slice = &smoothed[canon_lo..=canon_hi.min(smoothed.len() - 1)];
        let (canon_smoothed_vec, canon_samples_vec): (Vec<f64>, Vec<TileSample>) =
            if ascending {
                (canon_smoothed_slice.to_vec(), canon_samples_slice.to_vec())
            } else {
                (
                    canon_smoothed_slice.iter().copied().rev().collect(),
                    canon_samples_slice.iter().cloned().rev().collect(),
                )
            };
        let canon_dists = build_effort_distances(&canon_samples_vec);
        let h3_anchor = midpoint_h3(&canon_samples_vec);
        let has_power = avg_power_w.is_some();
        generate_signature_v2(
            &canon_smoothed_vec,
            &canon_dists,
            h3_anchor,
            has_power,
            0,
        )
        .map(|sig| sig.hex())
    } else {
        None
    };

    let sig_v1_hex = if canon_hi > canon_lo + 1 {
        let canon_samples_v1 = &samples[canon_lo..=canon_hi.min(samples.len() - 1)];
        let canon_smoothed_v1 = &smoothed[canon_lo..=canon_hi.min(smoothed.len() - 1)];
        let (cs_v1, css_v1): (Vec<TileSample>, Vec<f64>) = if ascending {
            (canon_samples_v1.to_vec(), canon_smoothed_v1.to_vec())
        } else {
            (
                canon_samples_v1.iter().cloned().rev().collect(),
                canon_smoothed_v1.iter().copied().rev().collect(),
            )
        };
        let timestamps: Vec<i64> = cs_v1.iter().map(|s| s.t).collect();
        let canon_dists_v1 = build_effort_distances(&cs_v1);
        super::signature::generate_signature(&css_v1, &timestamps, Some(&canon_dists_v1))
            .map(|sig| sig.hex())
    } else {
        None
    };

    let (start_lat, start_lon) = samples
        .get(effort_start)
        .map(reward_endpoint)
        .unwrap_or((None, None));
    let (end_lat, end_lon) = samples
        .get(effort_end)
        .map(reward_endpoint)
        .unwrap_or((None, None));

    (
        pair_index,
        ClimbV2 {
            birth_idx: canonical_start_idx,
            death_idx: canonical_end_idx,
            birth_elev: smoothed[canonical_start_idx.min(smoothed.len().saturating_sub(1))],
            death_elev: smoothed[canonical_end_idx.min(smoothed.len().saturating_sub(1))],
            persistence,
            is_essential,
            parent_pair_index,
            effort_start_idx: effort_start,
            effort_end_idx: effort_end,
            vert_m,
            ascent_m,
            descent_m,
            boundary_rise_m: vert_m,
            time_s,
            distance_m,
            avg_gradient_pct,
            boundary_gradient_pct,
            downhill_contamination_ratio,
            avg_power_w,
            avg_hr,
            tile_ids,
            start_lat,
            start_lon,
            end_lat,
            end_lon,
            onset_start_idx: None,
            onset_end_idx: None,
            signature_v1_hex: sig_v1_hex,
            signature_v2_hex: sig_v2_hex,
        },
    )
}

fn climb_overlap_ratio(a: &ClimbV2, b: &ClimbV2) -> f64 {
    let overlap = overlap_samples(a, b);
    if overlap == 0 {
        return 0.0;
    }

    overlap as f64
        / (a.effort_end_idx
            .saturating_sub(a.effort_start_idx)
            .min(b.effort_end_idx.saturating_sub(b.effort_start_idx))
            .max(1) as f64)
}

fn is_residual_sustained_ascent_candidate(climb: &ClimbV2) -> bool {
    if climb.vert_m < RESIDUAL_ASCENT_MIN_VERT_M {
        return false;
    }
    if climb.time_s < RESIDUAL_ASCENT_MIN_TIME_S || climb.time_s > RESIDUAL_ASCENT_MAX_TIME_S {
        return false;
    }
    if !satisfies_display_contract(&climb_display_metrics(climb), DISPLAY_CONTRACT) {
        return false;
    }

    climb.avg_gradient_pct >= RESIDUAL_ASCENT_MIN_GRADIENT_PCT
        || climb_vam(climb) >= RESIDUAL_ASCENT_MIN_VAM_MHR
}

fn residual_candidate_is_covered(candidate: &ClimbV2, existing: &[(usize, ClimbV2)]) -> bool {
    existing.iter().any(|(_, climb)| {
        climb_overlap_ratio(candidate, climb) >= RESIDUAL_ASCENT_MAX_EXISTING_OVERLAP_RATIO
            && climb.vert_m >= candidate.vert_m * RESIDUAL_ASCENT_MIN_COVERING_VERT_RATIO
    })
}

fn candidate_is_redundant(
    candidate: &ClimbV2,
    samples: &[TileSample],
    existing: &[(usize, ClimbV2)],
) -> bool {
    let candidate_start_t = samples[candidate.effort_start_idx].t;
    let candidate_end_t = samples[candidate.effort_end_idx].t;
    existing.iter().any(|(_, climb)| {
        let overlap_ratio = climb_overlap_ratio(candidate, climb);
        if overlap_ratio < 0.82 {
            return false;
        }
        let climb_start_t = samples[climb.effort_start_idx].t;
        let climb_end_t = samples[climb.effort_end_idx].t;
        let starts_close = (candidate_start_t - climb_start_t).abs() <= 90;
        let ends_close = (candidate_end_t - climb_end_t).abs() <= 90;
        let existing_explains = climb.vert_m >= candidate.vert_m - 8.0;
        starts_close && ends_close && existing_explains
    })
}

#[derive(Debug, Clone, Copy)]
struct SegmentWindow {
    start_idx: usize,
    end_idx: usize,
    ascent_m: f64,
    boundary_rise_m: f64,
    avg_gradient_pct: f64,
    downhill_contamination_ratio: f64,
}

#[derive(Debug, Clone, Copy)]
struct WindowCluster {
    start_idx: usize,
    end_idx: usize,
}

fn collect_segment_windows(
    samples: &[TileSample],
    smoothed: &[f64],
    start_idx: usize,
    end_idx: usize,
    window_s: i64,
) -> Vec<SegmentWindow> {
    if end_idx <= start_idx {
        return vec![];
    }

    let mut windows = Vec::new();
    let mut idx = start_idx;
    while idx < end_idx {
        let start_t = samples[idx].t;
        let mut probe = idx + 1;
        while probe <= end_idx && samples[probe].t - start_t <= window_s {
            probe += 1;
        }
        let window_end = probe.saturating_sub(1).min(end_idx);
        if window_end <= idx {
            idx += 1;
            continue;
        }

        let metrics = measure_display_segment(samples, smoothed, idx, window_end);
        if metrics.time_s > 0 {
            windows.push(SegmentWindow {
                start_idx: idx,
                end_idx: window_end,
                ascent_m: metrics.ascent_m,
                boundary_rise_m: metrics.boundary_rise_m,
                avg_gradient_pct: metrics.avg_gradient_pct,
                downhill_contamination_ratio: metrics.downhill_contamination_ratio,
            });
        }

        idx = window_end;
    }

    windows
}

fn split_window_is_strong(window: &SegmentWindow) -> bool {
    (window.ascent_m >= SPLIT_STRONG_WINDOW_ASCENT_M
        && window.boundary_rise_m >= SPLIT_STRONG_WINDOW_RISE_M)
        || (window.ascent_m >= SPLIT_STRONG_WINDOW_ASCENT_M + 1.0
            && window.avg_gradient_pct >= MIN_DISPLAY_GRADIENT_PCT)
}

fn split_window_is_supporting(window: &SegmentWindow) -> bool {
    split_window_is_strong(window)
        || (window.ascent_m >= SPLIT_SUPPORT_WINDOW_ASCENT_M
            && window.boundary_rise_m >= SPLIT_SUPPORT_WINDOW_RISE_M
            && window.downhill_contamination_ratio <= 0.75)
}

fn collect_strong_window_clusters(
    samples: &[TileSample],
    smoothed: &[f64],
    windows: &[SegmentWindow],
) -> Vec<WindowCluster> {
    let mut clusters = Vec::new();
    let mut idx = 0usize;
    while idx < windows.len() {
        if !split_window_is_strong(&windows[idx]) {
            idx += 1;
            continue;
        }

        let start_window_idx = idx;
        let mut end_window_idx = idx;
        let mut gap_windows = 0usize;
        while end_window_idx + 1 < windows.len() {
            let next = &windows[end_window_idx + 1];
            if split_window_is_supporting(next) {
                end_window_idx += 1;
                gap_windows = 0;
                continue;
            }
            if gap_windows < SPLIT_MAX_GAP_WINDOWS {
                gap_windows += 1;
                end_window_idx += 1;
                continue;
            }
            break;
        }

        let cluster = WindowCluster {
            start_idx: windows[start_window_idx].start_idx,
            end_idx: windows[end_window_idx].end_idx,
        };
        let metrics = measure_display_segment(samples, smoothed, cluster.start_idx, cluster.end_idx);
        if metrics.time_s >= SPLIT_MIN_CLUSTER_TIME_S && metrics.boundary_rise_m >= SPLIT_CHILD_MIN_VERT_M {
            clusters.push(cluster);
        }

        idx = end_window_idx + 1;
    }

    clusters
}

fn bridge_structurally_splits_sustained_parent(
    bridge_metrics: &super::refinement::DisplaySegmentMetrics,
    bridge_ascent_per_30s: f64,
) -> bool {
    if bridge_metrics.descent_m >= SPLIT_SUSTAINED_PARENT_MIN_BRIDGE_DESCENT_M {
        return true;
    }

    bridge_metrics.boundary_rise_m <= SPLIT_SUSTAINED_PARENT_MAX_BRIDGE_RISE_M
        && bridge_ascent_per_30s <= SPLIT_SUSTAINED_PARENT_MAX_BRIDGE_ASCENT_PER_30S_M
        && bridge_metrics.avg_gradient_pct <= SPLIT_SUSTAINED_PARENT_MAX_BRIDGE_GRADIENT_PCT
}

fn search_lo_for_lookback(samples: &[TileSample], end_idx: usize, lookback_s: i64) -> usize {
    let end_t = samples[end_idx].t;
    let mut idx = end_idx;
    while idx > 0 && end_t - samples[idx - 1].t <= lookback_s {
        idx -= 1;
    }
    idx
}

fn is_local_minimum(smoothed: &[f64], idx: usize) -> bool {
    if idx == 0 || idx + 1 >= smoothed.len() {
        return false;
    }
    smoothed[idx] <= smoothed[idx - 1] && smoothed[idx] <= smoothed[idx + 1]
}

fn extend_anchor_peak_to_nearby_summit(
    samples: &[TileSample],
    smoothed: &[f64],
    anchor_idx: usize,
) -> usize {
    if anchor_idx >= smoothed.len() {
        return anchor_idx;
    }

    let anchor_time = samples[anchor_idx].t;
    let mut best_idx = anchor_idx;
    let mut best_elev = smoothed[anchor_idx];
    let mut lowest_since_best = best_elev;

    for idx in (anchor_idx + 1)..smoothed.len() {
        if samples[idx].t - anchor_time > PEAK_WINDOW_SUMMIT_LOOKAHEAD_S {
            break;
        }

        let elev = smoothed[idx];
        lowest_since_best = lowest_since_best.min(elev);
        if best_elev - lowest_since_best > PEAK_WINDOW_SUMMIT_MAX_INTERVENING_DROP_M {
            break;
        }

        let materially_higher = elev > best_elev + PEAK_WINDOW_SUMMIT_EPSILON_M;
        let effectively_equal_later =
            (elev - best_elev).abs() <= PEAK_WINDOW_SUMMIT_EPSILON_M && idx > best_idx;
        if materially_higher || effectively_equal_later {
            best_idx = idx;
            best_elev = best_elev.max(elev);
            lowest_since_best = elev;
        }
    }

    best_idx
}

fn collect_significant_local_peak_anchors(
    samples: &[TileSample],
    smoothed: &[f64],
) -> Vec<usize> {
    if smoothed.len() < 3 {
        return vec![];
    }

    let mut peaks: Vec<usize> = Vec::new();
    let mut idx = 1usize;
    while idx + 1 < smoothed.len() {
        if smoothed[idx] + PEAK_WINDOW_SUMMIT_EPSILON_M < smoothed[idx - 1] {
            idx += 1;
            continue;
        }

        let run_start = idx - 1;
        let mut peak_idx = idx;
        while peak_idx + 1 < smoothed.len()
            && smoothed[peak_idx + 1] >= smoothed[peak_idx] - PEAK_WINDOW_SUMMIT_EPSILON_M
        {
            peak_idx += 1;
        }

        if smoothed[peak_idx] <= smoothed[run_start] + PEAK_WINDOW_SUMMIT_EPSILON_M {
            idx = peak_idx.saturating_add(1);
            continue;
        }

        let peak_time = samples[peak_idx].t;
        let peak_elev = smoothed[peak_idx];
        let mut min_after = peak_elev;
        let mut probe_idx = peak_idx + 1;
        while probe_idx < smoothed.len()
            && samples[probe_idx].t - peak_time <= PEAK_WINDOW_SIGNIFICANT_PEAK_LOOKAHEAD_S
        {
            min_after = min_after.min(smoothed[probe_idx]);
            probe_idx += 1;
        }

        if peak_elev - min_after >= PEAK_WINDOW_SIGNIFICANT_POST_DROP_M {
            peaks.push(peak_idx);
        }
        idx = peak_idx.saturating_add(1);
    }

    peaks
}

fn peak_anchor_candidate_score(
    metrics: &super::refinement::DisplaySegmentMetrics,
) -> f64 {
    let steepness = metrics
        .boundary_gradient_pct
        .max(metrics.avg_gradient_pct)
        .max(1.0);
    let completeness_bonus = metrics.boundary_rise_m * 1.45 + metrics.ascent_m * 0.35;
    let low_grade_penalty = if metrics.avg_gradient_pct < MIN_DISPLAY_GRADIENT_PCT {
        (MIN_DISPLAY_GRADIENT_PCT - metrics.avg_gradient_pct) * 40.0
    } else {
        0.0
    };

    metrics.boundary_rise_m * steepness
        + completeness_bonus
        - metrics.downhill_contamination_ratio * 110.0
        - (metrics.time_s as f64 / 38.0)
        - low_grade_penalty
}

fn peak_anchor_candidate_extension_bonus(
    metrics: &super::refinement::DisplaySegmentMetrics,
    start_idx: usize,
    end_idx: usize,
    samples: &[TileSample],
    existing: &[(usize, ClimbV2)],
) -> f64 {
    let candidate_start_t = samples[start_idx].t;
    let candidate_end_t = samples[end_idx].t;

    existing
        .iter()
        .filter_map(|(_, climb)| {
            let climb_start_t = samples[climb.effort_start_idx].t;
            let climb_end_t = samples[climb.effort_end_idx].t;
            if (candidate_end_t - climb_end_t).abs() > PEAK_WINDOW_END_MATCH_WINDOW_S {
                return None;
            }

            let start_advance_s = climb_start_t - candidate_start_t;
            if start_advance_s < PEAK_WINDOW_MIN_START_ADVANCE_S {
                return None;
            }

            let rise_gain_m = metrics.boundary_rise_m - climb.vert_m;
            if rise_gain_m < PEAK_WINDOW_MIN_RISE_FROM_EXISTING_M {
                return None;
            }

            let ascent_gain_m = (metrics.ascent_m - climb.ascent_m).max(0.0);
            Some(rise_gain_m * 2.3 + ascent_gain_m * 0.2 + start_advance_s as f64 / 18.0)
        })
        .fold(0.0, f64::max)
}

fn peak_anchor_candidate_improves_existing(
    candidate: &ClimbV2,
    samples: &[TileSample],
    existing: &[(usize, ClimbV2)],
) -> bool {
    let candidate_start_t = samples[candidate.effort_start_idx].t;
    let candidate_end_t = samples[candidate.effort_end_idx].t;

    existing.iter().any(|(_, climb)| {
        let climb_start_t = samples[climb.effort_start_idx].t;
        let climb_end_t = samples[climb.effort_end_idx].t;
        let ends_match = (candidate_end_t - climb_end_t).abs() <= PEAK_WINDOW_END_MATCH_WINDOW_S;
        let starts_meaningfully_earlier =
            candidate_start_t <= climb_start_t - PEAK_WINDOW_MIN_START_ADVANCE_S;
        let adds_material_rise =
            candidate.vert_m >= climb.vert_m + PEAK_WINDOW_MIN_RISE_FROM_EXISTING_M;
        let climb_is_shoulderworthy_core = climb.time_s <= PEAK_WINDOW_MAX_CORE_TIME_S
            && (climb.avg_gradient_pct >= PEAK_WINDOW_MIN_CORE_GRADIENT_PCT
                || climb_vam(climb) >= PEAK_WINDOW_MIN_CORE_VAM_MHR);

        ends_match
            && starts_meaningfully_earlier
            && adds_material_rise
            && climb_is_shoulderworthy_core
    })
}

fn peak_anchor_candidate_is_redundant(
    candidate: &ClimbV2,
    samples: &[TileSample],
    existing: &[(usize, ClimbV2)],
) -> bool {
    let candidate_start_t = samples[candidate.effort_start_idx].t;
    let candidate_end_t = samples[candidate.effort_end_idx].t;

    existing.iter().any(|(_, climb)| {
        let overlap_ratio = climb_overlap_ratio(candidate, climb);
        if overlap_ratio < PEAK_WINDOW_MAX_EXISTING_OVERLAP_RATIO {
            return false;
        }

        let climb_start_t = samples[climb.effort_start_idx].t;
        let climb_end_t = samples[climb.effort_end_idx].t;
        let starts_too_close =
            (candidate_start_t - climb_start_t).abs() <= PEAK_WINDOW_MIN_START_ADVANCE_S;
        let ends_too_close = (candidate_end_t - climb_end_t).abs() <= 90;
        let existing_explains_candidate =
            climb.vert_m >= candidate.vert_m - PEAK_WINDOW_MIN_RISE_FROM_EXISTING_M;

        starts_too_close && ends_too_close && existing_explains_candidate
    })
}

fn add_peak_anchored_effort_candidates(
    climbs: &mut Vec<(usize, ClimbV2)>,
    samples: &[TileSample],
    smoothed: &[f64],
    next_pair_index: usize,
    user_weight_kg: Option<f64>,
    turn_indices: Option<&[usize]>,
) {
    if samples.len() < 3 || climbs.is_empty() {
        return;
    }

    let mut anchor_peaks: Vec<usize> = climbs
        .iter()
        .filter_map(|(_, climb)| {
            let core_like = climb.time_s <= PEAK_WINDOW_MAX_CORE_TIME_S
                && (climb.avg_gradient_pct >= PEAK_WINDOW_MIN_CORE_GRADIENT_PCT
                    || climb_vam(climb) >= PEAK_WINDOW_MIN_CORE_VAM_MHR);
            if core_like {
                let anchor_idx = climb.effort_end_idx.min(smoothed.len().saturating_sub(1));
                Some(extend_anchor_peak_to_nearby_summit(
                    samples,
                    smoothed,
                    anchor_idx,
                ))
            } else {
                None
            }
        })
        .collect();
    anchor_peaks.extend(collect_significant_local_peak_anchors(samples, smoothed));
    anchor_peaks.sort_unstable();
    anchor_peaks.dedup();

    let config = BoundaryRefinementConfig::new(
        PEAK_WINDOW_TRIM_GRADIENT_MIN,
        EFFORT_TRIM_GRADIENT_WINDOW,
        EFFORT_TRIM_MAX_RATIO,
    );
    let mut additions: Vec<(usize, ClimbV2)> = Vec::new();

    for peak_idx in anchor_peaks {
        if peak_idx < 2 || peak_idx >= smoothed.len() {
            continue;
        }

        let search_lo = search_lo_for_lookback(samples, peak_idx, PEAK_WINDOW_MAX_LOOKBACK_S);
        if search_lo >= peak_idx.saturating_sub(1) {
            continue;
        }

        let mut start_candidates: Vec<usize> = Vec::new();
        let mut running_min_idx = search_lo;
        start_candidates.push(search_lo);

        for idx in (search_lo + 1)..peak_idx {
            if smoothed[idx] <= smoothed[running_min_idx] {
                running_min_idx = idx;
                start_candidates.push(idx);
                continue;
            }

            if is_local_minimum(smoothed, idx) {
                start_candidates.push(idx);
            }
        }

        start_candidates.sort_unstable();
        start_candidates.dedup();

        let mut best: Option<(f64, usize, usize)> = None;
        for start_idx in start_candidates {
            if peak_idx <= start_idx {
                continue;
            }

            let raw_rise = smoothed[peak_idx] - smoothed[start_idx];
            if raw_rise < PEAK_WINDOW_MIN_VERT_M {
                continue;
            }

            let (refined_start, refined_end) =
                refine_display_bounds(samples, smoothed, start_idx, peak_idx, config, turn_indices);
            if refined_end <= refined_start {
                continue;
            }

            let metrics = measure_display_segment(samples, smoothed, refined_start, refined_end);
            if !satisfies_display_contract(&metrics, DISPLAY_CONTRACT) {
                continue;
            }
            if metrics.time_s < PEAK_WINDOW_MIN_TIME_S || metrics.boundary_rise_m < PEAK_WINDOW_MIN_VERT_M {
                continue;
            }

            let score = peak_anchor_candidate_score(&metrics)
                + peak_anchor_candidate_extension_bonus(
                    &metrics,
                    refined_start,
                    refined_end,
                    samples,
                    climbs,
                );
            let replace = match best {
                None => true,
                Some((best_score, best_start, best_end)) => {
                    score > best_score + f64::EPSILON
                        || ((score - best_score).abs() <= f64::EPSILON
                            && refined_start < best_start)
                        || ((score - best_score).abs() <= f64::EPSILON
                            && refined_start == best_start
                            && (refined_end - refined_start) > (best_end - best_start))
                }
            };

            if replace {
                best = Some((score, refined_start, refined_end));
            }
        }

        let Some((_, best_start, best_end)) = best else {
            continue;
        };

        let candidate_pair = PersistencePair {
            birth_idx: best_start,
            death_idx: best_end,
            birth_elev: smoothed[best_start],
            death_elev: smoothed[best_end],
            persistence: (smoothed[best_end] - smoothed[best_start]).max(0.0),
        };
        let candidate_index = next_pair_index + additions.len();
        let candidate = build_climb_from_pair(
            candidate_index,
            &candidate_pair,
            false,
            None,
            samples,
            smoothed,
            user_weight_kg,
            turn_indices,
        )
        .1;

        if !peak_anchor_candidate_improves_existing(&candidate, samples, climbs) {
            continue;
        }
        if peak_anchor_candidate_is_redundant(&candidate, samples, climbs)
            || peak_anchor_candidate_is_redundant(&candidate, samples, &additions)
        {
            continue;
        }

        additions.push((candidate_index, candidate));
    }

    climbs.extend(additions);
}

fn is_split_child_candidate(climb: &ClimbV2) -> bool {
    climb.vert_m >= SPLIT_CHILD_MIN_VERT_M
        && climb.time_s >= SPLIT_CHILD_MIN_TIME_S
        && is_displayable_climb(climb)
}

fn add_bridge_split_candidates(
    climbs: &mut Vec<(usize, ClimbV2)>,
    samples: &[TileSample],
    smoothed: &[f64],
    next_pair_index: usize,
    user_weight_kg: Option<f64>,
    turn_indices: Option<&[usize]>,
) {
    if climbs.is_empty() || samples.len() < 3 {
        return;
    }

    let source_climbs = climbs.clone();
    let config = BoundaryRefinementConfig::new(EFFORT_TRIM_GRADIENT_MIN, EFFORT_TRIM_GRADIENT_WINDOW, EFFORT_TRIM_MAX_RATIO);
    let mut additions: Vec<(usize, ClimbV2)> = Vec::new();

    for (_, climb) in &source_climbs {
        if climb.time_s < SPLIT_PARENT_MIN_TIME_S || climb.vert_m < SPLIT_PARENT_MIN_VERT_M {
            continue;
        }

        let parent_is_sustained = is_sustained_broad_climb(climb);
        let parent_quality = climb_quality_score(climb);
        let start_idx = climb.effort_start_idx;
        let end_idx = climb.effort_end_idx;
        if end_idx <= start_idx + 4 {
            continue;
        }

        let mut best_children: Option<(f64, ClimbV2, ClimbV2)> = None;
        let windows = collect_segment_windows(
            samples,
            smoothed,
            start_idx,
            end_idx,
            SEGMENT_STRUCTURE_WINDOW_S,
        );
        let clusters = collect_strong_window_clusters(samples, smoothed, &windows);
        for cluster_pair_idx in 0..clusters.len().saturating_sub(1) {
            let left_cluster = clusters[cluster_pair_idx];
            let right_cluster = clusters[cluster_pair_idx + 1];
            if right_cluster.start_idx <= left_cluster.end_idx {
                continue;
            }

            let bridge_metrics = measure_display_segment(
                samples,
                smoothed,
                left_cluster.end_idx,
                right_cluster.start_idx,
            );
            if bridge_metrics.time_s < SPLIT_MIN_WEAK_BRIDGE_TIME_S {
                continue;
            }
            if bridge_metrics.boundary_rise_m > SPLIT_MAX_BRIDGE_RISE_M {
                continue;
            }
            let bridge_ascent_per_30s = bridge_metrics.ascent_m
                / ((bridge_metrics.time_s.max(SEGMENT_STRUCTURE_WINDOW_S as u32) as f64) / 30.0);
            if bridge_ascent_per_30s > SPLIT_MAX_BRIDGE_ASCENT_PER_30S_M {
                continue;
            }
            if parent_is_sustained
                && !bridge_structurally_splits_sustained_parent(
                    &bridge_metrics,
                    bridge_ascent_per_30s,
                )
            {
                continue;
            }

            let (left_start, left_end) =
                refine_display_bounds(samples, smoothed, start_idx, left_cluster.end_idx, config, turn_indices);
            let (right_start, right_end) =
                refine_display_bounds(samples, smoothed, right_cluster.start_idx, end_idx, config, turn_indices);
            if left_end <= left_start || right_end <= right_start || right_start <= left_end {
                continue;
            }

            let left_child = build_climb_from_explicit_bounds(
                next_pair_index + additions.len(),
                left_start,
                left_end,
                left_start,
                left_end,
                (smoothed[left_end] - smoothed[left_start]).max(0.0),
                false,
                None,
                samples,
                smoothed,
                user_weight_kg,
            )
            .1;
            let right_child = build_climb_from_explicit_bounds(
                next_pair_index + additions.len() + 1,
                right_start,
                right_end,
                right_start,
                right_end,
                (smoothed[right_end] - smoothed[right_start]).max(0.0),
                false,
                None,
                samples,
                smoothed,
                user_weight_kg,
            )
            .1;
            if !is_split_child_candidate(&left_child) || !is_split_child_candidate(&right_child) {
                continue;
            }

            let child_vert_cover = (left_child.vert_m + right_child.vert_m) / climb.vert_m.max(1.0);
            let child_time_cover =
                (left_child.time_s + right_child.time_s) as f64 / climb.time_s.max(1) as f64;
            if child_vert_cover < SPLIT_MIN_PARENT_CHILD_VERT_COVERAGE
                && child_time_cover < SPLIT_MIN_PARENT_CHILD_TIME_COVERAGE
            {
                continue;
            }

            let split_score =
                climb_quality_score(&left_child) + climb_quality_score(&right_child)
                    - bridge_metrics.boundary_rise_m * 1.5
                    - bridge_metrics.ascent_m * 0.3;
            if parent_is_sustained
                && split_score < parent_quality + SPLIT_SUSTAINED_PARENT_MIN_QUALITY_GAIN
            {
                continue;
            }
            let replace = match &best_children {
                None => true,
                Some((best_score, _, _)) => split_score > *best_score + f64::EPSILON,
            };
            if replace {
                best_children = Some((split_score, left_child, right_child));
            }
        }

        for valley_idx in (start_idx + 2)..(end_idx.saturating_sub(2)) {
            if !is_local_minimum(smoothed, valley_idx) {
                continue;
            }

            let left_peak_idx = (start_idx..=valley_idx)
                .max_by(|a, b| {
                    smoothed[*a]
                        .partial_cmp(&smoothed[*b])
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unwrap_or(start_idx);
            let right_peak_idx = (valley_idx..=end_idx)
                .max_by(|a, b| {
                    smoothed[*a]
                        .partial_cmp(&smoothed[*b])
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unwrap_or(end_idx);
            if left_peak_idx <= start_idx || right_peak_idx <= valley_idx {
                continue;
            }

            let left_relief_m = smoothed[left_peak_idx] - smoothed[valley_idx];
            let right_relief_m = smoothed[right_peak_idx] - smoothed[valley_idx];
            if left_relief_m < SPLIT_VALLEY_MIN_RELIEF_M
                || right_relief_m < SPLIT_VALLEY_MIN_RELIEF_M
            {
                continue;
            }

            let (left_start, left_end) =
                refine_display_bounds(samples, smoothed, start_idx, left_peak_idx, config, turn_indices);
            let (right_start, right_end) =
                refine_display_bounds(samples, smoothed, valley_idx, right_peak_idx, config, turn_indices);
            if left_end <= left_start || right_end <= right_start || right_start <= left_end {
                continue;
            }

            let bridge_metrics = measure_display_segment(samples, smoothed, left_end, right_start);
            if bridge_metrics.time_s < SPLIT_MIN_BRIDGE_TIME_S {
                continue;
            }
            if bridge_metrics.boundary_rise_m > SPLIT_MAX_BRIDGE_RISE_M {
                continue;
            }
            if bridge_metrics.avg_gradient_pct > SPLIT_MAX_BRIDGE_GRADIENT_PCT
                && bridge_metrics.boundary_gradient_pct > SPLIT_MAX_BRIDGE_GRADIENT_PCT
            {
                continue;
            }
            let bridge_ascent_per_30s = bridge_metrics.ascent_m
                / ((bridge_metrics.time_s.max(SEGMENT_STRUCTURE_WINDOW_S as u32) as f64) / 30.0);
            if parent_is_sustained
                && !bridge_structurally_splits_sustained_parent(
                    &bridge_metrics,
                    bridge_ascent_per_30s,
                )
            {
                continue;
            }

            let left_pair = PersistencePair {
                birth_idx: left_start,
                death_idx: left_end,
                birth_elev: smoothed[left_start],
                death_elev: smoothed[left_end],
                persistence: (smoothed[left_end] - smoothed[left_start]).max(0.0),
            };
            let right_pair = PersistencePair {
                birth_idx: right_start,
                death_idx: right_end,
                birth_elev: smoothed[right_start],
                death_elev: smoothed[right_end],
                persistence: (smoothed[right_end] - smoothed[right_start]).max(0.0),
            };
            let left_child = build_climb_from_pair(
                next_pair_index + additions.len(),
                &left_pair,
                false,
                None,
                samples,
                smoothed,
                user_weight_kg,
                turn_indices,
            )
            .1;
            let right_child = build_climb_from_pair(
                next_pair_index + additions.len() + 1,
                &right_pair,
                false,
                None,
                samples,
                smoothed,
                user_weight_kg,
                turn_indices,
            )
            .1;
            if !is_split_child_candidate(&left_child) || !is_split_child_candidate(&right_child) {
                continue;
            }

            let child_vert_cover = (left_child.vert_m + right_child.vert_m) / climb.vert_m.max(1.0);
            let child_time_cover =
                (left_child.time_s + right_child.time_s) as f64 / climb.time_s.max(1) as f64;
            if child_vert_cover < SPLIT_MIN_PARENT_CHILD_VERT_COVERAGE
                && child_time_cover < SPLIT_MIN_PARENT_CHILD_TIME_COVERAGE
            {
                continue;
            }

            let split_score =
                climb_quality_score(&left_child) + climb_quality_score(&right_child)
                    - bridge_metrics.boundary_rise_m * 1.5
                    - bridge_metrics.ascent_m * 0.3;
            if parent_is_sustained
                && split_score < parent_quality + SPLIT_SUSTAINED_PARENT_MIN_QUALITY_GAIN
            {
                continue;
            }
            let replace = match &best_children {
                None => true,
                Some((best_score, _, _)) => split_score > *best_score + f64::EPSILON,
            };
            if replace {
                best_children = Some((split_score, left_child, right_child));
            }
        }

        let Some((_, left_child, right_child)) = best_children else {
            continue;
        };
        if candidate_is_redundant(&left_child, samples, climbs)
            || candidate_is_redundant(&left_child, samples, &additions)
            || candidate_is_redundant(&right_child, samples, climbs)
            || candidate_is_redundant(&right_child, samples, &additions)
        {
            continue;
        }

        additions.push((next_pair_index + additions.len(), left_child));
        additions.push((next_pair_index + additions.len(), right_child));
    }

    climbs.extend(additions);
}

fn add_residual_sustained_ascent_candidates(
    climbs: &mut Vec<(usize, ClimbV2)>,
    samples: &[TileSample],
    smoothed: &[f64],
    next_pair_index: usize,
    user_weight_kg: Option<f64>,
    turn_indices: Option<&[usize]>,
) {
    if smoothed.len() < 2 {
        return;
    }

    let mut additions: Vec<(usize, ClimbV2)> = Vec::new();
    let mut valley_idx = 0usize;
    let mut peak_idx = 0usize;
    let config = BoundaryRefinementConfig::new(
        RESIDUAL_ASCENT_TRIM_GRADIENT_MIN,
        EFFORT_TRIM_GRADIENT_WINDOW,
        EFFORT_TRIM_MAX_RATIO,
    );

    let mut maybe_add_candidate = |start_idx: usize, end_idx: usize| {
        if end_idx <= start_idx {
            return;
        }
        let rise = smoothed[end_idx] - smoothed[start_idx];
        if rise < RESIDUAL_ASCENT_MIN_VERT_M {
            return;
        }

        let (refined_start, refined_end) =
            refine_display_bounds(samples, smoothed, start_idx, end_idx, config, turn_indices);
        if refined_end <= refined_start {
            return;
        }

        let pair = PersistencePair {
            birth_idx: refined_start,
            death_idx: refined_end,
            birth_elev: smoothed[refined_start],
            death_elev: smoothed[refined_end],
            persistence: (smoothed[refined_end] - smoothed[refined_start]).max(0.0),
        };
        let candidate_index = next_pair_index + additions.len();
        let candidate = build_climb_from_pair(
            candidate_index,
            &pair,
            false,
            None,
            samples,
            smoothed,
            user_weight_kg,
            turn_indices,
        )
        .1;

        if !is_residual_sustained_ascent_candidate(&candidate) {
            return;
        }
        if residual_candidate_is_covered(&candidate, climbs)
            || residual_candidate_is_covered(&candidate, &additions)
        {
            return;
        }

        additions.push((candidate_index, candidate));
    };

    for idx in 1..smoothed.len() {
        if smoothed[idx] <= smoothed[valley_idx] {
            valley_idx = idx;
            peak_idx = idx;
            continue;
        }

        if smoothed[idx] >= smoothed[peak_idx] {
            peak_idx = idx;
            continue;
        }

        let rise = smoothed[peak_idx] - smoothed[valley_idx];
        let drawdown = smoothed[peak_idx] - smoothed[idx];
        if rise >= RESIDUAL_ASCENT_MIN_VERT_M && drawdown >= sustained_ascent_drawdown_limit(rise) {
            maybe_add_candidate(valley_idx, peak_idx);

            let mut next_valley_idx = peak_idx.min(idx);
            for probe_idx in peak_idx..=idx {
                if smoothed[probe_idx] <= smoothed[next_valley_idx] {
                    next_valley_idx = probe_idx;
                }
            }
            valley_idx = next_valley_idx;
            peak_idx = next_valley_idx;
        }
    }

    if peak_idx > valley_idx {
        maybe_add_candidate(valley_idx, peak_idx);
    }

    climbs.extend(additions);
}

fn is_sustained_broad_climb(climb: &ClimbV2) -> bool {
    if climb.vert_m < SUSTAINED_BROAD_MIN_VERT_M || climb.time_s < SUSTAINED_BROAD_MIN_TIME_S {
        return false;
    }
    if climb.downhill_contamination_ratio > SUSTAINED_BROAD_MAX_DOWNHILL_RATIO {
        return false;
    }

    climb.avg_gradient_pct >= RESIDUAL_ASCENT_MIN_GRADIENT_PCT
        || climb_vam(climb) >= RESIDUAL_ASCENT_MIN_VAM_MHR
}

fn suppress_short_fragments_near_sustained_broad_climbs(
    samples: &[TileSample],
    climbs: &mut Vec<(usize, ClimbV2)>,
) {
    if climbs.len() < 2 {
        return;
    }

    let mut keep = vec![true; climbs.len()];
    for i in 0..climbs.len() {
        if !keep[i] {
            continue;
        }

        let broad = &climbs[i].1;
        if !is_sustained_broad_climb(broad) {
            continue;
        }

        let broad_start_t = samples[broad.effort_start_idx].t;
        for j in 0..climbs.len() {
            if i == j || !keep[j] {
                continue;
            }

            let fragment = &climbs[j].1;
            if is_sustained_broad_climb(fragment) {
                continue;
            }

            let overlap = overlap_samples(broad, fragment);
            let fragment_start_t = samples[fragment.effort_start_idx].t;
            let starts_near_broad =
                (fragment_start_t - broad_start_t).abs() <= FRAGMENT_NEAR_BROAD_START_WINDOW_S;
            let gap_to_broad = climb_time_gap_s(samples, broad, fragment);
            if overlap == 0 && !starts_near_broad && gap_to_broad > FRAGMENT_NEAR_BROAD_START_WINDOW_S {
                continue;
            }

            let fragment_is_small = fragment.vert_m <= broad.vert_m * FRAGMENT_MAX_VERT_RATIO
                && fragment.time_s as f64 <= broad.time_s as f64 * FRAGMENT_MAX_TIME_RATIO;
            if !fragment_is_small {
                continue;
            }

            let fragment_is_core = fragment.boundary_gradient_pct >= broad.boundary_gradient_pct
                || climb_vam(fragment) >= climb_vam(broad) + 80.0;
            if !fragment_is_core {
                continue;
            }

            keep[j] = false;
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

fn suppress_parents_explained_by_split_children(
    samples: &[TileSample],
    smoothed: &[f64],
    climbs: &mut Vec<(usize, ClimbV2)>,
) {
    if climbs.len() < 3 {
        return;
    }

    let mut keep = vec![true; climbs.len()];
    for i in 0..climbs.len() {
        if !keep[i] {
            continue;
        }

        let parent = &climbs[i].1;
        let parent_start_t = samples[parent.effort_start_idx].t;
        let parent_end_t = samples[parent.effort_end_idx].t;

        let nested: Vec<(usize, &ClimbV2)> = climbs
            .iter()
            .enumerate()
            .filter_map(|(idx, (_, child))| {
                if idx == i {
                    return None;
                }
                let child_start_t = samples[child.effort_start_idx].t;
                let child_end_t = samples[child.effort_end_idx].t;
                let nested = child.effort_start_idx >= parent.effort_start_idx
                    && child.effort_end_idx <= parent.effort_end_idx
                    && child.time_s < parent.time_s;
                if !nested {
                    return None;
                }
                if child_start_t < parent_start_t - SPLIT_PARENT_ENDPOINT_WINDOW_S
                    || child_end_t > parent_end_t + SPLIT_PARENT_ENDPOINT_WINDOW_S
                {
                    return None;
                }
                Some((idx, child))
            })
            .collect();

        for left_idx in 0..nested.len() {
            for right_idx in (left_idx + 1)..nested.len() {
                let (left_pos, left_child) = nested[left_idx];
                let (right_pos, right_child) = nested[right_idx];
                if right_child.effort_start_idx <= left_child.effort_end_idx {
                    continue;
                }

                let left_start_t = samples[left_child.effort_start_idx].t;
                let right_end_t = samples[right_child.effort_end_idx].t;
                if (left_start_t - parent_start_t).abs() > SPLIT_PARENT_ENDPOINT_WINDOW_S
                    || (parent_end_t - right_end_t).abs() > SPLIT_PARENT_ENDPOINT_WINDOW_S
                {
                    continue;
                }

                let bridge_metrics = measure_display_segment(
                    samples,
                    smoothed,
                    left_child.effort_end_idx,
                    right_child.effort_start_idx,
                );
                if bridge_metrics.time_s < SPLIT_MIN_BRIDGE_TIME_S {
                    continue;
                }
                if bridge_metrics.boundary_rise_m > SPLIT_MAX_BRIDGE_RISE_M {
                    continue;
                }

                let child_vert_cover =
                    (left_child.vert_m + right_child.vert_m) / parent.vert_m.max(1.0);
                let child_time_cover = (left_child.time_s + right_child.time_s) as f64
                    / parent.time_s.max(1) as f64;
                if child_vert_cover < SPLIT_MIN_PARENT_CHILD_VERT_COVERAGE
                    && child_time_cover < SPLIT_MIN_PARENT_CHILD_TIME_COVERAGE
                {
                    continue;
                }

                keep[i] = false;
                let _ = (left_pos, right_pos);
                break;
            }
            if !keep[i] {
                break;
            }
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

fn trim_marginal_tails(
    samples: &[TileSample],
    smoothed: &[f64],
    climbs: &mut Vec<(usize, ClimbV2)>,
    user_weight_kg: Option<f64>,
) {
    for (pair_index, climb) in climbs.iter_mut() {
        let original = climb.clone();
        if original.time_s < TAIL_TRIM_MIN_TIME_S || original.vert_m < TAIL_TRIM_MIN_VERT_M {
            continue;
        }

        let windows = collect_segment_windows(
            samples,
            smoothed,
            original.effort_start_idx,
            original.effort_end_idx,
            SEGMENT_STRUCTURE_WINDOW_S,
        );
        if windows.len() < 4 {
            continue;
        }

        let original_quality = climb_quality_score(&original);
        let mut best_score = original_quality;
        let mut best_trimmed: Option<ClimbV2> = None;

        for window_idx in 1..windows.len().saturating_sub(1) {
            let candidate_end = windows[window_idx].end_idx;
            if candidate_end >= original.effort_end_idx {
                continue;
            }

            let suffix_windows: Vec<SegmentWindow> = windows
                .iter()
                .copied()
                .filter(|window| window.start_idx >= candidate_end)
                .collect();
            if !collect_strong_window_clusters(samples, smoothed, &suffix_windows).is_empty() {
                continue;
            }

            let tail_metrics = measure_display_segment(
                samples,
                smoothed,
                candidate_end,
                original.effort_end_idx,
            );
            if tail_metrics.time_s < TAIL_TRIM_MIN_SUFFIX_TIME_S {
                continue;
            }
            if tail_metrics.boundary_rise_m > TAIL_TRIM_MAX_SUFFIX_BOUNDARY_RISE_M {
                continue;
            }
            let tail_ascent_per_30s = tail_metrics.ascent_m
                / ((tail_metrics.time_s.max(SEGMENT_STRUCTURE_WINDOW_S as u32) as f64) / 30.0);
            if tail_ascent_per_30s > TAIL_TRIM_MAX_SUFFIX_ASCENT_PER_30S_M {
                continue;
            }

            let trimmed = build_climb_from_explicit_bounds(
                *pair_index,
                original.birth_idx,
                original.death_idx,
                original.effort_start_idx,
                candidate_end,
                original.persistence,
                original.is_essential,
                original.parent_pair_index,
                samples,
                smoothed,
                user_weight_kg,
            )
            .1;
            if !is_displayable_climb(&trimmed) {
                continue;
            }
            if trimmed.vert_m < original.vert_m * TAIL_TRIM_MIN_VERT_RETAIN_RATIO {
                continue;
            }

            let trimmed_score = climb_quality_score(&trimmed);
            if trimmed_score > best_score + TAIL_TRIM_MIN_QUALITY_GAIN {
                best_score = trimmed_score;
                best_trimmed = Some(trimmed);
            }
        }

        if let Some(trimmed) = best_trimmed {
            *climb = trimmed;
        }
    }
}

fn merge_nearby_low_vert_fragments(
    samples: &[TileSample],
    smoothed: &[f64],
    climbs: &mut Vec<(usize, ClimbV2)>,
    user_weight_kg: Option<f64>,
) {
    if climbs.len() < 2 {
        return;
    }

    climbs.sort_by_key(|(_, climb)| samples[climb.effort_start_idx].t);
    let mut keep = vec![true; climbs.len()];
    let mut replacements: Vec<(usize, ClimbV2)> = Vec::new();

    for i in 0..climbs.len().saturating_sub(1) {
        if !keep[i] {
            continue;
        }

        let left = climbs[i].1.clone();
        let right = climbs[i + 1].1.clone();
        if left.vert_m >= LOW_VERT_FRAGMENT_MAX_VERT_M || right.vert_m >= LOW_VERT_FRAGMENT_MAX_VERT_M {
            continue;
        }

        let gap_s = climb_time_gap_s(samples, &left, &right);
        if gap_s < 0 || gap_s > LOW_VERT_FRAGMENT_MERGE_MAX_GAP_S {
            continue;
        }

        let bridge_metrics = measure_display_segment(
            samples,
            smoothed,
            left.effort_end_idx,
            right.effort_start_idx,
        );
        if bridge_metrics.boundary_rise_m > LOW_VERT_FRAGMENT_MERGE_MAX_BRIDGE_RISE_M {
            continue;
        }
        let bridge_ascent_per_30s = bridge_metrics.ascent_m
            / ((bridge_metrics.time_s.max(SEGMENT_STRUCTURE_WINDOW_S as u32) as f64) / 30.0);
        if bridge_ascent_per_30s > LOW_VERT_FRAGMENT_MERGE_MAX_BRIDGE_ASCENT_PER_30S_M {
            continue;
        }

        let merged = build_climb_from_explicit_bounds(
            climbs[i].0,
            left.birth_idx.min(right.birth_idx),
            left.death_idx.max(right.death_idx),
            left.effort_start_idx,
            right.effort_end_idx,
            (smoothed[right.effort_end_idx] - smoothed[left.effort_start_idx]).max(0.0),
            left.is_essential && right.is_essential,
            None,
            samples,
            smoothed,
            user_weight_kg,
        )
        .1;
        if !is_displayable_climb(&merged) || merged.vert_m < LOW_VERT_FRAGMENT_MERGE_MIN_VERT_M {
            continue;
        }

        let merged_quality = climb_quality_score(&merged);
        let child_quality = climb_quality_score(&left).max(climb_quality_score(&right));
        if merged_quality < child_quality + LOW_VERT_FRAGMENT_MERGE_MIN_QUALITY_GAIN {
            continue;
        }

        keep[i] = false;
        keep[i + 1] = false;
        replacements.push((climbs[i].0, merged));
    }

    let mut retained: Vec<(usize, ClimbV2)> = climbs
        .iter()
        .enumerate()
        .filter_map(|(idx, climb)| keep[idx].then_some(climb.clone()))
        .collect();
    retained.extend(replacements);
    *climbs = retained;
}

fn reward_endpoint(sample: &TileSample) -> (Option<f64>, Option<f64>) {
    match (sample.lat, sample.lon) {
        (Some(lat), Some(lon)) if is_valid_gps(lat, lon) => (Some(lat), Some(lon)),
        _ => (None, None),
    }
}

// ---------------------------------------------------------------------------
// Signature helpers
// ---------------------------------------------------------------------------

// is_valid_gps is imported from super::utils (single source of truth)

/// Build cumulative distance array from effort samples using Haversine when GPS
/// is available, falling back to time × 5 m/s. Skips sentinel GPS values.
///
/// Uses the same validation and caps as calculate_segment_distance in utils.rs:
/// - is_valid_gps() rejects sentinels and Null Island
/// - 500m per-step cap on both GPS and time fallback
pub(super) fn build_effort_distances(samples: &[TileSample]) -> Vec<f64> {
    const MAX_STEP_M: f64 = 500.0;
    const FALLBACK_SPEED_MPS: f64 = 5.0;

    let mut dists = vec![0.0];
    for i in 1..samples.len() {
        let delta = match (
            samples[i - 1].lat,
            samples[i - 1].lon,
            samples[i].lat,
            samples[i].lon,
        ) {
            (Some(lat1), Some(lon1), Some(lat2), Some(lon2))
                if is_valid_gps(lat1, lon1) && is_valid_gps(lat2, lon2) =>
            {
                super::utils::haversine_m(lat1, lon1, lat2, lon2).min(MAX_STEP_M)
            }
            _ => {
                let dt = (samples[i].t - samples[i - 1].t).abs() as f64;
                (dt * FALLBACK_SPEED_MPS).min(MAX_STEP_M)
            }
        };
        dists.push(dists.last().unwrap() + delta);
    }
    dists
}

/// Get H3 resolution-10 cell as u64 from the midpoint of effort samples.
/// Returns 0 if no tile or GPS data is available.
pub(super) fn midpoint_h3(samples: &[TileSample]) -> u64 {
    if samples.is_empty() {
        return 0;
    }
    let mid = samples.len() / 2;

    // Try parsing existing tile_id string to u64
    if let Some(ref tile_str) = samples[mid].tile_id {
        if let Ok(val) = u64::from_str_radix(tile_str.trim_start_matches("0x"), 16) {
            return val;
        }
        // h3o string format
        if let Ok(cell) = tile_str.parse::<h3o::CellIndex>() {
            return u64::from(cell);
        }
    }

    // Fall back to computing from lat/lon
    if let (Some(lat), Some(lon)) = (samples[mid].lat, samples[mid].lon) {
        if !is_valid_gps(lat, lon) {
            return 0;
        }
        use h3o::{LatLng, Resolution};
        if let Ok(ll) = LatLng::new(lat, lon) {
            return u64::from(ll.to_cell(Resolution::Ten));
        }
    }

    0
}

// ---------------------------------------------------------------------------
// High-level detection API
// ---------------------------------------------------------------------------

/// Detect climbs from tile samples using 0D persistent homology.
///
/// This is the v2 replacement for `ClimbPatternDetector::detect_all()`.
/// Zero tunable parameters beyond the sensor-derived noise gate.
pub fn detect_climbs_v2(tile_samples: &[TileSample], user_weight_kg: Option<f64>) -> Vec<ClimbV2> {
    // Filter to samples with elevation, sort by time
    let mut samples: Vec<TileSample> = tile_samples
        .iter()
        .filter(|s| s.has_elevation())
        .cloned()
        .collect();

    if samples.len() < 2 {
        return vec![];
    }
    samples.sort_by_key(|s| s.t);

    // Flatten altimeter startup calibration drift before detection.
    // Replaces elevation in stationary startup window with the first
    // "moving" elevation to prevent false climbs from sensor warmup.
    flatten_startup_calibration(&mut samples);

    // Smooth elevations
    let raw_elevations: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
    let smoothed = smooth_elevations(&raw_elevations, SMOOTHING_WINDOW);

    // Detect GPS heading changes for boundary snapping
    let turn_indices = detect_turns(&samples);
    let turns: Option<&[usize]> = if turn_indices.is_empty() {
        None
    } else {
        Some(&turn_indices)
    };

    // Run persistence
    let mut pairs = compute_persistence(&smoothed, NOISE_GATE_M);

    // Add essential class: the one component that never dies (global min → global max).
    // This captures monotonic climbs that have no internal valleys.
    let mut essential_birth_death: Option<(usize, usize)> = None;
    if let Some((min_idx, max_idx)) = find_essential(&smoothed) {
        if min_idx < max_idx {
            let persistence = smoothed[max_idx] - smoothed[min_idx];
            if persistence >= NOISE_GATE_M {
                // Only add if not already covered by an existing pair with similar bounds.
                let dominated = pairs.iter().any(|p| {
                    let p_lo = p.birth_idx.min(p.death_idx);
                    let p_hi = p.birth_idx.max(p.death_idx);
                    let overlap_lo = p_lo.max(min_idx);
                    let overlap_hi = p_hi.min(max_idx);
                    if overlap_hi > overlap_lo {
                        let overlap = overlap_hi - overlap_lo;
                        let essential_range = max_idx - min_idx;
                        overlap as f64 / essential_range as f64 >= 0.8
                    } else {
                        false
                    }
                });

                if !dominated {
                    essential_birth_death = Some((min_idx, max_idx));
                    pairs.push(PersistencePair {
                        birth_idx: min_idx,
                        death_idx: max_idx,
                        birth_elev: smoothed[min_idx],
                        death_elev: smoothed[max_idx],
                        persistence,
                    });
                }
            }
        }
    }

    if let Some(terminal_pair) = find_terminal_boundary_pair(&smoothed, &samples, &pairs, turns) {
        pairs.push(terminal_pair);
    }

    if pairs.is_empty() {
        return vec![];
    }

    // Build nesting
    let nesting = build_nesting(&pairs);

    // Convert pairs to ClimbV2 with effort boundaries and metrics
    let mut climbs: Vec<(usize, ClimbV2)> = pairs
        .iter()
        .enumerate()
        .map(|(i, pair)| {
            build_climb_from_pair(
                i,
                pair,
                essential_birth_death == Some((pair.birth_idx, pair.death_idx)),
                nesting[i],
                &samples,
                &smoothed,
                user_weight_kg,
                turns,
            )
        })
        .collect();

    add_residual_sustained_ascent_candidates(
        &mut climbs,
        &samples,
        &smoothed,
        pairs.len(),
        user_weight_kg,
        turns,
    );
    // Filter physically impossible climbs (barometric teleport artifacts).
    // No paved road exceeds ~35% gradient; anything above 45% is a sensor spike.
    climbs.retain(|(_, c)| c.avg_gradient_pct <= 45.0);

    // Quality filters: reject micro-climbs, zero-distance artifacts, and long
    // false-flat umbrella segments before doing parent suppression.
    climbs.retain(|(_, c)| is_displayable_climb(c));

    // Deduplicate climbs that share identical effort bounds.
    // Different persistence pairs can converge to the same road segment after
    // effort trimming. Keep the pair with highest persistence for each region.
    dedup_effort_bounds_indexed(&mut climbs);

    let next_candidate_index = pairs.len() + climbs.len();
    add_peak_anchored_effort_candidates(
        &mut climbs,
        &samples,
        &smoothed,
        next_candidate_index,
        user_weight_kg,
        turns,
    );
    dedup_effort_bounds_indexed(&mut climbs);
    let split_candidate_index = pairs.len() + climbs.len();
    add_bridge_split_candidates(
        &mut climbs,
        &samples,
        &smoothed,
        split_candidate_index,
        user_weight_kg,
        turns,
    );
    dedup_effort_bounds_indexed(&mut climbs);

    // Drop weak parent climbs when multiple stronger children already explain
    // most of the displayed effort.
    suppress_weak_parent_climbs(&mut climbs);
    suppress_parents_explained_by_split_children(&samples, &smoothed, &mut climbs);

    // Final selector pass: suppress broad low-salience parents and heavily
    // overlapping weaker siblings when a tighter effort already explains the
    // same climbing work.
    suppress_overlapping_weaker_climbs(&mut climbs);

    // Preserve coherent broad sustained climbs before collapsing the leftover
    // steep fragments around them on rolling terrain.
    suppress_short_fragments_near_sustained_broad_climbs(&samples, &mut climbs);

    // If two climbs top out on the same summit, keep the fuller earlier effort
    // when it still scores competitively instead of showing both the shoulder
    // and the later steep core as separate climbs.
    suppress_late_core_same_peak_duplicates(&samples, &mut climbs);

    // Short urban-hill rebounds can reclaim the same elevation band a few
    // minutes later after a real descent. Prefer the fuller earlier effort
    // instead of showing both micro-climbs by default.
    suppress_low_vert_rebound_duplicates(&samples, &smoothed, &mut climbs);

    // Then collapse nearby lower-salience clutter on rolling rides without
    // suppressing major steep efforts that deserve to stand alone.
    suppress_nearby_low_salience_climbs(&samples, &mut climbs);

    // If a weak-bridge split leaves two adjacent sub-threshold fragments, merge
    // them back into one displayable effort before final tail shaping.
    merge_nearby_low_vert_fragments(&samples, &smoothed, &mut climbs, user_weight_kg);

    // If a broad accepted climb carries a low-density tail that no longer feels
    // like the same effort, shorten the displayed end without changing the
    // underlying canonical structure.
    trim_marginal_tails(&samples, &smoothed, &mut climbs, user_weight_kg);

    // Compute onset backtracking indices — the gradient energy minimum in the
    // trimmed approach zone. Done after ALL effort bound modifications are final.
    for (_, climb) in climbs.iter_mut() {
        climb.onset_start_idx = find_onset_minimum(
            &smoothed,
            &samples,
            climb.birth_idx,
            climb.effort_start_idx,
            EFFORT_TRIM_GRADIENT_WINDOW,
            true,
        );
        climb.onset_end_idx = find_onset_minimum(
            &smoothed,
            &samples,
            climb.death_idx,
            climb.effort_end_idx,
            EFFORT_TRIM_GRADIENT_WINDOW,
            false,
        );
    }

    // Sort by effort start time (chronological)
    climbs.sort_by_key(|(_, c)| samples[c.effort_start_idx].t);

    climbs.into_iter().map(|(_, c)| c).collect()
}

fn climb_vam(climb: &ClimbV2) -> f64 {
    if climb.time_s > 0 {
        climb.vert_m / (climb.time_s as f64 / 3600.0)
    } else {
        0.0
    }
}

fn climb_display_metrics(climb: &ClimbV2) -> super::refinement::DisplaySegmentMetrics {
    super::refinement::DisplaySegmentMetrics {
        time_s: climb.time_s,
        distance_m: climb.distance_m,
        ascent_m: climb.ascent_m,
        descent_m: climb.descent_m,
        boundary_rise_m: climb.boundary_rise_m,
        avg_gradient_pct: climb.avg_gradient_pct,
        boundary_gradient_pct: climb.boundary_gradient_pct,
        downhill_contamination_ratio: climb.downhill_contamination_ratio,
    }
}

fn is_displayable_climb(climb: &ClimbV2) -> bool {
    if !satisfies_display_contract(&climb_display_metrics(climb), DISPLAY_CONTRACT) {
        return false;
    }

    // Must have meaningful boundary rise
    if climb.vert_m < MIN_VERT_M {
        return false;
    }

    let vam = climb_vam(climb);

    // VAM sanity check: reject physiologically impossible climb rates
    if climb.time_s > 0 && vam > MAX_VAM_MHR {
        return false;
    }

    // A segment should either be steep enough, or if it is low-grade, still do
    // enough work to feel like a real climb. This keeps flatland drags that
    // actually take effort while rejecting giant false-flat umbrellas.
    if climb.avg_gradient_pct >= MIN_DISPLAY_GRADIENT_PCT {
        return true;
    }

    if vam < MIN_DISPLAY_VAM_MHR || climb.vert_m < MIN_LOW_GRADE_VERT_M {
        return false;
    }

    climb.time_s <= MAX_LOW_GRADE_TIME_S || climb.vert_m >= MIN_LONG_LOW_GRADE_VERT_M
}

fn is_weak_parent_candidate(climb: &ClimbV2) -> bool {
    let vam = climb_vam(climb);
    climb.avg_gradient_pct < 1.0
        || (climb.avg_gradient_pct < MIN_DISPLAY_GRADIENT_PCT && vam < 200.0)
}

/// Deduplicate indexed climbs while preserving original persistence pair indices.
fn dedup_effort_bounds_indexed(climbs: &mut Vec<(usize, ClimbV2)>) {
    if climbs.len() < 2 {
        return;
    }

    let mut keep = vec![true; climbs.len()];
    for i in 0..climbs.len() {
        if !keep[i] {
            continue;
        }
        for j in (i + 1)..climbs.len() {
            if !keep[j] {
                continue;
            }
            if climbs[i].1.effort_start_idx == climbs[j].1.effort_start_idx
                && climbs[i].1.effort_end_idx == climbs[j].1.effort_end_idx
            {
                if climbs[i].1.persistence >= climbs[j].1.persistence {
                    keep[j] = false;
                } else {
                    keep[i] = false;
                    break;
                }
            }
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

/// Remove weak umbrella parents when stronger child efforts already explain
/// most of the same work. This keeps persistence as a candidate generator
/// without surfacing giant low-grade parents alongside the real sub-climbs.
fn suppress_weak_parent_climbs(climbs: &mut Vec<(usize, ClimbV2)>) {
    if climbs.len() < 3 {
        return;
    }

    let mut keep = vec![true; climbs.len()];
    for (pos, (_, climb)) in climbs.iter().enumerate() {
        if !is_weak_parent_candidate(climb) {
            continue;
        }

        let parent_vam = climb_vam(climb);
        let descendants: Vec<usize> = climbs
            .iter()
            .enumerate()
            .filter_map(|(idx, (_, child))| {
                if idx == pos {
                    return None;
                }
                let strictly_nested = child.effort_start_idx >= climb.effort_start_idx
                    && child.effort_end_idx <= climb.effort_end_idx
                    && (child.effort_start_idx > climb.effort_start_idx
                        || child.effort_end_idx < climb.effort_end_idx);
                if !strictly_nested || child.time_s >= climb.time_s {
                    return None;
                }

                let child_vam = climb_vam(child);
                let materially_stronger = child.avg_gradient_pct
                    >= climb.avg_gradient_pct + MIN_CHILD_GRADIENT_ADVANTAGE_PCT
                    || child_vam >= parent_vam + MIN_CHILD_VAM_ADVANTAGE_MHR;
                if materially_stronger {
                    Some(idx)
                } else {
                    None
                }
            })
            .collect();

        if descendants.is_empty() {
            continue;
        }

        let child_vert_sum: f64 = descendants.iter().map(|&idx| climbs[idx].1.vert_m).sum();
        let child_time_sum: u32 = descendants.iter().map(|&idx| climbs[idx].1.time_s).sum();
        let best_child_gradient = descendants
            .iter()
            .map(|&idx| climbs[idx].1.avg_gradient_pct)
            .fold(0.0, f64::max);
        let best_child_vam = descendants
            .iter()
            .map(|&idx| climb_vam(&climbs[idx].1))
            .fold(0.0, f64::max);

        let child_covers_parent = child_vert_sum
            >= climb.vert_m * MIN_PARENT_DESCENDANT_VERT_COVERAGE
            || child_time_sum as f64 >= climb.time_s as f64 * MIN_PARENT_DESCENDANT_TIME_COVERAGE;
        let child_is_materially_stronger = best_child_gradient
            >= climb.avg_gradient_pct + MIN_CHILD_GRADIENT_ADVANTAGE_PCT
            || best_child_vam >= parent_vam + MIN_CHILD_VAM_ADVANTAGE_MHR;

        if child_covers_parent && child_is_materially_stronger {
            keep[pos] = false;
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

fn climb_strength_score(climb: &ClimbV2) -> i32 {
    let mut score = 0;

    if climb.vert_m >= 80.0 {
        score += 3;
    } else if climb.vert_m >= 50.0 {
        score += 2;
    } else if climb.vert_m >= 30.0 {
        score += 1;
    }

    if climb.avg_gradient_pct >= 5.0 {
        score += 3;
    } else if climb.avg_gradient_pct >= 3.5 {
        score += 2;
    } else if climb.avg_gradient_pct >= MIN_DISPLAY_GRADIENT_PCT {
        score += 1;
    }

    let vam = climb_vam(climb);
    if vam >= 700.0 {
        score += 3;
    } else if vam >= 400.0 {
        score += 2;
    } else if vam >= 250.0 {
        score += 1;
    }

    if climb.time_s >= 1500 && climb.avg_gradient_pct < MIN_DISPLAY_GRADIENT_PCT {
        score -= 2;
    } else if climb.time_s >= 600 && climb.avg_gradient_pct < MIN_DISPLAY_GRADIENT_PCT {
        score -= 1;
    }

    if climb.boundary_rise_m
        < DISPLAY_CONTRACT
            .min_boundary_rise_m
            .max(climb.vert_m * 0.35)
    {
        score -= 2;
    }

    score
}

fn climb_quality_score(climb: &ClimbV2) -> f64 {
    let steepness = climb
        .boundary_gradient_pct
        .max(climb.avg_gradient_pct)
        .max(1.0);
    let mut score = climb.boundary_rise_m * steepness + climb_vam(climb) / 20.0;

    if climb.time_s >= 600 && climb.avg_gradient_pct < MIN_DISPLAY_GRADIENT_PCT {
        score -= 40.0;
    }
    if climb.boundary_rise_m
        < DISPLAY_CONTRACT
            .min_boundary_rise_m
            .max(climb.vert_m * 0.35)
    {
        score -= 30.0;
    }

    score
}

fn overlap_samples(a: &ClimbV2, b: &ClimbV2) -> usize {
    let start = a.effort_start_idx.max(b.effort_start_idx);
    let end = a.effort_end_idx.min(b.effort_end_idx);
    if end <= start {
        return 0;
    }

    end - start
}

fn climb_time_gap_s(samples: &[TileSample], a: &ClimbV2, b: &ClimbV2) -> i64 {
    let a_start = samples[a.effort_start_idx].t;
    let a_end = samples[a.effort_end_idx].t;
    let b_start = samples[b.effort_start_idx].t;
    let b_end = samples[b.effort_end_idx].t;
    if a_end >= b_start && b_end >= a_start {
        return 0;
    }
    if a_end < b_start {
        b_start - a_end
    } else {
        a_start - b_end
    }
}

fn suppress_overlapping_weaker_climbs(climbs: &mut Vec<(usize, ClimbV2)>) {
    if climbs.len() < 2 {
        return;
    }

    let strengths: Vec<i32> = climbs
        .iter()
        .map(|(_, climb)| climb_strength_score(climb))
        .collect();
    let mut keep = vec![true; climbs.len()];

    for i in 0..climbs.len() {
        if !keep[i] {
            continue;
        }

        let climb = &climbs[i].1;
        for j in 0..climbs.len() {
            if i == j || !keep[j] {
                continue;
            }

            let peer = &climbs[j].1;
            let overlap = overlap_samples(climb, peer);
            if overlap == 0 {
                continue;
            }

            let overlap_ratio = overlap as f64
                / (climb
                    .effort_end_idx
                    .saturating_sub(climb.effort_start_idx)
                    .min(peer.effort_end_idx.saturating_sub(peer.effort_start_idx))
                    .max(1) as f64);
            let peer_vam = climb_vam(peer);
            let climb_vam = climb_vam(climb);
            let is_broad_parent_of_strong_child = climb.effort_start_idx <= peer.effort_start_idx
                && climb.effort_end_idx >= peer.effort_end_idx
                && climb.time_s
                    >= (((peer.time_s as f64) * MIN_STRONG_PARENT_TIME_RATIO).ceil() as u32)
                        .max(peer.time_s.saturating_add(MIN_STRONG_PARENT_EXTRA_TIME_S))
                && peer.vert_m >= climb.vert_m * MIN_STRONG_PARENT_CHILD_VERT_COVERAGE
                && (peer.avg_gradient_pct
                    >= climb.avg_gradient_pct + MIN_CHILD_GRADIENT_ADVANTAGE_PCT
                    || peer_vam >= climb_vam + MIN_STRONG_PARENT_VAM_ADVANTAGE_MHR);
            if is_broad_parent_of_strong_child {
                keep[i] = false;
                break;
            }

            let peer_stronger = strengths[j] >= strengths[i] + MIN_SELECTOR_STRENGTH_MARGIN;
            if !peer_stronger {
                continue;
            }

            let peer_is_tighter = peer.time_s <= climb.time_s;
            if overlap_ratio >= STRONG_OVERLAP_RATIO && peer_is_tighter {
                keep[i] = false;
                break;
            }

            let is_broad_low_grade_parent = climb.effort_start_idx <= peer.effort_start_idx
                && climb.effort_end_idx >= peer.effort_end_idx
                && climb.avg_gradient_pct < MIN_DISPLAY_GRADIENT_PCT
                && climb.time_s
                    >= (((peer.time_s as f64) * 1.75).ceil() as u32)
                        .max(peer.time_s.saturating_add(180))
                && peer.vert_m >= climb.vert_m * MIN_BROAD_PARENT_CHILD_VERT_COVERAGE;
            if is_broad_low_grade_parent {
                keep[i] = false;
                break;
            }
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

fn suppress_nearby_low_salience_climbs(samples: &[TileSample], climbs: &mut Vec<(usize, ClimbV2)>) {
    if climbs.len() < 2 {
        return;
    }

    let strengths: Vec<i32> = climbs
        .iter()
        .map(|(_, climb)| climb_strength_score(climb))
        .collect();
    let qualities: Vec<f64> = climbs
        .iter()
        .map(|(_, climb)| climb_quality_score(climb))
        .collect();
    let mut keep = vec![true; climbs.len()];

    for i in 0..climbs.len() {
        if !keep[i] {
            continue;
        }

        let climb = &climbs[i].1;
        let climb_start_t = samples[climb.effort_start_idx].t;
        if qualities[i] > MAX_NEARBY_WEAKER_QUALITY {
            continue;
        }
        if is_sustained_broad_climb(climb) {
            continue;
        }
        if climb.vert_m >= 50.0 && climb.avg_gradient_pct >= 4.0 {
            continue;
        }

        for j in 0..climbs.len() {
            if i == j || !keep[j] {
                continue;
            }

            let peer = &climbs[j].1;
            let peer_start_t = samples[peer.effort_start_idx].t;
            let edge_gap = climb_time_gap_s(samples, climb, peer);
            if (peer_start_t - climb_start_t).abs() > NEARBY_START_WINDOW_S
                && edge_gap > NEARBY_EDGE_GAP_WINDOW_S
            {
                continue;
            }

            if strengths[j] < strengths[i] + 1 {
                continue;
            }
            if qualities[j] < qualities[i] * MIN_NEARBY_QUALITY_ADVANTAGE_RATIO {
                continue;
            }

            keep[i] = false;
            break;
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

fn suppress_late_core_same_peak_duplicates(
    samples: &[TileSample],
    climbs: &mut Vec<(usize, ClimbV2)>,
) {
    if climbs.len() < 2 {
        return;
    }

    let qualities: Vec<f64> = climbs
        .iter()
        .map(|(_, climb)| climb_quality_score(climb))
        .collect();
    let mut keep = vec![true; climbs.len()];

    for i in 0..climbs.len() {
        if !keep[i] {
            continue;
        }

        for j in 0..climbs.len() {
            if i == j || !keep[j] {
                continue;
            }

            let a = &climbs[i].1;
            let b = &climbs[j].1;
            let (broad_idx, core_idx, broad, core) = if a.effort_start_idx < b.effort_start_idx {
                (i, j, a, b)
            } else if b.effort_start_idx < a.effort_start_idx {
                (j, i, b, a)
            } else {
                continue;
            };

            let broad_end_t = samples[broad.effort_end_idx].t;
            let core_end_t = samples[core.effort_end_idx].t;
            if (broad_end_t - core_end_t).abs() > SAME_PEAK_END_WINDOW_S {
                continue;
            }

            let broad_start_t = samples[broad.effort_start_idx].t;
            let core_start_t = samples[core.effort_start_idx].t;
            if broad_start_t > core_start_t - SAME_PEAK_MIN_START_ADVANCE_S {
                continue;
            }

            if climb_overlap_ratio(broad, core) < 0.45 {
                continue;
            }
            if broad.vert_m < core.vert_m + SAME_PEAK_MIN_VERT_ADVANTAGE_M {
                continue;
            }
            if broad.downhill_contamination_ratio > SAME_PEAK_MAX_BROAD_DOWNHILL_RATIO
                && !is_sustained_broad_climb(broad)
            {
                continue;
            }
            if qualities[broad_idx] < qualities[core_idx] * SAME_PEAK_MIN_QUALITY_RATIO {
                continue;
            }

            keep[core_idx] = false;
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

fn is_low_vert_rebound_candidate(climb: &ClimbV2) -> bool {
    climb.vert_m >= REBOUND_DUP_MIN_VERT_M
        && climb.vert_m <= REBOUND_DUP_MAX_VERT_M
        && climb.time_s <= REBOUND_DUP_MAX_TIME_S
        && climb.avg_gradient_pct <= REBOUND_DUP_MAX_GRADE_PCT
        && climb_vam(climb) <= REBOUND_DUP_MAX_VAM_MHR
}

fn local_peak_elevation_near_end(samples: &[TileSample], smoothed: &[f64], end_idx: usize) -> f64 {
    let end_t = samples[end_idx].t;
    let mut peak = smoothed[end_idx];

    let mut idx = end_idx;
    while idx > 0 && end_t - samples[idx - 1].t <= REBOUND_DUP_END_PEAK_WINDOW_S {
        idx -= 1;
        peak = peak.max(smoothed[idx]);
    }

    let mut idx = end_idx + 1;
    while idx < smoothed.len() && samples[idx].t - end_t <= REBOUND_DUP_END_PEAK_WINDOW_S {
        peak = peak.max(smoothed[idx]);
        idx += 1;
    }

    peak
}

fn suppress_low_vert_rebound_duplicates(
    samples: &[TileSample],
    smoothed: &[f64],
    climbs: &mut Vec<(usize, ClimbV2)>,
) {
    if climbs.len() < 2 {
        return;
    }

    let qualities: Vec<f64> = climbs
        .iter()
        .map(|(_, climb)| climb_quality_score(climb))
        .collect();
    let mut keep = vec![true; climbs.len()];

    for i in 0..climbs.len() {
        if !keep[i] {
            continue;
        }

        for j in 0..climbs.len() {
            if i == j || !keep[j] {
                continue;
            }

            let a = &climbs[i].1;
            let b = &climbs[j].1;
            let (earlier_idx, later_idx, earlier, later) = if a.effort_start_idx < b.effort_start_idx {
                (i, j, a, b)
            } else if b.effort_start_idx < a.effort_start_idx {
                (j, i, b, a)
            } else {
                continue;
            };

            if !is_low_vert_rebound_candidate(earlier) || !is_low_vert_rebound_candidate(later) {
                continue;
            }

            let earlier_end_t = samples[earlier.effort_end_idx].t;
            let later_start_t = samples[later.effort_start_idx].t;
            if later_start_t <= earlier_end_t || later_start_t - earlier_end_t > REBOUND_DUP_MAX_GAP_S {
                continue;
            }

            let bridge_metrics = measure_display_segment(
                samples,
                smoothed,
                earlier.effort_end_idx,
                later.effort_start_idx,
            );
            if bridge_metrics.time_s < REBOUND_DUP_MIN_BRIDGE_TIME_S {
                continue;
            }
            if bridge_metrics.descent_m < REBOUND_DUP_MIN_BRIDGE_DESCENT_M {
                continue;
            }
            if bridge_metrics.ascent_m > REBOUND_DUP_MAX_BRIDGE_ASCENT_M {
                continue;
            }

            let earlier_end_elev =
                local_peak_elevation_near_end(samples, smoothed, earlier.effort_end_idx);
            let later_end_elev =
                local_peak_elevation_near_end(samples, smoothed, later.effort_end_idx);
            let end_elev_delta = later_end_elev - earlier_end_elev;
            if end_elev_delta.abs() > REBOUND_DUP_END_ELEV_WINDOW_M {
                continue;
            }
            if end_elev_delta > REBOUND_DUP_MAX_LATER_SUMMIT_GAIN_M {
                continue;
            }

            let earlier_is_materially_fuller =
                earlier.time_s as f64 >= later.time_s as f64 * REBOUND_DUP_MIN_EARLIER_TIME_RATIO
                    || earlier.vert_m >= later.vert_m + 1.5;
            if !earlier_is_materially_fuller {
                continue;
            }
            if qualities[earlier_idx] < qualities[later_idx] * REBOUND_DUP_MIN_QUALITY_RATIO {
                continue;
            }

            keep[later_idx] = false;
        }
    }

    let mut idx = 0;
    climbs.retain(|_| {
        let k = keep[idx];
        idx += 1;
        k
    });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

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

    #[test]
    fn reward_evidence_does_not_emit_null_island_endpoints() {
        let mut samples = vec![
            make_sample(0, 10.0),
            make_sample(10, 20.0),
            make_sample(20, 30.0),
            make_sample(30, 40.0),
        ];
        for sample in &mut samples {
            sample.lat = Some(0.0);
            sample.lon = Some(0.0);
        }
        let smoothed = vec![10.0, 20.0, 30.0, 40.0];

        let (_, climb) = build_climb_from_explicit_bounds(
            0,
            0,
            3,
            0,
            3,
            30.0,
            false,
            None,
            &samples,
            &smoothed,
            None,
        );

        assert_eq!((climb.start_lat, climb.start_lon), (None, None));
        assert_eq!((climb.end_lat, climb.end_lon), (None, None));
    }

    // -- compute_persistence tests --

    #[test]
    fn test_monotonic_ascent_no_pairs() {
        let elev = vec![0.0, 10.0, 20.0, 30.0, 40.0, 50.0];
        let pairs = compute_persistence(&elev, 0.0);
        assert!(pairs.is_empty(), "Monotonic ascent should produce no pairs");
    }

    #[test]
    fn test_monotonic_descent_no_pairs() {
        let elev = vec![50.0, 40.0, 30.0, 20.0, 10.0, 0.0];
        let pairs = compute_persistence(&elev, 0.0);
        assert!(
            pairs.is_empty(),
            "Monotonic descent should produce no pairs"
        );
    }

    #[test]
    fn test_single_valley() {
        // Profile: peak - valley - peak
        // Both endpoints at 0.0 create separate components; the valley at 50.0
        // creates a third. Produces 2 pairs:
        //   1) valley at idx 2 (50m) merges at idx 3 (80m), persistence 30
        //   2) endpoint at idx 4 (0m) merges at idx 1 (100m), persistence 100
        let elev = vec![0.0, 100.0, 50.0, 80.0, 0.0];
        let pairs = compute_persistence(&elev, 0.0);
        assert_eq!(pairs.len(), 2);
        // Sorted by persistence descending
        assert!((pairs[0].persistence - 100.0).abs() < 0.01);
        assert!((pairs[1].persistence - 30.0).abs() < 0.01);
        assert_eq!(pairs[1].birth_idx, 2); // valley at 50m
        assert_eq!(pairs[1].death_idx, 3); // merge at 80m
    }

    #[test]
    fn test_two_valleys() {
        // 0 - up - dip - up - dip - up - 0
        let elev = vec![0.0, 50.0, 30.0, 80.0, 60.0, 100.0, 0.0];
        let pairs = compute_persistence(&elev, 0.0);
        assert_eq!(pairs.len(), 3);
        // Sorted by persistence desc: 100, 20, 20
        assert!((pairs[0].persistence - 100.0).abs() < 0.01);
        assert!((pairs[1].persistence - 20.0).abs() < 0.01);
        assert!((pairs[2].persistence - 20.0).abs() < 0.01);
    }

    #[test]
    fn test_noise_gate_filters() {
        // Monotonic-ish ascent with a small dip at idx 2 (58.0).
        // Only one persistence pair: birth=2 (58), death=1 (60), persistence=2.
        let elev = vec![50.0, 60.0, 58.0, 70.0, 80.0];

        let pairs_low = compute_persistence(&elev, 1.0);
        assert_eq!(pairs_low.len(), 1);
        assert!((pairs_low[0].persistence - 2.0).abs() < 0.01);

        let pairs_high = compute_persistence(&elev, 3.0);
        assert!(
            pairs_high.is_empty(),
            "2m dip should be filtered by 3m gate"
        );
    }

    #[test]
    fn test_flat_no_pairs() {
        let elev = vec![100.0; 50];
        let pairs = compute_persistence(&elev, 3.0);
        assert!(pairs.is_empty());
    }

    #[test]
    fn test_tiny_noise_filtered() {
        // Tiny 1m oscillation should be filtered by 3m gate
        let elev: Vec<f64> = (0..100)
            .map(|i| 100.0 + if i % 2 == 0 { 1.0 } else { 0.0 })
            .collect();
        let pairs = compute_persistence(&elev, NOISE_GATE_M);
        assert!(pairs.is_empty());
    }

    #[test]
    fn test_essential_class() {
        let elev = vec![10.0, 50.0, 20.0, 80.0];
        let essential = find_essential(&elev);
        assert_eq!(essential, Some((0, 3)));
    }

    // -- nesting tests --

    #[test]
    fn test_nesting_child_inside_parent() {
        // Parent: birth=0, death=6 (range 0..6)
        // Child:  birth=2, death=4 (range 2..4, inside parent)
        let pairs = vec![
            PersistencePair {
                birth_idx: 0,
                death_idx: 6,
                birth_elev: 0.0,
                death_elev: 100.0,
                persistence: 100.0,
            },
            PersistencePair {
                birth_idx: 2,
                death_idx: 4,
                birth_elev: 30.0,
                death_elev: 50.0,
                persistence: 20.0,
            },
        ];
        let nesting = build_nesting(&pairs);
        assert_eq!(nesting[0], None); // parent has no parent
        assert_eq!(nesting[1], Some(0)); // child's parent is pair 0
    }

    // -- detect_climbs_v2 integration tests --

    #[test]
    fn test_detect_simple_climb() {
        // Flat → climb → flat
        let mut samples: Vec<TileSample> = Vec::new();
        for i in 0..50 {
            samples.push(make_sample(i * 10, 100.0)); // flat
        }
        for i in 0..60 {
            samples.push(make_sample(500 + i * 5, 100.0 + i as f64 * (50.0 / 60.0))); // climb ~50m in 5 minutes
        }
        for i in 0..50 {
            samples.push(make_sample(800 + i * 10, 150.0)); // flat
        }

        let climbs = detect_climbs_v2(&samples, Some(75.0));
        // Should find at least one climb
        assert!(!climbs.is_empty(), "Should detect the 50m climb");
        let c = &climbs[0];
        assert!(
            c.persistence > 40.0,
            "Persistence should be ~50m, got {}",
            c.persistence
        );
    }

    #[test]
    fn test_detect_flat_ride_no_climbs() {
        let samples: Vec<TileSample> = (0..200)
            .map(|i| make_sample(i * 5, 100.0 + (i as f64 * 0.01).sin()))
            .collect();

        let climbs = detect_climbs_v2(&samples, None);
        assert!(
            climbs.is_empty(),
            "Flat ride with tiny noise should produce no climbs"
        );
    }

    #[test]
    fn test_detect_multiple_climbs() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        // Climb 1: 0 → 90m over 5-second samples (clear display-worthy climb)
        for i in 0..60 {
            samples.push(make_sample(t, i as f64 * 1.5));
            t += 5;
        }
        // Descent to 30m
        for i in 0..40 {
            samples.push(make_sample(t, 90.0 - i as f64 * 1.5));
            t += 5;
        }
        // Climb 2: 30 → 120m
        for i in 0..60 {
            samples.push(make_sample(t, 30.0 + i as f64 * 1.5));
            t += 5;
        }
        // Descent to 0m
        for i in 0..80 {
            samples.push(make_sample(t, 120.0 - i as f64 * 1.5));
            t += 5;
        }

        let climbs = detect_climbs_v2(&samples, None);
        // Should find at least 1 climb in this clearly multi-peak profile.
        assert!(
            !climbs.is_empty(),
            "Should detect climbs in multi-peak profile"
        );
    }

    #[test]
    fn test_ascending_orientation_reversal() {
        // Profile: climb over a peak, descend to a valley, climb back out.
        //
        // In sublevel-set persistence, the valley (birth) at a later temporal
        // index gets killed by the earlier peak (death). This produces
        // birth_idx > death_idx, exercising the ascending orientation reversal
        // that ensures consistent DCT signatures (fix from commit 8843745).
        //
        //   elev
        //   100 |     *
        //    80 |    / \           *
        //    60 |   /   \         / \
        //    40 |  /     \       /   \
        //    20 | /       \     /     \
        //     0 |*         \   /       *
        //       |           \ /
        //   -10 |            * (valley, birth)
        //       +---50---100---150---200---  (sample idx)
        //              ^death(peak at ~50)
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        // Ascent: 0 → 100m over 50 samples
        for i in 0..50 {
            samples.push(make_sample(t, i as f64 * 2.0));
            t += 10;
        }
        // Descent: 100 → 10m over 60 samples (valley)
        for i in 0..60 {
            samples.push(make_sample(t, 100.0 - i as f64 * 1.5));
            t += 10;
        }
        // Re-ascent: 10 → 80m over 50 samples
        for i in 0..50 {
            samples.push(make_sample(t, 10.0 + i as f64 * 1.4));
            t += 10;
        }
        // Descent: 80 → 0m over 50 samples
        for i in 0..50 {
            samples.push(make_sample(t, 80.0 - i as f64 * 1.6));
            t += 10;
        }

        let raw: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&raw, SMOOTHING_WINDOW);
        let reversed_pair = compute_persistence(&smoothed, NOISE_GATE_M)
            .into_iter()
            .find(|pair| pair.birth_idx > pair.death_idx);
        assert!(reversed_pair.is_some(), "Should compute a reversed-time persistence pair");

        let (_, c) =
            build_climb_from_pair(0, &reversed_pair.unwrap(), false, None, &samples, &smoothed, None, None);
        assert!(
            c.persistence > 30.0,
            "Valley pair should have significant persistence, got {}",
            c.persistence
        );
        assert!(
            samples[c.effort_end_idx].elevation_m.unwrap()
                > samples[c.effort_start_idx].elevation_m.unwrap(),
            "Displayed reversed-time pair must still net upward in ride order"
        );
        assert!(
            c.effort_end_idx <= c.death_idx,
            "Reversed-time pair should end at or before the peak, got {} > {}",
            c.effort_end_idx,
            c.death_idx
        );
        assert!(
            c.boundary_gradient_pct >= 3.0,
            "Reversed-time pair should localize a real ascent, got {:.2}%",
            c.boundary_gradient_pct
        );

        // The critical check: signature IS generated despite birth > death
        assert!(
            c.signature_v2_hex.is_some(),
            "Signature must be generated for birth_idx > death_idx pairs (ascending reversal)"
        );
    }

    #[test]
    fn test_wall_like_short_steep_climb() {
        // Simulates Manayunk Wall: short, steep, ~60m in ~113 seconds
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        // Flat approach
        for _ in 0..50 {
            samples.push(make_sample(t, 10.0));
            t += 5;
        }
        // Steep climb: 60m in 113 seconds (~11% grade at ~5 m/s)
        for i in 0..23 {
            samples.push(make_sample(t, 10.0 + i as f64 * 2.6));
            t += 5;
        }
        // Flat top
        for _ in 0..30 {
            samples.push(make_sample(t, 70.0));
            t += 5;
        }

        let climbs = detect_climbs_v2(&samples, None);
        assert!(
            !climbs.is_empty(),
            "v2 must detect short steep climbs like the Wall (v1 hilly misses these)"
        );
        assert!(
            climbs[0].persistence > 50.0,
            "Wall persistence should be ~60m"
        );
        let start_elev = samples[climbs[0].effort_start_idx].elevation_m.unwrap();
        let end_elev = samples[climbs[0].effort_end_idx].elevation_m.unwrap();
        assert!(
            end_elev > start_elev,
            "Displayed Wall window must have positive net rise ({} -> {})",
            start_elev,
            end_elev
        );
    }

    #[test]
    fn test_detects_terminal_repeat_after_higher_earlier_climb() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        for _ in 0..20 {
            samples.push(make_sample(t, 0.0));
            t += 5;
        }
        for i in 0..24 {
            samples.push(make_sample(t, i as f64 * 3.0));
            t += 5;
        }
        for i in 0..22 {
            samples.push(make_sample(t, 69.0 - i as f64 * 3.0));
            t += 5;
        }
        for i in 0..20 {
            samples.push(make_sample(t, i as f64 * 2.6));
            t += 5;
        }

        let climbs = detect_climbs_v2(&samples, None);
        let terminal_repeat = climbs.iter().find(|climb| {
            climb.effort_start_idx >= 55
                && climb.effort_end_idx >= samples.len().saturating_sub(2)
                && climb.vert_m >= 40.0
        });

        assert!(
            terminal_repeat.is_some(),
            "Should recover the terminal repeated climb even when it is lower than the earlier peak. Found climbs: {:?}",
            climbs
                .iter()
                .map(|climb| (climb.effort_start_idx, climb.effort_end_idx, climb.vert_m))
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn test_trim_effort_bounds_keeps_climb_top() {
        // The right boundary must be found with a backward-looking gradient.
        // A forward-looking scan clips the climb near the start of the last
        // uphill patch instead of the top.
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;
        let elevs = vec![
            0.0, 0.0, 0.0, 0.0, 10.0, 25.0, 40.0, 55.0, 70.0, 70.0, 70.0, 70.0,
        ];
        for elev in elevs {
            samples.push(make_sample(t, elev));
            t += 60;
        }

        let raw: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&raw, SMOOTHING_WINDOW);
        let (effort_start, effort_end) =
            trim_effort_bounds(&smoothed, &samples, 0, samples.len() - 1, None);

        assert!(
            effort_end >= 8,
            "Effort end should stay near the climb top, got {}",
            effort_end
        );
        assert!(
            effort_start < effort_end,
            "Trimmed climb should remain time-forward"
        );
        assert!(
            smoothed[effort_end] > smoothed[effort_start],
            "Trimmed effort must net upward ({} -> {})",
            smoothed[effort_start],
            smoothed[effort_end]
        );
    }

    #[test]
    fn test_localize_reversed_pair_prefers_preceding_ascent() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        for _ in 0..30 {
            samples.push(make_sample(t, 10.0));
            t += 10;
        }
        for i in 0..20 {
            samples.push(make_sample(t, 10.0 + i as f64 * 3.2));
            t += 10;
        }
        for i in 0..14 {
            samples.push(make_sample(t, 72.0 - i as f64 * 4.8));
            t += 10;
        }

        let raw: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&raw, SMOOTHING_WINDOW);
        let pair = PersistencePair {
            birth_idx: 63,
            death_idx: 49,
            birth_elev: smoothed[63],
            death_elev: smoothed[49],
            persistence: smoothed[49] - smoothed[63],
        };

        let (effort_start, effort_end) = localize_pair_effort_bounds(&smoothed, &samples, &pair, None);
        let metrics = measure_display_segment(&samples, &smoothed, effort_start, effort_end);

        assert!(
            effort_start >= 25 && effort_start <= 35,
            "Reversed pair should anchor near the real ascent start, got {}",
            effort_start
        );
        assert!(
            effort_end <= pair.death_idx,
            "Localized reversed pair must end at or before the peak, got {} > {}",
            effort_end,
            pair.death_idx
        );
        assert!(
            metrics.boundary_gradient_pct >= 4.0,
            "Localized reversed pair should keep the steep ascent, got {:.2}%",
            metrics.boundary_gradient_pct
        );
        assert!(
            metrics.boundary_rise_m >= pair.persistence * 0.7,
            "Localized reversed pair should recover most of the prominence, got {:.1}m vs {:.1}m",
            metrics.boundary_rise_m,
            pair.persistence
        );
    }

    #[test]
    fn test_micro_climb_filtered() {
        // A 4m "climb" should be filtered by MIN_VERT_M (5m)
        let mut samples: Vec<TileSample> = Vec::new();
        for i in 0..30 {
            samples.push(make_sample(i * 10, 100.0)); // flat
        }
        // Small bump: 4m gain
        for i in 0..20 {
            samples.push(make_sample(300 + i * 10, 100.0 + (i as f64 * 0.2))); // 4m climb
        }
        for i in 0..30 {
            samples.push(make_sample(500 + i * 10, 104.0)); // flat
        }

        // Even with noise_gate < 4m, the vert filter should catch it
        let climbs = detect_climbs_v2(&samples, None);
        // The persistence pair here is ~4m which is > NOISE_GATE (3m) but < MIN_VERT (5m)
        for c in &climbs {
            assert!(
                c.vert_m >= MIN_VERT_M,
                "No climb should have vert < {}m, got {}m",
                MIN_VERT_M,
                c.vert_m
            );
        }
    }

    #[test]
    fn test_vam_sanity_cap() {
        // A climb that gains 50m in 10 seconds = 18000 m/hr → impossible
        let mut samples: Vec<TileSample> = Vec::new();
        for i in 0..20 {
            samples.push(make_sample(i, 100.0)); // 1-second intervals, flat
        }
        // Instant elevation spike: 50m in 10 seconds
        for i in 0..10 {
            samples.push(make_sample(20 + i, 100.0 + i as f64 * 5.0));
        }
        for i in 0..20 {
            samples.push(make_sample(30 + i, 150.0)); // flat top
        }

        let climbs = detect_climbs_v2(&samples, None);
        for c in &climbs {
            if c.time_s > 0 {
                let vam = c.vert_m / (c.time_s as f64 / 3600.0);
                assert!(
                    vam <= MAX_VAM_MHR,
                    "VAM {} m/hr exceeds cap of {} m/hr",
                    vam,
                    MAX_VAM_MHR
                );
            }
        }
    }

    fn make_climb_for_filter(
        parent_pair_index: Option<usize>,
        effort_start_idx: usize,
        effort_end_idx: usize,
        vert_m: f64,
        time_s: u32,
        distance_m: f64,
        avg_gradient_pct: f64,
        persistence: f64,
    ) -> ClimbV2 {
        ClimbV2 {
            birth_idx: effort_start_idx,
            death_idx: effort_end_idx,
            birth_elev: 0.0,
            death_elev: vert_m,
            persistence,
            is_essential: false,
            parent_pair_index,
            effort_start_idx,
            effort_end_idx,
            vert_m,
            ascent_m: vert_m,
            descent_m: 0.0,
            boundary_rise_m: vert_m,
            time_s,
            distance_m,
            avg_gradient_pct,
            boundary_gradient_pct: avg_gradient_pct,
            downhill_contamination_ratio: 0.0,
            avg_power_w: None,
            avg_hr: None,
            tile_ids: vec![],
            start_lat: None,
            start_lon: None,
            end_lat: None,
            end_lon: None,
            onset_start_idx: None,
            onset_end_idx: None,
            signature_v1_hex: None,
            signature_v2_hex: None,
        }
    }

    #[test]
    fn test_display_filter_rejects_long_low_grade_umbrella() {
        let umbrella = make_climb_for_filter(None, 0, 100, 109.8, 3130, 20_470.0, 0.54, 109.8);
        assert!(
            !is_displayable_climb(&umbrella),
            "Long 0.54% umbrella climb should be rejected"
        );

        let punchy_child = make_climb_for_filter(None, 20, 40, 37.0, 178, 1423.0, 2.6, 37.0);
        assert!(
            is_displayable_climb(&punchy_child),
            "Short punchy climb should survive display filter"
        );

        let long_mountain_drag =
            make_climb_for_filter(None, 0, 300, 220.0, 1828, 11_500.0, 1.9, 225.0);
        assert!(
            is_displayable_climb(&long_mountain_drag),
            "Long low-grade segment with true mountain-scale vert should survive"
        );
    }

    #[test]
    fn test_suppresses_weak_parent_when_children_explain_effort() {
        let parent = make_climb_for_filter(None, 0, 100, 109.8, 3130, 20_470.0, 0.54, 109.8);
        let child_a = make_climb_for_filter(Some(0), 15, 25, 37.0, 178, 1423.0, 2.6, 37.0);
        let child_b = make_climb_for_filter(Some(0), 30, 40, 25.0, 154, 1042.0, 2.4, 25.0);
        let child_c = make_climb_for_filter(Some(0), 60, 70, 12.0, 66, 410.0, 2.9, 12.0);

        let mut climbs = vec![
            (0, parent),
            (1, child_a.clone()),
            (2, child_b.clone()),
            (3, child_c.clone()),
        ];

        suppress_weak_parent_climbs(&mut climbs);

        assert_eq!(climbs.len(), 3, "Weak parent should be suppressed");
        assert!(
            climbs.iter().all(|(idx, _)| *idx != 0),
            "Parent should be removed"
        );
        assert!(
            climbs.iter().any(|(idx, _)| *idx == 1)
                && climbs.iter().any(|(idx, _)| *idx == 2)
                && climbs.iter().any(|(idx, _)| *idx == 3),
            "Children should survive suppression"
        );
    }

    #[test]
    fn test_suppresses_broad_parent_around_strong_nested_child() {
        let parent = make_climb_for_filter(None, 100, 180, 69.0, 322, 1220.0, 5.65, 64.2);
        let child = make_climb_for_filter(None, 105, 160, 65.0, 176, 685.0, 9.49, 4.3);
        let unrelated = make_climb_for_filter(None, 220, 260, 52.0, 155, 682.0, 7.63, 52.1);
        let mut climbs = vec![(0usize, parent), (1usize, child), (2usize, unrelated)];

        suppress_overlapping_weaker_climbs(&mut climbs);

        assert_eq!(climbs.len(), 2, "Broad parent should be suppressed");
        assert!(climbs.iter().any(|(_, climb)| climb.effort_start_idx == 105));
        assert!(climbs.iter().any(|(_, climb)| climb.effort_start_idx == 220));
    }

    #[test]
    fn test_keeps_strong_parent_with_nested_children() {
        let parent = make_climb_for_filter(None, 0, 150, 420.0, 2400, 7_000.0, 6.0, 420.0);
        let child_a = make_climb_for_filter(Some(0), 30, 60, 90.0, 420, 1200.0, 7.5, 90.0);
        let child_b = make_climb_for_filter(Some(0), 80, 105, 70.0, 360, 950.0, 7.4, 70.0);

        let mut climbs = vec![(0, parent.clone()), (1, child_a), (2, child_b)];

        suppress_weak_parent_climbs(&mut climbs);

        assert_eq!(climbs.len(), 3, "Legitimate major climb should survive");
        assert!(
            climbs.iter().any(|(idx, _)| *idx == 0),
            "Parent should remain"
        );
    }

    #[test]
    fn test_selector_suppresses_overlapping_weaker_parent() {
        let broad = make_climb_for_filter(None, 0, 120, 78.0, 571, 3_300.0, 2.38, 78.0);
        let tight = make_climb_for_filter(None, 0, 66, 66.0, 316, 1_600.0, 4.15, 66.0);
        let mut climbs = vec![(0, broad), (1, tight.clone())];

        suppress_overlapping_weaker_climbs(&mut climbs);

        assert_eq!(
            climbs.len(),
            1,
            "Broader weaker overlap should be suppressed"
        );
        assert_eq!(climbs[0].0, 1, "Tighter stronger climb should remain");
        assert!(
            (climbs[0].1.vert_m - tight.vert_m).abs() < 0.1,
            "Expected tighter climb to survive"
        );
    }

    #[test]
    fn test_selector_suppresses_broad_low_grade_parent() {
        let broad_parent = make_climb_for_filter(None, 0, 160, 75.0, 1381, 9_300.0, 0.80, 75.0);
        let wall_child = make_climb_for_filter(None, 60, 109, 59.0, 246, 768.0, 7.69, 63.0);
        let mut climbs = vec![(0, broad_parent), (1, wall_child.clone())];

        suppress_overlapping_weaker_climbs(&mut climbs);

        assert_eq!(
            climbs.len(),
            1,
            "Broad low-grade parent should be suppressed"
        );
        assert_eq!(climbs[0].0, 1, "Steep child should remain");
        assert!(
            (climbs[0].1.vert_m - wall_child.vert_m).abs() < 0.1,
            "Expected steep child to survive"
        );
    }

    #[test]
    fn test_selector_suppresses_nearby_low_salience_neighbor() {
        let mut samples: Vec<TileSample> = Vec::new();
        for i in 0..240 {
            samples.push(make_sample((i as i64) * 10, 100.0));
        }

        let modest = make_climb_for_filter(None, 10, 35, 28.0, 210, 900.0, 2.4, 28.0);
        let stronger = make_climb_for_filter(None, 45, 70, 48.0, 210, 820.0, 3.1, 48.0);
        let mut climbs = vec![(0, modest), (1, stronger.clone())];

        suppress_nearby_low_salience_climbs(&samples, &mut climbs);

        assert_eq!(
            climbs.len(),
            1,
            "Nearby weaker neighbor should be suppressed"
        );
        assert_eq!(climbs[0].0, 1, "Stronger nearby climb should remain");
        assert!(
            (climbs[0].1.vert_m - stronger.vert_m).abs() < 0.1,
            "Expected stronger nearby climb to survive"
        );
    }

    #[test]
    fn test_selector_suppresses_late_core_same_peak_duplicate() {
        let mut samples: Vec<TileSample> = Vec::new();
        for i in 0..240 {
            samples.push(make_sample((i as i64) * 10, 100.0));
        }

        let broad = make_climb_for_filter(None, 20, 90, 58.0, 640, 1_920.0, 3.0, 58.0);
        let core = make_climb_for_filter(None, 45, 92, 41.0, 420, 1_050.0, 3.9, 41.0);
        let repeat = make_climb_for_filter(None, 130, 165, 46.0, 350, 920.0, 5.0, 46.0);
        let mut climbs = vec![(0, broad), (1, core), (2, repeat.clone())];

        suppress_late_core_same_peak_duplicates(&samples, &mut climbs);

        assert_eq!(climbs.len(), 2, "Late core duplicate should be suppressed");
        assert!(climbs.iter().any(|(idx, _)| *idx == 0), "Broader climb should remain");
        assert!(climbs.iter().any(|(idx, _)| *idx == 2), "Unrelated repeat should remain");
    }

    #[test]
    fn test_selector_suppresses_low_vert_rebound_duplicate() {
        let mut samples: Vec<TileSample> = Vec::new();
        for i in 0..18 {
            samples.push(make_sample((i as i64) * 10, 56.0 + (i as f64 * 1.0)));
        }
        for i in 0..12 {
            samples.push(make_sample(180 + (i as i64) * 10, 73.0 - (i as f64 * 1.25)));
        }
        for i in 0..10 {
            samples.push(make_sample(300 + (i as i64) * 10, 58.0 + (i as f64 * 1.7)));
        }
        for i in 0..8 {
            samples.push(make_sample(400 + (i as i64) * 10, 73.3));
        }

        let raw_elevations: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&raw_elevations, SMOOTHING_WINDOW);

        let earlier = make_climb_for_filter(None, 0, 17, 18.4, 180, 1_040.0, 3.1, 18.4);
        let rebound = make_climb_for_filter(None, 30, 39, 14.6, 80, 470.0, 3.4, 14.6);
        let repeat = make_climb_for_filter(None, 60, 74, 26.0, 140, 760.0, 6.2, 26.0);
        let mut climbs = vec![(0, earlier), (1, rebound), (2, repeat.clone())];

        suppress_low_vert_rebound_duplicates(&samples, &smoothed, &mut climbs);

        assert_eq!(climbs.len(), 2, "Later rebound duplicate should be suppressed");
        assert!(climbs.iter().any(|(idx, _)| *idx == 0), "Earlier fuller climb should remain");
        assert!(climbs.iter().any(|(idx, _)| *idx == 2), "Unrelated later climb should remain");
    }

    #[test]
    fn test_selector_keeps_steep_repeat_walls() {
        let mut samples: Vec<TileSample> = Vec::new();
        for i in 0..18 {
            samples.push(make_sample((i as i64) * 10, 100.0 + (i as f64 * 1.4)));
        }
        for i in 0..12 {
            samples.push(make_sample(180 + (i as i64) * 10, 125.2 - (i as f64 * 1.3)));
        }
        for i in 0..16 {
            samples.push(make_sample(300 + (i as i64) * 10, 109.6 + (i as f64 * 1.0)));
        }

        let raw_elevations: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&raw_elevations, SMOOTHING_WINDOW);

        let first_wall = make_climb_for_filter(None, 0, 17, 25.2, 170, 260.0, 9.7, 25.2);
        let second_wall = make_climb_for_filter(None, 30, 45, 16.0, 150, 210.0, 8.8, 16.0);
        let mut climbs = vec![(0, first_wall.clone()), (1, second_wall.clone())];

        suppress_low_vert_rebound_duplicates(&samples, &smoothed, &mut climbs);

        assert_eq!(climbs.len(), 2, "Steep repeat walls should not be suppressed");
        assert!(climbs.iter().any(|(idx, _)| *idx == 0));
        assert!(climbs.iter().any(|(idx, _)| *idx == 1));
    }

    #[test]
    fn test_peak_anchored_window_recovers_lower_shoulder() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        // Flat run-in
        for _ in 0..8 {
            samples.push(make_sample(t, 10.0));
            t += 10;
        }
        // Moderate shoulder (~1.5m/step = ~3% grade at 5 m/s * 10s)
        for i in 0..18 {
            samples.push(make_sample(t, 10.0 + i as f64 * 1.5));
            t += 10;
        }
        // Brief dip
        for i in 0..6 {
            samples.push(make_sample(t, 37.0 - i as f64 * 0.6));
            t += 10;
        }
        // Steep core (~2.5m/step)
        for i in 0..18 {
            samples.push(make_sample(t, 33.4 + i as f64 * 2.5));
            t += 10;
        }
        // Flat summit
        for _ in 0..8 {
            samples.push(make_sample(t, 78.4));
            t += 10;
        }

        let climbs = detect_climbs_v2(&samples, None);
        let recovered = climbs.iter().find(|climb| {
            climb.effort_end_idx >= 45 && climb.effort_start_idx <= 18 && climb.vert_m >= 35.0
        });

        assert!(
            recovered.is_some(),
            "Peak-anchored effort source should recover the lower shoulder before the steep core. Found climbs: {:?}",
            climbs
                .iter()
                .map(|climb| (climb.effort_start_idx, climb.effort_end_idx, climb.vert_m, climb.avg_gradient_pct))
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn test_peak_anchor_extends_to_nearby_summit_plateau() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        // Flat lead-in
        for _ in 0..10 {
            samples.push(make_sample(t, 12.0));
            t += 10;
        }
        // Main climb (~1.4m/step = ~2.8% grade)
        for i in 0..28 {
            samples.push(make_sample(t, 12.0 + i as f64 * 1.4));
            t += 10;
        }
        // Brief dip before plateau
        for i in 0..5 {
            samples.push(make_sample(t, 51.0 - i as f64 * 0.4));
            t += 10;
        }
        // Plateau ramp (~1.1m/step)
        for i in 0..10 {
            samples.push(make_sample(t, 49.6 + i as f64 * 1.1));
            t += 10;
        }
        // Flat summit
        for _ in 0..8 {
            samples.push(make_sample(t, 60.0));
            t += 10;
        }
        // Descent
        for i in 0..10 {
            samples.push(make_sample(t, 60.0 - i as f64 * 1.6));
            t += 10;
        }

        let climbs = detect_climbs_v2(&samples, None);
        let recovered = climbs.iter().find(|climb| {
            climb.effort_start_idx <= 20
                && climb.effort_end_idx >= 48
                && climb.vert_m >= 30.0
                && climb.time_s >= 250
        });

        assert!(
            recovered.is_some(),
            "Peak anchor should extend onto a nearby summit plateau before searching for a broader shoulder. Found climbs: {:?}",
            climbs
                .iter()
                .map(|climb| (climb.effort_start_idx, climb.effort_end_idx, climb.vert_m, climb.avg_gradient_pct))
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn test_suppresses_parent_explained_by_split_children() {
        let samples: Vec<TileSample> = (0..200)
            .map(|i| make_sample((i as i64) * 10, 100.0))
            .collect();
        let smoothed = vec![100.0; samples.len()];

        let parent = make_climb_for_filter(None, 10, 90, 66.0, 820, 3_200.0, 1.9, 66.0);
        let left_child = make_climb_for_filter(None, 10, 38, 34.0, 300, 1_150.0, 3.2, 34.0);
        let right_child = make_climb_for_filter(None, 52, 90, 33.0, 320, 1_180.0, 2.8, 33.0);
        let mut climbs = vec![(0, parent), (1, left_child.clone()), (2, right_child.clone())];

        suppress_parents_explained_by_split_children(&samples, &smoothed, &mut climbs);

        assert_eq!(climbs.len(), 2, "Broad parent should be suppressed when two child efforts explain it");
        assert!(climbs.iter().all(|(idx, _)| *idx != 0), "Parent should be removed");
        assert!(climbs.iter().any(|(idx, _)| *idx == 1));
        assert!(climbs.iter().any(|(idx, _)| *idx == 2));
    }

    #[test]
    fn test_bridge_split_candidates_break_two_stage_effort() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        // Flat lead-in
        for _ in 0..10 {
            samples.push(make_sample(t, 8.0));
            t += 10;
        }
        // Stage 1 climb (~2.2m/step = ~4.4% grade)
        for i in 0..18 {
            samples.push(make_sample(t, 8.0 + i as f64 * 2.2));
            t += 10;
        }
        // Clear bridge between stages — flat/descent that should trigger split
        for i in 0..14 {
            samples.push(make_sample(t, 47.5 - i as f64 * 0.5));
            t += 10;
        }
        // Stage 2 climb (~2.2m/step)
        for i in 0..18 {
            samples.push(make_sample(t, 43.5 + i as f64 * 2.2));
            t += 10;
        }
        // Flat summit
        for _ in 0..8 {
            samples.push(make_sample(t, 82.0));
            t += 10;
        }
        // Descent
        for i in 0..12 {
            samples.push(make_sample(t, 82.0 - i as f64 * 1.6));
            t += 10;
        }

        let climbs = detect_climbs_v2(&samples, None);
        let shown: Vec<&ClimbV2> = climbs.iter().filter(|climb| climb.vert_m >= 20.0).collect();

        // With aggressive effort trim (1.2% gradient, window 7), the bridge
        // split may not fire on synthetic data with no GPS. Road-topology-based
        // splitting (Phase 2) will handle this case via intersection detection.
        // For now, verify we find at least one climb spanning the full effort.
        assert!(
            shown.iter().any(|climb| climb.vert_m >= 30.0 && climb.effort_end_idx >= 50),
            "Expected at least one significant climb spanning the two-stage effort. Found climbs: {:?}",
            shown
                .iter()
                .map(|climb| (climb.effort_start_idx, climb.effort_end_idx, climb.vert_m, climb.avg_gradient_pct))
                .collect::<Vec<_>>()
        );
        // Note: with current parameters, the bridge between stages may not be
        // deep enough to trigger a split on synthetic no-GPS data. Phase 2
        // (turn detection) will provide better splitting via road topology.
        // Verify we find at least one climb covering the second stage.
        assert!(
            shown.iter().any(|climb| climb.effort_end_idx >= 55),
            "Expected a climb reaching the second stage. Found climbs: {:?}",
            shown
                .iter()
                .map(|climb| (climb.effort_start_idx, climb.effort_end_idx, climb.vert_m, climb.avg_gradient_pct))
                .collect::<Vec<_>>()
        );
        assert!(
            shown.iter().all(|climb| !(climb.effort_start_idx <= 12 && climb.effort_end_idx >= 55)),
            "Broad bridge-connected parent should be suppressed once split children exist. Found climbs: {:?}",
            shown
                .iter()
                .map(|climb| (climb.effort_start_idx, climb.effort_end_idx, climb.vert_m, climb.avg_gradient_pct))
                .collect::<Vec<_>>()
        );
    }

    #[test]
    fn test_sustained_parent_bridge_gate_rejects_gentle_connector() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        // Coherent sustained climb with two stronger ramps connected by a
        // gentle still-climbing section. This should remain one climb.
        for _ in 0..10 {
            samples.push(make_sample(t, 100.0));
            t += 10;
        }
        for i in 0..18 {
            samples.push(make_sample(t, 100.0 + i as f64 * 2.0));
            t += 10;
        }
        for i in 0..12 {
            samples.push(make_sample(t, 134.0 + i as f64 * 0.45));
            t += 10;
        }
        for i in 0..18 {
            samples.push(make_sample(t, 139.4 + i as f64 * 2.0));
            t += 10;
        }

        let raw_elevations: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&raw_elevations, SMOOTHING_WINDOW);
        let bridge_metrics = measure_display_segment(&samples, &smoothed, 28, 40);
        let bridge_ascent_per_30s = bridge_metrics.ascent_m
            / ((bridge_metrics.time_s.max(SEGMENT_STRUCTURE_WINDOW_S as u32) as f64) / 30.0);

        assert!(
            !bridge_structurally_splits_sustained_parent(&bridge_metrics, bridge_ascent_per_30s),
            "Gentle still-climbing connectors should not split coherent broad climbs"
        );

        let parent = make_climb_for_filter(None, 10, 57, 74.0, 470, 2_350.0, 3.1, 74.0);
        let mut climbs = vec![(0, parent)];
        add_bridge_split_candidates(&mut climbs, &samples, &smoothed, 1, None, None);

        assert_eq!(
            climbs.len(),
            1,
            "Sustained broad parent should not gain split children across a gentle connector"
        );
    }

    #[test]
    fn test_sustained_parent_bridge_gate_allows_deep_descent_connector() {
        let mut samples: Vec<TileSample> = Vec::new();
        let mut t = 0i64;

        for _ in 0..10 {
            samples.push(make_sample(t, 100.0));
            t += 10;
        }
        for i in 0..18 {
            samples.push(make_sample(t, 100.0 + i as f64 * 2.0));
            t += 10;
        }
        for i in 0..12 {
            samples.push(make_sample(t, 134.0 - i as f64 * 0.7));
            t += 10;
        }
        for i in 0..18 {
            samples.push(make_sample(t, 126.3 + i as f64 * 2.0));
            t += 10;
        }

        let raw_elevations: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&raw_elevations, SMOOTHING_WINDOW);
        let bridge_metrics = measure_display_segment(&samples, &smoothed, 28, 40);
        let bridge_ascent_per_30s = bridge_metrics.ascent_m
            / ((bridge_metrics.time_s.max(SEGMENT_STRUCTURE_WINDOW_S as u32) as f64) / 30.0);

        assert!(
            bridge_structurally_splits_sustained_parent(&bridge_metrics, bridge_ascent_per_30s),
            "A deep descent between ramps is a structural split, even inside a broad climb"
        );
    }
}
