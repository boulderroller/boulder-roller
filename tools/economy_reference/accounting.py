"""Asset- and source-conserving accounting; principal never enters the payout ledger."""
from collections import defaultdict
from dataclasses import dataclass
from statistics import median


@dataclass
class Hold:
    hill: str
    asset: str
    amount: float
    source: str
    created: int
    kind: str
    owner: str | None = None
    available: int = 0


class Ledger:
    def __init__(self, p):
        self.p = p
        self.income = defaultdict(float)
        self.fees = defaultdict(float)
        self.payouts = defaultdict(float)
        self.held = []
        self.by_source = defaultdict(lambda: defaultdict(float))
        self.paid = defaultdict(float)
        self.transfers = defaultdict(float)

    def receive(self, hill, asset, amount, source, week, kind='pending', yield_income=False, available=0):
        if asset not in ('SOL', 'USDC') or amount < 0:
            raise ValueError('Invalid income')
        fee = amount * self.p['fee_on_yield'] if yield_income else amount * self.p['fee_on_cash']
        self.income[asset] += amount
        self.by_source[(asset, source)]['income'] += amount
        self.fees[asset] += fee
        self.by_source[(asset, source)]['fees'] += fee
        hold = Hold(hill, asset, amount - fee, source, week, kind, available=available)
        self.held.append(hold)
        return hold

    def pay(self, hold, owner, amount):
        if amount < 0 or amount > hold.amount + self.p['model']['epsilon']:
            raise ValueError('Unfunded payment')
        if hold.amount - amount <= self.p['model']['epsilon']:
            amount = hold.amount
        hold.amount -= amount
        self.payouts[hold.asset] += amount
        self.by_source[(hold.asset, hold.source)]['payouts'] += amount
        self.paid[(owner, hold.asset)] += amount
        self.transfers[(hold.source, owner, hold.asset)] += amount

    def held_total(self, asset):
        return sum(h.amount for h in self.held if h.asset == asset)

    def split(self, hold, amount, kind, owner=None):
        if amount < 0 or amount > hold.amount + self.p['model']['epsilon']:
            raise ValueError('Unfunded reservation')
        if hold.amount - amount <= self.p['model']['epsilon']:
            amount = hold.amount
        hold.amount -= amount
        child = Hold(hold.hill, hold.asset, amount, hold.source, hold.created, kind, owner, hold.available)
        self.held.append(child)
        return child

    def assert_conserved(self):
        eps = self.p['model']['epsilon']
        for asset in ('SOL', 'USDC'):
            assert abs(self.income[asset] - self.payouts[asset] - self.fees[asset] - self.held_total(asset)) <= eps * max(1, self.income[asset])
        for (asset, source), values in self.by_source.items():
            held = sum(h.amount for h in self.held if h.asset == asset and h.source == source)
            assert abs(values['income'] - values['payouts'] - values['fees'] - held) <= eps * max(1, values['income'])
        assert all(h.amount >= -eps for h in self.held)
        # Never discard monetary dust: repeated epsilon-sized deletions leak value.
        merged = {}
        for h in self.held:
            if h.amount <= 0:
                continue
            key = (h.hill, h.asset, h.source, h.created, h.kind, h.owner, h.available)
            if key in merged:
                merged[key].amount += h.amount
            else:
                merged[key] = h
        self.held = list(merged.values())


@dataclass
class Stake:
    owner: str
    amount: float
    start: int
    lock: int
    founding: bool
    notice_at: int | None = None
    withdrawn_at: int | None = None

    def active(self, week):
        return self.withdrawn_at is None or week < self.withdrawn_at


