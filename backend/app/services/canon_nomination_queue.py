"""Privacy-bounded detector evidence for the dev-only ClimbLab queue.

Detector output may nominate a place for human/compiler review, but it never
becomes canon or economic authority through this module. Aggregation happens in
Postgres so rider-, wallet-, activity-, and sample-level evidence never crosses
the response boundary.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any, Callable


_FINGERPRINT_DOMAIN = b"climblab-detector-nomination-v1\0"


def _candidate_fingerprint(
    signature_v2_hex: str,
    coarse_h3_cell: str,
) -> str:
    signature_bytes = signature_v2_hex.lower().encode("ascii")
    cell_bytes = coarse_h3_cell.lower().encode("ascii")
    return hashlib.sha256(
        _FINGERPRINT_DOMAIN
        + len(signature_bytes).to_bytes(2, "big")
        + signature_bytes
        + len(cell_bytes).to_bytes(2, "big")
        + cell_bytes
    ).hexdigest()


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def load_canon_nomination_queue(
    *,
    connection_factory: Callable[[], Any],
    min_distinct_activities: int = 2,
    min_independent_riders: int = 2,
    limit: int = 50,
) -> dict[str, Any]:
    """Return aggregate-only detector nominations for ClimbLab review.

    The signature used for grouping stays inside Postgres/Python and is replaced
    by a domain-separated hash before the payload is assembled. The output is a
    discovery queue only; canon publication still requires the existing
    compiler, review, and ratification flow.
    """

    if not 1 <= min_distinct_activities <= 1_000:
        raise ValueError("min_distinct_activities must be between 1 and 1000")
    if not 2 <= min_independent_riders <= 1_000:
        raise ValueError("min_independent_riders must be between 2 and 1000")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    connection = connection_factory()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH aggregated AS (
                    SELECT
                        lower(signature_v2_hex) AS detector_signature,
                        significance_cell_h3 AS coarse_h3_cell,
                        count(*)::integer AS evidence_count,
                        count(DISTINCT activity_id)::integer
                            AS distinct_activity_count,
                        count(DISTINCT wallet)::integer
                            AS independent_rider_count,
                        avg(vert_m)::double precision AS avg_vert_m,
                        avg(distance_m)::double precision AS avg_distance_m,
                        avg(avg_gradient_pct)::double precision
                            AS avg_gradient_pct,
                        max(significance_percentile)::double precision
                            AS max_significance_percentile,
                        min(created_at) AS first_observed_at,
                        max(created_at) AS last_observed_at,
                        array_agg(DISTINCT detector_version ORDER BY detector_version)
                            FILTER (WHERE detector_version IS NOT NULL)
                            AS detector_versions
                    FROM public.patterns_climb
                    WHERE signature_v2_hex ~* '^[0-9a-f]{128}$'
                      AND significance_cell_h3 ~* '^[0-9a-f]{15}$'
                      AND economic_eligible IS FALSE
                      AND abstention_reasons
                          @> ARRAY['MATCH:canon_traversal_required']::text[]
                      AND NOT (
                          COALESCE(match_trace, '{}'::jsonb)
                          ?& ARRAY['registry_id', 'canon_id', 'canon_version']
                      )
                    GROUP BY lower(signature_v2_hex), significance_cell_h3
                    HAVING count(DISTINCT activity_id) >= %s
                       AND count(DISTINCT wallet) >= %s
                )
                SELECT
                    detector_signature,
                    coarse_h3_cell,
                    evidence_count,
                    distinct_activity_count,
                    independent_rider_count,
                    avg_vert_m,
                    avg_distance_m,
                    avg_gradient_pct,
                    max_significance_percentile,
                    first_observed_at,
                    last_observed_at,
                    detector_versions
                FROM aggregated
                ORDER BY
                    distinct_activity_count DESC,
                    independent_rider_count DESC,
                    evidence_count DESC,
                    detector_signature ASC
                LIMIT %s
                """,
                (min_distinct_activities, min_independent_riders, limit),
            )
            rows = cursor.fetchall()
    finally:
        connection.close()

    candidates = []
    for row in rows:
        (
            detector_signature,
            coarse_h3_cell,
            evidence_count,
            distinct_activity_count,
            independent_rider_count,
            avg_vert_m,
            avg_distance_m,
            avg_gradient_pct,
            max_significance_percentile,
            first_observed_at,
            last_observed_at,
            detector_versions,
        ) = row
        candidates.append(
            {
                "candidate_fingerprint": _candidate_fingerprint(
                    detector_signature,
                    coarse_h3_cell,
                ),
                "coarse_h3_cell": str(coarse_h3_cell).lower(),
                "h3_resolution": 5,
                "evidence_count": int(evidence_count),
                "distinct_activity_count": int(distinct_activity_count),
                "independent_rider_count": int(independent_rider_count),
                "avg_vert_m": _optional_float(avg_vert_m),
                "avg_distance_m": _optional_float(avg_distance_m),
                "avg_gradient_pct": _optional_float(avg_gradient_pct),
                "max_significance_percentile": _optional_float(
                    max_significance_percentile
                ),
                "first_observed_at": _isoformat(first_observed_at),
                "last_observed_at": _isoformat(last_observed_at),
                "detector_versions": sorted(
                    str(version) for version in (detector_versions or []) if version
                ),
            }
        )

    return {
        "schema_version": "climblab_canon_nomination_queue_v1",
        "authority": "discovery_only",
        "privacy_contract": {
            "aggregation": "server_side",
            "rider_identifiers": "omitted",
            "activity_identifiers": "omitted",
            "raw_detector_signatures": "omitted",
            "sample_detail": "omitted",
        },
        "minimum_distinct_activity_count": min_distinct_activities,
        "minimum_independent_rider_count": min_independent_riders,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
