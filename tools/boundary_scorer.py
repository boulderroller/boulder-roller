#!/usr/bin/env python3
"""Score climb boundary quality against human annotations.

Loads annotations from tools/annotations/*.json, runs the persistence
detector + optional enrichment on each ride, and scores:

1. Boundary error: |detector_boundary - annotated_boundary| in samples
2. False positive rate: detected climbs the user skipped
3. False negative rate: annotated climbs the detector missed (future)

Usage:
    # Score current detector (no enrichment)
    python tools/boundary_scorer.py

    # Score with road enrichment applied
    python tools/boundary_scorer.py --enrich

    # Verbose: show per-climb details
    python tools/boundary_scorer.py -v
"""

import argparse
import gzip
import json
import math
import os
import sys
import tempfile

# Add backend to path for road enrichment
BACKEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
sys.path.insert(0, BACKEND_DIR)

import workout_parse as wp

ANNOTATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "annotations")
ACTIVITIES_DIR = "/Users/gabetemp/Downloads/Code/export_440100/activities"

# Chamounix ride: chart downsample mapping broke annotations for laps 2-7
UNRELIABLE_ANNOTATIONS = {
    "1573845543": [1, 2, 3, 4, 5, 6],  # only climb #0 (first lap) is reliable
}


def load_annotations():
    """Load all annotation files."""
    annotations = {}
    for fname in os.listdir(ANNOTATIONS_DIR):
        if not fname.endswith(".json"):
            continue
        ride_id = fname.replace(".json", "")
        with open(os.path.join(ANNOTATIONS_DIR, fname)) as f:
            annotations[ride_id] = json.load(f)
    return annotations


def parse_ride(ride_id):
    """Parse a ride file and return samples."""
    candidates = [
        f"{ride_id}.gpx", f"{ride_id}.fit.gz", f"{ride_id}.fit",
        f"{ride_id}.gpx.gz", f"{ride_id}.tcx.gz", f"{ride_id}.tcx",
    ]

    filepath = None
    for c in candidates:
        path = os.path.join(ACTIVITIES_DIR, c)
        if os.path.exists(path):
            filepath = path
            break

    if not filepath:
        return None

    # Handle gzip
    if filepath.endswith(".gz"):
        with gzip.open(filepath, "rb") as gz:
            data = gz.read()
        ext = os.path.splitext(filepath.replace(".gz", ""))[1]
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(data)
        tmp.close()
        actual = tmp.name
    else:
        actual = filepath

    activity = wp.parse_file(actual)

    if actual != filepath:
        os.unlink(actual)

    n = len(activity.time_ms)
    samples = []
    for i in range(n):
        s = {
            "t": activity.time_ms[i] // 1000,
            "elevation_m": float(activity.elevation_m[i])
            if activity.elevation_m is not None and i < len(activity.elevation_m)
            else None,
        }
        if activity.lat_e7 is not None and i < len(activity.lat_e7):
            s["lat"] = activity.lat_e7[i] / 1e7
            s["lon"] = activity.lon_e7[i] / 1e7
        samples.append(s)

    return samples


