//! Versioned training arithmetic. No effort, TSS, CAL or settlement caller uses this path.
//! The data-free Python oracle lives in tools/analytics_reference/icu_reference.py.
//! NP retains the reference zero-filled stream; work and zones use limited
//! dropout repair. The backend opts into v3 for unsmoothed, configured HR
//! zones and explicit calorie provenance. v1 and v2 remain replayable.

use crate::constants::{MAX_ACTIVITY_DURATION_S, MISSING_I32, MISSING_U16, MISSING_U8};
use crate::error::{WpError, WpResult};
use crate::ParsedActivity;
#[cfg(feature = "python")]
use pyo3::prelude::*;

pub const TRAINING_ENGINE_VERSION: u32 = 1;
const LATEST_TRAINING_ENGINE_VERSION: u32 = 3;

#[derive(Debug, Clone, Default)]
#[cfg_attr(feature = "python", pyclass(get_all))]
pub struct TrainingMetrics {
    pub engine_version: u32,
    pub load_basis: Option<String>,
    pub calories_estimate: bool,
    pub calories_basis: Option<String>,
    pub power_zone_tops_w: Option<Vec<u32>>,
    pub hr_zone_tops_bpm: Option<Vec<u32>>,
    pub power_curve_s: Vec<u32>,
    pub power_curve_w: Option<Vec<Option<f64>>>,
    pub best_20m_hr_bpm: Option<f64>,
    pub elapsed_s: Option<u32>,
    pub recording_s: Option<u32>,
    pub moving_s: Option<u32>,
    pub np_raw_w: Option<f64>,
    pub np_w: Option<u32>,
    pub load: Option<u32>,
    pub intensity_pct: Option<f64>,
    pub avg_power_w: Option<f64>,
    pub work_j: Option<f64>,
    pub variability_index: Option<f64>,
    pub efficiency_factor: Option<f64>,
    pub distance_m: Option<f64>,
    pub elevation_gain_m: Option<f64>,
    pub avg_hr_bpm: Option<f64>,
    pub max_hr_bpm: Option<u8>,
    pub avg_cadence_rpm: Option<f64>,
    pub max_cadence_rpm: Option<f64>,
    pub avg_speed_mps: Option<f64>,
    pub max_speed_mps: Option<f64>,
    pub max_power_w: Option<f64>,
    pub calories_kcal: Option<f64>,
    pub decoupling_pct: Option<f64>,
    pub power_zone_s: Option<Vec<u32>>,
    pub hr_zone_s: Option<Vec<u32>>,
}

#[derive(Debug, Clone)]
pub struct TrainingOptions {
    pub engine_version: u32,
    pub lthr_bpm: Option<f64>,
    pub resting_hr_bpm: f64,
    pub max_hr_bpm: Option<f64>,
    pub hrss_k: f64,
    pub ftp_w: f64,
    pub gap_fill_s: u32,
    /// Six zone separators; a conventional seventh entry is accepted but Z7
    /// remains open-ended.
    pub power_zones_pct: Vec<f64>,
    pub sweet_spot_pct: (f64, f64),
    /// Inclusive tops, including the last zone's top.
    pub hr_zones_bpm: Option<Vec<f64>>,
}

impl Default for TrainingOptions {
    fn default() -> Self {
        Self {
            engine_version: 1,
            lthr_bpm: None,
            resting_hr_bpm: 60.0,
            max_hr_bpm: None,
            hrss_k: 1.92,
            ftp_w: 0.0,
            gap_fill_s: 30,
            power_zones_pct: vec![55.0, 75.0, 90.0, 105.0, 120.0, 150.0],
            sweet_spot_pct: (84.0, 97.0),
            hr_zones_bpm: None,
        }
    }
}

fn validate(activity: &ParsedActivity, options: &TrainingOptions) -> WpResult<()> {
    if !(1..=LATEST_TRAINING_ENGINE_VERSION).contains(&options.engine_version)
        || !options.resting_hr_bpm.is_finite()
        || options.resting_hr_bpm < 0.0
        || !options.hrss_k.is_finite()
        || options.hrss_k <= 0.0
        || options
            .lthr_bpm
            .is_some_and(|v| !v.is_finite() || v <= options.resting_hr_bpm || v >= 255.0)
        || options
            .max_hr_bpm
            .is_some_and(|v| !v.is_finite() || v <= options.resting_hr_bpm || v >= 255.0)
    {
        return Err(WpError::Parse(
            "invalid training physiology or engine version".into(),
        ));
    }
    let n = activity.time_ms.len();
    let lengths = [
        activity.pwr_w.as_ref().map(Vec::len),
        activity.speed_mps.as_ref().map(Vec::len),
        activity.hr_bpm.as_ref().map(Vec::len),
        activity.cadence_rpm.as_ref().map(Vec::len),
        activity.dist_m.as_ref().map(Vec::len),
        activity.elevation_m.as_ref().map(Vec::len),
        activity.lat_e7.as_ref().map(Vec::len),
        activity.lon_e7.as_ref().map(Vec::len),
    ];
    if lengths.into_iter().flatten().any(|len| len != n) {
        return Err(WpError::Parse(
            "training arrays must have equal lengths".into(),
        ));
    }
    if activity.time_ms.windows(2).any(|w| w[1] < w[0]) {
        return Err(WpError::InvalidTimestamp(
            "training timestamps must be monotonic".into(),
        ));
    }
    if let (Some(first), Some(last)) = (activity.time_ms.first(), activity.time_ms.last()) {
        if last
            .checked_sub(*first)
            .is_none_or(|span| span > MAX_ACTIVITY_DURATION_S as i64 * 1000)
        {
            return Err(WpError::DurationLimitExceeded(
                "training timeline exceeds 48 hours".into(),
            ));
        }
    }
    let increasing = |values: &[f64]| {
        values.iter().all(|v| v.is_finite() && *v > 0.0) && values.windows(2).all(|w| w[0] < w[1])
    };
    if !options.ftp_w.is_finite()
        || options.ftp_w < 0.0
        || !(6..=7).contains(&options.power_zones_pct.len())
        || !increasing(&options.power_zones_pct)
        || !options.sweet_spot_pct.0.is_finite()
        || !options.sweet_spot_pct.1.is_finite()
        || options.sweet_spot_pct.0 < 0.0
        || options.sweet_spot_pct.0 > options.sweet_spot_pct.1
        || options
            .hr_zones_bpm
            .as_ref()
            .is_some_and(|z| z.is_empty() || !increasing(z))
    {
        return Err(WpError::Parse("invalid training FTP or zone bounds".into()));
    }
    Ok(())
}

struct Timeline {
    seconds: Vec<usize>,
    power: Vec<f64>,
    moving: Vec<bool>,
    has_power: bool,
    has_speed: bool,
}

