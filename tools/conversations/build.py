"""Regenerate the four-conversation numbers using only the admitted offline sources.

Run from the repository root with Python 3.12 and stage1_reference/requirements.txt:
    python -m tools.conversations.build
    python -m pytest tools/conversations/test_build.py -q

Exact quantities carry a rational value and a rounded decimal for display. Market
simulation floats retain the reference model's precision. No network calls.
"""
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
from decimal import Decimal, localcontext
from fractions import Fraction
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import argparse
import json
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.stage1_reference.arithmetic import apportion
from tools.stage1_reference.config import load_config as stage_config
from tools.stage1_reference.model import Model, DAY, WEEK
from tools.economy_reference.config import load_config as economy_config
from tools.economy_reference.experiments import unfunded_trader, cheap_claim, holder_drawdown
from tools.economy_reference.simulation import STRATEGIES, run
from tools.economy_reference.tournament import compact

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "history/conversations-2026-10-13"
LAUNCH = 1791201600  # Synthetic Monday from stage1_reference/tests/conftest.py.
LAMPORTS = 10**9
USDC = 10**6
PRICES = (Fraction("60.37"), Fraction("120.74"), Fraction(200))
APRS = (Fraction("0.022"), Fraction("0.052"))
SOURCES = {
    "brief": "history/codex-briefs-2026-10-13/four-conversations.md",
    "diamond": "history/hill-bonding-diamond-2026-10-08/DIAMOND.md",
    "parameters": "history/hill-bonding-diamond-2026-10-08/diamond.yaml",
    "stage1": "history/launch-readiness-2026-10-08/STAGE1_SPEC.md",
    "funding": "history/launch-readiness-2026-10-08/FUNDING.md",
    "readiness": "history/launch-readiness-2026-10-08/CHECKLIST.md",
    "design": "history/explainer-hill-bonding-2026-10-06/DESIGN.md",
    "intake": "history/codex-reports-2026-10-08/intake.md",
    "intake_factcheck": "history/codex-reports-2026-10-08/intake-factcheck.md",
    "token_intake": "history/codex-reports-2026-10-08/intake-round2-token-led.md",
    "token_factcheck": "history/codex-reports-2026-10-08/intake-round2-factcheck.md",
    "stage1_model": "tools/stage1_reference/model.py",
    "stage1_arithmetic": "tools/stage1_reference/arithmetic.py",
    "economy_model": "tools/economy_reference/simulation.py",
    "economy_accounting": "tools/economy_reference/accounting.py",
    "market": "tools/economy_reference/market.py",
    "experiments": "tools/economy_reference/experiments.py",
}
ASSUMPTIONS = {
    "A1": "[assumption] Prices $60.37/$120.74/$200 and gross APR 2.2%/5.2% stay constant; 52 weeks/year, 5% upstream commission once, no extra costs, losses or idle earning weeks. Inputs are comparisons, not quotes. Default $120.74/5.2% (parameters.model.default; parameters.example_hill.validator_commission).",
    "A2": "[assumption] Synthetic nine-decimal LST starts at 1 SOL/token and its redemption rate compounds by net APR/52 weekly; harvest each week, value each payout at that harvest rate. Token units are actual model entitlements; SOL/USD equivalents are valuations, not conversions. No real mint or provider is selected.",
    "A3": "[assumption] Bond at synthetic city week 0, with no harvested income that partial week; measure 26 full earning weeks 1–26. Hill stays live; verified field re-establishes each city season. Club 25/50/100 ascents use 5/10/20 distinct people with five ascents each, up to ten occupied seats and the first rider as earned Legend; 6 TSS/ascent. Below-field case: four people, 25 ascents (7/6/6/6).",
    "A4": "[assumption] Club is one aggregated owner and sole backer, and its pledge crosses the line. Pilot whale is sole backer on ten hills, 500 SOL each, across at least three hypothetical enabled tokens (2,000/2,000/1,000 basis SOL). Its per-hill riding is the tournament's 8 regulars ×2 plus 2 visitors ×1 =18 ascents, 6 TSS/ascent; same people recur in the stage1 sample, with ten occupied seats and an earned Legend.",
    "A5": "[assumption] Sponsor prices $500/$1,500/$5,000/$15,000 are intake solicitation examples; $30,000 is a Strava category benchmark, not a BoulderRoller quote. One USDC is valued at $1. Whole budget funds riders, spread equally across 1 or 5 hills; a cash season and each boost duration are alternatives, not additive. The cash season is 26 weekly receipts, not an invented 26-week boost; sufficient field/seats/ascents/headroom are conditional on actual settlement.",
    "A6": "[assumption] Service examples add FUNDING's illustrative 15% on top of rider budget; a separately negotiated fixed-dollar fee is an option with no assumed quote. Principle 7 wording/amendment remains pending Jon; existing protocol fee on cash stays zero.",
    "A7": "[assumption] Validator routes 100% of its 5% inflation commission, or buys incremental routing of 0.25%/0.50% of external stake per year net of upstream SAM costs. These are alternative contracts, not additive rewards; SFDP eligibility and sufficient qualifying stake are assumed only for conditional matching arithmetic. Foundation principal/delegator rewards never become hill money. Explicit matched-stake commission routing is shown separately, not presumed.",
    "A8": "[assumption] All numerical/behavioral model inputs under parameters.model are synthetic, including liquidity, CAL prices/budgets, bids, timing, riding/crew costs, sponsor gifts and demand. Only immediate earned-CAL sale and hardened ladder behavior are ratified defaults. Full effective configuration and scenario overrides are retained. Market runs are selected sensitivities, not the full factorial, an adoption forecast or deployed stages 2/3.",
    "A9": "[assumption] Honest-500 market comparison changes only whale.stake_sol_per_hill to 250: honest_long adds two such lots, plus its unchanged 10 community SOL/hill. It therefore has 510/hill and 5,100 total and a proposed 104-week second lot; it is not pilot-admissible. Stage1 pilot numbers are separate and have no CAL-claim income. No value is assigned to titles or DUNG.",
}


def exact(value):
    """Read an exact JSON quantity or a scalar, without passing through float."""
    return Fraction(value["exact"] if isinstance(value, dict) else str(value))


def decimal(value, places=12):
    value = exact(value)
    with localcontext() as context:
        context.prec = 60
        return f"{Decimal(value.numerator) / Decimal(value.denominator):.{places}f}"


