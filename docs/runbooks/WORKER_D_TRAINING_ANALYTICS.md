# Worker D: Training Analytics

> **Priority:** P4
> **Estimated Scope:** 5 tasks
> **Dependencies:** None (independent workstream)
> **Branch:** `feat/training-analytics`

---

## Overview

Implement training analytics features that serious cyclists expect. Currently, only lifetime totals are tracked. This workstream adds CTL/ATL/TSB fitness modeling, power zones, and training trends.

---

## Tasks

### ANALYTICS-401: CTL/ATL/TSB Fitness Modeling

**Current:** Only total TSS tracked, no fitness modeling

**Required:**
- **CTL (Chronic Training Load):** 42-day exponentially weighted TSS average
- **ATL (Acute Training Load):** 7-day exponentially weighted TSS average
- **TSB (Training Stress Balance):** CTL - ATL (form indicator)

**Database Schema:**
```sql
-- backend/sql/019_training_analytics.sql

-- Daily TSS aggregation for efficient queries
CREATE TABLE daily_training_load (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    total_tss NUMERIC NOT NULL DEFAULT 0,
    ride_count INT NOT NULL DEFAULT 0,
    total_duration_sec INT NOT NULL DEFAULT 0,
    total_distance_m NUMERIC NOT NULL DEFAULT 0,
    UNIQUE(user_id, date)
);

CREATE INDEX idx_dtl_user_date ON daily_training_load(user_id, date DESC);

-- Materialized fitness metrics (updated daily)
CREATE TABLE fitness_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    ctl NUMERIC NOT NULL DEFAULT 0,  -- Chronic Training Load (42-day)
    atl NUMERIC NOT NULL DEFAULT 0,  -- Acute Training Load (7-day)
    tsb NUMERIC NOT NULL DEFAULT 0,  -- Training Stress Balance (CTL - ATL)
    ramp_rate NUMERIC,               -- Weekly CTL change
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, date)
);

CREATE INDEX idx_fm_user_date ON fitness_metrics(user_id, date DESC);
```

**Backend Implementation:**
```python
# backend/app/services/fitness_analytics.py
from datetime import date, timedelta
from typing import List, Optional
import math

class FitnessAnalyticsService:
    # Time constants for exponential weighted averages
    CTL_TIME_CONSTANT = 42  # days
    ATL_TIME_CONSTANT = 7   # days

    async def calculate_fitness_metrics(
        self,
        user_id: str,
        target_date: date = None
    ) -> dict:
        """
        Calculate CTL, ATL, TSB for a user on a given date.

        Uses exponentially weighted moving averages:
        - CTL = yesterday's CTL + (today's TSS - yesterday's CTL) * (1 - e^(-1/42))
        - ATL = yesterday's ATL + (today's TSS - yesterday's ATL) * (1 - e^(-1/7))
        - TSB = CTL - ATL
        """
        target_date = target_date or date.today()

        # Get previous day's metrics
        yesterday = target_date - timedelta(days=1)
        prev_metrics = await self.repo.get_fitness_metrics(user_id, yesterday)

        prev_ctl = float(prev_metrics.get("ctl", 0)) if prev_metrics else 0
        prev_atl = float(prev_metrics.get("atl", 0)) if prev_metrics else 0

        # Get today's TSS
        daily_load = await self.repo.get_daily_training_load(user_id, target_date)
        today_tss = float(daily_load.get("total_tss", 0)) if daily_load else 0

        # Calculate decay factors
        ctl_decay = 1 - math.exp(-1 / self.CTL_TIME_CONSTANT)
        atl_decay = 1 - math.exp(-1 / self.ATL_TIME_CONSTANT)

        # Update CTL and ATL using EWA formula
        new_ctl = prev_ctl + (today_tss - prev_ctl) * ctl_decay
        new_atl = prev_atl + (today_tss - prev_atl) * atl_decay
        new_tsb = new_ctl - new_atl

        # Calculate ramp rate (weekly CTL change)
        week_ago = target_date - timedelta(days=7)
        week_ago_metrics = await self.repo.get_fitness_metrics(user_id, week_ago)
        week_ago_ctl = float(week_ago_metrics.get("ctl", 0)) if week_ago_metrics else 0
        ramp_rate = new_ctl - week_ago_ctl

        return {
            "date": target_date.isoformat(),
            "ctl": round(new_ctl, 1),
            "atl": round(new_atl, 1),
            "tsb": round(new_tsb, 1),
            "ramp_rate": round(ramp_rate, 1),
            "form": self._get_form_status(new_tsb)
        }

    def _get_form_status(self, tsb: float) -> str:
        """Interpret TSB as form status."""
        if tsb > 25:
            return "fresh"      # Well rested, ready to perform
        elif tsb > 5:
            return "form"       # Good form, race ready
        elif tsb > -10:
            return "neutral"    # Maintaining
        elif tsb > -30:
            return "tired"      # Accumulated fatigue
        else:
            return "exhausted"  # Risk of overtraining

    async def get_fitness_history(
        self,
        user_id: str,
        days: int = 90
    ) -> List[dict]:
        """Get fitness metrics history for charting."""
        end_date = date.today()
        start_date = end_date - timedelta(days=days)

        return await self.repo.get_fitness_metrics_range(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date
        )

    async def update_daily_aggregates(self, user_id: str, ride_date: date) -> None:
        """Update daily aggregates after a ride is processed."""
        rides = await self.repo.get_user_rides_for_date(user_id, ride_date)

        total_tss = sum(float(r.get("tss", 0)) for r in rides)
        total_duration = sum(int(r.get("duration_sec", 0)) for r in rides)
        total_distance = sum(float(r.get("distance_m", 0)) for r in rides)

        await self.repo.upsert_daily_training_load(
            user_id=user_id,
            date=ride_date,
            total_tss=total_tss,
            ride_count=len(rides),
            total_duration_sec=total_duration,
            total_distance_m=total_distance
        )

        # Recalculate fitness metrics for this date and forward
        await self._recalculate_fitness_forward(user_id, ride_date)

    async def _recalculate_fitness_forward(self, user_id: str, from_date: date) -> None:
        """Recalculate fitness metrics from a date forward to today."""
        current = from_date
        today = date.today()

        while current <= today:
            metrics = await self.calculate_fitness_metrics(user_id, current)
            await self.repo.upsert_fitness_metrics(
                user_id=user_id,
                date=current,
                ctl=metrics["ctl"],
                atl=metrics["atl"],
                tsb=metrics["tsb"],
                ramp_rate=metrics.get("ramp_rate")
            )
            current += timedelta(days=1)
```