impl Timeline {
    fn new(activity: &ParsedActivity, gap_fill_s: u32) -> Self {
        let start = activity.time_ms[0];
        let seconds: Vec<usize> = activity
            .time_ms
            .iter()
            .map(|t| ((t - start) / 1000) as usize)
            .collect();
        let n = seconds.last().unwrap() + 1;
        let mut power = vec![0.0; n];
        let mut moving = vec![false; n];
        let mut has_power = false;
        let mut has_speed = false;
        for (i, &k) in seconds.iter().enumerate() {
            if let Some(p) = activity
                .pwr_w
                .as_ref()
                .and_then(|p| p.get(i))
                .filter(|&&p| p != MISSING_U16)
            {
                power[k] = *p as f64;
                has_power = true;
            } else {
                power[k] = 0.0;
            }
            let speed = activity
                .speed_mps
                .as_ref()
                .and_then(|s| s.get(i))
                .copied()
                .or_else(|| activity.motion_speed_mps.get(i).copied());
            if let Some(speed) = speed.filter(|s| s.is_finite() && *s >= 0.0) {
                moving[k] = speed >= 0.05;
                has_speed = true;
            }
        }
        for pair in seconds.windows(2) {
            let (a, b) = (pair[0], pair[1]);
            let gap = b - a;
            if gap > 1 && gap <= gap_fill_s as usize {
                for k in a + 1..b {
                    power[k] = power[a] + (power[b] - power[a]) * (k - a) as f64 / gap as f64;
                    moving[k] = moving[a] && moving[b];
                }
            }
        }
        if !has_speed {
            // Provisional for speedless recordings (not covered by the local
            // scorer). Cadence supplies motion when present; otherwise count
            // recording time, including coasting, excluding abnormal gaps.
            // https://forum.intervals.icu/t/better-moving-time-for-trail-runs-hikes-etc/7076
            // https://forum.intervals.icu/t/intervals-miss-calculating-load/7823/13
            if let Some(cadence) = activity
                .cadence_rpm
                .as_ref()
                .filter(|c| c.iter().any(|&v| v != MISSING_U8))
            {
                for (&k, &c) in seconds.iter().zip(cadence) {
                    moving[k] = c > 0 && c != MISSING_U8;
                }
                for pair in seconds.windows(2) {
                    let (a, b) = (pair[0], pair[1]);
                    if b > a + 1 && b - a <= gap_fill_s as usize {
                        let active = moving[a] && moving[b];
                        moving[a + 1..b].fill(active);
                    }
                }
            } else {
                let mut gaps: Vec<usize> = seconds
                    .windows(2)
                    .map(|w| w[1] - w[0])
                    .filter(|&g| g > 0)
                    .collect();
                gaps.sort_unstable();
                // Twice the median, retaining half-second medians. Duplicate
                // timestamps do not define the stream's sampling interval.
                let limit = if gaps.is_empty() {
                    0
                } else {
                    gaps[(gaps.len() - 1) / 2] + gaps[gaps.len() / 2]
                };
                for &k in &seconds {
                    moving[k] = true;
                }
                for pair in seconds.windows(2) {
                    let (a, b) = (pair[0], pair[1]);
                    if b > a + 1 && b - a <= limit {
                        moving[a + 1..b].fill(true);
                    }
                }
            }
        }
        Self {
            seconds,
            power,
            moving,
            has_power,
            has_speed,
        }
    }
}

fn np(power: &[f64], moving: &[bool]) -> Option<f64> {
    let mut acc = 0.0;
    let mut total = 0.0;
    let mut count = 0;
    for (k, &p) in power.iter().enumerate() {
        acc += p;
        if k >= 30 {
            acc -= power[k - 30];
        }
        if moving[k] {
            total += (acc / (k + 1).min(30) as f64).powi(4);
            count += 1;
        }
    }
    (count > 0).then(|| (total / count as f64).powf(0.25))
}

fn valid_sensor(values: &Option<Vec<u8>>) -> Vec<f64> {
    values
        .iter()
        .flatten()
        .filter(|&&v| v > 0 && v != MISSING_U8)
        .map(|&v| v as f64)
        .collect()
}

fn mean(values: &[f64]) -> Option<f64> {
    (!values.is_empty()).then(|| values.iter().sum::<f64>() / values.len() as f64)
}

fn resample(seconds: &[usize], values: &[f64], gap_fill_s: u32) -> Vec<f64> {
    let mut out = vec![0.0; seconds.last().unwrap() + 1];
    for (&k, &value) in seconds.iter().zip(values) {
        out[k] = value;
    }
    for pair in seconds.windows(2) {
        let (a, b) = (pair[0], pair[1]);
        if b > a + 1 && b - a <= gap_fill_s as usize {
            for k in a + 1..b {
                out[k] = out[a] + (out[b] - out[a]) * (k - a) as f64 / (b - a) as f64;
            }
        }
    }
    out
}

