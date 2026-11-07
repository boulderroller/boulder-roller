from __future__ import annotations

import base64
import importlib.util
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "strava_file_import_cutover.py"
)
SPEC = importlib.util.spec_from_file_location("strava_file_import_cutover", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
cutover = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = cutover
SPEC.loader.exec_module(cutover)


class FakeStore:
    def __init__(
        self,
        *,
        connections: dict[str, str] | None = None,
        inactive_connections: set[str] | None = None,
        local_subscriptions: set[int] | None = None,
        imported_activity_links: int = 7,
        strava_origin_rides: int = 5,
    ) -> None:
        self.connections = dict(connections or {})
        self.inactive_connections = set(inactive_connections or set())
        self.local_subscriptions = set(local_subscriptions or set())
        self.imported_activity_links = imported_activity_links
        self.strava_origin_rides = strava_origin_rides
        self.events: list[tuple[str, object]] = []

    def list_stored_connection_ids(self) -> list[str]:
        self.events.append(("list_stored_connection_ids", None))
        return sorted(self.connections)

    def list_stored_connections(self) -> list[cutover.StoredGrant]:
        self.events.append(("list_stored_connections_with_tokens", None))
        return [
            cutover.StoredGrant(
                connection_id=connection_id,
                refresh_token=token,
                access_token=f"access-{token}",
            )
            for connection_id, token in sorted(self.connections.items())
        ]

    def list_active_connection_ids(self) -> list[str]:
        self.events.append(("list_active_connection_ids", None))
        return sorted(set(self.connections) - self.inactive_connections)

    def list_active_subscriptions(self) -> list[cutover.LocalSubscription]:
        self.events.append(("list_local_subscriptions", None))
        return [
            cutover.LocalSubscription(
                row_id=f"row-{subscription_id}",
                provider_subscription_id=subscription_id,
            )
            for subscription_id in sorted(self.local_subscriptions)
        ]

    def count_imported_activity_links(self) -> int:
        self.events.append(("count_imported_activity_links", None))
        return self.imported_activity_links

    def count_strava_origin_rides(self) -> int:
        self.events.append(("count_strava_origin_rides", None))
        return self.strava_origin_rides

    def mark_connection_revoked(self, connection_id: str) -> None:
        self.events.append(("mark_connection_revoked", connection_id))
        self.inactive_connections.add(connection_id)

    def mark_subscription_inactive(self, row_id: str) -> None:
        self.events.append(("mark_subscription_inactive", row_id))
        self.local_subscriptions.discard(int(row_id.removeprefix("row-")))


class FakeProvider:
    def __init__(
        self,
        *,
        subscriptions: set[int] | None = None,
        revoke_failures: set[str] | None = None,
        delete_failures: set[int] | None = None,
    ) -> None:
        self.application_id = "123"
        self.subscriptions = set(subscriptions or set())
        self.revoke_failures = set(revoke_failures or set())
        self.delete_failures = set(delete_failures or set())
        self.events: list[tuple[str, object]] = []

    def list_subscription_ids(self) -> list[int]:
        self.events.append(("list_provider_subscriptions", None))
        return sorted(self.subscriptions)

    def delete_subscription(self, subscription_id: int) -> None:
        self.events.append(("delete_subscription", subscription_id))
        if subscription_id in self.delete_failures:
            raise cutover.ProviderError("provider webhook delete failed")
        self.subscriptions.discard(subscription_id)

    def revoke_refresh_token(self, refresh_token: str) -> None:
        self.events.append(("revoke_refresh_token", refresh_token))
        if refresh_token in self.revoke_failures:
            raise cutover.ProviderError("provider token revoke failed")

    def revoke_access_token(self, access_token: str) -> None:
        self.events.append(("revoke_access_token", access_token))
        if access_token in self.revoke_failures:
            raise cutover.ProviderError("provider token revoke failed")


def _plan(store: FakeStore, provider: FakeProvider) -> cutover.CutoverPlan:
    return cutover.build_plan(
        store,
        provider,
        supabase_url="https://project-ref.supabase.co",
    )


def test_cli_defaults_to_dry_run_and_apply_requires_a_plan_hash() -> None:
    dry_run = cutover.parse_args([])
    assert dry_run.execute is False

    apply = cutover.parse_args(
        [
            "--execute",
            "--confirm",
            cutover.CONFIRMATION_PHRASE,
            "--expected-plan-sha256",
            "a" * 64,
            "--expected-supabase-url",
            "https://project-ref.supabase.co",
            "--expected-strava-application-id",
            "123",
            "--checkpoint-file",
            "/private/tmp/strava-cutover-checkpoint.json",
        ]
    )
    assert apply.execute is True
    assert apply.expected_plan_sha256 == "a" * 64
    assert apply.checkpoint_file.endswith("strava-cutover-checkpoint.json")


def test_dry_run_constructs_the_repo_compatible_client_for_modern_service_keys(
    monkeypatch,
    capsys,
) -> None:
    captured: dict[str, str] = {}

    def compatible_client(url: str, key: str):
        captured.update(url=url, key=key)
        return object()

    monkeypatch.setenv("SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_modern-test-key")
    monkeypatch.setenv("STRAVA_CLIENT_ID", "123")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        cutover,
        "create_backend_supabase_client",
        compatible_client,
        raising=False,
    )
    monkeypatch.setattr(
        cutover,
        "create_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("raw supabase client rejects modern service keys")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        cutover,
        "SupabaseCutoverStore",
        lambda _db, page_size: FakeStore(),
    )
    monkeypatch.setattr(
        cutover,
        "StravaProviderClient",
        lambda *_args, **_kwargs: FakeProvider(),
    )

    assert cutover.main(["--dry-run"]) == 0
    assert captured == {
        "url": "https://project-ref.supabase.co",
        "key": "sb_secret_modern-test-key",
    }
    captured_output = capsys.readouterr()
    assert "sb_secret_modern-test-key" not in captured_output.out
    assert "client-secret" not in captured_output.out
    assert "client-secret" not in captured_output.err


