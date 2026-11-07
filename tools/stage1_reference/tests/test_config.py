from fractions import Fraction

import pytest
import yaml

from tools.stage1_reference.config import DIAMOND, load_config


def edit_config(tmp_path, group, changes):
    data = yaml.load(DIAMOND.read_text(), Loader=yaml.BaseLoader)
    data["stage1"][group].update(changes)
    path = tmp_path / "diamond.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def ratified_config(tmp_path):
    data = yaml.load(DIAMOND.read_text(), Loader=yaml.BaseLoader)
    for section in data["stage1"].values():
        section.pop("provisional", None)
        section["status"] = "ratified"
        section["ratified"] = "2026-10-13"
    path = tmp_path / "ratified.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_ratified_sections_are_accepted(tmp_path):
    assert load_config(ratified_config(tmp_path)).fee == Fraction(1, 10)


@pytest.mark.parametrize("section", ["principal", "realized_yield", "pilot_caps", "seasons", "rider_week_cap", "boosts", "mechanics", "additional_section"])
@pytest.mark.parametrize("status", [None, "provisional", "unknown"])
def test_every_section_requires_known_ratified_status(tmp_path, section, status):
    path = ratified_config(tmp_path)
    data = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
    values = data["stage1"].setdefault(section, {})
    if status is None:
        values.pop("status", None)
    else:
        values["status"] = status
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match="status: ratified"):
        load_config(path)


def test_ratified_numbers_come_from_yaml_without_float_conversion(tmp_path):
    config = load_config(edit_config(tmp_path, "rider_week_cap", {"multiplier": "7/2"}))
    assert config.cap_multiplier == Fraction(7, 2)
    config = load_config(edit_config(tmp_path, "pilot_caps", {"per_hill_lamports": "987654321"}))
    assert config.hill_cap == 987654321
    assert load_config(edit_config(tmp_path, "seasons", {"weeks": "13"})).season_weeks == 13
    assert not load_config(edit_config(tmp_path, "boosts", {"enabled": "false"})).boosts_enabled


@pytest.mark.parametrize("group,key,value", [
    ("principal", "return_asset", "USDC"),
    ("realized_yield", "recognition", "rate_observation"),
    ("rider_week_cap", "comparison", "sum_dollars"),
    ("seasons", "anchor", "per_hill"),
    ("boosts", "irrevocable", "false"),
    ("pilot_caps", "status", "unknown"),
])
def test_unsupported_semantics_never_silently_use_defaults(tmp_path, group, key, value):
    with pytest.raises(ValueError):
        load_config(edit_config(tmp_path, group, {key: value}))


@pytest.mark.parametrize("key,value", [("finalization_grace_seconds", "-1"), ("dung_decimals", "-1"), ("tss_decimals", "-1")])
def test_invalid_time_or_precision_config_is_rejected(tmp_path, key, value):
    with pytest.raises(ValueError):
        load_config(edit_config(tmp_path, "mechanics", {key: value}))
