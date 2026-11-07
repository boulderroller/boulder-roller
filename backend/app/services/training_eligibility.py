"""The ride population shared by riding days, Training reads and replay."""

COUNTED_STATUSES = frozenset({"metrics_ready", "enriched", "completed", "under_review"})


def is_training_eligible(ride):
    return ride.get("processing_status") in COUNTED_STATUSES
