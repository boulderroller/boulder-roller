"""Critical path smoke tests for zero-coverage user flows.

Tests cover:
1. Upload flow: ride upload endpoint accepts file and returns ride ID
2. Auth flow: bootstrap endpoint returns expected shape
3. CAL accounting: TSS -> display/token units via ride processor helper
4. Vault matching: climb signatures matched against indexed vaults

Run with: pytest backend/tests/test_critical_path.py -v
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from tests.test_routes import MockRepository, MockUserRepository, MockAuthRepository, MockTokenRepository, _build_test_client, authenticate
from app.services.ride_privacy import RidePrivacyPolicy


V2_SIGNATURE_HEX = (
    "0208012901ef0258000000000000000062030000800000008000000000008000"
    "80008000000080008000800000008000e9105ad1a189212e4aaad7873984334a"
)


# ============================================================================
# 1. Upload Flow
# ============================================================================

class TestUploadFlow:
    """Test that the ride upload endpoint accepts a file and returns a ride ID."""

    def test_upload_ride_returns_ride_id(self):
        """Upload endpoint accepts base64 file data and returns a ride_id + status."""
        import base64

        repo = MockRepository()
        client = _build_test_client(repo)
        _device_id, access_token, _refresh = authenticate(client, repo)

        fake_fit_data = base64.b64encode(b"\x0e\x10\x00\x00" + b"\x00" * 100).decode()

        with patch("app.routes.rides.create_file_storage_service") as mock_storage_factory:
            mock_storage = MagicMock()
            mock_storage.compute_file_hash.return_value = "a" * 64
            mock_storage.upload_ride_file = AsyncMock(return_value=MagicMock(
                path="rides/test/test.fit",
                size_bytes=104,
                file_hash="a" * 64,
            ))
            mock_storage_factory.return_value = mock_storage

            # Mock the ride repository dependency used by the upload route
            mock_ride_repo = AsyncMock()
            mock_ride_repo.find_ride_by_hash = AsyncMock(return_value=None)
            mock_ride_repo.resolve_ride_privacy_policy = AsyncMock(
                return_value=RidePrivacyPolicy(
                    visibility="public",
                    map_visibility="hide_start_end",
                    map_hide_start_m=200,
                    map_hide_end_m=200,
                )
            )
            ride_id = str(uuid4())
            mock_ride_repo.create_ride = AsyncMock(return_value=ride_id)
            mock_ride_repo.get_ride = AsyncMock(return_value=None)

            from app.dependencies import get_ride_repository
            client.app.dependency_overrides[get_ride_repository] = lambda: mock_ride_repo

            # Mock the ride ingest enqueue to prevent side effects
            from app.services.ride_ingest import RideIngestEnqueueResult
            mock_enqueue_result = RideIngestEnqueueResult(accepted=True, backend="nats")
            with patch("app.routes.rides.enqueue_ride_ingest", new=AsyncMock(return_value=mock_enqueue_result)):
                response = client.post(
                    "/rides/upload",
                    headers={"Authorization": f"Bearer {access_token}"},
                    json={
                        "file_data_b64": fake_fit_data,
                        "file_type": "fit",
                    },
                )

        assert response.status_code == 200, f"Upload failed: {response.text}"
        body = response.json()
        assert "ride_id" in body
        assert "status" in body
        assert body["status"] in ("processing", "queued")

    def test_upload_rejects_invalid_base64(self):
        """Upload endpoint rejects bad base64 data."""
        repo = MockRepository()
        client = _build_test_client(repo)
        _device_id, access_token, _refresh = authenticate(client, repo)

        response = client.post(
            "/rides/upload",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "file_data_b64": "not-valid-base64!!!",
                "file_type": "fit",
            },
        )

        assert response.status_code == 400

    def test_upload_requires_auth(self):
        """Upload endpoint returns 401 without auth."""
        repo = MockRepository()
        client = _build_test_client(repo)

        response = client.post(
            "/rides/upload",
            json={
                "file_data_b64": "dGVzdA==",
                "file_type": "fit",
            },
        )

        assert response.status_code in (401, 403)


# ============================================================================
# 2. Auth Bootstrap Flow
# ============================================================================

class TestAuthBootstrap:
    """Test that /auth/bootstrap returns the expected response shape."""

    def test_bootstrap_unauthenticated_returns_expected_shape(self):
        """Bootstrap without auth returns the base shape with authenticated=False."""
        repo = MockRepository()
        client = _build_test_client(repo)

        response = client.get("/auth/bootstrap")

        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is False
        assert "invite_required" in body
        assert body["cohort_admission_required"] is False
        assert body["cohort_admitted"] is False
        assert "invite_validated" in body
        assert "needs_profile_setup" in body
        assert body["user"] is None
        assert body.get("points_config") is None

    def test_bootstrap_authenticated_returns_user_and_config(self):
        """Bootstrap with auth returns user profile and points config."""
        from app.schemas import UserProfilePrivate

        repo = MockRepository()
        repo.users_by_id[repo.user_id]["username"] = "testuser"
        repo.users_by_id[repo.user_id]["profile_setup_completed_at"] = datetime.now(timezone.utc).isoformat()
        client = _build_test_client(repo)
        _device_id, access_token, _refresh = authenticate(client, repo)

        # Mock load_private_user_profile to avoid deep user repo calls.
        mock_profile = UserProfilePrivate(
            id=repo.user_id,
            wallet=repo.wallet,
            username="testuser",
            total_rides=5,
            total_distance_m=50000.0,
            total_elevation_m=2000.0,
        )
        with patch("app.routes.auth.load_private_user_profile", new=AsyncMock(return_value=mock_profile)):
            response = client.get(
                "/auth/bootstrap",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is True
        assert body["auth_method_hint"] in ("wallet", "privy")
        assert body.get("points_config") is None
        assert body["user"] is not None
        assert body["user"]["wallet"] == repo.wallet
        assert body["needs_profile_setup"] is False

    def test_bootstrap_requires_explicit_profile_setup_completion(self):
        """A username alone does not satisfy first-run profile setup."""
        from app.schemas import UserProfilePrivate

        repo = MockRepository()
        repo.users_by_id[repo.user_id]["username"] = "testuser"
        repo.users_by_id[repo.user_id]["profile_setup_completed_at"] = None
        client = _build_test_client(repo)
        _device_id, access_token, _refresh = authenticate(client, repo)

        mock_profile = UserProfilePrivate(
            id=repo.user_id,
            wallet=repo.wallet,
            username="testuser",
        )
        with patch("app.routes.auth.load_private_user_profile", new=AsyncMock(return_value=mock_profile)):
            response = client.get(
                "/auth/bootstrap",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["authenticated"] is True
        assert body["needs_profile_setup"] is True


# ============================================================================
# 3. Frontend RUM / Web Vitals Ingest
# ============================================================================

class TestWebVitalsIngest:
    """Test that portal RUM can post web-vitals samples without auth."""

    def test_web_vitals_endpoint_accepts_portal_samples(self):
        """The portal performance runtime contract stays mounted at /metadata/web-vitals."""
        repo = MockRepository()
        client = _build_test_client(repo)

        response = client.post(
            "/metadata/web-vitals",
            json={
                "sampled": True,
                "metrics": [
                    {
                        "metric": "lcp",
                        "value": 1200.0,
                        "rating": "good",
                        "route": "/rides/demo?tab=proof",
                        "device": "desktop",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "web-vitals",
                        "visibility_state": "visible",
                        "navigation_type": "navigate",
                    },
                    {
                        "metric": "cls",
                        "value": 0.03,
                        "rating": "good",
                        "route": "/dashboard",
                        "device": "desktop",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "web-vitals",
                    },
                ],
            },
        )

        assert response.status_code == 200, response.text
        assert response.json() == {"accepted": 2, "dropped": 0}


# ============================================================================
# 4. CAL Accounting
# ============================================================================

class TestCalAccounting:
    """Test the TSS -> CAL conversion used by ride processing."""

    def test_cal_amounts_keep_display_units_separate_from_token_units(self):
        from app.services.ride_processor import CAL_DECIMALS_MULTIPLIER, _calculate_cal_amounts

        display_units, allocation_units = _calculate_cal_amounts(142.5)

        assert display_units == 142
        assert allocation_units == int(142.5 * CAL_DECIMALS_MULTIPLIER)

    def test_cal_amounts_zero_out_non_positive_tss(self):
        from app.services.ride_processor import _calculate_cal_amounts

        assert _calculate_cal_amounts(0) == (0, 0)
        assert _calculate_cal_amounts(-1) == (0, 0)


# ============================================================================
# 5. Vault Matching
# ============================================================================

class TestVaultMatching:
    """Test that climb signatures are matched against indexed vaults."""

    @pytest.mark.asyncio
    async def test_match_vaults_finds_matching_vault(self):
        """A geographic v2 match creates a VaultCompletion."""
        import uuid
        from app.services.pattern_engine import PatternEngine, UserProfile, VaultCompletion
        from app.services.vault_indexer import VaultSignatureCache, IndexedVault

        # Create a mock vault cache with one vault
        cache = VaultSignatureCache()
        cache._loaded = True

        vault = IndexedVault(
            id=1,
            signature_hex="ab" * 32,
            signature_hash_hex="cd" * 32,
            minter="vault-minter",
            name="Test Hill",
            vert_m=120.0,
            distance_m=1500,
            avg_gradient_pct=8.0,
            total_completions=5,
            total_staked=1000,
            kom_holder="wallet-kom",
            kom_time_s=600,
            created_at=datetime.now(timezone.utc),
            pda="pda-test",
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=39.0,
            start_lon=-75.0,
            end_lat=39.005,
            end_lon=-75.0,
        )
        cache._vaults = {1: vault}

        engine = PatternEngine(vault_cache=cache, use_rust_detector=False)

        # Create a mock climb pattern with signature
        from app.models.patterns import ClimbPattern as ClimbPatternModel
        pattern = ClimbPatternModel(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="test-wallet",
            arena_id=None,
            vert_m=120.0,
            time_s=550,
            avg_power_w=250,
            start_offset_s=100,
            end_offset_s=650,
            tile_ids=["tile1", "tile2"],
            distance_m=1500.0,
            avg_gradient_pct=8.0,
            signature_hex="ab" * 32,
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=39.0,
            start_lon=-75.0,
            end_lat=39.005,
            end_lon=-75.0,
            economic_eligible=True,
            abstention_reasons=None,
        )

        tile_samples = [
            {"t": t, "elevation_m": 100.0 + t * 0.2, "lat": 39.0, "lon": -75.0}
            for t in range(100, 660, 10)
        ]
        user_profile = UserProfile(wallet="test-wallet", weight_kg=75.0)

        with patch.object(
            engine,
            "_find_matches_reward_grade",
            return_value=[(vault, 0.95)],
        ):
            completions = await engine._match_vaults_and_record(
                climb_patterns=[pattern],
                tile_samples=tile_samples,
                user_profile=user_profile,
                activity_id=pattern.activity_id,
            )

        assert len(completions) == 1
        assert completions[0].vault_id == 1
        assert completions[0].vault_name == "Test Hill"
        assert completions[0].similarity == 0.95
        assert completions[0].completion_time_s == 550
        assert "cal_tribute" not in vars(completions[0])

    @pytest.mark.asyncio
    async def test_multi_climb_matches_do_not_expose_tribute_preview(self):
        import uuid

        from app.models.patterns import ClimbPattern as ClimbPatternModel
        from app.services.pattern_engine import PatternEngine, PatternResults, UserProfile
        from app.services.vault_indexer import IndexedVault, VaultSignatureCache

        activity_id = uuid.uuid4()
        cache = VaultSignatureCache()
        cache._loaded = True
        vaults = [
            IndexedVault(
                id=vault_id,
                signature_hex="ab" * 32,
                signature_hash_hex="cd" * 32,
                minter=f"vault-minter-{vault_id}",
                name=f"Test Hill {vault_id}",
                vert_m=vert_m,
                distance_m=1500,
                avg_gradient_pct=8.0,
                total_completions=5,
                total_staked=1000,
                kom_holder="wallet-kom",
                kom_time_s=600,
                created_at=datetime.now(timezone.utc),
                pda=f"pda-{vault_id}",
                signature_v2_hex=V2_SIGNATURE_HEX,
                start_lat=39.0,
                start_lon=-75.0,
                end_lat=39.005,
                end_lon=-75.0,
            )
            for vault_id, vert_m in ((1, 120.0), (2, 360.0))
        ]
        cache._vaults = {vault.id: vault for vault in vaults}
        patterns = [
            ClimbPatternModel(
                id=uuid.uuid4(),
                activity_id=activity_id,
                wallet="test-wallet",
                arena_id=None,
                vert_m=vert_m,
                time_s=550,
                avg_power_w=250,
                start_offset_s=offset,
                end_offset_s=offset + 550,
                tile_ids=[f"tile-{vault_id}"],
                distance_m=1500.0,
                avg_gradient_pct=8.0,
                signature_hex="ab" * 32,
                signature_v2_hex=V2_SIGNATURE_HEX,
                start_lat=39.0,
                start_lon=-75.0,
                end_lat=39.005,
                end_lon=-75.0,
                economic_eligible=True,
                abstention_reasons=None,
            )
            for offset, (vault_id, vert_m) in zip(
                (100, 1000),
                ((1, 120.0), (2, 360.0)),
            )
        ]
        engine = PatternEngine(vault_cache=cache, use_rust_detector=False)

        with patch.object(
            engine,
            "_find_matches_reward_grade",
            side_effect=[[(vaults[0], 0.96)], [(vaults[1], 0.97)]],
        ):
            completions = await engine._match_vaults_and_record(
                climb_patterns=patterns,
                tile_samples=[],
                user_profile=UserProfile(wallet="test-wallet", weight_kg=75.0),
                activity_id=activity_id,
            )

        assert [completion.vault_id for completion in completions] == [1, 2]
        assert all("cal_tribute" not in vars(completion) for completion in completions)
        assert all(
            "cal_tribute" not in (pattern.match_trace or {}).get("economic_action", {})
            for pattern in patterns
        )

        replay_payload = PatternResults(
            activity_id=activity_id,
            wallet="test-wallet",
            climb_patterns=patterns,
            vault_completions=completions,
        ).to_dict()
        assert all(
            "cal_tribute" not in completion
            for completion in replay_payload["vault_completions"]
        )

    @pytest.mark.asyncio
    async def test_match_vaults_abstains_when_two_active_vaults_qualify(self):
        import uuid
        from app.models.patterns import ClimbPattern as ClimbPatternModel
        from app.services.pattern_engine import PatternEngine, UserProfile
        from app.services.vault_indexer import IndexedVault, VaultSignatureCache

        cache = VaultSignatureCache()
        cache._loaded = True
        vaults = [
            IndexedVault(
                id=vault_id,
                signature_hex=("ab" if vault_id == 1 else "cd") * 32,
                signature_hash_hex=("ef" if vault_id == 1 else "12") * 32,
                minter=f"minter-{vault_id}",
                name=f"Hill {vault_id}",
                vert_m=120.0,
                distance_m=1500,
                avg_gradient_pct=8.0,
                total_completions=0,
                total_staked=0,
                kom_holder=None,
                kom_time_s=0,
                created_at=datetime.now(timezone.utc),
                pda=f"pda-{vault_id}",
                signature_v2_hex=V2_SIGNATURE_HEX,
                start_lat=39.0,
                start_lon=-75.0,
                end_lat=39.005,
                end_lon=-75.0,
            )
            for vault_id in (1, 2)
        ]
        cache._vaults = {vault.id: vault for vault in vaults}
        engine = PatternEngine(vault_cache=cache, use_rust_detector=False)
        pattern = ClimbPatternModel(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="test-wallet",
            arena_id=None,
            vert_m=120.0,
            time_s=550,
            avg_power_w=250,
            start_offset_s=100,
            end_offset_s=650,
            tile_ids=["tile1"],
            distance_m=1500.0,
            avg_gradient_pct=8.0,
            signature_hex="ab" * 32,
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=39.0,
            start_lon=-75.0,
            end_lat=39.005,
            end_lon=-75.0,
            economic_eligible=True,
            abstention_reasons=None,
        )

        with patch.object(
            engine,
            "_find_matches_reward_grade",
            return_value=[(vaults[0], 0.99), (vaults[1], 0.98)],
        ):
            completions = await engine._match_vaults_and_record(
                climb_patterns=[pattern],
                tile_samples=[],
                user_profile=UserProfile(wallet="test-wallet", weight_kg=75.0),
                activity_id=pattern.activity_id,
            )

        assert completions == []
        assert pattern.economic_eligible is False
        assert "MATCH:ambiguous_active_vaults" in (
            pattern.abstention_reasons or []
        )

    @pytest.mark.asyncio
    async def test_match_vaults_abstains_on_invalid_geographic_query(self):
        import uuid
        from app.models.patterns import ClimbPattern as ClimbPatternModel
        from app.services.pattern_engine import PatternEngine, UserProfile
        from app.services.patterns.climb_signature import InvalidRewardGradeQuery
        from app.services.vault_indexer import VaultSignatureCache

        cache = VaultSignatureCache()
        cache._loaded = True
        engine = PatternEngine(vault_cache=cache, use_rust_detector=False)
        pattern = ClimbPatternModel(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="test-wallet",
            arena_id=None,
            vert_m=120.0,
            time_s=550,
            avg_power_w=250,
            start_offset_s=100,
            end_offset_s=650,
            tile_ids=["tile1"],
            distance_m=1500.0,
            avg_gradient_pct=8.0,
            signature_hex="ab" * 32,
            signature_v2_hex=V2_SIGNATURE_HEX,
            start_lat=0.0,
            start_lon=0.0,
            end_lat=0.005,
            end_lon=0.0,
            economic_eligible=True,
            abstention_reasons=None,
        )

        with patch.object(
            engine,
            "_find_matches_reward_grade",
            side_effect=InvalidRewardGradeQuery("query start GPS is invalid"),
        ):
            completions = await engine._match_vaults_and_record(
                climb_patterns=[pattern],
                tile_samples=[],
                user_profile=UserProfile(wallet="test-wallet", weight_kg=75.0),
                activity_id=pattern.activity_id,
            )

        assert completions == []
        assert pattern.economic_eligible is False
        assert "MATCH:invalid_geographic_evidence" in (
            pattern.abstention_reasons or []
        )

    @pytest.mark.asyncio
    async def test_match_vaults_skips_when_cache_not_loaded(self):
        """No completions when vault cache is not loaded."""
        import uuid
        from app.services.pattern_engine import PatternEngine, UserProfile
        from app.services.vault_indexer import VaultSignatureCache

        cache = VaultSignatureCache()
        # cache._loaded is False by default

        engine = PatternEngine(vault_cache=cache, use_rust_detector=False)

        completions = await engine._match_vaults_and_record(
            climb_patterns=[],
            tile_samples=[],
            user_profile=UserProfile(wallet="w"),
            activity_id=uuid.uuid4(),
        )

        assert completions == []

    @pytest.mark.asyncio
    async def test_missing_native_reward_matcher_escapes_pattern_orchestration(self):
        import uuid
        from app.services.pattern_engine import PatternEngine, UserProfile
        from app.services.patterns.climb_signature import RewardGradeMatcherUnavailable
        from app.services.vault_indexer import VaultSignatureCache

        cache = VaultSignatureCache()
        cache._loaded = True
        engine = PatternEngine(vault_cache=cache, use_rust_detector=False)
        climb = MagicMock()

        with patch.object(
            engine,
            "_detect_climb_patterns",
            new=AsyncMock(return_value=[climb]),
        ):
            with patch.object(engine, "_run_template_matching", return_value=[]):
                with patch.object(
                    engine,
                    "_match_vaults_and_record",
                    new=AsyncMock(
                        side_effect=RewardGradeMatcherUnavailable(
                            "workout_parse matcher unavailable"
                        )
                    ),
                ):
                    with pytest.raises(
                        RewardGradeMatcherUnavailable,
                        match="workout_parse",
                    ):
                        await engine.detect_patterns(
                            activity_id=uuid.uuid4(),
                            tile_samples=[{"t": 0, "elevation_m": 100.0}],
                            user_profile=UserProfile(wallet="w"),
                            wallet_tile_history=set(),
                        )

    @pytest.mark.asyncio
    async def test_match_vaults_rejects_legacy_only_similarity_even_when_high(self):
        """Legacy signature similarity cannot create an economic completion."""
        import uuid
        from app.services.pattern_engine import PatternEngine, UserProfile
        from app.services.vault_indexer import VaultSignatureCache, IndexedVault

        cache = VaultSignatureCache()
        cache._loaded = True
        vault = IndexedVault(
            id=2,
            signature_hex="ef" * 32,
            signature_hash_hex="01" * 32,
            minter="minter2",
            name="Probable Hill",
            vert_m=80.0,
            distance_m=1000,
            avg_gradient_pct=6.0,
            total_completions=2,
            total_staked=500,
            kom_holder=None,
            kom_time_s=0,
            created_at=datetime.now(timezone.utc),
            pda="pda-2",
        )
        cache._vaults = {2: vault}

        engine = PatternEngine(vault_cache=cache, use_rust_detector=False)

        from app.models.patterns import ClimbPattern as ClimbPatternModel
        pattern = ClimbPatternModel(
            id=uuid.uuid4(),
            activity_id=uuid.uuid4(),
            wallet="w",
            arena_id=None,
            vert_m=80.0,
            time_s=400,
            start_offset_s=0,
            end_offset_s=400,
            tile_ids=["t1"],
            distance_m=1000.0,
            avg_gradient_pct=6.0,
            signature_hex="ef" * 32,
            economic_eligible=True,
            abstention_reasons=None,
        )

        with patch.object(cache, "find_matches", return_value=[(vault, 1.0)]) as legacy:
            completions = await engine._match_vaults_and_record(
                climb_patterns=[pattern],
                tile_samples=[{"t": 0, "elevation_m": 100.0}],
                user_profile=UserProfile(wallet="w"),
                activity_id=pattern.activity_id,
            )

        assert len(completions) == 0
        assert pattern.economic_eligible is False
        assert "MATCH:geographic_v2_required" in (pattern.abstention_reasons or [])
        legacy.assert_not_called()


def test_bootstrap_admission_reflects_stored_caller_state():
    repo=MockRepository()
    client=_build_test_client(repo)
    authenticate(client,repo)
    with patch('app.routes.auth.auth_settings.cohort_admission_required',True):
        assert client.get('/auth/bootstrap').json()['cohort_admitted'] is False
        repo.users_by_id[repo.user_id]['cohort_admitted_at']=datetime.now(timezone.utc).isoformat()
        response=client.get('/auth/bootstrap')
        assert response.status_code==200
        assert response.json()['cohort_admission_required'] is True
        assert response.json()['cohort_admitted'] is True
