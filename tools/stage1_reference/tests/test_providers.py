"""Captured mainnet bytes plus EXPLICITLY SIMULATED malicious/epoch variants."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
import pytest
from tools.stage1_reference.providers import FIXTURES, IDENTITIES, ProviderBook, observe, snapshot

EXPECTED = {
    "jitoSOL": (10650132353883915, 8153209489021421),
    "mSOL": (2254985557764365, 1596971612132375),
    "JupSOL": (5194388907066853, 4277554095630348),
}
EPOCH = 1057


def changed(accounts, offset, value, width=8):
    state, mint = accounts
    data = bytearray(state.data)
    data[offset:offset + width] = value.to_bytes(width, "little")
    return replace(state, data=bytes(data)), mint


@pytest.mark.parametrize("name", IDENTITIES)
def test_snapshot_rates_equal_hand_computed_rationals_and_source_hashes(name):
    accounts = snapshot(name)
    result = observe(name, accounts, EPOCH)
    assert (result.numerator, result.denominator) == EXPECTED[name]
    assert result.current
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    for filename, account in zip(IDENTITIES[name][:2], accounts):
        recorded = next(row for row in manifest["accounts"] if row["name"] == filename)
        assert hashlib.sha256(account.data).hexdigest() == recorded["sha256"]
        assert (FIXTURES / f"{filename}.bin").read_bytes() == account.data


@pytest.mark.parametrize("name", IDENTITIES)
@pytest.mark.parametrize("fault", ["owner", "pool", "mint", "layout", "mint_owner", "truncated"])
def test_bad_provenance_never_changes_admission_or_outage(name, fault):
    accounts = snapshot(name)
    book = ProviderBook()
    book.refresh(name, accounts, EPOCH)
    state, mint = accounts
    if fault == "owner": state = replace(state, owner=mint.owner)
    if fault == "pool": state = replace(state, address=mint.address)
    if fault == "mint": mint = replace(mint, address=state.address)
    if fault == "mint_owner": mint = replace(mint, owner=state.owner)
    if fault == "layout": state = replace(state, data=b"\xff" + state.data[1:])
    if fault == "truncated": state = replace(state, data=state.data[:-1])
    before = deepcopy(book.assets)
    with pytest.raises(ValueError): book.refresh(name, (state, mint), EPOCH)
    with pytest.raises(ValueError): book.exit_rate(name, (state, mint), EPOCH + 5, 999999999)
    assert book.assets == before


@pytest.mark.parametrize("name", IDENTITIES)
def test_epoch_admission_retains_one_value_then_reprices_once(name):
    accounts = snapshot(name)
    book = ProviderBook()
    original = book.refresh(name, accounts, EPOCH)
    drift = changed(accounts, 376 if name == "mSOL" else 258,
                    int.from_bytes(accounts[0].data[(376 if name == "mSOL" else 258):][:8], "little") + 12345)
    assert book.refresh(name, drift, EPOCH) == original
    assert book.assets[name].numeric_revision == 1
    if name != "mSOL": drift = changed(drift, 274, EPOCH + 1)
    assert book.refresh(name, drift, EPOCH + 1) > original
    assert book.assets[name].numeric_revision == 2
    if name != "mSOL": drift = changed(drift, 274, EPOCH + 2)
    book.refresh(name, drift, EPOCH + 2)
    assert book.assets[name].numeric_revision == 2  # numerical equality keeps campaign quotes


def test_stale_epoch_rejection_cannot_revoke_current_admission():
    book = ProviderBook(); accounts = snapshot("jitoSOL")
    book.refresh("jitoSOL", accounts, EPOCH)
    stale = changed(accounts, 274, EPOCH - 1)
    before = deepcopy(book.assets)
    with pytest.raises(ValueError, match="stale"): book.refresh("jitoSOL", stale, EPOCH)
    assert book.assets == before and book.fresh("jitoSOL", EPOCH)
    assert book.exit_rate("jitoSOL", stale, EPOCH, 100) == Fraction(*EXPECTED["jitoSOL"])


def test_bond_refresh_cannot_exclude_a_healthy_four_sol_lot(factory):
    book = ProviderBook(); x, y = snapshot("jitoSOL"), snapshot("mSOL")
    old = book.refresh("jitoSOL", x, EPOCH)
    from tools.stage1_reference.model import Model
    from tools.stage1_reference.config import load_config
    model = Model(load_config(), 1791201600); model.add_hill("h")
    model.allow_asset("jitoSOL", 9, old)
    model.allow_asset("mSOL", 9, observe("mSOL", y, EPOCH).rate)
    units = int(Fraction(4_000_000_000, 1) / old)
    lot = model.pledge("x", "h", "jitoSOL", units)
    assert not book.fresh("jitoSOL", EPOCH + 1)
    current_x = changed(x, 274, EPOCH + 1)
    with pytest.raises(ValueError): book.refresh_backed(["jitoSOL", "mSOL"], {"mSOL": y}, EPOCH + 1)
    rates = book.refresh_backed(["jitoSOL", "mSOL"], {"jitoSOL": current_x, "mSOL": y}, EPOCH + 1)
    for name, rate in rates.items(): model.observe_rate(name, rate)
    model.pledge("y", "h", "mSOL", int(Fraction(7_000_000_000, 1) / rates["mSOL"]))
    assert model.lots[lot].founding and model.hills["h"].founder == "y"


def test_outage_grace_requires_authentic_current_unavailability_and_resets_after_recovery():
    book = ProviderBook(); accounts = snapshot("JupSOL")
    book.refresh("JupSOL", accounts, EPOCH)
    with pytest.raises(ValueError): book.record_outage("JupSOL", accounts, EPOCH + 1, 99)
    book.record_outage("JupSOL", accounts, EPOCH + 2, 100)
    book.record_outage("JupSOL", accounts, EPOCH + 2, 200)
    assert book.assets["JupSOL"].stale_since == 100
    with pytest.raises(ValueError): book.exit_rate("JupSOL", accounts, EPOCH + 5, 604899)
    assert book.exit_rate("JupSOL", accounts, EPOCH + 5, 604900) is None
    recovered = changed(accounts, 274, EPOCH + 4)
    with pytest.raises(ValueError): book.exit_rate("JupSOL", recovered, EPOCH + 5, 604900)
    with pytest.raises(ValueError): book.record_outage("JupSOL", recovered, EPOCH + 5, 604900)
    assert book.assets["JupSOL"].stale_since == 100  # Native prior epoch is still grace.
    book.record_outage("JupSOL", recovered, EPOCH + 6, 604901)
    assert book.assets["JupSOL"].stale_since == 604901
    with pytest.raises(ValueError, match="current rate"): book.exit_rate("JupSOL", recovered, EPOCH + 4, 9000000)


def test_jupsol_deployed_exit_configuration_is_verified_without_rate_discount():
    result = observe("JupSOL", snapshot("JupSOL"), EPOCH)
    assert result.exits_verified
    assert result.rate == Fraction(*EXPECTED["JupSOL"])


def test_virtual_supply_can_exceed_live_supply_after_independent_burn():
    state, mint = snapshot("mSOL")
    data = bytearray(mint.data); data[36:44] = (1).to_bytes(8, "little")
    assert observe("mSOL", (state, replace(mint, data=bytes(data))), EPOCH).rate == Fraction(*EXPECTED["mSOL"])


def test_marinade_pause_does_not_erase_the_in_kind_accounting_quote():
    paused = changed(snapshot("mSOL"), 608, 1, 1)
    book = ProviderBook()
    assert book.refresh("mSOL", paused, EPOCH + 1) == Fraction(*EXPECTED["mSOL"])
    assert book.exit_rate("mSOL", paused, EPOCH + 1, 100) == Fraction(*EXPECTED["mSOL"])


@pytest.mark.parametrize("name,fault", [(name, fault) for name in IDENTITIES
    for fault in ("layout", "zero_supply")] + [("mSOL", "tickets")])
def test_authenticated_unreadability_still_allows_mature_in_kind_exit(name, fault):
    accounts = snapshot(name)
    book = ProviderBook(); book.refresh(name, accounts, EPOCH)
    if fault == "layout": broken = changed(accounts, 0, 255, 1)
    elif fault == "tickets": broken = changed(accounts, 528, 2**64 - 1)
    else: broken = changed(accounts, 504 if name == "mSOL" else 266, 0)
    book.record_outage(name, broken, EPOCH + 2, 100)
    # An unsupported layout/accounting failure can keep changing without ever
    # yielding a usable quote; byte churn must not restart the seven-day timer.
    churn = changed(broken, len(broken[0].data) - 1, 1, 1)
    book.record_outage(name, churn, EPOCH + 3, 200)
    assert book.assets[name].stale_since == 100
    with pytest.raises(ValueError): book.exit_rate(name, churn, EPOCH + 5, 604899)
    assert book.exit_rate(name, churn, EPOCH + 5, 604900) is None
    assert book.assets[name].quote.rate == Fraction(*EXPECTED[name])


@pytest.mark.parametrize("name", ["jitoSOL", "JupSOL"])
def test_lagging_lots_keep_founding_status_without_helping_the_line(name):
    from tools.stage1_reference.model import Model
    from tools.stage1_reference.config import load_config
    book = ProviderBook(); accounts = {name: snapshot(name), "mSOL": snapshot("mSOL")}
    for asset, data in accounts.items(): book.refresh(asset, data, EPOCH)
    model = Model(load_config(), 1791201600); model.add_hill("h")
    for asset in accounts: model.allow_asset(asset, 9, book.assets[asset].quote.rate)
    rate = book.assets[name].quote.rate
    lot = model.pledge("x", "h", name, int(Fraction(4_000_000_000) / rate))
    fresh, lagging = book.apply_campaign(model, list(accounts), accounts, EPOCH + 1)
    assert set(fresh) == {"mSOL"} and set(lagging) == {name}
    model.pledge("y", "h", "mSOL", int(Fraction(7_000_000_000) / fresh["mSOL"]))
    assert model.hills["h"].bonded_at is None
    expired_model, expired_book = deepcopy(model), deepcopy(book)
    model.pledge("z", "h", "mSOL", int(Fraction(4_000_000_000) / fresh["mSOL"]))
    assert model.lots[lot].founding and model.hills["h"].founder == "z"
    _, expired = expired_book.apply_campaign(expired_model, list(accounts), accounts, EPOCH + 2)
    expired_model.pledge("z", "h", "mSOL", int(Fraction(4_000_000_000) / fresh["mSOL"]))
    assert not expired_model.lots[lot].founding and expired_model.hills["h"].founder == "z"
    assert expired == {} and not book.lagging("mSOL", accounts["mSOL"], EPOCH + 1)


def test_opaque_outage_recovery_and_category_changes_restart_grace():
    name = "mSOL"; accounts = snapshot(name)
    book = ProviderBook(); book.refresh(name, accounts, EPOCH)
    broken = changed(accounts, 528, 2**64 - 1)
    with pytest.raises(ValueError): book.record_outage(name, broken, EPOCH, 50)
    assert book.exit_rate(name, broken, EPOCH, 50) == Fraction(*EXPECTED[name])
    book.record_outage(name, broken, EPOCH + 1, 100)
    with pytest.raises(ValueError): book.exit_rate(name, accounts, EPOCH + 5, 700000)
    book.refresh(name, accounts, EPOCH + 5)
    assert book.assets[name].stale_since is None
    book.record_outage(name, broken, EPOCH + 6, 700001)
    with pytest.raises(ValueError): book.exit_rate(name, broken, EPOCH + 6, 700002)
    book.refresh(name, accounts, EPOCH + 6)
    assert book.assets[name].stale_since is None
    pool = "jitoSOL"; data = snapshot(pool)
    book.refresh(pool, data, EPOCH)
    book.record_outage(pool, data, EPOCH + 2, 100)
    book.record_outage(pool, changed(data, 0, 255, 1), EPOCH + 3, 200)
    assert book.assets[pool].stale_since == 200
    book.record_outage(pool, data, EPOCH + 4, 300)
    assert book.assets[pool].stale_since == 300


@pytest.mark.parametrize("name", IDENTITIES)
def test_unreadable_current_cache_blocks_intake_and_harvest_but_preserves_exit_quote(name):
    from tools.stage1_reference.model import Model
    from tools.stage1_reference.config import load_config
    accounts = snapshot(name); book = ProviderBook()
    rate = book.refresh(name, accounts, EPOCH)
    model = Model(load_config(), 1791201600); model.add_hill("h")
    model.allow_asset(name, 9, rate)
    lot = model.pledge("x", "h", name, int(Fraction(11_000_000_000) / rate))
    at = 376 if name == "mSOL" else 258
    drift = changed(accounts, at, int.from_bytes(accounts[0].data[at:at + 8], "little") + EXPECTED[name][0])
    if name != "mSOL": drift = changed(drift, 274, EPOCH + 1)
    book.apply_campaign(model, [name], {name: drift}, EPOCH + 1)
    model.harvest(lot, 1)  # A valid doubled rate exposes genuine surplus.
    token = bytearray(drift[1].data); token[36:44] = (EXPECTED[name][1] * 2).to_bytes(8, "little")
    broken = drift[0], replace(drift[1], data=bytes(token))
    before = deepcopy(book.assets)
    fresh, lagging = book.apply_campaign(model, [name], {name: broken}, EPOCH + 1)
    assert fresh == lagging == {}
    assert book.assets == before and model._fresh(name)
    assert book.exit_rate(name, broken, EPOCH + 1, 100) == rate * 2
    frozen = deepcopy(model.__dict__)
    with pytest.raises(ValueError): model.pledge("bad", "h", name, 1)
    with pytest.raises(ValueError): model.harvest(lot, 1)
    assert model.__dict__ == frozen


@pytest.mark.parametrize("name", ["jitoSOL", "JupSOL"])
@pytest.mark.parametrize("cached", [True, False])
def test_lagging_uses_provider_epoch_and_quote_without_previous_epoch_admission(name, cached):
    from tools.stage1_reference.model import Model
    from tools.stage1_reference.config import load_config
    accounts = snapshot(name); book = ProviderBook()
    rate = observe(name, accounts, EPOCH).rate
    if cached: book.refresh(name, accounts, EPOCH)
    model = Model(load_config(), 1791201600); model.add_hill("h")
    model.allow_asset(name, 9, rate)
    model.allow_asset("mSOL", 9, observe("mSOL", snapshot("mSOL"), EPOCH).rate)
    lot = model.pledge("x", "h", name, int(Fraction(4_000_000_000) / rate))
    old_lot = deepcopy(model.lots[lot])
    previous = changed(changed(accounts, 258, EXPECTED[name][0] * 2), 274, EPOCH + 1)
    provided = {name: previous, "mSOL": snapshot("mSOL")}
    fresh, lagging = book.apply_campaign(model, list(provided), provided, EPOCH + 2)
    assert lagging == {name: rate * 2} and set(fresh) == {"mSOL"}
    assert model.backing("h") == 0
    expired_model, expired_book = deepcopy(model), deepcopy(book)
    model.pledge("trigger", "h", "mSOL", int(Fraction(11_000_000_000) / fresh["mSOL"]))
    assert model.lots[lot].founding
    protected = Fraction(old_lot.basis) / (rate * 2)
    ceil = -(-protected.numerator // protected.denominator)
    assert model.lots[lot].owner_units == old_lot.units - ceil
    expired_book.apply_campaign(expired_model, list(provided), provided, EPOCH + 3)
    expired_model.pledge("trigger", "h", "mSOL", int(Fraction(11_000_000_000) / fresh["mSOL"]))
    assert not expired_model.lots[lot].founding
    assert not book.lagging("mSOL", provided["mSOL"], 0)


@pytest.mark.parametrize("name", ["jitoSOL", "JupSOL"])
def test_lagging_marker_overrides_current_campaign_cache_but_not_exit_quote(name):
    from tools.stage1_reference.model import Model
    from tools.stage1_reference.config import load_config
    accounts = snapshot(name); book = ProviderBook()
    rate = book.refresh(name, accounts, EPOCH)
    model = Model(load_config(), 1791201600); model.add_hill("h")
    model.allow_asset(name, 9, rate)
    model.allow_asset("mSOL", 9, observe("mSOL", snapshot("mSOL"), EPOCH).rate)
    lot = model.pledge("x", "h", name, int(Fraction(4_000_000_000) / rate))
    previous = changed(changed(accounts, 258, EXPECTED[name][0] * 2), 274, EPOCH - 1)
    provided = {name: previous, "mSOL": snapshot("mSOL")}
    fresh, lagging = book.apply_campaign(model, list(provided), provided, EPOCH)
    assert set(fresh) == {"mSOL"} and lagging == {name: rate * 2}
    assert model.backing("h") == 0
    assert book.exit_rate(name, previous, EPOCH, 100) == model._exit_rate(name) == rate
    with pytest.raises(ValueError, match="rate stale"):
        model.pledge("incoming", "h", name, int(Fraction(1_000_000_000) / rate))
    model.pledge("trigger", "h", "mSOL", int(Fraction(11_000_000_000) / fresh["mSOL"]))
    assert model.lots[lot].founding and model.lots[lot].owner_units > 0
    with pytest.raises(ValueError, match="rate stale"):
        model.pledge("incoming", "h", name, int(Fraction(1_000_000_000) / rate))