def test_local_only_dry_run_and_execute_use_the_exact_plan_without_strava_contact(
    monkeypatch,
    capsys,
) -> None:
    store = FakeStore(
        connections={"connection-a": "refresh-a"},
        local_subscriptions={333340},
        imported_activity_links=11,
        strava_origin_rides=9,
    )

    monkeypatch.setenv("SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_modern-test-key")
    monkeypatch.setenv("STRAVA_CLIENT_ID", "123")
    monkeypatch.delenv("STRAVA_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("STRAVA_SYNC_ENABLED", "false")
    monkeypatch.setattr(
        cutover,
        "create_backend_supabase_client",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        cutover,
        "SupabaseCutoverStore",
        lambda _db, page_size: store,
    )
    monkeypatch.setattr(
        cutover,
        "StravaProviderClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local-only mode must not construct a Strava client")
        ),
    )
    monkeypatch.setattr(
        cutover.httpx,
        "Client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("local-only mode must not construct an HTTP client")
        ),
    )

    assert cutover.main(["--dry-run", "--local-only"]) == 0
    dry_run = json.loads(capsys.readouterr().out)
    assert dry_run["plan"]["cutover_mode"] == "local_only"
    assert dry_run["plan"]["strava_api_contact_planned"] is False
    assert dry_run["plan"]["provider_subscription_ids"] is None
    assert dry_run["plan"]["database_rows_deleted"] == 0
    assert dry_run["plan"]["strava_data_purge_planned"] is False
    assert store.inactive_connections == set()
    assert store.local_subscriptions == {333340}

    execution_args = [
        "--execute",
        "--local-only",
        "--confirm",
        cutover.LOCAL_ONLY_CONFIRMATION_PHRASE,
        "--expected-supabase-url",
        "https://project-ref.supabase.co",
        "--expected-strava-application-id",
        "123",
    ]
    with pytest.raises(cutover.ConfirmationError, match="plan-sha256"):
        cutover.main(
            execution_args
            + ["--expected-plan-sha256", "0" * 64]
        )
    assert store.inactive_connections == set()
    assert store.local_subscriptions == {333340}

    assert cutover.main(
        execution_args
        + ["--expected-plan-sha256", dry_run["plan"]["plan_sha256"]]
    ) == 0
    executed = json.loads(capsys.readouterr().out)
    assert executed["result"]["success"] is True
    assert executed["result"]["strava_api_contacted"] is False
    assert executed["result"]["connections_revoke_acknowledged"] is None
    assert executed["result"]["remaining_provider_subscription_count"] is None
    assert executed["result"]["database_rows_deleted"] == 0
    assert store.inactive_connections == {"connection-a"}
    assert store.local_subscriptions == set()
    assert ("list_stored_connections_with_tokens", None) not in store.events


