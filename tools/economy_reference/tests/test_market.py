import unittest
from tools.economy_reference.config import load_config
from tools.economy_reference.market import Market, Ladder, Boost


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.p = load_config()

    def test_round_trip_loses_fee_and_market_conserves(self):
        market = Market(self.p, 1000)
        cal, _ = market.buy(100)
        usd = market.sell(cal, 'whale')
        self.assertLess(usd, 100)
        self.assertAlmostEqual(market.usdc, 1000 + 100 - usd)
        market.assert_conserved()

    def test_default_ladder_requires_depth_independent_price_and_field(self):
        depth = self.p['model']['whale']['ladder_fix_depth_usdc']
        market = Market(self.p, depth)
        ladder = Ladder(self.p, [0.001], 10)
        for day in range(7):
            market.sample(day)
        self.assertEqual(ladder.activate(market, 7), [])
        self.assertEqual(ladder.activate(market, 7, independent_price=market.price), [])
        self.assertEqual(ladder.activate(market, 7, verified_riders=5), [])
        self.assertEqual(ladder.activate(market, 7, independent_price=market.price, verified_riders=4), [])
        self.assertEqual(ladder.activate(market, 7, independent_price=market.price / 2, verified_riders=5), [])
        shallow = Market(self.p, depth / 2)
        for day in range(7):
            shallow.sample(day)
        self.assertEqual(ladder.activate(shallow, 7, independent_price=shallow.price, verified_riders=5), [])
        self.assertEqual(ladder.activate(market, 7, independent_price=market.price, verified_riders=5), [10])

    def test_legacy_ladder_needs_full_window_depth_and_is_irrevocable(self):
        market = Market(self.p, 1000)
        ladder = Ladder(self.p, [0.001], 10)
        market.sample(0)
        self.assertEqual(ladder.activate(market, 1, hardened=False), [])
        for day in range(1, 7):
            market.sample(day)
        self.assertEqual(ladder.activate(market, 7, hardened=False), [10])
        market.sell(market.cal * 10, 'external')
        self.assertEqual(ladder.activate(market, 8, hardened=False), [])
        self.assertEqual(ladder.escrow_sol, 0)
        self.assertEqual(ladder.activated_sol, 10)

    def test_boost_is_fully_funded_and_cannot_cancel(self):
        boost = Boost(self.p, 100, 2, 4)
        self.assertEqual(sum(boost.due(w) for w in range(10)), 100)
        with self.assertRaises(ValueError):
            boost.cancel()
        with self.assertRaises(ValueError):
            Boost(self.p, 100, 0, 0)
