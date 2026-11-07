from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.vault_reward_identity import (
    VaultRewardIdentity,
    VaultRewardIdentityAmbiguous,
    VaultRewardIdentityIncomplete,
    VaultRewardIdentityMissing,
    reconcile_indexed_vault_reward_identity,
    reconcile_vault_reward_identities,
    resolve_reward_grade_vault_identity,
)


V2_SIGNATURE_HEX = (
    "0208012901ef0258000000000000000062030000800000008000000000008000"
    "80008000000080008000800000008000e9105ad1a189212e4aaad7873984334a"
)


def _row(*, pattern_id, wallet, start_lat, start_lon, **overrides):
    row = {
        "id": pattern_id,
        "wallet": wallet,
        "signature_hex": "ab" * 64,
        "signature_v2_hex": V2_SIGNATURE_HEX,
        "start_lat": start_lat,
        "start_lon": start_lon,
        "end_lat": start_lat + 0.005,
        "end_lon": start_lon,
        "vert_m": 120.0,
        "distance_m": 2000.0,
        "avg_gradient_pct": 6.0,
        "economic_eligible": True,
    }
    row.update(overrides)
    return row


def _endpoint_match(**kwargs):
    if kwargs["query_start"] != kwargs["candidate_start"]:
        return None
    return SimpleNamespace(similarity=1.0)


def test_resolver_rejects_global_cross_wallet_v1_collision():
    rows = [
        _row(
            pattern_id="philly",
            wallet="WalletCreator",
            start_lat=39.9500,
            start_lon=-75.1600,
        ),
        _row(
            pattern_id="tucson",
            wallet="WalletElsewhere",
            start_lat=32.2200,
            start_lon=-110.9700,
        ),
    ]

    with (
        patch(
            "app.services.vault_reward_identity._load_legacy_identity_rows",
            return_value=rows,
        ),
        patch(
            "app.services.vault_reward_identity.match_reward_grade_v2",
            side_effect=_endpoint_match,
        ),
        pytest.raises(VaultRewardIdentityAmbiguous),
    ):
        resolve_reward_grade_vault_identity(
            client=MagicMock(),
            signature_hex="ab" * 64,
            required_wallet="WalletCreator",
        )


def test_resolver_requires_all_legacy_rows_to_be_pairwise_compatible():
    rows = [
        _row(
            pattern_id="middle",
            wallet="WalletCreator",
            start_lat=39.9500,
            start_lon=-75.1600,
        ),
        _row(
            pattern_id="north-edge",
            wallet="WalletElsewhereA",
            start_lat=39.9512,
            start_lon=-75.1600,
        ),
        _row(
            pattern_id="south-edge",
            wallet="WalletElsewhereB",
            start_lat=39.9488,
            start_lon=-75.1600,
        ),
    ]

    def bounded_endpoint_match(**kwargs):
        if abs(kwargs["query_start"][0] - kwargs["candidate_start"][0]) > 0.0015:
            return None
        return SimpleNamespace(similarity=1.0)

    with (
        patch(
            "app.services.vault_reward_identity._load_legacy_identity_rows",
            return_value=rows,
        ),
        patch(
            "app.services.vault_reward_identity.match_reward_grade_v2",
            side_effect=bounded_endpoint_match,
        ),
        pytest.raises(VaultRewardIdentityAmbiguous),
    ):
        resolve_reward_grade_vault_identity(
            client=MagicMock(),
            signature_hex="ab" * 64,
            required_wallet="WalletCreator",
        )


def test_resolver_rejects_incomplete_eligible_collision_evidence():
    rows = [
        _row(
            pattern_id="complete",
            wallet="WalletCreator",
            start_lat=39.9500,
            start_lon=-75.1600,
        ),
        _row(
            pattern_id="incomplete",
            wallet="WalletElsewhere",
            start_lat=39.9500,
            start_lon=-75.1600,
            signature_v2_hex=None,
        ),
    ]

    with (
        patch(
            "app.services.vault_reward_identity._load_legacy_identity_rows",
            return_value=rows,
        ),
        patch(
            "app.services.vault_reward_identity.match_reward_grade_v2",
            side_effect=_endpoint_match,
        ),
        pytest.raises(VaultRewardIdentityIncomplete, match="incomplete"),
    ):
        resolve_reward_grade_vault_identity(
            client=MagicMock(),
            signature_hex="ab" * 64,
            required_wallet="WalletCreator",
        )


