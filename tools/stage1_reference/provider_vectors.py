"""Pin snapshot quotes and simulated epoch admission to a shared JSON vector."""
import argparse
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import json
from .providers import FIXTURES, IDENTITIES, ProviderBook, observe, snapshot
from .config import load_config
from .model import Model

OUTPUT = FIXTURES.parent / "stage1_provider_vectors.json"


def vectors():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    result = {"evidence": "Read-only mainnet snapshots; LOCAL simulated admission transitions", "slot": manifest["slot"],
              "captured_at_utc": manifest["captured_at_utc"], "epoch": 1057, "providers": []}
    for name in IDENTITIES:
        accounts = snapshot(name)
        observation = observe(name, accounts, 1057)
        book = ProviderBook(); book.refresh(name, accounts, 1057)
        data = bytearray(accounts[0].data)
        offset = 376 if name == "mSOL" else 258
        data[offset:offset + 8] = (int.from_bytes(data[offset:offset + 8], "little") + 12345).to_bytes(8, "little")
        drift = replace(accounts[0], data=bytes(data)), accounts[1]
        same = book.refresh(name, drift, 1057)
        if name != "mSOL":
            data[274:282] = (1058).to_bytes(8, "little")
            drift = replace(accounts[0], data=bytes(data)), accounts[1]
        next_rate = book.refresh(name, drift, 1058)
        result["providers"].append({"name": name, "numerator": str(observation.numerator), "denominator": str(observation.denominator),
          "one_token_basis": str(-(-(10**9 * observation.numerator) // observation.denominator)),
          "same_epoch_drift_rate": [str(same.numerator), str(same.denominator)],
          "next_epoch_drift_rate": [str(next_rate.numerator), str(next_rate.denominator)],
          "numeric_revisions": book.assets[name].numeric_revision})
    book = ProviderBook()
    accounts = {name: snapshot(name) for name in IDENTITIES}
    model = Model(load_config(), 1791201600); model.add_hill("h")
    for name, data in accounts.items():
        model.allow_asset(name, 9, book.refresh(name, data, 1057))
    for name, basis in (("jitoSOL", 4_000_000_000), ("JupSOL", 100_000_000)):
        model.pledge(name, "h", name, int(Fraction(basis) / book.assets[name].quote.rate))
    skipped_model, skipped_book = deepcopy(model), deepcopy(book)
    fresh, lagging = book.apply_campaign(model, list(accounts), accounts, 1058)
    result["grace"] = {"epoch": 1058, "lagging": list(lagging), "fresh": list(fresh),
                       "backing_before_trigger": str(model.backing("h"))}
    expired_model, expired_book, probe = deepcopy(model), deepcopy(book), deepcopy(model)
    probe.pledge("trigger", "h", "mSOL", int(Fraction(7_000_000_000) / fresh["mSOL"]))
    result["grace"]["seven_sol_bonds"] = probe.hills["h"].bonded_at is not None
    model.pledge("trigger", "h", "mSOL", int(Fraction(11_000_000_000) / fresh["mSOL"]))
    result["grace"]["founding_count"] = sum(lot.founding for lot in model.lots.values())
    result["grace"]["frozen_quotes"] = {name: [str(rate.numerator), str(rate.denominator)] for name, rate in lagging.items()}
    expired_book.apply_campaign(expired_model, list(accounts), accounts, 1059)
    expired_model.pledge("trigger", "h", "mSOL", int(Fraction(11_000_000_000) / fresh["mSOL"]))
    result["grace"]["expired_founding_count"] = sum(lot.founding for lot in expired_model.lots.values())
    previous = deepcopy(accounts)
    for name in ("jitoSOL", "JupSOL"):
        data = bytearray(accounts[name][0].data)
        data[258:266] = (int.from_bytes(data[258:266], "little") * 2).to_bytes(8, "little")
        data[274:282] = (1058).to_bytes(8, "little")
        previous[name] = replace(accounts[name][0], data=bytes(data)), accounts[name][1]
    fresh, lagging = skipped_book.apply_campaign(skipped_model, list(previous), previous, 1059)
    result["skipped_refresh_grace"] = {"epoch": 1059, "last_admitted_pool_epoch": 1057,
        "provider_update_epoch": 1058, "backing_before_trigger": str(skipped_model.backing("h")),
        "frozen_quotes": {name: [str(rate.numerator), str(rate.denominator)] for name, rate in lagging.items()}}
    skipped_model.pledge("trigger", "h", "mSOL", int(Fraction(11_000_000_000) / fresh["mSOL"]))
    result["skipped_refresh_grace"]["founding_count"] = sum(lot.founding for lot in skipped_model.lots.values())
    result["skipped_refresh_grace"]["prebond_units"] = {lot.asset: str(lot.owner_units)
        for lot in skipped_model.lots.values() if lot.asset in lagging}
    return result


def main():
    parser = argparse.ArgumentParser(__doc__); parser.add_argument("--check", action="store_true"); args = parser.parse_args()
    content = json.dumps(vectors(), indent=2) + "\n"
    if args.check:
        if OUTPUT.read_text() != content: raise SystemExit("provider vectors differ")
        print("3 snapshot rates, 6 epoch-admission vectors, founding grace/expiry and skipped-refresh quotes match")
    else:
        OUTPUT.write_text(content)


if __name__ == "__main__": main()
