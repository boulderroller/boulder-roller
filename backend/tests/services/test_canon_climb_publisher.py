from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import pytest

from app.services.canon_climb_publisher import publish_canon_climb_payload_to_db


CANON_ROW_ID = UUID("11111111-1111-1111-1111-111111111111")
CANON_ID = UUID("22222222-2222-2222-2222-222222222222")
PREVIOUS_CANON_ROW_ID = UUID("33333333-3333-3333-3333-333333333333")
OTHER_CANON_ID = UUID("44444444-4444-4444-4444-444444444444")


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self.connection = connection
        self.closed = False

    def execute(self, sql: str, params=None) -> None:
        self.connection.executed.append((sql, params))
        self.rowcount = 1
        if self.connection.fail_on_sql and self.connection.fail_on_sql in sql:
            raise RuntimeError("synthetic db failure")

    def fetchone(self):
        sql = self.connection.executed[-1][0]
        if "ORDER BY version DESC" in sql:
            return self.connection.latest_canon_row
        return self.connection.inserted_canon_row

    def fetchall(self):
        return self.connection.existing_fingerprint_rows

    def close(self) -> None:
        self.closed = True
        self.connection.cursor_closed = True


class _FakeConnection:
    def __init__(
        self,
        *,
        fail_on_sql: str | None = None,
        existing_fingerprint_rows: list[tuple[UUID, str, UUID | None, int, str]]
        | None = None,
        latest_canon_row: tuple[UUID, str, UUID, int, str] | None = None,
        inserted_canon_row: tuple[UUID, UUID, int, str] | None = None,
    ) -> None:
        self.fail_on_sql = fail_on_sql
        self.existing_fingerprint_rows = existing_fingerprint_rows or []
        self.latest_canon_row = latest_canon_row
        self.inserted_canon_row = inserted_canon_row or (
            CANON_ROW_ID,
            CANON_ID,
            1,
            "ratified",
        )
        self.executed: list[tuple[str, object]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.cursor_closed = False

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def _publish_payload() -> dict:
    return {
        "candidate_id": "canon-aaaaaaaaaaaaaaaa",
        "compiler_run_mode": "applied",
        "target_table": "canon_climbs",
        "target_version": 1,
        "climb": {
            "candidate_fingerprint": "a" * 64,
            "legacy_candidate_fingerprints": ["f" * 64],
            "display_name": "Levering Street: start gate to finish gate",
            "route_name": "Levering Street",
            "direction": "ascending",
            "centerline_polyline": "encoded-polyline-secret",
            "centerline_wkt": "LINESTRING(-75.22 40.02,-75.21 40.03)",
            "corridor_wkt": "MULTIPOLYGON(((-75.22 40.02,-75.21 40.02,-75.21 40.03,-75.22 40.02)))",
            "corridor_half_width_m": 25.0,
            "gate_start_wkt": "LINESTRING(-75.221 40.020,-75.219 40.020)",
            "gate_end_wkt": "LINESTRING(-75.211 40.030,-75.209 40.030)",
            "canonical_profile": [
                {"dist_m": 0.0, "elev_m": 12.0},
                {"dist_m": 100.0, "elev_m": 20.0},
            ],
            "length_m": 100.0,
            "vert_m": 8.0,
            "avg_gradient_pct": 8.0,
            "max_gradient_pct": 10.5,
            "worthiness_score": 88.0,
            "confidence": "high",
            "dem_source": "USGS 3DEP 10m local profile export",
            "compiler_version": "canon-compile-v0.2.0",
            "osm_way_refs": [123456789],
            "odbl_source": "OpenStreetMap contributors",
            "odbl_extract_at": "2026-07-05T00:00:00Z",
            "provenance": {
                "compiler": "fixture",
                "canonical_profile_hash": {
                    "algorithm": "blake3_canonical_profile_v1",
                    "value": "08aefaf54eadb227fff49b20abbca026a816d16576c19bc9f4e71e643e7c6d63",
                },
            },
            "low_confidence_flags": [],
            "ratified_by": "climb_lab_dev",
            "ratified_at": "2026-07-06T00:00:00+00:00",
        },
        "corridor_cells": [
            {
                "h3_resolution": 10,
                "tile_id": "8a2a1342b5a7fff",
                "coverage_role": "corridor",
            }
        ],
    }


def test_canon_publisher_bounds_lock_wait_before_any_row_lock() -> None:
    connection = _FakeConnection()
    publish_canon_climb_payload_to_db(_publish_payload(), connection_factory=lambda: connection)
    assert connection.executed[0] == ("SET LOCAL lock_timeout = '5s'", None)


@pytest.mark.parametrize("use_builder", [False, True])
def test_canon_publication_strips_local_profiles_without_mutating_review(use_builder) -> None:
    from app.services.climb_lab import build_canon_climb_publish_payload
    from psycopg2.extras import Json

    payload = _publish_payload()
    provenance = payload["climb"]["provenance"]
    provenance["compiler_profile_points"] = [{"lat": 40.0, "lon": -75.0}]
    provenance["finish_gate_rule"] = {
        "predecessor_profile_points": [{"lat": 40.0, "lon": -75.1}],
        "record_continuity_policy": "new_record_board",
        "evidence": [{"compiler_profile_points": [1], "keep": "authority"}],
    }
    provenance["capture_tolerance_revision"] = {"scope": "start_gate", "half_extent_m": 30}
    expected_profile = deepcopy(payload["climb"]["canonical_profile"])
    payload["climb"]["canonical_profile"][0]["compiler_profile_points"] = [1]
    payload["climb"]["canonical_profile"][1]["predecessor_profile_points"] = [2]
    original = deepcopy(payload)
    expected = deepcopy(provenance)
    del expected["compiler_profile_points"]
    del expected["finish_gate_rule"]["predecessor_profile_points"]
    del expected["finish_gate_rule"]["evidence"][0]["compiler_profile_points"]
    if use_builder:
        candidate = {**payload["climb"], "corridor_cells": payload["corridor_cells"],
                     "compiler_run_mode": "applied"}
        payload = build_canon_climb_publish_payload(candidate, ratified_by="local-test")
        assert payload["climb"]["provenance"] == expected
        assert payload["climb"]["canonical_profile"] == expected_profile
        assert candidate["provenance"] == original["climb"]["provenance"]
    connection = _FakeConnection()
    publish_canon_climb_payload_to_db(payload, connection_factory=lambda: connection)
    stored = [value.adapted for sql, params in connection.executed
              if "INSERT INTO public.canon_climbs" in sql
              for value in params if isinstance(value, Json)]
    assert expected in stored
    assert expected_profile in stored
    if not use_builder:
        assert payload == original


def test_publish_canon_climb_payload_uses_parameterized_db_statements() -> None:
    connection = _FakeConnection()

    result = publish_canon_climb_payload_to_db(
        _publish_payload(),
        connection_factory=lambda: connection,
    )

    assert {key: value for key, value in result.items() if key != "registration_artifact"} == {
        "canon_climb_id": str(CANON_ROW_ID),
        "canon_id": str(CANON_ID),
        "version": 1,
        "status": "ratified",
        "corridor_cell_count": 1,
    }
    assert result["registration_artifact"]["artifact"] == (
        "boulderroller.canon-registration"
    )
    assert result["registration_artifact"]["registry_row"]["id"] == str(
        CANON_ROW_ID
    )
    assert connection.committed is True
    assert connection.rolled_back is False
    assert connection.closed is True
    assert connection.cursor_closed is True
    assert len(connection.executed) == 5

    lineage_sql, lineage_params = connection.executed[1]
    assert "SELECT id, candidate_fingerprint" in lineage_sql
    assert "FOR UPDATE" in lineage_sql
    assert lineage_params == (["a" * 64, "f" * 64],)

    climb_sql, climb_params = connection.executed[2]
    assert "INSERT INTO public.canon_climbs AS cc" in climb_sql
    assert "gen_random_uuid()" in climb_sql
    assert "RETURNING id, canon_id, version, status" in climb_sql
    assert "cc.canon_id = EXCLUDED.canon_id" in climb_sql
    assert "ST_Buffer" in climb_sql
    assert "::geography" in climb_sql
    assert climb_params[9:12] == (
        "LINESTRING(-75.22 40.02,-75.21 40.03)",
        "LINESTRING(-75.22 40.02,-75.21 40.03)",
        25.0,
    )
    assert _publish_payload()["climb"]["corridor_wkt"] not in climb_params
    assert climb_params[:5] == (None, 1, None, "new_record_board", "a" * 64)
    assert climb_params[-1] == "2026-07-06T00:00:00+00:00"
    assert "aaaaaaaa" not in climb_sql
    assert "LINESTRING" not in climb_sql

    delete_sql, delete_params = connection.executed[3]
    assert delete_sql == "DELETE FROM public.canon_corridor_cells WHERE canon_climb_id = %s"
    assert delete_params == (CANON_ROW_ID,)

    cell_sql, cell_params = connection.executed[4]
    assert "INSERT INTO public.canon_corridor_cells" in cell_sql
    assert cell_params == (CANON_ROW_ID, 10, "8a2a1342b5a7fff", "corridor")


def test_publisher_keeps_precise_registry_metrics_and_emits_chain_projection() -> None:
    connection = _FakeConnection()
    payload = deepcopy(_publish_payload())
    payload["climb"].update(
        {
            "length_m": 2031.31,
            "vert_m": 87.36,
            "avg_gradient_pct": 4.301,
        }
    )

    result = publish_canon_climb_payload_to_db(
        payload,
        connection_factory=lambda: connection,
    )

    climb_params = connection.executed[2][1]
    assert climb_params[15:18] == (2031.31, 87.36, 4.301)
    assert result["registration_artifact"]["registry_row"]["length_m"] == 2031.31
    assert result["registration_artifact"]["registry_row"]["vert_m"] == 87.36
    assert result["registration_artifact"]["registry_row"]["avg_gradient_pct"] == 4.301
    assert result["registration_artifact"]["chain_metric_projection"] == {
        "algorithm": "boulderroller_chain_metric_projection_v1",
        "vert_decimeters": 874,
        "distance_meters": 2031,
        "avg_gradient_basis_points": 430,
    }


def test_publish_boundary_change_creates_successor_and_preserves_prior_version() -> None:
    connection = _FakeConnection(
        existing_fingerprint_rows=[
            (PREVIOUS_CANON_ROW_ID, "f" * 64, CANON_ID, 1, "ratified")
        ],
        latest_canon_row=(
            PREVIOUS_CANON_ROW_ID,
            "f" * 64,
            CANON_ID,
            1,
            "ratified",
        ),
        inserted_canon_row=(CANON_ROW_ID, CANON_ID, 2, "ratified"),
    )

    result = publish_canon_climb_payload_to_db(
        _publish_payload(),
        connection_factory=lambda: connection,
    )

    assert result["canon_climb_id"] == str(CANON_ROW_ID)
    assert result["canon_id"] == str(CANON_ID)
    assert result["version"] == 2

    latest_sql, latest_params = connection.executed[2]
    assert "ORDER BY version DESC" in latest_sql
    assert "FOR UPDATE" in latest_sql
    assert latest_params == (CANON_ID,)

    retire_sql, retire_params = connection.executed[3]
    assert "status = 'retired'" in retire_sql
    assert "candidate_fingerprint" not in retire_sql
    assert "version =" not in retire_sql
    assert retire_params == (PREVIOUS_CANON_ROW_ID,)

    insert_sql, insert_params = connection.executed[4]
    assert "INSERT INTO public.canon_climbs AS cc" in insert_sql
    assert "supersedes_climb_id" in insert_sql
    assert "record_continuity_policy" in insert_sql
    assert insert_params[:4] == (
        CANON_ID,
        2,
        PREVIOUS_CANON_ROW_ID,
        "new_record_board",
    )
    assert connection.committed is True


def test_republishing_current_successor_does_not_mint_another_version() -> None:
    connection = _FakeConnection(
        existing_fingerprint_rows=[
            (CANON_ROW_ID, "a" * 64, CANON_ID, 2, "ratified"),
            (PREVIOUS_CANON_ROW_ID, "f" * 64, CANON_ID, 1, "retired"),
        ],
        latest_canon_row=(CANON_ROW_ID, "a" * 64, CANON_ID, 2, "ratified"),
        inserted_canon_row=(CANON_ROW_ID, CANON_ID, 2, "ratified"),
    )

    result = publish_canon_climb_payload_to_db(
        _publish_payload(),
        connection_factory=lambda: connection,
    )

    assert result["version"] == 2
    assert not any(
        "status = 'retired'" in sql for sql, _ in connection.executed
    )
    insert_sql, insert_params = connection.executed[3]
    assert "INSERT INTO public.canon_climbs AS cc" in insert_sql
    assert "public.canon_vault_activations" in insert_sql
    assert "public.indexed_climbs" in insert_sql
    assert "indexed.canon_climb_id = cc.id" in insert_sql
    assert "activation.activation_status IN" in insert_sql
    assert "'reserved', 'confirmed', 'finalized'".replace(" ", "") in insert_sql.replace(
        " ", ""
    ).replace("\n", "")
    assert insert_params[:4] == (CANON_ID, 2, None, "new_record_board")


def test_explicit_same_fingerprint_revision_creates_successor_without_rewriting_prior() -> None:
    connection = _FakeConnection(
        existing_fingerprint_rows=[
            (PREVIOUS_CANON_ROW_ID, "a" * 64, CANON_ID, 1, "ratified"),
        ],
        latest_canon_row=(
            PREVIOUS_CANON_ROW_ID,
            "a" * 64,
            CANON_ID,
            1,
            "ratified",
        ),
        inserted_canon_row=(CANON_ROW_ID, CANON_ID, 2, "ratified"),
    )

    result = publish_canon_climb_payload_to_db(
        _publish_payload(),
        connection_factory=lambda: connection,
        explicit_successor=True,
        record_continuity_policy="new_record_board",
    )

    assert result["canon_climb_id"] == str(CANON_ROW_ID)
    assert result["version"] == 2
    retire_sql, retire_params = connection.executed[3]
    assert "status = 'retired'" in retire_sql
    assert retire_params == (PREVIOUS_CANON_ROW_ID,)
    insert_sql, insert_params = connection.executed[4]
    assert "ON CONFLICT (candidate_fingerprint)" not in insert_sql
    assert insert_params[:4] == (
        CANON_ID,
        2,
        PREVIOUS_CANON_ROW_ID,
        "new_record_board",
    )


def test_publish_rejects_unimplemented_record_carry_policy() -> None:
    connection = _FakeConnection()

    with pytest.raises(ValueError, match="record migration"):
        publish_canon_climb_payload_to_db(
            _publish_payload(),
            connection_factory=lambda: connection,
            explicit_successor=True,
            record_continuity_policy="carry_records_forward",
        )

    assert connection.executed == []


def test_publish_rejects_lineage_that_omits_the_latest_canon_version() -> None:
    connection = _FakeConnection(
        existing_fingerprint_rows=[
            (PREVIOUS_CANON_ROW_ID, "f" * 64, CANON_ID, 1, "retired")
        ],
        latest_canon_row=(
            CANON_ROW_ID,
            "e" * 64,
            CANON_ID,
            2,
            "ratified",
        ),
    )

    with pytest.raises(RuntimeError, match="lineage is stale"):
        publish_canon_climb_payload_to_db(
            _publish_payload(),
            connection_factory=lambda: connection,
        )

    assert len(connection.executed) == 3
    assert connection.committed is False
    assert connection.rolled_back is True


def test_publish_rejects_diagnostic_compiler_run() -> None:
    connection = _FakeConnection()
    payload = _publish_payload()
    payload["compiler_run_mode"] = "diagnostic_skip"

    with pytest.raises(ValueError, match="applied compiler run"):
        publish_canon_climb_payload_to_db(
            payload,
            connection_factory=lambda: connection,
        )

    assert connection.executed == []


@pytest.mark.parametrize(
    "filename",
    ["COMPILER-BEFORE.json", "COMPILER-PROPOSED.json", "ADMITTED-AFTER.json", "CLIMBLAB.json"],
)
def test_finish_gate_review_artifacts_cannot_publish(filename: str) -> None:
    import json
    from pathlib import Path
    from app.services.climb_lab import (
        build_climb_lab_compiler_candidate_summary,
        build_canon_climb_publish_payload,
    )

    path = (
        Path(__file__).resolve().parents[3]
        / "history/codex-reports-2026-10-20/gate-rule"
        / filename
    )
    report = json.loads(path.read_text())
    summary = build_climb_lab_compiler_candidate_summary(report)
    assert summary["totals"]["publish_ready_candidates"] == 0
    candidate = summary["candidates"][0]
    assert candidate["compiler_run_mode"] != "applied"
    with pytest.raises(ValueError, match="compiler_run_mode=applied"):
        build_canon_climb_publish_payload(candidate)

    payload = _publish_payload()
    payload["compiler_run_mode"] = candidate["compiler_run_mode"]

    def no_connection():
        pytest.fail("Review output must be rejected before opening a database connection")

    with pytest.raises(ValueError, match="applied compiler run"):
        publish_canon_climb_payload_to_db(payload, connection_factory=no_connection)


def test_finish_gate_prepared_successors_cannot_publish() -> None:
    import json
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[3]
        / "history/codex-reports-2026-10-20/gate-rule/SUCCESSORS.json"
    )
    prepared = json.loads(path.read_text())

    def no_connection():
        pytest.fail("Prepared successor opened a database connection")

    for successor in prepared:
        payload = successor["publish_payload"]
        with pytest.raises(ValueError, match="applied compiler run"):
            publish_canon_climb_payload_to_db(payload, connection_factory=no_connection)


