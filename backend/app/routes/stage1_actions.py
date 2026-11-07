"""Dark, owner-only prepare/check/submit routes; screens are a separate lane."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
import base64
from contextlib import asynccontextmanager
import hashlib
import json
import os
from copy import copy
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, create_model, field_validator
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

from ..db_pool import get_pool
from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..services.balance_transaction_coordinator import BalanceOperationError, BalanceOperationIntent, prepared_message_hash
from ..services.balance_transaction_submission import BalanceSubmissionError, submit_confirmed_balance_transaction
from ..services.boulder_balance_authority import AuthorityModel
from ..services.stage1_transactions import (get_stage1_tx_builder, Stage1Plan, Stage1LookupRequired,
    Stage1WithdrawalPaused, require_withdrawal_window, withdrawal_pause_until)
from ..services.stage1_operation_status import load_record
from ..services import stage1_availability
from ..middleware.rate_limiter import rate_limiter
from ..services.stage1_claim_cache import ClaimDiscoveryCache
from ..middleware.rate_limiter import rate_limit
from ..program_compatibility import program_compatibility
from .portfolio import _balance_coordinator, _prepared_balance_response

router = APIRouter()
claim_cache = ClaimDiscoveryCache()
Units = Annotated[str, StringConstraints(pattern=r"^(0|[1-9][0-9]*)$", max_length=20)]
Address = Annotated[str, StringConstraints(min_length=32, max_length=44)]
Lock = Literal[0, 13, 26, 52]


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="after", check_fields=False)
    @classmethod
    def exact_values(cls, value, info):
        if info.field_name in ("deposit_id", "request_id", "amount_base_units", "basis_lamports", "recent_slot") and value is not None:
            if int(value) >= 1 << 64 or (info.field_name in ("amount_base_units", "basis_lamports") and int(value) == 0):
                raise ValueError("Invalid u64 amount")
        if info.field_name in ("hill", "mint", "lot", "request", "lookup_table") and value is not None:
            if str(Pubkey.from_string(value)) != value:
                raise ValueError("Invalid public key")
        if info.field_name in ("lock_weeks", "role") and type(value) is not int:
            raise ValueError("Invalid lock")
        return value


class PledgeRequest(ActionRequest):
    hill: Address
    mint: Address
    deposit_id: Units
    amount_base_units: Units
    lock_weeks: Lock


class CancelPledgeRequest(ActionRequest):
    lot: Address


class NoticeRequest(ActionRequest):
    lot: Address
    request_id: Units
    basis_lamports: Units


class WithdrawalRequest(ActionRequest):
    lot: Address
    request: Address
    refresh_rate: bool = True


class ConvertRequest(ActionRequest):
    lot: Address
    lock_weeks: Lock
    refresh_rate: bool = True


class ClaimReference(ActionRequest):
    job_id: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    role: Literal[-1, 0, 1] = -1
    index: Annotated[int, Field(ge=0, le=65535)]


class ClaimRequest(ActionRequest):
    claims: Annotated[list[ClaimReference], Field(min_length=1, max_length=4)]
    lookup_table: Address | None = None


class TransportRequest(ActionRequest):
    mode: Literal["create", "deactivate", "close"]
    claims: Annotated[list[ClaimReference], Field(max_length=1)] = []
    recent_slot: Units | None = None
    lookup_table: Address | None = None


@rate_limit(category="stage1_actions")
async def limit_action(request: Request):
    pass


@rate_limit(category="stage1_claims")
async def limit_claims(request: Request):
    pass


async def action_builder(request: Request, user: AuthenticatedUser = Depends(get_current_user)):
    if os.getenv("STAGE1_ACTIONS_ENABLED", "").strip().lower() not in ("1", "true"):
        raise HTTPException(503, "TIM: stage1_actions_unavailable")
    # Shared by every new action and discovery route. Limit before creating a
    # builder or checking the chain, and key to authenticated identity, not IP.
    request.state.user_id = user.user_id
    await (limit_claims(request=request) if request.method == "GET" else limit_action(request=request))
    try:
        builder = get_stage1_tx_builder()
        request_builder = copy(builder)
        if request.method == "GET":
            # Claim discovery is a read: bind the stored release admission and
            # never refresh the chain version. Prepare/submit keep the live gate.
            network = await stage1_availability.stored_network()
            if not network or network["program"] != str(builder.program_id):
                raise ValueError("Stage 1 network not admitted")
            request_builder.observed_genesis = network["genesis"]
        else:
            await builder.require_enabled_chain()
            # The chain gate already observed genesis. Bind that live identity to
            # this request, rather than trusting a cached/database network label.
            request_builder.observed_genesis = program_compatibility(builder.rpc_url, str(builder.program_id)).genesis
        if not request_builder.observed_genesis:
            raise ValueError("Stage 1 network unobserved")
        return request_builder
    except Exception:
        raise HTTPException(503, "TIM: stage1_actions_unavailable") from None


async def stored_action_network(user: AuthenticatedUser = Depends(get_current_user)):
    network = await stage1_availability.stored_network() if stage1_availability.enabled('STAGE1_ACTIONS_ENABLED') else None
    if not network:
        raise HTTPException(503, 'TIM: stage1_actions_unavailable')
    return network


async def action_read_builder(network=Depends(stored_action_network)):
    try:
        return get_stage1_tx_builder()
    except Exception:
        raise HTTPException(503, 'TIM: stage1_actions_unavailable') from None


async def limit_read(user, kind, limit=12):
    allowed, _, reset = await rate_limiter.check_rate_limit(f'stage1.{kind}.{user.user_id}', limit, 60)
    if not allowed:
        raise HTTPException(429, 'TIM: stage1_actions_unavailable', headers={'Retry-After': str(max(1, reset - int(time.time())))})


@router.get('/me/lookups')
async def lookups(response: Response, offset: int = Query(0, ge=0),
                  user: AuthenticatedUser = Depends(get_current_user), builder=Depends(action_read_builder),
                  network=Depends(stored_action_network)):
    """Recover this owner's transport inventory without browser storage."""
    response.headers['Cache-Control'] = 'private, no-store'
    await limit_read(user, 'lookups', 30)
    pool = await get_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch("""SELECT reference_id,
            (array_agg(tx_signature ORDER BY created_at DESC) FILTER (
                WHERE metadata->>'transport_mode'='close'
                AND confirmation_status IN ('confirmed','finalized')))[1] AS close_signature
            FROM balance_operations WHERE rider_account_id=$1 AND protocol_wallet=$2
            AND metadata->>'program'=$3 AND metadata->>'genesis'=$4
            AND action_type='stage1_claim_transport' AND reference_type='stage1'
            AND reference_id IS NOT NULL AND confirmation_status NOT IN ('failed','expired')
            GROUP BY reference_id ORDER BY reference_id LIMIT 50 OFFSET $5""",
            user.user_id, user.wallet, network['program'], network['genesis'], offset)
    tables = []
    for row in rows:
        try:
            state = await builder.lookup_state(row['reference_id'], Pubkey.from_string(user.wallet))
            # Absence alone cannot prove a rent refund. Require the exact
            # owner-only close's finalized receipt before retiring inventory.
            if state == 'missing' and row.get('close_signature') and await builder.finalized_success(row['close_signature']):
                continue
            tables.append({'address': row['reference_id'], 'state': state})
        except ValueError:
            continue  # Never offer cleanup for another authority's account.
    return {'tables': tables, 'next_offset': offset + len(rows) if len(rows) == 50 else None}


