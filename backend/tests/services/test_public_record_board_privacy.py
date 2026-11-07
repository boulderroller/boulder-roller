from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from app.services.public_record_board_privacy import (
    PublicRecordBoardPrivacyUnavailable,
    project_public_record_board,
    route_span_is_public,
)


class _Query:
    def __init__(self, rows: list[dict[str, Any]], *, fail: bool = False) -> None:
        self._rows = [dict(row) for row in rows]
        self._fail = fail

    def select(self, _columns: str) -> "_Query":
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self._rows = [
            row for row in self._rows if str(row.get(column)) == str(value)
        ]
        return self

    def in_(self, column: str, values: list[Any]) -> "_Query":
        allowed = {str(value) for value in values}
        self._rows = [
            row for row in self._rows if str(row.get(column)) in allowed
        ]
        return self

    def execute(self) -> SimpleNamespace:
        if self._fail:
            raise RuntimeError("privacy storage unavailable")
        return SimpleNamespace(data=self._rows)


class _Client:
    def __init__(
        self,
        tables: dict[str, list[dict[str, Any]]],
        *,
        fail_table: str | None = None,
    ) -> None:
        self._tables = tables
        self._fail_table = fail_table

    def from_(self, table: str) -> _Query:
        return _Query(
            self._tables.get(table, []),
            fail=table == self._fail_table,
        )


def _route() -> list[dict[str, Any]]:
    return [
        {
            "latitude": 40.0000,
            "longitude": -75.0000,
            "timestamp": 0,
            "distance_m": 0,
        },
        {
            "latitude": 40.0030,
            "longitude": -75.0000,
            "timestamp": 60,
            "distance_m": 333,
        },
        {
            "latitude": 40.0060,
            "longitude": -75.0000,
            "timestamp": 120,
            "distance_m": 666,
        },
        {
            "latitude": 40.0090,
            "longitude": -75.0000,
            "timestamp": 180,
            "distance_m": 999,
        },
    ]


def _tables() -> dict[str, list[dict[str, Any]]]:
    return {
        "ride_economic_completion_steps": [
            {
                "ride_id": "ride-1",
                "vault_id": 44,
                "completion_time_s": 60,
                "completed_at": "1970-01-01T00:16:40+00:00",
                "expected_receipt_pda": "receipt-1",
                "completion_evidence_hash": "\\x01",
                "completion_evidence_version": 2,
                "state": "projected",
                "actual_tx_signature": "tx-1",
                "chain_confirmed_at": "2026-08-02T12:00:00Z",
                "segment_start_offset_s": 60,
                "segment_end_offset_s": 120,
            },
            {
                "ride_id": "ride-2",
                "vault_id": 44,
                "completion_time_s": 70,
                "completed_at": "1970-01-01T00:33:20+00:00",
                "expected_receipt_pda": "receipt-2",
                "completion_evidence_hash": "\\x02",
                "completion_evidence_version": 2,
                "state": "projected",
                "actual_tx_signature": "tx-2",
                "chain_confirmed_at": "2026-08-02T12:00:00Z",
                "segment_start_offset_s": 60,
                "segment_end_offset_s": 130,
            },
        ],
        "ride_economic_plans": [
            {
                "ride_id": "ride-1",
                "user_id": "user-1",
                "wallet": "wallet-1",
                "expected_attestation_pda": "attestation-1",
                "state": "complete",
            },
            {
                "ride_id": "ride-2",
                "user_id": "user-2",
                "wallet": "wallet-2",
                "expected_attestation_pda": "attestation-2",
                "state": "complete",
            },
        ],
        "indexed_climb_completion_receipts": [
            {
                "pda": "receipt-1",
                "ride_attestation_pda": "attestation-1",
                "vault_pda": "vault-pda",
                "completion_evidence_hash": "\\x01",
                "completion_evidence_version": 2,
            },
            {
                "pda": "receipt-2",
                "ride_attestation_pda": "attestation-2",
                "vault_pda": "vault-pda",
                "completion_evidence_hash": "\\x02",
                "completion_evidence_version": 2,
            },
        ],
        "rides": [
            {
                "id": "ride-1",
                "user_id": "user-1",
                "visibility": "public",
                "map_visibility": "show_all",
                "map_hide_start_m": 0,
                "map_hide_end_m": 0,
                "hide_from_leaderboards": False,
                "moderation_state": "visible",
                "ride_attestation_pda": "attestation-1",
                "gps_track": _route(),
            },
            {
                "id": "ride-2",
                "user_id": "user-2",
                "visibility": "public",
                "map_visibility": "show_all",
                "map_hide_start_m": 0,
                "map_hide_end_m": 0,
                "hide_from_leaderboards": False,
                "moderation_state": "visible",
                "ride_attestation_pda": "attestation-2",
                "gps_track": _route(),
            },
        ],
        "users": [
            {
                "id": "user-1",
                "wallet": "wallet-1",
                "is_public": True,
                "moderation_state": "visible",
            },
            {
                "id": "user-2",
                "wallet": "wallet-2",
                "is_public": True,
                "moderation_state": "visible",
            },
        ],
        "privacy_zones": [],
    }