def encode(value):
    if isinstance(value, Fraction):
        return {"exact": str(value), "decimal": decimal(value)}
    if isinstance(value, dict):
        return {str(key): encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [encode(item) for item in value]
    return value


def scenario_id(price, apr):
    return f"{decimal(price, 2)}_{decimal(apr, 3)}"


def budget(stake, apr, price, p, *, route="full_yield", routing_apr=None):
    commission = exact(p["example_hill"]["validator_commission"])
    fee = exact(p["fee_on_yield"])
    annual = stake * apr * (1 - commission) if route == "full_yield" else stake * apr * commission if route == "commission" else stake * routing_apr
    result = {"stake_sol": stake, "scenario": scenario_id(price, apr), "route": route}
    for name, weeks in (("week", 1), ("season", p["season_weeks"]), ("year", p["model"]["weeks_per_year"]),
                        ("founder_minimum_commitment", p["bond_lock_weeks"] + p["notice_weeks"])):
        net = annual * weeks / p["model"]["weeks_per_year"]
        rider = net * (1 - fee)
        result[name] = {"net_income_sol": net, "fee_sol": net * fee, "rider_sol": rider,
                        "net_income_usd": net * price, "fee_usd": net * fee * price, "rider_usd": rider * price,
                        "buckets_sol": {k: rider * exact(v) for k, v in p["rider_split"].items()},
                        "buckets_usd": {k: rider * exact(v) * price for k, v in p["rider_split"].items()}}
    result["stake_usd"] = stake * price
    result["ascent_only_usd_per_ascent_week"] = {
        str(count): result["week"]["buckets_usd"]["every_rider_by_ascents"] / count
        for count in (25, 50, 100)
    }
    if routing_apr is not None:
        result["routing_apr_after_upstream_costs"] = routing_apr
    return result


@lru_cache(maxsize=None)
def stage1_case(stake, apr, ascents, *, weeks=26, below_field=False, tournament_riding=False):
    """Execute the unmodified integer custody/settlement oracle through every week."""
    c = stage_config()
    p = economy_config()
    weekly = apr * (1 - exact(p["example_hill"]["validator_commission"])) / p["model"]["weeks_per_year"]
    counts = [7, 6, 6, 6] if below_field else [2] * 8 + [1] * 2 if tournament_riding else [5] * (ascents // 5)
    assert sum(counts) == ascents and max(counts) <= 7
    m = Model(c, LAUNCH)
    m.allow_asset("illustrative_LST", 9, Fraction(1))
    m.add_hill("hill")
    lot = m.pledge("backer", "hill", "illustrative_LST", stake * LAMPORTS)
    people = [f"p{i:02d}" for i in range(len(counts))]
    for person in people:
        m.register_person(person, f"wallet:{person}")
    m.set_board("hill", people[:p["model"]["top_ten_seats"]], people[0])
    m.advance(LAUNCH + WEEK + c.grace)
    assert m.settle("hill", 0).dung.potential == 0
    rows, rider_value, forgone_value, dung = [], Fraction(0), Fraction(0), 0
    for week in range(1, weeks + 1):
        for day in range(max(counts)):
            ridden = LAUNCH + week * WEEK + day * DAY + 1
            m.advance(max(m.now, ridden))
            for person, count in zip(people, counts):
                if day < count:
                    m.upload(f"{week}:{day}:{person}", "hill", person, ridden,
                             p["example_hill"]["climb_tss_per_ascent"] * c.tss_scale)
        rate = (1 + weekly) ** week
        m.observe_rate("illustrative_LST", rate)
        fee_before = m.ledgers["illustrative_LST"].fees
        harvested = m.harvest(lot)
        fee = m.ledgers["illustrative_LST"].fees - fee_before
        m.advance(LAUNCH + (week + 1) * WEEK + c.grace)
        settlement = m.settle("hill", week)
        claim_set = settlement.claims["illustrative_LST"]
        leaves = {leaf.person: leaf.amount for leaf in claim_set.leaves}
        claimable = sum(leaves.values())
        value = Fraction(claimable, LAMPORTS) * rate
        rider_value += value
        forgone_value += Fraction(harvested, LAMPORTS) * rate
        dung += settlement.dung.backers.get("backer", 0)
        weights = dict(m.snapshots["hill", week].backers)
        rows.append({"earning_week": week, "city_week": week, "rate_lamports_per_token_unit": rate,
                     "harvest_units": harvested, "fee_units": fee,
                     "bucket_units": apportion(harvested - fee, c.split),
                     "claimable_units": claimable, "cap_units": settlement.caps["illustrative_LST"],
                     "leaves": leaves, "rider_sol_at_harvest": value,
                     "backer_weight_sol": weights["backer"] / LAMPORTS,
                     "backer_dung_units": settlement.dung.backers.get("backer", 0),
                     "rider_dung_units": sum(settlement.dung.riders.values()),
                     "dung_unminted_units": settlement.dung.unminted})
    balances = m.balances("illustrative_LST")
    m.check()
    examples = {}
    for label, index in (("legend_and_top_seat", 0), ("top_seat", 1), ("ascents_only", 10)):
        if index < len(people):
            person = people[index]
            examples[label] = {"person": person,
                               "week1_sol": Fraction(rows[0]["leaves"].get(person, 0), LAMPORTS) * rows[0]["rate_lamports_per_token_unit"],
                               "season_sol_at_each_harvest": sum((Fraction(w["leaves"].get(person, 0), LAMPORTS) * w["rate_lamports_per_token_unit"] for w in rows), Fraction(0))}
    return {"stake_sol": stake, "gross_apr": apr, "ascents": ascents, "people": len(people),
            "ascents_by_person": dict(zip(people, counts)), "weeks": rows,
            "realized_units": m.ledgers["illustrative_LST"].realized,
            "fee_units": m.ledgers["illustrative_LST"].fees, "held_units": balances["held"],
            "rider_sol_at_harvest": rider_value, "forgone_sol_at_harvest": forgone_value,
            "backer_dung": Fraction(dung, c.dung_scale),
            "backer_dung_per_week": Fraction(dung, c.dung_scale * weeks),
            "backer_vote_weight_while_active_at_full_timer": Fraction(dung, c.dung_scale),
            "first_city_season": {
                "earning_weeks": len([w for w in rows if w["city_week"] < c.season_weeks]),
                "backer_dung": Fraction(sum(w["backer_dung_units"] for w in rows if w["city_week"] < c.season_weeks), c.dung_scale),
                "rider_sol_at_harvest": sum((w["rider_sol_at_harvest"] for w in rows if w["city_week"] < c.season_weeks), Fraction(0)),
            },
            "receipt_examples": examples,
            "founder": m.hills["hill"].founder, "claimed_units": balances["paid"],
            "source": ["stage1", "stage1_model", "parameters"], "assumptions": ["A1", "A2", "A3", "A4"]}


def sponsor_data(p):
    prices = [500, 1500, 5000, 15000, 30000]
    seasons, boosts, comparisons, services = [], [], [], []
    c = stage_config()
    for dollars in prices:
        services.append({"budget_usdc": dollars, "pending_percentage": Fraction(15, 100),
                         "pending_company_fee_usd": Fraction(dollars * 15, 100),
                         "pending_total_invoice_usd": Fraction(dollars * 115, 100),
                         "current_protocol_fee_usdc": 0,
                         "fixed_service_fee": "negotiated separately; no sourced amount"})
        for hills in (1, 5):
            slots = {f"h{h}\0{w:02d}": (f"h{h}", w) for h in range(hills) for w in range(1, 27)}
            schedule = []
            for key, units in apportion(dollars * USDC, dict.fromkeys(slots, 1)).items():
                hill, week = slots[key]
                schedule.append({"hill": hill, "week": week, "usdc_units": units,
                                 "buckets_units": apportion(units, c.split)})
            seasons.append({"budget_usdc": dollars, "hills": hills, "weeks": 26,
                            "schedule": schedule, "fee_usdc": 0, "backer_dung": 0,
                            "per_hill_week_usdc": Fraction(dollars, 26 * hills),
                            "week_buckets_usdc_per_hill": {k: Fraction(dollars, 26 * hills) * v for k, v in c.split.items()},
                            "per_hill_season_usdc": Fraction(dollars, hills)})
            for duration in range(c.boost_min, c.boost_max + 1):
                m = Model(c, LAUNCH)
                names = [f"h{i}" for i in range(hills)]
                for name in names:
                    m.add_hill(name)
                boost_id = m.boost("sponsor", names, dollars * USDC, 1, duration)
                boost = m.boosts[boost_id]
                boosts.append({"budget_usdc": dollars, "hills": hills, "duration_weeks": duration,
                               "per_hill_ride_week_usdc": Fraction(dollars, hills * duration),
                               "week_buckets_usdc_per_hill": {k: Fraction(dollars, hills * duration) * v for k, v in c.split.items()},
                               "protocol_fee_usdc_units": m.ledgers["USDC"].fees,
                               "backer_dung_units": 0, "funded_tail_weeks": 0,
                               "schedule": [{"hill": h, "ride_week": w, "usdc_units": u,
                                             "buckets_units": apportion(u, c.split)} for h, w, u in boost.schedule]})
            for price in PRICES:
                for apr in APRS:
                    comparisons.append({"budget_usdc": dollars, "hills": hills, "scenario": scenario_id(price, apr),
                                        "rider_usdc_season": dollars, "rider_usdc_week_all_hills": Fraction(dollars, 26),
                                        "per_hill_week_usdc": Fraction(dollars, 26 * hills),
                                        "season_sol_equivalent": dollars / price, "fee_usdc": 0})
    return {"source": ["intake", "intake_factcheck", "funding", "stage1", "stage1_model", "stage1_arithmetic"],
            "assumptions": ["A5", "A6"], "season_schedules": seasons, "boosts": boosts,
            "scenarios": comparisons, "service_options": services,
            "title": "Season sponsor/boost funder recognition; no Founder title, sporting seat or DUNG from cash.",
            "price_provenance": {"500_1500": "intake §4 merchant solicitation assumptions",
                                 "5000_15000": "intake §4 anchor solicitation assumptions; §5 $5,000/26-week test",
                                 "30000": "intake §3.1; intake_factcheck row 6a; https://business.strava.com/challenges (research snapshot 7–8 October 2026, not refreshed)"}}


def validator_data(p):
    rows, bounds = [], []
    for price in PRICES:
        for apr in APRS:
            for stake in (1000, 10000, 50000):
                match = min(Fraction(stake, 2), 50000)
                full = budget(stake, apr, price, p)
                commission = budget(stake, apr, price, p, route="commission")
                match_commission = budget(match, apr, price, p, route="commission")
                sam = []
                for routing in (Fraction("0.0025"), Fraction("0.005")):
                    entry = budget(stake, apr, price, p, route="sam_net", routing_apr=routing)
                    entry["gross_bid_apr_if_75pct_fee"] = routing / Fraction("0.25")
                    entry["gross_bid_sol_season"] = stake * entry["gross_bid_apr_if_75pct_fee"] / 2
                    entry["upstream_fee_sol_season"] = entry["gross_bid_sol_season"] * Fraction("0.75")
                    sam.append(entry)
                rows.append({"stake_sol": stake, "scenario": scenario_id(price, apr), "full_yield": full,
                             "commission_only": commission, "sam": sam,
                             "sfdp_matched_sol_conditional": match, "sfdp_total_delegation_sol_conditional": stake + match,
                             "sfdp_match_is_hill_money": False, "matched_commission_only_if_separately_routed": match_commission,
                             "operator_commission_retained_when_fully_routed_sol": 0,
                             "operator_gross_inflation_commission_sol_season": commission["season"]["net_income_sol"],
                             "full_yield_minimum_hills_at_500": (stake + 499) // 500,
                             "full_yield_fits_total_pilot_cap": stake <= 5000,
                             "external_delegation_backer_dung": 0, "external_delegation_bonding_credit_sol": 0})
            rate = apr * (1 - exact(p["example_hill"]["validator_commission"])) * (1 - exact(p["fee_on_yield"]))
            required = Fraction(1_000_000) / rate
            bounds.append({"scenario": scenario_id(price, apr), "annual_rider_usd": 1_000_000,
                           "net_rider_apr": rate, "required_stake_usd": required,
                           "required_stake_sol": required / price,
                           "formula": "1,000,000 / (gross_apr * (1 - validator_commission) * (1 - yield_fee))",
                           "pilot_5000_annual_rider_usd": 5000 * price * rate})
    return {"source": ["parameters", "intake", "intake_factcheck", "funding", "economy_accounting"],
            "assumptions": ["A1", "A7"], "scenarios": rows, "million_bound": bounds,
            "rights": "Full-yield hill lots earn only their normalized share of backer DUNG from actual hill TSS; Founder only if their pledge bonds a hill. External delegation/commission/SAM gets no hill stake, DUNG or Founder; recognition and retention benefit are unpriced.",
            "sfdp": {"match_rate": Fraction(1, 2), "match_cap_sol": 50000, "stake_to_reach_match_cap_sol": 100000,
                     "source_epoch": "893 onward in dated intake; award/eligibility not established",
                     "criteria_snapshot": "97% average vote credits; commission <=5%; MEV commission <=10%; total stake <=1,000,000 SOL; concentration/testnet criteria; vote-cost support ends after 180 epochs",
                     "citations": ["https://solana.org/faq", "https://solana.org/delegation-criteria"]},
            "sam": {"bid_flow_fee": Fraction(3, 4),
                    "citations": ["https://docs.marinade.finance/marinade-protocol/protocol-overview/stake-auction-market", "https://docs.marinade.finance/marinade-protocol/faq"],
                    "boundary": "Bid-flow haircut is not a haircut on all staking rewards; never add it to an LST return that already includes it. Delegation authority and a net quote are unestablished."}}


def market_data(p, pilot_cases):
    rows, honest, controls = [], [], []
    for price in PRICES:
        for apr in APRS:
            scenario = {"sol_usd": float(price), "gross_apr": float(apr)}
            for label, other in (("default", {}),
                                 ("thin_high_demand", {"market_depth_usdc": 1000, "riders": 50, "regular_fraction": 0.4, "speculator_intensity": 4}),
                                 ("high_demand", {"market_depth_usdc": 10000, "riders": 50, "regular_fraction": 0.4, "speculator_intensity": 4}),
                                 ("zero_speculators", {"speculator_intensity": 0})):
                for strategy in STRATEGIES:
                    result = compact(run(p, strategy, scenario | other))
                    rows.append({"scenario": scenario_id(price, apr), "condition": label, "strategy": strategy, "result": result})
            q = deepcopy(p)
            q["model"]["whale"]["stake_sol_per_hill"] = 250
            honest_result = compact(run(q, "honest_long", scenario))
            first_season = [phase for phase in honest_result["phases"] if phase["through_week"] <= p["season_weeks"]]
            honest.append({"scenario": scenario_id(price, apr), "parameter_override": {"model.whale.stake_sol_per_hill": 250},
                           "pilot_admissible": False, "hill_total_sol": 510, "total_sol": 5100,
                           "first_26_weeks": {
                               "whale_funded_rider_pay_usd": sum(first_season[-1]["cumulative_whale_rider_pay_usd"].values()),
                               "whale": {key: sum(phase["actors"]["whale"][key] for phase in first_season)
                                         for key in ("cash_usd", "opportunity_cost_usd", "economic_cash_usd", "hill_pay_usd", "cal", "dung")},
                           },
                           "result": honest_result})
            # The cheap-claim experiment reads example_hill rather than default inputs.
            q = deepcopy(p)
            q["example_hill"]["sol_usd"] = float(price)
            q["example_hill"]["rewards_sol_per_week"] = 1000 * float(apr) / p["model"]["weeks_per_year"]
            controls.append({"scenario": scenario_id(price, apr), "cheap_claim_input_stake_sol": 1000,
                             "unfunded_trader": unfunded_trader(q), "cheap_claim": cheap_claim(q),
                             "immediate_sale": holder_drawdown(q), "optional_retained_cal": holder_drawdown(q, False)})
    pilot = {"per_hill_basis_sol": 500, "hills": 10, "total_basis_sol": 5000,
             "per_token_basis_cap_sol": 2000, "minimum_token_count": 3,
             "illustrative_token_basis_sol": [2000, 2000, 1000],
             "cap_measure": "Running still-held deposit-time SOL basis; not market USD or appreciated token value (brief's later 13 October decision).",
             "budgets": [budget(5000, apr, price, p) for price in PRICES for apr in APRS],
             "model_cases_per_hill": pilot_cases,
             "backer_dung_week": pilot_cases[0]["backer_dung_per_week"] * 10,
             "backer_dung_season": pilot_cases[0]["backer_dung"] * 10,
             "backer_vote_weight_while_active": pilot_cases[0]["backer_vote_weight_while_active_at_full_timer"] * 10,
             "founder_titles": 10,
             "initial_backer_allocation_weight_per_hill": pilot_cases[0]["weeks"][0]["backer_weight_sol"],
             "stage1_backer_cal_claim_income": 0}
    return {"source": ["parameters", "diamond", "stage1", "brief", "economy_model", "economy_accounting", "market", "experiments"],
            "assumptions": ["A1", "A2", "A4", "A8", "A9"], "pilot": pilot,
            "tournament": rows, "honest_500_tournament": honest, "controls": controls,
            "full_factorial": False, "selection": "All eight strategies at six SOL/APR pairs, plus thin/high-demand, high-demand and zero-speculator controls. No legacy flags; selected conditions only.",
            "effective_model_inputs": p["model"],
            "stage1_difference": "Economy uses floats, combined USD cash caps, older hold/founder timing and proposed long locks. It does not enforce stage1 asset/hill/deployment caps. Use integer stage1 cases for pilot money; market outputs are not stage1 entitlements."}


def _case_job(job):
    stake, apr, ascents, below, tournament = job
    return stage1_case(stake, apr, ascents, below_field=below, tournament_riding=tournament)


def build():
    p = economy_config()
    c = stage_config()
    jobs = [(stake, apr, ascents, False, False) for stake in (10, 50, 500) for apr in APRS for ascents in (25, 50, 100)]
    jobs += [(stake, apr, 25, True, False) for stake in (10, 50, 500) for apr in APRS]
    jobs += [(500, apr, 18, False, True) for apr in APRS]
    # Independent offline worlds; only the parent writes artifacts. Keep order stable.
    with ProcessPoolExecutor(max_workers=p["model"]["tournament_workers"]) as workers:
        cases = list(workers.map(_case_job, jobs))
    club = {"source": ["parameters", "stage1", "stage1_model", "brief"], "assumptions": ["A1", "A2", "A3", "A4"],
            "budgets": [budget(stake, apr, price, p) for stake in (10, 50, 500) for price in PRICES for apr in APRS],
            "model_cases": cases[:-2],
            "line_sol": Fraction(c.line, LAMPORTS), "live_line_sol": Fraction(c.line, LAMPORTS) * c.live_fraction,
            "founder_title": "Pledge owner whose transaction crosses the line; no sporting seat or automatic Legend pay.",
            "lock_weeks": c.bond_lock_weeks, "notice_weeks": c.notice_weeks,
            "earliest_exit_initiation_weeks": c.bond_lock_weeks + c.notice_weeks,
            "earliest_return": "After lock + notice and actual liquidity; no sourced provider completion time.",
            "stale_rate_exit": "In-kind exit allowed after 7 stale-rate days per later 13 October decision; freshness clock, transaction ordering and interaction with ordinary exits are not specified/executed by this oracle. No assumed bypass of lock/notice.",
            "later_lock_weights": c.lock_weights,
            "weight_timing": "Bond at city week0: weeks1–25 basis*0.75*2; week26 basis*0.25*2 after lock expiry; week27 onward basis*0.25. Founder bonus changes division of the fixed backer half, not total issuance.",
            "below_field_max_weekly_paid_ascents": 4 * 7 * c.daily_ascents,
            "below_field_unavailable_cases": [50, 100]}
    data = {"schema_version": 1, "evidence_class": "Local/offline integer oracle and deterministic market simulation; no deployment, real funding, provider quote or verified rider outcome.",
            "source_manifest": {key: {"path": path, "sha256": sha256((ROOT / path).read_bytes()).hexdigest()} for key, path in SOURCES.items()},
            "assumptions": ASSUMPTIONS, "parameters": p,
            "scenarios": [{"id": scenario_id(price, apr), "sol_usd": price, "gross_apr": apr,
                           "default": price == exact(p["model"]["default"]["sol_usd"]) and apr == exact(p["model"]["default"]["gross_apr"])} for price in PRICES for apr in APRS],
            "number_convention": "Exact rational is authoritative; decimal rounds to 12 places. Token/USDC/DUNG units are integers. Market-model numbers are native binary-float outputs. Weekly/26-week ideal budgets require actual realization; model claims are funded entitlements, not wallet receipts. Parent source/assumption lists apply to every child figure.",
            "source_gaps": ["Deposit-basis caps supersede STAGE1_SPEC/model marked exposure; scenarios do not exercise appreciation-time intake. No reference cap implementation changed.",
                            "Seven-stale-day in-kind policy is brief-only; reference model has no stale-rate exit. No provider timing promised.",
                            "Accepted token mints, adapter costs/freshness/liquidity, SFDP award, routing contracts, sponsor demand/ROI, authentic field/TSS, title/DUNG monetary value and current production readiness are not established by supplied sources.",
                            "FUNDING approves service direction, but principle 7 wording/amendment is pending; no service fee is deducted from rider money.",
                            "No unchanged economy run represents exactly 500 sole-whale SOL/hill within pilot caps; default community additions and proposed 104-week lots remain explicit.",
                            "CHECKLIST is an 8 October snapshot; this work does not refresh live readiness or establish launch clearance."],
            "club": club, "sponsor": sponsor_data(p), "validator": validator_data(p), "whale": market_data(p, cases[-2:])}
    return encode(data)


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"] +
                     ["| " + " | ".join(str(v) for v in row) + " |" for row in rows])


def money(value, digits=2):
    amount = exact(value)
    return f"{'-' if amount < 0 else ''}${float(abs(amount)):,.{digits}f}"


def number(value, digits=6):
    return decimal(value, digits).rstrip("0").rstrip(".") if digits else decimal(value, 0)


def footnotes(data, assumptions, sources):
    return ("\n\n[TIM: framing]\n\n" +
            "\n\n".join(data["assumptions"][key] for key in assumptions) +
            "\n\nSources: " + "; ".join(f"[{key}](../../{data['source_manifest'][key]['path']})" for key in sources) +
            ". Outside-world facts retain the intake's 7–8 October 2026 research dates; no web refresh.\n\n" +
            "[numbers.json](numbers.json) contains all six SOL/APR combinations, exact inputs, source hashes, weekly model outputs and assumptions. " +
            "Regenerate with `python -m tools.conversations.build`; verify with `python -m pytest tools/conversations/test_build.py -q` " +
            "using Python 3.12 and `tools/stage1_reference/requirements.txt`. Exact rational values and integer units are authoritative; tables round. " +
            "Evidence: local/offline. No real funding, wallet receipt, provider integration or deployment is established.\n")


def documents(data):
    default = "120.74_0.052"
    price = Fraction("120.74")
    club = data["club"]
    budgets = {r["stake_sol"]: r for r in club["budgets"] if r["scenario"] == default}
    club_text = table(
        ["Pledge SOL (one hill)", "Principal USD", "Forgone SOL/week /26 weeks", "Rider budget USD/week /26 weeks", "Initial DUNG allocation weight"],
        [[s, money(b["stake_usd"]), f"{number(b['week']['net_income_sol'])} / {number(b['season']['net_income_sol'])}",
          f"{money(b['week']['rider_usd'])} / {money(b['season']['rider_usd'])}", number(Fraction(s * 3, 2))] for s, b in budgets.items()])
    club_text += "\n\n[TIM: framing]\n\nDefault: $120.74/SOL, 5.2% gross APR, 5% upstream commission, then 10% of realized net yield. "
    club_text += "These are ideal available budgets; the integer LST oracle in JSON records actual funded entitlements and rounding. USD is valuation at harvest, not a USDC promise.\n\n"
    club_text += table(["Pledge SOL", "Weekly ascents", "65% ascent bucket USD per ascent (before cap)", "Backer DUNG/week /26 full weeks"],
                       [[s, count, money(b["ascent_only_usd_per_ascent_week"][str(count)], 4),
                         f"{number(Fraction(count * 6, 2000))} / {number(Fraction(count * 6 * 26, 2000))}"]
                        for s, b in budgets.items() for count in (25, 50, 100)])
    club_text += "\n\nThe remaining cash buckets are 25% shared equally by occupied top-ten seats and 10% to the earned Local Legend. "
    club_text += "The cap combines all of a person's entitlements per asset; bucket-per-ascent figures above are not final individual payouts. "
    club_text += "At 500 SOL, the unmodified oracle gives these examples under A3 (Legend also holds a top-ten seat):\n\n"
    cases = [r for r in club["model_cases"] if r["stake_sol"] == 500 and exact(r["gross_apr"]) == Fraction("0.052") and r["people"] >= 5]
    club_text += table(["Ascents /people", "Top seat rider: USD first week /26 weeks", "Legend+top rider: USD first week /26 weeks", "3× cap: first-week USD"],
                       [[f"{r['ascents']} /{r['people']}",
                         " / ".join(money(exact(r["receipt_examples"]["top_seat"][key]) * price) for key in ("week1_sol", "season_sol_at_each_harvest")),
                         " / ".join(money(exact(r["receipt_examples"]["legend_and_top_seat"][key]) * price) for key in ("week1_sol", "season_sol_at_each_harvest")),
                         money(Fraction(r["weeks"][0]["cap_units"], LAMPORTS) * exact(r["weeks"][0]["rate_lamports_per_token_unit"]) * price)] for r in cases])
    club_text += "\n\nBelow five distinct riders in the city season: ascent cash can pay; top-ten and Legend shares wait (35% before other cap/rounding holds); DUNG is zero, with no later catch-up. "
    club_text += "Four people can make at most 28 paid ascents/week, so 50/100 below-field cases are impossible. The JSON exercises four people/25 ascents; held money ages into pool-only custody after 26 weeks, not a refund.\n\n"
    club_text += "The 10 SOL pledge reaches Philadelphia's line; the live threshold is 5 SOL. All three sole pledges trigger the Founder title, with no paid seat. "
    club_text += "500 SOL fills the hill's pilot cap. The club receives the entire fixed backer half only because it is the sole backer. "
    club_text += "Founder 2× changes allocation weight, never issuance. For a week-0 bond, weights are 1.5× basis in full weeks 1–25, 0.5× in week 26 after lock expiry, and 0.25× from week 27. "
    club_text += "Earned-DUNG vote weight equals accumulated DUNG while backing remains and its timer is full; after exit the timer decays over 104 weeks. Allocation weight and voting weight are different quantities.\n\n"
    club_text += "Lock: 26 weeks from bonding. Notice can start only then and lasts four weeks. Earliest exit initiation: week 30; return also needs actual liquidity, whose time is unknown. "
    club_text += "Yield continues to riders through notice/deactivation until return. Seven stale-rate days permit an in-kind exit under the brief's later decision; the old oracle does not execute this path, and the sources do not specify a lock/notice bypass. "
    club_text += "Returned asset is the deposited token; losses stay with its lot, so principal value is not guaranteed.\n\n"
    club_text += "The minimum 30-week commitment forgoes " + " / ".join(number(b["founder_minimum_commitment"]["net_income_sol"]) for b in budgets.values()) + " SOL for the 10/50/500 pledges at default APR; delayed liquidity adds time. "
    club_text += "The 26-full-week projection spans city weeks 1–26. Under the assumed week-0 bond, the first city season (weeks 0–25) has only 25 earning weeks; its exact cash and DUNG are separately recorded in JSON.\n\n"
    club_text += table(["SOL/USD", "Gross APR", "10 SOL: rider USD/week /season", "50 SOL: rider USD/week /season", "500 SOL: rider USD/week /season"],
                       [[number(s["sol_usd"], 2), f"{float(exact(s['gross_apr'])) * 100:g}%"] +
                        [f"{money(next(r for r in club['budgets'] if r['scenario'] == s['id'] and r['stake_sol'] == stake)['week']['rider_usd'])} / " +
                         money(next(r for r in club['budgets'] if r['scenario'] == s['id'] and r['stake_sol'] == stake)['season']['rider_usd']) for stake in (10, 50, 500)] for s in data["scenarios"]])
    club_text += footnotes(data, club["assumptions"], club["source"] + ["design", "diamond"])

    sponsor = data["sponsor"]
    sponsor_text = table(["Total rider budget USDC", "Hills", "Each hill/week USDC", "65% ascents /25% top-ten /10% Legend per hill/week"],
                         [[r["budget_usdc"], r["hills"], money(r["per_hill_week_usdc"]),
                           " / ".join(money(r["week_buckets_usdc_per_hill"][key]) for key in ("every_rider_by_ascents", "top_ten", "local_legend"))] for r in sponsor["season_schedules"]])
    sponsor_text += "\n\n[TIM: framing]\n\n26-week cash season. The same total budget is divided across one or five hills; buying five separate one-hill budgets costs five times as much. "
    sponsor_text += "The table shows weekly averages; exact micro-USDC schedules and Hamilton dust are in JSON. A season is modeled as 26 weekly receipts, not a 26-week boost. "
    sponsor_text += "All cash enters the rider lane with zero protocol fee. Records require the five-rider field; occupied seats, earned Legend, verified ascents and cap headroom determine funded claims. Otherwise money waits. Cash can fund a registered unbonded/non-live hill in an admitted city.\n\n"
    sponsor_text += "Strava's Sponsored Challenges start at $30,000 in the dated [intake citation](https://business.strava.com/challenges). "
    sponsor_text += "That is a category comparator, not a BoulderRoller price or audience claim. Lower rows use the intake's merchant/anchor solicitation assumptions.\n\n"
    sponsor_text += table(["Alternative $30,000 boost", "Hills", "Per hill/ride week USDC", "Funded tail weeks"],
                         [[f"{r['duration_weeks']} riding {'week' if r['duration_weeks'] == 1 else 'weeks'}", r["hills"], money(r["per_hill_ride_week_usdc"]), 0]
                          for r in sponsor["boosts"] if r["budget_usdc"] == 30000 and r["duration_weeks"] in (1, 8, 13)])
    sponsor_text += "\n\nEvery integer duration 1–13 is computed in JSON. A boost is fully escrowed at posting, irrevocable, starts at a future full week and buys only its selected hills' riding weeks. "
    sponsor_text += "It pays the same split with zero fee and no purchased DUNG. Upload age is at most seven days, but a late upload must also arrive strictly before its ride-week close plus 86,400 seconds to share that boost week's existing budget. "
    sponsor_text += "No extra tail budget or reopened root. Unused cash retries only through the last riding-week settlement, then waits for the existing 26-week pool-only fallback; no refund and no payment to later unrelated riding. "
    sponsor_text += "Season/boost funder title or recognition has no sourced monetary value and grants no Founder title or sporting seat.\n\n"
    sponsor_text += table(["Rider budget", "Current cash protocol fee", "Pending extra service fee at 15%", "Pending total invoice"],
                         [[money(r["budget_usdc"]), "$0", money(r["pending_company_fee_usd"]), money(r["pending_total_invoice_usd"])] for r in sponsor["service_options"]])
    sponsor_text += "\n\nFUNDING records Tim's approval of the direction; Jon's review and principle 7 amendment/wording remain pending. "
    sponsor_text += "A separately negotiated fixed service fee is another option; no fixed-dollar quote is supplied. Both are on top of the rider budget, never deducted from it. "
    sponsor_text += "Across all three SOL prices and both APRs, each USDC schedule is unchanged; only its SOL-equivalent comparison changes (all six rows per budget/hill count are in JSON).\n"
    sponsor_text += footnotes(data, sponsor["assumptions"], sponsor["source"])

    validator = data["validator"]
    vr = [r for r in validator["scenarios"] if r["scenario"] == default]
    validator_text = table(["External/backing SOL", "All net staking yield: rider USD/week /26 weeks", "100% of 5% commission: rider USD/week /26 weeks", "Conditional SFDP extra SOL"],
                           [[r["stake_sol"], " / ".join(money(r["full_yield"][k]["rider_usd"]) for k in ("week", "season")),
                             " / ".join(money(r["commission_only"][k]["rider_usd"]) for k in ("week", "season")), number(r["sfdp_matched_sol_conditional"])] for r in vr])
    validator_text += "\n\n[TIM: framing]\n\nDefault $120.74/SOL and 5.2% gross APR. These are alternative contributions: full-yield backing uses `stake × APR × 0.95 × 0.90`; "
    validator_text += "commission-only uses `stake × APR × 0.05 × 0.90`, with no second 5% haircut. Figures are available budgets before field/cap/holds. "
    validator_text += "1,000/10,000/50,000 SOL need at least 2/20/100 hills at the 500 cap. Only the first fits the 5,000 total pilot cap as hill principal; larger rows are external-delegation or future-scale comparisons, never pilot intake approvals.\n\n"
    validator_text += table(["External SOL", "Net routed APR", "SAM gross bid APR at 75% bid-flow fee", "Rider USD/week /26 weeks", "Operator gross bid SOL/26 weeks"],
                           [[r["stake_sol"], f"{float(exact(s['routing_apr_after_upstream_costs'])) * 100:g}%", f"{float(exact(s['gross_bid_apr_if_75pct_fee'])) * 100:g}%",
                             " / ".join(money(s[k]["rider_usd"]) for k in ("week", "season")), number(s["gross_bid_sol_season"])] for r in vr for s in r["sam"]])
    validator_text += "\n\nSAM's 75% applies to bid flow, not all staking rewards ([dated FAQ](https://docs.marinade.finance/marinade-protocol/faq)). "
    validator_text += "The intake's 0.25–0.50% net routing rates are assumptions after upstream costs; recovering the equivalent gross bid divides by 0.25, then the protocol takes its single 10% of delivered revenue. "
    validator_text += "These net routing rates are independent scenario inputs at both gross staking APRs, not promised incremental APY or free operator margin. Delegation rights and actual quotes are absent; holding an LST does not confer validator selection.\n\n"
    validator_text += "SFDP: `min(0.5 × qualifying external stake, 50,000 SOL)` gives 500/5,000/25,000 SOL for these cases; 100,000 qualifying SOL reaches the match ceiling. "
    validator_text += "Foundation principal and delegator rewards stay outside hill custody. Only separately agreed operator commission routing can add rider money. "
    validator_text += "Eligibility remains conditional; the dated [FAQ](https://solana.org/faq) and [criteria](https://solana.org/delegation-criteria) require performance/concentration/testnet conditions and commission ceilings, and vote support ends after 180 epochs.\n\n"
    validator_text += table(["Stake SOL", "Gross operator commission SOL/26 weeks", "Retained from that commission if 100% routed", "Matched-stake rider USD/week /26 weeks ONLY if separately routed"],
                           [[r["stake_sol"], number(r["operator_gross_inflation_commission_sol_season"]), 0,
                             " / ".join(money(r["matched_commission_only_if_separately_routed"][k]["rider_usd"]) for k in ("week", "season"))] for r in vr])
    validator_text += "\n\nWhat the operator gets: external delegation, potential retained commission/MEV/block revenue and recognition, less contribution and operating costs; no net profit is established. "
    validator_text += "Routing all modeled commission retains zero of that commission. Full-yield hill backing instead retains its principal subject to lot losses/exit rules and can earn backer DUNG from actual TSS; operator commission is not automatically donated. "
    validator_text += "External delegation/SAM/commission routing earns no hill backing credit, Founder title or DUNG. Actual retention value, costs and earned hill DUNG cannot be inferred from delegation size alone.\n\n"
    validator_text += table(["SOL/USD", "Gross APR", "Stake USD needed for $1M/year to riders", "Required SOL", "5,000-SOL pilot: rider USD/year"],
                           [[number(r["scenario"].split("_")[0], 2), f"{float(r['scenario'].split('_')[1]) * 100:g}%", money(r["required_stake_usd"]), number(r["required_stake_sol"], 2), money(r["pilot_5000_annual_rider_usd"])] for r in validator["million_bound"]])
    validator_text += "\n\nArithmetic: `1,000,000 ÷ (0.052 × 0.95 × 0.90) = $22,492,127.76` staked. "
    validator_text += "This requires all of the owner's net staking yield to be given up, uninterrupted realization and eventual eligible payouts; it is not a commission-routing bound. At 2.2%, the requirement is $53,163,211.06.\n"
    validator_text += footnotes(data, validator["assumptions"], validator["source"])

    whale = data["whale"]
    wb = next(r for r in whale["pilot"]["budgets"] if r["scenario"] == default)
    whale_text = table(["Pilot commitment", "Principal USD", "Forgone SOL/week /26 weeks", "Stage1 available rider USD/week /26 weeks", "Backer DUNG/week /26 weeks"],
                       [["500 SOL ×10 hills =5,000 SOL", money(wb["stake_usd"]),
                         f"{number(wb['week']['net_income_sol'])} / {number(wb['season']['net_income_sol'])}",
                         f"{money(wb['week']['rider_usd'])} / {money(wb['season']['rider_usd'])}",
                         f"{number(whale['pilot']['backer_dung_week'])} /{number(whale['pilot']['backer_dung_season'])}"]])
    whale_text += "\n\n[TIM: framing]\n\nDefault $120.74/SOL, 5.2% gross APR. Stage1 budget is ideal realized-yield capacity after commission/fee. "
    whale_text += f"A4 assumes 18 ascents/hill/week and 6 TSS/ascent with the field. The sole backer gets the fixed backer half, {whale['pilot']['founder_titles']} Founder titles, an initial allocation weight of {number(whale['pilot']['initial_backer_allocation_weight_per_hill'])} per hill, and {number(whale['pilot']['backer_vote_weight_while_active'])} accumulated earned-DUNG vote weight after 26 eligible weeks while stake remains. "
    whale_text += "No priced DUNG, purchased vote or stage1 CAL claim income. The JSON's exact one-hill token ledgers are samples; do not sum separately rounded fee ledgers as an exact ten-hill deployment.\n\n"
    whale_text += "Pilot limits use running deposit-time basis: 500 SOL per hill, 5,000 total, 2,000 per token. This commitment fills both hill and deployment limits and needs at least three enabled token exposures; the enabled mint list is unknown. "
    whale_text += "Remaining principal in exit still consumes intake capacity until returned. Appreciation does not enlarge deposit-basis intake under the later brief decision; the existing oracle's older marked-exposure cap is not that implementation. "
    whale_text += "Founding lots lock 26 weeks then require four weeks' notice and liquidity; no instant principal exit.\n\n"
    hd = next(r for r in whale["honest_500_tournament"] if r["scenario"] == default)
    result, actor = hd["result"], hd["result"]["totals"]["whale"]
    first = hd["first_26_weeks"]
    whale_text += table(["honest_long comparison through 26 weeks", "Offline result"],
                        [["Whale-funded rider hill pay USD", money(first["whale_funded_rider_pay_usd"])],
                         ["Whale CAL-claim cash receipts USD", money(first["whale"]["hill_pay_usd"])],
                         ["Whale economic cash after forgone yield USD", money(first["whale"]["economic_cash_usd"])],
                         ["Whale DUNG (no USD price)", number(first["whale"]["dung"])]]) + "\n\n"
    whale_text += table(["52-week honest_long market comparison", "Offline result"],
                        [["Whale principal /community principal SOL", "5,000 /100"],
                         ["Whale-funded rider hill pay USD", money(sum(result["whale_rider_pay_usd"].values()))],
                         ["Whale CAL-claim cash receipts USD", money(actor["hill_pay_usd"])],
                         ["Whale CAL purchases USD", money(result["amm_buy_outlay_usd"]["whale"])],
                         ["Whale economic cash after forgone yield USD", money(actor["economic_cash_usd"])],
                         ["Whale DUNG (no USD price)", number(actor["dung"])],
                         ["Future committed yield cost beyond horizon USD", money(result["whale_remaining_yield_cost_usd"])],
                         ["Admission", "Not pilot-admissible: 510/hill; 5,100 total; proposed 104-week second lot"]])
    whale_text += "\n\nA9 adapts each of honest_long's two whale lots to 250 SOL, without changing the reference model or hiding its community addition. "
    whale_text += "There is no unchanged tournament run for exactly 500 sole-whale SOL/hill inside the pilot. This comparison includes modeled stages 2/3, funded sponsor gifts, CAL trading and proposed long backing; it is not the stage1 promise. "
    whale_text += "Its full phase accounts distinguish hill cash, CAL cash, token marks, liquidation estimates and principal.\n\n"
    defaults = [r for r in whale["tournament"] if r["scenario"] == default and r["condition"] == "default"]
    whale_text += table(["Ratified-default strategy, 52 weeks", "Whale economic cash USD", "Whale-funded rider hill pay USD", "Whale DUNG"],
                        [[r["strategy"], money(r["result"]["totals"]["whale"]["economic_cash_usd"]), money(sum(r["result"]["whale_rider_pay_usd"].values())), number(r["result"]["totals"]["whale"]["dung"])] for r in defaults])
    whale_text += "\n\nEvery listed strategy retains immediate earned-CAL sale and the hardened ladder. Default backing sizes here are the original model's, not 500/hill. "
    whale_text += "P1 and phase rider cash checks are preserved in every run; funded payouts do not imply a profitable whale, retained-CAL investor or rider after real costs.\n\n"
    winners = []
    for strategy in STRATEGIES:
        candidates = [r for r in whale["tournament"] if r["strategy"] == strategy]
        best = max(candidates, key=lambda r: r["result"]["totals"]["whale"]["economic_cash_usd"])
        profit = best["result"]["totals"]["whale"]["economic_cash_usd"]
        if profit > 0:
            winners.append([strategy, best["scenario"], best["condition"], money(profit),
                            money(best["result"]["totals"]["late_buyers"]["liquidation_usd"]), money(best["result"]["totals"]["lp"]["liquidation_usd"])])
    whale_text += table(["Positive cash witness (selected cells)", "SOL price_APR", "Condition", "Whale USD", "Late-buyer liquidation P&L USD", "LP liquidation P&L USD"], winners)
    whale_text += "\n\n`thin_high_demand` means $1,000 starting AMM depth, 50 riders, 40% regulars and 4× assumed speculator bids; `high_demand` uses the same inputs at $10,000 depth. "
    whale_text += "`zero_speculators` sets speculative bids to zero. These are selected sensitivities, not the full factorial or a universal ranking. All actor/phase accounts, six price/APR pairs and every nonpositive result remain in JSON. "
    whale_text += "A crew can win riding cash/CAL/DUNG only with the assumed distinct verified people and real riding; defaults omit wages/riding costs. DUNG accumulation earns unpriced voting weight, not demonstrated cash profit; wash volume earns no protocol reward.\n\n"
    control = next(r for r in whale["controls"] if r["scenario"] == default)
    u, cheap = control["unfunded_trader"], control["cheap_claim"]
    whale_text += f"Pure-trader control: ${u['whale_cost_usd']:,} buy, ${3000:,} later buyer, {money(u['whale_profit_usd'])} whale profit, zero whale-funded rider pay; "
    whale_text += f"late buyer loses {money(-u['late_buyer_liquidation_pnl_usd'])} on liquidation and LP gains {money(u['lp_usdc_gain_after_late_exit'])}. "
    whale_text += "The hardened default ladder activates zero in the default ladder-pump run, but its liquid CAL trading can still profit from other buyers; activation is not required for that profit. "
    whale_text += f"Cheap-claim control: {number(cheap['cost_usd'], 3)} USDC buys {number(cheap['locked_cal'])} CAL locked for 104 weeks and receives {number(cheap['first_week_claim_usd'])} USD in week one from somebody else's funded yield. "
    whale_text += "This assumes negligible costs and fixed competition; competing claimants give up that share. Purchases pay the actual market seller/LP, not necessarily a rider. "
    whale_text += "Immediate sellers remove retained-CAL exposure from the default rider cohort; optional holders can still lose marked value. No protocol principal funds those trading gains.\n"
    whale_text += footnotes(data, whale["assumptions"], whale["source"] + ["design"])
    return {"club.md": club_text, "sponsor.md": sponsor_text, "validator.md": validator_text, "whale.md": whale_text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT / "numbers.json")
    parser.add_argument("--check", action="store_true", help="Compare regenerated bytes without writing")
    args = parser.parse_args()
    data = build()
    content = json.dumps(data, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.check:
        if args.output.read_text() != content:
            raise SystemExit("numbers.json differs; regenerate")
        print("numbers.json reproduces exactly")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
        print(f"Wrote {args.output.relative_to(ROOT) if args.output.is_relative_to(ROOT) else args.output}: {len(content):,} bytes")
    for name, content in documents(data).items():
        destination = args.output.parent / name
        if args.check:
            if destination.read_text() != content:
                raise SystemExit(f"{name} differs; regenerate")
        else:
            destination.write_text(content)


if __name__ == "__main__":
    main()
