"""Settlement Week DUNG conservation gate.

The current week's locked staker base is policy-reallocated to Record Royalty
before either bucket allocates. All stored carry remains typed: prior staker
carry is already-unlocked pro-rata dust and is never passed through the curve
again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ._alignment_helpers import anchor_program_source


REPO_ROOT = Path(__file__).resolve().parents[4]

DEFAULT_CONFIG = {
    "record_royalty": 5500,
    "stakers": 2700,
    "local_legend": 300,
    "pol": 500,
    "treasury": 1000,
}


@dataclass(frozen=True)
class BucketSettlement:
    name: str
    incoming: int
    allocations: tuple[int, ...]
    carry_out: int

    def assert_conserved(self) -> None:
        assert self.incoming == sum(self.allocations) + self.carry_out, (
            f"{self.name} leaked or borrowed DUNG: incoming={self.incoming}, "
            f"allocations={self.allocations}, carry_out={self.carry_out}"
        )


def _rust_array(name: str) -> list[int]:
    source = anchor_program_source()
    match = re.search(rf"pub const {name}:\s*\[u8;\s*\d+\]\s*=\s*\[([^\]]+)\];", source)
    assert match, f"missing {name} in Anchor source"
    return [int(part.strip()) for part in match.group(1).split(",") if part.strip()]


def _base_buckets(total_dung: int, config: dict[str, int] = DEFAULT_CONFIG) -> dict[str, int]:
    stakers = total_dung * config["stakers"] // 10_000
    local_legend = total_dung * config["local_legend"] // 10_000
    pol = total_dung * config["pol"] // 10_000
    treasury = total_dung * config["treasury"] // 10_000

    # Anchor assigns BPS floor dust to Record Royalty, then normal bucket carry
    # handles quiet-hill / partial-recipient cases without global leakage.
    record_royalty = total_dung - stakers - local_legend - pol - treasury
    return {
        "record_royalty": record_royalty,
        "stakers": stakers,
        "local_legend": local_legend,
        "pol": pol,
        "treasury": treasury,
    }


def _record_royalty_bucket(total: int, leaderboard_entries: int) -> BucketSettlement:
    rank_pcts = _rust_array("LEADERBOARD_RANK_PCTS")
    num_entries = min(leaderboard_entries, len(rank_pcts))
    if total <= 0 or num_entries == 0:
        allocations: tuple[int, ...] = ()
    else:
        pct_sum = sum(rank_pcts[:num_entries])
        allocations = tuple(total * pct // pct_sum for pct in rank_pcts[:num_entries])
    return BucketSettlement(
        name="record_royalty",
        incoming=total,
        allocations=allocations,
        carry_out=total - sum(allocations),
    )


def _staker_bucket(
    base_stakers: int,
    prior_unlocked_dust: int,
    settlement_week: int,
    stakers: tuple[dict[str, int], ...],
) -> tuple[BucketSettlement, int]:
    unlock_pcts = _rust_array("STAKER_UNLOCK_PCTS")
    eligible = tuple(
        staker
        for staker in stakers
        if staker["lp_tokens"] > 0 and staker["eligible_from_week"] <= settlement_week
    )
    unlock_pct = (
        0
        if not eligible
        else 100
        if len(eligible) >= len(unlock_pcts)
        else unlock_pcts[len(eligible) - 1]
    )
    unlock_bps = unlock_pct * 100
    weekly_unlocked = base_stakers * unlock_bps // 10_000
    locked_staker_amount = base_stakers - weekly_unlocked
    staker_distributable = weekly_unlocked + prior_unlocked_dust

    if staker_distributable <= 0 or not eligible:
        allocations: tuple[int, ...] = ()
    else:
        total_lp = sum(staker["lp_tokens"] for staker in eligible)
        allocations = tuple(
            staker_distributable * staker["lp_tokens"] // total_lp
            for staker in eligible
        )

    settlement = BucketSettlement(
        "stakers",
        staker_distributable,
        allocations,
        staker_distributable - sum(allocations),
    )
    return settlement, locked_staker_amount


def _single_recipient_bucket(name: str, total: int, active: bool) -> BucketSettlement:
    allocations = (total,) if active and total > 0 else ()
    return BucketSettlement(name, total, allocations, total - sum(allocations))


def _settle(
    *,
    pending_dung: int,
    carry_in: dict[str, int],
    leaderboard_entries: int,
    stakers: tuple[dict[str, int], ...],
    legend_active: bool,
    settlement_week: int = 10,
) -> dict[str, BucketSettlement]:
    base = _base_buckets(pending_dung)
    staker_settlement, locked_staker_amount = _staker_bucket(
        base["stakers"],
        carry_in.get("stakers", 0),
        settlement_week,
        stakers,
    )
    record_royalty_total = (
        base["record_royalty"]
        + carry_in.get("record_royalty", 0)
        + locked_staker_amount
    )
    local_legend_total = base["local_legend"] + carry_in.get("local_legend", 0)
    pol_total = base["pol"] + carry_in.get("pol", 0)
    treasury_total = base["treasury"] + carry_in.get("treasury", 0)
    return {
        "record_royalty": _record_royalty_bucket(record_royalty_total, leaderboard_entries),
        "stakers": staker_settlement,
        "local_legend": _single_recipient_bucket(
            "local_legend",
            local_legend_total,
            legend_active,
        ),
        "pol": _single_recipient_bucket("pol", pol_total, True),
        "treasury": _single_recipient_bucket("treasury", treasury_total, True),
    }


def _assert_all_buckets_conserve(settlement: dict[str, BucketSettlement]) -> None:
    expected = {"record_royalty", "stakers", "local_legend", "pol", "treasury"}
    assert set(settlement) == expected
    for bucket in settlement.values():
        bucket.assert_conserved()

    total_in = sum(bucket.incoming for bucket in settlement.values())
    total_out = sum(sum(bucket.allocations) + bucket.carry_out for bucket in settlement.values())
    assert total_in == total_out


def test_anchor_base_split_assigns_bps_floor_dust_to_record_royalty() -> None:
    """Base split dust is assigned before bucket-local carry logic runs."""
    source = anchor_program_source()
    assert "let allocated = shares.total()?;" in source
    assert "let dust = total_dung" in source
    assert ".checked_sub(allocated)" in source
    assert (
        "shares.record_royalty = checked_sum_u64([shares.record_royalty, dust])?;"
        in source
    )

    base = _base_buckets(10_001)
    naive_record_floor = 10_001 * DEFAULT_CONFIG["record_royalty"] // 10_000
    assert sum(base.values()) == 10_001
    assert base["record_royalty"] == naive_record_floor + 1


def test_quiet_hill_carries_empty_community_buckets_without_leakage() -> None:
    """No board/stakers: current locked base moves to RR; prior dust stays typed."""
    carry_in = {
        "record_royalty": 7,
        "stakers": 11,
        "local_legend": 13,
        "pol": 17,
        "treasury": 19,
    }
    settlement = _settle(
        pending_dung=10_001,
        carry_in=carry_in,
        leaderboard_entries=0,
        stakers=(),
        legend_active=False,
    )

    _assert_all_buckets_conserve(settlement)
    assert settlement["record_royalty"].allocations == ()
    assert settlement["record_royalty"].carry_out == settlement["record_royalty"].incoming
    assert settlement["stakers"].allocations == ()
    assert settlement["stakers"].incoming == carry_in["stakers"]
    assert settlement["stakers"].carry_out == carry_in["stakers"]
    base = _base_buckets(10_001)
    assert settlement["record_royalty"].incoming == (
        base["record_royalty"] + carry_in["record_royalty"] + base["stakers"]
    )
    assert settlement["local_legend"].allocations == ()
    assert settlement["local_legend"].carry_out == settlement["local_legend"].incoming
    assert settlement["pol"].carry_out == 0
    assert settlement["treasury"].carry_out == 0


def test_partial_recipient_settlement_carries_only_unlocked_staker_dust() -> None:
    """Current locked base moves to RR; only pro-rata staker dust carries."""
    carry_in = {
        "record_royalty": 101,
        "stakers": 103,
        "local_legend": 107,
        "pol": 109,
        "treasury": 113,
    }
    settlement = _settle(
        pending_dung=1_234_567,
        carry_in=carry_in,
        leaderboard_entries=3,
        stakers=(
            {"lp_tokens": 333, "eligible_from_week": 8},
            {"lp_tokens": 667, "eligible_from_week": 9},
            {"lp_tokens": 5_000, "eligible_from_week": 11},
        ),
        legend_active=True,
        settlement_week=10,
    )

    _assert_all_buckets_conserve(settlement)
    assert len(settlement["record_royalty"].allocations) == 3
    assert len(settlement["stakers"].allocations) == 2
    assert settlement["stakers"].carry_out == (
        settlement["stakers"].incoming - sum(settlement["stakers"].allocations)
    )
    assert settlement["stakers"].carry_out < len(settlement["stakers"].allocations)
    base = _base_buckets(1_234_567)
    weekly_unlocked = base["stakers"] * 300 // 10_000
    locked_staker_amount = base["stakers"] - weekly_unlocked
    assert settlement["stakers"].incoming == weekly_unlocked + carry_in["stakers"]
    assert settlement["record_royalty"].incoming == (
        base["record_royalty"]
        + carry_in["record_royalty"]
        + locked_staker_amount
    )
    assert settlement["local_legend"].carry_out == 0
    assert settlement["pol"].carry_out == 0
    assert settlement["treasury"].carry_out == 0