def _raw_entries() -> list[dict[str, Any]]:
    return [
        {"user": "wallet-1", "time_s": 60, "recorded_at": 1000},
        {"user": "wallet-2", "time_s": 70, "recorded_at": 2000},
    ]


def _vault() -> dict[str, Any]:
    return {
        "id": 44,
        "pda": "vault-pda",
        "kom_holder": "wallet-1",
        "kom_time_s": 60,
    }


def _replace_first_ride_with_released_v3(
    tables: dict[str, list[dict[str, Any]]],
) -> None:
    tables["ride_economic_completion_steps"] = [
        step
        for step in tables["ride_economic_completion_steps"]
        if step["ride_id"] != "ride-1"
    ]
    tables["indexed_climb_completion_receipts"][0].update({
        "completion_evidence_version": 3,
        "release_authority_pda": "release-authority-1",
    })
    released_step = {
        "snapshot_id": "release-snapshot-1",
        "step_index": 0,
        "pattern_id": "pattern-1",
        "vault_id": 44,
        "vault_signature": "vault-signature-1",
        "completion_time_s": 60,
        "completed_at": "1970-01-01T00:16:40+00:00",
        "exact_tribute_base_units": 100,
        "completion_evidence_version": 3,
        "completion_evidence_hash": "\\x01",
        "expected_receipt_pda": "receipt-1",
        "state": "projected",
        "actual_tx_signature": "release-tx-1",
        "chain_confirmed_at": "2026-08-02T12:00:00Z",
    }
    tables["reward_threshold_release_steps"] = [released_step]
    tables["reward_threshold_release_snapshots"] = [
        {
            "id": "release-snapshot-1",
            "ride_id": "ride-1",
            "user_id": "user-1",
            "snapshot_evidence": {
                "domain": "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1",
                "plan": {
                    "ride_id": "ride-1",
                    "user_id": "user-1",
                    "wallet": "wallet-1",
                    "expected_release_authority_pda": "release-authority-1",
                },
                "steps": [
                    {
                        **released_step,
                        "completion_evidence_hash_hex": "01",
                        "segment_start_offset_s": 60,
                        "segment_end_offset_s": 120,
                    }
                ],
            },
        }
    ]
    tables["reward_threshold_release_executions"] = [
        {
            "snapshot_id": "release-snapshot-1",
            "wallet": "wallet-1",
            "expected_release_authority_pda": "release-authority-1",
            "state": "complete",
        }
    ]


def test_released_v3_public_climb_uses_frozen_snapshot_route_span() -> None:
    tables = _tables()
    _replace_first_ride_with_released_v3(tables)

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=[_raw_entries()[0]],
    )

    assert [entry["user"] for entry in projection.entries] == ["wallet-1"]
    assert projection.kom_holder == "wallet-1"
    assert projection.kom_time_s == 60


@pytest.mark.parametrize(
    "malformation",
    ["missing_snapshot", "missing_evidence", "wrong_hash", "invalid_offsets"],
)
def test_released_v3_missing_or_malformed_snapshot_evidence_fails_closed(
    malformation: str,
) -> None:
    tables = _tables()
    _replace_first_ride_with_released_v3(tables)
    if malformation == "missing_snapshot":
        tables["reward_threshold_release_snapshots"] = []
    elif malformation == "missing_evidence":
        tables["reward_threshold_release_snapshots"][0]["snapshot_evidence"] = None
    elif malformation == "wrong_hash":
        tables["reward_threshold_release_snapshots"][0]["snapshot_evidence"][
            "steps"
        ][0]["completion_evidence_hash_hex"] = "02"
    else:
        tables["reward_threshold_release_snapshots"][0]["snapshot_evidence"][
            "steps"
        ][0]["segment_end_offset_s"] = 60

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=[_raw_entries()[0]],
    )

    assert projection.entries == []
    assert projection.kom_holder is None


def test_released_v3_climb_retains_route_privacy_filtering() -> None:
    tables = _tables()
    _replace_first_ride_with_released_v3(tables)
    tables["rides"][0].update({
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 400,
        "map_hide_end_m": 0,
    })

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=[_raw_entries()[0]],
    )

    assert projection.entries == []
    assert projection.kom_holder is None


def test_released_v3_receipt_must_bind_snapshot_release_authority() -> None:
    tables = _tables()
    _replace_first_ride_with_released_v3(tables)
    tables["indexed_climb_completion_receipts"][0][
        "release_authority_pda"
    ] = "different-release-authority"

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=[_raw_entries()[0]],
    )

    assert projection.entries == []
    assert projection.kom_holder is None


