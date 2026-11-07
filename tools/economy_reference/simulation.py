"""Parameterized agents, actual AMM execution, and phase-by-phase economic accounts."""
from collections import defaultdict, deque
from dataclasses import dataclass
import math
import random

from .accounting import (Claim, DungVote, Hill, Ledger, Settlement, claim_weights,
                         dung_allocation, pool_allocation, proportional, reset_earned_rider_timers)
from .market import Boost, Ladder, Market

STRATEGIES = {
    'honest_long': 'Bond; add a long commitment; buy and lock claims; hold through the horizon.',
    'livermore_corner': 'Back all hills; accumulate liquid CAL; invite momentum bids; distribute; notice and exit when legal.',
    'back_and_dump': 'Back all hills; accumulate CAL; sell in markup; give notice at lock expiry; exit after notice.',
    'crew_ride': 'Back all hills; field distinct verified crew riders; collect riding pay/CAL/DUNG; notice and exit.',
    'boost_then_dump': 'Buy CAL; post an irrevocable boost in markup; sell in distribution; hold no backing.',
    'ladder_pump': 'Escrow capped SOL steps; accumulate CAL; trigger trailing daily-price/depth checks; sell; respect activated locks.',
    'dung_accumulation': 'Found hills; add long backing; accumulate DUNG; steer gifts toward a chosen hill; hold.',
    'wash_trading': 'Round-trip through the AMM each week; pay both swap fees; receive no volume rewards.',
}
ACTORS = ('whale', 'regulars', 'visitors', 'crew', 'community', 'sponsors',
          'speculators', 'late_buyers', 'validator', 'protocol', 'lp')
RIDER_CLASSES = ('regulars', 'visitors', 'crew')


@dataclass
class Ride:
    rider: str
    day: int
    uploaded_day: int
    seconds: float
    tss: float


class Board:
    """Input identities/verification are trusted; this is not a fraud detector."""
    def __init__(self, p):
        self.p = p
        self.best = {}
        self.last_ascent = {}
        self.season_people = set()
        self.season_ascents = defaultdict(int)
        self.season = None
        self.seen = set()
        self.closed_week = -1

    def freeze(self, week, rides):
        if week <= self.closed_week:
            raise ValueError('Settlement week already frozen')
        self.closed_week = week
        season = week // self.p['season_weeks']
        if season != self.season:
            self.season, self.season_people = season, set()
            self.season_ascents.clear()
        ascents, tss = defaultdict(int), defaultdict(float)
        days = self.p['model']['days_per_week']
        for ride in sorted(rides, key=lambda r: (r.uploaded_day, r.day, r.seconds, r.rider)):
            age = ride.uploaded_day - ride.day
            if not 0 <= age <= self.p['upload_window_days'] or ride.uploaded_day // days != week:
                continue
            self.best[ride.rider] = min(self.best.get(ride.rider, math.inf), ride.seconds)
            key = (ride.rider, ride.day)
            if key in self.seen:
                continue
            self.seen.add(key)
            ascents[ride.rider] += self.p['ascents_per_hill_per_day']
            tss[ride.rider] += ride.tss
            self.last_ascent[ride.rider] = week
            self.season_people.add(ride.rider)
            self.season_ascents[ride.rider] += self.p['ascents_per_hill_per_day']
            self.best[ride.rider] = min(self.best.get(ride.rider, math.inf), ride.seconds)
        self.seen = {key for key in self.seen if key[1] >= (week + 1) * days - self.p['upload_window_days']}
        # Permanent record seats, frozen here; a season's field gates their payment.
        self.best = dict(sorted(self.best.items(), key=lambda item: (item[1], item[0]))[:self.p['model']['top_ten_seats']])
        records = list(self.best)
        legend = min(self.season_ascents, key=lambda who: (-self.season_ascents[who], who)) if self.season_ascents else None
        return dict(ascents), dict(tss), records, legend, len(self.season_people) >= self.p['min_field_riders']


