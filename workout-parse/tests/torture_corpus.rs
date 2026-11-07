use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::path::{Path, PathBuf};
use workout_parse::canonicalize::CURRENT_PARSER_VERSION;
use workout_parse::constants::{MISSING_I32, MISSING_U16, MISSING_U8};
use workout_parse::{parse_bytes, parse_file_bytes_for_version, ParsedActivity};

fn corpus_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join("torture")
}

fn manifest() -> Value {
    let bytes = fs::read(corpus_dir().join("manifest.json")).expect("read torture manifest");
    serde_json::from_slice(&bytes).expect("parse torture manifest")
}

fn case(case_id: &str) -> Value {
    manifest()["cases"]
        .as_array()
        .expect("manifest cases")
        .iter()
        .find(|case| case["id"] == case_id)
        .unwrap_or_else(|| panic!("missing torture case {case_id}"))
        .clone()
}

fn assert_optional_i32(actual: Option<&Vec<i32>>, expected: &Value) {
    if expected.is_null() {
        assert!(actual.is_none());
        return;
    }
    let actual = actual.expect("expected i32 stream");
    let expected = expected.as_array().expect("expected i32 array");
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        let normalized = if *actual == MISSING_I32 {
            None
        } else {
            Some(i64::from(*actual))
        };
        assert_eq!(normalized, expected.as_i64());
    }
}

fn assert_optional_u16(actual: Option<&Vec<u16>>, expected: &Value) {
    if expected.is_null() {
        assert!(actual.is_none());
        return;
    }
    let actual = actual.expect("expected u16 stream");
    let expected = expected.as_array().expect("expected u16 array");
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        let normalized = if *actual == MISSING_U16 {
            None
        } else {
            Some(u64::from(*actual))
        };
        assert_eq!(normalized, expected.as_u64());
    }
}

fn assert_optional_u8(actual: Option<&Vec<u8>>, expected: &Value) {
    if expected.is_null() {
        assert!(actual.is_none());
        return;
    }
    let actual = actual.expect("expected u8 stream");
    let expected = expected.as_array().expect("expected u8 array");
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        let normalized = if *actual == MISSING_U8 {
            None
        } else {
            Some(u64::from(*actual))
        };
        assert_eq!(normalized, expected.as_u64());
    }
}

fn assert_optional_f32(actual: Option<&Vec<f32>>, expected: &Value) {
    if expected.is_null() {
        assert!(actual.is_none());
        return;
    }
    let actual = actual.expect("expected f32 stream");
    let expected = expected.as_array().expect("expected f32 array");
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        if expected.is_null() {
            assert!(actual.is_nan(), "missing float must remain NaN");
        } else {
            let expected = expected.as_f64().expect("expected finite float") as f32;
            assert!((actual - expected).abs() <= f32::EPSILON);
        }
    }
}

fn assert_shape(activity: &ParsedActivity) {
    let n = activity.time_ms.len();
    for (name, len) in [
        ("lat_e7", activity.lat_e7.as_ref().map(Vec::len)),
        ("lon_e7", activity.lon_e7.as_ref().map(Vec::len)),
        ("elevation_m", activity.elevation_m.as_ref().map(Vec::len)),
        ("pwr_w", activity.pwr_w.as_ref().map(Vec::len)),
        ("hr_bpm", activity.hr_bpm.as_ref().map(Vec::len)),
        ("cadence_rpm", activity.cadence_rpm.as_ref().map(Vec::len)),
        ("speed_mps", activity.speed_mps.as_ref().map(Vec::len)),
        ("dist_m", activity.dist_m.as_ref().map(Vec::len)),
    ] {
        if let Some(len) = len {
            assert_eq!(len, n, "{name} must align one-to-one with timestamps");
        }
    }
}

