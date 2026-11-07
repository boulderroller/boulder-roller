#!/usr/bin/env python3
"""Read-only exploratory power-ride calibration; emits aggregates, never identifiers.
Usage: PYTHONPATH=<current canonical workout_parse wheel> python script.py --corpus-db <db> --output <output>
Imported watts are NOT attested or verified maximal efforts; outputs are not real-establishment FPR.
The database has no rider identity: pooled chronology is a corpus-level sensitivity exercise only.
"""
import argparse, collections, decimal, hashlib, json, math, sqlite3, sys
from pathlib import Path

try:
    from workout_parse import workout_parse
except ImportError:
    # Some canonical builds expose the native module directly.
    import workout_parse

D = decimal.Decimal
DURATIONS = [180, 420, 900]
FLOORS = [0.25, 0.30, 0.35, 0.40]
CAPS = [40000, 50000, 60000]


def fit(a):
    if any(x is None for x in a):
        return None
    x = [D(1) / D(t) for t in DURATIONS]
    y = [D(str(v)) for v in a]
    mx = sum(x) / 3
    my = sum(y) / 3
    w = sum((xx - mx) * (yy - my) for xx, yy in zip(x, y)) / sum(
        (xx - mx) ** 2 for xx in x
    )
    cp = my - w * mx
    if cp <= 0 or w <= 0:
        return None
    cp = float(cp.quantize(D(".000001"), rounding=decimal.ROUND_HALF_UP))
    w = float(w.quantize(D(".000001"), rounding=decimal.ROUND_HALF_UP))
    return dict(
        cp=cp,
        w=w,
        ratio=cp / a[0],
        residual=max(abs(v - (cp + w / t)) for v, t in zip(a, DURATIONS)),
    )


def stats(rows):
    result = {"count": len(rows)}
    if not rows:
        return result
    for k in ["cp", "w", "ratio", "residual"]:
        a = sorted(r[k] for r in rows)
        result[k] = {
            "min": a[0],
            "p01": a[int((len(a) - 1) * 0.01)],
            "p05": a[int((len(a) - 1) * 0.05)],
            "median": a[len(a) // 2],
            "p95": a[int((len(a) - 1) * 0.95)],
            "p99": a[int((len(a) - 1) * 0.99)],
            "max": a[-1],
        }
    result["gates"] = [
        {
            "ratio_floor": f,
            "w_ceiling_j": c,
            "review_count": sum(r["ratio"] < f or r["w"] > c for r in rows),
            "ratio_only": sum(r["ratio"] < f for r in rows),
            "w_only": sum(r["w"] > c for r in rows),
            "review_pct": 100
            * sum(r["ratio"] < f or r["w"] > c for r in rows)
            / len(rows),
        }
        for f in FLOORS
        for c in CAPS
    ]
    result["collinear_review_counts"] = {
        str(t): sum(r["residual"] <= t for r in rows) for t in [1e-6, 0.01, 0.1, 1]
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-db", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    p = args.corpus_db
    c = sqlite3.connect("file:" + str(p.resolve()) + "?mode=ro&immutable=1", uri=True)
    counts = collections.Counter()
    individual = []
    pool = []
    first = None
    last = None
    best = [None] * 3
    changed = []
    for start, raw in c.execute(
        "SELECT r.start_date,s.streams_json FROM activity_streams s LEFT JOIN rides r USING(activity_id) ORDER BY r.start_date,s.activity_id"
    ):
        counts["streams"] += 1
        ss = json.loads(raw)
        ss = (
            {v["type"]: v["data"] for v in ss}
            if isinstance(ss, list)
            else {
                k: v.get("data", v) if isinstance(v, dict) else v for k, v in ss.items()
            }
        )
        if "watts" not in ss:
            continue
        counts["with_watts"] += 1
        if first is None:
            first = start
        last = start
        if "time" not in ss or len(ss["time"]) != len(ss["watts"]):
            counts["bad_length_or_time"] += 1
            continue
        if any(
            v is not None
            and (
                not isinstance(v, (int, float))
                or not math.isfinite(v)
                or v < 0
                or v >= 65535
                or int(v) != v
            )
            for v in ss["watts"]
        ):
            counts["invalid_power"] += 1
            continue
        ts = [int(round(t * 1000)) for t in ss["time"]]
        ws = [65535 if w is None else int(w) for w in ss["watts"]]
        try:
            a = workout_parse.compute_mean_max_power_series(ts, ws, DURATIONS)
        except Exception as e:
            counts["canonical_error_" + type(e).__name__] += 1
            if "Duration limit exceeded" in str(e):
                counts["canonical_duration_limit_exceeded"] += 1
            continue
        counts["missing_180"] += a[0] is None
        counts["missing_420"] += a[1] is None
        counts["missing_900"] += a[2] is None
        f = fit(a)
        if f:
            counts["positive_cp_and_w"] += 1
            if 50 <= f["cp"] <= 500:
                individual.append(f)
            else:
                counts["outside_existing_bounds"] += 1
        elif all(v is not None for v in a):
            counts["nonpositive_cp_or_w"] += 1
        before = best[:]
        best = [
            max(v, b) if v is not None and b is not None else v if b is None else b
            for v, b in zip(a, best)
        ]
        pf = fit(best)
        if pf and 50 <= pf["cp"] <= 500:
            pool.append(pf)
            if best != before:
                changed.append(pf)
    result = {
        "evidence_class": "local exploratory historical imported power rides; not iOS establishments or verified honest riders",
        "module_path": workout_parse.__file__,
        "module_binary_sha256": hashlib.sha256(
            Path(workout_parse.__file__).read_bytes()
        ).hexdigest(),
        "database_sha256": (
            hashlib.file_digest(open(p, "rb"), "sha256").hexdigest()
            if hasattr(hashlib, "file_digest")
            else hashlib.sha256(p.read_bytes()).hexdigest()
        ),
        "database_counts": dict(counts),
        "power_date_range": [first, last],
        "individual_hypothetical_first_fit_existing_bounds": stats(individual),
        "pooled_chronological_envelopes_existing_bounds": stats(pool),
        "pooled_changed_envelopes_existing_bounds": stats(changed),
        "final_pooled_anchors": best,
        "example_degenerate": fit([400, 60 + 61200 / 420, 128]),
        "example_honest": fit([400, 300, 270]),
        "example_ideal_collinear_pass": fit([200 + 18000 / t for t in DURATIONS]),
        "limitations": [
            "No athlete identifier column; pooling is only a corpus-level sensitivity exercise, not multiple rider lifetime histories.",
            "Imported power is not iOS-attested, effort-certified, or ground-truth honest.",
            "Per-ride MMP is a hypothetical first fit, not a real establishment.",
            "Observed flag rates are not validated false-positive rates or independent-rider estimates.",
            "Conservative provisional gates cannot establish physiological plausibility or prevent all tailored profiles.",
        ],
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "counts": dict(counts),
                "individual": stats(individual),
                "pooled_changed": stats(changed),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