/// Read-side export for canonical efforts. Reuse the ride's timeline/repair
/// rules; never slice the activity before constructing trailing windows.
#[cfg(feature = "python")]
#[pyfunction]
pub(crate) fn training_timeline(
    py: Python<'_>,
    activity: &crate::PyParsedActivity,
) -> PyResult<Py<pyo3::types::PyDict>> {
    use pyo3::types::PyDict;
    let options = TrainingOptions { engine_version: 3, ..Default::default() };
    validate(&activity.inner, &options)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    if activity.inner.time_ms.is_empty() {
        return Err(pyo3::exceptions::PyValueError::new_err("empty effort timeline"));
    }
    let original = &activity.inner;
    let gps = gps_reading_stream(&activity.inner);
    let activity = gps.as_ref().unwrap_or(&activity.inner);
    let timeline = Timeline::new(activity, 30);
    let n = timeline.power.len();
    // Unknown sensors stay unknown. Linear interpolation is bounded by the
    // same 30-second recording gap; HR uses the existing hold convention.
    let sensor = |values: Vec<Option<f64>>, hold: bool| {
        let mut out = vec![None; n];
        for (&k, &v) in timeline.seconds.iter().zip(&values) {
            out[k] = v;
        }
        for pair in timeline.seconds.windows(2) {
            let (a, b) = (pair[0], pair[1]);
            if b > a + 1 && b - a <= 30 {
                for k in a + 1..b {
                    out[k] = if hold {
                        out[a]
                    } else {
                        out[a].zip(out[b]).map(|(x, y)| x + (y - x) * (k - a) as f64 / (b - a) as f64)
                    };
                }
            }
        }
        out
    };
    // Effort-only stop evidence: missing FIT fields are unknown, not the
    // parser's numeric zero placeholders. Never change shared Training motion.
    let own_speed: Vec<Option<f64>> = (0..original.time_ms.len()).map(|i| {
            if original.motion_sample_presence.get(i).is_some_and(|p| p & 1 == 0) {
                return None;
            }
            original.speed_mps.as_ref().and_then(|v| v.get(i)).copied()
                .or_else(|| original.motion_speed_mps.get(i).copied())
                .filter(|v| v.is_finite() && *v >= 0.0).map(f64::from)
        }).collect();
    // GPS speeds describe the preceding segment, not an instantaneous sensor
    // sample. Keep invalid segments unknown; shared GPS zero placeholders are
    // not stop evidence. Long-gap displacement is useful even without speed.
    let coordinate = |i: usize| -> Option<(f64, f64)> {
        let lat = *original.lat_e7.as_ref()?.get(i)?;
        let lon = *original.lon_e7.as_ref()?.get(i)?;
        if lat == MISSING_I32 || lon == MISSING_I32 { return None; }
        let (lat, lon) = (lat as f64 / 1e7, lon as f64 / 1e7);
        (lat.abs() <= 90.0 && lon.abs() <= 180.0).then_some((lat, lon))
    };
    let mut gps_speed = vec![None; original.time_ms.len()];
    let mut gps_distance = vec![None; original.time_ms.len()];
    let mut components = vec![None; original.time_ms.len()];
    let (mut total, mut component) = (0.0, 0usize);
    for i in 0..original.time_ms.len() {
        if i > 0 {
            let dt = (original.time_ms[i] - original.time_ms[i - 1]) as f64 / 1000.0;
            let meters = coordinate(i - 1).zip(coordinate(i)).and_then(|((a, b), (c, d))| {
                let meters = crate::haversine_m(a, b, c, d);
                (dt > 0.0 && meters / dt <= 100.0).then_some(meters)
            });
            if let Some(meters) = meters {
                total += meters;
                if dt <= 30.0 { gps_speed[i - 1] = Some(meters / dt); }
            } else {
                component += 1;
            }
        }
        if coordinate(i).is_some() {
            gps_distance[i] = Some(total);
            components[i] = Some(component);
        }
    }
    let raw_speed: Vec<Option<f64>> = own_speed.iter().zip(&gps_speed)
        .map(|(own, gps)| own.or(*gps)).collect();
    let mut speed = sensor(raw_speed.clone(), false);
    for (i, pair) in timeline.seconds.windows(2).enumerate() {
        if own_speed[i].is_none() {
            if let Some(value) = gps_speed[i] {
                for k in pair[0]..pair[1] { speed[k] = Some(value); }
            }
        }
    }
    let byte_sensor = |values: &Option<Vec<u8>>| {
        (0..activity.time_ms.len()).map(|i| {
            values.as_ref().map(|v| v[i]).filter(|&v| v != MISSING_U8).map(f64::from)
        }).collect::<Vec<_>>()
    };
    let own_distance: Vec<Option<f64>> = (0..original.time_ms.len()).map(|i| {
        if original.motion_sample_presence.get(i).is_some_and(|p| p & 2 == 0) {
            return None;
        }
        original.dist_m.as_ref().and_then(|v| v.get(i)).copied()
            .filter(|v| v.is_finite() && *v >= 0.0).map(f64::from)
    }).collect();
    let raw_distance = if own_distance.iter().any(Option::is_some) {
        components = own_distance.iter().map(|d| d.map(|_| 0)).collect();
        own_distance
    } else { gps_distance };
    let distance = sensor(raw_distance.clone(), false);
    let observed: Vec<usize> = timeline.seconds.iter().enumerate().filter_map(|(i, &s)| {
        activity.pwr_w.as_ref().filter(|p| p[i] != MISSING_U16).map(|_| s)
    }).collect();
    let dict = PyDict::new(py);
    dict.set_item("recording_sample_s", original.time_ms.iter()
        .map(|t| (t - original.time_ms[0]) as f64 / 1000.0).collect::<Vec<_>>())?;
    dict.set_item("recording_speed_mps", raw_speed)?;
    dict.set_item("recording_distance_m", &raw_distance)?;
    dict.set_item("distance_components", components)?;
    let mut covered = vec![false; n];
    for &s in &observed { covered[s] = true; }
    for pair in timeline.seconds.windows(2) {
        let (a, b) = (pair[0], pair[1]);
        if b - a <= 30 && covered[a] && covered[b] {
            for k in a..b { covered[k] = true; }
        }
    }
    dict.set_item("power_covered", covered)?;
    dict.set_item("duration_s", (activity.time_ms.last().unwrap() - activity.time_ms[0]) as f64 / 1000.0)?;
    dict.set_item("distance_sample_s", activity.time_ms.iter()
        .map(|t| (t - activity.time_ms[0]) as f64 / 1000.0).collect::<Vec<_>>())?;
    dict.set_item("distance_samples_m", raw_distance)?;
    dict.set_item("np_power_w", &timeline.power)?;
    dict.set_item("power_w", if timeline.has_power {
        repair_power(activity, &timeline.seconds, 30)
    } else { vec![0.0; n] })?;
    dict.set_item("moving", &timeline.moving)?;
    dict.set_item("power_observed_s", observed)?;
    dict.set_item("speed_mps", speed)?;
    dict.set_item("distance_m", distance)?;
    dict.set_item("cadence_rpm", sensor(byte_sensor(&activity.cadence_rpm), false))?;
    dict.set_item("hr_bpm", sensor(byte_sensor(&activity.hr_bpm), true))?;
    Ok(dict.into())
}

/// Bounded missing runs carry the previous power for their first five points,
/// except at recorded zero cadence. Suspicious-zero stability is still limited.
/// Model-curve spike repair cannot be inferred from
/// FTP; preserve spikes until that missing input and rule are known.
fn repair_power(activity: &ParsedActivity, seconds: &[usize], gap_fill_s: u32) -> Vec<f64> {
    let raw = activity.pwr_w.as_ref().unwrap();
    let mut out: Vec<f64> = raw
        .iter()
        .map(|&p| if p == MISSING_U16 { 0.0 } else { p as f64 })
        .collect();
    for missing in [true, false] {
        let bad = |k: usize| {
            if missing {
                raw[k] == MISSING_U16
            } else {
                raw[k] == 0 || raw[k] == MISSING_U16
            }
        };
        let mut i = 0;
        while i < raw.len() {
            if !bad(i) {
                i += 1;
                continue;
            }
            let a = i;
            while i < raw.len() && bad(i) {
                i += 1;
            }
            let b = i;
            if a == 0
                || b == raw.len()
                || (!missing && b - a > 9)
                || seconds[a - 1..=b]
                    .windows(2)
                    .any(|w| w[1] - w[0] > gap_fill_s as usize)
            {
                continue;
            }
            if missing {
                let previous = out[a - 1];
                for (k, p) in out.iter_mut().enumerate().take(b.min(a + 5)).skip(a) {
                    if activity
                        .cadence_rpm
                        .as_ref()
                        .is_none_or(|cadence| cadence[k] != 0)
                    {
                        *p = previous;
                    }
                }
            } else if a >= 5 {
                let last = out[a - 1];
                if last > 0.0
                    && out[a - 5..a]
                        .iter()
                        .all(|&p| p > 0.0 && (p - last).abs() <= last * 0.1)
                {
                    for (k, p) in out.iter_mut().enumerate().take(b).skip(a) {
                        // Missing points already received their bounded carry;
                        // they measure the run but must not extend that carry.
                        if raw[k] == 0
                            && activity
                                .cadence_rpm
                                .as_ref()
                                .is_none_or(|cadence| cadence[k] != 0)
                        {
                            *p = last;
                        }
                    }
                }
            }
        }
    }
    resample(seconds, &out, gap_fill_s)
}