def detect_and_score(ride_id, annot, samples, use_enrichment=False, verbose=False):
    """Run detector on a ride and score against annotations.

    Uses proximity-based matching: each annotated climb is matched to the
    detected climb whose midpoint is closest to the annotation's reference
    point (annotated midpoint for real climbs, detector midpoint for FPs).
    This is robust to changes in climb count from parameter tuning.
    """
    climbs_raw = wp.detect_climbs_persistence(samples, user_weight_kg=75.0)

    # Build climb list with effort indices
    climbs = []
    for c in climbs_raw:
        climbs.append({
            "effort_start_idx": c.effort_start_idx,
            "effort_end_idx": c.effort_end_idx,
            "vert_m": c.vert_m,
        })

    # Optionally apply road enrichment to refine boundaries
    if use_enrichment:
        try:
            from app.services.road_enrichment import enrich_climbs
            enrichments = enrich_climbs(climbs_raw, samples)
            for i, e in enumerate(enrichments):
                if i < len(climbs):
                    if e.suppressed:
                        climbs[i]["suppressed"] = True
                    # Apply onset-anchored boundary refinement
                    if e.refined_start is not None:
                        climbs[i]["effort_start_idx"] = e.refined_start
                    if e.refined_end is not None:
                        climbs[i]["effort_end_idx"] = e.refined_end
            # Remove suppressed climbs from detection list
            climbs = [c for c in climbs if not c.get("suppressed")]
        except Exception as ex:
            if verbose:
                print(f"  Road enrichment failed: {ex}")

    # Get unreliable indices for this ride
    unreliable = set(UNRELIABLE_ANNOTATIONS.get(ride_id, []))

    # Score each annotated climb
    results = {
        "ride_id": ride_id,
        "n_detected": len(climbs),
        "n_annotated": 0,
        "n_skipped": 0,
        "n_unreliable": len(unreliable),
        "start_errors": [],
        "end_errors": [],
        "false_positives": 0,
        "climb_details": [],
    }

    # Track which detected climbs have been matched to avoid double-matching
    matched_det_indices = set()

    def find_best_match(ref_start, ref_end):
        """Find detected climb that best overlaps with reference range.

        Uses the annotation's original detector_start/detector_end as reference.
        Matches by overlap fraction: what fraction of the reference range is covered
        by the detected climb. Falls back to midpoint proximity if no overlap.
        """
        ref_mid = (ref_start + ref_end) / 2
        ref_len = max(ref_end - ref_start, 1)

        best_idx = None
        best_score = -float("inf")

        for i, det in enumerate(climbs):
            if i in matched_det_indices:
                continue
            ds = det["effort_start_idx"]
            de = det["effort_end_idx"]

            # Compute overlap
            overlap_start = max(ref_start, ds)
            overlap_end = min(ref_end, de)
            overlap = max(0, overlap_end - overlap_start)
            overlap_frac = overlap / ref_len

            # Score: overlap fraction (0-1) minus distance penalty for non-overlapping
            det_mid = (ds + de) / 2
            dist = abs(det_mid - ref_mid) / max(ref_len, 1)

            if overlap > 0:
                score = 1000 + overlap_frac  # Overlap strongly preferred
            else:
                score = -dist  # Penalize distance when no overlap

            if score > best_score:
                best_score = score
                best_idx = i

        return best_idx, best_score

    for ac in annot["climbs"]:
        idx = ac["idx"]

        if idx in unreliable:
            continue

        ref_start = ac["detector_start"]
        ref_end = ac["detector_end"]

        if ac["skipped"]:
            # For false positives, find match using original detector range
            det_idx, score = find_best_match(ref_start, ref_end)

            if det_idx is not None and score > -5:
                det = climbs[det_idx]
                # Verify vert_m is plausible (within 2x of original)
                vert_ratio = det["vert_m"] / max(ac["vert_m"], 0.1)
                if 0.3 <= vert_ratio <= 3.0:
                    matched_det_indices.add(det_idx)
                    results["n_skipped"] += 1
                    results["false_positives"] += 1
                    results["climb_details"].append({
                        "idx": det_idx,
                        "road_name": ac.get("road_name"),
                        "verdict": "FALSE_POSITIVE",
                        "vert_m": det["vert_m"],
                    })
            # If no match found, FP was eliminated by parameter change — not counted
            continue

        ann_s = ac.get("annotated_start")
        ann_e = ac.get("annotated_end")

        if ann_s is None or ann_e is None:
            continue

        # For real climbs, match using original detector range as reference
        det_idx, score = find_best_match(ref_start, ref_end)

        if det_idx is None or score < -10:
            # No plausible match — this is a false negative
            continue

        det = climbs[det_idx]
        matched_det_indices.add(det_idx)

        results["n_annotated"] += 1

        start_err = det["effort_start_idx"] - ann_s  # negative = too early
        end_err = det["effort_end_idx"] - ann_e      # positive = too late

        results["start_errors"].append(start_err)
        results["end_errors"].append(end_err)

        results["climb_details"].append({
            "idx": det_idx,
            "road_name": ac.get("road_name"),
            "verdict": "ANNOTATED",
            "det_start": det["effort_start_idx"],
            "det_end": det["effort_end_idx"],
            "ann_start": ann_s,
            "ann_end": ann_e,
            "start_err": start_err,
            "end_err": end_err,
        })

    return results


