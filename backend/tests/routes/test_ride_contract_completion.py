"""Ride data contract completion (boulderroller-v2-71o2v).

Covers the truthful per-climb CAL itemization, real vault-match facts on the
patterns surface, the climb-earning pattern join key, and avg HR exposure.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

from app.routes.rides import (
    _fetch_pattern_vault_matches,
    _fetch_ride_cal_itemization,
    _fetch_ride_climb_earnings,
    _fetch_ride_economic_steps,
    _fetch_terminal_threshold_release_authority,
    _to_ride_record,
)


def _fake_repo(table_data: dict) -> MagicMock:
    repo = MagicMock()
    # Production clients expose the joined lifecycle RPC. This table-backed
    # fake deliberately exercises the compatibility path.
    repo.client.rpc = None

    def table(name: str):
        query = MagicMock()
        query.select.return_value = query
        query.eq.return_value = query
        query.in_.return_value = query
        query.order.return_value = query
        query.limit.return_value = query
        query.execute.return_value.data = table_data.get(name, [])
        return query

    repo.client.table.side_effect = table
    return repo


def _plan_tables(ride_id: str) -> dict:
    return {
        "ride_economic_plans": [
            {
                "ride_id": ride_id,
                "state": "complete",
                "policy_version": "ride_econ_v2",
                # Historical v1 fixture preserved forward-only.
                "exact_cal_base_units": 123450000000,
                "exact_tribute_base_units": 12345000000,
                "exact_tribute_budget_base_units": 12345000000,
                "tribute_policy_version": "cal_tribute_segment_np_fixed_10pct_v1",
            }
        ],
        "ride_economic_completion_steps": [
            {
                "step_index": 0,
                "pattern_id": "11111111-1111-1111-1111-111111111111",
                "vault_id": 16,
                "vault_signature": "sig-16",
                "completion_time_s": 512,
                "exact_tribute_base_units": 8000000000,
                "intensity_bps": 9100,
                "state": "projected",
            },
            {
                "step_index": 1,
                "pattern_id": "22222222-2222-2222-2222-222222222222",
                "vault_id": 21,
                "vault_signature": "sig-21",
                "completion_time_s": 231,
                "exact_tribute_base_units": 4345000000,
                "intensity_bps": 8800,
                "state": "projected",
            },
        ],
        "indexed_vaults": [
            {"id": 16, "name": "Manayunk Wall"},
            {"id": 21, "name": "Strawberry Hill"},
        ],
    }


def _terminal_threshold_release_tables(ride_id: str) -> dict:
    """A completed V3 child release over an immutable zero V2 parent."""
    tables = _plan_tables(ride_id)
    tables["ride_economic_plans"][0].update(
        exact_cal_base_units=0,
        exact_tribute_base_units=0,
        exact_tribute_budget_base_units=None,
        tribute_policy_version=None,
        reward_policy="threshold_provisional_hold_v1",
    )
    for step in tables["ride_economic_completion_steps"]:
        step["exact_tribute_base_units"] = 0

    snapshot_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    release_pattern_id = "66666666-6666-6666-6666-666666666666"
    tables["reward_threshold_release_snapshots"] = [
        {
            "id": snapshot_id,
            "ride_id": ride_id,
            "exact_cal_base_units": 222000000000,
            "exact_tribute_budget_base_units": 22200000000,
            "snapshot_evidence": {
                "domain": "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1"
            },
        }
    ]
    tables["reward_threshold_release_executions"] = [
        {
            "snapshot_id": snapshot_id,
            "state": "complete",
            "terminal_projected_at": "2026-08-18T14:03:00+00:00",
        }
    ]
    tables["reward_threshold_release_steps"] = [
        {
            "snapshot_id": snapshot_id,
            "step_index": 0,
            "pattern_id": release_pattern_id,
            "vault_id": 61,
            "vault_signature": "sig-61",
            "completion_time_s": 411,
            "exact_tribute_base_units": 15000000000,
            "intensity_bps": 9300,
            "completion_evidence_version": 3,
            "expected_receipt_pda": "ReleaseCompletionPda61",
            "completion_evidence_hash": "\\x" + "cd" * 32,
            "state": "projected",
            "chain_confirmed_at": "2026-08-18T14:01:00+00:00",
            "projected_at": "2026-08-18T14:02:00+00:00",
        }
    ]
    tables["indexed_vaults"] = [
        {
            "id": 61,
            "name": "Release Wall",
            "signature_hex": "sig-61",
            "kom_holder": "kom-wallet",
            "kom_time_s": 390,
            "canon_climb_id": "77777777-7777-7777-7777-777777777777",
        }
    ]
    return tables


def test_ordinary_derived_ride_skips_threshold_release_rpc() -> None:
    repo = _fake_repo({})
    rpc_calls = []

    def rpc(name: str, params: dict):
        rpc_calls.append((name, params))
        raise AssertionError("ordinary derived rides must not query release authority")

    repo.client.rpc = rpc
    ride_id = str(uuid4())

    assert _fetch_terminal_threshold_release_authority(
        repo,
        ride_id,
        {"reward_ftp_source": "derived_eftp"},
    ) == ("absent", None, [])
    assert rpc_calls == []


def test_ride_detail_consumers_share_one_release_lifecycle_read() -> None:
    ride_id = str(uuid4())
    tables = _terminal_threshold_release_tables(ride_id)
    repo = _fake_repo(tables)
    snapshot = tables["reward_threshold_release_snapshots"][0]
    steps = tables["reward_threshold_release_steps"]
    payload = {
        "status": "released",
        "ride_id": ride_id,
        "snapshot": snapshot,
        "execution_state": "complete",
        "terminal_projected_at": "2026-08-18T14:03:00+00:00",
        "steps": steps,
    }
    rpc_calls = []

    class Response:
        data = payload

    class Builder:
        def execute(self):
            return Response()

    def rpc(name: str, params: dict):
        rpc_calls.append((name, params))
        return Builder()

    repo.client.rpc = rpc
    ride = {
        "processing_status": "completed",
        "reward_ftp_source": "network_default",
        "wallet": "wallet-1",
    }

    resolution = _fetch_terminal_threshold_release_authority(repo, ride_id, ride)
    assert resolution[0] == "released"
    assert _fetch_ride_economic_steps(repo, ride_id, ride, resolution) == steps
    assert _fetch_ride_cal_itemization(repo, ride_id, ride, resolution) is not None
    _fetch_ride_climb_earnings(repo, ride_id, ride, resolution)
    assert rpc_calls == [
        (
            "resolve_reward_threshold_release_lifecycle",
            {"p_ride_id": ride_id},
        )
    ]


def test_ride_record_exposes_truthful_threshold_release_lifecycle() -> None:
    record = _to_ride_record(
        {
            "id": str(uuid4()),
            "user_id": str(uuid4()),
            "started_at": "2026-08-29T12:00:00+00:00",
            "processing_status": "completed",
            "_threshold_release_status": "under_review",
        }
    )

    assert record.model_dump(by_alias=True)["thresholdReleaseStatus"] == (
        "under_review"
    )


class TestRideCalItemization:
    def test_itemization_sums_exactly_to_ride_total(self) -> None:
        ride_id = str(uuid4())
        repo = _fake_repo(_plan_tables(ride_id))

        itemization = _fetch_ride_cal_itemization(
            repo, ride_id, {"processing_status": "completed"}
        )

        assert itemization is not None
        total = int(itemization.ride_cal_base_units)
        parts = sum(int(c.cal_tribute_base_units) for c in itemization.climbs)
        remainder = int(itemization.everything_between_base_units)
        assert parts + remainder == total
        assert total == 123450000000
        assert remainder == 111105000000
        assert itemization.tribute_budget_base_units == "12345000000"
        assert itemization.basis == "vault_tribute_flow"
        assert (
            itemization.tribute_policy_version
            == "cal_tribute_segment_np_fixed_10pct_v1"
        )
        names = {c.vault_id: c.climb_name for c in itemization.climbs}
        assert names == {16: "Manayunk Wall", 21: "Strawberry Hill"}
        # Join key for clients: the frozen pattern id.
        assert itemization.climbs[0].pattern_id == (
            "11111111-1111-1111-1111-111111111111"
        )

    def test_itemization_absent_until_ride_completed(self) -> None:
        ride_id = str(uuid4())
        repo = _fake_repo(_plan_tables(ride_id))
        assert (
            _fetch_ride_cal_itemization(
                repo, ride_id, {"processing_status": "enriched"}
            )
            is None
        )

    def test_itemization_absent_without_complete_plan(self) -> None:
        ride_id = str(uuid4())
        tables = _plan_tables(ride_id)
        tables["ride_economic_plans"][0]["state"] = "planned"
        repo = _fake_repo(tables)
        assert (
            _fetch_ride_cal_itemization(
                repo, ride_id, {"processing_status": "completed"}
            )
            is None
        )

    def test_itemization_absent_for_legacy_ride_without_plan(self) -> None:
        ride_id = str(uuid4())
        repo = _fake_repo({})
        assert (
            _fetch_ride_cal_itemization(
                repo, ride_id, {"processing_status": "completed"}
            )
            is None
        )

    def test_itemization_withheld_on_step_total_mismatch(self) -> None:
        """A plan whose stored tribute total disagrees with its steps is a
        data-integrity failure; the route withholds rather than inventing."""
        ride_id = str(uuid4())
        tables = _plan_tables(ride_id)
        tables["ride_economic_plans"][0]["exact_tribute_base_units"] = 999
        repo = _fake_repo(tables)
        assert (
            _fetch_ride_cal_itemization(
                repo, ride_id, {"processing_status": "completed"}
            )
            is None
        )

    def test_zero_tribute_ride_attributes_everything_between(self) -> None:
        """No eligible matched vault -> zero tribute; the whole ride total is
        'everything between' and the invariant still holds."""
        ride_id = str(uuid4())
        tables = _plan_tables(ride_id)
        tables["ride_economic_plans"][0]["exact_tribute_base_units"] = 0
        for step in tables["ride_economic_completion_steps"]:
            step["exact_tribute_base_units"] = 0
        repo = _fake_repo(tables)

        itemization = _fetch_ride_cal_itemization(
            repo, ride_id, {"processing_status": "completed"}
        )

        assert itemization is not None
        assert all(c.cal_tribute_base_units == "0" for c in itemization.climbs)
        assert (
            itemization.everything_between_base_units
            == itemization.ride_cal_base_units
        )

    def test_ride_record_serializes_itemization_camel_case(self) -> None:
        ride_id = str(uuid4())
        repo = _fake_repo(_plan_tables(ride_id))
        itemization = _fetch_ride_cal_itemization(
            repo, ride_id, {"processing_status": "completed"}
        )
        record = _to_ride_record(
            {
                "id": str(uuid4()),
                "user_id": str(uuid4()),
                "started_at": "2026-08-01T12:00:00+00:00",
                "processing_status": "completed",
                "kcals": 900,
                "avg_hr_bpm": 148,
            },
            cal_itemization=itemization,
        )
        payload = record.model_dump(by_alias=True, mode="json")
        assert payload["avgHrBpm"] == 148.0
        block = payload["calItemization"]
        assert block["rideCalBaseUnits"] == "123450000000"
        assert block["everythingBetweenBaseUnits"] == "111105000000"
        assert block["climbs"][0]["calTributeBaseUnits"] == "8000000000"
        assert block["climbs"][0]["patternId"] == (
            "11111111-1111-1111-1111-111111111111"
        )

    def test_ride_record_avg_hr_absent_stays_null(self) -> None:
        record = _to_ride_record(
            {
                "id": str(uuid4()),
                "user_id": str(uuid4()),
                "started_at": "2026-08-01T12:00:00+00:00",
                "processing_status": "completed",
                "kcals": 900,
            }
        )
        payload = record.model_dump(by_alias=True, mode="json")
        assert payload["avgHrBpm"] is None
        assert payload["calItemization"] is None

    def test_terminal_threshold_release_replaces_zero_parent_itemization(self) -> None:
        ride_id = str(uuid4())
        repo = _fake_repo(_terminal_threshold_release_tables(ride_id))

        itemization = _fetch_ride_cal_itemization(
            repo, ride_id, {"processing_status": "completed"}
        )

        assert itemization is not None
        assert itemization.ride_cal_base_units == "222000000000"
        assert itemization.tribute_budget_base_units == "22200000000"
        assert itemization.everything_between_base_units == "207000000000"
        assert (
            itemization.tribute_policy_version
            == "cal_tribute_segment_np_fixed_10pct_v1"
        )
        assert len(itemization.climbs) == 1
        assert itemization.climbs[0].pattern_id == (
            "66666666-6666-6666-6666-666666666666"
        )
        assert itemization.climbs[0].vault_id == 61

    def test_measured_threshold_release_reports_the_v2_policy(self) -> None:
        ride_id = str(uuid4())
        tables = _terminal_threshold_release_tables(ride_id)
        snapshot = tables["reward_threshold_release_snapshots"][0]
        snapshot["exact_tribute_budget_base_units"] = 15000000000
        snapshot["snapshot_evidence"] = {
            "domain": "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2"
        }

        itemization = _fetch_ride_cal_itemization(
            _fake_repo(tables), ride_id, {"processing_status": "completed"}
        )

        assert itemization is not None
        assert itemization.tribute_policy_version == "cal_tribute_segment_tss_v2"

    def test_malformed_terminal_threshold_release_is_withheld(self) -> None:
        ride_id = str(uuid4())
        tables = _terminal_threshold_release_tables(ride_id)
        tables["reward_threshold_release_executions"][0]["terminal_projected_at"] = None
        repo = _fake_repo(tables)

        assert (
            _fetch_ride_cal_itemization(
                repo, ride_id, {"processing_status": "completed"}
            )
            is None
        )

    def test_pending_threshold_release_keeps_zero_parent_authoritative(self) -> None:
        ride_id = str(uuid4())
        tables = _terminal_threshold_release_tables(ride_id)
        tables["reward_threshold_release_executions"][0].update(
            state="cal_confirmed",
            terminal_projected_at=None,
        )
        repo = _fake_repo(tables)

        itemization = _fetch_ride_cal_itemization(
            repo, ride_id, {"processing_status": "completed"}
        )

        assert itemization is not None
        assert itemization.ride_cal_base_units == "0"
        assert all(climb.cal_tribute_base_units == "0" for climb in itemization.climbs)


def _vault_match_tables(ride_id: str) -> dict:
    tables = _plan_tables(ride_id)
    tables["vault_completions"] = [
        {
            "vault_signature": "sig-16",
            "wallet": "wallet-1",
            "activity_id": ride_id,
            "time_seconds": 512,
            "is_pr": True,
            "chain_confirmation_status": "confirmed",
            "on_chain_tx": None,
            "completion_receipt_pda": "CompletionPda111",
            "completion_evidence_hash": "\\x" + "ab" * 32,
            "chain_confirmed_at": "2026-08-01T13:01:00+00:00",
        },
        {
            # Not chain-confirmed: must never produce a vaultMatch.
            "vault_signature": "sig-21",
            "wallet": "wallet-1",
            "activity_id": ride_id,
            "time_seconds": 231,
            "is_pr": False,
            "chain_confirmation_status": "pending",
            "on_chain_tx": None,
            "completion_receipt_pda": None,
            "completion_evidence_hash": None,
            "chain_confirmed_at": None,
        },
    ]
    tables["indexed_vaults"] = [
        {
            "id": 16,
            "name": "Manayunk Wall",
            "signature_hex": "sig-16",
            "kom_holder": "kom-wallet",
            "kom_time_s": 455,
            "canon_climb_id": "33333333-3333-3333-3333-333333333333",
        },
        {
            "id": 21,
            "name": "Strawberry Hill",
            "signature_hex": "sig-21",
            "kom_holder": None,
            "kom_time_s": 0,
            "canon_climb_id": None,
        },
    ]
    tables["indexed_leaderboards"] = [
        {
            "vault_id": 16,
            "entries": [
                {"user": "wallet-3", "time_s": 470, "recorded_at": 1776600300},
                {"user": "wallet-1", "time_s": 498, "recorded_at": 1776600200},
                {"user": "kom-wallet", "time_s": 455, "recorded_at": 1776600100},
            ],
        },
    ]
    tables["indexed_completions"] = [
        {"vault_id": 16, "best_time_s": 498},
    ]
    return tables


class TestPatternVaultMatches:
    def test_emits_real_completion_facts_keyed_by_pattern(self) -> None:
        ride_id = str(uuid4())
        repo = _fake_repo(_vault_match_tables(ride_id))

        matches = _fetch_pattern_vault_matches(repo, ride_id, {"wallet": "wallet-1"})

        assert set(matches) == {"11111111-1111-1111-1111-111111111111"}
        match = matches["11111111-1111-1111-1111-111111111111"]
        assert match == {
            "id": "16",
            "vaultId": 16,
            "vaultClimbId": "33333333-3333-3333-3333-333333333333",
            "name": "Manayunk Wall",
            "yourTime": 512,
            "isPR": True,
            "yourBestTime": 498,
            "yourRank": 3,
            "komTime": 455,
            "komHolder": "kom-wallet",
        }

    def test_rank_comes_from_the_chain_indexed_board_not_the_legacy_cache(self) -> None:
        ride_id = str(uuid4())
        tables = _vault_match_tables(ride_id)
        tables["vault_leaderboards"] = [{"vault_signature": "sig-16", "rank": 1}]
        tables["indexed_leaderboards"] = []
        repo = _fake_repo(tables)

        matches = _fetch_pattern_vault_matches(repo, ride_id, {"wallet": "wallet-1"})

        assert matches["11111111-1111-1111-1111-111111111111"]["yourRank"] is None

    def test_no_matches_without_authoritative_completion(self) -> None:
        ride_id = str(uuid4())
        tables = _vault_match_tables(ride_id)
        for row in tables["vault_completions"]:
            row["chain_confirmation_status"] = "pending"
        repo = _fake_repo(tables)
        assert _fetch_pattern_vault_matches(repo, ride_id, {"wallet": "wallet-1"}) == {}

    def test_no_matches_for_ride_without_plan_steps(self) -> None:
        ride_id = str(uuid4())
        repo = _fake_repo({})
        assert _fetch_pattern_vault_matches(repo, ride_id, {"wallet": "wallet-1"}) == {}

    def test_terminal_threshold_release_uses_v3_pattern_vault_binding(self) -> None:
        ride_id = str(uuid4())
        tables = _terminal_threshold_release_tables(ride_id)
        tables["vault_completions"] = [
            {
                "vault_signature": "sig-61",
                "wallet": "wallet-1",
                "activity_id": ride_id,
                "time_seconds": 411,
                "is_pr": True,
                "chain_confirmation_status": "confirmed",
                "on_chain_tx": "release-completion-tx",
                "completion_receipt_pda": "ReleaseCompletionPda61",
                "completion_evidence_hash": "\\x" + "cd" * 32,
                "completion_evidence_version": 3,
                "chain_confirmed_at": "2026-08-18T14:01:00+00:00",
            }
        ]
        tables["indexed_leaderboards"] = [
            {
                "vault_id": 61,
                "entries": [
                    {"user": "wallet-1", "time_s": 402, "recorded_at": 1776600200},
                    {"user": "wallet-9", "time_s": 390, "recorded_at": 1776600100},
                ],
            },
        ]
        tables["indexed_completions"] = [
            {"vault_id": 61, "best_time_s": 402},
        ]
        repo = _fake_repo(tables)

        matches = _fetch_pattern_vault_matches(repo, ride_id, {"wallet": "wallet-1"})

        assert set(matches) == {"66666666-6666-6666-6666-666666666666"}
        assert matches["66666666-6666-6666-6666-666666666666"]["vaultId"] == 61


class TestClimbEarningPatternJoin:
    def test_climb_earning_carries_frozen_pattern_id(self) -> None:
        ride_id = str(uuid4())
        tables = _vault_match_tables(ride_id)
        tables["vault_completions"] = [
            {
                "vault_signature": "sig-16",
                "wallet": "wallet-1",
                "activity_id": ride_id,
                "time_seconds": 512,
                "best_time_seconds": 498,
                "is_pr": True,
                "completed_at": "2026-08-01T13:00:00+00:00",
                "on_chain_tx": "tx-1",
                "cal_tribute": 8000000000,
                "chain_confirmation_status": "confirmed",
                "completion_receipt_pda": "CompletionPda111",
                "completion_evidence_hash": "\\x" + "ab" * 32,
                "completion_evidence_version": 2,
                "chain_confirmed_at": "2026-08-01T13:01:00+00:00",
            }
        ]
        repo = _fake_repo(tables)

        earnings = _fetch_ride_climb_earnings(repo, ride_id, {"wallet": "wallet-1"})

        assert len(earnings) == 1
        assert earnings[0].pattern_id == "11111111-1111-1111-1111-111111111111"

    def test_terminal_threshold_release_uses_v3_pattern_join(self) -> None:
        ride_id = str(uuid4())
        tables = _terminal_threshold_release_tables(ride_id)
        tables["vault_completions"] = [
            {
                "vault_signature": "sig-61",
                "wallet": "wallet-1",
                "activity_id": ride_id,
                "time_seconds": 411,
                "best_time_seconds": 402,
                "is_pr": True,
                "completed_at": "2026-08-18T14:00:00+00:00",
                "on_chain_tx": "release-completion-tx",
                "cal_tribute": 15000000000,
                "chain_confirmation_status": "confirmed",
                "completion_receipt_pda": "ReleaseCompletionPda61",
                "completion_evidence_hash": "\\x" + "cd" * 32,
                "completion_evidence_version": 3,
                "chain_confirmed_at": "2026-08-18T14:01:00+00:00",
            }
        ]
        repo = _fake_repo(tables)

        earnings = _fetch_ride_climb_earnings(repo, ride_id, {"wallet": "wallet-1"})

        assert len(earnings) == 1
        assert earnings[0].pattern_id == "66666666-6666-6666-6666-666666666666"
        assert earnings[0].vault_id == 61
        assert earnings[0].completion_evidence_version == 3

    def test_malformed_terminal_threshold_release_withholds_climb_earnings(self) -> None:
        ride_id = str(uuid4())
        tables = _terminal_threshold_release_tables(ride_id)
        tables["reward_threshold_release_steps"][0]["state"] = "confirmed"
        tables["vault_completions"] = [
            {
                "vault_signature": "sig-61",
                "wallet": "wallet-1",
                "activity_id": ride_id,
                "time_seconds": 411,
                "completed_at": "2026-08-18T14:00:00+00:00",
                "on_chain_tx": "release-completion-tx",
                "cal_tribute": 15000000000,
                "chain_confirmation_status": "confirmed",
                "completion_receipt_pda": "ReleaseCompletionPda61",
                "completion_evidence_hash": "\\x" + "cd" * 32,
                "completion_evidence_version": 3,
                "chain_confirmed_at": "2026-08-18T14:01:00+00:00",
            }
        ]
        repo = _fake_repo(tables)

        assert _fetch_ride_climb_earnings(repo, ride_id, {"wallet": "wallet-1"}) == []
