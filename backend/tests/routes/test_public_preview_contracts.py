from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Optional
from uuid import uuid4

import pytest
from fastapi import HTTPException, Response

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")

from app.public_preview_contracts import (
    build_public_record_board,
    public_preview_cache_control,
    public_preview_media_items,
)
from app.routes import public_previews
from app.utils.polyline import encode_gps_track, encode_polyline


class StaticQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)
        self.filters: list[tuple[str, Any]] = []
        self._limit: Optional[int] = None
        self._order: Optional[tuple[str, bool]] = None
        self._range: Optional[tuple[int, int]] = None

    def select(self, *_args: Any, **_kwargs: Any) -> "StaticQuery":
        return self

    def eq(self, key: str, value: Any) -> "StaticQuery":
        self.filters.append((key, value))
        return self

    def in_(self, key: str, values: list[Any]) -> "StaticQuery":
        self.rows = [row for row in self.rows if row.get(key) in values]
        return self

    def order(self, key: str, desc: bool = False) -> "StaticQuery":
        self._order = (key, desc)
        return self

    def limit(self, value: int) -> "StaticQuery":
        self._limit = value
        return self

    def range(self, start: int, end: int) -> "StaticQuery":
        self._range = (start, end)
        return self

    def execute(self) -> SimpleNamespace:
        rows = list(self.rows)
        for key, value in self.filters:
            rows = [row for row in rows if row.get(key) == value]
        if self._order:
            key, desc = self._order
            rows = sorted(rows, key=lambda row: row.get(key) or 0, reverse=desc)
        if self._limit is not None:
            rows = rows[: self._limit]
        if self._range is not None:
            start, end = self._range
            rows = rows[start : end + 1]
        return SimpleNamespace(data=rows)


class StaticClient:
    def __init__(
        self,
        tables: dict[str, list[dict[str, Any]]],
        *,
        runtime_states: Optional[dict[str, str]] = None,
    ) -> None:
        self.tables = tables
        self.runtime_states = runtime_states or {}

    def from_(self, table: str) -> StaticQuery:
        return StaticQuery(self.tables.get(table, []))

    def table(self, table: str) -> StaticQuery:
        return self.from_(table)

    def rpc(self, name: str, params: dict[str, Any]) -> StaticQuery:
        assert name == "get_canon_climb_runtime_states"
        return StaticQuery(
            [
                {
                    "canon_climb_id": climb_id,
                    "runtime_state": self.runtime_states.get(climb_id, "unavailable"),
                }
                for climb_id in params["p_canon_climb_ids"]
            ]
        )