def test_publish_rejects_ambiguous_fingerprint_lineage() -> None:
    connection = _FakeConnection(
        existing_fingerprint_rows=[
            (CANON_ROW_ID, "a" * 64, CANON_ID, 2, "ratified"),
            (PREVIOUS_CANON_ROW_ID, "f" * 64, OTHER_CANON_ID, 1, "ratified"),
        ]
    )

    with pytest.raises(RuntimeError, match="multiple canon identities"):
        publish_canon_climb_payload_to_db(
            _publish_payload(),
            connection_factory=lambda: connection,
        )

    assert len(connection.executed) == 2
    assert connection.committed is False
    assert connection.rolled_back is True


def test_publish_canon_climb_payload_rejects_compiler_generated_sql_text() -> None:
    connection = _FakeConnection()
    payload = _publish_payload()
    payload["compiler_sql"] = "DROP TABLE public.canon_climbs"

    with pytest.raises(ValueError, match="compiler-generated SQL text"):
        publish_canon_climb_payload_to_db(
            payload,
            connection_factory=lambda: connection,
        )

    assert connection.executed == []
    assert connection.committed is False
    assert connection.rolled_back is False


@pytest.mark.parametrize("invalid_width", [0, -1, float("nan"), float("inf")])
def test_publish_canon_climb_payload_rejects_invalid_corridor_width(
    invalid_width: float,
) -> None:
    connection = _FakeConnection()
    payload = _publish_payload()
    payload["climb"]["corridor_half_width_m"] = invalid_width

    with pytest.raises(ValueError, match="finite and positive"):
        publish_canon_climb_payload_to_db(
            payload,
            connection_factory=lambda: connection,
        )

    assert connection.executed == []


def test_publish_canon_climb_payload_rolls_back_when_cell_insert_fails() -> None:
    connection = _FakeConnection(fail_on_sql="INSERT INTO public.canon_corridor_cells")

    with pytest.raises(RuntimeError, match="synthetic db failure"):
        publish_canon_climb_payload_to_db(
            _publish_payload(),
            connection_factory=lambda: connection,
        )

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.closed is True
    assert connection.cursor_closed is True
