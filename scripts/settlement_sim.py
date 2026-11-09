"""Settlement math simulation — faithful port of lib.rs distribute_epoch_rewards,
credit_tribute_bucket, roll_to_next_settlement_week, apply_emission_rate, halving,
staker unlock curve. Integer math throughout, mirroring u64 semantics.

Invariants checked each week:
  I1: base split conserves total_dung exactly (dust -> record royalty)
  I2: minted + carried == available (no leakage anywhere)
  I3: CAL tribute conserved mod threshold (remainder + converted*1000 == total in)
  I4: staker allocation never exceeds weekly unlock plus prior unlocked dust
Reports: emission-rate drift of the "1000 CAL = 1 DUNG" story, carry dynamics,
same-week staker reallocation, halving remainder losses.
"""

THRESHOLD = 1_000  # VAULT_CAL_TO_DUNG_THRESHOLD (CAL base units -> DUNG base units)
RANK_PCTS = [30, 20, 15, 10, 8, 6, 5, 3, 2, 1]
UNLOCK_PCTS = [1, 3, 6, 11, 17, 25, 35, 50, 70, 100]
BPS = dict(lb=5500, stakers=2700, legend=300, pol=500, treasury=1000)
CAL = 1_000_000_000  # 1 CAL in base units


class Vault:
    def __init__(self):
        self.cal_tribute_accumulated = 0   # remainder bucket, current week
        self.cal_tribute_accumulated_next = 0
        self.pending_rewards = 0           # DUNG base units
        self.pending_rewards_next = 0
        self.carry = dict(rr=0, stakers=0, legend=0, pol=0, treasury=0)
        self.total_cal_in = 0              # audit: all tribute ever credited
        self.total_dung_pending_ever = 0   # audit: all conversions

    def credit_bucket(self, current_week: bool, cal):
        self.total_cal_in += cal
        if current_week:
            self.cal_tribute_accumulated += cal
            conv = self.cal_tribute_accumulated // THRESHOLD
            self.cal_tribute_accumulated %= THRESHOLD
            self.pending_rewards += conv
            self.total_dung_pending_ever += conv
        else:
            self.cal_tribute_accumulated_next += cal
            conv = self.cal_tribute_accumulated_next // THRESHOLD
            self.cal_tribute_accumulated_next %= THRESHOLD
            self.pending_rewards_next += conv
            self.total_dung_pending_ever += conv

    def roll(self):
        self.pending_rewards = self.pending_rewards_next
        self.pending_rewards_next = 0
        carried = self.cal_tribute_accumulated + self.cal_tribute_accumulated_next
        self.cal_tribute_accumulated = 0
        self.cal_tribute_accumulated_next = 0
        # re-run credit on carried remainder (mirrors roll_to_next_settlement_week)
        self.cal_tribute_accumulated += carried
        conv = self.cal_tribute_accumulated // THRESHOLD
        self.cal_tribute_accumulated %= THRESHOLD
        self.pending_rewards += conv
        self.total_dung_pending_ever += conv


def distribute(v: Vault, emission_bps, lb_entries, staker_lps, legend_active):
    """Returns dict of minted amounts; mutates vault carries. Mirrors lib.rs."""
    raw = v.pending_rewards
    total = raw * emission_bps // 10_000          # apply_emission_rate
    emission_loss = raw - total                    # silently dropped at roll

    base_st = total * BPS["stakers"] // 10_000
    base_lg = total * BPS["legend"] // 10_000
    base_pol = total * BPS["pol"] // 10_000
    base_tr = total * BPS["treasury"] // 10_000
    base_rr = total - (base_st + base_lg + base_pol + base_tr)  # dust -> RR
    # I1
    assert base_rr + base_st + base_lg + base_pol + base_tr == total

    eligible_staker_lps = [lp for lp in staker_lps if lp > 0]
    staker_count = len(eligible_staker_lps)
    unlock_pct = (
        0
        if staker_count == 0
        else 100
        if staker_count >= len(UNLOCK_PCTS)
        else UNLOCK_PCTS[staker_count - 1]
    )
    unlock_bps = unlock_pct * 100
    weekly_unlocked = base_st * unlock_bps // 10_000
    locked = base_st - weekly_unlocked
    staker_distributable = weekly_unlocked + v.carry["stakers"]

    rr_total = base_rr + v.carry["rr"] + locked
    lg_total = base_lg + v.carry["legend"]
    pol_total = base_pol + v.carry["pol"]
    tr_total = base_tr + v.carry["treasury"]
    available = rr_total + staker_distributable + lg_total + pol_total + tr_total

    minted = dict(rr=0, stakers=0, legend=0, pol=0, treasury=0)

    # 1. record royalty
    if rr_total > 0 and lb_entries:
        n = min(len(lb_entries), 10)
        pct_sum = sum(RANK_PCTS[:n])
        for i in range(n):
            minted["rr"] += rr_total * RANK_PCTS[i] // pct_sum
    v.carry["rr"] = rr_total - minted["rr"]

    # 2. legend
    if lg_total > 0 and legend_active:
        minted["legend"] = lg_total
    v.carry["legend"] = lg_total - minted["legend"]

    # 3. stakers
    total_lp = sum(eligible_staker_lps)
    if staker_distributable > 0 and total_lp > 0:
        for lp in eligible_staker_lps:
            minted["stakers"] += staker_distributable * lp // total_lp
    v.carry["stakers"] = staker_distributable - minted["stakers"]
    assert minted["stakers"] <= staker_distributable  # I4

    # 4/5. pol + treasury (always mintable)
    minted["pol"] = pol_total
    v.carry["pol"] = 0
    minted["treasury"] = tr_total
    v.carry["treasury"] = 0

    # I2 conservation
    total_minted = sum(minted.values())
    total_carried = sum(v.carry.values())
    assert total_minted + total_carried == available, (total_minted, total_carried, available)

    v.roll()
    return minted, emission_loss, locked