class FakePreviewRepo:
    def __init__(self) -> None:
        self.public_user_id = str(uuid4())
        self.private_user_id = str(uuid4())
        self.public_ride_id = str(uuid4())
        self.private_ride_id = str(uuid4())
        self.no_route_ride_id = str(uuid4())
        self.fixture_ride_id = str(uuid4())
        board_user_id = str(uuid4())
        board_ride_id = str(uuid4())
        self.users = {
            self.public_user_id: {
                "id": self.public_user_id,
                "wallet": "public-wallet",
                "username": "rider",
                "display_name": "Rider One",
                "avatar_url": "https://example.test/avatar.png",
                "bio": "Climber",
                "is_public": True,
                "created_at": "2026-06-01T12:00:00+00:00",
                "follower_count": 7,
                "following_count": 3,
            },
            self.private_user_id: {
                "id": self.private_user_id,
                "wallet": "private-wallet",
                "username": "private",
                "is_public": False,
            },
        }
        self.rides = {
            self.public_ride_id: {
                "id": self.public_ride_id,
                "user_id": self.public_user_id,
                "file_name": "Hill Work.fit",
                "processing_status": "completed",
                "started_at": "2026-06-01T10:00:00+00:00",
                "created_at": "2026-06-01T11:00:00+00:00",
                "distance_m": 18000,
                "elevation_gain_m": 620,
                "duration_sec": 3600,
                "cal_earned": 90,
                "dung_minted": 12,
                "visibility": "public",
                "gps_track": encode_gps_track(
                    [
                        {"latitude": 39.95, "longitude": -75.17, "timestamp": 0},
                        {"latitude": 39.96, "longitude": -75.16, "timestamp": 60},
                        {"latitude": 39.97, "longitude": -75.15, "timestamp": 120},
                    ]
                ),
                "location": "Philadelphia, PA",
                "ride_hash_hex": "ab" * 32,
                "attestation_commitment_hex": "cd" * 32,
            },
            self.private_ride_id: {
                "id": self.private_ride_id,
                "user_id": self.public_user_id,
                "file_name": "Private Spin.fit",
                "processing_status": "completed",
                "visibility": "private",
                "gps_track": encode_gps_track(
                    [
                        {"latitude": 40.0, "longitude": -75.0, "timestamp": 0},
                        {"latitude": 40.1, "longitude": -75.1, "timestamp": 60},
                    ]
                ),
            },
            self.no_route_ride_id: {
                "id": self.no_route_ride_id,
                "user_id": self.public_user_id,
                "file_name": "Hill Work No Route.fit",
                "processing_status": "completed",
                "started_at": "2026-06-02T10:00:00+00:00",
                "created_at": "2026-06-02T11:00:00+00:00",
                "distance_m": 12000,
                "elevation_gain_m": 420,
                "duration_sec": 2700,
                "visibility": "public",
                "location": "Boulder, CO",
            },
            self.fixture_ride_id: {
                "id": self.fixture_ride_id,
                "user_id": self.public_user_id,
                "file_name": "Full Stack Smoke 20260609.fit",
                "processing_status": "completed",
                "started_at": "2026-06-03T10:00:00+00:00",
                "created_at": "2026-06-03T11:00:00+00:00",
                "distance_m": 5000,
                "elevation_gain_m": 120,
                "duration_sec": 900,
                "visibility": "public",
                "location": "Boulder, CO",
            },
        }
        self.public_climb_id = str(uuid4())
        self.no_route_climb_id = str(uuid4())
        self.fixture_climb_id = str(uuid4())
        public_canon_id = str(uuid4())
        no_route_canon_id = str(uuid4())
        fixture_canon_id = str(uuid4())
        climb_pda = "canon-climb-pda-1"
        vault_pda = "canon-vault-pda-44"
        signature_hex = "ab" * 64
        self.client = StaticClient(
            {
                "canon_climbs": [
                    {
                        "id": self.public_climb_id,
                        "canon_id": public_canon_id,
                        "version": 1,
                        "status": "ratified",
                        "display_name": "Flagstaff Climb",
                        "route_name": "Flagstaff Road",
                        "centerline_polyline": encode_polyline(
                            [
                                (40.0001, -105.301),
                                (40.011, -105.295),
                                (40.0221, -105.287),
                            ]
                        ),
                        "canonical_profile": [],
                        "length_m": 2100.0,
                        "vert_m": 250.0,
                        "avg_gradient_pct": 8.2,
                        "worthiness_score": 0.9,
                        "provenance": {"region": "Boulder"},
                    },
                    {
                        "id": self.no_route_climb_id,
                        "canon_id": no_route_canon_id,
                        "version": 1,
                        "status": "ratified",
                        "display_name": "Magnolia Road",
                        "route_name": "Magnolia Road",
                        "centerline_polyline": None,
                        "canonical_profile": [],
                        "length_m": 3100.0,
                        "vert_m": 330.0,
                        "avg_gradient_pct": 9.4,
                        "worthiness_score": 0.9,
                        "provenance": {"region": "Boulder"},
                    },
                    {
                        "id": self.fixture_climb_id,
                        "canon_id": fixture_canon_id,
                        "version": 1,
                        "status": "ratified",
                        "display_name": "Full Stack Smoke 20260609",
                        "route_name": "Fixture Route",
                        "centerline_polyline": None,
                        "canonical_profile": [],
                        "length_m": 800.0,
                        "vert_m": 60.0,
                        "avg_gradient_pct": 7.1,
                        "worthiness_score": 0.9,
                        "provenance": {"region": "Test"},
                    },
                ],
                "indexed_climbs": [
                    {
                        "pda": climb_pda,
                        "canon_climb_id": self.public_climb_id,
                        "vault_pda": vault_pda,
                        "quarantined": False,
                    },
                ],
                "indexed_vaults": [
                    {
                        "id": 44,
                        "pda": vault_pda,
                        "climb_pda": climb_pda,
                        "canon_binding_status": "active",
                        "name": "Flagstaff Climb",
                        "signature_hex": signature_hex,
                        "total_completions": 9,
                        "polyline_json": "[[40.0001, -105.301], [40.011, -105.295], [40.0221, -105.287]]",
                        "kom_holder": "wallet-kom",
                        "kom_time_s": 312,
                    }
                ],
                "indexed_leaderboards": [
                    {
                        "vault_id": 44,
                        "entries": [
                            {"user": "wallet-kom", "time_s": 312, "recorded_at": 1000},
                            {"user": "wallet-second", "time_s": 330, "recorded_at": 2000},
                        ],
                    }
                ],
                "ride_economic_completion_steps": [
                    {
                        "ride_id": board_ride_id,
                        "vault_id": 44,
                        "completion_time_s": 312,
                        "completed_at": "1970-01-01T00:16:40+00:00",
                        "expected_receipt_pda": "receipt-kom",
                        "completion_evidence_hash": "\\x01",
                        "completion_evidence_version": 2,
                        "state": "projected",
                        "actual_tx_signature": "tx-kom",
                        "chain_confirmed_at": "2026-08-02T12:00:00Z",
                        "segment_start_offset_s": 0,
                        "segment_end_offset_s": 120,
                    }
                ],
                "ride_economic_plans": [
                    {
                        "ride_id": board_ride_id,
                        "user_id": board_user_id,
                        "wallet": "wallet-kom",
                        "expected_attestation_pda": "attestation-kom",
                        "state": "complete",
                    }
                ],
                "indexed_climb_completion_receipts": [
                    {
                        "pda": "receipt-kom",
                        "ride_attestation_pda": "attestation-kom",
                        "vault_pda": vault_pda,
                        "completion_evidence_hash": "\\x01",
                        "completion_evidence_version": 2,
                    }
                ],
                "rides": [
                    {
                        "id": board_ride_id,
                        "user_id": board_user_id,
                        "visibility": "public",
                        "map_visibility": "show_all",
                        "map_hide_start_m": 0,
                        "map_hide_end_m": 0,
                        "hide_from_leaderboards": False,
                        "moderation_state": "visible",
                        "ride_attestation_pda": "attestation-kom",
                        "gps_track": encode_gps_track(
                            [
                                {"latitude": 40.0001, "longitude": -105.301, "timestamp": 0},
                                {"latitude": 40.011, "longitude": -105.295, "timestamp": 60},
                                {"latitude": 40.0221, "longitude": -105.287, "timestamp": 120},
                            ]
                        ),
                    }
                ],
                "users": [
                    {
                        "id": board_user_id,
                        "wallet": "wallet-kom",
                        "is_public": True,
                        "moderation_state": "visible",
                    }
                ],
                "privacy_zones": [],
                "indexed_stakes": [
                    {
                        "vault_id": 44,
                        "user_pubkey": "wallet-staker",
                        "cal_staked": 1200,
                        "lp_tokens": 1200,
                    }
                ],
            },
            runtime_states={
                self.public_climb_id: "active",
                self.no_route_climb_id: "available",
                self.fixture_climb_id: "available",
            },
        )

    async def get_ride(self, ride_id: str) -> Optional[dict[str, Any]]:
        return self.rides.get(ride_id)

    async def get_user_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        return dict(self.users[user_id]) if user_id in self.users else None

    async def get_user_by_identifier(self, identifier: str) -> Optional[dict[str, Any]]:
        lookup = identifier.lstrip("@")
        for user in self.users.values():
            if lookup in {str(user.get("id")), str(user.get("username")), str(user.get("wallet"))}:
                return dict(user)
        return None

    async def get_user_stats(self, user_id: str) -> dict[str, Any]:
        if user_id == self.public_user_id:
            return {
                "total_rides": 23,
                "total_distance_km": 512.5,
                "total_elevation_m": 9400,
                "total_dung_earned": 88,
            }
        return {}

    async def get_public_user_recent_rides(self, user_id: str, limit: int = 10) -> list[dict[str, Any]]:
        return [
            ride
            for ride in self.rides.values()
            if ride.get("user_id") == user_id and ride.get("visibility") == "public"
        ][:limit]

    async def list_ride_media_for_rides(
        self,
        ride_ids: list[str],
        *,
        include_uploading: bool = False,
    ) -> dict[str, list[dict[str, Any]]]:
        return {ride_id: [] for ride_id in ride_ids}

    async def get_public_beetle_cards_for_wallet(self, wallet: str) -> list[dict[str, Any]]:
        return [
            {
                "id": str(uuid4()),
                "wallet": wallet,
                "cardType": "CLIMB",
                "scopeName": "Flagstaff Climb",
            }
        ]

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[dict[str, Any]]:
        return None