def test_execute_requires_a_checkpoint_before_any_provider_mutation(
    monkeypatch,
) -> None:
    store = FakeStore()
    provider = FakeProvider()
    plan = _plan(store, provider)
    store.events.clear()
    provider.events.clear()

    monkeypatch.setenv("SUPABASE_URL", plan.supabase_url)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "sb_secret_modern-test-key")
    monkeypatch.setenv("STRAVA_CLIENT_ID", provider.application_id)
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("STRAVA_SYNC_ENABLED", "false")
    monkeypatch.setattr(
        cutover,
        "create_backend_supabase_client",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        cutover,
        "SupabaseCutoverStore",
        lambda _db, page_size: store,
    )
    monkeypatch.setattr(
        cutover,
        "StravaProviderClient",
        lambda *_args, **_kwargs: provider,
    )

    with pytest.raises(cutover.ConfirmationError, match="checkpoint-file"):
        cutover.main(
            [
                "--execute",
                "--confirm",
                cutover.CONFIRMATION_PHRASE,
                "--expected-plan-sha256",
                plan.sha256,
                "--expected-supabase-url",
                plan.supabase_url,
                "--expected-strava-application-id",
                provider.application_id,
            ]
        )

    assert not any(
        event[0] in {"delete_subscription", "revoke_refresh_token", "revoke_access_token"}
        for event in provider.events
    )


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://project-ref.supabase.co",
        "https://operator:password@project-ref.supabase.co",
        "https://project-ref.supabase.co/rest/v1",
        "https://project-ref.supabase.co?secret=value",
        "https://project-ref.supabase.co#fragment",
    ],
)
def test_cutover_rejects_noncanonical_or_secret_bearing_targets(
    unsafe_url: str,
) -> None:
    with pytest.raises(cutover.ConfirmationError):
        cutover._normalized_url(unsafe_url)


def test_anon_supabase_jwt_is_rejected_before_client_or_provider_construction(
    monkeypatch,
) -> None:
    def jwt_part(payload: dict) -> str:
        return base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")

    anon_key = ".".join(
        (
            jwt_part({"alg": "HS256", "typ": "JWT"}),
            jwt_part({"role": "anon"}),
            "signature",
        )
    )
    monkeypatch.setenv("SUPABASE_URL", "https://project-ref.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", anon_key)
    monkeypatch.setenv("STRAVA_CLIENT_ID", "123")
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        cutover,
        "create_backend_supabase_client",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("client must not be constructed for an anon key")
        ),
    )

    with pytest.raises(cutover.ConfirmationError, match="service-role"):
        cutover.main(["--dry-run"])


def test_plan_contains_counts_and_digest_without_loading_tokens() -> None:
    store = FakeStore(
        connections={"connection-b": "secret-b", "connection-a": "secret-a"},
        local_subscriptions={333340},
    )
    provider = FakeProvider(subscriptions={333340, 444440})

    plan = _plan(store, provider)

    assert plan.stored_connection_count == 2
    assert plan.local_subscription_ids == (333340,)
    assert plan.provider_subscription_ids == (333340, 444440)
    assert len(plan.sha256) == 64
    assert plan.to_public_dict()["revoke_request_count_without_checkpoint"] == 4
    assert plan.to_public_dict()["execute_requires_checkpoint"] is True
    assert ("list_stored_connections_with_tokens", None) not in store.events
    assert "secret-a" not in plan.to_public_dict().__repr__()


def test_dry_run_plan_performs_no_provider_or_database_mutation() -> None:
    store = FakeStore(
        connections={"connection-a": "refresh-a"},
        local_subscriptions={333340},
    )
    provider = FakeProvider(subscriptions={333340})

    _plan(store, provider)

    assert not any(event[0].startswith("mark_") for event in store.events)
    assert not any(
        event[0] in {"delete_subscription", "revoke_refresh_token"}
        for event in provider.events
    )