def run(scenario):
    print(f"\n=== {scenario} ===")
    v = Vault()
    emission_bps = 10_000
    total_minted_ever = 0
    total_emission_loss = 0
    weekly_cal = 12_000 * CAL  # ~12k CAL/wk tribute (small Philly cohort)

    for week in range(1, 41):
        # halving at week 26 (EPOCHS_PER_HALVING)
        if scenario == "halving" and week == 27:
            emission_bps //= 2

        # tribute arrives during the week
        v.credit_bucket(True, weekly_cal)

        # scenario-specific participants
        if scenario == "cold_start":
            lb = list(range(min(week // 4, 10)))       # board fills slowly
            stakers = [100 * CAL] * min(week // 5, 12) # stakers arrive slowly
        elif scenario == "one_whale_staker":
            lb = list(range(10))
            stakers = [50_000 * CAL]                   # 1 staker forever
        elif scenario == "halving":
            lb = list(range(10))
            stakers = [100 * CAL] * 10
        else:  # steady
            lb = list(range(10))
            stakers = [100 * CAL] * 10

        minted, eloss, locked = distribute(v, emission_bps, lb, stakers, legend_active=True)
        total_minted_ever += sum(minted.values())
        total_emission_loss += eloss

        if week in (1, 5, 10, 26, 27, 30, 40):
            print(f"wk{week:>3}: minted={sum(minted.values())/1e9:>9.3f} DUNG "
                  f"(rr={minted['rr']/1e9:.3f} st={minted['stakers']/1e9:.3f}) "
                  f"carry_st={v.carry['stakers']/1e9:>8.3f} carry_rr={v.carry['rr']/1e9:.3f} "
                  f"locked_this_wk={locked/1e9:.3f} eloss={eloss/1e9:.3f}")

    # I3: CAL conservation into DUNG pipeline
    expected_conversions = (v.total_cal_in - v.cal_tribute_accumulated
                            - v.cal_tribute_accumulated_next) // THRESHOLD
    assert v.total_dung_pending_ever == expected_conversions, "CAL->DUNG leakage"

    dung_expected_at_1000_to_1 = v.total_cal_in // THRESHOLD
    outstanding = sum(v.carry.values()) + v.pending_rewards
    print(f"  totals: cal_in={v.total_cal_in/CAL:,.0f} CAL -> minted={total_minted_ever/1e9:,.3f} DUNG"
          f" + outstanding={outstanding/1e9:,.3f} + emission_loss={total_emission_loss/1e9:,.3f}")
    print(f"  '1000 CAL = 1 DUNG' story predicts {dung_expected_at_1000_to_1/1e9:,.3f} DUNG;"
          f" realized+outstanding = {(total_minted_ever+outstanding)/1e9:,.3f}"
          f" ({100*(total_minted_ever+outstanding)/dung_expected_at_1000_to_1:.1f}%)")


for s in ("steady", "cold_start", "one_whale_staker", "halving"):
    run(s)
print("\nBookkeeping invariants held (I1 conservation of splits, "
      "I2 mint+carry==available, I3 CAL->DUNG no leakage, I4 per-call staker cap).")
print("This does not certify carry fairness, deferred-claim solvency, or crank liveness; "
      "run scripts/reproduce_settlement_lifecycle_failures.py for those counterexamples.")
