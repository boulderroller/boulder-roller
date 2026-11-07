import unittest
from tools.economy_reference.config import load_config
from tools.economy_reference.accounting import Claim, DungVote, Hill, Ledger, Settlement, Stake, YieldLot
from tools.economy_reference.simulation import Board, Ride


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.p = load_config()

    def test_prebond_yield_remains_claimable_after_bond(self):
        hill = Hill('h', self.p)
        hill.pledge('a', 4, 0)
        hill.accrue_escrow(0.01)
        hill.pledge('b', 6, 1)
        self.assertAlmostEqual(hill.claim_escrow_yield('a'), 0.04)
        self.assertEqual(hill.claim_escrow_yield('a'), 0)
        self.assertEqual(hill.principal, 10)

    def test_empty_legend_release_and_exact_season_expiry(self):
        ledger = Ledger(self.p)
        s = Settlement(self.p, ledger)
        s.distribute(0, 'h', 'USDC', 100, 'sponsors', {'a': 1}, [], None, False)
        s.close_week(1)
        self.assertAlmostEqual(ledger.payouts['USDC'], 65)
        s.release_waits(1, 'h', {'a': 1}, ['a'], 'a', True, True, {}, False)
        s.close_week(1)
        self.assertAlmostEqual(ledger.payouts['USDC'], 100)
        s.distribute(2, 'h', 'USDC', 100, 'sponsors', {}, [], None, False)
        s.close_week(1)
        s.release_waits(28, 'h', {'a': 1}, ['a'], 'a', True, True, {}, False)
        self.assertAlmostEqual(sum(h.amount for h in ledger.held if h.kind == 'pool'), 100)
        ledger.assert_conserved()

    def test_inactive_yield_recovers_only_when_live(self):
        ledger = Ledger(self.p)
        s = Settlement(self.p, ledger)
        s.distribute(0, 'h', 'SOL', 100, 'whale', {'a': 1}, ['a'], 'a', True, yield_income=True, live=False)
        s.close_week(1)
        self.assertEqual(ledger.payouts['SOL'], 0)
        s.release_waits(1, 'h', {'a': 1}, ['a'], 'a', True, True, {}, False)
        s.close_week(1)
        self.assertAlmostEqual(ledger.payouts['SOL'], 90)

    def test_cap_combines_multiple_sources_and_assets(self):
        ledger = Ledger(self.p)
        s = Settlement(self.p, ledger)
        people = {str(i): 1 for i in range(100)}
        for asset, source in [('SOL', 'whale'), ('USDC', 'sponsors')]:
            s.distribute(0, 'h', asset, 100, source, people, list(people)[:10], '0', True)
        s.close_week(1)
        paid = sum(v for (who, asset), v in ledger.paid.items() if who == '0')
        self.assertLessEqual(paid, 3 * 2 * 0.65 + 1e-8)
        self.assertGreater(ledger.held_total('SOL'), 0)
        ledger.assert_conserved()

    def test_earned_and_received_votes_decay_per_lot(self):
        lot = Stake('backer', 100, 0, 26, True, 26, 30)
        vote = DungVote('backer', 10, 0, stake=lot)
        self.assertEqual(vote.weight(29, self.p), 10)
        self.assertEqual(vote.weight(82, self.p), 5)
        received = DungVote('buyer', 10, 0, received=True)
        self.assertEqual(received.weight(0, self.p), 0)
        received.lock_weeks = 104
        self.assertEqual(received.weight(0, self.p), 4)
        self.assertEqual(received.weight(104, self.p), 0)

    def test_lot_loss_must_recover_before_new_income(self):
        damaged, healthy = YieldLot(100, 100), YieldLot(100, 100)
        self.assertEqual(damaged.realize(-20), 0)
        self.assertEqual(healthy.realize(10), 10)
        self.assertEqual(damaged.realize(10), 0)
        self.assertEqual(damaged.realize(15), 5)

    def test_upload_week_dedup_freeze_and_field_rollover(self):
        board = Board(self.p)
        ascents, _, records, _, field = board.freeze(0, [Ride(str(i), 0, 0, 300+i, 6) for i in range(4)])
        self.assertFalse(field)
        ascents, _, _, _, field = board.freeze(1, [Ride('fourth', 1, 8, 280, 6), Ride('fourth', 1, 8, 290, 6), Ride('stale', 0, 8, 270, 6)])
        self.assertEqual(ascents, {'fourth': 1})
        self.assertTrue(field)
        with self.assertRaises(ValueError):
            board.freeze(1, [])
        _, _, records, _, field = board.freeze(26, [])
        self.assertFalse(field)
        self.assertIn('fourth', records)

    def test_received_dung_cannot_buy_more_than_full_timer(self):
        received = DungVote('buyer', 100, 0, received=True, lock_weeks=208)
        with self.assertRaises(ValueError):
            received.weight(0, self.p)

    def test_paid_ascent_cap_does_not_hide_a_faster_record(self):
        board = Board(self.p)
        ascents, _, _, _, _ = board.freeze(0, [Ride('a', 0, 0, 400, 6), Ride('a', 0, 1, 300, 6)])
        self.assertEqual(ascents['a'], 1)
        self.assertEqual(board.best['a'], 300)

    def test_later_locked_lot_does_not_prevent_founder_notice(self):
        hill = Hill('h', self.p)
        hill.pledge('a', 10, 0)
        hill.add_stake('a', 20, 104, 0)
        hill.notice_lot(0, 26)
        self.assertEqual(hill.withdraw('a', 30), 10)
        self.assertEqual(hill.principal, 20)
        with self.assertRaises(ValueError):
            hill.notice_lot(1, 30)

    def test_bonded_ascent_refreshes_all_earned_rider_dung(self):
        from tools.economy_reference.accounting import reset_earned_rider_timers
        first = DungVote('rider', 10, 0)
        second = DungVote('rider', 20, 0)
        received = DungVote('rider', 30, 0, received=True, lock_weeks=104)
        reset_earned_rider_timers([first, second, received], {'rider': 52})
        self.assertEqual(first.weight(52, self.p), 10)
        self.assertEqual(second.weight(52, self.p), 20)
        self.assertEqual(received.weight(52, self.p), 6)

    def test_crossing_pledger_gets_title_without_a_paid_seat(self):
        hill = Hill('h', self.p)
        hill.pledge('first', 4, 0)
        hill.pledge('founder', 6, 0)
        self.assertEqual(hill.founder_title_owner, 'founder')
        self.assertTrue(all(s.founding for s in hill.stakes))
