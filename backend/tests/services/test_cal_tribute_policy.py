from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.services import ride_economic_plan_builder as builder
from app.services import workout_parse_adapter


U64_MAX = 18_446_744_073_709_551_615


def test_segment_tss_is_measured_directly_in_cal_base_units() -> None:
    calculate_segment = getattr(builder, "calculate_segment_tss_base_units")
    calculate_budget = getattr(builder, "calculate_ride_tribute_budget")

    threshold_hour = calculate_segment(
        segment_np_duration_s=3_600,
        segment_np_milliwatts=250_000,
        reward_ftp_w=250,
    )
    half_threshold_hour = calculate_segment(
        segment_np_duration_s=1_800,
        segment_np_milliwatts=250_000,
        reward_ftp_w=250,
    )
    assert threshold_hour == 100_000_000_000
    assert half_threshold_hour == 50_000_000_000
    assert calculate_budget(200_000_000_000, [threshold_hour, half_threshold_hour]) == (
        150_000_000_000
    )


def test_segment_tss_uses_squared_intensity_not_relative_allocation() -> None:
    calculate_segment = getattr(builder, "calculate_segment_tss_base_units")

    low_power = calculate_segment(
        segment_np_duration_s=300,
        segment_np_milliwatts=150_000,
        reward_ftp_w=250,
    )
    high_power = calculate_segment(
        segment_np_duration_s=300,
        segment_np_milliwatts=300_000,
        reward_ftp_w=250,
    )

    assert high_power == low_power * 4


def test_ride_budget_is_the_sum_of_independently_floored_climb_tss() -> None:
    calculate_budget = getattr(builder, "calculate_ride_tribute_budget")
    assert calculate_budget(1_000, [100, 333, 7]) == 440
    with pytest.raises(ValueError, match="exceeds full attested CAL"):
        calculate_budget(439, [100, 333, 7])


def test_missing_power_has_zero_tribute_without_a_gradient_proxy() -> None:
    calculate_segment = getattr(builder, "calculate_segment_tss_base_units")

    assert calculate_segment(
        segment_np_duration_s=300,
        segment_np_milliwatts=None,
        reward_ftp_w=250,
    ) == 0
    assert calculate_segment(
        segment_np_duration_s=300,
        segment_np_milliwatts=0,
        reward_ftp_w=250,
    ) == 0


def test_immutable_reward_ftp_changes_measured_segment_tss() -> None:
    calculate_segment = getattr(builder, "calculate_segment_tss_base_units")
    calculate_intensity = getattr(builder, "calculate_intensity_bps")

    assert calculate_intensity(
        segment_np_milliwatts=300_000, reward_ftp_w=200
    ) == 15_000
    assert calculate_intensity(
        segment_np_milliwatts=300_000, reward_ftp_w=250
    ) == 12_000
    assert calculate_segment(
        segment_np_duration_s=120,
        segment_np_milliwatts=300_000,
        reward_ftp_w=200,
    ) > calculate_segment(
        segment_np_duration_s=120,
        segment_np_milliwatts=300_000,
        reward_ftp_w=250,
    )


@pytest.mark.parametrize(
    ("cal_base_units", "segment_np_duration_s", "segment_np_milliwatts"),
    [(-1, 30, 200), (1, -1, 200), (1, 30, -1)],
)
def test_tribute_policy_rejects_negative_integer_inputs(
    cal_base_units: int,
    segment_np_duration_s: int,
    segment_np_milliwatts: int,
) -> None:
    calculate_budget = getattr(builder, "calculate_ride_tribute_budget")
    calculate_segment = getattr(builder, "calculate_segment_tss_base_units")

    if cal_base_units < 0:
        with pytest.raises(ValueError):
            calculate_budget(cal_base_units, [])
    else:
        with pytest.raises(ValueError):
            calculate_segment(
                segment_np_duration_s=segment_np_duration_s,
                segment_np_milliwatts=segment_np_milliwatts,
                reward_ftp_w=250,
            )


