from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

import psycopg2
import pytest

from app.services.canon_nomination_queue import load_canon_nomination_queue
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


SIGNATURE = "ab" * 64
COARSE_H3_CELL = "852a1073fffffff"


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, rows):
        self.cursor_instance = _Cursor(rows)
        self.closed = False

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


def test_nomination_queue_aggregates_in_sql_and_emits_no_rider_evidence() -> None:
    connection = _Connection(
        [
            (
                SIGNATURE,
                COARSE_H3_CELL,
                5,
                3,
                2,
                84.5,
                712.25,
                11.9,
                96.2,
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 20, tzinfo=timezone.utc),
                ["canonical_v2", "canonical_v2.1"],
            )
        ]
    )

    payload = load_canon_nomination_queue(
        connection_factory=lambda: connection,
        min_distinct_activities=2,
        min_independent_riders=2,
        limit=25,
    )

    assert connection.closed is True
    assert connection.cursor_instance.params == (2, 2, 25)
    normalized_sql = " ".join(connection.cursor_instance.sql.split())
    assert "GROUP BY lower(signature_v2_hex)" in normalized_sql
    assert "count(DISTINCT activity_id)" in normalized_sql
    assert "count(DISTINCT wallet)" in normalized_sql
    assert "economic_eligible IS FALSE" in normalized_sql
    assert (
        "abstention_reasons @> ARRAY['MATCH:canon_traversal_required']::text[]"
        in normalized_sql
    )
    assert "match_trace" in normalized_sql
    assert "GROUP BY lower(signature_v2_hex), significance_cell_h3" in normalized_sql
    assert "economic_eligible IS TRUE" not in normalized_sql
    assert payload["authority"] == "discovery_only"
    assert payload["candidate_count"] == 1
    assert payload["candidates"] == [
        {
            "candidate_fingerprint": hashlib.sha256(
                b"climblab-detector-nomination-v1\0"
                + len(SIGNATURE).to_bytes(2, "big")
                + SIGNATURE.encode("ascii")
                + len(COARSE_H3_CELL).to_bytes(2, "big")
                + COARSE_H3_CELL.encode("ascii")
            ).hexdigest(),
            "coarse_h3_cell": COARSE_H3_CELL,
            "h3_resolution": 5,
            "evidence_count": 5,
            "distinct_activity_count": 3,
            "independent_rider_count": 2,
            "avg_vert_m": 84.5,
            "avg_distance_m": 712.25,
            "avg_gradient_pct": 11.9,
            "max_significance_percentile": 96.2,
            "first_observed_at": "2026-07-01T00:00:00+00:00",
            "last_observed_at": "2026-07-20T00:00:00+00:00",
            "detector_versions": ["canonical_v2", "canonical_v2.1"],
        }
    ]

    serialized = json.dumps(payload, sort_keys=True)
    for forbidden_key in (
        "activity_id",
        "wallet",
        "user_id",
        "signature_hex",
        "signature_v2_hex",
        "raw_samples",
        "start_lat",
        "start_lon",
        "end_lat",
        "end_lon",
    ):
        assert f'"{forbidden_key}"' not in serialized


