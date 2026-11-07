"""Synthetic effort/leaderboard contracts and viewer-specific privacy."""

from copy import deepcopy
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")

from app.dependencies import AuthenticatedUser

OWNER = AuthenticatedUser(wallet="wallet-owner", user_id="owner", device_id="test")
OTHER = AuthenticatedUser(wallet="wallet-other", user_id="other", device_id="test")
EFFORT_ID = "11111111-1111-4111-8111-111111111111"
CLIMB_ID = "22222222-2222-4222-8222-222222222222"


def effort(**overrides):
    return {
        "id": EFFORT_ID, "ride_id": "ride", "user_id": "owner", "climb_id": CLIMB_ID,
        "canon_version": 1, "start_offset_s": 10, "end_offset_s": 110,
        "time_s": 100, "avg_power_w": 300, "power_kind": "measured", "w_per_kg": 4,
        "achieved_at": "2026-10-01T12:01:50Z",
        "metrics": {"engine_version": 1, "time_s": 100, "avg_power_w": 300,
                    "power_kind": "measured", "w_per_kg": 4, "np_w": 310,
                    "load": 4, "intensity_factor": 1.24,
                    "threshold": {"value": 250}, "stops": [
                        {"start_s": 20, "end_s": 25, "duration_s": 5, "start_m": 60, "end_m": 61,
                         "cost": {"estimate": True, "basis": "adjacent_pace_replacement",
                                  "seconds": 4.8, "range_s": [4.75, 4.85]}}
                    ]},
        "ride": {"id": "ride", "user_id": "owner", "visibility": "public",
                 "map_visibility": "show_all", "map_hide_start_m": 0, "map_hide_end_m": 0,
                 "hide_from_leaderboards": False, "moderation_state": "visible",
                 "processing_status": "completed"},
        "rider": {"id": "owner", "wallet": OWNER.wallet, "share_wkg": False,
                  "is_public": True, "account_state": "active", "moderation_state": "visible"},
        **overrides,
    }


@pytest.mark.parametrize("viewer,share,visible", [(None, False, False), (OTHER, False, False),
                                               (OWNER, False, True), (OTHER, True, True)])
def test_wkg_and_private_training_numbers_are_projected_by_viewer(viewer, share, visible):
    from app.services.climb_effort_reads import project_effort

    row = effort()
    row["rider"]["share_wkg"] = share
    row["metrics"]["weight_kg"] = 75  # a future/internal extra must never escape
    result = project_effort(row, viewer).model_dump(exclude_none=True)
    metrics = result["metrics"]
    assert ("w_per_kg" in metrics) is visible
    assert ("load" in metrics) is (viewer == OWNER)
    assert ("threshold" in metrics) is (viewer == OWNER)
    assert "weight_kg" not in str(result)
    assert metrics["stops"][0]["cost"]["estimate"] is True
    assert result["effort_id"] == EFFORT_ID


@pytest.mark.asyncio
@pytest.mark.parametrize("visibility,viewer,follows,allowed", [
    ("public", None, False, True), ("private", OWNER, False, True),
    ("private", OTHER, True, False), ("followers", OTHER, True, True),
    ("followers", OTHER, False, False), ("followers", None, False, False),
])
async def test_effort_endpoint_enforces_ride_audience(visibility, viewer, follows, allowed):
    from app.services.climb_effort_reads import read_effort

    row = effort()
    row["ride"]["visibility"] = visibility
    repo = SimpleNamespace(get_effort=AsyncMock(return_value=row), get_follow=AsyncMock(return_value=follows),
                           public_span=AsyncMock(return_value=True))
    if allowed:
        result = await read_effort(repo, EFFORT_ID, viewer)
        assert result.effort_id == EFFORT_ID
    else:
        with pytest.raises(HTTPException) as exc:
            await read_effort(repo, EFFORT_ID, viewer)
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_hidden_map_span_does_not_reveal_effort_or_stop_locations():
    from app.services.climb_effort_reads import read_effort

    repo = SimpleNamespace(get_effort=AsyncMock(return_value=effort()),
                           public_span=AsyncMock(return_value=False))
    with pytest.raises(HTTPException) as exc:
        await read_effort(repo, EFFORT_ID, OTHER)
    assert exc.value.status_code == 404
    assert (await read_effort(repo, EFFORT_ID, OWNER)).effort_id == EFFORT_ID


