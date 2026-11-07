#!/usr/bin/env python3
"""Offline real-stream audit of returned native claims and grid-optimal partitions.

PYTHONPATH=backend python tools/corpus/audit_effort_trim.py /path/to/golden_corpus.db
Build the audit-only search first:
  cargo build --release --manifest-path workout-parse/Cargo.toml --example optimal_effort_partition
Gains are measurements for Tim, never admission gates. The optimal result is exact
on the stated 10 s cut grid, not an upper bound over arbitrary cut timestamps.
"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import statistics
import subprocess

import workout_parse as wp
from app.services.ride_effort_trim import normalize, subtract, intersect
from app.services.ride_effort_policy import (
    build_ride_effort_policy,
    MIN_POWER_SAMPLE_COUNT,
    MIN_POWER_SAMPLE_COVERAGE_BPS,
    MIN_POWER_MOVING_TIME_SECONDS,
)


def policy_cal(metrics):
    # Isolate partition economics from file-age/source/identity gates. The corpus
    # cannot attest those external facts; each candidate must still pass the real
    # native power-evidence policy, including sample counts and coverage.
    started = datetime(2026, 9, 23, tzinfo=timezone.utc)
    completed = started + timedelta(seconds=metrics.duration_s)
    policy = build_ride_effort_policy(
        dict(
            tss=round(float(metrics.tss or 0), 1),
            metrics_version=wp.METRICS_VERSION,
            normalized_power_w=metrics.normalized_power_w,
            power_sample_count=metrics.power_sample_count,
            power_sample_coverage_bps=metrics.power_sample_coverage_bps,
            moving_time_sec=metrics.moving_time_s,
            duration_sec=metrics.duration_s,
        ),
        started_at=started,
        completed_at=completed,
        now=completed,
    )
    return policy.rewardable_cal_base_units / 1_000_000_000


def native_activity(times, power):
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = []
    for t, p in zip(times, power, strict=True):
        watts = "" if p is None else f"<power>{p}</power>"
        points.append(
            f'<trkpt lat="40" lon="-75"><time>{(origin + timedelta(milliseconds=t)).isoformat()}</time>'
            f"<extensions>{watts}</extensions></trkpt>"
        )
    activity = wp.parse_file_bytes(
        (
            '<gpx version="1.1"><trk><trkseg>'
            + "".join(points)
            + "</trkseg></trk></gpx>"
        ).encode(),
        "gpx",
    )
    return activity, int(origin.timestamp() * 1000)


def measure_requests(activity, effort, requests):
    """Measure native-returned P, never the requested set difference."""
    claims = []
    values = []
    double_paid_ms = 0
    for a, b in requests:
        requested = subtract(intersect(effort, [(a, b)]), claims)
        metrics, returned = wp.compute_metrics_in_spans(activity, 200, requested)
        raw = float(metrics.tss or 0)
        rounded = policy_cal(metrics)
        # Match the file-level sub-1-TSS clearing rule (no Threshold hold here).
        paid = normalize(returned) if rounded >= 1 else []
        double_paid_ms += sum(d - c for c, d in intersect(paid, claims))
        claims = normalize(claims + paid)
        values.append((raw, rounded if rounded >= 1 else 0.0))
    return values, double_paid_ms


def gain_record(values, whole, **extra):
    total = sum(values)
    return dict(
        gain_percent=(total / whole - 1) * 100,
        whole_tss=whole,
        partition_tss=total,
        piece_count=len(values),
        **extra,
    )


def larger(old, new):
    return new if old is None or new["gain_percent"] > old["gain_percent"] else old


def audit(path, trials=8, grid_s=10, search_binary=None):
    rng = random.Random(890604)
    digest = hashlib.sha256()
    count = powered = partitions = invalid = double_paid_ms = 0
    max_gain = max_round_gain = max_optimal = max_optimal_raw = None
    optimal_gains = []
    optimal_raw_gains = []
    binary = (
        search_binary
        or Path(__file__).resolve().parents[2]
        / "workout-parse/target/release/examples/optimal_effort_partition"
    )
    search = subprocess.Popen(
        [str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
    )
    try:
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            for activity_id, raw in db.execute(
                "SELECT activity_id, streams_json FROM activity_streams ORDER BY activity_id"
            ):
                digest.update(raw.encode())
                count += 1
                streams = {s["type"]: s["data"] for s in json.loads(raw)}
                times = [int(t * 1000) for t in streams.get("time", [])]
                power = streams.get("watts", [])
                if len(power) != len(times) or len(times) < 60:
                    continue
                power = [
                    int(p) if p is not None and 0 <= p < 65535 else None for p in power
                ]
                try:
                    activity, origin = native_activity(times, power)
                    effort = normalize(wp.effort_spans_ms(activity))
                    metrics, _ = wp.compute_metrics_in_spans(activity, 200, effort)
                    whole = float(metrics.tss or 0)
                except (wp.DurationLimitExceeded, wp.ParseError):
                    invalid += 1
                    continue
                rounded_whole = round(whole, 1)
                if whole <= 0 or policy_cal(metrics) <= 0:
                    continue
                powered += 1
                start, end = effort[0][0], effort[-1][1]
                for trial in range(trials):
                    cuts = sorted(
                        set(
                            [start, end]
                            + [
                                rng.randrange(start // 1000, end // 1000) * 1000
                                for _ in range(rng.randint(1, 9))
                            ]
                        )
                    )
                    requests = list(zip(cuts, cuts[1:]))
                    if trial % 2:
                        requests = [
                            (
                                max(start, a - rng.randrange(0, 121) * 1000),
                                min(end, b + rng.randrange(0, 121) * 1000),
                            )
                            for a, b in requests
                        ]
                        rng.shuffle(requests)
                    values, duplicates = measure_requests(activity, effort, requests)
                    double_paid_ms += duplicates
                    partitions += 1
                    max_gain = larger(
                        max_gain,
                        gain_record(
                            [v[0] for v in values], whole, activity_id=activity_id
                        ),
                    )
                    max_round_gain = larger(
                        max_round_gain,
                        gain_record(
                            [v[1] for v in values],
                            rounded_whole,
                            activity_id=activity_id,
                        ),
                    )

                search.stdin.write(
                    json.dumps(
                        dict(
                            times=times,
                            power=power,
                            grid_s=grid_s,
                            minimum=[
                                MIN_POWER_SAMPLE_COUNT,
                                MIN_POWER_SAMPLE_COVERAGE_BPS,
                                MIN_POWER_MOVING_TIME_SECONDS,
                            ],
                        )
                    )
                    + "\n"
                )
                search.stdin.flush()
                witness = json.loads(search.stdout.readline())
                for objective in ("raw", "cal"):
                    requests = [(a + origin, b + origin) for a, b in witness[objective]]
                    values, duplicates = measure_requests(activity, effort, requests)
                    double_paid_ms += duplicates
                    if objective == "cal":
                        assert (
                            round(sum(v[1] for v in values) * 10)
                            == witness["cal_tenths"]
                        ), "native witness differs from search price"
                        record = gain_record(
                            [v[1] for v in values],
                            rounded_whole,
                            activity_id=activity_id,
                            cuts_ms=witness["cal"],
                        )
                        optimal_gains.append(record["gain_percent"])
                        max_optimal = larger(max_optimal, record)
                    else:
                        assert (
                            abs(sum(v[0] for v in values) - witness["raw_tss"]) < 0.001
                        ), "native raw witness differs from search price"
                        raw_record = gain_record(
                            [v[0] for v in values],
                            whole,
                            activity_id=activity_id,
                            cuts_ms=witness["raw"],
                        )
                        optimal_raw_gains.append(raw_record["gain_percent"])
                        max_optimal_raw = larger(max_optimal_raw, raw_record)
    finally:
        search.stdin.close()
        search.wait(timeout=10)
        search.stdout.close()
    return dict(
        evidence_class="local cached real streams",
        seed=890604,
        streams_sha256=digest.hexdigest(),
        streams=count,
        powered_streams=powered,
        native_rejected_streams=invalid,
        trials_per_stream=trials,
        partitions=partitions,
        double_paid_milliseconds=double_paid_ms,
        double_paid_seconds=double_paid_ms / 1000,
        largest_raw_tss_gain=max_gain,
        largest_rounded_cal_gain=max_round_gain,
        optimal_grid_seconds=grid_s,
        optimal_objective="sum of rounded CAL passing native sample-count, coverage and moving-time gates; conditional on otherwise eligible files",
        largest_optimal_cal_gain=max_optimal,
        median_optimal_cal_gain_percent=statistics.median(optimal_gains),
        largest_optimal_raw_tss_gain=max_optimal_raw,
        median_optimal_raw_tss_gain_percent=statistics.median(optimal_raw_gains),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--grid-seconds", type=int, default=10)
    args = parser.parse_args()
    if args.grid_seconds < 1:
        parser.error("grid-seconds must be positive")
    result = audit(args.database, grid_s=args.grid_seconds)
    print(json.dumps(result, indent=2))
    if result["double_paid_milliseconds"]:
        raise SystemExit("native returned claims overlap")
