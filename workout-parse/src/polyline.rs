//! Polyline encoding/decoding for GPS tracks.
//!
//! Uses the standard polyline algorithm (same as Google Maps) for lat/lon compression,
//! with a companion format for elevation and timestamps.
//!
//! GPS Track Format (stored as JSONB in rides.gps_track):
//! {
//!     "polyline": str,          // Encoded lat/lon pairs
//!     "elevations": [int, ...], // Delta-encoded elevation in decimeters
//!     "timestamps": [int, ...], // Delta-encoded seconds from start
//!     "distances": [int, ...],  // Delta-encoded distance in meters
//!     "elevation_missing_ranges": [[start, count], ...], // Optional v2 mask
//!     "precision": int,         // Polyline precision (default 5 = ~1m accuracy)
//!     "version": int            // Format version for future compatibility
//! }
//!
//! Compression ratios:
//! - Raw JSON: ~50 bytes/point → 900KB for 18,000 points
//! - Polyline: ~3 bytes/point → 54KB for 18,000 points (94% smaller)

#[cfg(feature = "python")]
use chrono::DateTime;
#[cfg(feature = "python")]
use pyo3::prelude::*;
#[cfg(feature = "python")]
use pyo3::types::{PyDict, PyList};

/// Encode a single number using polyline algorithm.
fn encode_number(num: i32) -> String {
    // Left-shift the number by 1, invert if negative
    let mut sgn_num = num << 1;
    if num < 0 {
        sgn_num = !sgn_num;
    }

    // Break into 5-bit chunks
    let mut encoded = String::new();
    while sgn_num >= 0x20 {
        let chunk = (0x20 | (sgn_num & 0x1f)) + 63;
        encoded.push(chunk as u8 as char);
        sgn_num >>= 5;
    }
    encoded.push((sgn_num + 63) as u8 as char);

    encoded
}

/// Decode a single number from polyline string, returning (value, new_index).
fn decode_number(encoded: &str, mut index: usize) -> (i32, usize) {
    let bytes: Vec<char> = encoded.chars().collect();
    let mut result = 0i32;
    let mut shift = 0;

    loop {
        let b = bytes[index] as i32 - 63;
        index += 1;
        result |= (b & 0x1f) << shift;
        shift += 5;
        if b < 0x20 {
            break;
        }
    }

    // Invert if odd
    let final_result = if result & 1 != 0 {
        !(result >> 1)
    } else {
        result >> 1
    };

    (final_result, index)
}

/// Encode a list of (lat, lon) points to a polyline string.
///
/// # Arguments
/// * `points` - List of (latitude, longitude) tuples
/// * `precision` - Number of decimal places (default 5 = ~1m accuracy)
///
/// # Returns
/// Encoded polyline string
pub fn encode_polyline(points: &[(f64, f64)], precision: u8) -> String {
    if points.is_empty() {
        return String::new();
    }

    let factor = 10_i32.pow(precision as u32);
    let mut encoded = String::new();
    let mut prev_lat = 0i32;
    let mut prev_lon = 0i32;

    for &(lat, lon) in points {
        let curr_lat = (lat * factor as f64).round() as i32;
        let curr_lon = (lon * factor as f64).round() as i32;

        encoded.push_str(&encode_number(curr_lat - prev_lat));
        encoded.push_str(&encode_number(curr_lon - prev_lon));

        prev_lat = curr_lat;
        prev_lon = curr_lon;
    }

    encoded
}

/// Decode a polyline string to a list of (lat, lon) points.
///
/// # Arguments
/// * `encoded` - Polyline string
/// * `precision` - Precision used during encoding (default 5)
///
/// # Returns
/// List of (latitude, longitude) tuples
pub fn decode_polyline(encoded: &str, precision: u8) -> Vec<(f64, f64)> {
    if encoded.is_empty() {
        return Vec::new();
    }

    let factor = 10_f64.powi(precision as i32);
    let mut points = Vec::new();
    let mut index = 0;
    let mut lat = 0i32;
    let mut lon = 0i32;

    while index < encoded.len() {
        let (lat_delta, new_index) = decode_number(encoded, index);
        let (lon_delta, new_index) = decode_number(encoded, new_index);

        lat += lat_delta;
        lon += lon_delta;
        index = new_index;

        points.push((lat as f64 / factor, lon as f64 / factor));
    }

    points
}