def test_resolver_requires_caller_owned_source_to_be_economically_eligible():
    rows = [
        _row(
            pattern_id="creator-ineligible",
            wallet="WalletCreator",
            start_lat=39.9500,
            start_lon=-75.1600,
            economic_eligible=False,
        ),
        _row(
            pattern_id="other-eligible",
            wallet="WalletElsewhere",
            start_lat=39.9500,
            start_lon=-75.1600,
        ),
    ]

    with (
        patch(
            "app.services.vault_reward_identity._load_legacy_identity_rows",
            return_value=rows,
        ),
        patch(
            "app.services.vault_reward_identity.match_reward_grade_v2",
            side_effect=_endpoint_match,
        ),
        pytest.raises(VaultRewardIdentityMissing, match="creator"),
    ):
        resolve_reward_grade_vault_identity(
            client=MagicMock(),
            signature_hex="ab" * 64,
            required_wallet="WalletCreator",
        )


def test_resolver_rejects_null_economic_eligibility_for_creator_source():
    rows = [
        _row(
            pattern_id="creator-null-eligibility",
            wallet="WalletCreator",
            start_lat=39.9500,
            start_lon=-75.1600,
            economic_eligible=None,
        )
    ]

    with (
        patch(
            "app.services.vault_reward_identity._load_legacy_identity_rows",
            return_value=rows,
        ),
        patch(
            "app.services.vault_reward_identity.match_reward_grade_v2",
            side_effect=_endpoint_match,
        ),
        pytest.raises(VaultRewardIdentityMissing, match="creator"),
    ):
        resolve_reward_grade_vault_identity(
            client=MagicMock(),
            signature_hex="ab" * 64,
            required_wallet="WalletCreator",
        )


def test_reconciliation_persists_and_verifies_exact_v2_identity():
    identity = VaultRewardIdentity(
        pattern_id="pattern-1",
        wallet="WalletCreator",
        signature_hex="ab" * 64,
        signature_v2_hex=V2_SIGNATURE_HEX,
        start_lat=39.9500,
        start_lon=-75.1600,
        end_lat=39.9550,
        end_lon=-75.1600,
        vert_m=120.0,
        distance_m=2000.0,
        avg_gradient_pct=6.0,
        economic_eligible=True,
    )
    expected_patch = identity.as_indexed_vault_patch()

    update_query = MagicMock()
    update_query.update.return_value = update_query
    update_query.eq.return_value = update_query
    update_query.execute.return_value = SimpleNamespace(data=[])
    verify_query = MagicMock()
    verify_query.select.return_value = verify_query
    verify_query.eq.return_value = verify_query
    verify_query.limit.return_value = verify_query
    verify_query.execute.return_value = SimpleNamespace(
        data=[{"id": 7, **expected_patch}]
    )
    client = MagicMock()
    client.table.side_effect = [update_query, verify_query]
    vault = {
        "id": 7,
        "signature_hex": "ab" * 64,
        "minter": "WalletCreator",
        "signature_v2_hex": None,
    }

    with patch(
        "app.services.vault_reward_identity.resolve_reward_grade_vault_identity",
        return_value=identity,
    ) as resolve:
        result = reconcile_indexed_vault_reward_identity(
            client=client,
            vault=vault,
            apply=True,
        )

    assert result == identity
    resolve.assert_called_once_with(
        client=client,
        signature_hex="ab" * 64,
        required_wallet="WalletCreator",
    )
    update_query.update.assert_called_once_with(expected_patch)
    update_query.eq.assert_called_once_with("id", 7)


def test_batch_reconciliation_reports_unresolved_vaults_without_writing():
    query = MagicMock()
    query.select.return_value = query
    query.order.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.execute.return_value = SimpleNamespace(
        data=[
            {"id": 1, "signature_hex": "ab" * 64},
            {"id": 2, "signature_hex": "cd" * 64},
        ]
    )
    client = MagicMock()
    client.table.return_value = query
    identity = MagicMock()

    with patch(
        "app.services.vault_reward_identity.reconcile_indexed_vault_reward_identity",
        side_effect=[
            identity,
            VaultRewardIdentityAmbiguous("cross-city collision"),
        ],
    ) as reconcile:
        report = reconcile_vault_reward_identities(
            client=client,
            apply=False,
        )

    assert report.scanned == 2
    assert report.resolved == 1
    assert report.updated == 0
    assert report.failures == [
        {
            "vault_id": 2,
            "error_type": "VaultRewardIdentityAmbiguous",
            "error": "cross-city collision",
        }
    ]
    assert reconcile.call_count == 2
    assert all(call.kwargs["apply"] is False for call in reconcile.call_args_list)
