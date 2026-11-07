from datetime import datetime, timezone
from functools import wraps
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.services.ride_effort_trim import (
    normalize,
    subtract,
    intersect,
    EffortTrim,
    resolve_effort_trim,
    completion_window_ms,
)
from app.services.ride_effort_policy import (
    build_ride_effort_policy,
    build_paid_effort_policy,
)


def test_canonical_arithmetic():
    assert normalize([(20, 40), (0, 20), (30, 50)]) == [(0, 50)]
    assert subtract([(0, 100)], [(20, 40), (60, 80)]) == [(0, 20), (40, 60), (80, 100)]
    assert intersect([(0, 100)], [(20, 40)]) == [(20, 40)]


@pytest.mark.asyncio
async def test_fast_path_and_frozen_empty_never_load():
    loader = AsyncMock(side_effect=AssertionError("unexpected reload"))
    repo = SimpleNamespace(
        get_effort_trim_basis=AsyncMock(
            return_value={
                "frozen": None,
                "covered_spans_ms": [],
                "covered_completion_windows": [],
            }
        )
    )
    trim = await resolve_effort_trim(
        repository=repo,
        ride_id="r",
        user_id="u",
        effort_ms=[(0, 3600000)],
        load_native_activity=loader,
        reward_ftp_w=200,
    )
    assert trim.paid_ms == trim.effort_ms and trim.paid_metrics is None
    repo.get_effort_trim_basis.return_value = {
        "frozen": {
            "effort_spans_ms": [[0, 3600000]],
            "paid_spans_ms": [],
            "covered_spans_ms": [[0, 3600000]],
        },
        "covered_spans_ms": [[0, 3600000]],
        "covered_completion_windows": [],
    }
    trim = await resolve_effort_trim(
        repository=repo,
        ride_id="r",
        user_id="u",
        effort_ms=[(0, 3600000)],
        load_native_activity=loader,
        reward_ftp_w=200,
    )
    assert trim.paid_ms == [] and trim.frozen


def test_paid_idle_gate_counts_boundary_interval_without_bridging_removed_time():
    from datetime import timedelta
    from app.services.ride_idle_evidence import assess_idle_recording

    start = datetime(2026, 9, 25, tzinfo=timezone.utc)
    records = [
        SimpleNamespace(timestamp=start + timedelta(seconds=i), speed_mps=0)
        for i in range(121)
    ]
    ms = int(start.timestamp() * 1000)
    evidence = assess_idle_recording(
        records, keep_ms=[(ms, ms + 40000), (ms + 45000, ms + 65000)]
    )
    assert evidence.recorded_duration_s == 60
    assert evidence.stationary_duration_s == 40