fn power_zones(power: &[f64], moving: &[bool], options: &TrainingOptions) -> Vec<u32> {
    let tops: Vec<f64> = options.power_zones_pct[..6]
        .iter()
        .map(|pct| (options.ftp_w * pct / 100.0).floor())
        .collect();
    let low = (options.ftp_w * options.sweet_spot_pct.0 / 100.0).floor();
    let high = (options.ftp_w * options.sweet_spot_pct.1 / 100.0).floor();
    let mut counts = vec![0; 8];
    let mut sum = 0.0;
    for (k, &p) in power.iter().enumerate() {
        sum += p;
        if k >= 5 {
            sum -= power[k - 5];
        }
        if moving[k] {
            let avg = (sum / (k + 1).min(5) as f64).round();
            let zone = tops.iter().position(|&top| avg <= top).unwrap_or(6);
            counts[zone] += 1;
            if avg >= low && avg <= high {
                counts[7] += 1;
            }
        }
    }
    counts
}

/// HR has its own timing: hold the previous reading across gaps up to 30 s.
/// Carry the first five recorded missing readings, even at a movement stop.
/// This improves conformance without changing power's moving/NP timeline;
/// endpoint timing remains a conformance limitation.
fn hr_timeline(
    activity: &ParsedActivity,
    timeline: &Timeline,
    gap_fill_s: u32,
) -> (Vec<f64>, Vec<bool>) {
    let raw = activity.hr_bpm.as_ref().unwrap();
    let seconds = &timeline.seconds;
    let values: Vec<f64> = raw
        .iter()
        .map(|&v| if v == MISSING_U8 { 0.0 } else { v as f64 })
        .collect();
    let mut samples = resample(seconds, &values, 0);
    let mut active = timeline.moving.clone();
    for pair in seconds.windows(2) {
        let (a, b) = (pair[0], pair[1]);
        if b > a + 1 && b - a <= 30 {
            let previous = samples[a];
            samples[a + 1..b].fill(previous);
            if timeline.has_speed {
                let moving = active[a] && active[b];
                active[a + 1..b].fill(moving);
            }
            // Speedless rides keep the provisional cadence/recording mask,
            // including its exclusion of abnormal recording gaps.
        }
    }
    let missing = |i: usize| raw[i] == 0 || raw[i] == MISSING_U8;
    let mut i = 0;
    while i < raw.len() {
        if !missing(i) {
            i += 1;
            continue;
        }
        let a = i;
        while i < raw.len() && missing(i) {
            i += 1;
        }
        let b = i;
        if a == 0
            || b == raw.len()
            || seconds[a - 1..=b]
                .windows(2)
                .any(|w| w[1] - w[0] > gap_fill_s as usize)
        {
            continue;
        }
        for k in a..b.min(a + 5) {
            // A later record at the same second remains authoritative.
            if seconds[k] < seconds[k + 1] {
                samples[seconds[k]] = values[a - 1];
                active[seconds[k]] = true;
            }
        }
    }
    (samples, active)
}

struct HrZoneContext<'a> {
    has_sensor_speed: bool,
    sample_presence: &'a [u8],
    has_prior_reading: bool,
    preceding_records: usize,
}

fn hr_zones(
    activity: &ParsedActivity,
    timeline: &Timeline,
    tops: &[f64],
    options: &TrainingOptions,
    smooth: bool,
    context: &HrZoneContext<'_>,
) -> Vec<u32> {
    let (samples, mut active) = hr_timeline(activity, timeline, options.gap_fill_s);
    let mut missing_zone_one = vec![false; samples.len()];
    if options.engine_version >= 3 {
        let raw = activity.hr_bpm.as_ref().unwrap();
        let mut missing_run = context.preceding_records;
        let mut seen_hr = context.has_prior_reading;
        for (i, (&k, &h)) in timeline.seconds.iter().zip(raw).enumerate() {
            missing_run = if h == 0 || h == MISSING_U8 {
                missing_run + 1
            } else {
                seen_hr = true;
                0
            };
            // A later record at this second owns its sensor presence as well.
            if timeline.seconds.get(i + 1) == Some(&k) {
                continue;
            }
            // FIT retains absent speed as zero in the canonical stream. For
            // HR zones only, absent speed is not an observed stop. Completely
            // speedless streams retain their GPS or cadence/recording motion.
            if context.has_sensor_speed
                && context.sample_presence.len() == raw.len()
                && context.sample_presence[i] & 1 == 0
            {
                active[k] = true;
            }
            // Only the first five missing records before the ride's first HR
            // reading may count in Z1. After a reading, missing HR without an
            // existing held/carried value is omitted, including in later spans.
            // This never invents BPM for HRSS or best-HR calculations.
            missing_zone_one[k] = !seen_hr && (1..=5).contains(&missing_run);
        }
    }
    classify_hr(&samples, &active, tops, smooth, &missing_zone_one)
}

fn classify_hr(
    samples: &[f64],
    active: &[bool],
    tops: &[f64],
    smooth: bool,
    missing_zone_one: &[bool],
) -> Vec<u32> {
    let mut counts = vec![0; tops.len()];
    for (i, (&raw, &moving)) in samples.iter().zip(active).enumerate() {
        let window = &samples[i.saturating_sub(4)..=i];
        let h = if smooth {
            window.iter().sum::<f64>() / window.len() as f64
        } else {
            raw
        };
        if moving && (h > 0.0 || missing_zone_one[i]) {
            let zone = tops
                .iter()
                .position(|&top| h <= top)
                .unwrap_or(tops.len() - 1);
            counts[zone] += 1;
        }
    }
    counts
}

const CURVE_DURATIONS: &[u32] = &[
    1, 5, 15, 30, 60, 120, 180, 300, 420, 600, 900, 1200, 1800, 2700, 3600, 7200,
];

