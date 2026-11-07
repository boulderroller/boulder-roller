from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.routes.dev import (
    _build_backfilled_climb_pattern_kwargs,
    _find_high_gain_zero_climb_activities,
    _insert_backfilled_climb_patterns,
    _score_backfill_climb_match,
    backfill_all_climb_patterns,
    backfill_climb_patterns,
)


class FakePatternRepository:
    def __init__(self):
        self.calls = []

    async def store_climb_pattern(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


class _FakeTableQuery:
    def __init__(self, data, *, upserts=None):
        self.data = data
        self.upserts = upserts

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def single(self):
        return self

    def limit(self, *args, **kwargs):
        return self

    def upsert(self, payload, *args, **kwargs):
        if self.upserts is not None:
            self.upserts.append({"payload": payload, "kwargs": kwargs})
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class _FakeSupabaseClient:
    def __init__(self, *, activity_id, user_id):
        self.activity_id = str(activity_id)
        self.user_id = str(user_id)
        self.review_upserts = []

    def table(self, name: str):
        if name == "rides":
            return _FakeTableQuery(
                {
                    "gps_track": "encoded-polyline",
                    "started_at": "2020-07-18T15:14:12+00:00",
                    "user_id": self.user_id,
                }
            )
        if name == "users":
            return _FakeTableQuery([{"wallet": "corey-wallet"}])
        if name == "ride_climb_backfill_reviews":
            return _FakeTableQuery([], upserts=self.review_upserts)
        return _FakeTableQuery([])


class _RecordingTableQuery:
    def __init__(self, data):
        self.data = data
        self.filters = []
        self.selected = None
        self.limit_value = None

    def select(self, *args, **kwargs):
        self.selected = args[0] if args else None
        return self

    def gte(self, *args, **kwargs):
        self.filters.append(("gte", args))
        return self

    def eq(self, *args, **kwargs):
        self.filters.append(("eq", args))
        return self

    def order(self, *args, **kwargs):
        self.filters.append(("order", args))
        return self

    def limit(self, value, *args, **kwargs):
        self.limit_value = value
        return self

    def in_(self, *args, **kwargs):
        self.filters.append(("in", args))
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)


class _ZeroClimbCandidateClient:
    def __init__(self, review_rows=None):
        self.queries = []
        self.review_rows = review_rows or []

    def table(self, name: str):
        if name == "rides":
            query = _RecordingTableQuery(
                [
                    {"id": "ride-with-climb", "elevation_gain_m": 100.0},
                    {"id": "corey-zero-climb", "elevation_gain_m": 4407.4},
                    {"id": "another-zero-climb", "elevation_gain_m": 250.0},
                ]
            )
        elif name == "patterns_climb":
            query = _RecordingTableQuery([{"activity_id": "ride-with-climb"}])
        elif name == "ride_climb_backfill_reviews":
            query = _RecordingTableQuery(self.review_rows)
        else:
            query = _RecordingTableQuery([])
        self.queries.append((name, query))
        return query


def _fake_climb():
    return SimpleNamespace(
        vert_m=440.7,
        time_s=1234,
        start_time_offset_s=100,
        end_time_offset_s=1334,
        avg_power_w=260.0,
        w_per_kg=3.6,
        avg_hr=151,
        tile_ids=["8928308280fffff", "89283082813ffff"],
        distance_m=5200.0,
        avg_gradient_pct=8.47,
        signature_hex="ab" * 32,
        signature_v2_hex="cd" * 32,
        persistence=118.5,
        start_lat=39.7392,
        start_lon=-104.9903,
        end_lat=39.7601,
        end_lon=-105.0102,
    )


def test_zero_climb_selector_finds_high_gain_rides_without_existing_climb_rows():
    client = _ZeroClimbCandidateClient()

    activity_ids = _find_high_gain_zero_climb_activities(
        client,
        min_elevation_gain_m=50.0,
        scan_limit=250,
    )

    assert activity_ids == ["corey-zero-climb", "another-zero-climb"]
    rides_query = client.queries[0][1]
    patterns_query = client.queries[1][1]
    assert ("gte", ("elevation_gain_m", 50.0)) in rides_query.filters
    assert ("eq", ("processing_status", "completed")) in rides_query.filters
    assert rides_query.limit_value == 250
    assert (
        "in",
        ("activity_id", ["ride-with-climb", "corey-zero-climb", "another-zero-climb"]),
    ) in patterns_query.filters


