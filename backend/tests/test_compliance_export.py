import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID
from pathlib import Path
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.compliance_repository import ComplianceRepository
from app.dependencies import AuthenticatedUser, get_current_user
from app.routes import compliance
from app.services.data_export import DataExportError


UID = "11111111-1111-4111-8111-111111111111"


SQL = Path(__file__).parents[1] / "sql"
CATALOG = json.loads((SQL / "153_public_data_api_rls_lockdown.catalog.json").read_text())
KNOWN_TABLES = {row["name"] for row in CATALOG["app_relations"] + CATALOG["predecessor_152"]["relations"]}
# The catalog records identity, not ACLs. Model the baseline service-role read
# grants, then replay every explicit exception. New tables default to unreadable.
SERVICE_SELECT = set(KNOWN_TABLES)
# 172's backend ledger inherits the service default preserved by153. The real
# PostgreSQL check in test_stage1_canonical_migrations exercises that privilege.
# Keep this named fixture explicit; CREATE TABLE alone never implies access.
SERVICE_SELECT.add("balance_operations")
PUBLIC_SELECT = set()
IDENTIFIER = r"(?:public\.)?([a-z_][a-z_0-9]*)"
ACL = re.compile(
    r"(GRANT|REVOKE)\s+(ALL(?:\s+PRIVILEGES)?|[A-Z,\s]+)\s+ON\s+(?:TABLE\s+)?"
    r"((?:public\.)?[a-z_][a-z_0-9]*(?:\s*,\s*(?:public\.)?[a-z_][a-z_0-9]*)*)"
    r"\s+(TO|FROM)\s+([a-z_,\s]+);", re.I)
for path in sorted(SQL.glob("[0-9][0-9][0-9]_*.sql")):
    text = re.sub(r"--[^\n]*|/\*.*?\*/", "", path.read_text(), flags=re.S)
    if int(path.name[:3]) > 153:
        KNOWN_TABLES.update(re.findall(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + IDENTIFIER, text, re.I))
        for table in re.findall(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + IDENTIFIER, text, re.I):
            KNOWN_TABLES.discard(table)
            SERVICE_SELECT.discard(table)
            PUBLIC_SELECT.discard(table)
    for operation, privileges, tables, direction, roles in ACL.findall(text):
        if not ({"SELECT", "ALL"} & set(re.findall(r"\w+", privileges.upper()))):
            continue
        for role, grants in (("service_role", SERVICE_SELECT), ("public", PUBLIC_SELECT)):
            if role not in {item.strip().lower() for item in roles.split(",")}:
                continue
            for table in re.findall(IDENTIFIER, tables, re.I):
                if operation.upper() == "GRANT":
                    grants.add(table)
                else:
                    grants.discard(table)


class ExportClient:
    """PostgREST double with a two-row server cap independent of page size.

    Like the pinned client it has no or_(); composite keyset reads run through
    tests.pinned_postgrest instead.
    """
    def __init__(self, failure=None):
        self.failure = failure
        self.calls = []
        self.rows = {
            "users": [{"id": UID, "wallet": "fixture-wallet"}],
            "rides": [{"id": str(i), "user_id": UID, "raw_file_path": f"rides/{UID}/{i}.fit", "upload_verified_at": "2026-10-01"} for i in range(5)],
            "auth_refresh_tokens": [{"id": str(i), "wallet": "fixture-wallet", "device_id": f"device-{i}",
                "token_hash": "credential-hash", "created_at": "2026-10-01"} for i in range(5)],
            "privacy_zones": [{"id": str(i), "user_id": UID, "latitude": 40.12345} for i in range(5)],
            "audit_log": [{"id": str(i), "user_id": UID, "metadata": {"refresh_token": "secret"}} for i in range(5)],
            "activity_streams": [{"id": f"{i}-{j}", "ride_id": str(i), "values": [100, 200]} for i in range(5) for j in range(3)],
        }
        for rows in self.rows.values():
            for item in rows:
                item.setdefault("created_at", "2026-10-01")

    def table(self, name):
        if name not in KNOWN_TABLES:
            raise AssertionError(f"Unknown table: {name}")
        if name not in SERVICE_SELECT | PUBLIC_SELECT:
            raise PermissionError(f"service_role cannot SELECT: {name}")
        return ExportQuery(self, name)


