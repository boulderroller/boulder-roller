#!/usr/bin/env python3
"""Read cached real streams without network access; aggregate idle-review evidence.

Usage: PYTHONPATH=backend python tools/corpus/audit_idle_recording.py /path/to/golden_corpus.db
No rider coordinates or activity IDs are emitted. This is an offline calibration
sample, not a representative population or a ground-truth fraud label set.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from app.services import ride_idle_evidence as policy


def audit(path: Path) -> dict:
    counts = Counter()
    values = []
    powered = []
    digest = hashlib.sha256()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT streams_json FROM activity_streams ORDER BY activity_id")
        for (raw,) in rows:
            digest.update(raw.encode())
            streams = {s["type"]: s["data"] for s in json.loads(raw)}
            counts.update(streams.keys())
            time = streams.get("time", [])
            records = []
            for i, second in enumerate(time):
                fields = {"timestamp": start + timedelta(seconds=second)}
                for source, dest in (("watts", "power_w"), ("cadence", "cadence_rpm"),
                                     ("velocity_smooth", "speed_mps"), ("distance", "distance_m")):
                    channel = streams.get(source, [])
                    if i < len(channel):
                        fields[dest] = channel[i]
                gps = streams.get("latlng", [])
                if i < len(gps) and gps[i]:
                    fields["lat"], fields["lon"] = gps[i]
                records.append(SimpleNamespace(**fields))
            result = policy.assess_idle_recording(records)
            if result.recorded_duration_s:
                share = result.stationary_duration_s / result.recorded_duration_s
                values.append(share)
                if "watts" in streams:
                    powered.append(share)

    # Nearest rank (ceil(p*N)), calculated from duration ratios before the
    # production gate's basis-point flooring. Tail counts are strictly above.
    def summary(series):
        ordered = sorted(series)
        return {
            "count": len(ordered),
            "percentile_method": "nearest_rank_ceil_p_times_n",
            "share_percentiles_pct": {
                str(p): 100 * ordered[max(0, math.ceil(len(ordered)*p/100)-1)]
                for p in (50, 90, 95, 99, 99.9, 100)
            } if ordered else {},
            "counts_above_percent": {
                str(p): sum(x > p / 100 for x in ordered) for p in (50, 75, 90)
            },
            "review_count": sum(x >= policy.STATIONARY_REVIEW_SHARE_BPS / 10_000
                                for x in ordered),
        }

    # The proposed margin is a review recommendation, not a runtime parameter.
    # Choose the smallest whole-basis-point gate >= max + 0.50 percentage points.
    max_share = max(values)
    zero_hit_bps = math.floor(max_share * 10_000) + 1
    margin_bps = 50
    recommended_bps = math.ceil(max_share * 10_000 + margin_bps)
    candidates = sorted({5_000, 7_500, 9_000, 9_200, zero_hit_bps,
                         recommended_bps, 9_300, 9_500})
    gates = [{
        "gate_bps": bps,
        "stationary_percent": bps / 100,
        "approx_tss_multiple_just_below_gate": math.sqrt(1 / (1 - bps / 10_000)),
        "rides_reaching_gate": sum(x >= bps / 10_000 for x in values),
        "power_rides_reaching_gate": sum(x >= bps / 10_000 for x in powered),
        "margin_above_observed_max_percentage_points": bps / 100 - 100 * max_share,
    } for bps in candidates]
    return {"stream_content_sha256": digest.hexdigest(), "channels": dict(counts),
            "policy": policy.assess_idle_recording([]).as_dict(),
            "all_recordings": summary(values), "power_recordings": summary(powered),
            "candidate_gates": gates,
            "recommendation": {"gate_bps": recommended_bps,
                               "minimum_margin_percentage_points": margin_bps / 100,
                               "runtime_gate_bps": policy.STATIONARY_REVIEW_SHARE_BPS}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.database), indent=2))
