//! workout-parse: High-performance workout file parser with PyO3 bindings.
//!
//! Parses FIT, GPX, and TCX files. Computes NP/TSS/IF. Projects GPS to H3 tiles.
//!
//! ## Modules
//!
//! - `tiles` - H3 hexagonal tile projection
//! - `metrics` - NP/TSS/IF calculation
//! - `geo_features` - Geographic feature attribution (OSM preprocessing + lookup)
//! - `polyline` - Polyline encoding/decoding for GPS tracks

#[cfg(feature = "osm")]
pub mod canon;
pub mod canonicalize;
pub mod climb;
pub mod constants;
pub mod decompress;
pub mod error;
pub mod geo_features;
pub mod metrics;
pub mod polyline;
#[cfg(feature = "swift")]
pub mod swift_api;
pub mod tiles;
pub mod training;
pub mod training_context;

// UniFFI scaffolding must sit at the crate root; the Swift-facing surface
// itself lives in `swift_api`.
#[cfg(feature = "swift")]
uniffi::setup_scaffolding!("workout_parse");

// Used by the PyO3 bindings and by in-crate tests; allow it to sit unused in
// binding-free configurations (e.g. `--no-default-features` release builds).
#[cfg_attr(not(feature = "python"), allow(unused_imports))]
use canonicalize::{canonicalize, hash_canonical_ride_hex};
use canonicalize::{
    CURRENT_PARSER_VERSION, PARSER_VERSION_V1, PARSER_VERSION_V2, PARSER_VERSION_V3,
    PARSER_VERSION_V4, PARSER_VERSION_V5,
};
use constants::*;
use decompress::decompress_safe;
use error::{WpError, WpResult};
#[cfg(feature = "python")]
use h3o::Resolution;
use metrics::{
    calculate_if, calculate_kcals, calculate_tss, compute_power_metrics,
    compute_threshold_power_anchors, continuous_moving_time_s, sample_coverage_bps,
    ComputedMetrics,
};
#[cfg(feature = "python")]
use metrics::METRICS_VERSION;
#[cfg(feature = "python")]
use polyline::{py_decode_gps_track, py_decode_polyline, py_encode_gps_track, py_encode_polyline};
#[cfg(feature = "python")]
use tiles::{cells_to_strings, project_to_cells, project_to_h3, unique_cells, H3Cell};

#[cfg(feature = "python")]
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::PyBytes;

/// Parsed activity data.
#[derive(Debug, Clone)]
pub struct ParsedActivity {
    // Timestamps
    pub time_ms: Vec<i64>,

    // GPS (scaled by 1e7 for precision)
    pub lat_e7: Option<Vec<i32>>,
    pub lon_e7: Option<Vec<i32>>,
    pub elevation_m: Option<Vec<f32>>,

    // Power/HR/Cadence
    pub pwr_w: Option<Vec<u16>>,
    pub hr_bpm: Option<Vec<u8>>,
    pub cadence_rpm: Option<Vec<u8>>,

    // Speed/Distance
    pub speed_mps: Option<Vec<f32>>,
    pub dist_m: Option<Vec<f32>>,

    /// Per-record motion-channel presence, outside canonicalization: bit 0 is
    /// speed, bit 1 distance. Legacy arrays encode absent values as zero; this
    /// evidence preserves the difference without changing historical hashes.
    pub motion_sample_presence: Vec<u8>,
    /// TCX Speed extension evidence; not added to the legacy hash-bound speed
    /// channel or metrics. NaN means absent at this record.
    pub motion_speed_mps: Vec<f32>,

    // Metadata
    pub sport: String,
    pub device_name: Option<String>,
    pub started_at_ms: i64,
    pub total_elapsed_s: u32,

    // Evidence held outside canonicalization (never hashed): the device's
    // own testimony about pauses, identity, totals, and ambient temperature.
    /// Explicit timer stop→start spans (ms since epoch) from FIT Event
    /// messages. Empty when the file carries no timer events.
    pub timer_pauses: Vec<(i64, i64)>,
    /// Ambient temperature per record (°C); NaN where absent.
    pub temperature_c: Option<Vec<f32>>,
    /// Every DeviceInfo message: head unit and connected sensors.
    pub devices: Vec<DeviceProvenance>,
    /// The device's Session totals, kept outside canonicalization and legacy
    /// effort arithmetic. Training v1 prefers the supplied summary fields.
    pub device_summary: Option<DeviceSummary>,
    /// Device clock and indoor flags, never part of canonical or pay inputs.
    pub training_context: training_context::TrainingContext,
    /// FIT Lap messages, in file order.
    pub laps: Vec<LapSummary>,
    /// Per-record GPS accuracy (meters, EPE); NaN where absent.
    pub gps_accuracy_m: Option<Vec<f32>>,
    /// Per-record left/right balance, raw FIT byte (bit7 = right flag).
    pub lr_balance_raw: Option<Vec<u8>>,
}

/// One device lap: the rider's own segmentation of the ride.
#[derive(Debug, Clone, Default)]
pub struct LapSummary {
    pub started_at_ms: Option<i64>,
    pub total_elapsed_s: Option<f64>,
    pub total_timer_s: Option<f64>,
    pub total_distance_m: Option<f64>,
    pub total_ascent_m: Option<f64>,
    pub avg_power_w: Option<u16>,
    pub max_power_w: Option<u16>,
    pub avg_hr_bpm: Option<u8>,
    pub avg_cadence_rpm: Option<u8>,
}

/// One device the file testifies about (head unit or paired sensor).
#[derive(Debug, Clone, Default)]
pub struct DeviceProvenance {
    pub manufacturer: Option<String>,
    pub product: Option<String>,
    pub serial_number: Option<String>,
    pub device_type: Option<String>,
    pub software_version: Option<String>,
}

/// The device's own summary claims from the FIT Session message.
#[derive(Debug, Clone, Default)]
pub struct DeviceSummary {
    /// FIT Session calories, retained as device evidence outside canonicalization.
    pub total_calories_kcal: Option<f64>,
    pub avg_hr_bpm: Option<u8>,
    pub max_hr_bpm: Option<u8>,
    pub total_timer_time_s: Option<f64>,
    pub total_elapsed_time_s: Option<f64>,
    pub total_distance_m: Option<f64>,
    pub total_ascent_m: Option<f64>,
    pub avg_power_w: Option<u16>,
    pub max_power_w: Option<u16>,
}

impl ParsedActivity {
    /// Moving time derived from explicit timer events: elapsed span minus
    /// recorded pause spans, clamped to evidence. None when the file
    /// carries no timer events (callers keep the gap heuristic).
    pub fn event_moving_time_s(&self) -> Option<u32> {
        if self.timer_pauses.is_empty() || self.time_ms.is_empty() {
            return None;
        }
        let start = *self.time_ms.first()?;
        let end = *self.time_ms.last()?;
        if end <= start {
            return None;
        }
        let mut paused_ms: i64 = 0;
        for &(stop, resume) in &self.timer_pauses {
            let clamped_stop = stop.max(start);
            let clamped_resume = resume.min(end);
            if clamped_resume > clamped_stop {
                paused_ms += clamped_resume - clamped_stop;
            }
        }
        let moving_ms = (end - start - paused_ms).max(0);
        Some((moving_ms / 1000) as u32)
    }
}

impl Default for ParsedActivity {
    fn default() -> Self {
        Self {
            time_ms: vec![],
            lat_e7: None,
            lon_e7: None,
            elevation_m: None,
            pwr_w: None,
            hr_bpm: None,
            cadence_rpm: None,
            speed_mps: None,
            dist_m: None,
            motion_sample_presence: Vec::new(),
            motion_speed_mps: Vec::new(),
            sport: "cycling".to_string(),
            device_name: None,
            started_at_ms: 0,
            total_elapsed_s: 0,
            timer_pauses: vec![],
            temperature_c: None,
            devices: vec![],
            device_summary: None,
            training_context: training_context::TrainingContext::default(),
            laps: vec![],
            gps_accuracy_m: None,
            lr_balance_raw: None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum WorkoutFileType {
    Fit,
    Gpx,
    Tcx,
}

fn xml_bytes(data: &[u8]) -> &[u8] {
    data.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(data)
}

fn detect_xml_file_type(data: &[u8]) -> WpResult<WorkoutFileType> {
    use quick_xml::events::Event;
    use quick_xml::Reader;

    let mut reader = Reader::from_reader(xml_bytes(data));
    reader.trim_text(true);
    let mut buf = Vec::new();

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(ref element)) | Ok(Event::Empty(ref element)) => {
                let local_name = element.local_name();
                return match local_name.as_ref() {
                    b"gpx" => Ok(WorkoutFileType::Gpx),
                    b"TrainingCenterDatabase" => Ok(WorkoutFileType::Tcx),
                    name => Err(WpError::UnsupportedFileType(format!(
                        "Unsupported XML root element: {}",
                        String::from_utf8_lossy(name)
                    ))),
                };
            }
            Ok(Event::Eof) => {
                return Err(WpError::UnsupportedFileType(
                    "XML input has no root element".into(),
                ));
            }
            Err(error) => {
                return Err(WpError::UnsupportedFileType(format!(
                    "Invalid XML input: {error}"
                )));
            }
            _ => {}
        }
        buf.clear();
    }
}

fn detect_file_type(data: &[u8]) -> WpResult<WorkoutFileType> {
    if data.len() >= 12 && &data[8..12] == b".FIT" {
        return Ok(WorkoutFileType::Fit);
    }

    let candidate = xml_bytes(data);
    let candidate = candidate
        .iter()
        .position(|byte| !byte.is_ascii_whitespace())
        .map(|index| &candidate[index..])
        .unwrap_or(candidate);
    if candidate.starts_with(b"<") {
        return detect_xml_file_type(candidate);
    }

    Err(WpError::UnsupportedFileType(
        "Could not detect file type from content".into(),
    ))
}

fn detect_file_type_v1(data: &[u8]) -> WpResult<WorkoutFileType> {
    if data.len() >= 12 && &data[8..12] == b".FIT" {
        Ok(WorkoutFileType::Fit)
    } else if data.starts_with(b"<?xml") || data.starts_with(b"<gpx") {
        // V1 intentionally routed XML declarations to GPX before checking
        // TrainingCenterDatabase. Replay must preserve that historical path.
        Ok(WorkoutFileType::Gpx)
    } else if data.starts_with(b"<TrainingCenterDatabase") {
        Ok(WorkoutFileType::Tcx)
    } else if data.len() >= 4 && data[0] == b'.' {
        // Historical fallback retained for V1 source compatibility.
        Ok(WorkoutFileType::Fit)
    } else {
        Err(WpError::UnsupportedFileType(
            "Could not detect file type from content".into(),
        ))
    }
}

pub(crate) fn validate_activity_timestamps(time_ms: &[i64]) -> WpResult<(i64, u32)> {
    let first = *time_ms
        .first()
        .ok_or_else(|| WpError::InvalidTimestamp("activity has no timestamps".into()))?;

    for (index, pair) in time_ms.windows(2).enumerate() {
        if pair[1] < pair[0] {
            return Err(WpError::InvalidTimestamp(format!(
                "timestamp at index {} is out of order ({} < {})",
                index + 1,
                pair[1],
                pair[0]
            )));
        }
    }

    let last = *time_ms.last().unwrap_or(&first);
    let duration_ms = last.checked_sub(first).ok_or_else(|| {
        WpError::InvalidTimestamp("activity timestamp span overflowed i64".into())
    })?;
    let maximum_ms = (MAX_ACTIVITY_DURATION_S as i64) * 1_000;
    if duration_ms > maximum_ms {
        return Err(WpError::DurationLimitExceeded(format!(
            "Activity duration {}s exceeds maximum {}s",
            duration_ms / 1_000,
            MAX_ACTIVITY_DURATION_S
        )));
    }

    let duration_s = u32::try_from(duration_ms / 1_000).map_err(|_| {
        WpError::DurationLimitExceeded("Activity duration does not fit in u32 seconds".into())
    })?;
    Ok((first, duration_s))
}

/// Parse raw bytes (handles decompression automatically).
pub fn parse_bytes(data: &[u8]) -> WpResult<ParsedActivity> {
    parse_bytes_for_version(data, CURRENT_PARSER_VERSION)
}

fn preserve_missing_elevation_for_version(parser_version: u32) -> WpResult<bool> {
    match parser_version {
        PARSER_VERSION_V1 => Ok(false),
        PARSER_VERSION_V2 | PARSER_VERSION_V3 | PARSER_VERSION_V4 | PARSER_VERSION_V5 => Ok(true),
        _ => Err(WpError::Parse(format!(
            "unsupported parser_version for source parsing: {parser_version}"
        ))),
    }
}

/// Parse source bytes according to the recorded parser semantics.
///
/// V1 intentionally preserves the legacy XML interpretation where a missing
/// elevation sample meant sea level. V2 preserves missing elevation as missing.
/// This dispatch must happen before canonicalization for replay to be valid.
pub fn parse_bytes_for_version(data: &[u8], parser_version: u32) -> WpResult<ParsedActivity> {
    let preserve_missing_elevation = preserve_missing_elevation_for_version(parser_version)?;
    let decompressed = decompress_safe(data, 0)?;
    let bytes = decompressed.as_slice();

    let file_type = if parser_version == PARSER_VERSION_V1 {
        detect_file_type_v1(bytes)?
    } else {
        detect_file_type(bytes)?
    };
    match file_type {
        WorkoutFileType::Fit => parse_fit(bytes),
        WorkoutFileType::Gpx => parse_gpx(bytes, preserve_missing_elevation),
        WorkoutFileType::Tcx => parse_tcx(bytes, preserve_missing_elevation),
    }
}

/// Parse source bytes with an optional explicit file type under recorded
/// parser semantics. Version validation intentionally occurs before explicit
/// FIT/GPX/TCX dispatch so an unknown version cannot inherit V2 behavior.
pub fn parse_file_bytes_for_version(
    data: &[u8],
    file_type: &str,
    parser_version: u32,
) -> WpResult<ParsedActivity> {
    let preserve_missing_elevation = preserve_missing_elevation_for_version(parser_version)?;
    match file_type.to_ascii_lowercase().as_str() {
        "fit" | "gpx" | "tcx" => {
            let decompressed = decompress_safe(data, 0)?;
            match file_type.to_ascii_lowercase().as_str() {
                "fit" => parse_fit(decompressed.as_slice()),
                "gpx" => parse_gpx(decompressed.as_slice(), preserve_missing_elevation),
                "tcx" => parse_tcx(decompressed.as_slice(), preserve_missing_elevation),
                _ => unreachable!(),
            }
        }
        _ => parse_bytes_for_version(data, parser_version),
    }
}

