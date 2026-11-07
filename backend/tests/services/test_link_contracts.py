from __future__ import annotations

from app.link_contracts import (
    LINK_CONTRACT_VERSION,
    LinkAccessStatus,
    LinkTargetType,
    build_resolved_link,
    canonical_web_path,
    link_schema,
    parse_link_target,
)


def test_parse_link_target_accepts_canonical_and_legacy_paths() -> None:
    assert parse_link_target("/rides/ride-1") == (LinkTargetType.ride, "ride-1")
    assert parse_link_target("/ride/ride-1") == (LinkTargetType.ride, "ride-1")
    assert parse_link_target("/activities/ride-1") == (LinkTargetType.ride, "ride-1")
    assert parse_link_target("https://boulderroller.app/riders/alice") == (LinkTargetType.rider, "alice")
    assert parse_link_target("/climbs/climb-1/leaderboard") == (LinkTargetType.record_board, "climb-1")
    assert parse_link_target("/scan/tx/sig-1") == (LinkTargetType.scan_tx, "sig-1")
    assert parse_link_target("/account/pubkey-1") == (LinkTargetType.scan_account, "pubkey-1")


def test_canonical_web_paths_are_plural_and_cross_client() -> None:
    assert canonical_web_path(LinkTargetType.rider, "alice") == "/riders/alice"
    assert canonical_web_path(LinkTargetType.ride, "ride-1") == "/rides/ride-1"
    assert canonical_web_path(LinkTargetType.climb, "climb-1") == "/climbs/climb-1"
    assert canonical_web_path(LinkTargetType.record_board, "climb-1") == "/climbs/climb-1/leaderboard"
    assert canonical_web_path(LinkTargetType.report, "report-1") == "/notifications?reportId=report-1"
    assert canonical_web_path(LinkTargetType.proof, "proof-1") == "/notifications?proofId=proof-1"
    assert canonical_web_path(LinkTargetType.scan_tx, "sig/1") == "/notifications?scanTx=sig%2F1"


def test_build_resolved_link_exposes_share_and_og_payloads() -> None:
    link = build_resolved_link(
        target_type=LinkTargetType.ride,
        target_id="ride-1",
        title="Morning Ride",
        description="42.0 km ride on Boulder Roller",
        status=LinkAccessStatus.resolved,
        metadata={"visibility": "public"},
    )

    assert link["contractVersion"] == LINK_CONTRACT_VERSION
    assert link["webPath"] == "/rides/ride-1"
    assert link["appUrl"] == "boulderroller://rides/ride-1"
    assert link["share"]["url"].endswith("/rides/ride-1")
    assert link["openGraph"]["title"] == "Morning Ride"
    assert link["metadata"] == {"visibility": "public"}


def test_link_schema_documents_supported_targets_and_aliases() -> None:
    schema = link_schema()

    assert schema["contractVersion"] == LINK_CONTRACT_VERSION
    ride_schema = next(target for target in schema["targets"] if target["type"] == "ride")
    assert ride_schema["webPathTemplate"] == "/rides/:rideId"
    assert "/activities/:rideId" in ride_schema["aliases"]
