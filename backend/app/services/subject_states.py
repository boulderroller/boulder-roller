"""Subject-scoped observations; an absent fact never inherits a ride-wide state."""
from typing import Any

from .ride_effort_policy import (
    PARTLY_COUNTED_COPY, ALREADY_COUNTED_COPY,
)


def ride_subject_states(ride: dict[str, Any]) -> dict[str, dict[str, str | None]]:
    states: dict[str, dict[str, str | None]] = {}
    if ride.get('id'):
        states['storage'] = {'state': 'saved', 'reason': 'ride_stored'}
    if ride.get('phase2_completed_at') and not ride.get('phase2_error'):
        states['matching'] = {'state': 'finalized', 'reason': 'phase2_completed'}
    elif ride.get('phase2_error'):
        states['matching'] = {'state': 'needs_review', 'reason': 'phase2_error'}
    elif ride.get('processing_status') in ('processing', 'metrics_ready'):
        states['matching'] = {'state': 'counting', 'reason': 'matching_pending'}

    policy = ride.get('reward_policy')
    threshold = ride.get('threshold_economy_state')
    reason = ride.get('review_reason')
    if (ride.get('covered_effort_seconds') or 0) > 0 and ride.get('paid_effort_seconds') == 0 and policy == 'not_counted':
        states['cal'] = {'state': 'not_counted', 'reason': ALREADY_COUNTED_COPY or None}
        return states
    if threshold == 'held' or policy == 'threshold_provisional_hold_v1':
        return states
    if threshold == 'review' or policy == 'manual_review':
        states['cal'] = {'state': 'needs_review', 'reason': reason or 'manual_review'}
    elif threshold in ('lapsed', 'not_counted') or policy in ('not_counted', 'estimated_only'):
        states['cal'] = {'state': 'not_counted', 'reason': reason or threshold or policy}
    elif ride.get('finalized_at') and ride.get('cal_earned') is not None:
        states['cal'] = {'state': 'finalized', 'reason': 'settlement_finalized'}
    if (
        PARTLY_COUNTED_COPY
        and states.get("cal", {}).get("state") == "finalized"
        and (ride.get("covered_effort_seconds") or 0) > 0
        and (ride.get("paid_effort_seconds") or 0) > 0
    ):
        states['cal']['reason'] = PARTLY_COUNTED_COPY
    # Attestation, a held amount, active LP, or uncollected DUNG alone does not
    # authorize a word for CAL, position or collection.
    return states
