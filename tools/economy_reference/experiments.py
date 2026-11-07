"""Adversarial controls, named legacy comparisons and unratified claim experiments."""
from .accounting import Claim, Ledger, Settlement, claim_weights
from .market import Market
from .simulation import STRATEGIES, run


def unfunded_trader(p):
    c = p['model']['property_checks']
    market = Market(p, p['model']['default']['market_depth_usdc'])
    tokens, _ = market.buy(c['unfunded_bid_usdc'])
    late, _ = market.buy(c['unfunded_late_bid_usdc'])
    proceeds = market.sell(tokens, 'whale')
    market.assert_conserved()
    empty_ledger = Ledger(p)
    unfunded = empty_ledger.receive('h', 'USDC', 0, 'whale', 0)
    refused = False
    try:
        empty_ledger.pay(unfunded, 'whale', c['unfunded_bid_usdc'])
    except ValueError:
        refused = True
    empty_ledger.assert_conserved()
    return {'whale_cost_usd': c['unfunded_bid_usdc'], 'whale_proceeds_usd': proceeds,
            'whale_profit_usd': proceeds - c['unfunded_bid_usdc'],
            'whale_rider_pay_usd': 0, 'profit_to_rider_pay': None,
            'late_buyer_liquidation_pnl_usd': market.liquidation(late) - c['unfunded_late_bid_usdc'],
            'late_buyer_marked_pnl_usd': late * market.price - c['unfunded_late_bid_usdc'],
            'lp_usdc_change_before_late_exit': market.usdc - market.initial_usdc,
            'lp_usdc_gain_after_late_exit': market.usdc - market.initial_usdc - market.liquidation(late),
            'P3': proceeds <= c['unfunded_bid_usdc'],
            'ratified_promise': 'Every payout is funded, and riders are paid in every phase. Ratified 13 Oct 2026; free secondary transfers do not require profitable traders to fund riders.',
            'unfunded_protocol_payment_refused': refused,
            'unfunded_protocol_payments_usd': empty_ledger.payouts['USDC']}


def cheap_claim(p, own_funding_gate=False):
    c = p['model']['property_checks']
    market = Market(p, p['model']['default']['market_depth_usdc'])
    tokens, _ = market.buy(c['claim_bargain_usdc'])
    riders = {f'r{i}': 1 for i in range(p['min_field_riders'])}
    claims = [Claim(who, p['example_hill']['climb_tss_per_ascent'], 0, p['timer_weeks'], False) for who in riders]
    # Candidate rule: capital claims require that claimant's prior delivered rider funding.
    # This claimant has none. Bought tokens still exist and the trade still costs money.
    if not own_funding_gate:
        claims.append(Claim('whale', tokens, 0, p['timer_weeks'], True))
    weights = claim_weights(claims, riders, 0, p)
    ledger = Ledger(p)
    s = Settlement(p, ledger)
    income = p['example_hill']['rewards_sol_per_week'] * (1 - p['example_hill']['validator_commission'])
    s.distribute(0, 'h', 'SOL', income, 'community', riders, list(riders), list(riders)[0], True,
                 yield_income=True, stage2=True, claims=weights)
    s.close_week(p['example_hill']['sol_usd'])
    proceeds = ledger.paid[('whale', 'SOL')] * p['example_hill']['sol_usd']
    return {'candidate_own_funding_gate': own_funding_gate, 'cost_usd': c['claim_bargain_usdc'], 'first_week_claim_usd': proceeds,
            'first_week_cash_profit_usd': proceeds - c['claim_bargain_usdc'],
            'locked_cal': 0 if own_funding_gate else tokens,
            'liquid_cal': tokens if own_funding_gate else 0,
            'lock_weeks': 0 if own_funding_gate else p['timer_weeks'],
            'donor_income_sol': income, 'whale_backing_sol': 0,
            'condition': 'An extremely small, cheap claim on somebody else\'s realized yield; no gas cost, competition fixed for this one week.',
            'P3_whale_funded_riders': proceeds <= c['claim_bargain_usdc'],
            'P3_same_funding_stream_paid_riders': sum(v for (who, asset), v in ledger.paid.items() if who in riders) > 0}


def holder_drawdown(p, autosell=None):
    if autosell is None:
        autosell = p['model']['default']['immediate_cal_sale']
    c = p['model']['property_checks']
    market = Market(p, p['model']['default']['market_depth_usdc'])
    held = c['marked_rider_cal']  # explicitly pre-existing earned CAL; opening wealth is not revenue
    realized = market.sell(held, 'regulars') if autosell else 0
    if autosell:
        held = 0
    whale, _ = market.buy(c['attention_buy_usdc'])
    start_marked = realized + held * market.price
    market.sell(whale, 'whale')
    income = c['donor_gift_usdc']
    end_marked = realized + held * market.price + income
    market.assert_conserved()
    return {'auto_sell_earned_cal': autosell, 'phase_cash_usd': income,
            'phase_marked_usd': end_marked - start_marked,
            'opening_marked_usd': start_marked, 'ending_marked_usd': end_marked,
            'P2_cash': True, 'P2_marked': end_marked >= start_marked,
            'assumption': 'Two-phase control, existing earned inventory, one outside round trip, fixed sponsor gift; paper repricing is not a cash transfer.'}


def controls(p):
    return {'unfunded_trader': unfunded_trader(p), 'cheap_claim': cheap_claim(p),
            'cheap_claim_own_funding_gate': cheap_claim(p, True),
            'unfunded_trader_after_claim_gate': unfunded_trader(p),
            'holder_drawdown': holder_drawdown(p), 'legacy_holder_drawdown': holder_drawdown(p, False),
            'no_whale': run(p, 'no_whale'),
            'zero_speculators': {s: run(p, s, {'speculator_intensity': 0}) for s in STRATEGIES},
            'named_scenarios': {name: {s: run(p, s, scenario=name) for s in STRATEGIES}
                                for name in p['model']['scenarios']},
            'crew_cost_stress': run(p, 'crew_ride', fixes=('crew_wages', 'riding_cost')),
            'ladder_hardened_deep': run(p, 'ladder_pump', {'market_depth_usdc': p['model']['whale']['ladder_fix_depth_usdc']}),
            'boost_response': run(p, 'boost_then_dump', {'boost_response_fraction': p['model']['property_checks']['boost_response_fraction']}),
            'validator_contribution': run(p, 'honest_long', {'validator': True})}
