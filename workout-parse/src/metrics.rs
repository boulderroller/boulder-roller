//! Metrics calculation: NP, TSS, IF, and kcals.
//!
//! Server always recomputes these using server-side FTP.

use crate::constants::*;
use crate::error::{WpError, WpResult};

/// Semantic version of the authoritative effort-metrics engine.
pub const METRICS_VERSION: &str = "workout_parse_metrics_v1";

/// Represents a continuous segment of riding (between pauses).
/// Internal to crate - not exposed in Python API.
pub(crate) struct Segment {
    pub(crate) power: Vec<u16>, // 1Hz power values, 0 for coasting/dropout
}

/// Computed metrics for an activity.
#[derive(Debug, Clone)]
pub struct ComputedMetrics {
    pub duration_s: u32,
    pub moving_time_s: u32,
    pub distance_m: f32,
    pub elevation_gain_m: f32,

    // Power metrics (None if no power data)
    pub normalized_power_w: Option<u16>,
    pub(crate) normalized_power_raw: Option<f32>,
    pub avg_power_w: Option<u16>,
    pub max_power_w: Option<u16>,
    pub power_sample_count: u32,
    pub power_sample_coverage_bps: u16,
    pub normalized_power_duration_s: u32,

    // Effort metrics
    pub tss: Option<f32>,
    pub intensity_factor: Option<f32>,
    pub kcals: Option<u32>,

    // HR metrics
    pub avg_hr_bpm: Option<u8>,
    pub max_hr_bpm: Option<u8>,
    pub heart_rate_sample_count: u32,
    pub heart_rate_sample_coverage_bps: u16,

    // Speed
    pub avg_speed_mps: Option<f32>,
    pub max_speed_mps: Option<f32>,

    // Cadence
    pub avg_cadence_rpm: Option<u8>,
}

impl Default for ComputedMetrics {
    fn default() -> Self {
        Self {
            duration_s: 0,
            moving_time_s: 0,
            distance_m: 0.0,
            elevation_gain_m: 0.0,
            normalized_power_w: None,
            normalized_power_raw: None,
            avg_power_w: None,
            max_power_w: None,
            power_sample_count: 0,
            power_sample_coverage_bps: 0,
            normalized_power_duration_s: 0,
            tss: None,
            intensity_factor: None,
            kcals: None,
            avg_hr_bpm: None,
            max_hr_bpm: None,
            heart_rate_sample_count: 0,
            heart_rate_sample_coverage_bps: 0,
            avg_speed_mps: None,
            max_speed_mps: None,
            avg_cadence_rpm: None,
        }
    }
}

pub(crate) fn sample_coverage_bps(valid_samples: usize, total_samples: usize) -> u16 {
    if total_samples == 0 {
        return 0;
    }
    ((valid_samples.saturating_mul(10_000) / total_samples).min(10_000)) as u16
}

pub(crate) fn continuous_moving_time_s(time_ms: &[i64]) -> u32 {
    let Some(&first) = time_ms.first() else {
        return 0;
    };

    let mut segment_start = first;
    let mut previous = first;
    let mut total_seconds = 0u64;

    for &timestamp in time_ms.iter().skip(1) {
        if timestamp.saturating_sub(previous) > PAUSE_THRESHOLD_S * 1_000 {
            let segment_seconds = previous
                .saturating_sub(segment_start)
                .div_euclid(1_000)
                .saturating_add(1);
            total_seconds = total_seconds.saturating_add(segment_seconds.max(1) as u64);
            segment_start = timestamp;
        }
        previous = timestamp;
    }

    let segment_seconds = previous
        .saturating_sub(segment_start)
        .div_euclid(1_000)
        .saturating_add(1);
    total_seconds = total_seconds.saturating_add(segment_seconds.max(1) as u64);
    total_seconds.min(u32::MAX as u64) as u32
}

