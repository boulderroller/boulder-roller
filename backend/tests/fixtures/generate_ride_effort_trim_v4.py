"""Regenerate the I5 reference from real inputs using an isolated base checkout.

PYTHONPATH=<base>/backend:<repo> python this_file.py > reference.json
The app import path selects the implementation; the input recipe stays identical.
Only persistence, external Vault matching and climb-time validation are replaced.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import timedelta
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.ride_attester import OnchainRideIdentity
from app.services.ride_effort_policy import build_ride_effort_policy
from app.services.reward_ftp import RewardFtpSnapshot
from app.services.workout_parse_adapter import (
    calculate_metrics_rust,
    parse_ride_file_bytes_rust,
)
from backend.tests.services.test_threshold_hold_measured_admission import (
    RIDE_ID,
    USER_ID,
    WALLET,
    STARTED_AT,
    _processor,
    _climb,
    _established_threshold,
)


async def compute_cases():
    cases = []
    for name, power, stale, held in (
        ("rewardable_climb", 200, False, False),
        ("not_counted_prior_file_policy", 200, True, False),
        ("not_counted_small_tss", 10, False, False),
        ("threshold_hold_climb", 200, False, True),
    ):
        points = "".join(
            f'<trkpt lat="40" lon="-75"><time>{(STARTED_AT + timedelta(seconds=i)).isoformat()}</time>'
            f"<extensions><power>{power}</power></extensions></trkpt>"
            for i in range(3600)
        )
        ride = parse_ride_file_bytes_rust(
            f'<gpx version="1.1"><trk><trkseg>{points}</trkseg></trk></gpx>'.encode(),
            "gpx",
        )
        threshold = (
            RewardFtpSnapshot.network_default() if held else _established_threshold()
        )
        metrics = calculate_metrics_rust(ride, user_ftp_w=threshold.ftp_w)
        policy = build_ride_effort_policy(
            metrics,
            started_at=ride.started_at,
            completed_at=ride.completed_at,
            now=ride.completed_at + timedelta(days=45 if stale else 0),
        )
        if stale:
            # A persisted not_counted file decision is an input, not reclassified.
            # Economic TSS still comes from native power at the verified FTP.
            policy = replace(policy, reward_policy="not_counted", review_reason=None)
        processor, repository = _processor()
        climb = _climb()
        climb.economic_eligible = policy.is_rewardable
        patterns = SimpleNamespace(climb_patterns=[climb], vault_allocations=[])
        loader = AsyncMock(
            side_effect=AssertionError("untrimmed fast path reloaded native")
        )
        kwargs = dict(
            ride_id=RIDE_ID,
            user_id=USER_ID,
            user_wallet=WALLET,
            identity=OnchainRideIdentity(b"\x12" * 32, b"\x23" * 32, 5, 1),
            effort_policy=policy,
            economic_metrics=metrics,
            started_at=ride.started_at,
            completed_at=ride.completed_at,
            total_tss=int(metrics.tss),
            total_distance_m=int(metrics.distance_m),
            total_vert_m=int(metrics.elevation_gain_m),
            total_ride_duration_s=3600,
            reward_ftp_snapshot=threshold,
            pattern_results=patterns,
            tile_samples=[],
            raw_climb_samples=[{"t": i, "power_w": power} for i in range(3600)],
        )
        if (
            "effort_spans_ms"
            in inspect.signature(processor._freeze_ride_economic_plan).parameters
        ):
            from app.services.workout_parse_adapter import effort_spans_ms_rust

            kwargs.update(
                effort_spans_ms=effort_spans_ms_rust(ride), load_native_activity=loader
            )
        result = await processor._freeze_ride_economic_plan(**kwargs)
        loader.assert_not_awaited()
        repository.freeze_plan.assert_awaited_once()
        cases.append(
            dict(
                name=name,
                power_w=power,
                tss=metrics.tss,
                payload=result[0],
                allocations=result[1],
                vault_allocations=patterns.vault_allocations,
            )
        )
    return cases


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "source_commit": "d5340381d",
                "recipe": "3600 native 1 Hz GPX power samples, real processor and climb builder; fixed identity/FTP; stale policy at +45 days",
                "cases": asyncio.run(compute_cases()),
            },
            indent=2,
        )
    )
