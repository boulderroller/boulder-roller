"""Outcome checks for the sourced conversation numbers, not a second money model."""
from fractions import Fraction
from hashlib import sha256
import json

import pytest

from tools.conversations.build import OUTPUT, ROOT, documents, encode, exact, stage1_case
from tools.economy_reference.config import load_config as economy_config
from tools.economy_reference.simulation import run
from tools.economy_reference.tournament import compact
from tools.stage1_reference.arithmetic import apportion
from tools.stage1_reference.config import load_config


@pytest.fixture(scope="module")
def numbers():
    return json.loads((OUTPUT / "numbers.json").read_text())


def test_main_figures_and_all_sensitivity_inputs(numbers):
    assert len(numbers["scenarios"]) == 6
    assert {exact(s["sol_usd"]) for s in numbers["scenarios"]} == {Fraction("60.37"), Fraction("120.74"), Fraction(200)}
    base = next(r for r in numbers["club"]["budgets"] if r["stake_sol"] == 500 and r["scenario"] == "120.74_0.052")
    assert exact(base["week"]["rider_sol"]) == Fraction("0.4275")
    assert exact(base["week"]["rider_usd"]) == Fraction("51.61635")
    assert exact(base["season"]["rider_usd"]) == Fraction("1342.0251")
    bound = next(r for r in numbers["validator"]["million_bound"] if r["scenario"] == "120.74_0.052")
    assert exact(bound["required_stake_usd"]) * Fraction("0.04446") == 1_000_000
    assert numbers["whale"]["pilot"]["total_basis_sol"] == 5000
    assert numbers["whale"]["pilot"]["minimum_token_count"] == 3


def test_integer_stage1_funding_and_field(numbers):
    config = load_config()
    for row in numbers["club"]["model_cases"]:
        paid = sum(w["claimable_units"] for w in row["weeks"])
        assert paid + row["fee_units"] + row["held_units"] == row["realized_units"]
        for week in row["weeks"]:
            assert sum(week["leaves"].values()) == week["claimable_units"]
            assert max(week["leaves"].values(), default=0) <= week["cap_units"]
        if row["people"] >= config.field:
            assert row["held_units"] == 0
            assert exact(row["backer_dung"]) == Fraction(row["ascents"] * 6 * 26, 2000)
        else:
            assert exact(row["backer_dung"]) == 0
            assert row["held_units"] > 0
    # Outcome probe exercises the untouched model, including its lifetime fee.
    probe = stage1_case(10, Fraction("0.052"), 25, weeks=1)
    week = probe["weeks"][0]
    assert week["bucket_units"] == apportion(week["harvest_units"] - week["fee_units"], config.split)
    assert exact(probe["rider_sol_at_harvest"]) == pytest.approx(.00855, abs=2e-9)
    saved = next(r for r in numbers["club"]["model_cases"] if r["stake_sol"] == 10 and exact(r["gross_apr"]) == Fraction("0.052") and r["ascents"] == 25 and r["people"] == 5)
    assert saved["weeks"][0] == encode(week)


def test_sponsor_escrow_and_no_tail(numbers):
    for row in numbers["sponsor"]["boosts"]:
        assert sum(x["usdc_units"] for x in row["schedule"]) == row["budget_usdc"] * 10**6
        assert len({x["ride_week"] for x in row["schedule"]}) == row["duration_weeks"]
        assert row["protocol_fee_usdc_units"] == row["backer_dung_units"] == 0
        assert row["funded_tail_weeks"] == 0
    for row in numbers["sponsor"]["season_schedules"]:
        assert len(row["schedule"]) == 26 * row["hills"]
        assert sum(x["usdc_units"] for x in row["schedule"]) == row["budget_usdc"] * 10**6


def test_market_results_preserve_money_and_pilot_boundary(numbers):
    for row in numbers["whale"]["tournament"]:
        result = row["result"]
        assert result["scenario"]["immediate_cal_sale"] is True
        assert result["scenario"]["hardened_ladder"] is True
        assert result["P1"] and result["P2_cash"]
        for ledger in result["vault"].values():
            assert ledger["income"] == pytest.approx(ledger["fees"] + ledger["paid"] + ledger["held"], abs=1e-6)
    target = numbers["whale"]["honest_500_tournament"][0]
    assert target["result"]["principal_committed_sol"]["whale"] == 5000
    assert target["result"]["principal_committed_sol"]["community"] == 100
    assert target["pilot_admissible"] is False
    control = numbers["whale"]["controls"][0]["unfunded_trader"]
    assert control["whale_profit_usd"] > 0
    assert control["whale_rider_pay_usd"] == 0
    assert control["late_buyer_liquidation_pnl_usd"] < 0
    witness = next(r for r in numbers["whale"]["tournament"] if r["scenario"] == "60.37_0.022" and r["condition"] == "thin_high_demand" and r["strategy"] == "livermore_corner")
    assert witness["result"] == compact(run(economy_config(), "livermore_corner", witness["result"]["scenario"]))
    assert witness["result"]["totals"]["whale"]["economic_cash_usd"] > 0
    assert witness["result"]["whale_rider_pay_usd"]["regulars"] > 0


def test_sources_and_rendered_pages_match(numbers):
    for source in numbers["source_manifest"].values():
        assert sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]
    for filename, content in documents(numbers).items():
        assert (OUTPUT / filename).read_text() == content