class Hill:
    def __init__(self, name, p):
        self.name, self.p = name, p
        self.escrow = defaultdict(float)
        self.escrow_yield = defaultdict(float)
        self.stakes = []
        self.bonded_at = None
        self.founder_title_owner = None

    @property
    def bonded(self):
        return self.bonded_at is not None

    @property
    def live(self):
        return self.bonded and self.principal >= self.p['line_sol']['philadelphia'] * self.p['live_fraction']

    @property
    def principal(self):
        return sum(s.amount for s in self.stakes if s.withdrawn_at is None)

    def pledge(self, owner, amount, week):
        if amount <= 0 or self.bonded:
            raise ValueError('Use later stake after bonding; pledge must be positive')
        self.escrow[owner] += amount
        if sum(self.escrow.values()) >= self.p['line_sol']['philadelphia']:
            self.bonded_at = week
            self.founder_title_owner = owner
            for who, sol in self.escrow.items():
                self.stakes.append(Stake(who, sol, week, self.p['bond_lock_weeks'], True))
            self.escrow.clear()

    def accrue_escrow(self, weekly_rate):
        for who, amount in self.escrow.items():
            self.escrow_yield[who] += amount * weekly_rate

    def claim_escrow_yield(self, owner):
        return self.escrow_yield.pop(owner, 0)

    def cancel_pledge(self, owner):
        if self.bonded:
            raise ValueError('Bonded principal is locked')
        return self.escrow.pop(owner, 0) + self.escrow_yield.pop(owner, 0)

    def add_stake(self, owner, amount, lock, week):
        if not self.bonded or amount <= 0 or lock not in self.p['lock_options_weeks_proposed']:
            raise ValueError('Invalid later stake')
        self.stakes.append(Stake(owner, amount, week, lock, False))

    def notice_lot(self, index, week):
        lot = self.stakes[index]
        if lot.withdrawn_at is not None or week < lot.start + lot.lock:
            raise ValueError('Notice follows the particular lot lock')
        if lot.notice_at is None:
            lot.notice_at = week

    def notice(self, owner, week):
        lots = [s for s in self.stakes if s.owner == owner and s.withdrawn_at is None and s.notice_at is None]
        if any(week < s.start + s.lock for s in lots):
            raise ValueError('Notice follows lock expiry')
        for s in lots:
            s.notice_at = week

    def withdraw(self, owner, week):
        amount = 0
        for s in self.stakes:
            if s.owner == owner and s.withdrawn_at is None and s.notice_at is not None and week >= s.notice_at + self.p['notice_weeks']:
                s.withdrawn_at = week
                amount += s.amount
        return amount

    def committed_weeks(self, stake, week):
        if not stake.active(week):
            return 0
        exit_at = (stake.notice_at + self.p['notice_weeks']) if stake.notice_at is not None else max(week, stake.start + stake.lock) + self.p['notice_weeks']
        return max(0, exit_at - week)


@dataclass
class Claim:
    owner: str
    amount: float
    start: int
    duration: int
    capital: bool

    def ve(self, week, p):
        if self.amount < 0 or (self.capital and not 0 < self.duration <= p['timer_weeks']):
            raise ValueError('Invalid capital claim or amount')
        return self.amount * max(0, min(p['timer_weeks'], self.start + self.duration - week)) / p['timer_weeks']

    def reset(self, week, p):
        if self.capital:
            raise ValueError('Riding cannot reset an outside-capital lock')
        self.start, self.duration = week, p['timer_weeks']

    def release(self, week):
        if self.capital and week < self.start + self.duration:
            raise ValueError('No early exit')
        amount, self.amount = self.amount, 0
        return amount


def claim_weights(claims, work, week, p):
    ve = defaultdict(float)
    for c in claims:
        ve[c.owner] += c.ve(week, p)
    total, total_work = sum(ve.values()), sum(work.values())
    capital = p['capital_weight']
    # Detailed DESIGN boost; outside capital has no verified work and receives 40%.
    return {who: min(value, capital * value + (1 - capital) * total * work.get(who, 0) / total_work)
            if total_work else capital * value for who, value in ve.items()}


def proportional(amount, weights):
    total = sum(weights.values())
    return {who: amount * value / total for who, value in weights.items() if value > 0} if total else {}


def direct_split(amount, ascents, records, legend, field, split, p):
    if len(records) != len(set(records)):
        raise ValueError('One record seat per identity')
    if len(records) > p['model']['top_ten_seats']:
        raise ValueError('Too many record seats')
    payments = defaultdict(float)
    held = []
    for kind, weights in (
        ('every_rider_by_ascents', ascents),
        ('top_ten', {r: 1 for r in records} if field else {}),
        ('local_legend', {legend: 1} if legend is not None and field else {}),
    ):
        value = amount * split[kind]
        allocation = proportional(value, weights)
        if not allocation:
            held.append((kind, value))
        for who, value in allocation.items():
            payments[who] += value
    return dict(payments), held