/// Prepare reading-only distance/motion for GPX and speedless TCX. The parsed
/// activity and canonical/economic streams remain untouched. A GPS segment
/// supplies its preceding interval; the terminal point has no elapsed time.
fn gps_reading_stream(activity: &ParsedActivity) -> Option<ParsedActivity> {
    let (Some(lat), Some(lon)) = (&activity.lat_e7, &activity.lon_e7) else {
        return None;
    };
    let needs_distance = activity
        .dist_m
        .as_ref()
        .is_none_or(|v| !v.iter().any(|x| x.is_finite() && *x >= 0.0))
        || (activity.motion_sample_presence.len() == activity.time_ms.len()
            && activity.motion_sample_presence.iter().all(|p| p & 2 == 0));
    let needs_speed = activity
        .speed_mps
        .as_ref()
        .is_none_or(|v| !v.iter().any(|x| x.is_finite() && *x >= 0.0))
        && !activity
            .motion_speed_mps
            .iter()
            .any(|x| x.is_finite() && *x >= 0.0);
    if !needs_distance && !needs_speed {
        return None;
    }
    let mut distance = vec![0.0; lat.len()];
    let mut speed = vec![0.0; lat.len()];
    let mut valid = false;
    for i in 1..lat.len() {
        distance[i] = distance[i - 1];
        let coords = [lat[i - 1], lon[i - 1], lat[i], lon[i]];
        let dt = (activity.time_ms[i] - activity.time_ms[i - 1]) as f64 / 1000.0;
        if coords.contains(&MISSING_I32) || dt <= 0.0 || dt > 30.0 {
            continue;
        }
        let [a, b, c, d] = coords.map(|v| v as f64 / 1e7);
        if a.abs() > 90.0 || c.abs() > 90.0 || b.abs() > 180.0 || d.abs() > 180.0 {
            continue;
        }
        let meters = crate::haversine_m(a, b, c, d);
        // Reject impossible jumps, never turn a GPS glitch into work or motion.
        if meters / dt > 100.0 {
            continue;
        }
        valid = true;
        distance[i] += meters as f32;
        speed[i - 1] = (meters / dt) as f32;
    }
    if !valid {
        return None;
    }
    let mut reading = activity.clone();
    if needs_distance {
        reading.dist_m = Some(distance);
    }
    if needs_speed {
        reading.speed_mps = Some(speed);
    }
    Some(reading)
}

fn best_window(values: &[f64], seconds: usize, require_positive: bool) -> Option<f64> {
    if values.len() < seconds {
        return None;
    }
    let mut sum = 0.0;
    let mut missing = 0;
    let mut best: Option<f64> = None;
    for (i, &v) in values.iter().enumerate() {
        sum += v;
        missing += usize::from(v <= 0.0);
        if i >= seconds {
            sum -= values[i - seconds];
            missing -= usize::from(values[i - seconds] <= 0.0);
        }
        if i + 1 >= seconds && (!require_positive || missing == 0) {
            best = Some(best.unwrap_or(0.0).max(sum / seconds as f64));
        }
    }
    best
}

pub fn compute_training_metrics(
    activity: &ParsedActivity,
    options: &TrainingOptions,
) -> WpResult<TrainingMetrics> {
    compute_with_hr_presence(
        activity,
        options,
        &activity.motion_sample_presence,
        false,
        0,
    )
}

