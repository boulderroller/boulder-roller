from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from starlette.requests import Request
from app import cohort_admission as access

@pytest.mark.asyncio
@pytest.mark.parametrize('required,admitted,denied', [(False,False,False),(False,True,False),(True,False,True),(True,True,False)])
@pytest.mark.parametrize('path',['/vaults/{vault_id}/stake/prepare','/vaults/{vault_id}/harvest/prepare'])
async def test_admission_gate(required,admitted,denied,path,monkeypatch):
    monkeypatch.setattr(access,'load_auth_settings',lambda: SimpleNamespace(cohort_admission_required=required))
    repo=SimpleNamespace(is_admitted=AsyncMock(return_value=admitted))
    request=Request({'type':'http','method':'POST','path':'/vaults/1/stake/prepare','route':SimpleNamespace(path=path)})
    monkeypatch.setattr(access,'get_admission_repository',lambda:repo)
    user=SimpleNamespace(user_id='user',wallet='wallet')
    if denied:
        with pytest.raises(HTTPException) as err:
            await access.require_cohort_admission(request,user,repo)
        assert err.value.status_code == 403
        assert err.value.detail['error']['code'] == 'cohort_admission_required'
    else:
        await access.require_cohort_admission(request,user,repo)
    if not required:
        repo.is_admitted.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.parametrize('path',['/vaults/{vault_id}/unstake/prepare','/vaults','/auth/verify','/rides','/portfolio/balance/add-funds/prepare'])
async def test_other_actions_are_never_gated(path,monkeypatch):
    monkeypatch.setattr(access,'load_auth_settings',lambda: SimpleNamespace(cohort_admission_required=True))
    repo=SimpleNamespace(is_admitted=AsyncMock(return_value=False))
    request=Request({'type':'http','method':'POST','path':path,'route':SimpleNamespace(path=path)})
    monkeypatch.setattr(access,'get_admission_repository',lambda:repo)
    await access.require_cohort_admission(request,SimpleNamespace(user_id='user'),repo)
    repo.is_admitted.assert_not_called()


def test_cookie_rejects_raw_digest_tampering_and_non_ascii():
    from app.invite_security import hash_invite_code, invite_cookie, read_invite_cookie
    signed=invite_cookie('person-code-test')
    assert read_invite_cookie(signed)==hash_invite_code('person-code-test')
    for value in [hash_invite_code('person-code-test'),signed[:-1]+'z', 'a'*64+'.é', '', '.', 'a'*64+'.'+'b'*64]:
        assert read_invite_cookie(value)==''


def test_application_mounts_admission_only_on_the_two_preparations():
    from app.main import create_app
    app=create_app()
    mounted={route.path for route in app.routes if any(getattr(dep,'call',None) is access.require_cohort_admission for dep in getattr(getattr(route,'dependant',None),'dependencies',[]))}
    assert mounted == access.PREPARATION_PATHS


@pytest.mark.parametrize('path',['/vaults/1/stake/prepare','/vaults/1/harvest/prepare'])
def test_real_preparation_route_denies_before_transaction_building(path,monkeypatch):
    from app.main import create_app
    from app.dependencies import get_current_user, get_repository
    from app.routes.vaults import get_vault_repo
    from fastapi.testclient import TestClient
    monkeypatch.setattr(access,'load_auth_settings',lambda:SimpleNamespace(cohort_admission_required=True))
    app=create_app()
    app.dependency_overrides[get_current_user]=lambda:SimpleNamespace(user_id='user',wallet='wallet')
    app.dependency_overrides[access.get_admission_repository]=lambda:SimpleNamespace(is_admitted=AsyncMock(return_value=False))
    app.dependency_overrides[get_repository]=lambda:SimpleNamespace()
    app.dependency_overrides[get_vault_repo]=lambda:SimpleNamespace()
    response=TestClient(app).post(path,json={'calAmount':100})
    assert response.status_code == 403
    assert response.json()['detail']['error']['code']=='cohort_admission_required'


@pytest.mark.parametrize('environment',['development','test','staging','production'])
def test_config_admission_defaults_off_everywhere(environment,monkeypatch,caplog):
    from app.config import get_environment,load_auth_settings
    monkeypatch.setenv('ENVIRONMENT',environment)
    monkeypatch.delenv('COHORT_ADMISSION_REQUIRED',raising=False)
    monkeypatch.delenv('INVITE_CODE_SECRET',raising=False)
    get_environment.cache_clear();load_auth_settings.cache_clear()
    settings=load_auth_settings()
    assert settings.cohort_admission_required is False
    assert settings.invite_code_secret==settings.refresh_token_secret
    assert 'INVITE_CODE_SECRET is unset' in caplog.text
    assert settings.refresh_token_secret not in caplog.text
