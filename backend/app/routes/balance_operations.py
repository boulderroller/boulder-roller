"""Authenticated rider-safe reads for durable Balance operations."""

from __future__ import annotations

import asyncio
from dataclasses import asdict

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository
from ..services.balance_operation_status import SupabaseBalanceOperationReader


router = APIRouter()


class RiderBalanceOperationResponse(BaseModel):
    """The deliberate rider boundary; support and chain fields stay private."""

    operation_id: str
    action_type: str
    asset: str
    amount: str
    reference_type: Optional[str]
    reference_id: Optional[str]
    rider_state: Optional[str]
    read_state: str
    pending: bool
    delayed: bool
    needs_review: bool
    recorded: bool
    stage1_terminal_failure: Optional[bool] = None


def _rider_response(operation) -> RiderBalanceOperationResponse:
    data = asdict(operation.rider)
    if operation.support.action_type.startswith('stage1_'):
        data['stage1_terminal_failure'] = operation.support.confirmation_status in ('failed', 'expired')
    return RiderBalanceOperationResponse(**data)


@router.get("/lookup", response_model=RiderBalanceOperationResponse, response_model_exclude_unset=True)
async def lookup_balance_operation(
    client_request_id: str = Query(..., min_length=1, max_length=120),
    reference_type: str = Query(..., min_length=1, max_length=40),
    reference_id: str = Query(..., min_length=1, max_length=120),
    action_type: str = Query(..., min_length=1, max_length=40),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> RiderBalanceOperationResponse:
    operation = await asyncio.to_thread(
        SupabaseBalanceOperationReader(repo.client).find_for_rider,
        current_user.user_id,
        client_request_id=client_request_id,
        reference_type=reference_type,
        reference_id=reference_id,
        action_type=action_type,
    )
    if operation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found")
    from ..services.stage1_operation_status import reconcile_stage1_operation
    operation = await reconcile_stage1_operation(operation, repo.client)
    return _rider_response(operation)


@router.get("/{operation_id}", response_model=RiderBalanceOperationResponse, response_model_exclude_unset=True)
async def get_balance_operation(
    operation_id: str = Path(..., min_length=1, max_length=160),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> RiderBalanceOperationResponse:
    operation = await asyncio.to_thread(
        SupabaseBalanceOperationReader(repo.client).get_for_rider,
        operation_id,
        rider_account_id=current_user.user_id,
    )
    if operation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operation not found")
    from ..services.stage1_operation_status import reconcile_stage1_operation
    operation = await reconcile_stage1_operation(operation, repo.client)
    return _rider_response(operation)
