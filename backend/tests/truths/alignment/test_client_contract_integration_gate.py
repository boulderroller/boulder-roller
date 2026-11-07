from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]


def read_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backend_defines_canonical_client_contract_dtos() -> None:
    contracts = read_file("backend/app/client_contracts.py")

    for symbol in [
        "class TruthSource",
        "CLIENT_CONTRACT_MODELS",
        "def client_contract_json_schema",
        "class ClimbSummary",
        "class VaultEconomy",
        "class RideAttestationStatus",
        "class RideStatusResponse",
        "class RideEarnings",
        "class SettlementStatus",
        "class RecordBoard",
        "class LocalLegendStatus",
        'CLIENT_CONTRACT_VERSION = "client.v1"',
    ]:
        assert symbol in contracts


def test_backend_routes_emit_contract_dtos_not_raw_projection_shapes_only() -> None:
    climbs = read_file("backend/app/routes/climbs.py")
    rides = read_file("backend/app/routes/rides.py")
    distributions = read_file("backend/app/routes/distributions.py")

    assert "ClimbSummary" in climbs and "VaultEconomy" in climbs
    assert "RecordBoard" in climbs and "RecordBoardEntry" in climbs
    assert "RideStatusResponse" in rides and "RideEarnings" in rides
    assert "_build_ride_status_response" in rides
    assert "SettlementStatus" in distributions
    assert 'finalized_at=ride.get("finalized_at")' in rides


def test_clients_have_types_for_canonical_contract_payloads() -> None:
    mobile_api = read_file("mobile/src/lib/api.ts")
    portal_api = read_file("web/portal/src/lib/api.ts")
    portal_ride_view = "\n".join(
        [
            read_file("web/portal/src/pages/RideView.tsx"),
            read_file("web/portal/src/pages/RideViewCore.tsx"),
        ]
    )
    scan_types = read_file("web/scan/src/types.ts")
    scan_vault_page = read_file("web/scan/src/pages/VaultPage.tsx")
    scan_account_page = read_file("web/scan/src/pages/AccountPage.tsx")
    scan_receipt = read_file("web/scan/src/pages/TransactionPage.tsx")
    mobile_post_ride = read_file("mobile/src/screens/PostRideScreen.tsx")
    mobile_post_ride_display = read_file("mobile/src/lib/postRideDisplay.ts")
    mobile_ride_detail = read_file("mobile/src/screens/RideDetailScreen.tsx")

    for source in [mobile_api, portal_api]:
        assert "export type TruthSource" in source
        assert "export interface VaultEconomy" in source
        assert "contractVersion: 'client.v1'" in source
        assert "vaultEconomy?: VaultEconomy" in source

    assert "earnings?:" in mobile_api
    assert "export interface SettlementStatus" in portal_api
    assert "export interface RideStatus" in portal_api
    assert "async getRideStatus(rideId: string" in portal_api
    assert "Promise<RideStatus>" in portal_api
    assert "useRideStatus" in portal_ride_view
    assert "Verification" in portal_ride_view
    assert "RideAttestation" in portal_ride_view
    assert "Ride Record" not in portal_ride_view
    assert "Counted CAL" in portal_ride_view
    assert "solanaExplorerUrl" in portal_ride_view
    for proof_field in [
        "rideAttestationPda?: string | null",
        "rideAttestationTxSignature?: string | null",
        "txSignature?: string | null",
    ]:
        assert proof_field in mobile_api
        assert proof_field in portal_api
    assert "vault_economy?: VaultEconomy" in scan_types
    # Previously pinned Protocol Proof panels, Ride Proofs and truth chips; ratified rooms link ledger rows to receipts.
    for label in ["Completions", "Ride attested", "Settlements", "Registration", "Climb account", "Vault account"]:
        assert label in scan_vault_page
    assert 'to={`/tx/${row.signature}`}' in scan_vault_page
    assert "recent_ride_attestations?: RideAttestationSummary[]" in scan_types
    for label in ["Completions", "Ride attested", "Settlements"]:
        assert label in scan_account_page
    assert 'to={`/tx/${r.signature}`}' in scan_account_page
    for label in ["Ride hash", "Signature", "Slot", "Program", "Accounts", "Instructions"]:
        assert label in scan_receipt
    assert "PostRideCascadePanel" in mobile_post_ride
    assert "deriveAttestationView" in mobile_ride_detail
    assert "BoulderScan" in mobile_ride_detail
    assert "Open BoulderScan" in mobile_ride_detail
    assert (
        "serverStatus?.earnings?.calEarned" in mobile_post_ride
        or "status?.earnings?.calEarned" in mobile_post_ride_display
    )
    assert "serverStatus?.earnings?.calEarned" in mobile_ride_detail


def test_mobile_upload_contract_preserves_ride_attestation_inputs() -> None:
    upload_queue = read_file("mobile/src/services/uploadQueue.ts")
    mobile_upload_tests = read_file("mobile/src/services/__tests__/uploadQueue.test.ts")
    backend_handshake_tests = read_file("backend/tests/routes/test_ride_attestation_handshake.py")
    upload_fixture = read_file("tests/fixtures/upload_init_handshake_v1.json")

    assert "preliminary_ride_hash" in upload_queue
    assert "parser_version" in upload_queue
    assert "buildUploadInitPayload" in upload_queue
    assert "upload_init_handshake_v1.json" in mobile_upload_tests
    assert "upload_init_handshake_v1.json" in backend_handshake_tests
    assert '"schema": "boulderroller.upload_init_handshake.v1"' in upload_fixture
    assert '"preliminary_ride_hash"' in upload_fixture