@asynccontextmanager
async def proof_connection(action):
    if action in ("self-claim", "claim-transport"):
        pool = await get_pool()
        async with pool.acquire() as connection:
            yield connection
    else:
        yield None


def response_for(action, plan, *, prepared=None, operation=None):
    state = (operation.confirmation_status if operation else "ready")
    result = _prepared_balance_response(
        action_type="stage1_" + action.replace("-", "_"), rider_label="TIM: stage1_" + action.replace("-", "_"),
        asset=plan.asset, amount_base_units=plan.amount, rider_state="TIM: stage1_" + state,
        rider_detail="TIM: stage1_" + state if operation else "TIM: stage1_confirmation",
        next_step="none" if state in ("confirmed", "finalized", "failed", "expired") else "pending" if operation else "sign",
        prepared_transaction=prepared, operation=operation)
    if plan.intent:
        result["intent"] = plan.intent
    return result


@router.get("/me/claims")
async def claims(response: Response, limit: int = Query(10, ge=1, le=10), offset: int = Query(0, ge=0, le=2147483647),
                 user: AuthenticatedUser = Depends(get_current_user), builder=Depends(action_builder)):
    response.headers["Cache-Control"] = "private, no-store"
    result = []
    async with proof_connection("self-claim") as connection:
        rows = await connection.fetch("""SELECT p.job_id,p.role,p.leaf_index,j.week FROM stage1_keeper_proofs p
            JOIN stage1_keeper_jobs j ON j.id=p.job_id JOIN stage1_keeper_scopes s ON s.id=j.scope_id
            WHERE p.person=$1 AND p.paid_slot IS NULL AND j.state='complete' AND NOT j.export_suspended
            AND s.program=$2 AND EXISTS (SELECT 1 FROM stage1_keeper_payout_actions a,
              jsonb_array_elements(a.operation->'refs') ref
              WHERE a.job_id=p.job_id AND a.state='failed'
              AND ref->>'job_id'=p.job_id AND (ref->>'role')::integer=p.role
              AND (ref->>'index')::integer=p.leaf_index)
            ORDER BY j.week,p.job_id,p.role,p.leaf_index LIMIT $3 OFFSET $4""",
            user.wallet, str(builder.program_id), limit, offset)
        # Query eligibility before looking in the cache: paid, suspended or
        # erased proofs disappear immediately when durable truth changes.
        genesis = await connection.fetchval("SELECT genesis FROM stage1_keeper_network")
        if genesis != builder.observed_genesis:
            raise HTTPException(503, "TIM: stage1_actions_unavailable")
        cache_key = (user.wallet, user.user_id, builder.rpc_url, str(builder.program_id), genesis,
                     tuple((r["week"], r["job_id"], r["role"], r["leaf_index"]) for r in rows), limit, offset)
        cached = claim_cache.get(cache_key)
        if cached is not None:
            return cached
        reader = builder.discovery_reader()
        for row in rows:
            reference = {"job_id": row["job_id"], "role": row["role"], "index": row["leaf_index"]}
            try:
                plan = await reader.plan("self-claim", ClaimRequest(claims=[reference]), user.wallet, connection)
            except ValueError:
                continue  # Paid/closed/suspended or mismatched live truth is absent.
            result.append({"reference": reference, "intent": plan.intent, "requires_lookup": builder.requires_lookup(plan)})
    value = {"claims": result, "next_offset": offset + len(rows) if len(rows) == limit else None}
    claim_cache.put(cache_key, value)
    return value