def native_ride(start=0, seconds=3600, power=200):
    from datetime import timedelta
    from app.services.workout_parse_adapter import parse_ride_file_bytes_rust

    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=12)
    base = base.replace(minute=0, second=0)
    points = "".join(
        f'<trkpt lat="40" lon="-75"><time>{(base+timedelta(seconds=start+i)).isoformat()}</time><extensions><power>{power(i) if callable(power) else power}</power><speed>0</speed></extensions></trkpt>'
        for i in range(seconds)
    )
    return parse_ride_file_bytes_rust(
        f'<gpx version="1.1"><trk><trkseg>{points}</trkseg></trk></gpx>'.encode(), "gpx"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "pieces",
    [
        [(0, 720), (576, 720), (1152, 720), (1728, 720), (2304, 720)],
        [(0, 3600), (600, 360)],
        [(0, 3600), (3590, 3610)],
        [(0, 3600), (7200, 3600), (3500, 3800)],
        [(0, 1800), (1800, 1800), (0, 3600)],
    ],
)
async def test_native_chain_slice_handover_and_out_of_order(pieces):
    from app.services.workout_parse_adapter import (
        effort_spans_ms_rust,
        calculate_metrics_rust,
    )

    coverage = []
    paid_total = 0
    cal = 0
    for start, n in pieces:
        ride = native_ride(start, n)
        effort = effort_spans_ms_rust(ride)
        repo = SimpleNamespace(
            get_effort_trim_basis=AsyncMock(
                return_value={
                    "frozen": None,
                    "covered_spans_ms": coverage,
                    "covered_completion_windows": [],
                }
            )
        )
        trim = await resolve_effort_trim(
            repository=repo,
            ride_id="r",
            user_id="u",
            effort_ms=effort,
            load_native_activity=AsyncMock(return_value=ride),
            reward_ftp_w=200,
        )
        policy = build_paid_effort_policy(
            build_ride_effort_policy(
                calculate_metrics_rust(ride, user_ftp_w=200),
                started_at=ride.started_at,
                completed_at=ride.completed_at,
            ),
            trim,
            started_at=ride.started_at,
            completed_at=ride.completed_at,
        )
        assert not intersect(trim.paid_ms, coverage)
        coverage = normalize(coverage + trim.paid_ms)
        paid_total += sum(b - a for a, b in trim.paid_ms) // 1000
        cal += policy.rewardable_cal_base_units
    ridden = (
        sum(
            b - a for a, b in normalize([(a * 1000, (a + n) * 1000) for a, n in pieces])
        )
        // 1000
    )
    assert paid_total == ridden
    assert cal == round(ridden * 100 / 3600, 1) * 1_000_000_000


@pytest.mark.asyncio
async def test_empty_claim_replay_and_short_remainder_have_identical_payload():
    from app.services.workout_parse_adapter import (
        effort_spans_ms_rust,
        calculate_metrics_rust,
    )

    ride = native_ride(0, 3600)
    effort = effort_spans_ms_rust(ride)
    start, end = effort[0]
    repo = SimpleNamespace(
        get_effort_trim_basis=AsyncMock(
            return_value={
                "frozen": None,
                "covered_spans_ms": [(start, end - 20000)],
                "covered_completion_windows": [],
            }
        )
    )
    trim = await resolve_effort_trim(
        repository=repo,
        ride_id="r",
        user_id="u",
        effort_ms=effort,
        load_native_activity=AsyncMock(return_value=ride),
        reward_ftp_w=200,
    )
    file = build_ride_effort_policy(
        calculate_metrics_rust(ride, user_ftp_w=200),
        started_at=ride.started_at,
        completed_at=ride.completed_at,
    )
    policy = build_paid_effort_policy(
        file, trim, started_at=ride.started_at, completed_at=ride.completed_at
    )
    assert policy.reward_policy == "not_counted" and trim.paid_ms == []
    first = trim.payload()
    repo.get_effort_trim_basis.return_value = {
        "frozen": {
            "effort_spans_ms": effort,
            "paid_spans_ms": [],
            "covered_spans_ms": [(start, end - 20000)],
        },
        "covered_spans_ms": effort,
        "covered_completion_windows": [],
    }
    replay = await resolve_effort_trim(
        repository=repo,
        ride_id="r",
        user_id="u",
        effort_ms=effort,
        load_native_activity=AsyncMock(return_value=ride),
        reward_ftp_w=200,
    )
    build_paid_effort_policy(
        file, replay, started_at=ride.started_at, completed_at=ride.completed_at
    )
    assert replay.payload() == first


@pytest.mark.asyncio
async def test_missing_native_evidence_only_reviews_when_trim_needed():
    from app.services.ride_effort_trim import PaidEffortEvidenceUnavailableError

    async def missing():
        raise PaidEffortEvidenceUnavailableError("missing file")

    repo = SimpleNamespace(
        get_effort_trim_basis=AsyncMock(
            return_value={
                "frozen": None,
                "covered_spans_ms": [(0, 1000)],
                "covered_completion_windows": [],
            }
        )
    )
    with pytest.raises(PaidEffortEvidenceUnavailableError):
        await resolve_effort_trim(
            repository=repo,
            ride_id="r",
            user_id="u",
            effort_ms=[(0, 3600000)],
            load_native_activity=missing,
            reward_ftp_w=200,
        )


