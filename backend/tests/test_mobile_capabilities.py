"""L3.04 mobile-capabilities block (bead boulderroller-v2-f4acp.2.4)."""

from app.routes.health import get_mobile_capabilities


def test_defaults_are_available(monkeypatch) -> None:
    for key in (
        "BR_MOBILE_CAP_RIDE_UPLOAD",
        "BR_MOBILE_CAP_PUSH_REGISTRATION",
        "BR_MOBILE_CAP_PROFILE_WRITES",
    ):
        monkeypatch.delenv(key, raising=False)
    caps = get_mobile_capabilities()
    assert caps.contract_version == "mobile_caps.v1"
    assert caps.owner == "mobile-lane"
    assert caps.ride_upload is True
    assert caps.push_registration is True
    assert caps.profile_writes is True


def test_only_exact_false_disables(monkeypatch) -> None:
    monkeypatch.setenv("BR_MOBILE_CAP_RIDE_UPLOAD", "false")
    monkeypatch.setenv("BR_MOBILE_CAP_PUSH_REGISTRATION", "FALSE")
    monkeypatch.setenv("BR_MOBILE_CAP_PROFILE_WRITES", "no")  # typo-safe: stays on
    caps = get_mobile_capabilities()
    assert caps.ride_upload is False
    assert caps.push_registration is False
    assert caps.profile_writes is True


def test_rollback_is_the_next_read(monkeypatch) -> None:
    monkeypatch.setenv("BR_MOBILE_CAP_RIDE_UPLOAD", "false")
    assert get_mobile_capabilities().ride_upload is False
    monkeypatch.setenv("BR_MOBILE_CAP_RIDE_UPLOAD", "true")
    assert get_mobile_capabilities().ride_upload is True


def test_block_serializes_snake_case_for_the_client() -> None:
    payload = get_mobile_capabilities().model_dump()
    assert set(payload) == {
        "contract_version",
        "owner",
        "ride_upload",
        "push_registration",
        "profile_writes",
    }