def semantic_intent_key(action, payload):
    # Generated account IDs and transport choices do not change the rider's
    # action. Keep existing lot/request addresses and all economic terms.
    excluded = {'signed_transaction', 'last_valid_block_height', 'client_request_id', 'refresh_rate'}
    if action == 'pledge':
        excluded.add('deposit_id')
    if action == 'withdrawal-notice':
        excluded.add('request_id')
    if action == 'self-claim':
        excluded.add('lookup_table')
    if action == 'claim-transport' and payload.mode == 'create':
        excluded.update({'recent_slot', 'lookup_table'})
    terms = payload.model_dump(exclude=excluded)
    if 'claims' in terms:
        terms['claims'] = sorted(terms['claims'], key=lambda r: (r['job_id'], r['role'], r['index']))
    return hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


async def pending_intent(user, action_type, metadata):
    pool = await get_pool()
    async with pool.acquire() as connection:
        return await connection.fetchrow("""SELECT operation_id,reference_id FROM balance_operations
            WHERE rider_account_id=$1 AND protocol_wallet=$2 AND action_type=$3
            AND metadata->>'program'=$4 AND metadata->>'genesis'=$5 AND metadata->>'intent_key'=$6
            AND confirmation_status IN ('prepared','submitted') LIMIT 1""",
            user.user_id, user.wallet, action_type, metadata['program'], metadata['genesis'], metadata['intent_key'])


