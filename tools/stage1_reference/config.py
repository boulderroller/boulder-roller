"""Read decimal YAML scalars as strings: binary floats never enter arithmetic."""

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import yaml

DIAMOND = Path(__file__).resolve().parents[2] / "history/hill-bonding-diamond-2026-10-08/diamond.yaml"


@dataclass(frozen=True)
class Config:
    line: int
    live_fraction: Fraction
    bond_lock_weeks: int
    notice_weeks: int
    lock_weights: dict[int, Fraction]
    season_weeks: int
    weekday: int
    hour: int
    field: int
    daily_ascents: int
    upload_days: int
    fee: Fraction
    split: dict[str, Fraction]
    cap_multiplier: Fraction
    token_cap: int
    hill_cap: int
    total_cap: int
    cap_delay: int
    grace: int
    held_weeks: int
    boosts_enabled: bool
    boost_min: int
    boost_max: int
    cash_requires_live: bool
    dung_scale: int
    tss_scale: int
    dung_per_tss: Fraction
    dung_split: dict[str, Fraction]
    rider_dung_split: dict[str, Fraction]
    founder_multiplier: int


def load_config(path=DIAMOND, city="philadelphia") -> Config:
    with Path(path).open() as stream:
        data = yaml.load(stream, Loader=yaml.BaseLoader)
    stage = data["stage1"]
    required = {"principal", "realized_yield", "pilot_caps", "seasons", "rider_week_cap", "boosts", "mechanics"}
    if not required.issubset(stage):
        raise ValueError("every required stage1 section must have status: ratified")
    for name, section in stage.items():
        if not isinstance(section, dict) or section.get("status") != "ratified":
            raise ValueError(f"{name}: stage1 section must have status: ratified")
    supported = {
        "principal": {"basis": "deposit_sol_redemption_value", "return_asset": "deposited_token", "losses": "originating_lot", "stale_exit": "full_lot_in_kind_after_seven_stale_days", "stale_campaign_tokens": "zero_backing_excluded_cancel_or_convert"},
        "pilot_caps": {"measurement": "held_deposit_basis"},
        "realized_yield": {"recognition": "transferred_surplus_units", "payout": "in_kind", "below_basis_harvest": "false"},
        "seasons": {"anchor": "city_launch"},
        "rider_week_cap": {"population": "positive_combined_entitlements", "comparison": "per_asset", "excess": "ascents_with_headroom_then_hold"},
        "boosts": {"escrow_at_posting": "true", "irrevocable": "true", "fee": "0", "earns_dung": "false", "split": "rider_split"},
        "mechanics": {"live_measurement": "week_open", "partial_bond_week": "hold_yield", "dung_partial_bond_week": "unminted", "prebond_earnings": "segregate_units_at_bond", "deactivation_rewards": "riders_until_return", "founder_bonus": "hill_first_full_bonded_season", "fee_scope": "module_asset_lifetime", "boost_allocation": "equal_hill_ride_week", "boost_after_window": "hold_for_pool"},
    }
    for group, modes in supported.items():
        for key, value in modes.items():
            if stage[group][key] != value:
                raise ValueError(f"unsupported stage1.{group}.{key}")
    for key, value in {"basis_rounding": "ceil_lamport", "partial_exits": "proportional_units_owner_dust"}.items():
        if stage["mechanics"][key] != value:
            raise ValueError(f"unsupported stage1.mechanics.{key}")
    def shares(values):
        result = {key: Fraction(value) for key, value in values.items()}
        if sum(result.values()) != 1 or any(value < 0 for value in result.values()):
            raise ValueError("shares must be nonnegative and sum to one")
        return result
    def boolean(value):
        if value not in ("true", "false"):
            raise ValueError("expected YAML boolean")
        return value == "true"
    caps, seasons, boosts, mechanics = (stage[key] for key in ("pilot_caps", "seasons", "boosts", "mechanics"))
    if any(not 0 <= int(mechanics[key]) <= 18 for key in ("dung_decimals", "tss_decimals")):
        raise ValueError("precision must be 0 through 18 decimal places")
    if int(mechanics["finalization_grace_seconds"]) < 0:
        raise ValueError("finalization grace must be nonnegative")
    config = Config(
        line=int(Fraction(data["line_sol"][city]) * 10**9),
        live_fraction=Fraction(data["live_fraction"]),
        bond_lock_weeks=int(data["bond_lock_weeks"]), notice_weeks=int(data["notice_weeks"]),
        lock_weights={int(key): Fraction(value) for key, value in data["lock_weights"].items()},
        season_weeks=int(seasons["weeks"]), weekday=int(seasons["week_start_weekday"]), hour=int(seasons["week_start_hour_utc"]),
        field=int(data["min_field_riders"]), daily_ascents=int(data["ascents_per_hill_per_day"]), upload_days=int(data["upload_window_days"]),
        fee=Fraction(data["fee_on_yield"]), split=shares(data["rider_split"]), cap_multiplier=Fraction(stage["rider_week_cap"]["multiplier"]),
        token_cap=int(caps["per_token_lamports"]), hill_cap=int(caps["per_hill_lamports"]), total_cap=int(caps["total_lamports"]), cap_delay=int(caps["increase_delay_seconds"]),
        grace=int(mechanics["finalization_grace_seconds"]), held_weeks=int(mechanics["held_age_weeks"]),
        boosts_enabled=boolean(boosts["enabled"]), boost_min=int(boosts["min_weeks"]), boost_max=int(boosts["max_weeks"]),
        cash_requires_live=boolean(mechanics["cash_requires_live"]),
        dung_scale=10**int(mechanics["dung_decimals"]), tss_scale=10**int(mechanics["tss_decimals"]),
        dung_per_tss=Fraction(data["dung_per_climb_tss"]), dung_split=shares(data["dung_split"]), rider_dung_split=shares(data["rider_dung_split"]), founder_multiplier=int(data["founding_dung_multiplier"]),
    )
    if not (0 <= config.fee < 1 and 0 < config.live_fraction <= 1 and config.cap_multiplier >= 1):
        raise ValueError("invalid fee, live fraction or cap")
    if any(value <= 0 for value in (config.line, config.season_weeks, config.field, config.held_weeks, config.token_cap, config.hill_cap, config.total_cap, config.cap_delay, config.daily_ascents)):
        raise ValueError("positive limits required")
    if not 1 <= config.boost_min <= config.boost_max:
        raise ValueError("invalid boost window")
    if not 0 <= config.weekday <= 6 or not 0 <= config.hour <= 23 or config.upload_days < 1:
        raise ValueError("invalid calendar")
    if config.bond_lock_weeks < 0 or config.notice_weeks < 0 or config.founder_multiplier < 1 or config.dung_per_tss < 0:
        raise ValueError("invalid duration or mint weight")
    if 0 not in config.lock_weights or config.bond_lock_weeks not in config.lock_weights or any(key < 0 or value < 0 for key, value in config.lock_weights.items()):
        raise ValueError("invalid lock weights")
    return config
