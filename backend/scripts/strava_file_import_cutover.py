#!/usr/bin/env python3
"""Retire Strava connections and webhooks for file-import-only mode.

Dry-run is the default. Execution is guarded by the exact dry-run plan digest,
target Supabase URL, Strava application ID, and a fixed confirmation phrase.
Provider-revoke mode deauthorizes grants and removes the provider webhook.
``--local-only`` makes no Strava API request and only disables local rows when
the provider application is already dead. The script never deletes connection,
import-link, ride, or file data.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.supabase_client import (  # noqa: E402
    BackendSupabaseClient,
    MODERN_SECRET_PREFIX,
    create_backend_supabase_client,
)


SCHEMA = "boulderroller.strava-file-import-cutover.v2"
CHECKPOINT_SCHEMA = "boulderroller.strava-file-import-cutover-checkpoint.v1"
CONFIRMATION_PHRASE = "FILE_IMPORT_ONLY_REVOKE_STRAVA_GRANTS"
LOCAL_ONLY_CONFIRMATION_PHRASE = "FILE_IMPORT_ONLY_DISABLE_LOCAL_STRAVA_ROWS"
PROVIDER_REVOKE_MODE = "provider_revoke"
LOCAL_ONLY_MODE = "local_only"
STRAVA_REVOKE_URL = "https://www.strava.com/oauth/revoke"
STRAVA_SUBSCRIPTIONS_URL = "https://www.strava.com/api/v3/push_subscriptions"
STRAVA_IMPORT_SOURCES = ("strava", "strava_stream_reconstructed_gpx")
DEFAULT_PAGE_SIZE = 500
MAX_REVOKE_ATTEMPTS = 3

_CLIENT_SECRET_QUERY_PATTERN = re.compile(
    r"(?i)(client_secret=)[^&\s\"']*"
)
_HTTP_LOGGER_NAMES = (
    "httpx",
    "httpcore",
    "httpcore.connection",
    "httpcore.connection_pool",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
)


def _redact_client_secret(value: str, client_secret: str | None = None) -> str:
    redacted = value
    if client_secret:
        redacted = redacted.replace(client_secret, "[REDACTED]")
    return _CLIENT_SECRET_QUERY_PATTERN.sub(r"\1[REDACTED]", redacted)


class _ClientSecretRedactionFilter(logging.Filter):
    def __init__(self, client_secret: str) -> None:
        super().__init__()
        self.client_secret = client_secret

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_client_secret(record.getMessage(), self.client_secret)
        record.args = ()
        return True


def _install_client_secret_log_redaction(client_secret: str) -> None:
    redaction_filter = _ClientSecretRedactionFilter(client_secret)
    for logger_name in _HTTP_LOGGER_NAMES:
        logging.getLogger(logger_name).addFilter(redaction_filter)


class CutoverError(RuntimeError):
    """Base class for safe, redacted cutover failures."""


class ProviderError(CutoverError):
    """Strava did not confirm a requested provider operation."""


class ProviderHaltError(ProviderError):
    """A provider-wide condition requires stopping before the next grant."""


class DatabaseError(CutoverError):
    """The local cutover state could not be read or verified."""


class ConfirmationError(CutoverError):
    """The operator did not confirm the reviewed target and plan."""


class PlanDriftError(CutoverError):
    """The live mutation target differs from the reviewed dry-run plan."""


class CheckpointError(CutoverError):
    """Durable cutover progress could not be loaded or preserved."""


@dataclass(frozen=True)
class StoredGrant:
    connection_id: str
    refresh_token: str
    access_token: str


@dataclass(frozen=True)
class LocalSubscription:
    row_id: str
    provider_subscription_id: int | None


@dataclass(frozen=True)
class CutoverPlan:
    supabase_url: str
    strava_application_id: str
    cutover_mode: str
    stored_connection_ids: tuple[str, ...]
    active_connection_ids: tuple[str, ...]
    local_subscriptions: tuple[LocalSubscription, ...]
    provider_subscription_ids: tuple[int, ...] | None
    imported_activity_link_count: int
    strava_origin_ride_count: int
    sha256: str

    @property
    def stored_connection_count(self) -> int:
        return len(self.stored_connection_ids)

    @property
    def active_connection_count(self) -> int:
        return len(self.active_connection_ids)

    @property
    def inactive_connection_count(self) -> int:
        return self.stored_connection_count - self.active_connection_count

    @property
    def local_subscription_ids(self) -> tuple[int, ...]:
        return tuple(
            sorted(
                subscription.provider_subscription_id
                for subscription in self.local_subscriptions
                if subscription.provider_subscription_id is not None
            )
        )

    def to_public_dict(self) -> dict[str, Any]:
        provider_contact_planned = self.cutover_mode == PROVIDER_REVOKE_MODE
        return {
            "schema": SCHEMA,
            "cutover_mode": self.cutover_mode,
            "target_supabase_host": _public_target_host(self.supabase_url),
            "strava_application_id": self.strava_application_id,
            "strava_api_contact_planned": provider_contact_planned,
            "stored_connection_count": self.stored_connection_count,
            "active_connection_count": self.active_connection_count,
            "inactive_connection_count": self.inactive_connection_count,
            "local_active_subscription_count": len(self.local_subscriptions),
            "local_provider_subscription_ids": list(self.local_subscription_ids),
            "provider_subscription_ids": (
                list(self.provider_subscription_ids)
                if self.provider_subscription_ids is not None
                else None
            ),
            "provider_subscription_inventory": (
                "queried" if provider_contact_planned else "skipped_local_only"
            ),
            "imported_activity_link_count": self.imported_activity_link_count,
            "strava_origin_ride_count": self.strava_origin_ride_count,
            "plan_sha256": self.sha256,
            "revoke_request_count_without_checkpoint": (
                self.stored_connection_count * 2 if provider_contact_planned else 0
            ),
            "execute_requires_checkpoint": provider_contact_planned,
            "database_rows_deleted": 0,
            "strava_data_purge_planned": False,
        }


def _grant_fingerprint(grant: StoredGrant) -> str:
    digest = hashlib.sha256()
    for value in (
        grant.connection_id,
        grant.refresh_token,
        grant.access_token,
    ):
        encoded = value.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


class CutoverProgress(Protocol):
    def validate_grants(self, grants: list[StoredGrant]) -> None: ...

    def provider_acknowledged(self, grant: StoredGrant) -> bool: ...

    def local_marked_inactive(self, grant: StoredGrant) -> bool: ...

    def record_provider_acknowledged(self, grant: StoredGrant) -> None: ...

    def record_local_marked_inactive(self, grant: StoredGrant) -> None: ...


class InMemoryCutoverProgress:
    """Non-durable progress used by focused unit tests."""

    def __init__(self) -> None:
        self._receipts: dict[str, dict[str, Any]] = {}

    def _receipt(self, grant: StoredGrant) -> dict[str, Any] | None:
        receipt = self._receipts.get(grant.connection_id)
        if receipt is None:
            return None
        if receipt.get("token_fingerprint") != _grant_fingerprint(grant):
            raise PlanDriftError(
                "stored Strava tokens changed after a revocation checkpoint"
            )
        return receipt

    def validate_grants(self, grants: list[StoredGrant]) -> None:
        by_id = {grant.connection_id: grant for grant in grants}
        if len(by_id) != len(grants):
            raise DatabaseError("stored Strava grant inventory contains duplicate ids")
        if not set(self._receipts).issubset(by_id):
            raise PlanDriftError(
                "a checkpointed Strava connection row is missing from storage"
            )
        for connection_id in self._receipts:
            receipt = self._receipt(by_id[connection_id])
            if receipt is None:
                raise CheckpointError("Strava checkpoint receipt disappeared")
            if receipt.get("local_marked_inactive") and not receipt.get(
                "provider_acknowledged"
            ):
                raise CheckpointError("Strava checkpoint receipt order is invalid")

    def provider_acknowledged(self, grant: StoredGrant) -> bool:
        receipt = self._receipt(grant)
        return bool(receipt and receipt.get("provider_acknowledged"))

    def local_marked_inactive(self, grant: StoredGrant) -> bool:
        receipt = self._receipt(grant)
        return bool(receipt and receipt.get("local_marked_inactive"))

    def record_provider_acknowledged(self, grant: StoredGrant) -> None:
        self._receipts[grant.connection_id] = {
            "token_fingerprint": _grant_fingerprint(grant),
            "provider_acknowledged": True,
            "local_marked_inactive": False,
        }

    def record_local_marked_inactive(self, grant: StoredGrant) -> None:
        receipt = self._receipt(grant)
        if not receipt or not receipt.get("provider_acknowledged"):
            raise CheckpointError(
                "cannot checkpoint a local mark before provider acknowledgement"
            )
        receipt["local_marked_inactive"] = True


class FileCutoverProgress(InMemoryCutoverProgress):
    """Private, target-bound, token-free progress for resumable execution."""

    def __init__(self, checkpoint_path: str, plan: CutoverPlan) -> None:
        super().__init__()
        self.path = Path(checkpoint_path).expanduser()
        if not self.path.is_absolute():
            raise ConfirmationError("--checkpoint-file must be an absolute path")
        self.supabase_url = plan.supabase_url
        self.strava_application_id = plan.strava_application_id
        self._load_or_create()

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": CHECKPOINT_SCHEMA,
            "target_supabase_url": self.supabase_url,
            "strava_application_id": self.strava_application_id,
            "receipts": self._receipts,
        }

    def _load_or_create(self) -> None:
        if self.path.is_symlink():
            raise CheckpointError("checkpoint path must not be a symbolic link")
        if not self.path.exists():
            self._persist()
            return
        if not self.path.is_file():
            raise CheckpointError("checkpoint path must be a regular file")
        try:
            if self.path.stat().st_mode & 0o077:
                raise CheckpointError(
                    "checkpoint file must not be accessible by group or others"
                )
        except OSError as exc:
            raise CheckpointError("failed to inspect the Strava checkpoint") from exc
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise CheckpointError("failed to read the Strava checkpoint") from exc
        if not isinstance(payload, dict) or payload.get("schema") != CHECKPOINT_SCHEMA:
            raise CheckpointError("Strava checkpoint schema is invalid")
        if payload.get("target_supabase_url") != self.supabase_url:
            raise CheckpointError("Strava checkpoint Supabase target does not match")
        if payload.get("strava_application_id") != self.strava_application_id:
            raise CheckpointError("Strava checkpoint application does not match")
        receipts = payload.get("receipts")
        if not isinstance(receipts, dict):
            raise CheckpointError("Strava checkpoint receipts are invalid")
        for connection_id, receipt in receipts.items():
            if not isinstance(connection_id, str) or not isinstance(receipt, dict):
                raise CheckpointError("Strava checkpoint receipt is invalid")
            fingerprint = receipt.get("token_fingerprint")
            if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                raise CheckpointError("Strava checkpoint fingerprint is invalid")
            if not isinstance(receipt.get("provider_acknowledged"), bool):
                raise CheckpointError("Strava checkpoint provider state is invalid")
            if not isinstance(receipt.get("local_marked_inactive"), bool):
                raise CheckpointError("Strava checkpoint local state is invalid")
        self._receipts = receipts

    def _persist(self) -> None:
        parent = self.path.parent
        if not parent.is_dir():
            raise CheckpointError("checkpoint parent directory does not exist")
        temporary_path: str | None = None
        try:
            fd, temporary_path = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                dir=str(parent),
                text=True,
            )
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._payload(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            if self.path.is_symlink():
                raise CheckpointError("checkpoint path became a symbolic link")
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise CheckpointError("failed to preserve Strava checkpoint") from exc
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def record_provider_acknowledged(self, grant: StoredGrant) -> None:
        super().record_provider_acknowledged(grant)
        self._persist()

    def record_local_marked_inactive(self, grant: StoredGrant) -> None:
        super().record_local_marked_inactive(grant)
        self._persist()


@dataclass(frozen=True)
class CutoverResult:
    success: bool
    cutover_mode: str
    strava_api_contacted: bool
    connections_revoked: int | None
    connections_marked_inactive: int
    failed_connection_count: int
    provider_subscriptions_deleted: int | None
    local_subscriptions_disabled: int
    remaining_active_connection_count: int
    remaining_local_subscription_count: int
    remaining_provider_subscription_count: int | None
    stored_connection_count_before: int
    stored_connection_count_after: int
    imported_activity_links_before: int
    imported_activity_links_after: int
    strava_origin_rides_before: int
    strava_origin_rides_after: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "cutover_mode": self.cutover_mode,
            "strava_api_contacted": self.strava_api_contacted,
            "connections_revoke_acknowledged": self.connections_revoked,
            "connections_marked_inactive": self.connections_marked_inactive,
            "failed_connection_count": self.failed_connection_count,
            "provider_subscriptions_deleted": self.provider_subscriptions_deleted,
            "local_subscriptions_disabled": self.local_subscriptions_disabled,
            "remaining_active_connection_count": self.remaining_active_connection_count,
            "remaining_local_subscription_count": self.remaining_local_subscription_count,
            "remaining_provider_subscription_count": self.remaining_provider_subscription_count,
            "stored_connection_count_before": self.stored_connection_count_before,
            "stored_connection_count_after": self.stored_connection_count_after,
            "imported_activity_links_before": self.imported_activity_links_before,
            "imported_activity_links_after": self.imported_activity_links_after,
            "strava_origin_rides_before": self.strava_origin_rides_before,
            "strava_origin_rides_after": self.strava_origin_rides_after,
            "database_rows_deleted": 0,
        }


class CutoverIncompleteError(CutoverError):
    def __init__(self, result: CutoverResult) -> None:
        super().__init__(
            "Strava cutover incomplete; confirmed successes were preserved and "
            "remaining grants require a new dry-run plan"
        )
        self.result = result


class CutoverStore(Protocol):
    def list_stored_connection_ids(self) -> list[str]: ...

    def list_active_connection_ids(self) -> list[str]: ...

    def list_stored_connections(self) -> list[StoredGrant]: ...

    def list_active_subscriptions(self) -> list[LocalSubscription]: ...

    def count_imported_activity_links(self) -> int: ...

    def count_strava_origin_rides(self) -> int: ...

    def mark_connection_revoked(self, connection_id: str) -> None: ...

    def mark_subscription_inactive(self, row_id: str) -> None: ...


class StravaProvider(Protocol):
    application_id: str

    def list_subscription_ids(self) -> list[int]: ...

    def delete_subscription(self, subscription_id: int) -> None: ...

    def revoke_refresh_token(self, refresh_token: str) -> None: ...

    def revoke_access_token(self, access_token: str) -> None: ...


def _normalized_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ConfirmationError("SUPABASE_URL must be an absolute HTTPS origin")
    if parsed.username is not None or parsed.password is not None:
        raise ConfirmationError("SUPABASE_URL must not contain user information")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ConfirmationError(
            "SUPABASE_URL must be a canonical origin without path, query, or fragment"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfirmationError("SUPABASE_URL contains an invalid port") from exc
    host = parsed.hostname.lower()
    formatted_host = f"[{host}]" if ":" in host else host
    port_suffix = f":{port}" if port is not None else ""
    return f"https://{formatted_host}{port_suffix}"


def _public_target_host(supabase_url: str) -> str:
    parsed = urlparse(supabase_url)
    host = parsed.hostname or ""
    formatted_host = f"[{host}]" if ":" in host else host
    return f"{formatted_host}:{parsed.port}" if parsed.port is not None else formatted_host


def _plan_payload(
    *,
    supabase_url: str,
    strava_application_id: str,
    cutover_mode: str,
    stored_connection_ids: tuple[str, ...],
    active_connection_ids: tuple[str, ...],
    local_subscriptions: tuple[LocalSubscription, ...],
    provider_subscription_ids: tuple[int, ...] | None,
    imported_activity_link_count: int,
    strava_origin_ride_count: int,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "supabase_url": supabase_url,
        "strava_application_id": strava_application_id,
        "cutover_mode": cutover_mode,
        "stored_connection_ids": list(stored_connection_ids),
        "active_connection_ids": list(active_connection_ids),
        "local_subscriptions": [
            {
                "row_id": subscription.row_id,
                "provider_subscription_id": subscription.provider_subscription_id,
            }
            for subscription in local_subscriptions
        ],
        "provider_subscription_ids": (
            list(provider_subscription_ids)
            if provider_subscription_ids is not None
            else None
        ),
        "imported_activity_link_count": imported_activity_link_count,
        "strava_origin_ride_count": strava_origin_ride_count,
    }


def build_plan(
    store: CutoverStore,
    provider: StravaProvider | None,
    *,
    supabase_url: str,
    local_only: bool = False,
    strava_application_id: str | None = None,
) -> CutoverPlan:
    normalized_url = _normalized_url(supabase_url)
    stored_connection_ids = tuple(sorted(store.list_stored_connection_ids()))
    active_connection_ids = tuple(sorted(store.list_active_connection_ids()))
    if not set(active_connection_ids).issubset(stored_connection_ids):
        raise DatabaseError("active Strava connections are not a subset of stored rows")
    local_subscriptions = tuple(
        sorted(
            store.list_active_subscriptions(),
            key=lambda subscription: (
                subscription.provider_subscription_id is None,
                subscription.provider_subscription_id or 0,
                subscription.row_id,
            ),
        )
    )
    if local_only:
        if provider is not None:
            raise ConfirmationError(
                "local-only planning must not construct a Strava provider client"
            )
        application_id = str(strava_application_id or "").strip()
        if not application_id:
            raise ConfirmationError(
                "local-only planning requires the Strava application ID"
            )
        cutover_mode = LOCAL_ONLY_MODE
        provider_subscription_ids = None
    else:
        if provider is None:
            raise ConfirmationError("provider-revoke planning requires Strava access")
        application_id = str(provider.application_id)
        cutover_mode = PROVIDER_REVOKE_MODE
        provider_subscription_ids = tuple(sorted(provider.list_subscription_ids()))
    imported_activity_link_count = store.count_imported_activity_links()
    strava_origin_ride_count = store.count_strava_origin_rides()
    payload = _plan_payload(
        supabase_url=normalized_url,
        strava_application_id=application_id,
        cutover_mode=cutover_mode,
        stored_connection_ids=stored_connection_ids,
        active_connection_ids=active_connection_ids,
        local_subscriptions=local_subscriptions,
        provider_subscription_ids=provider_subscription_ids,
        imported_activity_link_count=imported_activity_link_count,
        strava_origin_ride_count=strava_origin_ride_count,
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return CutoverPlan(
        supabase_url=normalized_url,
        strava_application_id=application_id,
        cutover_mode=cutover_mode,
        stored_connection_ids=stored_connection_ids,
        active_connection_ids=active_connection_ids,
        local_subscriptions=local_subscriptions,
        provider_subscription_ids=provider_subscription_ids,
        imported_activity_link_count=imported_activity_link_count,
        strava_origin_ride_count=strava_origin_ride_count,
        sha256=digest,
    )


def validate_apply_request(
    plan: CutoverPlan,
    *,
    confirmation: str | None,
    expected_plan_sha256: str | None,
    expected_supabase_url: str | None = None,
    expected_strava_application_id: str | None = None,
) -> None:
    required_confirmation = (
        LOCAL_ONLY_CONFIRMATION_PHRASE
        if plan.cutover_mode == LOCAL_ONLY_MODE
        else CONFIRMATION_PHRASE
    )
    if confirmation != required_confirmation:
        raise ConfirmationError(
            f"execution requires --confirm {required_confirmation}"
        )
    if expected_plan_sha256 != plan.sha256:
        raise ConfirmationError("--expected-plan-sha256 does not match the live plan")
    if expected_supabase_url is not None:
        if _normalized_url(expected_supabase_url) != plan.supabase_url:
            raise ConfirmationError("--expected-supabase-url does not match the live target")
    if expected_strava_application_id is not None:
        if str(expected_strava_application_id) != plan.strava_application_id:
            raise ConfirmationError(
                "--expected-strava-application-id does not match the live target"
            )


def _result(
    *,
    plan: CutoverPlan,
    revoked: int | None,
    marked_inactive: int,
    failures: int,
    provider_deleted: int | None,
    local_disabled: int,
    remaining_active: int,
    remaining_local: int,
    remaining_provider: int | None,
    stored_after: int,
    imported_after: int,
    rides_after: int,
) -> CutoverResult:
    if plan.cutover_mode == LOCAL_ONLY_MODE:
        success = (
            failures == 0
            and remaining_active == 0
            and remaining_local == 0
            and remaining_provider is None
            and stored_after == plan.stored_connection_count
            and imported_after == plan.imported_activity_link_count
            and rides_after == plan.strava_origin_ride_count
        )
    else:
        success = (
            failures == 0
            and revoked == plan.stored_connection_count
            and marked_inactive == plan.stored_connection_count
            and remaining_active == 0
            and remaining_local == 0
            and remaining_provider == 0
            and stored_after == plan.stored_connection_count
            and imported_after == plan.imported_activity_link_count
            and rides_after == plan.strava_origin_ride_count
        )
    return CutoverResult(
        success=success,
        cutover_mode=plan.cutover_mode,
        strava_api_contacted=plan.cutover_mode == PROVIDER_REVOKE_MODE,
        connections_revoked=revoked,
        connections_marked_inactive=marked_inactive,
        failed_connection_count=failures,
        provider_subscriptions_deleted=provider_deleted,
        local_subscriptions_disabled=local_disabled,
        remaining_active_connection_count=remaining_active,
        remaining_local_subscription_count=remaining_local,
        remaining_provider_subscription_count=remaining_provider,
        stored_connection_count_before=plan.stored_connection_count,
        stored_connection_count_after=stored_after,
        imported_activity_links_before=plan.imported_activity_link_count,
        imported_activity_links_after=imported_after,
        strava_origin_rides_before=plan.strava_origin_ride_count,
        strava_origin_rides_after=rides_after,
    )


def execute_cutover(
    store: CutoverStore,
    provider: StravaProvider,
    plan: CutoverPlan,
    *,
    progress: CutoverProgress | None = None,
) -> CutoverResult:
    if plan.cutover_mode != PROVIDER_REVOKE_MODE:
        raise ConfirmationError(
            "provider cutover cannot execute a local-only plan"
        )
    progress = progress or InMemoryCutoverProgress()
    current_plan = build_plan(store, provider, supabase_url=plan.supabase_url)
    if current_plan.sha256 != plan.sha256:
        raise PlanDriftError(
            "cutover target drifted after dry-run; review a new plan before execution"
        )

    grants = store.list_stored_connections()
    if tuple(sorted(grant.connection_id for grant in grants)) != plan.stored_connection_ids:
        raise PlanDriftError(
            "stored Strava grant rows drifted before revocation; review a new plan"
        )
    progress.validate_grants(grants)

    provider_deleted = 0
    provider_subscription_ids = plan.provider_subscription_ids
    if provider_subscription_ids is None:
        raise ConfirmationError("provider cutover plan has no provider inventory")
    for subscription_id in provider_subscription_ids:
        provider.delete_subscription(subscription_id)
        provider_deleted += 1
    remaining_provider_ids = provider.list_subscription_ids()
    if remaining_provider_ids:
        raise ProviderError(
            "Strava still reports an active webhook subscription; no grants were revoked"
        )

    local_disabled = 0
    for subscription in plan.local_subscriptions:
        store.mark_subscription_inactive(subscription.row_id)
        local_disabled += 1

    active_connection_ids = set(plan.active_connection_ids)
    for grant in grants:
        try:
            if not progress.provider_acknowledged(grant):
                provider.revoke_refresh_token(grant.refresh_token)
                provider.revoke_access_token(grant.access_token)
                progress.record_provider_acknowledged(grant)
            if (
                grant.connection_id in active_connection_ids
                or not progress.local_marked_inactive(grant)
            ):
                store.mark_connection_revoked(grant.connection_id)
                progress.record_local_marked_inactive(grant)
        except ProviderHaltError:
            break
        except (ProviderError, DatabaseError):
            continue

    revoked = sum(progress.provider_acknowledged(grant) for grant in grants)
    marked_inactive = sum(
        progress.local_marked_inactive(grant) for grant in grants
    )
    failures = len(grants) - marked_inactive

    stored_after_ids = tuple(sorted(store.list_stored_connection_ids()))
    active_after_ids = store.list_active_connection_ids()
    local_after = store.list_active_subscriptions()
    provider_after = provider.list_subscription_ids()
    imported_after = store.count_imported_activity_links()
    rides_after = store.count_strava_origin_rides()

    result = _result(
        plan=plan,
        revoked=revoked,
        marked_inactive=marked_inactive,
        failures=failures,
        provider_deleted=provider_deleted,
        local_disabled=local_disabled,
        remaining_active=len(active_after_ids),
        remaining_local=len(local_after),
        remaining_provider=len(provider_after),
        stored_after=len(stored_after_ids),
        imported_after=imported_after,
        rides_after=rides_after,
    )
    if stored_after_ids != plan.stored_connection_ids or not result.success:
        raise CutoverIncompleteError(result)
    return result


def execute_local_only_cutover(
    store: CutoverStore,
    plan: CutoverPlan,
) -> CutoverResult:
    """Disable exact local Strava rows without loading tokens or contacting Strava."""
    if plan.cutover_mode != LOCAL_ONLY_MODE:
        raise ConfirmationError(
            "local-only cutover cannot execute a provider-revoke plan"
        )
    current_plan = build_plan(
        store,
        None,
        supabase_url=plan.supabase_url,
        local_only=True,
        strava_application_id=plan.strava_application_id,
    )
    if current_plan.sha256 != plan.sha256:
        raise PlanDriftError(
            "cutover target drifted after dry-run; review a new plan before execution"
        )

    local_disabled = 0
    for subscription in plan.local_subscriptions:
        store.mark_subscription_inactive(subscription.row_id)
        local_disabled += 1

    marked_inactive = 0
    for connection_id in plan.active_connection_ids:
        store.mark_connection_revoked(connection_id)
        marked_inactive += 1

    stored_after_ids = tuple(sorted(store.list_stored_connection_ids()))
    active_after_ids = store.list_active_connection_ids()
    local_after = store.list_active_subscriptions()
    imported_after = store.count_imported_activity_links()
    rides_after = store.count_strava_origin_rides()
    result = _result(
        plan=plan,
        revoked=None,
        marked_inactive=marked_inactive,
        failures=len(active_after_ids),
        provider_deleted=None,
        local_disabled=local_disabled,
        remaining_active=len(active_after_ids),
        remaining_local=len(local_after),
        remaining_provider=None,
        stored_after=len(stored_after_ids),
        imported_after=imported_after,
        rides_after=rides_after,
    )
    if stored_after_ids != plan.stored_connection_ids or not result.success:
        raise CutoverIncompleteError(result)
    return result


class SupabaseCutoverStore:
    def __init__(
        self,
        db: BackendSupabaseClient,
        *,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if page_size < 1 or page_size > 1000:
            raise ValueError("page_size must be between 1 and 1000")
        self.db = db
        self.page_size = page_size

    def _select_all(
        self,
        table: str,
        columns: str,
        *,
        active_only: bool = False,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        offset = 0
        while True:
            try:
                query = self.db.table(table).select(columns)
                if active_only:
                    query = query.eq("is_active", True)
                response = (
                    query.order("id")
                    .range(offset, offset + self.page_size - 1)
                    .execute()
                )
            except Exception as exc:
                raise DatabaseError(f"failed to inventory {table}") from exc
            page = list(getattr(response, "data", None) or [])
            if not page:
                return rows
            for row in page:
                row_id = str(row.get("id") or "")
                if not row_id or row_id in seen_ids:
                    raise DatabaseError(
                        f"{table} pagination returned a missing or duplicate id"
                    )
                seen_ids.add(row_id)
            rows.extend(page)
            offset += len(page)

    def list_stored_connection_ids(self) -> list[str]:
        return [
            str(row["id"])
            for row in self._select_all("strava_connections", "id")
        ]

    def list_active_connection_ids(self) -> list[str]:
        return [
            str(row["id"])
            for row in self._select_all(
                "strava_connections",
                "id",
                active_only=True,
            )
        ]

    def list_stored_connections(self) -> list[StoredGrant]:
        grants: list[StoredGrant] = []
        for row in self._select_all(
            "strava_connections",
            "id,refresh_token,access_token",
        ):
            connection_id = str(row.get("id") or "")
            refresh_token = str(row.get("refresh_token") or "")
            access_token = str(row.get("access_token") or "")
            if not connection_id or not refresh_token or not access_token:
                raise DatabaseError("stored Strava grant row is missing required fields")
            grants.append(
                StoredGrant(
                    connection_id=connection_id,
                    refresh_token=refresh_token,
                    access_token=access_token,
                )
            )
        return grants

    def list_active_subscriptions(self) -> list[LocalSubscription]:
        subscriptions: list[LocalSubscription] = []
        for row in self._select_all(
            "strava_webhook_subscriptions",
            "id,subscription_id",
            active_only=True,
        ):
            row_id = str(row.get("id") or "")
            if not row_id:
                raise DatabaseError("local Strava subscription row has no id")
            raw_provider_id = row.get("subscription_id")
            subscriptions.append(
                LocalSubscription(
                    row_id=row_id,
                    provider_subscription_id=(
                        int(raw_provider_id) if raw_provider_id is not None else None
                    ),
                )
            )
        return subscriptions

    def _exact_count(self, table: str, *, import_sources: bool = False) -> int:
        try:
            query = self.db.table(table).select("id", count="exact")
            if import_sources:
                query = query.in_("import_source", list(STRAVA_IMPORT_SOURCES))
            response = query.limit(1).execute()
        except Exception as exc:
            raise DatabaseError(f"failed to count {table}") from exc
        count = getattr(response, "count", None)
        if count is None:
            raise DatabaseError(f"exact count unavailable for {table}")
        return int(count)

    def count_imported_activity_links(self) -> int:
        return self._exact_count("strava_imported_activities")

    def count_strava_origin_rides(self) -> int:
        return self._exact_count("rides", import_sources=True)

    def _verify_inactive(self, table: str, row_id: str) -> None:
        try:
            response = (
                self.db.table(table)
                .select("id,is_active")
                .eq("id", row_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise DatabaseError(f"failed to verify {table} row") from exc
        rows = list(getattr(response, "data", None) or [])
        if len(rows) != 1 or rows[0].get("is_active") is not False:
            raise DatabaseError(f"{table} row did not verify inactive")

    def mark_connection_revoked(self, connection_id: str) -> None:
        try:
            (
                self.db.table("strava_connections")
                .update({"is_active": False})
                .eq("id", connection_id)
                .execute()
            )
        except Exception as exc:
            raise DatabaseError("failed to mark Strava grant inactive") from exc
        self._verify_inactive("strava_connections", connection_id)

    def mark_subscription_inactive(self, row_id: str) -> None:
        try:
            (
                self.db.table("strava_webhook_subscriptions")
                .update({"is_active": False})
                .eq("id", row_id)
                .execute()
            )
        except Exception as exc:
            raise DatabaseError("failed to mark Strava subscription inactive") from exc
        self._verify_inactive("strava_webhook_subscriptions", row_id)


class StravaProviderClient:
    def __init__(
        self,
        client: httpx.Client,
        *,
        application_id: str,
        client_secret: str,
        max_revoke_attempts: int = 3,
    ) -> None:
        if not 1 <= max_revoke_attempts <= MAX_REVOKE_ATTEMPTS:
            raise ConfirmationError(
                f"max_revoke_attempts must be between 1 and {MAX_REVOKE_ATTEMPTS}"
            )
        self.client = client
        self.application_id = str(application_id)
        self._client_secret = client_secret
        self.max_revoke_attempts = max_revoke_attempts
        _install_client_secret_log_redaction(client_secret)

    def list_subscription_ids(self) -> list[int]:
        try:
            response = self.client.get(
                STRAVA_SUBSCRIPTIONS_URL,
                params={
                    "client_id": self.application_id,
                    "client_secret": self._client_secret,
                },
            )
        except httpx.TransportError as exc:
            raise ProviderError("Strava subscription inventory request failed") from exc
        if response.status_code != 200:
            raise ProviderError(
                f"Strava subscription inventory returned HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            if not isinstance(payload, list):
                raise TypeError
            return sorted({int(row["id"]) for row in payload})
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("Strava subscription inventory was malformed") from exc

    def delete_subscription(self, subscription_id: int) -> None:
        try:
            response = self.client.delete(
                f"{STRAVA_SUBSCRIPTIONS_URL}/{subscription_id}",
                params={
                    "client_id": self.application_id,
                    "client_secret": self._client_secret,
                },
            )
        except httpx.TransportError:
            response = None
        if response is not None and response.status_code == 204:
            return
        if subscription_id not in self.list_subscription_ids():
            return
        status = response.status_code if response is not None else "transport_error"
        raise ProviderError(
            f"Strava webhook delete was not confirmed (status={status})"
        )

    def _revoke_token(self, token: str, *, token_type_hint: str) -> None:
        for attempt in range(1, self.max_revoke_attempts + 1):
            try:
                response = self.client.post(
                    STRAVA_REVOKE_URL,
                    auth=httpx.BasicAuth(
                        username=self.application_id,
                        password=self._client_secret,
                    ),
                    data={
                        "token": token,
                        "token_type_hint": token_type_hint,
                    },
                )
            except httpx.TransportError as exc:
                if attempt == self.max_revoke_attempts:
                    raise ProviderHaltError(
                        "Strava grant revocation transport failed; checkpoint preserved"
                    ) from exc
                time.sleep(min(2 ** (attempt - 1), 4))
                continue

            if response.status_code == 200:
                return
            if response.status_code == 503 and attempt < self.max_revoke_attempts:
                time.sleep(min(2 ** (attempt - 1), 4))
                continue
            if response.status_code == 429:
                raise ProviderHaltError(
                    "Strava rate-limited grant revocation; checkpoint preserved"
                )
            if response.status_code == 401 or response.status_code >= 500:
                raise ProviderHaltError(
                    f"Strava grant revocation halted on HTTP {response.status_code}; "
                    "checkpoint preserved"
                )
            raise ProviderError(
                f"Strava grant revocation returned HTTP {response.status_code}"
            )
        raise ProviderHaltError(
            "Strava grant revocation exhausted retry attempts; checkpoint preserved"
        )

    def revoke_refresh_token(self, refresh_token: str) -> None:
        self._revoke_token(refresh_token, token_type_hint="refresh_token")

    def revoke_access_token(self, access_token: str) -> None:
        self._revoke_token(access_token, token_type_hint="access_token")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="disable local connection and webhook rows without Strava API contact",
    )
    parser.add_argument("--confirm")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--expected-supabase-url")
    parser.add_argument("--expected-strava-application-id")
    parser.add_argument("--checkpoint-file")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--max-revoke-attempts", type=int, default=3)
    parser.add_argument("--request-timeout-seconds", type=float, default=20.0)
    return parser.parse_args(list(argv) if argv is not None else None)


def _require_service_role_key(service_key: str) -> None:
    if service_key.startswith(MODERN_SECRET_PREFIX):
        if len(service_key) > len(MODERN_SECRET_PREFIX):
            return
        raise ConfirmationError("Supabase service-role secret key is incomplete")

    parts = service_key.split(".")
    if len(parts) == 3:
        try:
            payload_segment = parts[1]
            padding = "=" * (-len(payload_segment) % 4)
            payload = json.loads(
                base64.urlsafe_b64decode(payload_segment + padding).decode("utf-8")
            )
        except (binascii.Error, UnicodeDecodeError, ValueError):
            payload = None
        if isinstance(payload, dict) and payload.get("role") == "service_role":
            return

    raise ConfirmationError(
        "SUPABASE_SERVICE_KEY must be a server service-role secret; "
        "anon, publishable, authenticated, and opaque keys are not accepted"
    )


def _required_environment(
    *,
    local_only: bool = False,
) -> tuple[str, str, str, str | None]:
    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    service_key = (
        os.getenv("SUPABASE_SERVICE_KEY", "").strip()
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )
    client_id = os.getenv("STRAVA_CLIENT_ID", "").strip()
    client_secret = os.getenv("STRAVA_CLIENT_SECRET", "").strip()
    required_values = [
        ("SUPABASE_URL", supabase_url),
        ("SUPABASE_SERVICE_KEY", service_key),
        ("STRAVA_CLIENT_ID", client_id),
    ]
    if not local_only:
        required_values.append(("STRAVA_CLIENT_SECRET", client_secret))
    missing = [name for name, value in required_values if not value]
    if missing:
        raise ConfirmationError(
            "required server environment is missing: " + ", ".join(missing)
        )
    _require_service_role_key(service_key)
    return supabase_url, service_key, client_id, client_secret or None


def _validate_execution_request(
    args: argparse.Namespace,
    plan: CutoverPlan,
) -> None:
    sync_gate = os.getenv("STRAVA_SYNC_ENABLED", "").strip().lower()
    if sync_gate not in {"0", "false", "no", "off"}:
        raise ConfirmationError(
            "--execute requires explicit STRAVA_SYNC_ENABLED=false"
        )
    if not args.expected_supabase_url:
        raise ConfirmationError("--execute requires --expected-supabase-url")
    if not args.expected_strava_application_id:
        raise ConfirmationError(
            "--execute requires --expected-strava-application-id"
        )
    if plan.cutover_mode == PROVIDER_REVOKE_MODE and not args.checkpoint_file:
        raise ConfirmationError("--execute requires --checkpoint-file")
    validate_apply_request(
        plan,
        confirmation=args.confirm,
        expected_plan_sha256=args.expected_plan_sha256,
        expected_supabase_url=args.expected_supabase_url,
        expected_strava_application_id=args.expected_strava_application_id,
    )


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    supabase_url, service_key, client_id, client_secret = _required_environment(
        local_only=args.local_only
    )
    supabase_url = _normalized_url(supabase_url)
    db = create_backend_supabase_client(supabase_url, service_key)
    store = SupabaseCutoverStore(db, page_size=args.page_size)

    if args.local_only:
        plan = build_plan(
            store,
            None,
            supabase_url=supabase_url,
            local_only=True,
            strava_application_id=client_id,
        )
        output: dict[str, Any] = {
            "schema": SCHEMA,
            "mode": "dry_run",
            "plan": plan.to_public_dict(),
        }
        if args.execute:
            _validate_execution_request(args, plan)
            output["mode"] = "executed"
            try:
                output["result"] = execute_local_only_cutover(
                    store,
                    plan,
                ).to_public_dict()
            except CutoverIncompleteError as exc:
                output["mode"] = "incomplete"
                output["result"] = exc.result.to_public_dict()
                print(json.dumps(output, indent=2, sort_keys=True))
                return 1
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0

    if client_secret is None:
        raise ConfirmationError("STRAVA_CLIENT_SECRET is required for provider access")
    with httpx.Client(timeout=args.request_timeout_seconds) as http_client:
        provider = StravaProviderClient(
            http_client,
            application_id=client_id,
            client_secret=client_secret,
            max_revoke_attempts=args.max_revoke_attempts,
        )
        plan = build_plan(store, provider, supabase_url=supabase_url)
        output = {
            "schema": SCHEMA,
            "mode": "dry_run",
            "plan": plan.to_public_dict(),
        }
        if args.execute:
            _validate_execution_request(args, plan)
            progress = FileCutoverProgress(args.checkpoint_file, plan)
            output["mode"] = "executed"
            try:
                output["result"] = execute_cutover(
                    store,
                    provider,
                    plan,
                    progress=progress,
                ).to_public_dict()
            except CutoverIncompleteError as exc:
                output["mode"] = "incomplete"
                output["result"] = exc.result.to_public_dict()
                print(json.dumps(output, indent=2, sort_keys=True))
                return 1
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CutoverError as exc:
        print(
            _redact_client_secret(
                str(exc),
                os.getenv("STRAVA_CLIENT_SECRET", "").strip() or None,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
