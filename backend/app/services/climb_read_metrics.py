"""Reading-only climb metrics. Never an input to tribute or canon matching."""

import math


def climb_category(length_m, grade_pct):
    if length_m is None or grade_pct is None:
        return None
    score = float(length_m) * float(grade_pct)
    if not math.isfinite(score):
        return None
    for top, category in (
        (80000, "HC"),
        (64000, "1"),
        (32000, "2"),
        (16000, "3"),
        (8000, "4"),
    ):
        if score > top:
            return category
    return None


def retained_climb_reads(activity, patterns):
    """Replay read metrics without editing patterns or their economic bindings.

    The saved, unrounded avg-power/W-per-kg pair retains the original mass
    denominator. If it cannot recover that denominator, W/kg stays absent.
    """
    import workout_parse as wp
    from .training_metrics import ENGINE_VERSION

    reads = {}
    for pattern in patterns:
        start, end = pattern.get("start_offset_s"), pattern.get("end_offset_s")
        bounds_valid = start is not None and end is not None and end > start >= 0
        avg = (
            wp.compute_training_metrics(
                activity,
                0,
                engine_version=ENGINE_VERSION,
                start_s=math.floor(start),
                end_s=math.ceil(end),
            ).avg_power_w
            if bounds_valid
            else None
        )
        old_power, old_wkg = pattern.get("avg_power_w"), pattern.get("w_per_kg")
        mass = (
            old_power / old_wkg
            if old_power and old_wkg and old_power > 0 and old_wkg > 0
            else None
        )
        reads[str(pattern["id"])] = {
            "avg_power_w": avg,
            "w_per_kg": avg / mass if avg is not None and mass else None,
            "basis": "training_engine_span",
            "weight_basis": "retained_pattern_denominator" if mass else None,
        }
    return reads
