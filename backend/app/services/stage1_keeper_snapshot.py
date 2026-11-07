"""Build an immutable measurement from admitted receipts and boundary archives.

Current indexer rows are not historical inputs. Opening backing/live state and
closing record seats must already have finalized boundary evidence in the new
archive. No fallback to today's seats, wall clock, user wallet or ride creation.
"""
from collections import Counter
from datetime import datetime, timezone

from solders.pubkey import Pubkey

from .stage1_keeper_merkle import digest, uint

WEEK, DAY = 604800, 86400


def recipient_people(snapshot, held_people=()):
    return set(snapshot["board"]) | set(snapshot["ascents"]) | set(held_people) | {l['owner'] for l in snapshot.get('opening',{}).get('dung', {}).get('lots', [])} | {r['person'] for r in snapshot.get('boost_rides', [])} | ({snapshot["legend"]} if snapshot["legend"] else set())


def bind_recipients(snapshot, registrations, held_people=()):
    """Attach exact registrations to this frozen measurement, without rereading rides."""
    snapshot = {k: v for k, v in snapshot.items() if k not in ("commitment", "commitment_inputs")}
    recipients = {}
    for person in recipient_people(snapshot, held_people):
        registration = registrations.get(person)
        if not registration or registration["registered_at"] > snapshot["registration_cutoff"]:
            continue
        Pubkey.from_string(registration["recipient"])
        recipients[person] = registration["recipient"]
    snapshot["recipients"] = recipients
    snapshot["commitment_inputs"] = {"schema": 2, "context": snapshot["context"],
        "components": {k: digest(v) for k,v in snapshot.items() if k != "context"}}
    snapshot["commitment"] = digest(snapshot["commitment_inputs"])
    return snapshot


def freeze_records(closing):
    """Freeze seat order before identity erasure; anonymous keys cannot be sorted as pubkeys."""
    if "seats" in closing:
        return closing
    closing = dict(closing)
    records, close = closing["board"], closing["boundary"]
    if len(records) > 10 or len({r["person"] for r in records}) != len(records):
        raise ValueError("invalid frozen record seats")
    for r in records:
        uint(r["time_s"], 32)
        if r["time_s"] == 0 or not 0 < r["recorded_at"] < close:
            raise ValueError("invalid record provenance")
    closing["seats"] = [r["person"] for r in sorted(records, key=lambda r: (r["time_s"], r["recorded_at"], bytes(Pubkey.from_string(r["person"]))))]
    term = closing["legend"]
    closing["earned_legend"] = term["person"] if term and term["active"] and not term["bootstrap"] and term["term_start"] < close <= term["term_end"] else None
    return closing


