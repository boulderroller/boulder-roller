from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.repositories import SupabaseRepository, TokenRepository
from app.token_amounts import units_to_base_units


class TokenBalanceClient:
    def __init__(self) -> None:
        self.table_name = ""

    def table(self, table_name: str) -> "TokenBalanceClient":
        self.table_name = table_name
        return self

    def select(self, *_args: Any, **_kwargs: Any) -> "TokenBalanceClient":
        return self

    def eq(self, *_args: Any, **_kwargs: Any) -> "TokenBalanceClient":
        return self

    def in_(self, *_args: Any, **_kwargs: Any) -> "TokenBalanceClient":
        return self

    def execute(self) -> SimpleNamespace:
        if self.table_name == "rides":
            return SimpleNamespace(data=[])
        if self.table_name == "proofs":
            return SimpleNamespace(data=[{"id": "proof-1"}])
        if self.table_name == "mint_events":
            return SimpleNamespace(
                data=[
                    {"proof_id": "proof-1", "amount": "0.1"},
                    {"proof_id": "proof-1", "amount": Decimal("0.2")},
                    {"proof_id": "proof-1", "amount": "0.000000001"},
                ]
            )
        return SimpleNamespace(data=[])


@pytest.mark.parametrize("repository_type", [TokenRepository, SupabaseRepository])
@pytest.mark.asyncio
async def test_dung_aggregation_preserves_decimal_dust(repository_type: type) -> None:
    repo = repository_type(TokenBalanceClient())

    async def run_sync(func: Any, operation: str = "supabase") -> Any:
        return func()

    repo._run = run_sync  # type: ignore[method-assign]
    balances = await repo.get_token_balances("user-1")

    assert balances["dung"] == Decimal("0.300000001")
    assert units_to_base_units(balances["dung"]) == 300_000_001