def test_zero_climb_selector_excludes_reviewed_terminal_outcomes():
    client = _ZeroClimbCandidateClient(
        review_rows=[{"activity_id": "corey-zero-climb"}]
    )

    activity_ids = _find_high_gain_zero_climb_activities(
        client,
        min_elevation_gain_m=50.0,
        scan_limit=250,
        detector_algorithm="canonical_v2",
    )

    assert activity_ids == ["another-zero-climb"]
    review_query = client.queries[2][1]
    assert (
        "in",
        ("activity_id", ["corey-zero-climb", "another-zero-climb"]),
    ) in review_query.filters
    assert ("eq", ("detector_algorithm", "canonical_v2")) in review_query.filters
    assert ("eq", ("status", "reviewed")) in review_query.filters


def test_backfilled_climb_payload_preserves_persistence_detector_fields():
    activity_id = uuid4()
    source_samples = [
        {"t": 100, "lat": 39.7392, "lon": -104.9903, "elevation_m": 1600.0},
        {"t": 1334, "lat": 39.7601, "lon": -105.0102, "elevation_m": 2040.7},
    ]
    payload = _build_backfilled_climb_pattern_kwargs(
        activity_id=activity_id,
        wallet="rider-wallet",
        climb=_fake_climb(),
        detector_version="canonical_v2",
        source_samples=source_samples,
    )

    assert payload["activity_id"] == activity_id
    assert payload["wallet"] == "rider-wallet"
    assert payload["detector_version"] == "canonical_v2"
    assert payload["signature_hex"] == "ab" * 32
    assert payload["signature_v2_hex"] == "cd" * 32
    assert payload["persistence_m"] == pytest.approx(118.5)
    assert payload["distance_m"] == pytest.approx(5200.0)
    assert payload["avg_gradient_pct"] == pytest.approx(8.47)
    assert payload["start_lat"] == pytest.approx(39.7392)
    assert payload["end_lon"] == pytest.approx(-105.0102)
    assert payload["economic_eligible"] is True
    assert payload["abstention_reasons"] is None
    assert payload["match_trace"]["source_quality"]["elevation_coverage"] == 1.0


def test_backfill_matcher_accepts_canonical_window_shift_with_strong_overlap():
    existing = {
        "vert_m": 88.0,
        "start_offset_s": 13509,
        "end_offset_s": 14159,
    }
    canonical = SimpleNamespace(
        vert_m=60.3,
        start_time_offset_s=13799,
        end_time_offset_s=14159,
    )

    assert _score_backfill_climb_match(existing, canonical) < 500

    disjoint = SimpleNamespace(
        vert_m=60.3,
        start_time_offset_s=12000,
        end_time_offset_s=12360,
    )

    assert _score_backfill_climb_match(existing, disjoint) > 500


@pytest.mark.asyncio
async def test_zero_climb_backfill_can_insert_detected_climbs():
    repo = FakePatternRepository()
    activity_id = uuid4()

    inserted = await _insert_backfilled_climb_patterns(
        pattern_repo=repo,
        activity_id=activity_id,
        wallet="rider-wallet",
        climbs=[_fake_climb()],
        detector_version="canonical_v2",
    )

    assert inserted == 1
    assert len(repo.calls) == 1
    assert repo.calls[0]["activity_id"] == activity_id
    assert repo.calls[0]["wallet"] == "rider-wallet"
    assert repo.calls[0]["detector_version"] == "canonical_v2"