fn compute_with_hr_presence(
    activity: &ParsedActivity,
    options: &TrainingOptions,
    hr_sample_presence: &[u8],
    hr_before_span: bool,
    records_before_span: usize,
) -> WpResult<TrainingMetrics> {
    validate(activity, options)?;
    let mut result = TrainingMetrics {
        engine_version: options.engine_version,
        ..Default::default()
    };
    if activity.time_ms.is_empty() {
        return Ok(result);
    }
    // Missing recorded speed may be admitted for HR zones, but derived GPS
    // stops must keep their motion decision. Check before preparing GPS reads.
    let has_sensor_speed = activity
        .speed_mps
        .iter()
        .flatten()
        .chain(&activity.motion_speed_mps)
        .any(|x| x.is_finite() && *x >= 0.0);
    let hr_context = HrZoneContext {
        has_sensor_speed,
        sample_presence: hr_sample_presence,
        has_prior_reading: hr_before_span,
        preceding_records: records_before_span,
    };
    let gps = (options.engine_version >= 2)
        .then(|| gps_reading_stream(activity))
        .flatten();
    let activity = gps.as_ref().unwrap_or(activity);
    let timeline = Timeline::new(activity, options.gap_fill_s);
    let elapsed = *timeline.seconds.last().unwrap() as u32;
    result.elapsed_s = Some(elapsed);
    let long_gaps: u32 = timeline
        .seconds
        .windows(2)
        .map(|w| (w[1] - w[0]) as u32)
        .filter(|&g| g > 30)
        .sum();
    result.recording_s = elapsed.checked_sub(1 + long_gaps);
    result.moving_s = Some(timeline.moving.iter().filter(|&&m| m).count() as u32);
    if timeline.has_power {
        let repaired = repair_power(activity, &timeline.seconds, options.gap_fill_s);
        result.work_j = Some(repaired.iter().sum());
        result.calories_estimate = true;
        result.calories_basis = Some(
            if options.engine_version == 2 {
                "work_kj_div_4.184_div_0.22"
            } else {
                "work_kj_div_4.184_div_0.24"
            }
            .into(),
        );
        if options.engine_version >= 2 {
            result.power_curve_s = CURVE_DURATIONS.to_vec();
            result.power_curve_w = Some(
                CURVE_DURATIONS
                    .iter()
                    .map(|&d| best_window(&repaired, d as usize, false))
                    .collect(),
            );
        }
        result.avg_power_w = result
            .recording_s
            .filter(|&s| s > 0)
            .map(|s| result.work_j.unwrap() / s as f64);
        // A named work-based estimate, not a reconstruction of provider
        // calories. v3 follows the 24% reference-compatible fallback, while
        // historical v2 retains 22%. A positive device total wins below.
        result.calories_kcal = result.work_j.map(|j| {
            j / 1000.0
                / 4.184
                / if options.engine_version == 2 {
                    0.22
                } else {
                    0.24
                }
        });
        result.np_raw_w = np(&timeline.power, &timeline.moving);
        result.np_w = result.np_raw_w.map(|v| v.round() as u32);
        if options.ftp_w > 0.0 {
            result.load_basis = Some("power".into());
            result.power_zone_tops_w = Some(
                options
                    .power_zones_pct
                    .iter()
                    .take(6)
                    .map(|p| (options.ftp_w * p / 100.0).floor() as u32)
                    .collect(),
            );
            result.power_zone_s = Some(power_zones(&repaired, &timeline.moving, options));
            result.intensity_pct = result.np_w.map(|p| p as f64 * 100.0 / options.ftp_w);
            result.load = result.np_w.zip(result.moving_s).map(|(p, s)| {
                ((p as f64 / options.ftp_w).powi(2) * s as f64 / 3600.0 * 100.0).round() as u32
            });
        }
    }
    let hr = valid_sensor(&activity.hr_bpm);
    result.avg_hr_bpm = mean(&hr);
    result.max_hr_bpm = hr.iter().copied().reduce(f64::max).map(|v| v as u8);
    if let Some(session) = &activity.device_summary {
        let valid = |v: &u8| *v > 0 && *v != MISSING_U8;
        result.avg_hr_bpm = session
            .avg_hr_bpm
            .filter(valid)
            .map(|v| v as f64)
            .or(result.avg_hr_bpm);
        result.max_hr_bpm = session.max_hr_bpm.filter(valid).or(result.max_hr_bpm);
    }
    if !hr.is_empty() {
        if let Some(tops) = &options.hr_zones_bpm {
            result.hr_zone_s = Some(hr_zones(
                activity,
                &timeline,
                tops,
                options,
                false,
                &hr_context,
            ));
            if options.engine_version >= 3 {
                result.hr_zone_tops_bpm = Some(tops.iter().map(|&v| v as u32).collect());
            }
        }
    }
    if options.engine_version >= 2 && !hr.is_empty() {
        let (heart, active) = hr_timeline(activity, &timeline, options.gap_fill_s);
        result.best_20m_hr_bpm = best_window(&heart, 1200, true);
        if let Some(lthr) = options.lthr_bpm {
            let mut tops: Vec<f64> = [81.0, 90.0, 94.0, 100.0, 103.0, 106.0]
                .iter()
                .map(|p| (lthr * p / 100.0).floor() - 1.0)
                .collect();
            if options.engine_version < 3 || options.hr_zones_bpm.is_none() {
                result.hr_zone_tops_bpm = Some(tops.iter().map(|&v| v as u32).collect());
                tops.push(1000.0);
                result.hr_zone_s = Some(hr_zones(
                    activity,
                    &timeline,
                    &tops,
                    options,
                    options.engine_version == 2,
                    &hr_context,
                ));
            }
            if result.load.is_none() {
                if let Some(max_hr) = options.max_hr_bpm.filter(|&m| m >= lthr) {
                    let reserve = max_hr - options.resting_hr_bpm;
                    let fraction = (lthr - options.resting_hr_bpm) / reserve;
                    let denominator = fraction * (options.hrss_k * fraction).exp() * 3600.0;
                    let trimp: f64 = heart
                        .iter()
                        .zip(&active)
                        .filter(|(h, a)| **h > 0.0 && **a)
                        .map(|(&h, _)| {
                            let f = ((h - options.resting_hr_bpm) / reserve).clamp(0.0, 1.0);
                            f * (options.hrss_k * f).exp()
                        })
                        .sum();
                    result.load = Some((100.0 * trimp / denominator).round() as u32);
                    result.load_basis = Some("hrss".into());
                }
            }
        }
    }
    let cadence = valid_sensor(&activity.cadence_rpm);
    result.avg_cadence_rpm = mean(&cadence);
    result.max_cadence_rpm = cadence.iter().copied().reduce(f64::max);
    let speed: Vec<f64> = activity
        .speed_mps
        .iter()
        .flatten()
        .copied()
        .filter(|v| v.is_finite() && *v >= 0.0)
        .map(|v| v as f64)
        .collect();
    result.avg_speed_mps = mean(&speed);
    result.max_speed_mps = speed.into_iter().reduce(f64::max);
    result.max_power_w = activity
        .pwr_w
        .iter()
        .flatten()
        .copied()
        .filter(|&v| v != MISSING_U16)
        .map(|v| v as f64)
        .reduce(f64::max);
    result.variability_index = result
        .np_w
        .zip(result.avg_power_w)
        .filter(|&(_, avg)| avg.round() > 0.0)
        .map(|(p, avg)| p as f64 / avg.round());
    result.efficiency_factor = result
        .np_w
        .zip(result.avg_hr_bpm)
        .filter(|&(_, avg)| avg.round() > 0.0)
        .map(|(p, avg)| p as f64 / avg.round());
    result.distance_m = activity
        .dist_m
        .iter()
        .flatten()
        .copied()
        .filter(|v| v.is_finite() && *v >= 0.0)
        .reduce(f32::max)
        .map(|v| v as f64);
    if options.engine_version >= 2 && result.distance_m.is_none() {
        let speed = activity
            .speed_mps
            .as_ref()
            .unwrap_or(&activity.motion_speed_mps);
        if speed.iter().any(|v| v.is_finite() && *v >= 0.0) {
            let values: Vec<f64> = speed
                .iter()
                .map(|v| {
                    if v.is_finite() && *v >= 0.0 {
                        *v as f64
                    } else {
                        0.0
                    }
                })
                .collect();
            result.distance_m = Some(
                resample(&timeline.seconds, &values, options.gap_fill_s)
                    .iter()
                    .sum(),
            );
        }
    }
    let elev: Vec<f64> = activity
        .elevation_m
        .iter()
        .flatten()
        .copied()
        .filter(|v| v.is_finite())
        .map(|v| v as f64)
        .collect();
    if elev.len() >= 2 {
        let elev = if options.engine_version >= 2 {
            crate::climb::utils::smooth_elevations(&elev, 21)
        } else {
            elev
        };
        result.elevation_gain_m = Some(elev.windows(2).map(|w| (w[1] - w[0]).max(0.0)).sum());
    }
    if let Some(session) = &activity.device_summary {
        let finite_total = |v: f64| v.is_finite() && v >= 0.0;
        result.distance_m = session
            .total_distance_m
            .filter(|&v| finite_total(v))
            .or(result.distance_m);
        result.elevation_gain_m = session
            .total_ascent_m
            .filter(|&v| finite_total(v))
            .or(result.elevation_gain_m);
        let device_calories = session.total_calories_kcal.filter(|&v| {
            // v3 treats device zero as unknown; historical replay is unchanged.
            finite_total(v) && (options.engine_version < 3 || v > 0.0)
        });
        if device_calories.is_some() {
            // The device estimates expenditure too. Preserve the old flags
            // on historical replay while retaining the device basis in v3.
            result.calories_estimate = options.engine_version >= 3;
            result.calories_basis = Some("device".into());
        }
        result.calories_kcal = device_calories.or(result.calories_kcal);
    }
    if options.engine_version >= 2 {
        result.avg_speed_mps = result
            .distance_m
            .zip(result.moving_s)
            .filter(|&(_, moving)| moving > 0)
            .map(|(distance, moving)| distance / moving as f64);
    }
    // Whole-ride decoupling stays absent: the tested minute-bin/HR-lag
    // hypotheses did not establish ICU's method. Do not substitute interval
    // decoupling or publish a guessed correlation lag as a confirmed metric.
    Ok(result)
}