**API Endpoints:**
```python
# backend/app/routes/analytics.py
from fastapi import APIRouter, Depends, Query
from datetime import date, timedelta

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/fitness")
async def get_fitness_metrics(
    current_user: AuthenticatedUser = Depends(get_current_user),
    analytics: FitnessAnalyticsService = Depends(get_analytics_service),
):
    """Get current fitness metrics (CTL/ATL/TSB)."""
    metrics = await analytics.calculate_fitness_metrics(current_user.user_id)
    return metrics


@router.get("/fitness/history")
async def get_fitness_history(
    days: int = Query(90, le=365),
    current_user: AuthenticatedUser = Depends(get_current_user),
    analytics: FitnessAnalyticsService = Depends(get_analytics_service),
):
    """Get fitness metrics history for charting."""
    history = await analytics.get_fitness_history(current_user.user_id, days)
    return {"history": history, "days": days}


@router.get("/training-load")
async def get_training_load(
    days: int = Query(28, le=365),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get daily training load summary."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    daily_loads = await repo.get_daily_training_loads(
        user_id=current_user.user_id,
        start_date=start_date,
        end_date=end_date
    )

    return {
        "daily_loads": daily_loads,
        "total_tss": sum(d.get("total_tss", 0) for d in daily_loads),
        "avg_daily_tss": sum(d.get("total_tss", 0) for d in daily_loads) / max(len(daily_loads), 1)
    }
```

---

### ANALYTICS-402: Power Zones

**Current:** FTP stored but zones not calculated

**Standard 7-Zone Model:**
```
Zone 1 (Recovery):      <55% FTP
Zone 2 (Endurance):     55-75% FTP
Zone 3 (Tempo):         75-90% FTP
Zone 4 (Threshold):     90-105% FTP
Zone 5 (VO2max):        105-120% FTP
Zone 6 (Anaerobic):     120-150% FTP
Zone 7 (Neuromuscular): >150% FTP
```