@pytest.mark.asyncio
async def test_backfill_endpoint_treats_zero_existing_climbs_as_insert_target(monkeypatch):
    monkeypatch.delenv("CLIMB_ALGORITHM", raising=False)
    activity_id = uuid4()
    user_id = uuid4()
    pattern_repo = FakePatternRepository()
    repo = SimpleNamespace(
        _client=_FakeSupabaseClient(activity_id=activity_id, user_id=user_id),
        get_patterns_for_activity=AsyncMock(return_value={"climb_patterns": []}),
    )
    tile_runs = [
        {
            "tile_id": "8928308280fffff",
            "t": 100,
            "lat": 39.7392,
            "lon": -104.9903,
            "elevation_m": 1600.0,
            "power_w": 260,
            "hr_bpm": 151,
            "speed_mps": 6.1,
        }
    ]

    with patch("app.routes.dev.create_supabase_repository", return_value=repo), patch(
        "app.routes.dev.PatternRepository", return_value=pattern_repo
    ), patch(
        "app.routes.dev.decode_gps_track",
        return_value=[{"lat": 39.7392, "lon": -104.9903}],
    ), patch(
        "app.routes.dev.tile_service.get_tile_run_sequence", return_value=tile_runs
    ) as project_tiles, patch(
        "app.routes.dev.detect_climbs_with_rust", return_value=[_fake_climb()]
    ) as detect:
        response = await backfill_climb_patterns(
            str(activity_id),
            admin_ctx=(uuid4(), "admin-wallet"),
        )

    repo.get_patterns_for_activity.assert_awaited_once()
    project_tiles.assert_called_once()
    assert project_tiles.call_args.kwargs["start_time"] is None
    detect.assert_called_once()
    detect_kwargs = detect.call_args.kwargs
    assert detect_kwargs["tile_samples"] == tile_runs
    assert detect_kwargs["algorithm"] == "canonical_v2"
    assert response["success"] is True
    assert response["existing_patterns"] == 0
    assert response["new_detections"] == 1
    assert response["inserted_patterns"] == 1
    assert response["detector_algorithm"] == "canonical_v2"
    assert pattern_repo.calls[0]["activity_id"] == activity_id
    assert pattern_repo.calls[0]["wallet"] == "corey-wallet"
    assert "source_quality" in pattern_repo.calls[0]["match_trace"]


@pytest.mark.asyncio
async def test_backfill_endpoint_records_reviewed_no_canonical_climb(monkeypatch):
    monkeypatch.delenv("CLIMB_ALGORITHM", raising=False)
    activity_id = uuid4()
    user_id = uuid4()
    client = _FakeSupabaseClient(activity_id=activity_id, user_id=user_id)
    repo = SimpleNamespace(
        _client=client,
        get_patterns_for_activity=AsyncMock(return_value={"climb_patterns": []}),
    )
    tile_runs = [
        {
            "tile_id": "8928308280fffff",
            "t": 100,
            "lat": 39.7392,
            "lon": -104.9903,
            "elevation_m": 1600.0,
        }
    ]

    with patch("app.routes.dev.create_supabase_repository", return_value=repo), patch(
        "app.routes.dev.decode_gps_track",
        return_value=[{"lat": 39.7392, "lon": -104.9903}],
    ), patch(
        "app.routes.dev.tile_service.get_tile_run_sequence", return_value=tile_runs
    ), patch(
        "app.routes.dev.detect_climbs_with_rust", return_value=[]
    ):
        response = await backfill_climb_patterns(
            str(activity_id),
            admin_ctx=(uuid4(), "admin-wallet"),
        )

    assert response["success"] is True
    assert response["new_detections"] == 0
    assert response["review_outcome"] == "no_canonical_climb"
    assert response["review_recorded"] is True
    assert client.review_upserts[0]["payload"]["activity_id"] == str(activity_id)
    assert client.review_upserts[0]["payload"]["outcome"] == "no_canonical_climb"


@pytest.mark.asyncio
async def test_backfill_all_counts_reviewed_terminal_outcomes_not_failures():
    with patch(
        "app.routes.dev.create_supabase_repository",
        return_value=SimpleNamespace(_client=object()),
    ), patch(
        "app.routes.dev._find_activities_with_incomplete_climb_patterns",
        return_value=[],
    ), patch(
        "app.routes.dev._find_high_gain_zero_climb_activities",
        return_value=["ride-missing-gps"],
    ), patch(
        "app.routes.dev.backfill_climb_patterns",
        new=AsyncMock(
            return_value={
                "success": False,
                "review_recorded": True,
                "review_outcome": "missing_gps_track",
            }
        ),
    ):
        response = await backfill_all_climb_patterns(
            admin_ctx=(uuid4(), "admin-wallet"),
        )

    assert response["total"] == 1
    assert response["reviewed_terminal"] == 1
    assert response["failed"] == 0
