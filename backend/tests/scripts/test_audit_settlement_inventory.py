import base64
import importlib.util
import struct
from pathlib import Path

from solders.pubkey import Pubkey

spec = importlib.util.spec_from_file_location('audit', Path(__file__).parents[2] / 'scripts/audit_settlement_inventory.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def fixture(monkeypatch, count, *, bad_inert=False):
    program = Pubkey.new_unique()
    vault_key = audit._derive_vault_pda(0, program)[0]
    counter_key, bump = audit._derive_vault_counter_pda(program)
    def account(key, data):
        return {'pubkey': str(key), 'account': {'owner': str(program), 'data': [base64.b64encode(data).decode(), 'base64']}}
    accounts = [account(counter_key, audit.discriminator('VaultCounter') + struct.pack('<QB', 1, bump)),
                account(vault_key, audit.discriminator('Vault'))]
    decoded = {}
    for index in range(count + int(bad_inert)):
        rider = Pubkey.new_unique()
        key, bump = audit._derive_vault_stake_pda(rider, 0, program)
        inert = index == count
        # Include zero-current-LP tombstones and pending-only accounts in inventory.
        decoded[str(key)] = dict(user=str(rider), pda=str(key), vault_id=0,
            bump=(bump + 1) % 256 if inert else bump, lp_tokens=0,
            effective_lp_tokens=1 if index % 2 and not inert else 0,
            pending_lp_tokens=1 if not index % 2 and not inert else 0,
            snapshot_layout='weekly')
        accounts.append(account(key, audit.discriminator('VaultStake')))
    monkeypatch.setattr(audit, '_decode_anchor_vault_account', lambda data, key: dict(id=0, staker_count=count))
    monkeypatch.setattr(audit, '_decode_anchor_vault_stake_account', lambda data, key: decoded[str(key)])
    return accounts, program


def test_ceiling_includes_tombstones_and_pending_positions(monkeypatch):
    accounts, program = fixture(monkeypatch, 33)
    rows, errors, _, count = audit.evaluate(accounts, program)
    assert count == 33 and rows[0][2] == 33
    assert 'OVER CEILING' in rows[0][-1] and errors
    accounts, program = fixture(monkeypatch, 32)
    assert audit.evaluate(accounts, program)[1] == []


def test_inert_stake_bump_is_checked_too(monkeypatch):
    accounts, program = fixture(monkeypatch, 1, bad_inert=True)
    rows, errors, _, count = audit.evaluate(accounts, program)
    assert count == 2 and rows[0][2] == 1 and rows[0][4] == 1
    assert any('stored bump' in error for error in errors)


def test_missing_vault_counter_cannot_report_pass(monkeypatch):
    accounts, program = fixture(monkeypatch, 0)
    assert audit.evaluate(accounts[1:], program)[1]