// Shared segment boundaries and bucket extent for coverage and pricing.
fn effort_segments(time_ms: &[i64]) -> Vec<(usize, usize, i64, usize)> {
    if time_ms.len() < 2 || time_ms.last() <= time_ms.first() {
        return vec![];
    }
    let mut boundaries = vec![0];
    for i in 1..time_ms.len() {
        if time_ms[i] - time_ms[i - 1] > PAUSE_THRESHOLD_S * 1000 {
            boundaries.push(i);
        }
    }
    boundaries.push(time_ms.len());
    boundaries
        .windows(2)
        .filter_map(|w| {
            let (a, b) = (w[0], w[1]);
            let start = time_ms[a];
            let end = time_ms[b - 1];
            (end > start).then(|| (a, b, start, ((end - start) / 1000) as usize + 1))
        })
        .collect()
}

pub(crate) fn effort_spans_ms(time_ms: &[i64]) -> Vec<(i64, i64)> {
    effort_segments(time_ms)
        .iter()
        .map(|&(_, _, start, n)| (start, start + n as i64 * 1000))
        .collect()
}

/// Resample first, then retain whole buckets. Removed seconds always split NP runs.
pub(crate) fn compute_power_metrics_in_spans(
    time_ms: &[i64],
    power_w: &[u16],
    keep_ms: &[(i64, i64)],
) -> WpResult<(ComputedMetrics, Vec<(i64, i64)>)> {
    if time_ms.len() != power_w.len() || time_ms.windows(2).any(|w| w[1] < w[0]) {
        return Err(WpError::Parse("invalid power metric arrays".into()));
    }
    let segments = resample_power_1hz(time_ms, power_w)?;
    let bounds = effort_segments(time_ms);
    let mut runs = Vec::new();
    let mut spans: Vec<(i64, i64)> = Vec::new();
    let mut valid = Vec::new();
    let mut sample_count = 0;
    for (segment, &(a, b, start, _)) in segments.iter().zip(bounds.iter()) {
        let kept: Vec<bool> = (0..segment.power.len())
            .map(|i| {
                let s = start + i as i64 * 1000;
                keep_ms.iter().any(|&(lo, hi)| lo <= s && s + 1000 <= hi)
            })
            .collect();
        let mut run = Vec::new();
        for (i, &power) in segment.power.iter().enumerate() {
            if kept[i] {
                let s = start + i as i64 * 1000;
                if let Some(last) = spans.last_mut().filter(|last| last.1 == s) {
                    last.1 = s + 1000;
                } else {
                    spans.push((s, s + 1000));
                }
                run.push(power);
            } else if !run.is_empty() {
                runs.push(Segment {
                    power: std::mem::take(&mut run),
                });
            }
        }
        if !run.is_empty() {
            runs.push(Segment { power: run });
        }
        for i in a..b {
            let bucket = ((time_ms[i] - start) / 1000) as usize;
            if kept.get(bucket) == Some(&true) {
                sample_count += 1;
                if power_w[i] != MISSING_U16 {
                    valid.push(power_w[i]);
                }
            }
        }
    }
    let mut metrics = ComputedMetrics::default();
    metrics.moving_time_s = runs.iter().map(|r| r.power.len() as u32).sum();
    metrics.duration_s = metrics.moving_time_s;
    metrics.power_sample_count = valid.len() as u32;
    metrics.power_sample_coverage_bps = sample_coverage_bps(valid.len(), sample_count);
    if !valid.is_empty() {
        metrics.max_power_w = valid.iter().max().copied();
        let sum: u64 = runs.iter().flat_map(|r| &r.power).map(|&v| v as u64).sum();
        if metrics.moving_time_s > 0 {
            metrics.avg_power_w = Some((sum as f64 / metrics.moving_time_s as f64).round() as u16);
        }
        metrics.normalized_power_raw = calculate_np(&runs);
        metrics.normalized_power_w = metrics.normalized_power_raw.map(|v| v.round() as u16);
        metrics.normalized_power_duration_s = runs
            .iter()
            .filter(|r| r.power.len() >= NP_WINDOW_S)
            .map(|r| r.power.len() as u32)
            .sum();
    }
    Ok((metrics, spans))
}

