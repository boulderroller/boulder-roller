from app.routes.admin_platform import _supply_state_from_indexed_row


def test_admin_supply_uses_exact_spl_mint_supply_not_legacy_derivation() -> None:
    state = _supply_state_from_indexed_row(
        {
            "max_supply": "1000000000000000000",
            "total_minted": "100",
            "total_burned": "5",
            "circulating": "95",
            "spl_mint_supply": "91",
            "community_minted": "18446744073709551615",
            "treasury_minted": "7",
            "team_minted": "8",
            "investor_minted": "9",
            "pol_minted": "10",
        }
    )

    assert state.total_minted_base_units == "100"
    assert state.protocol_burned_base_units == "5"
    assert state.circulating_supply_base_units == "91"
    assert state.circulating_source == "spl_mint_supply"
    assert state.community_minted_base_units == "18446744073709551615"
    assert state.treasury_minted_base_units == "7"
    assert state.team_minted_base_units == "8"
    assert state.investor_minted_base_units == "9"
    assert state.pol_minted_base_units == "10"


def test_admin_supply_never_fabricates_zero_when_mint_supply_is_unavailable() -> None:
    state = _supply_state_from_indexed_row(
        {
            "total_minted": "100",
            "total_burned": "5",
            "circulating": "95",
            "spl_mint_supply": None,
        }
    )

    assert state.circulating_supply_base_units is None
    assert state.circulating_source == "unavailable"
