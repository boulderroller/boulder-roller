from copy import deepcopy

import pytest


@pytest.mark.parametrize("rejection", ["expired", "future", "invalid"])
def test_rejected_observation_preserves_freshness_until_expiry(factory, rejection):
    model = factory()
    model.allow_asset("x", 9, 1)
    expiry = model.now + 60
    model.observe_rate("x", 1, fresh_until=expiry)
    victim = model.pledge("victim", "h", "x", 60)
    admitted = deepcopy(model.assets["x"])

    if rejection == "invalid":
        with pytest.raises(ValueError, match="positive exact"):
            model.observe_rate("x", 0)
    else:
        observed, until = ((model.now - 61, model.now - 1) if rejection == "expired"
                           else (model.now + 1, model.now + 61))
        assert model.observe_rate("x", 9, observed_at=observed, fresh_until=until) is False
    assert model.assets["x"] == admitted
    with pytest.raises(ValueError, match="has not expired"):
        model.mark_rate_stale("x")
    assert model.backing("h") == 60
    model.advance(expiry - 1)
    assert model.backing("h") == 60
    same_token = model.pledge("owner", "h", "x", 1)
    assert model.lots[same_token].basis == 1
    model.advance(expiry)
    assert model.backing("h") == 0
    with pytest.raises(ValueError, match="stale"):
        model.pledge("victim", "h", "x", 1)
    assert model.observe_rate("x", 9, observed_at=expiry - 61, fresh_until=expiry) is False
    assert model.assets["x"] == admitted
    model.pledge("founder", "h", "lst", 100)
    assert model.hills["h"].founder == "founder"
    assert not model.lots[victim].founding and not model.lots[same_token].founding
    assert model.cancel(victim, "victim") == 60
