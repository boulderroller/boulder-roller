"""One external CAL/USDC constant-product AMM. Its fees belong to its LP."""
from collections import defaultdict
from dataclasses import dataclass


class Market:
    def __init__(self, p, depth):
        if depth <= 0:
            raise ValueError('Positive market depth required')
        self.p = p
        self.usdc = depth
        self.cal = depth / p['model']['market']['initial_cal_usdc']
        self.initial_usdc, self.initial_cal = self.usdc, self.cal
        self.usdc_in = self.usdc_out = self.cal_in = self.cal_out = 0
        self.origins = {p['model']['market']['provenance_initial']: self.cal}
        self.samples = []
        self.fees_usdc = self.fees_cal = 0

    @property
    def price(self):
        return self.usdc / self.cal

    def buy(self, dollars):
        if dollars < 0:
            raise ValueError('Negative buy')
        effective = dollars * (1 - self.p['model']['market']['swap_fee'])
        out = self.cal * effective / (self.usdc + effective)
        fractions = {k: v / self.cal for k, v in self.origins.items()}
        attribution = {k: dollars * f for k, f in fractions.items()}
        for origin, f in fractions.items():
            self.origins[origin] -= out * f
        self.usdc += dollars
        self.cal -= out
        self.usdc_in += dollars
        self.cal_out += out
        self.fees_usdc += dollars - effective
        return out, attribution

    def sell(self, tokens, origin):
        if tokens < 0:
            raise ValueError('Negative sell')
        effective = tokens * (1 - self.p['model']['market']['swap_fee'])
        out = self.usdc * effective / (self.cal + effective)
        self.cal += tokens
        self.usdc -= out
        self.cal_in += tokens
        self.usdc_out += out
        self.origins[origin] = self.origins.get(origin, 0) + tokens
        self.fees_cal += tokens - effective
        return out

    def liquidation(self, tokens):
        effective = tokens * (1 - self.p['model']['market']['swap_fee'])
        return self.usdc * effective / (self.cal + effective)

    def sample(self, day):
        if self.samples and day <= self.samples[-1][0]:
            raise ValueError('Oracle observations must advance time')
        self.samples.append((day, self.price, self.usdc))
        window = self.p['ladder']['price_window_days']
        self.samples = self.samples[-window:]

    def oracle(self, day):
        window = self.p['ladder']['price_window_days']
        samples = [row for row in self.samples if day - window <= row[0] < day]
        if len(samples) != window or samples[-1][0] - samples[0][0] != window - 1:
            return None
        return sum(row[1] for row in samples) / window, min(row[2] for row in samples)

    def assert_conserved(self):
        eps = self.p['model']['epsilon']
        assert abs(self.usdc - self.initial_usdc - self.usdc_in + self.usdc_out) <= eps * max(1, self.usdc_in)
        assert abs(self.cal - self.initial_cal - self.cal_in + self.cal_out) <= eps * max(1, self.cal_in)
        assert abs(sum(self.origins.values()) - self.cal) <= eps * max(1, self.cal)
        assert self.cal > 0 and self.usdc > 0


class Ladder:
    def __init__(self, p, prices, tranche_sol):
        if len(prices) > p['ladder']['max_steps'] or any(v <= 0 for v in prices):
            raise ValueError('Invalid ladder')
        if not 0 < tranche_sol <= p['model']['whale']['ladder_step_cap_sol']:
            raise ValueError('Ladder step exceeds SOL cap')
        self.p, self.steps = p, list(prices)
        self.tranche_sol = tranche_sol
        self.escrow_sol = len(prices) * tranche_sol
        self.activated_sol = 0

    def activate(self, market, day, *, hardened=None, independent_price=None, verified_riders=None):
        if hardened is None:
            hardened = self.p['model']['default']['hardened_ladder']
        quote = market.oracle(day)
        if quote is None:
            return []
        price, depth = quote
        c = self.p['model']['whale']
        minimum = c['ladder_fix_depth_usdc'] if hardened else c['ladder_min_depth_usdc']
        if depth < minimum:
            return []
        if hardened and (independent_price is None or verified_riders is None
                         or verified_riders < c['ladder_fix_demand_riders']
                         or price > independent_price * c['ladder_fix_independent_price_ratio']):
            return []
        result = []
        for step in list(self.steps):
            if price >= step:
                self.steps.remove(step)
                self.escrow_sol -= self.tranche_sol
                self.activated_sol += self.tranche_sol
                result.append(self.tranche_sol)
        return result


@dataclass
class Boost:
    p: dict
    amount: float
    start: int
    weeks: int

    def __post_init__(self):
        if self.amount <= 0 or not self.p['boost']['min_weeks'] <= self.weeks <= self.p['boost']['max_weeks']:
            raise ValueError('Boost must be funded for a permitted window')

    def due(self, week):
        return self.amount / self.weeks if self.start <= week < self.start + self.weeks else 0

    def cancel(self):
        if self.p['boost']['irrevocable']:
            raise ValueError('Posted boost is irrevocable')
        raise ValueError('Reference model does not implement revocable boosts')