@pytest.mark.asyncio
async def test_leaderboard_keeps_seats_and_pins_best_distinct_rider_past_ten():
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection

    own = effort()
    others = []
    for i in range(11):
        row = deepcopy(own)
        row.update(id=f"effort-{i}", user_id=f"user-{i}", time_s=80 + i,
                   ride_id=f"ride-{i}", completion_id=f"completion-{i}")
        row["rider"].update(id=f"user-{i}", wallet=f"wallet-{i}")
        row["ride"].update(id=f"ride-{i}", user_id=f"user-{i}")
        others.append(row)
    slower_repeat = {**own, "id": "slower", "time_s": 120}
    repo = SimpleNamespace(
        get_efforts=AsyncMock(return_value=[others[0]]),
        completion_efforts=AsyncMock(return_value=[*others, slower_repeat, own]),
        public_span=AsyncMock(return_value=True),
    )
    projection = PublicRecordBoardProjection(
        entries=[{"user": "wallet-0", "position": 1, "rank": 1, "tie_size": 1,
                  "is_tied": False, "time_s": 80, "recorded_at": 1000}],
        kom_holder="wallet-0", kom_time_s=80, effort_ids={"wallet-0": "effort-0"},
    )
    rows, viewer = await enrich_board(repo, projection, vault_signature="sig", viewer=OWNER)
    assert len(rows) == 1
    assert rows[0].position == 1 and rows[0].effort_id == "effort-0"
    assert rows[0].avg_power_w == 300 and rows[0].power_kind == "measured"
    assert rows[0].w_per_kg is None
    assert viewer.effort_id == EFFORT_ID and viewer.best_time_seconds == 100
    assert viewer.rank == 12 and viewer.position is None
    assert viewer.place_source == "offchain_completions" and viewer.w_per_kg == 4


@pytest.mark.asyncio
async def test_opt_in_uses_existing_privacy_v2_contract_and_defaults_false():
    from app.routes.privacy import PrivacySettingsUpdate, get_privacy_settings, update_privacy_settings
    from backend.tests.routes.test_privacy_settings import FakePrivacySettingsRepo

    repo = FakePrivacySettingsRepo()
    viewer = AuthenticatedUser(wallet="wallet-1", user_id="user-1", device_id="test")
    before = await get_privacy_settings(current_user=viewer, repo=repo)
    assert before.share_wkg is False
    after = await update_privacy_settings(
        PrivacySettingsUpdate.model_validate({"shareWkg": True}), current_user=viewer, repo=repo
    )
    assert after.contract_version == "privacy.v2" and after.share_wkg is True
    assert repo.updated_payloads == [{"share_wkg": True}]
    assert after.model_dump(by_alias=True)["shareWkg"] is True
    revoked = await update_privacy_settings(
        PrivacySettingsUpdate.model_validate({"shareWkg": False}), current_user=viewer, repo=repo
    )
    assert revoked.share_wkg is False


@pytest.mark.parametrize("value", ["true", 1, "false"])
def test_wkg_consent_requires_a_boolean(value):
    from app.routes.privacy import PrivacySettingsUpdate
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PrivacySettingsUpdate.model_validate({"shareWkg": value})


@pytest.mark.asyncio
async def test_only_public_efforts_count_in_place_and_ties_share_place():
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    own = effort()
    own["ride"]["visibility"] = "private"
    other = deepcopy(own)
    other.update(user_id="other", id="other")
    other["ride"].update(user_id="other", visibility="public")
    other["rider"].update(id="other", wallet=OTHER.wallet, share_wkg=True)
    projection = PublicRecordBoardProjection(entries=[], kom_holder=None, kom_time_s=None)
    repo = SimpleNamespace(get_efforts=AsyncMock(return_value=[]),
                           completion_efforts=AsyncMock(return_value=[own, other]),
                           public_span=AsyncMock(return_value=True))
    rows, pinned = await enrich_board(repo, projection, vault_signature="sig", viewer=OWNER)
    assert rows == [] and pinned is None
    own["ride"]["visibility"] = "public"
    rows, pinned = await enrich_board(repo, projection, vault_signature="sig", viewer=OWNER)
    assert pinned.rank == 1 and pinned.tie_size == 2
    assert pinned.w_per_kg == 4 and pinned.effort_id == EFFORT_ID
    assert (await enrich_board(repo, projection, vault_signature="sig", viewer=None)) == ([], None)