class ExportQuery:
    def __init__(self, client, table):
        self.client, self.name = client, table
        self.filters, self.greater = {}, {}
        self.columns, self.keys = "*", []
        self.start, self.end = 0, 1

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def in_(self, key, value):
        self.filters[key] = value
        return self

    def gt(self, key, value):
        self.greater[key] = value
        return self

    def order(self, key, desc=False):
        self.keys = self.keys or key.split(",")  # PostgREST applies the first order parameter only.
        return self

    def limit(self, value):
        self.end = value - 1
        return self

    def range(self, start, end):
        self.start, self.end = start, end
        return self

    def execute(self):
        self.client.calls.append((self.name, self.columns, self.filters.copy(), self.greater.copy()))
        if self.client.failure == self.name:
            raise RuntimeError("database unreachable with sensitive upstream context")
        rows = [r for r in self.client.rows.get(self.name, [])
                if all((r.get(k) in v if isinstance(v, list) else r.get(k) == v) for k, v in self.filters.items())
                and all(r.get(k) > v for k, v in self.greater.items())]
        rows.sort(key=lambda r: tuple(r[k] for k in self.keys))
        rows = rows[self.start:min(self.end + 1, self.start + 2)]
        if self.columns != "*":
            rows = [{k: v for k, v in r.items() if k in self.columns.split(",")} for r in rows]
        return SimpleNamespace(data=rows)


def repository(client):
    return ComplianceRepository(client=client)


@pytest.mark.asyncio
async def test_export_paginates_all_datasets_including_children_and_excludes_credentials(monkeypatch):
    client = ExportClient()
    storage = SimpleNamespace(get_file_info=AsyncMock(return_value={"size": 21}))
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    exported = await repository(client).export_user_data(UUID(UID))
    assert len(exported["rides"]) == 5
    assert len(exported["sessions"]) == 5
    assert len(exported["privacy_zones"]) == 5
    assert len(exported["activity_streams"]) == 15
    assert len(exported["audit_log"]) == 5
    assert len(exported["files"]) == 5
    assert all(item["size_bytes"] == 21 and "content_base64" not in item for item in exported["files"])
    assert exported["sessions"][0]["device_id"] == "device-0"
    assert "token_hash" not in json.dumps(exported)
    assert "refresh_token" not in json.dumps(exported)
    assert all(columns != "*" for table, columns, _, _ in client.calls if table == "auth_refresh_tokens")
    assert {"vault_completions", "user_profile_snapshots", "economic_events", "follows", "notifications", "notification_preferences", "reward_threshold_efforts",
            "reward_threshold_candidates", "reward_threshold_source_envelopes", "reward_threshold_ratchets",
            "reward_threshold_pending_promotions", "ios_diagnostics", "mobile_push_devices"} <= {call[0] for call in client.calls}
    assert not {"token_balances", "user_stakes"} & {call[0] for call in client.calls}


@pytest.mark.parametrize("dataset", ["rides", "privacy_zones", "auth_refresh_tokens", "reward_threshold_efforts"])
def test_export_dataset_errors_are_visible_and_never_completed(monkeypatch, dataset):
    repo = repository(ExportClient(failure=dataset))
    repo.log_audit_event = AsyncMock()
    monkeypatch.setattr(compliance, "ComplianceRepository", lambda: repo)
    app = FastAPI()
    app.include_router(compliance.router)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser("fixture-wallet", UID, "device")
    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.get("/compliance/export")
    assert response.status_code == 503
    assert "completed" not in response.text
    assert "download_url" not in response.text
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.asyncio
async def test_export_missing_failed_media_is_not_relabelled_as_never_uploaded(monkeypatch):
    from app.services.file_storage import FileNotFoundError
    client = ExportClient()
    client.rows["rides"] = []
    client.rows["ride_media"] = [{"id": "media", "user_id": UID, "storage_path": f"ride-media/{UID}/photo.jpg", "upload_status": "failed"}]
    storage = SimpleNamespace(get_file_info=AsyncMock(side_effect=FileNotFoundError("absent")))
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    with pytest.raises(DataExportError):
        await repository(client).export_user_data(UUID(UID))