/// Delta-encode an array of integers for compact storage.
pub fn encode_delta_array(values: &[i32]) -> Vec<i32> {
    if values.is_empty() {
        return Vec::new();
    }

    let mut result = Vec::with_capacity(values.len());
    result.push(values[0]);

    for i in 1..values.len() {
        result.push(values[i] - values[i - 1]);
    }

    result
}

/// Decode a delta-encoded array back to absolute values.
pub fn decode_delta_array(deltas: &[i32]) -> Vec<i32> {
    if deltas.is_empty() {
        return Vec::new();
    }

    let mut result = Vec::with_capacity(deltas.len());
    result.push(deltas[0]);

    for i in 1..deltas.len() {
        result.push(result[i - 1] + deltas[i]);
    }

    result
}

/// GPS point structure for encoding/decoding.
#[derive(Debug, Clone)]
pub struct GpsPoint {
    pub sequence_num: Option<usize>,
    pub latitude: f64,
    pub longitude: f64,
    pub elevation_m: Option<f64>,
    pub timestamp: Option<i32>, // seconds from start
    pub distance_m: Option<f64>,
}

/// Compact GPS track format.
#[derive(Debug, Clone)]
pub struct GpsTrack {
    pub polyline: String,
    pub elevations: Vec<i32>,
    pub timestamps: Vec<i32>,
    pub distances: Vec<i32>,
    pub elevation_missing_ranges: Vec<(usize, usize)>,
    pub precision: u8,
    pub version: u8,
}

fn is_missing_elevation(elevation_m: Option<f64>) -> bool {
    !matches!(elevation_m, Some(elevation) if elevation.is_finite())
}

fn missing_elevation_ranges(points: &[GpsPoint]) -> Vec<(usize, usize)> {
    let mut ranges = Vec::new();
    let mut current_start: Option<usize> = None;

    for (idx, point) in points.iter().enumerate() {
        if is_missing_elevation(point.elevation_m) {
            if current_start.is_none() {
                current_start = Some(idx);
            }
        } else if let Some(start) = current_start.take() {
            ranges.push((start, idx - start));
        }
    }

    if let Some(start) = current_start {
        ranges.push((start, points.len() - start));
    }

    ranges
}

fn elevation_missing_at(ranges: &[(usize, usize)], idx: usize) -> bool {
    ranges
        .iter()
        .any(|(start, count)| idx >= *start && idx < start.saturating_add(*count))
}

/// Encode a full GPS track to compact format.
///
/// # Arguments
/// * `points` - List of GPS points
/// * `precision` - Polyline precision (default 5)
///
/// # Returns
/// Compact track ready for JSONB storage
pub fn encode_gps_track(points: &[GpsPoint], precision: u8) -> GpsTrack {
    if points.is_empty() {
        return GpsTrack {
            polyline: String::new(),
            elevations: Vec::new(),
            timestamps: Vec::new(),
            distances: Vec::new(),
            elevation_missing_ranges: Vec::new(),
            precision,
            version: 2,
        };
    }

    // Sort by sequence_num if available
    let mut sorted_points = points.to_vec();
    if points.iter().any(|p| p.sequence_num.is_some()) {
        sorted_points.sort_by_key(|p| p.sequence_num.unwrap_or(0));
    }

    // Extract coordinates
    let coords: Vec<(f64, f64)> = sorted_points
        .iter()
        .map(|p| (p.latitude, p.longitude))
        .collect();
    let polyline = encode_polyline(&coords, precision);

    // Extract elevations (convert to decimeters for integer storage)
    let elevations: Vec<i32> = sorted_points
        .iter()
        .map(|p| {
            p.elevation_m
                .filter(|e| e.is_finite())
                .map(|e| (e * 10.0).round() as i32)
                .unwrap_or(0)
        })
        .collect();
    let elevation_missing_ranges = missing_elevation_ranges(&sorted_points);

    // Extract timestamps
    let timestamps: Vec<i32> = sorted_points
        .iter()
        .enumerate()
        .map(|(i, p)| p.timestamp.unwrap_or(i as i32))
        .collect();

    // Extract distances (meters as integers)
    let distances: Vec<i32> = sorted_points
        .iter()
        .map(|p| p.distance_m.map(|d| d.round() as i32).unwrap_or(0))
        .collect();

    GpsTrack {
        polyline,
        elevations: encode_delta_array(&elevations),
        timestamps: encode_delta_array(&timestamps),
        distances: encode_delta_array(&distances),
        elevation_missing_ranges,
        precision,
        version: 2,
    }
}