@pytest.mark.asyncio
async def test_estimated_row_carries_kind_without_wkg_even_when_opted_in():
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    row = effort(avg_power_w=None, estimated_power_w=219.7, estimated_power_range_w=[200, 240], power_kind="estimated", w_per_kg=None)
    row["rider"]["share_wkg"] = True
    repo = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]), public_span=AsyncMock(return_value=True))
    projection = PublicRecordBoardProjection(
        entries=[{"user": OWNER.wallet, "position": 1, "rank": 1, "tie_size": 1,
                  "is_tied": False, "time_s": 100}], kom_holder=OWNER.wallet, kom_time_s=100,
        effort_ids={OWNER.wallet: EFFORT_ID})
    rows, _ = await enrich_board(repo, projection, vault_signature="sig")
    assert rows[0].avg_power_w is None and rows[0].power_kind == "estimated"
    assert rows[0].estimated_power_w == 219.7 and rows[0].estimated_power_range_w == [200, 240]
    assert "w_per_kg" not in rows[0].model_dump()


@pytest.mark.parametrize("viewer", [None, OWNER, OTHER])
def test_http_effort_route_omits_unshared_wkg_and_mass(monkeypatch, viewer):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import climbs
    from app.dependencies import get_repository, get_optional_current_user

    fake = SimpleNamespace(get_effort=AsyncMock(return_value=effort()),
                           public_span=AsyncMock(return_value=True),
                           get_follow=AsyncMock(return_value=False))
    monkeypatch.setattr(climbs, "ClimbEffortRepository", lambda _: fake)
    app = FastAPI()
    app.include_router(climbs.router, prefix="/climbs")
    app.dependency_overrides[get_repository] = lambda: SimpleNamespace(client=object())
    app.dependency_overrides[get_optional_current_user] = lambda: viewer
    with TestClient(app) as client:
        response = client.get(f"/climbs/efforts/{EFFORT_ID}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["contract_version"] == "client.v1"
    assert ("w_per_kg" in payload["metrics"]) is (viewer == OWNER)
    assert ("load" in payload["metrics"]) is (viewer == OWNER)
    assert "weight" not in response.text


@pytest.mark.parametrize("path", ["/vaults/44", "/vaults/44/leaderboard"])
@pytest.mark.parametrize("viewer", [None, OWNER])
@pytest.mark.parametrize('estimated', [False, True])
def test_http_vault_routes_keep_fractional_power_kind_and_effort_link(monkeypatch, path, viewer, estimated):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import vaults
    from app.dependencies import get_optional_current_user, get_user_repository
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from backend.tests.routes.test_legacy_public_board_privacy import _VaultRepo, _UserRepo

    row = effort(avg_power_w=None if estimated else 300.5,
                 power_kind='estimated' if estimated else 'measured',
                 estimated_power_w=219.7 if estimated else None,
                 estimated_power_range_w=[200, 240] if estimated else None,
                 w_per_kg=None if estimated else 4)
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]),
                           completion_efforts=AsyncMock(return_value=[row]),
                           public_span=AsyncMock(return_value=True))
    monkeypatch.setattr(vaults, "ClimbEffortRepository", lambda _: fake)
    monkeypatch.setattr(vaults, "_project_public_vault_board", AsyncMock(return_value=PublicRecordBoardProjection(
        entries=[{"user": OWNER.wallet, "position": 1, "rank": 1, "tie_size": 1,
                  "is_tied": False, "time_s": 100, "recorded_at": 1000}],
        kom_holder=OWNER.wallet, kom_time_s=100, effort_ids={OWNER.wallet: EFFORT_ID},
    )))
    app = FastAPI()
    app.include_router(vaults.router)
    app.dependency_overrides[vaults.get_vault_repo] = lambda: _VaultRepo()
    app.dependency_overrides[get_user_repository] = lambda: _UserRepo()
    def authenticate():
        assert path.endswith('leaderboard'), 'Vault detail must not resolve an unused viewer'
        return viewer
    app.dependency_overrides[get_optional_current_user] = authenticate
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 200, response.text
    entry = response.json()["leaderboard"][0]
    assert entry.get("avg_power_w") == (None if estimated else 300.5)
    assert entry["power_kind"] == ('estimated' if estimated else 'measured') and entry["effort_id"] == EFFORT_ID
    assert entry["ride_id"] == row["ride_id"]
    if estimated:
        assert entry['estimated_power_w'] == 219.7 and entry['estimated_power_range_w'] == [200, 240]
    assert ("w_per_kg" in entry) is (not estimated and viewer == OWNER and path.endswith("leaderboard"))
    if path == "/vaults/44":
        fake.completion_efforts.assert_not_awaited()


