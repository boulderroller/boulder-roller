from copy import deepcopy
from app.notification_contracts import build_notification_insert, serialize_notification
from app.services.mobile_push import build_push_payload


def test_event_snapshot_is_retained_when_board_later_changes():
    board = dict(revision='tx:board:7', occurredAt='2026-09-08T20:00:00Z', climbId='climb-9', before=[{'wallet':'rider','place':4}], after=[])
    original = deepcopy(board)
    row = build_notification_insert(wallet='rider', notification_type='leaderboard_bumped', title='', board_snapshot=board)
    board['before'][0]['place'] = 1
    board['after'].append({'wallet':'rider','place':2})
    expected = dict(revision=original['revision'],occurredAt=original['occurredAt'],climbId='climb-9',beforePlace=4,afterPlace=None)
    assert row['metadata']['transition'] == expected
    assert serialize_notification(row)['transition'] == expected
    assert build_push_payload(row)['br']['transition'] == expected
    assert row['occurred_at'] == '2026-09-08T20:00:00+00:00'


def test_legacy_event_does_not_invent_transition_from_old_rank():
    row = build_notification_insert(wallet='rider',notification_type='leaderboard_bumped', title='',metadata={'old_rank':4,'rank':2,'climb_id':'climb-9'})
    assert serialize_notification(row)['transition'] is None
