from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json, RealDictCursor

from app.services.canon_traversal_evidence import CanonTraversalEvidence
from backend.tests.services.test_settlement_clock_postgres_runtime import (
    _connection,
    postgres_dsn,
)


class _TileService:
    def lat_lng_to_tile(self, _lat: float, _lon: float, _resolution: int) -> str:
        return "8a2a1342b5a7fff"


def _bootstrap(cursor) -> None:
    cursor.execute(
        """
        DROP SCHEMA public CASCADE;
        CREATE SCHEMA public;
        DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        DO $$ BEGIN CREATE ROLE service_role NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
        CREATE TABLE public.rides (id UUID PRIMARY KEY);
        """
    )


def test_jsonb_round_trip_keeps_digest_and_schema_is_retry_safe(postgres_dsn: str) -> None:
    ride_id = uuid4()
    started_at = datetime(2026, 7, 20, tzinfo=timezone.utc)
    parsed = SimpleNamespace(
        started_at=started_at,
        records=[
            SimpleNamespace(
                timestamp=started_at,
                lat=-0.0,
                lon=0.0,
                elevation_m=1e20,
                power_w=250,
                heart_rate_bpm=150,
                speed_mps=1e-20,
            )
        ],
    )
    evidence = CanonTraversalEvidence.build(
        ride_id=ride_id,
        ride_hash_hex="ab" * 32,
        ride_parser_version=7,
        parsed_ride=parsed,
        tile_service=_TileService(),
    )
    row = evidence.to_row()

    with _connection(postgres_dsn) as connection:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            _bootstrap(cursor)
            migration = (
                Path(__file__).resolve().parents[2]
                / "sql/139_canon_traversal_evidence.sql"
            ).read_text(encoding="utf-8")
            cursor.execute(migration)
            cursor.execute(migration)
            cursor.execute("INSERT INTO public.rides (id) VALUES (%s)", (str(ride_id),))
            cursor.execute(
                """
                INSERT INTO public.canon_traversal_evidence (
                    ride_id, ride_hash_hex, ride_parser_version, evidence_version,
                    sample_count, sample_digest, samples
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ride_id, ride_hash_hex, ride_parser_version, evidence_version)
                DO UPDATE SET samples = EXCLUDED.samples
                """,
                (
                    str(ride_id),
                    row["ride_hash_hex"],
                    row["ride_parser_version"],
                    row["evidence_version"],
                    row["sample_count"],
                    row["sample_digest"],
                    Json(row["samples"]),
                ),
            )
            cursor.execute(
                "SELECT * FROM public.canon_traversal_evidence WHERE ride_id = %s",
                (str(ride_id),),
            )
            restored = CanonTraversalEvidence.from_row(dict(cursor.fetchone()))
            assert restored.samples == evidence.samples
            cursor.execute(
                """
                SELECT has_table_privilege(
                           'anon', 'public.canon_traversal_evidence', 'SELECT'
                       ) AS anon_can_select,
                       has_table_privilege(
                           'authenticated', 'public.canon_traversal_evidence', 'SELECT'
                       ) AS authenticated_can_select,
                       has_table_privilege(
                           'service_role', 'public.canon_traversal_evidence', 'SELECT'
                       ) AS service_role_can_select,
                       has_table_privilege(
                           'service_role', 'public.canon_traversal_evidence', 'DELETE'
                       ) AS service_role_can_delete
                """
            )
            assert tuple(cursor.fetchone().values()) == (False, False, True, False)

            tampered = list(row["samples"])
            tampered[0] = list(tampered[0])
            tampered[0][1] = "1"
            with pytest.raises(
                psycopg2.errors.DataException,
                match="canon traversal evidence is immutable",
            ):
                cursor.execute(
                    """
                    UPDATE public.canon_traversal_evidence
                    SET samples = %s
                    WHERE ride_id = %s
                    """,
                    (Json(tampered), str(ride_id)),
                )
