//! Climb pattern detector.
//!
//! Implements both legacy (gradient + drop tolerance) and momentum-based detection.
//! All thresholds are now configurable via `ClimbDetectorConfig` for terrain adaptation.

use std::collections::HashSet;

// Detection smoothing is terrain-configurable; reward signatures use the fixed
// canonical smoothing window shared with persistence detection.
use super::constants::SMOOTHING_WINDOW;
use super::persistence::{build_effort_distances, midpoint_h3};
use super::refinement::{
    measure_display_segment, refine_display_bounds, satisfies_display_contract,
    BoundaryRefinementConfig, DisplayClimbContract,
};
use super::signature::generate_signature;
use super::signature_v2::generate_signature_v2;
use super::types::*;
use super::utils::*;

/// Climb pattern detector with configurable thresholds.
pub struct ClimbPatternDetector {
    config: ClimbDetectorConfig,
}

impl ClimbPatternDetector {
    /// Create a new detector with the given configuration.
    pub fn new(config: ClimbDetectorConfig) -> Self {
        Self { config }
    }

    /// Create a detector with default configuration (Momentum algorithm).
    pub fn with_defaults() -> Self {
        Self::new(ClimbDetectorConfig::default())
    }

    /// Detect all climb patterns from tile samples.
    ///
    /// Returns climbs in chronological order (by start time).
    pub fn detect_all(
        &self,
        tile_samples: &[TileSample],
        arena_tiles: Option<&HashSet<String>>,
        user_weight_kg: Option<f64>,
    ) -> Vec<ClimbPattern> {
        // Filter samples with elevation data
        let mut samples: Vec<TileSample> = tile_samples
            .iter()
            .filter(|s| s.has_elevation())
            .cloned()
            .collect();

        if samples.len() < 2 {
            return vec![];
        }

        // Filter by arena tiles if provided
        if let Some(arena) = arena_tiles {
            samples.retain(|s| s.tile_id.as_ref().map_or(true, |id| arena.contains(id)));
        }

        if samples.len() < 2 {
            return vec![];
        }

        // Sort by timestamp
        samples.sort_by_key(|s| s.t);

        // Extract elevations and smooth
        let elevations: Vec<f64> = samples.iter().map(|s| s.elevation_m.unwrap()).collect();
        let smoothed = smooth_elevations(&elevations, self.config.smoothing_window);
        let signature_smoothed = smooth_elevations(&elevations, SMOOTHING_WINDOW);

        // Segment climbs using chosen algorithm
        let segments = match self.config.algorithm {
            DetectionAlgorithm::Legacy => self.segment_climbs_legacy(&samples, &smoothed),
            DetectionAlgorithm::Momentum => self.segment_climbs_momentum(&samples, &smoothed),
        };

        if segments.is_empty() {
            return vec![];
        }

        // Precompute cumulative ascent for efficient range queries
        let cumulative = build_cumulative_ascent(&smoothed);
        let display_contract = DisplayClimbContract::default();
        let refinement = BoundaryRefinementConfig::new(
            self.config.gradient_min_pct,
            self.config.gradient_window,
            self.config.max_trim_ratio,
        );

        // Process each segment into a ClimbPattern
        let mut climbs = Vec::new();

        for seg in segments {
            // Trim flat run-ins/run-outs
            let (trimmed_start, trimmed_end) =
                refine_display_bounds(&samples, &smoothed, seg.start_idx, seg.end_idx, refinement, None);
            let trimmed_metrics =
                measure_display_segment(&samples, &smoothed, trimmed_start, trimmed_end);

            if !satisfies_display_contract(&trimmed_metrics, display_contract) {
                continue;
            }
            if trimmed_metrics.time_s < self.config.time_min_s
                || trimmed_metrics.time_s > self.config.time_max_s
            {
                continue;
            }
            if trimmed_metrics.ascent_m < self.config.vert_min_m {
                continue;
            }

            // Check VAM threshold
            let mut final_start = trimmed_start;
            let mut final_end = trimmed_end;
            let mut final_metrics = trimmed_metrics;
            let mut final_time_s = trimmed_metrics.time_s;
            let mut final_vert_m = trimmed_metrics.ascent_m;

            let vam = if final_time_s > 0 {
                (final_vert_m / final_time_s as f64) * 3600.0
            } else {
                0.0
            };

            if vam < self.config.vam_min {
                // Try to find high-VAM sub-segment
                if let Some((sub_start, sub_end)) =
                    self.find_high_vam_subsegment(&samples, &cumulative, trimmed_start, trimmed_end)
                {
                    final_start = sub_start;
                    final_end = sub_end;
                    final_metrics =
                        measure_display_segment(&samples, &smoothed, final_start, final_end);
                    if !satisfies_display_contract(&final_metrics, display_contract) {
                        continue;
                    }
                    final_time_s = final_metrics.time_s;
                    final_vert_m = final_metrics.ascent_m;
                } else {
                    continue; // Skip this segment
                }
            }

            // Extract window samples
            let window_samples = &samples[final_start..=final_end];

            // Calculate metrics
            let avg_power_w = calculate_average_power(window_samples);
            let avg_hr = calculate_average_hr(window_samples);
            let distance_m = if final_metrics.distance_m > 0.0 {
                Some(final_metrics.distance_m)
            } else {
                None
            };

            let w_per_kg = match (avg_power_w, user_weight_kg) {
                (Some(power), Some(weight)) if weight > 0.0 => Some(power / weight),
                _ => None,
            };

            let avg_gradient_pct = distance_m.map(|_| final_metrics.avg_gradient_pct);

            // Extract tile IDs
            let tile_ids: Vec<String> = window_samples
                .iter()
                .filter_map(|s| s.tile_id.clone())
                .collect::<HashSet<_>>()
                .into_iter()
                .collect();

            // Generate signature if enabled
            let signature_hex = if self.config.generate_signatures {
                self.generate_climb_signature(&samples, &smoothed, final_start, final_end)
            } else {
                None
            };
            let signature_v2_hex = if self.config.generate_signatures && window_samples.len() > 2 {
                let distances = build_effort_distances(window_samples);
                generate_signature_v2(
                    &signature_smoothed[final_start..=final_end],
                    &distances,
                    midpoint_h3(window_samples),
                    avg_power_w.is_some(),
                    0,
                )
                .map(|signature| signature.hex())
            } else {
                None
            };
            let (start_lat, start_lon) = reward_endpoint(&samples[final_start]);
            let (end_lat, end_lon) = reward_endpoint(&samples[final_end]);

            climbs.push(ClimbPattern {
                vert_m: final_vert_m,
                time_s: final_time_s,
                avg_power_w,
                w_per_kg,
                avg_hr,
                start_time_offset_s: samples[final_start].t as u32,
                end_time_offset_s: samples[final_end].t as u32,
                arena_id: None,
                tile_ids: if tile_ids.is_empty() {
                    None
                } else {
                    Some(tile_ids)
                },
                avg_gradient_pct,
                distance_m,
                signature_hex,
                signature_v2_hex,
                start_lat,
                start_lon,
                end_lat,
                end_lon,
            });

            if climbs.len() >= 25 {
                break;
            }
        }

        climbs
    }

