"""
CAL Token Routes - CAL balance queries.

Reads from the user's SPL CAL ATA on devnet.
"""

from ..services.privacy_logging import scrub_log_text
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository
from ..token_amounts import base_units_to_units, parse_base_units

router = APIRouter()
logger = logging.getLogger(__name__)


class CalOnchainResponse(BaseModel):
    calBalance: str
    calBalanceBaseUnits: str
    canMintToday: bool = False


@router.get("/onchain", response_model=CalOnchainResponse)
async def get_cal_onchain(
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get user's CAL balance from on-chain SPL ATA.
    """
    from ..solana_direct import get_cal_balance_base_units

    try:
        cal_balance_base_units = parse_base_units(
            await get_cal_balance_base_units(current_user.wallet),
            field_name="cal_balance_base_units",
        )
    except Exception as e:
        logger.warning(f"Failed to read SPL CAL for {current_user.user_id}: {scrub_log_text(e)}")
        cal_balance_base_units = 0

    return CalOnchainResponse(
        calBalance=base_units_to_units(cal_balance_base_units),
        calBalanceBaseUnits=str(cal_balance_base_units),
        canMintToday=False,
    )