/// Resample power data to 1Hz for accurate NP calculation.
///
/// Key behaviors:
/// - Bins samples into 1-second buckets
/// - Missing samples (MISSING_U16) within continuous riding -> treated as 0W
/// - No samples in a given second (smart recording) -> carry-forward last known power
/// - Gaps > PAUSE_THRESHOLD_S -> segment boundary (pause)
/// - Returns segments, not a single array, to handle pauses correctly
pub(crate) fn resample_power_1hz(time_ms: &[i64], power_w: &[u16]) -> WpResult<Vec<Segment>> {
    if time_ms.len() != power_w.len() || time_ms.is_empty() {
        return Ok(vec![]);
    }

    let start_ms = time_ms[0];
    let end_ms = time_ms[time_ms.len() - 1];

    // Guard against corrupt timestamps (end before or equal to start)
    if end_ms <= start_ms {
        return Ok(vec![]); // No valid duration
    }

    let duration_s = ((end_ms - start_ms) / 1000) as usize;

    // OOM protection: reject corrupt files with huge timestamp spans
    if duration_s > MAX_ACTIVITY_DURATION_S {
        return Err(WpError::DurationLimitExceeded(format!(
            "Activity span {}s exceeds max {}s",
            duration_s, MAX_ACTIVITY_DURATION_S
        )));
    }

    let mut segments: Vec<Segment> = Vec::new();
    for (seg_start_idx, seg_end_idx, seg_start_ms, seg_duration_s) in effort_segments(time_ms) {
        // Bin samples into 1-second buckets
        let mut bucket_sums: Vec<u64> = vec![0; seg_duration_s];
        let mut bucket_counts: Vec<u32> = vec![0; seg_duration_s];

        for i in seg_start_idx..seg_end_idx {
            let bucket = ((time_ms[i] - seg_start_ms) / 1000) as usize;
            if bucket < seg_duration_s {
                let p = power_w[i];
                // MISSING_U16 -> treat as 0W (sensor dropout)
                // 0 -> valid 0W (coasting)
                let effective_power = if p == MISSING_U16 { 0 } else { p };
                bucket_sums[bucket] += effective_power as u64;
                bucket_counts[bucket] += 1;
            }
        }

        // Build 1Hz power array with carry-forward for sparse samples
        let mut power_1hz: Vec<u16> = Vec::with_capacity(seg_duration_s);

        // Seed carry-forward with the first available bucket average
        let mut last_power: u16 = 0;
        for i in 0..seg_duration_s {
            if bucket_counts[i] > 0 {
                last_power = (bucket_sums[i] / bucket_counts[i] as u64) as u16;
                break;
            }
        }

        for i in 0..seg_duration_s {
            if bucket_counts[i] > 0 {
                last_power = (bucket_sums[i] / bucket_counts[i] as u64) as u16;
            }
            // No samples in this second (smart recording) -> hold-last-value
            power_1hz.push(last_power);
        }

        segments.push(Segment { power: power_1hz });
    }

    Ok(segments)
}

/// Calculate Normalized Power from segments.
///
/// NP is calculated per-segment, then combined weighted by segment duration.
/// This correctly handles pauses without inflating NP.
pub(crate) fn calculate_np(segments: &[Segment]) -> Option<f32> {
    if segments.is_empty() {
        return None;
    }

    let mut total_fourth_power_sum: f64 = 0.0;
    let mut total_windows: usize = 0;

    for seg in segments {
        if seg.power.len() < NP_WINDOW_S {
            continue;
        }

        // O(n) sliding window for 30-second rolling average
        let mut window_sum: u64 = 0;
        for i in 0..NP_WINDOW_S {
            window_sum += seg.power[i] as u64;
        }

        let mut rolling_avg = window_sum as f64 / NP_WINDOW_S as f64;
        total_fourth_power_sum += rolling_avg.powi(4);
        total_windows += 1;

        for i in NP_WINDOW_S..seg.power.len() {
            window_sum -= seg.power[i - NP_WINDOW_S] as u64;
            window_sum += seg.power[i] as u64;
            rolling_avg = window_sum as f64 / NP_WINDOW_S as f64;
            total_fourth_power_sum += rolling_avg.powi(4);
            total_windows += 1;
        }
    }

    if total_windows == 0 {
        return None;
    }

    Some((total_fourth_power_sum / total_windows as f64).powf(0.25) as f32)
}

