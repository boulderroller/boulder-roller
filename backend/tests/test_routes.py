from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import math
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import base58
from nacl.signing import SigningKey

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from fastapi.testclient import TestClient

from app.dependencies import (
    get_repository,
    get_ride_repository,
    get_token_repository,
    get_auth_repository,
    get_user_repository,
)
from app.main import create_app
from app.repositories import AuthRepository, DatabaseRepository, TokenRepository, UserRepository
from app.routes.proofs import _build_proof_verification_message
from app.schemas import HealthResponse
from app.security import hash_refresh_token
from app.invite_security import hash_invite_code
from app.cohort_admission import get_admission_repository
from app.services.ride_privacy import RidePrivacyPolicy
# TokenMintClient removed — replaced by CAL batch pipeline


class MockRepository(DatabaseRepository):
    def __init__(self) -> None:
        self.user_id = str(uuid4())
        self.wallet = "wallet-test"
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.segments = [
            {
                "id": str(uuid4()),
                "name": "Test Segment",
                "geom": {"type": "LineString", "coordinates": []},
                "region": "Test Region",
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]
        self.segment_by_id = {seg["id"]: seg for seg in self.segments}
        self.health_ok = True
        self.nonces: Dict[str, Dict[str, Optional[str]]] = {}
        self.refresh_tokens: Dict[str, Dict[str, Optional[str]]] = {}
        self.identities: Dict[tuple[str, str], Dict[str, Any]] = {}
        self.rides_for_user: list[dict[str, Any]] = []
        self.counted_climb_steps: dict[str, list[dict[str, Any]]] = {}
        self.token_balances: Dict[str, float] = {"dung": 0.0, "kcal": 0.0}
        self.user_states: Dict[str, Dict[str, Any]] = {}
        self.claims: Dict[tuple[str, str], Dict[str, Any]] = {}
        self.epochs: Dict[str, Dict[str, Any]] = {}
        self.epoch_records: Dict[tuple[str, int], Dict[str, Any]] = {}
        self.leaderboards: Dict[tuple[str, int], list[Dict[str, Any]]] = {}
        self.vesting_schedules: list[Dict[str, Any]] = []
        self.harvest_events: list[Dict[str, Any]] = []
        self.transactions: list[Dict[str, Any]] = []
        self.follows: set[tuple[str, str]] = set()
        self.activities: list[Dict[str, Any]] = []
        self.notifications: list[Dict[str, Any]] = []
        self.notification_prefs: Dict[str, Dict[str, Any]] = {}
        self.comments: list[Dict[str, Any]] = []
        self.kudos: set[tuple[str, str, str]] = set()
        self.ride_streaks: Dict[str, int] = {}
        self.segment_activity: Dict[tuple[str, int], Dict[str, Any]] = {}
        self.pending_airdrops: list[Dict[str, Any]] = []
        self.waitlist: list[Dict[str, Any]] = []
        self.users_by_email: Dict[str, Dict[str, Any]] = {}
        self.users_by_id: Dict[str, Dict[str, Any]] = {
            self.user_id: {
                "id": self.user_id,
                "wallet": self.wallet,
                "username": None,
                "profile_setup_completed_at": None,
                "ftp_w": 200,
                "weight_kg": 75.0,
            }
        }
        self.daily_loads: Dict[tuple[str, date], Dict[str, Any]] = {}
        self.fitness_metrics: Dict[tuple[str, date], Dict[str, Any]] = {}
        self.rides_by_date: Dict[tuple[str, date], list[Dict[str, Any]]] = {}
        self.rides: Dict[str, Dict[str, Any]] = {}
        self.proofs: Dict[str, Dict[str, Any]] = {}
        self.threshold_projection: Dict[str, Any] = {
            "state": "established",
            "current_w": 245,
            "established_at": "2026-08-17T12:00:00+00:00",
            "last_raised_at": None,
            "pending_monday": None,
            "training_denominator": {
                "watts": 245,
                "kind": "sealed",
                "provisional": False,
            },
        }

    async def create_user(self, wallet: str, email: Optional[str] = None) -> str:
        self.wallet = wallet
        self.last_created = {"wallet": wallet, "email": email, "created_at": self.created_at}  # type: ignore[attr-defined]
        return self.user_id

    async def get_user_id(self, wallet: str) -> Optional[str]:
        return self.user_id if wallet == self.wallet else None

    async def get_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        if wallet != self.wallet:
            return None
        return {
            "id": self.user_id,
            "wallet": self.wallet,
            "email": "",
            "created_at": self.created_at,
        }

    async def get_reward_threshold_rider_projection(self, user_id: str) -> Dict[str, Any]:
        assert user_id == self.user_id
        return dict(self.threshold_projection)

    async def resolve_ride_privacy_policy(
        self,
        user_id: str,
        **overrides: Any,
    ) -> RidePrivacyPolicy:
        assert user_id == self.user_id
        return RidePrivacyPolicy.from_values(
            visibility=overrides.get("visibility") or "public",
            map_visibility=overrides.get("map_visibility") or "hide_start_end",
            map_hide_start_m=(
                overrides.get("map_hide_start_m")
                if overrides.get("map_hide_start_m") is not None
                else 200
            ),
            map_hide_end_m=(
                overrides.get("map_hide_end_m")
                if overrides.get("map_hide_end_m") is not None
                else 200
            ),
        )

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self.users_by_email.get(email.strip().lower())

    async def list_rides_for_user(
        self,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        del user_id
        return self.rides_for_user[offset:offset + limit]

    async def list_counted_climb_steps(
        self, rides: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            str(ride["id"]): self.counted_climb_steps[str(ride["id"])]
            for ride in rides if str(ride["id"]) in self.counted_climb_steps
        }

    async def get_user_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.user_states.get(user_id)

    async def update_cal_balance(self, user_id: str, amount: float) -> Dict[str, Any]:
        state = self.user_states.get(user_id) or {
            "user_id": user_id,
            "cal_balance": 0.0,
            "cal_earned_today": 0.0,
            "last_cal_mint": None,
            "total_rides": 0,
            "total_tss": 0,
            "bio_score": 1000,
        }
        state["cal_balance"] = float(state.get("cal_balance", 0)) + float(amount)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.user_states[user_id] = state
        return state

    async def record_cal_mint(self, user_id: str, amount: float, minted_at: datetime) -> Dict[str, Any]:
        state = await self.update_cal_balance(user_id, amount)
        last_mint = state.get("last_cal_mint")
        if last_mint:
            try:
                last_dt = datetime.fromisoformat(str(last_mint))
            except ValueError:
                last_dt = None
        else:
            last_dt = None

        if last_dt and last_dt.date() == minted_at.date():
            state["cal_earned_today"] = float(state.get("cal_earned_today", 0)) + float(amount)
        else:
            state["cal_earned_today"] = float(amount)
        state["last_cal_mint"] = minted_at.isoformat()
        self.user_states[user_id] = state
        return state

    async def get_user_ride_streak(self, user_id: str) -> int:
        return self.ride_streaks.get(user_id, 0)

    async def create_vesting_schedule(
        self,
        user_id: str,
        token_type: str,
        total_amount: int,
        end_date: datetime,
        source_type: Optional[str],
        source_id: Optional[str],
    ) -> Dict[str, Any]:
        schedule = {
            "id": str(uuid4()),
            "user_id": user_id,
            "token_type": token_type,
            "total_amount": total_amount,
            "end_date": end_date,
            "start_date": datetime.now(timezone.utc),
            "source_type": source_type,
            "source_id": source_id,
        }
        self.vesting_schedules.append(schedule)
        return schedule

    async def get_user_vesting_schedules(self, user_id: str) -> list[Dict[str, Any]]:
        return [s for s in self.vesting_schedules if s.get("user_id") == user_id]

    async def get_user_claims(self, user_id: str) -> list[dict[str, Any]]:
        return [claim for (uid, _), claim in self.claims.items() if uid == user_id]

    async def get_user_claim(self, user_id: str, segment_id: str) -> Optional[Dict[str, Any]]:
        return self.claims.get((user_id, segment_id))

    async def upsert_claim(self, user_id: str, segment_id: str, amount: float, lp_tokens: float) -> None:
        self.claims[(user_id, segment_id)] = {
            "user_id": user_id,
            "segment_id": segment_id,
            "amount": amount,
            "lp_tokens": lp_tokens,
            "staked_at": datetime.now(timezone.utc).isoformat(),
        }

    async def delete_claim(self, user_id: str, segment_id: str) -> None:
        self.claims.pop((user_id, segment_id), None)

    async def deduct_cal(self, user_id: str, amount: float) -> None:
        state = self.user_states.get(user_id) or {
            "user_id": user_id,
            "cal_balance": 0.0,
            "cal_earned_today": 0.0,
            "last_cal_mint": None,
            "total_rides": 0,
            "total_tss": 0,
            "bio_score": 1000,
        }
        if float(state.get("cal_balance") or 0) < float(amount):
            raise ValueError("Insufficient CAL balance")
        state["cal_balance"] = float(state.get("cal_balance", 0)) - float(amount)
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.user_states[user_id] = state

    async def update_user_state(self, user_id: str, updates: dict[str, Any]) -> None:
        state = self.user_states.get(user_id) or {
            "user_id": user_id,
            "cal_balance": 0.0,
            "cal_earned_today": 0.0,
            "last_cal_mint": None,
            "total_rides": 0,
            "total_tss": 0,
            "bio_score": 1000,
        }
        state.update(updates)
        self.user_states[user_id] = state

    async def get_segment_by_id(self, segment_id: str) -> Optional[Dict[str, Any]]:
        return self.segment_by_id.get(segment_id)

    async def get_segment_pool(self, segment_id: str) -> Dict[str, float]:
        """Calculate pool totals from all claims for a segment."""
        claims_for_segment = [
            claim for (uid, sid), claim in self.claims.items()
            if sid == segment_id
        ]
        total_dung = sum(float(claim.get("amount") or 0) for claim in claims_for_segment)
        total_lp = sum(float(claim.get("lp_tokens") or 0) for claim in claims_for_segment)
        return {"total_dung": total_dung, "total_lp": total_lp}

    async def get_current_epoch(self, segment_id: str) -> Optional[Dict[str, Any]]:
        return self.epochs.get(segment_id)

    async def get_epoch(self, segment_id: str, epoch_number: int) -> Optional[Dict[str, Any]]:
        return self.epoch_records.get((segment_id, epoch_number))

    async def get_segment_epoch_activity(self, segment_id: str, epoch_number: int) -> Dict[str, Any]:
        return self.segment_activity.get((segment_id, epoch_number), {})

    async def update_claim_harvest(self, user_id: str, segment_id: str, last_harvest_epoch: int) -> None:
        claim = self.claims.get((user_id, segment_id))
        if claim:
            claim["last_harvest_epoch"] = last_harvest_epoch

    async def create_harvest_event(
        self,
        user_id: str,
        segment_id: str,
        epoch_number: int,
        lp_tokens_held: float,
        dung_harvested: float,
        tx_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        event = {
            "id": str(uuid4()),
            "user_id": user_id,
            "segment_id": segment_id,
            "epoch_number": epoch_number,
            "lp_tokens_held": lp_tokens_held,
            "dung_harvested": dung_harvested,
            "tx_signature": tx_signature,
            "harvested_at": datetime.now(timezone.utc).isoformat(),
        }
        self.harvest_events.append(event)
        return event

    async def get_leaderboard(self, segment_id: str, epoch_number: int, limit: int = 100) -> list[Dict[str, Any]]:
        return self.leaderboards.get((segment_id, epoch_number), [])[:limit]

    async def create_token_transaction(
        self,
        user_id: str,
        tx_type: str,
        token_type: str,
        amount: float,
        balance_after: Optional[float],
        reference_type: Optional[str],
        reference_id: Optional[str],
        tx_signature: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        tx = {
            "id": str(uuid4()),
            "user_id": user_id,
            "tx_type": tx_type,
            "token_type": token_type,
            "amount": amount,
            "balance_after": balance_after,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "tx_signature": tx_signature,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.transactions.append(tx)
        return tx

    async def get_user_transactions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        tx_type: Optional[str] = None,
        token_type: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        txs = [tx for tx in self.transactions if tx["user_id"] == user_id]
        if tx_type:
            txs = [tx for tx in txs if tx.get("tx_type") == tx_type]
        if token_type:
            txs = [tx for tx in txs if tx.get("token_type") == token_type]
        return txs[offset : offset + limit]

    async def get_all_user_transactions(self, user_id: str) -> list[Dict[str, Any]]:
        return [tx for tx in self.transactions if tx["user_id"] == user_id]

    async def save_nonce(
        self,
        wallet: str,
        nonce: str,
        issued_at: datetime,
        expires_at: datetime,
        device_id: str,
    ) -> Dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "wallet": wallet,
            "nonce": nonce,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "device_id": device_id,
            "used_at": None,
        }
        self.nonces[nonce] = record
        return record

    async def get_nonce(self, nonce: str) -> Optional[Dict[str, Any]]:
        return self.nonces.get(nonce)

    async def mark_nonce_used(self, nonce_id: UUID) -> None:
        for record in self.nonces.values():
            if record["id"] == str(nonce_id):
                record["used_at"] = datetime.now(timezone.utc).isoformat()
                break

    async def consume_nonce(self, nonce_id: UUID, wallet: str) -> bool:
        for record in self.nonces.values():
            if record["id"] == str(nonce_id) and record["wallet"] == wallet:
                if record.get("used_at") is not None:
                    return False
                record["used_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False

    async def delete_refresh_tokens_for_device(self, wallet: str, device_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for record in self.refresh_tokens.values():
            if (
                record.get("wallet") == wallet
                and record.get("device_id") == device_id
                and record.get("revoked_at") is None
            ):
                record["revoked_at"] = now
                record["revocation_reason"] = "replaced"

    async def store_refresh_token(
        self,
        wallet: str,
        device_id: str,
        token_hash: str,
        expires_at: datetime,
        user_agent: Optional[str],
        revoke_existing: bool = True,
    ) -> None:
        if revoke_existing:
            await self.delete_refresh_tokens_for_device(wallet, device_id)
        self.refresh_tokens[token_hash] = {
            "wallet": wallet,
            "device_id": device_id,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "user_agent": user_agent,
            "revoked_at": None,
            "revocation_reason": None,
        }

    async def get_refresh_token(self, token_hash: str) -> Optional[Dict[str, Any]]:
        return self.refresh_tokens.get(token_hash)

    async def revoke_refresh_token(
        self, token_hash: str, revoked_at: datetime, reason: str = "revoked"
    ) -> None:
        record = self.refresh_tokens.get(token_hash)
        if record:
            record["revoked_at"] = revoked_at.isoformat()
            record["revocation_reason"] = reason

    async def rotate_refresh_token(
        self,
        *,
        old_token_hash: str,
        new_token_hash: str,
        wallet: str,
        device_id: str,
        expires_at: datetime,
        user_agent: Optional[str],
        rotated_at: datetime,
    ) -> bool:
        record = self.refresh_tokens.get(old_token_hash)
        if not record or record.get("revoked_at") is not None:
            return False
        if record.get("wallet") != wallet or record.get("device_id") != device_id:
            return False
        record["revoked_at"] = rotated_at.isoformat()
        record["revocation_reason"] = "rotated"
        await self.store_refresh_token(
            wallet=wallet,
            device_id=device_id,
            token_hash=new_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            revoke_existing=False,
        )
        return True

    async def list_segments(
        self,
        bbox: Optional[tuple[float, float, float, float]] = None,
        query: Optional[str] = None,
    ) -> list[dict]:
        self.last_segments_args = {
            "bbox": bbox,
            "query": query,
        }  # type: ignore[attr-defined]
        return self.segments

    async def create_ride(
        self,
        user_id: str,
        status: str,
        file_type: Optional[str],
        ride_id: Optional[str] = None,
        started_at: Optional[str] = None,
        tss: float = 0,
        kcals: float = 0,
        duration_sec: int = 0,
        raw_file_path: Optional[str] = None,
        raw_file_size_bytes: Optional[int] = None,
        file_hash: Optional[str] = None,
        preliminary_ride_hash_hex: Optional[str] = None,
        preliminary_parser_version: Optional[int] = None,
        import_diagnostics: Optional[Dict[str, Any]] = None,
        privacy_policy: Optional[RidePrivacyPolicy] = None,
    ) -> str:
        rid = ride_id or str(uuid4())
        record = {
            "id": rid,
            "user_id": user_id,
            "tss": tss or 6,
            "kcals": kcals,
            "duration_sec": duration_sec,
            "started_at": started_at,
            "status": status,
            "file_type": file_type,
            "ride_id": rid,
            "processing_status": status,
            "raw_file_path": raw_file_path,
            "raw_file_size_bytes": raw_file_size_bytes,
            "file_hash": file_hash,
            "preliminary_ride_hash_hex": preliminary_ride_hash_hex,
            "preliminary_parser_version": preliminary_parser_version,
            "import_diagnostics": import_diagnostics,
            **(
                privacy_policy.to_storage_dict()
                if privacy_policy is not None
                else {}
            ),
        }
        self.last_ride = record  # type: ignore[attr-defined]
        self.rides[rid] = record
        return rid

    async def find_ride_by_hash(
        self,
        user_id: str,
        file_hash: str,
    ) -> Optional[Dict[str, Any]]:
        for ride in self.rides.values():
            if ride.get("user_id") == user_id and ride.get("file_hash") == file_hash:
                return ride
        return None

    async def update_ride_status(
        self,
        ride_id: UUID,
        status: str,
        error_message: str | None = None,
        **metrics: Any,
    ) -> None:
        self.last_ride_status = {  # type: ignore[attr-defined]
            "ride_id": str(ride_id),
            "status": status,
            "error_message": error_message,
            "metrics": metrics,
        }
        ride = self.rides.get(str(ride_id))
        if ride:
            ride["processing_status"] = status
            ride.update(metrics)

    async def update_ride_metadata(
        self,
        ride_id: str,
        updates: Dict[str, Any],
    ) -> None:
        ride = self.rides.get(ride_id)
        if ride:
            ride.update(updates)

    async def store_activity_stream(
        self,
        ride_id: UUID,
        stream_type: str,
        timestamps,
        values,
    ) -> UUID:
        stream_id = uuid4()
        self.last_stream = {  # type: ignore[attr-defined]
            "ride_id": str(ride_id),
            "stream_type": stream_type,
            "timestamps": timestamps,
            "values": values,
            "id": str(stream_id),
        }
        return stream_id

    async def get_activity_stream(
        self,
        ride_id: UUID,
        stream_type: str,
    ) -> Optional[Dict]:
        if hasattr(self, "last_stream") and self.last_stream.get("ride_id") == str(ride_id) and self.last_stream.get("stream_type") == stream_type:  # type: ignore[attr-defined]
            return self.last_stream  # type: ignore[attr-defined]
        return None

    async def store_gps_points(
        self,
        ride_id: UUID,
        points,
    ) -> int:
        self.last_gps_points = {  # type: ignore[attr-defined]
            "ride_id": str(ride_id),
            "points": points,
        }
        return len(points)

    async def get_gps_track(
        self,
        ride_id: UUID,
        limit: int = 50000,
    ):
        return self.last_gps_points.get("points", []) if hasattr(self, "last_gps_points") else []  # type: ignore[attr-defined]

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.users_by_id.get(user_id)

    async def get_users_by_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        return [self.users_by_id[uid] for uid in user_ids if uid in self.users_by_id]

    async def create_follow(self, follower_id: str, following_id: str) -> Dict[str, Any]:
        self.follows.add((follower_id, following_id))
        return {"follower_id": follower_id, "following_id": following_id}

    async def delete_follow(self, follower_id: str, following_id: str) -> bool:
        try:
            self.follows.remove((follower_id, following_id))
            return True
        except KeyError:
            return False

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[Dict[str, Any]]:
        return {"follower_id": follower_id, "following_id": following_id} if (follower_id, following_id) in self.follows else None

    async def get_followers(self, user_id: str, limit: int = 50, offset: int = 0) -> list[Dict[str, Any]]:
        ids = [follower for follower, following in self.follows if following == user_id]
        return [self.users_by_id.get(uid, {"id": uid}) for uid in ids][offset : offset + limit]

    async def get_following(self, user_id: str, limit: int = 50, offset: int = 0) -> list[Dict[str, Any]]:
        ids = [following for follower, following in self.follows if follower == user_id]
        return [self.users_by_id.get(uid, {"id": uid}) for uid in ids][offset : offset + limit]

    async def get_following_ids(self, user_id: str) -> list[str]:
        return [following for follower, following in self.follows if follower == user_id]

    async def create_activity(
        self,
        user_id: str,
        activity_type: str,
        title: str,
        description: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_public: bool = True,
    ) -> Dict[str, Any]:
        activity = {
            "id": str(uuid4()),
            "user_id": user_id,
            "activity_type": activity_type,
            "title": title,
            "description": description,
            "target_type": target_type,
            "target_id": target_id,
            "metadata": metadata or {},
            "is_public": is_public,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "kudos_count": 0,
        }
        self.activities.append(activity)
        return activity

    async def get_feed_activities(self, user_ids: list[str], limit: int = 20, before: Optional[datetime] = None) -> list[Dict[str, Any]]:
        acts = [a for a in self.activities if a["user_id"] in user_ids and a.get("is_public", True)]
        acts = sorted(acts, key=lambda a: a.get("created_at"), reverse=True)
        return acts[:limit]

    async def get_global_activities(
        self,
        limit: int = 20,
        before: Optional[datetime] = None,
        activity_type: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        acts = [a for a in self.activities if a.get("is_public", True)]
        if activity_type:
            acts = [a for a in acts if a.get("activity_type") == activity_type]
        acts = sorted(acts, key=lambda a: a.get("created_at"), reverse=True)
        return acts[:limit]

    async def create_notification(
        self,
        user_id: str,
        notification_type: str,
        title: str,
        message: Optional[str],
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        notification = {
            "id": str(uuid4()),
            "user_id": user_id,
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "data": data or {},
            "read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.notifications.append(notification)
        return notification

    async def get_user_notifications(self, user_id: str, limit: int = 50, unread_only: bool = False) -> list[Dict[str, Any]]:
        notif = [n for n in self.notifications if n["user_id"] == user_id]
        if unread_only:
            notif = [n for n in notif if not n.get("read")]
        return sorted(notif, key=lambda n: n["created_at"], reverse=True)[:limit]

    async def get_unread_notification_count(self, user_id: str) -> int:
        return len([n for n in self.notifications if n["user_id"] == user_id and not n.get("read")])

    async def mark_notification_read(self, notification_id: str, user_id: str) -> bool:
        for n in self.notifications:
            if n["id"] == notification_id and n["user_id"] == user_id:
                n["read"] = True
                n["read_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False

    async def mark_all_notifications_read(self, user_id: str) -> int:
        count = 0
        for n in self.notifications:
            if n["user_id"] == user_id and not n.get("read"):
                n["read"] = True
                n["read_at"] = datetime.now(timezone.utc).isoformat()
                count += 1
        return count

    async def get_notification_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.notification_prefs.get(user_id)

    async def upsert_notification_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        prefs = self.notification_prefs.get(user_id, {"user_id": user_id})
        prefs.update(preferences)
        self.notification_prefs[user_id] = prefs
        return prefs

    async def create_comment(
        self,
        user_id: str,
        target_type: str,
        target_id: str,
        content: str,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        comment = {
            "id": str(uuid4()),
            "user_id": user_id,
            "target_type": target_type,
            "target_id": target_id,
            "content": content,
            "parent_id": parent_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self.comments.append(comment)
        return comment

    async def get_comments(self, target_type: str, target_id: str) -> list[Dict[str, Any]]:
        return [c for c in self.comments if c["target_type"] == target_type and c["target_id"] == target_id]

    async def create_kudos(self, user_id: str, target_type: str, target_id: str) -> Dict[str, Any]:
        self.kudos.add((user_id, target_type, target_id))
        return {"user_id": user_id, "target_type": target_type, "target_id": target_id}

    async def get_kudos(self, user_id: str, target_type: str, target_id: str) -> Optional[Dict[str, Any]]:
        return {"user_id": user_id, "target_type": target_type, "target_id": target_id} if (user_id, target_type, target_id) in self.kudos else None

    async def delete_kudos(self, user_id: str, target_type: str, target_id: str) -> bool:
        try:
            self.kudos.remove((user_id, target_type, target_id))
            return True
        except KeyError:
            return False

    async def increment_kudos_count(self, target_type: str, target_id: str) -> None:
        for act in self.activities:
            if act.get("target_type") == target_type and act.get("target_id") == target_id:
                act["kudos_count"] = int(act.get("kudos_count") or 0) + 1

    async def decrement_kudos_count(self, target_type: str, target_id: str) -> None:
        for act in self.activities:
            if act.get("target_type") == target_type and act.get("target_id") == target_id:
                act["kudos_count"] = max(int(act.get("kudos_count") or 0) - 1, 0)

    async def get_user_rides_for_date(self, user_id: str, ride_date: date) -> list[Dict[str, Any]]:
        return self.rides_by_date.get((user_id, ride_date), [])

    async def get_daily_training_load(self, user_id: str, target_date: date) -> Optional[Dict[str, Any]]:
        return self.daily_loads.get((user_id, target_date))

    async def upsert_daily_training_load(
        self,
        user_id: str,
        date: date,
        total_tss: float,
        ride_count: int,
        total_duration_sec: int,
        total_distance_m: float,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "date": date,
            "total_tss": total_tss,
            "ride_count": ride_count,
            "total_duration_sec": total_duration_sec,
            "total_distance_m": total_distance_m,
        }
        self.daily_loads[(user_id, date)] = payload
        return payload

    async def get_daily_training_loads(self, user_id: str, start_date: date, end_date: date) -> list[Dict[str, Any]]:
        return [
            payload
            for (uid, day), payload in sorted(self.daily_loads.items(), key=lambda item: item[0][1])
            if uid == user_id and start_date <= day <= end_date
        ]

    async def get_fitness_metrics(self, user_id: str, target_date: date) -> Optional[Dict[str, Any]]:
        return self.fitness_metrics.get((user_id, target_date))

    async def get_fitness_metrics_range(
        self,
        user_id: str,
        start_date: date,
        end_date: date,
    ) -> list[Dict[str, Any]]:
        return [
            payload
            for (uid, day), payload in sorted(self.fitness_metrics.items(), key=lambda item: item[0][1])
            if uid == user_id and start_date <= day <= end_date
        ]

    async def upsert_fitness_metrics(
        self,
        user_id: str,
        date: date,
        ctl: float,
        atl: float,
        tsb: float,
        ramp_rate: float | None = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "date": date,
            "ctl": ctl,
            "atl": atl,
            "tsb": tsb,
            "ramp_rate": ramp_rate,
        }
        self.fitness_metrics[(user_id, date)] = payload
        return payload

    async def create_proof(
        self,
        ride_id: str,
        effort_score: float,
        signature: str = "",
        user_id: Optional[str] = None,
        proof_id: Optional[str] = None,
        dung_amount: Optional[float] = None,
        proof_hash: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        proof_id = proof_id or str(uuid4())
        record = {
            "id": proof_id,
            "proof_id": proof_id,
            "ride_id": ride_id,
            "effort_score": effort_score,
            "signature": signature,
            "user_id": user_id,
            "dung_amount": dung_amount,
            "proof_hash": proof_hash,
            "status": status,
            "minted": False,
        }
        self.last_proof = record  # type: ignore[attr-defined]
        self.proofs[proof_id] = record
        return proof_id

    async def update_proof_signature(self, proof_id: str, signature: str) -> None:
        if hasattr(self, "last_proof") and self.last_proof.get("proof_id") == proof_id:
            self.last_proof["signature"] = signature

    async def create_mint_event(
        self,
        proof_id: str,
        amount: float,
        tx_hash: str,
        status: str,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        created = (created_at or datetime.now(timezone.utc)).isoformat()
        event_id = str(uuid4())
        self.last_mint = {  # type: ignore[attr-defined]
            "proof_id": proof_id,
            "amount": amount,
            "tx_hash": tx_hash,
            "status": status,
            "created_at": created,
        }
        return {
            "id": event_id,
            "proof_id": proof_id,
            "amount": amount,
            "tx_hash": tx_hash,
            "status": status,
            "created_at": created,
        }

    async def health(self) -> bool:
        return self.health_ok

    async def dispose(self) -> None:
        return

    async def get_token_balances(self, user_id: str) -> Dict[str, float]:
        return self.token_balances

    # Additional abstract methods required by DatabaseRepository
    async def get_ride(self, ride_id: str) -> Optional[Dict[str, Any]]:
        return self.rides.get(str(ride_id))

    async def get_ride_segment_efforts(self, ride_id: UUID) -> list[Dict[str, Any]]:
        return []

    async def get_user_achievements(self, user_id: UUID, limit: int = 50) -> list[Dict[str, Any]]:
        return []

    async def get_proof(self, proof_id: str) -> Optional[Dict[str, Any]]:
        return self.proofs.get(proof_id)

    async def get_proof_for_ride(self, ride_id: str) -> Optional[Dict[str, Any]]:
        for proof in self.proofs.values():
            if proof.get("ride_id") == ride_id:
                return proof
        return None

    async def proof_has_mint(self, proof_id: str) -> bool:
        proof = self.proofs.get(proof_id)
        return bool(proof and proof.get("minted"))

    async def update_proof_status(self, proof_id: str, status: str, tx_signature: Optional[str]) -> None:
        proof = self.proofs.get(proof_id)
        if proof:
            proof["status"] = status
            proof["tx_signature"] = tx_signature

    async def record_mint_event(
        self,
        user_id: str,
        ride_id: str,
        proof_id: str,
        dung_amount: float,
        tx_signature: Optional[str],
        status: str,
    ) -> Dict[str, Any]:
        proof = self.proofs.get(proof_id)
        if proof:
            proof["minted"] = True
        event = {
            "id": str(uuid4()),
            "user_id": user_id,
            "ride_id": ride_id,
            "proof_id": proof_id,
            "dung_amount": dung_amount,
            "tx_signature": tx_signature,
            "status": status,
        }
        return event

    async def refund_cal(self, user_id: str, amount: float) -> None:
        await self.update_cal_balance(user_id, amount)

    async def delete_ride(self, ride_id: str) -> None:
        pass

    async def create_segment_effort(
        self,
        ride_id: UUID,
        user_id: UUID,
        segment_id: int | UUID,
        elapsed_time_sec: int,
        effort_score: float,
        average_power_w: Optional[float],
        average_hr_bpm: Optional[float],
        elevation_gain_m: Optional[float],
        distance_m: Optional[float],
        is_pr: bool,
        is_kom: bool,
        rank_at_time: Optional[int],
    ) -> UUID:
        return uuid4()

    async def get_segment_best_effort(self, segment_id: int | UUID) -> Optional[Dict[str, Any]]:
        return None

    async def get_user_best_segment_effort(self, user_id: UUID, segment_id: int | UUID) -> Optional[Dict[str, Any]]:
        return None

    async def get_segment_effort_rank(self, segment_id: int | UUID, elapsed_time_sec: int) -> Optional[int]:
        return None

    async def create_achievement(
        self,
        user_id: UUID,
        ride_id: UUID,
        achievement_type: str,
        title: str,
        description: str,
        value: Optional[float],
        rank: Optional[int],
        segment_id: Optional[int | UUID],
        metadata: Dict,
    ) -> UUID:
        return uuid4()

    async def get_user_max_power(self, user_id: UUID) -> Optional[float]:
        return None

    async def get_user_total_distance(self, user_id: UUID) -> float:
        return 0.0

    async def get_user_total_elevation(self, user_id: UUID) -> float:
        return 0.0

    async def get_user_ride_count(self, user_id: UUID) -> int:
        return 0

    async def get_user_riding_streak(self, user_id: UUID) -> int:
        return 0

    async def get_user_wallet(self, user_id: UUID) -> Optional[str]:
        return None

    async def check_username_available(self, username: str) -> tuple[bool, Optional[str]]:
        return True, None

    async def update_user_profile(self, wallet: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        return {}

    async def get_user_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        return None

    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        return {}

    async def get_full_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        return None

    async def list_user_sessions(self, wallet: str, current_token_hash: str) -> list[Dict[str, Any]]:
        return []

    async def revoke_session(self, session_id: str, wallet: str) -> bool:
        return False

    async def revoke_all_other_sessions(
        self, wallet: str, current_token_hash: str, reason: str = "revoked"
    ) -> int:
        return 0

    async def revoke_all_sessions(
        self,
        wallet: str,
        include_current: bool,
        current_token_hash: str,
        reason: str = "revoked",
    ) -> int:
        if wallet != self.wallet:
            return 0
        if include_current:
            count = len(self.refresh_tokens)
            for record in self.refresh_tokens.values():
                record["revoked_at"] = datetime.now(timezone.utc).isoformat()
                record["revocation_reason"] = reason
            return count
        return await self.revoke_all_other_sessions(wallet, current_token_hash, reason=reason)

    async def update_session_last_used(self, token_hash: str) -> None:
        pass

    # CAL airdrop methods
    async def get_users_due_for_airdrop(self, limit: int = 100) -> list[Dict[str, Any]]:
        return self.pending_airdrops[:limit]

    async def process_cal_airdrop(self, user_id: str, amount: float) -> Dict[str, Any]:
        state = await self.update_cal_balance(user_id, amount)
        event = {
            "id": str(uuid4()),
            "user_id": user_id,
            "amount": amount,
            "cal_balance": state.get("cal_balance"),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        self.transactions.append(
            {
                "id": str(uuid4()),
                "user_id": user_id,
                "tx_type": "airdrop",
                "token_type": "cal",
                "amount": amount,
                "balance_after": state.get("cal_balance"),
                "reference_type": "airdrop",
                "reference_id": event["id"],
                "tx_signature": None,
                "metadata": {},
                "created_at": event["processed_at"],
            }
        )
        return event

    # Waitlist
    async def add_to_waitlist(self, email: str, source: str, ip_hash: int) -> Dict[str, Any]:
        entry = {
            "id": str(uuid4()),
            "email": email,
            "source": source,
            "ip_hash": ip_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.waitlist.append(entry)
        return entry

    # Tile infrastructure methods (Phase 1)
    async def store_activity_tile_samples(
        self,
        ride_id: UUID,
        tile_samples: list[Dict[str, Any]],
    ) -> int:
        self.last_tile_samples = {
            "ride_id": str(ride_id),
            "tile_samples": tile_samples,
        }
        return len(tile_samples)

    async def update_wallet_tile_history(
        self,
        user_id: UUID,
        tile_ids: list[str],
        visited_at: Optional[datetime] = None,
    ) -> int:
        if not hasattr(self, "wallet_tile_history"):
            self.wallet_tile_history: Dict[str, set] = {}
        wallet = self.wallet
        if wallet not in self.wallet_tile_history:
            self.wallet_tile_history[wallet] = set()
        new_tiles = set(tile_ids) - self.wallet_tile_history[wallet]
        self.wallet_tile_history[wallet].update(tile_ids)
        return len(new_tiles)

    async def get_wallet_tile_history(self, wallet: str) -> set[str]:
        if not hasattr(self, "wallet_tile_history"):
            self.wallet_tile_history: Dict[str, set] = {}
        return self.wallet_tile_history.get(wallet, set())

    # Pattern storage methods (Phase 2)
    async def store_climb_pattern(self, **kwargs) -> str:
        pattern_id = str(kwargs.get("pattern_id", uuid4()))
        if not hasattr(self, "climb_patterns"):
            self.climb_patterns: list = []
        self.climb_patterns.append(kwargs)
        return pattern_id

    async def store_steady_pattern(self, **kwargs) -> str:
        pattern_id = str(kwargs.get("pattern_id", uuid4()))
        self.last_steady_pattern = kwargs
        return pattern_id

    async def store_exploration_pattern(self, **kwargs) -> str:
        pattern_id = str(kwargs.get("pattern_id", uuid4()))
        self.last_exploration_pattern = kwargs
        return pattern_id

    async def get_patterns_for_activity(self, ride_id: UUID) -> Dict[str, Any]:
        return {
            "climb_patterns": getattr(self, "climb_patterns", []),
            "steady_pattern": getattr(self, "last_steady_pattern", None),
            "exploration_pattern": getattr(self, "last_exploration_pattern", None),
        }

    # Helper method used by Supabase repository
    async def _run(self, fn):
        """Mock implementation of _run for async queries."""
        import asyncio
        if asyncio.iscoroutinefunction(fn):
            return await fn()
        return fn()

    @property
    def _client(self):
        """Mock Supabase client for direct table access."""
        class MockResponse:
            data = []
        class MockQuery:
            def select(self, *args, **kwargs): return self
            def eq(self, *args, **kwargs): return self
            def limit(self, *args, **kwargs): return self
            def order(self, *args, **kwargs): return self
            def gte(self, *args, **kwargs): return self
            def lte(self, *args, **kwargs): return self
            def execute(self): return MockResponse()
        class MockTable:
            def table(self, name): return MockQuery()
        return MockTable()


class MockAuthRepository:
    """Mock auth repository for testing."""

    def __init__(self, mock_repo: "MockRepository") -> None:
        self.mock_repo = mock_repo

    @staticmethod
    def _normalize_subject(provider: str, subject: str) -> str:
        if provider == "wallet":
            return subject.strip()
        return subject.strip()

    async def save_nonce(
        self,
        wallet: str,
        nonce: str,
        issued_at: datetime,
        expires_at: datetime,
        device_id: str,
    ) -> Dict[str, Any]:
        nonce_id = str(uuid4())
        record = {
            "id": nonce_id,
            "wallet": wallet,
            "nonce": nonce,
            "issued_at": issued_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "device_id": device_id,
            "used_at": None,
        }
        self.mock_repo.nonces[nonce] = record
        return record

    async def get_nonce(self, nonce: str) -> Optional[Dict[str, Any]]:
        return self.mock_repo.nonces.get(nonce)

    async def mark_nonce_used(self, nonce_id: UUID) -> None:
        for nonce, record in self.mock_repo.nonces.items():
            if record.get("id") == str(nonce_id):
                record["used_at"] = datetime.now(timezone.utc).isoformat()
                break

    async def consume_nonce(self, nonce_id: UUID, wallet: str) -> bool:
        for record in self.mock_repo.nonces.values():
            if record.get("id") == str(nonce_id) and record.get("wallet") == wallet:
                if record.get("used_at") is not None:
                    return False
                record["used_at"] = datetime.now(timezone.utc).isoformat()
                return True
        return False

    async def store_refresh_token(
        self,
        wallet: str,
        device_id: str,
        token_hash: str,
        expires_at: datetime,
        user_agent: Optional[str],
        revoke_existing: bool = True,
    ) -> None:
        if revoke_existing:
            await self.delete_refresh_tokens_for_device(wallet, device_id)
        self.mock_repo.refresh_tokens[token_hash] = {
            "wallet": wallet,
            "device_id": device_id,
            "token_hash": token_hash,
            "expires_at": expires_at.isoformat(),
            "user_agent": user_agent,
            "revoked_at": None,
            "revocation_reason": None,
        }

    async def get_refresh_token(self, token_hash: str) -> Optional[Dict[str, Any]]:
        return self.mock_repo.refresh_tokens.get(token_hash)

    async def revoke_refresh_token(
        self, token_hash: str, revoked_at: datetime, reason: str = "revoked"
    ) -> None:
        record = self.mock_repo.refresh_tokens.get(token_hash)
        if record:
            record["revoked_at"] = revoked_at.isoformat()
            record["revocation_reason"] = reason

    async def rotate_refresh_token(
        self,
        *,
        old_token_hash: str,
        new_token_hash: str,
        wallet: str,
        device_id: str,
        expires_at: datetime,
        user_agent: Optional[str],
        rotated_at: datetime,
    ) -> bool:
        record = self.mock_repo.refresh_tokens.get(old_token_hash)
        if not record or record.get("revoked_at") is not None:
            return False
        if record.get("wallet") != wallet or record.get("device_id") != device_id:
            return False
        record["revoked_at"] = rotated_at.isoformat()
        record["revocation_reason"] = "rotated"
        await self.store_refresh_token(
            wallet=wallet,
            device_id=device_id,
            token_hash=new_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            revoke_existing=False,
        )
        return True

    async def delete_refresh_tokens_for_device(self, wallet: str, device_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        for record in self.mock_repo.refresh_tokens.values():
            if (
                record.get("wallet") == wallet
                and record.get("device_id") == device_id
                and record.get("revoked_at") is None
            ):
                record["revoked_at"] = now
                record["revocation_reason"] = "replaced"

    async def update_session_last_used(self, token_hash: str) -> None:
        pass  # No-op for tests

    async def is_device_known(self, wallet: str, device_id: str) -> bool:
        """Check if a device has been seen before for this wallet."""
        return any(
            record.get("wallet") == wallet and record.get("device_id") == device_id
            for record in self.mock_repo.refresh_tokens.values()
        )

    async def revoke_all_sessions(
        self,
        wallet: str,
        include_current: bool,
        current_token_hash: str,
        reason: str = "revoked",
    ) -> int:
        return await self.mock_repo.revoke_all_sessions(
            wallet,
            include_current,
            current_token_hash,
            reason=reason,
        )

    async def get_identity_user_id(self, provider: str, provider_subject: str) -> Optional[str]:
        key = (provider, self._normalize_subject(provider, provider_subject))
        record = self.mock_repo.identities.get(key)
        if not record:
            return None
        return str(record.get("user_id")) if record.get("user_id") else None

    async def link_wallet_identity(self, user_id: str, wallet: str) -> None:
        subject = self._normalize_subject("wallet", wallet)
        key = ("wallet", subject)
        existing = self.mock_repo.identities.get(key)
        if existing and existing.get("user_id") != user_id:
            raise ValueError("wallet identity already linked to another user")
        self.mock_repo.identities[key] = {
            "user_id": user_id,
            "provider": "wallet",
            "provider_subject": subject,
            "wallet": wallet,
        }

    async def link_privy_identity(
        self,
        user_id: str,
        privy_subject: str,
        wallet: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        subject = self._normalize_subject("privy", privy_subject)
        key = ("privy", subject)
        existing = self.mock_repo.identities.get(key)
        if existing and existing.get("user_id") != user_id:
            raise ValueError("privy identity already linked to another user")
        self.mock_repo.identities[key] = {
            "user_id": user_id,
            "provider": "privy",
            "provider_subject": subject,
            "wallet": wallet,
            "metadata": metadata or {},
        }


class MockInviteSupabase:
    def __init__(self, responses: Dict[str, list[Dict[str, Any]]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, Dict[str, Any]]] = []
        self._current_response: list[Dict[str, Any]] = []

    def rpc(self, name: str, args: Dict[str, Any]) -> "MockInviteSupabase":
        self.calls.append((name, args))
        self._current_response = self.responses.get(name, [])
        return self

    def execute(self) -> SimpleNamespace:
        return SimpleNamespace(data=self._current_response)


class MockUserRepository:
    """Mock user repository for testing."""

    def __init__(self, mock_repo: "MockRepository") -> None:
        self.mock_repo = mock_repo

    async def create_user(self, wallet: str, email: Optional[str] = None) -> str:
        normalized_email = email.strip().lower() if email else None
        if wallet == self.mock_repo.wallet:
            if normalized_email:
                self.mock_repo.users_by_email[normalized_email] = {
                    "id": self.mock_repo.user_id,
                    "wallet": wallet,
                    "email": normalized_email,
                }
            return self.mock_repo.user_id
        # Create new user for different wallets
        new_id = str(uuid4())
        self.mock_repo.users_by_id[new_id] = {
            "id": new_id,
            "wallet": wallet,
            "email": normalized_email or "",
        }
        if normalized_email:
            self.mock_repo.users_by_email[normalized_email] = self.mock_repo.users_by_id[new_id]
        return new_id

    async def get_user_id(self, wallet: str) -> Optional[str]:
        if wallet == self.mock_repo.wallet:
            return self.mock_repo.user_id
        for uid, user in self.mock_repo.users_by_id.items():
            if user.get("wallet") == wallet:
                return uid
        return None

    async def get_auth_account_authority(
        self,
        wallet: str,
    ) -> Dict[str, Optional[str]]:
        authority_override = getattr(
            self.mock_repo,
            "auth_account_authority_override",
            None,
        )
        if isinstance(authority_override, BaseException):
            raise authority_override
        if authority_override is not None:
            return authority_override
        if wallet in getattr(self.mock_repo, "deleted_wallets", set()):
            return {"user_id": None, "account_state": "anonymized"}
        states = getattr(self.mock_repo, "account_states", {})
        user_id = await self.get_user_id(wallet)
        return {
            "user_id": user_id,
            "account_state": states.get(wallet, "active" if user_id else None),
        }

    async def is_wallet_deleted(self, wallet: str) -> bool:
        return wallet in getattr(self.mock_repo, "deleted_wallets", set())

    async def get_account_state(self, wallet: str) -> Optional[str]:
        states = getattr(self.mock_repo, "account_states", {})
        if wallet in states:
            return states[wallet]
        return "active" if await self.get_user_id(wallet) else None

    async def get_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        if wallet == self.mock_repo.wallet:
            return {
                "id": self.mock_repo.user_id,
                "wallet": self.mock_repo.wallet,
                "email": "",
                "created_at": self.mock_repo.created_at,
            }
        for user in self.mock_repo.users_by_id.values():
            if user.get("wallet") == wallet:
                return user
        return None

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        return self.mock_repo.users_by_email.get(email.strip().lower())

    async def get_user_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self.mock_repo.user_states.get(user_id)

    async def get_full_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        if wallet == self.mock_repo.wallet:
            record = self.mock_repo.users_by_id.get(self.mock_repo.user_id, {})
            return {
                "id": self.mock_repo.user_id,
                "wallet": wallet,
                "username": record.get("username"),
                "profile_setup_completed_at": record.get("profile_setup_completed_at"),
            }
        for user in self.mock_repo.users_by_id.values():
            if user.get("wallet") == wallet:
                return user
        return None

    async def get_profile_setup_state(self, wallet: str) -> Optional[Dict[str, Any]]:
        if wallet == self.mock_repo.wallet:
            record = self.mock_repo.users_by_id.get(self.mock_repo.user_id, {})
            return {
                "id": self.mock_repo.user_id,
                "username": record.get("username"),
                "profile_setup_completed_at": record.get("profile_setup_completed_at"),
            }
        for user in self.mock_repo.users_by_id.values():
            if user.get("wallet") == wallet:
                return {
                    "id": user.get("id"),
                    "username": user.get("username"),
                    "profile_setup_completed_at": user.get("profile_setup_completed_at"),
                }
        return None

    async def get_private_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        if wallet == self.mock_repo.wallet:
            record = self.mock_repo.users_by_id.get(self.mock_repo.user_id, {})
            return {
                "id": self.mock_repo.user_id,
                "wallet": wallet,
                "username": record.get("username"),
                "profile_setup_completed_at": record.get("profile_setup_completed_at"),
                "ftp_w": record.get("ftp_w", 200),
                "weight_kg": record.get("weight_kg", 75.0),
                "preferred_units": record.get("preferred_units", "metric"),
                "is_public": record.get("is_public", True),
            }
        for user in self.mock_repo.users_by_id.values():
            if user.get("wallet") == wallet:
                return user
        return None

    async def update_user_profile(self, wallet: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        if wallet == self.mock_repo.wallet:
            record = self.mock_repo.users_by_id.setdefault(
                self.mock_repo.user_id,
                {"id": self.mock_repo.user_id, "wallet": wallet},
            )
        else:
            record = next((user for user in self.mock_repo.users_by_id.values() if user.get("wallet") == wallet), None)
            if record is None:
                return {}
        record.update(updates)
        if record.get("username") and not record.get("profile_setup_completed_at"):
            record["profile_setup_completed_at"] = datetime.now(timezone.utc).isoformat()
        return dict(record)

    async def update_user_state(self, user_id: str, updates: Dict[str, Any]) -> None:
        state = self.mock_repo.user_states.get(user_id, {"user_id": user_id})
        state.update(updates)
        self.mock_repo.user_states[user_id] = state


class MockTokenRepository:
    """Mock token repository for testing."""

    def __init__(self) -> None:
        self.transactions: list[Dict[str, Any]] = []

    async def create_token_transaction(
        self,
        user_id: str,
        tx_type: str,
        token_type: str,
        amount: float,
        balance_after: Optional[float] = None,
        reference_type: Optional[str] = None,
        reference_id: Optional[str] = None,
        tx_signature: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        record = {
            "id": str(uuid4()),
            "user_id": user_id,
            "tx_type": tx_type,
            "token_type": token_type,
            "amount": amount,
            "balance_after": balance_after,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "tx_signature": tx_signature,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.transactions.append(record)
        return record


class _StaticQueryResult:
    def __init__(self, data: list[dict[str, Any]]) -> None:
        self.data = data


class _StaticSupabaseQuery:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = [dict(row) for row in rows]
        self._limit: Optional[int] = None
        self._range: Optional[tuple[int, int]] = None

    def select(self, _fields: str) -> "_StaticSupabaseQuery":
        return self

    def eq(self, key: str, value: Any) -> "_StaticSupabaseQuery":
        self._rows = [row for row in self._rows if row.get(key) == value]
        return self

    def ilike(self, key: str, pattern: str) -> "_StaticSupabaseQuery":
        needle = pattern.strip("%").lower()
        self._rows = [row for row in self._rows if needle in str(row.get(key) or "").lower()]
        return self

    def in_(self, key: str, values: list[Any]) -> "_StaticSupabaseQuery":
        allowed = set(values)
        self._rows = [row for row in self._rows if row.get(key) in allowed]
        return self

    def gte(self, key: str, value: Any) -> "_StaticSupabaseQuery":
        self._rows = [row for row in self._rows if row.get(key) is not None and row.get(key) >= value]
        return self

    def lte(self, key: str, value: Any) -> "_StaticSupabaseQuery":
        self._rows = [row for row in self._rows if row.get(key) is not None and row.get(key) <= value]
        return self

    def order(self, key: str, desc: bool = False) -> "_StaticSupabaseQuery":
        self._rows = sorted(self._rows, key=lambda row: row.get(key) or 0, reverse=desc)
        return self

    def limit(self, value: int) -> "_StaticSupabaseQuery":
        self._limit = value
        return self

    def range(self, start: int, end: int) -> "_StaticSupabaseQuery":
        self._range = (start, end)
        return self

    def execute(self) -> _StaticQueryResult:
        rows = self._rows
        if self._range is not None:
            start, end = self._range
            rows = rows[start:end + 1]
        if self._limit is not None:
            rows = rows[: self._limit]
        return _StaticQueryResult(rows)


class _StaticSupabaseClient:
    def __init__(self, tables: dict[str, list[dict[str, Any]]]) -> None:
        self._tables = tables

    def from_(self, table: str) -> _StaticSupabaseQuery:
        return _StaticSupabaseQuery(self._tables.get(table, []))


class _FailOnQuerySupabaseClient:
    def from_(self, table: str) -> _StaticSupabaseQuery:
        raise AssertionError(f"canonical invalid ID queried {table}")


class SegmentApiRepository(MockRepository):
    def __init__(
        self,
        climb_vault_rows: Optional[list[dict[str, Any]]] = None,
        indexed_vault_rows: Optional[list[dict[str, Any]]] = None,
        vault_leaderboard_rows: Optional[list[dict[str, Any]]] = None,
        indexed_leaderboard_rows: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__()
        self.client = _StaticSupabaseClient({
            "climb_vault": climb_vault_rows or [],
            "indexed_vaults": indexed_vault_rows or [],
            "vault_leaderboards": vault_leaderboard_rows or [],
            "indexed_leaderboards": indexed_leaderboard_rows or [],
        })


_mock_token_repo = MockTokenRepository()


def _override_token_repository() -> MockTokenRepository:
    return _mock_token_repo


def _build_test_client(repo: MockRepository) -> TestClient:
    app = create_app()

    async def _override_repository() -> AsyncGenerator[DatabaseRepository, None]:
        try:
            yield repo
        finally:
            await repo.dispose()

    # Create mock auth and user repos that share state with main mock repo
    mock_auth_repo = MockAuthRepository(repo)
    mock_user_repo = MockUserRepository(repo)

    def _override_auth_repository() -> MockAuthRepository:
        return mock_auth_repo

    def _override_user_repository() -> MockUserRepository:
        return mock_user_repo

    async def _is_admitted(user_id):
        return bool(repo.users_by_id.get(user_id, {}).get('cohort_admitted_at'))
    app.dependency_overrides[get_admission_repository] = lambda: SimpleNamespace(is_admitted=_is_admitted)
    app.dependency_overrides[get_repository] = _override_repository
    app.dependency_overrides[get_ride_repository] = lambda: repo
    app.dependency_overrides[get_token_repository] = _override_token_repository
    app.dependency_overrides[get_auth_repository] = _override_auth_repository
    app.dependency_overrides[get_user_repository] = _override_user_repository
    return TestClient(app)


def authenticate(client: TestClient, repo: MockRepository) -> tuple[str, str, str]:
    device_id = str(uuid4())
    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "device_id": device_id})
    assert nonce_res.status_code == 200
    nonce = nonce_res.json()["nonce"]

    verify_res = client.post(
        "/auth/verify",
        json={
            "wallet": repo.wallet,
            "signature": "stub-signature",
            "nonce": nonce,
            "device_id": device_id,
        },
    )
    assert verify_res.status_code == 200
    body = verify_res.json()
    return device_id, body["access_token"], body["refresh_token"]


def _install_signing_wallet(repo: MockRepository) -> SigningKey:
    signing_key = SigningKey.generate()
    repo.wallet = base58.b58encode(bytes(signing_key.verify_key)).decode()
    return signing_key


def _sign_proof_payload(
    signing_key: SigningKey,
    wallet: str,
    ride: dict[str, Any],
    *,
    effort_score: float,
) -> str:
    message = _build_proof_verification_message(
        wallet=wallet,
        ride=ride,
        effort_score=effort_score,
    )
    return base58.b58encode(signing_key.sign(message.encode("utf-8")).signature).decode()


def test_auth_flow() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, access_token, refresh_token = authenticate(client, repo)

    nonce_record = next(iter(repo.nonces.values()))
    assert nonce_record["used_at"] is not None

    token_hash = hash_refresh_token(refresh_token)
    record = repo.refresh_tokens.get(token_hash)
    assert record is not None
    assert record["wallet"] == repo.wallet
    assert record["device_id"] == device_id


def test_authenticated_route_translates_account_authority_outage_before_mutation() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)
    repo.auth_account_authority_override = RuntimeError(  # type: ignore[attr-defined]
        "database unavailable"
    )

    with patch.object(
        MockUserRepository,
        "create_user",
        new=AsyncMock(side_effect=AssertionError("must not create during authority outage")),
    ):
        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "account_authority_unavailable"


def test_authenticated_route_translates_account_deletion_fence_to_unauthorized() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)
    repo.auth_account_authority_override = RuntimeError(  # type: ignore[attr-defined]
        "account_deletion_write_fenced"
    )

    response = client.get(
        "/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 401
    detail = response.json()["detail"]["error"]
    assert detail["code"] == "account_deletion_pending"
    assert detail["message"] == "Account deletion is in progress"


def test_authenticated_route_emits_stable_account_lifecycle_codes() -> None:
    cases = (
        ("deletion_pending", "account_deletion_pending"),
        ("anonymized", "account_deleted"),
    )
    for account_state, expected_code in cases:
        repo = MockRepository()
        client = _build_test_client(repo)
        _device_id, access_token, _refresh_token = authenticate(client, repo)
        repo.auth_account_authority_override = {  # type: ignore[attr-defined]
            "user_id": None,
            "account_state": account_state,
        }

        response = client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == 401
        assert response.json()["detail"]["error"]["code"] == expected_code


def test_refresh_rotates_token() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, access_token, old_refresh_token = authenticate(client, repo)
    old_hash = hash_refresh_token(old_refresh_token)

    refresh_res = client.post(
        "/auth/refresh",
        json={"device_id": device_id},
    )
    assert refresh_res.status_code == 200
    body = refresh_res.json()
    assert body["access_token"] != access_token
    assert body["wallet"] == repo.wallet
    new_hash = hash_refresh_token(body["refresh_token"])
    assert repo.refresh_tokens[old_hash]["revoked_at"] is not None
    assert repo.refresh_tokens[old_hash]["revocation_reason"] == "rotated"
    assert repo.refresh_tokens[new_hash]["revoked_at"] is None


def test_refresh_fails_closed_when_identity_is_missing_during_tombstone_outage() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, _access_token, refresh_token = authenticate(client, repo)
    token_hash = hash_refresh_token(refresh_token)
    repo.auth_account_authority_override = {  # type: ignore[attr-defined]
        "user_id": None,
        "account_state": None,
    }

    refresh_res = client.post(
        "/auth/refresh",
        json={"device_id": device_id},
    )

    assert refresh_res.status_code == 401
    detail = refresh_res.json().get("detail", {}).get("error", {})
    assert detail.get("code") == "account_identity_unavailable"
    assert repo.refresh_tokens[token_hash]["revoked_at"] is None
    assert len(repo.refresh_tokens) == 1


def test_refresh_rejects_a_tombstoned_wallet_even_with_an_active_user_row() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, _access_token, refresh_token = authenticate(client, repo)
    token_hash = hash_refresh_token(refresh_token)
    repo.deleted_wallets = {repo.wallet}  # type: ignore[attr-defined]

    refresh_res = client.post(
        "/auth/refresh",
        json={"device_id": device_id},
    )

    assert refresh_res.status_code == 401
    assert refresh_res.json()["detail"]["error"]["code"] == "account_deleted"
    assert repo.refresh_tokens[token_hash]["revoked_at"] is None
    assert len(repo.refresh_tokens) == 1


def test_recent_refresh_rotation_does_not_revoke_sessions() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, _access_token, old_refresh_token = authenticate(client, repo)

    # Rotate once to invalidate previous refresh token.
    refresh_res = client.post("/auth/refresh", json={"device_id": device_id})
    assert refresh_res.status_code == 200
    active_hash = hash_refresh_token(refresh_res.json()["refresh_token"])

    # Immediate replay is a benign concurrency/retry race, not proof of theft.
    client.cookies.set("refresh_token", old_refresh_token)
    replay_res = client.post("/auth/refresh", json={"device_id": device_id})
    assert replay_res.status_code == 409
    detail = replay_res.json().get("detail", {}).get("error", {})
    assert detail.get("code") == "refresh_rotated"
    assert repo.refresh_tokens[active_hash]["revoked_at"] is None


def test_refresh_reuse_after_rotation_grace_revokes_sessions() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, _access_token, old_refresh_token = authenticate(client, repo)
    old_hash = hash_refresh_token(old_refresh_token)

    refresh_res = client.post("/auth/refresh", json={"device_id": device_id})
    assert refresh_res.status_code == 200
    active_hash = hash_refresh_token(refresh_res.json()["refresh_token"])

    repo.refresh_tokens[old_hash]["revoked_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=60)
    ).isoformat()
    repo.refresh_tokens[old_hash]["revocation_reason"] = "rotated"

    client.cookies.set("refresh_token", old_refresh_token)
    replay_res = client.post("/auth/refresh", json={"device_id": device_id})
    assert replay_res.status_code == 401
    detail = replay_res.json().get("detail", {}).get("error", {})
    assert detail.get("code") == "refresh_reuse_detected"
    assert repo.refresh_tokens[active_hash]["revoked_at"] is not None
    assert repo.refresh_tokens[active_hash]["revocation_reason"] == "refresh_reuse_detected"


def test_missing_refresh_record_does_not_revoke_active_sessions() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, _access_token, old_refresh_token = authenticate(client, repo)
    old_hash = hash_refresh_token(old_refresh_token)

    refresh_res = client.post("/auth/refresh", json={"device_id": device_id})
    assert refresh_res.status_code == 200
    active_hash = hash_refresh_token(refresh_res.json()["refresh_token"])
    repo.refresh_tokens.pop(old_hash)

    client.cookies.set("refresh_token", old_refresh_token)
    replay_res = client.post("/auth/refresh", json={"device_id": device_id})
    assert replay_res.status_code == 401
    detail = replay_res.json().get("detail", {}).get("error", {})
    assert detail.get("code") == "refresh_unknown"
    assert repo.refresh_tokens[active_hash]["revoked_at"] is None


def test_auth_request_contract_accepts_camel_case_fields() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id = str(uuid4())

    nonce_res = client.post("/auth/nonce", json={"wallet": repo.wallet, "deviceId": device_id})
    assert nonce_res.status_code == 200
    nonce = nonce_res.json()["nonce"]

    verify_res = client.post(
        "/auth/verify",
        json={
            "wallet": repo.wallet,
            "signature": "stub-signature",
            "nonce": nonce,
            "deviceId": device_id,
        },
    )
    assert verify_res.status_code == 200
    body = verify_res.json()
    assert body["wallet"] == repo.wallet
    assert "access_token" in body


def test_onboarding_state_reflects_invite_and_authentication() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)

    initial = client.get("/auth/onboarding/state")
    assert initial.status_code == 200
    initial_body = initial.json()
    assert initial_body["authenticated"] is False
    assert initial_body["invite_validated"] is False

    with (
        patch("app.routes.auth.get_supabase_client", return_value=None),
        patch.dict(
            os.environ,
            {"INVITE_CODES": "alpha-code-1,alpha-code-2,alpha-code-3,alpha-code-4"},
        ),
    ):
        invite_res = client.post("/auth/invite/validate", json={"code": "alpha-code-1"})
    assert invite_res.status_code == 200
    assert invite_res.json()["valid"] is True

    invited = client.get("/auth/onboarding/state")
    assert invited.status_code == 200
    invited_body = invited.json()
    assert invited_body["authenticated"] is False
    assert invited_body["invite_validated"] is True

    authenticate(client, repo)
    authed = client.get("/auth/onboarding/state")
    assert authed.status_code == 200
    authed_body = authed.json()
    assert authed_body["authenticated"] is True
    assert authed_body["auth_method_hint"] == "wallet"
    assert authed_body["needs_profile_setup"] is True

    repo.users_by_id[repo.user_id]["username"] = "testuser"
    username_only = client.get("/auth/onboarding/state")
    assert username_only.status_code == 200
    assert username_only.json()["needs_profile_setup"] is True

    repo.users_by_id[repo.user_id]["profile_setup_completed_at"] = datetime.now(timezone.utc).isoformat()
    completed = client.get("/auth/onboarding/state")
    assert completed.status_code == 200
    assert completed.json()["needs_profile_setup"] is False


def test_email_preflight_is_not_a_public_membership_oracle() -> None:
    client = _build_test_client(MockRepository())

    responses = [
        client.post("/auth/email/preflight", json={"email": email})
        for email in ("known@example.com", "unknown@example.com")
    ]

    assert [response.status_code for response in responses] == [404, 404]
    assert responses[0].json() == responses[1].json()


def test_invite_validate_uses_non_mutating_check_rpc() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    code_id = str(uuid4())
    supabase = MockInviteSupabase(
        {
            "check_invite_code": [
                {"valid": True, "message": "Invite code valid", "code_id": code_id}
            ]
        }
    )

    with patch("app.routes.auth.get_supabase_client", return_value=supabase):
        response = client.post("/auth/invite/validate", json={"code": " ALPHA-CODE-1 "})

    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert supabase.calls == [("check_invite_code", {"p_code": hash_invite_code("alpha-code-1")})]


def test_invite_validate_surfaces_check_failures_without_wallet() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)

    for message in (
        "Invalid invite code",
        "Invite code has expired",
        "Invite code has reached maximum uses",
    ):
        supabase = MockInviteSupabase(
            {"check_invite_code": [{"valid": False, "message": message, "code_id": None}]}
        )
        with patch("app.routes.auth.get_supabase_client", return_value=supabase):
            response = client.post("/auth/invite/validate", json={"code": "alpha-code-1"})

        assert response.status_code == 200
        assert response.json() == {"valid": False, "message": message, "code_id": None}
        assert supabase.calls == [("check_invite_code", {"p_code": hash_invite_code("alpha-code-1")})]


def test_wallet_signup_consumes_invite_once_wallet_is_known() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = "new-wallet-invite-consume"
    device_id = str(uuid4())
    code_id = str(uuid4())
    supabase = MockInviteSupabase(
        {
            "consume_invite_code": [
                {"valid": True, "message": "Invite code consumed", "code_id": code_id}
            ]
        }
    )

    nonce_res = client.post("/auth/nonce", json={"wallet": wallet, "device_id": device_id})
    assert nonce_res.status_code == 200

    with (
        patch("app.routes.auth.auth_settings.require_invite_code", True),
        patch("app.routes.auth.get_supabase_client", return_value=supabase),
    ):
        verify_res = client.post(
            "/auth/verify",
            json={
                "wallet": wallet,
                "signature": "stub-signature",
                "nonce": nonce_res.json()["nonce"],
                "device_id": device_id,
                "inviteCode": "ALPHA-CODE-1",
            },
        )

    assert verify_res.status_code == 200
    assert supabase.calls
    call_name, call_args = supabase.calls[0]
    assert call_name == "consume_invite_code"
    assert call_args["p_code"] == hash_invite_code("alpha-code-1")
    assert call_args["p_wallet"] == wallet
    assert call_args["p_ip_address"]
    assert call_args["p_user_agent"]


def test_wallet_signup_accepts_legacy_shared_idempotent_invite_consumption() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = "new-wallet-invite-repeat"
    device_id = str(uuid4())
    code_id = str(uuid4())
    supabase = MockInviteSupabase(
        {
            "consume_invite_code": [
                {
                    "valid": True,
                    "message": "Invite code valid (already used by this wallet)",
                    "code_id": code_id,
                }
            ]
        }
    )

    nonce_res = client.post("/auth/nonce", json={"wallet": wallet, "device_id": device_id})
    assert nonce_res.status_code == 200

    with (
        patch("app.routes.auth.auth_settings.require_invite_code", True),
        patch("app.routes.auth.get_supabase_client", return_value=supabase),
    ):
        verify_res = client.post(
            "/auth/verify",
            json={
                "wallet": wallet,
                "signature": "stub-signature",
                "nonce": nonce_res.json()["nonce"],
                "device_id": device_id,
                "inviteCode": "ALPHA-CODE-1",
            },
        )

    assert verify_res.status_code == 200
    assert supabase.calls[0][0] == "consume_invite_code"


def test_logout_revokes_refresh_and_clears_cookies() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    device_id, _access_token, refresh_token = authenticate(client, repo)
    token_hash = hash_refresh_token(refresh_token)

    logout_res = client.post("/auth/logout", json={"device_id": device_id})
    assert logout_res.status_code == 200
    assert logout_res.json()["status"] == "logged_out"

    record = repo.refresh_tokens.get(token_hash)
    assert record is not None
    assert record["token_hash"] == token_hash
    assert record["revoked_at"] is not None
    assert record["revocation_reason"] == "logged_out"

    set_cookie_headers = logout_res.headers.get_list("set-cookie")
    assert any("access_token=\"\"" in header for header in set_cookie_headers)
    assert any("refresh_token=\"\"" in header for header in set_cookie_headers)


def test_deleted_wallet_authority_wins_before_new_user_invite_handling() -> None:
    repo = MockRepository()
    repo.deleted_wallets = {repo.wallet}  # type: ignore[attr-defined]
    client = _build_test_client(repo)
    device_id = str(uuid4())
    nonce = client.post(
        "/auth/nonce",
        json={"wallet": repo.wallet, "device_id": device_id},
    ).json()["nonce"]

    with patch("app.routes.auth.auth_settings.require_invite_code", True):
        response = client.post(
            "/auth/verify",
            json={
                "wallet": repo.wallet,
                "signature": "stub-signature",
                "nonce": nonce,
                "device_id": device_id,
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "account_deleted"


def test_wallet_identity_cannot_bypass_an_unavailable_account_authority() -> None:
    repo = MockRepository()
    repo.identities[("wallet", repo.wallet)] = {
        "user_id": repo.user_id,
        "provider": "wallet",
        "provider_subject": repo.wallet,
    }
    client = _build_test_client(repo)
    device_id = str(uuid4())
    nonce = client.post(
        "/auth/nonce",
        json={"wallet": repo.wallet, "device_id": device_id},
    ).json()["nonce"]
    repo.auth_account_authority_override = RuntimeError(  # type: ignore[attr-defined]
        "database unavailable"
    )

    response = client.post(
        "/auth/verify",
        json={
            "wallet": repo.wallet,
            "signature": "stub-signature",
            "nonce": nonce,
            "device_id": device_id,
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "account_authority_unavailable"
    assert repo.refresh_tokens == {}


def test_privy_verify_accepts_alias_and_links_identity() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = "privy-wallet-test"
    device_id = str(uuid4())

    privy_user = {
        "linked_accounts": [
            {"type": "wallet", "chain_type": "solana", "address": wallet}
        ],
    }
    with (
        patch("app.routes.auth.verify_privy_token") as mock_verify,
        patch("app.routes.auth.fetch_privy_user", return_value=privy_user),
    ):
        mock_verify.return_value = {
            "sub": "did:privy:test-user",
            "linked_accounts": [
                {"type": "wallet", "chain_type": "solana", "address": wallet}
            ],
            "iss": "https://auth.privy.io",
            "aud": "boulderrollers",
        }
        response = client.post(
            "/auth/privy/verify",
            json={
                "wallet": wallet,
                "privyToken": "token-from-privy",
                "deviceId": device_id,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["wallet"] == wallet

    user_id = next(
        uid
        for uid, user in repo.users_by_id.items()
        if user.get("wallet") == wallet
    )
    assert repo.identities[("wallet", wallet)]["user_id"] == user_id
    assert repo.identities[("privy", "did:privy:test-user")]["user_id"] == user_id


def test_privy_identity_cannot_bypass_an_unavailable_account_authority() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    privy_subject = "did:privy:deleted-residual"
    repo.identities[("privy", privy_subject)] = {
        "user_id": repo.user_id,
        "provider": "privy",
        "provider_subject": privy_subject,
    }
    repo.auth_account_authority_override = RuntimeError(  # type: ignore[attr-defined]
        "database unavailable"
    )
    privy_user = {
        "linked_accounts": [
            {"type": "wallet", "chain_type": "solana", "address": repo.wallet}
        ],
    }
    with (
        patch("app.routes.auth.verify_privy_token") as mock_verify,
        patch("app.routes.auth.fetch_privy_user", return_value=privy_user),
    ):
        mock_verify.return_value = {
            "sub": privy_subject,
            "iss": "https://auth.privy.io",
            "aud": "boulderrollers",
        }
        response = client.post(
            "/auth/privy/verify",
            json={
                "wallet": repo.wallet,
                "privyToken": "token-from-privy",
                "deviceId": str(uuid4()),
            },
        )

    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "account_authority_unavailable"
    assert repo.refresh_tokens == {}


def test_privy_email_backfill_failure_does_not_abort_a_returning_rider_login() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = repo.wallet
    device_id = str(uuid4())
    privy_subject = "did:privy:returning-user"
    privy_user = {
        "linked_accounts": [
            {"type": "wallet", "chain_type": "solana", "address": wallet},
            {"type": "email", "address": "rider@example.test"},
        ],
    }
    with (
        patch("app.routes.auth.verify_privy_token") as mock_verify,
        patch("app.routes.auth.fetch_privy_user", return_value=privy_user),
        patch.object(
            MockUserRepository,
            "update_user_profile",
            new=AsyncMock(side_effect=RuntimeError("profile write unavailable")),
        ),
    ):
        mock_verify.return_value = {
            "sub": privy_subject,
            "iss": "https://auth.privy.io",
            "aud": "boulderrollers",
        }
        response = client.post(
            "/auth/privy/verify",
            json={
                "wallet": wallet,
                "privyToken": "token-from-privy",
                "deviceId": device_id,
            },
        )

    assert response.status_code == 200
    assert repo.identities[("wallet", wallet)]["user_id"] == repo.user_id
    assert repo.identities[("privy", privy_subject)]["user_id"] == repo.user_id


def test_privy_email_backfill_does_not_swallow_account_deletion_fence() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = repo.wallet
    device_id = str(uuid4())
    privy_user = {
        "linked_accounts": [
            {"type": "wallet", "chain_type": "solana", "address": wallet},
            {"type": "email", "address": "rider@example.test"},
        ],
    }
    with (
        patch("app.routes.auth.verify_privy_token") as mock_verify,
        patch("app.routes.auth.fetch_privy_user", return_value=privy_user),
        patch.object(
            MockUserRepository,
            "update_user_profile",
            new=AsyncMock(side_effect=RuntimeError("account_deletion_write_fenced")),
        ),
    ):
        mock_verify.return_value = {
            "sub": "did:privy:fenced-user",
            "iss": "https://auth.privy.io",
            "aud": "boulderrollers",
        }
        response = client.post(
            "/auth/privy/verify",
            json={
                "wallet": wallet,
                "privyToken": "token-from-privy",
                "deviceId": device_id,
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "account_deletion_pending"


def test_privy_verify_same_device_can_login_twice() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = "privy-wallet-repeat"
    device_id = str(uuid4())

    privy_user = {
        "linked_accounts": [
            {"type": "wallet", "chain_type": "solana", "address": wallet}
        ],
    }
    with (
        patch("app.routes.auth.verify_privy_token") as mock_verify,
        patch("app.routes.auth.fetch_privy_user", return_value=privy_user),
    ):
        mock_verify.return_value = {
            "sub": "did:privy:repeat-user",
            "linked_accounts": [
                {"type": "wallet", "chain_type": "solana", "address": wallet}
            ],
            "iss": "https://auth.privy.io",
            "aud": "boulderrollers",
        }
        first = client.post(
            "/auth/privy/verify",
            json={
                "wallet": wallet,
                "privyToken": "token-from-privy",
                "deviceId": device_id,
            },
        )
        second = client.post(
            "/auth/privy/verify",
            json={
                "wallet": wallet,
                "privyToken": "token-from-privy",
                "deviceId": device_id,
            },
        )

    assert first.status_code == 200
    assert second.status_code == 200

    first_hash = hash_refresh_token(first.json()["refresh_token"])
    second_hash = hash_refresh_token(second.json()["refresh_token"])
    assert first_hash != second_hash
    assert repo.refresh_tokens[first_hash]["revoked_at"] is not None
    assert repo.refresh_tokens[first_hash]["revocation_reason"] == "replaced"
    assert repo.refresh_tokens[second_hash]["revoked_at"] is None


def test_privy_identity_conflict_returns_409() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = "privy-conflict-wallet"
    device_id = str(uuid4())
    wallet_user_id = str(uuid4())
    conflicting_user_id = str(uuid4())
    repo.users_by_id[wallet_user_id] = {
        "id": wallet_user_id,
        "wallet": wallet,
        "email": "",
    }
    repo.identities[("privy", "did:privy:conflict")] = {
        "user_id": conflicting_user_id,
        "provider": "privy",
        "provider_subject": "did:privy:conflict",
    }

    privy_user = {
        "linked_accounts": [
            {"type": "wallet", "chain_type": "solana", "address": wallet}
        ],
    }
    with (
        patch("app.routes.auth.verify_privy_token") as mock_verify,
        patch("app.routes.auth.fetch_privy_user", return_value=privy_user),
    ):
        mock_verify.return_value = {
            "sub": "did:privy:conflict",
            "linked_accounts": [
                {"type": "wallet", "chain_type": "solana", "address": wallet}
            ],
            "iss": "https://auth.privy.io",
            "aud": "boulderrollers",
        }
        response = client.post(
            "/auth/privy/verify",
            json={
                "wallet": wallet,
                "privy_token": "token-from-privy",
                "device_id": device_id,
            },
        )

    assert response.status_code == 409
    detail = response.json().get("detail", {}).get("error", {})
    assert detail.get("code") == "identity_conflict"


def test_get_rides_returns_user_rides() -> None:
    repo = MockRepository()
    ride_id = str(uuid4())
    repo.rides_for_user = [
        {
            "id": ride_id,
            "user_id": repo.user_id,
            "started_at": "2024-10-01T12:00:00Z",
            "kcals": 450,
            "completed_at": None,
            "segments": [],
        }
    ]
    client = _build_test_client(repo)
    _device_id, access_token, _ = authenticate(client, repo)
    response = client.get("/rides", headers={"Authorization": f"Bearer {access_token}"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == ride_id
    assert body[0]["calories"] == 450
    assert "countedSpans" not in body[0]  # No recorded shape or counted authority.


def test_get_ride_detail_uses_frontend_alias_fields() -> None:
    repo = MockRepository()
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "started_at": "2024-10-01T12:00:00Z",
        "completed_at": "2024-10-01T14:00:00Z",
        "processing_status": "completed",
        "distance_m": 42000.0,
        "elevation_gain_m": 900.0,
        "duration_sec": 7200,
        "kcals": 1100.0,
        "tss": 215.0,
        "avg_power_w": 250.0,
        "normalized_power_w": 265.0,
        "cal_earned": 120,
        "place_label": "Boulder, CO",
        "gps_track": [
            {"lat": 40.0101, "lon": -105.2502, "ele": 1600.0, "t": 0},
            {"lat": 40.0111, "lon": -105.2512, "ele": 1604.5, "t": 5},
            {"lat": 40.0121, "lon": -105.2522, "ele": 1611.0, "t": 10},
        ],
        "ride_hash_hex": "ab" * 32,
        "attestation_commitment_hex": "cd" * 32,
        "ride_parser_version": 1,
        "ride_attestation_pda": "2" * 44,
        "ride_attestation_tx_signature": "3" * 88,
        "ride_attested_at": "2024-10-01T14:01:00Z",
    }

    client = _build_test_client(repo)
    _device_id, access_token, _ = authenticate(client, repo)
    response = client.get(f"/rides/{ride_id}", headers={"Authorization": f"Bearer {access_token}"})
    assert response.status_code == 200

    body = response.json()
    assert body["distanceM"] == 42000.0
    assert body["elevationM"] == 900.0
    assert body["durationS"] == 7200
    assert body["calories"] == 1100.0
    assert body["attestationStatus"] == "attested"
    assert body["rideHashHex"] == "ab" * 32
    assert body["attestationCommitmentHex"] == "cd" * 32
    assert body["parserVersion"] == 1
    assert body["rideAttestationPda"] == "2" * 44
    assert body["rideAttestationTxSignature"] == "3" * 88
    assert body["rideAttestedAt"] == "2024-10-01T14:01:00+00:00"
    assert body["routePreview"]["contractVersion"] == "route_preview.v1"
    assert body["routePreview"]["pointCount"] == 3
    assert body["routePreview"]["placeLabel"] == "Boulder, CO"
    assert "durationSec" not in body
    assert "elevationGainM" not in body
    assert "caloriesBurned" not in body


def test_get_ride_status_reports_attestation_progression() -> None:
    repo = MockRepository()
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "started_at": "2024-10-01T12:00:00Z",
        "completed_at": "2024-10-01T14:00:00Z",
        "processing_status": "completed",
        "tss": 215.0,
        "kcals": 1100.0,
        "distance_m": 42000.0,
        "elevation_gain_m": 900.0,
        "duration_sec": 7200,
        "avg_power_w": 250.0,
        "normalized_power_w": 265.0,
        "ride_hash_hex": "ab" * 32,
        "attestation_commitment_hex": "cd" * 32,
        "ride_parser_version": 1,
    }

    client = _build_test_client(repo)
    _device_id, access_token, _ = authenticate(client, repo)

    provisional = client.get(
        f"/rides/{ride_id}/status",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert provisional.status_code == 200
    provisional_body = provisional.json()
    assert provisional_body["status"] == "completed"
    assert provisional_body["attestation_status"] == "provisional"
    assert provisional_body["ride_hash_hex"] == "ab" * 32
    assert provisional_body["parser_version"] == 1

    repo.rides[ride_id]["ride_attestation_pda"] = "4" * 44
    repo.rides[ride_id]["ride_attestation_tx_signature"] = "5" * 88
    repo.rides[ride_id]["ride_attested_at"] = "2024-10-01T14:02:00Z"

    attested = client.get(
        f"/rides/{ride_id}/status",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert attested.status_code == 200
    attested_body = attested.json()
    assert attested_body["attestation_status"] == "attested"
    assert attested_body["ride_attestation_pda"] == "4" * 44
    assert attested_body["ride_attestation_tx_signature"] == "5" * 88
    assert attested_body["ride_attested_at"] == "2024-10-01T14:02:00Z"


def test_get_ride_status_reports_under_review_state() -> None:
    repo = MockRepository()
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "started_at": "2024-10-01T12:00:00Z",
        "completed_at": "2024-10-01T14:00:00Z",
        "processing_status": "under_review",
        "ride_hash_hex": "ab" * 32,
        "attestation_commitment_hex": "cd" * 32,
        "ride_parser_version": 1,
        "preliminary_ride_hash_hex": "ef" * 32,
        "preliminary_parser_version": 1,
        "canonical_match": False,
        "review_reason": "preliminary_hash_mismatch",
    }

    client = _build_test_client(repo)
    _device_id, access_token, _ = authenticate(client, repo)

    response = client.get(
        f"/rides/{ride_id}/status",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "under_review"
    assert body["attestation_status"] == "under_review"
    assert body["preliminary_ride_hash_hex"] == "ef" * 32
    assert body["preliminary_parser_version"] == 1
    assert body["canonical_match"] is False
    assert body["review_reason"] == "preliminary_hash_mismatch"


def test_upload_init_persists_preliminary_attestation_fields() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _ = authenticate(client, repo)

    with patch("app.routes.rides.create_file_storage_service") as storage_factory:
        storage_factory.return_value.create_signed_upload_url = AsyncMock(
            return_value={"signed_url": "https://example.test/upload"}
        )
        response = client.post(
            "/rides/upload/init",
            json={
                "file_type": "fit",
                "file_hash": "ab" * 32,
                "file_size": 1234,
                "preliminary_ride_hash": "cd" * 32,
                "parser_version": 1,
            },
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    assert repo.last_ride["preliminary_ride_hash_hex"] == "cd" * 32
    assert repo.last_ride["preliminary_parser_version"] == 1


def test_ride_telemetry_endpoints_support_legacy_non_uuid_ids(monkeypatch) -> None:
    from types import SimpleNamespace
    monkeypatch.setattr("app.routes.rides.ClimbEffortRepository", lambda _: SimpleNamespace(
        get_efforts=AsyncMock(return_value=[]), recorded_power_rides=AsyncMock(return_value=set()),
    ))
    repo = MockRepository()
    repo.client = None
    client = _build_test_client(repo)
    _device_id, access_token, _ = authenticate(client, repo)

    ride_id = "strava-legacy-12345"
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "started_at": "2020-07-18T08:00:00Z",
        "processing_status": "completed",
        "kcals": 450,
    }
    repo.last_gps_points = {
        "ride_id": ride_id,
        "points": [
            {"sequence_num": 0, "timestamp": 0, "latitude": 40.01, "longitude": -105.22, "elevation_m": 1600.0, "distance_m": 0.0},
            {"sequence_num": 1, "timestamp": 5, "latitude": 40.02, "longitude": -105.23, "elevation_m": 1604.0, "distance_m": 90.0},
        ],
    }  # type: ignore[attr-defined]
    repo.last_stream = {
        "id": str(uuid4()),
        "ride_id": ride_id,
        "stream_type": "power",
        "timestamps": [0, 5],
        "values": [180, 190],
        "sample_count": 2,
        "min_value": 180,
        "max_value": 190,
        "avg_value": 185.0,
    }  # type: ignore[attr-defined]
    repo.climb_patterns = [
        {
            "start_offset_s": 0,
            "end_offset_s": 600,
            "vert_m": 120.0,
            "time_s": 900,
        }
    ]  # type: ignore[attr-defined]

    headers = {"Authorization": f"Bearer {access_token}"}

    gps_res = client.get(f"/rides/{ride_id}/gps", headers=headers)
    assert gps_res.status_code == 200
    assert len(gps_res.json().get("gps_points", [])) == 2

    stream_res = client.get(f"/rides/{ride_id}/streams?type=power", headers=headers)
    assert stream_res.status_code == 200
    assert stream_res.json().get("sample_count") == 2

    patterns_res = client.get(f"/rides/{ride_id}/patterns", headers=headers)
    assert patterns_res.status_code == 200
    assert len(patterns_res.json().get("patterns", {}).get("climb_patterns", [])) == 1



# DEPRECATED: Segment tests removed - segments replaced by tile-based patterns
# See /rides/{ride_id}/patterns for pattern-based competition


def test_health_endpoint_ok() -> None:
    """Health/db returns 200 when asyncpg pool is available."""
    repo = MockRepository()
    repo.health_ok = True
    client = _build_test_client(repo)

    # Mock asyncpg pool with a working connection
    mock_conn = MagicMock()
    mock_conn.fetchval = AsyncMock(return_value=1)

    @asynccontextmanager
    async def _acquire():
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.acquire = _acquire

    async def _mock_get_pool():
        return mock_pool

    with patch("app.db_pool.get_pool", new=_mock_get_pool):
        response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == HealthResponse(status="ok").model_dump()


def test_health_endpoint_failure() -> None:
    """Health/db returns 503 when both asyncpg and REST fail."""
    repo = MockRepository()
    repo.health_ok = False
    client = _build_test_client(repo)

    # Mock asyncpg pool to raise an error
    async def _failing_pool():
        raise RuntimeError("No DATABASE_URL")

    # Mock Supabase REST to also fail
    def _failing_supabase():
        raise RuntimeError("REST also down")

    with patch("app.db_pool.get_pool", new=_failing_pool), \
         patch("app.repositories.get_supabase_client", new=_failing_supabase):
        response = client.get("/health/db")
    assert response.status_code == 503
    assert "Database connectivity check failed" in response.json()["detail"]


def test_waitlist_endpoint_is_public() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)

    response = client.post("/waitlist", json={"email": " Test@Example.com ", "source": "portal_access"})

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["contractVersion"] == "waitlist.v1"
    assert response.json()["state"] == "accepted"
    assert response.json()["email"] == "test@example.com"
    assert response.json()["source"] == "portal_access"
    assert response.json()["submittedAt"] == repo.waitlist[0]["created_at"]
    assert repo.waitlist[0]["email"] == "test@example.com"


def test_waitlist_endpoint_reports_storage_failure() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)

    async def _failing_waitlist(**_kwargs: Any) -> Dict[str, Any]:
        raise RuntimeError("missing waitlist table")

    repo.add_to_waitlist = _failing_waitlist  # type: ignore[method-assign]

    response = client.post("/waitlist", json={"email": "test@example.com", "source": "landing"})

    assert response.status_code == 503
    assert repo.waitlist == []


def test_mint_balance_endpoint_still_available() -> None:
    repo = MockRepository()
    repo.token_balances = {"dung": Decimal("999999"), "kcal": 7.0}
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    with patch(
        "app.routes.mint.solana_direct.get_wallet_dung_balance_source",
        new=AsyncMock(
            return_value=SimpleNamespace(
                amount_base_units=1,
                source="spl_wallet_ata",
                status="live",
                token_account="WalletDungAtaCompatibility",
                slot=456,
            )
        ),
    ):
        response = client.get("/mint", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json() == {
        "dung": "0.000000001",
        "dung_base_units": "1",
        "dung_source": "spl_wallet_ata",
        "dung_status": "live",
        "dung_token_account": "WalletDungAtaCompatibility",
        "dung_slot": 456,
        "kcal": 7.0,
    }


def test_proof_verify_uses_current_sealed_threshold_denominator() -> None:
    repo = MockRepository()
    signing_key = _install_signing_wallet(repo)
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "tss": 88.4,
        "kcals": 640.0,
        "duration_sec": 3600,
        "normalized_power_raw_w": 200.0,
        "normalized_power_duration_s": 3600,
        "threshold_training_w": 200,
        "threshold_training_kind": "sealed",
    }
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)
    signature = _sign_proof_payload(
        signing_key,
        repo.wallet,
        repo.rides[ride_id],
        effort_score=66.6,
    )

    response = client.post(
        "/proofs/verify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"ride_id": ride_id, "signature": signature},
    )

    assert response.status_code == 200
    assert response.json()["effort_score"] == 66.6
    created = repo.proofs[response.json()["proof_id"]]
    assert created["ride_id"] == ride_id
    assert created["signature"] == signature
    assert created["proof_hash"] is not None


def test_proof_verify_rejects_pre_cutover_stored_tss() -> None:
    repo = MockRepository()
    signing_key = _install_signing_wallet(repo)
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "tss": 88.4,
        "kcals": 640.0,
        "duration_sec": 3600,
    }
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)
    signature = _sign_proof_payload(
        signing_key,
        repo.wallet,
        repo.rides[ride_id],
        effort_score=88.4,
    )

    response = client.post(
        "/proofs/verify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"ride_id": ride_id, "signature": signature},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "threshold_training_unavailable"}
    assert repo.proofs == {}


def test_proof_verify_rejects_stored_tss_without_recomputable_power() -> None:
    repo = MockRepository()
    signing_key = _install_signing_wallet(repo)
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "tss": 73.2,
        "threshold_training_w": 200,
        "threshold_training_kind": "sealed",
    }
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)
    signature = _sign_proof_payload(
        signing_key,
        repo.wallet,
        repo.rides[ride_id],
        effort_score=73.2,
    )

    response = client.post(
        "/proofs/verify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"ride_id": ride_id, "signature": signature},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "threshold_training_unavailable"}
    assert repo.proofs == {}


def test_proof_verify_does_not_freeze_a_pending_monday_denominator() -> None:
    repo = MockRepository()
    _install_signing_wallet(repo)
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "tss": 66.6,
        "threshold_training_kind": "pending",
    }
    repo.threshold_projection = {
        "state": "established",
        "current_w": 245,
        "established_at": "2026-08-17T12:00:00+00:00",
        "last_raised_at": None,
        "pending_monday": {
            "promotion_id": str(uuid4()),
            "watts": 251,
            "effective_at": "2099-08-31T12:00:00+00:00",
        },
        "training_denominator": {
            "watts": 251,
            "kind": "pending",
            "provisional": True,
        },
    }
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    response = client.post(
        "/proofs/verify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"ride_id": ride_id, "signature": "proof-signature"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "threshold_training_unavailable"}
    assert repo.proofs == {}


def test_proof_verify_fails_closed_when_threshold_authority_is_invalid() -> None:
    repo = MockRepository()
    _install_signing_wallet(repo)
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "tss": 66.6,
        "normalized_power_raw_w": 200.0,
        "normalized_power_duration_s": 3600,
        "threshold_training_kind": "sealed",
    }
    repo.threshold_projection = {}
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    response = client.post(
        "/proofs/verify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"ride_id": ride_id, "signature": "proof-signature"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {"code": "threshold_authority_unavailable"}
    assert repo.proofs == {}


def test_proof_verify_rejects_invalid_signature() -> None:
    repo = MockRepository()
    _install_signing_wallet(repo)
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "tss": 50.0,
        "normalized_power_raw_w": 185.0,
        "normalized_power_duration_s": 3600,
        "threshold_training_kind": "sealed",
    }
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    response = client.post(
        "/proofs/verify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"ride_id": ride_id, "signature": "proof-signature"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid proof signature"
    assert repo.proofs == {}


def test_proof_verify_reuses_existing_proof_for_same_ride() -> None:
    repo = MockRepository()
    signing_key = _install_signing_wallet(repo)
    ride_id = str(uuid4())
    repo.rides[ride_id] = {
        "id": ride_id,
        "user_id": repo.user_id,
        "tss": 42.0,
    }
    proof_id = str(uuid4())
    repo.proofs[proof_id] = {
        "id": proof_id,
        "ride_id": ride_id,
        "effort_score": 42.0,
        "signature": "existing",
        "user_id": repo.user_id,
    }
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    response = client.post(
        "/proofs/verify",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "ride_id": ride_id,
            "signature": _sign_proof_payload(
                signing_key,
                repo.wallet,
                repo.rides[ride_id],
                effort_score=42.0,
            ),
        },
    )

    assert response.status_code == 200
    assert response.json() == {"proof_id": proof_id, "effort_score": 42.0}
    assert len(repo.proofs) == 1


def test_staking_claims_endpoint_still_available() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)
    repo.claims[(repo.user_id, "123")] = {
        "user_id": repo.user_id,
        "segment_id": "123",
        "amount": 100.0,
        "lp_tokens": 25.0,
    }

    response = client.get("/staking/claims", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["claims"][0]["claim_id"] == f"{repo.user_id}:123"
    assert body["claims"][0]["segment_id"] == 123
    assert body["claims"][0]["lp_tokens"] == 25


def test_admin_strava_subscription_requires_admin_role() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    with patch("app.routes.admin.ComplianceRepository") as compliance_repo:
        compliance_repo.return_value.get_admin_role = AsyncMock(return_value=None)
        response = client.get(
            "/admin/strava/subscription",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 403


def test_admin_check_returns_non_admin_payload() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    with patch("app.routes.admin.ComplianceRepository") as compliance_repo:
        compliance_repo.return_value.get_admin_role = AsyncMock(return_value=None)
        response = client.get(
            "/admin/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"isAdmin": False, "role": None}


def test_admin_check_returns_admin_payload() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    with patch("app.routes.admin.ComplianceRepository") as compliance_repo:
        compliance_repo.return_value.get_admin_role = AsyncMock(return_value="super_admin")
        response = client.get(
            "/admin/check",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"isAdmin": True, "role": "super_admin"}


def test_admin_strava_health_requires_admin_role() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    with patch("app.routes.admin.ComplianceRepository") as compliance_repo:
        compliance_repo.return_value.get_admin_role = AsyncMock(return_value=None)
        response = client.get(
            "/admin/strava/health",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 403


def test_get_segment_returns_canonical_segment() -> None:
    repo = SegmentApiRepository(
        climb_vault_rows=[
            {
                "id": "4",
                "name": "Smoke Climb",
                "distance_m": 4321.0,
                "total_vert_m": 321.0,
                "avg_gradient_pct": 7.4,
                "bounds_min_lat": 39.1,
                "bounds_min_lon": -105.3,
                "bounds_max_lat": 39.2,
                "bounds_max_lon": -105.2,
                "uci_category": "2",
                "region": "Boulder",
                "active": True,
            }
        ],
    )
    client = _build_test_client(repo)

    response = client.get("/segments/4")

    assert response.status_code == 200
    body = response.json()
    expected_legacy_fields = {
        "id": "4",
        "name": "Smoke Climb",
        "length_m": 4321.0,
        "elev_gain_m": 321.0,
        "start_lat": 39.1,
        "start_lon": -105.3,
        "end_lat": 39.2,
        "end_lon": -105.2,
        "avg_gradient_pct": 7.4,
        "category": "3",
        "region": "Boulder",
        "vault_id": None,
        "vault_signature": None,
        "has_vault": False,
        "total_staked": "0",
        "total_staked_base_units": "0",
        "total_cal_staked": "0",
        "total_cal_staked_base_units": "0",
        "total_completions": 0,
    }
    for key, value in expected_legacy_fields.items():
        assert body[key] == value
    assert body["contract_version"] == "client.v1"
    assert body["truth_source"] == "projected"
    assert body["vault_economy"] == {
        "contract_version": "client.v1",
        "truth_source": "projected",
        "has_vault": False,
        "vault_id": None,
        "vault_signature": None,
        "total_staked": "0",
        "total_staked_base_units": "0",
        "total_cal_staked": "0",
        "total_cal_staked_base_units": "0",
        "total_completions": 0,
        "current_carry": None,
    }


def test_get_segment_includes_vault_route_preview_when_polyline_available() -> None:
    climb_id = "d1b054f6-46af-49d8-b3d2-90ac407fe493"
    signature_hex = "ab" * 64
    repo = SegmentApiRepository(
        climb_vault_rows=[
            {
                "id": climb_id,
                "name": "Flagstaff Climb",
                "distance_m": 2100.0,
                "total_vert_m": 250.0,
                "avg_gradient_pct": 8.2,
                "bounds_min_lat": 40.0001,
                "bounds_min_lon": -105.301,
                "bounds_max_lat": 40.0221,
                "bounds_max_lon": -105.287,
                "signature_hex": signature_hex,
                "uci_category": "2",
                "region": "Boulder",
                "active": True,
            }
        ],
        indexed_vault_rows=[
            {
                "id": 44,
                "name": "Flagstaff Climb",
                "signature_hex": signature_hex,
                "total_staked": 1200,
                "total_completions": 9,
                "polyline_json": "[[40.0001, -105.301], [40.011, -105.295], [40.0221, -105.287]]",
            }
        ],
    )
    client = _build_test_client(repo)

    response = client.get(f"/segments/{climb_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["has_vault"] is True
    assert body["route_preview"]["contractVersion"] == "route_preview.v1"
    assert body["route_preview"]["source"] == "climb_polyline"
    assert body["route_preview"]["pointCount"] == 3
    assert body["route_preview"]["placeLabel"] == "Boulder"


def test_get_segment_returns_404_for_missing_segment() -> None:
    repo = SegmentApiRepository()
    client = _build_test_client(repo)

    response = client.get("/segments/404")

    assert response.status_code == 404
    assert response.json() == {"detail": "Climb not found"}


def test_get_segment_supports_legacy_numeric_vault_ids() -> None:
    repo = SegmentApiRepository(
        indexed_vault_rows=[
            {
                "id": 4,
                "name": "Smoke Vault",
                "distance_m": 2600,
                "vert_m": 185.0,
                "avg_gradient_pct": 7.1,
            }
        ],
    )
    client = _build_test_client(repo)

    response = client.get("/segments/4")

    assert response.status_code == 200
    body = response.json()
    expected_legacy_fields = {
        "id": "4",
        "name": "Smoke Vault",
        "length_m": 2600.0,
        "elev_gain_m": 185.0,
        "start_lat": None,
        "start_lon": None,
        "end_lat": None,
        "end_lon": None,
        "avg_gradient_pct": 7.1,
        "category": "3",
        "region": None,
        "vault_id": 4,
        "vault_signature": None,
        "has_vault": True,
        "total_staked": "0",
        "total_staked_base_units": "0",
        "total_cal_staked": "0",
        "total_cal_staked_base_units": "0",
        "total_completions": 0,
    }
    for key, value in expected_legacy_fields.items():
        assert body[key] == value
    assert body["contract_version"] == "client.v1"
    assert body["truth_source"] == "projected"
    assert body["vault_economy"] == {
        "contract_version": "client.v1",
        "truth_source": "projected",
        "has_vault": True,
        "vault_id": 4,
        "vault_signature": None,
        "total_staked": "0",
        "total_staked_base_units": "0",
        "total_cal_staked": "0",
        "total_cal_staked_base_units": "0",
        "total_completions": 0,
        "current_carry": None,
    }


def test_get_segment_leaderboard_omits_unlinked_board_entry_after_signature_match() -> None:
    signature_hex = "ab" * 64
    repo = SegmentApiRepository(
        climb_vault_rows=[
            {
                "id": "d1b054f6-46af-49d8-b3d2-90ac407fe493",
                "name": "Real Test Climb",
                "signature_hex": signature_hex,
                "active": True,
            }
        ],
        indexed_vault_rows=[
            {
                "id": 4,
                "name": "Real Test Climb",
                "signature_hex": signature_hex,
                "kom_holder": "wallet-kom",
                "kom_time_s": 2275,
            }
        ],
        indexed_leaderboard_rows=[
            {
                "vault_id": 4,
                "entries": [
                    {
                        "user": "wallet-kom",
                        "time_s": 2275,
                        "recorded_at": None,
                    }
                ],
            }
        ],
    )
    client = _build_test_client(repo)

    response = client.get("/segments/d1b054f6-46af-49d8-b3d2-90ac407fe493/leaderboard")

    assert response.status_code == 200
    body = response.json()
    assert body["contract_version"] == "client.v1"
    assert body["truth_source"] == "projected"
    assert body["climb_id"] == "d1b054f6-46af-49d8-b3d2-90ac407fe493"
    assert body["climb_name"] == "Real Test Climb"
    assert body["segment_id"] == "d1b054f6-46af-49d8-b3d2-90ac407fe493"
    assert body["segment_name"] == "Real Test Climb"
    assert body["vault_id"] == 4
    assert body["entries"] == []
    assert body["leaderboard"] == []
    assert body["kom_holder"] is None
    assert body["kom_time_s"] is None


def test_canonical_climb_leaderboard_rejects_numeric_vault_id_before_query() -> None:
    repo = SegmentApiRepository()
    repo.client = _FailOnQuerySupabaseClient()
    client = _build_test_client(repo)

    response = client.get("/climbs/7/leaderboard")

    assert response.status_code == 404
    assert response.json() == {"detail": "Climb not found"}


def test_segment_leaderboard_preserves_numeric_vault_id_compatibility() -> None:
    signature_hex = "cd" * 64
    repo = SegmentApiRepository(
        indexed_vault_rows=[
            {
                "id": 7,
                "name": "Legacy Compatible Climb",
                "signature_hex": signature_hex,
                "kom_holder": None,
                "kom_time_s": 0,
            }
        ],
        indexed_leaderboard_rows=[],
    )
    client = _build_test_client(repo)

    response = client.get("/segments/7/leaderboard")

    assert response.status_code == 200
    assert response.json()["climb_id"] == "7"
    assert response.json()["vault_id"] == 7


def test_admin_strava_health_returns_snapshot() -> None:
    repo = MockRepository()
    client = _build_test_client(repo)
    _device_id, access_token, _refresh_token = authenticate(client, repo)

    snapshot = {
        "health_status": "WARNING",
        "enabled": True,
        "sync_enabled": False,
        "integration_mode": "file_import_only",
        "state_verified": True,
        "redirect_uri": "https://app.boulderroller.xyz/strava/callback",
        "webhook_callback_url": "https://api.boulderroller.xyz/strava/webhook",
        "subscription": {
            "active": True,
            "subscription_id": 333340,
            "callback_url": "https://api.boulderroller.xyz/strava/webhook",
            "created_at": "2026-03-04T17:07:41Z",
        },
        "connections": {
            "active_count": 4,
            "recent_sync_24h": 3,
            "stale_sync_7d": 1,
            "last_webhook_at": "2026-03-04T17:08:00Z",
        },
        "backfill": {
            "none": 1,
            "in_progress": 2,
            "complete": 1,
        },
        "rate_limits": {
            "storage": "redis",
            "redis_available": True,
            "usage_15min": 22,
            "limit_15min": 100,
            "remaining_15min": 78,
            "usage_daily": 118,
            "limit_daily": 1000,
            "remaining_daily": 882,
            "reset_in_seconds_15min": 420,
        },
        "alerts": ["15-minute Strava quota is above 80%."],
        "generated_at": "2026-03-04T17:08:10Z",
    }

    with patch("app.routes.admin.ComplianceRepository") as compliance_repo:
        compliance_repo.return_value.get_admin_role = AsyncMock(return_value="super_admin")
        with patch("app.routes.strava.get_strava_health_snapshot", new=AsyncMock(return_value=snapshot)):
            response = client.get(
                "/admin/strava/health",
                headers={"Authorization": f"Bearer {access_token}"},
            )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["sync_enabled"] is False
    assert body["integration_mode"] == "file_import_only"
    assert body["state_verified"] is True
    assert body["subscription"]["subscription_id"] == 333340
    assert body["connections"]["active_count"] == 4
    assert body["rate_limits"]["usage_15min"] == 22


def test_checked_cookie_is_signed_digest_and_consumed_without_rehashing():
    from app.invite_security import read_invite_cookie
    repo = MockRepository()
    client = _build_test_client(repo)
    code_id = str(uuid4())
    supabase = MockInviteSupabase({
        'check_invite_code': [{'valid': True, 'message': 'Invite code valid', 'code_id': code_id}],
        'consume_invite_code': [{'valid': True, 'message': 'Invite code consumed', 'code_id': code_id}],
    })
    with patch('app.routes.auth.get_supabase_client', return_value=supabase), patch('app.routes.auth.auth_settings.require_invite_code', True):
        result = client.post('/auth/invite/validate', json={'code':'single-person-code'})
        cookie = result.cookies.get('invite_code')
        assert cookie and 'single-person-code' not in cookie
        assert read_invite_cookie(cookie) == hash_invite_code('single-person-code')
        wallet, device = 'cookie-signup-wallet', str(uuid4())
        nonce = client.post('/auth/nonce',json={'wallet':wallet,'device_id':device}).json()['nonce']
        response = client.post('/auth/verify',json={'wallet':wallet,'device_id':device,'nonce':nonce,'signature':'stub-signature'})
    assert response.status_code == 200
    assert supabase.calls[-1][1]['p_code'] == hash_invite_code('single-person-code')
    assert supabase.calls[-1][1]['p_email'] is None


def test_privy_invite_consumption_uses_verified_email_and_checked_digest():
    from app.invite_security import invite_cookie
    repo = MockRepository()
    client = _build_test_client(repo)
    wallet = 'new-privy-invited-wallet'
    supabase = MockInviteSupabase({'consume_invite_code':[{'valid':True,'message':'Invite code consumed','code_id':str(uuid4())}]})
    privy_user={'linked_accounts':[{'type':'wallet','chain_type':'solana','address':wallet},{'type':'email','address':'Verified@Example.com'}]}
    client.cookies.set('invite_code',invite_cookie('person-code-test'))
    with patch('app.routes.auth.get_supabase_client',return_value=supabase), patch('app.routes.auth.auth_settings.require_invite_code',True), patch('app.routes.auth.verify_privy_token',return_value={'sub':'did:privy:invited'}), patch('app.routes.auth.fetch_privy_user',return_value=privy_user):
        result=client.post('/auth/privy/verify',json={'wallet':wallet,'privyToken':'test-token','deviceId':str(uuid4())})
    assert result.status_code == 200
    assert supabase.calls[-1][1]['p_email'] == 'Verified@Example.com'
    assert supabase.calls[-1][1]['p_code'] == hash_invite_code('person-code-test')


def test_invalid_single_use_invite_creates_no_account_or_session():
    for reason in ['Invalid invite code','Invite code has expired','Invite code has reached maximum uses']:
        repo = MockRepository()
        client = _build_test_client(repo)
        wallet,device='rejected-invite-wallet',str(uuid4())
        nonce=client.post('/auth/nonce',json={'wallet':wallet,'device_id':device}).json()['nonce']
        supabase=MockInviteSupabase({'consume_invite_code':[{'valid':False,'message':reason,'code_id':None}]})
        with patch('app.routes.auth.get_supabase_client',return_value=supabase),patch('app.routes.auth.auth_settings.require_invite_code',True):
            response=client.post('/auth/verify',json={'wallet':wallet,'device_id':device,'nonce':nonce,'signature':'stub-signature','inviteCode':'single-use-code'})
        assert response.status_code==403
        assert response.json()['detail']['error']['code']=='invite_invalid'
        assert not repo.refresh_tokens
        assert not any(row['wallet']==wallet for row in repo.users_by_id.values())


def test_invite_minimum_length_is_eight():
    client=_build_test_client(MockRepository())
    assert client.post('/auth/invite/validate',json={'code':'1234567'}).status_code==422


def test_invite_validation_errors_do_not_echo_plaintext():
    client=_build_test_client(MockRepository())
    response=client.post('/auth/invite/validate',json={'code':['secret-invite-value']})
    assert response.status_code==422
    assert 'secret-invite-value' not in response.text


def test_existing_dev_invite_fallback_accepts_signed_cookie_digest():
    import asyncio
    from app.routes.auth import _consume_invite_code_for_signup
    with patch.dict(os.environ, {'INVITE_CODES':'local-dev-code'}), patch('app.routes.auth.get_supabase_client',side_effect=RuntimeError('offline')):
        result=asyncio.run(_consume_invite_code_for_signup(hash_invite_code('local-dev-code'),'wallet',None,None,already_hashed=True))
    assert result[0] is True
    with patch.dict(os.environ, {'INVITE_CODES':'local-dev-code'}), patch('app.routes.auth.get_environment',return_value='production'), patch('app.routes.auth.get_supabase_client',side_effect=RuntimeError('offline')):
        result=asyncio.run(_consume_invite_code_for_signup(hash_invite_code('local-dev-code'),'wallet',None,None,already_hashed=True))
    assert result[0] is False
