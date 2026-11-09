#!/usr/bin/env python3
"""Read-only H2 admission audit. One finalized getProgramAccounts snapshot.

No keypair is loaded and no transaction is constructed. Exit 1 means incompatible
inventory/bump/account data; exit 2 means the audit could not be completed.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from solders.pubkey import Pubkey
from app.solana_direct import (
    _decode_anchor_vault_account, _decode_anchor_vault_stake_account,
    _derive_vault_pda, _derive_vault_stake_pda, _derive_vault_counter_pda,
    _stake_requires_settlement_account, parse_vault_counter,
)
from app.solana_env import DEFAULT_BOULDER_ROLLERS_PROGRAM_ID

CANDIDATE_CEILING = 32
DEVNET_GENESIS = 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG'


def discriminator(name):
    return hashlib.sha256(f'account:{name}'.encode()).digest()[:8]


def evaluate(accounts, program_id):
    vaults, stakes, errors = {}, [], []
    counter = None
    fingerprints = []
    seen = set()
    for item in accounts:
        address = item['pubkey']
        account = item['account']
        data = base64.b64decode(account['data'][0], validate=True)
        fingerprints.append((address, account['owner'], hashlib.sha256(data).hexdigest()))
        if address in seen:
            errors.append(f'duplicate account {address}')
        seen.add(address)
        if account['owner'] != str(program_id):
            errors.append(f'foreign owner at {address}')
            continue
        try:
            key = Pubkey.from_string(address)
            if data[:8] == discriminator('VaultCounter'):
                if key != _derive_vault_counter_pda(program_id)[0] or counter is not None:
                    raise ValueError('non-canonical/duplicate VaultCounter')
                counter = parse_vault_counter(data).count
            elif data[:8] == discriminator('Vault'):
                vault = _decode_anchor_vault_account(data, key)
                vid = int(vault['id'])
                if key != _derive_vault_pda(vid, program_id)[0] or vid in vaults:
                    raise ValueError('non-canonical/duplicate Vault')
                vaults[vid] = vault
            elif data[:8] == discriminator('VaultStake'):
                stake = _decode_anchor_vault_stake_account(data, key)
                stakes.append(stake)
        except Exception as exc:
            errors.append(f'{address}: {exc}')
    if counter is None or sorted(vaults) != list(range(int(counter or 0))):
        errors.append(f'VaultCounter scope incomplete: count={counter}, decoded Vaults={len(vaults)}')
    relevant, total, bad = Counter(), Counter(), Counter()
    for stake in stakes:
        vid = int(stake['vault_id'])
        total[vid] += 1
        if vid not in vaults:
            errors.append(f'orphan VaultStake {stake["pda"]}, Vault {vid}')
        expected, bump = _derive_vault_stake_pda(Pubkey.from_string(stake['user']), vid, program_id)
        if stake['pda'] != str(expected) or int(stake['bump']) != bump:
            bad[vid] += 1
            errors.append(f'VaultStake {stake["pda"]}: stored bump {stake["bump"]}, canonical {bump}, canonical PDA {expected}')
        if _stake_requires_settlement_account(stake):
            relevant[vid] += 1
    rows = []
    for vid, vault in sorted(vaults.items()):
        stored_count = int(vault['staker_count'])
        issues = []
        if relevant[vid] > CANDIDATE_CEILING or stored_count > CANDIDATE_CEILING:
            issues.append('OVER CEILING')
        if stored_count != relevant[vid]:
            issues.append('COUNT MISMATCH')
        if bad[vid]:
            issues.append('NON-CANONICAL BUMP/PDA')
        if issues:
            errors.append(f'Vault {vid}: {", ".join(issues)}')
        rows.append((vid, total[vid], relevant[vid], stored_count, bad[vid], ', '.join(issues) or 'PASS'))
    digest = hashlib.sha256(json.dumps(sorted(fingerprints), separators=(',', ':')).encode()).hexdigest()
    return rows, errors, digest, len(stakes)


def render(rows, errors, digest, stake_count, *, program_id, slot, endpoint, observed_at):
    lines = [f'# Devnet settlement inventory audit — {observed_at}', '',
             'Evidence class: live, read-only, finalized devnet account snapshot.', '',
             f'Program: `{program_id}`. RPC host: `{endpoint}`. Finalized slot: `{slot}`.',
             f'Candidate: `a905fb14`; provisional ceiling: {CANDIDATE_CEILING} relevant positions per Vault.',
             f'Account inventory SHA-256: `{digest}`.', '',
             '| Vault | All positions | Relevant positions | Stored staker_count | Bad bumps/PDAs | Result |',
             '| ---: | ---: | ---: | ---: | ---: | --- |']
    lines += ['| ' + ' | '.join(map(str, row)) + ' |' for row in rows]
    lines += ['', f'**{"FAIL" if errors else "PASS"}**: {len(rows)} Vaults; {stake_count} VaultStake accounts checked, including inert positions.',
              'Relevant means live LP, effective snapshot LP, or pending snapshot LP is nonzero. Legacy layouts use the existing decoder/relevance rule.',
              'This proves compatibility at this snapshot only; it is not a capacity certificate or authorization to deploy.', '']
    lines += [f'- {error}' for error in errors]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rpc-url', default=os.getenv('SOLANA_RPC_URL', 'https://api.devnet.solana.com'))
    parser.add_argument('--program-id', default=DEFAULT_BOULDER_ROLLERS_PROGRAM_ID)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    program = Pubkey.from_string(args.program_id)
    with httpx.Client(timeout=120) as client:
        def rpc(method, params):
            response = client.post(args.rpc_url, json={'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params})
            response.raise_for_status()
            body = response.json()
            if 'error' in body:
                raise RuntimeError(f'{method}: {body["error"]}')
            return body['result']
        if rpc('getGenesisHash', []) != DEVNET_GENESIS:
            raise RuntimeError('RPC genesis is not devnet')
        snapshot = rpc('getProgramAccounts', [str(program), {'encoding': 'base64', 'commitment': 'finalized', 'withContext': True}])
    rows, errors, digest, stake_count = evaluate(snapshot['value'], program)
    report = render(rows, errors, digest, stake_count, program_id=program,
                    slot=snapshot['context']['slot'], endpoint=urlsplit(args.rpc_url).hostname,
                    observed_at=datetime.now(timezone.utc).isoformat())
    print(report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report)
    return int(bool(errors))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        # Never include a credential-bearing provider URL in a public report.
        print(f'Audit incomplete ({type(exc).__name__}); no compatibility claim.', file=sys.stderr)
        sys.exit(2)
