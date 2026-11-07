"""Ride-record projection of DEM correction + title storage split.

Covers boulderroller-v2-odmi6.2.1 (elevationCorrectedM / elevationCorrection /
per-point relief on /gps) and boulderroller-v2-g0o24 (rides.title read
preference; PATCH writes title, not file_name).

Red-first record: on pre-change code RideRecord has no elevationCorrectedM or
elevationCorrection fields, /gps points carry no elevation_corrected_m,
title always mirrors file_name, and PATCH clobbers file_name — every test in
this module fails there.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.dependencies import AuthenticatedUser
from app.routes.rides import (
    _attach_corrected_elevation,
    _to_ride_record,
    update_ride,
)
from app.schemas import RideUpdateRequest
from app.services.elevation_correction import encode_correction_profile


def _ride_row(**overrides):
    row = {
        "id": str(uuid4()),
        "user_id": str(uuid4()),
        "processing_status": "completed",
        "started_at": "2026-08-11T12:00:00+00:00",
        "kcals": 500,
        "visibility": "public",
        "elevation_gain_m": 321.0,
        "file_name": "morning_loop.fit",
    }
    row.update(overrides)
    return row


class TestRideRecordElevationCorrection:
    def test_corrected_ride_projects_summary_and_total(self):
        row = _ride_row(
            elevation_correction_status="corrected",
            elevation_correction_source="usgs_3dep_13as_dv_1as_grid_v1",
            elevation_correction_version="dem_grid_bilinear_match8m_median3_hysteresis2m_v3",
            elevation_correction_coverage_bps=9990,
            elevation_corrected_gain_m=287.5,
        )
        record = _to_ride_record(row)
        assert record.elevation_corrected_m == 287.5
        assert record.elevation_correction.status == "corrected"
        assert record.elevation_correction.coverage_bps == 9990
        # Raw device truth is untouched by the projection.
        assert record.elevation_gain_m == 321.0
        payload = record.model_dump(by_alias=True)
        assert payload["elevationCorrectedM"] == 287.5
        assert payload["elevationCorrection"]["sourceVersion"] == (
            "usgs_3dep_13as_dv_1as_grid_v1"
        )
        assert payload["elevationM"] == 321.0

    def test_unavailable_correction_is_explicit_never_zero(self):
        row = _ride_row(
            elevation_correction_status="unavailable",
            elevation_correction_reason="insufficient_dem_coverage",
            elevation_correction_coverage_bps=4200,
        )
        record = _to_ride_record(row)
        assert record.elevation_corrected_m is None
        assert record.elevation_correction.status == "unavailable"
        assert record.elevation_correction.reason == "insufficient_dem_coverage"

    def test_legacy_ride_without_attempt_has_null_projection(self):
        record = _to_ride_record(_ride_row())
        assert record.elevation_corrected_m is None
        assert record.elevation_correction is None


class TestGpsCorrectedElevationAttachment:
    def test_corrected_profile_zips_onto_points(self):
        profile = encode_correction_profile([10.0, None, 12.4])
        ride = {
            "elevation_correction_status": "corrected",
            "elevation_correction_profile": profile,
        }
        points = [
            {"sequence_num": 0, "latitude": 40.0, "longitude": -75.2, "elevation_m": 9.0},
            {"sequence_num": 1, "latitude": 40.001, "longitude": -75.2, "elevation_m": 9.5},
            {"sequence_num": 2, "latitude": 40.002, "longitude": -75.2, "elevation_m": 55.0},
            {"sequence_num": 3, "latitude": 40.003, "longitude": -75.2, "elevation_m": 56.0},
        ]
        result = _attach_corrected_elevation(ride, points)
        assert result[0]["elevation_corrected_m"] == 10.0
        assert result[1]["elevation_corrected_m"] is None
        assert result[2]["elevation_corrected_m"] == 12.4
        # Beyond the stored profile: absent, never invented.
        assert result[3]["elevation_corrected_m"] is None
        # Raw device elevation still travels with every point.
        assert result[2]["elevation_m"] == 55.0

    def test_uncorrected_ride_yields_null_per_point(self):
        points = [{"latitude": 40.0, "longitude": -75.2, "elevation_m": 9.0}]
        result = _attach_corrected_elevation(_ride_row(), points)
        assert result[0]["elevation_corrected_m"] is None


class TestTitleStorageSplit:
    def test_title_column_wins_over_file_name(self):
        record = _to_ride_record(_ride_row(title="Manayunk Ride"))
        assert record.title == "Manayunk Ride"

    def test_legacy_null_title_falls_back_to_file_name(self):
        record = _to_ride_record(_ride_row())
        assert record.title == "morning_loop.fit"

    def test_untitled_ride_without_file_name_stays_bare_ride(self):
        record = _to_ride_record(_ride_row(file_name=None))
        assert record.title == "Ride"

    @pytest.mark.asyncio
    async def test_patch_title_writes_title_not_file_name(self):
        ride = _ride_row()
        repo = MagicMock()
        repo.get_ride = AsyncMock(return_value=ride)
        repo.update_ride_metadata = AsyncMock()
        current_user = AuthenticatedUser(
            wallet="w1", user_id=ride["user_id"], device_id="d1"
        )
        with patch("app.routes.rides.check_ride_access", AsyncMock()):
            await update_ride(
                ride_id=ride["id"],
                update_request=RideUpdateRequest(title="Wissahickon Ramble"),
                current_user=current_user,
                repo=repo,
            )
        repo.update_ride_metadata.assert_awaited_once_with(
            ride["id"], {"title": "Wissahickon Ramble"}
        )

    @pytest.mark.asyncio
    async def test_patch_empty_title_clears_to_null(self):
        ride = _ride_row()
        repo = MagicMock()
        repo.get_ride = AsyncMock(return_value=ride)
        repo.update_ride_metadata = AsyncMock()
        current_user = AuthenticatedUser(
            wallet="w1", user_id=ride["user_id"], device_id="d1"
        )
        with patch("app.routes.rides.check_ride_access", AsyncMock()):
            await update_ride(
                ride_id=ride["id"],
                update_request=RideUpdateRequest(title="   "),
                current_user=current_user,
                repo=repo,
            )
        repo.update_ride_metadata.assert_awaited_once_with(ride["id"], {"title": None})