/// Decode a compact GPS track back to full points.
///
/// # Arguments
/// * `track` - Compact track from encode_gps_track
///
/// # Returns
/// List of GPS points
pub fn decode_gps_track(track: &GpsTrack) -> Vec<GpsPoint> {
    if track.polyline.is_empty() {
        return Vec::new();
    }

    let coords = decode_polyline(&track.polyline, track.precision);
    let elevations = decode_delta_array(&track.elevations);
    let timestamps = decode_delta_array(&track.timestamps);
    let distances = decode_delta_array(&track.distances);

    let mut points = Vec::with_capacity(coords.len());

    for (i, (lat, lon)) in coords.iter().enumerate() {
        let elev_dm = elevations.get(i).copied();
        let elev_m = if elevation_missing_at(&track.elevation_missing_ranges, i) {
            None
        } else {
            elev_dm.map(|dm| dm as f64 / 10.0)
        };
        let dist_m = distances.get(i).map(|&d| d as f64);

        points.push(GpsPoint {
            sequence_num: Some(i),
            latitude: *lat,
            longitude: *lon,
            elevation_m: elev_m,
            timestamp: timestamps.get(i).copied(),
            distance_m: dist_m,
        });
    }

    points
}

// =============================================================================
// PyO3 Bindings
// =============================================================================

/// Python-exposed encode_polyline function.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (points, precision=5))]
pub fn py_encode_polyline(points: Vec<(f64, f64)>, precision: u8) -> String {
    encode_polyline(&points, precision)
}

/// Python-exposed decode_polyline function.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (encoded, precision=5))]
pub fn py_decode_polyline(encoded: &str, precision: u8) -> Vec<(f64, f64)> {
    decode_polyline(encoded, precision)
}

