//! File clock and indoor evidence, deliberately outside canonical/economic data.
use chrono::{Local, TimeZone};
use fitparser::{profile::MesgNum, FitDataRecord, Value};

#[derive(Debug, Clone, Default)]
pub struct TrainingContext {
    pub utc_offset_s: Option<i32>,
    pub indoor_or_virtual: bool,
    conflicting_offsets: bool,
}

impl TrainingContext {
    pub fn observe_creator(&mut self, creator: &str) {
        let creator = creator.to_ascii_lowercase();
        self.indoor_or_virtual |= [
            "zwift",
            "trainerroad",
            "trainer_road",
            "bkool",
            "rouvy",
            "fulgaz",
            "boulderroller-strava-import-virtual",
        ]
        .iter()
        .any(|provider| creator.contains(provider));
    }

    pub fn observe(&mut self, record: &FitDataRecord) {
        let mut utc = None;
        let mut local = None;
        for field in record.fields() {
            // fitparser 0.7 decodes enums to profile names, including resolved
            // antplus_device_type subfields. A paired trainer is indoor evidence.
            if let Value::String(value) = field.value() {
                self.indoor_or_virtual |= match field.name() {
                    "sub_sport" => matches!(
                        value.as_str(),
                        "virtual_activity" | "indoor_cycling" | "spin"
                    ),
                    "sport" | "activity_type" | "device_type" | "antplus_device_type" => {
                        value == "fitness_equipment"
                    }
                    "manufacturer" => matches!(value.as_str(), "zwift" | "trainer_road" | "bkool"),
                    _ => false,
                };
            }
            if record.kind() == MesgNum::Activity {
                if let Value::Timestamp(value) = field.value() {
                    match field.name() {
                        "timestamp" => utc = Some(value.timestamp()),
                        // FIT local_date_time is a wall-clock count, not an
                        // instant. Undo fitparser's host-local epoch conversion
                        // before subtracting UTC (including host DST changes).
                        "local_timestamp" => {
                            if let Some(epoch) =
                                Local.with_ymd_and_hms(1989, 12, 31, 0, 0, 0).earliest()
                            {
                                local = Some(value.timestamp() - epoch.timestamp() + 631_065_600);
                            }
                        }
                        _ => {}
                    }
                }
            }
        }
        // Garmin FIT activity local_timestamp - timestamp gives the offset:
        // https://developer.garmin.com/fit/articles/cookbook/datetime.html
        if let (Some(local), Some(utc)) = (local, utc) {
            let offset = local - utc;
            if !(-43_200..=50_400).contains(&offset) {
                self.conflicting_offsets = true;
            } else if let Some(previous) = self.utc_offset_s {
                self.conflicting_offsets |= i64::from(previous) != offset;
            }
            self.utc_offset_s = if self.conflicting_offsets {
                None
            } else {
                Some(offset as i32)
            };
        }
    }
}