    /// Segment climbs using legacy gradient + drop tolerance algorithm.
    fn segment_climbs_legacy(&self, samples: &[TileSample], smoothed: &[f64]) -> Vec<ClimbSegment> {
        let n = samples.len();
        if n < 2 {
            return vec![];
        }

        let cumulative = build_cumulative_ascent(smoothed);

        // Precompute gradients with config-specified window
        let gradient_window = self.config.gradient_window.max(5); // Minimum 5 samples
        let gradients: Vec<f64> = (0..n)
            .map(|i| calculate_local_gradient_with_window(samples, smoothed, i, gradient_window))
            .collect();

        let mut segments = Vec::new();
        let mut in_climb = false;
        let mut climb_start = 0;
        let mut peak_idx = 0;
        let mut peak_elev = 0.0;

        for i in 0..n {
            let gradient = gradients[i];
            let elev = smoothed[i];

            if !in_climb {
                if gradient >= self.config.gradient_start_threshold {
                    in_climb = true;
                    climb_start = i;
                    peak_idx = i;
                    peak_elev = elev;
                }
            } else {
                if elev > peak_elev {
                    peak_elev = elev;
                    peak_idx = i;
                }

                if (peak_elev - elev) > self.config.drop_tolerance_m {
                    // Emit segment if valid
                    if let Some(seg) =
                        self.maybe_create_segment(samples, &cumulative, climb_start, peak_idx)
                    {
                        segments.push(seg);
                    }
                    in_climb = false;
                }
            }
        }

        // Handle climb extending to end
        if in_climb {
            if let Some(seg) =
                self.maybe_create_segment(samples, &cumulative, climb_start, peak_idx)
            {
                segments.push(seg);
            }
        }

        segments.sort_by_key(|s| (s.start_idx, s.end_idx));
        segments
    }

