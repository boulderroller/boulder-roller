"""Generate the shared local-validator custody vectors from the ratified oracle.

Run: python -m tools.stage1_reference.custody_vectors [--check]
No handwritten expected balances; all outputs below come from Model actions.
"""
import json
import sys
from fractions import Fraction
from pathlib import Path

from .config import load_config
from .model import Model, WEEK

DESTINATION = Path(__file__).resolve().parents[2] / "protocol/anchor/tests/fixtures/stage1_custody_vectors.json"


def vectors():
    cases = [
        ("unchanged", 100, (1, 1), (1, 1), 37, 0, (1, 1)),
        ("owner-dust", 100, (1, 1), (3, 1), 4, 0, (3, 1)),
        ("loss", 100, (1, 1), (3, 4), 37, 13, (3, 4)),
        ("deactivation-yield", 100, (1, 1), (1, 1), 100, 26, (2, 1)),
        ("subtoken-reject", 3, (3, 2), (3, 2), 1, 52, (3, 2)),
        ("subtoken-harvest-rollback", 100, (1, 1), (2, 1), 1, 0, (2, 1)),
        ("ceil-basis", 1999, (1, 1000), (1, 1000), 2, 0, (1, 1000)),
        ("full-loss", 101, (7, 3), (1, 3), 236, 0, (1, 3)),
    ]
    result = []
    for name, units, deposited, exiting, basis, lock, returning in cases:
        model = Model(load_config(), launch=1791201600)
        model.allow_asset("seed", 9, Fraction(1))
        model.allow_asset("lst", 9, Fraction(*deposited))
        model.add_hill("hill")
        model.pledge("founder", "hill", "seed", 10_000_000_000)
        model.advance(model.now + 123)
        lot_id = model.pledge("owner", "hill", "lst", units, lock_weeks=lock)
        lot = model.lots[lot_id]
        original_basis = lot.basis
        lock_seconds = lot.lock_end - model.now
        model.advance(lot.lock_end)
        model.notice(lot_id, "owner", basis)
        model.advance(model.now + 4 * WEEK)
        model.observe_rate("lst", Fraction(*exiting))
        row = dict(name=name, units=str(units), deposit_rate=deposited, exit_rate=exiting,
                   return_rate=returning, requested_basis=str(basis), lock_weeks=lock,
                   original_basis=str(original_basis), lock_seconds=lock_seconds,
                   notice_seconds=4 * WEEK)
        try:
            child_id = model.begin_exit(lot_id, "owner")
        except ValueError as error:
            row["reject"] = str(error)
            row["remaining_units"] = str(model.lots[lot_id].units)
            row["remaining_basis"] = str(model.lots[lot_id].basis)
            row["harvested"] = str(model.ledgers["lst"].realized)
        else:
            child = model.lots[child_id]
            row.update(exit_units=str(child.units), owner_dust=str(child.owner_units),
                       remaining_units=str(lot.units), remaining_basis=str(lot.basis),
                       harvest_at_begin=str(model.ledgers["lst"].realized))
            model.observe_rate("lst", Fraction(*returning))
            row["returned"] = str(model.finish_exit(child_id, "owner", liquid=True))
            row["harvested"] = str(model.ledgers["lst"].realized)
            row["fees"] = str(model.ledgers["lst"].fees)
        result.append(row)
    bond = Model(load_config(), launch=1791201600)
    bond.allow_asset("lst", 9, Fraction(1))
    bond.add_hill("hill")
    first = bond.pledge("first", "hill", "lst", 6_000_000_000)
    bond.observe_rate("lst", Fraction(2))
    trigger = bond.pledge("trigger", "hill", "lst", 2_000_000_000)
    founding = bond.lots[first]
    bonding = dict(first_units="6000000000", trigger_units="2000000000",
                   first_principal_units=str(founding.units), owner_reserve=str(founding.owner_units),
                   trigger_basis=str(bond.lots[trigger].basis), founder=bond.hills["hill"].founder,
                   lock_seconds=founding.lock_end - bond.now)
    stale = Model(load_config(), launch=1791201600)
    stale.allow_asset("lst", 9, Fraction(1))
    stale.add_hill("hill")
    stale.pledge("founder", "hill", "lst", 10_000_000_000)
    lot = stale.pledge("owner", "hill", "lst", 100)
    stale.notice(lot, "owner", 100)
    stale.advance(stale.now + 4 * WEEK)
    stale.observe_rate("lst", Fraction(2))
    stale.mark_rate_stale("lst")
    stale.advance(stale.now + WEEK)
    before = stale.held_basis
    child = stale.begin_exit(lot, "owner")
    returned = stale.finish_exit(child, "owner", liquid=True)
    stale_exit = dict(stale_seconds=WEEK, returned=str(returned), harvested=str(stale.ledgers["lst"].realized),
                     released_basis=str(before - stale.held_basis))
    campaign = Model(load_config(), launch=1791201600)
    campaign.allow_asset("lst", 9, Fraction(1))
    campaign.allow_asset("x", 9, Fraction(1))
    campaign.add_hill("hill")
    campaign.pledge("backer", "hill", "lst", 6_000_000_000)
    dust = campaign.pledge("owner", "hill", "x", 1)
    excluded = campaign.pledge("owner", "hill", "x", 10)
    recovered = campaign.pledge("owner", "hill", "x", 3)
    campaign.mark_rate_stale("x")
    campaign.pledge("backer", "hill", "lst", 1)
    campaign.pledge("trigger", "hill", "lst", 4_000_000_000)
    cancelled = campaign.cancel(dust, "owner")
    campaign.observe_rate("x", Fraction(2))
    fresh_cancelled = campaign.cancel(recovered, "owner")
    campaign.convert(excluded, "owner", 13)
    converted = campaign.lots[excluded]
    stale_campaign = dict(founding_count=sum(lot.founding for lot in campaign.lots.values()),
                          founder=campaign.hills["hill"].founder, excluded_founding=converted.founding,
                          cancelled_units=str(cancelled), fresh_cancelled_units=str(fresh_cancelled), converted_units=str(converted.units),
                          converted_basis=str(converted.basis), owner_reserve=str(converted.owner_units),
                          lock_seconds=converted.lock_end - campaign.now,
                          held_basis=str(campaign.held_basis), harvested=str(campaign.ledgers["x"].realized))
    return {"evidence": "offline oracle; consumed by ordinary local-validator transactions", "cap_measurement": "held_deposit_basis",
            "bonding": bonding, "stale_exit": stale_exit, "stale_campaign": stale_campaign, "cases": result}


if __name__ == "__main__":
    text = json.dumps(vectors(), indent=2) + "\n"
    if "--check" in sys.argv:
        if DESTINATION.read_text() != text:
            raise SystemExit("custody vectors differ from the reference model")
        print(f"{len(vectors()['cases'])} exit vectors, stale exit, stale campaign and bonding match the ratified reference model")
    else:
        DESTINATION.write_text(text)
