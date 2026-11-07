from datetime import datetime, timedelta, timezone

from app.services.power_curve import (
    DURATION_LADDER_S,
    THRESHOLD_ANCHORS_S,
    aggregate_rider_power_curve,
    power_stream_to_arrays,
)


def _stream(watts_by_second):
    start = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
    return {
        "timestamps": [(start + timedelta(seconds=i)).isoformat() for i in range(len(watts_by_second))],
        "values": [float(w) for w in watts_by_second],
    }


def _fake_mean_max(time_ms, power_w, durations):
    # Plain (pause-blind) mean-max on 1 Hz input; the Rust routine is the
    # authority — this stands in for it so the aggregation is testable.
    out = []
    for d in durations:
        if len(power_w) < d:
            out.append(None)
            continue
        best = max(sum(power_w[i:i + d]) / d for i in range(len(power_w) - d + 1))
        out.append(best)
    return out


def test_ladder_contains_the_threshold_anchors():
    for anchor in THRESHOLD_ANCHORS_S:
        assert anchor in DURATION_LADDER_S


def test_stream_conversion_drops_null_and_negative_samples():
    stream = _stream([200, 210, 220])
    stream["values"][1] = None
    stream["values"][2] = -5.0
    time_ms, power_w = power_stream_to_arrays(stream)
    assert power_w == [200]
    assert len(time_ms) == 1


def test_aggregate_takes_elementwise_max_across_rides():
    short_hard = _stream([400] * 10 + [100] * 50)
    long_steady = _stream([250] * 120)
    curve = aggregate_rider_power_curve(
        [short_hard, long_steady], mean_max=_fake_mean_max, durations_s=(1, 5, 60, 120, 180)
    )
    assert curve["available"] is True
    assert curve["sampledRides"] == 2
    best = dict(zip(curve["durationsS"], curve["bestW"]))
    assert best[1] == 400.0
    assert best[5] == 400.0
    assert best[60] == 250.0
    assert best[120] == 250.0
    assert best[180] is None, "no ride is long enough for a 3-minute window"


def test_no_power_rides_is_honestly_unavailable():
    curve = aggregate_rider_power_curve([_stream([])], mean_max=_fake_mean_max, durations_s=(5, 60))
    assert curve["available"] is False
    assert curve["sampledRides"] == 0
    assert curve["bestW"] == [None, None]
