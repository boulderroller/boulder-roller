"""Frozen database rows, not real rider evidence."""
import copy

import pytest
from solders.pubkey import Pubkey

from app.services.stage1_keeper_snapshot import build_snapshot, bind_recipients

LAUNCH = 1791201600
WEEK, DAY = 604800, 86400
PEOPLE = [str(Pubkey.from_bytes(bytes([i + 1]) * 32)) for i in range(12)]


def inputs(week=1):
    return {"context": ["program", "city", "hill", week, "mint"], "launch": LAUNCH,
            "canon_id": "canon", "opening": {"live": True, "boundary": LAUNCH + week * WEEK,
                "commitment": "finalized", "slot": 20, "evidence": "11" * 32},
            "closing": {"boundary": LAUNCH + (week + 1) * WEEK, "commitment": "finalized", "slot": 50,
                "evidence": "22" * 32, "board": [], "legend": None, "assets": ["mint"]},
            "recipients": {p: {"recipient": p, "registered_at": LAUNCH} for p in PEOPLE}}


def ride(person=0, uploaded=None, ridden=None, receipt="receipt"):
    uploaded = uploaded if uploaded is not None else LAUNCH + WEEK + 100
    return {"receipt": receipt, "canon_id": "canon", "person": PEOPLE[person],
            "uploaded_at": uploaded, "ridden_at": uploaded - 60 if ridden is None else ridden,
            "verified_at": uploaded, "trusted": True, "evidence": "33" * 32}


def test_exact_recipient_binding_preserves_the_frozen_measurement():
    data, rows = inputs(), [ride(), ride(person=1, receipt='second')]
    frozen = build_snapshot({**data, 'recipients': {}}, rows)
    original = copy.deepcopy(frozen)
    registrations = copy.deepcopy(data['recipients'])
    registrations[PEOPLE[1]]['registered_at'] = frozen['registration_cutoff'] + 1
    rebound = bind_recipients(frozen, registrations, [PEOPLE[5]])
    assert rebound == build_snapshot({**data, 'recipients': registrations, 'held_people': [PEOPLE[5]]}, rows)
    assert frozen == original and set(rebound['recipients']) == {PEOPLE[0], PEOPLE[5]}
    for name in frozen.keys() - {'recipients', 'commitment', 'commitment_inputs'}:
        assert rebound[name] == frozen[name]


def test_late_upload_and_cross_week_daily_ownership():
    first = ride(uploaded=LAUNCH + WEEK - 1, ridden=LAUNCH + WEEK - 60, receipt="first")
    second = ride(ridden=LAUNCH + WEEK - 60, receipt="second")
    s = build_snapshot(inputs(), [second, first])
    assert s["ascents"] == {}
    assert [r["receipt"] for r in s["rides"]] == ["second"]


@pytest.mark.parametrize("age,admitted", [(0, True), (604800, True), (604801, False), (-1, False)])
def test_upload_age_exact_edges(age, admitted):
    r = ride(ridden=LAUNCH + WEEK + 100 - age)
    assert bool(build_snapshot(inputs(), [r])["rides"]) == admitted


def test_season_field_distinct_reset_and_threshold():
    rows = [ride(i, receipt=f"r{i}") for i in range(5)]
    assert build_snapshot(inputs(), rows)["field"]
    assert not build_snapshot(inputs(), rows[:4])["field"]
    assert not build_snapshot(inputs(26), rows)["field"]


def test_board_order_bootstrap_and_delayed_finalizer():
    data = inputs()
    data["closing"]["board"] = [{"person": p, "time_s": 60, "recorded_at": LAUNCH + 10} for p in reversed(PEOPLE[:5])]
    data["closing"]["legend"] = {"person": PEOPLE[0], "bootstrap": True, "active": True,
                                    "term_start": LAUNCH, "term_end": LAUNCH + 9 * WEEK}
    a = build_snapshot(data, [])
    assert a["board"] == sorted(PEOPLE[:5], key=lambda p: bytes(Pubkey.from_string(p)))
    assert a["legend"] is None
    b = copy.deepcopy(data)
    b["recipients"][PEOPLE[0]]["registered_at"] = LAUNCH + 3 * WEEK
    assert PEOPLE[0] not in build_snapshot(b, [])["recipients"]


def test_missing_historical_truth_is_blocked():
    data = inputs()
    del data["opening"]
    with pytest.raises(ValueError, match="opening"):
        build_snapshot(data, [])


def test_canonical_commitment_is_input_order_independent():
    rows = [ride(i, receipt=f"r{i}") for i in range(5)]
    assert build_snapshot(inputs(), rows) == build_snapshot(inputs(), list(reversed(rows)))


def test_subsecond_age_is_not_rounded_into_admission():
    row = ride(ridden=LAUNCH + 100)
    row.update(ridden_at_us=(LAUNCH + 100)*1_000_000, uploaded_at_us=(LAUNCH + WEEK + 100)*1_000_000+1)
    assert not build_snapshot(inputs(), [row])["rides"]


def test_prelaunch_board_and_grace_registration():
    data = inputs()
    data["closing"]["board"] = [{"person": PEOPLE[0], "time_s": 60, "recorded_at": LAUNCH - WEEK}]
    data["freeze_at"] = LAUNCH + 2*WEEK + DAY
    data["recipients"][PEOPLE[0]]["registered_at"] = LAUNCH + 2*WEEK + 1
    assert build_snapshot(data, [])["board"] == [PEOPLE[0]]


@pytest.mark.parametrize("lag,admitted", [(1, True), (86400, False), (86399, True)])
def test_last_day_upload_processing_uses_fixed_close_plus_grace(lag, admitted):
    close = LAUNCH + 2*WEEK
    row = ride(uploaded=close-1, ridden=close-DAY)
    row["verified_at"] = close+lag
    assert bool(build_snapshot(inputs(), [row])["rides"]) == admitted


def test_missing_recipient_does_not_discard_or_block_riding():
    data = inputs()
    data["recipients"] = {}
    snapshot = build_snapshot(data, [ride()])
    assert snapshot["ascents"] == {PEOPLE[0]: 1} and snapshot["recipients"] == {}


def test_commitment_can_be_rehashed_after_private_preimages_are_removed():
    from app.services.stage1_keeper_merkle import digest
    snapshot = build_snapshot(inputs(), [ride()])
    original = snapshot["commitment"]
    snapshot["rides"] = []
    snapshot["ascents"] = {"anonymous:erased": 1}
    snapshot["recipients"] = {}
    assert digest(snapshot["commitment_inputs"]) == original