def compute_summary(all_results):
    """Compute aggregate score across all rides."""
    total_start_errors = []
    total_end_errors = []
    total_annotated = 0
    total_false_pos = 0
    total_detected = 0
    total_skipped = 0

    for r in all_results:
        total_start_errors.extend(r["start_errors"])
        total_end_errors.extend(r["end_errors"])
        total_annotated += r["n_annotated"]
        total_false_pos += r["false_positives"]
        total_detected += r["n_detected"]
        total_skipped += r["n_skipped"]

    def stats(errors):
        if not errors:
            return {"mean": 0, "median": 0, "mae": 0, "rmse": 0, "n": 0}
        errors_sorted = sorted(errors)
        n = len(errors)
        mae = sum(abs(e) for e in errors) / n
        rmse = math.sqrt(sum(e * e for e in errors) / n)
        median = errors_sorted[n // 2]
        mean = sum(errors) / n
        return {
            "mean": round(mean, 1),
            "median": median,
            "mae": round(mae, 1),
            "rmse": round(rmse, 1),
            "n": n,
        }

    return {
        "n_rides": len(all_results),
        "n_detected": total_detected,
        "n_annotated": total_annotated,
        "n_false_positives": total_false_pos,
        "false_positive_rate": round(total_false_pos / max(total_detected, 1), 2),
        "start_errors": stats(total_start_errors),
        "end_errors": stats(total_end_errors),
    }


def main():
    parser = argparse.ArgumentParser(description="Score climb boundaries against annotations")
    parser.add_argument("--enrich", action="store_true", help="Apply road enrichment")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show per-climb details")
    args = parser.parse_args()

    annotations = load_annotations()
    print(f"Loaded {len(annotations)} annotation files")

    all_results = []

    for ride_id, annot in sorted(annotations.items()):
        samples = parse_ride(ride_id)
        if samples is None:
            print(f"  {ride_id}: source file not found, skipping")
            continue

        result = detect_and_score(ride_id, annot, samples, args.enrich, args.verbose)
        all_results.append(result)

        if args.verbose:
            print(f"\n=== {ride_id} ({result['n_detected']} detected) ===")
            for cd in result["climb_details"]:
                if cd["verdict"] == "FALSE_POSITIVE":
                    print(f"  #{cd['idx']+1:2d} {cd['road_name'] or '':25s} FALSE POSITIVE ({cd['vert_m']:.1f}m)")
                else:
                    print(
                        f"  #{cd['idx']+1:2d} {cd['road_name'] or '':25s} "
                        f"start_err={cd['start_err']:+5d}  end_err={cd['end_err']:+5d}"
                    )

    summary = compute_summary(all_results)

    print(f"\n{'='*60}")
    print(f"BOUNDARY SCORE SUMMARY")
    print(f"{'='*60}")
    print(f"Rides scored:        {summary['n_rides']}")
    print(f"Climbs detected:     {summary['n_detected']}")
    print(f"Climbs annotated:    {summary['n_annotated']}")
    print(f"False positives:     {summary['n_false_positives']} ({summary['false_positive_rate']:.0%})")
    print()
    print(f"START boundary error (negative = too early):")
    s = summary["start_errors"]
    print(f"  Mean: {s['mean']:+.1f}  Median: {s['median']:+d}  MAE: {s['mae']:.1f}  RMSE: {s['rmse']:.1f}  (n={s['n']})")
    print()
    print(f"END boundary error (positive = too late):")
    e = summary["end_errors"]
    print(f"  Mean: {e['mean']:+.1f}  Median: {e['median']:+d}  MAE: {e['mae']:.1f}  RMSE: {e['rmse']:.1f}  (n={e['n']})")
    print()

    # Composite score: lower is better
    # Weighted: start errors matter more (user complaint), false positives are costly
    composite = s["mae"] + e["mae"] * 0.5 + summary["n_false_positives"] * 50
    print(f"COMPOSITE SCORE: {composite:.0f}  (lower is better)")
    print(f"  = start_MAE({s['mae']:.0f}) + 0.5*end_MAE({e['mae']:.0f}) + 50*FP({summary['n_false_positives']})")


if __name__ == "__main__":
    main()