/// Python-exposed encode_gps_track function.
///
/// Args:
///     points: List of GPS point dicts with keys:
///         - latitude: float
///         - longitude: float
///         - elevation_m: Optional[float]
///         - timestamp: Optional[int]  (seconds from start)
///         - distance_m: Optional[float]
///         - sequence_num: Optional[int]
///     precision: Polyline precision (default 5)
///
/// Returns:
///     Compact track dict ready for JSONB storage
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(signature = (points, precision=5))]
pub fn py_encode_gps_track(
    py: Python<'_>,
    points: &Bound<'_, PyList>,
    precision: u8,
) -> PyResult<PyObject> {
    // Parse points from Python dicts
    // Track start_time for ISO string timestamp conversion
    let mut start_time: Option<DateTime<chrono::FixedOffset>> = None;
    let mut parsed_points: Vec<GpsPoint> = Vec::with_capacity(points.len());

    for (idx, item) in points.iter().enumerate() {
        let dict = match item.downcast::<PyDict>() {
            Ok(d) => d,
            Err(_) => continue,
        };

        // Required fields
        let latitude: f64 = match dict.get_item("latitude") {
            Ok(Some(v)) => match v.extract() {
                Ok(val) => val,
                Err(_) => continue,
            },
            _ => continue,
        };
        let longitude: f64 = match dict.get_item("longitude") {
            Ok(Some(v)) => match v.extract() {
                Ok(val) => val,
                Err(_) => continue,
            },
            _ => continue,
        };

        // Optional fields
        let elevation_m: Option<f64> = dict
            .get_item("elevation_m")
            .ok()
            .and_then(|v| v.and_then(|v| v.extract().ok()));

        // Timestamp: try int first, then ISO string
        let timestamp: Option<i32> = if let Ok(Some(ts_val)) = dict.get_item("timestamp") {
            // Try extracting as i32 directly
            if let Ok(ts_int) = ts_val.extract::<i32>() {
                Some(ts_int)
            } else if let Ok(ts_i64) = ts_val.extract::<i64>() {
                // Handle i64 timestamps (sometimes Python sends these)
                Some(ts_i64 as i32)
            } else if let Ok(ts_str) = ts_val.extract::<&str>() {
                // Parse ISO 8601 string
                // Try RFC3339 first (2024-01-15T10:30:00+00:00)
                let parsed = DateTime::parse_from_rfc3339(ts_str)
                    .or_else(|_| {
                        // Try common ISO formats without timezone
                        DateTime::parse_from_str(
                            &format!("{}+00:00", ts_str.replace('Z', "")),
                            "%Y-%m-%dT%H:%M:%S%.f%:z",
                        )
                    })
                    .or_else(|_| {
                        // Try with Z suffix
                        DateTime::parse_from_str(ts_str, "%Y-%m-%dT%H:%M:%SZ")
                            .map(|dt| dt.with_timezone(&chrono::FixedOffset::east_opt(0).unwrap()))
                    });

                if let Ok(dt) = parsed {
                    if start_time.is_none() {
                        start_time = Some(dt);
                    }
                    let secs = (dt - start_time.unwrap()).num_seconds() as i32;
                    Some(secs)
                } else {
                    // Fallback to index if parsing fails
                    Some(idx as i32)
                }
            } else {
                // Fallback to index
                Some(idx as i32)
            }
        } else {
            Some(idx as i32)
        };

        let distance_m: Option<f64> = dict
            .get_item("distance_m")
            .ok()
            .and_then(|v| v.and_then(|v| v.extract().ok()));

        let sequence_num: Option<usize> = dict
            .get_item("sequence_num")
            .ok()
            .and_then(|v| v.and_then(|v| v.extract().ok()));

        parsed_points.push(GpsPoint {
            sequence_num,
            latitude,
            longitude,
            elevation_m,
            timestamp,
            distance_m,
        });
    }

    // Encode track
    let track = encode_gps_track(&parsed_points, precision);

    // Convert to Python dict
    let result = PyDict::new(py);
    result.set_item("polyline", track.polyline)?;
    result.set_item("elevations", track.elevations)?;
    result.set_item("timestamps", track.timestamps)?;
    result.set_item("distances", track.distances)?;
    if !track.elevation_missing_ranges.is_empty() {
        result.set_item(
            "elevation_missing_ranges",
            track.elevation_missing_ranges.clone(),
        )?;
    }
    result.set_item("precision", track.precision)?;
    result.set_item("version", track.version)?;

    Ok(result.into())
}

