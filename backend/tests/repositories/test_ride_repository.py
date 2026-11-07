from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call
from uuid import uuid4

import pytest

from app.repositories.ride import RideRepository
from app.services.ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy
from app.services.strava_service import StravaService


@pytest.fixture
def ride_repo() -> tuple[RideRepository, MagicMock]:
    client = MagicMock()
    table = client.table.return_value
    table.update.return_value.eq.return_value.execute.return_value = MagicMock()

    repo = RideRepository(client)
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())
    return repo, table


@pytest.mark.asyncio
async def test_update_ride_status_clears_stale_error_on_success(ride_repo):
    repo, table = ride_repo
    ride_id = uuid4()

    await repo.update_ride_status(ride_id, "completed")

    table.update.assert_called_once_with(
        {"processing_status": "completed", "error_message": None}
    )


@pytest.mark.asyncio
async def test_update_ride_status_preserves_explicit_failure_error(ride_repo):
    repo, table = ride_repo
    ride_id = uuid4()

    await repo.update_ride_status(ride_id, "failed", error_message="boom")

    table.update.assert_called_once_with(
        {"processing_status": "failed", "error_message": "boom"}
    )


@pytest.mark.asyncio
async def test_transition_ride_status_compares_expected_state_and_reports_winner(
    ride_repo,
):
    repo, table = ride_repo
    ride_id = uuid4()
    query = MagicMock()
    table.update.return_value = query
    query.eq.return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"id": str(ride_id)}])

    transitioned = await repo.transition_ride_status(
        ride_id,
        expected_status="pending",
        new_status="processing",
    )

    assert transitioned is True
    table.update.assert_called_once_with(
        {"processing_status": "processing", "error_message": None}
    )
    assert query.eq.call_args_list == [
        call("id", str(ride_id)),
        call("processing_status", "pending"),
    ]


@pytest.mark.asyncio
async def test_transition_ride_status_rejects_non_state_fields_before_write(
    ride_repo,
):
    repo, table = ride_repo

    with pytest.raises(ValueError, match="unsupported ride transition field"):
        await repo.transition_ride_status(
            uuid4(),
            expected_status="pending",
            new_status="processing",
            reward_ftp_w=999,
        )

    table.update.assert_not_called()


@pytest.mark.asyncio
async def test_update_phase_status_success_clears_global_error(ride_repo):
    repo, table = ride_repo
    ride_id = uuid4()

    await repo.update_phase_status(
        ride_id=ride_id,
        phase=3,
        success=True,
        duration_ms=321,
        cal_earned=84,
    )

    payload = table.update.call_args[0][0]

    assert payload["processing_status"] == "completed"
    assert payload["error_message"] is None
    assert payload["phase3_error"] is None
    assert payload["phase3_duration_ms"] == 321
    assert payload["cal_earned"] == 84


@pytest.mark.asyncio
async def test_update_ride_status_passes_through_attestation_metadata(ride_repo):
    repo, table = ride_repo
    ride_id = uuid4()

    await repo.update_ride_status(
        ride_id,
        "completed",
        ride_hash_hex="ab" * 32,
        attestation_commitment_hex="cd" * 32,
        ride_parser_version=1,
        ride_attestation_pda="2" * 44,
        ride_attestation_tx_signature="3" * 88,
        ride_attested_at="2024-10-01T14:02:00Z",
    )

    payload = table.update.call_args[0][0]
    assert payload["processing_status"] == "completed"
    assert payload["ride_hash_hex"] == "ab" * 32
    assert payload["attestation_commitment_hex"] == "cd" * 32
    assert payload["ride_parser_version"] == 1
    assert payload["ride_attestation_pda"] == "2" * 44
    assert payload["ride_attestation_tx_signature"] == "3" * 88
    assert payload["ride_attested_at"] == "2024-10-01T14:02:00Z"