/// Compute the power-bearing subset of canonical metrics for any time window.
///
/// Ride-level and climb-window metrics both call this function so pause,
/// dropout, smart-recording, averaging, and NP behavior cannot drift.
pub(crate) fn compute_power_metrics(time_ms: &[i64], power_w: &[u16]) -> WpResult<ComputedMetrics> {
    if time_ms.len() != power_w.len() {
        return Err(WpError::Parse(
            "power metric timestamps and values must have equal lengths".to_string(),
        ));
    }
    if time_ms.windows(2).any(|window| window[1] < window[0]) {
        return Err(WpError::InvalidTimestamp(
            "power metric timestamps must be monotonic".to_string(),
        ));
    }

    let mut metrics = ComputedMetrics::default();
    metrics.moving_time_s = continuous_moving_time_s(time_ms);

    let valid_power: Vec<u16> = power_w
        .iter()
        .take(time_ms.len())
        .filter_map(|&power| (power != MISSING_U16).then_some(power))
        .collect();
    metrics.power_sample_count = valid_power.len().min(u32::MAX as usize) as u32;
    metrics.power_sample_coverage_bps = sample_coverage_bps(valid_power.len(), time_ms.len());

    if valid_power.is_empty() {
        return Ok(metrics);
    }

    metrics.max_power_w = valid_power.iter().max().copied();
    let segments = resample_power_1hz(time_ms, power_w)?;
    let resampled_count: usize = segments.iter().map(|segment| segment.power.len()).sum();
    if resampled_count > 0 {
        let resampled_sum: u64 = segments
            .iter()
            .flat_map(|segment| segment.power.iter())
            .map(|&power| u64::from(power))
            .sum();
        metrics.avg_power_w = Some((resampled_sum as f64 / resampled_count as f64).round() as u16);
    }
    metrics.normalized_power_raw = calculate_np(&segments);
    metrics.normalized_power_w = metrics
        .normalized_power_raw
        .map(|normalized_power| normalized_power.round() as u16);
    metrics.normalized_power_duration_s = segments
        .iter()
        .filter(|segment| segment.power.len() >= NP_WINDOW_S)
        .map(|segment| segment.power.len())
        .sum::<usize>()
        .min(u32::MAX as usize) as u32;

    Ok(metrics)
}

/// Compute the ratified 3/7/15-minute mean-max power anchors.
///
/// This deliberately reuses the canonical power resampling path so smart
/// recording, dropout, and pause behavior cannot drift from the reward-bearing
/// ride metrics. Windows never cross a pause boundary.
/// Pause-aware mean-maximal power at each requested duration (seconds).
/// One arithmetic for every reading of "best power over N seconds": the
/// Threshold anchors and the rider power curve both come through here.
pub(crate) fn compute_mean_max_power(
    time_ms: &[i64],
    power_w: &[u16],
    durations_s: &[usize],
) -> WpResult<Vec<Option<f64>>> {
    if time_ms.len() != power_w.len() {
        return Err(WpError::Parse(
            "mean-max timestamps and values must have equal lengths".to_string(),
        ));
    }
    if time_ms.windows(2).any(|window| window[1] < window[0]) {
        return Err(WpError::InvalidTimestamp(
            "mean-max timestamps must be monotonic".to_string(),
        ));
    }

    let segments = resample_power_1hz(time_ms, power_w)?;
    let mut best = vec![None; durations_s.len()];

    for (slot, &duration_s) in durations_s.iter().enumerate() {
        if duration_s == 0 {
            continue;
        }
        let mut best_sum: Option<u64> = None;
        for segment in &segments {
            if segment.power.len() < duration_s {
                continue;
            }

            let mut window_sum: u64 = segment.power[..duration_s]
                .iter()
                .map(|&power| u64::from(power))
                .sum();
            best_sum = Some(best_sum.map_or(window_sum, |current| current.max(window_sum)));

            for index in duration_s..segment.power.len() {
                window_sum -= u64::from(segment.power[index - duration_s]);
                window_sum += u64::from(segment.power[index]);
                best_sum = Some(best_sum.map_or(window_sum, |current| current.max(window_sum)));
            }
        }
        best[slot] = best_sum.map(|sum| sum as f64 / duration_s as f64);
    }

    Ok(best)
}

pub(crate) fn compute_threshold_power_anchors(
    time_ms: &[i64],
    power_w: &[u16],
) -> WpResult<[Option<f64>; 3]> {
    let values = compute_mean_max_power(time_ms, power_w, &[180, 420, 900])?;
    Ok([values[0], values[1], values[2]])
}

