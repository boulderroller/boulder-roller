from __future__ import annotations

from decimal import Decimal

import pytest

from app.token_amounts import (
    TokenAmountError,
    U64_MAX,
    base_units_to_units,
    fee_split_base_units,
    parse_base_units,
    require_base_units_string,
    units_to_base_units,
)


def test_base_units_stay_exact_above_javascript_safe_integer() -> None:
    value = "9007199254740993"

    assert require_base_units_string(value) == value
    assert parse_base_units(value) == 9_007_199_254_740_993


def test_nine_decimal_units_round_trip_exactly() -> None:
    assert units_to_base_units("340") == 340_000_000_000
    assert units_to_base_units("0.000000001") == 1
    assert base_units_to_units("9007199254740993") == "9007199.254740993"


def test_fee_split_matches_protocol_floor_math() -> None:
    fee, net = fee_split_base_units("1001", Decimal("500"))

    assert fee == 50
    assert net == 951


@pytest.mark.parametrize(
    "value",
    [1.0, True, "1.1", "-1", "1e3", str(U64_MAX + 1)],
)
def test_base_unit_parser_rejects_inexact_or_out_of_range_values(value: object) -> None:
    with pytest.raises(TokenAmountError):
        parse_base_units(value)


def test_api_base_units_require_a_string() -> None:
    with pytest.raises(TokenAmountError):
        require_base_units_string(9_007_199_254_740_993)


def test_overlong_inputs_fail_before_unbounded_integer_parsing() -> None:
    overlong = "9" * 10_000

    with pytest.raises(TokenAmountError, match="u64 range"):
        parse_base_units(overlong)
    with pytest.raises(TokenAmountError, match="u64 range"):
        units_to_base_units(overlong)
