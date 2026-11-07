from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import json
import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.routes import admin_access
from app.routes.admin import require_admin
from app.dependencies import get_current_user
from app.access_repository import get_access_repository
from app.invite_security import hash_invite_code


def test_access_admin_mint_returns_plaintext_once_and_other_actions_omit_it():
    actor, invite_id=str(uuid4()),str(uuid4())
    calls=[]
    async def action(actor,action,target=None,details=None,code_hash=None):
        calls.append((actor,action,target,details,code_hash))
        if action=='mint_invite':
            return {'ok':True,'invite':{'id':invite_id,'remaining':details['max_uses']}}
        if action=='list_invites':
            return {'ok':True,'invites':[{'id':invite_id,'uses':[],'remaining':1}]}
        return {'ok':True}
    app=FastAPI(); app.include_router(admin_access.router)
    app.dependency_overrides[require_admin]=lambda:(actor,'admin')
    app.dependency_overrides[get_access_repository]=lambda:SimpleNamespace(action=action)
    client=TestClient(app)
    minted=client.post('/admin/access/invites',json={'intended_for':'rider@example.com','label':'cohort rider'})
    assert minted.status_code==200
    assert minted.headers['cache-control']=='no-store'
    code=minted.json()['code']
    assert len(code)==32
    assert calls[0][4]==hash_invite_code(code)
    assert code not in repr(calls)
    responses=[client.get('/admin/access/invites'),client.post(f'/admin/access/invites/{invite_id}/deactivate')]
    for suffix in ['cohort/admit','cohort/revoke','sessions/revoke']:
        responses.append(client.post('/admin/access/'+suffix,json={'wallet':'rider-wallet'}))
    assert all(response.status_code==200 and code not in response.text for response in responses)
    assert [call[1] for call in calls]==['mint_invite','list_invites','deactivate_invite','admit_cohort','revoke_cohort','revoke_sessions']
    assert calls[0][3]['max_uses']==1 and calls[0][3]['expires_in_days']==7
    assert all(call[0]==actor for call in calls)
    if output := os.environ.get('ACCESS_DOOR_EVIDENCE_PATH'):
        Path(output).write_text(json.dumps({
            'evidence_class':'local HTTP routes with fake repository; database semantics tested separately in PostgreSQL',
            'mint':{**minted.json(),'code':'[REDACTED]'},
            'remaining_responses':[response.json() for response in responses],
        },indent=2)+'\n')


def test_non_admin_cannot_invoke_access_actions():
    app=FastAPI();app.include_router(admin_access.router)
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(user_id=str(uuid4()),wallet='non-admin')
    repo=SimpleNamespace(action=AsyncMock())
    app.dependency_overrides[get_access_repository]=lambda:repo
    with patch('app.routes.admin.ComplianceRepository') as compliance:
        compliance.return_value.get_admin_role=AsyncMock(return_value=None)
        client=TestClient(app)
        for method,path,body in [('GET','/admin/access/invites',None),('POST','/admin/access/invites',{}),('POST','/admin/access/cohort/admit',{'wallet':'rider'}),('POST','/admin/access/cohort/revoke',{'wallet':'rider'}),('POST','/admin/access/sessions/revoke',{'wallet':'rider'}),('POST',f'/admin/access/invites/{uuid4()}/deactivate',None)]:
            assert client.request(method,path,json=body).status_code==403
    repo.action.assert_not_called()