    /// Segment climbs using momentum-based physics model.
    fn segment_climbs_momentum(
        &self,
        samples: &[TileSample],
        smoothed: &[f64],
    ) -> Vec<ClimbSegment> {
        let n = samples.len();
        if n < 2 {
            return vec![];
        }

        let cumulative = build_cumulative_ascent(smoothed);

        // Precompute gradients with config-specified window
        let gradient_window = self.config.gradient_window.max(5); // Minimum 5 samples
        let gradients: Vec<f64> = (0..n)
            .map(|i| calculate_local_gradient_with_window(samples, smoothed, i, gradient_window))
            .collect();

        let mut segments = Vec::new();
        let mut momentum = 0.0;
        let mut momentum_history = Vec::with_capacity(n);
        let mut in_climb = false;
        let mut climb_start = 0;
        let mut peak_idx = 0;
        let mut peak_elev = 0.0;

        for i in 0..n {
            let gradient = gradients[i];
            let elev = smoothed[i];

            // Update momentum based on gradient
            if gradient >= self.config.gradient_start_threshold {
                // Strong climbing: build momentum
                momentum += (gradient - self.config.momentum_gradient_neutral)
                    * self.config.momentum_climb_rate;
            } else if gradient >= self.config.momentum_gradient_neutral {
                // Gentle climbing: slow build
                momentum += (gradient - self.config.momentum_gradient_neutral)
                    * self.config.momentum_climb_rate
                    * 0.5;
            } else if gradient <= self.config.gradient_end_threshold {
                // Descending: drain momentum faster
                momentum += gradient * self.config.momentum_drain_rate;
            } else {
                // Flat: passive decay
                momentum *= self.config.momentum_decay_rate;
            }

            // Clamp momentum
            momentum = momentum.clamp(0.0, self.config.momentum_max);
            momentum_history.push(momentum);

            if !in_climb {
                if momentum >= self.config.momentum_start_threshold {
                    in_climb = true;
                    climb_start = Self::find_momentum_start(&momentum_history, i);
                    peak_idx = i;
                    peak_elev = elev;
                }
            } else {
                if elev > peak_elev {
                    peak_elev = elev;
                    peak_idx = i;
                }

                // Check for climb end
                if momentum <= self.config.momentum_end_threshold {
                    if let Some(seg) =
                        self.maybe_create_segment(samples, &cumulative, climb_start, peak_idx)
                    {
                        segments.push(seg);
                    }
                    in_climb = false;
                } else if (peak_elev - elev) > self.config.drop_tolerance_m {
                    // Hard drop - also ends climb
                    if let Some(seg) =
                        self.maybe_create_segment(samples, &cumulative, climb_start, peak_idx)
                    {
                        segments.push(seg);
                    }
                    in_climb = false;
                    momentum = 0.0;
                }
            }
        }

        // Handle climb extending to end
        if in_climb {
            if let Some(seg) =
                self.maybe_create_segment(samples, &cumulative, climb_start, peak_idx)
            {
                segments.push(seg);
            }
        }

        segments.sort_by_key(|s| (s.start_idx, s.end_idx));
        segments
    }

    /// Find where momentum started building (look back).
    fn find_momentum_start(momentum_history: &[f64], current_idx: usize) -> usize {
        if current_idx < 2 {
            return 0;
        }

        for i in (0..current_idx).rev() {
            if momentum_history[i] < 0.5 {
                return i + 1;
            }
        }
        0
    }

    /// Create a segment if it meets basic time/vert constraints.
    fn maybe_create_segment(
        &self,
        samples: &[TileSample],
        cumulative: &[f64],
        start_idx: usize,
        end_idx: usize,
    ) -> Option<ClimbSegment> {
        if end_idx <= start_idx {
            return None;
        }

        let time_s = (samples[end_idx].t - samples[start_idx].t) as u32;
        if time_s < self.config.time_min_s || time_s > self.config.time_max_s {
            return None;
        }

        let vert_m = vert_gain(cumulative, start_idx, end_idx);
        if vert_m < self.config.vert_min_m {
            return None;
        }

        Some(ClimbSegment { start_idx, end_idx })
    }