def test_segment_power_adapter_freezes_the_exact_window_and_missing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[int], list[int | None]]] = []

    class FakeWorkoutParse:
        METRICS_VERSION = "workout_parse_metrics_test"

        @staticmethod
        def compute_segment_power_metrics(
            time_ms: list[int], power_w: list[int | None]
        ) -> SimpleNamespace:
            calls.append((time_ms, power_w))
            return SimpleNamespace(
                normalized_power_w=247,
                normalized_power_raw_w=247.125,
                normalized_power_duration_s=3,
                power_sample_count=2,
                power_sample_coverage_bps=6_667,
                moving_time_s=3,
            )

    monkeypatch.setattr(workout_parse_adapter, "_wp", FakeWorkoutParse())

    metrics = workout_parse_adapter.calculate_segment_power_metrics_rust(
        [
            {"t": 9, "power_w": 999},
            {"t": 10, "power_w": 200},
            {"t": 11, "power_w": None},
            {"t": 12, "power_w": 0},
            {"t": 13, "power_w": 999},
        ],
        start_offset_s=10,
        end_offset_s=12,
    )

    assert calls == [([10_000, 11_000, 12_000], [200, None, 0])]
    assert metrics.normalized_power_w == 247
    assert metrics.normalized_power_milliwatts == 247_125
    assert metrics.normalized_power_duration_s == 3
    assert metrics.power_sample_count == 2
    assert metrics.power_sample_coverage_bps == 6_667
    assert metrics.moving_time_s == 3
    assert metrics.metrics_version == "workout_parse_metrics_test"


def test_segment_power_adapter_rejects_disordered_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workout_parse_adapter, "_wp", object())

    with pytest.raises(ValueError, match="monotonic"):
        workout_parse_adapter.calculate_segment_power_metrics_rust(
            [{"t": 12, "power_w": 200}, {"t": 11, "power_w": 200}],
            start_offset_s=10,
            end_offset_s=12,
        )


class _FakeVaultRepository:
    async def get_vault_by_id(self, vault_id: int) -> dict[str, object]:
        return {
            "id": vault_id,
            "signature_hex": f"{vault_id:064x}",
            "activation_status": "active",
            "on_chain_vault_pda": f"vault-{vault_id}",
            "chain_activation_active": True,
            "chain_activation_seed_generation": 2,
        }

    async def validate_climb_time(self, **_: object) -> dict[str, object]:
        return {"is_valid": True}


def _exact_binding(vault_id: int) -> dict[str, object]:
    return {
        "id": vault_id,
        "signature_hex": f"{vault_id:02x}" * 64,
        "canon_binding_status": "active",
        "canon_activation_status": "finalized",
        "canon_climb_id": "11111111-1111-1111-1111-111111111111",
        "canon_id": "22222222-2222-2222-2222-222222222222",
        "canon_version": 1,
        "canonical_profile_hash_hex": "ab" * 32,
        "expected_vault_activation_pda": "vault-activation-pda",
        "vault_activation_pda": "vault-activation-pda",
        "constructor_evidence_verified": True,
        "constructor_evidence_hash": "cd" * 32,
        "vault_activation_is_active": True,
        "vault_activation_seed_generation": 2,
        "vault_activation_seed_completions_written": 0,
        "vault_activation_leaderboard_seeded": True,
        "vault_activation_matched_users": 0,
        "vault_activation_matched_completions": 0,
        "vault_activation_created_at": 100,
        "vault_activation_activated_at": 100,
        "vault_activation_last_seed_at": 100,
        "vault_activation_seed_cutoff_at": 100,
        "vault_activation_evidence_hash": "cd" * 32,
    }


class _FakeRideExecutor:
    def __init__(self) -> None:
        self.tributes: list[int] = []

    def build_completion_evidence_v2(self, *, cal_tribute: int, **_: object) -> bytes:
        self.tributes.append(cal_tribute)
        return int(cal_tribute).to_bytes(32, "little")


class _FakeProcessor:
    def __init__(self) -> None:
        self.vault_repo = _FakeVaultRepository()
        self.ride_executor = _FakeRideExecutor()

    async def match_climbs_to_vault(self, **kwargs) -> tuple[int, list[dict]]:
        for climb in kwargs["climb_patterns"]:
            climb.canon_vault_binding = _exact_binding(climb.indexed_vault_id)
        return 0, []


def _climb(*, vault_id: int, start_s: int, gradient: float) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        indexed_vault_id=vault_id,
        economic_eligible=True,
        time_s=60,
        distance_m=600,
        vert_m=60,
        avg_gradient_pct=gradient,
        start_time_offset_s=start_s,
        end_time_offset_s=start_s + 59,
    )


