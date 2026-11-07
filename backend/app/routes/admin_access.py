"""Founder-operated access door; plaintext is returned only by mint."""
import secrets
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ConfigDict
from .admin import require_admin
from ..access_repository import AccessRepository, get_access_repository
from ..invite_security import hash_invite_code

router = APIRouter(prefix='/admin/access', tags=['admin-access'])

class MintInviteRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    max_uses: int = Field(default=1, ge=1, le=100000)
    expires_in_days: int = Field(default=7, ge=1, le=3650)
    intended_for: str | None = Field(default=None, min_length=1, max_length=320)
    label: str | None = Field(default=None, min_length=1, max_length=200)

class WalletRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    wallet: str = Field(min_length=1, max_length=128)


def _result(result):
    if not result.get('ok'):
        raise HTTPException(409 if result.get('error') == 'identity_conflict' else 404, detail=result.get('error'))
    return result

@router.post('/invites')
async def mint_invite(payload: MintInviteRequest, response: Response,
                      admin_ctx=Depends(require_admin), repo: AccessRepository=Depends(get_access_repository)):
    code = secrets.token_hex(16)
    result = _result(await repo.action(str(admin_ctx[0]), 'mint_invite',
        details=payload.model_dump(), code_hash=hash_invite_code(code)))
    response.headers['Cache-Control'] = 'no-store'
    return {**result, 'code': code}

@router.get('/invites')
async def list_invites(response: Response, admin_ctx=Depends(require_admin), repo: AccessRepository=Depends(get_access_repository)):
    response.headers['Cache-Control'] = 'no-store'
    return _result(await repo.action(str(admin_ctx[0]), 'list_invites'))

@router.post('/invites/{invite_id}/deactivate')
async def deactivate_invite(invite_id: UUID, admin_ctx=Depends(require_admin), repo: AccessRepository=Depends(get_access_repository)):
    return _result(await repo.action(str(admin_ctx[0]), 'deactivate_invite', target=str(invite_id)))

@router.post('/cohort/admit')
async def admit_cohort(payload: WalletRequest, admin_ctx=Depends(require_admin), repo: AccessRepository=Depends(get_access_repository)):
    return _result(await repo.action(str(admin_ctx[0]), 'admit_cohort', target=payload.wallet))

@router.post('/cohort/revoke')
async def revoke_cohort(payload: WalletRequest, admin_ctx=Depends(require_admin), repo: AccessRepository=Depends(get_access_repository)):
    return _result(await repo.action(str(admin_ctx[0]), 'revoke_cohort', target=payload.wallet))

@router.post('/sessions/revoke')
async def revoke_sessions(payload: WalletRequest, admin_ctx=Depends(require_admin), repo: AccessRepository=Depends(get_access_repository)):
    return _result(await repo.action(str(admin_ctx[0]), 'revoke_sessions', target=payload.wallet))
