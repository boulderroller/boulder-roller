"""Exact integer guards for values encoded by the Anchor ride instructions."""

from __future__ import annotations

from numbers import Integral
from typing import Any

U8_MAX = 2**8 - 1
U16_MAX = 2**16 - 1
U32_MAX = 2**32 - 1
U64_MAX = 2**64 - 1
U128_MAX = 2**128 - 1
I64_MIN = -(2**63)
I64_MAX = 2**63 - 1


def exact_uint(value: Any, *, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{field} must be an integer")
    parsed = int(value)
    if parsed < 0 or parsed > maximum:
        raise ValueError(f"{field} must be between 0 and {maximum}")
    return parsed


def exact_positive_uint(value: Any, *, field: str, maximum: int) -> int:
    parsed = exact_uint(value, field=field, maximum=maximum)
    if parsed == 0:
        raise ValueError(f"{field} must be positive")
    return parsed


def exact_i64(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{field} must be an integer")
    parsed = int(value)
    if parsed < I64_MIN or parsed > I64_MAX:
        raise ValueError(f"{field} must fit signed 64-bit integer")
    return parsed