fn assert_accepted(activity: &ParsedActivity, expected: &Value) {
    assert_shape(activity);
    if let Some(value) = expected.get("sample_count") {
        assert_eq!(activity.time_ms.len() as u64, value.as_u64().unwrap());
    }
    if let Some(value) = expected.get("duration_s") {
        assert_eq!(u64::from(activity.total_elapsed_s), value.as_u64().unwrap());
    }
    if let Some(value) = expected.get("started_at_ms") {
        assert_eq!(activity.started_at_ms, value.as_i64().unwrap());
    }
    if let Some(value) = expected.get("lat_e7") {
        assert_optional_i32(activity.lat_e7.as_ref(), value);
    }
    if let Some(value) = expected.get("elevation_m") {
        assert_optional_f32(activity.elevation_m.as_ref(), value);
    }
    if let Some(value) = expected.get("pwr_w") {
        assert_optional_u16(activity.pwr_w.as_ref(), value);
    }
    if let Some(value) = expected.get("hr_bpm") {
        assert_optional_u8(activity.hr_bpm.as_ref(), value);
    }
    if let Some(value) = expected.get("cadence_rpm") {
        assert_optional_u8(activity.cadence_rpm.as_ref(), value);
    }
}

fn assert_case(case_id: &str) {
    let case = case(case_id);
    let path = corpus_dir().join(case["file"].as_str().unwrap());
    let data = fs::read(&path).unwrap_or_else(|error| panic!("read {}: {error}", path.display()));
    let digest = hex::encode(Sha256::digest(&data));
    assert_eq!(digest, case["sha256"].as_str().unwrap());
    assert_eq!(data.len() as u64, case["byte_length"].as_u64().unwrap());

    let file_type = case["file_type"].as_str().unwrap();
    let explicit = catch_unwind(AssertUnwindSafe(|| {
        parse_file_bytes_for_version(&data, file_type, CURRENT_PARSER_VERSION)
    }));
    assert!(explicit.is_ok(), "{case_id} panicked on explicit dispatch");
    let automatic = catch_unwind(AssertUnwindSafe(|| parse_bytes(&data)));
    assert!(automatic.is_ok(), "{case_id} panicked on automatic dispatch");

    match case["outcome"].as_str().unwrap() {
        "reject" => {
            assert!(explicit.unwrap().is_err(), "{case_id} must reject explicitly");
            assert!(automatic.unwrap().is_err(), "{case_id} must reject automatically");
        }
        "accept" => {
            let explicit = explicit
                .unwrap()
                .unwrap_or_else(|error| panic!("{case_id} explicit parse failed: {error}"));
            let automatic = automatic
                .unwrap()
                .unwrap_or_else(|error| panic!("{case_id} auto parse failed: {error}"));
            assert_accepted(&explicit, &case["expected"]);
            assert_accepted(&automatic, &case["expected"]);
        }
        outcome => panic!("unsupported torture outcome {outcome}"),
    }
}

macro_rules! corpus_case_tests {
    ($($name:ident => $case_id:literal),+ $(,)?) => {
        $(
            #[test]
            fn $name() {
                assert_case($case_id);
            }
        )+
    };
}

/// Doctrine-correct expectations the current parser does not yet enforce.
///
/// Each test asserts the manifest outcome the corpus doctrine requires and is
/// ignored because the shipping parser behaves otherwise. Every one is a
/// recorded parser-defect finding on bead boulderroller-v2-8pac2 — tracked,
/// not blessed. Fixing a defect means removing its `#[ignore]`, never
/// weakening the assertion; parser fixes must respect the parser-semantics
/// version guard (tools/check_parser_semantics_version.sh).
macro_rules! corpus_defect_tests {
    ($($name:ident => $case_id:literal, $finding:literal),+ $(,)?) => {
        $(
            #[test]
            #[ignore = $finding]
            fn $name() {
                assert_case($case_id);
            }
        )+
    };
}

