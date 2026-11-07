"""Render the bounded research report directly from the saved tournament data."""
import json
from pathlib import Path
from .config import DEFAULT_PATH


def money(value):
    precision = 3 if 0 < abs(value) < 0.01 else 2
    return ('-' if value < 0 else '') + f'${abs(value):,.{precision}f}'


def render(data):
    defaults, grid, controls = data['defaults'], data['grid_summary'], data['controls']
    p = data['parameters']
    cfg = p['model']['default']
    trader, drawdown = controls['unfunded_trader'], controls['legacy_holder_drawdown']
    legacy = controls['named_scenarios']['legacy_hold_base_ladder']
    p3_failures = sum(g['P3_cash_failures'] for g in grid.values())
    corner_best = max((r for r in data['grid_runs'] if r['strategy'] == 'livermore_corner'), key=lambda r: r['totals']['whale']['economic_cash_usd'])
    best = corner_best['scenario']
    corner_ratio = corner_best['whale_profit_to_independent_rider_pay']
    ratio_text = f'{corner_ratio:.2f}×' if corner_ratio is not None else 'undefined'
    pieces = [f'''# Economy reference model and whale strategy tournament

Offline simulation, updated 13 October 2026. These numbers are conditional experiments, not forecasts, live markets or physical rider evidence.

All {data['grid_count']:,} factorial runs preserve funding. Riders receive positive cash before riding costs, but retained CAL can lose wealth. An unfunded trader earns {money(trader['whale_profit_usd'])} while paying riders nothing. Profitable corners and boosts depend on assumed outside bids. Backing remains a contribution.

**Ratified by Tim, 13 October:** riders can sell CAL as soon as earned; the app shows cash and token value separately. The promise is **every payout is funded, and riders are paid in every phase**, replacing universal trader-funded-rider profit claims. Ladders require a deep enough market, an independent price reference and a real riding field.

Defaults are now `model.default.immediate_cal_sale: true` and `model.default.hardened_ladder: true`. Existing parameters are unchanged; numerical model inputs remain unratified. `tools/economy_reference/` contains Python 3.12 code and 32 tests; `results.json` contains the grid and legacy comparisons. The original golden and product code are unchanged.

**Method.** The factorial crosses SOL at $60.37/$120.74, gross yield 2.2%/5.2%, AMM depth $1,000/$10,000, 50/300 weekly riders, 40%/80% regulars, speculation zero/four, and stage 2 off/on. Each strategy has 128 cells, ten hills and 52 weeks. Scale cases pair five hills/26 weeks and twenty hills/104 weeks. Seed {p['model']['seed']} fixes performances. Tests add 500 accounting cases and 40 agent paths at five hills, 50 riders and 26 weeks across five seeds.

All eight tables show **phase economic cash P&L in USD**, including forgone ordinary staking yield and AMM execution, excluding principal and unsold inventory. Divide each amount by $120.74 for SOL equivalents; JSON stores both denominations for every actor/phase, plus spot-marked and joint-liquidation values. Phases are accumulation, markup, distribution and exit, thirteen weeks each. Sponsor P&L is −$3,250 each phase, including pool gifts; the optional validator is off. LP columns show cash changes while inventory remains, not total investment returns.
''']
    descriptions = {
        'honest_long': ('Honest long backer', 'Found every hill, add long backing, buy and lock claims, then hold. This commits 2,000 SOL and buys $5,000 CAL. Beyond the table, remaining mandatory yield costs another ' + money(defaults['honest_long']['whale_remaining_yield_cost_usd']) + '; locked CAL is not an immediate cash exit.'),
        'livermore_corner': ('Livermore’s corner', 'Back ten hills with 1,000 SOL, accumulate $10,000 liquid CAL, wait for speculative buying, sell during distribution, then exit after lock and notice. Default riders sell their new CAL throughout.'),
        'back_and_dump': ('Back-and-dump', 'Use the same budget, sell in markup, exit when legal. Its best grid result is ' + money(grid['back_and_dump']['best_cash_usd']) + '. This is not a universal verdict on early sales.'),
        'crew_ride': ('The crew ride', 'Back with 1,000 SOL and send ten distinct crew riders seven times weekly. Here the population is 80 regulars, ten visitors and ten crew. The whale alone loses; combining crew receipts gives ' + money(defaults['crew_ride']['whale_plus_crew_cash_usd']) + '. A $1/ascent riding-cost and wage stress changes that coalition to ' + money(controls['crew_cost_stress']['whale_plus_crew_cash_usd']) + '.'),
        'boost_then_dump': ('Boost-then-dump', 'Buy $10,000 CAL, escrow a $2,000 eight-week boost on two hills during markup, and sell in distribution. No SOL backing or purchased DUNG; the boost remains payable.'),
        'ladder_pump': ('The ladder pump', 'Escrow three 100-SOL tranches at $0.012/$0.020/$0.030 CAL, then trade the same $10,000 budget. The hardened seven-day trigger activates ' + str(int(defaults['ladder_pump']['ladder_activated_sol'])) + ' SOL, versus ' + str(int(legacy['ladder_pump']['ladder_activated_sol'])) + ' SOL with both legacy behaviors. Stage-2-off cells cannot activate ladders.'),
        'dung_accumulation': ('DUNG accumulation', 'Commit 2,000 SOL, buy no CAL, collect ' + f"{defaults['dung_accumulation']['totals']['whale']['dung']:.2f}" + ' DUNG and direct votes toward one hill. DUNG has no assigned cash value. Like honest backing, mandatory yield continues beyond the horizon.'),
        'wash_trading': ('Wash trading', 'Round-trip $2,000 weekly through the external AMM. Volume produces no protocol income or reward; both swap legs pay fees. Every grid case loses cash.'),
    }
    columns = [('whale', 'Whale'), ('regulars', 'Regular'), ('visitors', 'Visitor'), ('crew', 'Crew'), ('community', 'Backers'), ('speculators', 'Spec.'), ('late_buyers', 'Late'), ('protocol', 'Fee'), ('lp', 'LP')]
    for strategy, (title, explanation) in descriptions.items():
        r = defaults[strategy]
        pieces.append(f'\n**{title}.** {explanation}\n\nAssumptions: 10 hills/52 weeks; $120.74/SOL; 5.2% gross APR; $10,000 AMM; stages 2+3; speculation=1; immediate CAL sale; hardened ladders.\n')
        pieces.append('| Phase | ' + ' | '.join(label for _, label in columns) + ' |\n')
        pieces.append('|---|' + '---:|' * len(columns) + '\n')
        for phase in r['phases']:
            pieces.append('| ' + phase['phase'].capitalize() + ' | ' + ' | '.join(f"{phase['actors'][actor]['economic_cash_usd']:,.0f}" for actor, _ in columns) + ' |\n')
        g = grid[strategy]
        pieces.append(f"\nGrid: {g['profitable_cash_runs']}/128 cash-positive whales; range {money(g['worst_cash_usd'])} to {money(g['best_cash_usd'])}.\n")
    pieces.append(f'''
**Property verdicts and loss bearers.**

**P1 passes locally.** Every settlement checks SOL/USDC conservation by source, including holds. Principal and AMM trades never fund the vault. Founder multipliers redistribute the fixed backer half without increasing issuance. Actor economic cash plus held vault money reconciles, adding back expenses in cost stresses. This does not prove chain custody, staking realization or identity verification.

**P2 passes under the narrow default cash assumptions.** All grid phases pass before riding costs. The legacy retained-CAL control receives {money(drawdown['phase_cash_usd'])} but changes wealth by {money(drawdown['phase_marked_usd'])}. With the ratified immediate-sale default, the paired control gains {money(controls['holder_drawdown']['phase_marked_usd'])}. Cash and token valuation stay separate. Voluntary sale removes retained-inventory exposure in this model; it does not cover cycling costs or guarantee every execution price.

**Universal P3 is disproven and retired.** The grid retains {p3_failures} diagnostic failures. The independent trader spends $1,000, receives {money(trader['whale_proceeds_usd'])}, and pays riders $0: profit/payment is undefined. At the same executable endpoint, the later buyer loses {money(-trader['late_buyer_liquidation_pnl_usd'])} and the LP gains {money(trader['lp_usdc_gain_after_late_exit'])}. The best funded corner's profit/delivered independent-rider pay is {ratio_text}. JSON retains source payments and phase accounts; timing is checked at phase boundaries.

A still-unratified own-funding prerequisite changes the cheap outside-capital claim's one-week result from {money(controls['cheap_claim']['first_week_cash_profit_usd'])} to {money(controls['cheap_claim_own_funding_gate']['first_week_cash_profit_usd'])}. It damages the claim game and leaves free trading's {money(trader['whale_profit_usd'])} intact. It is not a default. The ledger probe rejects an unfunded payout, supporting the ratified funding promise without asserting control over external trading.

**P4 is mixed; P5 is explicit.** The best corner uses {best['riders']} riders, {best['regular_fraction']:.0%} regulars, {money(best['sol_usd'])}/SOL, {best['gross_apr']:.1%} APR, {money(best['market_depth_usdc'])} depth, speculation={best['speculator_intensity']} and stage 2 {'on' if best['stage2'] else 'off'}. Backers bear forgone yield, sponsors bear cash costs, traders/LPs bear execution and inventory outcomes, and riders bear real riding costs plus repricing if they choose to hold. Crew receipts depend on actual riding, outside subsidies and free labor. Selling to late buyers does not establish their profit.

**Whale playbook.** The **claim** can recover yield on others' backing: a one-week $0.001 purchase returns about $0.027 with zero gas cost and little competition. This existence witness is not a viable quote. The **founder** crosses the line for a title and normalized DUNG weight, without a record seat. Ten SOL through 30 weeks costs 0.285 SOL at default yield. The **territory** buys influence: DUNG directs approximately {money(defaults['dung_accumulation']['pool_allocated_usd_by_hill']['0'])} toward its chosen hill, subject to the ascent cap, for {money(-defaults['dung_accumulation']['totals']['whale']['economic_cash_usd'])} in forgone yield. The backer receives no pool income.

The **duration** game extends modeled committed claim value; its financial win is not established. The **ladder** can win funded activation when all three ratified checks pass. Default activation is {int(defaults['ladder_pump']['ladder_activated_sol'])} SOL; the $20,000-depth control activates {int(controls['ladder_hardened_deep']['ladder_activated_sol'])} SOL. Unit tests exercise valid activation and refuse missing reference/field, insufficient depth and excessive price divergence. Trading can profit while activation is rejected; hardened triggers do not restore P3.

The **boost** spends $2,000 to fund chosen riding. Without response, its window has {defaults['boost_then_dump']['boosted_window_ascents']} target-hill ascents; a hypothetical 25% routing response produces {controls['boost_response']['boosted_window_ascents']}, with total rides unchanged. The **season** buys association: $20 weekly funds $520 over 26 weeks on one hill, without fees or DUNG. Advertising is unpriced. A cash-winning version of every game is **not established**. State the objective before calling a game won; zero-speculator reruns expose dependence on outside buying.

**Assumptions and remaining limits.** All numbers come from `diamond.yaml`. Defaults use 100 riders, normally 80 regulars/20 new visitors weekly; regulars ride twice, visitors once, and each ascent supplies six eligible climb-TSS. Off-hill issuance is zero. All riders sell earned CAL, discretized across daily market steps after weekly issuance accounting. This models immediate-sale availability, not compulsory product sales. `legacy_hold` restores regulars' 15% sale, 250-CAL hold threshold and half-release at a threefold rise. `legacy_base_ladder` restores the old trigger; `legacy_hold_base_ladder` restores both. All three rerun eight strategies. Synthetic momentum/late bids use $150/$600 weekly bases, a 25% attention term and bounded price response, not calibrated demand.

The LP starts with historically earned CAL at $0.01 and $10,000 USDC; its 0.3% fee is external. Community backing is ten SOL/hill and CAL buying $5/week. Sponsors contribute $20/hill/week plus $50 pool gifts. Yield has 5% validator commission. SOL price/yield stay fixed per scenario; principal depreciation, taxes, borrowing, redemption, gas, failures and real-world verification are absent. Default riding costs and wages are zero; attention, titles and DUNG have no dollar valuation.

Claims use net yield only; cash remains entirely rider-directed. Calendar seasons gate records/DUNG; permanent top-ten seats survive rollover, and Local Legend uses season ascents with deterministic ties. The median cap combines positive direct recipients across sources/assets; CAL claims are separate. Cap excess waits for its recipient, expires before release at a season, then joins a gift-started pool. Pool allocation renews that hold deadline. These interpretations are unratified.

CAL timers are hill-specific; bonded ascents refresh earned rider DUNG; backer votes follow individual lots. Longer backing and boosts remain proposals; ladder hardening is ratified. Unactivated escrow yield cancels against the staking baseline. The independent price reference is synthetic, not a production oracle. Depth/field/divergence numbers remain unratified. Committed claim value assumes unchanged yield/eligibility and no dilution: an upper-bound stream, never a redemption floor. JSON separates cash, marked and joint-liquidation values; locked CAL is not immediately liquid. No-whale, zero-speculation, validator, cost and legacy controls remain inspectable.
''')
    return ''.join(pieces)


def main():
    directory = DEFAULT_PATH.parents[1] / 'economy-tournament-2026-10-08'
    data = json.loads((directory / 'results.json').read_text())
    text = render(data)
    words = len(text.split())
    if not 1500 <= words <= 2500:
        raise ValueError(f'Report has {words} whitespace words, expected brief range')
    (directory / 'RESULTS.md').write_text(text)
    print(f'RESULTS.md: {words} words; 8 strategy tables generated from results.json')


if __name__ == '__main__':
    main()