async def execute(action, payload, user, builder, response, repo=None):
    response.headers["Cache-Control"] = "private, no-store"
    check_withdrawal_window(action)
    signed = getattr(payload, "signed_transaction", None)
    if signed:
        claim_cache.invalidate_owner(user.wallet)
    try:
        tx = builder.decode_signed_transaction(signed) if signed else None
    except Exception:
        raise HTTPException(400, "TIM: stage1_confirmation_invalid") from None
    action_type = "stage1_" + action.replace("-", "_")
    operation = None
    request_hash = hashlib.sha256(json.dumps(payload.model_dump(exclude={"signed_transaction", "last_valid_block_height", "client_request_id"}), sort_keys=True).encode()).hexdigest()
    if tx is not None:
        if getattr(repo, "client", None) is None:
            raise HTTPException(503, "TIM: stage1_operations_unavailable")
        coordinator = _balance_coordinator(repo)
        identity = hashlib.sha256((user.user_id + action_type + str(tx.signatures[0])).encode()).hexdigest()
        operation = load_record(repo.client, coordinator._derive_operation_id(identity), user.user_id)
        if operation:
            if (operation.protocol_wallet != user.wallet or operation.action_type != action_type
                    or operation.metadata.get("request_hash") != request_hash
                    or operation.metadata.get("signed_hash") != hashlib.sha256(base64.b64decode(signed)).hexdigest()):
                raise HTTPException(400, "TIM: stage1_confirmation_mismatch")
            plan = Stage1Plan([], operation.metadata["mint"], int(operation.amount), operation.source,
                operation.destination, operation.reference_id, operation.metadata["rent_payer"])
            if operation.confirmation_status in ("confirmed", "finalized", "failed", "expired"):
                return response_for(action, plan, operation=operation)
    if operation is None:
        try:
            async with proof_connection(action) as connection:
                plan = await builder.plan(action, payload, user.wallet, connection)
            prepared = await builder.build(plan, blockhash=tx.message.recent_blockhash if tx else None)
            check_withdrawal_window(action)
        except Stage1LookupRequired:
            raise HTTPException(409, {"code": "stage1_lookup_required", "rider_label": "TIM: stage1_lookup_required"}) from None
        except Stage1WithdrawalPaused as exc:
            raise withdrawal_pause_response(exc.retry_at) from None
        except (ValueError, KeyError, TypeError):
            raise HTTPException(409, "TIM: stage1_action_unavailable") from None
        if tx is None:
            return response_for(action, plan, prepared=prepared)
        expected = VersionedTransaction.from_bytes(base64.b64decode(prepared.transaction))
        if builder.message_bytes(tx) != builder.message_bytes(expected):
            raise HTTPException(400, "TIM: stage1_confirmation_mismatch")
    metadata = None
    try:
        if operation is None:
            metadata = {"client_request_id": payload.client_request_id, "mint": plan.asset,
                        "rent_payer": plan.rent_payer, "abi": builder_abi(),
                        "last_valid_block_height": str(payload.last_valid_block_height), "request_hash": request_hash,
                        "recent_blockhash": str(tx.message.recent_blockhash),
                        "signed_hash": hashlib.sha256(base64.b64decode(signed)).hexdigest(),
                        "program": str(builder.program_id), "genesis": await builder.genesis(),
                        "intent_key": semantic_intent_key(action, payload)}
            # Recheck after asynchronous preparation and before ledger insertion.
            check_withdrawal_window(action)
            if action == 'claim-transport':
                metadata['transport_mode'] = payload.mode
            operation = coordinator.prepare_operation(BalanceOperationIntent(
                action_type=action_type, rider_account_id=user.user_id, protocol_wallet=user.wallet,
                authority_model=AuthorityModel.WALLET_BOUNDARY, asset="SOL" if action in ("registration", "claim-transport") else "SPL",
                amount=str(plan.amount), source=plan.source, destination=plan.destination,
                reference_type="stage1", reference_id=plan.reference,
                idempotency_key=identity,
                prepared_message_hash=prepared_message_hash(prepared.transaction), tx_signature=str(tx.signatures[0]),
                fee_payer=str(builder.fee_payer.pubkey()), step_up_satisfied=True,
                metadata=metadata,
            ))
        submission = await submit_confirmed_balance_transaction(builder=builder, coordinator=coordinator,
            operation=operation, transaction_b64=signed, last_valid_block_height=int(operation.metadata["last_valid_block_height"]))
    except Stage1WithdrawalPaused as exc:
        # The signed bytes already have a durable reservation. Keep it pending
        # until receipt/expiry proves the outcome, even though this send stopped.
        return {**response_for(action, plan, operation=operation), 'withdrawals_paused_until': str(exc.retry_at)}
    except BalanceOperationError:
        # A partial UNIQUE index arbitrates concurrent tabs before any send.
        # Only a persisted terminal outcome frees it; no wall-clock timeout.
        try:
            existing = await pending_intent(user, action_type, metadata) if metadata else None
        except Exception:
            existing = None
        if existing:
            raise HTTPException(409, {'code': 'stage1_operation_pending', **dict(existing)}) from None
        raise HTTPException(503, "TIM: stage1_operations_unavailable") from None
    except BalanceSubmissionError as exc:
        # Include the durable operation so the existing owner-only operation
        # read can reconcile even when the response to send/confirm was lost.
        return response_for(action, plan, operation=exc.operation)
    operation = coordinator.mark_projection_recorded(submission.operation)
    return response_for(action, plan, operation=operation)