def phase_for(week, weeks, p):
    cuts = p['model']['phases']
    for phase, key in (('accumulation', 'accumulation_end'), ('markup', 'markup_end'), ('distribution', 'distribution_end')):
        if week < math.ceil(weeks * cuts[key]):
            return phase
    return 'exit'


def run(p, strategy, overrides=None, *, seed=None, fixes=(), scenario=None):
    if strategy not in STRATEGIES and strategy != 'no_whale':
        raise ValueError(strategy)
    cfg = dict(p['model']['default'])
    if scenario is not None:
        if scenario not in p['model']['scenarios']:
            raise ValueError(f'Unknown named scenario: {scenario}')
        cfg.update(p['model']['scenarios'][scenario])
    cfg.update(overrides or {})
    # Retain the original experiment flags as aliases; report effective behavior.
    if 'cash_only_riders' in fixes:
        cfg['immediate_cal_sale'] = True
    if 'harden_ladder' in fixes:
        cfg['hardened_ladder'] = True
    if cfg['weeks'] <= 0 or cfg['riders'] <= 0 or cfg['hills'] <= 0 or cfg['sol_usd'] <= 0 or cfg['gross_apr'] < 0 or not 0 <= cfg['regular_fraction'] <= 1:
        raise ValueError('Invalid scenario')
    seed = p['model']['seed'] if seed is None else seed
    rng = random.Random(seed)
    m, w, rf = p['model'], p['model']['whale'], p['model']['riders']
    fund, spec = m['funding'], m['speculators']
    sol = cfg['sol_usd']
    weekly_rate = cfg['gross_apr'] * (1 - p['example_hill']['validator_commission']) / m['weeks_per_year']
    hills = {str(i): Hill(str(i), p) for i in range(cfg['hills'])}
    boards = {h: Board(p) for h in hills}
    ledger, market = Ledger(p), Market(p, cfg['market_depth_usdc'])
    settlement = Settlement(p, ledger)
    classes = {a: a for a in ACTORS}
    cash, opportunity, liquid = defaultdict(float), defaultdict(float), defaultdict(float)
    claims = {h: [] for h in hills}
    rider_claim = {}
    last_rider_week = {}
    work = {h: deque(maxlen=p['boost_work_window_weeks']) for h in hills}
    votes = {}
    dung = defaultdict(float)
    directed = defaultdict(float)
    rider_ascent_count = defaultdict(float)
    hill_ascent_count = defaultdict(float)
    boosted_window_ascents = 0
    historical_inventory_buy_attribution = defaultdict(float)
    principal_added = defaultdict(float)
    fees_trade = defaultdict(float)
    boost = ladder = None
    buy_outlay = defaultdict(float)
    notice_sent = set()
    pool_delivered_by_hill = defaultdict(float)
    max_pool_cap_ratio = 0
    regular_count = round(cfg['riders'] * cfg['regular_fraction'])
    crew_count = round(cfg['riders'] * rf['crew_fraction']) if strategy == 'crew_ride' else 0
    regular_count = min(regular_count, cfg['riders'] - crew_count)
    visitor_count = cfg['riders'] - regular_count - crew_count
    backs = strategy in ('honest_long', 'livermore_corner', 'back_and_dump', 'crew_ride', 'dung_accumulation')
    long = strategy in ('honest_long', 'dung_accumulation')
    for name, hill in hills.items():
        # Whale supplies the founding pledge in funded strategies; community adds later.
        if backs:
            hill.pledge('whale', w['stake_sol_per_hill'], 0)
            principal_added['whale'] += w['stake_sol_per_hill']
            if long:
                # Founding money itself retains mandatory 26 weeks; additional long lot is explicit.
                hill.add_stake('whale', w['stake_sol_per_hill'], w['long_lock_weeks'], 0)
                principal_added['whale'] += w['stake_sol_per_hill']
            hill.add_stake('community', fund['community_sol_per_hill'], p['bond_lock_weeks'], 0)
        else:
            hill.pledge('community', fund['community_sol_per_hill'], 0)
        principal_added['community'] += fund['community_sol_per_hill']
    if strategy == 'ladder_pump' and cfg['stage2']:
        ladder = Ladder(p, w['ladder_prices_usdc'], w['ladder_sol_per_step'])

    def actor(who):
        return classes.get(who, who)

    def buy(who, dollars, hill=None, lock=None, week=0):
        if dollars <= 0:
            return 0
        amount, origins = market.buy(dollars)
        cash[who] -= dollars
        buy_outlay[who] += dollars
        fees_trade[who] += dollars * m['market']['swap_fee']
        if who == 'whale':
            for origin, value in origins.items():
                historical_inventory_buy_attribution[origin] += value
        if hill is None:
            liquid[who] += amount
        else:
            claims[hill].append(Claim(who, amount, week, lock, True))
        return amount

    def sell(who, amount):
        if amount <= 0:
            return
        if amount > liquid[who] + m['epsilon']:
            raise ValueError('Selling unavailable CAL')
        before = market.price
        dollars = market.sell(amount, actor(who))
        liquid[who] -= amount
        cash[who] += dollars
        fees_trade[who] += amount * before * m['market']['swap_fee']

    def token_balances(week):
        balances = defaultdict(float)
        unlocked = defaultdict(float)
        for who, value in liquid.items():
            balances[actor(who)] += value
            unlocked[actor(who)] += value
        for positions in claims.values():
            for c in positions:
                balances[actor(c.owner)] += c.amount
                if not c.capital or week >= c.start + c.duration:
                    unlocked[actor(c.owner)] += c.amount
        return balances, unlocked

    def snapshot(week):
        balances, unlocked = token_balances(week)
        aggregate_exit = market.liquidation(sum(unlocked.values()))
        exit_values = proportional(aggregate_exit, unlocked)
        actual = defaultdict(float)
        hillpay = defaultdict(float)
        for who, value in cash.items():
            actual[actor(who)] += value
        for (who, asset), amount in ledger.paid.items():
            value = amount * (sol if asset == 'SOL' else 1)
            actual[actor(who)] += value
            hillpay[actor(who)] += value
        actual['protocol'] += ledger.fees['SOL'] * sol + ledger.fees['USDC']
        actual['lp'] = market.usdc - market.initial_usdc
        result = {}
        for a in ACTORS:
            net = actual[a] - opportunity[a]
            marked = net + balances[a] * market.price
            liquidation = net + exit_values.get(a, 0)
            if a == 'lp':
                marked = market.usdc + market.cal * market.price - market.initial_usdc - market.initial_cal * m['market']['initial_cal_usdc']
                liquidation = market.usdc - aggregate_exit - market.initial_usdc
            result[a] = {'cash_usd': actual[a], 'opportunity_cost_usd': opportunity[a],
                         'economic_cash_usd': net, 'marked_usd': marked, 'liquidation_usd': liquidation,
                         'hill_pay_usd': hillpay[a], 'cal': balances[a], 'dung': dung[a]}
        return result

    def source_rider_pay(source):
        by_class = defaultdict(float)
        for (funder, recipient, asset), amount in ledger.transfers.items():
            if funder == source and actor(recipient) in RIDER_CLASSES:
                by_class[actor(recipient)] += amount * (sol if asset == 'SOL' else 1)
        return {a: by_class[a] for a in RIDER_CLASSES}

    phases = []
    before = snapshot(0)
    previous_price = market.price
    peak_price = market.price
    minted_cal = 0
    daily = m['days_per_week']
    price_path = []
    last_states = {}
    for week in range(cfg['weeks']):
        phase = phase_for(week, cfg['weeks'], p)
        # Legal exits: no notice before each lot's lock; no early CAL release.
        for hill in hills.values():
            for owner in ('whale',):
                if not long:
                    for index, stake in enumerate(hill.stakes):
                        if stake.owner == owner and stake.notice_at is None and week >= stake.start + stake.lock:
                            hill.notice_lot(index, week)
                    hill.withdraw(owner, week)
        for positions in claims.values():
            for c in positions:
                if c.capital and week >= c.start + c.duration and c.amount:
                    liquid[c.owner] += c.release(week)

        if strategy == 'boost_then_dump' and boost is None and phase == 'markup':
            boost = Boost(p, w['boost_usdc'], week, w['boost_weeks'])
            cash['whale'] -= boost.amount
            boost_hills = list(hills)[:w['boost_hill_count']]
            for h in boost_hills:
                for offset in range(boost.weeks):
                    ledger.receive(h, 'USDC', boost.amount / boost.weeks / len(boost_hills), 'whale', week,
                                   kind='boost', available=week + offset)
        if ladder is not None:
            for amount in ladder.activate(market, week * daily, hardened=cfg['hardened_ladder'],
                                           independent_price=m['market']['initial_cal_usdc'],
                                           verified_riders=min((len(b.season_people) for b in boards.values()), default=0)):
                destination = min(hills, key=lambda h: (hills[h].principal, h))
                hills[destination].add_stake('whale', amount, p['bond_lock_weeks'], week)
                principal_added['whale'] += amount

        # Inputs are verified synthetic rides. Actual eligible TSS, not buy flow, mints CAL.
        rides = {h: [] for h in hills}
        for group, count, ascents in (('regulars', regular_count, rf['regular_ascents_week']),
                                      ('crew', crew_count, rf['crew_ascents_week']),
                                      ('visitors', visitor_count, rf['visitor_ascents_week'])):
            for index in range(count):
                who = f'{group}:{week}:{index}' if group == 'visitors' else f'{group}:{index}'
                classes[who] = group
                destination = str(index % len(hills))
                if boost is not None and boost.due(week) and cfg['boost_response_fraction']:
                    if rng.random() < cfg['boost_response_fraction']:
                        destination = str(index % min(w['boost_hill_count'], len(hills)))
                time = rf['time_base_seconds'] + rng.random() * rf['time_spread_seconds']
                if group == 'crew':
                    time -= rf['crew_time_advantage_seconds']
                for day in range(min(ascents, daily)):
                    rides[destination].append(Ride(who, week * daily + day, week * daily + day, time, p['example_hill']['climb_tss_per_ascent']))
        sale = defaultdict(float)
        states = {}
        for h, hill in hills.items():
            ascents, tss, records, legend, field = boards[h].freeze(week, rides[h])
            states[h] = (ascents, records, legend, field)
            hill_ascent_count[h] += sum(ascents.values())
            if boost is not None and boost.due(week) and h in list(hills)[:w['boost_hill_count']]:
                boosted_window_ascents += sum(ascents.values())
            work[h].append(tss)
            for who, n in ascents.items():
                cls = actor(who)
                if hill.bonded:
                    last_rider_week[who] = week
                rider_ascent_count[cls] += n
                cash[who] -= n * (rf['cost_stress_per_ascent_usdc'] if 'riding_cost' in fixes else rf['cost_per_ascent_usdc'])
                if cls == 'crew':
                    wage = w['crew_wage_stress_per_ascent_usdc'] if 'crew_wages' in fixes else w['crew_wage_per_ascent_usdc']
                    cash['whale'] -= n * wage
                    cash[who] += n * wage
                amount = tss[who] * p['cal_per_paid_tss']
                minted_cal += amount
                key = (h, who)
                c = rider_claim.get(key)
                if c is None or c.amount == 0:
                    c = rider_claim[key] = Claim(who, 0, week, p['timer_weeks'], False)
                    claims[h].append(c)
                c.reset(week, p)
                fraction = rf['visitor_sell_fraction'] if cls == 'visitors' else rf['crew_sell_fraction'] if cls == 'crew' else rf['regular_sell_fraction']
                if cls == 'regulars' and c.amount >= rf['full_claim_cal']:
                    fraction = rf['regular_full_claim_sell_fraction']
                if cfg['immediate_cal_sale']:
                    fraction = 1
                c.amount += amount * (1 - fraction)
                sale[who] += amount * fraction
                if cls == 'regulars' and market.price >= m['market']['initial_cal_usdc'] * rf['release_price_multiple']:
                    release = c.amount * rf['release_fraction']
                    c.amount -= release
                    sale[who] += release
                liquid[who] += sale[who]
                if (h, who) in votes:
                    votes[(h, who)].reset_week = week
            # Remove empty visitor claim records; positive previous claims are retained.
            claims[h] = [c for c in claims[h] if c.amount > 0]
        # Daily observations cover elapsed time, not trade-count weighting.
        for day in range(daily):
            for who, amount in sale.items():
                sell(who, amount / daily)
            fraction = m['strategy_buy_fraction'].get(strategy, 0)
            if phase == 'accumulation' and fraction:
                dollars = w['cal_budget_usdc'] * fraction / math.ceil(cfg['weeks'] * m['phases']['accumulation_end']) / daily
                h = str(week % len(hills)) if strategy == 'honest_long' and cfg['stage2'] else None
                buy('whale', dollars, h, w['claim_lock_weeks'], week)
            if cfg['stage2']:
                buy('community', fund['community_cal_bid_week_usdc'] / daily,
                    str(week % len(hills)), fund['community_claim_lock_weeks'], week)
            signal = min(spec['maximum_signal'], spec['attention_bid_fraction'] + spec['positive_momentum_multiplier'] * max(0, market.price / previous_price - 1))
            if phase == 'markup':
                buy('speculators', cfg['speculator_intensity'] * spec['momentum_bid_week_usdc'] * signal / daily)
            if phase == 'distribution':
                buy('late_buyers', cfg['speculator_intensity'] * spec['late_bid_week_usdc'] * signal / daily)
            selling_phase = 'markup' if strategy == 'back_and_dump' else 'distribution'
            if phase == selling_phase and strategy in ('livermore_corner', 'back_and_dump', 'boost_then_dump', 'ladder_pump'):
                end = math.ceil(cfg['weeks'] * m['phases']['markup_end' if selling_phase == 'markup' else 'distribution_end'])
                remaining_days = (end - week) * daily - day
                sell('whale', liquid['whale'] / remaining_days)
            if strategy == 'wash_trading':
                amount = buy('whale', w['wash_roundtrip_week_usdc'] / daily)
                sell('whale', amount)
            if phase in ('distribution', 'exit'):
                sell('speculators', liquid['speculators'] * spec['exit_sell_fraction_week'] / daily)
            if phase == 'exit':
                sell('late_buyers', liquid['late_buyers'] * spec['late_exit_sell_fraction_week'] / daily)
            market.sample(week * daily + day)
        previous_price = market.price
        peak_price = max(peak_price, market.price)
        price_path.append(market.price)

        # Settlement occurs after the board freezes; money is paid in its own asset.
        for h, hill in hills.items():
            ascents, records, legend, field = states[h]
            window_work = defaultdict(float)
            for block in work[h]:
                for who, value in block.items():
                    window_work[who] += value
            weights = claim_weights(claims[h], window_work, week, p)
            settlement.release_waits(week, h, ascents, records, legend, field, hill.live, weights, cfg['stage2'])
            for stake in hill.stakes:
                if stake.active(week):
                    income = stake.amount * weekly_rate
                    opportunity[stake.owner] += income * sol
                    settlement.distribute(week, h, 'SOL', income, stake.owner, ascents, records, legend, field,
                                          yield_income=True, stage2=cfg['stage2'], claims=weights, live=hill.live)
            cash['sponsors'] -= fund['sponsor_cash_hill_week']
            settlement.distribute(week, h, 'USDC', fund['sponsor_cash_hill_week'], 'sponsors', ascents, records, legend, field)
            if cfg['validator']:
                income = fund['validator_external_sol'] * fund['validator_contribution_apr'] / m['weeks_per_year'] / len(hills)
                cash['validator'] -= income * sol
                settlement.distribute(week, h, 'SOL', income, 'validator', ascents, records, legend, field, yield_income=True)
            for hold in list(ledger.held):
                if hold.hill == h and hold.kind == 'boost' and hold.available <= week:
                    hold.kind = 'pending'
                    settlement.distribute_hold(hold, ascents, records, legend, field)
            riders_dung, backers_dung = dung_allocation(p, hill, week, sum(ascents.values()) * p['example_hill']['climb_tss_per_ascent'], ascents, records, legend, field)
            for who, amount in riders_dung.items():
                dung[actor(who)] += amount
                key = (h, who)
                if key not in votes:
                    votes[key] = DungVote(who, 0, boards[h].last_ascent[who])
                votes[key].amount += amount
                # Record earnings alone do not reset an absent rider's timer.
                if who in ascents:
                    votes[key].reset_week = week
            for who, amount in backers_dung.items():
                dung[who] += amount
                lots = {i: s.amount * p['lock_weights'][str(min(s.lock, max(map(int, p['lock_weights']))))] *
                        (p['founding_dung_multiplier'] if s.founding and week < hill.bonded_at + p['season_weeks'] else 1)
                        for i, s in enumerate(hill.stakes) if s.owner == who and s.active(week)}
                for index, value in proportional(amount, lots).items():
                    key = (h, who, index)
                    if key not in votes:
                        votes[key] = DungVote(who, 0, week, stake=hill.stakes[index])
                    votes[key].amount += value
        reset_earned_rider_timers(votes.values(), last_rider_week)
        if cfg['stage3']:
            cash['sponsors'] -= fund['shared_gift_week_usdc']
            ledger.receive('shared', 'USDC', fund['shared_gift_week_usdc'], 'sponsors', week, kind='pool')
            if fund['shared_gift_week_usdc'] > 0 and sum(hill.bonded for hill in hills.values()) >= p['pool_min_hills']:
                ballots = defaultdict(float)
                for key, vote in votes.items():
                    destination = next(iter(hills)) if actor(vote.owner) in ('whale', 'crew') else key[0]
                    ballots[destination] += vote.weight(week, p)
                activity = {h: sum(state[0].values()) for h, state in states.items() if hills[h].bonded}
                for hold in list(ledger.held):
                    if hold.kind != 'pool' or hold.amount <= 0:
                        continue
                    available = hold.amount
                    allocation = pool_allocation(p, available, activity, ballots)
                    for h, amount in allocation.items():
                        limit = available * p['pool_cap_x'] * activity[h] / sum(activity.values())
                        max_pool_cap_ratio = max(max_pool_cap_ratio, amount / limit if limit else 0)
                        pool_delivered_by_hill[h] += amount * (sol if hold.asset == 'SOL' else 1)
                        part = ledger.split(hold, amount, 'pending')
                        part.hill, part.created = h, week
                        settlement.distribute_hold(part, *states[h])
        settlement.close_week(sol)
        market.assert_conserved()
        balances, _ = token_balances(week)
        assert abs(sum(balances.values()) + market.cal - market.initial_cal - minted_cal) <= m['epsilon'] * max(1, minted_cal)
        assert settlement.max_cap_ratio <= 1 + m['epsilon']
        assert max_pool_cap_ratio <= 1 + m['epsilon']
        last_states = states
        next_phase = phase_for(week + 1, cfg['weeks'], p) if week + 1 < cfg['weeks'] else None
        if next_phase != phase:
            current = snapshot(week)
            delta = {a: {k: current[a][k] - before[a][k] for k in current[a]} for a in ACTORS}
            for a in ACTORS:
                for key in list(delta[a]):
                    if key.endswith('_usd'):
                        delta[a][key[:-4] + '_sol_equivalent'] = delta[a][key] / sol
            paid = source_rider_pay('whale')
            phases.append({'phase': phase, 'through_week': week + 1, 'actors': delta,
                           'cumulative_whale_rider_pay_usd': paid,
                           'price_usdc': market.price,
                           'rider_cash_nonnegative': all(delta[a]['economic_cash_usd'] >= -m['epsilon'] for a in RIDER_CLASSES),
                           'rider_marked_nonnegative': sum(delta[a]['marked_usd'] for a in RIDER_CLASSES) >= -m['epsilon']})
            before = current
    final = snapshot(cfg['weeks'] - 1)
    paid = source_rider_pay('whale')
    future_cost = 0
    calendar = []
    committed_claim_stream = 0
    for h, hill in hills.items():
        for stake in hill.stakes:
            committed = hill.committed_weeks(stake, cfg['weeks'])
            if stake.owner == 'whale':
                future_cost += stake.amount * weekly_rate * committed * sol
            calendar.append({'hill': h, 'owner': stake.owner, 'sol': stake.amount, 'lock_until_week': stake.start + stake.lock,
                             'notice_week': stake.notice_at, 'withdrawn_week': stake.withdrawn_at, 'remaining_committed_weeks': committed})
            # Upper bound on cash stream, not an executable floor; gate current live/field.
            if cfg['stage2'] and hill.live and last_states[h][3]:
                committed_claim_stream += stake.amount * weekly_rate * committed * (1 - p['fee_on_yield']) * p['claim_share_of_riders'] * sol
    claiming_cal = sum(c.amount for positions in claims.values() for c in positions)
    external_paid = paid['regulars'] + paid['visitors']
    whale_profit = final['whale']['economic_cash_usd']
    return {'strategy': strategy, 'scenario': cfg, 'seed': seed, 'fixes': list(fixes), 'phases': phases,
            'totals': final, 'whale_rider_pay_usd': paid,
            'whale_profit_to_independent_rider_pay': whale_profit / external_paid if whale_profit > 0 and external_paid else None,
            'P1': True, 'P2_cash': all(x['rider_cash_nonnegative'] for x in phases),
            'P2_marked': all(x['rider_marked_nonnegative'] for x in phases),
            'P3_cash': all(sum(ph['actors']['whale'][key] for ph in phases[:i+1]) <= m['epsilon'] or sum(x for cls, x in row['cumulative_whale_rider_pay_usd'].items() if cls != 'crew') > m['epsilon']
                           for i, row in enumerate(phases) for key in ('economic_cash_usd',)),
            'principal_committed_sol': dict(principal_added), 'whale_remaining_yield_cost_usd': future_cost,
            'whale_plus_crew_cash_usd': whale_profit + final['crew']['economic_cash_usd'],
            'cal_minted': minted_cal, 'cal_price_final': market.price, 'cal_price_peak': peak_price,
            'price_path': price_path, 'amm_buy_outlay_usd': dict(buy_outlay),
            'amm_inventory_origin_usd_not_direct_payments': dict(historical_inventory_buy_attribution),
            'ladder_activated_sol': ladder.activated_sol if ladder else 0,
            'ladder_escrow_sol': ladder.escrow_sol if ladder else 0,
            'boost_unspent_usdc': sum(h.amount for h in ledger.held if h.kind == 'boost'),
            'pool_allocated_usd_by_hill': dict(pool_delivered_by_hill), 'rider_ascents': dict(rider_ascent_count), 'hill_ascents': dict(hill_ascent_count),
            'boosted_window_ascents': boosted_window_ascents,
            'committed_claim_stream_usd': committed_claim_stream,
            'committed_claim_value_per_cal_usd': committed_claim_stream / claiming_cal if claiming_cal else None,
            'unlock_calendar': calendar,
            'vault': {a: {'income': ledger.income[a], 'fees': ledger.fees[a], 'paid': ledger.payouts[a], 'held': ledger.held_total(a)} for a in ('SOL', 'USDC')},
            'max_direct_cap_ratio': settlement.max_cap_ratio, 'max_pool_cap_ratio': max_pool_cap_ratio}