def test_frozen_paid_policy_does_not_age_out_on_retry():
    from datetime import timedelta
    from app.services.workout_parse_adapter import (
        calculate_paid_metrics_rust,
        effort_spans_ms_rust,
        calculate_metrics_rust,
    )

    ride = native_ride()
    effort = effort_spans_ms_rust(ride)
    start, end = effort[0]
    metrics, paid = calculate_paid_metrics_rust(ride, [(start + 1800000, end)], 200)
    policy = build_ride_effort_policy(
        calculate_metrics_rust(ride, user_ftp_w=200),
        started_at=ride.started_at,
        completed_at=ride.completed_at,
    )
    trim = EffortTrim(effort, paid, paid_metrics=metrics, frozen=True)
    result = build_paid_effort_policy(
        policy,
        trim,
        started_at=ride.started_at - timedelta(days=60),
        completed_at=ride.completed_at - timedelta(days=60),
    )
    assert (
        result.reward_policy == "rewardable"
        and result.rewardable_cal_base_units == 50_000_000_000
    )


@pytest.mark.asyncio
async def test_untrimmed_pause_climb_keeps_existing_sample_evidence():
    from uuid import uuid4
    from backend.tests.services.test_cal_tribute_policy import _FakeProcessor, _climb
    from app.services import ride_economic_plan_builder as builder
    from app.services.ride_effort_trim import epoch_ms

    start = datetime(2026, 9, 25, tzinfo=timezone.utc)
    origin = epoch_ms(start)
    times = list(range(41)) + [100] + list(range(200, 241))
    climb = _climb(vault_id=41, start_s=0, gradient=5)
    climb.end_time_offset_s = 240
    climb.time_s = 240
    args = dict(
        climb_patterns=[climb],
        tile_samples=[],
        raw_climb_samples=[{"t": i, "power_w": 200} for i in times],
        user_id=uuid4(),
        user_wallet="wallet",
        ride_id=uuid4(),
        ride_hash=b"r" * 32,
        completed_at=start,
        exact_ride_cal_base_units=100_000_000_000,
        total_ride_duration_s=241,
        reward_ftp_w=200,
    )
    old, _ = await builder.build_completion_plan(_FakeProcessor(), **args)
    effort = [(origin, origin + 41000), (origin + 200000, origin + 241000)]
    new, _ = await builder.build_completion_plan(
        _FakeProcessor(),
        **args,
        effort_trim=EffortTrim(effort, effort),
        ride_started_at=start,
    )
    assert new == old and new[0].segment_power_sample_count == 83


