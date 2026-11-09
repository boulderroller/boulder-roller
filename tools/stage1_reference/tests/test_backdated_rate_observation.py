def test_backdated_admission_never_shortens_an_existing_expiry(factory):
    model = factory()
    expiry = model.now + 60
    model.observe_rate("lst", 1, fresh_until=expiry)
    observed = model.now - 30
    assert model.observe_rate("lst", 2, observed_at=observed, fresh_until=model.now + 30)
    assert model.assets["lst"].rate == 2
    assert model.assets["lst"].observed_at == observed
    assert model.assets["lst"].fresh_until == expiry
    model.advance(expiry - 1)
    lot = model.pledge("owner", "h", "lst", 1)
    assert model.lots[lot].basis == 2
    assert model.observe_rate("lst", 2, fresh_until=model.now + 60)
    assert model.assets["lst"].fresh_until == model.now + 60
