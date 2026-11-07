"""Small deterministic offline outcome probe; all displayed amounts are integers."""

from dataclasses import asdict
from fractions import Fraction
import json

from .config import load_config
from .model import Model, WEEK


def main():
    model = Model(load_config(), launch=1791201600)
    model.allow_asset("example-LST", 9, Fraction(1))
    model.add_hill("example-hill")
    for i in range(5):
        model.register_person(f"person-{i}", f"recipient-{i}")
    lot = model.pledge("example-backer", "example-hill", "example-LST", 10_000_000_000)
    model.boost("example-sponsor", ["example-hill"], 2_000_000, 1, 1)
    model.advance(model.launch + WEEK + model.config.grace)
    model.settle("example-hill", 0)
    model.observe_rate("example-LST", Fraction(6, 5))
    model.harvest(lot, 1_000_000)
    model.sponsor("example-hill", 1_000_000)
    for i in range(5):
        model.upload(f"receipt-{i}", "example-hill", f"person-{i}", model.now, 1_000_000)
    model.set_board("example-hill", ["person-0", "person-1"], "person-2")
    model.advance(model.launch + 2 * WEEK + model.config.grace)
    settlement = model.settle("example-hill", 1)
    claims = settlement.claims["example-LST"]
    leaf = claims.leaves[0]
    collected = model.claim("example-hill", 1, "example-LST", leaf, claims.proof(0), leaf.person, leaf.recipient)
    print(json.dumps({
        "evidence": "offline_reference_model",
        "bonded": model.hills["example-hill"].bonded_at is not None,
        "collected_token_base_units": collected,
        "balances": {asset: model.balances(asset) for asset in model.ledgers},
        "roots": {asset: {"sha256": claims.root.hash.hex(), "sum": claims.root.total, "leaves": len(claims.leaves)} for asset, claims in settlement.claims.items()},
        "dung_mint_data": asdict(settlement.dung),
        "invariants_hold": model.check(),
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