def build_snapshot(inputs, rows, history=()):
    launch, week = uint(inputs["launch"]), uint(inputs["context"][3])
    date = datetime.fromtimestamp(launch, timezone.utc)
    if date.weekday() != 0 or (date.hour, date.minute, date.second) != (12, 0, 0):
        raise ValueError("city launch must be Monday 12:00 UTC")
    start, close = launch + week * WEEK, launch + (week + 1) * WEEK
    for name, at in (("opening", start), ("closing", close)):
        boundary = inputs.get(name)
        if not boundary or boundary.get("boundary") != at or boundary.get("commitment") != "finalized" or not boundary.get("evidence") or not boundary.get("slot"):
            raise ValueError(f"missing finalized {name} boundary evidence")
    opening, closing = inputs["opening"], freeze_records(inputs["closing"])
    if type(opening.get("live")) is not bool or closing["slot"] < opening["slot"]:
        raise ValueError("invalid frozen opening")
    if inputs.get("kind") != "dung" and inputs["context"][4] not in closing["assets"]:
        raise ValueError("asset not admitted at close")
    # History is already admitted by this builder and frozen in the database.
    # Its coarse week/paid-ascent facts survive erasure without private times.
    accepted, rejected = [dict(r) for r in history], []
    receipts = {r["receipt"] for r in accepted}
    historical_receipts = set(receipts)
    first = {r["ride_day_key"] for r in accepted if r.get("ride_day_key")}
    def micros(row, name):
        return uint(row.get(name + "_us", row[name] * 1_000_000))
    for row in sorted(rows, key=lambda r: (micros(r, "uploaded_at"), r["receipt"].encode())):
        if row["receipt"] in historical_receipts:
            continue
        if row["receipt"] in receipts:
            raise ValueError("duplicate admitted receipt")
        reason = None
        ride_at, upload_at = micros(row, "ridden_at"), micros(row, "uploaded_at")
        if row["canon_id"] != inputs["canon_id"]:
            continue
        if upload_at >= (close + DAY) * 1_000_000:
            continue
        if row.get("trusted") is not True or not row.get("evidence"):
            reason = "untrusted_time_or_receipt"
        elif ride_at < launch * 1_000_000 or not 0 <= upload_at - ride_at <= WEEK * 1_000_000:
            reason = "upload_age"
        elif micros(row, "verified_at") >= (launch + ((upload_at // 1_000_000 - launch) // WEEK + 1) * WEEK + DAY) * 1_000_000:
            reason = "unverified_at_upload_week_grace"
        if reason:
            rejected.append({"receipt": row["receipt"], "reason": reason})
            continue
        Pubkey.from_string(row["person"])
        receipts.add(row["receipt"])
        day_key = digest([inputs["context"][2], row["person"], ride_at // (DAY * 1_000_000)])
        bond = inputs.get('admission_bond')
        if bond and (bond.get('hill') != inputs['context'][2] or bond.get('city') != inputs['context'][1]
                     or not bond.get('evidence') or bond.get('now',0) < close+DAY
                     or bond.get('slot',0) < closing['slot'] or type(bond.get('bonded')) is not bool):
            raise ValueError('invalid admission bond provenance')
        accepted.append({**row, "admitted_week": (upload_at // 1_000_000-launch)//WEEK,
                         "ride_day_key": day_key, "paid_ascent": day_key not in first,
                         "ride_week": (ride_at//1_000_000-launch)//WEEK,
                         "boost_eligible": max(upload_at,micros(row,'verified_at')) < (launch+((ride_at//1_000_000-launch)//WEEK+1)*WEEK+DAY)*1_000_000,
                         **({'post_bond':bond['bonded'] and ride_at >= bond['bonded_at']*1_000_000,
                             'bond_eligibility_digest':digest(bond)} if bond else {})})
        first.add(day_key)
    weekly = [r for r in accepted if r["admitted_week"] == week]
    ascents = Counter(r["person"] for r in weekly if r["paid_ascent"])
    field_people = sorted({r["person"] for r in accepted if (week//26)*26 <= r["admitted_week"] <= week}, key=lambda p: p.encode())
    board, legend = closing["seats"], closing["earned_legend"]
    snapshot = {"schema": 2, "context": inputs["context"], "canon_id": inputs["canon_id"], "launch": launch,
                "opening": opening, "closing": closing, "live": opening["live"],
                "field": len(field_people) >= 5, "field_people": field_people,
                "rides": weekly, "admissions": accepted,
                "boost_rides": [r for r in accepted if r['paid_ascent'] and r.get('ride_week')==week and r.get('boost_eligible')], "ascents": dict(ascents), "board": board, "legend": legend,
                "registration_cutoff": inputs.get("freeze_at", close), "rejected": rejected}
    if inputs.get('admission_bond'):
        snapshot['admission_bond'] = inputs['admission_bond']
    people = set(ascents)|set(board)|({legend} if legend else set())
    snapshot['rider_tie_ranks'] = inputs.get('rider_tie_ranks') or (
        {p:i for i,p in enumerate(sorted(people,key=lambda p:p.encode()))} if not any(p.startswith('anonymous:') for p in people) else None)
    return bind_recipients(snapshot, inputs["recipients"], inputs.get("held_people", ()))


# Canon traversal, including hills without a CAL vault. The on-chain hill bond
# authenticates scope.canon_id; frozen ride identity and exact gate evidence bind
# the canonical result. CAL economics and vault activation are not admission.
COMPLETIONS_SQL = """
SELECT cp.id::text AS receipt, cc.canon_id::text AS canon_id, p.wallet AS person,
 jsonb_build_object('evidence',to_jsonb(e), 'ride_id',r.id::text, 'ride_hash',encode(p.ride_hash,'hex'),
 'parser_version',p.parser_version,'reward_ftp_w',p.reward_ftp_w,
 'started_at_ms',floor(extract(epoch FROM p.started_at)*1000)::bigint,
 'paid_spans_ms',CASE WHEN to_jsonb(p)->>'paid_spans' IS NULL THEN NULL ELSE
 (SELECT coalesce(jsonb_agg(jsonb_build_array(floor(extract(epoch FROM lower(span))*1000)::bigint,
 floor(extract(epoch FROM upper(span))*1000)::bigint)),'[]'::jsonb) FROM unnest((to_jsonb(p)->>'paid_spans')::tstzmultirange) span) END,
 'start_offset',cp.match_trace->'gate_crossings'->'start_time_s_raw',
 'end_offset',cp.match_trace->'gate_crossings'->'finish_time_s_raw','time_s',cp.time_s) AS _power,
 floor(extract(epoch from r.upload_verified_at))::bigint AS uploaded_at,
 floor(extract(epoch from moment.ridden_at))::bigint AS ridden_at,
 floor(extract(epoch from greatest(cp.created_at,r.phase2_completed_at,p.attestation_confirmed_at)))::bigint AS verified_at,
 floor(extract(epoch from r.upload_verified_at)*1000000)::bigint AS uploaded_at_us,
 floor(extract(epoch from moment.ridden_at)*1000000)::bigint AS ridden_at_us,
 floor(extract(epoch from greatest(cp.created_at,r.phase2_completed_at,p.attestation_confirmed_at))*1000000)::bigint AS verified_at_us,
 encode(digest(e.sample_digest || cp.match_trace::text || encode(p.attestation_commitment,'hex'),'sha256'),'hex') AS evidence,
 (moment.ridden_at BETWEEN p.started_at AND p.completed_at
  AND (cp.match_trace->'monotonic_progress'->>'accepted')::boolean IS TRUE) AS trusted
FROM public.patterns_climb cp
JOIN public.rides r ON r.id=cp.activity_id
JOIN public.ride_economic_plans p ON p.ride_id=r.id AND p.wallet=cp.wallet
JOIN public.canon_traversal_evidence e ON e.ride_id=r.id
 AND e.ride_hash_hex=encode(p.ride_hash,'hex') AND e.ride_parser_version=p.parser_version
 AND e.evidence_version='canon_traversal_evidence_v1'
JOIN public.canon_climbs cc ON cc.id::text=cp.match_trace->>'registry_id'
 AND cc.canon_id::text=cp.match_trace->>'canon_id'
 AND cc.version::text=cp.match_trace->>'canon_version'
CROSS JOIN LATERAL (SELECT p.started_at +
 (cp.match_trace->'gate_crossings'->>'finish_time_s_raw')::numeric * interval '1 second' AS ridden_at) moment
WHERE cc.canon_id=$1::uuid AND cc.status IN ('ratified','retired')
 AND cp.detector_version='canon_traversal_v1'
 AND cp.match_trace->>'trace_version'='canon_traversal_trace_v1'
 AND coalesce(cp.match_trace->>'authority','') <> 'discovery_only'
 AND cp.created_at IS NOT NULL AND r.phase2_completed_at IS NOT NULL
 AND p.attestation_confirmed_at IS NOT NULL AND p.attestation_actual_tx_signature IS NOT NULL
 AND r.upload_verified_at IS NOT NULL
 AND r.upload_verified_at < to_timestamp($2)
"""