**Implementation:**
```python
# backend/app/services/zones.py
from typing import List, Dict, Optional
from dataclasses import dataclass

@dataclass
class PowerZone:
    zone: int
    name: str
    description: str
    min_watts: int
    max_watts: Optional[int]
    min_pct: float
    max_pct: Optional[float]
    color: str

class ZonesService:
    ZONE_DEFINITIONS = [
        (1, "Recovery", "Active recovery", 0, 0.55, "#CCCCCC"),
        (2, "Endurance", "Aerobic base building", 0.55, 0.75, "#66B3FF"),
        (3, "Tempo", "Muscular endurance", 0.75, 0.90, "#00CC66"),
        (4, "Threshold", "Lactate threshold", 0.90, 1.05, "#FFCC00"),
        (5, "VO2max", "Aerobic capacity", 1.05, 1.20, "#FF6600"),
        (6, "Anaerobic", "Anaerobic capacity", 1.20, 1.50, "#FF3333"),
        (7, "Neuromuscular", "Sprint power", 1.50, None, "#CC00CC"),
    ]

    def calculate_power_zones(self, ftp: int) -> List[PowerZone]:
        """Calculate power zones based on FTP."""
        zones = []
        for zone_num, name, desc, min_pct, max_pct, color in self.ZONE_DEFINITIONS:
            min_watts = int(ftp * min_pct)
            max_watts = int(ftp * max_pct) if max_pct else None

            zones.append(PowerZone(
                zone=zone_num,
                name=name,
                description=desc,
                min_watts=min_watts,
                max_watts=max_watts,
                min_pct=min_pct,
                max_pct=max_pct,
                color=color
            ))

        return zones

    def get_zone_for_power(self, power: float, ftp: int) -> int:
        """Determine which zone a given power value falls into."""
        pct_ftp = power / ftp

        for zone_num, _, _, min_pct, max_pct, _ in self.ZONE_DEFINITIONS:
            if max_pct is None or pct_ftp < max_pct:
                if pct_ftp >= min_pct:
                    return zone_num

        return 7  # Anything above 150% is Zone 7

    async def calculate_zone_distribution(
        self,
        power_data: List[float],
        ftp: int,
        timestamps: List[float] = None
    ) -> Dict[int, dict]:
        """
        Calculate time spent in each power zone.

        Returns dict with zone number as key and stats as value.
        """
        zones = {z: {"time_sec": 0, "pct": 0} for z in range(1, 8)}
        total_time = 0

        # If no timestamps, assume 1-second samples
        if timestamps is None:
            for power in power_data:
                if power > 0:
                    zone = self.get_zone_for_power(power, ftp)
                    zones[zone]["time_sec"] += 1
                    total_time += 1
        else:
            # Use actual time deltas
            for i, power in enumerate(power_data):
                if power > 0 and i > 0:
                    delta = timestamps[i] - timestamps[i-1]
                    zone = self.get_zone_for_power(power, ftp)
                    zones[zone]["time_sec"] += delta
                    total_time += delta

        # Calculate percentages
        if total_time > 0:
            for zone in zones:
                zones[zone]["pct"] = round(zones[zone]["time_sec"] / total_time * 100, 1)

        return zones
```

**Add to ride processing:**
```python
# In backend/app/services/ride_metrics.py

async def calculate_zone_distribution(
    self,
    ride_id: str,
    user_id: str
) -> dict:
    """Calculate power zone distribution for a ride."""
    # Get user's FTP
    user = await self.repo.get_user_by_id(user_id)
    ftp = user.get("ftp_w", 200)

    # Get power stream
    power_stream = await self.repo.get_activity_stream(ride_id, "power")
    if not power_stream or not power_stream.get("values"):
        return None

    zones_service = ZonesService()
    distribution = await zones_service.calculate_zone_distribution(
        power_data=power_stream["values"],
        ftp=ftp,
        timestamps=power_stream.get("timestamps")
    )

    return {
        "ftp_used": ftp,
        "zones": distribution
    }
```

**API Endpoint:**
```python
@router.get("/zones")
async def get_power_zones(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get user's power zones based on their FTP."""
    user = await repo.get_full_user_profile(current_user.wallet)
    ftp = user.get("ftp_w", 200)

    zones_service = ZonesService()
    zones = zones_service.calculate_power_zones(ftp)

    return {
        "ftp": ftp,
        "zones": [z.__dict__ for z in zones]
    }

@router.get("/rides/{ride_id}/zones")
async def get_ride_zone_distribution(
    ride_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    metrics_service: RideMetricsService = Depends(get_metrics_service),
):
    """Get power zone distribution for a specific ride."""
    distribution = await metrics_service.calculate_zone_distribution(
        ride_id=ride_id,
        user_id=current_user.user_id
    )

    if not distribution:
        raise HTTPException(404, "No power data available for this ride")

    return distribution
```

---

### ANALYTICS-404: Training Load Trends