def test_apply_disables_webhook_before_revoking_each_grant_and_preserves_imports() -> None:
    store = FakeStore(
        connections={"connection-a": "refresh-a", "connection-b": "refresh-b"},
        local_subscriptions={333340},
        imported_activity_links=11,
    )
    provider = FakeProvider(subscriptions={333340})
    plan = _plan(store, provider)

    result = cutover.execute_cutover(store, provider, plan)

    assert result.success is True
    assert result.connections_revoked == 2
    assert result.provider_subscriptions_deleted == 1
    assert result.local_subscriptions_disabled == 1
    assert result.imported_activity_links_before == 11
    assert result.imported_activity_links_after == 11
    assert result.strava_origin_rides_before == 5
    assert result.strava_origin_rides_after == 5
    assert store.inactive_connections == {"connection-a", "connection-b"}
    assert store.local_subscriptions == set()
    assert provider.subscriptions == set()
    delete_index = provider.events.index(("delete_subscription", 333340))
    first_revoke_index = provider.events.index(("revoke_refresh_token", "refresh-a"))
    assert delete_index < first_revoke_index


def test_apply_stops_before_grant_revocation_when_webhook_disable_fails() -> None:
    store = FakeStore(
        connections={"connection-a": "refresh-a"},
        local_subscriptions={333340},
    )
    provider = FakeProvider(subscriptions={333340}, delete_failures={333340})
    plan = _plan(store, provider)

    with pytest.raises(cutover.ProviderError, match="webhook delete"):
        cutover.execute_cutover(store, provider, plan)

    assert store.inactive_connections == set()
    assert store.local_subscriptions == {333340}
    assert not any(event[0] == "revoke_refresh_token" for event in provider.events)


def test_partial_grant_failure_is_resumable_and_only_marks_confirmed_revocations() -> None:
    store = FakeStore(
        connections={"connection-a": "refresh-a", "connection-b": "refresh-b"},
        local_subscriptions={333340},
    )
    provider = FakeProvider(
        subscriptions={333340},
        revoke_failures={"refresh-b"},
    )
    plan = _plan(store, provider)

    with pytest.raises(cutover.CutoverIncompleteError) as excinfo:
        cutover.execute_cutover(store, provider, plan)

    assert excinfo.value.result.connections_revoked == 1
    assert excinfo.value.result.failed_connection_count == 1
    assert store.inactive_connections == {"connection-a"}
    assert provider.subscriptions == set()

    provider.revoke_failures.clear()
    rerun_plan = _plan(store, provider)
    rerun = cutover.execute_cutover(store, provider, rerun_plan)

    assert rerun.success is True
    assert rerun.connections_revoked == 2
    assert store.inactive_connections == {"connection-a", "connection-b"}


def test_rate_limit_halts_and_checkpointed_rerun_skips_confirmed_prefix() -> None:
    class RateLimitedProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.rate_limited_tokens = {"refresh-b"}

        def revoke_refresh_token(self, refresh_token: str) -> None:
            self.events.append(("revoke_refresh_token", refresh_token))
            if refresh_token in self.rate_limited_tokens:
                raise cutover.ProviderHaltError("Strava rate limit reached")

    store = FakeStore(
        connections={
            "connection-a": "refresh-a",
            "connection-b": "refresh-b",
            "connection-c": "refresh-c",
        }
    )
    provider = RateLimitedProvider()
    progress = cutover.InMemoryCutoverProgress()

    with pytest.raises(cutover.CutoverIncompleteError) as excinfo:
        cutover.execute_cutover(
            store,
            provider,
            _plan(store, provider),
            progress=progress,
        )

    assert excinfo.value.result.connections_revoked == 1
    assert excinfo.value.result.failed_connection_count == 2
    assert ("revoke_refresh_token", "refresh-c") not in provider.events

    provider.rate_limited_tokens.clear()
    provider.events.clear()
    rerun = cutover.execute_cutover(
        store,
        provider,
        _plan(store, provider),
        progress=progress,
    )

    assert rerun.success is True
    assert rerun.connections_revoked == 3
    assert ("revoke_refresh_token", "refresh-a") not in provider.events
    assert ("revoke_access_token", "access-refresh-a") not in provider.events
    assert ("revoke_refresh_token", "refresh-b") in provider.events
    assert ("revoke_refresh_token", "refresh-c") in provider.events


