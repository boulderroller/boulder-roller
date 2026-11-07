//! Exercise every current golden, including the in-memory activity that the
//! Python raw-file checks cannot construct through the read-only binding.

use serde::de::DeserializeOwned;
use serde_json::Value;
use std::fs;
use std::path::PathBuf;
use workout_parse::canonicalize::{canonicalize, hash_canonical_ride_hex, CURRENT_PARSER_VERSION};
use workout_parse::constants::{MISSING_I32, MISSING_U16, MISSING_U8};
use workout_parse::{parse_file_bytes_for_version, ParsedActivity};

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .unwrap()
        .to_owned()
}

fn stream<T: Copy + DeserializeOwned>(activity: &Value, field: &str, missing: T) -> Option<Vec<T>> {
    activity.get(field).map(|values| {
        serde_json::from_value::<Vec<Option<T>>>(values.clone())
            .unwrap()
            .into_iter()
            .map(|value| value.unwrap_or(missing))
            .collect()
    })
}

#[test]
fn every_current_vector_matches_canonical_bytes_and_hash() {
    let path = repo_root().join(format!(
        "tests/fixtures/canonical_ride_v{CURRENT_PARSER_VERSION}_vectors.json"
    ));
    let fixture: Value = serde_json::from_slice(&fs::read(path).unwrap()).unwrap();
    assert_eq!(fixture["parser_version"], CURRENT_PARSER_VERSION);
    let vectors = fixture["vectors"].as_object().unwrap();
    assert!(!vectors.is_empty());
    for (name, vector) in vectors {
        let activity = if let Some(input) = vector.get("activity") {
            ParsedActivity {
                time_ms: serde_json::from_value(input["time_ms"].clone()).unwrap(),
                lat_e7: stream(input, "lat_e7", MISSING_I32),
                lon_e7: stream(input, "lon_e7", MISSING_I32),
                elevation_m: stream(input, "elevation_m", f32::NAN),
                pwr_w: stream(input, "pwr_w", MISSING_U16),
                hr_bpm: stream(input, "hr_bpm", MISSING_U8),
                cadence_rpm: stream(input, "cadence_rpm", MISSING_U8),
                speed_mps: stream(input, "speed_mps", f32::NAN),
                dist_m: stream(input, "dist_m", f32::NAN),
                sport: input["sport"].as_str().unwrap().to_owned(),
                started_at_ms: input["started_at_ms"].as_i64().unwrap(),
                ..ParsedActivity::default()
            }
        } else {
            let raw = fs::read(repo_root().join(vector["source_path"].as_str().unwrap())).unwrap();
            parse_file_bytes_for_version(
                &raw,
                vector["file_type"].as_str().unwrap(),
                CURRENT_PARSER_VERSION,
            )
            .unwrap()
        };
        assert_eq!(
            String::from_utf8(canonicalize(&activity, CURRENT_PARSER_VERSION).unwrap()).unwrap(),
            vector["canonical_json"].as_str().unwrap(),
            "{name} canonical bytes"
        );
        assert_eq!(
            hash_canonical_ride_hex(&activity, CURRENT_PARSER_VERSION).unwrap(),
            vector["ride_hash"].as_str().unwrap(),
            "{name} hash"
        );
    }
}
