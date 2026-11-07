from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "prove_agent_dogfood_ride.py"
spec = importlib.util.spec_from_file_location("prove_agent_dogfood_ride", MODULE_PATH)
assert spec is not None
dogfood = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = dogfood
spec.loader.exec_module(dogfood)


def test_generate_current_power_tcx_is_reward_grade(tmp_path: Path) -> None:
    completed_at = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    tcx_bytes = dogfood.generate_tcx_bytes(
        completed_at=completed_at,
        duration_minutes=50,
        sample_seconds=5,
        start_lat=40.0,
        start_lon=-105.0,
        base_altitude_m=1600,
        elevation_gain_m=400,
        distance_m=9000,
    )

    summary = dogfood.validate_tcx_bytes(
        tcx_bytes,
        path=tmp_path / "dogfood.tcx",
        now=completed_at + timedelta(minutes=5),
    )

    assert tcx_bytes.startswith(b"<TrainingCenterDatabase")
    assert summary.file_type == "tcx"
    assert summary.trackpoints == 601
    assert summary.gps_points == summary.trackpoints
    assert summary.power_points == summary.trackpoints
    assert summary.heart_rate_points == summary.trackpoints
    assert summary.cadence_points == summary.trackpoints
    assert summary.avg_power_w > 200
    assert summary.elevation_gain_m > 390
    assert summary.freshness_seconds == 300
    assert summary.reward_grade_input is True
    dogfood.assert_parser_visible_tcx(tcx_bytes)


def test_validate_rejects_missing_power() -> None:
    completed_at = datetime(2026, 6, 12, 18, 0, tzinfo=timezone.utc)
    tcx_bytes = dogfood.generate_tcx_bytes(
        completed_at=completed_at,
        duration_minutes=10,
        sample_seconds=5,
        start_lat=40.0,
        start_lon=-105.0,
        base_altitude_m=1600,
        elevation_gain_m=100,
        distance_m=2000,
    )
    route_only = tcx_bytes.replace(b"<Watts>", b"<NoWatts>").replace(
        b"</Watts>", b"</NoWatts>"
    )

    with pytest.raises(ValueError, match="watts"):
        dogfood.validate_tcx_bytes(route_only, now=completed_at + timedelta(minutes=5))


def test_live_rollout_status_requires_collect_dung(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(api_url: str, method: str, path: str, **kwargs):
        return dogfood.HttpResult(
            ok=True,
            status=200,
            body={
                "environment": "production",
                "solana_stub_mode": False,
                "auth_signature_bypass_effective": False,
                "dev_routes_enabled": False,
                "balance_rollout": {
                    "stage": "collect_dung",
                    "enabled_actions": ["collect_dung"],
                    "action_order": list(dogfood.EXPECTED_BALANCE_ACTION_ORDER),
                    "enforced": True,
                    "order_valid": True,
                    "blockers": [],
                },
            },
        )

    monkeypatch.setattr(dogfood, "api_request", fake_request)

    status = dogfood.assert_live_rollout_status("https://api.boulderroller.xyz")

    assert status["balance_rollout"]["enabled_actions"] == ["collect_dung"]


def test_live_rollout_status_rejects_closed_collect_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_request(api_url: str, method: str, path: str, **kwargs):
        return dogfood.HttpResult(
            ok=True,
            status=200,
            body={
                "environment": "production",
                "solana_stub_mode": False,
                "auth_signature_bypass_effective": False,
                "dev_routes_enabled": False,
                "balance_rollout": {
                    "stage": "off",
                    "enabled_actions": [],
                    "action_order": list(dogfood.EXPECTED_BALANCE_ACTION_ORDER),
                    "enforced": True,
                    "order_valid": True,
                    "blockers": [],
                },
            },
        )

    monkeypatch.setattr(dogfood, "api_request", fake_request)

    with pytest.raises(RuntimeError, match="collect_dung not enabled"):
        dogfood.assert_live_rollout_status("https://api.boulderroller.xyz")


def test_probe_pending_dung_reports_positive_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_request(api_url: str, method: str, path: str, **kwargs):
        calls.append(path)
        if path == "/vaults/my/stakes":
            return dogfood.HttpResult(ok=True, status=200, body={"stakes": [{"vault_id": 7}]})
        if path == "/vaults?limit=3":
            return dogfood.HttpResult(
                ok=True,
                status=200,
                body={
                    "vaults": [
                        {"id": 7, "name": "Ready", "on_chain_active": True},
                        {"id": 8, "name": "Empty", "on_chain_active": True},
                        {"id": 9, "name": "Stale", "on_chain_active": True},
                    ]
                },
            )
        if path == "/vaults/7/pending-rewards":
            return dogfood.HttpResult(
                ok=True,
                status=200,
                body={"total_pending": 1250, "net_estimate": 1187.5},
            )
        if path == "/vaults/8/pending-rewards":
            return dogfood.HttpResult(ok=True, status=200, body={"total_pending": 0})
        if path == "/vaults/9/pending-rewards":
            return dogfood.HttpResult(ok=False, status=404, body={"detail": "Vault not found on-chain"})
        raise AssertionError(path)

    monkeypatch.setattr(dogfood, "api_request", fake_request)

    probe = dogfood.probe_pending_dung("https://api.boulderroller.xyz", "token", limit=3)

    assert calls == [
        "/vaults/my/stakes",
        "/vaults?limit=3",
        "/vaults/7/pending-rewards",
        "/vaults/8/pending-rewards",
        "/vaults/9/pending-rewards",
    ]
    assert probe["stake_count"] == 1
    assert probe["vault_count"] == 3
    assert probe["positive"] == [
        {
            "vault_id": 7,
            "vault_name": "Ready",
            "on_chain_active": True,
            "status": 200,
            "total_pending": 1250.0,
            "net_estimate": 1187.5,
        }
    ]
    assert probe["checked"][1]["total_pending"] == 0.0
    assert probe["errors"] == [
        {
            "vault_id": 9,
            "vault_name": "Stale",
            "on_chain_active": True,
            "status": 404,
            "detail": "Vault not found on-chain",
        }
    ]


def test_probe_pending_dung_requires_positive_limit() -> None:
    with pytest.raises(ValueError, match="vault scan limit"):
        dogfood.probe_pending_dung("https://api.boulderroller.xyz", "token", limit=0)