**Implementation:**
```python
@router.get("/trends/weekly")
async def get_weekly_trends(
    weeks: int = Query(12, le=52),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get weekly training summary trends."""
    end_date = date.today()
    start_date = end_date - timedelta(weeks=weeks)

    # Get daily loads
    daily_loads = await repo.get_daily_training_loads(
        user_id=current_user.user_id,
        start_date=start_date,
        end_date=end_date
    )

    # Group by week
    weekly = {}
    for load in daily_loads:
        load_date = load["date"]
        week_start = load_date - timedelta(days=load_date.weekday())
        week_key = week_start.isoformat()

        if week_key not in weekly:
            weekly[week_key] = {
                "week_start": week_key,
                "total_tss": 0,
                "ride_count": 0,
                "total_duration_sec": 0,
                "total_distance_m": 0
            }

        weekly[week_key]["total_tss"] += load.get("total_tss", 0)
        weekly[week_key]["ride_count"] += load.get("ride_count", 0)
        weekly[week_key]["total_duration_sec"] += load.get("total_duration_sec", 0)
        weekly[week_key]["total_distance_m"] += load.get("total_distance_m", 0)

    # Calculate week-over-week changes
    sorted_weeks = sorted(weekly.values(), key=lambda x: x["week_start"])
    for i, week in enumerate(sorted_weeks):
        if i > 0:
            prev = sorted_weeks[i-1]
            week["tss_change"] = week["total_tss"] - prev["total_tss"]
            week["tss_change_pct"] = (
                round((week["total_tss"] - prev["total_tss"]) / max(prev["total_tss"], 1) * 100, 1)
            )
        else:
            week["tss_change"] = 0
            week["tss_change_pct"] = 0

    return {"weeks": sorted_weeks}


@router.get("/trends/rolling")
async def get_rolling_averages(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get rolling averages (7-day, 28-day, 90-day)."""
    today = date.today()

    periods = {
        "7_day": 7,
        "28_day": 28,
        "90_day": 90
    }

    result = {}
    for period_name, days in periods.items():
        start_date = today - timedelta(days=days)
        loads = await repo.get_daily_training_loads(
            user_id=current_user.user_id,
            start_date=start_date,
            end_date=today
        )

        total_tss = sum(l.get("total_tss", 0) for l in loads)
        total_rides = sum(l.get("ride_count", 0) for l in loads)
        total_distance = sum(l.get("total_distance_m", 0) for l in loads)

        result[period_name] = {
            "avg_daily_tss": round(total_tss / days, 1),
            "total_tss": round(total_tss, 1),
            "total_rides": total_rides,
            "total_distance_km": round(total_distance / 1000, 1),
            "days": days
        }

    return result
```

---

## Testing Instructions

### Unit Tests