@pytest.mark.asyncio
async def test_update_ride_status_passes_through_preliminary_attestation_metadata(ride_repo):
    repo, table = ride_repo
    ride_id = uuid4()

    await repo.update_ride_status(
        ride_id,
        "under_review",
        preliminary_ride_hash_hex="ef" * 32,
        preliminary_parser_version=1,
        canonical_match=False,
        review_reason="preliminary_hash_mismatch",
    )

    payload = table.update.call_args[0][0]
    assert payload["processing_status"] == "under_review"
    assert payload["preliminary_ride_hash_hex"] == "ef" * 32
    assert payload["preliminary_parser_version"] == 1
    assert payload["canonical_match"] is False
    assert payload["review_reason"] == "preliminary_hash_mismatch"


@pytest.mark.asyncio
async def test_create_ride_stores_import_source_diagnostics(ride_repo):
    repo, table = ride_repo
    table.insert.return_value.execute.return_value = MagicMock()

    ride_id = str(uuid4())
    diagnostics = {
        "import_source": "strava_stream_reconstructed_gpx",
        "quality_tier": "degraded",
        "flags": ["STRAVA:max_gap_warn_45s"],
    }

    await repo.create_ride(
        user_id="user-1",
        ride_id=ride_id,
        status="processing",
        file_type="gpx",
        import_source="strava_stream_reconstructed_gpx",
        import_source_id="12345",
        import_diagnostics=diagnostics,
        privacy_policy=RidePrivacyPolicy.from_values(
            visibility="public",
            map_visibility="hide_start_end",
            map_hide_start_m=200,
            map_hide_end_m=200,
        ),
    )

    payload = table.insert.call_args[0][0]
    assert payload["import_source"] == "strava_stream_reconstructed_gpx"
    assert payload["import_source_id"] == "12345"
    assert payload["import_diagnostics"] == diagnostics


@pytest.mark.asyncio
async def test_resolve_ride_privacy_policy_merges_override_over_complete_defaults() -> None:
    client = MagicMock()
    repo = RideRepository(client)
    repo._run = AsyncMock(return_value=SimpleNamespace(data=[{
        "default_ride_visibility": "public",
        "default_map_visibility": "hide_start_end",
        "default_map_hide_start_m": 200,
        "default_map_hide_end_m": 200,
    }]))

    policy = await repo.resolve_ride_privacy_policy(
        "user-1",
        visibility="followers",
        map_visibility="show_all",
        map_hide_start_m=0,
        map_hide_end_m=0,
    )

    assert policy.to_storage_dict() == {
        "visibility": "followers",
        "map_visibility": "show_all",
        "map_hide_start_m": 0,
        "map_hide_end_m": 0,
    }


@pytest.mark.asyncio
async def test_resolve_ride_privacy_policy_fails_closed_when_defaults_unavailable() -> None:
    repo = RideRepository(MagicMock())
    repo._run = AsyncMock(side_effect=RuntimeError("database unavailable"))

    with pytest.raises(PrivacySettingsUnavailable):
        await repo.resolve_ride_privacy_policy("user-1")


class _FakeRideQuery:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def select(self, value):
        self.calls.append(("select", value))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def in_(self, column, values):
        self.calls.append(("in", column, values))
        return self

    def order(self, column, desc=False):
        self.calls.append(("order", column, desc))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows)


class _FakeRideClient:
    def __init__(self, query):
        self.query = query

    def table(self, name):
        assert name == "rides"
        return self.query


@pytest.mark.asyncio
async def test_find_ride_by_import_identity_uses_provider_source_aliases() -> None:
    row = {"id": "ride-1", "import_source": "strava_stream_reconstructed_gpx"}
    query = _FakeRideQuery([row])
    repo = RideRepository(_FakeRideClient(query))
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())

    result = await repo.find_ride_by_import_identity("user-1", "strava", "12345")

    assert result == row
    assert ("eq", "user_id", "user-1") in query.calls
    assert ("eq", "import_source_id", "12345") in query.calls
    assert ("in", "import_source", ["strava", "strava_stream_reconstructed_gpx"]) in query.calls