@pytest.mark.asyncio
async def test_private_competitor_never_counts_in_offchain_place():
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    own = effort()
    private = effort(id='private', time_s=90, user_id=OTHER.user_id)
    private['ride'].update(visibility='private', user_id=OTHER.user_id)
    private['rider'].update(id=OTHER.user_id, wallet=OTHER.wallet)
    repo = SimpleNamespace(get_efforts=AsyncMock(return_value=[]),
        completion_efforts=AsyncMock(return_value=[own, private]), public_span=AsyncMock(return_value=True))
    _, pinned = await enrich_board(repo, PublicRecordBoardProjection(entries=[], kom_holder=None, kom_time_s=None),
                                   vault_signature='sig', viewer=OWNER)
    assert pinned.rank == 1 and pinned.tie_size == 1


@pytest.mark.asyncio
async def test_viewer_and_competitor_scans_are_bounded_by_the_public_seat():
    from app.services.climb_effort_reads import enrich_board
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    row = effort()
    repo = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]), public_span=AsyncMock(return_value=True),
                           completion_efforts=AsyncMock(return_value=[row]))
    projection = PublicRecordBoardProjection(entries=[{'user': OWNER.wallet, 'rank': 1, 'position': 1,
        'tie_size': 1, 'is_tied': False, 'time_s': 100}], effort_ids={OWNER.wallet: EFFORT_ID}, kom_holder=None, kom_time_s=None)
    await enrich_board(repo, projection, vault_signature='sig', viewer=OWNER)
    own, competitors = repo.completion_efforts.call_args_list
    assert own.kwargs['max_time_s'] == 100 and own.kwargs['wallet'] == OWNER.wallet
    assert callable(own.kwargs['first_eligible'])
    assert competitors.kwargs['max_time_s'] == 100


def test_effort_contract_is_in_schema_bundle():
    from app.client_contracts import client_contract_json_schema
    schemas = client_contract_json_schema()["schemas"]
    assert "ClimbEffort" in schemas and "ClimbEffortMetrics" in schemas
    assert "weight_kg" not in str(schemas["ClimbEffort"])


@pytest.mark.asyncio
async def test_changed_privacy_removes_kom_identity_as_well_as_the_row(monkeypatch):
    from app.routes import vaults
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from backend.tests.routes.test_legacy_public_board_privacy import _VaultRepo, _UserRepo
    row = effort()
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]),
                           public_span=AsyncMock(return_value=False))
    monkeypatch.setattr(vaults, "ClimbEffortRepository", lambda _: fake)
    monkeypatch.setattr(vaults, "_project_public_vault_board", AsyncMock(return_value=PublicRecordBoardProjection(
        entries=[{"user": OWNER.wallet, "position": 1, "rank": 1, "tie_size": 1,
                  "is_tied": False, "time_s": 100, "recorded_at": 1000}],
        kom_holder=OWNER.wallet, kom_time_s=100, effort_ids={OWNER.wallet: EFFORT_ID},
    )))
    detail = await vaults.get_vault(44, _VaultRepo(), _UserRepo())
    assert detail.leaderboard == []
    assert detail.kom_holder is None and detail.kom_time_s is None