```python
# backend/tests/test_analytics.py
import pytest
from datetime import date, timedelta
import math

from app.services.fitness_analytics import FitnessAnalyticsService
from app.services.zones import ZonesService


class TestFitnessMetrics:

    def test_ctl_calculation_from_zero(self):
        """CTL should increase when TSS is added to zero baseline."""
        service = FitnessAnalyticsService()

        # With CTL = 0 and TSS = 100
        # New CTL = 0 + (100 - 0) * (1 - e^(-1/42))
        # New CTL ≈ 100 * 0.0235 ≈ 2.35
        ctl_decay = 1 - math.exp(-1 / 42)
        expected_ctl = 100 * ctl_decay

        # Verify calculation
        assert abs(expected_ctl - 2.35) < 0.1

    def test_atl_responds_faster_than_ctl(self):
        """ATL should change faster than CTL (7-day vs 42-day constant)."""
        ctl_decay = 1 - math.exp(-1 / 42)
        atl_decay = 1 - math.exp(-1 / 7)

        # ATL decay factor should be higher
        assert atl_decay > ctl_decay
        assert abs(atl_decay - 0.133) < 0.01

    def test_tsb_calculation(self):
        """TSB = CTL - ATL."""
        # If CTL = 50 and ATL = 70, TSB = -20 (fatigued)
        tsb = 50 - 70
        assert tsb == -20

    def test_form_status_interpretation(self):
        """Test form status based on TSB."""
        service = FitnessAnalyticsService()

        assert service._get_form_status(30) == "fresh"
        assert service._get_form_status(15) == "form"
        assert service._get_form_status(0) == "neutral"
        assert service._get_form_status(-20) == "tired"
        assert service._get_form_status(-40) == "exhausted"


class TestPowerZones:

    def test_zone_calculation_at_200_ftp(self):
        """Test zone boundaries at 200W FTP."""
        service = ZonesService()
        zones = service.calculate_power_zones(200)

        # Zone 1: <55% = <110W
        assert zones[0].zone == 1
        assert zones[0].max_watts == 110

        # Zone 4 (Threshold): 90-105% = 180-210W
        assert zones[3].zone == 4
        assert zones[3].min_watts == 180
        assert zones[3].max_watts == 210

    def test_get_zone_for_power(self):
        """Test zone determination for specific power values."""
        service = ZonesService()
        ftp = 200

        assert service.get_zone_for_power(100, ftp) == 1   # <55%
        assert service.get_zone_for_power(130, ftp) == 2   # 55-75%
        assert service.get_zone_for_power(170, ftp) == 3   # 75-90%
        assert service.get_zone_for_power(200, ftp) == 4   # 90-105%
        assert service.get_zone_for_power(220, ftp) == 5   # 105-120%
        assert service.get_zone_for_power(280, ftp) == 6   # 120-150%
        assert service.get_zone_for_power(350, ftp) == 7   # >150%

    async def test_zone_distribution(self):
        """Test zone distribution calculation."""
        service = ZonesService()

        # 10 samples: 5 at Z2, 3 at Z4, 2 at Z5
        power_data = [140, 140, 140, 140, 140, 200, 200, 200, 220, 220]
        ftp = 200

        distribution = await service.calculate_zone_distribution(power_data, ftp)

        assert distribution[2]["time_sec"] == 5
        assert distribution[2]["pct"] == 50.0
        assert distribution[4]["time_sec"] == 3
        assert distribution[5]["time_sec"] == 2


class TestTrainingTrends:

    async def test_weekly_aggregation(self, mock_repo):
        """Test that daily loads aggregate to weeks correctly."""
        # Create daily loads spanning 2 weeks
        daily_loads = [
            {"date": date(2024, 1, 1), "total_tss": 50, "ride_count": 1},
            {"date": date(2024, 1, 2), "total_tss": 60, "ride_count": 1},
            {"date": date(2024, 1, 8), "total_tss": 70, "ride_count": 1},
        ]

        # Week 1 (Jan 1-7): 110 TSS
        # Week 2 (Jan 8-14): 70 TSS
```

### Manual Testing Checklist

```markdown
## Training Analytics Manual Testing Checklist

### Fitness Metrics (CTL/ATL/TSB)
- [ ] GET /analytics/fitness → Returns current CTL, ATL, TSB
- [ ] Verify TSB = CTL - ATL
- [ ] Verify form status interpretation correct
- [ ] GET /analytics/fitness/history → Returns history array
- [ ] Verify history sorted by date
- [ ] Upload new ride → Verify metrics update next day

### Power Zones
- [ ] GET /analytics/zones → Returns 7 zones
- [ ] Verify zone boundaries match FTP percentage
- [ ] Update FTP in profile → Verify zones recalculate
- [ ] GET /rides/{id}/zones → Returns zone distribution
- [ ] Verify zone percentages sum to ~100%
- [ ] Test ride without power data → Verify graceful error

### Training Load Trends
- [ ] GET /analytics/training-load → Returns daily loads
- [ ] GET /analytics/trends/weekly → Returns weekly summaries
- [ ] Verify week-over-week change calculations
- [ ] GET /analytics/trends/rolling → Returns 7/28/90 day averages
- [ ] Upload rides → Verify daily aggregates update

### Edge Cases
- [ ] New user with no rides → Verify zero values, no errors
- [ ] User with only old rides → Verify CTL decayed
- [ ] Very high TSS ride → Verify no overflow
- [ ] Multiple rides same day → Verify correct aggregation
```

---

## Success Criteria

- [ ] CTL/ATL/TSB calculated correctly using exponential weighted average
- [ ] Power zones calculated from FTP
- [ ] Zone distribution available per ride
- [ ] Weekly training trends with week-over-week comparisons
- [ ] Rolling averages (7/28/90 day)
- [ ] Form status interpretation
- [ ] All unit tests pass
- [ ] Manual testing checklist complete

---

## Files to Create/Modify

| File | Change |
|------|--------|
| `backend/sql/019_training_analytics.sql` | NEW - Analytics schema |
| `backend/app/services/fitness_analytics.py` | NEW - CTL/ATL/TSB |
| `backend/app/services/zones.py` | NEW - Power zones |
| `backend/app/routes/analytics.py` | NEW - Analytics endpoints |
| `backend/app/services/ride_processor.py` | Add zone calculation |
| `backend/app/main.py` | Register analytics router |
