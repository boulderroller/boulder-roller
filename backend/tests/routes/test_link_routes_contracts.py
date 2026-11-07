from __future__ import annotations

from typing import Any, Optional

import pytest
from fastapi import HTTPException

from app.dependencies import AuthenticatedUser
from app.routes.links import resolve_link_path, resolve_link_query


class FakeLinkRepo:
    def __init__(self) -> None:
        self.users = {
            "owner-user": {
                "id": "owner-user",
                "wallet": "owner-wallet",
                "username": "owner",
                "display_name": "Owner",
                "is_public": True,
            },
            "private-user": {
                "id": "private-user",
                "wallet": "private-wallet",
                "username": "private",
                "display_name": "Private",
                "is_public": False,
            },
        }
        self.rides = {
            "ride-public": {
                "id": "ride-public",
                "user_id": "owner-user",
                "file_name": "Morning Ride.fit",
                "distance_m": 42000,
                "processing_status": "completed",
                "visibility": "public",
                "ride_attestation_tx_signature": "tx-ride-public",
                "finalized_at": "2026-04-30T12:00:00+00:00",
            },
            "ride-private": {
                "id": "ride-private",
                "user_id": "owner-user",
                "file_name": "Private Ride.fit",
                "visibility": "private",
            },
        }
        self.climbs = {
            "climb-1": {
                "id": "climb-1",
                "vault_id": 1,
                "name": "Flagstaff",
                "signature_hex": "vaultsig",
                "region": "Boulder",
            }
        }
        self.follows: set[tuple[str, str]] = set()
        self.reports = {
            "report-1": {
                "id": "report-1",
                "reporterId": "viewer-user",
                "targetType": "ride",
                "targetId": "ride-public",
                "status": "open",
            }
        }

    async def get_user_by_identifier(self, identifier: str) -> Optional[dict[str, Any]]:
        for user in self.users.values():
            if identifier in {user["id"], user["wallet"], user["username"]}:
                return dict(user)
        return None

    async def get_ride(self, ride_id: str) -> Optional[dict[str, Any]]:
        ride = self.rides.get(ride_id)
        return dict(ride) if ride else None

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[dict[str, Any]]:
        if (follower_id, following_id) in self.follows:
            return {"follower_id": follower_id, "following_id": following_id}
        return None

    async def get_link_climb(self, climb_id: str) -> Optional[dict[str, Any]]:
        climb = self.climbs.get(climb_id)
        return dict(climb) if climb else None

    async def get_social_report_for_reporter(self, report_id: str, reporter_id: str) -> Optional[dict[str, Any]]:
        report = self.reports.get(report_id)
        if report and report.get("reporterId") == reporter_id:
            return dict(report)
        return None


@pytest.fixture
def viewer() -> AuthenticatedUser:
    return AuthenticatedUser(wallet="viewer-wallet", user_id="viewer-user", device_id="device-1")


@pytest.mark.asyncio
async def test_resolve_public_ride_returns_share_contract(viewer: AuthenticatedUser) -> None:
    response = await resolve_link_query(
        target_type="ride",
        target_id="ride-public",
        url=None,
        current_user=viewer,
        repo=FakeLinkRepo(),  # type: ignore[arg-type]
    )

    assert response["contractVersion"] == "link.v1"
    assert response["status"] == "resolved"
    assert response["target"]["contractVersion"] == "target_action.v1"
    assert response["target"]["type"] == "ride"
    assert response["target"]["id"] == "ride-public"
    assert response["primaryAction"] == "open_ride"
    assert response["viewerCapabilities"]["canShare"] is True
    assert response["webPath"] == "/rides/ride-public"
    assert response["appUrl"] == "boulderroller://rides/ride-public"
    assert response["title"] == "Morning Ride"
    assert response["access"]["canView"] is True
    assert response["metadata"]["privacy"]["visibility"] == "public"
    assert response["scanState"] == "finalized"
    assert response["scanTargets"][0]["url"] == "https://scan.boulderroller.xyz/tx/tx-ride-public"


@pytest.mark.asyncio
async def test_resolve_private_ride_returns_forbidden_contract(viewer: AuthenticatedUser) -> None:
    response = await resolve_link_path(
        target_type="ride",
        target_id="ride-private",
        current_user=viewer,
        repo=FakeLinkRepo(),  # type: ignore[arg-type]
    )

    assert response["status"] == "forbidden"
    assert response["webPath"] == "/rides/ride-private"
    assert response["access"]["canView"] is False
    assert response["access"]["requiresAuth"] is True
    assert response["scanState"] == "private"
    assert response["scanTargets"] == []


@pytest.mark.asyncio
async def test_resolve_private_profile_returns_forbidden_contract() -> None:
    response = await resolve_link_query(
        target_type=None,
        target_id=None,
        url="https://boulderroller.app/riders/private",
        current_user=None,
        repo=FakeLinkRepo(),  # type: ignore[arg-type]
    )

    assert response["status"] == "forbidden"
    assert response["target"]["type"] == "rider"
    assert response["target"]["id"] == "private"
    assert response["primaryAction"] == "open_rider"
    assert response["title"] == "Private rider profile"


@pytest.mark.asyncio
async def test_resolve_record_board_and_scan_targets_are_protocol_public() -> None:
    repo = FakeLinkRepo()
    record_board = await resolve_link_query(
        target_type=None,
        target_id=None,
        url="/climbs/climb-1/leaderboard",
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
    )
    scan_tx = await resolve_link_path(
        target_type="scan_tx",
        target_id="signature-1",
        current_user=None,
        repo=repo,  # type: ignore[arg-type]
    )

    assert record_board["target"]["type"] == "record_board"
    assert record_board["target"]["id"] == "climb-1"
    assert record_board["primaryAction"] == "open_climb"
    assert record_board["access"]["protocolPublic"] is True
    assert record_board["webPath"] == "/climbs/climb-1/leaderboard"
    assert record_board["title"] == "Flagstaff Leaderboard"
    assert record_board["description"] == "Leaderboard standings for this climb."
    assert record_board["scanState"] == "recorded"
    assert record_board["scanTargets"][0]["type"] == "vault"
    assert scan_tx["externalUrl"] == "https://scan.boulderroller.xyz/tx/signature-1"
    assert scan_tx["share"]["url"] == scan_tx["externalUrl"]
    assert scan_tx["scanTargets"][0]["type"] == "transaction"


@pytest.mark.asyncio
async def test_resolve_report_target_routes_to_report_status(viewer: AuthenticatedUser) -> None:
    response = await resolve_link_path(
        target_type="report",
        target_id="report-1",
        current_user=viewer,
        repo=FakeLinkRepo(),  # type: ignore[arg-type]
    )

    assert response["target"]["type"] == "report"
    assert response["target"]["id"] == "report-1"
    assert response["primaryAction"] == "open_report"
    assert response["metadata"]["targetType"] == "ride"


@pytest.mark.asyncio
async def test_resolve_missing_target_raises_404(viewer: AuthenticatedUser) -> None:
    with pytest.raises(HTTPException) as exc:
        await resolve_link_path(
            target_type="ride",
            target_id="missing",
            current_user=viewer,
            repo=FakeLinkRepo(),  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 404
