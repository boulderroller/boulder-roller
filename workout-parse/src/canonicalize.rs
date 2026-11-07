//! Deterministic ride canonicalization for replay protection and attestation identity.

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::constants::MAX_ACTIVITY_DURATION_S;
use crate::error::{WpError, WpResult};
use crate::{validate_activity_timestamps, ParsedActivity, MISSING_I32, MISSING_U16, MISSING_U8};

pub const PARSER_VERSION_V1: u32 = 1;
pub const PARSER_VERSION_V2: u32 = 2;
pub const PARSER_VERSION_V3: u32 = 3;
pub const PARSER_VERSION_V4: u32 = 4;
pub const PARSER_VERSION_V5: u32 = 5;
pub const CURRENT_PARSER_VERSION: u32 = PARSER_VERSION_V5;

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct CanonicalSampleV1 {
    pub cadence_rpm: Option<u8>,
    pub dist_dm: Option<i64>,
    pub elev_dm: Option<i64>,
    pub hr_bpm: Option<u8>,
    pub lat_e6: Option<i64>,
    pub lon_e6: Option<i64>,
    pub power_w: Option<u16>,
    pub sec_offset: i64,
    pub speed_cms: Option<i64>,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct CanonicalRideV1 {
    pub parser_version: u32,
    pub samples: Vec<CanonicalSampleV1>,
    pub sport: String,
    pub started_at_ms: i64,
}

#[derive(Debug, Clone, Default)]
struct BucketAccumulator {
    last_lat_e6: Option<i64>,
    last_lon_e6: Option<i64>,
    last_elev_dm: Option<i64>,
    last_dist_dm: Option<i64>,
    speed_sum: i64,
    speed_count: i64,
    power_sum: i64,
    power_count: i64,
    hr_sum: i64,
    hr_count: i64,
    cadence_sum: i64,
    cadence_count: i64,
}

impl BucketAccumulator {
    fn into_sample(self, sec_offset: i64) -> CanonicalSampleV1 {
        CanonicalSampleV1 {
            cadence_rpm: rounded_mean_u8(self.cadence_sum, self.cadence_count),
            dist_dm: self.last_dist_dm,
            elev_dm: self.last_elev_dm,
            hr_bpm: rounded_mean_u8(self.hr_sum, self.hr_count),
            lat_e6: self.last_lat_e6,
            lon_e6: self.last_lon_e6,
            power_w: rounded_mean_u16(self.power_sum, self.power_count),
            sec_offset,
            speed_cms: rounded_mean_i64(self.speed_sum, self.speed_count),
        }
    }
}

fn normalize_sport(sport: &str) -> String {
    sport
        .trim()
        .chars()
        .filter(|ch| ch.is_ascii())
        .collect::<String>()
        .to_ascii_lowercase()
}

fn round_scaled_f64(value: f64, scale: f64) -> Option<i64> {
    if value.is_finite() {
        Some((value * scale).round() as i64)
    } else {
        None
    }
}

fn rounded_mean_i64(sum: i64, count: i64) -> Option<i64> {
    if count == 0 {
        None
    } else {
        Some((sum as f64 / count as f64).round() as i64)
    }
}

fn rounded_mean_u16(sum: i64, count: i64) -> Option<u16> {
    rounded_mean_i64(sum, count).and_then(|value| u16::try_from(value).ok())
}

fn rounded_mean_u8(sum: i64, count: i64) -> Option<u8> {
    rounded_mean_i64(sum, count).and_then(|value| u8::try_from(value).ok())
}

fn sample_second(time_ms: i64, started_at_ms: i64) -> WpResult<i64> {
    let elapsed_ms = time_ms.checked_sub(started_at_ms).ok_or_else(|| {
        WpError::InvalidTimestamp("canonical timestamp offset overflowed i64".into())
    })?;
    if elapsed_ms < 0 {
        return Err(WpError::InvalidTimestamp(format!(
            "canonical timestamp {time_ms} precedes start {started_at_ms}"
        )));
    }
    Ok(elapsed_ms / 1_000)
}

fn canonicalize_struct(
    activity: &ParsedActivity,
    parser_version: u32,
) -> WpResult<CanonicalRideV1> {
    let sport = normalize_sport(&activity.sport);

    if activity.time_ms.is_empty() {
        return Ok(CanonicalRideV1 {
            parser_version,
            samples: Vec::new(),
            sport,
            started_at_ms: activity.started_at_ms,
        });
    }

    let (first_timestamp_ms, _) = validate_activity_timestamps(&activity.time_ms)?;
    if activity.started_at_ms != first_timestamp_ms {
        return Err(WpError::InvalidTimestamp(format!(
            "started_at_ms {} does not match first sample {}",
            activity.started_at_ms, first_timestamp_ms
        )));
    }

    let last_sec_offset = sample_second(
        *activity.time_ms.last().unwrap_or(&activity.started_at_ms),
        activity.started_at_ms,
    )?;
    let bucket_count = usize::try_from(last_sec_offset)
        .ok()
        .and_then(|offset| offset.checked_add(1))
        .ok_or_else(|| {
            WpError::DurationLimitExceeded("canonical bucket count overflowed".into())
        })?;
    if bucket_count > MAX_ACTIVITY_DURATION_S + 1 {
        return Err(WpError::DurationLimitExceeded(format!(
            "Canonical timeline requires {bucket_count} buckets"
        )));
    }
    let mut buckets = vec![BucketAccumulator::default(); bucket_count];

    for (i, &time_ms) in activity.time_ms.iter().enumerate() {
        let sec_offset = sample_second(time_ms, activity.started_at_ms)?;
        let bucket_index = usize::try_from(sec_offset).map_err(|_| {
            WpError::DurationLimitExceeded("canonical sample offset does not fit usize".into())
        })?;
        let bucket = buckets.get_mut(bucket_index).ok_or_else(|| {
            WpError::DurationLimitExceeded(format!(
                "canonical sample offset {bucket_index} exceeds bounded timeline"
            ))
        })?;

        if let Some(lat_e7) = activity
            .lat_e7
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
        {
            if lat_e7 != MISSING_I32 {
                bucket.last_lat_e6 = Some((lat_e7 as f64 / 10.0).round() as i64);
            }
        }

        if let Some(lon_e7) = activity
            .lon_e7
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
        {
            if lon_e7 != MISSING_I32 {
                bucket.last_lon_e6 = Some((lon_e7 as f64 / 10.0).round() as i64);
            }
        }

        if let Some(elev_m) = activity
            .elevation_m
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
        {
            bucket.last_elev_dm = round_scaled_f64(elev_m as f64, 10.0);
        }

        if let Some(dist_m) = activity
            .dist_m
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
        {
            bucket.last_dist_dm = round_scaled_f64(dist_m as f64, 10.0);
        }

        if let Some(speed_mps) = activity
            .speed_mps
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
            .and_then(|value| round_scaled_f64(value as f64, 100.0))
        {
            bucket.speed_sum += speed_mps;
            bucket.speed_count += 1;
        }

        if let Some(power_w) = activity
            .pwr_w
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
        {
            if power_w != MISSING_U16 {
                bucket.power_sum += i64::from(power_w);
                bucket.power_count += 1;
            }
        }

        if let Some(hr_bpm) = activity
            .hr_bpm
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
        {
            if hr_bpm != MISSING_U8 {
                bucket.hr_sum += i64::from(hr_bpm);
                bucket.hr_count += 1;
            }
        }

        if let Some(cadence_rpm) = activity
            .cadence_rpm
            .as_ref()
            .and_then(|values| values.get(i))
            .copied()
        {
            if cadence_rpm != MISSING_U8 {
                bucket.cadence_sum += i64::from(cadence_rpm);
                bucket.cadence_count += 1;
            }
        }
    }

    let samples = buckets
        .into_iter()
        .enumerate()
        .map(|(sec_offset, bucket)| bucket.into_sample(sec_offset as i64))
        .collect();

    Ok(CanonicalRideV1 {
        parser_version,
        samples,
        sport,
        started_at_ms: activity.started_at_ms,
    })
}

/// V1 is permanently bound to the pre-9e6d49aa interpretation of missing
/// XML elevation. Do not route raw V1 replay through the current parser.
pub fn canonicalize_v1_struct(activity: &ParsedActivity) -> WpResult<CanonicalRideV1> {
    canonicalize_struct(activity, PARSER_VERSION_V1)
}

pub fn canonicalize_v2_struct(activity: &ParsedActivity) -> WpResult<CanonicalRideV1> {
    canonicalize_struct(activity, PARSER_VERSION_V2)
}

pub fn canonicalize_v3_struct(activity: &ParsedActivity) -> WpResult<CanonicalRideV1> {
    canonicalize_struct(activity, PARSER_VERSION_V3)
}

pub fn canonicalize_v4_struct(activity: &ParsedActivity) -> WpResult<CanonicalRideV1> {
    canonicalize_struct(activity, PARSER_VERSION_V4)
}

pub fn canonicalize_v5_struct(activity: &ParsedActivity) -> WpResult<CanonicalRideV1> {
    canonicalize_struct(activity, PARSER_VERSION_V5)
}

pub fn canonicalize(activity: &ParsedActivity, parser_version: u32) -> WpResult<Vec<u8>> {
    match parser_version {
        PARSER_VERSION_V1 => serde_json::to_vec(&canonicalize_v1_struct(activity)?)
            .map_err(|err| WpError::Parse(format!("canonicalization serialization failed: {err}"))),
        PARSER_VERSION_V2 => serde_json::to_vec(&canonicalize_v2_struct(activity)?)
            .map_err(|err| WpError::Parse(format!("canonicalization serialization failed: {err}"))),
        PARSER_VERSION_V3 => serde_json::to_vec(&canonicalize_v3_struct(activity)?)
            .map_err(|err| WpError::Parse(format!("canonicalization serialization failed: {err}"))),
        PARSER_VERSION_V4 => serde_json::to_vec(&canonicalize_v4_struct(activity)?)
            .map_err(|err| WpError::Parse(format!("canonicalization serialization failed: {err}"))),
        PARSER_VERSION_V5 => serde_json::to_vec(&canonicalize_v5_struct(activity)?)
            .map_err(|err| WpError::Parse(format!("canonicalization serialization failed: {err}"))),
        _ => Err(WpError::Parse(format!(
            "unsupported canonicalization parser_version: {parser_version}"
        ))),
    }
}

pub fn hash_canonical_ride(activity: &ParsedActivity, parser_version: u32) -> WpResult<[u8; 32]> {
    let canonical = canonicalize(activity, parser_version)?;
    Ok(Sha256::digest(canonical).into())
}

pub fn hash_canonical_ride_hex(activity: &ParsedActivity, parser_version: u32) -> WpResult<String> {
    Ok(hex::encode(hash_canonical_ride(activity, parser_version)?))
}

#[cfg(test)]
mod tests {
    use super::*;

    const REFERENCE_GPX: &[u8] = include_bytes!("../tests/fixtures/canonical_v1_reference.gpx");
    const REFERENCE_GPX_CANONICAL_JSON: &str = concat!(
        "{\"parser_version\":1,\"samples\":[",
        "{\"cadence_rpm\":81,\"dist_dm\":null,\"elev_dm\":16005,\"hr_bpm\":141,",
        "\"lat_e6\":40123457,\"lon_e6\":-105123457,\"power_w\":205,\"sec_offset\":0,\"speed_cms\":null},",
        "{\"cadence_rpm\":85,\"dist_dm\":null,\"elev_dm\":16010,\"hr_bpm\":145,",
        "\"lat_e6\":40123460,\"lon_e6\":-105123460,\"power_w\":220,\"sec_offset\":1,\"speed_cms\":null},",
        "{\"cadence_rpm\":null,\"dist_dm\":null,\"elev_dm\":null,\"hr_bpm\":null,",
        "\"lat_e6\":null,\"lon_e6\":null,\"power_w\":null,\"sec_offset\":2,\"speed_cms\":null},",
        "{\"cadence_rpm\":null,\"dist_dm\":null,\"elev_dm\":15995,\"hr_bpm\":null,",
        "\"lat_e6\":40123470,\"lon_e6\":-105123470,\"power_w\":null,\"sec_offset\":3,\"speed_cms\":null}",
        "],\"sport\":\"cycling\",\"started_at_ms\":1577836800000}"
    );
    const REFERENCE_GPX_RIDE_HASH: &str =
        "429a9a50c7fea255f284379e7e05b34c1fbb6fe64f90cd9415fb6a3232de33aa";

    fn sample_activity() -> ParsedActivity {
        ParsedActivity {
            time_ms: vec![1_000, 1_200, 2_500, 4_000],
            lat_e7: Some(vec![123_456_789, 123_456_799, MISSING_I32, 123_456_700]),
            lon_e7: Some(vec![-987_654_321, -987_654_300, MISSING_I32, -987_654_222]),
            elevation_m: Some(vec![10.0, 10.14, 11.0, 9.99]),
            pwr_w: Some(vec![100, 101, MISSING_U16, 250]),
            hr_bpm: Some(vec![MISSING_U8, 120, 140, 141]),
            cadence_rpm: Some(vec![80, 82, 84, MISSING_U8]),
            speed_mps: Some(vec![5.12, 5.50, 6.0, 0.0]),
            dist_m: Some(vec![0.0, 1.49, 20.0, 45.05]),
            sport: "  CyCling🚵 ".to_string(),
            device_name: Some("device".to_string()),
            started_at_ms: 1_000,
            total_elapsed_s: 4,
            ..ParsedActivity::default()
        }
    }

    #[test]
    fn canonicalize_v1_produces_expected_json() {
        let activity = sample_activity();
        let canonical = canonicalize(&activity, 1).unwrap();
        let expected = concat!(
            "{\"parser_version\":1,\"samples\":[",
            "{\"cadence_rpm\":81,\"dist_dm\":15,\"elev_dm\":101,\"hr_bpm\":120,",
            "\"lat_e6\":12345680,\"lon_e6\":-98765430,\"power_w\":101,\"sec_offset\":0,\"speed_cms\":531},",
            "{\"cadence_rpm\":84,\"dist_dm\":200,\"elev_dm\":110,\"hr_bpm\":140,",
            "\"lat_e6\":null,\"lon_e6\":null,\"power_w\":null,\"sec_offset\":1,\"speed_cms\":600},",
            "{\"cadence_rpm\":null,\"dist_dm\":null,\"elev_dm\":null,\"hr_bpm\":null,",
            "\"lat_e6\":null,\"lon_e6\":null,\"power_w\":null,\"sec_offset\":2,\"speed_cms\":null},",
            "{\"cadence_rpm\":null,\"dist_dm\":450,\"elev_dm\":100,\"hr_bpm\":141,",
            "\"lat_e6\":12345670,\"lon_e6\":-98765422,\"power_w\":250,\"sec_offset\":3,\"speed_cms\":0}",
            "],\"sport\":\"cycling\",\"started_at_ms\":1000}"
        );
        assert_eq!(String::from_utf8(canonical).unwrap(), expected);
    }

    #[test]
    fn canonicalize_v1_hash_is_stable() {
        let activity = sample_activity();
        let hash = hash_canonical_ride_hex(&activity, 1).unwrap();
        assert_eq!(
            hash,
            "6b59b7f94e764d8b326a88a3109f0dde80d472327066bce67bbf51b0a7034517"
        );
    }

    #[test]
    fn canonicalize_v1_preserves_empty_seconds() {
        let activity = sample_activity();
        let ride = canonicalize_v1_struct(&activity).unwrap();
        assert_eq!(ride.samples.len(), 4);
        assert_eq!(ride.samples[2].sec_offset, 2);
        assert!(ride.samples[2].power_w.is_none());
        assert!(ride.samples[2].lat_e6.is_none());
    }

    #[test]
    fn canonicalize_v1_treats_nan_elevation_as_missing_not_sea_level() {
        let mut activity = ParsedActivity::default();
        activity.time_ms = vec![1_000, 2_000, 3_000];
        activity.started_at_ms = 1_000;
        activity.elevation_m = Some(vec![f32::NAN, 0.0, 12.34]);

        let ride = canonicalize_v1_struct(&activity).unwrap();

        assert!(ride.samples[0].elev_dm.is_none());
        assert_eq!(ride.samples[1].elev_dm, Some(0));
        assert_eq!(ride.samples[2].elev_dm, Some(123));
    }

    #[test]
    fn canonicalize_v1_reference_gpx_matches_expected_vector() {
        let activity = crate::parse_bytes_for_version(REFERENCE_GPX, PARSER_VERSION_V1).unwrap();
        let canonical = canonicalize(&activity, PARSER_VERSION_V1).unwrap();

        assert_eq!(
            String::from_utf8(canonical).unwrap(),
            REFERENCE_GPX_CANONICAL_JSON
        );
    }

    #[test]
    fn canonicalize_v1_reference_gpx_hash_matches_expected_vector() {
        let activity = crate::parse_bytes_for_version(REFERENCE_GPX, PARSER_VERSION_V1).unwrap();
        let ride_hash = hash_canonical_ride_hex(&activity, PARSER_VERSION_V1).unwrap();

        assert_eq!(ride_hash, REFERENCE_GPX_RIDE_HASH);
    }

    #[test]
    fn parser_v5_is_current_while_older_versions_remain_supported() {
        assert_eq!(CURRENT_PARSER_VERSION, PARSER_VERSION_V5);
        assert_ne!(
            canonicalize(&sample_activity(), PARSER_VERSION_V1).unwrap(),
            canonicalize(&sample_activity(), PARSER_VERSION_V2).unwrap()
        );
        assert_ne!(
            canonicalize(&sample_activity(), PARSER_VERSION_V2).unwrap(),
            canonicalize(&sample_activity(), PARSER_VERSION_V3).unwrap()
        );
        assert_ne!(
            canonicalize(&sample_activity(), PARSER_VERSION_V3).unwrap(),
            canonicalize(&sample_activity(), PARSER_VERSION_V4).unwrap()
        );
        assert_ne!(
            canonicalize(&sample_activity(), PARSER_VERSION_V4).unwrap(),
            canonicalize(&sample_activity(), PARSER_VERSION_V5).unwrap()
        );
    }

    #[test]
    fn canonicalization_rejects_out_of_order_timestamps() {
        let mut activity = sample_activity();
        activity.time_ms = vec![2_000, 1_000];
        activity.started_at_ms = 2_000;

        let error = canonicalize(&activity, 1).unwrap_err();
        assert!(error.to_string().contains("out of order"));
    }

    #[test]
    fn canonicalization_rejects_span_over_activity_limit() {
        let mut activity = sample_activity();
        activity.time_ms = vec![
            0,
            ((crate::constants::MAX_ACTIVITY_DURATION_S as i64) + 1) * 1_000,
        ];
        activity.started_at_ms = 0;

        let error = canonicalize(&activity, 1).unwrap_err();
        assert!(matches!(error, WpError::DurationLimitExceeded(_)));
    }
}