@pytest.mark.asyncio
async def test_export_over_memory_budget_fails_before_returning_partial_data(monkeypatch):
    from app.services import data_export
    monkeypatch.setattr(data_export, "MAX_EXPORT_BYTES", 100, raising=False)
    client = ExportClient()
    client.rows["rides"] = []
    with pytest.raises(DataExportError):
        await repository(client).export_user_data(UUID(UID))


@pytest.mark.asyncio
async def test_aborted_upload_and_twenty_ordinary_rides_export_without_bulk_bytes(monkeypatch):
    """Claude's 20 x two-hour ride reproduction, plus a never-uploaded file."""
    from app.services.file_storage import FileNotFoundError
    client = ExportClient()
    from app.utils.polyline import encode_gps_track
    track = encode_gps_track([{
        "latitude": 40.12345 + i * .00001, "longitude": -79.12345,
        "elevation": 350.0, "timestamp": i,
    } for i in range(7200)])
    client.rows["rides"] = [
        {"id": str(i), "user_id": UID, "processing_status": "completed",
         "upload_verified_at": "2026-10-01", "raw_file_path": f"rides/{UID}/{i}.fit",
         "raw_file_size_bytes": 404802, "file_hash": "a" * 64,
         "gps_track": track}
        for i in range(20)
    ] + [{"id": "aborted", "user_id": UID, "processing_status": "failed", "error_message": "Upload aborted by user",
          "raw_file_path": f"rides/{UID}/aborted.fit"}]
    client.rows["activity_streams"] = [
        {"id": f"{i}-{kind}", "ride_id": str(i), "stream_type": kind,
         "sample_count": 7200, "timestamps": list(range(7200)), "values": [200.0] * 7200}
        for i in range(20) for kind in ("power", "heartrate", "cadence", "speed", "temperature")
    ]

    async def info(path):
        if "aborted" in path:
            raise FileNotFoundError("absent")
        return {"size": 404802}

    storage = SimpleNamespace(get_file_info=AsyncMock(side_effect=info),
                              download_ride_file=AsyncMock(side_effect=AssertionError("no inline bytes")))
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    exported = await repository(client).export_user_data(UUID(UID))
    assert len(exported["rides"]) == 21
    assert len(exported["activity_streams"]) == 100
    assert exported["rides"][0]["gps_track"] == track
    assert len(json.dumps(exported)) < 4 * 1024 * 1024
    assert all("values" not in row and "timestamps" not in row for row in exported["activity_streams"])
    assert exported["files"][-1]["content_status"] == "absent"
    assert exported["files"][0]["download_endpoint"] == "/rides/0/original"
    storage.download_ride_file.assert_not_called()


@pytest.mark.asyncio
async def test_export_includes_wallet_addressed_notifications(monkeypatch):
    client = ExportClient()
    client.rows["rides"] = []
    client.rows["notifications"] = [
        {"id": "1", "user_id": UID, "wallet": "fixture-wallet"},
        {"id": "2", "user_id": None, "wallet": "fixture-wallet"},
        {"id": "3", "user_id": None, "wallet": "someone-else"},
    ]
    exported = await repository(client).export_user_data(UUID(UID))
    assert [row["id"] for row in exported["notifications"]] == ["1", "2"]


@pytest.mark.asyncio
async def test_capacity_error_is_not_relabelled_as_unavailable(monkeypatch):
    monkeypatch.setattr("app.services.data_export.MAX_EXPORT_BYTES", 1)
    with pytest.raises(DataExportError, match="capacity"):
        await repository(ExportClient()).export_user_data(UUID(UID))


def test_export_double_rejects_nonexistent_tables():
    with pytest.raises(AssertionError, match="Unknown table"):
        ExportClient().table("gps_points")


