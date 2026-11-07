import Foundation

/// Tim owns both lines: how it was estimated, then what would make it exact.
/// backend/tests/truths/test_estimate_copy_parity.py keeps this map in step
/// with web/portal/src/lib/estimateCopy.ts.
enum EstimateCopy {
    static let slots: [String: [String]] = [
        "threshold_cp_3_7_15_v1": ["Estimated from your best-ever 3, 7 and 15-minute power.", "Record rides in the iOS app with one power meter; your Threshold is sealed from them each Monday."],
        "hrss": ["Worked out from heart rate, because this ride has no power.", "This ride stays an estimate. Rides with power, after your Threshold is sealed, are exact."],
        "work_kj_div_4.184_div_0.24": ["Worked out from the ride's work, at an assumed 24% efficiency.", "It stays an estimate: real efficiency varies from rider to rider."],
        "95_percent_best_20m_hr": ["95% of your best 20-minute heart rate.", "There's no place to set your threshold heart rate yet."],
        "90_percent_max_hr": ["90% of your max heart rate.", "There's no place to set your threshold heart rate yet."],
        "observed_peak_hr": ["The highest heart rate seen on your rides.", "There's no place to set your max heart rate yet."],
        "last_configured_hr_zone": ["The top of your last heart-rate zone on file.", "There's no place to set your max heart rate yet."],
        "intervals_default_60": ["A resting heart rate of 60, intervals.icu's default.", "There's no place to set your resting heart rate yet."],
        "stored_ride_loads": ["Built from your rides' loads, some of them estimated.", "Exact once every ride's load comes from power on a sealed Threshold."],
        "power": ["From your power, using an estimated Threshold or incomplete ride history.", "Rides after your Threshold is sealed in the iOS app are exact."],
        "ios_threshold": ["Your Threshold from the iOS app.", "Ride with the app to keep it current."],
        "rider": ["A value you set.", "It's your own number. Update it when it changes."],
        "device": ["Calories reported by your recording device.", "Device calorie counts are estimates too; nothing in the app makes them exact."],
        "unavailable": ["This ride doesn't have the data for an estimate.", "Record heart rate or power."],
    ]

    static func lines(basis: String?) -> [String] {
        visibleLines(basis.flatMap { slots[$0] } ?? [])
    }

    static func visibleLines(_ slots: [String]) -> [String] {
        slots.map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && !$0.contains("TIM:") }
    }
}
