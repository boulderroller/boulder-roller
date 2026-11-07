"""
Strava Service: OAuth flow and activity import from Strava.

Handles:
- OAuth 2.0 authorization code exchange
- Token refresh
- Activity listing
- GPX reconstruction from Strava activity streams
- Connection storage
"""
from __future__ import annotations

from .privacy_logging import scrub_log_text
import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
from supabase import Client

from app.config import load_strava_settings, StravaSettings
from app.metrics import (
    record_strava_api_request,
    record_strava_token_refresh,
)
from app.repositories import get_supabase_client
from app.repositories.notification import NotificationRepository
from app.services.ride_provenance_policy import (
    ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER,
    ECONOMIC_POLICY_AUTOMATIC_ELIGIBLE,
    PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC,
)
from app.services.strava_rate_limiter import get_strava_rate_limiter

logger = logging.getLogger(__name__)

# Strava API endpoints
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"

# Required scopes for activity import
# activity:read_all - access to all activities (not just public)
STRAVA_SCOPES = "activity:read_all"
STRAVA_STREAM_RECONSTRUCTED_GPX_SOURCE = "strava_stream_reconstructed_gpx"


@dataclass
class StravaConnection:
    """Stored Strava OAuth connection."""
    id: UUID
    wallet: str
    strava_athlete_id: int
    athlete_username: Optional[str]
    athlete_firstname: Optional[str]
    athlete_lastname: Optional[str]
    access_token: str
    refresh_token: str
    expires_at: datetime
    scope: str
    connected_at: datetime
    last_sync_at: Optional[datetime]
    is_active: bool


@dataclass
class StravaActivity:
    """Strava activity summary."""
    id: int
    name: str
    type: str
    sport_type: str
    start_date: datetime
    distance: float  # meters
    moving_time: int  # seconds
    elapsed_time: int  # seconds
    total_elevation_gain: float  # meters
    has_power: bool
    already_imported: bool = False


@dataclass
class StravaTokenResponse:
    """Response from Strava token exchange."""
    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp
    athlete_id: int
    athlete_username: Optional[str]
    athlete_firstname: Optional[str]
    athlete_lastname: Optional[str]


@dataclass(frozen=True)
class StravaImportDiagnostics:
    """Quality report for GPX reconstructed from Strava streams.

    This is source provenance, not detector input. It tells later pipeline
    stages and client surfaces how much fidelity the reconstructed GPX carried
    relative to the Strava streams we received.
    """

    import_source: str
    source_activity_id: str
    quality_tier: str
    trackpoint_count: int
    stream_counts: Dict[str, int]
    median_interval_s: Optional[float]
    max_gap_s: Optional[int]
    gap_count_over_10s: int
    gap_count_over_30s: int
    altitude_coverage: float
    power_coverage: float
    heartrate_coverage: float
    cadence_coverage: float
    flags: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "import_source": self.import_source,
            "ingest_source": self.import_source,
            "provenance_tier": PROVENANCE_TIER_TRUSTED_PROVIDER_SYNC,
            "provenance_economic_policy": ECONOMIC_POLICY_AUTOMATIC_ELIGIBLE,
            "economic_guardrail_profile": ECONOMIC_GUARDRAIL_TRUSTED_PROVIDER,
            "preliminary_attestation_required": False,
            "source_activity_id": self.source_activity_id,
            "quality_tier": self.quality_tier,
            "trackpoint_count": self.trackpoint_count,
            "stream_counts": self.stream_counts,
            "median_interval_s": self.median_interval_s,
            "max_gap_s": self.max_gap_s,
            "gap_count_over_10s": self.gap_count_over_10s,
            "gap_count_over_30s": self.gap_count_over_30s,
            "altitude_coverage": round(self.altitude_coverage, 3),
            "power_coverage": round(self.power_coverage, 3),
            "heartrate_coverage": round(self.heartrate_coverage, 3),
            "cadence_coverage": round(self.cadence_coverage, 3),
            "flags": list(self.flags),
        }


class StravaServiceError(Exception):
    """Base error for Strava service operations."""
    pass


class StravaNotConfiguredError(StravaServiceError):
    """Strava credentials not configured."""
    pass


class StravaAuthError(StravaServiceError):
    """OAuth flow error."""
    pass


class StravaAPIError(StravaServiceError):
    """Strava API request error."""
    pass