/// Parse FIT file bytes.
fn parse_fit(data: &[u8]) -> WpResult<ParsedActivity> {
    use fitparser::Value;
    use std::io::Cursor;

    let mut cursor = Cursor::new(data);
    let fit_data =
        fitparser::from_reader(&mut cursor).map_err(|e| WpError::InvalidFit(e.to_string()))?;

    let mut activity = ParsedActivity::default();
    let mut time_ms_vec: Vec<i64> = Vec::new();
    let mut lat_vec: Vec<i32> = Vec::new();
    let mut lon_vec: Vec<i32> = Vec::new();
    let mut pwr_vec: Vec<u16> = Vec::new();
    let mut hr_vec: Vec<u8> = Vec::new();
    let mut cad_vec: Vec<u8> = Vec::new();
    let mut spd_vec: Vec<f32> = Vec::new();
    let mut dist_vec: Vec<f32> = Vec::new();
    let mut elev_vec: Vec<f32> = Vec::new();
    let mut temp_vec: Vec<f32> = Vec::new();
    let mut has_temperature = false;
    let mut acc_vec: Vec<f32> = Vec::new();
    let mut has_accuracy = false;
    let mut lr_vec: Vec<u8> = Vec::new();
    let mut has_lr = false;
    let mut pending_timer_stop_ms: Option<i64> = None;

    let mut has_gps = false;
    let mut has_power = false;
    let mut has_hr = false;
    let mut has_cadence = false;
    let mut has_speed = false;
    let mut has_distance = false;
    let mut has_elevation = false;

    for record in fit_data {
        activity.training_context.observe(&record);
        match record.kind() {
            fitparser::profile::MesgNum::Record => {
                let mut timestamp_ms: Option<i64> = None;
                let mut lat: Option<i32> = None;
                let mut lon: Option<i32> = None;
                let mut power: Option<u16> = None;
                let mut hr: Option<u8> = None;
                let mut cadence: Option<u8> = None;
                let mut speed: Option<f32> = None;
                let mut distance: Option<f32> = None;
                let mut altitude: Option<f32> = None;
                let mut temperature: Option<f32> = None;
                let mut gps_accuracy: Option<f32> = None;
                let mut lr_balance: Option<u8> = None;

                for field in record.fields() {
                    match field.name() {
                        "timestamp" => {
                            if let Value::Timestamp(ts) = field.value() {
                                timestamp_ms = Some(ts.timestamp_millis());
                            }
                        }
                        "position_lat" => {
                            if let Value::SInt32(v) = field.value() {
                                // Convert semicircles to e7 degrees
                                let deg = (*v as f64) * (180.0 / 2147483648.0);
                                lat = Some((deg * 1e7) as i32);
                                has_gps = true;
                            }
                        }
                        "position_long" => {
                            if let Value::SInt32(v) = field.value() {
                                let deg = (*v as f64) * (180.0 / 2147483648.0);
                                lon = Some((deg * 1e7) as i32);
                            }
                        }
                        "power" => {
                            if let Value::UInt16(v) = field.value() {
                                power = Some(*v);
                                has_power = true;
                            }
                        }
                        "heart_rate" => {
                            if let Value::UInt8(v) = field.value() {
                                hr = Some(*v);
                                has_hr = true;
                            }
                        }
                        "cadence" => {
                            if let Value::UInt8(v) = field.value() {
                                cadence = Some(*v);
                                has_cadence = true;
                            }
                        }
                        "enhanced_speed" | "speed" => {
                            match field.value() {
                                Value::Float64(v) => {
                                    speed = Some(*v as f32);
                                    has_speed = true;
                                }
                                Value::UInt16(v) => {
                                    // Speed in m/s * 1000
                                    speed = Some(*v as f32 / 1000.0);
                                    has_speed = true;
                                }
                                _ => {}
                            }
                        }
                        "distance" => {
                            match field.value() {
                                Value::Float64(v) => {
                                    distance = Some(*v as f32);
                                    has_distance = true;
                                }
                                Value::UInt32(v) => {
                                    // Distance in cm or m depending on device
                                    distance = Some(*v as f32 / 100.0);
                                    has_distance = true;
                                }
                                _ => {}
                            }
                        }
                        "gps_accuracy" => {
                            if let Value::UInt8(v) = field.value() {
                                gps_accuracy = Some(*v as f32);
                                has_accuracy = true;
                            }
                        }
                        "left_right_balance" => {
                            if let Value::UInt8(v) = field.value() {
                                lr_balance = Some(*v);
                                has_lr = true;
                            }
                        }
                        "temperature" => {
                            match field.value() {
                                Value::SInt8(v) => {
                                    temperature = Some(*v as f32);
                                    has_temperature = true;
                                }
                                Value::Float64(v) => {
                                    temperature = Some(*v as f32);
                                    has_temperature = true;
                                }
                                _ => {}
                            }
                        }
                        "enhanced_altitude" | "altitude" => {
                            match field.value() {
                                Value::Float64(v) => {
                                    altitude = Some(*v as f32);
                                    has_elevation = true;
                                }
                                Value::UInt16(v) => {
                                    // Altitude offset by 500m, in 0.2m units
                                    altitude = Some((*v as f32 / 5.0) - 500.0);
                                    has_elevation = true;
                                }
                                _ => {}
                            }
                        }
                        _ => {}
                    }
                }

                if let Some(ts) = timestamp_ms {
                    time_ms_vec.push(ts);
                    lat_vec.push(lat.unwrap_or(MISSING_I32));
                    lon_vec.push(lon.unwrap_or(MISSING_I32));
                    pwr_vec.push(power.unwrap_or(MISSING_U16));
                    hr_vec.push(hr.unwrap_or(MISSING_U8));
                    cad_vec.push(cadence.unwrap_or(MISSING_U8));
                    activity.motion_sample_presence.push(
                        u8::from(speed.is_some()) | (u8::from(distance.is_some()) << 1),
                    );
                    spd_vec.push(speed.unwrap_or(0.0));
                    dist_vec.push(distance.unwrap_or(0.0));
                    elev_vec.push(altitude.unwrap_or(f32::NAN));
                    temp_vec.push(temperature.unwrap_or(f32::NAN));
                    acc_vec.push(gps_accuracy.unwrap_or(f32::NAN));
                    lr_vec.push(lr_balance.unwrap_or(u8::MAX));
                }
            }
            fitparser::profile::MesgNum::FileId => {
                for field in record.fields() {
                    if field.name() == "manufacturer" {
                        activity.device_name = Some(format!("{:?}", field.value()));
                    }
                }
            }
            fitparser::profile::MesgNum::Sport => {
                for field in record.fields() {
                    if field.name() == "sport" {
                        activity.sport = format!("{:?}", field.value()).to_lowercase();
                    }
                }
            }
            fitparser::profile::MesgNum::Event => {
                // Explicit timer testimony: a stop opens a pause span, the
                // next start closes it. Unpaired stops close at the last
                // sample (handled after the loop).
                let mut is_timer = false;
                let mut event_type: Option<String> = None;
                let mut event_ts_ms: Option<i64> = None;
                for field in record.fields() {
                    match field.name() {
                        "event" => {
                            let value = format!("{:?}", field.value()).to_lowercase();
                            if value.contains("timer") {
                                is_timer = true;
                            }
                        }
                        "event_type" => {
                            event_type = Some(
                                format!("{:?}", field.value()).to_lowercase()
                            );
                        }
                        "timestamp" => {
                            if let Value::Timestamp(ts) = field.value() {
                                event_ts_ms = Some(ts.timestamp_millis());
                            }
                        }
                        _ => {}
                    }
                }
                if is_timer {
                    if let (Some(kind), Some(ts)) = (event_type, event_ts_ms) {
                        if kind.contains("stop") {
                            if pending_timer_stop_ms.is_none() {
                                pending_timer_stop_ms = Some(ts);
                            }
                        } else if kind.contains("start") {
                            if let Some(stop_ms) = pending_timer_stop_ms.take() {
                                if ts > stop_ms {
                                    activity.timer_pauses.push((stop_ms, ts));
                                }
                            }
                        }
                    }
                }
            }
            fitparser::profile::MesgNum::DeviceInfo => {
                let mut device = DeviceProvenance::default();
                let mut saw_any = false;
                for field in record.fields() {
                    let rendered = || format!("{:?}", field.value());
                    match field.name() {
                        "manufacturer" => {
                            device.manufacturer = Some(rendered());
                            saw_any = true;
                        }
                        "product" | "garmin_product" | "product_name" => {
                            device.product = Some(rendered());
                            saw_any = true;
                        }
                        "serial_number" => {
                            device.serial_number = Some(rendered());
                            saw_any = true;
                        }
                        "device_type" | "antplus_device_type" | "source_type" => {
                            if device.device_type.is_none() {
                                device.device_type = Some(rendered());
                                saw_any = true;
                            }
                        }
                        "software_version" => {
                            device.software_version = Some(rendered());
                            saw_any = true;
                        }
                        _ => {}
                    }
                }
                if saw_any {
                    activity.devices.push(device);
                }
            }
            fitparser::profile::MesgNum::Lap => {
                let mut lap = LapSummary::default();
                let mut saw_any = false;
                for field in record.fields() {
                    let as_f64 = |value: &Value| -> Option<f64> {
                        match value {
                            Value::Float64(v) => Some(*v),
                            Value::Float32(v) => Some(*v as f64),
                            Value::UInt32(v) => Some(*v as f64),
                            Value::UInt16(v) => Some(*v as f64),
                            _ => None,
                        }
                    };
                    match field.name() {
                        "start_time" => {
                            if let Value::Timestamp(ts) = field.value() {
                                lap.started_at_ms = Some(ts.timestamp_millis());
                                saw_any = true;
                            }
                        }
                        "total_elapsed_time" => {
                            lap.total_elapsed_s = as_f64(field.value());
                            saw_any = true;
                        }
                        "total_timer_time" => {
                            lap.total_timer_s = as_f64(field.value());
                            saw_any = true;
                        }
                        "total_distance" => {
                            lap.total_distance_m = as_f64(field.value());
                            saw_any = true;
                        }
                        "total_ascent" => {
                            lap.total_ascent_m = as_f64(field.value());
                            saw_any = true;
                        }
                        "avg_power" => {
                            if let Value::UInt16(v) = field.value() {
                                lap.avg_power_w = Some(*v);
                                saw_any = true;
                            }
                        }
                        "max_power" => {
                            if let Value::UInt16(v) = field.value() {
                                lap.max_power_w = Some(*v);
                                saw_any = true;
                            }
                        }
                        "avg_heart_rate" => {
                            if let Value::UInt8(v) = field.value() {
                                lap.avg_hr_bpm = Some(*v);
                                saw_any = true;
                            }
                        }
                        "avg_cadence" => {
                            if let Value::UInt8(v) = field.value() {
                                lap.avg_cadence_rpm = Some(*v);
                                saw_any = true;
                            }
                        }
                        _ => {}
                    }
                }
                if saw_any {
                    activity.laps.push(lap);
                }
            }
            fitparser::profile::MesgNum::Session => {
                let mut summary = activity.device_summary.take().unwrap_or_default();
                for field in record.fields() {
                    let as_f64 = |value: &Value| -> Option<f64> {
                        match value {
                            Value::Float64(v) => Some(*v),
                            Value::Float32(v) => Some(*v as f64),
                            Value::UInt32(v) => Some(*v as f64),
                            Value::UInt16(v) => Some(*v as f64),
                            _ => None,
                        }
                    };
                    match field.name() {
                        "total_calories" => {
                            summary.total_calories_kcal = as_f64(field.value());
                        }
                        "avg_heart_rate" => {
                            if let Value::UInt8(v) = field.value() {
                                summary.avg_hr_bpm = Some(*v);
                            }
                        }
                        "max_heart_rate" => {
                            if let Value::UInt8(v) = field.value() {
                                summary.max_hr_bpm = Some(*v);
                            }
                        }
                        "total_timer_time" => {
                            summary.total_timer_time_s = as_f64(field.value());
                        }
                        "total_elapsed_time" => {
                            summary.total_elapsed_time_s = as_f64(field.value());
                        }
                        "total_distance" => {
                            summary.total_distance_m = as_f64(field.value());
                        }
                        "total_ascent" => {
                            summary.total_ascent_m = as_f64(field.value());
                        }
                        "avg_power" => {
                            if let Value::UInt16(v) = field.value() {
                                summary.avg_power_w = Some(*v);
                            }
                        }
                        "max_power" => {
                            if let Value::UInt16(v) = field.value() {
                                summary.max_power_w = Some(*v);
                            }
                        }
                        _ => {}
                    }
                }
                activity.device_summary = Some(summary);
            }
            _ => {}
        }
    }

    if time_ms_vec.is_empty() {
        return Err(WpError::InvalidFit("No data records found".into()));
    }

    // An unpaired timer stop (rider ended without resuming) closes at the
    // last sample — pause evidence never extends past recorded ground.
    if let (Some(stop_ms), Some(&last_ms)) = (pending_timer_stop_ms, time_ms_vec.last()) {
        if last_ms > stop_ms {
            activity.timer_pauses.push((stop_ms, last_ms));
        }
    }

    // Set timestamps
    let (started_at_ms, total_elapsed_s) = validate_activity_timestamps(&time_ms_vec)?;
    activity.started_at_ms = started_at_ms;
    activity.total_elapsed_s = total_elapsed_s;

    activity.time_ms = time_ms_vec;

    if has_gps {
        activity.lat_e7 = Some(lat_vec);
        activity.lon_e7 = Some(lon_vec);
    }
    if has_power {
        activity.pwr_w = Some(pwr_vec);
    }
    if has_hr {
        activity.hr_bpm = Some(hr_vec);
    }
    if has_cadence {
        activity.cadence_rpm = Some(cad_vec);
    }
    if has_temperature {
        activity.temperature_c = Some(temp_vec);
    }
    if has_accuracy {
        activity.gps_accuracy_m = Some(acc_vec);
    }
    if has_lr {
        activity.lr_balance_raw = Some(lr_vec);
    }
    if has_speed {
        activity.speed_mps = Some(spd_vec);
    }
    if has_distance {
        activity.dist_m = Some(dist_vec);
    }
    if has_elevation {
        activity.elevation_m = Some(elev_vec);
    }

    Ok(activity)
}