/// Calculate TSS from NP and FTP.
/// TSS = (duration_sec * NP * IF) / (FTP * 3600) * 100
pub fn calculate_tss(duration_s: u32, np: f32, ftp: u16) -> f32 {
    if ftp == 0 {
        return 0.0;
    }
    let intensity_factor = np / ftp as f32;
    (duration_s as f32 * np * intensity_factor) / (ftp as f32 * 3600.0) * 100.0
}

/// Calculate Intensity Factor.
pub fn calculate_if(np: f32, ftp: u16) -> f32 {
    if ftp == 0 {
        return 0.0;
    }
    np / ftp as f32
}

/// Calculate kcals from average power and duration.
/// Uses ~25% mechanical efficiency.
pub fn calculate_kcals(avg_power_w: u16, duration_s: u32) -> u32 {
    const CYCLING_EFFICIENCY: f32 = 0.25;
    const KCAL_PER_KJ: f32 = 0.239;

    let work_kj = (avg_power_w as f32 * duration_s as f32) / 1000.0;
    (work_kj / CYCLING_EFFICIENCY * KCAL_PER_KJ) as u32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn effort_trim_never_bridges_removed_buckets() {
        let times: Vec<i64> = (0..120).map(|i| i * 1000).collect();
        let power = vec![200; 120];
        let full = compute_power_metrics(&times, &power).unwrap();
        let (kept, spans) =
            compute_power_metrics_in_spans(&times, &power, &effort_spans_ms(&times)).unwrap();
        assert_eq!(spans, vec![(0, 120000)]);
        assert_eq!(kept.normalized_power_raw, full.normalized_power_raw);
        assert_eq!(
            kept.normalized_power_duration_s,
            full.normalized_power_duration_s
        );
        assert_eq!(
            calculate_tss(
                kept.normalized_power_duration_s,
                kept.normalized_power_raw.unwrap(),
                200
            ),
            calculate_tss(
                full.normalized_power_duration_s,
                full.normalized_power_raw.unwrap(),
                200
            )
        );
        let (trimmed, spans) =
            compute_power_metrics_in_spans(&times, &power, &[(0, 60000), (70000, 120000)]).unwrap();
        assert_eq!(spans, vec![(0, 60000), (70000, 120000)]);
        assert_eq!(trimmed.moving_time_s, 110);
        assert_eq!(trimmed.normalized_power_duration_s, 110);
        assert_eq!(trimmed.normalized_power_raw, Some(200.0));
        let (short, _) =
            compute_power_metrics_in_spans(&times, &power, &[(0, 20000), (25000, 45000)]).unwrap();
        assert_eq!(short.normalized_power_raw, None);
        assert_eq!(short.normalized_power_duration_s, 0);
        let (empty, spans) = compute_power_metrics_in_spans(&times, &power, &[]).unwrap();
        assert_eq!(empty.normalized_power_raw, None);
        assert!(spans.is_empty());
    }

    #[test]
    fn test_np_steady_state() {
        // 60 seconds at constant 200W -> NP should be ~200W
        let power = vec![200u16; 60];
        let seg = Segment { power };
        let np = calculate_np(&[seg]).unwrap();
        assert!((np - 200.0).abs() < 1.0);
    }

    #[test]
    fn test_np_variability() {
        // Variability across the 30s rolling window should increase NP above avg.
        // (Alternating 1s on/1s off averages out within the 30s window and can yield NP == avg.)
        let mut power = vec![100u16; 60];
        for p in power.iter_mut().skip(30) {
            *p = 300;
        }
        let seg = Segment { power };
        let np = calculate_np(&[seg]).unwrap();
        // Avg is 200, NP should be higher due to variability
        assert!(np > 200.0);
    }

    #[test]
    fn test_tss_one_hour_at_ftp() {
        // 1 hour at FTP = 100 TSS
        let tss = calculate_tss(3600, 200.0, 200);
        assert!((tss - 100.0).abs() < 1.0);
    }

    #[test]
    fn test_resample_keeps_zero_power_and_splits_pauses() {
        let time_ms: Vec<i64> = (0..60)
            .chain(360..420)
            .map(|second| second * 1_000)
            .collect();
        let power: Vec<u16> = (0..120)
            .map(|index| if index % 5 == 0 { 0 } else { 200 })
            .collect();

        let segments = resample_power_1hz(&time_ms, &power).unwrap();

        assert_eq!(segments.len(), 2);
        assert_eq!(segments[0].power.len(), 60);
        assert_eq!(segments[1].power.len(), 60);
        assert_eq!(segments[0].power[0], 0);
        assert_eq!(segments[0].power[1], 200);
    }

    #[test]
    fn test_short_segments_remain_available_for_non_np_metrics() {
        let segments = resample_power_1hz(&[0, 1_000, 2_000], &[200, 0, 240]).unwrap();

        assert_eq!(segments.len(), 1);
        assert_eq!(segments[0].power, vec![200, 0, 240]);
        assert!(calculate_np(&segments).is_none());
    }

    #[test]
    fn test_power_metrics_reuse_pause_aware_np_for_a_climb_window() {
        let time_ms: Vec<i64> = (0..60)
            .chain(360..420)
            .map(|second| second * 1_000)
            .collect();
        let power_w: Vec<u16> = (0..60).map(|_| 200).chain((0..60).map(|_| 300)).collect();

        let metrics = compute_power_metrics(&time_ms, &power_w).unwrap();

        assert_eq!(metrics.moving_time_s, 120);
        assert_eq!(metrics.power_sample_count, 120);
        assert_eq!(metrics.power_sample_coverage_bps, 10_000);
        assert_eq!(metrics.avg_power_w, Some(250));
        assert_eq!(metrics.normalized_power_w, Some(264));
    }

    #[test]
    fn test_power_metrics_count_missing_samples_without_treating_them_as_recorded() {
        let time_ms: Vec<i64> = (0..60).map(|second| second * 1_000).collect();
        let power_w: Vec<u16> = (0..60)
            .map(|second| if second % 2 == 0 { 200 } else { MISSING_U16 })
            .collect();

        let metrics = compute_power_metrics(&time_ms, &power_w).unwrap();

        assert_eq!(metrics.power_sample_count, 30);
        assert_eq!(metrics.power_sample_coverage_bps, 5_000);
        assert_eq!(metrics.avg_power_w, Some(100));
        assert_eq!(metrics.normalized_power_w, Some(100));
    }

    #[test]
    fn test_mean_max_ladder_reproduces_threshold_anchors_exactly() {
        let time_ms: Vec<i64> = (0..1200).map(|i| i * 1000).collect();
        let power_w: Vec<u16> = (0..1200).map(|i| 150 + ((i * 7) % 90) as u16).collect();
        let anchors = compute_threshold_power_anchors(&time_ms, &power_w).unwrap();
        let ladder =
            compute_mean_max_power(&time_ms, &power_w, &[5, 60, 180, 420, 900, 3600]).unwrap();
        assert_eq!(ladder[2], anchors[0]);
        assert_eq!(ladder[3], anchors[1]);
        assert_eq!(ladder[4], anchors[2]);
        assert!(ladder[0].unwrap() >= ladder[1].unwrap());
        assert!(
            ladder[5].is_none(),
            "ride shorter than the window yields no value"
        );
    }

    #[test]
    fn test_threshold_anchors_use_pause_aware_mean_max_power() {
        let time_ms: Vec<i64> = (0..900).map(|second| second * 1_000).collect();
        let power_w: Vec<u16> = (0..900)
            .map(|second| match second {
                0..=179 => 400,
                180..=419 => 300,
                _ => 250,
            })
            .collect();

        let anchors = compute_threshold_power_anchors(&time_ms, &power_w).unwrap();

        assert_eq!(anchors[0], Some(400.0));
        assert!((anchors[1].unwrap() - 342.857_142).abs() < 0.000_01);
        assert!((anchors[2].unwrap() - 293.333_333).abs() < 0.000_01);
    }

    #[test]
    fn test_threshold_anchors_never_bridge_a_pause() {
        let time_ms: Vec<i64> = (0..500)
            .chain(1_000..1_500)
            .map(|second| second * 1_000)
            .collect();
        let power_w = vec![300; 1_000];

        let anchors = compute_threshold_power_anchors(&time_ms, &power_w).unwrap();

        assert_eq!(anchors, [Some(300.0), Some(300.0), None]);
    }
}
