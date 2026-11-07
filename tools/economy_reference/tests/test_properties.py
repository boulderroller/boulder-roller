"""Deterministic generated cases, including adversarial nulls, without Hypothesis."""
import json
from pathlib import Path
import random
import unittest

from tools.economy_reference.accounting import Ledger, Settlement, pool_allocation
from tools.economy_reference.config import load_config
from tools.economy_reference.experiments import unfunded_trader, holder_drawdown
from tools.economy_reference.simulation import STRATEGIES, run
from tools.economy_reference.tournament import normalize


class PropertyTests(unittest.TestCase):
    def setUp(self):
        self.p = load_config()

    def test_P1_generated_source_asset_field_and_pool_cases(self):
        p = self.p
        check = p['model']['property_checks']
        for seed in check['random_seeds']:
            rng = random.Random(seed)
            for _ in range(check['random_cases']):
                ledger = Ledger(p)
                settlement = Settlement(p, ledger)
                count = rng.randrange(p['min_field_riders'] * p['model']['top_ten_seats'])
                riders = {str(i): rng.randint(1, p['model']['days_per_week']) for i in range(count)}
                seats = list(riders)[:p['model']['top_ten_seats']]
                field = count >= p['min_field_riders']
                for asset, source in (('SOL', 'whale'), ('USDC', 'sponsors')):
                    settlement.distribute(0, 'h', asset, rng.random() * p['example_hill']['stake_sol'], source,
                                          riders, seats, next(iter(riders), None), field,
                                          yield_income=asset == 'SOL', stage2=True, claims={})
                settlement.close_week(p['example_hill']['sol_usd'])
                ledger.assert_conserved()
                activity = {str(i): rng.randrange(p['model']['default']['riders']) for i in range(p['model']['default']['hills'])}
                amount = rng.random() * p['example_hill']['stake_sol']
                allocation = pool_allocation(p, amount, activity, {str(rng.randrange(len(activity))): 1})
                if sum(activity.values()):
                    self.assertAlmostEqual(sum(allocation.values()), amount)
                    for h, value in allocation.items():
                        self.assertLessEqual(value, amount * p['pool_cap_x'] * activity[h] / sum(activity.values()) + p['model']['epsilon'])

    def test_P1_and_P2_cash_generated_agent_paths(self):
        p = self.p
        c = p['model']['property_checks']
        for seed in c['random_seeds']:
            rng = random.Random(seed)
            for strategy in STRATEGIES:
                overrides = {key: rng.choice(values) for key, values in p['model']['grid'].items()}
                overrides.update(weeks=c['property_weeks'], hills=c['small_hills'], riders=c['small_riders'])
                result = run(p, strategy, overrides, seed=seed)
                self.assertTrue(result['P1'], (seed, strategy))
                self.assertTrue(result['P2_cash'], (seed, strategy))

    def test_counterexamples_must_not_be_blessed(self):
        self.assertFalse(unfunded_trader(self.p)['P3'])
        self.assertFalse(holder_drawdown(self.p, False)['P2_marked'])
        self.assertTrue(holder_drawdown(self.p)['P2_marked'])

    def test_fixed_seed_legacy_golden(self):
        expected = json.loads(Path(__file__).with_name('golden.json').read_text())
        result = run(self.p, 'livermore_corner', scenario='legacy_hold_base_ladder')
        self.assertFalse(result['scenario']['immediate_cal_sale'])
        self.assertFalse(result['scenario']['hardened_ladder'])
        # Preserve every original golden field/value; only the two new flag keys
        # are absent from the pre-ratification snapshot.
        result['scenario'] = {k: result['scenario'][k] for k in expected['scenario']}
        actual = normalize({k: result[k] for k in expected}, self.p['model']['output_digits'])
        self.assertEqual(actual, expected)