@pytest.mark.asyncio
async def test_builder_attributes_each_climbs_measured_tss_not_gradient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metrics_by_start = {
        0: workout_parse_adapter.SegmentPowerMetricsCompat(
            normalized_power_w=100,
            normalized_power_milliwatts=100_000,
            normalized_power_duration_s=60,
            power_sample_count=60,
            power_sample_coverage_bps=10_000,
            moving_time_s=60,
            metrics_version="workout_parse_metrics_v1",
        ),
        60: workout_parse_adapter.SegmentPowerMetricsCompat(
            normalized_power_w=300,
            normalized_power_milliwatts=300_000,
            normalized_power_duration_s=60,
            power_sample_count=60,
            power_sample_coverage_bps=10_000,
            moving_time_s=60,
            metrics_version="workout_parse_metrics_v1",
        ),
    }
    def measured_metrics(_samples, *, start_offset_s, end_offset_s, keep_ms_relative=None):
        assert keep_ms_relative is None
        return metrics_by_start[start_offset_s]

    monkeypatch.setattr(
        builder,
        "calculate_segment_power_metrics_rust",
        measured_metrics,
        raising=False,
    )
    processor = _FakeProcessor()

    steps, allocations = await builder.build_completion_plan(
        processor,
        climb_patterns=[
            _climb(vault_id=41, start_s=0, gradient=15.0),
            _climb(vault_id=42, start_s=60, gradient=1.0),
        ],
        tile_samples=[],
        raw_climb_samples=[],
        user_id=uuid4(),
        user_wallet="rider-wallet",
        ride_id=uuid4(),
        ride_hash=b"r" * 32,
        completed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        exact_ride_cal_base_units=10_000_000_000,
        total_ride_duration_s=120,
        reward_ftp_w=250,
    )

    assert [step.exact_tribute_base_units for step in steps] == [
        266_666_666,
        2_400_000_000,
    ]
    assert [step.segment_np_w for step in steps] == [100, 300]
    assert [step.segment_np_milliwatts for step in steps] == [100_000, 300_000]
    assert [step.segment_np_duration_s for step in steps] == [60, 60]
    assert [step.tribute_weight for step in steps] == [0, 0]
    assert [step.intensity_bps for step in steps] == [4_000, 12_000]
    assert [allocation["cal_tribute"] for allocation in allocations] == [
        266_666_666,
        2_400_000_000,
    ]
    assert sum(allocation["cal_tribute"] for allocation in allocations) == (
        2_666_666_666
    )
    assert processor.ride_executor.tributes == [266_666_666, 2_400_000_000]


@pytest.mark.asyncio
async def test_builder_keeps_completion_but_assigns_zero_when_power_is_insufficient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        builder,
        "calculate_segment_power_metrics_rust",
        lambda *_args, **_kwargs: workout_parse_adapter.SegmentPowerMetricsCompat(
            normalized_power_w=250,
            normalized_power_milliwatts=250_000,
            normalized_power_duration_s=29,
            power_sample_count=29,
            power_sample_coverage_bps=10_000,
            moving_time_s=29,
            metrics_version="workout_parse_metrics_v1",
        ),
        raising=False,
    )
    processor = _FakeProcessor()

    steps, allocations = await builder.build_completion_plan(
        processor,
        climb_patterns=[_climb(vault_id=41, start_s=0, gradient=15.0)],
        tile_samples=[],
        raw_climb_samples=[],
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        user_wallet="rider-wallet",
        ride_id=UUID("00000000-0000-0000-0000-000000000002"),
        ride_hash=b"r" * 32,
        completed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
        exact_ride_cal_base_units=1_000,
        total_ride_duration_s=60,
        reward_ftp_w=250,
    )

    assert len(steps) == 1
    assert steps[0].segment_np_w is None
    assert steps[0].segment_np_milliwatts is None
    assert steps[0].segment_np_duration_s == 29
    assert steps[0].tribute_weight == 0
    assert steps[0].exact_tribute_base_units == 0
    assert allocations[0]["cal_tribute"] == 0


@pytest.mark.asyncio
async def test_builder_rejects_np_duration_beyond_the_climb_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        builder,
        "calculate_segment_power_metrics_rust",
        lambda *_args, **_kwargs: workout_parse_adapter.SegmentPowerMetricsCompat(
            normalized_power_w=250,
            normalized_power_milliwatts=250_000,
            normalized_power_duration_s=61,
            power_sample_count=60,
            power_sample_coverage_bps=10_000,
            moving_time_s=60,
            metrics_version="workout_parse_metrics_v1",
        ),
        raising=False,
    )

    with pytest.raises(ValueError, match="NP duration exceeds climb window"):
        await builder.build_completion_plan(
            _FakeProcessor(),
            climb_patterns=[_climb(vault_id=41, start_s=0, gradient=10.0)],
            tile_samples=[],
            raw_climb_samples=[],
            user_id=uuid4(),
            user_wallet="rider-wallet",
            ride_id=uuid4(),
            ride_hash=b"r" * 32,
            completed_at=datetime(2026, 7, 16, tzinfo=timezone.utc),
            exact_ride_cal_base_units=100_000_000_000,
            total_ride_duration_s=60,
            reward_ftp_w=250,
        )