def test_empty_cutover_is_an_idempotent_success() -> None:
    store = FakeStore()
    provider = FakeProvider()
    plan = _plan(store, provider)

    first = cutover.execute_cutover(store, provider, plan)
    second = cutover.execute_cutover(store, provider, _plan(store, provider))

    assert first.success is True
    assert second.success is True
    assert first.connections_revoked == 0
    assert second.provider_subscriptions_deleted == 0


def test_file_checkpoint_is_target_bound_resumable_and_contains_no_tokens(
    tmp_path,
) -> None:
    store = FakeStore(connections={"connection-a": "refresh-a"})
    provider = FakeProvider()
    plan = _plan(store, provider)
    grant = store.list_stored_connections()[0]
    path = tmp_path / "strava-cutover-checkpoint.json"

    progress = cutover.FileCutoverProgress(str(path), plan)
    progress.validate_grants([grant])
    progress.record_provider_acknowledged(grant)
    progress.record_local_marked_inactive(grant)

    checkpoint_text = path.read_text()
    assert "refresh-a" not in checkpoint_text
    assert "access-refresh-a" not in checkpoint_text
    assert path.stat().st_mode & 0o077 == 0

    reloaded = cutover.FileCutoverProgress(str(path), plan)
    reloaded.validate_grants([grant])
    assert reloaded.provider_acknowledged(grant) is True
    assert reloaded.local_marked_inactive(grant) is True


def test_already_inactive_rows_are_still_revoked_at_provider() -> None:
    store = FakeStore(
        connections={"connection-a": "refresh-a"},
        inactive_connections={"connection-a"},
    )
    provider = FakeProvider()

    result = cutover.execute_cutover(store, provider, _plan(store, provider))

    assert result.connections_revoked == 1
    assert ("revoke_refresh_token", "refresh-a") in provider.events


def test_stale_refresh_and_live_access_tokens_are_both_revoked_before_local_disable() -> None:
    class DualTokenStore(FakeStore):
        def list_stored_connections(self) -> list[cutover.StoredGrant]:
            return [
                cutover.StoredGrant(
                    connection_id="connection-a",
                    refresh_token="stale-refresh",
                    access_token="live-access",
                )
            ]

    store = DualTokenStore(connections={"connection-a": "stale-refresh"})
    provider = FakeProvider()

    result = cutover.execute_cutover(store, provider, _plan(store, provider))

    assert result.connections_revoked == 1
    assert result.connections_marked_inactive == 1
    assert ("revoke_refresh_token", "stale-refresh") in provider.events
    assert ("revoke_access_token", "live-access") in provider.events
    assert store.inactive_connections == {"connection-a"}


def test_provider_acknowledgement_is_reported_when_local_disable_fails() -> None:
    class LocalWriteFailureStore(FakeStore):
        fail_local_write = True

        def list_stored_connections(self) -> list[cutover.StoredGrant]:
            return [
                cutover.StoredGrant(
                    connection_id="connection-a",
                    refresh_token="refresh-a",
                    access_token="access-a",
                )
            ]

        def mark_connection_revoked(self, connection_id: str) -> None:
            if self.fail_local_write:
                raise cutover.DatabaseError("local update failed")
            super().mark_connection_revoked(connection_id)

    store = LocalWriteFailureStore(connections={"connection-a": "refresh-a"})
    provider = FakeProvider()
    progress = cutover.InMemoryCutoverProgress()

    with pytest.raises(cutover.CutoverIncompleteError) as excinfo:
        cutover.execute_cutover(
            store,
            provider,
            _plan(store, provider),
            progress=progress,
        )

    assert excinfo.value.result.connections_revoked == 1
    assert excinfo.value.result.connections_marked_inactive == 0
    assert excinfo.value.result.failed_connection_count == 1
    assert store.inactive_connections == set()

    store.fail_local_write = False
    provider.events.clear()
    rerun = cutover.execute_cutover(
        store,
        provider,
        _plan(store, provider),
        progress=progress,
    )

    assert rerun.success is True
    assert not any(event[0].startswith("revoke_") for event in provider.events)
    assert store.inactive_connections == {"connection-a"}