class FakeVaultRepo:
    async def get_user_leaderboard_positions(self, wallet: str) -> list[dict[str, Any]]:
        return [
            {
                "vault_id": 44,
                "vault_name": "Flagstaff Climb",
                "rank": 1,
                "best_time_seconds": 312,
                "wallet": wallet,
            }
        ]

    async def get_user_leaderboard_stats(self, wallet: str) -> dict[str, Any]:
        return {
            "total_positions": 1,
            "kom_count": 1,
            "podium_count": 1,
            "top10_count": 1,
            "total_vaults_completed": 1,
            "best_percentile": 1,
        }


@pytest.mark.asyncio
async def test_ride_public_preview_redacts_route_and_blocks_private_surfaces() -> None:
    repo = FakePreviewRepo()
    response = Response()

    preview = await public_previews.get_ride_public_preview(
        repo.public_ride_id,
        response,
        repo=repo,  # type: ignore[arg-type]
    )

    assert preview["seo"]["title"] == f"{preview['title']} · {preview['objectType'].capitalize()} · Boulder Roller"
    assert preview["contractVersion"] == "public_preview.v1"
    assert preview["canonicalPath"] == f"/rides/{repo.public_ride_id}"
    assert preview["compatPaths"] == [f"/activities/{repo.public_ride_id}"]
    assert preview["previewPolicy"]["rawGpsAvailable"] is False
    assert preview["previewPolicy"]["streamsAvailable"] is False
    assert preview["previewPolicy"]["privateRideHistoryAvailable"] is False
    assert preview["ride"]["routePreview"]["points"] == []
    assert preview["ride"]["routePreview"]["fallbackReason"] == "privacy_redacted"
    assert preview["ride"]["privacy"]["redactGps"] is True
    assert "calEarned" not in preview["ride"]
    assert "dungEarned" not in preview["ride"]
    assert "gps_track" not in preview["ride"]
    assert "patterns" not in preview["ride"]
    assert "rideHashHex" not in preview["ride"]
    assert "attestationCommitmentHex" not in preview["ride"]
    assert "parserVersion" not in preview["ride"]
    assert "rideAttestationTxSignature" not in preview["ride"]
    assert "no-store" in response.headers["Cache-Control"]