def test_nomination_queue_requires_independent_riders_and_discovery_abstention(
    postgres_dsn: str,
) -> None:
    same_rider_signature = "11" * 64
    independent_signature = "22" * 64
    economic_signature = "33" * 64
    canon_bound_signature = "44" * 64
    with _connection(postgres_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
            cursor.execute(
                """
                CREATE TABLE public.patterns_climb (
                    activity_id UUID NOT NULL,
                    wallet TEXT NOT NULL,
                    signature_v2_hex TEXT,
                    significance_cell_h3 TEXT,
                    vert_m DOUBLE PRECISION,
                    distance_m DOUBLE PRECISION,
                    avg_gradient_pct DOUBLE PRECISION,
                    significance_percentile DOUBLE PRECISION,
                    created_at TIMESTAMPTZ NOT NULL,
                    detector_version TEXT,
                    economic_eligible BOOLEAN,
                    abstention_reasons TEXT[],
                    match_trace JSONB
                )
                """
            )
            rows = []
            for signature, wallets, economic_eligible, reasons, trace in (
                (
                    same_rider_signature,
                    ["one-rider", "one-rider"],
                    False,
                    ["MATCH:canon_traversal_required"],
                    None,
                ),
                (
                    independent_signature,
                    ["rider-a", "rider-b"],
                    False,
                    ["MATCH:canon_traversal_required"],
                    None,
                ),
                (
                    economic_signature,
                    ["rider-a", "rider-b"],
                    True,
                    [],
                    None,
                ),
                (
                    canon_bound_signature,
                    ["rider-a", "rider-b"],
                    False,
                    ["MATCH:canon_traversal_required"],
                    {
                        "registry_id": str(uuid4()),
                        "canon_id": str(uuid4()),
                        "canon_version": 1,
                    },
                ),
            ):
                for index, wallet in enumerate(wallets):
                    rows.append(
                        (
                            str(uuid4()),
                            wallet,
                            signature,
                            COARSE_H3_CELL,
                            80 + index,
                            700 + index,
                            11 + index,
                            95 + index,
                            datetime(2026, 7, 1 + index, tzinfo=timezone.utc),
                            "canonical_v2",
                            economic_eligible,
                            reasons,
                            json.dumps(trace) if trace is not None else None,
                        )
                    )
            cursor.executemany(
                """
                INSERT INTO public.patterns_climb VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                rows,
            )

    payload = load_canon_nomination_queue(
        connection_factory=lambda: psycopg2.connect(postgres_dsn),
        min_distinct_activities=2,
        min_independent_riders=2,
        limit=25,
    )

    assert payload["candidate_count"] == 1
    candidate = payload["candidates"][0]
    assert candidate["candidate_fingerprint"] == hashlib.sha256(
        b"climblab-detector-nomination-v1\0"
        + len(independent_signature).to_bytes(2, "big")
        + independent_signature.encode("ascii")
        + len(COARSE_H3_CELL).to_bytes(2, "big")
        + COARSE_H3_CELL.encode("ascii")
    ).hexdigest()
    assert candidate["independent_rider_count"] == 2
    assert candidate["distinct_activity_count"] == 2
    assert candidate["coarse_h3_cell"] == COARSE_H3_CELL
    serialized = json.dumps(payload, sort_keys=True)
    for identity in ("one-rider", "rider-a", "rider-b"):
        assert identity not in serialized
    for signature in (
        same_rider_signature,
        independent_signature,
        economic_signature,
        canon_bound_signature,
    ):
        assert signature not in serialized


def test_nomination_fingerprint_distinguishes_same_profile_in_different_cells() -> None:
    other_cell = "852a1077fffffff"
    connection = _Connection(
        [
            (
                SIGNATURE,
                cell,
                2,
                2,
                2,
                80.0,
                700.0,
                11.0,
                95.0,
                datetime(2026, 7, 1, tzinfo=timezone.utc),
                datetime(2026, 7, 2, tzinfo=timezone.utc),
                ["canonical_v2"],
            )
            for cell in (COARSE_H3_CELL, other_cell)
        ]
    )

    payload = load_canon_nomination_queue(
        connection_factory=lambda: connection,
        min_distinct_activities=2,
        min_independent_riders=2,
        limit=25,
    )

    assert {candidate["coarse_h3_cell"] for candidate in payload["candidates"]} == {
        COARSE_H3_CELL,
        other_cell,
    }
    assert len(
        {candidate["candidate_fingerprint"] for candidate in payload["candidates"]}
    ) == 2


@pytest.mark.parametrize(
    ("min_distinct_activities", "min_independent_riders", "limit"),
    [(0, 2, 25), (2, 1, 25), (2, 2, 0), (2, 2, 101)],
)
def test_nomination_queue_rejects_unbounded_requests(
    min_distinct_activities: int,
    min_independent_riders: int,
    limit: int,
) -> None:
    with pytest.raises(ValueError):
        load_canon_nomination_queue(
            connection_factory=lambda: None,
            min_distinct_activities=min_distinct_activities,
            min_independent_riders=min_independent_riders,
            limit=limit,
        )