@pytest.mark.asyncio
@pytest.mark.parametrize("covered", [1800, 3600])
async def test_processor_retries_and_replay_hash_stays_identical(covered):
    from uuid import uuid4
    from app.services.ride_processor import RideProcessor
    from app.services.ride_attester import OnchainRideIdentity
    from app.services.reward_ftp import RewardFtpSnapshot
    from app.services.ride_economic_plan import freeze_ride_economic_plan
    from app.repositories.ride_economic import StaleEffortCoverageError
    from app.services.workout_parse_adapter import (
        effort_spans_ms_rust,
        calculate_metrics_rust,
    )
    from backend.tests.services.test_ride_economic_coordinator import RecordingExecutor

    ride = native_ride()
    effort = effort_spans_ms_rust(ride)
    start, end = effort[0]
    metrics = calculate_metrics_rust(ride, user_ftp_w=200)
    file_policy = build_ride_effort_policy(
        metrics, started_at=ride.started_at, completed_at=ride.completed_at
    )
    frozen = None
    calls = []
    basis_calls = 0

    async def basis(**kwargs):
        nonlocal basis_calls
        basis_calls += 1
        # A competitor commits while the first draft is priced.
        return {
            "frozen": frozen,
            "covered_spans_ms": (
                [] if basis_calls == 1 else [(start, start + covered * 1000)]
            ),
            "covered_completion_windows": [],
        }

    async def freeze(**kwargs):
        nonlocal frozen
        if not calls:
            calls.append(kwargs["plan"])
            raise StaleEffortCoverageError("race")
        calls.append(kwargs["plan"])
        frozen = {
            k: kwargs["plan"]["effort_trim"][k]
            for k in ("effort_spans_ms", "paid_spans_ms")
        }
        frozen["covered_spans_ms"] = [(start, start + covered * 1000)]
        return kwargs["plan"]

    repo = SimpleNamespace(get_effort_trim_basis=basis, freeze_plan=freeze)

    async def submit(draft):
        return await freeze_ride_economic_plan(
            repository=repo, executor=RecordingExecutor(), draft=draft
        )

    processor = SimpleNamespace(
        ride_economic_repository=repo,
        ride_economic_coordinator=SimpleNamespace(freeze_plan=submit),
    )
    args = dict(
        ride_id=uuid4(),
        user_id=uuid4(),
        user_wallet="wallet-1",
        identity=OnchainRideIdentity(b"r" * 32, b"r" * 32, 1, 1),
        effort_policy=file_policy,
        economic_metrics=metrics,
        effort_spans_ms=effort,
        load_native_activity=AsyncMock(return_value=ride),
        started_at=ride.started_at,
        completed_at=ride.completed_at,
        total_tss=100,
        total_distance_m=0,
        total_vert_m=0,
        total_ride_duration_s=3600,
        reward_ftp_snapshot=RewardFtpSnapshot(
            200,
            "derived_eftp",
            "reward_ftp_policy_2026_08_24_threshold_v1",
            str(uuid4()),
        ),
        pattern_results=None,
        tile_samples=[],
        raw_climb_samples=[],
    )
    first = await RideProcessor._freeze_ride_economic_plan(processor, **args)
    replay = await RideProcessor._freeze_ride_economic_plan(processor, **args)
    assert len(calls) == 3 and basis_calls == 3
    assert first[0]["plan_evidence_hash_hex"] == replay[0]["plan_evidence_hash_hex"]
    assert first[0]["exact_cal_base_units"] == (
        50_000_000_000 if covered == 1800 else 0
    )