@pytest.mark.asyncio
async def test_keyset_pagination_survives_deletion(monkeypatch):
    from app.services.data_export import ExportReader
    client = ExportClient()
    real_execute = ExportQuery.execute
    def execute(query):
        if query.name == "privacy_zones" and len([c for c in client.calls if c[0] == query.name]) == 1:
            client.rows[query.name].pop(0)
        return real_execute(query)
    monkeypatch.setattr(ExportQuery, "execute", execute)
    async def run(fn): return fn()
    reader = ExportReader(client, run)
    assert [r["id"] for r in await reader.rows("privacy_zones", {"user_id": UID})] == list("01234")


@pytest.mark.asyncio
async def test_account_export_reads_every_composite_key_row_through_the_pinned_client():
    # The real pinned client has no or_(), and PostgREST applies only its first
    # order parameter. Rows tie on their first key, and page boundaries cut
    # those runs.
    from app.services.data_export import export_account
    from tests.pinned_postgrest import PinnedPostgrest

    wallet = "fixture-wallet"
    datasets = {
        "leaderboard_entries": ("segment_id", "epoch_number", [
            {"user_id": UID, "segment_id": str(UUID(int=segment)), "epoch_number": epoch}
            for segment in (1, 2) for epoch in range(600)]),
        "ride_effort_completion_windows": ("ride_id", "vault_id", [
            {"user_id": UID, "ride_id": str(UUID(int=ride)), "vault_id": vault}
            for ride in (3, 4) for vault in range(1, 301)]),
        "vault_leaderboards": ("vault_signature", "rank", [
            {"wallet": wallet, "vault_signature": f"vault-{vault:03d}", "rank": rank}
            for vault in range(60) for rank in range(1, 11)]),
    }
    tables = {table: list(rows) for table, (_, _, rows) in datasets.items()}
    tables["leaderboard_entries"].append(
        {"user_id": str(UUID(int=99)), "segment_id": str(UUID(int=1)), "epoch_number": 0})
    tables["users"] = [{"id": UID, "wallet": wallet}]
    server = PinnedPostgrest(tables)
    async def run(fn): return fn()

    exported = await export_account(server.client, run, UID)

    for table, (first, second, rows) in datasets.items():
        assert [(row[first], row[second]) for row in exported[table]] == sorted(
            (row[first], row[second]) for row in rows), table


def test_ride_download_streams_every_canon_evidence_row_through_the_pinned_client(monkeypatch):
    from tests.pinned_postgrest import PinnedPostgrest

    ride_id = "22222222-2222-4222-8222-222222222222"
    # One ride file evaluated under successive parser versions: every row ties on its hash.
    evidence = [{"ride_id": ride_id, "ride_hash_hex": "ab" * 32, "ride_parser_version": version,
                 "evidence_version": "canon_traversal_evidence_v1"} for version in range(1, 6)]
    server = PinnedPostgrest({"rides": [{"id": ride_id, "user_id": UID}],
                              "canon_traversal_evidence": evidence})
    monkeypatch.setattr(compliance, "ComplianceRepository", lambda: repository(server.client))
    app = FastAPI()
    app.include_router(compliance.router)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser("fixture-wallet", UID, "device")
    with TestClient(app) as http:
        response = http.get(f"/compliance/export/rides/{ride_id}/data")

    assert response.status_code == 200
    assert [row["ride_parser_version"] for row in response.json()["canon_traversal_evidence"]] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_failed_import_does_not_claim_missing_original_was_never_uploaded(monkeypatch):
    from app.services.file_storage import FileNotFoundError
    client = ExportClient()
    client.rows["rides"] = [{"id": "import", "user_id": UID, "processing_status": "failed",
        "import_source": "strava", "upload_verified_at": "2026-10-01",
        "raw_file_path": "rides/owner/import.fit", "file_hash": "a" * 64}]
    storage = SimpleNamespace(get_file_info=AsyncMock(side_effect=FileNotFoundError("absent")))
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    with pytest.raises(DataExportError, match="files"):
        await repository(client).export_user_data(UUID(UID))


