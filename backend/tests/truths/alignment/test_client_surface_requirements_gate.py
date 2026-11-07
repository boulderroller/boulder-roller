from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
FIXTURE = ROOT / "backend/tests/fixtures/client_v1/surface_requirements.json"


def read_file(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load_requirements() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_surface_requirements_fixture_draws_the_design_boundary() -> None:
    requirements = load_requirements()

    assert requirements["schema"] == "boulderroller.client_surface_requirements.v1"
    assert requirements["contract_version"] == "client.v1"
    assert requirements["design_boundary"] == "functional_requirements_only"
    assert "Ride" in requirements["copy_boundary"]["normal_rider_surfaces_prefer"]
    assert "Status" in requirements["copy_boundary"]["normal_rider_surfaces_prefer"]
    assert "Verification" in requirements["copy_boundary"]["normal_rider_surfaces_prefer"]
    assert "RideAttestation" in requirements["copy_boundary"]["technical_witness_surfaces_may_use"]

    surface_ids = {surface["id"] for surface in requirements["surfaces"]}
    assert surface_ids == {
        "mobile.record",
        "mobile.post_ride",
        "mobile.ride_detail",
        "mobile.climbs",
        "portal.ride_view",
        "portal.climb_view",
        "portal.vault_view",
        "scan.climb_witness",
    }


def test_mobile_portal_scan_surfaces_expose_required_truth_fields() -> None:
    requirements = load_requirements()

    # Previously pinned Protocol Proof/proof-chain/Proof Material/Settlement Events; the ratified witness uses completion, registration and settlement rows.
    # Climb records and Local Legend live in composed room components. Week
    # remains required on Ride Verification and the Vault DUNG-history panel,
    # where settlement time is meaningful, rather than the all-time board.
    for surface in requirements["surfaces"]:
        combined_source = "\n".join(read_file(path) for path in surface["files"])
        for required in surface["requires"]:
            assert required in combined_source, f"{surface['id']} missing {required!r}"


def test_normal_rider_surfaces_do_not_lead_with_protocol_jargon() -> None:
    normal_surfaces = [
        ["mobile/src/screens/PostRideScreen.tsx"],
        ["mobile/src/screens/RideDetailScreen.tsx"],
        ["mobile/src/components/RideReviewBanner.tsx"],
        ["web/portal/src/pages/RideView.tsx", "web/portal/src/pages/RideViewCore.tsx"],
    ]

    for paths in normal_surfaces:
        source = "\n".join(read_file(path) for path in paths)
        assert "Attestation:" not in source
        assert "RideAttestation PDA" not in source
        assert "Ride Record" not in source
        assert (
            "Proof state" in source
            or "Proof pending" in source
            or "Verified on-chain" in source
            or "Verification" in source
        )


def test_boulderscan_remains_the_technical_witness_surface() -> None:
    scan_page = read_file("web/scan/src/pages/VaultPage.tsx")

    # Previously pinned proof panels; the ratified witness keeps signature and account doors on ledger rows.
    for label in ["Completions", "Ride attested", "Registration", "Climb account", "Vault account", "Leaderboard", "Settlements", "Local Legend"]:
        assert label in scan_page
    assert 'to={`/tx/${row.signature}`}' in scan_page
    assert 'to={`/tx/${registration.signature}`}' in scan_page
    assert 'to={`/account/${registration.climb_account}`}' in scan_page
    assert 'to={`/account/${registration.vault_account}`}' in scan_page