@pytest.mark.asyncio
@pytest.mark.parametrize("persisted_cal", [0, 222])
async def test_public_preview_never_exposes_threshold_child_release_cal(
    persisted_cal: int,
) -> None:
    repo = FakePreviewRepo()
    repo.rides[repo.public_ride_id].update(
        reward_policy="threshold_provisional_hold_v1",
        cal_earned=persisted_cal,
    )

    preview = await public_previews.get_ride_public_preview(
        repo.public_ride_id,
        Response(),
        repo=repo,  # type: ignore[arg-type]
    )

    assert "calEarned" not in preview["ride"]


def test_public_preview_contract_disables_shared_caching_for_privacy_edits() -> None:
    assert public_preview_cache_control() == "private, no-store, max-age=0"


@pytest.mark.asyncio
async def test_public_ride_preview_has_intentional_route_unavailable_asset() -> None:
    repo = FakePreviewRepo()

    preview = await public_previews.get_ride_public_preview(
        repo.no_route_ride_id,
        Response(),
        repo=repo,  # type: ignore[arg-type]
    )

    route_preview = preview["ride"]["routePreview"]
    assert route_preview["points"] == []
    assert route_preview["fallbackReason"] == "route_unavailable"
    assert route_preview["placeLabel"] == "Boulder, CO"
    assert preview["assets"]["routePreview"]["kind"] == "route_unavailable_preview"