def test_mark_activity_imported_upserts_provider_activity_identity() -> None:
    service = StravaService.__new__(StravaService)
    service.db = MagicMock()
    table = service.db.table.return_value
    table.upsert.return_value.execute.return_value = SimpleNamespace(data=[])
    connection_id = uuid4()
    ride_id = uuid4()

    service.mark_activity_imported(
        connection_id=connection_id,
        strava_activity_id=12345,
        activity_id=ride_id,
    )

    table.upsert.assert_called_once_with(
        {
            "strava_connection_id": str(connection_id),
            "strava_activity_id": 12345,
            "activity_id": str(ride_id),
        },
        on_conflict="strava_connection_id,strava_activity_id",
    )


@pytest.mark.asyncio
async def test_complete_ride_media_upload_uses_atomic_rpc() -> None:
    client = MagicMock()
    row = {"id": "media-1", "ride_id": "ride-1", "upload_status": "ready", "role": "cover"}
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=[row])
    repo = RideRepository(client)
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())

    result = await repo.complete_ride_media_upload("media-1", ride_id="ride-1", storage_path="sanitized/ride-media/photo.jpg", size_bytes=12345, width=16, height=24)

    assert result == row
    client.rpc.assert_called_once_with(
        "complete_sanitized_ride_media_upload",
        {
            "p_media_id": "media-1",
            "p_ride_id": "ride-1",
            "p_size_bytes": 12345,
            "p_storage_path": "sanitized/ride-media/photo.jpg",
            "p_width": 16,
            "p_height": 24,
            "p_mime_type": "image/jpeg",
        },
    )


@pytest.mark.asyncio
async def test_bind_reward_ftp_snapshot_uses_parsed_activity_time() -> None:
    client = MagicMock()
    row = {
        "reward_ftp_w": 200,
        "reward_ftp_source": "network_default",
        "reward_ftp_authority_id": None,
        "reward_ftp_policy_version": "reward_ftp_policy_2026_07_14",
    }
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=[row])
    repo = RideRepository(client)
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())
    ride_id = uuid4()

    result = await repo.bind_reward_ftp_snapshot(
        ride_id=ride_id,
        activity_started_at=datetime(2026, 7, 13, 12, 0),
    )

    assert result == row
    client.rpc.assert_called_once_with(
        "bind_ride_reward_ftp",
        {
            "p_ride_id": str(ride_id),
            "p_activity_started_at": "2026-07-13T12:00:00+00:00",
        },
    )


@pytest.mark.asyncio
async def test_register_reward_threshold_effort_sends_only_derived_anchors() -> None:
    client = MagicMock()
    row = {"disposition": "pending_raise", "target_ftp_w": 256}
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=[row])
    repo = RideRepository(client)
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())
    ride_id = uuid4()

    result = await repo.register_reward_threshold_effort(
        ride_id=ride_id,
        best_180s_w=350.0,
        best_420s_w=292.857,
        best_900s_w=270.0,
    )

    assert result == row
    client.rpc.assert_called_once_with(
        "register_reward_threshold_effort",
        {
            "p_ride_id": str(ride_id),
            "p_best_180s_w": 350.0,
            "p_best_420s_w": 292.857,
            "p_best_900s_w": 270.0,
        },
    )


@pytest.mark.asyncio
async def test_register_reward_threshold_effort_rejects_empty_immutable_row() -> None:
    client = MagicMock()
    repo = RideRepository(client)

    with pytest.raises(ValueError, match="at least one power anchor"):
        await repo.register_reward_threshold_effort(
            ride_id=uuid4(),
            best_180s_w=None,
            best_420s_w=None,
            best_900s_w=None,
        )

    client.rpc.assert_not_called()


@pytest.mark.asyncio
async def test_set_ride_media_cover_uses_atomic_rpc() -> None:
    client = MagicMock()
    row = {"id": "media-1", "ride_id": "ride-1", "upload_status": "ready", "role": "cover"}
    client.rpc.return_value.execute.return_value = SimpleNamespace(data=[row])
    repo = RideRepository(client)
    repo._run = AsyncMock(side_effect=lambda func, operation="supabase": func())

    result = await repo.set_ride_media_cover(ride_id="ride-1", media_id="media-1")

    assert result == row
    client.rpc.assert_called_once_with(
        "set_ride_media_cover",
        {
            "p_ride_id": "ride-1",
            "p_media_id": "media-1",
        },
    )
