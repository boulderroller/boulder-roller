"""Exact token amount parsing and formatting for API boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any


U64_MAX = (1 << 64) - 1
U64_MAX_TEXT = str(U64_MAX)
TOKEN_DECIMALS = 9
_BASE_UNITS_RE = re.compile(r"^[0-9]+$")
_TOKEN_UNITS_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


class TokenAmountError(ValueError):
    """Raised when a token amount cannot be represented exactly."""


@dataclass(frozen=True)
class ExactTokenAmount:
    units: str
    base_units: str


def parse_base_units(
    value: Any,
    *,
    field_name: str = "amount_base_units",
    allow_zero: bool = True,
) -> int:
    """Parse an integer token amount without accepting binary floats."""
    if isinstance(value, bool) or isinstance(value, float):
        raise TokenAmountError(f"{field_name} must be an exact integer")

    if isinstance(value, int):
        amount = value
    elif isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise TokenAmountError(f"{field_name} must be an exact integer")
        amount = int(value)
    elif isinstance(value, str):
        normalized = value.strip()
        if not _BASE_UNITS_RE.fullmatch(normalized):
            raise TokenAmountError(f"{field_name} must contain decimal digits only")
        significant = normalized.lstrip("0") or "0"
        if len(significant) > len(U64_MAX_TEXT) or (
            len(significant) == len(U64_MAX_TEXT) and significant > U64_MAX_TEXT
        ):
            raise TokenAmountError(f"{field_name} exceeds the on-chain u64 range")
        amount = int(normalized)
    else:
        raise TokenAmountError(f"{field_name} must be an integer or decimal string")

    if amount < 0 or (amount == 0 and not allow_zero):
        qualifier = "greater than zero" if not allow_zero else "non-negative"
        raise TokenAmountError(f"{field_name} must be {qualifier}")
    if amount > U64_MAX:
        raise TokenAmountError(f"{field_name} exceeds the on-chain u64 range")
    return amount


def require_base_units_string(
    value: Any,
    *,
    field_name: str = "amount_base_units",
    allow_zero: bool = True,
) -> str:
    """Validate that an API supplied base-unit amount is a decimal string."""
    if not isinstance(value, str):
        raise TokenAmountError(f"{field_name} must be a decimal string")
    return str(
        parse_base_units(
            value,
            field_name=field_name,
            allow_zero=allow_zero,
        )
    )


def units_to_base_units(
    value: Any,
    *,
    decimals: int = TOKEN_DECIMALS,
    field_name: str = "amount",
) -> int:
    """Convert an exact human-unit decimal to integer token base units."""
    if decimals < 0:
        raise TokenAmountError("decimals must be non-negative")
    if isinstance(value, bool) or isinstance(value, float):
        raise TokenAmountError(f"{field_name} must be an exact decimal")

    if isinstance(value, int):
        normalized = str(value)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise TokenAmountError(f"{field_name} must be finite")
        normalized = format(value, "f")
    elif isinstance(value, str):
        normalized = value.strip()
    else:
        raise TokenAmountError(f"{field_name} must be a decimal string")

    if not _TOKEN_UNITS_RE.fullmatch(normalized):
        raise TokenAmountError(f"{field_name} must be a non-negative decimal")
    whole, _, fraction = normalized.partition(".")
    if len(fraction) > decimals:
        raise TokenAmountError(f"{field_name} has more than {decimals} decimal places")
    padded_fraction = fraction.ljust(decimals, "0")
    raw_text = (whole + padded_fraction).lstrip("0") or "0"
    if len(raw_text) > len(U64_MAX_TEXT) or (
        len(raw_text) == len(U64_MAX_TEXT) and raw_text > U64_MAX_TEXT
    ):
        raise TokenAmountError(f"{field_name}_base_units exceeds the on-chain u64 range")
    raw = int(raw_text)
    return parse_base_units(raw, field_name=f"{field_name}_base_units")


def base_units_to_units(
    value: Any,
    *,
    decimals: int = TOKEN_DECIMALS,
    field_name: str = "amount_base_units",
) -> str:
    """Format integer token base units as an exact human-unit decimal."""
    if decimals < 0:
        raise TokenAmountError("decimals must be non-negative")
    amount = parse_base_units(value, field_name=field_name)
    if decimals == 0:
        return str(amount)
    scale = 10**decimals
    whole, fraction = divmod(amount, scale)
    if fraction == 0:
        return str(whole)
    return f"{whole}.{fraction:0{decimals}d}".rstrip("0")


def exact_token_amount(
    value: Any,
    *,
    decimals: int = TOKEN_DECIMALS,
    field_name: str = "amount_base_units",
) -> ExactTokenAmount:
    amount = parse_base_units(value, field_name=field_name)
    return ExactTokenAmount(
        units=base_units_to_units(amount, decimals=decimals, field_name=field_name),
        base_units=str(amount),
    )


def fee_split_base_units(total: Any, fee_bps: Any) -> tuple[int, int]:
    """Match the protocol's checked floor(total * bps / 10_000) split."""
    total_amount = parse_base_units(total, field_name="total_base_units")
    if isinstance(fee_bps, bool) or isinstance(fee_bps, float):
        raise TokenAmountError("fee_bps must be an exact integer")
    try:
        bps_decimal = Decimal(str(fee_bps))
    except (InvalidOperation, ValueError) as exc:
        raise TokenAmountError("fee_bps must be an exact integer") from exc
    if not bps_decimal.is_finite() or bps_decimal != bps_decimal.to_integral_value():
        raise TokenAmountError("fee_bps must be an exact integer")
    bps = int(bps_decimal)
    if bps < 0 or bps > 10_000:
        raise TokenAmountError("fee_bps must be between 0 and 10000")
    fee = total_amount * bps // 10_000
    return fee, total_amount - fee