@pytest.mark.asyncio
async def test_private_ride_public_preview_does_not_confirm_detail() -> None:
    repo = FakePreviewRepo()

    with pytest.raises(HTTPException) as exc:
        await public_previews.get_ride_public_preview(
            repo.private_ride_id,
            Response(),
            repo=repo,  # type: ignore[arg-type]
        )

    assert exc.value.status_code == 404
    assert exc.value.detail == "Ride preview unavailable"


@pytest.mark.asyncio
async def test_climb_public_preview_attaches_record_board_without_wallet_identity() -> None:
    repo = FakePreviewRepo()

    preview = await public_previews.get_climb_public_preview(
        repo.public_climb_id,
        Response(),
        repo=repo,  # type: ignore[arg-type]
    )

    assert preview["seo"]["title"] == f"{preview['title']} · {preview['objectType'].capitalize()} · Boulder Roller"
    assert preview["contractVersion"] == "public_preview.v1"
    assert preview["canonicalPath"] == f"/climbs/{repo.public_climb_id}"
    assert "leaderboard" not in preview
    assert preview["climb"]["recordBoard"]["entries"][0] == {
        "rank": 1,
        "position": 1,
        "competitionRank": 1,
        "tieSize": 1,
        "isTied": False,
        "bestTimeSeconds": 312,
        "avgPowerW": None,
        "powerKind": None,
        "estimatedPowerW": None,
        "estimatedPowerRangeW": None,
        "completionId": None,
        "achievedAt": None,
        "rider": {"displayLabel": "Rider 1", "identityHidden": True},
    }
    assert "wallet-kom" not in str(preview["climb"]["recordBoard"])
    assert "wallet-second" not in str(preview["climb"]["recordBoard"])
    assert preview["assets"]["recordBoard"]["kind"] == "record_board_preview"
    assert preview["assets"]["routePreview"]["preview"]["source"] == "canon_centerline"


@pytest.mark.asyncio
async def test_climb_public_preview_has_intentional_route_unavailable_asset() -> None:
    repo = FakePreviewRepo()

    preview = await public_previews.get_climb_public_preview(
        repo.no_route_climb_id,
        Response(),
        repo=repo,  # type: ignore[arg-type]
    )

    route_preview = preview["climb"]["routePreview"]
    assert route_preview["points"] == []
    assert route_preview["fallbackReason"] == "route_unavailable"
    assert route_preview["placeLabel"] == "Boulder"
    assert preview["assets"]["routePreview"]["kind"] == "route_unavailable_preview"


@pytest.mark.asyncio
async def test_fixture_named_public_objects_do_not_get_signed_out_previews() -> None:
    repo = FakePreviewRepo()

    with pytest.raises(HTTPException) as ride_exc:
        await public_previews.get_ride_public_preview(
            repo.fixture_ride_id,
            Response(),
            repo=repo,  # type: ignore[arg-type]
        )

    with pytest.raises(HTTPException) as climb_exc:
        await public_previews.get_climb_public_preview(
            repo.fixture_climb_id,
            Response(),
            repo=repo,  # type: ignore[arg-type]
        )

    assert ride_exc.value.status_code == 404
    assert ride_exc.value.detail == "Ride preview unavailable"
    assert climb_exc.value.status_code == 404
    assert climb_exc.value.detail == "Climb preview unavailable"