/// Python-exposed decode_gps_track function.
///
/// Args:
///     track: Compact track dict from encode_gps_track
///
/// Returns:
///     List of GPS point dicts
#[cfg(feature = "python")]
#[pyfunction]
pub fn py_decode_gps_track(py: Python<'_>, track: &Bound<'_, PyDict>) -> PyResult<Vec<PyObject>> {
    // Parse track from Python dict
    let polyline: String = track.get_item("polyline")?.unwrap().extract()?;
    let elevations: Vec<i32> = track
        .get_item("elevations")?
        .map(|v| v.extract())
        .unwrap_or_else(|| Ok(Vec::new()))?;
    let timestamps: Vec<i32> = track
        .get_item("timestamps")?
        .map(|v| v.extract())
        .unwrap_or_else(|| Ok(Vec::new()))?;
    let distances: Vec<i32> = track
        .get_item("distances")?
        .map(|v| v.extract())
        .unwrap_or_else(|| Ok(Vec::new()))?;
    let elevation_missing_ranges: Vec<(usize, usize)> = track
        .get_item("elevation_missing_ranges")?
        .map(|v| v.extract())
        .unwrap_or_else(|| Ok(Vec::new()))?;
    let precision: u8 = track
        .get_item("precision")?
        .map(|v| v.extract())
        .unwrap_or(Ok(5))?;

    let gps_track = GpsTrack {
        polyline,
        elevations,
        timestamps,
        distances,
        elevation_missing_ranges,
        precision,
        version: 2,
    };

    // Decode track
    let points = decode_gps_track(&gps_track);

    // Convert to Python dicts
    let mut result = Vec::new();
    for point in points {
        let dict = PyDict::new(py);
        dict.set_item("sequence_num", point.sequence_num)?;
        dict.set_item("latitude", point.latitude)?;
        dict.set_item("longitude", point.longitude)?;
        dict.set_item("elevation_m", point.elevation_m)?;
        dict.set_item("timestamp", point.timestamp)?;
        dict.set_item("distance_m", point.distance_m)?;
        result.push(dict.into());
    }

    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_encode_decode_number() {
        let test_cases = vec![
            0, 1, -1, 100, -100, 1000, -1000, 32767, -32768, 100000, -100000,
        ];

        for num in test_cases {
            let encoded = encode_number(num);
            let (decoded, _) = decode_number(&encoded, 0);
            assert_eq!(num, decoded, "Failed for {}", num);
        }
    }

    #[test]
    fn test_encode_decode_polyline() {
        let points = vec![(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)];

        let encoded = encode_polyline(&points, 5);
        let decoded = decode_polyline(&encoded, 5);

        assert_eq!(points.len(), decoded.len());
        for (i, ((orig_lat, orig_lon), (dec_lat, dec_lon))) in
            points.iter().zip(decoded.iter()).enumerate()
        {
            assert!(
                (orig_lat - dec_lat).abs() < 0.00001,
                "Latitude mismatch at {}",
                i
            );
            assert!(
                (orig_lon - dec_lon).abs() < 0.00001,
                "Longitude mismatch at {}",
                i
            );
        }
    }

    #[test]
    fn test_empty_polyline() {
        let points: Vec<(f64, f64)> = vec![];
        let encoded = encode_polyline(&points, 5);
        assert_eq!(encoded, "");

        let decoded = decode_polyline("", 5);
        assert_eq!(decoded.len(), 0);
    }

    #[test]
    fn test_delta_encoding() {
        let values = vec![100, 105, 103, 110, 108];
        let deltas = encode_delta_array(&values);
        let decoded = decode_delta_array(&deltas);

        assert_eq!(values, decoded);
        assert_eq!(deltas, vec![100, 5, -2, 7, -2]);
    }

    #[test]
    fn test_gps_track_encoding() {
        let points = vec![
            GpsPoint {
                sequence_num: Some(0),
                latitude: 37.7749,
                longitude: -122.4194,
                elevation_m: Some(10.5),
                timestamp: Some(0),
                distance_m: Some(0.0),
            },
            GpsPoint {
                sequence_num: Some(1),
                latitude: 37.7750,
                longitude: -122.4195,
                elevation_m: Some(11.2),
                timestamp: Some(1),
                distance_m: Some(15.3),
            },
        ];

        let track = encode_gps_track(&points, 5);
        let decoded = decode_gps_track(&track);

        assert_eq!(points.len(), decoded.len());
        assert_eq!(track.version, 2);
        assert_eq!(track.precision, 5);

        // Check first point
        assert!((points[0].latitude - decoded[0].latitude).abs() < 0.00001);
        assert!((points[0].longitude - decoded[0].longitude).abs() < 0.00001);
        assert!((points[0].elevation_m.unwrap() - decoded[0].elevation_m.unwrap()).abs() < 0.1);
    }

    #[test]
    fn test_gps_track_encoding_preserves_missing_elevation_and_sea_level() {
        let points = vec![
            GpsPoint {
                sequence_num: Some(0),
                latitude: 37.7749,
                longitude: -122.4194,
                elevation_m: None,
                timestamp: Some(0),
                distance_m: Some(0.0),
            },
            GpsPoint {
                sequence_num: Some(1),
                latitude: 37.7750,
                longitude: -122.4195,
                elevation_m: Some(0.0),
                timestamp: Some(1),
                distance_m: Some(15.3),
            },
            GpsPoint {
                sequence_num: Some(2),
                latitude: 37.7751,
                longitude: -122.4196,
                elevation_m: Some(12.3),
                timestamp: Some(2),
                distance_m: Some(30.1),
            },
        ];

        let track = encode_gps_track(&points, 5);
        let decoded = decode_gps_track(&track);

        assert_eq!(track.elevation_missing_ranges, vec![(0, 1)]);
        assert_eq!(decoded[0].elevation_m, None);
        assert_eq!(decoded[1].elevation_m, Some(0.0));
        assert!((decoded[2].elevation_m.unwrap() - 12.3).abs() < 0.1);
    }
}