class Settlement:
    def __init__(self, p, ledger):
        self.p, self.ledger = p, ledger
        self.pending = []
        self.max_cap_ratio = 0

    def distribute(self, week, hill, asset, amount, source, ascents, records, legend, field,
                   yield_income=False, stage2=False, claims=None, live=True):
        hold = self.ledger.receive(hill, asset, amount, source, week, yield_income=yield_income)
        self.distribute_hold(hold, ascents, records, legend, field, stage2 and yield_income, claims, live)

    def distribute_hold(self, hold, ascents, records, legend, field, stage2=False, claims=None, live=True):
        if not live:
            hold.kind = 'inactive_yield'
            return
        amount = hold.amount
        if stage2:
            part = self.ledger.split(hold, amount * self.p['claim_share_of_riders'], 'claims')
            if field:
                allocation = proportional(part.amount, claims or {})
                for who, value in allocation.items():
                    self.ledger.pay(part, who, value)
            else:
                self.queue(part, proportional(part.amount, ascents))
                part.kind = 'every_rider_by_ascents'
        payments, waits = direct_split(hold.amount, ascents, records, legend, field, self.p['rider_split'], self.p)
        self.queue(hold, payments)
        for kind, value in waits:
            self.ledger.split(hold, value, kind)

    def queue(self, hold, allocation):
        for who, value in allocation.items():
            child = self.ledger.split(hold, value, 'cap', who)
            self.pending.append(child)

    def release_waits(self, week, hill, ascents, records, legend, field, live, claims, stage2):
        for hold in list(self.ledger.held):
            if hold.hill != hill or hold.kind in ('pool', 'boost') or hold.amount <= 0:
                continue
            if week - hold.created >= self.p['season_weeks']:
                hold.kind = 'pool'
                continue
            if hold.kind == 'cap':
                self.pending.append(hold)
            elif hold.kind == 'inactive_yield' and live:
                self.distribute_hold(hold, ascents, records, legend, field, stage2, claims)
            elif hold.kind == 'claims' and field:
                for who, value in proportional(hold.amount, claims).items():
                    self.ledger.pay(hold, who, value)
            elif hold.kind == 'every_rider_by_ascents':
                self.queue(hold, proportional(hold.amount, ascents))
            elif hold.kind == 'top_ten' and field:
                self.queue(hold, proportional(hold.amount, {r: 1 for r in records}))
            elif hold.kind == 'local_legend' and field and legend is not None:
                self.queue(hold, {legend: hold.amount})

    def close_week(self, sol_usd):
        # Median positive direct recipient-week, all direct sources/assets combined.
        by_hill = defaultdict(lambda: defaultdict(float))
        for h in self.pending:
            by_hill[h.hill][h.owner] += h.amount * (sol_usd if h.asset == 'SOL' else 1)
        caps = {hill: self.p['rider_week_cap_x'] * median(values.values()) for hill, values in by_hill.items()}
        for hold in self.pending:
            total = by_hill[hold.hill][hold.owner]
            fraction = min(1, caps[hold.hill] / total) if total else 0
            self.ledger.pay(hold, hold.owner, hold.amount * fraction)
            self.max_cap_ratio = max(self.max_cap_ratio, min(total, caps[hold.hill]) / caps[hold.hill] if caps[hold.hill] else 0)
        self.pending.clear()
        self.ledger.assert_conserved()


def dung_allocation(p, hill, week, tss, ascents, records, legend, field):
    if not hill.bonded or not field:
        return {}, {}
    minted = tss * p['dung_per_climb_tss']
    riders, _ = direct_split(minted * p['dung_split']['riders'], ascents, records, legend, field, p['rider_dung_split'], p)
    weights = defaultdict(float)
    for stake in hill.stakes:
        if not stake.active(week):
            continue
        lock = min(stake.lock, max(map(int, p['lock_weights'])))
        factor = p['lock_weights'][str(lock)]
        if stake.founding and week < hill.bonded_at + p['season_weeks']:
            factor *= p['founding_dung_multiplier']
        weights[stake.owner] += stake.amount * factor
    return riders, proportional(minted * p['dung_split']['backers'], weights)


def pool_allocation(p, amount, ascents, votes):
    activity = {h: n for h, n in ascents.items() if n > 0}
    total = sum(activity.values())
    if not total:
        return {}
    caps = {h: amount * p['pool_cap_x'] * n / total for h, n in activity.items()}
    weights = {h: votes.get(h, 0) for h in activity}
    if not sum(weights.values()):
        weights = activity
    target = proportional(amount, weights)
    paid = {h: min(target.get(h, 0), caps[h]) for h in activity}
    remainder = amount - sum(paid.values())
    while remainder > p['model']['epsilon']:
        eligible = {h: activity[h] for h in activity if caps[h] > paid[h]}
        if not eligible:
            raise AssertionError('Pool cap cannot strand distributable money')
        for h, share in proportional(remainder, eligible).items():
            paid[h] += min(share, caps[h] - paid[h])
        remainder = amount - sum(paid.values())
    return paid


@dataclass
class DungVote:
    owner: str
    amount: float
    reset_week: int
    received: bool = False
    lock_weeks: int = 0
    stake: Stake | None = None

    def weight(self, week, p):
        if self.received:
            if not 0 <= self.lock_weeks <= p['timer_weeks']:
                raise ValueError('Received DUNG lock exceeds claim timer')
            return self.amount * p['capital_weight'] * max(0, self.reset_week + self.lock_weeks - week) / p['timer_weeks']
        if self.stake is not None:
            if self.stake.active(week):
                return self.amount
            reset = self.stake.withdrawn_at
        else:
            reset = self.reset_week
        return self.amount * max(0, p['timer_weeks'] - (week - reset)) / p['timer_weeks']


def reset_earned_rider_timers(votes, last_ascent):
    for vote in votes:
        if vote.stake is None and not vote.received:
            vote.reset_week = max(vote.reset_week, last_ascent.get(vote.owner, vote.reset_week))


@dataclass
class YieldLot:
    """One asset lot's recovery hurdle; losses cannot be hidden in another lot."""
    principal: float
    value: float

    def realize(self, change):
        self.value += change
        income = max(0, self.value - self.principal)
        self.value -= income
        return income