def test_bulk_download_is_owner_only_and_has_no_account_size_limit(monkeypatch):
    client = ExportClient()
    ride_id = "22222222-2222-4222-8222-222222222222"
    client.rows["rides"] = [{"id": ride_id, "user_id": UID, "gps_track": [{"latitude": 40.123}] * 200}]
    client.rows["activity_streams"] = [{"id": "stream", "ride_id": ride_id, "values": list(range(1000))}]
    client.rows["ride_economic_plans"] = [{"ride_id": ride_id, "user_id": "someone-else"}]
    client.rows["ride_economic_plan_audits"] = [{"id": "foreign", "ride_id": ride_id, "details": "foreign private plan"}]
    monkeypatch.setattr("app.services.data_export.MAX_EXPORT_BYTES", 10)
    monkeypatch.setattr(compliance, "ComplianceRepository", lambda: repository(client))
    app = FastAPI()
    app.include_router(compliance.router)
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser("fixture-wallet", UID, "device")
    with TestClient(app) as http:
        response = http.get(f"/compliance/export/rides/{ride_id}/data")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json()["activity_streams"][0]["values"] == list(range(1000))
        assert len(response.json()["rides"][0]["gps_track"]) == 200
        assert "foreign private plan" not in response.text
        assert "ride_economic_plan_audits" not in response.json()
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser("other", "other", "device")
        assert http.get(f"/compliance/export/rides/{ride_id}/data").status_code == 404


@pytest.mark.asyncio
async def test_upload_manifest_does_not_trust_client_metadata_hash(monkeypatch):
    client = ExportClient()
    client.rows["rides"] = [{"id": "upload", "user_id": UID, "processing_status": "uploading",
                             "raw_file_path": "rides/owner/upload.fit", "file_hash": "client-declared"}]
    storage = SimpleNamespace(get_file_info=AsyncMock(return_value={"size": 4, "metadata": {"sha256": "client-forged"}}))
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    exported = await repository(client).export_user_data(UUID(UID))
    assert exported["files"][0]["content_status"] == "absent"
    assert "sha256" not in exported["files"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["Superseded by retry before upload completed", "Storage unavailable", "unknown failure"])
async def test_never_uploaded_ride_manifest_does_not_require_storage(monkeypatch, message):
    from app.services.data_export import file_manifest
    storage = SimpleNamespace(get_file_info=AsyncMock(side_effect=AssertionError("Unverified upload is not published")))
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service", lambda: storage)
    files = await file_manifest({"profile": {}, "ride_media": [], "rides": [{
        "id": "pending", "processing_status": "failed", "error_message": message,
        "raw_file_path": "rides/owner/pending.fit", "file_hash": "client-declared",
    }]})
    assert files[0]["content_status"] == "absent"
    assert "sha256" not in files[0]
    storage.get_file_info.assert_not_awaited()


@pytest.mark.asyncio
async def test_file_manifest_fetches_metadata_in_bounded_parallel_batches(monkeypatch):
    from app.services.data_export import file_manifest
    active = peak = 0
    async def info(path):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.001)
        active -= 1
        return {"size": 42}
    monkeypatch.setattr("app.services.file_storage.create_file_storage_service",
                        lambda: SimpleNamespace(get_file_info=info))
    rides = [{"id": str(i), "raw_file_path": f"rides/owner/{i}.fit", "upload_verified_at": "2026-10-01"}
             for i in range(25)]
    files = await file_manifest({"profile": {}, "ride_media": [], "rides": rides})
    assert 1 < peak <= 8
    assert [row["path"] for row in files] == [row["raw_file_path"] for row in rides]
    assert all(row["size_bytes"] == 42 for row in files)


def test_export_catalog_models_absent_and_revoked_tables():
    client = ExportClient()
    with pytest.raises(AssertionError, match="Unknown table"):
        client.table("export_requests")
    with pytest.raises(PermissionError, match="service_role"):
        client.table("canon_vault_activations")
    with pytest.raises(PermissionError, match="service_role"):
        client.table("stage1_indexer_maintenance")
    for table in ("reward_threshold_efforts", "vault_creation_handoffs", "ride_effort_completion_windows"):
        client.table(table)  # Narrow grants restored by180, without any write grant.
