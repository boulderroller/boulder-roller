"""Owner-scoped metadata export, with separate downloads for bulk ride data."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any


class DataExportError(RuntimeError):
    """Safe diagnostics: dataset and failure class, never provider payloads."""

    def __init__(self, dataset: str, reason: str = "unavailable"):
        self.dataset, self.reason = dataset, reason
        super().__init__(f"Account export {reason}: {dataset}")


MAX_EXPORT_BYTES = 32 * 1024 * 1024
_CREDENTIAL_KEYS = frozenset({
    "token", "tokenhash", "accesstoken", "refreshtoken", "statustokenhash", "apnstoken",
    "authorization", "cookie", "cookies", "password", "passwordhash", "secret", "secretkey",
    "privatekey", "nonce", "invitecode", "invitecodehash", "workerleasetoken", "leasetoken",
    "deletedwalletfingerprint", "walletfingerprint", "leaseowner", "workerid",
})
SESSION_COLUMNS = "id,device_id,user_agent,ip_address,location_hint,created_at,last_used_at,expires_at,revoked_at,revocation_reason"
PUSH_COLUMNS = "device_id,environment,app_version,created_at,updated_at"
STRAVA_COLUMNS = "id,wallet,strava_athlete_id,athlete_username,athlete_firstname,athlete_lastname,scope,connected_at,last_sync_at,is_active,expires_at"
RIDE_COLUMNS = "id,user_id,processing_status,error_message,import_source,created_at,raw_file_path,raw_file_size_bytes,file_hash,upload_verified_at,gps_track"
STREAM_COLUMNS = "id,ride_id,stream_type,sample_count,min_value,max_value,avg_value,created_at"
# Full rows of these datasets are available in the authenticated per-ride download.
RIDE_DATASETS = (
    ("activity_streams", "ride_id", "id", STREAM_COLUMNS),
    ("activity_tile_samples", "activity_id", "id", None),
    ("canon_traversal_evidence", "ride_id", "ride_hash_hex,ride_parser_version,evidence_version", None),
    ("patterns_climb", "activity_id", "id", "id,activity_id,wallet"),
    ("ride_climb_backfill_reviews", "activity_id", "id", "id,activity_id"),
    ("replay_ride_results", "ride_id", "id", "id,ride_id"),
    ("ride_diffs", "ride_id", "id", "id,ride_id"),
    ("training_replay_state", "ride_id", "ride_id", "*"),
    ("training_pay_attempts", "ride_id", "ride_id", "ride_id,started_at,active,phase1_completed_at,phase2_completed_at,phase3_completed_at"),
)
PLAN_DATASETS = (
    ("ride_economic_completion_steps", "ride_id", "id", "*"),
    ("ride_economic_plan_audits", "ride_id", "id", "id,ride_id"),
    ("ride_economic_reviews", "ride_id", "id", "id,ride_id"),
    ("ride_economic_review_resolutions", "ride_id", "request_id", "request_id,ride_id"),
)


def without_credentials(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: without_credentials(item) for key, item in value.items()
                if re.sub(r"[^a-z0-9]", "", key.lower()) not in _CREDENTIAL_KEYS}
    if isinstance(value, list):
        return [without_credentials(item) for item in value]
    return value


class ExportReader:
    def __init__(self, client: Any, run: Any, *, bounded: bool = True):
        self.client, self.run, self.used_bytes = client, run, 0
        self.bounded = bounded

    def reserve(self, dataset: str, value: Any) -> None:
        self.used_bytes += len(json.dumps(value, default=str).encode("utf-8"))
        if self.bounded and self.used_bytes > MAX_EXPORT_BYTES:
            raise DataExportError(dataset, "exceeds response capacity")

    async def rows(self, table: str, filters: dict, key: str = "id", columns: str = "*") -> list[dict]:
        return [item async for page in self.pages(table, filters, key, columns) for item in page]

    async def pages(self, table: str, filters: dict, key="id", columns="*"):
        seen, cursor = set(), None
        keys = key.split(",")
        while True:
            def read():
                query = self.client.table(table).select(columns)
                for field, value in filters.items():
                    query = query.in_(field, value) if isinstance(value, list) else query.eq(field, value)
                for field in keys:
                    query = query.order(field)
                if cursor is not None:
                    if len(keys) == 1:
                        query = query.gt(keys[0], cursor[0])
                    else:
                        # Lexicographic cursor; values are quoted, schema-owned keys.
                        clauses = []
                        for index, field in enumerate(keys):
                            terms = [f"{keys[j]}.eq.{json.dumps(cursor[j])}" for j in range(index)]
                            terms.append(f"{field}.gt.{json.dumps(cursor[index])}")
                            clauses.append(terms[0] if len(terms) == 1 else "and(" + ",".join(terms) + ")")
                        query = query.or_(",".join(clauses))
                return query.range(0, 499).execute()
            try:
                page = getattr(await self.run(read), "data", None)
                if not isinstance(page, list):
                    raise ValueError("Malformed page")
                for item in page:
                    if not isinstance(item, dict) or any(item.get(k) is None for k in keys):
                        raise ValueError("Malformed row")
                    identity = tuple(item[k] for k in keys)
                    if identity in seen:
                        raise ValueError("Pagination did not advance")
                    seen.add(identity)
            except Exception as exc:
                raise DataExportError(table) from exc
            if not page:
                return
            clean = without_credentials(page)
            self.reserve(table, clean)  # Capacity failures must retain their reason.
            cursor = tuple(page[-1][k] for k in keys)
            yield clean
            # Only an empty page ends the read, even with a lower provider cap.

    async def children(self, table: str, parents: list, foreign_key: str, key="id", columns="*") -> list:
        result = []
        for offset in range(0, len(parents), 100):
            result.extend(await self.rows(table, {foreign_key: parents[offset:offset + 100]}, key, columns))
        return result


async def export_account(client: Any, run: Any, user_id: str) -> dict[str, Any]:
    reader = ExportReader(client, run)
    rows = reader.rows
    own = {"user_id": user_id}
    profiles = await rows("users", {"id": user_id})
    if len(profiles) != 1 or not profiles[0].get("wallet"):
        raise DataExportError("owner")
    profile = profiles[0]
    wallet = {"wallet": profile["wallet"]}
    data: dict[str, Any] = {"profile": profile, "rides": await rows("rides", own, columns=RIDE_COLUMNS)}
    for table, key in (
        ("user_state", "user_id"), ("achievements", "id"), ("privacy_zones", "id"),
        ("ride_media", "id"), ("notification_preferences", "user_id"), ("daily_training_load", "id"),
        ("fitness_metrics", "id"), ("auth_identities", "id"), ("activities", "id"),
        ("comments", "id"), ("kudos", "id"), ("audit_log", "id"),
        ("reward_ftp_authorities", "id"), ("reward_threshold_efforts", "id"),
        ("reward_threshold_candidates", "id"), ("reward_threshold_source_envelopes", "power_source_id"),
        ("reward_threshold_ratchets", "user_id"), ("reward_threshold_pending_promotions", "id"),
        ("reward_threshold_provisional_holds", "id"), ("reward_threshold_release_batches", "id"),
        ("reward_threshold_release_snapshots", "id"), ("claims", "segment_id"),
        ("vesting_schedules", "id"), ("harvest_events", "id"), ("token_transactions", "id"),
        ("segment_efforts", "id"), ("leaderboard_entries", "segment_id,epoch_number"),
        ("ride_economic_plans", "ride_id"), ("ride_effort_completion_windows", "ride_id,vault_id"),
    ):
        data[table] = await rows(table, own, key)
    for name, filters, key in (("following", {"follower_id": user_id}, "following_id"),
                               ("followers", {"following_id": user_id}, "follower_id")):
        data[name] = await rows("follows", filters, key)
    for table, filters, key, columns in (
        ("social_reports", {"reporter_id": user_id}, "id", "id,reporter_id,target_type,target_id,reason,details,status,reporter_message,created_at,updated_at"),
        ("deletion_requests", own, "id", "id,user_id,requested_at,completed_at,status,contract_version,blockers,failure_code,attempt_count,unuploaded_rides_acknowledged,completion_verified_at,updated_at"),
        ("mobile_push_devices", wallet, "device_id", PUSH_COLUMNS),
        ("strava_connections", wallet, "id", STRAVA_COLUMNS),
        ("invite_code_usage", wallet, "id", "id,code_id,wallet,used_at,ip_address,user_agent"),
        ("vault_creation_handoffs", {"creator_wallet": profile["wallet"]}, "vault_id", "*"),
        ("dung_mint_events", {"recipient": profile["wallet"]}, "id", "*"),
        ("dung_burn_events", {"burner": profile["wallet"]}, "id", "*"),
    ):
        data[table] = await rows(table, filters, key, columns)
    data["sessions"] = await rows("auth_refresh_tokens", wallet, columns=SESSION_COLUMNS)
    for table, key in (
        ("vault_stakes", "id"), ("ios_diagnostics", "id"), ("mobile_push_deliveries", "id"),
        ("vault_completions", "id"), ("economic_events", "id"), ("user_profile_snapshots", "id"),
        ("patterns_steady", "id"), ("patterns_exploration", "id"), ("scored_patterns", "id"),
        ("beetle_cards", "id"), ("distribution_receipts", "id"), ("leaderboard_history", "id"),
        ("cal_daily_balances", "date"), ("wallet_tile_history", "tile_id"),
        ("vault_shadow_usdc", "vault_signature"), ("tx_lifecycle", "id"),
        ("vault_leaderboards", "vault_signature,rank"), ("replay_batches", "id"),
    ):
        data[table] = await rows(table, wallet, key)
    for table, first, second, key in (
        ("notifications", own, wallet, "id"),
        ("balance_operations", {"rider_account_id": user_id}, {"protocol_wallet": profile["wallet"]}, "operation_id"),
    ):
        union = await rows(table, first, key) + await rows(table, second, key)
        data[table] = list({item[key]: item for item in union}.values())

    ride_ids = [r["id"] for r in data["rides"]]
    plan_ids = [r["ride_id"] for r in data["ride_economic_plans"]]
    for table, foreign_key, key, columns in (*RIDE_DATASETS, *PLAN_DATASETS):
        if columns is not None:
            parents = plan_ids if (table, foreign_key, key, columns) in PLAN_DATASETS else ride_ids
            data[table] = await reader.children(table, parents, foreign_key, key, columns)
    for table, parent, parent_key, foreign_key, key in (
        ("climb_efforts", "rides", "id", "ride_id", "id"),
        ("strava_imported_activities", "strava_connections", "id", "strava_connection_id", "id"),
        ("beetle_card_level_history", "beetle_cards", "id", "beetle_card_id", "id"),
        ("reward_threshold_provisional_hold_admissions", "reward_threshold_provisional_holds", "id", "hold_id", "hold_id"),
        ("reward_threshold_release_batch_items", "reward_threshold_release_batches", "id", "batch_id", "id"),
        ("reward_threshold_release_executions", "reward_threshold_release_snapshots", "id", "snapshot_id", "snapshot_id"),
        ("reward_threshold_release_steps", "reward_threshold_release_snapshots", "id", "snapshot_id", "id"),
        ("reward_threshold_release_item_claims", "reward_threshold_release_batch_items", "id", "batch_item_id", "batch_item_id"),
    ):
        columns = "*" if table != "reward_threshold_release_item_claims" else (
            "batch_item_id,attempts,consumed_snapshot_id,consumed_at,terminal_disposition,terminal_reason,"
            "terminal_evidence,terminal_at,repair_reason,repaired_at,created_at,updated_at")
        data[table] = await reader.children(table, [r[parent_key] for r in data[parent]], foreign_key, key, columns)
    data["ride_data_downloads"] = [
        {"ride_id": ride_id, "download_endpoint": f"/compliance/export/rides/{ride_id}/data"}
        for ride_id in sorted(set(ride_ids + plan_ids))
    ]
    data["files"] = await file_manifest(data)
    reader.reserve("files", data["files"])
    reader.reserve("ride_data_downloads", data["ride_data_downloads"])
    data["external_datasets"] = {"discord_intake": "no_verified_account_link"}
    return data


async def file_manifest(data: dict) -> list[dict]:
    from .file_storage import FileNotFoundError, create_file_storage_service
    entries = {}
    for ride in data["rides"]:
        if path := ride.get("raw_file_path"):
            entries[path] = {"path": path, "size_bytes": ride.get("raw_file_size_bytes"),
                             "sha256": ride.get("file_hash"), "download_endpoint": f"/rides/{ride['id']}/original",
                             "pending_upload": not bool(ride.get("upload_verified_at"))}
            if entries[path]["pending_upload"]:
                entries[path].pop("sha256", None)  # Client-declared until upload verification.
                entries[path].pop("size_bytes", None)
                entries[path]["content_status"] = "absent"
    for media in data["ride_media"]:
        if path := media.get("storage_path"):
            entries[path] = {"path": path, "pending_upload": media.get("upload_status") == "uploading"}
    profile = data["profile"]
    for field in ("avatar_storage_path", "avatar_pending_storage_path"):
        if path := profile.get(field):
            entries[path] = {"path": path, "pending_upload": field == "avatar_pending_storage_path"}
    for path in profile.get("avatar_cleanup_storage_paths") or []:
        entries.setdefault(path, {"path": path, "pending_upload": True, "cleanup_pending": True})
    for entry in list(entries.values()):
        if entry["pending_upload"] and entry["path"].startswith(("avatars/", "ride-media/")):
            path = "sanitized/" + entry["path"]
            entries.setdefault(path, {"path": path, "pending_upload": True})
    if not entries:
        return []
    try:
        storage = create_file_storage_service()
        async def fetch_metadata(entry):
            if entry.get("content_status") == "absent":
                return  # No verified upload; even a staged object is not an original.
            path = entry["path"]
            try:
                info = await storage.get_file_info(path)
            except FileNotFoundError:
                if not entry["pending_upload"]:
                    raise DataExportError("files")
                entry["content_status"] = "absent"
                return
            entry.update(content_status="available", size_bytes=info["size"])
            metadata = info.get("metadata") or {}
            if (path.startswith("sanitized/") and metadata.get("photo_sanitizer_version") == 1
                    and not entry.get("sha256") and metadata.get("sha256")):
                entry["sha256"] = metadata["sha256"]
            if info.get("etag"):
                entry["storage_etag"] = info["etag"]  # Opaque; not always a content hash.
        pending = list(entries.values())
        for offset in range(0, len(pending), 8):
            # Bound both request concurrency and task allocation. Finish the batch
            # before surfacing any failure so no background reads outlive export.
            results = await asyncio.gather(*(fetch_metadata(entry) for entry in pending[offset:offset + 8]),
                                           return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        return [{k: v for k, v in entry.items() if v is not None} for entry in entries.values()]
    except DataExportError:
        raise
    except Exception as exc:
        raise DataExportError("files") from exc


async def export_ride(client: Any, run: Any, user_id: str, ride_id: str):
    """Authorize first; stream pages so valid bulk evidence has no account-size cap."""
    reader = ExportReader(client, run, bounded=False)
    owned_ride = {"id": ride_id, "user_id": user_id}
    owned_plan = {"ride_id": ride_id, "user_id": user_id}
    rides = await reader.rows("rides", owned_ride, columns="id")
    plans = await reader.rows("ride_economic_plans", owned_plan, "ride_id", "ride_id")
    if not rides and not plans:
        return None
    datasets = []
    if rides:
        datasets.append(("rides", owned_ride, "id", "*"))
    if plans:
        datasets.append(("ride_economic_plans", owned_plan, "ride_id", "*"))
    for table, foreign_key, key, columns in (*RIDE_DATASETS, *PLAN_DATASETS):
        if (table, foreign_key, key, columns) in RIDE_DATASETS and not rides:
            continue
        if (table, foreign_key, key, columns) in PLAN_DATASETS and not plans:
            continue
        select = columns if table == "training_pay_attempts" else "*"
        datasets.append((table, {foreign_key: ride_id}, key, select))

    async def content():
        yield "{"
        for index, (table, filters, key, columns) in enumerate(datasets):
            yield ("," if index else "") + json.dumps(table) + ":["
            first = True
            async for page in reader.pages(table, filters, key, columns):
                for item in page:
                    yield ("" if first else ",") + json.dumps(item, default=str, separators=(",", ":"))
                    first = False
            yield "]"
        yield "}"
    return content()
