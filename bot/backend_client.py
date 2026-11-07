import base64
import uuid
from typing import Any, Dict, Optional

import httpx


class BackendClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30.0)

    async def close(self):
        await self._client.aclose()

    async def get_nonce(self, wallet: str, device_id: str) -> Dict[str, Any]:
        resp = await self._client.post("/auth/nonce", json={"wallet": wallet, "device_id": device_id})
        resp.raise_for_status()
        return resp.json()

    async def verify_signature(self, wallet: str, signature: str, nonce: str, device_id: str) -> Dict[str, Any]:
        resp = await self._client.post(
            "/auth/verify",
            json={"wallet": wallet, "signature": signature, "nonce": nonce, "device_id": device_id},
        )
        resp.raise_for_status()
        return resp.json()

    async def refresh(self, refresh_token: str, device_id: str) -> Dict[str, Any]:
        resp = await self._client.post("/auth/refresh", json={"refresh_token": refresh_token, "device_id": device_id})
        resp.raise_for_status()
        return resp.json()

    async def upload_ride(self, file_bytes: bytes, file_type: str, access_token: str) -> Dict[str, Any]:
        file_b64 = base64.b64encode(file_bytes).decode("ascii")
        resp = await self._client.post(
            "/rides/upload",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"file_data_b64": file_b64, "file_type": file_type},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_ride_status(self, ride_id: str, access_token: str) -> Dict[str, Any]:
        resp = await self._client.get(
            f"/rides/{ride_id}/status",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_ride_segments(self, ride_id: str, access_token: str) -> Dict[str, Any]:
        resp = await self._client.get(
            f"/rides/{ride_id}/segments",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()

    async def list_rides(self, access_token: str) -> Dict[str, Any]:
        resp = await self._client.get("/rides", headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()

    async def get_token_balances(self, access_token: str) -> Dict[str, Any]:
        resp = await self._client.get("/mint", headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()

    async def get_kcal_balance(self, access_token: str) -> Dict[str, Any]:
        resp = await self._client.get("/cal/balance", headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()

    async def get_claims(self, access_token: str) -> Dict[str, Any]:
        resp = await self._client.get("/staking/claims", headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()

    async def list_segments(self, query: Optional[str], access_token: str) -> Dict[str, Any]:
        params = {}
        if query:
            params["q"] = query
        resp = await self._client.get("/segments/list", headers={"Authorization": f"Bearer {access_token}"}, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_pending_rewards(self, access_token: str) -> Dict[str, Any]:
        resp = await self._client.get("/staking/pending-rewards", headers={"Authorization": f"Bearer {access_token}"})
        resp.raise_for_status()
        return resp.json()


def generate_device_id(chat_id: int) -> str:
    # Use a stable UUID per chat for auth flows (backend expects UUID format)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"telegram-{chat_id}"))
