"""API-only admission for Deposit CAL and Collect DUNG preparation."""
from fastapi import Depends, HTTPException, Request
from .config import load_auth_settings
from .dependencies import AuthenticatedUser, get_current_user
from .repositories.base import BaseRepository, get_supabase_client

PREPARATION_PATHS = frozenset({
    '/vaults/{vault_id}/stake/prepare',
    '/vaults/{vault_id}/harvest/prepare',
})

class AdmissionRepository(BaseRepository):
    def __init__(self, client=None):
        self._client = client

    async def is_admitted(self, user_id: str) -> bool:
        client = self._client or get_supabase_client()
        result = await self._run(lambda: client.table('users')
            .select('cohort_admitted_at').eq('id', user_id).limit(1).execute())
        return bool(result.data and result.data[0].get('cohort_admitted_at'))


def get_admission_repository() -> AdmissionRepository:
    return AdmissionRepository()


async def require_cohort_admission(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: AdmissionRepository = Depends(get_admission_repository),
) -> None:
    if (request.method != 'POST'
        or getattr(request.scope.get('route'), 'path', None) not in PREPARATION_PATHS
        or not load_auth_settings().cohort_admission_required):
        return
    if current_user is None:
        raise HTTPException(401, detail='Not authenticated')
    if not await repo.is_admitted(current_user.user_id):
        raise HTTPException(403, detail={'error': {'code': 'cohort_admission_required'}})
