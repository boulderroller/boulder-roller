"""Atomic founder access actions, backed by a server-only audited RPC."""
from .repositories.base import BaseRepository, get_supabase_client

class AccessRepository(BaseRepository):
    async def action(self, actor: str, action: str, target=None, details=None, code_hash=None):
        response = await self._run(lambda: self._client.rpc('access_admin_action', {
            'p_actor': actor, 'p_action': action, 'p_target': target,
            'p_details': details or {}, 'p_code_hash': code_hash,
        }).execute())
        return response.data


def get_access_repository() -> AccessRepository:
    return AccessRepository(get_supabase_client())