@pytest.mark.asyncio
async def test_rider_public_preview_strips_wallets_and_uses_redacted_recent_rides() -> None:
    repo = FakePreviewRepo()

    preview = await public_previews.get_rider_public_preview(
        "rider",
        Response(),
        limit=5,
        repo=repo,  # type: ignore[arg-type]
        vault_repo=FakeVaultRepo(),  # type: ignore[arg-type]
    )

    assert preview["seo"]["title"] == f"{preview['title']} · {preview['objectType'].capitalize()} · Boulder Roller"
    assert preview["contractVersion"] == "public_preview.v1"
    assert preview["canonicalPath"] == "/riders/rider"
    assert preview["rider"]["username"] == "rider"
    assert "total_dung_earned" not in preview["profile"]
    assert "wallet" not in str(preview["profile"])
    assert "wallet" not in str(preview["leaderboard"])
    assert "wallet" not in str(preview["beetleCards"])
    ride = preview["recentRides"]["rides"][0]
    assert "dung_minted" not in ride
    assert ride["routePreview"]["fallbackReason"] == "privacy_redacted"
    assert ride["privacy"]["redactGps"] is True


@pytest.mark.asyncio
async def test_private_rider_public_preview_is_noindex_and_hides_history() -> None:
    repo = FakePreviewRepo()

    preview = await public_previews.get_rider_public_preview(
        "private",
        Response(),
        limit=5,
        repo=repo,  # type: ignore[arg-type]
        vault_repo=FakeVaultRepo(),  # type: ignore[arg-type]
    )

    assert preview["seo"]["robots"] == "noindex,nofollow"
    assert preview["recentRides"]["rides"] == []
    assert preview["recentRides"]["privacy"]["reason"] == "private_profile"


def test_public_preview_media_is_cover_only_and_moderated() -> None:
    media = public_preview_media_items(
        [
            {
                "id": "detail",
                "url": "https://example.test/detail.jpg",
                "role": "detail",
                "moderationState": "visible",
            },
            {
                "id": "rejected-cover",
                "url": "https://example.test/rejected.jpg",
                "role": "cover",
                "moderationState": "rejected",
            },
            {
                "id": "cover",
                "url": "https://example.test/cover.jpg",
                "role": "cover",
                "moderationState": "approved",
            },
            {
                "id": "second-cover",
                "url": "https://example.test/second.jpg",
                "role": "cover",
                "moderationState": "featured",
            },
        ]
    )

    assert [item["id"] for item in media] == ["cover"]


def test_public_record_board_preserves_ties_seat_gaps_and_identity_boundary() -> None:
    board = build_public_record_board({"entries": [
        {"position": 2, "rank": 2, "competitionRank": 1, "tieSize": 2,
         "isTied": True, "bestTimeSeconds": 50, "avgPowerW": None,
         "identityHidden": True, "username": "must-stay-hidden", "userId": "private-id",
         "wallet": "private-wallet"},
        {"position": 5, "rank": 5, "competitionRank": 5, "tieSize": 1,
         "isTied": False, "bestTimeSeconds": 60, "avgPowerW": 0,
         "username": "public-rider", "userId": "public-id"},
    ]})
    assert board is not None
    first, second = board["entries"]
    assert (first["position"], first["rank"], first["competitionRank"], first["tieSize"], first["isTied"]) == (2, 2, 1, 2, True)
    assert first["avgPowerW"] is None
    assert first["rider"] == {"displayLabel": "Rider 2", "identityHidden": True}
    assert "private" not in str(board) and "must-stay-hidden" not in str(board)
    assert (second["position"], second["competitionRank"], second["isTied"]) == (5, 5, False)
    assert second["avgPowerW"] == 0
    assert second["rider"]["username"] == "public-rider"


@pytest.mark.parametrize("kind,object_type", [("climbs", "climb"), ("rides", "ride"), ("riders", "profile")])
def test_public_preview_seo_points_to_share_image(kind, object_type):
    from app.public_preview_contracts import public_preview_seo
    seo = public_preview_seo(title="A title", description="Existing description", canonical_path=f"/{kind}/abc", object_type=object_type)
    assert seo["openGraph"]["image"] == {
        "kind": "public_preview_card",
        "url": f"https://app.boulderroller.xyz/api/og?kind={kind}&id=abc",
        "alt": "A title",
    }