def test_plan_drift_aborts_before_any_mutation() -> None:
    store = FakeStore(connections={"connection-a": "refresh-a"})
    provider = FakeProvider()
    plan = _plan(store, provider)
    store.connections["connection-b"] = "refresh-b"

    with pytest.raises(cutover.PlanDriftError):
        cutover.execute_cutover(store, provider, plan)

    assert store.connections == {
        "connection-a": "refresh-a",
        "connection-b": "refresh-b",
    }
    assert not any(event[0].startswith("mark_") for event in store.events)
    assert not any(event[0] == "revoke_refresh_token" for event in provider.events)


def test_checkpoint_token_drift_aborts_before_webhook_or_grant_mutation() -> None:
    store = FakeStore(
        connections={"connection-a": "refresh-a"},
        local_subscriptions={333340},
    )
    provider = FakeProvider(subscriptions={333340})
    plan = _plan(store, provider)
    progress = cutover.InMemoryCutoverProgress()
    progress.record_provider_acknowledged(store.list_stored_connections()[0])
    store.connections["connection-a"] = "rotated-refresh-a"
    provider.events.clear()

    with pytest.raises(cutover.PlanDriftError, match="tokens changed"):
        cutover.execute_cutover(
            store,
            provider,
            plan,
            progress=progress,
        )

    assert ("delete_subscription", 333340) not in provider.events
    assert not any(event[0].startswith("revoke_") for event in provider.events)
    assert store.local_subscriptions == {333340}


def test_apply_confirmation_rejects_wrong_phrase_or_digest() -> None:
    store = FakeStore(connections={"connection-a": "refresh-a"})
    provider = FakeProvider()
    plan = _plan(store, provider)

    with pytest.raises(cutover.ConfirmationError):
        cutover.validate_apply_request(
            plan,
            confirmation="wrong",
            expected_plan_sha256=plan.sha256,
        )
    with pytest.raises(cutover.ConfirmationError):
        cutover.validate_apply_request(
            plan,
            confirmation=cutover.CONFIRMATION_PHRASE,
            expected_plan_sha256="0" * 64,
        )
    with pytest.raises(cutover.ConfirmationError):
        cutover.validate_apply_request(
            plan,
            confirmation=cutover.CONFIRMATION_PHRASE,
            expected_plan_sha256=plan.sha256,
            expected_supabase_url="https://other-project.supabase.co",
        )

    assert store.connections == {"connection-a": "refresh-a"}


def test_provider_revoke_retries_only_retryable_503_without_exposing_token(monkeypatch) -> None:
    statuses = iter([503, 503, 200])
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(next(statuses), request=request)

    monkeypatch.setattr(cutover.time, "sleep", lambda _seconds: None)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = cutover.StravaProviderClient(
            client,
            application_id="123",
            client_secret="client-secret",
            max_revoke_attempts=3,
        )
        provider.revoke_refresh_token("refresh-secret")

    assert len(requests) == 3
    assert all(request.url.path == "/oauth/revoke" for request in requests)
    assert all(request.headers["Authorization"].startswith("Basic ") for request in requests)
    assert all(b"token_type_hint=refresh_token" in request.content for request in requests)


def test_provider_revoke_attempts_cannot_exceed_the_reviewed_retry_budget() -> None:
    with httpx.Client() as client:
        with pytest.raises(cutover.ConfirmationError):
            cutover.StravaProviderClient(
                client,
                application_id="123",
                client_secret="client-secret",
                max_revoke_attempts=4,
            )


def test_provider_revoke_access_token_uses_the_access_token_hint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = cutover.StravaProviderClient(
            client,
            application_id="123",
            client_secret="client-secret",
        )
        provider.revoke_access_token("access-secret")

    assert len(requests) == 1
    assert b"token_type_hint=access_token" in requests[0].content


