"""Mobile push send worker (boulderroller-v2-k7387): the payload builder is
a two-category allowlist that fails closed; dry-run logs instead of sending;
placeholder copy structurally cannot ship; the key boundary is one truthful
config error."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services import mobile_push
from app.services.mobile_push import (
    ApnsClient,
    ApnsConfigError,
    MobilePushWorker,
    PushPayloadError,
    build_push_payload,
)


def _notification(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "11111111-1111-4111-8111-111111111111",
        "wallet": "RiderWallet1111111111111111111111111111111",
        "notification_type": "settlement_finalized",
        "title": "Settlement finalized",
        "message": "A vault settlement you participated in finalized on-chain.",
        "data": {"vault_id": 16, "settlement_week": 131},
        "created_at": "2026-08-12T01:00:00+00:00",
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# Payload builder — the allowlist
# ---------------------------------------------------------------------------

def test_settlement_payload_deep_links_to_settlements() -> None:
    payload = build_push_payload(_notification())
    assert payload["br"] == {"category": "settlement"}
    assert payload["aps"]["alert"]["title"].startswith("[COPY: Tim]")


def test_displacement_payload_deep_links_to_the_climb() -> None:
    transition = {"revision": "board:7", "occurredAt": "2026-09-08T20:00:00Z", "climbId": "16", "beforePlace": 4, "afterPlace": None}
    payload = build_push_payload(
        _notification(
            notification_type="leaderboard_bumped",
            data={"vault_id": 16, "vault_name": "Manayunk Wall", "transition": transition},
        )
    )
    assert payload["br"] == {"category": "displacement", "climb_id": "16", "transition": transition}
    assert "Manayunk Wall" in payload["aps"]["alert"]["body"]


def test_displacement_accepts_climb_id_key_variants() -> None:
    for key in ("climb_id", "climbId", "vault_id", "vaultId"):
        payload = build_push_payload(
            _notification(notification_type="leaderboard_bumped", data={key: "c-9"})
        )
        assert payload["br"]["climb_id"] == "c-9"


def test_displacement_without_routable_climb_fails_closed() -> None:
    with pytest.raises(PushPayloadError):
        build_push_payload(
            _notification(notification_type="leaderboard_bumped", data={})
        )


@pytest.mark.parametrize(
    "notification_type",
    [
        "ride_finalized",
        "kudos_created",
        "record_rank_moved",
        "payout_received",
        "login_new_device",
        "",
        "settlement",  # the category name is not the row type
    ],
)
def test_every_other_notification_type_fails_closed(notification_type: str) -> None:
    with pytest.raises(PushPayloadError):
        build_push_payload(_notification(notification_type=notification_type))


def test_copy_slots_are_explicit_tim_placeholders() -> None:
    """The four rider-facing strings stay [COPY: Tim] until ratified; the
    ratification latch stays closed. Flipping the latch without new copy is
    a review-visible code change, not an env flag."""
    assert mobile_push.COPY_RATIFIED is False
    for slot in (
        mobile_push.SETTLEMENT_PUSH_TITLE,
        mobile_push.SETTLEMENT_PUSH_BODY,
        mobile_push.DISPLACEMENT_PUSH_TITLE,
        mobile_push.DISPLACEMENT_PUSH_BODY,
    ):
        assert slot.startswith("[COPY: Tim]")


# ---------------------------------------------------------------------------
# Worker cycle
# ---------------------------------------------------------------------------

class FakeRepo:
    def __init__(
        self,
        pending: list[dict[str, Any]],
        devices: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        self.pending = pending
        self.devices = devices or {}
        self.deliveries: list[dict[str, Any]] = []
        self.deleted_tokens: list[str] = []

    async def pending_push_notifications(self, *, since_iso: str, limit: int = 50):
        return self.pending

    async def devices_for_wallet(self, wallet: str):
        return self.devices.get(wallet, [])

    async def record_push_delivery(self, **kwargs: Any) -> bool:
        self.deliveries.append(kwargs)
        return True

    async def delete_push_token(self, apns_token: str) -> None:
        self.deleted_tokens.append(apns_token)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_dry_run_cycle_logs_and_ledgers_without_sending() -> None:
    wallet = "RiderWallet1111111111111111111111111111111"
    repo = FakeRepo(
        pending=[_notification()],
        devices={wallet: [
            {"device_id": "d1", "apns_token": "ab" * 32, "environment": "sandbox"},
        ]},
    )
    worker = MobilePushWorker(repo, dry_run=True, interval_seconds=1, scan_window_hours=1)
    counters = _run(worker.run_cycle())
    assert counters["dry_run"] == 1
    assert counters["sent"] == 0
    assert len(repo.deliveries) == 1
    delivery = repo.deliveries[0]
    assert delivery["mode"] == "dry_run"
    assert delivery["category"] == "settlement"
    assert delivery["device_count"] == 1
    assert delivery["detail"]["payload"]["br"] == {"category": "settlement"}


def test_cycle_records_no_devices_truthfully() -> None:
    repo = FakeRepo(pending=[_notification()])
    worker = MobilePushWorker(repo, dry_run=True, interval_seconds=1, scan_window_hours=1)
    counters = _run(worker.run_cycle())
    assert counters["no_devices"] == 1
    assert repo.deliveries[0]["mode"] == "no_devices"


def test_cycle_fails_closed_on_unroutable_displacement() -> None:
    repo = FakeRepo(
        pending=[_notification(notification_type="leaderboard_bumped", data={})]
    )
    worker = MobilePushWorker(repo, dry_run=True, interval_seconds=1, scan_window_hours=1)
    counters = _run(worker.run_cycle())
    assert counters["failed"] == 1
    assert repo.deliveries[0]["mode"] == "failed"
    assert "climb id" in repo.deliveries[0]["detail"]["error"]


def test_real_send_is_blocked_while_copy_is_placeholder() -> None:
    """Even with dry-run off and devices present, unratified copy cannot
    ship: the worker refuses before any APNs client is constructed."""
    wallet = "RiderWallet1111111111111111111111111111111"
    repo = FakeRepo(
        pending=[_notification()],
        devices={wallet: [
            {"device_id": "d1", "apns_token": "ab" * 32, "environment": "sandbox"},
        ]},
    )
    worker = MobilePushWorker(repo, dry_run=False, interval_seconds=1, scan_window_hours=1)
    counters = _run(worker.run_cycle())
    assert counters["failed"] == 1
    assert counters["sent"] == 0
    assert repo.deliveries[0]["mode"] == "failed"
    assert "[COPY: Tim]" in repo.deliveries[0]["detail"]["error"]


def test_apns_client_refuses_to_exist_without_the_key() -> None:
    """The key boundary is one truthful config error naming what's missing."""
    with pytest.raises(ApnsConfigError) as excinfo:
        ApnsClient(key_path="", key_id="", team_id="", topic="com.boulderroller.app")
    message = str(excinfo.value)
    assert "APNS_KEY_PATH" in message
    assert "APNS_KEY_ID" in message
    assert "APNS_TEAM_ID" in message

    with pytest.raises(ApnsConfigError) as missing_file:
        ApnsClient(
            key_path="/nonexistent/AuthKey_TEST.p8",
            key_id="TESTKEYID1",
            team_id="TESTTEAMID",
            topic="com.boulderroller.app",
        )
    assert "not found" in str(missing_file.value)


def test_worker_defaults_are_off_and_dry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env defaults: worker disabled, dry-run on — the documented pre-key
    operating state. Flags OFF until the p8 exists."""
    monkeypatch.delenv("MOBILE_PUSH_WORKER_ENABLED", raising=False)
    monkeypatch.delenv("MOBILE_PUSH_DRY_RUN", raising=False)
    assert mobile_push.push_worker_enabled() is False
    worker = MobilePushWorker(FakeRepo(pending=[]), interval_seconds=1, scan_window_hours=1)
    assert worker.dry_run is True