def withdrawal_pause_response(retry_at):
    return HTTPException(409, {'code': 'stage1_withdrawal_paused', 'retry_at': str(retry_at)})


def check_withdrawal_window(action):
    try:
        require_withdrawal_window(action)
    except Stage1WithdrawalPaused as exc:
        raise withdrawal_pause_response(exc.retry_at) from None


def builder_abi():
    from ..services.stage1_transactions import ABI
    return ABI


def add_action(action, request_model):
    submit_model = create_model("Stage1" + action.title().replace("-", "") + "Submit", __base__=request_model,
        signed_transaction=(Annotated[str, StringConstraints(min_length=1, max_length=1800)], ...),
        last_valid_block_height=(Annotated[int, Field(gt=0)], ...),
        client_request_id=(Annotated[str, StringConstraints(min_length=1, max_length=120)], ...))

    async def prepare(payload, response: Response, user: AuthenticatedUser = Depends(get_current_user), builder=Depends(action_builder)):
        return await execute(action, payload, user, builder, response)

    async def submit(payload, response: Response, user: AuthenticatedUser = Depends(get_current_user), builder=Depends(action_builder), repo=Depends(get_repository)):
        return await execute(action, payload, user, builder, response, repo)

    # Set concrete models before FastAPI inspects the endpoints. Each action has
    # its own closed request schema; wallet/recipient/extra keys are rejected.
    prepare.__annotations__["payload"] = request_model
    submit.__annotations__["payload"] = submit_model
    router.add_api_route(f"/me/{action}/prepare", prepare, methods=["POST"], name=f"prepare_stage1_{action}")
    router.add_api_route(f"/me/{action}", submit, methods=["POST"], name=f"submit_stage1_{action}")


for _action, _model in (
    ("cancel-pledge", CancelPledgeRequest), ("registration", ActionRequest), ("self-claim", ClaimRequest), ("claim-transport", TransportRequest), ("pledge", PledgeRequest),
    ("withdrawal-notice", NoticeRequest), ("cancel-notice", WithdrawalRequest),
    ("begin-withdrawal", WithdrawalRequest), ("complete-withdrawal", WithdrawalRequest), ("convert-pledge", ConvertRequest),
):
    add_action(_action, _model)

