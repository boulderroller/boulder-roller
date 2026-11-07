//! Offline 10 s-grid partition search, using the production resampler and TSS.
//! Not part of admission. JSON lines in/out let the corpus harness reuse one process.
use std::io::{self, BufRead};
use workout_parse::{constants, error};
#[allow(dead_code)]
#[path = "../src/metrics.rs"]
mod metrics;

struct Prefix {
    start: i64,
    len: usize,
    fourth: Vec<f64>,
}

fn optimal(
    time: &[i64],
    power: &[u16],
    grid_s: i64,
    minimum: [usize; 3],
) -> error::WpResult<serde_json::Value> {
    let segments = metrics::resample_power_1hz(time, power)?;
    let mut valid_prefix = vec![0_usize];
    for &p in power {
        valid_prefix.push(valid_prefix.last().unwrap() + usize::from(p != constants::MISSING_U16));
    }
    let spans = metrics::effort_spans_ms(time);
    let mut prefixes = Vec::new();
    for (segment, &(start, _)) in segments.iter().zip(&spans) {
        let mut fourth = vec![0.0];
        let mut sum = 0_u64;
        for (i, &p) in segment.power.iter().enumerate() {
            sum += p as u64;
            if i >= constants::NP_WINDOW_S {
                sum -= segment.power[i - constants::NP_WINDOW_S] as u64;
            }
            if i + 1 >= constants::NP_WINDOW_S {
                fourth.push(
                    fourth.last().unwrap() + (sum as f64 / constants::NP_WINDOW_S as f64).powi(4),
                );
            }
        }
        prefixes.push(Prefix {
            start,
            len: segment.power.len(),
            fourth,
        });
    }
    let (start, end) = match (spans.first(), spans.last()) {
        (Some(a), Some(b)) => (a.0, b.1),
        _ => return Ok(serde_json::json!({"raw": [], "cal": []})),
    };
    let mut cuts: Vec<i64> = (start..end).step_by((grid_s * 1000) as usize).collect();
    cuts.push(end);
    let n = cuts.len();
    let mut best = vec![[0.0_f64; 2]; n];
    let mut previous = vec![[0_usize; 2]; n];
    for j in 1..n {
        for i in 0..j {
            let mut fourth = 0.0;
            let mut windows = 0;
            let mut duration = 0;
            let mut moving = 0;
            let mut sample_count = 0;
            let mut valid_count = 0;
            for segment in &prefixes {
                // Whole-bucket containment, exactly as the in-spans metric path.
                let lo = ((cuts[i] - segment.start + 999).div_euclid(1000))
                    .clamp(0, segment.len as i64) as usize;
                let hi = ((cuts[j] - segment.start).div_euclid(1000)).clamp(0, segment.len as i64)
                    as usize;
                moving += hi.saturating_sub(lo);
                let a = time.partition_point(|t| *t < segment.start + lo as i64 * 1000);
                let b = time.partition_point(|t| *t < segment.start + hi as i64 * 1000);
                sample_count += b - a;
                valid_count += valid_prefix[b] - valid_prefix[a];
                if hi.saturating_sub(lo) < constants::NP_WINDOW_S {
                    continue;
                }
                let last = hi - constants::NP_WINDOW_S + 1;
                fourth += segment.fourth[last] - segment.fourth[lo];
                windows += last - lo;
                duration += hi - lo;
            }
            let raw = if windows == 0 {
                0.0
            } else {
                let np = (fourth / windows as f64).max(0.0).powf(0.25) as f32;
                metrics::calculate_tss(duration as u32, np, 200) as f64
            };
            let tenths = (raw * 10.0).round_ties_even();
            // Sub-1-TSS files claim/pay nothing under the admitted policy.
            let eligible = valid_count >= minimum[0]
                && metrics::sample_coverage_bps(valid_count, sample_count) as usize >= minimum[1]
                && moving >= minimum[2];
            let cal = if eligible && tenths >= 10.0 {
                tenths
            } else {
                0.0
            };
            for (objective, value) in [raw, cal].into_iter().enumerate() {
                if i == 0 || best[i][objective] + value > best[j][objective] {
                    best[j][objective] = best[i][objective] + value;
                    previous[j][objective] = i;
                }
            }
        }
    }
    let witnesses: Vec<Vec<(i64, i64)>> = (0..2)
        .map(|objective| {
            let mut parts = Vec::new();
            let mut j = n - 1;
            while j > 0 {
                let i = previous[j][objective];
                parts.push((cuts[i], cuts[j]));
                j = i;
            }
            parts.reverse();
            parts
        })
        .collect();
    Ok(
        serde_json::json!({"raw": witnesses[0], "cal": witnesses[1], "raw_tss": best[n-1][0], "cal_tenths": best[n-1][1]}),
    )
}

fn main() {
    for line in io::stdin().lock().lines() {
        let value: serde_json::Value = serde_json::from_str(&line.unwrap()).unwrap();
        let times: Vec<i64> = serde_json::from_value(value["times"].clone()).unwrap();
        let power: Vec<Option<u16>> = serde_json::from_value(value["power"].clone()).unwrap();
        let power: Vec<u16> = power
            .into_iter()
            .map(|p| p.unwrap_or(constants::MISSING_U16))
            .collect();
        println!(
            "{}",
            optimal(
                &times,
                &power,
                value["grid_s"].as_i64().unwrap(),
                serde_json::from_value(value["minimum"].clone()).unwrap()
            )
            .unwrap()
        );
    }
}

#[cfg(test)]
mod search_tests {
    use super::*;

    #[test]
    fn sparse_power_cannot_earn_from_interpolated_buckets() {
        let times: Vec<i64> = (0..18).map(|i| i * 5000).collect();
        let power = vec![400; 18];
        assert_eq!(
            optimal(&times, &power, 10, [30, 5000, 30]).unwrap()["cal_tenths"],
            0.0
        );
    }

    #[test]
    fn grid_search_matches_exhaustive_native_partition_prices() {
        let times: Vec<i64> = (0..90).map(|i| i * 1000).collect();
        let power: Vec<u16> = (0..90)
            .map(|i| if (30..60).contains(&i) { 400 } else { 100 })
            .collect();
        let mut best = 0.0_f64;
        for mask in 0..(1 << 8) {
            let mut cuts = vec![0];
            for i in 1..9 {
                if mask & (1 << (i - 1)) != 0 {
                    cuts.push(i * 10000);
                }
            }
            cuts.push(90000);
            let mut total = 0.0;
            for w in cuts.windows(2) {
                let (m, _) =
                    metrics::compute_power_metrics_in_spans(&times, &power, &[(w[0], w[1])])
                        .unwrap();
                let tss = m
                    .normalized_power_raw
                    .map(|np| metrics::calculate_tss(m.normalized_power_duration_s, np, 200) as f64)
                    .unwrap_or(0.0);
                let tenths = (tss * 10.0).round_ties_even();
                if tenths >= 10.0 {
                    total += tenths;
                }
            }
            best = best.max(total);
        }
        assert_eq!(
            optimal(&times, &power, 10, [30, 5000, 30]).unwrap()["cal_tenths"]
                .as_f64()
                .unwrap(),
            best
        );
    }
}