@pytest.mark.asyncio
async def test_partly_paid_climb_and_held_release_use_only_paid_seconds():
    from uuid import uuid4
    from app.services.ride_effort_trim import epoch_ms
    from app.services.workout_parse_adapter import (
        calculate_paid_metrics_rust,
        effort_spans_ms_rust,
    )
    from app.services import ride_economic_plan_builder as builder
    from app.services.threshold_release_planner import (
        build_threshold_hold_evidence,
        ThresholdReleasePlanner,
    )
    from backend.tests.services.test_threshold_release_planner import (
        _claim,
        RecordingRepository,
        DeterministicExecutor,
    )
    from backend.tests.services.test_cal_tribute_policy import _FakeProcessor, _climb

    ride = native_ride()
    effort = effort_spans_ms_rust(ride)
    start, end = effort[0]
    metrics, paid = calculate_paid_metrics_rust(ride, [(start + 1800000, end)], 200)
    trim = EffortTrim(effort, paid, paid_metrics=metrics)
    args = dict(
        climb_patterns=[
            _climb(vault_id=41, start_s=1770, gradient=5),
            _climb(vault_id=42, start_s=1700, gradient=5),
        ],
        tile_samples=[],
        raw_climb_samples=[{"t": i, "power_w": 200} for i in range(3600)],
        user_id=uuid4(),
        user_wallet="wallet",
        ride_id=uuid4(),
        ride_hash=b"r" * 32,
        completed_at=ride.completed_at,
        exact_ride_cal_base_units=50_000_000_000,
        total_ride_duration_s=3600,
        reward_ftp_w=200,
        effort_trim=trim,
        ride_started_at=ride.started_at,
    )
    steps, _ = await builder.build_completion_plan(_FakeProcessor(), **args)
    assert (
        len(steps) == 1
        and steps[0].vault_id == 41
        and steps[0].segment_np_duration_s == 30
    )
    assert steps[0].completion_time_s == 60
    evidence = build_threshold_hold_evidence(
        metrics=metrics,
        completion_steps=steps,
        effort_trim=trim,
        started_at=ride.started_at,
        completed_at=ride.completed_at,
    )
    assert (
        evidence["version"] == 2
        and evidence["metrics"]["normalized_power_duration_s"] == 1800
    )
    claim = _claim()
    claim["hold_evidence"] = evidence
    claim["admitted_at"] = ride.completed_at.isoformat()
    claim["established_at"] = ride.completed_at.isoformat()
    planner = ThresholdReleasePlanner(
        repository=RecordingRepository(claim), executor=DeterministicExecutor()
    )
    snapshot, released = planner._build_snapshot(claim)
    assert (
        snapshot["exact_cal_base_units"] == 32_000_000_000
    )  # 1800 s at 200 W, established FTP 250 W.
    assert len(released) == 1
    trim.covered_completion_windows = [
        {"vault_id": 41, "start_ms": start + 1770000, "end_ms": start + 1830000}
    ]
    deduped, _ = await builder.build_completion_plan(_FakeProcessor(), **args)
    assert deduped == []


@pytest.mark.asyncio
async def test_climb_above_paid_budget_is_typed_review_without_cap():
    from uuid import uuid4
    from app.services.ride_effort_trim import ClimbTributeExceedsPaidCalError, epoch_ms
    from app.services import ride_economic_plan_builder as builder
    from backend.tests.services.test_cal_tribute_policy import _FakeProcessor, _climb

    started = datetime(2026, 9, 25, tzinfo=timezone.utc)
    origin = epoch_ms(started)
    trim = EffortTrim([(origin, origin + 120000)], [(origin + 60000, origin + 120000)])
    with pytest.raises(ClimbTributeExceedsPaidCalError):
        await builder.build_completion_plan(
            _FakeProcessor(),
            climb_patterns=[_climb(vault_id=41, start_s=60, gradient=5)],
            tile_samples=[],
            raw_climb_samples=[{"t": i, "power_w": 1000} for i in range(120)],
            user_id=uuid4(),
            user_wallet="wallet",
            ride_id=uuid4(),
            ride_hash=b"r" * 32,
            completed_at=started,
            exact_ride_cal_base_units=1_000_000_000,
            total_ride_duration_s=120,
            reward_ftp_w=200,
            effort_trim=trim,
            ride_started_at=started,
        )


