"""Backend DB publisher for ratified ClimbLab canon candidates."""

from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Callable

from psycopg2.extras import Json

from .canon_commitment import CANON_PROFILE_HASH_ALGORITHM, canonical_profile_hash_hex
from .canon_registration_artifact import build_canon_registration_artifact


ConnectionFactory = Callable[[], Any]


class DeferredCommitConnection:
    """Share an outer transaction without per-climb commit or close."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        return None


def strip_local_compiler_profiles(value: Any) -> Any:
    """Copy a publication value without local-only compiler profile arrays."""
    if isinstance(value, dict):
        return {key: strip_local_compiler_profiles(item) for key, item in value.items()
                if key not in {"compiler_profile_points", "predecessor_profile_points"}}
    if isinstance(value, list):
        return [strip_local_compiler_profiles(item) for item in value]
    return value


_COMPILER_SQL_PAYLOAD_KEYS = {
    "sql",
    "sql_text",
    "insert_sql",
    "compiler_sql",
    "compiler_generated_sql",
}
_REQUIRED_CLIMB_FIELDS = (
    "candidate_fingerprint",
    "legacy_candidate_fingerprints",
    "display_name",
    "direction",
    "centerline_polyline",
    "centerline_wkt",
    "corridor_wkt",
    "corridor_half_width_m",
    "gate_start_wkt",
    "gate_end_wkt",
    "canonical_profile",
    "length_m",
    "vert_m",
    "avg_gradient_pct",
    "worthiness_score",
    "confidence",
    "dem_source",
    "compiler_version",
    "osm_way_refs",
    "odbl_source",
    "provenance",
)


def _reject_compiler_sql_text(publish_payload: dict[str, Any]) -> None:
    supplied = sorted(
        key
        for key in _COMPILER_SQL_PAYLOAD_KEYS
        if publish_payload.get(key)
    )
    if supplied:
        raise ValueError(
            "compiler-generated SQL text is not accepted by the canon publisher: "
            + ", ".join(supplied)
        )


def _validated_publish_parts(
    publish_payload: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _reject_compiler_sql_text(publish_payload)
    if publish_payload.get("compiler_run_mode") != "applied":
        raise ValueError("canon publication requires an applied compiler run")
    if publish_payload.get("target_table") != "canon_climbs":
        raise ValueError("unsupported canon publish target table")
    if publish_payload.get("target_version") != 1:
        raise ValueError("unsupported canon publish target version")

    climb = strip_local_compiler_profiles(dict(publish_payload.get("climb") or {}))
    missing_fields = [
        field
        for field in _REQUIRED_CLIMB_FIELDS
        if climb.get(field) is None or climb.get(field) == "" or climb.get(field) == []
    ]
    if missing_fields:
        raise ValueError(
            "canon publish payload is missing climb fields: "
            + ", ".join(missing_fields)
        )
    corridor_half_width_m = float(climb["corridor_half_width_m"])
    if not isfinite(corridor_half_width_m) or corridor_half_width_m <= 0:
        raise ValueError("canon corridor_half_width_m must be finite and positive")
    climb["corridor_half_width_m"] = corridor_half_width_m
    current_fingerprint = str(climb["candidate_fingerprint"])
    legacy_fingerprints = []
    for raw_fingerprint in climb["legacy_candidate_fingerprints"]:
        fingerprint = str(raw_fingerprint).strip()
        if (
            fingerprint
            and fingerprint != current_fingerprint
            and fingerprint not in legacy_fingerprints
        ):
            legacy_fingerprints.append(fingerprint)
    if not legacy_fingerprints:
        raise ValueError("canon publish payload has no distinct legacy fingerprint")
    climb["legacy_candidate_fingerprints"] = legacy_fingerprints
    climb["low_confidence_flags"] = list(climb.get("low_confidence_flags") or [])
    climb["ratified_at"] = (
        climb.get("ratified_at") or datetime.now(timezone.utc).isoformat()
    )
    profile_hash = canonical_profile_hash_hex(climb["canonical_profile"])
    profile_evidence = (climb.get("provenance") or {}).get(
        "canonical_profile_hash"
    ) or {}
    if (
        profile_evidence.get("algorithm") != CANON_PROFILE_HASH_ALGORITHM
        or str(profile_evidence.get("value") or "").lower() != profile_hash
    ):
        raise ValueError("canon publish payload profile hash evidence is invalid")

    corridor_cells = [
        {
            "h3_resolution": int(cell.get("h3_resolution") or 10),
            "tile_id": str(cell["tile_id"]),
            "coverage_role": str(cell.get("coverage_role") or "corridor"),
        }
        for cell in publish_payload.get("corridor_cells") or []
        if cell.get("tile_id")
    ]
    if not corridor_cells:
        raise ValueError("canon publish payload has no corridor cells")
    return climb, corridor_cells


def _resolve_canon_publication_target(
    cursor: Any,
    climb: dict[str, Any],
    *,
    explicit_successor: bool = False,
) -> tuple[Any | None, int, Any | None]:
    current_fingerprint = climb["candidate_fingerprint"]
    recognized_fingerprints = [
        current_fingerprint,
        *climb["legacy_candidate_fingerprints"],
    ]
    cursor.execute(
        """
        SELECT id, candidate_fingerprint, canon_id, version, status
        FROM public.canon_climbs
        WHERE candidate_fingerprint = ANY(%s)
        FOR UPDATE
        """,
        (recognized_fingerprints,),
    )
    existing_rows = cursor.fetchall()
    if not existing_rows:
        if explicit_successor:
            raise RuntimeError("explicit canon successor has no predecessor")
        return None, 1, None

    current_rows = [row for row in existing_rows if row[1] == current_fingerprint]

    if any(row[2] is None for row in existing_rows):
        if len(existing_rows) == 1 and current_rows:
            return None, 1, None
        raise RuntimeError(
            "canon fingerprint lineage includes an unratified candidate"
        )

    canon_ids = {row[2] for row in existing_rows}
    if len(canon_ids) != 1:
        raise RuntimeError(
            "canon fingerprint lineage resolves to multiple canon identities"
        )
    canon_id = next(iter(canon_ids))

    cursor.execute(
        """
        SELECT id, candidate_fingerprint, canon_id, version, status
        FROM public.canon_climbs
        WHERE canon_id = %s
        ORDER BY version DESC
        LIMIT 1
        FOR UPDATE
        """,
        (canon_id,),
    )
    latest_row = cursor.fetchone()
    if latest_row is None:
        raise RuntimeError("canon fingerprint lineage has no canonical version")

    latest_id, latest_fingerprint, _, latest_version, latest_status = latest_row
    if latest_fingerprint == current_fingerprint:
        if latest_status == "retired":
            raise RuntimeError("current canon fingerprint belongs to a retired version")
        if explicit_successor:
            if latest_status != "ratified":
                raise RuntimeError("latest canon version is not active for succession")
            return canon_id, latest_version + 1, latest_id
        return canon_id, latest_version, None

    if current_rows:
        raise RuntimeError("current canon fingerprint is not the latest version")
    if latest_fingerprint not in recognized_fingerprints:
        raise RuntimeError("canon fingerprint lineage is stale")
    if latest_status != "ratified":
        raise RuntimeError("latest canon version is not active for succession")

    return canon_id, latest_version + 1, latest_id


def publish_canon_climb_payload_to_db(
    publish_payload: dict[str, Any],
    *,
    connection_factory: ConnectionFactory,
    explicit_successor: bool = False,
    record_continuity_policy: str = "new_record_board",
) -> dict[str, Any]:
    """Insert a ratified canon climb and corridor cells using DB parameters only."""
    if record_continuity_policy != "new_record_board":
        raise ValueError(
            "carry_records_forward is unavailable until exact record migration is proven"
        )
    climb, corridor_cells = _validated_publish_parts(publish_payload)

    conn = connection_factory()
    cursor = conn.cursor()
    try:
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        canon_id, canon_version, predecessor_id = _resolve_canon_publication_target(
            cursor,
            climb,
            explicit_successor=explicit_successor,
        )
        if predecessor_id is not None:
            cursor.execute(
                """
                UPDATE public.canon_climbs
                SET status = 'retired',
                    retired_at = COALESCE(retired_at, now()),
                    updated_at = now()
                WHERE id = %s
                  AND status = 'ratified'
                """,
                (predecessor_id,),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("prior canon version could not be retired")

        conflict_clause = "" if explicit_successor else """
            ON CONFLICT (candidate_fingerprint) WHERE status <> 'retired'
            DO UPDATE SET
                status = 'ratified',
                canon_id = COALESCE(cc.canon_id, EXCLUDED.canon_id),
                display_name = EXCLUDED.display_name,
                route_name = EXCLUDED.route_name,
                centerline_polyline = EXCLUDED.centerline_polyline,
                centerline_geom = EXCLUDED.centerline_geom,
                corridor_geom = EXCLUDED.corridor_geom,
                gate_start_line = EXCLUDED.gate_start_line,
                gate_end_line = EXCLUDED.gate_end_line,
                canonical_profile = EXCLUDED.canonical_profile,
                length_m = EXCLUDED.length_m,
                vert_m = EXCLUDED.vert_m,
                avg_gradient_pct = EXCLUDED.avg_gradient_pct,
                max_gradient_pct = EXCLUDED.max_gradient_pct,
                worthiness_score = EXCLUDED.worthiness_score,
                confidence = EXCLUDED.confidence,
                dem_source = EXCLUDED.dem_source,
                compiler_version = EXCLUDED.compiler_version,
                osm_way_refs = EXCLUDED.osm_way_refs,
                odbl_source = EXCLUDED.odbl_source,
                odbl_extract_at = EXCLUDED.odbl_extract_at,
                provenance = EXCLUDED.provenance,
                low_confidence_flags = EXCLUDED.low_confidence_flags,
                ratified_by = EXCLUDED.ratified_by,
                ratified_at = COALESCE(cc.ratified_at, EXCLUDED.ratified_at),
                updated_at = now()
            WHERE (cc.canon_id IS NULL OR cc.canon_id = EXCLUDED.canon_id)
              AND NOT EXISTS (
                  SELECT 1
                  FROM public.canon_vault_activations AS activation
                  WHERE activation.canon_climb_id = cc.id
                    AND activation.activation_status IN (
                        'reserved', 'confirmed', 'finalized'
                      )
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM public.indexed_climbs AS indexed
                  WHERE indexed.canon_climb_id = cc.id
              )
        """
        cursor.execute(
            f"""
            INSERT INTO public.canon_climbs AS cc (
                canon_id,
                version,
                status,
                supersedes_climb_id,
                record_continuity_policy,
                candidate_fingerprint,
                display_name,
                route_name,
                direction,
                centerline_polyline,
                centerline_geom,
                corridor_geom,
                gate_start_line,
                gate_end_line,
                canonical_profile,
                length_m,
                vert_m,
                avg_gradient_pct,
                max_gradient_pct,
                worthiness_score,
                confidence,
                dem_source,
                compiler_version,
                osm_way_refs,
                odbl_source,
                odbl_extract_at,
                provenance,
                low_confidence_flags,
                ratified_by,
                ratified_at
            ) VALUES (
                COALESCE(%s::uuid, gen_random_uuid()),
                %s,
                'ratified',
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                ST_GeomFromText(%s, 4326),
                ST_Multi(
                    ST_Buffer(
                        ST_GeomFromText(%s, 4326)::geography,
                        %s
                    )::geometry
                ),
                ST_GeomFromText(%s, 4326),
                ST_GeomFromText(%s, 4326),
                %s::jsonb,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                %s::jsonb,
                %s,
                %s,
                %s
            )
            {conflict_clause}
            RETURNING id, canon_id, version, status
            """,
            (
                canon_id,
                canon_version,
                predecessor_id,
                record_continuity_policy,
                climb["candidate_fingerprint"],
                climb["display_name"],
                climb.get("route_name"),
                climb["direction"],
                climb["centerline_polyline"],
                climb["centerline_wkt"],
                climb["centerline_wkt"],
                climb["corridor_half_width_m"],
                climb["gate_start_wkt"],
                climb["gate_end_wkt"],
                Json(climb["canonical_profile"]),
                climb["length_m"],
                climb["vert_m"],
                climb["avg_gradient_pct"],
                climb.get("max_gradient_pct"),
                climb["worthiness_score"],
                climb["confidence"],
                climb["dem_source"],
                climb["compiler_version"],
                climb["osm_way_refs"],
                climb["odbl_source"],
                climb.get("odbl_extract_at"),
                Json(climb["provenance"]),
                climb["low_confidence_flags"],
                climb.get("ratified_by"),
                climb["ratified_at"],
            ),
        )
        canon_row = cursor.fetchone()
        if canon_row is None:
            raise RuntimeError("canon climb insert returned no row")
        canon_climb_id = canon_row[0]

        cursor.execute(
            "DELETE FROM public.canon_corridor_cells WHERE canon_climb_id = %s",
            (canon_climb_id,),
        )
        for cell in corridor_cells:
            cursor.execute(
                """
                INSERT INTO public.canon_corridor_cells (
                    canon_climb_id,
                    h3_resolution,
                    tile_id,
                    coverage_role
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    canon_climb_id,
                    cell["h3_resolution"],
                    cell["tile_id"],
                    cell["coverage_role"],
                ),
            )
        registration_artifact = build_canon_registration_artifact(
            {
                "id": canon_row[0],
                "canon_id": canon_row[1],
                "version": canon_row[2],
                "status": canon_row[3],
                "supersedes_climb_id": predecessor_id,
                "record_continuity_policy": record_continuity_policy,
                "display_name": climb["display_name"],
                "canonical_profile": climb["canonical_profile"],
                "length_m": climb["length_m"],
                "vert_m": climb["vert_m"],
                "avg_gradient_pct": climb["avg_gradient_pct"],
                "provenance": climb["provenance"],
            }
        )
        conn.commit()
        return {
            "canon_climb_id": str(canon_row[0]),
            "canon_id": str(canon_row[1]),
            "version": canon_row[2],
            "status": canon_row[3],
            "corridor_cell_count": len(corridor_cells),
            "registration_artifact": registration_artifact,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()