def test_provider_webhook_inventory_and_delete_match_strava_request_contract() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": 333340}], request=request)
        return httpx.Response(204, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = cutover.StravaProviderClient(
            client,
            application_id="123",
            client_secret="client-secret",
        )
        assert provider.list_subscription_ids() == [333340]
        provider.delete_subscription(333340)

    assert [request.method for request in requests] == ["GET", "DELETE"]
    assert requests[0].url.path == "/api/v3/push_subscriptions"
    assert requests[1].url.path == "/api/v3/push_subscriptions/333340"
    assert all(request.url.params["client_id"] == "123" for request in requests)
    assert all(
        request.url.params["client_secret"] == "client-secret"
        for request in requests
    )


def test_provider_http_logs_redact_client_secret_from_request_urls(caplog) -> None:
    client_secret = "client secret+/=?&"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[], request=request)

    caplog.set_level(logging.INFO)
    # The hosted suite can leave these library loggers at WARNING even when
    # the root capture level is INFO. Exercise the production filters against
    # the records that each library actually emits.
    caplog.set_level(logging.INFO, logger="httpx")
    caplog.set_level(logging.INFO, logger="httpcore.connection")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = cutover.StravaProviderClient(
            client,
            application_id="123",
            client_secret=client_secret,
        )
        assert provider.list_subscription_ids() == []
        logging.getLogger("httpcore.connection").info(
            "trace url=%s",
            httpx.URL(
                "https://www.strava.com/api/v3/push_subscriptions",
                params={"client_secret": client_secret},
            ),
        )

    logged_output = "\n".join(record.getMessage() for record in caplog.records)
    assert logged_output.count("client_secret=[REDACTED]") == 2
    assert client_secret not in logged_output
    assert quote(client_secret, safe="") not in logged_output


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (400, cutover.ProviderError),
        (401, cutover.ProviderHaltError),
        (429, cutover.ProviderHaltError),
    ],
)
def test_provider_revoke_fails_closed_on_nonretryable_status(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = cutover.StravaProviderClient(
            client,
            application_id="123",
            client_secret="client-secret",
        )
        with pytest.raises(expected_error) as excinfo:
            provider.revoke_refresh_token("refresh-secret")

    assert calls == 1
    assert "refresh-secret" not in str(excinfo.value)
    assert "client-secret" not in str(excinfo.value)


class _FakeQuery:
    def __init__(self, client: "_FakeSupabase", table: str) -> None:
        self.client = client
        self.table = table
        self.filters: list[tuple[str, object]] = []
        self.range_value: tuple[int, int] | None = None
        self.count_requested = False
        self.update_payload: dict | None = None

    def select(self, _columns: str, count: str | None = None) -> "_FakeQuery":
        self.count_requested = count == "exact"
        return self

    def update(self, payload: dict) -> "_FakeQuery":
        self.update_payload = payload
        return self

    def eq(self, column: str, value: object) -> "_FakeQuery":
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values: list[str]) -> "_FakeQuery":
        self.filters.append((column, set(values)))
        return self

    def order(self, _column: str) -> "_FakeQuery":
        return self

    def range(self, start: int, end: int) -> "_FakeQuery":
        self.range_value = (start, end)
        self.client.ranges.append((self.table, start, end))
        return self

    def limit(self, _value: int) -> "_FakeQuery":
        return self

    def execute(self) -> SimpleNamespace:
        rows = list(self.client.rows[self.table])
        for column, value in self.filters:
            if isinstance(value, set):
                rows = [row for row in rows if row.get(column) in value]
            else:
                rows = [row for row in rows if row.get(column) == value]
        if self.update_payload is not None:
            target_ids = {row["id"] for row in rows}
            for row in self.client.rows[self.table]:
                if row["id"] in target_ids:
                    row.update(self.update_payload)
            return SimpleNamespace(data=rows, count=None)
        exact_count = len(rows) if self.count_requested else None
        if self.range_value is not None:
            start, end = self.range_value
            rows = rows[start : end + 1]
            if self.client.server_page_cap is not None:
                rows = rows[: self.client.server_page_cap]
        return SimpleNamespace(data=rows, count=exact_count)


class _FakeSupabase:
    def __init__(
        self,
        rows: dict[str, list[dict]],
        *,
        server_page_cap: int | None = None,
    ) -> None:
        self.rows = rows
        self.server_page_cap = server_page_cap
        self.ranges: list[tuple[str, int, int]] = []

    def table(self, table: str) -> _FakeQuery:
        return _FakeQuery(self, table)