# Bounded, brief process-local reuse; the shared rate limiter also protects
# across workers. In-flight requests for one owner/lot share one simulation.
eligibility_cache = OrderedDict()
eligibility_inflight = {}


def with_withdrawal_window(result):
    # Recheck cached and shared in-flight results at response time as well.
    retry_at = withdrawal_pause_until(time.time())
    if retry_at is None:
        return result
    return {**result, 'withdrawals_paused_until': str(retry_at), 'actions': {
        action: value for action, value in result['actions'].items()
        if action not in ('begin-withdrawal', 'complete-withdrawal')}}


class EligibilityRequest(ActionRequest):
    lot: Address


@router.post('/me/eligibility')
async def eligibility(payload: EligibilityRequest, response: Response,
                      user: AuthenticatedUser = Depends(get_current_user), builder=Depends(action_read_builder)):
    response.headers['Cache-Control'] = 'private, no-store'
    cache_key = (str(builder.program_id), user.user_id, user.wallet, payload.lot)
    cached = eligibility_cache.get(cache_key)
    if cached and time.monotonic() < cached[0]:
        return with_withdrawal_window(cached[1])
    if cache_key in eligibility_inflight:
        return with_withdrawal_window(await asyncio.shield(eligibility_inflight[cache_key]))
    await limit_read(user, 'eligibility')
    # A second call can reach this point while the shared limiter awaits I/O.
    if cache_key in eligibility_inflight:
        return with_withdrawal_window(await asyncio.shield(eligibility_inflight[cache_key]))
    async def compute():
        result, week_end = await simulate_eligibility(payload, user, builder)
        # Never reuse a pre-Monday week after its boundary, even within 15s.
        now = time.time()
        pause_end = withdrawal_pause_until(now)
        ttl = max(0, min(15, week_end - now, pause_end - now if pause_end else 15))
        eligibility_cache[cache_key] = (time.monotonic() + ttl, result)
        eligibility_cache.move_to_end(cache_key)
        while len(eligibility_cache) > 256:
            eligibility_cache.popitem(last=False)
        return result
    task = asyncio.create_task(compute())
    eligibility_inflight[cache_key] = task
    try:
        return with_withdrawal_window(await asyncio.shield(task))
    finally:
        if task.done():
            eligibility_inflight.pop(cache_key, None)
        else:
            task.add_done_callback(lambda _: eligibility_inflight.pop(cache_key, None))


async def simulate_eligibility(payload, user, builder):
    """Unsigned on-demand simulation with one finalized clock for due/week truth."""
    try:
        lot = await builder.account(Pubkey.from_string(payload.lot), 'Stage1PledgeLot')
        if lot['owner'] != user.wallet:
            raise ValueError('Owner mismatch')
        now = await builder.clock()
        city = await builder.account(builder.pda('s1v1_city'), 'Stage1CityConfig')
        week = (now - city['season_anchor']) // 604800
        if week < 0:
            raise ValueError('Season not started')
        result = {}
        for action in ('convert-pledge', 'begin-withdrawal', 'complete-withdrawal'):
            if action == 'convert-pledge':
                candidates = [ConvertRequest(lot=payload.lot, lock_weeks=0, refresh_rate=refresh) for refresh in (True, False)]
            else:
                request = lot.get('exit_request' if action == 'complete-withdrawal' else 'pending_request')
                if not request or request == str(Pubkey.default()):
                    continue
                candidates = [WithdrawalRequest(lot=payload.lot, request=request, refresh_rate=refresh) for refresh in (True, False)]
            for candidate in candidates:
                try:
                    plan = await builder.plan(action, candidate, user.wallet, chain_time=now)
                    if await builder.simulate(plan):
                        result[action] = {'refresh_rate': candidate.refresh_rate}
                        break
                except (ValueError, KeyError):
                    continue
        return {'actions': result, 'chain_time': str(now), 'week': str(week)}, city['season_anchor'] + (week+1)*604800
    except ValueError:
        raise HTTPException(409, 'TIM: stage1_action_unavailable') from None
