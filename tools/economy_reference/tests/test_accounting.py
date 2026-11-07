"""Behavioral contracts: these are written before the accounting implementation."""
import unittest

from tools.economy_reference.config import load_config
from tools.economy_reference.accounting import Hill, Ledger, Settlement, Claim, claim_weights, dung_allocation, pool_allocation


class AccountingTests(unittest.TestCase):
    def setUp(self):
        self.p = load_config()

    def test_realized_yield_fee_and_fee_free_cash_conserve_each_asset(self):
        ledger = Ledger(self.p)
        settlement = Settlement(self.p, ledger)
        riders = {str(i): 1 for i in range(10)}
        settlement.distribute(0, 'h', 'SOL', 0.95, 'whale', riders, list(riders), '0', True, yield_income=True)
        settlement.distribute(0, 'h', 'USDC', 100, 'sponsor', riders, list(riders), '0', True)
        settlement.close_week(self.p['example_hill']['sol_usd'])
        self.assertAlmostEqual(ledger.fees['SOL'], 0.095)
        self.assertEqual(ledger.fees['USDC'], 0)
        self.assertAlmostEqual(ledger.payouts['SOL'], 0.855)
        self.assertAlmostEqual(ledger.payouts['USDC'], 100)
        ledger.assert_conserved()

    def test_field_claim_share_returns_to_ascent_riders(self):
        ledger = Ledger(self.p)
        settlement = Settlement(self.p, ledger)
        settlement.distribute(0, 'h', 'SOL', 100, 'whale', {'a': 1}, [], None, False, yield_income=True, stage2=True)
        settlement.close_week(self.p['example_hill']['sol_usd'])
        # 90 net; 20% returns to ascent riders, 65% of remaining 80% direct.
        self.assertAlmostEqual(ledger.payouts['SOL'], 90 * (0.2 + 0.8 * 0.65))
        self.assertAlmostEqual(ledger.held_total('SOL'), 90 * 0.8 * 0.35)
        ledger.assert_conserved()

    def test_founding_bonus_changes_weights_not_total_mint(self):
        hill = Hill('h', self.p)
        hill.pledge('founder', 10, 0)
        hill.add_stake('later', 10, 26, 0)
        r, b = dung_allocation(self.p, hill, 0, 1000, {'a': 1}, ['a'], 'a', True)
        self.assertAlmostEqual(sum(r.values()), 0.5)
        self.assertAlmostEqual(sum(b.values()), 0.5)
        self.assertAlmostEqual(b['founder'] / b['later'], 2)
        _, later = dung_allocation(self.p, hill, 26, 1000, {'a': 1}, ['a'], 'a', True)
        self.assertAlmostEqual(later['founder'], later['later'])

    def test_bond_lock_notice_escrow_and_later_stake(self):
        hill = Hill('h', self.p)
        hill.pledge('a', 4, 0)
        self.assertFalse(hill.bonded)
        self.assertEqual(hill.cancel_pledge('a'), 4)
        hill.pledge('a', 10, 0)
        self.assertTrue(hill.live)
        with self.assertRaises(ValueError):
            hill.notice('a', 25)
        hill.notice('a', 26)
        self.assertEqual(hill.withdraw('a', 29), 0)
        self.assertEqual(hill.withdraw('a', 30), 10)
        self.assertTrue(hill.bonded)
        self.assertFalse(hill.live)
        hill.add_stake('b', 5, 0, 30)
        self.assertTrue(hill.live)

    def test_rider_reset_and_capital_lock_no_early_exit(self):
        rider = Claim('r', 100, 0, 104, False)
        capital = Claim('c', 100, 0, 104, True)
        self.assertAlmostEqual(capital.ve(52, self.p), 50)
        with self.assertRaises(ValueError):
            capital.release(52)
        rider.reset(52, self.p)
        self.assertAlmostEqual(rider.ve(52, self.p), 100)
        weights = claim_weights([rider, capital], {'r': 1}, 52, self.p)
        self.assertAlmostEqual(weights['r'], 100)
        self.assertAlmostEqual(weights['c'], 20)
        self.assertEqual(rider.release(52), 100)
        self.assertEqual(capital.release(104), 100)

    def test_pool_cap_repeated_overflow_and_zero_ascents(self):
        shares = pool_allocation(self.p, 100, {'a': 1, 'b': 2, 'c': 7}, {'a': 100})
        self.assertAlmostEqual(sum(shares.values()), 100)
        self.assertLessEqual(shares['a'], 20)
        for h, n in {'a': 1, 'b': 2, 'c': 7}.items():
            self.assertLessEqual(shares[h], 2 * n * 10 + 1e-9)
        self.assertEqual(pool_allocation(self.p, 100, {'a': 0}, {'a': 1}), {})


if __name__ == '__main__':
    unittest.main()

class SmallAmountTests(unittest.TestCase):
    def test_pool_distributes_small_tranches_without_dropping_headroom(self):
        p = load_config()
        activity = {str(i): 1 for i in range(100)}
        result = pool_allocation(p, 0.0000001, activity, {'0': 100})
        self.assertAlmostEqual(sum(result.values()), 0.0000001, places=14)