/// Parse GPX file bytes.
fn parse_gpx(data: &[u8], preserve_missing_elevation: bool) -> WpResult<ParsedActivity> {
    use quick_xml::events::Event;
    use quick_xml::Reader;

    let mut reader = Reader::from_reader(xml_bytes(data));
    reader.trim_text(true);

    let mut activity = ParsedActivity::default();
    activity.sport = "cycling".to_string();

    let mut time_ms_vec: Vec<i64> = Vec::new();
    let mut lat_vec: Vec<i32> = Vec::new();
    let mut lon_vec: Vec<i32> = Vec::new();
    let mut elev_vec: Vec<f32> = Vec::new();
    let mut hr_vec: Vec<u8> = Vec::new();
    let mut cad_vec: Vec<u8> = Vec::new();
    let mut pwr_vec: Vec<u16> = Vec::new();

    let mut has_hr = false;
    let mut has_cad = false;
    let mut has_pwr = false;
    let mut has_elevation = false;

    let mut buf = Vec::new();
    let mut current_lat: Option<i32> = None;
    let mut current_lon: Option<i32> = None;
    let mut current_ele: Option<f32> = None;
    let mut current_time: Option<i64> = None;
    let mut current_hr: Option<u8> = None;
    let mut current_cad: Option<u8> = None;
    let mut current_pwr: Option<u16> = None;
    let mut in_ele = false;
    let mut in_time = false;
    let mut in_hr = false;
    let mut in_cad = false;
    let mut in_pwr = false;
    let mut in_trkpt = false;

    loop {
        let event = reader.read_event_into(&mut buf);
        if let Ok(Event::Start(ref e)) = event {
            if e.local_name().as_ref() == b"gpx" {
                for attr in e.attributes().flatten() {
                    if attr.key.local_name().as_ref() == b"creator" {
                        if let Ok(creator) = std::str::from_utf8(&attr.value) {
                            activity.training_context.observe_creator(creator);
                        }
                    }
                }
            }
        }
        match event {
            // V1 intentionally preserves the parser's old raw QName matching,
            // global element flags, and self-closing element treatment.
            Ok(Event::Start(ref e)) | Ok(Event::Empty(ref e)) if !preserve_missing_elevation => {
                match e.name().as_ref() {
                    b"trkpt" => {
                        for attr in e.attributes().flatten() {
                            match attr.key.as_ref() {
                                b"lat" => {
                                    if let Ok(s) = std::str::from_utf8(&attr.value) {
                                        if let Ok(v) = s.parse::<f64>() {
                                            current_lat = Some((v * 1e7) as i32);
                                        }
                                    }
                                }
                                b"lon" => {
                                    if let Ok(s) = std::str::from_utf8(&attr.value) {
                                        if let Ok(v) = s.parse::<f64>() {
                                            current_lon = Some((v * 1e7) as i32);
                                        }
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                    b"ele" => in_ele = true,
                    b"time" => in_time = true,
                    b"hr" | b"heartrate" => in_hr = true,
                    b"cad" | b"cadence" => in_cad = true,
                    b"power" => in_pwr = true,
                    _ => {}
                }
            }
            Ok(Event::Start(ref e)) => {
                let local_name = e.local_name();
                match local_name.as_ref() {
                    b"trkpt" => {
                        in_trkpt = true;
                        current_lat = None;
                        current_lon = None;
                        current_ele = None;
                        current_time = None;
                        current_hr = None;
                        current_cad = None;
                        current_pwr = None;
                        // Parse lat/lon from attributes
                        for attr in e.attributes().flatten() {
                            let attribute_name = attr.key.local_name();
                            match attribute_name.as_ref() {
                                b"lat" => {
                                    if let Ok(s) = std::str::from_utf8(&attr.value) {
                                        if let Ok(v) = s.parse::<f64>() {
                                            current_lat = Some((v * 1e7) as i32);
                                        }
                                    }
                                }
                                b"lon" => {
                                    if let Ok(s) = std::str::from_utf8(&attr.value) {
                                        if let Ok(v) = s.parse::<f64>() {
                                            current_lon = Some((v * 1e7) as i32);
                                        }
                                    }
                                }
                                _ => {}
                            }
                        }
                    }
                    b"ele" if in_trkpt => in_ele = true,
                    b"time" if in_trkpt => in_time = true,
                    b"hr" | b"heartrate" if in_trkpt => in_hr = true,
                    b"cad" | b"cadence" if in_trkpt => in_cad = true,
                    b"power" if in_trkpt => in_pwr = true,
                    _ => {}
                }
            }
            Ok(Event::Text(ref e)) => {
                if let Ok(text) = e.unescape() {
                    let text = text.trim();
                    if in_ele {
                        if let Ok(v) = text.parse::<f64>() {
                            current_ele = Some(v as f32);
                            has_elevation = true;
                        }
                    } else if in_time {
                        // Parse ISO 8601 timestamp
                        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(text) {
                            current_time = Some(dt.timestamp_millis());
                        }
                    } else if in_hr {
                        if let Ok(v) = text.parse::<u8>() {
                            current_hr = Some(v);
                            has_hr = true;
                        }
                    } else if in_cad {
                        if let Ok(v) = text.parse::<u8>() {
                            current_cad = Some(v);
                            has_cad = true;
                        }
                    } else if in_pwr {
                        if let Ok(v) = text.parse::<u16>() {
                            current_pwr = Some(v);
                            has_pwr = true;
                        }
                    }
                }
            }
            Ok(Event::End(ref e)) if !preserve_missing_elevation => match e.name().as_ref() {
                b"trkpt" => {
                    if let (Some(time), Some(lat), Some(lon)) =
                        (current_time, current_lat, current_lon)
                    {
                        time_ms_vec.push(time);
                        lat_vec.push(lat);
                        lon_vec.push(lon);
                        elev_vec.push(current_ele.unwrap_or(0.0));
                        hr_vec.push(current_hr.unwrap_or(MISSING_U8));
                        cad_vec.push(current_cad.unwrap_or(MISSING_U8));
                        pwr_vec.push(current_pwr.unwrap_or(MISSING_U16));
                    }
                    current_lat = None;
                    current_lon = None;
                    current_ele = None;
                    current_time = None;
                    current_hr = None;
                    current_cad = None;
                    current_pwr = None;
                }
                b"ele" => in_ele = false,
                b"time" => in_time = false,
                b"hr" | b"heartrate" => in_hr = false,
                b"cad" | b"cadence" => in_cad = false,
                b"power" => in_pwr = false,
                _ => {}
            },
            Ok(Event::End(ref e)) => {
                let local_name = e.local_name();
                match local_name.as_ref() {
                    b"trkpt" => {
                        if let (Some(time), Some(lat), Some(lon)) =
                            (current_time, current_lat, current_lon)
                        {
                            time_ms_vec.push(time);
                            lat_vec.push(lat);
                            lon_vec.push(lon);
                            elev_vec.push(if preserve_missing_elevation {
                                current_ele.unwrap_or(f32::NAN)
                            } else {
                                current_ele.unwrap_or(0.0)
                            });
                            hr_vec.push(current_hr.unwrap_or(MISSING_U8));
                            cad_vec.push(current_cad.unwrap_or(MISSING_U8));
                            pwr_vec.push(current_pwr.unwrap_or(MISSING_U16));
                        }
                        // Reset
                        current_lat = None;
                        current_lon = None;
                        current_ele = None;
                        current_time = None;
                        current_hr = None;
                        current_cad = None;
                        current_pwr = None;
                        in_trkpt = false;
                    }
                    b"ele" => in_ele = false,
                    b"time" => in_time = false,
                    b"hr" | b"heartrate" => in_hr = false,
                    b"cad" | b"cadence" => in_cad = false,
                    b"power" => in_pwr = false,
                    _ => {}
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(WpError::InvalidGpx(e.to_string())),
            _ => {}
        }
        buf.clear();
    }

    if time_ms_vec.is_empty() {
        return Err(WpError::InvalidGpx("No trackpoints found".into()));
    }

    let (started_at_ms, total_elapsed_s) = validate_activity_timestamps(&time_ms_vec)?;
    activity.started_at_ms = started_at_ms;
    activity.total_elapsed_s = total_elapsed_s;

    activity.time_ms = time_ms_vec;
    activity.lat_e7 = Some(lat_vec);
    activity.lon_e7 = Some(lon_vec);
    if has_elevation || !preserve_missing_elevation {
        activity.elevation_m = Some(elev_vec);
    }

    if has_hr {
        activity.hr_bpm = Some(hr_vec);
    }
    if has_cad {
        activity.cadence_rpm = Some(cad_vec);
    }
    if has_pwr {
        activity.pwr_w = Some(pwr_vec);
    }

    Ok(activity)
}

/// Parse TCX file bytes.
fn parse_tcx(data: &[u8], preserve_missing_elevation: bool) -> WpResult<ParsedActivity> {
    // TCX is similar to GPX - XML with trackpoints
    // For now, use a simplified parser
    use quick_xml::events::Event;
    use quick_xml::Reader;

    let mut reader = Reader::from_reader(xml_bytes(data));
    reader.trim_text(true);

    let mut activity = ParsedActivity::default();
    activity.sport = "cycling".to_string();

    let mut time_ms_vec: Vec<i64> = Vec::new();
    let mut lat_vec: Vec<i32> = Vec::new();
    let mut lon_vec: Vec<i32> = Vec::new();
    let mut elev_vec: Vec<f32> = Vec::new();
    let mut hr_vec: Vec<u8> = Vec::new();
    let mut cad_vec: Vec<u8> = Vec::new();
    let mut pwr_vec: Vec<u16> = Vec::new();
    let mut dist_vec: Vec<f32> = Vec::new();

    let mut has_hr = false;
    let mut has_cad = false;
    let mut has_pwr = false;
    let mut has_elevation = false;

    let mut buf = Vec::new();
    let mut current_lat: Option<i32> = None;
    let mut current_lon: Option<i32> = None;
    let mut current_ele: Option<f32> = None;
    let mut current_time: Option<i64> = None;
    let mut current_hr: Option<u8> = None;
    let mut current_cad: Option<u8> = None;
    let mut current_pwr: Option<u16> = None;
    let mut current_dist: Option<f32> = None;
    let mut current_speed: Option<f32> = None;

    let mut in_time = false;
    let mut in_lat = false;
    let mut in_lon = false;
    let mut in_ele = false;
    let mut in_hr = false;
    let mut in_cad = false;
    let mut in_pwr = false;
    let mut in_dist = false;
    let mut in_speed = false;
    let mut in_trackpoint = false;

    loop {
        match reader.read_event_into(&mut buf) {
            Ok(Event::Start(ref e)) if !preserve_missing_elevation => match e.name().as_ref() {
                b"Time" => in_time = true,
                b"LatitudeDegrees" => in_lat = true,
                b"LongitudeDegrees" => in_lon = true,
                b"AltitudeMeters" => in_ele = true,
                b"HeartRateBpm" => in_hr = true,
                b"Cadence" => in_cad = true,
                b"Watts" => in_pwr = true,
                b"DistanceMeters" => in_dist = true,
                b"Speed" => in_speed = true,
                b"Value" if in_hr => {}
                _ => {}
            },
            Ok(Event::Start(ref e)) => {
                let local_name = e.local_name();
                match local_name.as_ref() {
                    b"Trackpoint" => {
                        in_trackpoint = true;
                        current_lat = None;
                        current_lon = None;
                        current_ele = None;
                        current_time = None;
                        current_hr = None;
                        current_cad = None;
                        current_pwr = None;
                        current_dist = None;
                        current_speed = None;
                    }
                    b"Time" if in_trackpoint => in_time = true,
                    b"LatitudeDegrees" if in_trackpoint => in_lat = true,
                    b"LongitudeDegrees" if in_trackpoint => in_lon = true,
                    b"AltitudeMeters" if in_trackpoint => in_ele = true,
                    b"HeartRateBpm" if in_trackpoint => in_hr = true,
                    b"Cadence" if in_trackpoint => in_cad = true,
                    b"Watts" if in_trackpoint => in_pwr = true,
                    b"DistanceMeters" if in_trackpoint => in_dist = true,
                    b"Speed" if in_trackpoint => in_speed = true,
                    b"Value" if in_hr => {} // HR value is inside <Value> tag
                    _ => {}
                }
            }
            Ok(Event::Text(ref e)) => {
                if let Ok(text) = e.unescape() {
                    let text = text.trim();
                    if in_time {
                        if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(text) {
                            current_time = Some(dt.timestamp_millis());
                        }
                    } else if in_lat {
                        if let Ok(v) = text.parse::<f64>() {
                            current_lat = Some((v * 1e7) as i32);
                        }
                    } else if in_lon {
                        if let Ok(v) = text.parse::<f64>() {
                            current_lon = Some((v * 1e7) as i32);
                        }
                    } else if in_ele {
                        if let Ok(v) = text.parse::<f64>() {
                            current_ele = Some(v as f32);
                            has_elevation = true;
                        }
                    } else if in_hr {
                        if let Ok(v) = text.parse::<u8>() {
                            current_hr = Some(v);
                            has_hr = true;
                        }
                    } else if in_cad {
                        if let Ok(v) = text.parse::<u8>() {
                            current_cad = Some(v);
                            has_cad = true;
                        }
                    } else if in_pwr {
                        if let Ok(v) = text.parse::<u16>() {
                            current_pwr = Some(v);
                            has_pwr = true;
                        }
                    } else if in_dist {
                        if let Ok(v) = text.parse::<f32>() {
                            current_dist = Some(v);
                        }
                    } else if in_speed {
                        current_speed = text.parse::<f32>().ok();
                    }
                }
            }
            Ok(Event::End(ref e)) if !preserve_missing_elevation => match e.name().as_ref() {
                b"Trackpoint" => {
                    if let Some(time) = current_time {
                        time_ms_vec.push(time);
                        lat_vec.push(current_lat.unwrap_or(MISSING_I32));
                        lon_vec.push(current_lon.unwrap_or(MISSING_I32));
                        elev_vec.push(current_ele.unwrap_or(0.0));
                        hr_vec.push(current_hr.unwrap_or(MISSING_U8));
                        cad_vec.push(current_cad.unwrap_or(MISSING_U8));
                        pwr_vec.push(current_pwr.unwrap_or(MISSING_U16));
                        dist_vec.push(current_dist.unwrap_or(0.0));
                        activity.motion_sample_presence
                            .push(u8::from(current_speed.is_some()) | (u8::from(current_dist.is_some()) << 1));
                        activity.motion_speed_mps.push(current_speed.unwrap_or(f32::NAN));
                    }
                    current_lat = None;
                    current_lon = None;
                    current_ele = None;
                    current_time = None;
                    current_hr = None;
                    current_cad = None;
                    current_pwr = None;
                    current_dist = None;
                    current_speed = None;
                }
                b"Time" => in_time = false,
                b"LatitudeDegrees" => in_lat = false,
                b"LongitudeDegrees" => in_lon = false,
                b"AltitudeMeters" => in_ele = false,
                b"HeartRateBpm" => in_hr = false,
                b"Cadence" => in_cad = false,
                b"Watts" => in_pwr = false,
                b"DistanceMeters" => in_dist = false,
                b"Speed" => in_speed = false,
                _ => {}
            },
            Ok(Event::End(ref e)) => {
                let local_name = e.local_name();
                match local_name.as_ref() {
                    b"Trackpoint" => {
                        if let Some(time) = current_time {
                            time_ms_vec.push(time);
                            lat_vec.push(current_lat.unwrap_or(MISSING_I32));
                            lon_vec.push(current_lon.unwrap_or(MISSING_I32));
                            elev_vec.push(if preserve_missing_elevation {
                                current_ele.unwrap_or(f32::NAN)
                            } else {
                                current_ele.unwrap_or(0.0)
                            });
                            hr_vec.push(current_hr.unwrap_or(MISSING_U8));
                            cad_vec.push(current_cad.unwrap_or(MISSING_U8));
                            pwr_vec.push(current_pwr.unwrap_or(MISSING_U16));
                            dist_vec.push(current_dist.unwrap_or(0.0));
                            activity.motion_sample_presence
                                .push(u8::from(current_speed.is_some()) | (u8::from(current_dist.is_some()) << 1));
                            activity.motion_speed_mps.push(current_speed.unwrap_or(f32::NAN));
                        }
                        // Reset
                        current_lat = None;
                        current_lon = None;
                        current_ele = None;
                        current_time = None;
                        current_hr = None;
                        current_cad = None;
                        current_pwr = None;
                        current_dist = None;
                        current_speed = None;
                        in_trackpoint = false;
                    }
                    b"Time" => in_time = false,
                    b"LatitudeDegrees" => in_lat = false,
                    b"LongitudeDegrees" => in_lon = false,
                    b"AltitudeMeters" => in_ele = false,
                    b"HeartRateBpm" => in_hr = false,
                    b"Cadence" => in_cad = false,
                    b"Watts" => in_pwr = false,
                    b"DistanceMeters" => in_dist = false,
                    b"Speed" => in_speed = false,
                    _ => {}
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => return Err(WpError::InvalidTcx(e.to_string())),
            _ => {}
        }
        buf.clear();
    }

    if time_ms_vec.is_empty() {
        return Err(WpError::InvalidTcx("No trackpoints found".into()));
    }

    let (started_at_ms, total_elapsed_s) = validate_activity_timestamps(&time_ms_vec)?;
    activity.started_at_ms = started_at_ms;
    activity.total_elapsed_s = total_elapsed_s;

    activity.time_ms = time_ms_vec;
    activity.lat_e7 = Some(lat_vec);
    activity.lon_e7 = Some(lon_vec);
    if has_elevation || !preserve_missing_elevation {
        activity.elevation_m = Some(elev_vec);
    }
    activity.dist_m = Some(dist_vec);

    if has_hr {
        activity.hr_bpm = Some(hr_vec);
    }
    if has_cad {
        activity.cadence_rpm = Some(cad_vec);
    }
    if has_pwr {
        activity.pwr_w = Some(pwr_vec);
    }

    Ok(activity)
}

// =============================================================================
// PyO3 Bindings
// =============================================================================

/// Python-exposed parsed activity.

#[cfg(feature = "python")]
#[pyclass(name = "ParsedActivity")]
pub struct PyParsedActivity {
    inner: ParsedActivity,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyParsedActivity {
    #[getter]
    fn time_ms<'py>(&self, py: Python<'py>) -> Py<PyArray1<i64>> {
        self.inner.time_ms.clone().into_pyarray(py).into()
    }

    #[getter]
    fn lat_e7<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<i32>>> {
        self.inner
            .lat_e7
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn lon_e7<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<i32>>> {
        self.inner
            .lon_e7
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn elevation_m<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<f32>>> {
        self.inner
            .elevation_m
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn pwr_w<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<u16>>> {
        self.inner
            .pwr_w
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn hr_bpm<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<u8>>> {
        self.inner
            .hr_bpm
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn cadence_rpm<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<u8>>> {
        self.inner
            .cadence_rpm
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn temperature_c<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<f32>>> {
        self.inner
            .temperature_c
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    /// Explicit timer pause spans as (stop_ms, resume_ms) tuples.
    #[getter]
    fn timer_pauses(&self) -> Vec<(i64, i64)> {
        self.inner.timer_pauses.clone()
    }

    /// Moving time from explicit timer events; None without events.
    #[getter]
    fn event_moving_time_s(&self) -> Option<u32> {
        self.inner.event_moving_time_s()
    }

    /// Device provenance rows as dicts (head unit + sensors).
    #[getter]
    fn devices(&self, py: Python<'_>) -> Vec<Py<pyo3::types::PyDict>> {
        use pyo3::types::PyDict;
        self.inner
            .devices
            .iter()
            .map(|d| {
                let dict = PyDict::new(py);
                let _ = dict.set_item("manufacturer", d.manufacturer.clone());
                let _ = dict.set_item("product", d.product.clone());
                let _ = dict.set_item("serial_number", d.serial_number.clone());
                let _ = dict.set_item("device_type", d.device_type.clone());
                let _ = dict.set_item("software_version", d.software_version.clone());
                dict.into()
            })
            .collect()
    }

    /// Device laps as dicts, in file order.
    #[getter]
    fn laps(&self, py: Python<'_>) -> Vec<Py<pyo3::types::PyDict>> {
        use pyo3::types::PyDict;
        self.inner
            .laps
            .iter()
            .map(|lap| {
                let dict = PyDict::new(py);
                let _ = dict.set_item("started_at_ms", lap.started_at_ms);
                let _ = dict.set_item("total_elapsed_s", lap.total_elapsed_s);
                let _ = dict.set_item("total_timer_s", lap.total_timer_s);
                let _ = dict.set_item("total_distance_m", lap.total_distance_m);
                let _ = dict.set_item("total_ascent_m", lap.total_ascent_m);
                let _ = dict.set_item("avg_power_w", lap.avg_power_w);
                let _ = dict.set_item("max_power_w", lap.max_power_w);
                let _ = dict.set_item("avg_hr_bpm", lap.avg_hr_bpm);
                let _ = dict.set_item("avg_cadence_rpm", lap.avg_cadence_rpm);
                dict.into()
            })
            .collect()
    }

    #[getter]
    fn gps_accuracy_m<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<f32>>> {
        self.inner
            .gps_accuracy_m
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    /// Raw FIT left/right balance bytes (255 = missing).
    #[getter]
    fn lr_balance_raw<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<u8>>> {
        self.inner
            .lr_balance_raw
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    /// Device time and indoor evidence, outside canonical ride identity.
    #[getter]
    fn training_context(&self, py: Python<'_>) -> PyResult<Py<pyo3::types::PyDict>> {
        let dict = pyo3::types::PyDict::new(py);
        dict.set_item("utc_offset_s", self.inner.training_context.utc_offset_s)?;
        dict.set_item("indoor_or_virtual", self.inner.training_context.indoor_or_virtual)?;
        Ok(dict.into())
    }

    /// The device's Session claims as a dict; None when absent.
    #[getter]
    fn device_summary(&self, py: Python<'_>) -> Option<Py<pyo3::types::PyDict>> {
        use pyo3::types::PyDict;
        self.inner.device_summary.as_ref().map(|s| {
            let dict = PyDict::new(py);
            let _ = dict.set_item("total_calories_kcal", s.total_calories_kcal);
            let _ = dict.set_item("avg_hr_bpm", s.avg_hr_bpm);
            let _ = dict.set_item("max_hr_bpm", s.max_hr_bpm);
            let _ = dict.set_item("total_timer_time_s", s.total_timer_time_s);
            let _ = dict.set_item("total_elapsed_time_s", s.total_elapsed_time_s);
            let _ = dict.set_item("total_distance_m", s.total_distance_m);
            let _ = dict.set_item("total_ascent_m", s.total_ascent_m);
            let _ = dict.set_item("avg_power_w", s.avg_power_w);
            let _ = dict.set_item("max_power_w", s.max_power_w);
            dict.into()
        })
    }

    /// Non-canonical presence evidence; empty on formats without motion channels.
    #[getter]
    fn motion_sample_presence(&self) -> Vec<u8> {
        self.inner.motion_sample_presence.clone()
    }

    /// Recorded TCX speed outside the historical hash-bound metrics channels.
    #[getter]
    fn motion_speed_mps<'py>(&self, py: Python<'py>) -> Py<PyArray1<f32>> {
        self.inner.motion_speed_mps.clone().into_pyarray(py).into()
    }

    #[getter]
    fn speed_mps<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<f32>>> {
        self.inner
            .speed_mps
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn dist_m<'py>(&self, py: Python<'py>) -> Option<Py<PyArray1<f32>>> {
        self.inner
            .dist_m
            .as_ref()
            .map(|v| v.clone().into_pyarray(py).into())
    }

    #[getter]
    fn sport(&self) -> &str {
        &self.inner.sport
    }

    #[getter]
    fn device_name(&self) -> Option<&str> {
        self.inner.device_name.as_deref()
    }

    #[getter]
    fn started_at_ms(&self) -> i64 {
        self.inner.started_at_ms
    }

    #[getter]
    fn total_elapsed_s(&self) -> u32 {
        self.inner.total_elapsed_s
    }
}

/// Python-exposed computed metrics.
#[cfg(feature = "python")]
#[pyclass(name = "ComputedMetrics")]
pub struct PyComputedMetrics {
    inner: ComputedMetrics,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyComputedMetrics {
    #[getter]
    fn duration_s(&self) -> u32 {
        self.inner.duration_s
    }

    #[getter]
    fn moving_time_s(&self) -> u32 {
        self.inner.moving_time_s
    }

    #[getter]
    fn distance_m(&self) -> f32 {
        self.inner.distance_m
    }

    #[getter]
    fn elevation_gain_m(&self) -> f32 {
        self.inner.elevation_gain_m
    }

    #[getter]
    fn normalized_power_w(&self) -> Option<u16> {
        self.inner.normalized_power_w
    }

    #[getter]
    fn normalized_power_raw_w(&self) -> Option<f32> {
        self.inner.normalized_power_raw
    }

    #[getter]
    fn normalized_power_duration_s(&self) -> u32 {
        self.inner.normalized_power_duration_s
    }

    #[getter]
    fn avg_power_w(&self) -> Option<u16> {
        self.inner.avg_power_w
    }

    #[getter]
    fn max_power_w(&self) -> Option<u16> {
        self.inner.max_power_w
    }

    #[getter]
    fn power_sample_count(&self) -> u32 {
        self.inner.power_sample_count
    }

    #[getter]
    fn power_sample_coverage_bps(&self) -> u16 {
        self.inner.power_sample_coverage_bps
    }

    #[getter]
    fn tss(&self) -> Option<f32> {
        self.inner.tss
    }

    #[getter]
    fn intensity_factor(&self) -> Option<f32> {
        self.inner.intensity_factor
    }

    #[getter]
    fn kcals(&self) -> Option<u32> {
        self.inner.kcals
    }

    #[getter]
    fn avg_hr_bpm(&self) -> Option<u8> {
        self.inner.avg_hr_bpm
    }

    #[getter]
    fn max_hr_bpm(&self) -> Option<u8> {
        self.inner.max_hr_bpm
    }

    #[getter]
    fn heart_rate_sample_count(&self) -> u32 {
        self.inner.heart_rate_sample_count
    }

    #[getter]
    fn heart_rate_sample_coverage_bps(&self) -> u16 {
        self.inner.heart_rate_sample_coverage_bps
    }

    #[getter]
    fn avg_speed_mps(&self) -> Option<f32> {
        self.inner.avg_speed_mps
    }

    #[getter]
    fn max_speed_mps(&self) -> Option<f32> {
        self.inner.max_speed_mps
    }

    #[getter]
    fn avg_cadence_rpm(&self) -> Option<u8> {
        self.inner.avg_cadence_rpm
    }
}

/// Python-exposed H3 cell.
#[cfg(feature = "python")]
#[pyclass(name = "H3Cell")]
#[derive(Clone)]
pub struct PyH3Cell {
    inner: H3Cell,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyH3Cell {
    /// Get the H3 index as a hex string (e.g., "8a2a1072b59ffff").
    #[getter]
    fn index(&self) -> String {
        self.inner.to_string()
    }

    /// Get the resolution of this cell (0-15).
    #[getter]
    fn resolution(&self) -> u8 {
        self.inner.resolution()
    }

    /// Alias for index - returns hex string.
    fn to_string(&self) -> String {
        self.inner.to_string()
    }

    fn __repr__(&self) -> String {
        format!(
            "H3Cell(index='{}', resolution={})",
            self.inner.to_string(),
            self.inner.resolution()
        )
    }

    fn __str__(&self) -> String {
        self.inner.to_string()
    }

    fn __hash__(&self) -> u64 {
        use std::hash::{Hash, Hasher};
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        self.inner.index().hash(&mut hasher);
        hasher.finish()
    }

    fn __eq__(&self, other: &PyH3Cell) -> bool {
        self.inner.index() == other.inner.index()
    }
}

/// Legacy alias for backwards compatibility.
/// DEPRECATED: Use H3Cell instead.
#[cfg(feature = "python")]
#[pyclass(name = "Tile")]
#[derive(Clone)]
pub struct PyTile {
    inner: H3Cell,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyTile {
    /// DEPRECATED: Use H3Cell.index instead.
    #[getter]
    fn index(&self) -> String {
        self.inner.to_string()
    }

    /// DEPRECATED: Returns resolution, not zoom.
    #[getter]
    fn z(&self) -> u8 {
        self.inner.resolution()
    }

    /// DEPRECATED: H3 doesn't use x coordinate.
    #[getter]
    fn x(&self) -> u32 {
        0
    }

    /// DEPRECATED: H3 doesn't use y coordinate.
    #[getter]
    fn y(&self) -> u32 {
        0
    }

    /// DEPRECATED: H3 uses hex strings, not quadkeys.
    fn quadkey(&self) -> String {
        self.inner.to_string()
    }

    fn __repr__(&self) -> String {
        format!(
            "Tile(index='{}') [DEPRECATED: use H3Cell]",
            self.inner.to_string()
        )
    }
}

// =============================================================================
// Climb Detection PyO3 Bindings
// =============================================================================

#[cfg(feature = "python")]
use climb::{
    detect_climbs_v2, ClimbDetectorConfig, ClimbPattern, ClimbPatternDetector, ClimbV2,
    DetectionAlgorithm, MatchResult, SignatureV2, TerrainClassification, TerrainClassifier,
    TerrainMetrics, TileSample,
};
#[cfg(feature = "python")]
use std::collections::HashSet;

/// Python-exposed climb pattern.
#[cfg(feature = "python")]
#[pyclass(name = "ClimbPattern")]
#[derive(Clone)]
pub struct PyClimbPattern {
    inner: ClimbPattern,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyClimbPattern {
    /// Total vertical gain in meters.
    #[getter]
    fn vert_m(&self) -> f64 {
        self.inner.vert_m
    }

    /// Duration in seconds.
    #[getter]
    fn time_s(&self) -> u32 {
        self.inner.time_s
    }

    /// Average power during climb (watts).
    #[getter]
    fn avg_power_w(&self) -> Option<f64> {
        self.inner.avg_power_w
    }

    /// Watts per kilogram.
    #[getter]
    fn w_per_kg(&self) -> Option<f64> {
        self.inner.w_per_kg
    }

    /// Average heart rate.
    #[getter]
    fn avg_hr(&self) -> Option<u8> {
        self.inner.avg_hr
    }

    /// Start time offset from activity start (seconds).
    #[getter]
    fn start_time_offset_s(&self) -> u32 {
        self.inner.start_time_offset_s
    }

    /// End time offset from activity start (seconds).
    #[getter]
    fn end_time_offset_s(&self) -> u32 {
        self.inner.end_time_offset_s
    }

    /// Arena identifier (optional).
    #[getter]
    fn arena_id(&self) -> Option<String> {
        self.inner.arena_id.clone()
    }

    /// H3 tile IDs traversed during climb.
    #[getter]
    fn tile_ids(&self) -> Option<Vec<String>> {
        self.inner.tile_ids.clone()
    }

    /// Average gradient percentage.
    #[getter]
    fn avg_gradient_pct(&self) -> Option<f64> {
        self.inner.avg_gradient_pct
    }

    /// Horizontal distance in meters.
    #[getter]
    fn distance_m(&self) -> Option<f64> {
        self.inner.distance_m
    }

    /// 64-byte signature as hex string.
    #[getter]
    fn signature_hex(&self) -> Option<String> {
        self.inner.signature_hex.clone()
    }

    /// Canonical v2 signature from the selected detector bounds.
    #[getter]
    fn signature_v2_hex(&self) -> Option<String> {
        self.inner.signature_v2_hex.clone()
    }

    #[getter]
    fn start_lat(&self) -> Option<f64> {
        self.inner.start_lat
    }

    #[getter]
    fn start_lon(&self) -> Option<f64> {
        self.inner.start_lon
    }

    #[getter]
    fn end_lat(&self) -> Option<f64> {
        self.inner.end_lat
    }

    #[getter]
    fn end_lon(&self) -> Option<f64> {
        self.inner.end_lon
    }

    /// UCI-style climb category (HC, 1, 2, 3, 4, UC).
    #[getter]
    fn category(&self) -> &'static str {
        self.inner.calculate_uci_category()
    }

    /// VAM (Vertical Ascent Meters per hour).
    #[getter]
    fn vam(&self) -> f64 {
        self.inner.vam()
    }

    /// Convert to Python dict.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        use pyo3::types::PyDict;
        let dict = PyDict::new(py);
        dict.set_item("vert_m", self.inner.vert_m)?;
        dict.set_item("time_s", self.inner.time_s)?;
        dict.set_item("avg_power_w", self.inner.avg_power_w)?;
        dict.set_item("w_per_kg", self.inner.w_per_kg)?;
        dict.set_item("avg_hr", self.inner.avg_hr)?;
        dict.set_item("start_time_offset_s", self.inner.start_time_offset_s)?;
        dict.set_item("end_time_offset_s", self.inner.end_time_offset_s)?;
        dict.set_item("arena_id", self.inner.arena_id.clone())?;
        dict.set_item("tile_ids", self.inner.tile_ids.clone())?;
        dict.set_item("avg_gradient_pct", self.inner.avg_gradient_pct)?;
        dict.set_item("distance_m", self.inner.distance_m)?;
        dict.set_item("signature_hex", self.inner.signature_hex.clone())?;
        dict.set_item("signature_v2_hex", self.inner.signature_v2_hex.clone())?;
        dict.set_item("start_lat", self.inner.start_lat)?;
        dict.set_item("start_lon", self.inner.start_lon)?;
        dict.set_item("end_lat", self.inner.end_lat)?;
        dict.set_item("end_lon", self.inner.end_lon)?;
        dict.set_item("category", self.inner.calculate_uci_category())?;
        dict.set_item("vam", self.inner.vam())?;
        Ok(dict.into())
    }

    fn __repr__(&self) -> String {
        format!(
            "ClimbPattern(vert_m={:.0}, time_s={}, category='{}')",
            self.inner.vert_m,
            self.inner.time_s,
            self.inner.calculate_uci_category()
        )
    }
}

/// Python-exposed v2 climb (persistence-based).
#[cfg(feature = "python")]
#[pyclass(name = "ClimbV2")]
#[derive(Clone)]
pub struct PyClimbV2 {
    inner: ClimbV2,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyClimbV2 {
    #[getter]
    fn vert_m(&self) -> f64 {
        self.inner.vert_m
    }
    #[getter]
    fn time_s(&self) -> u32 {
        self.inner.time_s
    }
    #[getter]
    fn distance_m(&self) -> f64 {
        self.inner.distance_m
    }
    #[getter]
    fn avg_gradient_pct(&self) -> f64 {
        self.inner.avg_gradient_pct
    }
    #[getter]
    fn persistence(&self) -> f64 {
        self.inner.persistence
    }
    #[getter]
    fn is_essential(&self) -> bool {
        self.inner.is_essential
    }
    #[getter]
    fn birth_elev(&self) -> f64 {
        self.inner.birth_elev
    }
    #[getter]
    fn death_elev(&self) -> f64 {
        self.inner.death_elev
    }
    #[getter]
    fn avg_power_w(&self) -> Option<f64> {
        self.inner.avg_power_w
    }
    #[getter]
    fn avg_hr(&self) -> Option<u8> {
        self.inner.avg_hr
    }
    #[getter]
    fn tile_ids(&self) -> Vec<String> {
        self.inner.tile_ids.clone()
    }
    #[getter]
    fn effort_start_idx(&self) -> usize {
        self.inner.effort_start_idx
    }
    #[getter]
    fn effort_end_idx(&self) -> usize {
        self.inner.effort_end_idx
    }
    #[getter]
    fn birth_idx(&self) -> usize {
        self.inner.birth_idx
    }
    #[getter]
    fn death_idx(&self) -> usize {
        self.inner.death_idx
    }
    #[getter]
    fn start_lat(&self) -> Option<f64> {
        self.inner.start_lat
    }
    #[getter]
    fn start_lon(&self) -> Option<f64> {
        self.inner.start_lon
    }
    #[getter]
    fn end_lat(&self) -> Option<f64> {
        self.inner.end_lat
    }
    #[getter]
    fn end_lon(&self) -> Option<f64> {
        self.inner.end_lon
    }
    #[getter]
    fn onset_start_idx(&self) -> Option<usize> {
        self.inner.onset_start_idx
    }
    #[getter]
    fn onset_end_idx(&self) -> Option<usize> {
        self.inner.onset_end_idx
    }
    #[getter]
    fn signature_v1_hex(&self) -> Option<String> {
        self.inner.signature_v1_hex.clone()
    }
    #[getter]
    fn signature_v2_hex(&self) -> Option<String> {
        self.inner.signature_v2_hex.clone()
    }

    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        use pyo3::types::PyDict;
        let dict = PyDict::new(py);
        dict.set_item("vert_m", self.inner.vert_m)?;
        dict.set_item("time_s", self.inner.time_s)?;
        dict.set_item("distance_m", self.inner.distance_m)?;
        dict.set_item("avg_gradient_pct", self.inner.avg_gradient_pct)?;
        dict.set_item("persistence", self.inner.persistence)?;
        dict.set_item("is_essential", self.inner.is_essential)?;
        dict.set_item("birth_elev", self.inner.birth_elev)?;
        dict.set_item("death_elev", self.inner.death_elev)?;
        dict.set_item("avg_power_w", self.inner.avg_power_w)?;
        dict.set_item("avg_hr", self.inner.avg_hr)?;
        dict.set_item("tile_ids", self.inner.tile_ids.clone())?;
        dict.set_item("effort_start_idx", self.inner.effort_start_idx)?;
        dict.set_item("effort_end_idx", self.inner.effort_end_idx)?;
        dict.set_item("birth_idx", self.inner.birth_idx)?;
        dict.set_item("death_idx", self.inner.death_idx)?;
        dict.set_item("start_lat", self.inner.start_lat)?;
        dict.set_item("start_lon", self.inner.start_lon)?;
        dict.set_item("end_lat", self.inner.end_lat)?;
        dict.set_item("end_lon", self.inner.end_lon)?;
        dict.set_item("onset_start_idx", self.inner.onset_start_idx)?;
        dict.set_item("onset_end_idx", self.inner.onset_end_idx)?;
        dict.set_item("signature_v1_hex", self.inner.signature_v1_hex.clone())?;
        dict.set_item("signature_v2_hex", self.inner.signature_v2_hex.clone())?;
        Ok(dict.into())
    }

    fn __repr__(&self) -> String {
        format!(
            "ClimbV2(vert_m={:.0}, persistence={:.1}, time_s={}, essential={}, sig_v2={})",
            self.inner.vert_m,
            self.inner.persistence,
            self.inner.time_s,
            self.inner.is_essential,
            self.inner.signature_v2_hex.is_some()
        )
    }
}

/// Python-exposed v2 signature matching.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (hex_a, hex_b))]
fn match_signatures_v2(hex_a: &str, hex_b: &str) -> PyResult<PyObject> {
    use pyo3::types::PyDict;

    let sig_a = SignatureV2::from_hex(hex_a)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid v2 signature hex (a)"))?;
    let sig_b = SignatureV2::from_hex(hex_b)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid v2 signature hex (b)"))?;

    let result = sig_a.match_against(&sig_b);
    let distance = sig_a.dct_distance(&sig_b);

    Python::with_gil(|py| {
        let dict = PyDict::new(py);
        let (result_str, confidence) = match result {
            MatchResult::Match { confidence } => ("match", confidence),
            MatchResult::ProbableMatch { confidence } => ("probable_match", confidence),
            MatchResult::NoMatch => ("no_match", 0.0),
            MatchResult::Incompatible => ("incompatible", 0.0),
        };
        dict.set_item("result", result_str)?;
        dict.set_item("confidence", confidence)?;
        dict.set_item("dct_distance", distance)?;
        Ok(dict.into())
    })
}

/// Match two climbs using signature + start-point GPS proximity.
///
/// This compatibility function is for discovery and diagnostics. Reward-grade
/// vault assignment requires oriented start and end proximity and is enforced
/// by the backend's shared `match_reward_grade_v2` path.
///
/// Returns the same dict as `match_signatures_v2` plus `gps_distance_m`.
/// GPS gate: start points must be within `max_gps_m` (default 150m).
/// If GPS coordinates are not provided (0.0), the GPS gate is skipped.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (hex_a, hex_b, lat_a, lon_a, lat_b, lon_b, max_gps_m=150.0))]
fn match_climb_pair(
    hex_a: &str,
    hex_b: &str,
    lat_a: f64,
    lon_a: f64,
    lat_b: f64,
    lon_b: f64,
    max_gps_m: f64,
) -> PyResult<PyObject> {
    use pyo3::types::PyDict;

    let sig_a = SignatureV2::from_hex(hex_a)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid v2 signature hex (a)"))?;
    let sig_b = SignatureV2::from_hex(hex_b)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid v2 signature hex (b)"))?;

    // GPS proximity gate (if coordinates provided)
    let has_gps =
        lat_a.abs() > 0.001 && lon_a.abs() > 0.001 && lat_b.abs() > 0.001 && lon_b.abs() > 0.001;

    let gps_dist = if has_gps {
        haversine_m(lat_a, lon_a, lat_b, lon_b)
    } else {
        0.0
    };

    if has_gps && gps_dist > max_gps_m {
        return Python::with_gil(|py| {
            let dict = PyDict::new(py);
            dict.set_item("result", "no_match")?;
            dict.set_item("confidence", 0.0)?;
            dict.set_item("dct_distance", f64::MAX)?;
            dict.set_item("gps_distance_m", gps_dist)?;
            Ok(dict.into())
        });
    }

    // Signature matching (multi-gate pipeline)
    let result = sig_a.match_against(&sig_b);
    let distance = sig_a.dct_distance(&sig_b);

    Python::with_gil(|py| {
        let dict = PyDict::new(py);
        let (result_str, confidence) = match result {
            MatchResult::Match { confidence } => ("match", confidence),
            MatchResult::ProbableMatch { confidence } => ("probable_match", confidence),
            MatchResult::NoMatch => ("no_match", 0.0),
            MatchResult::Incompatible => ("incompatible", 0.0),
        };
        dict.set_item("result", result_str)?;
        dict.set_item("confidence", confidence)?;
        dict.set_item("dct_distance", distance)?;
        dict.set_item("gps_distance_m", gps_dist)?;
        Ok(dict.into())
    })
}

/// Largest finite cumulative distance in a track.
/// Crafted FIT files can carry NaN/Inf distance values; non-finite entries are ignored.
fn max_finite_distance(dist: &[f32]) -> Option<f32> {
    dist.iter()
        .copied()
        .filter(|d| d.is_finite())
        .max_by(f32::total_cmp)
}

/// Haversine distance in meters between two GPS points.
#[cfg_attr(not(feature = "python"), allow(dead_code))]
fn haversine_m(lat1: f64, lon1: f64, lat2: f64, lon2: f64) -> f64 {
    const R: f64 = 6_371_000.0;
    let phi1 = lat1.to_radians();
    let phi2 = lat2.to_radians();
    let dphi = (lat2 - lat1).to_radians();
    let dlam = (lon2 - lon1).to_radians();
    let a = (dphi / 2.0).sin().powi(2) + phi1.cos() * phi2.cos() * (dlam / 2.0).sin().powi(2);
    R * 2.0 * a.sqrt().atan2((1.0 - a).sqrt())
}

/// Find the best discovery match for a climb from a list of candidates.
///
/// Each candidate is a dict with keys: `signature_hex`, `lat`, `lon`.
/// This start-point-only compatibility helper cannot authorize economics.
/// Returns the best matching candidate dict (with `result`, `confidence`,
/// `dct_distance`, `gps_distance_m` added) or None if no match.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (signature_hex, lat, lon, candidates, max_gps_m=150.0))]
fn find_best_vault_match(
    signature_hex: &str,
    lat: f64,
    lon: f64,
    candidates: &Bound<'_, pyo3::types::PyList>,
    max_gps_m: f64,
) -> PyResult<PyObject> {
    use pyo3::types::PyDict;

    let sig = SignatureV2::from_hex(signature_hex)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Invalid signature hex"))?;

    let has_query_gps = lat.abs() > 0.001 && lon.abs() > 0.001;

    let mut best_result: Option<(String, f64, f64, f64, usize)> = None; // (result, conf, dct_d, gps_d, idx)

    for (idx, item) in candidates.iter().enumerate() {
        let dict = item
            .downcast::<pyo3::types::PyDict>()
            .map_err(|_| pyo3::exceptions::PyTypeError::new_err("Candidate must be a dict"))?;

        let cand_hex: String = dict
            .get_item("signature_hex")?
            .ok_or_else(|| pyo3::exceptions::PyKeyError::new_err("Missing signature_hex"))?
            .extract()?;

        let cand_sig = match SignatureV2::from_hex(&cand_hex) {
            Some(s) => s,
            None => continue,
        };

        // GPS gate
        let cand_lat: f64 = dict
            .get_item("lat")?
            .and_then(|v| v.extract().ok())
            .unwrap_or(0.0);
        let cand_lon: f64 = dict
            .get_item("lon")?
            .and_then(|v| v.extract().ok())
            .unwrap_or(0.0);

        let has_cand_gps = cand_lat.abs() > 0.001 && cand_lon.abs() > 0.001;
        let gps_dist = if has_query_gps && has_cand_gps {
            let d = haversine_m(lat, lon, cand_lat, cand_lon);
            if d > max_gps_m {
                continue;
            }
            d
        } else {
            0.0
        };

        // Signature matching
        let result = sig.match_against(&cand_sig);
        let dct_d = sig.dct_distance(&cand_sig);

        let (result_str, confidence) = match result {
            MatchResult::Match { confidence } => ("match", confidence),
            MatchResult::ProbableMatch { confidence } => ("probable_match", confidence),
            MatchResult::NoMatch | MatchResult::Incompatible => continue,
        };

        // Keep best by confidence (prefer definite match over probable)
        let is_better = match &best_result {
            None => true,
            Some((prev_result, prev_conf, _, _, _)) => {
                if result_str == "match" && prev_result == "probable_match" {
                    true
                } else if result_str == prev_result {
                    confidence > *prev_conf
                } else {
                    false
                }
            }
        };

        if is_better {
            best_result = Some((result_str.to_string(), confidence, dct_d, gps_dist, idx));
        }
    }

    Python::with_gil(|py| match best_result {
        None => Ok(py.None()),
        Some((result_str, confidence, dct_d, gps_d, idx)) => {
            let dict = PyDict::new(py);
            dict.set_item("result", result_str)?;
            dict.set_item("confidence", confidence)?;
            dict.set_item("dct_distance", dct_d)?;
            dict.set_item("gps_distance_m", gps_d)?;
            dict.set_item("candidate_index", idx)?;
            Ok(dict.into())
        }
    })
}

/// Detect climbs using v2 persistence algorithm.
///
/// Zero-parameter topological approach. Returns all climbs above the
/// sensor-derived 3m noise gate, sorted by effort start time.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (tile_samples, user_weight_kg=None))]
fn detect_climbs_persistence(
    py: Python<'_>,
    tile_samples: &Bound<'_, pyo3::types::PyList>,
    user_weight_kg: Option<f64>,
) -> PyResult<Vec<PyClimbV2>> {
    let samples: Vec<TileSample> = tile_samples
        .iter()
        .filter_map(|item| {
            let dict = item.downcast::<pyo3::types::PyDict>().ok()?;
            let t: i64 = dict.get_item("t").ok()??.extract().ok()?;
            let tile_id: Option<String> = dict
                .get_item("tile_id")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let elevation_m: Option<f64> = dict
                .get_item("elevation_m")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let power_w: Option<u16> = dict
                .get_item("power_w")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let hr_bpm: Option<u8> = dict
                .get_item("hr_bpm")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lat: Option<f64> = dict
                .get_item("lat")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lon: Option<f64> = dict
                .get_item("lon")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            Some(TileSample {
                t,
                tile_id,
                elevation_m,
                power_w,
                hr_bpm,
                lat,
                lon,
            })
        })
        .collect();

    let climbs = py.allow_threads(|| detect_climbs_v2(&samples, user_weight_kg));
    Ok(climbs.into_iter().map(|c| PyClimbV2 { inner: c }).collect())
}

/// Detect climb patterns from tile sample data (v1).
///
/// This is the main entry point for climb detection from Python.
///
/// # Arguments
/// * `tile_samples` - List of dicts with t, elevation_m, power_w, hr_bpm, lat, lon, tile_id
/// * `arena_tiles` - Optional set of H3 tile IDs to restrict detection
/// * `user_weight_kg` - Optional rider weight for W/kg calculation
/// * `algorithm` - "momentum" (default) or "legacy"
/// * `generate_signatures` - Whether to generate 64-byte signatures (default: true)
///
/// # Returns
/// List of ClimbPattern objects sorted by start time.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (tile_samples, arena_tiles=None, user_weight_kg=None, algorithm="momentum", generate_signatures=true))]
fn detect_climbs(
    py: Python<'_>,
    tile_samples: &Bound<'_, pyo3::types::PyList>,
    arena_tiles: Option<Vec<String>>,
    user_weight_kg: Option<f64>,
    algorithm: &str,
    generate_signatures: bool,
) -> PyResult<Vec<PyClimbPattern>> {
    // Parse tile samples from Python dicts
    let samples: Vec<TileSample> = tile_samples
        .iter()
        .filter_map(|item| {
            let dict = item.downcast::<pyo3::types::PyDict>().ok()?;

            let t: i64 = dict.get_item("t").ok()??.extract().ok()?;
            let tile_id: Option<String> = dict
                .get_item("tile_id")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let elevation_m: Option<f64> = dict
                .get_item("elevation_m")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let power_w: Option<u16> = dict
                .get_item("power_w")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let hr_bpm: Option<u8> = dict
                .get_item("hr_bpm")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lat: Option<f64> = dict
                .get_item("lat")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lon: Option<f64> = dict
                .get_item("lon")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());

            Some(TileSample {
                t,
                tile_id,
                elevation_m,
                power_w,
                hr_bpm,
                lat,
                lon,
            })
        })
        .collect();

    // Parse arena tiles
    let arena_set: Option<HashSet<String>> = arena_tiles.map(|v| v.into_iter().collect());

    // Parse algorithm
    let algo = match algorithm.to_lowercase().as_str() {
        "legacy" => DetectionAlgorithm::Legacy,
        _ => DetectionAlgorithm::Momentum,
    };

    // Build config
    let config = ClimbDetectorConfig {
        algorithm: algo,
        generate_signatures,
        ..Default::default()
    };

    // Run detection with GIL released
    let climbs = py.allow_threads(|| {
        let detector = ClimbPatternDetector::new(config);
        detector.detect_all(&samples, arena_set.as_ref(), user_weight_kg)
    });

    // Convert to Python objects
    Ok(climbs
        .into_iter()
        .map(|c| PyClimbPattern { inner: c })
        .collect())
}

// =============================================================================
// Terrain Classification PyO3 Bindings
// =============================================================================

/// Python-exposed terrain metrics.
#[cfg(feature = "python")]
#[pyclass(name = "TerrainMetrics")]
#[derive(Clone)]
pub struct PyTerrainMetrics {
    inner: TerrainMetrics,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyTerrainMetrics {
    /// Total elevation gain in meters.
    #[getter]
    fn total_gain_m(&self) -> f64 {
        self.inner.total_gain_m
    }

    /// Total elevation loss in meters.
    #[getter]
    fn total_loss_m(&self) -> f64 {
        self.inner.total_loss_m
    }

    /// Maximum elevation in meters.
    #[getter]
    fn max_elevation_m(&self) -> f64 {
        self.inner.max_elevation_m
    }

    /// Minimum elevation in meters.
    #[getter]
    fn min_elevation_m(&self) -> f64 {
        self.inner.min_elevation_m
    }

    /// Elevation range (max - min) in meters.
    #[getter]
    fn elevation_range_m(&self) -> f64 {
        self.inner.elevation_range_m
    }

    /// Maximum sustained gradient percentage.
    #[getter]
    fn max_sustained_gradient_pct(&self) -> f64 {
        self.inner.max_sustained_gradient_pct
    }

    /// Average climbing gradient percentage.
    #[getter]
    fn avg_climbing_gradient_pct(&self) -> f64 {
        self.inner.avg_climbing_gradient_pct
    }

    /// Gradient standard deviation.
    #[getter]
    fn gradient_std_dev(&self) -> f64 {
        self.inner.gradient_std_dev
    }

    /// Total distance in meters (if available).
    #[getter]
    fn total_distance_m(&self) -> Option<f64> {
        self.inner.total_distance_m
    }

    /// Duration in seconds.
    #[getter]
    fn duration_s(&self) -> u32 {
        self.inner.duration_s
    }

    /// Number of samples analyzed.
    #[getter]
    fn sample_count(&self) -> usize {
        self.inner.sample_count
    }

    /// Convert to Python dict.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        use pyo3::types::PyDict;
        let dict = PyDict::new(py);
        dict.set_item("total_gain_m", self.inner.total_gain_m)?;
        dict.set_item("total_loss_m", self.inner.total_loss_m)?;
        dict.set_item("max_elevation_m", self.inner.max_elevation_m)?;
        dict.set_item("min_elevation_m", self.inner.min_elevation_m)?;
        dict.set_item("elevation_range_m", self.inner.elevation_range_m)?;
        dict.set_item(
            "max_sustained_gradient_pct",
            self.inner.max_sustained_gradient_pct,
        )?;
        dict.set_item(
            "avg_climbing_gradient_pct",
            self.inner.avg_climbing_gradient_pct,
        )?;
        dict.set_item("gradient_std_dev", self.inner.gradient_std_dev)?;
        dict.set_item("total_distance_m", self.inner.total_distance_m)?;
        dict.set_item("duration_s", self.inner.duration_s)?;
        dict.set_item("sample_count", self.inner.sample_count)?;
        Ok(dict.into())
    }

    fn __repr__(&self) -> String {
        format!(
            "TerrainMetrics(gain={:.0}m, max_gradient={:.1}%)",
            self.inner.total_gain_m, self.inner.max_sustained_gradient_pct
        )
    }
}

/// Python-exposed terrain classification result.
#[cfg(feature = "python")]
#[pyclass(name = "TerrainClassification")]
#[derive(Clone)]
pub struct PyTerrainClassification {
    inner: TerrainClassification,
}

#[cfg(feature = "python")]
#[pymethods]
impl PyTerrainClassification {
    /// Terrain class as string: "flat", "rolling", "hilly", "mountainous".
    #[getter]
    fn class_name(&self) -> &'static str {
        self.inner.class.as_str()
    }

    /// Terrain class as integer (0=flat, 1=rolling, 2=hilly, 3=mountainous).
    #[getter]
    fn class_value(&self) -> u8 {
        self.inner.class as u8
    }

    /// Classification confidence (0.0 - 1.0).
    #[getter]
    fn confidence(&self) -> f64 {
        self.inner.confidence
    }

    /// Terrain metrics used for classification.
    #[getter]
    fn metrics(&self) -> PyTerrainMetrics {
        PyTerrainMetrics {
            inner: self.inner.metrics.clone(),
        }
    }

    /// Difficulty score (0.0 - 10.0+).
    #[getter]
    fn difficulty_score(&self) -> f64 {
        self.inner.metrics.difficulty_score()
    }

    /// Convert to Python dict.
    fn to_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        use pyo3::types::PyDict;
        let dict = PyDict::new(py);
        dict.set_item("class", self.inner.class.as_str())?;
        dict.set_item("class_value", self.inner.class as u8)?;
        dict.set_item("confidence", self.inner.confidence)?;
        dict.set_item("difficulty_score", self.inner.metrics.difficulty_score())?;
        dict.set_item("metrics", self.metrics().to_dict(py)?)?;
        Ok(dict.into())
    }

    fn __repr__(&self) -> String {
        format!(
            "TerrainClassification(class='{}', confidence={:.2}, difficulty={:.1})",
            self.inner.class.as_str(),
            self.inner.confidence,
            self.inner.metrics.difficulty_score()
        )
    }
}

/// Classify terrain from tile sample data.
///
/// Analyzes elevation profile to determine terrain type.
/// Returns terrain classification with recommended thresholds.
///
/// # Arguments
/// * `tile_samples` - List of dicts with t, elevation_m (lat, lon optional)
///
/// # Returns
/// TerrainClassification with class, confidence, and metrics.
/// Returns None if insufficient data.
#[cfg(feature = "python")]
#[pyfunction]
fn classify_terrain(
    py: Python<'_>,
    tile_samples: &Bound<'_, pyo3::types::PyList>,
) -> PyResult<Option<PyTerrainClassification>> {
    // Parse tile samples from Python dicts
    let samples: Vec<TileSample> = tile_samples
        .iter()
        .filter_map(|item| {
            let dict = item.downcast::<pyo3::types::PyDict>().ok()?;

            let t: i64 = dict.get_item("t").ok()??.extract().ok()?;
            let elevation_m: Option<f64> = dict
                .get_item("elevation_m")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lat: Option<f64> = dict
                .get_item("lat")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lon: Option<f64> = dict
                .get_item("lon")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());

            Some(TileSample {
                t,
                tile_id: None,
                elevation_m,
                power_w: None,
                hr_bpm: None,
                lat,
                lon,
            })
        })
        .collect();

    // Run classification with GIL released
    let result = py.allow_threads(|| {
        let classifier = TerrainClassifier::default();
        classifier.classify(&samples)
    });

    Ok(result.map(|c| PyTerrainClassification { inner: c }))
}

/// Detect climb patterns with terrain-adaptive thresholds.
///
/// This is an enhanced version that first classifies terrain, then uses
/// appropriate thresholds for climb detection.
///
/// # Arguments
/// * `tile_samples` - List of dicts with t, elevation_m, power_w, hr_bpm, lat, lon, tile_id
/// * `terrain` - Optional terrain type: "flat", "rolling", "hilly", "mountainous", or "auto"
/// * `arena_tiles` - Optional set of H3 tile IDs to restrict detection
/// * `user_weight_kg` - Optional rider weight for W/kg calculation
/// * `algorithm` - "momentum" (default) or "legacy"
/// * `generate_signatures` - Whether to generate 64-byte signatures (default: true)
///
/// # Returns
/// List of ClimbPattern objects sorted by start time.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (tile_samples, terrain="auto", config_overrides=None, arena_tiles=None, user_weight_kg=None, algorithm="momentum", generate_signatures=true))]
fn detect_climbs_adaptive(
    py: Python<'_>,
    tile_samples: &Bound<'_, pyo3::types::PyList>,
    terrain: &str,
    config_overrides: Option<&Bound<'_, pyo3::types::PyDict>>,
    arena_tiles: Option<Vec<String>>,
    user_weight_kg: Option<f64>,
    algorithm: &str,
    generate_signatures: bool,
) -> PyResult<Vec<PyClimbPattern>> {
    // Parse tile samples from Python dicts
    let samples: Vec<TileSample> = tile_samples
        .iter()
        .filter_map(|item| {
            let dict = item.downcast::<pyo3::types::PyDict>().ok()?;

            let t: i64 = dict.get_item("t").ok()??.extract().ok()?;
            let tile_id: Option<String> = dict
                .get_item("tile_id")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let elevation_m: Option<f64> = dict
                .get_item("elevation_m")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let power_w: Option<u16> = dict
                .get_item("power_w")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let hr_bpm: Option<u8> = dict
                .get_item("hr_bpm")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lat: Option<f64> = dict
                .get_item("lat")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());
            let lon: Option<f64> = dict
                .get_item("lon")
                .ok()
                .and_then(|v| v.map(|v| v.extract().ok()).flatten());

            Some(TileSample {
                t,
                tile_id,
                elevation_m,
                power_w,
                hr_bpm,
                lat,
                lon,
            })
        })
        .collect();

    // Parse arena tiles
    let arena_set: Option<HashSet<String>> = arena_tiles.map(|v| v.into_iter().collect());

    // Parse algorithm
    let algo = match algorithm.to_lowercase().as_str() {
        "legacy" => DetectionAlgorithm::Legacy,
        _ => DetectionAlgorithm::Momentum,
    };

    // Determine terrain class (check for named profiles first, then terrain types)
    let terrain_lower = terrain.to_lowercase();
    let mut config =
        if let Some(profile_config) = ClimbDetectorConfig::for_terrain_str(&terrain_lower) {
            // Direct profile match (flat, rolling, hilly, mountainous, urban_hills)
            profile_config
        } else if terrain_lower == "auto" {
            // Auto-detect terrain from ride data
            let classifier = TerrainClassifier::default();
            match classifier.classify(&samples).map(|c| c.class) {
                Some(tc) => ClimbDetectorConfig::for_terrain(tc),
                None => ClimbDetectorConfig::default(),
            }
        } else {
            // Unknown terrain string, use default
            ClimbDetectorConfig::default()
        };

    // Apply algorithm and signature settings
    config.algorithm = algo;
    config.generate_signatures = generate_signatures;

    // Apply config overrides from Python dict (protocol-level tuning)
    if let Some(overrides) = config_overrides {
        // Core thresholds
        if let Ok(Some(v)) = overrides.get_item("vert_min_m") {
            if let Ok(val) = v.extract::<f64>() {
                config.vert_min_m = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("drop_tolerance_m") {
            if let Ok(val) = v.extract::<f64>() {
                config.drop_tolerance_m = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("time_min_s") {
            if let Ok(val) = v.extract::<u32>() {
                config.time_min_s = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("time_max_s") {
            if let Ok(val) = v.extract::<u32>() {
                config.time_max_s = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("vam_min") {
            if let Ok(val) = v.extract::<f64>() {
                config.vam_min = val;
            }
        }

        // Gradient thresholds
        if let Ok(Some(v)) = overrides.get_item("gradient_min_pct") {
            if let Ok(val) = v.extract::<f64>() {
                config.gradient_min_pct = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("gradient_start_threshold") {
            if let Ok(val) = v.extract::<f64>() {
                config.gradient_start_threshold = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("gradient_end_threshold") {
            if let Ok(val) = v.extract::<f64>() {
                config.gradient_end_threshold = val;
            }
        }

        // Momentum model
        if let Ok(Some(v)) = overrides.get_item("momentum_start_threshold") {
            if let Ok(val) = v.extract::<f64>() {
                config.momentum_start_threshold = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("momentum_end_threshold") {
            if let Ok(val) = v.extract::<f64>() {
                config.momentum_end_threshold = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("momentum_climb_rate") {
            if let Ok(val) = v.extract::<f64>() {
                config.momentum_climb_rate = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("momentum_drain_rate") {
            if let Ok(val) = v.extract::<f64>() {
                config.momentum_drain_rate = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("momentum_decay_rate") {
            if let Ok(val) = v.extract::<f64>() {
                config.momentum_decay_rate = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("momentum_max") {
            if let Ok(val) = v.extract::<f64>() {
                config.momentum_max = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("momentum_gradient_neutral") {
            if let Ok(val) = v.extract::<f64>() {
                config.momentum_gradient_neutral = val;
            }
        }

        // Processing params
        if let Ok(Some(v)) = overrides.get_item("smoothing_window") {
            if let Ok(val) = v.extract::<usize>() {
                config.smoothing_window = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("gradient_window") {
            if let Ok(val) = v.extract::<usize>() {
                config.gradient_window = val;
            }
        }
        if let Ok(Some(v)) = overrides.get_item("max_trim_ratio") {
            if let Ok(val) = v.extract::<f64>() {
                config.max_trim_ratio = val;
            }
        }
    }

    // Run detection with GIL released
    let climbs = py.allow_threads(|| {
        let detector = ClimbPatternDetector::new(config);
        detector.detect_all(&samples, arena_set.as_ref(), user_weight_kg)
    });

    // Convert to Python objects
    Ok(climbs
        .into_iter()
        .map(|c| PyClimbPattern { inner: c })
        .collect())
}

// Custom exceptions
#[cfg(feature = "python")]
pyo3::create_exception!(workout_parse, ParseError, pyo3::exceptions::PyException);
#[cfg(feature = "python")]
pyo3::create_exception!(
    workout_parse,
    DecompressionLimitExceeded,
    pyo3::exceptions::PyException
);
#[cfg(feature = "python")]
pyo3::create_exception!(
    workout_parse,
    DurationLimitExceeded,
    pyo3::exceptions::PyException
);

/// Parse a workout file from a path.
/// Releases GIL during parsing for async compatibility.
#[cfg(feature = "python")]
#[pyfunction]
fn parse_file(py: Python<'_>, path: &str) -> PyResult<PyParsedActivity> {
    let result = py.allow_threads(|| {
        let data = std::fs::read(path).map_err(WpError::Io)?;
        parse_bytes(&data)
    });

    match result {
        Ok(activity) => Ok(PyParsedActivity { inner: activity }),
        Err(WpError::DecompressionLimitExceeded(msg)) => {
            Err(PyErr::new::<DecompressionLimitExceeded, _>(msg))
        }
        Err(WpError::DurationLimitExceeded(msg)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(msg))
        }
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

/// Parse a workout file from bytes.
/// Releases GIL during parsing for async compatibility.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "parse_bytes")]
fn py_parse_bytes(py: Python<'_>, data: &[u8]) -> PyResult<PyParsedActivity> {
    let result = py.allow_threads(|| parse_bytes(data));

    match result {
        Ok(activity) => Ok(PyParsedActivity { inner: activity }),
        Err(WpError::DecompressionLimitExceeded(msg)) => {
            Err(PyErr::new::<DecompressionLimitExceeded, _>(msg))
        }
        Err(WpError::DurationLimitExceeded(msg)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(msg))
        }
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

/// Parse a workout file from raw bytes with optional file type hint.
///
/// This is the preferred entry point for in-memory parsing (no disk I/O).
/// If file_type is "auto" or empty, file type is detected from magic bytes
/// (same as `parse_bytes`). Otherwise, file_type can be "fit", "gpx", or
/// "tcx" to force a specific parser, skipping magic-byte detection.
///
/// Handles compressed input (gzip/zip) automatically via decompress_safe.
/// Releases GIL during parsing for async compatibility.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (data, file_type="auto", parser_version=None))]
fn parse_file_bytes(
    py: Python<'_>,
    data: &[u8],
    file_type: &str,
    parser_version: Option<u32>,
) -> PyResult<PyParsedActivity> {
    let ft = file_type.to_lowercase();
    let parser_version = parser_version.unwrap_or(CURRENT_PARSER_VERSION);
    let result = py.allow_threads(|| parse_file_bytes_for_version(data, &ft, parser_version));

    match result {
        Ok(activity) => Ok(PyParsedActivity { inner: activity }),
        Err(WpError::DecompressionLimitExceeded(msg)) => {
            Err(PyErr::new::<DecompressionLimitExceeded, _>(msg))
        }
        Err(WpError::DurationLimitExceeded(msg)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(msg))
        }
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

/// Produce canonicalized ride bytes for replay protection and attestation identity.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (activity, parser_version=None))]
fn canonicalize_ride<'py>(
    py: Python<'py>,
    activity: &PyParsedActivity,
    parser_version: Option<u32>,
) -> PyResult<Bound<'py, PyBytes>> {
    let parser_version = parser_version.unwrap_or(CURRENT_PARSER_VERSION);
    let result = py.allow_threads(|| canonicalize(&activity.inner, parser_version));

    match result {
        Ok(bytes) => Ok(PyBytes::new_bound(py, &bytes)),
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

/// Compute the canonical ride hash as a lowercase hex string.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (activity, parser_version=None))]
fn hash_canonical_ride(
    py: Python<'_>,
    activity: &PyParsedActivity,
    parser_version: Option<u32>,
) -> PyResult<String> {
    let parser_version = parser_version.unwrap_or(CURRENT_PARSER_VERSION);
    let result = py.allow_threads(|| hash_canonical_ride_hex(&activity.inner, parser_version));

    match result {
        Ok(hash) => Ok(hash),
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

/// Recompute TSS from a frozen authoritative NP/duration pair and a sealed
/// Threshold without introducing a second backend formula.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "calculate_tss_from_power")]
fn py_calculate_tss_from_power(
    duration_s: u32,
    normalized_power_w: f32,
    ftp_w: u16,
) -> PyResult<f32> {
    if duration_s == 0
        || ftp_w == 0
        || !normalized_power_w.is_finite()
        || normalized_power_w <= 0.0
    {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "duration, normalized power, and Threshold must be positive",
        ));
    }
    Ok(calculate_tss(duration_s, normalized_power_w, ftp_w))
}

/// Compute authoritative activity metrics for one parsed ride.
///
/// Single reward-bearing metrics path shared by every language binding: the
/// PyO3 `compute_metrics` function and the Swift (UniFFI) bindings both
/// delegate here so NP/TSS/IF math can never fork per platform. The body is
/// the former `compute_metrics` closure, moved verbatim.
pub fn compute_activity_metrics(inner: &ParsedActivity, ftp: u16) -> WpResult<ComputedMetrics> {
        let mut metrics = if let Some(ref power_w) = inner.pwr_w {
            compute_power_metrics(&inner.time_ms, power_w)?
        } else {
            let mut empty = ComputedMetrics::default();
            empty.moving_time_s = continuous_moving_time_s(&inner.time_ms);
            empty
        };

        // Elapsed duration remains available for display. TSS uses
        // the NP-bearing recorded duration, excluding sample gaps >30 seconds.
        // Recorded zero watts stay in NP/TSS, including stationary recording.
        // See backend/app/services/ride_idle_evidence.py for cited duration semantics; its
        // evidence gate never edits these samples or this metrics-v1 formula.
        if inner.time_ms.len() >= 2 {
            let duration_ms = inner.time_ms.last().unwrap() - inner.time_ms.first().unwrap();
            metrics.duration_s = (duration_ms / 1000) as u32;
        }
        if let Some(normalized_power) = metrics.normalized_power_raw {
            metrics.intensity_factor = Some(calculate_if(normalized_power, ftp));
            metrics.tss = Some(calculate_tss(
                metrics.normalized_power_duration_s,
                normalized_power,
                ftp,
            ));
        }
        if let Some(avg) = metrics.avg_power_w {
            metrics.kcals = Some(calculate_kcals(avg, metrics.moving_time_s));
        }

        // HR metrics
        if let Some(ref hr) = inner.hr_bpm {
            let valid_hr: Vec<u8> = hr
                .iter()
                .take(inner.time_ms.len())
                .filter(|&&h| h != MISSING_U8 && h > 0)
                .copied()
                .collect();
            metrics.heart_rate_sample_count = valid_hr.len().min(u32::MAX as usize) as u32;
            metrics.heart_rate_sample_coverage_bps =
                sample_coverage_bps(valid_hr.len(), inner.time_ms.len());

            if !valid_hr.is_empty() {
                metrics.avg_hr_bpm = Some(
                    (valid_hr.iter().map(|&h| h as u32).sum::<u32>() as f64 / valid_hr.len() as f64)
                        .round() as u8,
                );
                metrics.max_hr_bpm = valid_hr.iter().max().copied();
            }
        }

        // Speed metrics
        if let Some(ref spd) = inner.speed_mps {
            let valid_speed: Vec<f32> = spd
                .iter()
                .filter(|&&s| s > 0.0 && s < 100.0) // sanity check
                .copied()
                .collect();

            if !valid_speed.is_empty() {
                metrics.avg_speed_mps =
                    Some(valid_speed.iter().sum::<f32>() / valid_speed.len() as f32);
                metrics.max_speed_mps = valid_speed.iter().cloned().reduce(f32::max);
            }
        }

        // Distance: prefer embedded dist_m, fall back to GPS haversine sum
        if let Some(ref dist) = inner.dist_m {
            if let Some(max_dist) = max_finite_distance(dist) {
                metrics.distance_m = max_dist;
            }
        }
        if metrics.distance_m == 0.0 {
            // Fallback: compute from GPS coordinates (needed for GPX files which
            // don't embed cumulative distance). Uses haversine with 500m per-step
            // cap to match climb detection distance calculations.
            if let (Some(ref lat), Some(ref lon)) = (&inner.lat_e7, &inner.lon_e7) {
                let mut total_dist = 0.0f64;
                for i in 1..lat.len().min(lon.len()) {
                    let lat1 = lat[i - 1] as f64 / 1e7;
                    let lon1 = lon[i - 1] as f64 / 1e7;
                    let lat2 = lat[i] as f64 / 1e7;
                    let lon2 = lon[i] as f64 / 1e7;
                    if lat1.abs() <= 90.0
                        && lon1.abs() <= 180.0
                        && lat2.abs() <= 90.0
                        && lon2.abs() <= 180.0
                        && !(lat1 == 0.0 && lon1 == 0.0)
                        && !(lat2 == 0.0 && lon2 == 0.0)
                    {
                        let dlat = (lat2 - lat1).to_radians();
                        let dlon = (lon2 - lon1).to_radians();
                        let a = (dlat / 2.0).sin().powi(2)
                            + lat1.to_radians().cos()
                                * lat2.to_radians().cos()
                                * (dlon / 2.0).sin().powi(2);
                        let d = 6_371_000.0 * 2.0 * a.sqrt().atan2((1.0 - a).sqrt());
                        total_dist += d.min(500.0);
                    }
                }
                if total_dist > 0.0 {
                    metrics.distance_m = total_dist as f32;
                }
            }
        }

        // Cadence
        if let Some(ref cad) = inner.cadence_rpm {
            let valid_cad: Vec<u8> = cad
                .iter()
                .filter(|&&c| c != MISSING_U8 && c > 0)
                .copied()
                .collect();

            if !valid_cad.is_empty() {
                metrics.avg_cadence_rpm = Some(
                    (valid_cad.iter().map(|&c| c as u32).sum::<u32>() as f64
                        / valid_cad.len() as f64)
                        .round() as u8,
                );
            }
        }

        // Elevation gain: smooth with SMA(21) before accumulating to match
        // Strava-like elevation processing (reduces barometric noise inflation).
        if let Some(ref elev) = inner.elevation_m {
            let valid: Vec<f64> = elev
                .iter()
                .map(|&e| e as f64)
                .filter(|&e| e > -500.0)
                .collect();
            if valid.len() >= 2 {
                let smoothed = crate::climb::utils::smooth_elevations(&valid, 21);
                let gain: f64 = smoothed.windows(2).map(|w| (w[1] - w[0]).max(0.0)).sum();
                metrics.elevation_gain_m = gain as f32;
            }
        }

        Ok(metrics)
}

/// Compute metrics using server-side FTP.
#[cfg(feature = "python")]
#[pyfunction]
fn compute_metrics(
    py: Python<'_>,
    activity: &PyParsedActivity,
    ftp: u16,
) -> PyResult<PyComputedMetrics> {
    let inner = &activity.inner;
    let result = py.allow_threads(|| compute_activity_metrics(inner, ftp));

    match result {
        Ok(metrics) => Ok(PyComputedMetrics { inner: metrics }),
        Err(WpError::DurationLimitExceeded(msg)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(msg))
        }
        Err(e) => Err(PyErr::new::<ParseError, _>(e.to_string())),
    }
}

#[cfg(feature = "python")]
#[pyfunction(name = "effort_spans_ms")]
fn py_effort_spans_ms(py: Python<'_>, activity: &PyParsedActivity) -> Vec<(i64, i64)> {
    let inner = &activity.inner;
    py.allow_threads(|| metrics::effort_spans_ms(&inner.time_ms))
}

#[cfg(feature = "python")]
#[pyfunction]
fn compute_metrics_in_spans(
    py: Python<'_>,
    activity: &PyParsedActivity,
    ftp: u16,
    keep_ms: Vec<(i64, i64)>,
) -> PyResult<(PyComputedMetrics, Vec<(i64, i64)>)> {
    let inner = &activity.inner;
    let result = py.allow_threads(|| {
        let missing = vec![MISSING_U16; inner.time_ms.len()];
        let (mut metrics, spans) = metrics::compute_power_metrics_in_spans(
            &inner.time_ms,
            inner.pwr_w.as_ref().unwrap_or(&missing),
            &keep_ms,
        )?;
        if let Some(np) = metrics.normalized_power_raw {
            metrics.tss = Some(calculate_tss(metrics.normalized_power_duration_s, np, ftp));
            metrics.intensity_factor = Some(calculate_if(np, ftp));
        }
        Ok((metrics, spans))
    });
    match result {
        Ok((metrics, spans)) => Ok((PyComputedMetrics { inner: metrics }, spans)),
        Err(WpError::DurationLimitExceeded(message)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(message))
        }
        Err(error) => Err(PyErr::new::<ParseError, _>(error.to_string())),
    }
}

#[cfg(feature = "python")]
#[pyfunction]
fn compute_segment_power_metrics_in_spans(
    py: Python<'_>,
    time_ms: Vec<i64>,
    power_w: Vec<Option<u16>>,
    keep_ms: Vec<(i64, i64)>,
) -> PyResult<PyComputedMetrics> {
    let encoded_power: Vec<u16> = power_w
        .into_iter()
        .map(|power| power.unwrap_or(MISSING_U16))
        .collect();
    let result = py.allow_threads(|| {
        metrics::compute_power_metrics_in_spans(&time_ms, &encoded_power, &keep_ms)
    });
    match result {
        Ok((metrics, _)) => Ok(PyComputedMetrics { inner: metrics }),
        Err(WpError::DurationLimitExceeded(message)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(message))
        }
        Err(error) => Err(PyErr::new::<ParseError, _>(error.to_string())),
    }
}

/// Compute canonical pause-aware power metrics for one climb window.
#[cfg(feature = "python")]
#[pyfunction]
fn compute_segment_power_metrics(
    py: Python<'_>,
    time_ms: Vec<i64>,
    power_w: Vec<Option<u16>>,
) -> PyResult<PyComputedMetrics> {
    let encoded_power: Vec<u16> = power_w
        .into_iter()
        .map(|power| power.unwrap_or(MISSING_U16))
        .collect();
    let result = py.allow_threads(|| compute_power_metrics(&time_ms, &encoded_power));

    match result {
        Ok(metrics) => Ok(PyComputedMetrics { inner: metrics }),
        Err(WpError::DurationLimitExceeded(message)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(message))
        }
        Err(error) => Err(PyErr::new::<ParseError, _>(error.to_string())),
    }
}

/// Compute canonical pause-aware 3/7/15-minute mean-max power anchors.
/// Mean-maximal power at each duration from raw arrays (ms timestamps,
/// watts). Same arithmetic as the Threshold anchors; feeds the power curve.
#[cfg(feature = "python")]
#[pyfunction(name = "compute_mean_max_power_series")]
fn py_compute_mean_max_power_series(
    py: Python<'_>,
    time_ms: Vec<i64>,
    power_w: Vec<u16>,
    durations_s: Vec<usize>,
) -> PyResult<Vec<Option<f64>>> {
    py.allow_threads(|| metrics::compute_mean_max_power(&time_ms, &power_w, &durations_s))
        .map_err(|error| pyo3::exceptions::PyValueError::new_err(error.to_string()))
}

#[cfg(feature = "python")]
#[pyfunction(name = "compute_threshold_power_anchors")]
fn py_compute_threshold_power_anchors(
    py: Python<'_>,
    activity: &PyParsedActivity,
) -> PyResult<PyObject> {
    use pyo3::types::PyDict;

    let anchors = match activity.inner.pwr_w.as_ref() {
        Some(power_w) => py.allow_threads(|| {
            compute_threshold_power_anchors(&activity.inner.time_ms, power_w)
        }),
        None => Ok([None, None, None]),
    };

    match anchors {
        Ok(values) => {
            let result = PyDict::new_bound(py);
            for (duration_s, value) in [180, 420, 900].into_iter().zip(values) {
                result.set_item(duration_s.to_string(), value)?;
            }
            Ok(result.into_py(py))
        }
        Err(WpError::DurationLimitExceeded(message)) => {
            Err(PyErr::new::<DurationLimitExceeded, _>(message))
        }
        Err(error) => Err(PyErr::new::<ParseError, _>(error.to_string())),
    }
}

/// Project GPS coordinates to H3 cells at a given resolution.
///
/// Args:
///     lat_e7: Latitudes in e7 format (degrees * 10^7)
///     lon_e7: Longitudes in e7 format (degrees * 10^7)
///     resolution: H3 resolution (0-15, default 10 for ~50m hexagons)
///
/// Returns:
///     List of unique H3Cell objects
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (lat_e7, lon_e7, resolution=10))]
fn get_h3_cells(
    py: Python<'_>,
    lat_e7: PyReadonlyArray1<i32>,
    lon_e7: PyReadonlyArray1<i32>,
    resolution: u8,
) -> PyResult<Vec<PyH3Cell>> {
    let lat_slice = lat_e7.as_slice()?;
    let lon_slice = lon_e7.as_slice()?;

    let res = match resolution {
        0 => Resolution::Zero,
        1 => Resolution::One,
        2 => Resolution::Two,
        3 => Resolution::Three,
        4 => Resolution::Four,
        5 => Resolution::Five,
        6 => Resolution::Six,
        7 => Resolution::Seven,
        8 => Resolution::Eight,
        9 => Resolution::Nine,
        10 => Resolution::Ten,
        11 => Resolution::Eleven,
        12 => Resolution::Twelve,
        13 => Resolution::Thirteen,
        14 => Resolution::Fourteen,
        15 => Resolution::Fifteen,
        _ => {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "Resolution must be 0-15",
            ))
        }
    };

    let cells = py.allow_threads(|| {
        let raw_cells = project_to_h3(lat_slice, lon_slice, res);
        unique_cells(&raw_cells)
    });

    Ok(cells.into_iter().map(|c| PyH3Cell { inner: c }).collect())
}

/// Get H3 cell indexes as strings (for database storage).
///
/// Args:
///     lat_e7: Latitudes in e7 format (degrees * 10^7)
///     lon_e7: Longitudes in e7 format (degrees * 10^7)
///     resolution: H3 resolution (0-15, default 10)
///
/// Returns:
///     List of unique H3 index strings (e.g., ["8a2a1072b59ffff", ...])
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (lat_e7, lon_e7, resolution=10))]
fn get_h3_strings(
    py: Python<'_>,
    lat_e7: PyReadonlyArray1<i32>,
    lon_e7: PyReadonlyArray1<i32>,
    resolution: u8,
) -> PyResult<Vec<String>> {
    let lat_slice = lat_e7.as_slice()?;
    let lon_slice = lon_e7.as_slice()?;

    let res = match resolution {
        0 => Resolution::Zero,
        1 => Resolution::One,
        2 => Resolution::Two,
        3 => Resolution::Three,
        4 => Resolution::Four,
        5 => Resolution::Five,
        6 => Resolution::Six,
        7 => Resolution::Seven,
        8 => Resolution::Eight,
        9 => Resolution::Nine,
        10 => Resolution::Ten,
        11 => Resolution::Eleven,
        12 => Resolution::Twelve,
        13 => Resolution::Thirteen,
        14 => Resolution::Fourteen,
        15 => Resolution::Fifteen,
        _ => {
            return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
                "Resolution must be 0-15",
            ))
        }
    };

    let strings = py.allow_threads(|| {
        let raw_cells = project_to_h3(lat_slice, lon_slice, res);
        let unique = unique_cells(&raw_cells);
        cells_to_strings(&unique)
    });

    Ok(strings)
}

/// DEPRECATED: Use get_h3_cells instead.
/// Kept for backwards compatibility - returns H3 cells disguised as Tiles.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (lat_e7, lon_e7, _zoom=10))]
fn get_tiles(
    py: Python<'_>,
    lat_e7: PyReadonlyArray1<i32>,
    lon_e7: PyReadonlyArray1<i32>,
    _zoom: u8,
) -> PyResult<Vec<PyTile>> {
    let lat_slice = lat_e7.as_slice()?;
    let lon_slice = lon_e7.as_slice()?;

    let cells = py.allow_threads(|| {
        let raw_cells = project_to_cells(lat_slice, lon_slice);
        unique_cells(&raw_cells)
    });

    Ok(cells.into_iter().map(|c| PyTile { inner: c }).collect())
}

/// Compute raw persistence pairs from an elevation array.
///
/// Returns ALL pairs (including sub-noise-gate ones), with each pair tagged
/// as above or below the noise gate. This is used by the admin elevation
/// profile visualisation to show which topological features survived filtering.
///
/// # Arguments
/// * `elevations` - Raw elevation values (f64 array)
/// * `noise_gate` - Noise gate threshold in meters (typically 3.0)
///
/// # Returns
/// List of dicts, each with: birth_idx, death_idx, birth_elev, death_elev,
/// persistence, above_noise_gate (bool).  Sorted by persistence descending.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (elevations, noise_gate=3.0))]
fn compute_persistence_pairs(
    py: Python<'_>,
    elevations: Vec<f64>,
    noise_gate: f64,
) -> PyResult<Vec<PyObject>> {
    use climb::persistence::compute_persistence;
    use pyo3::types::PyDict;

    // Get ALL pairs (noise_gate = 0.0) so nothing is filtered out
    let all_pairs = py.allow_threads(|| compute_persistence(&elevations, 0.0));

    let results: Vec<PyObject> = all_pairs
        .iter()
        .map(|pair| {
            let dict = PyDict::new(py);
            dict.set_item("birth_idx", pair.birth_idx).unwrap();
            dict.set_item("death_idx", pair.death_idx).unwrap();
            dict.set_item("birth_elev", pair.birth_elev).unwrap();
            dict.set_item("death_elev", pair.death_elev).unwrap();
            dict.set_item("persistence", pair.persistence).unwrap();
            dict.set_item("above_noise_gate", pair.persistence >= noise_gate)
                .unwrap();
            dict.into()
        })
        .collect();

    Ok(results)
}

/// Python module definition.
#[cfg(feature = "python")]
#[pymodule]
fn workout_parse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(training::py_compute_training_metrics, m)?)?;
    m.add_function(wrap_pyfunction!(training::training_timeline, m)?)?;
    m.add_class::<training::TrainingMetrics>()?;
    m.add("TRAINING_ENGINE_VERSION", training::TRAINING_ENGINE_VERSION)?;
    // Core functions
    m.add_function(wrap_pyfunction!(parse_file, m)?)?;
    m.add_function(wrap_pyfunction!(py_parse_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(parse_file_bytes, m)?)?;
    m.add_function(wrap_pyfunction!(canonicalize_ride, m)?)?;
    m.add_function(wrap_pyfunction!(hash_canonical_ride, m)?)?;
    m.add_function(wrap_pyfunction!(compute_metrics, m)?)?;
    m.add_function(wrap_pyfunction!(py_effort_spans_ms, m)?)?;
    m.add_function(wrap_pyfunction!(compute_metrics_in_spans, m)?)?;
    m.add_function(wrap_pyfunction!(compute_segment_power_metrics_in_spans, m)?)?;
    m.add_function(wrap_pyfunction!(py_calculate_tss_from_power, m)?)?;
    m.add_function(wrap_pyfunction!(compute_segment_power_metrics, m)?)?;
    m.add_function(wrap_pyfunction!(py_compute_threshold_power_anchors, m)?)?;
    m.add_function(wrap_pyfunction!(py_compute_mean_max_power_series, m)?)?;

    // H3 tile functions (new)
    m.add_function(wrap_pyfunction!(get_h3_cells, m)?)?;
    m.add_function(wrap_pyfunction!(get_h3_strings, m)?)?;

    // Legacy tile function (deprecated, for backwards compat)
    m.add_function(wrap_pyfunction!(get_tiles, m)?)?;

    // Climb detection
    m.add_function(wrap_pyfunction!(detect_climbs, m)?)?;
    m.add_function(wrap_pyfunction!(detect_climbs_adaptive, m)?)?;
    m.add_function(wrap_pyfunction!(detect_climbs_persistence, m)?)?;
    m.add_function(wrap_pyfunction!(match_signatures_v2, m)?)?;
    m.add_function(wrap_pyfunction!(match_climb_pair, m)?)?;
    m.add_function(wrap_pyfunction!(find_best_vault_match, m)?)?;
    m.add_function(wrap_pyfunction!(compute_persistence_pairs, m)?)?;

    // Terrain classification
    m.add_function(wrap_pyfunction!(classify_terrain, m)?)?;

    // Polyline encoding/decoding
    m.add_function(wrap_pyfunction!(py_encode_polyline, m)?)?;
    m.add_function(wrap_pyfunction!(py_decode_polyline, m)?)?;
    m.add_function(wrap_pyfunction!(py_encode_gps_track, m)?)?;
    m.add_function(wrap_pyfunction!(py_decode_gps_track, m)?)?;

    // Classes
    m.add_class::<PyParsedActivity>()?;
    m.add_class::<PyComputedMetrics>()?;
    m.add_class::<PyH3Cell>()?;
    m.add_class::<PyClimbPattern>()?;
    m.add_class::<PyClimbV2>()?;
    m.add_class::<PyTerrainMetrics>()?;
    m.add_class::<PyTerrainClassification>()?;

    // Legacy class (deprecated, for backwards compat)
    m.add_class::<PyTile>()?;

    // Exceptions
    m.add("ParseError", m.py().get_type::<ParseError>())?;
    m.add(
        "DecompressionLimitExceeded",
        m.py().get_type::<DecompressionLimitExceeded>(),
    )?;
    m.add(
        "DurationLimitExceeded",
        m.py().get_type::<DurationLimitExceeded>(),
    )?;

    // Constants
    m.add("CURRENT_PARSER_VERSION", CURRENT_PARSER_VERSION)?;
    m.add("PARSER_VERSION_V1", PARSER_VERSION_V1)?;
    m.add("PARSER_VERSION_V2", PARSER_VERSION_V2)?;
    m.add("PARSER_VERSION_V3", PARSER_VERSION_V3)?;
    m.add("PARSER_VERSION_V4", PARSER_VERSION_V4)?;
    m.add("PARSER_VERSION_V5", PARSER_VERSION_V5)?;
    m.add("METRICS_VERSION", METRICS_VERSION)?;
    m.add("MISSING_U8", MISSING_U8)?;
    m.add("MISSING_U16", MISSING_U16)?;
    m.add("MISSING_I32", MISSING_I32)?;
    m.add("MISSING_I64", MISSING_I64)?;

    // H3 default resolution constant
    m.add("DEFAULT_H3_RESOLUTION", 10u8)?;

    Ok(())
}

#[cfg(test)]
mod parser_input_tests {
    use super::*;
    use proptest::prelude::*;
    use std::panic::{catch_unwind, AssertUnwindSafe};

    const GPX_WITH_NAMESPACED_SENSORS: &[u8] = br#"<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"
  xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
  xmlns:br="https://boulderroller.xyz/xmlschemas/ride/v1">
  <trk><trkseg>
    <trkpt lat="39.9500" lon="-75.1600">
      <time>2026-07-13T12:00:00Z</time>
      <extensions><gpxtpx:TrackPointExtension><gpxtpx:hr>151</gpxtpx:hr><gpxtpx:cad>87</gpxtpx:cad></gpxtpx:TrackPointExtension><br:power>304</br:power></extensions>
    </trkpt>
    <trkpt lat="39.9501" lon="-75.1601"><ele>12.5</ele><time>2026-07-13T12:00:01Z</time></trkpt>
  </trkseg></trk>
</gpx>"#;

    const TCX_WITH_XML_DECLARATION: &[u8] = br#"<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
  xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2">
  <Activities><Activity Sport="Biking"><Lap StartTime="2026-07-13T12:00:00Z"><Track>
    <Trackpoint><Time>2026-07-13T12:00:00Z</Time><Position><LatitudeDegrees>39.95</LatitudeDegrees><LongitudeDegrees>-75.16</LongitudeDegrees></Position><HeartRateBpm><Value>149</Value></HeartRateBpm><Cadence>86</Cadence><Extensions><ns3:TPX><ns3:Watts>287</ns3:Watts></ns3:TPX></Extensions></Trackpoint>
    <Trackpoint><Time>2026-07-13T12:00:01Z</Time><Position><LatitudeDegrees>39.9501</LatitudeDegrees><LongitudeDegrees>-75.1601</LongitudeDegrees></Position><AltitudeMeters>13.25</AltitudeMeters></Trackpoint>
  </Track></Lap></Activity></Activities>
</TrainingCenterDatabase>"#;

    const FIT_FIXTURE: &[u8] = include_bytes!("../../docs/t_h_e_w_a_l_l.fit");
    const CROSS_FORMAT_GPX: &[u8] =
        include_bytes!("../tests/fixtures/canonical_cross_format_ride.gpx");
    const CROSS_FORMAT_TCX: &[u8] =
        include_bytes!("../tests/fixtures/canonical_cross_format_ride.tcx");
    const CROSS_FORMAT_FIT_BASE64: &str =
        include_str!("../../tests/fixtures/mobile_sensor_ride_fit_v1.base64");
    const CROSS_FORMAT_VECTORS: &str =
        include_str!("../../tests/fixtures/canonical_cross_format_v2_vectors.json");

    fn gpx_with_times(first: &str, second: &str) -> Vec<u8> {
        format!(
            r#"<gpx><trk><trkseg><trkpt lat="39.95" lon="-75.16"><time>{first}</time></trkpt><trkpt lat="39.96" lon="-75.17"><time>{second}</time></trkpt></trkseg></trk></gpx>"#
        )
        .into_bytes()
    }

    #[test]
    fn max_finite_distance_ignores_non_finite_values() {
        assert_eq!(
            max_finite_distance(&[1.0, f32::NAN, 3.5, f32::INFINITY, 2.0]),
            Some(3.5)
        );
        assert_eq!(max_finite_distance(&[f32::NAN, f32::NEG_INFINITY]), None);
        assert_eq!(max_finite_distance(&[]), None);
    }

    #[test]
    fn gpx_preserves_missing_elevation_and_namespaced_sensors() {
        let activity = parse_bytes(GPX_WITH_NAMESPACED_SENSORS).unwrap();

        let elevation = activity.elevation_m.unwrap();
        assert!(elevation[0].is_nan());
        assert_eq!(elevation[1], 12.5);
        assert_eq!(activity.hr_bpm.unwrap()[0], 151);
        assert_eq!(activity.cadence_rpm.unwrap()[0], 87);
        assert_eq!(activity.pwr_w.unwrap()[0], 304);
    }

    #[test]
    fn self_closing_gpx_element_does_not_leak_parse_state() {
        let data = br#"<gpx><trk><trkseg><trkpt lat="39.95" lon="-75.16"><ele/><time>2026-07-13T12:00:00Z</time></trkpt></trkseg></trk></gpx>"#;
        let activity = parse_bytes(data).unwrap();

        assert_eq!(activity.time_ms.len(), 1);
        assert!(activity.elevation_m.is_none());
    }

    #[test]
    fn v1_raw_replay_keeps_legacy_xml_namespace_and_missing_elevation_semantics() {
        let v1 =
            parse_file_bytes_for_version(GPX_WITH_NAMESPACED_SENSORS, "gpx", PARSER_VERSION_V1)
                .unwrap();
        let v2 = parse_file_bytes_for_version(
            GPX_WITH_NAMESPACED_SENSORS,
            "gpx",
            CURRENT_PARSER_VERSION,
        )
        .unwrap();

        assert_eq!(v1.elevation_m.as_ref().unwrap()[0], 0.0);
        assert!(v1.hr_bpm.is_none());
        assert!(v1.cadence_rpm.is_none());
        assert!(v1.pwr_w.is_none());
        assert!(v2.elevation_m.as_ref().unwrap()[0].is_nan());
        assert_eq!(v2.hr_bpm.as_ref().unwrap()[0], 151);
        assert_eq!(v2.cadence_rpm.as_ref().unwrap()[0], 87);
        assert_eq!(v2.pwr_w.as_ref().unwrap()[0], 304);
    }

    #[test]
    fn v1_raw_replay_keeps_legacy_tcx_namespace_and_missing_elevation_semantics() {
        let v1 = parse_file_bytes_for_version(TCX_WITH_XML_DECLARATION, "tcx", PARSER_VERSION_V1)
            .unwrap();
        let v2 =
            parse_file_bytes_for_version(TCX_WITH_XML_DECLARATION, "tcx", CURRENT_PARSER_VERSION)
                .unwrap();

        assert_eq!(v1.elevation_m.as_ref().unwrap()[0], 0.0);
        assert_eq!(v1.hr_bpm.as_ref().unwrap()[0], 149);
        assert_eq!(v1.cadence_rpm.as_ref().unwrap()[0], 86);
        assert!(v1.pwr_w.is_none());
        assert!(v2.elevation_m.as_ref().unwrap()[0].is_nan());
        assert_eq!(v2.pwr_w.as_ref().unwrap()[0], 287);
    }

    #[test]
    fn v1_raw_replay_retains_self_closing_element_state_leak() {
        let data = br#"<gpx><trk><trkseg><trkpt lat="39.95" lon="-75.16"><ele/><time>2026-07-13T12:00:00Z</time></trkpt></trkseg></trk></gpx>"#;

        let v1 = parse_file_bytes_for_version(data, "gpx", PARSER_VERSION_V1);
        let v2 = parse_file_bytes_for_version(data, "gpx", PARSER_VERSION_V2).unwrap();

        assert!(matches!(v1, Err(WpError::InvalidGpx(_))));
        assert_eq!(v2.time_ms.len(), 1);
    }

    #[test]
    fn v1_raw_replay_retains_tcx_start_only_self_closing_behavior() {
        let data = br#"<TrainingCenterDatabase><Activities><Activity><Lap><Track><Trackpoint><Time>2026-07-13T12:00:00Z</Time><DistanceMeters/><Value>12</Value></Trackpoint></Track></Lap></Activity></Activities></TrainingCenterDatabase>"#;

        let v1 = parse_file_bytes_for_version(data, "tcx", PARSER_VERSION_V1).unwrap();
        let v2 = parse_file_bytes_for_version(data, "tcx", PARSER_VERSION_V2).unwrap();

        assert_eq!(v1.dist_m.as_ref().unwrap()[0], 0.0);
        assert_eq!(v2.dist_m.as_ref().unwrap()[0], 0.0);
    }

    #[test]
    fn v1_auto_detection_uses_historical_prefix_order() {
        let v1_tcx = parse_bytes_for_version(TCX_WITH_XML_DECLARATION, PARSER_VERSION_V1);
        let v2_tcx = parse_bytes_for_version(TCX_WITH_XML_DECLARATION, PARSER_VERSION_V2).unwrap();
        let v1_dot_fit = parse_bytes_for_version(b".not-a-fit", PARSER_VERSION_V1);
        let v2_dot_fit = parse_bytes_for_version(b".not-a-fit", PARSER_VERSION_V2);

        assert!(matches!(v1_tcx, Err(WpError::InvalidGpx(_))));
        assert_eq!(v2_tcx.time_ms.len(), 2);
        assert!(matches!(v1_dot_fit, Err(WpError::InvalidFit(_))));
        assert!(matches!(v2_dot_fit, Err(WpError::UnsupportedFileType(_))));
    }

    #[test]
    fn cross_format_v2_golden_vectors_preserve_the_same_ride_observations() {
        use base64::Engine;

        let vectors: serde_json::Value = serde_json::from_str(CROSS_FORMAT_VECTORS).unwrap();
        let fit_bytes = base64::engine::general_purpose::STANDARD
            .decode(CROSS_FORMAT_FIT_BASE64.trim())
            .unwrap();
        let parsed = [
            (
                "fit",
                parse_file_bytes_for_version(&fit_bytes, "fit", PARSER_VERSION_V2).unwrap(),
            ),
            (
                "gpx",
                parse_file_bytes_for_version(CROSS_FORMAT_GPX, "gpx", PARSER_VERSION_V2).unwrap(),
            ),
            (
                "tcx",
                parse_file_bytes_for_version(CROSS_FORMAT_TCX, "tcx", PARSER_VERSION_V2).unwrap(),
            ),
        ];

        for (file_type, activity) in &parsed {
            let expected = &vectors["vectors"][file_type];
            let canonical =
                String::from_utf8(canonicalize(activity, PARSER_VERSION_V2).unwrap()).unwrap();
            assert_eq!(canonical, expected["canonical_json"].as_str().unwrap());
            assert_eq!(
                hash_canonical_ride_hex(activity, PARSER_VERSION_V2).unwrap(),
                expected["ride_hash"].as_str().unwrap()
            );
        }

        let fit_canonical: serde_json::Value = serde_json::from_str(
            vectors["vectors"]["fit"]["canonical_json"]
                .as_str()
                .unwrap(),
        )
        .unwrap();
        for file_type in ["gpx", "tcx"] {
            let xml_canonical: serde_json::Value = serde_json::from_str(
                vectors["vectors"][file_type]["canonical_json"]
                    .as_str()
                    .unwrap(),
            )
            .unwrap();
            for (fit_sample, xml_sample) in fit_canonical["samples"]
                .as_array()
                .unwrap()
                .iter()
                .zip(xml_canonical["samples"].as_array().unwrap())
            {
                for field in [
                    "cadence_rpm",
                    "elev_dm",
                    "hr_bpm",
                    "lat_e6",
                    "lon_e6",
                    "power_w",
                    "sec_offset",
                ] {
                    assert_eq!(fit_sample[field], xml_sample[field], "{file_type} {field}");
                }
            }
        }
    }

    #[test]
    fn unknown_version_fails_closed_for_auto_and_explicit_file_type() {
        for file_type in ["auto", "gpx", "tcx", "fit"] {
            let error = parse_file_bytes_for_version(GPX_WITH_NAMESPACED_SENSORS, file_type, 999)
                .unwrap_err();
            assert!(error.to_string().contains("unsupported parser_version"));
        }
    }

    #[test]
    fn xml_declaration_detects_tcx_and_preserves_extensions() {
        let activity = parse_bytes(TCX_WITH_XML_DECLARATION).unwrap();

        let elevation = activity.elevation_m.unwrap();
        assert!(elevation[0].is_nan());
        assert_eq!(elevation[1], 13.25);
        assert_eq!(activity.hr_bpm.unwrap()[0], 149);
        assert_eq!(activity.cadence_rpm.unwrap()[0], 86);
        assert_eq!(activity.pwr_w.unwrap()[0], 287);
    }

    #[test]
    fn out_of_order_xml_timestamps_are_rejected() {
        let data = gpx_with_times("2026-07-13T12:00:01Z", "2026-07-13T12:00:00Z");
        let error = parse_bytes(&data).unwrap_err();

        assert!(error.to_string().contains("out of order"));
    }

    #[test]
    fn extreme_xml_timestamp_span_is_rejected() {
        let data = gpx_with_times("2026-07-13T12:00:00Z", "2026-07-15T12:00:01Z");
        let error = parse_bytes(&data).unwrap_err();

        assert!(matches!(error, WpError::DurationLimitExceeded(_)));
    }

    #[test]
    fn equal_timestamps_share_one_bounded_canonical_bucket() {
        let data = gpx_with_times("2026-07-13T12:00:00Z", "2026-07-13T12:00:00Z");
        let activity = parse_bytes(&data).unwrap();
        let canonical = canonicalize(&activity, CURRENT_PARSER_VERSION).unwrap();
        let canonical: serde_json::Value = serde_json::from_slice(&canonical).unwrap();

        assert_eq!(activity.total_elapsed_s, 0);
        assert_eq!(canonical["samples"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn truncated_known_inputs_never_panic() {
        for fixture in [
            GPX_WITH_NAMESPACED_SENSORS,
            TCX_WITH_XML_DECLARATION,
            FIT_FIXTURE,
        ] {
            let step = (fixture.len() / 128).max(1);
            for end in (0..fixture.len()).step_by(step) {
                let outcome = catch_unwind(AssertUnwindSafe(|| parse_bytes(&fixture[..end])));
                assert!(
                    outcome.is_ok(),
                    "parser panicked at truncation offset {end}"
                );
            }
            let final_truncation = &fixture[..fixture.len().saturating_sub(1)];
            assert!(catch_unwind(AssertUnwindSafe(|| parse_bytes(final_truncation))).is_ok());
        }
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(64))]

        #[test]
        fn malformed_fit_gpx_and_tcx_never_panic(
            suffix in proptest::collection::vec(any::<u8>(), 0..1024)
        ) {
            let prefixes: [&[u8]; 3] = [
                b"<?xml version=\"1.0\"?><gpx><trk><trkseg><trkpt",
                b"<?xml version=\"1.0\"?><TrainingCenterDatabase><Activities>",
                b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT",
            ];

            for prefix in prefixes {
                let mut input = prefix.to_vec();
                input.extend_from_slice(&suffix);
                let outcome = catch_unwind(AssertUnwindSafe(|| parse_bytes(&input)));
                prop_assert!(outcome.is_ok());
            }
        }
    }
}

#[cfg(test)]
mod evidence_tests {
    use super::*;

    fn base_activity() -> ParsedActivity {
        ParsedActivity {
            time_ms: vec![0, 60_000, 120_000, 180_000, 240_000],
            started_at_ms: 0,
            total_elapsed_s: 240,
            ..ParsedActivity::default()
        }
    }

    #[test]
    fn event_moving_time_subtracts_recorded_pauses() {
        let mut activity = base_activity();
        // One explicit 60 s pause mid-ride.
        activity.timer_pauses = vec![(60_000, 120_000)];
        assert_eq!(activity.event_moving_time_s(), Some(180));
    }

    #[test]
    fn event_moving_time_clamps_pauses_to_recorded_ground() {
        let mut activity = base_activity();
        // Pause span claims time beyond the last sample: only the recorded
        // overlap counts.
        activity.timer_pauses = vec![(180_000, 900_000)];
        assert_eq!(activity.event_moving_time_s(), Some(180));
    }

    #[test]
    fn no_timer_events_means_no_event_claim() {
        let activity = base_activity();
        assert_eq!(activity.event_moving_time_s(), None);
    }

    #[test]
    fn new_evidence_fields_never_touch_the_canonical_hash() {
        let mut bare = base_activity();
        bare.lat_e7 = Some(vec![1, 2, 3, 4, 5]);
        bare.lon_e7 = Some(vec![1, 2, 3, 4, 5]);
        let mut loaded = bare.clone();
        loaded.timer_pauses = vec![(0, 60_000)];
        loaded.temperature_c = Some(vec![21.0; 5]);
        loaded.devices = vec![DeviceProvenance {
            manufacturer: Some("garmin".into()),
            ..DeviceProvenance::default()
        }];
        loaded.device_summary = Some(DeviceSummary {
            total_timer_time_s: Some(180.0),
            ..DeviceSummary::default()
        });
        loaded.laps = vec![LapSummary {
            total_distance_m: Some(1000.0),
            ..LapSummary::default()
        }];
        loaded.gps_accuracy_m = Some(vec![4.0; 5]);
        loaded.lr_balance_raw = Some(vec![0x80 | 52; 5]);
        let bare_hash = canonicalize::hash_canonical_ride(&bare, 5).unwrap();
        let loaded_hash = canonicalize::hash_canonical_ride(&loaded, 5).unwrap();
        assert_eq!(bare_hash, loaded_hash);
    }
}
