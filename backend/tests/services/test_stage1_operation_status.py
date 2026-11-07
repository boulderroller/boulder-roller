"""Owner operation recovery uses observed signatures and finalized blockhash expiry."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from solders.hash import Hash
from solders.signature import Signature
from app.services import stage1_operation_status as subject
from app.services import stage1_transactions
from app.services.balance_operation_status import operation_status_from_record
from app.services.balance_transaction_coordinator import BalanceOperationIntent, BalanceTransactionCoordinator, InMemoryBalanceOperationLog
from app.services.boulder_balance_authority import AuthorityModel


@pytest.mark.asyncio
@pytest.mark.parametrize('case,expected', [('confirmed','recorded'), ('finalized','recorded'), ('failed','needs_review'), ('expired','needs_review'), ('pending','pending'), ('other_network','pending'), ('rpc_missing','pending'), ('new_hash','pending'), ('write_lost','pending')])
async def test_reconcile_exact_signature_or_finalized_expiry(monkeypatch, case, expected):
    monkeypatch.setenv('STAGE1_ACTIONS_ENABLED','true')
    log=InMemoryBalanceOperationLog(); coordinator=BalanceTransactionCoordinator(sink=log)
    operation=coordinator.prepare_operation(BalanceOperationIntent(action_type='stage1_registration',rider_account_id='owner',protocol_wallet='wallet',
        authority_model=AuthorityModel.WALLET_BOUNDARY,asset='SOL',amount='0',source='wallet',destination='wallet',step_up_satisfied=True,
        tx_signature=str(Signature.default()),metadata={'program':'program','genesis':'genesis','recent_blockhash':str(Hash.default())}))
    monkeypatch.setattr(subject,'load_record',lambda *args:log.get(operation.operation_id))
    monkeypatch.setattr(subject,'BalanceTransactionCoordinator',lambda **kw:coordinator)
    monkeypatch.setattr(stage1_transactions,'get_stage1_tx_builder',lambda:SimpleNamespace(program_id='program',rpc_url='http://127.0.0.1:1',require_enabled_chain=AsyncMock()))
    if case=='write_lost': monkeypatch.setattr(log, 'update', lambda record: None)
    observed=SimpleNamespace(err='program error' if case=='failed' else None,confirmation_status='confirmed' if case in ('failed','write_lost') else case)
    rpc=SimpleNamespace(get_genesis_hash=AsyncMock(return_value=SimpleNamespace(value='other' if case=='other_network' else 'genesis')),
        get_signature_statuses=AsyncMock(return_value=SimpleNamespace(value=[observed if case in ('confirmed','finalized','failed','write_lost') else None])))
    if case=='rpc_missing':rpc.get_signature_statuses.side_effect=RuntimeError('RPC unavailable')
    context=SimpleNamespace(__aenter__=AsyncMock(return_value=rpc),__aexit__=AsyncMock())
    class RPC:
        async def __aenter__(self):return rpc
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(subject,'AsyncClient',lambda *args:RPC())
    validity=AsyncMock(return_value=SimpleNamespace(value=case!='expired'))
    if case=='new_hash':validity.side_effect=[SimpleNamespace(value=False),SimpleNamespace(value=True)]
    monkeypatch.setattr(subject,'is_blockhash_valid_compat',validity)
    result=await subject.reconcile_stage1_operation(operation_status_from_record(operation),object())
    assert result.rider.read_state==expected
    from app.routes.balance_operations import _rider_response
    assert _rider_response(result).stage1_terminal_failure is (case in ('failed','expired'))
    if case=='expired':
        assert result.support.confirmation_status=='expired'
        assert rpc.get_signature_statuses.await_count==2
        assert [call.kwargs['commitment'] for call in validity.call_args_list]==['finalized','confirmed']
    if case=='other_network':rpc.get_signature_statuses.assert_not_awaited()