    /// Find high-VAM sub-segment within a rejected low-VAM segment.
    fn find_high_vam_subsegment(
        &self,
        samples: &[TileSample],
        cumulative: &[f64],
        start_idx: usize,
        end_idx: usize,
    ) -> Option<(usize, usize)> {
        let segment_len = end_idx - start_idx;
        if segment_len < 10 {
            return None;
        }

        let min_window = (self.config.time_min_s as usize).max(60);
        let mut best_vam = 0.0;
        let mut best_range = None;

        // Scan from end backwards with expanding windows
        for sub_end in (start_idx + min_window..=end_idx).rev().step_by(5) {
            for window_size in (min_window..segment_len.min(600)).step_by(30) {
                let sub_start = start_idx.max(sub_end.saturating_sub(window_size));
                if sub_start >= sub_end.saturating_sub(min_window) {
                    continue;
                }

                let sub_time = (samples[sub_end].t - samples[sub_start].t) as u32;
                if sub_time < self.config.time_min_s {
                    continue;
                }

                let sub_vert = vert_gain(cumulative, sub_start, sub_end);
                if sub_vert < self.config.vert_min_m {
                    continue;
                }

                let sub_vam = if sub_time > 0 {
                    (sub_vert / sub_time as f64) * 3600.0
                } else {
                    0.0
                };

                if sub_vam >= self.config.vam_min && sub_vam > best_vam {
                    best_vam = sub_vam;
                    best_range = Some((sub_start, sub_end));
                }
            }
        }

        best_range
    }

    /// Generate 64-byte signature for a climb segment.
    fn generate_climb_signature(
        &self,
        samples: &[TileSample],
        smoothed: &[f64],
        start_idx: usize,
        end_idx: usize,
    ) -> Option<String> {
        if end_idx <= start_idx || end_idx >= samples.len() {
            return None;
        }

        let segment_elevations: Vec<f64> = smoothed[start_idx..=end_idx].to_vec();
        let segment_timestamps: Vec<i64> =
            samples[start_idx..=end_idx].iter().map(|s| s.t).collect();

        // Calculate distances if GPS available
        let distances: Option<Vec<f64>> = {
            let segment_samples = &samples[start_idx..=end_idx];
            if segment_samples
                .iter()
                .all(|s| s.lat.is_some() && s.lon.is_some())
            {
                let mut dists = vec![0.0];
                for i in 1..segment_samples.len() {
                    let prev = &segment_samples[i - 1];
                    let curr = &segment_samples[i];
                    let d = haversine_m(
                        prev.lat.unwrap(),
                        prev.lon.unwrap(),
                        curr.lat.unwrap(),
                        curr.lon.unwrap(),
                    );
                    dists.push(dists.last().unwrap() + d);
                }
                Some(dists)
            } else {
                None
            }
        };

        generate_signature(
            &segment_elevations,
            &segment_timestamps,
            distances.as_deref(),
        )
        .map(|sig| sig.hex())
    }
}

fn reward_endpoint(sample: &TileSample) -> (Option<f64>, Option<f64>) {
    match (sample.lat, sample.lon) {
        (Some(lat), Some(lon)) if is_valid_gps(lat, lon) => (Some(lat), Some(lon)),
        _ => (None, None),
    }
}