def test_legacy_client_aliases_stay_inside_named_compatibility_adapters() -> None:
    mobile_api = read_file("mobile/src/lib/api.ts")
    portal_api = read_file("web/portal/src/lib/api.ts")
    scan_api = read_file("web/scan/src/lib/api.ts")

    assert "Compatibility aliases for callers not yet renamed" in mobile_api
    assert "return this.getClimbs(limit, offset)" in mobile_api
    assert "return this.getClimb(id)" in mobile_api
    assert "this.request('GET', `/vaults" not in mobile_api

    assert "Canonical API targets `/climbs/*`" in portal_api
    assert "back-compat alias" in portal_api
    assert "this.get(`/climbs/list" in portal_api
    assert "this.get(`/climbs/${climbId}`)" in portal_api
    assert "payload.climbs ?? payload.segments" in portal_api

    # Previously pinned readApi's unescaped path; the ratified Climb reads the encoded canonical path without live fixture fallback.
    climb_reader = scan_api.split("export function getClimb(", 1)[1].split("export function getTransaction", 1)[0]
    assert 'const path = `/v1/climbs/${encodeURIComponent(id)}`' in climb_reader
    assert "return USE_FIXTURES ? fixtureForPath<ClimbResponse>(path) : fetchJson<ClimbResponse>(path)" in climb_reader
    assert "readApi" not in climb_reader
    assert "getVault" not in climb_reader
    assert "readApi<VaultResponse>(`/v1/vaults/${id}`)" in scan_api
    assert "const legacy = await getVault(id)" not in scan_api


def test_protocol_gate_script_covers_the_cross_surface_contract_seams() -> None:
    script = read_file("scripts/protocol-gate.sh")

    assert "test_ride_processor_client_contract_smoke.py" in script
    assert "test_client_contract_integration_gate.py" in script
    assert "test_client_surface_requirements_gate.py" in script
    assert "test_ride_hash_symmetry_gate.py" in script
    assert "src/lib/__tests__/api.test.ts" in script
    assert "src/lib/__tests__/canonicalize.test.ts" in script
    assert "src/services/__tests__/uploadQueue.test.ts" in script
    assert "npm run typecheck" in script
    assert "npm run build" in script


def test_client_contract_golden_fixtures_exist_for_cross_surface_payloads() -> None:
    fixture_dir = ROOT / "backend/tests/fixtures/client_v1"

    for fixture in [
        "climb_summary.json",
        "record_board.json",
        "ride_attestation_status.json",
        "ride_earnings.json",
        "ride_status_response.json",
        "settlement_status.json",
        "vault_economy.json",
    ]:
        payload = (fixture_dir / fixture).read_text(encoding="utf-8")
        assert '"contract_version": "client.v1"' in payload
        assert '"truth_source":' in payload


def test_ride_processor_fixture_smoke_guards_evidence_to_status_boundary() -> None:
    smoke = read_file("backend/tests/services/test_ride_processor_client_contract_smoke.py")

    assert "canonical_ride_v4_vectors.json" in smoke
    assert "upload_init" in smoke
    assert "RideProcessor" in smoke
    assert "record_ride_attestation" in smoke
    assert "credit_cal" in smoke
    assert "build_completion_plan" in smoke
    assert "ride_economic_coordinator.freeze_plan" in smoke
    assert "ride_economic_coordinator.execute" in smoke
    assert "_build_ride_status_response" in smoke
    assert "RideStatusResponse.model_validate" in smoke
    assert 'frozen_draft.reward_policy == "threshold_provisional_hold_v1"' in smoke
    assert "status_contract.climb_earnings == []" in smoke
    assert "status_contract.progression" in smoke
    assert "status_contract.climb_earnings" in smoke


def test_compatibility_alias_inventory_stays_explicit_until_retirement() -> None:
    inventory = read_file("history/CLIENT_CONTRACT_COMPAT_INVENTORY_2026-04-21.md")

    for alias in [
        "Backend `/segments/*`",
        "Backend response `segments` / `segment_id` / `segment_name`",
        "Indexer `/v1/vaults` and `/v1/vaults/:id`",
        "BoulderScan `/vault/:id`",
        "BoulderScan `getVault` / `getVaults`",
        "Mobile `getVault` / `getVaults`",
        "Portal `getVault*` economic methods",
        "Portal `/segments/:climbId`",
    ]:
        assert alias in inventory

    assert "`boulderroller-v2-ejy8` remains blocked" in inventory
    assert "Retirement Conditions" in inventory
    assert "getClimbs` / `getClimb`" in inventory
    assert "/v1/climbs/:id" in inventory


def test_irl_recording_validation_loop_exists_for_physical_truth_gates() -> None:
    loop = read_file("history/IRL_RECORDING_VALIDATION_LOOP_2026-04-21.md")

    for section in [
        "Gate A — Fresh Recording",
        "Gate B — Retry And Idempotency",
        "Gate C — Crash Recovery",
        "Gate D — Proof Surface",
        "Exit Criteria",
    ]:
        assert section in loop

    for term in [
        "parser_version",
        "preliminary_ride_hash",
        "uploading → processing → completed",
        "under_review",
        "BoulderScan",
    ]:
        assert term in loop
