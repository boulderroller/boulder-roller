from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.dependencies import AuthenticatedUser
from app.routes import analytics as routes


def handler(name):
    f = getattr(routes, name)
    return getattr(f, "__wrapped__", f)


def repo(rides=(), threshold=None):
    r = AsyncMock()
    r.list_threshold_training_rides.return_value = list(rides)
    r.current_training_threshold.return_value = threshold
    r.training_settings.return_value = {}
    return r


def user():
    return AuthenticatedUser("wallet", str(uuid4()), "device")


def ride(load=64, **metrics):
    return {
        "id": "ride",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "processing_status": "completed",
        "tss": 999,
        "duration_sec": 999,
        "training_metrics": {
            "engine_version": 2,
            "load": load,
            "load_estimate": True,
            **metrics,
        },
    }


@pytest.mark.asyncio
async def test_unscored_legacy_ride_does_not_invent_fitness():
    r = repo([{**ride(), "training_metrics": None}])
    result = await handler("get_fitness_metrics")(
        request=None,
        current_user=user(),
        analytics=AsyncMock(),
        ride_repo=r,
        timezone="UTC",
    )
    assert result["ctl"] is None and result["tsb"] is None
    assert result["training_available"] is False


@pytest.mark.asyncio
async def test_snapshot_uses_frozen_hr_load_without_pay_threshold():
    r = repo([ride(load_basis="hrss")])
    u = user()
    fitness = await handler("get_fitness_metrics")(
        request=None, current_user=u, analytics=AsyncMock(), ride_repo=r, timezone="UTC"
    )
    load = await handler("get_training_load")(
        request=None, current_user=u, days=28, ride_repo=r, timezone="UTC"
    )
    assert fitness["ctl"] == 2 and fitness["atl"] == 9 and fitness["tsb"] == -7
    assert fitness["estimate"] is True and fitness["basis"] == "stored_ride_loads"
    assert load["total_tss"] == 64 and load["avg_daily_tss"] == pytest.approx(64 / 28)
    assert load["snapshot"]["fitness_metrics"]["tsb"] == fitness["tsb"]
    assert (
        load["training_available"] is True and load["threshold_state"] == "establishing"
    )
    r.get_reward_threshold_rider_projection.assert_not_awaited()


@pytest.mark.asyncio
async def test_training_threshold_estimate_exposed_without_changing_history():
    r = repo(
        [ride()], {"value": 280, "estimate": True, "basis": "threshold_cp_3_7_15_v1"}
    )
    first = await handler("get_training_load")(
        request=None, current_user=user(), days=28, ride_repo=r, timezone="UTC"
    )
    r.current_training_threshold.return_value = {
        "value": 300,
        "estimate": False,
        "basis": "ios_threshold",
    }
    second = await handler("get_training_load")(
        request=None, current_user=user(), days=28, ride_repo=r, timezone="UTC"
    )
    assert (
        first["threshold_state"] == "estimated"
        and second["threshold_state"] == "established"
    )
    assert first["total_tss"] == second["total_tss"] == 64
    assert first["training_threshold"]["estimate"] is True


@pytest.mark.asyncio
async def test_unavailable_or_bad_dates_fail_loudly():
    for rows in ([{**ride(), "started_at": "bad"}], None):
        r = repo(rows or [])
        if rows is None:
            r.list_threshold_training_rides.side_effect = RuntimeError("offline")
        with pytest.raises(HTTPException) as exc:
            await handler("get_training_load")(
                request=None, current_user=user(), days=28, ride_repo=r, timezone="UTC"
            )
        assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_calendar_preserves_zero_moving_instead_of_elapsed():
    r = repo([ride(moving_s=0)])
    result = await handler("get_riding_days")(
        request=None, days=365, current_user=user(), ride_repo=r, timezone="UTC"
    )
    assert result["days"][0]["moving_s"] == 0
    r.list_threshold_training_rides.return_value = [ride(moving_s=700)]
    again = await handler("get_riding_days")(
        request=None, days=365, current_user=user(), ride_repo=r, timezone="UTC"
    )
    assert again["days"][0]["moving_s"] == 700


@pytest.mark.asyncio
async def test_power_curve_uses_stored_engine_points_not_streams():
    r = repo([ride(power_curve_s=[180, 420, 900], power_curve_w=[350, 293, 270])])
    result = await handler("get_power_curve")(
        request=None, current_user=user(), ride_repo=r
    )
    assert result["available"] is True and result["sampledRides"] == 1
    assert result["threshold"]["anchorsW"] == {"180": 350, "420": 293, "900": 270}
    r.get_activity_stream.assert_not_awaited()
