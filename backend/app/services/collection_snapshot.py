"""One confirmed RPC revision of collection quotes, independent of index history."""
from datetime import datetime, timezone
import logging

import base58
from solana.rpc.async_api import AsyncClient
from solders.account_decoder import UiAccountEncoding
from solders.commitment_config import CommitmentLevel
from solders.pubkey import Pubkey
from solders.rpc.config import RpcAccountInfoConfig, RpcProgramAccountsConfig
from solders.rpc.filter import Memcmp
from solders.rpc.requests import GetProgramAccounts
from solders.rpc.responses import GetProgramAccountsWithContextResp

from .. import solana_direct as chain

logger = logging.getLogger(__name__)


async def get_collection_snapshot(wallet: str) -> dict:
    config = chain.load_readonly_config()
    rider = Pubkey.from_string(wallet)
    request = GetProgramAccounts(config.program_id, RpcProgramAccountsConfig(
        RpcAccountInfoConfig(encoding=UiAccountEncoding.Base64, commitment=CommitmentLevel.Confirmed),
        filters=[Memcmp(0, base58.b58encode(chain._vault_stake_account_discriminator()).decode()), Memcmp(8, str(rider))],
        with_context=True,
    ))
    async with AsyncClient(config.rpc_url) as client:
        response = await client._provider.make_request(request, GetProgramAccountsWithContextResp)
    inventory = response.value
    slot = int(inventory.context.slot)
    rows = inventory.value
    positions = []
    seen = set()
    for account in rows:
        try:
            if account.account.owner != config.program_id:
                raise ValueError('owner mismatch')
            stake = chain._decode_anchor_vault_stake_account(chain._account_data_bytes(account.account.data), account.pubkey)
            vault_id = chain._vault_stake_u64(stake, 'vault_id')
            pda, bump = chain._derive_vault_stake_pda(rider, vault_id, config.program_id)
            if account.pubkey != pda or stake.get('bump') != bump or stake.get('user') != str(rider) or vault_id in seen:
                raise ValueError('stake identity mismatch')
            lp = chain._vault_stake_u64(stake, 'lp_tokens')
            # Same active-position and unclaimed balance predicate as pending-rewards.
            # The on-chain field resets on harvest; indexed cumulative history is unused.
            ready = chain._vault_stake_u64(stake, 'rewards_earned') if lp > 0 else 0
            seen.add(vault_id)
            positions.append({'vaultId': vault_id, 'dungReadyBaseUnits': str(ready)})
        except Exception as exc:
            logger.warning('Collection account unavailable: %s', exc)
    complete = len(positions) == len(rows)
    return {
        'revision': f'{config.program_id}:{wallet}:{slot}',
        'asOf': datetime.now(timezone.utc).isoformat(),
        'coverage': {'completeness': 'complete' if complete else 'partial', 'population': 'wallet_vault_stakes', 'observedCount': len(positions), 'expectedCount': len(rows)},
        'positions': sorted(positions, key=lambda row: row['vaultId']),
        'uncollectedDungBaseUnits': str(sum(int(row['dungReadyBaseUnits']) for row in positions)) if complete else None,
    }