corpus_case_tests! {
    case_fit_empty => "fit_empty",
    case_fit_header_only => "fit_header_only",
    case_fit_truncated_mid_record => "fit_truncated_mid_record",
    case_fit_bad_header_crc => "fit_bad_header_crc",
    case_fit_bad_file_crc => "fit_bad_file_crc",
    case_fit_oversized_declared => "fit_oversized_declared",
    case_gps_teleport => "gps_teleport",
    case_gps_null_island => "gps_null_island",
    case_gps_impossible_speed => "gps_impossible_speed",
    case_gps_altitude_spike => "gps_altitude_spike",
    case_gps_altitude_dropout => "gps_altitude_dropout",
    case_gps_duplicate_timestamps => "gps_duplicate_timestamps",
    case_gps_out_of_order => "gps_out_of_order",
    case_gps_out_of_range => "gps_out_of_range",
    case_time_dst_spring_forward => "time_dst_spring_forward",
    case_time_dst_fall_back => "time_dst_fall_back",
    case_time_offset_change => "time_offset_change",
    case_time_non_monotonic => "time_non_monotonic",
    case_time_unix_epoch_zero => "time_unix_epoch_zero",
    case_device_wahoo_sparse_power => "device_wahoo_sparse_power",
    case_device_garmin_hr_cadence => "device_garmin_hr_cadence",
    case_device_hammerhead_developer_noise => "device_hammerhead_developer_noise",
    case_device_apple_watch_hr_only => "device_apple_watch_hr_only",
    case_device_phone_only => "device_phone_only",
    case_encoding_utf16 => "encoding_utf16",
    case_zero_length_stream => "zero_length_stream",
    case_enormous_gzip_bomb => "enormous_gzip_bomb",
}

corpus_defect_tests! {
    case_fit_wrong_architecture => "fit_wrong_architecture",
        "bead boulderroller-v2-8pac2 finding F1: fitparser tolerates an invalid FIT architecture byte (2)",
    case_gps_nonfinite => "gps_nonfinite",
        "bead boulderroller-v2-8pac2 finding F2: NaN latitude saturates to 0 and fabricates a coordinate downstream gates accept",
    case_unit_semicircles_as_degrees => "unit_semicircles_as_degrees",
        "bead boulderroller-v2-8pac2 finding F3: semicircle-scale degrees saturate to i32::MAX, fabricating 214.7483647",
    case_time_invalid_timestamp => "time_invalid_timestamp",
        "bead boulderroller-v2-8pac2 finding F4: an unparseable <time> silently deletes its point instead of rejecting the source",
    case_time_year_zero => "time_year_zero",
        "bead boulderroller-v2-8pac2 finding F5: year-zero timestamps parse although the downstream datetime contract cannot represent them",
    case_unit_imperial_elevation => "unit_imperial_elevation",
        "bead boulderroller-v2-8pac2 finding F6: a declared feet unit on <ele> is silently read as meters",
    case_encoding_invalid_utf8 => "encoding_invalid_utf8",
        "bead boulderroller-v2-8pac2 finding F7: invalid UTF-8 makes the XML non-well-formed but is silently skipped",
    case_xml_truncated_after_trackpoint => "xml_truncated_after_trackpoint",
        "bead boulderroller-v2-8pac2 finding F8: GPX EOF with unclosed elements is accepted as a complete ride",
    case_tcx_truncated_after_trackpoint => "tcx_truncated_after_trackpoint",
        "bead boulderroller-v2-8pac2 finding F8: TCX EOF with unclosed elements is accepted as a complete ride",
    case_tcx_half_coordinate => "tcx_half_coordinate",
        "bead boulderroller-v2-8pac2 finding F9: a TCX Position with latitude only emits a half-valid GPS pair",
}

#[test]
fn manifest_covers_every_required_torture_category() {
    let manifest = manifest();
    assert_eq!(
        manifest["case_count"].as_u64().unwrap(),
        manifest["cases"].as_array().unwrap().len() as u64
    );
    let categories: std::collections::BTreeSet<_> = manifest["cases"]
        .as_array()
        .unwrap()
        .iter()
        .map(|case| case["category"].as_str().unwrap())
        .collect();
    for required in [
        "malformed_fit",
        "gps_pathology",
        "time_pathology",
        "device_quirk",
        "unit_and_encoding",
        "empty_input",
        "enormous_input",
        "truncated_xml",
    ] {
        assert!(categories.contains(required), "missing category {required}");
    }
}