@pytest.mark.asyncio
async def test_paid_idle_gate_cannot_be_diluted_by_covered_riding():
    from uuid import uuid4
    from app.services.ride_processor import RideProcessor
    from app.services.ride_attester import OnchainRideIdentity
    from app.services.reward_ftp import RewardFtpSnapshot
    from app.services.ride_idle_evidence import assess_idle_recording
    from app.services.workout_parse_adapter import (
        effort_spans_ms_rust,
        calculate_metrics_rust,
    )

    ride = native_ride(power=lambda i: 200 if i < 1800 else (0 if i < 3500 else 1000))
    effort = effort_spans_ms_rust(ride)
    start, end = effort[0]
    assert assess_idle_recording(ride.records).review_reason is None
    metrics = calculate_metrics_rust(ride, user_ftp_w=200)
    repo = SimpleNamespace(
        get_effort_trim_basis=AsyncMock(
            return_value={
                "frozen": None,
                "covered_spans_ms": [(start, start + 1800000)],
                "covered_completion_windows": [],
            }
        )
    )
    coordinator = SimpleNamespace(freeze_plan=AsyncMock())
    processor = SimpleNamespace(
        ride_economic_repository=repo, ride_economic_coordinator=coordinator
    )
    result = await RideProcessor._freeze_ride_economic_plan(
        processor,
        ride_id=uuid4(),
        user_id=uuid4(),
        user_wallet="wallet",
        identity=OnchainRideIdentity(b"r" * 32, b"r" * 32, 1, 1),
        effort_policy=build_ride_effort_policy(
            metrics, started_at=ride.started_at, completed_at=ride.completed_at
        ),
        economic_metrics=metrics,
        effort_spans_ms=effort,
        load_native_activity=AsyncMock(return_value=ride),
        started_at=ride.started_at,
        completed_at=ride.completed_at,
        total_tss=int(metrics.tss),
        total_distance_m=0,
        total_vert_m=0,
        total_ride_duration_s=3600,
        reward_ftp_snapshot=RewardFtpSnapshot.network_default(),
        pattern_results=None,
        tile_samples=[],
        raw_climb_samples=[],
    )
    assert (
        result[0] is None
        and result[2].review_reason == "implausible_stationary_recording"
    )
    coordinator.freeze_plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_untrimmed_serializer_preserves_supplied_v4_fields():
    """Reference payloads were produced by the actual d5340381d V4 builder."""
    import json
    from pathlib import Path
    from dataclasses import fields
    from uuid import UUID
    from app.services.ride_attester import OnchainRideIdentity
    from app.services.ride_economic_plan import (
        RideEconomicPlanDraft,
        freeze_ride_economic_plan,
    )
    from app.services.ride_effort_trim import epoch_ms
    from backend.tests.services.test_ride_economic_coordinator import RecordingExecutor

    reference = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/ride_effort_trim_v4_untrimmed.json"
        ).read_text()
    )
    for case in reference["cases"]:
        old = case["plan"]
        args = {
            f.name: old[f.name] for f in fields(RideEconomicPlanDraft) if f.name in old
        }
        for key in ("ride_id", "user_id"):
            args[key] = UUID(args[key])
        for key in ("started_at", "completed_at"):
            args[key] = datetime.fromisoformat(args[key])
        effort = [(epoch_ms(args["started_at"]), epoch_ms(args["completed_at"]))]
        args.update(
            identity=OnchainRideIdentity(b"r" * 32, b"r" * 32, 1, 1),
            completion_steps=[],
            effort_trim=EffortTrim(effort, effort),
        )
        repo = SimpleNamespace(
            freeze_plan=AsyncMock(side_effect=lambda **kwargs: kwargs)
        )
        current = await freeze_ride_economic_plan(
            repository=repo,
            executor=RecordingExecutor(),
            draft=RideEconomicPlanDraft(**args),
        )
        assert current["steps"] == case["steps"]
        assert current["plan"]["effort_trim"]["paid_metrics"] is None
        assert (
            current["plan"]["plan_evidence_hash_hex"] != old["plan_evidence_hash_hex"]
        )
        assert {
            k: v
            for k, v in current["plan"].items()
            if k not in ("effort_trim", "plan_evidence_hash_hex")
        } == {k: v for k, v in old.items() if k != "plan_evidence_hash_hex"}


def test_fully_covered_replay_keeps_zero_estimated_projection():
    from app.services.ride_effort_policy import RideEffortPolicy
    from app.services.ride_processor import _snapshot_file_policy
    saved=RideEffortPolicy('power_verified','not_counted',0,0,0)
    assert _snapshot_file_policy(saved,100,None)==saved


