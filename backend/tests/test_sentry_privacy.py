import json
from copy import deepcopy

import pytest

from app.main import _scrub_sensitive_sentry_request_body


@pytest.mark.parametrize("request_present", [False, True])
def test_sentry_removes_personal_data_on_all_routes_and_background_errors(request_present):
    personal = {
        "latitude": 40.123456, "longitude": -79.987654,
        "email": "rider@example.test", "wallet": "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgEUx",
        "access_token": "secret-bearer-token", "display_name": "Private Rider",
    }
    rider_id = "11111111-1111-4111-8111-111111111111"
    event = {
        "event_id": "a" * 32, "level": "error",
        "user": {"id": rider_id, **personal},
        "extra": {"ride_id": rider_id, "status_code": 503, "payload": personal},
        "message": str(personal), "logentry": {"message": str(personal)},
        "exception": {"values": [{"type": "RuntimeError", "value": str(personal),
            "stacktrace": {"frames": [{"filename": "routes/rides.py", "function": "complete",
                "lineno": 123, "vars": {"request": personal}}]}}]},
        "breadcrumbs": {"values": [{"category": "http", "message": str(personal),
            "data": {"status_code": 503, "url": "https://example.test/api?token=secret-bearer-token", **personal}}]},
        "spans": [{"op": "http.client", "description": str(personal), "data": personal}],
    }
    if request_present:
        event["request"] = {"url": "https://example.test/rides?email=rider@example.test#secret-bearer-token",
            "method": "POST", "data": personal, "query_string": str(personal),
            "headers": {"Authorization": "secret-bearer-token"}, "cookies": personal,
            "env": {"RAW_URI": str(personal)}}
    result = _scrub_sensitive_sentry_request_body(deepcopy(event), {})
    encoded = json.dumps(result)
    for value in personal.values():
        assert str(value) not in encoded
    assert result["event_id"] == event["event_id"]
    assert result["user"]["id"] == rider_id
    assert result["extra"] == {"ride_id": rider_id, "status_code": 503}
    frame = result["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert frame["filename"] == "routes/rides.py"
    assert frame["function"] == "complete"
    assert frame["lineno"] == 123


def test_sentry_rejects_untrusted_code_strings_and_source_url_credentials_but_keeps_timing():
    event = {"extra": {"code": "secret-token"},
        "exception": {"values": [{"type": "RuntimeError", "mechanism": {"type": "generic", "handled": False},
            "stacktrace": {"frames": [{"filename": "https://alice:secret-token@example.test/rider@example.test/app.js", "lineno": 3}]}}]},
        "threads": {"values": [{"stacktrace": {"frames": [{"filename": "routes/rides.py", "lineno": 12}]}}]},
        "spans": [{"op": "http.client", "start_timestamp": 100, "timestamp": 101}],
        "breadcrumbs": {"values": [{"category": "http", "timestamp": 100}]}}
    result = _scrub_sensitive_sentry_request_body(event, {})
    assert "secret-token" not in json.dumps(result)
    assert "rider@example.test" not in json.dumps(result)
    assert result["spans"][0]["start_timestamp"] == 100
    assert result["spans"][0]["timestamp"] == 101
    assert result["breadcrumbs"]["values"][0]["timestamp"] == 100
    assert result["threads"]["values"][0]["stacktrace"]["frames"][0]["lineno"] == 12
    assert result["exception"]["values"][0]["mechanism"]["handled"] is False


def test_real_sdk_preserves_log_title_route_and_iso_timings():
    import logging
    import sentry_sdk
    from sentry_sdk.transport import Transport
    captured = []
    class Capture(Transport):
        def capture_envelope(self, envelope):
            for item in envelope.items:
                if item.type in ("event", "transaction"):
                    captured.append(json.loads(item.get_bytes()))
    with sentry_sdk.init(
        dsn="https://public@example.invalid/1", transport=Capture,
        before_send=_scrub_sensitive_sentry_request_body,
        before_send_transaction=_scrub_sensitive_sentry_request_body,
        traces_sample_rate=1.0,
    ):
        sentry_sdk.add_breadcrumb(category="http", message="private rider", timestamp="2026-10-20T12:00:00.123Z")
        try:
            raise RuntimeError('duplicate key value violates unique constraint "vault_stakes_pkey"')
        except RuntimeError:
            logging.getLogger("privacy-probe").error("Vault stake failed for %s", "private rider", exc_info=True)
        logging.getLogger("privacy-probe").error("Static projection failed")
        name = "Private Rider"
        logging.getLogger("privacy-probe").error(f"Failure for {name}: %s", "untrusted value")
        logging.getLogger("privacy-probe").error("Named failure for %(account)s", {"account": "rider", name: "ignored"})
        with sentry_sdk.start_transaction(name="/vaults/{vault_id}/stake", source="route", op="http.server"):
            with sentry_sdk.start_span(op="http.client", description="https://example.invalid?secret=1"):
                pass
        sentry_sdk.flush()
    error = next(event for event in captured if "logentry" in event or "exception" in event)
    assert error["logentry"]["message"] == "Vault stake failed for %s"
    assert error["logentry"]["params"] == ["[Filtered]"]
    assert error["breadcrumbs"]["values"][0]["timestamp"] == "2026-10-20T12:00:00.123000Z"
    assert any(event.get("logentry", {}).get("message") == "Static projection failed" for event in captured)
    transaction = next(event for event in captured if event.get("type") == "transaction")
    assert transaction["transaction"] == "/vaults/{vault_id}/stake"
    assert isinstance(transaction["spans"][0]["timestamp"], str)
    assert isinstance(transaction["spans"][0]["start_timestamp"], str)
    assert "private rider" not in json.dumps(captured)
    assert "Private Rider" not in json.dumps(captured)
