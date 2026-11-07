import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request, status

from .. import solana_direct
from ..dependencies import (
    AuthenticatedUser,
    get_current_user,
    get_repository,
)
from ..repositories import DatabaseRepository
from ..schemas import TokenBalanceResponse
from ..token_amounts import base_units_to_units

router = APIRouter()


@router.get("", response_model=TokenBalanceResponse)
async def token_balances(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> TokenBalanceResponse:
    """Compatibility token balance endpoint still used by native clients."""
    balances_task = asyncio.create_task(repo.get_token_balances(current_user.user_id))
    try:
        dung_source = await solana_direct.get_wallet_dung_balance_source(current_user.wallet)
    except Exception as exc:
        balances_task.cancel()
        await asyncio.gather(balances_task, return_exceptions=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Live DUNG balance is unavailable.",
        ) from exc
    balances = await balances_task
    dung_base_units = dung_source.amount_base_units
    return TokenBalanceResponse(
        dung=base_units_to_units(dung_base_units),
        dung_base_units=str(dung_base_units),
        dung_source="spl_wallet_ata",
        dung_status=dung_source.status,
        dung_token_account=dung_source.token_account,
        dung_slot=dung_source.slot,
        kcal=float(balances.get("kcal") or 0),
    )
