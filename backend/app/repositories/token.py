"""Token repository - CAL/DUNG balances, minting, vesting, and transactions."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from ..utils.postgrest_paging import window
from .base import BaseRepository


class TokenRepository(BaseRepository):
    """Repository for token operations (CAL, DUNG, minting, vesting)."""

    def _first_row(self, response) -> Optional[Dict[str, Any]]:
        """Extract first row from response."""
        data = getattr(response, "data", None) or []
        return dict(data[0]) if data else None

    async def get_token_balances(self, user_id: str) -> Dict[str, Any]:
        """Get DUNG and kcal balances for user."""
        total_kcal = 0.0
        rides_response = await self._run(
            lambda: self._client.table("rides")
            .select("kcals")
            .eq("user_id", user_id)
            .execute()
        )
        rides_data = getattr(rides_response, "data", None) or []
        for row in rides_data:
            try:
                total_kcal += float(row.get("kcals") or 0)
            except (TypeError, ValueError):
                continue

        proofs_response = await self._run(
            lambda: self._client.table("proofs")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        proofs_data = getattr(proofs_response, "data", None) or []
        proof_ids = [row.get("id") for row in proofs_data if row.get("id")]

        total_dung = Decimal(0)
        if proof_ids:
            minted_response = await self._run(
                lambda: self._client.table("mint_events")
                .select("amount, proof_id")
                .in_("proof_id", proof_ids)
                .execute()
            )
            minted_data = getattr(minted_response, "data", None) or []
            for row in minted_data:
                try:
                    amount = Decimal(str(row.get("amount") or 0))
                    if not amount.is_finite():
                        continue
                    total_dung += amount
                except (InvalidOperation, TypeError, ValueError):
                    continue

        return {"dung": total_dung, "kcal": float(total_kcal)}

    async def update_cal_balance(self, user_id: str, amount: float) -> Dict[str, Any]:
        """Add amount to user's CAL balance."""
        state = await self._get_user_state(user_id)
        current_balance = float(state.get("cal_balance") or 0) if state else 0.0
        payload = {
            "user_id": user_id,
            "cal_balance": current_balance + float(amount),
            "cal_earned_today": float(state.get("cal_earned_today") or 0) if state else 0.0,
            "last_cal_mint": state.get("last_cal_mint") if state else None,
            "total_rides": state.get("total_rides") if state else 0,
            "total_tss": state.get("total_tss") if state else 0,
            "bio_score": state.get("bio_score") if state else 1000,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._run(
            lambda: self._client.table("user_state")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return payload

    async def deduct_cal(self, user_id: str, amount: float) -> None:
        """DEPRECATED: Wrong CAL model. CAL is not deducted from users.

        The correct model: CAL is earned from TSS, tributed to vaults crossed.
        This method is kept for backwards compatibility but should not be called.
        """
        import warnings
        warnings.warn(
            "deduct_cal is deprecated - CAL is earned from TSS, not deducted from users",
            DeprecationWarning,
            stacklevel=2,
        )

    async def refund_cal(self, user_id: str, amount: float) -> None:
        """Refund CAL to user balance."""
        await self.update_cal_balance(user_id, float(amount))

    async def record_cal_mint(
        self, user_id: str, amount: float, minted_at: datetime
    ) -> Dict[str, Any]:
        """Record CAL minting event and update user state."""
        state = await self._get_user_state(user_id)
        cal_balance = float(state.get("cal_balance") or 0) if state else 0.0
        last_mint_raw = state.get("last_cal_mint") if state else None
        cal_earned_today = float(state.get("cal_earned_today") or 0) if state else 0.0

        last_mint_dt: Optional[datetime] = None
        if last_mint_raw:
            try:
                last_mint_dt = datetime.fromisoformat(str(last_mint_raw).replace("Z", "+00:00"))
            except ValueError:
                last_mint_dt = None

        if last_mint_dt and last_mint_dt.date() == minted_at.date():
            cal_earned_today += float(amount)
        else:
            cal_earned_today = float(amount)

        payload = {
            "user_id": user_id,
            "cal_balance": cal_balance + float(amount),
            "cal_earned_today": cal_earned_today,
            "last_cal_mint": minted_at.isoformat(),
            "total_rides": state.get("total_rides") if state else 0,
            "total_tss": state.get("total_tss") if state else 0,
            "bio_score": state.get("bio_score") if state else 1000,
            "updated_at": minted_at.isoformat(),
        }

        await self._run(
            lambda: self._client.table("user_state")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return payload

    async def process_cal_airdrop(self, user_id: str, amount: float) -> Dict[str, Any]:
        """Add CAL to user and schedule next airdrop in 24 hours."""
        now = datetime.now(timezone.utc)
        next_airdrop = now + timedelta(hours=24)

        state = await self._get_user_state(user_id)
        cal_balance = float(state.get("cal_balance") or 0) if state else 0.0

        payload = {
            "user_id": user_id,
            "cal_balance": cal_balance + float(amount),
            "cal_earned_today": float(amount),
            "last_cal_mint": now.isoformat(),
            "next_cal_airdrop": next_airdrop.isoformat(),
            "updated_at": now.isoformat(),
        }

        # Preserve other fields
        if state:
            payload["total_rides"] = state.get("total_rides", 0)
            payload["total_tss"] = state.get("total_tss", 0)
            payload["bio_score"] = state.get("bio_score", 1000)

        await self._run(
            lambda: self._client.table("user_state")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return payload

    async def get_users_due_for_airdrop(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get users whose next_cal_airdrop is due."""
        now = datetime.now(timezone.utc)
        response = await self._run(
            lambda: self._client.table("user_state")
            .select("user_id, cal_balance, next_cal_airdrop")
            .lte("next_cal_airdrop", now.isoformat())
            .limit(limit)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    # Minting operations
    async def proof_has_mint(self, proof_id: str) -> bool:
        """Check if a proof already has a mint event."""
        response = await self._run(
            lambda: self._client.table("mint_events")
            .select("id")
            .eq("proof_id", proof_id)
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        return bool(row)

    async def create_mint_event(
        self,
        proof_id: str,
        amount: float,
        tx_hash: str,
        status: str,
        created_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Create a mint event record."""
        event_id = str(uuid.uuid4())
        created = (created_at or datetime.now(timezone.utc)).isoformat()
        payload = {
            "id": event_id,
            "proof_id": proof_id,
            "amount": float(amount),
            "tx_hash": tx_hash,
            "status": status,
            "created_at": created,
        }
        await self._run(
            lambda: self._client.table("mint_events").insert(payload).execute()
        )
        return payload

    async def record_mint_event(
        self,
        user_id: str,
        ride_id: str,
        proof_id: str,
        dung_amount: float,
        tx_signature: Optional[str],
        status: str,
    ) -> Dict[str, Any]:
        """Record a full mint event with user/ride context."""
        payload = {
            "proof_id": proof_id,
            "amount": float(dung_amount),
            "tx_hash": tx_signature or "",
            "status": status,
            "user_id": user_id,
            "ride_id": ride_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        await self._run(lambda: self._client.table("mint_events").insert(payload).execute())
        return payload

    # Vesting operations
    async def create_vesting_schedule(
        self,
        user_id: str,
        token_type: str,
        total_amount: int,
        end_date: datetime,
        source_type: Optional[str],
        source_id: Optional[str],
    ) -> Dict[str, Any]:
        """Create a vesting schedule for a user."""
        payload = {
            "user_id": user_id,
            "token_type": token_type,
            "total_amount": total_amount,
            "end_date": end_date.isoformat(),
            "source_type": source_type,
            "source_id": source_id,
        }
        response = await self._run(
            lambda: self._client.table("vesting_schedules").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_user_vesting_schedules(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all vesting schedules for a user."""
        response = await self._run(
            lambda: self._client.table("vesting_schedules")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    # Claims operations
    async def get_user_claims(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all claims for a user with segment info."""
        response = await self._run(
            lambda: self._client.table("claims")
            .select(
                "segment_id, amount, lp_tokens, staked_at, last_harvest_epoch, segments(name,length_m,elev_gain_m)"
            )
            .eq("user_id", user_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_user_claim(
        self, user_id: str, segment_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get a specific claim for a user on a segment."""
        response = await self._run(
            lambda: self._client.table("claims")
            .select("*")
            .eq("user_id", user_id)
            .eq("segment_id", segment_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def upsert_claim(
        self, user_id: str, segment_id: str, amount: float, lp_tokens: float
    ) -> None:
        """Create or update a claim."""
        payload = {
            "user_id": user_id,
            "segment_id": segment_id,
            "amount": float(amount),
            "lp_tokens": float(lp_tokens),
            "staked_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._run(
            lambda: self._client.table("claims")
            .upsert(payload, on_conflict="user_id,segment_id")
            .execute()
        )

    async def delete_claim(self, user_id: str, segment_id: str) -> None:
        """Delete a claim."""
        await self._run(
            lambda: self._client.table("claims")
            .delete()
            .eq("user_id", user_id)
            .eq("segment_id", segment_id)
            .execute()
        )

    async def update_claim_harvest(
        self, user_id: str, segment_id: str, last_harvest_epoch: int
    ) -> None:
        """Update the last harvest epoch for a claim."""
        payload = {"last_harvest_epoch": last_harvest_epoch}
        await self._run(
            lambda: self._client.table("claims")
            .update(payload)
            .eq("user_id", user_id)
            .eq("segment_id", segment_id)
            .execute()
        )

    async def create_harvest_event(
        self,
        user_id: str,
        segment_id: str,
        epoch_number: int,
        lp_tokens_held: float,
        dung_harvested: float,
        tx_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a harvest event record."""
        payload = {
            "user_id": user_id,
            "segment_id": segment_id,
            "epoch_number": epoch_number,
            "lp_tokens_held": lp_tokens_held,
            "dung_harvested": dung_harvested,
            "tx_signature": tx_signature,
            "harvested_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._run(
            lambda: self._client.table("harvest_events").insert(payload).execute()
        )
        return self._first_row(response) or payload

    # Token transactions
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
        """Create a token transaction record."""
        payload = {
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
        response = await self._run(
            lambda: self._client.table("token_transactions").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_user_transactions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        tx_type: Optional[str] = None,
        token_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get paginated token transactions for a user."""
        def _query():
            query = window(
                self._client.table("token_transactions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True),
                offset,
                limit,
            )
            if tx_type:
                query = query.eq("tx_type", tx_type)
            if token_type:
                query = query.eq("token_type", token_type)
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_all_user_transactions(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all token transactions for a user."""
        response = await self._run(
            lambda: self._client.table("token_transactions")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    # Helper method
    async def _get_user_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user state from user_state table."""
        response = await self._run(
            lambda: self._client.table("user_state")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)