@pytest.mark.parametrize("suffix,source", [
    ("leaderboard", "onchain"),
    ("leaderboard/window?window=year", "offchain_completions"),
])
def test_http_climb_boards_expose_effort_power_date_and_viewer(monkeypatch, suffix, source):
    from datetime import datetime, timezone
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.routes import climbs
    from app.dependencies import get_repository, get_optional_current_user
    from app.services.public_record_board_privacy import PublicRecordBoardProjection
    from backend.tests.routes.test_climb_leaderboard_privacy import _Client, CLIMB_ID as ROUTE_CLIMB_ID
    from backend.tests.repositories.test_climb_effort_reads import Query

    class WindowQuery(Query):
        @property
        def not_(self):
            return self

        def is_(self, key, _value):
            self.rows = [r for r in self.rows if r.get(key) is not None]
            return self

        def gte(self, key, value):
            self.rows = [r for r in self.rows if r[key] >= value]
            return self

    client = _Client()
    client.selects = []
    client.from_ = lambda table: WindowQuery(client, table)
    row = effort()
    client.tables["vault_completions"] = [{
        "id": "completion-1", "wallet": OWNER.wallet, "time_seconds": 100,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "vault_signature": "ab" * 64, "validated": True, "chain_confirmation_status": "confirmed",
    }]
    fake = SimpleNamespace(get_efforts=AsyncMock(return_value=[row]),
                           completion_efforts=AsyncMock(return_value=[row]),
                           public_span=AsyncMock(return_value=True))
    monkeypatch.setattr(climbs, "ClimbEffortRepository", lambda _: fake)
    monkeypatch.setattr(climbs, "load_canon_climb_runtime_states",
                        lambda **_: {str(ROUTE_CLIMB_ID): "active"})
    if source == "onchain":
        monkeypatch.setattr(climbs, "project_public_record_board", lambda *_, **__: PublicRecordBoardProjection(
            entries=[{"user": OWNER.wallet, "position": 1, "rank": 1, "tie_size": 1,
                      "is_tied": False, "time_s": 100, "recorded_at": 1000}],
            kom_holder=OWNER.wallet, kom_time_s=100, effort_ids={OWNER.wallet: EFFORT_ID},
        ))
    else:
        # Exercise the real receipt/privacy resolver for the window's timestamp
        # handoff, using only synthetic evidence.
        from backend.tests.services.test_public_record_board_privacy import _tables
        evidence = _tables()
        evidence["ride_economic_completion_steps"][0].update(
            pattern_id=EFFORT_ID, completion_time_s=100,
            completed_at=client.tables["vault_completions"][0]["completed_at"])
        evidence["ride_economic_plans"][0].update(user_id=OWNER.user_id, wallet=OWNER.wallet)
        evidence["rides"][0]["user_id"] = OWNER.user_id
        evidence["users"][0].update(id=OWNER.user_id, wallet=OWNER.wallet)
        client.tables.update(evidence)
    app = FastAPI()
    app.include_router(climbs.router, prefix="/climbs")
    app.dependency_overrides[get_repository] = lambda: SimpleNamespace(client=client)
    app.dependency_overrides[get_optional_current_user] = lambda: OWNER
    with TestClient(app) as http:
        response = http.get(f"/climbs/{ROUTE_CLIMB_ID}/{suffix}")
    assert response.status_code == 200, response.text
    board = response.json()
    entry = board["entries"][0]
    assert entry["avg_power_w"] == 300 and entry["power_kind"] == "measured"
    assert entry["effort_id"] == EFFORT_ID and entry["achieved_at"] == row["achieved_at"]
    assert entry["ride_id"] == row["ride_id"]
    assert entry["place_source"] == source
    assert board["viewer_entry"]["effort_id"] == EFFORT_ID


@pytest.mark.parametrize('viewer', [None, OTHER])
@pytest.mark.parametrize('share', [False, True])
def test_all_threshold_scaled_metrics_and_max_hr_are_owner_only(viewer, share):
    from app.services.climb_effort_reads import project_effort
    row = effort()
    row['rider']['share_wkg'] = share
    private = dict(intensity_factor=1.2, load=9, power_zone_tops_w=[100], power_zone_s=[10],
                   threshold={'value': 250}, intensity_pct=120, percent_of_threshold=120, max_hr_bpm=180)
    row['metrics'].update(private)
    data = project_effort(row, viewer).model_dump(exclude_none=True)['metrics']
    assert all(key not in data for key in private)
    assert ('w_per_kg' in data) == share


def test_preview_separates_estimates_and_omits_hidden_identity_date():
    from app.public_preview_contracts import build_public_record_board
    board = build_public_record_board({'entries':[{
        'rank':1, 'wallet':'hidden-wallet', 'best_time_seconds':100, 'avg_power_w':219.7,
        'power_kind':'estimated', 'estimated_power_w':219.7, 'estimated_power_range_w':[200,240],
        'achieved_at':'2026-10-01T12:00:00Z', 'identityHidden':True, 'w_per_kg':None,
    }]})
    row = board['entries'][0]
    assert row['avgPowerW'] is None and row['powerKind'] == 'estimated'
    assert row['estimatedPowerW'] == 219.7 and row['estimatedPowerRangeW'] == [200,240]
    assert row['achievedAt'] is None and 'wPerKg' not in row