class StravaRevocationError(StravaServiceError):
    """Strava connection was revoked externally (user disconnected via Strava settings)."""
    pass


class StravaService:
    """Service for Strava OAuth and activity import."""

    def __init__(self, db: Optional[Client] = None, settings: Optional[StravaSettings] = None):
        self.db = db or get_supabase_client()
        self.settings = settings or load_strava_settings()
        self.notification_repo = NotificationRepository(self.db)

    def _ensure_configured(self) -> None:
        """Raise unless the retired Strava sync path is explicitly enabled."""
        if not self.settings.enabled:
            raise StravaNotConfiguredError("Strava client_id and client_secret not configured")
        if not self.settings.sync_enabled:
            raise StravaNotConfiguredError(
                "Strava sync is disabled in file-import-only mode"
            )

    def get_authorization_url(self, state: str) -> str:
        """
        Generate Strava OAuth authorization URL.

        Args:
            state: Anti-CSRF state parameter (e.g., wallet address or session token)

        Returns:
            URL to redirect user to for Strava authorization
        """
        self._ensure_configured()
        params = {
            "client_id": self.settings.client_id,
            "redirect_uri": self.settings.redirect_uri,
            "response_type": "code",
            "scope": STRAVA_SCOPES,
            "state": state,
        }
        query = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{STRAVA_AUTH_URL}?{query}"

    @staticmethod
    def _record_request_metric(endpoint: str, method: str, response: httpx.Response, start_time: float) -> None:
        record_strava_api_request(
            endpoint=endpoint,
            method=method,
            status_code=response.status_code,
            duration_seconds=time.perf_counter() - start_time,
        )

    async def exchange_code_for_tokens(self, code: str) -> StravaTokenResponse:
        """
        Exchange authorization code for access and refresh tokens.

        Args:
            code: Authorization code from Strava callback

        Returns:
            Token response with athlete info
        """
        self._ensure_configured()
        async with httpx.AsyncClient() as client:
            start = time.perf_counter()
            response = await client.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            self._record_request_metric("oauth_token", "POST", response, start)
            if response.status_code != 200:
                logger.error(f"Strava token exchange failed: {response.status_code} {response.text}")
                raise StravaAuthError(f"Token exchange failed: {response.status_code}")

            data = response.json()
            athlete = data.get("athlete", {})
            return StravaTokenResponse(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=data["expires_at"],
                athlete_id=athlete.get("id"),
                athlete_username=athlete.get("username"),
                athlete_firstname=athlete.get("firstname"),
                athlete_lastname=athlete.get("lastname"),
            )

    async def refresh_access_token(self, refresh_token: str) -> StravaTokenResponse:
        """
        Refresh an expired access token.

        Args:
            refresh_token: Current refresh token

        Returns:
            New token response
        """
        self._ensure_configured()
        async with httpx.AsyncClient() as client:
            start = time.perf_counter()
            response = await client.post(
                STRAVA_TOKEN_URL,
                data={
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            self._record_request_metric("oauth_refresh", "POST", response, start)
            if response.status_code != 200:
                record_strava_token_refresh("error")
                logger.error(f"Strava token refresh failed: {response.status_code} {response.text}")
                raise StravaAuthError(f"Token refresh failed: {response.status_code}")
            record_strava_token_refresh("success")

            data = response.json()
            return StravaTokenResponse(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                expires_at=data["expires_at"],
                athlete_id=0,  # Not returned on refresh
                athlete_username=None,
                athlete_firstname=None,
                athlete_lastname=None,
            )

    async def save_connection(
        self,
        wallet: str,
        tokens: StravaTokenResponse,
    ) -> StravaConnection:
        """
        Save or update a Strava connection.

        Args:
            wallet: User wallet address
            tokens: Token response from Strava

        Returns:
            Saved connection record
        """
        expires_at = datetime.fromtimestamp(tokens.expires_at, tz=timezone.utc)

        # Upsert based on wallet + athlete_id
        result = self.db.table("strava_connections").upsert(
            {
                "wallet": wallet,
                "strava_athlete_id": tokens.athlete_id,
                "athlete_username": tokens.athlete_username,
                "athlete_firstname": tokens.athlete_firstname,
                "athlete_lastname": tokens.athlete_lastname,
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "expires_at": expires_at.isoformat(),
                "scope": STRAVA_SCOPES,
                "is_active": True,
            },
            on_conflict="wallet,strava_athlete_id",
        ).execute()

        row = result.data[0]
        return self._row_to_connection(row)

    def get_connection(self, wallet: str) -> Optional[StravaConnection]:
        """
        Get active Strava connection for a wallet.

        Args:
            wallet: User wallet address

        Returns:
            Connection if exists and active, None otherwise
        """
        result = self.db.table("strava_connections").select("*").eq(
            "wallet", wallet
        ).eq("is_active", True).limit(1).execute()

        if not result.data:
            return None
        return self._row_to_connection(result.data[0])

    async def ensure_valid_token(self, connection: StravaConnection) -> StravaConnection:
        """
        Ensure the connection has a valid (non-expired) access token.
        Refreshes if needed.

        Args:
            connection: Current connection

        Returns:
            Connection with valid token (may be updated)

        Raises:
            StravaRevocationError: If the connection was revoked externally
        """
        self._ensure_configured()
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        # Refresh if expires within 5 minutes
        if connection.expires_at <= now + timedelta(seconds=300):
            logger.info(f"Refreshing Strava token for wallet [redacted]")
            try:
                tokens = await self.refresh_access_token(connection.refresh_token)
            except StravaAuthError as e:
                # Token refresh failed - likely revoked externally
                logger.warning(
                    f"Strava token refresh failed for wallet [redacted]. "
                    "This may indicate the user revoked access via Strava settings."
                )
                await self._handle_external_revocation(connection)
                raise StravaRevocationError(
                    "Strava connection was revoked. Please reconnect your Strava account."
                ) from e

            # Update stored tokens
            expires_at = datetime.fromtimestamp(tokens.expires_at, tz=timezone.utc)
            self.db.table("strava_connections").update({
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "expires_at": expires_at.isoformat(),
            }).eq("id", str(connection.id)).execute()

            # Return updated connection
            connection.access_token = tokens.access_token
            connection.refresh_token = tokens.refresh_token
            connection.expires_at = expires_at

        return connection

    async def _handle_external_revocation(self, connection: StravaConnection) -> None:
        """
        Handle a Strava connection that was revoked externally.

        Marks the connection as inactive and creates a notification for the user.

        Args:
            connection: The revoked connection
        """
        # Mark connection as inactive
        self.db.table("strava_connections").update({
            "is_active": False,
        }).eq("id", str(connection.id)).execute()

        logger.info(f"Marked Strava connection as inactive for wallet [redacted]")

        # Create notification for user
        try:
            await self.notification_repo.create_event_notification(
                wallet=connection.wallet,
                notification_type="strava_revoked",
                title="Strava connection was revoked",
                message="Your Strava account was disconnected externally. Please reconnect to continue importing activities.",
                metadata={
                    "athlete_id": connection.strava_athlete_id,
                    "athlete_username": connection.athlete_username,
                },
                target_type="connected_app",
                target_id="strava",
            )
            logger.info(f"Created strava_revoked notification for wallet [redacted]")
        except Exception as e:
            logger.warning(f"Failed to create strava_revoked notification: {e}")

    async def confirm_external_revocation(self, connection: StravaConnection) -> bool:
        """
        Confirm whether a webhook-reported deauthorization is real.

        Strava webhook POSTs are not HMAC-signed. Treat deauthorize events as
        hints and only deactivate the local connection after an authenticated
        Strava API call proves the stored token is no longer accepted.
        """
        try:
            connection = await self.ensure_valid_token(connection)
        except StravaRevocationError:
            return True

        async with httpx.AsyncClient() as client:
            start = time.perf_counter()
            response = await client.get(
                f"{STRAVA_API_BASE}/athlete",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            self._record_request_metric("athlete_verify", "GET", response, start)
            get_strava_rate_limiter().update_from_headers(dict(response.headers))

        if response.status_code == 200:
            logger.info(
                "Ignoring unconfirmed Strava deauthorize webhook for wallet %s; "
                "stored token is still valid",
                "[redacted]",
            )
            return False

        if response.status_code in (401, 403):
            await self._handle_external_revocation(connection)
            return True

        raise StravaAPIError(
            f"Failed to verify Strava revocation for wallet {connection.wallet}: "
            f"{response.status_code}"
        )

    async def get_activities(
        self,
        connection: StravaConnection,
        page: int = 1,
        per_page: int = 30,
        after: Optional[datetime] = None,
    ) -> List[StravaActivity]:
        """
        Get athlete's activities from Strava.

        Args:
            connection: Valid Strava connection
            page: Page number (1-indexed)
            per_page: Activities per page (max 200)
            after: Only return activities after this time

        Returns:
            List of activity summaries
        """
        connection = await self.ensure_valid_token(connection)

        params: Dict[str, Any] = {
            "page": page,
            "per_page": min(per_page, 200),
        }
        if after:
            params["after"] = int(after.timestamp())

        async with httpx.AsyncClient() as client:
            start = time.perf_counter()
            response = await client.get(
                f"{STRAVA_API_BASE}/athlete/activities",
                headers={"Authorization": f"Bearer {connection.access_token}"},
                params=params,
            )
            self._record_request_metric("athlete_activities", "GET", response, start)
            get_strava_rate_limiter().update_from_headers(dict(response.headers))
            if response.status_code == 401:
                # 401 after token refresh means revocation
                logger.warning(
                    f"Strava API returned 401 for wallet [redacted]. "
                    "Access may have been revoked externally."
                )
                await self._handle_external_revocation(connection)
                raise StravaRevocationError(
                    "Strava connection was revoked. Please reconnect your Strava account."
                )
            if response.status_code != 200:
                logger.error(f"Strava activities fetch failed: {response.status_code} {response.text}")
                raise StravaAPIError(f"Failed to fetch activities: {response.status_code}")

            data = response.json()

        # Get already imported activity IDs
        imported_ids = self._get_imported_activity_ids(connection.id)

        activities = []
        for item in data:
            # Only include cycling activities
            if item.get("type") not in ("Ride", "VirtualRide", "EBikeRide"):
                continue

            activities.append(StravaActivity(
                id=item["id"],
                name=item["name"],
                type=item["type"],
                sport_type=item.get("sport_type", item["type"]),
                start_date=datetime.fromisoformat(item["start_date"].replace("Z", "+00:00")),
                distance=item.get("distance", 0),
                moving_time=item.get("moving_time", 0),
                elapsed_time=item.get("elapsed_time", 0),
                total_elevation_gain=item.get("total_elevation_gain", 0),
                has_power=item.get("device_watts", False),
                already_imported=item["id"] in imported_ids,
            ))

        return activities

    async def download_activity_file(
        self,
        connection: StravaConnection,
        activity_id: int,
    ) -> tuple[bytes, str]:
        """
        Download activity data from Strava and build a GPX file.

        Strava's V3 API does not expose original FIT/GPX/TCX export endpoints.
        We fetch activity streams (latlng, altitude, time, watts, heartrate, cadence)
        and reconstruct a GPX file from them.

        Args:
            connection: Valid Strava connection
            activity_id: Strava activity ID

        Returns:
            Tuple of (file_bytes, file_type) — always ('gpx' bytes, 'gpx')
        """
        file_bytes, file_type, _diagnostics = (
            await self.download_activity_file_with_diagnostics(connection, activity_id)
        )
        return file_bytes, file_type

    async def download_activity_file_with_diagnostics(
        self,
        connection: StravaConnection,
        activity_id: int,
    ) -> tuple[bytes, str, StravaImportDiagnostics]:
        """Download Strava streams and return reconstructed GPX plus provenance."""
        connection = await self.ensure_valid_token(connection)
        return await self._build_gpx_from_streams(connection, activity_id)

    async def _build_gpx_from_streams(
        self,
        connection: StravaConnection,
        activity_id: int,
    ) -> tuple[bytes, str, StravaImportDiagnostics]:
        """
        Build a GPX file from Strava streams data.

        This is a fallback when export endpoints aren't available.
        """
        async with httpx.AsyncClient() as client:
            # Fetch streams
            streams_start = time.perf_counter()
            response = await client.get(
                f"{STRAVA_API_BASE}/activities/{activity_id}/streams",
                headers={"Authorization": f"Bearer {connection.access_token}"},
                params={
                    "keys": "time,latlng,altitude,watts,heartrate,cadence",
                    "key_by_type": "true",
                },
            )
            self._record_request_metric("activity_streams", "GET", response, streams_start)
            get_strava_rate_limiter().update_from_headers(dict(response.headers))

            if response.status_code != 200:
                raise StravaAPIError(f"Failed to fetch streams: {response.status_code}")

            streams = response.json()

            # Also get activity details for metadata
            activity_start = time.perf_counter()
            activity_response = await client.get(
                f"{STRAVA_API_BASE}/activities/{activity_id}",
                headers={"Authorization": f"Bearer {connection.access_token}"},
            )
            self._record_request_metric("activity_detail", "GET", activity_response, activity_start)
            get_strava_rate_limiter().update_from_headers(dict(activity_response.headers))

            if activity_response.status_code != 200:
                raise StravaAPIError(f"Failed to fetch activity: {activity_response.status_code}")

            activity = activity_response.json()

        diagnostics = self.assess_stream_reconstruction_fidelity(activity_id, streams)
        gpx_content = self._streams_to_gpx(activity, streams, diagnostics)
        return gpx_content.encode("utf-8"), "gpx", diagnostics

    @staticmethod
    def _stream_data(streams: Dict[str, Any], key: str) -> List[Any]:
        stream = streams.get(key) or {}
        data = stream.get("data") or []
        return data if isinstance(data, list) else []

    @staticmethod
    def _median(values: List[float]) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            return float(ordered[mid])
        return float((ordered[mid - 1] + ordered[mid]) / 2)

    @classmethod
    def assess_stream_reconstruction_fidelity(
        cls,
        activity_id: int,
        streams: Dict[str, Any],
    ) -> StravaImportDiagnostics:
        """Assess how trustworthy a Strava-stream-reconstructed GPX will be."""
        stream_keys = ("time", "latlng", "altitude", "watts", "heartrate", "cadence")
        stream_counts = {
            key: len(cls._stream_data(streams, key))
            for key in stream_keys
        }
        time_data = cls._stream_data(streams, "time")
        trackpoint_count = min(stream_counts["time"], stream_counts["latlng"])

        flags: List[str] = []
        if stream_counts["time"] == 0:
            flags.append("STRAVA:missing_time_stream")
        if stream_counts["latlng"] == 0:
            flags.append("STRAVA:missing_latlng_stream")
        if trackpoint_count < 10:
            flags.append(f"STRAVA:too_few_trackpoints_{trackpoint_count}")

        required_counts = [
            stream_counts["time"],
            stream_counts["latlng"],
            stream_counts["altitude"],
        ]
        non_zero_required = [count for count in required_counts if count > 0]
        if len(set(non_zero_required)) > 1:
            flags.append("STRAVA:required_stream_length_mismatch")

        optional_counts = [
            stream_counts["watts"],
            stream_counts["heartrate"],
            stream_counts["cadence"],
        ]
        non_zero_optional = [count for count in optional_counts if count > 0]
        if non_zero_optional and any(count not in (0, trackpoint_count) for count in optional_counts):
            flags.append("STRAVA:optional_stream_length_mismatch")

        if stream_counts["altitude"] == 0:
            flags.append("STRAVA:missing_altitude_stream")

        intervals: List[float] = []
        for index in range(1, min(len(time_data), trackpoint_count)):
            try:
                dt = float(time_data[index]) - float(time_data[index - 1])
            except (TypeError, ValueError):
                continue
            if dt > 0:
                intervals.append(dt)

        median_interval_s = cls._median(intervals)
        max_gap_s = int(max(intervals)) if intervals else None
        gap_count_over_10s = sum(1 for dt in intervals if dt > 10)
        gap_count_over_30s = sum(1 for dt in intervals if dt > 30)

        if median_interval_s is not None:
            if median_interval_s > 10:
                flags.append(f"STRAVA:sparse_sampling_{median_interval_s:.1f}s")
            elif median_interval_s > 5:
                flags.append(f"STRAVA:degraded_sampling_{median_interval_s:.1f}s")
        if max_gap_s is not None:
            if max_gap_s > 300:
                flags.append(f"STRAVA:max_gap_severe_{max_gap_s}s")
            elif max_gap_s > 30:
                flags.append(f"STRAVA:max_gap_warn_{max_gap_s}s")

        denominator = max(trackpoint_count, 1)
        altitude_coverage = min(stream_counts["altitude"], trackpoint_count) / denominator
        power_coverage = min(stream_counts["watts"], trackpoint_count) / denominator
        heartrate_coverage = min(stream_counts["heartrate"], trackpoint_count) / denominator
        cadence_coverage = min(stream_counts["cadence"], trackpoint_count) / denominator

        if 0 < altitude_coverage < 0.90:
            flags.append(f"STRAVA:altitude_coverage_{altitude_coverage:.0%}")

        if (
            stream_counts["time"] == 0
            or stream_counts["latlng"] == 0
            or trackpoint_count < 10
        ):
            quality_tier = "unusable"
        elif (
            stream_counts["altitude"] == 0
            or altitude_coverage < 0.50
            or (median_interval_s is not None and median_interval_s > 10)
            or (max_gap_s is not None and max_gap_s > 300)
        ):
            quality_tier = "low"
        elif flags:
            quality_tier = "degraded"
        else:
            quality_tier = "high"

        return StravaImportDiagnostics(
            import_source=STRAVA_STREAM_RECONSTRUCTED_GPX_SOURCE,
            source_activity_id=str(activity_id),
            quality_tier=quality_tier,
            trackpoint_count=trackpoint_count,
            stream_counts=stream_counts,
            median_interval_s=median_interval_s,
            max_gap_s=max_gap_s,
            gap_count_over_10s=gap_count_over_10s,
            gap_count_over_30s=gap_count_over_30s,
            altitude_coverage=altitude_coverage,
            power_coverage=power_coverage,
            heartrate_coverage=heartrate_coverage,
            cadence_coverage=cadence_coverage,
            flags=flags,
        )

    def _streams_to_gpx(
        self,
        activity: Dict[str, Any],
        streams: Dict[str, Any],
        diagnostics: Optional[StravaImportDiagnostics] = None,
    ) -> str:
        """Convert Strava streams to GPX format."""
        from datetime import timedelta

        start_time = datetime.fromisoformat(activity["start_date"].replace("Z", "+00:00"))
        name = activity.get("name", "Strava Activity")

        time_data = self._stream_data(streams, "time")
        latlng_data = self._stream_data(streams, "latlng")
        altitude_data = self._stream_data(streams, "altitude")
        power_data = self._stream_data(streams, "watts")
        hr_data = self._stream_data(streams, "heartrate")
        cadence_data = self._stream_data(streams, "cadence")

        device = str(activity.get('device_name') or '').casefold()
        virtual = (
            activity.get('type') in ('VirtualRide', 'VirtualEBikeRide')
            or activity.get('sport_type') in ('VirtualRide', 'VirtualEBikeRide')
            or activity.get('trainer') is True
            or any(provider in device for provider in (
                'zwift', 'rouvy', 'mywhoosh', 'trainerroad', 'fulgaz',
                'bkool', 'wahoo systm', 'rgt',
            ))
        )
        creator = 'BoulderRoller-Strava-Import-Virtual' if virtual else 'BoulderRoller-Strava-Import'

        gpx_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<gpx version="1.1" creator="{creator}">',
            '<metadata>',
            f'<name>{escape(str(name), quote=False)}</name>',
            f'<time>{start_time.isoformat()}</time>',
        ]
        if diagnostics is not None:
            gpx_lines.extend([
                '<extensions>',
                f'<import_source>{diagnostics.import_source}</import_source>',
                f'<source_activity_id>{diagnostics.source_activity_id}</source_activity_id>',
                f'<quality_tier>{diagnostics.quality_tier}</quality_tier>',
                f'<trackpoint_count>{diagnostics.trackpoint_count}</trackpoint_count>',
                '</extensions>',
            ])
        gpx_lines.extend([
            '</metadata>',
            '<trk>',
            f'<name>{escape(str(name), quote=False)}</name>',
            '<trkseg>',
        ])

        for i, t in enumerate(time_data):
            if i >= len(latlng_data):
                break

            lat, lon = latlng_data[i]
            point_time = start_time + timedelta(seconds=t)
            ele = altitude_data[i] if i < len(altitude_data) else None

            gpx_lines.append(
                f'<trkpt lat="{escape(str(lat), quote=True)}" lon="{escape(str(lon), quote=True)}">'
            )
            if ele is not None:
                gpx_lines.append(f'<ele>{ele}</ele>')
            gpx_lines.append(f'<time>{point_time.isoformat()}</time>')

            # Extensions for power, HR, cadence
            extensions = []
            if i < len(power_data) and power_data[i] is not None:
                extensions.append(f'<power>{power_data[i]}</power>')
            if i < len(hr_data) and hr_data[i] is not None:
                extensions.append(f'<hr>{hr_data[i]}</hr>')
            if i < len(cadence_data) and cadence_data[i] is not None:
                extensions.append(f'<cad>{cadence_data[i]}</cad>')

            if extensions:
                gpx_lines.append('<extensions>')
                gpx_lines.extend(extensions)
                gpx_lines.append('</extensions>')

            gpx_lines.append('</trkpt>')

        gpx_lines.extend([
            '</trkseg>',
            '</trk>',
            '</gpx>',
        ])

        return '\n'.join(gpx_lines)

    def mark_activity_imported(
        self,
        connection_id: UUID,
        strava_activity_id: int,
        activity_id: UUID,
    ) -> None:
        """
        Mark a Strava activity as imported.

        Args:
            connection_id: Strava connection ID
            strava_activity_id: Strava's activity ID
            activity_id: Boulder Roller ride ID for the imported activity
        """
        self.db.table("strava_imported_activities").upsert({
            "strava_connection_id": str(connection_id),
            "strava_activity_id": strava_activity_id,
            "activity_id": str(activity_id),
        }, on_conflict="strava_connection_id,strava_activity_id").execute()

    def get_connection_by_athlete_id(self, athlete_id: int) -> Optional[StravaConnection]:
        """
        Get active Strava connection by athlete ID.

        Used by webhook handler to resolve which user owns the activity.

        Args:
            athlete_id: Strava athlete ID (owner_id in webhook payload)

        Returns:
            Connection if exists and active, None otherwise
        """
        result = self.db.table("strava_connections").select("*").eq(
            "strava_athlete_id", athlete_id
        ).eq("is_active", True).limit(1).execute()

        if not result.data:
            return None
        return self._row_to_connection(result.data[0])

    async def disconnect(self, wallet: str) -> bool:
        """
        Disconnect Strava account.

        Calls Strava's deauthorize endpoint to revoke our access token,
        then marks the local connection as inactive.

        Args:
            wallet: User wallet address

        Returns:
            True if disconnected, False if no connection found
        """
        # Get the current connection to retrieve the access token
        connection = self.get_connection(wallet)
        if not connection:
            return False

        # Call Strava's deauthorize endpoint
        try:
            async with httpx.AsyncClient() as client:
                start = time.perf_counter()
                response = await client.post(
                    "https://www.strava.com/oauth/deauthorize",
                    params={"access_token": connection.access_token},
                )
                self._record_request_metric("oauth_deauthorize", "POST", response, start)
                if response.status_code == 200:
                    logger.info(f"Strava deauthorization successful for wallet [redacted]")
                else:
                    logger.warning(
                        f"Strava deauthorization returned {response.status_code} for wallet [redacted] "
                        f"(continuing with local disconnect)"
                    )
        except Exception as e:
            logger.warning(f"Strava deauthorization request failed for wallet [redacted]: {scrub_log_text(e)}")

        # Mark local connection as inactive regardless of deauth result
        result = self.db.table("strava_connections").update({
            "is_active": False,
        }).eq("wallet", wallet).eq("is_active", True).execute()

        return len(result.data) > 0

    def _get_imported_activity_ids(self, connection_id: UUID) -> set[int]:
        """Get set of already imported Strava activity IDs."""
        result = self.db.table("strava_imported_activities").select(
            "strava_activity_id"
        ).eq("strava_connection_id", str(connection_id)).execute()

        return {row["strava_activity_id"] for row in result.data}

    def _row_to_connection(self, row: Dict[str, Any]) -> StravaConnection:
        """Convert database row to StravaConnection."""
        return StravaConnection(
            id=UUID(row["id"]),
            wallet=row["wallet"],
            strava_athlete_id=row["strava_athlete_id"],
            athlete_username=row.get("athlete_username"),
            athlete_firstname=row.get("athlete_firstname"),
            athlete_lastname=row.get("athlete_lastname"),
            access_token=row["access_token"],
            refresh_token=row["refresh_token"],
            expires_at=datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00")),
            scope=row["scope"],
            connected_at=datetime.fromisoformat(row["connected_at"].replace("Z", "+00:00")),
            last_sync_at=datetime.fromisoformat(row["last_sync_at"].replace("Z", "+00:00")) if row.get("last_sync_at") else None,
            is_active=row["is_active"],
        )


def create_strava_service() -> StravaService:
    """Factory function to create a StravaService."""
    return StravaService()