def test_supabase_store_paginates_every_grant_and_updates_only_exact_row() -> None:
    rows = {
        "strava_connections": [
            {
                "id": f"connection-{index:04d}",
                "refresh_token": f"token-{index:04d}",
                "is_active": True,
            }
            for index in range(1001)
        ],
        "strava_webhook_subscriptions": [],
        "strava_imported_activities": [{"id": "import-1"}],
        "rides": [
            {"id": "ride-1", "import_source": "strava"},
            {"id": "ride-2", "import_source": "manual_file_upload"},
        ],
    }
    db = _FakeSupabase(rows)
    store = cutover.SupabaseCutoverStore(db, page_size=500)

    assert len(store.list_stored_connection_ids()) == 1001
    assert db.ranges == [
        ("strava_connections", 0, 499),
        ("strava_connections", 500, 999),
        ("strava_connections", 1000, 1499),
        ("strava_connections", 1001, 1500),
    ]
    store.mark_connection_revoked("connection-1000")

    assert rows["strava_connections"][1000]["is_active"] is False
    assert all(
        row["is_active"] is True
        for row in rows["strava_connections"][:1000]
    )
    assert store.count_imported_activity_links() == 1
    assert store.count_strava_origin_rides() == 1


def test_supabase_store_does_not_treat_a_server_capped_page_as_end_of_data() -> None:
    rows = {
        "strava_connections": [
            {"id": f"connection-{index}", "is_active": False}
            for index in range(5)
        ],
    }
    db = _FakeSupabase(rows, server_page_cap=2)
    store = cutover.SupabaseCutoverStore(db, page_size=500)

    assert store.list_stored_connection_ids() == [
        "connection-0",
        "connection-1",
        "connection-2",
        "connection-3",
        "connection-4",
    ]
    assert db.ranges == [
        ("strava_connections", 0, 499),
        ("strava_connections", 2, 501),
        ("strava_connections", 4, 503),
        ("strava_connections", 5, 504),
    ]


def test_supabase_store_loads_both_stored_tokens_and_rejects_missing_tokens() -> None:
    rows = {
        "strava_connections": [
            {
                "id": "connection-a",
                "refresh_token": "refresh-a",
                "access_token": "access-a",
            }
        ],
    }
    store = cutover.SupabaseCutoverStore(_FakeSupabase(rows))

    assert store.list_stored_connections() == [
        cutover.StoredGrant(
            connection_id="connection-a",
            refresh_token="refresh-a",
            access_token="access-a",
        )
    ]

    rows["strava_connections"][0]["access_token"] = ""
    with pytest.raises(cutover.DatabaseError, match="missing required fields"):
        store.list_stored_connections()


def test_local_only_cutover_updates_exact_supabase_rows_without_purging_data() -> None:
    rows = {
        "strava_connections": [
            {
                "id": "connection-active",
                "refresh_token": "refresh-active",
                "access_token": "access-active",
                "is_active": True,
            },
            {
                "id": "connection-inactive",
                "refresh_token": "refresh-inactive",
                "access_token": "access-inactive",
                "is_active": False,
            },
        ],
        "strava_webhook_subscriptions": [
            {"id": "webhook-active", "subscription_id": 333340, "is_active": True},
            {"id": "webhook-inactive", "subscription_id": 444440, "is_active": False},
        ],
        "strava_imported_activities": [{"id": "import-1"}],
        "rides": [
            {"id": "ride-1", "import_source": "strava"},
            {"id": "ride-2", "import_source": "manual_file_upload"},
        ],
    }
    store = cutover.SupabaseCutoverStore(_FakeSupabase(rows))
    plan = cutover.build_plan(
        store,
        None,
        supabase_url="https://project-ref.supabase.co",
        local_only=True,
        strava_application_id="123",
    )

    result = cutover.execute_local_only_cutover(store, plan)

    assert result.success is True
    assert result.connections_marked_inactive == 1
    assert result.local_subscriptions_disabled == 1
    assert result.strava_api_contacted is False
    assert [row["is_active"] for row in rows["strava_connections"]] == [False, False]
    assert [row["is_active"] for row in rows["strava_webhook_subscriptions"]] == [
        False,
        False,
    ]
    assert rows["strava_connections"][0]["refresh_token"] == "refresh-active"
    assert rows["strava_connections"][0]["access_token"] == "access-active"
    assert len(rows["strava_connections"]) == 2
    assert rows["strava_imported_activities"] == [{"id": "import-1"}]
    assert len(rows["rides"]) == 2