/// Calculate local gradient at an index using a forward-looking window.
/// The window_size parameter allows terrain-adaptive gradient calculation.
fn calculate_local_gradient_with_window(
    samples: &[TileSample],
    smoothed: &[f64],
    idx: usize,
    window_size: usize,
) -> f64 {
    const ESTIMATED_CYCLING_SPEED_MPS: f64 = 5.0;

    let n = samples.len();
    if idx >= n - 1 {
        return 0.0;
    }

    let end_idx = (idx + window_size).min(n - 1);
    if end_idx <= idx {
        return 0.0;
    }

    let elev_delta = smoothed[end_idx] - smoothed[idx];
    let time_delta = (samples[end_idx].t - samples[idx].t) as f64;

    if time_delta <= 0.0 {
        return 0.0;
    }

    let horiz_dist_m = time_delta * ESTIMATED_CYCLING_SPEED_MPS;
    if horiz_dist_m <= 0.0 {
        return 0.0;
    }

    (elev_delta / horiz_dist_m) * 100.0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_sample(t: i64, elev: f64) -> TileSample {
        TileSample {
            t,
            tile_id: Some(format!("tile_{}", t)),
            elevation_m: Some(elev),
            power_w: Some(250),
            hr_bpm: Some(150),
            lat: None,
            lon: None,
        }
    }

    #[test]
    fn test_basic_climb_detection() {
        // Create a 10-minute climb gaining 420m (~7m per 10 seconds)
        let samples: Vec<TileSample> = (0..61)
            .map(|i| make_sample(i * 10, 1000.0 + (i as f64 * 7.0)))
            .collect();

        let detector = ClimbPatternDetector::with_defaults();
        let climbs = detector.detect_all(&samples, None, Some(75.0));

        assert!(!climbs.is_empty(), "Should detect at least one climb");
        let climb = &climbs[0];
        assert!(climb.vert_m >= 300.0, "Vert should be >= 300m");
        assert!(climb.time_s >= 120, "Time should be >= 2 minutes");
    }

    #[test]
    fn test_no_climb_on_flat() {
        // Flat terrain - no climb should be detected
        let samples: Vec<TileSample> = (0..100)
            .map(|i| make_sample(i * 10, 1000.0 + (i as f64 * 0.1)))
            .collect();

        let detector = ClimbPatternDetector::with_defaults();
        let climbs = detector.detect_all(&samples, None, None);

        assert!(climbs.is_empty(), "Should not detect climb on flat terrain");
    }

    #[test]
    fn test_momentum_algorithm() {
        let samples: Vec<TileSample> = (0..150)
            .map(|i| {
                let mut sample = make_sample(i * 10, 1000.0 + (i as f64 * 2.5));
                sample.lat = Some(39.95 + i as f64 * 0.00001);
                sample.lon = Some(-75.16);
                sample
            })
            .collect();

        let config = ClimbDetectorConfig {
            algorithm: DetectionAlgorithm::Momentum,
            ..Default::default()
        };
        let detector = ClimbPatternDetector::new(config);
        let climbs = detector.detect_all(&samples, None, None);

        assert!(!climbs.is_empty(), "Momentum algorithm should detect climb");
        assert!(climbs[0].signature_v2_hex.is_some());
        assert!(climbs[0].start_lat.is_some());
        assert!(climbs[0].start_lon.is_some());
        assert!(climbs[0].end_lat.is_some());
        assert!(climbs[0].end_lon.is_some());
    }

    #[test]
    fn reward_evidence_does_not_emit_null_island_endpoints() {
        let samples: Vec<TileSample> = (0..150)
            .map(|i| {
                let mut sample = make_sample(i * 10, 1000.0 + (i as f64 * 2.5));
                sample.lat = Some(0.0);
                sample.lon = Some(0.0);
                sample
            })
            .collect();

        let climbs = ClimbPatternDetector::with_defaults().detect_all(&samples, None, None);

        assert!(!climbs.is_empty());
        let signature = crate::climb::signature_v2::SignatureV2::from_hex(
            climbs[0].signature_v2_hex.as_deref().unwrap(),
        )
        .unwrap();
        assert_eq!(signature.h3_anchor, 0);
        assert_eq!(climbs[0].start_lat, None);
        assert_eq!(climbs[0].start_lon, None);
        assert_eq!(climbs[0].end_lat, None);
        assert_eq!(climbs[0].end_lon, None);
    }

    #[test]
    fn reward_signature_is_independent_of_detector_smoothing_tuning() {
        let samples: Vec<TileSample> = (0..150)
            .map(|i| {
                let ripple = if i % 6 < 3 { 0.8 } else { -0.8 };
                let mut sample = make_sample(i * 10, 1000.0 + (i as f64 * 2.5) + ripple);
                sample.lat = Some(39.95 + i as f64 * 0.00001);
                sample.lon = Some(-75.16);
                sample
            })
            .collect();

        let mut narrow_config = ClimbDetectorConfig::default();
        narrow_config.smoothing_window = 3;
        let mut wide_config = narrow_config.clone();
        wide_config.smoothing_window = 7;

        let narrow = ClimbPatternDetector::new(narrow_config).detect_all(&samples, None, None);
        let wide = ClimbPatternDetector::new(wide_config).detect_all(&samples, None, None);

        assert!(!narrow.is_empty());
        assert!(!wide.is_empty());
        assert_eq!(narrow[0].start_time_offset_s, wide[0].start_time_offset_s);
        assert_eq!(narrow[0].end_time_offset_s, wide[0].end_time_offset_s);
        assert_eq!(narrow[0].signature_v2_hex, wide[0].signature_v2_hex);
    }

    #[test]
    fn test_legacy_algorithm() {
        let samples: Vec<TileSample> = (0..150)
            .map(|i| make_sample(i * 10, 1000.0 + (i as f64 * 2.5)))
            .collect();

        let config = ClimbDetectorConfig {
            algorithm: DetectionAlgorithm::Legacy,
            ..Default::default()
        };
        let detector = ClimbPatternDetector::new(config);
        let climbs = detector.detect_all(&samples, None, None);

        assert!(!climbs.is_empty(), "Legacy algorithm should detect climb");
    }
}
