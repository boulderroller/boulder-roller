import ast
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from app import solana_direct


@pytest.mark.parametrize('name', [
    'make_admin_override_open_settlement_week_ix',
    'make_admin_seed_pending_rewards_ix',
    'make_admin_override_stake_eligibility_ix',
])
def test_backend_has_no_builder_for_localnet_only_setup_instructions(name):
    # The program compiles these only into the isolated stage1-localnet test
    # build (cargo feature smoke-helpers); deployable binaries do not have them.
    assert not hasattr(solana_direct, name)
    assert not hasattr(solana_direct, name.replace('make_', 'send_').removesuffix('_ix'))


def test_current_smokes_never_invoke_the_three_disabled_entries():
    scripts = Path(__file__).parents[2] / 'scripts'
    for name in ('smoke_devnet_economics', 'smoke_full_stack', 'smoke_wallet_signed_economics',
                 'prove_composed_withdraw_devnet', 'rehearsal_evidence'):
        tree = ast.parse((scripts / f'{name}.py').read_text())
        for call in (n for n in ast.walk(tree) if isinstance(n, ast.Call)):
            target = getattr(call.func, 'id', getattr(call.func, 'attr', ''))
            assert target not in {
                'send_admin_override_open_settlement_week', 'make_admin_override_open_settlement_week_ix',
                'send_admin_seed_pending_rewards', 'make_admin_seed_pending_rewards_ix',
                'send_admin_override_stake_eligibility', 'make_admin_override_stake_eligibility_ix',
            }, (name, call.lineno, target)


@pytest.mark.asyncio
async def test_clock_wait_does_not_finish_on_host_time(monkeypatch):
    import smoke_devnet_economics as smoke
    from app.services.settlement_chain import SettlementChain
    clock = AsyncMock(side_effect=[99, 100])
    sleep = AsyncMock()
    monkeypatch.setattr(SettlementChain, 'read_chain_time', clock)
    monkeypatch.setattr(smoke.asyncio, 'sleep', sleep)
    await smoke.wait_for_smoke_time(object(), 100)
    assert clock.await_count == 2
    sleep.assert_awaited_once_with(1)