@pytest.mark.asyncio
async def test_untrimmed_processor_matches_v4_cal_tss_climbs_and_hold_evidence():
    import json
    from copy import deepcopy
    from pathlib import Path
    from backend.tests.fixtures.generate_ride_effort_trim_v4 import compute_cases

    reference = json.loads(
        (
            Path(__file__).parents[1] / "fixtures/ride_effort_trim_v4_processor.json"
        ).read_text()
    )
    actual = await compute_cases()
    for old, new in zip(reference["cases"], actual, strict=True):
        assert new["tss"] == old["tss"]
        expected, computed = deepcopy(old), deepcopy(new)
        for case in (expected, computed):
            plan = case["payload"]["plan"]
            plan.pop("effort_trim", None)
            plan.pop("plan_evidence_hash_hex")
            hold = case["payload"].get("threshold_hold")
            if hold:
                hold.pop("admission_plan_evidence_hash_hex")
                hold["hold_evidence"].pop("effort_trim", None)
        assert computed == expected, old["name"]
    assert actual[0]["payload"]["steps"]
    assert actual[1]["payload"]["plan"]["total_tss"] == int(actual[1]["tss"]) > 0
    assert actual[1]["payload"]["plan"]["exact_cal_base_units"] == 0
    assert actual[3]["payload"]["threshold_hold"]["hold_evidence"]["completion_steps"]


def test_trimmed_native_bindings_preserve_error_types():
    import workout_parse as wp

    with pytest.raises(wp.ParseError):
        wp.compute_segment_power_metrics_in_spans([1000, 0], [200, 200], [(0, 2000)])
    with pytest.raises(wp.DurationLimitExceeded):
        wp.compute_segment_power_metrics_in_spans(
            [0, 172801000], [200, 200], [(0, 172802000)]
        )


def test_trimmed_segment_adapter_guards_missing_native_binding(monkeypatch):
    from app.services import workout_parse_adapter as adapter

    monkeypatch.setattr(adapter, "_get_workout_parse", lambda: SimpleNamespace())
    with pytest.raises(RuntimeError, match="canonical climb-window power metrics"):
        adapter.calculate_segment_power_metrics_rust(
            [], start_offset_s=0, end_offset_s=59, keep_ms_relative=[(0, 60000)]
        )


@pytest.mark.asyncio
async def test_frozen_effort_integrity_has_a_distinct_error():
    from app.services.ride_effort_trim import PaidEffortEvidenceMismatchError

    repo = SimpleNamespace(
        get_effort_trim_basis=AsyncMock(
            return_value={
                "frozen": {
                    "effort_spans_ms": [[0, 1000]],
                    "paid_spans_ms": [],
                    "covered_spans_ms": [],
                },
                "covered_spans_ms": [],
                "covered_completion_windows": [],
            }
        )
    )
    with pytest.raises(PaidEffortEvidenceMismatchError, match="stored effort differs"):
        await resolve_effort_trim(
            repository=repo,
            ride_id="r",
            user_id="u",
            effort_ms=[(0, 2000)],
            load_native_activity=AsyncMock(),
            reward_ftp_w=200,
        )


@pytest.mark.asyncio
async def test_processor_passes_climb_windows_to_each_trim_basis_read(monkeypatch):
    from app.services.ride_processor import RideProcessor
    from backend.tests.fixtures.generate_ride_effort_trim_v4 import compute_cases

    freeze = RideProcessor._freeze_ride_economic_plan
    expected_reads = []

    @wraps(freeze)
    async def checked_freeze(self, **kwargs):
        expected = [
            list(completion_window_ms(
                kwargs["started_at"], climb.start_time_offset_s, climb.end_time_offset_s
            ))
            for climb in kwargs["pattern_results"].climb_patterns
        ]
        result = await freeze(self, **kwargs)
        reads = self.ride_economic_repository.get_effort_trim_basis.await_args_list
        assert reads
        for read in reads:
            assert read.kwargs["completion_spans_ms"] == expected
        expected_reads.append(expected)
        return result

    monkeypatch.setattr(RideProcessor, "_freeze_ride_economic_plan", checked_freeze)
    await compute_cases()
    assert len(expected_reads) == 4
