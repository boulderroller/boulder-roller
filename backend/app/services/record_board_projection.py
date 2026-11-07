"""Pure projection helpers for the on-chain Record Board."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from solders.pubkey import Pubkey


def _wallet_sort_key(value: Any) -> tuple[int, bytes]:
    wallet = str(value or "")
    try:
        return (0, bytes(Pubkey.from_string(wallet)))
    except ValueError:
        return (1, wallet.encode("utf-8"))


def project_competition_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Attach occupied position and standard-competition tie rank metadata."""
    projected = [dict(entry) for entry in entries]
    projected.sort(
        key=lambda entry: (
            int(entry.get("time_s") or 0),
            int(entry.get("recorded_at") or 0),
            _wallet_sort_key(entry.get("user")),
        )
    )
    projected = projected[:limit]

    group_start = 0
    while group_start < len(projected):
        group_time = int(projected[group_start].get("time_s") or 0)
        group_end = group_start + 1
        while (
            group_end < len(projected)
            and int(projected[group_end].get("time_s") or 0) == group_time
        ):
            group_end += 1

        tie_size = group_end - group_start
        for index in range(group_start, group_end):
            projected[index]["position"] = index + 1
            projected[index]["rank"] = group_start + 1
            projected[index]["tie_size"] = tie_size
            projected[index]["is_tied"] = tie_size > 1
        group_start = group_end

    return projected