def test_private_chain_winner_is_omitted_without_reranking_survivor() -> None:
    tables = _tables()
    tables["rides"][0]["visibility"] = "private"
    raw_entries = _raw_entries()
    frozen_raw = deepcopy(raw_entries)

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=raw_entries,
    )

    assert raw_entries == frozen_raw
    assert [entry["user"] for entry in projection.entries] == ["wallet-2"]
    assert projection.entries[0]["position"] == 2
    assert projection.entries[0]["rank"] == 2
    assert projection.kom_holder is None
    assert projection.kom_time_s is None


def test_visible_co_winner_keeps_chain_tie_rank_when_named_kom_is_private() -> None:
    tables = _tables()
    tables["rides"][0]["visibility"] = "private"
    tables["ride_economic_completion_steps"][1].update({
        "completion_time_s": 60,
        "segment_end_offset_s": 120,
    })
    raw_entries = _raw_entries()
    raw_entries[1]["time_s"] = 60

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=raw_entries,
    )

    assert [entry["user"] for entry in projection.entries] == ["wallet-2"]
    assert projection.entries[0]["position"] == 2
    assert projection.entries[0]["rank"] == 1
    assert projection.entries[0]["tie_size"] == 2
    assert projection.kom_holder is None


@pytest.mark.parametrize(
    ("ride_updates", "profile_updates"),
    [
        ({"visibility": "followers"}, {}),
        ({"hide_from_leaderboards": True}, {}),
        ({"moderation_state": "hidden"}, {}),
        ({"map_visibility": "hide_entire"}, {}),
        ({"gps_track": {"polyline": "~", "version": 2}}, {}),
        ({}, {"is_public": False}),
        ({}, {"moderation_state": "removed"}),
    ],
)
def test_non_public_ride_or_profile_state_is_never_eligible(
    ride_updates: dict[str, Any],
    profile_updates: dict[str, Any],
) -> None:
    tables = _tables()
    tables["rides"][0].update(ride_updates)
    tables["users"][0].update(profile_updates)

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=[_raw_entries()[0]],
    )

    assert projection.entries == []
    assert projection.kom_holder is None


def test_hidden_endpoint_or_zone_overlap_excludes_only_affected_span() -> None:
    tables = _tables()
    tables["rides"][0].update({
        "map_visibility": "hide_start_end",
        "map_hide_start_m": 400,
        "map_hide_end_m": 0,
    })
    tables["privacy_zones"] = [
        {
            "user_id": "user-2",
            "latitude": 40.0060,
            "longitude": -75.0000,
            "radius_m": 200,
        }
    ]

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=_raw_entries(),
    )

    assert projection.entries == []


def test_ambiguous_or_unlinked_chain_entry_fails_closed() -> None:
    tables = _tables()
    duplicate = deepcopy(tables["ride_economic_completion_steps"][0])
    duplicate.update({"ride_id": "ride-duplicate", "expected_receipt_pda": "receipt-duplicate"})
    tables["ride_economic_completion_steps"].append(duplicate)
    tables["ride_economic_plans"].append({
        "ride_id": "ride-duplicate",
        "user_id": "user-duplicate",
        "wallet": "wallet-1",
        "expected_attestation_pda": "attestation-duplicate",
        "state": "complete",
    })
    tables["indexed_climb_completion_receipts"].append({
        "pda": "receipt-duplicate",
        "ride_attestation_pda": "attestation-duplicate",
        "vault_pda": "vault-pda",
        "completion_evidence_hash": "\\x01",
        "completion_evidence_version": 2,
    })
    tables["rides"].append({
        **tables["rides"][0],
        "id": "ride-duplicate",
        "user_id": "user-duplicate",
        "ride_attestation_pda": "attestation-duplicate",
    })
    tables["users"].append({
        "id": "user-duplicate",
        "wallet": "wallet-1",
        "is_public": True,
        "moderation_state": "visible",
    })

    projection = project_public_record_board(
        _Client(tables),
        vault_row=_vault(),
        raw_entries=[_raw_entries()[0], {"user": "missing", "time_s": 90}],
    )

    assert projection.entries == []
    assert projection.kom_holder is None


def test_privacy_storage_failure_blocks_public_projection() -> None:
    with pytest.raises(
        PublicRecordBoardPrivacyUnavailable,
        match="privacy projection unavailable",
    ):
        project_public_record_board(
            _Client(_tables(), fail_table="privacy_zones"),
            vault_row=_vault(),
            raw_entries=_raw_entries(),
        )


def test_route_span_requires_complete_visible_time_coverage() -> None:
    visible = _route()
    assert route_span_is_public(
        visible,
        start_offset_s=60,
        end_offset_s=120,
    )

    redacted = deepcopy(visible)
    redacted[2].update({
        "latitude": None,
        "longitude": None,
        "redacted": True,
    })
    assert not route_span_is_public(
        redacted,
        start_offset_s=60,
        end_offset_s=120,
    )
    assert not route_span_is_public(
        visible[:2],
        start_offset_s=60,
        end_offset_s=120,
    )