#[cfg(feature = "python")]
/// Compute versioned training reads without changing canonical/effort metrics.
/// The default remains v1 for historical callers; production explicitly uses
/// v3. Decoupling remains absent until the whole-ride method is established.
/// Speedless movement and exact power repair remain conformance limitations.
/// FTP zero omits FTP-dependent values; calories retain their named basis.
#[pyfunction(name = "compute_training_metrics", signature = (activity, ftp_w, gap_fill_s=30, power_zones_pct=None, sweet_spot_pct=None, hr_zones_bpm=None, engine_version=1, lthr_bpm=None, resting_hr_bpm=60.0, max_hr_bpm=None, hrss_k=1.92, start_s=None, end_s=None))]
pub(crate) fn py_compute_training_metrics(
    py: Python<'_>,
    activity: &crate::PyParsedActivity,
    ftp_w: f64,
    gap_fill_s: u32,
    power_zones_pct: Option<Vec<f64>>,
    sweet_spot_pct: Option<(f64, f64)>,
    hr_zones_bpm: Option<Vec<f64>>,
    engine_version: u32,
    lthr_bpm: Option<f64>,
    resting_hr_bpm: f64,
    max_hr_bpm: Option<f64>,
    hrss_k: f64,
    start_s: Option<u32>,
    end_s: Option<u32>,
) -> PyResult<TrainingMetrics> {
    let defaults = TrainingOptions::default();
    let options = TrainingOptions {
        engine_version,
        lthr_bpm,
        resting_hr_bpm,
        max_hr_bpm,
        hrss_k,
        ftp_w,
        gap_fill_s,
        power_zones_pct: power_zones_pct.unwrap_or(defaults.power_zones_pct),
        sweet_spot_pct: sweet_spot_pct.unwrap_or(defaults.sweet_spot_pct),
        hr_zones_bpm,
    };
    let mut selected;
    let mut hr_sample_presence = None;
    let mut hr_before_span = false;
    let mut records_before_span = 0;
    // Validate before any slicing, including lat/lon needed by GPX spans.
    validate(&activity.inner, &options)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?;
    let input = if start_s.is_some() || end_s.is_some() {
        let (Some(start), Some(end)) = (start_s, end_s) else {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "both span bounds required",
            ));
        };
        if end <= start {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "invalid training span",
            ));
        }
        selected = activity.inner.clone();
        let origin = *selected.time_ms.first().unwrap_or(&0);
        let lo = selected
            .time_ms
            .partition_point(|&t| t < origin + start as i64 * 1000);
        let hi = selected
            .time_ms
            .partition_point(|&t| t <= origin + end as i64 * 1000);
        records_before_span = lo;
        hr_before_span = selected
            .hr_bpm
            .as_ref()
            .is_some_and(|hr| hr[..lo].iter().any(|&h| h > 0 && h != MISSING_U8));
        macro_rules! slice {
            ($field:ident) => {
                selected.$field = selected.$field.as_ref().map(|v| v[lo..hi].to_vec());
            };
        }
        slice!(pwr_w);
        slice!(hr_bpm);
        slice!(cadence_rpm);
        slice!(speed_mps);
        slice!(dist_m);
        slice!(elevation_m);
        slice!(lat_e7);
        slice!(lon_e7);
        if selected.motion_speed_mps.len() == selected.time_ms.len() {
            selected.motion_speed_mps = selected.motion_speed_mps[lo..hi].to_vec();
        }
        if options.engine_version >= 3
            && selected.motion_sample_presence.len() == selected.time_ms.len()
        {
            // Slice only HR's view of presence: changing the shared mask here
            // would also change legacy GPS/distance fallback for spans.
            hr_sample_presence = Some(selected.motion_sample_presence[lo..hi].to_vec());
        }
        selected.time_ms = selected.time_ms[lo..hi].to_vec();
        if let Some(distance) = &mut selected.dist_m {
            let first = distance
                .iter()
                .find(|v| v.is_finite())
                .copied()
                .unwrap_or(0.0);
            for v in distance {
                *v -= first;
            }
        }
        selected.device_summary = None;
        &selected
    } else {
        &activity.inner
    };
    py.allow_threads(|| {
        compute_with_hr_presence(
            input,
            &options,
            hr_sample_presence
                .as_deref()
                .unwrap_or(&input.motion_sample_presence),
            hr_before_span,
            records_before_span,
        )
    })
    .map_err(|e| match e {
        WpError::DurationLimitExceeded(message) => crate::DurationLimitExceeded::new_err(message),
        _ => pyo3::exceptions::PyValueError::new_err(e.to_string()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn speedless_recording_and_cadence_fallbacks_are_provisional() {
        let mut activity = ParsedActivity {
            time_ms: vec![0, 2000, 4000, 14000, 16000],
            pwr_w: Some(vec![0; 5]),
            hr_bpm: Some(vec![130; 5]),
            speed_mps: Some(vec![f32::NAN; 5]),
            ..Default::default()
        };
        let options = TrainingOptions {
            ftp_w: 250.0,
            hr_zones_bpm: Some(vec![130.0, 180.0]),
            ..Default::default()
        };
        let recording = compute_training_metrics(&activity, &options).unwrap();
        assert_eq!(recording.moving_s, Some(8));
        assert_eq!(recording.np_w, Some(0));
        assert_eq!(recording.load, Some(0));
        assert_eq!(recording.hr_zone_s, Some(vec![8, 0]));
        activity.cadence_rpm = Some(vec![90, 0, 90, 0, 90]);
        let cadence = compute_training_metrics(&activity, &options).unwrap();
        assert_eq!(cadence.moving_s, Some(3));
        assert_eq!(cadence.power_zone_s, Some(vec![3, 0, 0, 0, 0, 0, 0, 0]));
        activity.speed_mps = Some(vec![0.0; 5]);
        assert_eq!(
            compute_training_metrics(&activity, &options)
                .unwrap()
                .moving_s,
            Some(0)
        );
    }

    #[test]
    fn power_missing_carry_stops_after_five_points() {
        let activity = ParsedActivity {
            time_ms: (0..40).map(|s| s * 1000).collect(),
            pwr_w: Some([vec![200; 10], vec![MISSING_U16; 12], vec![300; 18]].concat()),
            speed_mps: Some(vec![5.0; 40]),
            ..Default::default()
        };
        let result = compute_training_metrics(&activity, &TrainingOptions::default()).unwrap();
        assert_eq!(result.work_j, Some(15.0 * 200.0 + 18.0 * 300.0));
        assert_eq!(
            result.calories_kcal,
            result.work_j.map(|j| j / 1000.0 / 4.184 / 0.24)
        );
    }

    #[test]
    fn hr_zone_timing_is_independent_of_power_gap_fill() {
        let activity = ParsedActivity {
            time_ms: vec![0, 10000, 20000, 51000],
            pwr_w: Some(vec![200; 4]),
            speed_mps: Some(vec![5.0; 4]),
            hr_bpm: Some(vec![120, 150, 120, 150]),
            ..Default::default()
        };
        let options = TrainingOptions {
            gap_fill_s: 8,
            hr_zones_bpm: Some(vec![130.0, 180.0]),
            ..Default::default()
        };
        let result = compute_training_metrics(&activity, &options).unwrap();
        assert_eq!(result.hr_zone_s, Some(vec![11, 11]));
        assert_eq!(result.moving_s, Some(4));
    }

    #[test]
    fn dropout_zero_cadence_and_spike_reference_cases() {
        // Synthetic oracle: 42 ticks at 200 W, with one 5000 W spike.
        // Missing ticks carry the last power; zero cadence protects that point.
        let mut activity = ParsedActivity {
            time_ms: (0..42).map(|s| s * 1000).collect(),
            pwr_w: Some(vec![200; 42]),
            speed_mps: Some(vec![5.0; 42]),
            cadence_rpm: Some(vec![90; 42]),
            ..Default::default()
        };
        let power = activity.pwr_w.as_mut().unwrap();
        power[10] = MISSING_U16;
        power[11] = MISSING_U16;
        power[20] = 5000;
        let options = TrainingOptions {
            ftp_w: 250.0,
            ..Default::default()
        };
        let missing = compute_training_metrics(&activity, &options).unwrap();
        assert_eq!(missing.work_j, Some(13200.0));
        activity.cadence_rpm.as_mut().unwrap()[11] = 0;
        let stopped_missing = compute_training_metrics(&activity, &options).unwrap();
        assert_eq!(stopped_missing.work_j, Some(13000.0));
        activity.pwr_w.as_mut().unwrap()[10..12].fill(0);
        let zero = compute_training_metrics(&activity, &options).unwrap();
        assert_eq!(zero.work_j, Some(13000.0));
        assert_eq!(zero.np_w, missing.np_w);
        assert_eq!(
            zero.power_zone_s.as_ref().unwrap()[..7].iter().sum::<u32>(),
            42
        );
    }

    #[test]
    fn empty_and_all_missing_streams_do_not_claim_zero_measurements() {
        let result =
            compute_training_metrics(&ParsedActivity::default(), &TrainingOptions::default())
                .unwrap();
        assert_eq!(result.engine_version, 1);
        assert_eq!(result.elapsed_s, None);
        assert_eq!(result.work_j, None);
        let activity = ParsedActivity {
            time_ms: vec![0, 1000],
            pwr_w: Some(vec![MISSING_U16; 2]),
            hr_bpm: Some(vec![MISSING_U8; 2]),
            speed_mps: Some(vec![f32::NAN; 2]),
            ..Default::default()
        };
        let result = compute_training_metrics(&activity, &TrainingOptions::default()).unwrap();
        assert_eq!(result.moving_s, Some(2));
        assert_eq!(result.work_j, None);
        assert_eq!(result.avg_hr_bpm, None);
        assert_eq!(result.hr_zone_s, None);
    }

    #[test]
    fn device_totals_and_rounded_ratio_inputs() {
        let activity = ParsedActivity {
            time_ms: (0..60).map(|s| s * 1000).collect(),
            pwr_w: Some(vec![200; 60]),
            speed_mps: Some(vec![5.0; 60]),
            hr_bpm: Some([vec![100; 30], vec![101; 30]].concat()),
            dist_m: Some(vec![5.0; 60]),
            elevation_m: Some(vec![10.0; 60]),
            device_summary: Some(crate::DeviceSummary {
                total_distance_m: Some(305.0),
                total_ascent_m: Some(12.0),
                total_calories_kcal: Some(123.0),
                ..Default::default()
            }),
            ..Default::default()
        };
        let result = compute_training_metrics(&activity, &TrainingOptions::default()).unwrap();
        assert_eq!(result.distance_m, Some(305.0));
        assert_eq!(result.elevation_gain_m, Some(12.0));
        assert_eq!(result.calories_kcal, Some(123.0));
        assert_eq!(result.variability_index, Some(200.0 / 207.0));
        assert_eq!(result.efficiency_factor, Some(200.0 / 101.0));
    }

    #[test]
    fn partial_first_window_and_stopped_seconds() {
        let activity = ParsedActivity {
            time_ms: vec![0, 1000, 2000],
            pwr_w: Some(vec![200, MISSING_U16, 400]),
            speed_mps: Some(vec![5.0, 0.0, 5.0]),
            ..Default::default()
        };
        let metrics = compute_training_metrics(&activity, &TrainingOptions::default()).unwrap();
        assert_eq!(metrics.np_w, Some(200));
        assert_eq!(metrics.moving_s, Some(2));
        assert_eq!(metrics.recording_s, Some(1));
        assert_eq!(metrics.load, None);
    }

    #[test]
    fn gaps_and_both_ends_moving() {
        for gap in 1..=40 {
            for fill in [8, 30] {
                let activity = ParsedActivity {
                    time_ms: vec![0, gap * 1000, (gap + 2) * 1000],
                    pwr_w: Some(vec![200, 400, MISSING_U16]),
                    speed_mps: Some(vec![5.0, 5.0, 0.0]),
                    ..Default::default()
                };
                let timeline = Timeline::new(&activity, fill);
                assert_eq!(
                    timeline.moving.iter().filter(|&&m| m).count(),
                    if gap <= fill as i64 {
                        gap as usize + 1
                    } else {
                        2
                    }
                );
                assert!(!timeline.moving[gap as usize + 1]);
                if gap > 1 {
                    assert_eq!(
                        timeline.power[1],
                        if gap <= fill as i64 {
                            200.0 + 200.0 / gap as f64
                        } else {
                            0.0
                        }
                    );
                }
            }
        }
    }

    #[test]
    fn malformed_arrays_and_spans_are_rejected() {
        let mut activity = ParsedActivity {
            time_ms: vec![0, 1000],
            pwr_w: Some(vec![100]),
            ..Default::default()
        };
        assert!(compute_training_metrics(&activity, &TrainingOptions::default()).is_err());
        activity.pwr_w = None;
        activity.time_ms = vec![1000, 0];
        assert!(compute_training_metrics(&activity, &TrainingOptions::default()).is_err());
        activity.time_ms = vec![i64::MIN, i64::MAX];
        assert!(compute_training_metrics(&activity, &TrainingOptions::default()).is_err());
    }
}
