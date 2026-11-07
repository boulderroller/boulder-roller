"""Reconcile the exact owner-signed signature; no inferred indexer completion."""
from __future__ import annotations

import asyncio
import os
from solana.rpc.async_api import AsyncClient
from solders.signature import Signature
from solders.hash import Hash
from .solana_submit import is_blockhash_valid_compat

from .balance_operation_status import operation_record_from_row, operation_status_from_record
from .balance_transaction_coordinator import BalanceProjectionStatus, BalanceTransactionCoordinator, SupabaseBalanceOperationSink


def load_record(client, operation_id, user_id):
    rows = client.table('balance_operations').select('*').eq('operation_id', operation_id).eq('rider_account_id', user_id).limit(1).execute().data
    return operation_record_from_row(rows[0]) if rows else None


async def reconcile_stage1_operation(status, client):
    """Called by the existing owner-only reader. A missing RPC result stays pending."""
    if not status or not status.support.action_type.startswith('stage1_'):
        return status
    if os.getenv('STAGE1_ACTIONS_ENABLED', '').lower() not in ('true', '1'):
        return status
    record = await asyncio.to_thread(load_record, client, status.support.operation_id, status.support.rider_account_id)
    if not record or record.confirmation_status in ('failed', 'expired') or record.projection_status == 'recorded':
        return status
    from .stage1_transactions import get_stage1_tx_builder
    try:
        builder = get_stage1_tx_builder()
        await builder.require_enabled_chain()
        if record.metadata.get('program') != str(builder.program_id):
            return status
        async with AsyncClient(builder.rpc_url) as rpc:
            if str((await rpc.get_genesis_hash()).value) != record.metadata.get('genesis'):
                return status
            observation = (await rpc.get_signature_statuses([Signature.from_string(record.tx_signature)], search_transaction_history=True)).value[0]
            expired = False
            if observation is None and record.metadata.get('recent_blockhash'):
                validity = await is_blockhash_valid_compat(rpc, Hash.from_string(record.metadata['recent_blockhash']), commitment='finalized')
                # A newly confirmed hash may not be present in the finalized
                # bank yet. Both banks must reject it before absence is expiry.
                confirmed_validity = await is_blockhash_valid_compat(rpc, Hash.from_string(record.metadata['recent_blockhash']), commitment='confirmed')
                if not validity.value and not confirmed_validity.value:
                    # Recheck history after the finalized expiry observation.
                    observation = (await rpc.get_signature_statuses([Signature.from_string(record.tx_signature)], search_transaction_history=True)).value[0]
                    expired = observation is None
        coordinator = BalanceTransactionCoordinator(sink=SupabaseBalanceOperationSink(client))
        if expired:
            record = coordinator.mark_failed(record, reason='Signed blockhash expired with signature absent from history', expired=True)
        elif observation and observation.err and str(observation.confirmation_status).lower().split('.')[-1] in ('confirmed', 'finalized'):
            record = coordinator.mark_failed(record, reason=str(observation.err))
        elif observation and str(observation.confirmation_status).lower().split('.')[-1] in ('confirmed', 'finalized'):
            record = coordinator.mark_confirmed(record, finalized='finalized' in str(observation.confirmation_status).lower())
            # Stage1 has no off-chain money projection to apply. This records
            # the confirmed chain receipt, not a claim that indexer pages caught up.
            record = coordinator.mark_projection(record, BalanceProjectionStatus.RECORDED)
        # Updates can fail without raising. The durable row controls whether
        # the cross-tab exclusion has actually been released.
        persisted = await asyncio.to_thread(load_record, client, record.operation_id, record.rider_account_id)
        return operation_status_from_record(persisted) if persisted else status
    except Exception:
        return status
