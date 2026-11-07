from __future__ import annotations

from app.link_contracts import LinkTargetType
from app.search_contracts import (
    SEARCH_CONTRACT_VERSION,
    SearchResultType,
    SearchType,
    build_search_response,
    build_search_result,
    classify_protocol_search,
    normalize_search_query,
    search_schema,
)


def test_normalize_search_query_compacts_whitespace() -> None:
    assert normalize_search_query("  Saw   Mill   Rd  ") == "Saw Mill Rd"


def test_protocol_classifier_routes_scan_inputs() -> None:
    signature = "3KMUV89vL7A4jtH9Azi5X2B8QftzrVTbF3r8RL4zkDqz3bUxn9r3b1n4pY2Wm8Lh"
    account = "Gk4mA2yq8wtN2P2gS9f6q4b1nJ7tW3eK5vH9cLmR1Zq"

    assert classify_protocol_search(signature) == (LinkTargetType.scan_tx, signature)
    assert classify_protocol_search(f"account:{account}") == (LinkTargetType.scan_account, account)
    assert classify_protocol_search(f"/proof/{signature}") == (LinkTargetType.proof, signature)
    assert classify_protocol_search("@tim") is None


def test_build_search_result_uses_link_targets_and_camel_contract() -> None:
    result = build_search_result(
        result_id="climb:142",
        result_type=SearchResultType.climb,
        title="Manayunk Wall",
        subtitle="Climb · Philadelphia",
        target_type=LinkTargetType.climb,
        target_id="142",
        stats=[{"label": "Grade", "value": "8.9%"}],
        matched_fields=["name"],
        scan_state="recorded",
    )

    assert result["contractVersion"] == SEARCH_CONTRACT_VERSION
    assert result["target"]["contractVersion"] == "target_action.v1"
    assert result["target"]["type"] == "climb"
    assert result["target"]["id"] == "142"
    assert result["webPath"] == "/climbs/142"
    assert result["stats"] == [{"label": "Grade", "value": "8.9%"}]
    assert result["matchedFields"] == ["name"]
    assert result["scanState"] == "recorded"


def test_build_search_response_limits_and_reports_more() -> None:
    response = build_search_response(
        query="ride",
        search_type=SearchType.all,
        results=[
            build_search_result(
                result_id=f"ride:{index}",
                result_type=SearchResultType.ride,
                title=f"Ride {index}",
                subtitle="Ride",
                target_type=LinkTargetType.ride,
                target_id=str(index),
            )
            for index in range(3)
        ],
        limit=2,
    )

    assert response["contractVersion"] == SEARCH_CONTRACT_VERSION
    assert response["normalizedQuery"] == "ride"
    assert response["hasMore"] is True
    assert [result["id"] for result in response["results"]] == ["ride:0", "ride:1"]


def test_search_schema_documents_cross_client_targets() -> None:
    schema = search_schema()

    assert schema["contractVersion"] == SEARCH_CONTRACT_VERSION
    assert "riders" in schema["types"]
    assert "ride" in schema["targets"]
    assert schema["targetContractVersion"] == "link.v1"
