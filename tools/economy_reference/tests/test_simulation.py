import unittest
from tools.economy_reference.config import load_config
from tools.economy_reference.simulation import run


class SimulationTests(unittest.TestCase):
    def test_ratified_defaults_sell_earned_cal_and_harden_ladders(self):
        p = load_config()
        result = run(p, 'ladder_pump')
        for actor in ('regulars', 'visitors', 'crew'):
            self.assertLessEqual(abs(result['totals'][actor]['cal']), p['model']['epsilon'], actor)
        self.assertEqual(result['ladder_activated_sol'], 0)

    def test_named_legacy_variants_are_independent_and_overridable(self):
        p = load_config()
        hold = run(p, 'ladder_pump', scenario='legacy_hold')
        self.assertGreater(hold['totals']['regulars']['cal'], 0)
        self.assertEqual(hold['ladder_activated_sol'], 0)
        base = run(p, 'ladder_pump', scenario='legacy_base_ladder')
        self.assertLessEqual(abs(base['totals']['regulars']['cal']), p['model']['epsilon'])
        self.assertGreater(base['ladder_activated_sol'], 0)
        override = run(p, 'ladder_pump', {'immediate_cal_sale': True}, scenario='legacy_hold')
        self.assertEqual(override['totals'], run(p, 'ladder_pump')['totals'])
        self.assertTrue(p['model']['default']['immediate_cal_sale'])

    def test_crew_cap_carry_conserves_income(self):
        result = run(load_config(), 'crew_ride')
        self.assertTrue(result['P1'])
        self.assertLessEqual(result['max_direct_cap_ratio'], 1)

    def test_full_rider_release_can_reenter_claim(self):
        p = load_config()
        p['model']['riders']['release_fraction'] = 1
        p['model']['riders']['release_price_multiple'] = 2
        self.assertTrue(run(p, 'livermore_corner', {'weeks': 12, 'riders': 20, 'hills': 2, 'market_depth_usdc': 1000}, scenario='legacy_hold')['P1'])

    def test_stranded_cash_waits_until_shared_pool_has_gifts(self):
        p = load_config()
        p['model']['funding']['shared_gift_week_usdc'] = 0
        result = run(p, 'crew_ride')
        self.assertEqual(result['pool_allocated_usd_by_hill'], {})
        self.assertGreater(result['vault']['USDC']['held'], 0)
