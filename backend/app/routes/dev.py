"""
Dev/Debug endpoints for tile visualization and testing.

These endpoints are for development only and should be disabled in production.
"""

from __future__ import annotations

import h3
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import UUID, uuid4

import psycopg2

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Tuple

from .admin import require_admin
from ..services.canon_climb_publisher import publish_canon_climb_payload_to_db
from ..services.canon_nomination_queue import load_canon_nomination_queue
from ..services.tile_service import TileService
from ..services.pattern_engine import PatternEngine, UserProfile
from ..services.patterns.climb import ClimbPatternDetector, detect_climbs_with_rust
from ..services.patterns.steady import SteadyPatternDetector
from ..services.patterns.exploration import ExplorationPatternDetector, ExplorationConfig
from ..services.gps_track_repair import evaluate_climb_source_quality, pattern_quality_kwargs
from ..services.ride_parser import _parse_fit, _parse_gpx
from ..services.climb_vault import ClimbVaultService
from ..repositories import PatternRepository, create_supabase_repository
from ..services.climb_lab import (
    apply_climb_lab_review_action,
    build_climb_lab_bounded_scan_summary,
    build_climb_lab_candidate_pipeline_summary,
    build_climb_lab_candidate_review_summary,
    build_climb_lab_review_candidate_map_detail,
    build_climb_lab_review_state_summary,
    build_climb_lab_calibration_inventory,
    build_climb_lab_corpus_summary,
    build_climb_lab_elevation_signal_summary,
    build_climb_lab_road_graph_summary,
    build_climb_lab_road_edge_signal_summary,
    find_climb_lab_review_candidate,
    load_climb_lab_compiler_candidate_summary,
    record_climb_lab_review_decision,
)
from .dev_climb_lab import CLIMB_LAB_HTML, CLIMB_LAB_REVIEW_HTML
from .dev_dashboard_v3 import DASHBOARD_HTML_V3
from ..utils.polyline import decode_gps_track

logger = logging.getLogger(__name__)
# Ensure logger outputs INFO level
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s - %(message)s')

# Initialize vault service for dev endpoints
_vault_service = None

def get_vault_service():
    global _vault_service
    if _vault_service is None:
        try:
            repo = create_supabase_repository()
            if hasattr(repo, 'client'):
                _vault_service = ClimbVaultService(repo.client)
        except Exception as e:
            logger.warning(f"Could not initialize vault service: {e}")
    return _vault_service

router = APIRouter(prefix="/dev", tags=["dev"])

tile_service = TileService()
pattern_engine = PatternEngine()

CLIMB_BACKFILL_REVIEW_TABLE = "ride_climb_backfill_reviews"
TERMINAL_ZERO_CLIMB_BACKFILL_OUTCOMES = {
    "no_canonical_climb",
    "missing_gps_track",
    "gps_decode_failed",
    "tile_projection_failed",
}


class ClimbLabReviewActionRequest(BaseModel):
    note: Optional[str] = None


class ClimbLabReviewDecisionRequest(BaseModel):
    decision: str
    note: Optional[str] = None


def _current_climb_detector_algorithm() -> str:
    return os.getenv("CLIMB_ALGORITHM", "canonical_v2").strip().lower() or "canonical_v2"


def _unique_activity_ids(*activity_id_groups: List[str]) -> List[str]:
    seen = set()
    activity_ids: List[str] = []
    for group in activity_id_groups:
        for activity_id in group:
            if activity_id and activity_id not in seen:
                seen.add(activity_id)
                activity_ids.append(activity_id)
    return activity_ids


def _find_activities_with_incomplete_climb_patterns(client) -> List[str]:
    result = client.table("patterns_climb")\
        .select("activity_id")\
        .is_("distance_m", "null")\
        .execute()
    return _unique_activity_ids([r["activity_id"] for r in result.data or []])


def _find_high_gain_zero_climb_activities(
    client,
    *,
    min_elevation_gain_m: float = 50.0,
    scan_limit: int = 250,
    detector_algorithm: Optional[str] = None,
) -> List[str]:
    """Find rides that need climb insertion, not just climb-row repair."""
    detector_algorithm = detector_algorithm or _current_climb_detector_algorithm()
    ride_result = client.table("rides")\
        .select("id, elevation_gain_m")\
        .gte("elevation_gain_m", min_elevation_gain_m)\
        .eq("processing_status", "completed")\
        .order("uploaded_at")\
        .limit(scan_limit)\
        .execute()

    candidate_ids = [str(row["id"]) for row in ride_result.data or [] if row.get("id")]
    if not candidate_ids:
        return []

    existing_result = client.table("patterns_climb")\
        .select("activity_id")\
        .in_("activity_id", candidate_ids)\
        .execute()
    existing_activity_ids = {
        str(row["activity_id"])
        for row in existing_result.data or []
        if row.get("activity_id")
    }
    missing_climb_ids = [
        activity_id for activity_id in candidate_ids if activity_id not in existing_activity_ids
    ]
    if not missing_climb_ids:
        return []

    reviewed_activity_ids = _find_reviewed_terminal_climb_backfill_activities(
        client,
        missing_climb_ids,
        detector_algorithm=detector_algorithm,
    )
    return [
        activity_id
        for activity_id in missing_climb_ids
        if activity_id not in reviewed_activity_ids
    ]


def _find_reviewed_terminal_climb_backfill_activities(
    client,
    activity_ids: List[str],
    *,
    detector_algorithm: str,
) -> set[str]:
    if not activity_ids:
        return set()

    try:
        result = client.table(CLIMB_BACKFILL_REVIEW_TABLE)\
            .select("activity_id")\
            .in_("activity_id", activity_ids)\
            .eq("detector_algorithm", detector_algorithm)\
            .eq("status", "reviewed")\
            .in_("outcome", sorted(TERMINAL_ZERO_CLIMB_BACKFILL_OUTCOMES))\
            .execute()
    except Exception as exc:
        logger.warning(
            "[Backfill] Could not read %s; zero-climb selector will not exclude reviewed rides: %s",
            CLIMB_BACKFILL_REVIEW_TABLE,
            exc,
        )
        return set()

    return {
        str(row["activity_id"])
        for row in result.data or []
        if row.get("activity_id")
    }


def _record_climb_backfill_review(
    client,
    *,
    activity_id: str,
    detector_algorithm: str,
    outcome: str,
    reviewed_by: Optional[str],
    details: Dict,
) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "activity_id": activity_id,
        "detector_algorithm": detector_algorithm,
        "outcome": outcome,
        "status": "reviewed",
        "reviewed_by": reviewed_by,
        "reviewed_at": now,
        "details": details,
        "updated_at": now,
    }
    try:
        client.table(CLIMB_BACKFILL_REVIEW_TABLE)\
            .upsert(payload, on_conflict="activity_id,detector_algorithm")\
            .execute()
        return True
    except Exception as exc:
        logger.warning(
            "[Backfill] Could not record %s outcome for activity %s: %s",
            outcome,
            activity_id,
            exc,
        )
        return False


def _build_backfilled_climb_pattern_kwargs(
    *,
    activity_id: UUID,
    wallet: str,
    climb,
    detector_version: str,
    source_samples: Optional[List[Dict]] = None,
) -> Dict:
    payload = {
        "pattern_id": uuid4(),
        "activity_id": activity_id,
        "wallet": wallet,
        "vert_m": climb.vert_m,
        "time_s": climb.time_s,
        "start_offset_s": climb.start_time_offset_s,
        "end_offset_s": climb.end_time_offset_s,
        "avg_power_w": getattr(climb, "avg_power_w", None),
        "w_per_kg": getattr(climb, "w_per_kg", None),
        "avg_hr": getattr(climb, "avg_hr", None),
        "tile_ids": climb.tile_ids,
        "distance_m": climb.distance_m,
        "avg_gradient_pct": climb.avg_gradient_pct,
        "signature_hex": climb.signature_hex,
        "signature_v2_hex": getattr(climb, "signature_v2_hex", None),
        "persistence_m": getattr(climb, "persistence", None),
        "start_lat": getattr(climb, "start_lat", None),
        "start_lon": getattr(climb, "start_lon", None),
        "end_lat": getattr(climb, "end_lat", None),
        "end_lon": getattr(climb, "end_lon", None),
        "detector_version": detector_version,
    }
    if source_samples is not None:
        payload.update(
            pattern_quality_kwargs(
                climb,
                source_samples,
                context=f"dev_backfill:{detector_version}",
            )
        )
    return payload


def _score_backfill_climb_match(existing_pattern: Dict, new_climb) -> float:
    existing_start = float(existing_pattern.get("start_offset_s") or 0)
    existing_end = float(existing_pattern.get("end_offset_s") or 0)
    existing_vert = float(existing_pattern.get("vert_m") or 0)
    new_start = float(getattr(new_climb, "start_time_offset_s", 0) or 0)
    new_end = float(getattr(new_climb, "end_time_offset_s", 0) or 0)
    new_vert = float(getattr(new_climb, "vert_m", 0) or 0)

    time_diff = abs(new_start - existing_start) + abs(new_end - existing_end)
    vert_diff = abs(new_vert - existing_vert)
    base_score = time_diff + vert_diff * 10

    overlap_s = max(0.0, min(existing_end, new_end) - max(existing_start, new_start))
    existing_duration = max(1.0, existing_end - existing_start)
    new_duration = max(1.0, new_end - new_start)
    overlap_ratio = overlap_s / min(existing_duration, new_duration)
    if overlap_ratio >= 0.65:
        return min(base_score, (1.0 - overlap_ratio) * 200 + vert_diff * 4)
    return base_score


async def _insert_backfilled_climb_patterns(
    *,
    pattern_repo: PatternRepository,
    activity_id: UUID,
    wallet: str,
    climbs: List,
    detector_version: str,
    source_samples: Optional[List[Dict]] = None,
) -> int:
    inserted = 0
    for climb in climbs:
        await pattern_repo.store_climb_pattern(
            **_build_backfilled_climb_pattern_kwargs(
                activity_id=activity_id,
                wallet=wallet,
                climb=climb,
                detector_version=detector_version,
                source_samples=source_samples,
            )
        )
        inserted += 1
    return inserted


def _get_db_connection():
    """Get database connection using DATABASE_URL or fallback."""
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return psycopg2.connect(database_url)
    required = ["DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required DB env vars: {', '.join(missing)}")
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )


def attribute_climb_to_road(tile_ids: List[str]) -> Dict:
    """
    Attribute a climb segment to road(s) from OSM data.

    Scores roads by coverage and contiguity, returns the best match(es)
    with hyphenated naming for multi-road climbs.

    Args:
        tile_ids: List of H3 tile IDs from the climb segment (in order)

    Returns:
        Dict with road_name, road_grade, road_coverage_pct, or empty dict if no match
    """
    if not tile_ids:
        return {}

    try:
        conn = _get_db_connection()
        cursor = conn.cursor()

        # Find all roads that touch these climb tiles
        placeholders = ",".join(["%s"] * len(tile_ids))
        cursor.execute(f"""
            SELECT rf.id, rf.name, rf.road_class, rf.grade,
                   COUNT(*) as tile_count
            FROM tile_features tf
            JOIN road_features rf ON tf.road_feature_id = rf.id
            WHERE tf.tile_id IN ({placeholders})
            AND rf.name IS NOT NULL
            AND rf.name != ''
            GROUP BY rf.id, rf.name, rf.road_class, rf.grade
            ORDER BY tile_count DESC
        """, tile_ids)

        roads = cursor.fetchall()
        conn.close()

        if not roads:
            return {}

        # Road class weights (prefer named/important roads)
        CLASS_WEIGHTS = {
            'Primary': 1.5,
            'Secondary': 1.3,
            'Tertiary': 1.1,
            'Residential': 1.0,
            'Cycleway': 1.2,
            'Path': 0.8,
            'Service': 0.5,
        }

        # Score each road
        scored_roads = []
        total_tiles = len(tile_ids)
        tile_set = set(tile_ids)

        for road_id, name, road_class, grade, tile_count in roads:
            coverage = tile_count / total_tiles
            class_weight = CLASS_WEIGHTS.get(road_class, 1.0)

            # Calculate contiguity bonus (how consecutive are the tiles?)
            # For simplicity, use coverage as proxy (higher coverage = more contiguous)
            contiguity_bonus = 1 + (coverage * 0.5)

            score = coverage * class_weight * contiguity_bonus

            scored_roads.append({
                'name': name,
                'road_class': road_class,
                'grade': grade,
                'tile_count': tile_count,
                'coverage': coverage,
                'score': score,
            })

        # Sort by score descending
        scored_roads.sort(key=lambda r: -r['score'])

        primary = scored_roads[0]
        result = {
            'road_name': primary['name'],
            'road_grade': primary['grade'],
            'road_coverage_pct': round(primary['coverage'] * 100, 1),
        }

        # Check for significant secondary road (for hyphenated name)
        if len(scored_roads) > 1:
            secondary = scored_roads[1]
            # If secondary has >40% of primary's score and different name, include it
            if (secondary['score'] > primary['score'] * 0.4
                and secondary['coverage'] > 0.15
                and secondary['name'] != primary['name']):  # Don't hyphenate same road
                # Hyphenate: Primary-Secondary
                result['road_name'] = f"{primary['name']}-{secondary['name']}"
                result['road_coverage_pct'] = round(
                    (primary['coverage'] + secondary['coverage']) * 100, 1
                )

        return result

    except Exception as e:
        logger.warning(f"Road attribution failed: {e}")
        return {}

try:
    import workout_parse as _rust_wp
except Exception:  # pragma: no cover - optional dev dependency
    _rust_wp = None


def _use_rust_parser() -> bool:
    return os.getenv("USE_RUST_PARSER", "false").lower() == "true" and _rust_wp is not None


def _gps_points_from_rust_bytes(content: bytes) -> list[dict]:
    activity = _rust_wp.parse_bytes(content)

    time_ms = activity.time_ms
    lat_e7 = activity.lat_e7
    lon_e7 = activity.lon_e7
    elev_m = getattr(activity, "elevation_m", None)
    pwr_w = activity.pwr_w
    hr_bpm = activity.hr_bpm
    speed_mps = activity.speed_mps

    if lat_e7 is None or lon_e7 is None:
        return []

    gps_points: list[dict] = []
    for i in range(len(time_ms)):
        if lat_e7[i] == _rust_wp.MISSING_I32 or lon_e7[i] == _rust_wp.MISSING_I32:
            continue

        gps_points.append(
            {
                "lat": lat_e7[i] / 1e7,
                "lon": lon_e7[i] / 1e7,
                "elevation_m": float(elev_m[i]) if elev_m is not None else None,
                "power_w": int(pwr_w[i]) if pwr_w is not None and pwr_w[i] != _rust_wp.MISSING_U16 else None,
                "hr_bpm": int(hr_bpm[i]) if hr_bpm is not None and hr_bpm[i] != _rust_wp.MISSING_U8 else None,
                "speed_mps": float(speed_mps[i]) if speed_mps is not None and speed_mps[i] > 0 else None,
                "timestamp": datetime.fromtimestamp(time_ms[i] / 1000, tz=timezone.utc),
            }
        )

    return gps_points


def _gps_points_from_parsed_ride(parsed) -> list[dict]:
    gps_points = []
    for rec in parsed.records:
        if rec.lat is not None and rec.lon is not None:
            gps_points.append(
                {
                    "lat": rec.lat,
                    "lon": rec.lon,
                    "elevation_m": rec.elevation_m,
                    "power_w": rec.power_w,
                    "hr_bpm": rec.heart_rate_bpm,
                    "speed_mps": rec.speed_mps,
                    "timestamp": rec.timestamp,
                }
            )
    return gps_points


class TileProjectionRequest(BaseModel):
    """Request for projecting GPS points to tiles."""
    points: List[Dict]  # List of {lat, lon, elevation_m?, power_w?, hr_bpm?, timestamp?}
    resolution: int = 10


class TileProjectionResponse(BaseModel):
    """Response with projected tiles."""
    tiles: List[Dict]
    unique_tile_count: int
    total_samples: int
    bounds: Dict  # {min_lat, max_lat, min_lon, max_lon}


class PatternDetectionRequest(BaseModel):
    """Request for detecting patterns from GPS points."""
    points: List[Dict]
    wallet: str = "dev-test-wallet"
    weight_kg: Optional[float] = 70.0
    ftp_w: Optional[int] = 250
    resolution: int = 10


class PatternDetectionResponse(BaseModel):
    """Response with detected patterns."""
    tile_count: int
    patterns: Dict
    summary: str


class ThresholdsConfig(BaseModel):
    """Configurable thresholds for pattern detection."""
    climb_vert_min_m: float = 50
    climb_time_min_s: int = 120
    climb_time_max_s: int = 3600
    climb_drop_tolerance_m: float = 30
    climb_smoothing_window: int = 5
    climb_algorithm: str = "legacy"  # "legacy" or "momentum"
    climb_smart_trim: bool = False  # Use convolution kernels for boundary detection
    climb_generate_signatures: bool = True  # Generate 64-byte signatures for vault matching
    exploration_new_tile_min: int = 50
    steady_min_duration_s: int = 1200
    steady_power_cv_max: float = 0.10


class RedetectRequest(BaseModel):
    """Request for re-running pattern detection with custom thresholds."""
    tile_samples: List[Dict]
    thresholds: ThresholdsConfig = ThresholdsConfig()
    wallet_tile_history: List[str] = []
    weight_kg: float = 70.0
    ftp_w: int = 250


@router.post("/tiles/redetect")
async def redetect_patterns(
    request: RedetectRequest,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Re-run pattern detection with custom thresholds.

    Allows testing different threshold configurations without re-uploading files.
    Returns patterns along with rejected segments for algorithm debugging.
    """
    if not request.tile_samples:
        raise HTTPException(status_code=400, detail="No tile samples provided")

    # Create climb detector with custom thresholds
    climb_detector = ClimbPatternDetector(
        vert_min_m=request.thresholds.climb_vert_min_m,
        time_min_s=request.thresholds.climb_time_min_s,
        time_max_s=request.thresholds.climb_time_max_s,
        drop_tolerance_m=request.thresholds.climb_drop_tolerance_m,
        smoothing_window=request.thresholds.climb_smoothing_window,
        algorithm=request.thresholds.climb_algorithm,
        smart_trim=request.thresholds.climb_smart_trim,
        generate_signatures=request.thresholds.climb_generate_signatures,
    )

    steady_detector = SteadyPatternDetector()

    exploration_config = ExplorationConfig(
        global_new_tiles_min=request.thresholds.exploration_new_tile_min,
    )
    exploration_detector = ExplorationPatternDetector(config=exploration_config)

    try:
        # Run climb detection with debug info
        climb_patterns, rejected_segments = climb_detector.detect_all_with_debug(
            tile_samples=request.tile_samples,
            user_weight_kg=request.weight_kg,
        )

        # Convert climbs to dict with debug info
        climb_patterns_dict = [c.to_dict() for c in climb_patterns]
        logger.warning(f"[REDETECT] Climb detection done: {len(climb_patterns)} climbs found")

        # Add road attribution to each climb pattern
        for climb in climb_patterns_dict:
            tile_ids = climb.get("tile_ids") or []
            if tile_ids:
                attribution = attribute_climb_to_road(tile_ids)
                if attribution:
                    climb["road_name"] = attribution.get("road_name")
                    climb["road_grade"] = attribution.get("road_grade")
                    climb["road_coverage_pct"] = attribution.get("road_coverage_pct")

        # Add vault matching for each climb pattern
        vault_service = get_vault_service()
        logger.warning(f"[VaultMatch] Service: {'initialized' if vault_service else 'NONE'}, climb_patterns: {len(climb_patterns)}")
        if vault_service:
            for i, (climb_pattern, climb_dict) in enumerate(zip(climb_patterns, climb_patterns_dict)):
                try:
                    logger.info(f"[VaultMatch] Climb {i}: vert={climb_pattern.vert_m:.0f}m, sig_hex={'yes' if climb_pattern.signature_hex else 'NO'}")
                    if climb_pattern.signature_hex:
                        matches = await vault_service.match_climb_pattern(
                            pattern=climb_pattern,
                            tile_samples=request.tile_samples,
                            min_similarity=0.5,
                        )
                        logger.info(f"[VaultMatch] Vault matches found: {len(matches)}")
                        if matches:
                            best = matches[0]
                            climb_dict["vault_match"] = {
                                "vault_climb_id": str(best.vault_climb.id),
                                "name": best.vault_climb.name,
                                "slug": best.vault_climb.slug,
                                "similarity": round(best.similarity, 2),
                                "is_strong_match": best.is_strong_match,
                            }
                            logger.info(f"[VaultMatch] MATCHED: {climb_pattern.vert_m:.0f}m -> {best.vault_climb.name} ({best.similarity:.0%})")
                except Exception as e:
                    logger.error(f"[VaultMatch] ERROR for climb {i}: {e}", exc_info=True)

        # Convert rejected segments to dict
        rejected_dict = [r.to_dict() for r in rejected_segments]

        # Run other pattern detectors using the pattern engine
        engine = PatternEngine(
            climb_detector=climb_detector,
            steady_detector=steady_detector,
            exploration_detector=exploration_detector,
        )

        user_profile = UserProfile(
            wallet="dev-test-wallet",
            weight_kg=request.weight_kg,
            ftp_w=request.ftp_w,
        )

        full_patterns = await engine.detect_patterns(
            activity_id=uuid4(),
            tile_samples=request.tile_samples,
            user_profile=user_profile,
            wallet_tile_history=set(request.wallet_tile_history),
        )

        # Build combined response with debug info
        patterns_dict = full_patterns.to_dict()
        # Replace climb_patterns with our debug-enhanced version
        patterns_dict["climb_patterns"] = climb_patterns_dict

        return {
            "patterns": patterns_dict,
            "rejected_segments": rejected_dict,
            "summary": full_patterns.summary(),
            "thresholds_used": request.thresholds.model_dump(),
            "_debug_vault": {
                "vault_service_initialized": vault_service is not None,
                "climb_count": len(climb_patterns),
                "climbs_with_signatures": sum(1 for c in climb_patterns if c.signature_hex),
            },
        }
    except Exception as e:
        logger.error(f"Redetect failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tiles/project", response_model=TileProjectionResponse)
async def project_tiles(
    request: TileProjectionRequest,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Project GPS points to H3 tiles.

    Returns tile IDs with boundaries for visualization.
    """
    if not request.points:
        raise HTTPException(status_code=400, detail="No GPS points provided")

    # Project to tiles
    tile_samples = tile_service.get_tile_sequence(
        gps_points=request.points,
        resolution=request.resolution,
    )

    # Get unique tiles with boundaries
    seen_tiles = set()
    tiles_with_bounds = []

    min_lat = min_lon = float('inf')
    max_lat = max_lon = float('-inf')

    for sample in tile_samples:
        # Track bounds
        min_lat = min(min_lat, sample.lat)
        max_lat = max(max_lat, sample.lat)
        min_lon = min(min_lon, sample.lon)
        max_lon = max(max_lon, sample.lon)

        if sample.tile_id not in seen_tiles:
            seen_tiles.add(sample.tile_id)

            # Get tile boundary
            boundary = tile_service.get_tile_boundary(sample.tile_id)
            center = tile_service.tile_to_lat_lng(sample.tile_id)

            tiles_with_bounds.append({
                "tile_id": sample.tile_id,
                "center": {"lat": center[0], "lon": center[1]},
                "boundary": [{"lat": b[0], "lon": b[1]} for b in boundary],
                "first_t": sample.t,
                "elevation_m": sample.elevation_m,
                "power_w": sample.power_w,
                "hr_bpm": sample.hr_bpm,
            })

    return TileProjectionResponse(
        tiles=tiles_with_bounds,
        unique_tile_count=len(seen_tiles),
        total_samples=len(tile_samples),
        bounds={
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        }
    )


@router.post("/tiles/upload")
async def upload_and_project(
    file: UploadFile = File(...),
    resolution: int = 10,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Upload a FIT or GPX file and project to H3 tiles.

    Returns tiles with boundaries and detected patterns.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = await file.read()
    filename_lower = file.filename.lower()

    parser_used = "python"
    try:
        if _use_rust_parser():
            gps_points = _gps_points_from_rust_bytes(content)
            parser_used = "rust"
        else:
            if filename_lower.endswith(".fit"):
                parsed = _parse_fit(content)
            elif filename_lower.endswith(".gpx"):
                parsed = _parse_gpx(content)
            else:
                raise HTTPException(
                    status_code=400,
                    detail="Unsupported file format. Use .fit or .gpx (or set USE_RUST_PARSER=true for .tcx)",
                )
            gps_points = _gps_points_from_parsed_ride(parsed)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to parse file: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    if not gps_points:
        raise HTTPException(status_code=400, detail="No GPS points found in file")

    # Project to tiles
    tile_samples = tile_service.get_tile_sequence(
        gps_points=gps_points,
        resolution=resolution,
    )

    # Get unique tiles with boundaries
    seen_tiles = set()
    tiles_with_bounds = []

    min_lat = min_lon = float('inf')
    max_lat = max_lon = float('-inf')

    for sample in tile_samples:
        min_lat = min(min_lat, sample.lat)
        max_lat = max(max_lat, sample.lat)
        min_lon = min(min_lon, sample.lon)
        max_lon = max(max_lon, sample.lon)

        if sample.tile_id not in seen_tiles:
            seen_tiles.add(sample.tile_id)

            boundary = tile_service.get_tile_boundary(sample.tile_id)
            center = tile_service.tile_to_lat_lng(sample.tile_id)

            tiles_with_bounds.append({
                "tile_id": sample.tile_id,
                "center": {"lat": center[0], "lon": center[1]},
                "boundary": [{"lat": b[0], "lon": b[1]} for b in boundary],
                "first_t": sample.t,
                "elevation_m": sample.elevation_m,
                "power_w": sample.power_w,
                "hr_bpm": sample.hr_bpm,
            })

    # Build GPS track for polyline (include elevation, power, HR for chart)
    gps_track = [
        {
            "lat": sample.lat,
            "lon": sample.lon,
            "t": sample.t,
            "elevation_m": sample.elevation_m,
            "power_w": sample.power_w,
            "hr_bpm": sample.hr_bpm,
        }
        for sample in tile_samples
    ]

    # Detect patterns (include lat/lon for distance calculation)
    tile_dicts = [
        {
            "tile_id": s.tile_id,
            "t": int(s.t),
            "elevation_m": s.elevation_m,
            "power_w": s.power_w,
            "hr_bpm": s.hr_bpm,
            "lat": s.lat,
            "lon": s.lon,
        }
        for s in tile_samples
    ]

    user_profile = UserProfile(
        wallet="dev-test-wallet",
        weight_kg=70.0,
        ftp_w=250,
    )

    try:
        patterns = await pattern_engine.detect_patterns(
            activity_id=uuid4(),
            tile_samples=tile_dicts,
            user_profile=user_profile,
            wallet_tile_history=set(),
        )
        patterns_dict = patterns.to_dict()

        # Add road attribution to each climb pattern
        for climb in patterns_dict.get("climb_patterns", []):
            tile_ids = climb.get("tile_ids") or []
            if tile_ids:
                attribution = attribute_climb_to_road(tile_ids)
                if attribution:
                    climb["road_name"] = attribution.get("road_name")
                    climb["road_grade"] = attribution.get("road_grade")
                    climb["road_coverage_pct"] = attribution.get("road_coverage_pct")

        pattern_summary = patterns.summary()
    except Exception as e:
        logger.error(f"Pattern detection failed: {e}")
        patterns_dict = {}
        pattern_summary = f"Detection failed: {str(e)}"

    return {
        "filename": file.filename,
        "parser": parser_used,
        "gps_point_count": len(gps_points),
        "tile_count": len(seen_tiles),
        "total_samples": len(tile_samples),
        "tiles": tiles_with_bounds,
        "gps_track": gps_track,
        "tile_samples": tile_dicts,  # Full tile samples for redetect
        "bounds": {
            "min_lat": min_lat,
            "max_lat": max_lat,
            "min_lon": min_lon,
            "max_lon": max_lon,
        },
        "patterns": patterns_dict,
        "pattern_summary": pattern_summary,
    }


@router.post("/tiles/upload-bulk")
async def upload_bulk(
    files: List[UploadFile] = File(...),
    resolution: int = 10,
    skip_patterns: bool = False,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Upload multiple FIT or GPX files and project all to H3 tiles.

    Returns aggregated tiles across all rides with per-file stats.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    all_tiles = set()  # Track unique tiles across all files
    all_tiles_with_bounds = []
    files_out: list[dict] = []

    global_min_lat = global_min_lon = float('inf')
    global_max_lat = global_max_lon = float('-inf')

    total_gps_points = 0
    total_patterns = {"climbs": 0, "steady": 0, "exploration": 0}

    for file in files:
        if not file.filename:
            continue

        content = await file.read()
        filename_lower = file.filename.lower()

        parser_used = "python"
        try:
            if _use_rust_parser():
                gps_points = _gps_points_from_rust_bytes(content)
                parser_used = "rust"
            else:
                if filename_lower.endswith(".fit"):
                    parsed = _parse_fit(content)
                elif filename_lower.endswith(".gpx"):
                    parsed = _parse_gpx(content)
                else:
                    files_out.append(
                        {
                            "filename": file.filename,
                            "status": "error",
                            "error": "Unsupported format",
                        }
                    )
                    continue
                gps_points = _gps_points_from_parsed_ride(parsed)
        except Exception as e:
            logger.error(f"Failed to parse {file.filename}: {e}")
            files_out.append({
                "filename": file.filename,
                "status": "error",
                "error": str(e)
            })
            continue

        if not gps_points:
            files_out.append({
                "filename": file.filename,
                "status": "error",
                "error": "No GPS points found"
            })
            continue

        total_gps_points += len(gps_points)

        # Project to tiles
        tile_samples = tile_service.get_tile_sequence(
            gps_points=gps_points,
            resolution=resolution,
        )

        # Track tiles and bounds
        file_tiles = set()
        file_min_lat = file_min_lon = float('inf')
        file_max_lat = file_max_lon = float('-inf')
        for sample in tile_samples:
            global_min_lat = min(global_min_lat, sample.lat)
            global_max_lat = max(global_max_lat, sample.lat)
            global_min_lon = min(global_min_lon, sample.lon)
            global_max_lon = max(global_max_lon, sample.lon)

            file_min_lat = min(file_min_lat, sample.lat)
            file_max_lat = max(file_max_lat, sample.lat)
            file_min_lon = min(file_min_lon, sample.lon)
            file_max_lon = max(file_max_lon, sample.lon)

            file_tiles.add(sample.tile_id)

            if sample.tile_id not in all_tiles:
                all_tiles.add(sample.tile_id)
                boundary = tile_service.get_tile_boundary(sample.tile_id)
                center = tile_service.tile_to_lat_lng(sample.tile_id)
                all_tiles_with_bounds.append({
                    "tile_id": sample.tile_id,
                    "center": {"lat": center[0], "lon": center[1]},
                    "boundary": [{"lat": b[0], "lon": b[1]} for b in boundary],
                })

        # Build GPS track for this file (include elevation for chart)
        gps_track = [
            {"lat": sample.lat, "lon": sample.lon, "t": sample.t, "elevation_m": sample.elevation_m}
            for sample in tile_samples
        ]

        # Build tile samples for detection/redetection
        tile_dicts = [
            {
                "tile_id": s.tile_id,
                "t": int(s.t),
                "elevation_m": s.elevation_m,
                "power_w": s.power_w,
                "hr_bpm": s.hr_bpm,
                "speed_mps": s.speed_mps,
            }
            for s in tile_samples
        ]

        sensor_coverage = {
            "total": len(tile_dicts),
            "elevation": len([s for s in tile_dicts if s.get("elevation_m") is not None]),
            "power": len([s for s in tile_dicts if s.get("power_w") is not None]),
            "hr": len([s for s in tile_dicts if s.get("hr_bpm") is not None]),
            "speed": len([s for s in tile_dicts if s.get("speed_mps") is not None]),
        }

        # Detect patterns (optional - can be slow for large files)
        pattern_summary = "Skipped"
        patterns_dict = None
        if not skip_patterns:
            user_profile = UserProfile(
                wallet="dev-test-wallet",
                weight_kg=70.0,
                ftp_w=250,
            )

            pattern_summary = "No patterns"
            try:
                patterns = await pattern_engine.detect_patterns(
                    activity_id=uuid4(),
                    tile_samples=tile_dicts,
                    user_profile=user_profile,
                    wallet_tile_history=set(),
                )
                patterns_dict = patterns.to_dict()
                pattern_summary = patterns.summary()

                # Aggregate pattern counts
                if patterns.climb_patterns:
                    total_patterns["climbs"] += len(patterns.climb_patterns)
                if patterns.steady_pattern:
                    total_patterns["steady"] += 1
                if patterns.exploration_pattern:
                    total_patterns["exploration"] += 1
            except Exception as e:
                logger.error(f"Pattern detection failed for {file.filename}: {e}")
                patterns_dict = None

        files_out.append({
            "filename": file.filename,
            "status": "success",
            "parser": parser_used,
            "gps_points": len(gps_points),
            "tiles": len(file_tiles),
            "total_samples": len(tile_samples),
            "bounds": {
                "min_lat": file_min_lat if file_min_lat != float("inf") else 0,
                "max_lat": file_max_lat if file_max_lat != float("-inf") else 0,
                "min_lon": file_min_lon if file_min_lon != float("inf") else 0,
                "max_lon": file_max_lon if file_max_lon != float("-inf") else 0,
            },
            "gps_track": gps_track,
            "tile_samples": tile_dicts,
            "sensor_coverage": sensor_coverage,
            "patterns": patterns_dict,
            "pattern_summary": pattern_summary,
        })

    return {
        "file_count": len(files),
        "successful_files": len([f for f in files_out if f.get("status") == "success"]),
        "total_gps_points": total_gps_points,
        "total_unique_tiles": len(all_tiles),
        "tiles": all_tiles_with_bounds,
        "files": files_out,
        "bounds": {
            "min_lat": global_min_lat if global_min_lat != float('inf') else 0,
            "max_lat": global_max_lat if global_max_lat != float('-inf') else 0,
            "min_lon": global_min_lon if global_min_lon != float('inf') else 0,
            "max_lon": global_max_lon if global_max_lon != float('-inf') else 0,
        },
        "total_patterns": total_patterns,
    }


@router.get("/tiles/dashboard", response_class=HTMLResponse)
async def tiles_dashboard():
    """Serve the tile visualization dashboard."""
    return DASHBOARD_HTML


@router.get("/tiles/dashboard-v3", response_class=HTMLResponse)
async def tiles_dashboard_v3():
    """Serve the modern tile visualization dashboard (v3)."""
    return DASHBOARD_HTML_V3


@router.get("/climb-lab", response_class=HTMLResponse)
async def climb_lab_dashboard():
    """Serve the isolated ClimbLab development workbench."""
    return CLIMB_LAB_HTML


@router.get("/climb-lab/review", response_class=HTMLResponse)
async def climb_lab_review_dashboard():
    """Serve the focused ClimbLab candidate review workbench."""
    return CLIMB_LAB_REVIEW_HTML


@router.get("/climb-lab/corpus")
async def climb_lab_corpus():
    """Return metadata-only activity corpus inventory for ClimbLab."""
    return build_climb_lab_corpus_summary()


@router.get("/climb-lab/calibration")
async def climb_lab_calibration(
    source_id: str = "garmin_device",
    limit: int = 18,
    offset: int = 0,
):
    """Return privacy-preserving ride-level summaries for ClimbLab calibration."""
    return build_climb_lab_calibration_inventory(
        source_id=source_id,
        limit=limit,
        offset=offset,
    )


@router.get("/climb-lab/elevation-signals")
async def climb_lab_elevation_signals(
    source_id: str = "garmin_device",
    file_limit: int = 18,
    signal_limit: int = 24,
    min_gain_m: float = 45,
):
    """Return privacy-preserving uphill interval summaries for ClimbLab."""
    return build_climb_lab_elevation_signal_summary(
        source_id=source_id,
        file_limit=file_limit,
        signal_limit=signal_limit,
        min_gain_m=min_gain_m,
    )


@router.get("/climb-lab/road-graph")
async def climb_lab_road_graph():
    """Return fixture road graph readiness for ClimbLab."""
    return build_climb_lab_road_graph_summary()


@router.get("/climb-lab/road-signals")
async def climb_lab_road_signals():
    """Return fixture road-edge climb signal summaries for ClimbLab."""
    return build_climb_lab_road_edge_signal_summary()


@router.get("/climb-lab/pipeline-results")
async def climb_lab_pipeline_results():
    """Return end-to-end fixture candidate pipeline results for ClimbLab."""
    return build_climb_lab_candidate_pipeline_summary()


@router.get("/climb-lab/nomination-queue")
async def climb_lab_nomination_queue(
    min_distinct_activities: int = 2,
    min_independent_riders: int = 2,
    limit: int = 50,
):
    """Return aggregate-only detector evidence for canon nomination review."""
    try:
        return load_canon_nomination_queue(
            connection_factory=_get_db_connection,
            min_distinct_activities=min_distinct_activities,
            min_independent_riders=min_independent_riders,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (RuntimeError, psycopg2.Error) as exc:
        logger.error("ClimbLab nomination queue unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="ClimbLab nomination queue is unavailable.",
        ) from exc


def _climb_lab_review_source_summary(
    *,
    preset: str,
    max_ways: int,
    max_candidates: int,
    max_elevation_nodes: int,
):
    compiler_summary = load_climb_lab_compiler_candidate_summary()
    if compiler_summary is not None:
        return compiler_summary
    return build_climb_lab_bounded_scan_summary(
        preset_id=preset,
        max_ways=max_ways,
        max_candidates=max_candidates,
        max_elevation_nodes=max_elevation_nodes,
    )


def _climb_lab_canon_db_publish_enabled() -> bool:
    return os.getenv("CLIMB_LAB_CANON_DB_PUBLISH_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _publish_canon_candidate_to_db(publish_payload: Dict) -> Dict:
    if not _climb_lab_canon_db_publish_enabled():
        raise RuntimeError(
            "Set CLIMB_LAB_CANON_DB_PUBLISH_ENABLED=true to publish canon candidates"
        )
    return publish_canon_climb_payload_to_db(
        publish_payload,
        connection_factory=_get_db_connection,
    )


@router.get("/climb-lab/scan-results")
async def climb_lab_scan_results(
    preset: str = "boulder_foothills_north",
    max_ways: int = 80,
    max_candidates: int = 16,
    max_elevation_nodes: int = 210,
):
    """Return bounded real-area candidate scan results for ClimbLab."""
    return build_climb_lab_bounded_scan_summary(
        preset_id=preset,
        max_ways=max_ways,
        max_candidates=max_candidates,
        max_elevation_nodes=max_elevation_nodes,
    )


@router.get("/climb-lab/review-candidates")
async def climb_lab_review_candidates(
    preset: str = "philadelphia_manayunk_wall",
    max_ways: int = 90,
    max_candidates: int = 18,
    max_elevation_nodes: int = 240,
):
    """Return the dev-only canon ratification review payload for ClimbLab."""
    try:
        source_summary = _climb_lab_review_source_summary(
            preset=preset,
            max_ways=max_ways,
            max_candidates=max_candidates,
            max_elevation_nodes=max_elevation_nodes,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_climb_lab_candidate_review_summary(source_summary)


@router.get("/climb-lab/review-state")
async def climb_lab_review_state():
    """Return persisted dev-only ClimbLab decisions for agent inspection."""
    return build_climb_lab_review_state_summary()


@router.get("/climb-lab/review-candidates/{candidate_id}/map-detail")
async def climb_lab_review_candidate_map_detail(
    candidate_id: str,
    preset: str = "philadelphia_manayunk_wall",
    max_ways: int = 90,
    max_candidates: int = 18,
    max_elevation_nodes: int = 240,
):
    """Return single-candidate map/profile detail for ClimbLab review."""
    try:
        source_summary = _climb_lab_review_source_summary(
            preset=preset,
            max_ways=max_ways,
            max_candidates=max_candidates,
            max_elevation_nodes=max_elevation_nodes,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    candidate = find_climb_lab_review_candidate(source_summary, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="ClimbLab review candidate not found")
    return build_climb_lab_review_candidate_map_detail(candidate)


@router.post("/climb-lab/review-candidates/{candidate_id}/decision")
async def climb_lab_review_candidate_decision(
    candidate_id: str,
    payload: ClimbLabReviewDecisionRequest,
    preset: str = "philadelphia_manayunk_wall",
    max_ways: int = 90,
    max_candidates: int = 18,
    max_elevation_nodes: int = 240,
):
    """Persist a reversible ClimbLab review decision without publishing rows."""
    try:
        source_summary = _climb_lab_review_source_summary(
            preset=preset,
            max_ways=max_ways,
            max_candidates=max_candidates,
            max_elevation_nodes=max_elevation_nodes,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    candidate = find_climb_lab_review_candidate(source_summary, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="ClimbLab review candidate not found")
    result = record_climb_lab_review_decision(
        candidate_id=candidate_id,
        decision=payload.decision,
        note=payload.note,
        candidate=candidate,
        reviewed_by="climb_lab_dev",
    )
    if result.get("status") == "rejected":
        raise HTTPException(status_code=400, detail=result)
    return result


@router.post("/climb-lab/review-candidates/{candidate_id}/actions/{action_id}")
async def climb_lab_review_candidate_action(
    candidate_id: str,
    action_id: str,
    payload: ClimbLabReviewActionRequest,
):
    """Record a ClimbLab review action and publish complete approvals."""
    source_summary = None
    candidate = None
    publisher = None
    if action_id == "approve":
        try:
            source_summary = load_climb_lab_compiler_candidate_summary()
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        candidate = find_climb_lab_review_candidate(source_summary, candidate_id)
        if candidate is not None and _climb_lab_canon_db_publish_enabled():
            publisher = _publish_canon_candidate_to_db

    result = apply_climb_lab_review_action(
        candidate_id=candidate_id,
        action_id=action_id,
        note=payload.note,
        candidate=candidate,
        publisher=publisher,
        ratified_by="climb_lab_dev",
    )
    if result.get("status") == "rejected":
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/tiles/roads")
async def get_roads_for_tiles(tile_ids: str):
    """
    Get road geometries that overlap with the given tiles.

    Returns road polylines reconstructed from tile centers.
    """
    tile_list = [t.strip() for t in tile_ids.split(",") if t.strip()]
    if not tile_list:
        return {"roads": []}

    try:
        conn = _get_db_connection()

        cursor = conn.cursor()

        # Find all roads that touch these tiles
        placeholders = ",".join(["%s"] * len(tile_list))
        cursor.execute(f"""
            SELECT DISTINCT rf.id, rf.name, rf.road_class, rf.grade, rf.length_m
            FROM tile_features tf
            JOIN road_features rf ON tf.road_feature_id = rf.id
            WHERE tf.tile_id IN ({placeholders})
            AND rf.name IS NOT NULL
            ORDER BY rf.length_m DESC
            LIMIT 50
        """, tile_list)

        roads_meta = cursor.fetchall()

        roads = []
        for road_id, name, road_class, grade, length_m in roads_meta:
            # Get all tiles for this road
            cursor.execute("""
                SELECT tile_id FROM tile_features
                WHERE road_feature_id = %s
                ORDER BY tile_id
            """, (road_id,))

            road_tiles = [row[0] for row in cursor.fetchall()]

            # Convert tiles to lat/lon coordinates
            coords = []
            for tile_id in road_tiles:
                try:
                    lat, lon = h3.cell_to_latlng(tile_id)
                    coords.append([lat, lon])
                except:
                    pass

            if len(coords) >= 2:
                roads.append({
                    "id": road_id,
                    "name": name,
                    "road_class": road_class,
                    "grade": grade,
                    "length_m": length_m,
                    "coords": coords
                })

        cursor.close()
        conn.close()

        return {"roads": roads}

    except Exception as e:
        logger.error(f"Error fetching roads: {e}")
        return {"roads": [], "error": str(e)}


@router.get("/tiles/attribution")
async def get_tile_attribution(tile_ids: str):
    """
    Get road attribution data for given tile IDs.

    Returns road name, class, and grade for each tile from the OSM database.
    """
    tile_list = [t.strip() for t in tile_ids.split(",") if t.strip()]
    if not tile_list:
        return {}

    result = {}

    try:
        conn = _get_db_connection()

        cursor = conn.cursor()

        for tile_id in tile_list:
            # Query road features for this tile
            cursor.execute("""
                SELECT rf.name, rf.road_class, rf.grade
                FROM tile_features tf
                JOIN road_features rf ON tf.road_feature_id = rf.id
                WHERE tf.tile_id = %s
                ORDER BY rf.length_m DESC
                LIMIT 1
            """, (tile_id,))

            row = cursor.fetchone()
            if row:
                result[tile_id] = {
                    "road_name": row[0],
                    "road_class": row[1],
                    "road_grade": row[2]
                }
            else:
                result[tile_id] = {}

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"Error fetching tile attribution: {e}")
        # Return empty results on error
        for tile_id in tile_list:
            result[tile_id] = {}

    return result


@router.get("/tiles/vault-climbs")
async def get_vault_climbs():
    """
    Get all active vault climbs for map overlay and browser.

    Returns climb metadata including bounds for drawing rectangles on map.
    """
    vault_service = get_vault_service()
    if not vault_service:
        return {"climbs": [], "error": "Vault service not initialized"}

    try:
        # Query all active climbs from vault (including tile sequence)
        result = vault_service.client.from_("climb_vault").select(
            "id, name, slug, description, region, "
            "bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon, "
            "h3_tile_ids, "
            "total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m, "
            "uci_category, difficulty_score, tags, source, featured"
        ).eq("active", True).order("total_vert_m", desc=True).execute()

        climbs = []
        for row in result.data:
            # Convert tile IDs to boundaries for map rendering
            tile_ids = row.get("h3_tile_ids") or []
            tiles_with_boundaries = []
            for tile_id in tile_ids:
                try:
                    boundary = h3.cell_to_boundary(tile_id)
                    tiles_with_boundaries.append({
                        "id": tile_id,
                        "boundary": [{"lat": lat, "lon": lng} for lat, lng in boundary]
                    })
                except Exception:
                    pass  # Skip invalid tile IDs

            climbs.append({
                "id": row["id"],
                "name": row["name"],
                "slug": row["slug"],
                "description": row.get("description"),
                "region": row.get("region"),
                "bounds": {
                    "min_lat": row["bounds_min_lat"],
                    "max_lat": row["bounds_max_lat"],
                    "min_lon": row["bounds_min_lon"],
                    "max_lon": row["bounds_max_lon"],
                },
                "tiles": tiles_with_boundaries,  # Canonical tile sequence with boundaries
                "tile_count": len(tile_ids),
                "stats": {
                    "vert_m": row["total_vert_m"],
                    "avg_gradient_pct": row["avg_gradient_pct"],
                    "max_gradient_pct": row["max_gradient_pct"],
                    "distance_m": row["distance_m"],
                },
                "category": row.get("uci_category", "UC"),
                "difficulty": row.get("difficulty_score"),
                "tags": row.get("tags", []),
                "source": row.get("source"),
                "featured": row.get("featured", False),
            })

        logger.info(f"[Vault] Returning {len(climbs)} vault climbs for dashboard")
        return {"climbs": climbs, "count": len(climbs)}

    except Exception as e:
        logger.error(f"Error fetching vault climbs: {e}")
        return {"climbs": [], "error": str(e)}


@router.patch("/tiles/vault-climbs/{climb_id}")
async def update_vault_climb(
    climb_id: str,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Update vault climb bounds (for manual editing via dashboard).

    Accepts bounds as a JSON object:
    {
        "bounds": {
            "min_lat": 40.0238,
            "max_lat": 40.0315,
            "min_lon": -75.2265,
            "max_lon": -75.2165
        }
    }
    """
    vault_service = get_vault_service()
    if not vault_service:
        return {"success": False, "error": "Vault service not initialized"}

    try:
        data = await request.json()
        update_fields = {}

        # Handle bounds update
        bounds = data.get("bounds")
        if bounds:
            if not all(k in bounds for k in ["min_lat", "max_lat", "min_lon", "max_lon"]):
                return {"success": False, "error": "Missing required bounds fields"}
            if bounds["min_lat"] >= bounds["max_lat"]:
                return {"success": False, "error": "min_lat must be less than max_lat"}
            if bounds["min_lon"] >= bounds["max_lon"]:
                return {"success": False, "error": "min_lon must be less than max_lon"}
            update_fields.update({
                "bounds_min_lat": bounds["min_lat"],
                "bounds_max_lat": bounds["max_lat"],
                "bounds_min_lon": bounds["min_lon"],
                "bounds_max_lon": bounds["max_lon"],
            })

        # Handle name update
        new_name = data.get("name")
        if new_name:
            new_name = new_name.strip()
            if new_name:
                update_fields["name"] = new_name
                # Also update slug
                new_slug = new_name.lower().replace(" ", "-").replace("'", "")
                update_fields["slug"] = new_slug

        if not update_fields:
            return {"success": False, "error": "No fields to update (provide 'bounds' or 'name')"}

        result = vault_service.client.from_("climb_vault").update(update_fields).eq("id", climb_id).execute()

        if result.data:
            logger.info(f"[Vault] Updated climb {climb_id}: {list(update_fields.keys())}")
            return {"success": True, "updated": result.data[0]}
        else:
            return {"success": False, "error": "Climb not found"}

    except Exception as e:
        logger.error(f"Error updating vault climb: {e}")
        return {"success": False, "error": str(e)}


@router.post("/tiles/vault-climbs")
async def create_vault_climb(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Create a new vault climb (from detected pattern or manual entry).

    Accepts climb data as JSON:
    {
        "name": "Climb Name",
        "bounds": {"min_lat": ..., "max_lat": ..., "min_lon": ..., "max_lon": ...},
        "stats": {"vert_m": 100, "avg_gradient_pct": 5.0, "max_gradient_pct": 12.0, "distance_m": 1500},
        "signature_hex": "optional...",
        "description": "optional description",
        "region": "Philadelphia",
        "tags": ["optional", "tags"]
    }
    """
    vault_service = get_vault_service()
    if not vault_service:
        return {"success": False, "error": "Vault service not initialized"}

    try:
        data = await request.json()

        # Validate required fields
        name = data.get("name", "").strip()
        if not name:
            return {"success": False, "error": "Name is required"}

        bounds = data.get("bounds", {})
        if not all(k in bounds for k in ["min_lat", "max_lat", "min_lon", "max_lon"]):
            return {"success": False, "error": "Bounds are required (min_lat, max_lat, min_lon, max_lon)"}

        stats = data.get("stats", {})
        tile_sequence = data.get("tile_sequence", [])
        logger.info(f"[Vault] Received tile_sequence with {len(tile_sequence)} tiles")

        # Generate slug from name
        slug = name.lower().replace(" ", "-").replace("'", "")

        # Check if slug already exists
        existing = vault_service.client.from_("climb_vault").select("id").eq("slug", slug).execute()
        if existing.data:
            return {"success": False, "error": f"A climb with slug '{slug}' already exists"}

        # Build the vault entry
        tile_sequence = data.get("tile_sequence", [])

        vault_entry = {
            "name": name,
            "slug": slug,
            "description": data.get("description", f"Climb added from dev dashboard"),
            "region": data.get("region", "Unknown"),
            "country_code": data.get("country_code", "US"),
            "bounds_min_lat": bounds["min_lat"],
            "bounds_max_lat": bounds["max_lat"],
            "bounds_min_lon": bounds["min_lon"],
            "bounds_max_lon": bounds["max_lon"],
            "h3_tile_ids": tile_sequence if tile_sequence else None,  # Canonical tile sequence
            "total_vert_m": stats.get("vert_m", 0),
            "avg_gradient_pct": stats.get("avg_gradient_pct", 0),
            "max_gradient_pct": stats.get("max_gradient_pct", 0),
            "distance_m": stats.get("distance_m", 0),
            "signature_hex": data.get("signature_hex") or "0" * 128,  # Placeholder if no signature
            "signature_tolerance": 0.55,
            "uci_category": "UC",
            "difficulty_score": stats.get("vert_m", 0) * (1 + abs(stats.get("avg_gradient_pct", 0)) / 10),
            "tags": data.get("tags", []),
            "source": "manual",  # Use 'manual' as valid source enum value
            "verified": False,
            "active": True,
            "featured": False,
        }

        logger.info(f"[Vault] h3_tile_ids being saved: {vault_entry.get('h3_tile_ids')}")
        logger.info(f"[Vault] Full vault_entry: {vault_entry}")

        result = vault_service.client.from_("climb_vault").insert(vault_entry).execute()

        if result.data:
            logger.info(f"[Vault] Created new climb: {name} (slug: {slug})")
            return {"success": True, "created": result.data[0]}
        else:
            return {"success": False, "error": "Failed to create climb"}

    except Exception as e:
        logger.error(f"Error creating vault climb: {e}")
        return {"success": False, "error": str(e)}


@router.get("/patterns/{activity_id}")
async def debug_patterns(activity_id: str):
    """
    Debug endpoint to check patterns for an activity without auth.
    Returns the same data as /rides/{id}/patterns but skips authorization.
    """
    try:
        repo = create_supabase_repository()
        patterns = await repo.get_patterns_for_activity(UUID(activity_id))

        # Enrich climb patterns (same logic as routes/rides.py)
        if patterns.get("climb_patterns"):
            from ..services.canon_traversal import authoritative_canon_climb_id

            for climb in patterns["climb_patterns"]:
                canon_registry_id = authoritative_canon_climb_id(climb)
                if canon_registry_id:
                    climb["climbId"] = canon_registry_id
                vert_m = climb.get("vert_m", 0)
                time_s = climb.get("time_s", 0)
                climb["duration_s"] = time_s
                if time_s > 0:
                    climb["vam"] = round(vert_m / time_s * 3600, 1)
                else:
                    climb["vam"] = 0
                if not climb.get("name") and not climb.get("road_name"):
                    climb["name"] = f"Climb ({vert_m}m)"

        # Calculate summary
        summary_parts = []
        if patterns.get("climb_patterns"):
            total_vert = sum(p.get("vert_m", 0) for p in patterns["climb_patterns"])
            summary_parts.append(f"{int(total_vert)}m climbed")
        if patterns.get("steady_pattern"):
            mins = patterns["steady_pattern"].get("duration_s", 0) // 60
            summary_parts.append(f"{mins}min steady")
        if patterns.get("exploration_pattern"):
            new_tiles = patterns["exploration_pattern"].get("new_tiles_wallet", 0)
            summary_parts.append(f"{new_tiles} new areas explored")

        return {
            "ride_id": activity_id,
            "patterns": patterns,
            "summary": ", ".join(summary_parts) if summary_parts else "No patterns detected",
            "total_count": (
                len(patterns.get("climb_patterns", []))
                + (1 if patterns.get("steady_pattern") else 0)
                + (1 if patterns.get("exploration_pattern") else 0)
            ),
        }
    except Exception as e:
        logger.error(f"Error getting patterns for {activity_id}: {e}")
        return {"error": str(e)}


@router.post("/patterns/backfill/{activity_id}")
async def backfill_climb_patterns(
    activity_id: str,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Backfill missing distance_m, avg_gradient_pct, and tile_ids for climb patterns.

    This endpoint:
    1. Fetches existing patterns_climb rows for the activity
    2. Loads gps_track (polyline encoded) from rides table
    3. Decodes to GPS records with accurate lat/lon
    4. Projects to tiles using TileService.get_tile_run_sequence()
    5. Re-runs climb detection using Rust detector with accurate GPS data
    6. Updates the patterns_climb rows with the new data

    Use this to fix rides processed before the distance/gradient fields were added.
    """
    try:
        repo = create_supabase_repository()

        activity_uuid = UUID(activity_id)
        detector_algorithm = _current_climb_detector_algorithm()

        # 1. Get existing climb patterns for this activity. Zero existing rows is
        # a repair target, not a terminal condition.
        patterns = await repo.get_patterns_for_activity(UUID(activity_id))
        climb_patterns = patterns.get("climb_patterns", [])

        # 2. Fetch gps_track from rides table
        result = repo._client.table("rides")\
            .select("gps_track, started_at, user_id")\
            .eq("id", activity_id)\
            .single()\
            .execute()

        ride_data = result.data
        if not ride_data or not ride_data.get("gps_track"):
            review_recorded = False
            if not climb_patterns:
                review_recorded = _record_climb_backfill_review(
                    repo._client,
                    activity_id=activity_id,
                    detector_algorithm=detector_algorithm,
                    outcome="missing_gps_track",
                    reviewed_by=admin_ctx[1],
                    details={"reason": "rides.gps_track missing or empty"},
                )
            return {
                "success": False,
                "message": "No GPS track found for this activity",
                "review_outcome": "missing_gps_track" if not climb_patterns else None,
                "review_recorded": review_recorded,
            }

        wallet = next((p.get("wallet") for p in climb_patterns if p.get("wallet")), None)
        if not wallet and ride_data.get("user_id"):
            user_result = repo._client.table("users")\
                .select("wallet")\
                .eq("id", ride_data["user_id"])\
                .limit(1)\
                .execute()
            user_rows = user_result.data or []
            wallet = user_rows[0].get("wallet") if user_rows else None

        if not wallet:
            return {"success": False, "message": "Could not resolve ride wallet for climb backfill"}

        # 3. Decode GPS track from polyline format
        gps_track = ride_data["gps_track"]
        gps_points = decode_gps_track(gps_track)

        if not gps_points:
            review_recorded = False
            if not climb_patterns:
                review_recorded = _record_climb_backfill_review(
                    repo._client,
                    activity_id=activity_id,
                    detector_algorithm=detector_algorithm,
                    outcome="gps_decode_failed",
                    reviewed_by=admin_ctx[1],
                    details={"reason": "decode_gps_track returned no points"},
                )
            return {
                "success": False,
                "message": "Could not decode GPS track",
                "review_outcome": "gps_decode_failed" if not climb_patterns else None,
                "review_recorded": review_recorded,
            }

        logger.info(f"[Backfill] Activity {activity_id}: Decoded {len(gps_points)} GPS points from polyline")

        # 4. Project GPS points to tiles using TileService (same as fresh uploads)
        # Decoded polyline timestamps are already ride-relative offsets. For
        # legacy absolute timestamps, TileService can normalize from the first
        # sample, so do not subtract rides.started_at a second time here.
        tiles_mem = tile_service.get_tile_run_sequence(
            points=gps_points,
            resolution=TileService.DEFAULT_RESOLUTION,
            start_time=None,
        )

        if not tiles_mem:
            review_recorded = False
            if not climb_patterns:
                review_recorded = _record_climb_backfill_review(
                    repo._client,
                    activity_id=activity_id,
                    detector_algorithm=detector_algorithm,
                    outcome="tile_projection_failed",
                    reviewed_by=admin_ctx[1],
                    details={"reason": "tile projection returned no samples", "gps_points": len(gps_points)},
                )
            return {
                "success": False,
                "message": "Could not project GPS track to tiles",
                "review_outcome": "tile_projection_failed" if not climb_patterns else None,
                "review_recorded": review_recorded,
            }

        logger.info(f"[Backfill] Activity {activity_id}: Projected to {len(tiles_mem)} tile runs")

        # 5. Run climb detection using the production detector path. This must
        # not drift back to the old momentum-only repair path, because rides
        # with zero persisted climbs need the same persistence/canonical rescue
        # behavior as fresh uploads.
        new_climbs = detect_climbs_with_rust(
            tile_samples=tiles_mem,
            terrain="auto",
            user_weight_kg=75.0,  # Default weight
            algorithm=detector_algorithm,
            generate_signatures=True,
        )

        logger.info(
            f"[Backfill] Detected {len(new_climbs)} climbs from GPS polyline data "
            f"using algorithm={detector_algorithm}"
        )

        if not climb_patterns:
            if not new_climbs:
                review_recorded = _record_climb_backfill_review(
                    repo._client,
                    activity_id=activity_id,
                    detector_algorithm=detector_algorithm,
                    outcome="no_canonical_climb",
                    reviewed_by=admin_ctx[1],
                    details={
                        "gps_points": len(gps_points),
                        "tile_runs": len(tiles_mem),
                        "detector_algorithm": detector_algorithm,
                    },
                )
                return {
                    "success": True,
                    "activity_id": activity_id,
                    "existing_patterns": 0,
                    "new_detections": 0,
                    "inserted_patterns": 0,
                    "updated_patterns": 0,
                    "detector_algorithm": detector_algorithm,
                    "gps_points": len(gps_points),
                    "tile_runs": len(tiles_mem),
                    "review_outcome": "no_canonical_climb",
                    "review_recorded": review_recorded,
                }

            pattern_repo = PatternRepository(repo._client)
            inserted_count = await _insert_backfilled_climb_patterns(
                pattern_repo=pattern_repo,
                activity_id=activity_uuid,
                wallet=wallet,
                climbs=new_climbs,
                detector_version=detector_algorithm,
                source_samples=tiles_mem,
            )
            return {
                "success": True,
                "activity_id": activity_id,
                "existing_patterns": 0,
                "new_detections": len(new_climbs),
                "inserted_patterns": inserted_count,
                "updated_patterns": 0,
                "detector_algorithm": detector_algorithm,
                "gps_points": len(gps_points),
                "tile_runs": len(tiles_mem),
            }

        # 6. Match new climbs to existing patterns and update
        updated_count = 0
        for existing_pattern in climb_patterns:
            existing_id = existing_pattern.get("id")
            # Find matching new climb by time offsets and vert
            best_match = None
            best_score = float('inf')

            for new_climb in new_climbs:
                score = _score_backfill_climb_match(existing_pattern, new_climb)

                if score < best_score:
                    best_score = score
                    best_match = new_climb

            if best_match and best_score < 500:  # Reasonable threshold
                # Update the pattern in database
                update_data = {}
                if best_match.distance_m is not None:
                    update_data["distance_m"] = round(best_match.distance_m, 1)
                if best_match.avg_gradient_pct is not None:
                    update_data["avg_gradient_pct"] = round(best_match.avg_gradient_pct, 2)
                if best_match.tile_ids:
                    update_data["tile_ids"] = best_match.tile_ids
                if best_match.signature_hex:
                    update_data["signature_hex"] = best_match.signature_hex
                signature_v2_hex = getattr(best_match, "signature_v2_hex", None)
                if signature_v2_hex:
                    update_data["signature_v2_hex"] = signature_v2_hex
                persistence_m = getattr(best_match, "persistence", None)
                if persistence_m is not None:
                    update_data["persistence_m"] = persistence_m
                for attr, column in [
                    ("start_lat", "start_lat"),
                    ("start_lon", "start_lon"),
                    ("end_lat", "end_lat"),
                    ("end_lon", "end_lon"),
                ]:
                    value = getattr(best_match, attr, None)
                    if value is not None:
                        update_data[column] = value
                update_data["detector_version"] = detector_algorithm
                quality = evaluate_climb_source_quality(
                    best_match,
                    tiles_mem,
                    context=f"dev_backfill:{detector_algorithm}",
                )
                update_data["economic_eligible"] = bool(quality["economic_eligible"])
                update_data["abstention_reasons"] = quality["abstention_reasons"] or None
                update_data["match_trace"] = {"source_quality": quality}

                if update_data:
                    try:
                        repo._client.table("patterns_climb")\
                            .update(update_data)\
                            .eq("id", existing_id)\
                            .execute()
                        updated_count += 1
                        logger.info(f"[Backfill] Updated pattern {existing_id}: distance={update_data.get('distance_m')}m, gradient={update_data.get('avg_gradient_pct')}%")
                    except Exception as e:
                        logger.error(f"[Backfill] Failed to update pattern {existing_id}: {e}")

        return {
            "success": True,
            "activity_id": activity_id,
            "existing_patterns": len(climb_patterns),
            "new_detections": len(new_climbs),
            "inserted_patterns": 0,
            "updated_patterns": updated_count,
            "detector_algorithm": detector_algorithm,
            "gps_points": len(gps_points),
            "tile_runs": len(tiles_mem),
        }

    except Exception as e:
        logger.error(f"[Backfill] Error for activity {activity_id}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


@router.post("/patterns/backfill-all")
async def backfill_all_climb_patterns(
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Backfill missing climb pattern data for ALL activities with null distance_m.

    Returns a summary of how many activities were processed and updated.
    Use with caution - can be slow for large databases.
    """
    try:
        repo = create_supabase_repository()
        detector_algorithm = _current_climb_detector_algorithm()

        # Find activities with incomplete climb rows, plus high-gain completed
        # rides that have no climb rows at all. The latter is the Corey-class
        # stale import failure: no row means a pattern-row based selector cannot
        # see the repair target.
        incomplete_pattern_activity_ids = _find_activities_with_incomplete_climb_patterns(
            repo._client
        )
        zero_climb_activity_ids = _find_high_gain_zero_climb_activities(
            repo._client,
            detector_algorithm=detector_algorithm,
        )
        activity_ids = _unique_activity_ids(incomplete_pattern_activity_ids, zero_climb_activity_ids)

        if not activity_ids:
            return {"success": True, "message": "No activities need backfill", "count": 0}

        logger.info(
            "[Backfill-All] Found %d activities needing backfill "
            "(incomplete_rows=%d, zero_climb_high_gain=%d)",
            len(activity_ids),
            len(incomplete_pattern_activity_ids),
            len(zero_climb_activity_ids),
        )

        # Process each activity
        results = {
            "total": len(activity_ids),
            "success": 0,
            "failed": 0,
            "no_samples": 0,
            "reviewed_terminal": 0,
            "details": []
        }

        for activity_id in activity_ids[:50]:  # Limit to 50 per call to avoid timeout
            try:
                response = await backfill_climb_patterns(activity_id, admin_ctx=admin_ctx)
                if (
                    response.get("review_recorded")
                    and response.get("review_outcome") in TERMINAL_ZERO_CLIMB_BACKFILL_OUTCOMES
                ):
                    results["reviewed_terminal"] += 1
                    if response.get("success"):
                        results["success"] += 1
                elif response.get("success"):
                    results["success"] += 1
                    if response.get("updated_patterns", 0) > 0:
                        results["details"].append({
                            "activity_id": activity_id,
                            "updated": response.get("updated_patterns", 0)
                        })
                elif "No tile samples" in response.get("message", ""):
                    results["no_samples"] += 1
                else:
                    results["failed"] += 1
            except Exception as e:
                results["failed"] += 1
                logger.error(f"[Backfill-All] Failed for {activity_id}: {e}")

        remaining = len(activity_ids) - 50
        if remaining > 0:
            results["remaining"] = remaining
            results["message"] = f"Processed 50 of {len(activity_ids)} activities. Call again to process more."

        results["selector_counts"] = {
            "incomplete_pattern_rows": len(incomplete_pattern_activity_ids),
            "zero_climb_high_gain_rides": len(zero_climb_activity_ids),
        }

        return results

    except Exception as e:
        logger.error(f"[Backfill-All] Error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


# =============================================================================
# REPLAY SYSTEM ENDPOINTS (A5: Replay Model + Structured Diffing)
# =============================================================================


class ReplayCreateRequest(BaseModel):
    """Request to create a replay batch."""
    scope: str = "ride"  # ride, user, epoch, mass
    ride_ids: Optional[List[str]] = None
    wallet: Optional[str] = None
    epoch_id: Optional[int] = None
    from_version_id: Optional[int] = None
    to_version_id: Optional[int] = None
    dry_run: bool = False
    run_immediately: bool = False  # If True, process all rides synchronously


class ReplayPromoteRequest(BaseModel):
    """Request to promote a replay batch to production."""
    reviewed_by: str  # wallet of the reviewer


@router.post("/admin/replay/create")
async def create_replay(
    request: ReplayCreateRequest,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Create a replay batch for specified rides.

    A replay batch reprocesses rides through the current pipeline and
    compares results against the original processing outputs. All results
    are stored in staging tables — production tables are never modified.

    Set run_immediately=true to process all rides synchronously and
    generate a scorecard in the response. Otherwise, use the batch_id
    to trigger processing separately.

    Args:
        scope: One of 'ride', 'user', 'epoch', 'mass'
        ride_ids: List of ride IDs (for scope='ride' or 'mass')
        wallet: User wallet (for scope='user', auto-fetches rides)
        from_version_id: Pipeline version that produced originals (optional)
        to_version_id: Pipeline version for replay (optional)
        dry_run: If True, results cannot be promoted
        run_immediately: If True, process all rides synchronously
    """
    from ..services.replay_service import get_replay_service

    replay_service = get_replay_service()

    try:
        batch = await replay_service.create_replay_batch(
            scope=request.scope,
            ride_ids=request.ride_ids,
            wallet=request.wallet,
            epoch_id=request.epoch_id,
            from_version_id=request.from_version_id,
            to_version_id=request.to_version_id,
            dry_run=request.dry_run,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    result = {
        "batch_id": batch.id,
        "scope": batch.scope,
        "status": batch.status,
        "total_rides": batch.total_rides,
        "dry_run": batch.dry_run,
        "created_at": batch.created_at,
    }

    # Optionally run all rides immediately
    if request.run_immediately and batch.total_rides > 0:
        try:
            run_result = await replay_service.run_batch(batch.id)
            result["run_result"] = run_result
            result["status"] = "completed"
        except Exception as e:
            logger.error(f"[Replay] Batch run failed: {e}", exc_info=True)
            result["run_error"] = str(e)

    return result


@router.get("/admin/replay/{batch_id}")
async def get_replay_status(
    batch_id: str,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Get replay batch status including progress and scorecard.

    Returns the batch metadata, per-ride result summary, and
    scorecard (if generated).
    """
    from ..services.replay_service import get_replay_service

    replay_service = get_replay_service()
    batch = await replay_service.get_batch(batch_id)

    if not batch:
        raise HTTPException(status_code=404, detail=f"Replay batch {batch_id} not found")

    return batch


@router.post("/admin/replay/{batch_id}/run")
async def run_replay_batch(
    batch_id: str,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Process all rides in a replay batch.

    Runs each ride through the pipeline, stores results in staging,
    generates diffs, and produces a scorecard when complete.

    For batches with many rides, this may take several minutes.
    """
    from ..services.replay_service import get_replay_service

    replay_service = get_replay_service()

    try:
        result = await replay_service.run_batch(batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/admin/replay/{batch_id}/scorecard")
async def generate_replay_scorecard(
    batch_id: str,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Generate or regenerate the scorecard for a replay batch.

    The scorecard summarizes how many rides had metric changes,
    climb changes, vault match changes, and the total economic delta.
    """
    from ..services.replay_service import get_replay_service

    replay_service = get_replay_service()
    scorecard = await replay_service.generate_scorecard(batch_id)

    return {"batch_id": batch_id, "scorecard": scorecard}


@router.post("/admin/replay/{batch_id}/promote")
async def promote_replay(
    batch_id: str,
    body: ReplayPromoteRequest,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Promote staging results to production.

    Promotion is currently disabled. The endpoint only validates that the
    batch is in a promotable state, then returns 501 until real production
    promotion semantics exist.

    Requires the batch to be in 'completed' status and not a dry run.
    """
    from ..services.replay_service import get_replay_service

    replay_service = get_replay_service()

    try:
        result = await replay_service.promote_batch(batch_id, reviewed_by=body.reviewed_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError as e:
        raise HTTPException(status_code=501, detail=str(e))

    return result


# ---------------------------------------------------------------------------
# Economic Ledger consistency & verification endpoints
# ---------------------------------------------------------------------------




@router.get("/ledger/verify-chain")
async def ledger_verify_chain(
    wallet: str,
    denomination: str = "POINTS",
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """
    Verify the SHA-256 hash chain integrity for a wallet+denomination
    in the economic_events ledger.

    Walks events in chronological order and recomputes each hash,
    checking linkage and content integrity.

    Requires admin auth.
    """
    from ..repositories import create_supabase_repository
    from ..services.economic_ledger import get_economic_ledger_service
    from ..schemas import LedgerHashChainResponse

    repo = create_supabase_repository()
    ledger = get_economic_ledger_service(repo.client)

    result = await ledger.verify_hash_chain(
        wallet=wallet,
        denomination=denomination,
    )

    return LedgerHashChainResponse(
        wallet=wallet,
        denomination=denomination,
        valid=result["valid"],
        events_checked=result["events_checked"],
        first_broken_id=result.get("first_broken_id"),
        error=result.get("error"),
    )


# The dashboard HTML - a full dev tool for visualizing tiles and patterns
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tile Dev Dashboard · Boulder Roller</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #1a1d12;
            color: #d0d8bf;
            min-height: 100vh;
        }

        .header {
            background: #2a2d1e;
            border-bottom: 2px solid #3a3d2e;
            padding: 16px 24px;
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .header h1 {
            font-size: 20px;
            font-weight: 800;
            color: #8ba87a;
        }

        .header .badge {
            background: #d4a574;
            color: #1a1d12;
            font-size: 10px;
            font-weight: 700;
            padding: 4px 8px;
            border-radius: 4px;
            text-transform: uppercase;
        }

        .container {
            display: grid;
            grid-template-columns: 380px 1fr;
            height: calc(100vh - 64px);
        }

        .sidebar {
            background: #2a2d1e;
            border-right: 2px solid #3a3d2e;
            overflow-y: auto;
            padding: 20px;
        }

        .section {
            margin-bottom: 24px;
        }

        .section-title {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: #8ba87a;
            margin-bottom: 12px;
        }

        .upload-zone {
            border: 2px dashed #3a3d2e;
            border-radius: 8px;
            padding: 32px;
            text-align: center;
            cursor: pointer;
            transition: all 0.2s;
        }

        .upload-zone:hover, .upload-zone.drag-over {
            border-color: #8ba87a;
            background: rgba(139, 168, 122, 0.05);
        }

        .upload-zone .icon {
            font-size: 32px;
            margin-bottom: 8px;
        }

        .upload-zone .text {
            font-size: 13px;
            color: #8a8d7a;
        }

        .upload-zone .formats {
            font-size: 11px;
            color: #6a6d5a;
            margin-top: 4px;
        }

        input[type="file"] {
            display: none;
        }

        .stats-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }

        .stat-card {
            background: #1a1d12;
            border: 1px solid #3a3d2e;
            border-radius: 6px;
            padding: 12px;
        }

        .stat-card .label {
            font-size: 10px;
            text-transform: uppercase;
            color: #6a6d5a;
            margin-bottom: 4px;
        }

        .stat-card .value {
            font-family: 'Cousine', monospace;
            font-size: 20px;
            font-weight: 700;
            color: #d0d8bf;
        }

        .stat-card .value.accent {
            color: #d4a574;
        }

        .patterns-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .files-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
            max-height: 200px;
            overflow-y: auto;
        }

        .files-meta {
            font-size: 11px;
            color: #8a8d7a;
            margin-bottom: 8px;
        }

        .files-table-wrap {
            border: 1px solid #3a3d2e;
            border-radius: 6px;
            overflow: auto;
            max-height: 280px;
            background: #1a1d12;
        }

        .files-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }

        .files-table th {
            position: sticky;
            top: 0;
            z-index: 2;
            background: #2a2d1e;
            border-bottom: 1px solid #3a3d2e;
            padding: 8px 8px;
            text-align: left;
            font-size: 10px;
            text-transform: uppercase;
            color: #6a6d5a;
        }

        .files-table td {
            border-bottom: 1px solid #2a2d1e;
            padding: 8px 8px;
            vertical-align: middle;
        }

        .files-table td.right,
        .files-table th.right {
            text-align: right;
        }

        .files-table tr:hover {
            background: rgba(139, 168, 122, 0.06);
            cursor: pointer;
        }

        .files-table tr.active {
            background: rgba(139, 168, 122, 0.10);
        }

        .files-table .file-name {
            max-width: 160px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            color: #d0d8bf;
        }

        .files-table .mono {
            font-family: 'Cousine', monospace;
            color: #8a8d7a;
        }

        .files-table .status-error {
            color: #e57373;
        }

        .files-table .swatch {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 2px;
            margin-right: 6px;
            vertical-align: middle;
        }

        .table-actions {
            margin-top: 8px;
        }

        .diagnostics-box {
            margin-top: 10px;
            font-size: 11px;
            color: #8a8d7a;
            line-height: 1.35;
        }

        .file-item {
            background: #1a1d12;
            border: 1px solid #3a3d2e;
            border-radius: 4px;
            padding: 8px 10px;
            font-size: 11px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .file-item .name {
            color: #d0d8bf;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 180px;
        }

        .file-item .tiles {
            color: #8ba87a;
            font-family: 'Cousine', monospace;
        }

        .file-item.error {
            border-color: #e57373;
        }

        .file-item.error .name {
            color: #e57373;
        }

        .pattern-card {
            background: #1a1d12;
            border: 1px solid #3a3d2e;
            border-radius: 6px;
            padding: 12px;
        }

        .pattern-card .type {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            margin-bottom: 6px;
        }

        .pattern-card .type.climb { color: #e57373; }
        .pattern-card .type.steady { color: #64b5f6; }
        .pattern-card .type.exploration { color: #81c784; }

        .pattern-card .detail {
            font-family: 'Cousine', monospace;
            font-size: 13px;
            color: #8a8d7a;
        }

        .resolution-control {
            display: flex;
            align-items: center;
            gap: 12px;
            background: #1a1d12;
            border: 1px solid #3a3d2e;
            border-radius: 6px;
            padding: 12px;
        }

        .resolution-control label {
            font-size: 12px;
            color: #8a8d7a;
        }

        .resolution-control select {
            flex: 1;
            background: #2a2d1e;
            border: 1px solid #3a3d2e;
            color: #d0d8bf;
            padding: 8px;
            border-radius: 4px;
            font-family: inherit;
        }

        .map-container {
            position: relative;
        }

        #map {
            width: 100%;
            height: 100%;
            background: #1a1d12;
        }

        .map-legend {
            position: absolute;
            bottom: 20px;
            right: 20px;
            background: #2a2d1e;
            border: 1px solid #3a3d2e;
            border-radius: 6px;
            padding: 12px;
            z-index: 1000;
            font-size: 11px;
        }

        .pattern-summary-control {
            background: rgba(42, 45, 30, 0.92);
            border: 1px solid #3a3d2e;
            border-radius: 8px;
            padding: 10px 12px;
            color: #d0d8bf;
            font-size: 11px;
            max-width: 260px;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
        }

        .pattern-summary-control .title {
            font-size: 10px;
            text-transform: uppercase;
            color: #6a6d5a;
            margin-bottom: 4px;
        }

        .pattern-summary-control .summary {
            font-family: 'Cousine', monospace;
            color: #d4a574;
            line-height: 1.2;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-bottom: 6px;
        }

        .legend-item:last-child {
            margin-bottom: 0;
        }

        .legend-color {
            width: 16px;
            height: 16px;
            border-radius: 3px;
        }

        .loading {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: #2a2d1e;
            border: 1px solid #3a3d2e;
            border-radius: 8px;
            padding: 24px 32px;
            text-align: center;
            z-index: 2000;
            display: none;
        }

        .loading.show {
            display: block;
        }

        .loading .spinner {
            width: 32px;
            height: 32px;
            border: 3px solid #3a3d2e;
            border-top-color: #8ba87a;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 12px;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        .empty-state {
            text-align: center;
            padding: 40px 20px;
            color: #6a6d5a;
        }

        .empty-state .icon {
            font-size: 48px;
            margin-bottom: 12px;
        }

        .tile-info-popup {
            font-family: 'Cousine', monospace;
            font-size: 11px;
        }

        .tile-info-popup .tile-id {
            font-weight: 700;
            color: #8ba87a;
            word-break: break-all;
        }

        /* Leaflet overrides */
        .leaflet-container {
            background: #1a1d12;
        }

        .leaflet-popup-content-wrapper {
            background: #2a2d1e;
            color: #d0d8bf;
            border-radius: 6px;
        }

        .leaflet-popup-tip {
            background: #2a2d1e;
        }

        /* Collapsible sections */
        .collapsible {
            background: #1a1d12;
            border: 1px solid #3a3d2e;
            border-radius: 6px;
            margin-bottom: 12px;
        }

        .collapsible-header {
            padding: 10px 12px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            color: #8ba87a;
        }

        .collapsible-header:hover {
            background: rgba(139, 168, 122, 0.1);
        }

        .collapsible-header .arrow {
            transition: transform 0.2s;
        }

        .collapsible.open .collapsible-header .arrow {
            transform: rotate(90deg);
        }

        .collapsible-content {
            display: none;
            padding: 12px;
            border-top: 1px solid #3a3d2e;
        }

        .collapsible.open .collapsible-content {
            display: block;
        }

        /* Sliders */
        .slider-group {
            margin-bottom: 12px;
        }

        .slider-group label {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            color: #8a8d7a;
            margin-bottom: 4px;
        }

        .slider-group input[type="range"] {
            width: 100%;
            height: 6px;
            background: #3a3d2e;
            border-radius: 3px;
            outline: none;
            -webkit-appearance: none;
        }

        .slider-group input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 14px;
            height: 14px;
            background: #8ba87a;
            border-radius: 50%;
            cursor: pointer;
        }

        .slider-value {
            font-family: 'Cousine', monospace;
            color: #d4a574;
        }

        /* Buttons */
        .btn {
            background: #8ba87a;
            color: #1a1d12;
            border: none;
            padding: 8px 16px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
        }

        .btn:hover {
            background: #9db88a;
        }

        .btn:disabled {
            background: #4a4d3e;
            cursor: not-allowed;
        }

        .btn-secondary {
            background: transparent;
            border: 1px solid #3a3d2e;
            color: #8a8d7a;
        }

        .btn-secondary:hover {
            border-color: #8ba87a;
            color: #8ba87a;
        }

        /* Tile history */
        .history-display {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
        }

        .history-count {
            font-family: 'Cousine', monospace;
            color: #81c784;
        }

        /* GPS Quality badge */
        .quality-badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 10px;
            font-weight: 700;
            text-transform: uppercase;
        }

        .quality-good { background: #81c784; color: #1a1d12; }
        .quality-fair { background: #fff176; color: #1a1d12; }
        .quality-poor { background: #e57373; color: #1a1d12; }

        /* CAL cost display */
        .cal-cost {
            background: #1a1d12;
            border: 1px solid #3a3d2e;
            border-radius: 6px;
            padding: 12px;
            margin-top: 12px;
        }

        .cal-cost .label {
            font-size: 10px;
            text-transform: uppercase;
            color: #6a6d5a;
        }

        .cal-cost .value {
            font-family: 'Cousine', monospace;
            font-size: 18px;
            color: #d4a574;
        }

        .cal-cost .percent {
            font-size: 11px;
            color: #8a8d7a;
        }

        /* Elevation chart */
        .elevation-container {
            position: absolute;
            bottom: 0;
            left: 0;
            right: 0;
            height: 150px;
            background: #2a2d1e;
            border-top: 2px solid #3a3d2e;
            z-index: 1000;
            display: none;
        }

        .elevation-container.show {
            display: block;
        }

        .elevation-container canvas {
            width: 100% !important;
            height: 100% !important;
        }

        /* Warnings */
        .warnings-list {
            margin-top: 8px;
        }

        .warning-item {
            background: rgba(229, 115, 115, 0.1);
            border-left: 3px solid #e57373;
            padding: 6px 10px;
            font-size: 11px;
            color: #e57373;
            margin-bottom: 4px;
        }

        /* Arena input */
        .arena-input {
            width: 100%;
            background: #2a2d1e;
            border: 1px solid #3a3d2e;
            color: #d0d8bf;
            padding: 8px;
            border-radius: 4px;
            font-family: 'Cousine', monospace;
            font-size: 11px;
            resize: vertical;
            min-height: 60px;
        }

        .arena-input::placeholder {
            color: #6a6d5a;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🪲 Boulder Rollers</h1>
        <span class="badge">Tile Dev Dashboard</span>
    </div>

    <div class="container">
        <div class="sidebar">
            <div class="section">
                <div class="section-title">Upload Ride Files</div>
                <div class="upload-zone" id="uploadZone">
                    <div class="icon">📁</div>
                    <div class="text">Drop FIT or GPX files here</div>
                    <div class="formats">Supports multiple files • click to browse</div>
                </div>
                <input type="file" id="fileInput" accept=".fit,.gpx" multiple>
            </div>

            <div class="section">
                <div class="section-title">H3 Resolution</div>
                <div class="resolution-control">
                    <label>Resolution:</label>
                    <select id="resolution">
                        <option value="8">8 - Neighborhood (~500m)</option>
                        <option value="9">9 - Block (~200m)</option>
                        <option value="10" selected>10 - Street (~50m) ★</option>
                        <option value="11">11 - Building (~25m)</option>
                        <option value="12">12 - Precise (~10m)</option>
                    </select>
                </div>
            </div>

            <div class="section">
                <div class="section-title">Options</div>
                <div class="resolution-control">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" id="skipPatterns" checked style="width: 16px; height: 16px;">
                        <span>Skip pattern detection (faster)</span>
                    </label>
                </div>
                <div class="resolution-control" style="margin-top: 8px;">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer;">
                        <input type="checkbox" id="addToHistory" style="width: 16px; height: 16px;">
                        <span>Add tiles to history</span>
                    </label>
                </div>
                <div class="history-display">
                    <span>Tile History:</span>
                    <span><span class="history-count" id="historyCount">0</span> tiles <button class="btn btn-secondary" style="width: auto; padding: 2px 8px; margin-left: 8px;" onclick="clearHistory()">Clear</button></span>
                </div>
            </div>

            <!-- Pattern Thresholds -->
            <div class="section">
                <div class="collapsible" id="thresholdsCollapsible">
                    <div class="collapsible-header" onclick="toggleCollapsible('thresholdsCollapsible')">
                        <span>Tune Thresholds</span>
                        <span class="arrow">▶</span>
                    </div>
                    <div class="collapsible-content">
                        <div class="slider-group">
                            <label>
                                <span>Climb Min Vert</span>
                                <span class="slider-value" id="climbVertValue">50m</span>
                            </label>
                            <input type="range" id="climbVert" min="0" max="1500" step="10" value="50" oninput="updateSliderValue('climbVert', 'm')">
                        </div>
                        <div class="slider-group">
                            <label>
                                <span>Climb Min Time</span>
                                <span class="slider-value" id="climbTimeMinValue">2min</span>
                            </label>
                            <input type="range" id="climbTimeMin" min="0" max="30" step="1" value="2" oninput="updateSliderValue('climbTimeMin', 'min')">
                        </div>
                        <div class="slider-group">
                            <label>
                                <span>Climb Max Time</span>
                                <span class="slider-value" id="climbTimeValue">60min</span>
                            </label>
                            <input type="range" id="climbTime" min="5" max="240" step="5" value="60" oninput="updateSliderValue('climbTime', 'min')">
                        </div>
                        <div class="slider-group">
                            <label>
                                <span>Climb Drop Tolerance</span>
                                <span class="slider-value" id="climbDropValue">30m</span>
                            </label>
                            <input type="range" id="climbDrop" min="0" max="150" step="5" value="30" oninput="updateSliderValue('climbDrop', 'm')">
                        </div>
                        <div class="slider-group">
                            <label>
                                <span>Climb Smoothing Window</span>
                                <span class="slider-value" id="climbSmoothValue">5</span>
                            </label>
                            <input type="range" id="climbSmooth" min="1" max="15" step="1" value="5" oninput="updateSliderValue('climbSmooth', '')">
                        </div>
                        <div class="slider-group">
                            <label>
                                <span>Exploration Min Tiles</span>
                                <span class="slider-value" id="explorationTilesValue">50</span>
                            </label>
                            <input type="range" id="explorationTiles" min="10" max="200" value="50" oninput="updateSliderValue('explorationTiles', '')">
                        </div>
                        <button class="btn" onclick="redetectPatterns()" id="redetectBtn" disabled>Re-detect Patterns</button>
                    </div>
                </div>
            </div>

            <!-- Arena Filter -->
            <div class="section">
                <div class="collapsible" id="arenaCollapsible">
                    <div class="collapsible-header" onclick="toggleCollapsible('arenaCollapsible')">
                        <span>Arena Filter</span>
                        <span class="arrow">▶</span>
                    </div>
                    <div class="collapsible-content">
                        <textarea class="arena-input" id="arenaInput" placeholder="Paste tile IDs (comma-separated) or GeoJSON polygon..."></textarea>
                        <button class="btn" style="margin-top: 8px;" onclick="applyArenaFilter()" id="arenaBtn" disabled>Apply Filter</button>
                        <button class="btn btn-secondary" style="margin-top: 4px;" onclick="clearArenaFilter()">Clear Filter</button>
                    </div>
                </div>
            </div>

            <div class="section" id="filesSection" style="display: none;">
                <div class="section-title">Files</div>
                <div class="files-meta" id="filesMeta"></div>
                <div class="files-table-wrap">
                    <table class="files-table" id="filesTable">
                        <thead>
                            <tr>
                                <th>Active</th>
                                <th>Show</th>
                                <th>File</th>
                                <th>Parser</th>
                                <th class="right">Pts</th>
                                <th class="right">Dist</th>
                                <th class="right">Gain</th>
                                <th class="right">Tiles</th>
                                <th>Patterns</th>
                            </tr>
                        </thead>
                        <tbody id="filesTableBody"></tbody>
                    </table>
                </div>
                <div class="table-actions">
                    <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; margin-top: 10px;">
                        <input type="checkbox" id="applyThresholdsToChecked" style="width: 16px; height: 16px;">
                        <span style="font-size: 11px; color: #8a8d7a;">Apply re-detect to checked files (otherwise active only)</span>
                    </label>
                </div>
            </div>

            <div class="section" id="diagnosticsSection" style="display: none;">
                <div class="section-title">Diagnostics</div>
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 11px; color: #8a8d7a;">GPS Quality:</span>
                    <span class="quality-badge" id="gpsQuality">--</span>
                </div>
                <div class="warnings-list" id="warningsList"></div>
                <div class="diagnostics-box" id="diagnosticsBox"></div>
            </div>

            <div class="section" id="patternsSection" style="display: none;">
                <div class="section-title">Detected Patterns</div>
                <div class="patterns-list" id="patternsList">
                    <!-- Patterns will be inserted here -->
                </div>
                <div class="cal-cost" id="calCost" style="display: none;">
                    <div class="label">Estimated CAL Cost</div>
                    <div class="value" id="calCostValue">0</div>
                    <div class="percent" id="calCostPercent">0% of daily budget (2200)</div>
                </div>
            </div>

            <div class="section" id="exportSection" style="display: none;">
                <button class="btn btn-secondary" onclick="exportTestCase()">Export as Test Case</button>
            </div>
        </div>

        <div class="map-container">
            <div id="map"></div>

            <div class="elevation-container" id="elevationContainer">
                <canvas id="elevationChart"></canvas>
            </div>

            <div class="map-legend">
                <div class="legend-item">
                    <div class="legend-color" style="background: rgba(139, 168, 122, 0.4); border: 2px solid #8ba87a;"></div>
                    <span>H3 Tile</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #d4a574;"></div>
                    <span>GPS Track</span>
                </div>
                <div class="legend-item">
                    <div class="legend-color" style="background: #ff1744;"></div>
                    <span>Climb Pattern</span>
                </div>
            </div>

            <div class="loading" id="loading">
                <div class="spinner"></div>
                <div>Processing ride...</div>
            </div>
        </div>
    </div>

    <script>
        // Initialize map
        const map = L.map('map').setView([40.0150, -105.2705], 13); // Boulder, CO default

        // Dark tile layer
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            maxZoom: 19
        }).addTo(map);

        // Layer groups
        let tilesLayer = L.layerGroup().addTo(map);
        let trackLayer = L.layerGroup().addTo(map);
        let patternsLayer = L.layerGroup().addTo(map);
        let hoverLayer = L.layerGroup().addTo(map);
        let pinnedLayer = L.layerGroup().addTo(map);

        // Active file pattern summary (map overlay)
        let patternSummaryEl = null;
        const patternSummaryControl = L.control({ position: 'topright' });
        patternSummaryControl.onAdd = function () {
            patternSummaryEl = L.DomUtil.create('div', 'pattern-summary-control');
            patternSummaryEl.innerHTML = `
                <div class="title">Active Patterns</div>
                <div class="summary" id="patternSummaryText">--</div>
            `;
            return patternSummaryEl;
        };
        patternSummaryControl.addTo(map);

        // Elements
        const uploadZone = document.getElementById('uploadZone');
        const fileInput = document.getElementById('fileInput');
        const resolution = document.getElementById('resolution');
        const loading = document.getElementById('loading');
        const filesSection = document.getElementById('filesSection');
        const diagnosticsSection = document.getElementById('diagnosticsSection');
        const patternsSection = document.getElementById('patternsSection');

        const filesMeta = document.getElementById('filesMeta');
        const filesTableBody = document.getElementById('filesTableBody');
        const diagnosticsBox = document.getElementById('diagnosticsBox');

        // Track colors for multiple rides
        const trackColors = ['#d4a574', '#64b5f6', '#81c784', '#e57373', '#ba68c8', '#4dd0e1', '#fff176', '#ff8a65'];
        let lastFiles = null;

        // Dashboard state
        let elevationChart = null;
        let currentArenaFilter = null;

        const state = {
            files: [], // [{ id, filename, status, color, show, showChart, showTiles, showPatterns, gps_track, tile_samples, patterns, pattern_summary, sensor_coverage, parser, gps_points, tiles }]
            activeFileId: null,
            tileIndex: new Map(), // tile_id -> { boundary, center }
            layersByFile: new Map(), // fileId -> { track, tiles, patterns }
            hoverMarker: null,
            selectedPattern: null,
            selectedPatternRange: null, // { startKm, endKm }
            patternOverlayIndex: new Map(), // patternId -> L.Polyline
        };

        // CAL constants - NOTE: CAL is earned from TSS, not daily budget
        // This UI is for visualization purposes only; actual CAL comes from ride TSS
        const CAL_PER_TSS = 1; // 1 CAL per TSS from rides (correct model)

        // Load tile history from localStorage
        function getTileHistory() {
            const stored = localStorage.getItem('tileHistory');
            return stored ? JSON.parse(stored) : [];
        }

        function saveTileHistory(tiles) {
            localStorage.setItem('tileHistory', JSON.stringify(tiles));
            updateHistoryDisplay();
        }

        function addToTileHistory(newTiles) {
            const history = new Set(getTileHistory());
            newTiles.forEach(t => history.add(t));
            saveTileHistory([...history]);
        }

        function clearHistory() {
            localStorage.removeItem('tileHistory');
            updateHistoryDisplay();
        }

        function updateHistoryDisplay() {
            const history = getTileHistory();
            document.getElementById('historyCount').textContent = history.length.toLocaleString();
        }

        // Collapsible toggle
        function toggleCollapsible(id) {
            const el = document.getElementById(id);
            el.classList.toggle('open');
        }

        // Slider value update
        function updateSliderValue(id, unit) {
            const slider = document.getElementById(id);
            const valueEl = document.getElementById(id + 'Value');
            valueEl.textContent = slider.value + unit;
        }

        function formatOffset(seconds) {
            const s = Math.max(0, Math.floor(seconds || 0));
            const h = Math.floor(s / 3600);
            const m = Math.floor((s % 3600) / 60);
            const ss = s % 60;
            if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`;
            return `${m}:${String(ss).padStart(2, '0')}`;
        }

        function haversineMeters(lat1, lon1, lat2, lon2) {
            const R = 6371000; // meters
            const toRad = (deg) => deg * Math.PI / 180;
            const dLat = toRad(lat2 - lat1);
            const dLon = toRad(lon2 - lon1);
            const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
                      Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
                      Math.sin(dLon / 2) * Math.sin(dLon / 2);
            const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
            return R * c;
        }

        function enrichTrackWithDistance(track) {
            if (!track || track.length === 0) return [];
            const sorted = [...track].sort((a, b) => (a.t || 0) - (b.t || 0));
            let dist = 0;
            let prev = null;
            return sorted.map(p => {
                if (prev && typeof p.lat === 'number' && typeof p.lon === 'number' && typeof prev.lat === 'number' && typeof prev.lon === 'number') {
                    dist += haversineMeters(prev.lat, prev.lon, p.lat, p.lon);
                }
                prev = p;
                return { ...p, dist_m: dist };
            });
        }

        function smoothSeries(values, window) {
            const w = Math.max(1, window || 1);
            if (values.length < w) return values;
            const out = [];
            for (let i = 0; i < values.length; i++) {
                const start = Math.max(0, i - Math.floor(w / 2));
                const end = Math.min(values.length, i + Math.floor(w / 2) + 1);
                let sum = 0;
                let count = 0;
                for (let j = start; j < end; j++) {
                    const v = values[j];
                    if (v === null || v === undefined) continue;
                    sum += v;
                    count += 1;
                }
                out.push(count > 0 ? (sum / count) : null);
            }
            return out;
        }

        function computeElevationGain(track, smoothingWindow) {
            const elevations = track.map(p => (p.elevation_m === null || p.elevation_m === undefined) ? null : Number(p.elevation_m));
            const smoothed = smoothSeries(elevations, smoothingWindow || 5);
            let gain = 0;
            for (let i = 1; i < smoothed.length; i++) {
                const prev = smoothed[i - 1];
                const cur = smoothed[i];
                if (prev === null || cur === null) continue;
                const d = cur - prev;
                if (d > 0) gain += d;
            }
            return gain;
        }

        function readThresholds() {
            return {
                climb_vert_min_m: parseInt(document.getElementById('climbVert').value),
                climb_time_min_s: parseInt(document.getElementById('climbTimeMin').value) * 60,
                climb_time_max_s: parseInt(document.getElementById('climbTime').value) * 60,
                climb_drop_tolerance_m: parseInt(document.getElementById('climbDrop').value),
                climb_smoothing_window: parseInt(document.getElementById('climbSmooth').value),
                exploration_new_tile_min: parseInt(document.getElementById('explorationTiles').value)
            };
        }

        // GPS Quality calculation
        function calculateGpsQuality(gpsTracks) {
            const warnings = [];
            let maxSpeed = 0;
            let teleportations = 0;
            let totalPoints = 0;

            gpsTracks.forEach(track => {
                const points = track.track || [];
                totalPoints += points.length;

                for (let i = 1; i < points.length; i++) {
                    const p1 = points[i - 1];
                    const p2 = points[i];
                    const dt = p2.t - p1.t;
                    if (dt <= 0) continue;

                    // Calculate distance using Haversine
                    const R = 6371000; // Earth radius in meters
                    const lat1 = p1.lat * Math.PI / 180;
                    const lat2 = p2.lat * Math.PI / 180;
                    const dLat = (p2.lat - p1.lat) * Math.PI / 180;
                    const dLon = (p2.lon - p1.lon) * Math.PI / 180;

                    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                              Math.cos(lat1) * Math.cos(lat2) *
                              Math.sin(dLon/2) * Math.sin(dLon/2);
                    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
                    const dist = R * c;

                    const speed = (dist / dt) * 3.6; // km/h
                    maxSpeed = Math.max(maxSpeed, speed);

                    if (dist > 500 && dt < 10) {
                        teleportations++;
                    }
                }
            });

            if (maxSpeed > 100) {
                warnings.push(`Max speed ${maxSpeed.toFixed(0)} km/h (suspicious)`);
            }
            if (teleportations > 0) {
                warnings.push(`${teleportations} teleportation${teleportations > 1 ? 's' : ''} detected`);
            }

            let quality = 'good';
            let qualityClass = 'quality-good';
            if (warnings.length > 0) {
                quality = 'fair';
                qualityClass = 'quality-fair';
            }
            if (warnings.length > 2 || teleportations > 3) {
                quality = 'poor';
                qualityClass = 'quality-poor';
            }

            return { quality, qualityClass, warnings, maxSpeed };
        }

        // Pattern count (CAL is earned from TSS, not spent on patterns)
        function calculatePatternCount(patterns) {
            if (!patterns) return 0;
            let count = 0;
            if (patterns.climb_patterns) count += patterns.climb_patterns.length;
            if (patterns.steady_pattern) count += 1;
            if (patterns.exploration_pattern) count += 1;
            return count;
        }

        function updateCalCost(patterns) {
            // NOTE: CAL is earned from TSS, not spent on patterns
            // This display shows pattern count for informational purposes
            const count = calculatePatternCount(patterns);
            const calCostEl = document.getElementById('calCost');

            if (count > 0) {
                calCostEl.style.display = 'block';
                document.getElementById('calCostValue').textContent = count;
                document.getElementById('calCostPercent').textContent = `patterns detected (CAL earned from ride TSS)`;
            } else {
                calCostEl.style.display = 'none';
            }
        }

        // Initialize on load
        updateHistoryDisplay();

        // Keep diagnostics in sync with threshold sliders
        ['climbVert', 'climbTimeMin', 'climbTime', 'climbDrop', 'climbSmooth', 'explorationTiles'].forEach((id) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.addEventListener('input', () => updateDiagnostics());
        });

        // File upload handling
        uploadZone.addEventListener('click', () => fileInput.click());

        uploadZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadZone.classList.add('drag-over');
        });

        uploadZone.addEventListener('dragleave', () => {
            uploadZone.classList.remove('drag-over');
        });

        uploadZone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadZone.classList.remove('drag-over');
            const files = e.dataTransfer.files;
            if (files.length > 0) processFiles(files);
        });

        fileInput.addEventListener('change', (e) => {
            const files = e.target.files;
            if (files.length > 0) processFiles(files);
        });

        resolution.addEventListener('change', () => {
            if (lastFiles) {
                processFiles(lastFiles);
            }
        });

        async function processFiles(files) {
            lastFiles = files;
            loading.classList.add('show');

            const formData = new FormData();
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            const skipPatterns = document.getElementById('skipPatterns').checked;

            try {
                const response = await fetch(`/dev/tiles/upload-bulk?resolution=${resolution.value}&skip_patterns=${skipPatterns}`, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Upload failed');
                }

                const data = await response.json();
                displayBulkResults(data);
            } catch (error) {
                console.error('Error:', error);
                alert('Error processing files: ' + error.message);
            } finally {
                loading.classList.remove('show');
            }
        }

        function displayBulkResults(data) {
            // Clear existing layers + state
            tilesLayer.clearLayers();
            trackLayer.clearLayers();
            patternsLayer.clearLayers();
            hoverLayer.clearLayers();
            pinnedLayer.clearLayers();

            state.files = [];
            state.activeFileId = null;
            state.tileIndex = new Map();
            state.layersByFile = new Map();
            state.hoverMarker = null;
            state.selectedPattern = null;
            state.selectedPatternRange = null;
            state.patternOverlayIndex = new Map();

            // Build tile boundary index (tile_id -> boundary/center)
            (data.tiles || []).forEach(tile => {
                if (tile && tile.tile_id) state.tileIndex.set(tile.tile_id, tile);
            });

            // Build per-file state
            const files = data.files || [];
            files.forEach((file, idx) => {
                const id = `${idx}:${file.filename || 'file'}`;
                const color = trackColors[idx % trackColors.length];

                state.files.push({
                    id,
                    filename: file.filename,
                    status: file.status,
                    error: file.error,
                    parser: file.parser,
                    gps_points: file.gps_points || 0,
                    tiles: file.tiles || 0,
                    total_samples: file.total_samples || 0,
                    bounds: file.bounds || null,
                    gps_track: file.gps_track || [],
                    tile_samples: file.tile_samples || [],
                    sensor_coverage: file.sensor_coverage || null,
                    patterns: file.patterns || null,
                    pattern_summary: file.pattern_summary || null,
                    color,
                    show: file.status === 'success',
                    showChart: file.status === 'success',
                    showTiles: false,
                    showPatterns: true,
                });
            });

            // Precompute per-file track stats (distance, gain) for UI + chart
            state.files.forEach(file => {
                if (file.status !== 'success') return;
                file.enriched_track = enrichTrackWithDistance(file.gps_track || []);
                file.distance_m = file.enriched_track.length ? file.enriched_track[file.enriched_track.length - 1].dist_m : 0;
                file.elevation_gain_m = computeElevationGain(file.enriched_track, 5);
                file.duration_s = file.enriched_track.length ? (file.enriched_track[file.enriched_track.length - 1].t || 0) : 0;
            });

            // Pick active file (first successful)
            const firstSuccess = state.files.find(f => f.status === 'success');
            state.activeFileId = firstSuccess ? firstSuccess.id : null;

            // Create map layers for visible files
            state.files.forEach(file => {
                if (file.status !== 'success') return;
                if (file.show) drawFileTrack(file);
            });

            // Add to history if checkbox checked (visible files only)
            if (document.getElementById('addToHistory').checked) {
                const tileIds = new Set();
                state.files.filter(f => f.status === 'success' && f.show).forEach(f => {
                    (f.tile_samples || []).forEach(s => {
                        if (s && s.tile_id) tileIds.add(s.tile_id);
                    });
                });
                addToTileHistory([...tileIds]);
            }

            // Enable actions based on active file
            const active = getActiveFile();
            const hasSamples = !!(active && active.tile_samples && active.tile_samples.length > 0);
            document.getElementById('redetectBtn').disabled = !hasSamples;
            document.getElementById('arenaBtn').disabled = !hasSamples;
            document.getElementById('exportSection').style.display = hasSamples ? 'block' : 'none';

            // Default: show tiles for the active file
            if (active && active.show) {
                active.showTiles = true;
                drawFileTiles(active);
            }

            // Render file table
            filesSection.style.display = 'block';
            renderFilesTable();

            // Diagnostics (GPS quality on visible files)
            diagnosticsSection.style.display = 'block';
            const visibleTracks = state.files
                .filter(f => f.status === 'success' && f.show)
                .map(f => ({ track: f.gps_track || [] }));
            const gpsQuality = calculateGpsQuality(visibleTracks);
            const gpsQualityEl = document.getElementById('gpsQuality');
            gpsQualityEl.textContent = gpsQuality.quality.toUpperCase();
            gpsQualityEl.className = 'quality-badge ' + gpsQuality.qualityClass;

            const warningsList = document.getElementById('warningsList');
            warningsList.innerHTML = '';
            gpsQuality.warnings.forEach(w => {
                const div = document.createElement('div');
                div.className = 'warning-item';
                div.textContent = w;
                warningsList.appendChild(div);
            });

            // Patterns panel (active file)
            if (active) displayPatterns(active.patterns);
            updatePatternSummaryControl();
            drawPatternsForActiveFile();
            updateDiagnostics();

            // Render elevation chart (distance-based)
            renderElevationChart();

            // Fit map to bounds
            if (data.bounds && data.bounds.min_lat !== 0) {
                const bounds = [
                    [data.bounds.min_lat, data.bounds.min_lon],
                    [data.bounds.max_lat, data.bounds.max_lon]
                ];
                map.fitBounds(bounds, { padding: [50, 50] });
            }
        }

        function getActiveFile() {
            return state.files.find(f => f.id === state.activeFileId) || null;
        }

        function updatePatternSummaryControl() {
            const el = document.getElementById('patternSummaryText');
            if (!el) return;
            const active = getActiveFile();
            if (!active) {
                el.textContent = '--';
                return;
            }
            const summary = active.pattern_summary || (active.patterns ? 'Patterns detected' : 'Patterns skipped');
            el.textContent = `${active.filename}: ${summary}`;
        }

        function drawFileTrack(file) {
            if (!file || !file.gps_track || file.gps_track.length === 0) return;

            const points = file.gps_track.map(p => [p.lat, p.lon]);
            const polyline = L.polyline(points, {
                color: file.color,
                weight: 3,
                opacity: 0.85
            }).addTo(trackLayer);
            polyline.bindPopup(`<b>${file.filename}</b>`);

            const existing = state.layersByFile.get(file.id) || {};
            existing.track = polyline;
            state.layersByFile.set(file.id, existing);
        }

        function removeFileTrack(fileId) {
            const layers = state.layersByFile.get(fileId);
            if (layers && layers.track) {
                trackLayer.removeLayer(layers.track);
                layers.track = null;
            }
        }

        function drawFileTiles(file) {
            if (!file || !file.tile_samples || file.tile_samples.length === 0) return;

            // Remove existing tile layer for this file
            removeFileTiles(file.id);

            const tileIds = new Set();
            file.tile_samples.forEach(s => {
                if (s && s.tile_id) tileIds.add(s.tile_id);
            });

            const group = L.layerGroup();
            tileIds.forEach(tileId => {
                const tile = state.tileIndex.get(tileId);
                if (!tile || !tile.boundary) return;
                const boundary = tile.boundary.map(p => [p.lat, p.lon]);
                const polygon = L.polygon(boundary, {
                    color: '#8ba87a',
                    fillColor: '#8ba87a',
                    fillOpacity: 0.12,
                    weight: 1
                });
                polygon.bindPopup(`<div class="tile-info-popup"><div class="tile-id">${tileId}</div></div>`);
                group.addLayer(polygon);
            });

            tilesLayer.addLayer(group);

            const existing = state.layersByFile.get(file.id) || {};
            existing.tiles = group;
            state.layersByFile.set(file.id, existing);
        }

        function removeFileTiles(fileId) {
            const layers = state.layersByFile.get(fileId);
            if (layers && layers.tiles) {
                tilesLayer.removeLayer(layers.tiles);
                layers.tiles = null;
            }
        }

        function getTrackSegmentByTime(track, startS, endS) {
            if (!track || track.length === 0) return [];
            const start = Math.min(startS, endS);
            const end = Math.max(startS, endS);

            const pts = track.filter(p => typeof p.t === 'number' && p.t >= start && p.t <= end);
            if (pts.length >= 2) return pts;

            // Fallback: pick nearest points around boundaries
            let bestStart = null;
            let bestEnd = null;
            track.forEach(p => {
                if (typeof p.t !== 'number') return;
                if (bestStart === null || Math.abs(p.t - start) < Math.abs(bestStart.t - start)) bestStart = p;
                if (bestEnd === null || Math.abs(p.t - end) < Math.abs(bestEnd.t - end)) bestEnd = p;
            });
            const out = [];
            if (bestStart) out.push(bestStart);
            if (bestEnd && bestEnd !== bestStart) out.push(bestEnd);
            return out;
        }

        function getDistanceKmAtTime(track, seconds) {
            if (!track || track.length === 0) return null;
            const t = Number(seconds || 0);
            let best = null;
            for (let i = 0; i < track.length; i++) {
                const p = track[i];
                if (p.t === undefined || p.t === null) continue;
                if (best === null || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p;
            }
            if (!best || best.dist_m === undefined || best.dist_m === null) return null;
            return best.dist_m / 1000;
        }

        function clearPatternOverlays() {
            patternsLayer.clearLayers();
            state.patternOverlayIndex = new Map();
        }

        function drawPatternsForActiveFile() {
            clearPatternOverlays();
            const active = getActiveFile();
            if (!active || !active.patterns) return;

            const patterns = active.patterns;

            const climbColor = '#ff1744';
            const steadyColor = '#64b5f6';
            const explorationColor = '#81c784';

            (patterns.climb_patterns || []).forEach((p, idx) => {
                drawPatternSegment(active, p, 'CLIMB', climbColor, idx + 1);
            });

            if (patterns.steady_pattern) {
                drawPatternSegment(active, patterns.steady_pattern, 'STEADY', steadyColor, null);
            }

            if (patterns.exploration_pattern) {
                drawPatternSegment(active, patterns.exploration_pattern, 'EXPLORATION', explorationColor, null);
            }
        }

        function drawPatternSegment(file, pattern, kind, color, indexLabel) {
            if (!pattern || !file || !file.gps_track) return;

            const startS = pattern.start_offset_s || 0;
            const endS = pattern.end_offset_s || 0;
            const pts = getTrackSegmentByTime(file.gps_track, startS, endS);
            if (pts.length < 2) return;

            const latlngs = pts.map(p => [p.lat, p.lon]);
            const isSelected = state.selectedPattern && state.selectedPattern.id === pattern.id;

            const weight = isSelected ? 9 : 7;
            L.polyline(latlngs, {
                color: '#000000',
                weight: weight + 4,
                opacity: isSelected ? 0.35 : 0.25,
                lineCap: 'round',
            }).addTo(patternsLayer);

            const polyline = L.polyline(latlngs, {
                color,
                weight,
                opacity: isSelected ? 0.95 : 0.8,
                lineCap: 'round',
            }).addTo(patternsLayer);

            const label = indexLabel ? `${kind} ${indexLabel}` : kind;
            const tooltip = `${label} • ${Math.round(startS)}s→${Math.round(endS)}s`;
            polyline.bindTooltip(tooltip, { sticky: true });

            if (pattern.id) state.patternOverlayIndex.set(pattern.id, polyline);
        }

        function selectPattern(pattern, kind) {
            if (!pattern || !pattern.id) return;
            state.selectedPattern = { id: pattern.id, kind: kind };
            const active = getActiveFile();
            if (active && active.enriched_track) {
                const startKm = getDistanceKmAtTime(active.enriched_track, pattern.start_offset_s || 0);
                const endKm = getDistanceKmAtTime(active.enriched_track, pattern.end_offset_s || 0);
                state.selectedPatternRange = (startKm !== null && endKm !== null) ? { startKm, endKm } : null;
            } else {
                state.selectedPatternRange = null;
            }
            drawPatternsForActiveFile();

            const polyline = state.patternOverlayIndex.get(pattern.id);
            if (polyline) {
                map.fitBounds(polyline.getBounds(), { padding: [40, 40] });
            }

            if (elevationChart) elevationChart.update();
        }

        function setActiveFile(fileId) {
            state.activeFileId = fileId;
            state.selectedPattern = null;
            state.selectedPatternRange = null;

            // Keep tiles focused on the active file
            state.files.forEach(f => {
                if (f.id !== fileId && f.showTiles) {
                    f.showTiles = false;
                    removeFileTiles(f.id);
                }
            });

            const active = getActiveFile();
            if (active && active.show) {
                active.showTiles = true;
                drawFileTiles(active);
            }

            renderFilesTable();
            if (active) {
                displayPatterns(active.patterns);
                document.getElementById('redetectBtn').disabled = !(active.tile_samples && active.tile_samples.length > 0);
                document.getElementById('arenaBtn').disabled = !(active.tile_samples && active.tile_samples.length > 0);
            }
            updatePatternSummaryControl();
            drawPatternsForActiveFile();
            renderElevationChart();
            updateDiagnostics();
        }

        function renderFilesTable() {
            const total = state.files.length;
            const ok = state.files.filter(f => f.status === 'success').length;
            const visible = state.files.filter(f => f.status === 'success' && f.show).length;

            filesMeta.textContent = `${ok}/${total} parsed • ${visible} visible`;

            filesTableBody.innerHTML = '';

            state.files.forEach((file) => {
                const tr = document.createElement('tr');
                if (file.id === state.activeFileId) tr.classList.add('active');

                const activeCell = document.createElement('td');
                const activeRadio = document.createElement('input');
                activeRadio.type = 'radio';
                activeRadio.name = 'activeFile';
                activeRadio.checked = file.id === state.activeFileId;
                activeRadio.disabled = file.status !== 'success';
                activeRadio.addEventListener('click', (e) => e.stopPropagation());
                activeRadio.addEventListener('change', () => setActiveFile(file.id));
                activeCell.appendChild(activeRadio);

                const showCell = document.createElement('td');
                const showBox = document.createElement('input');
                showBox.type = 'checkbox';
                showBox.checked = !!file.show;
                showBox.disabled = file.status !== 'success';
                showBox.style.width = '16px';
                showBox.style.height = '16px';
                showBox.addEventListener('click', (e) => e.stopPropagation());
                showBox.addEventListener('change', () => {
                    file.show = showBox.checked;
                    file.showChart = showBox.checked;
                    if (file.show) {
                        drawFileTrack(file);
                    } else {
                        removeFileTrack(file.id);
                        file.showTiles = false;
                        removeFileTiles(file.id);
                    }

                    // Re-render chart using visible series
                    renderElevationChart();
                    renderFilesTable();

                    if (!file.show && file.id === state.activeFileId) {
                        const next = state.files.find(f => f.status === 'success' && f.show);
                        if (next) setActiveFile(next.id);
                        else {
                            state.activeFileId = null;
                            patternsLayer.clearLayers();
                            updatePatternSummaryControl();
                            updateDiagnostics();
                        }
                    }
                });
                showCell.appendChild(showBox);

                const tilesBox = document.createElement('input');
                tilesBox.type = 'checkbox';
                tilesBox.checked = !!file.showTiles;
                tilesBox.disabled = file.status !== 'success' || !file.show;
                tilesBox.style.width = '16px';
                tilesBox.style.height = '16px';
                tilesBox.style.marginLeft = '8px';
                tilesBox.title = 'Show tiles';
                tilesBox.addEventListener('click', (e) => e.stopPropagation());
                tilesBox.addEventListener('change', () => {
                    file.showTiles = tilesBox.checked;
                    if (file.showTiles) drawFileTiles(file);
                    else removeFileTiles(file.id);
                    renderFilesTable();
                });
                showCell.appendChild(tilesBox);

                const nameCell = document.createElement('td');
                if (file.status === 'success') {
                    nameCell.innerHTML = `<span class="swatch" style="background:${file.color};"></span><span class="file-name">${file.filename}</span>`;
                } else {
                    nameCell.innerHTML = `<span class="status-error">${file.filename || 'Unknown file'}</span>`;
                }

                const parserCell = document.createElement('td');
                parserCell.className = 'mono';
                parserCell.textContent = file.parser || '--';

                const ptsCell = document.createElement('td');
                ptsCell.className = 'right mono';
                ptsCell.textContent = (file.gps_points || 0).toLocaleString();

                const distCell = document.createElement('td');
                distCell.className = 'right mono';
                distCell.textContent = file.status === 'success'
                    ? `${((file.distance_m || 0) / 1000).toFixed(1)}km`
                    : '--';

                const gainCell = document.createElement('td');
                gainCell.className = 'right mono';
                gainCell.textContent = file.status === 'success'
                    ? `${Math.round(file.elevation_gain_m || 0)}m`
                    : '--';

                const tilesCell = document.createElement('td');
                tilesCell.className = 'right mono';
                tilesCell.textContent = (file.tiles || 0).toLocaleString();

                const patternsCell = document.createElement('td');
                patternsCell.className = 'mono';
                patternsCell.textContent = file.status === 'success'
                    ? (file.pattern_summary || (file.patterns ? 'Patterns' : 'Skipped'))
                    : (file.error || 'Error');

                tr.appendChild(activeCell);
                tr.appendChild(showCell);
                tr.appendChild(nameCell);
                tr.appendChild(parserCell);
                tr.appendChild(ptsCell);
                tr.appendChild(distCell);
                tr.appendChild(gainCell);
                tr.appendChild(tilesCell);
                tr.appendChild(patternsCell);

                tr.addEventListener('click', () => {
                    if (file.status !== 'success') return;
                    setActiveFile(file.id);
                });

                filesTableBody.appendChild(tr);
            });
        }

        function computeBestNetGainWindow(tileSamples, thresholds) {
            const timeMin = Number(thresholds.climb_time_min_s || 0);
            const timeMax = Number(thresholds.climb_time_max_s || 0);
            const smoothing = Number(thresholds.climb_smoothing_window || 5);

            const rows = (tileSamples || [])
                .filter(s => s && s.t !== undefined && s.t !== null && s.elevation_m !== undefined && s.elevation_m !== null)
                .map(s => ({ t: Number(s.t), elev: Number(s.elevation_m) }))
                .filter(s => !Number.isNaN(s.t) && !Number.isNaN(s.elev))
                .sort((a, b) => a.t - b.t);

            if (rows.length < 2) return null;

            const times = rows.map(r => r.t);
            const elevs = smoothSeries(rows.map(r => r.elev), smoothing);

            let deque = [];
            let addIdx = 0;
            let best = null;

            for (let endIdx = 0; endIdx < rows.length; endIdx++) {
                const endT = times[endIdx];
                const endElev = elevs[endIdx];
                if (endElev === null) continue;

                // Add start candidates that satisfy duration >= timeMin
                while (addIdx < rows.length && times[addIdx] <= endT - timeMin) {
                    const e = elevs[addIdx];
                    if (e !== null) {
                        while (deque.length && elevs[deque[deque.length - 1]] >= e) {
                            deque.pop();
                        }
                        deque.push(addIdx);
                    }
                    addIdx += 1;
                }

                // Remove candidates that violate duration <= timeMax
                while (deque.length && times[deque[0]] < endT - timeMax) {
                    deque.shift();
                }

                if (!deque.length) continue;

                const startIdx = deque[0];
                const startElev = elevs[startIdx];
                if (startElev === null) continue;

                const netGain = endElev - startElev;
                const duration = endT - times[startIdx];
                if (duration < timeMin || duration > timeMax) continue;

                if (!best || netGain > best.net_gain_m) {
                    best = {
                        net_gain_m: netGain,
                        duration_s: duration,
                        start_offset_s: times[startIdx],
                        end_offset_s: endT,
                    };
                }
            }

            return best;
        }

        function updateDiagnostics() {
            const active = getActiveFile();
            if (!active) {
                diagnosticsBox.innerHTML = '';
                return;
            }

            const thresholds = readThresholds();
            const samples = active.tile_samples || [];

            const coverage = active.sensor_coverage || {
                total: samples.length,
                elevation: samples.filter(s => s && s.elevation_m !== undefined && s.elevation_m !== null).length,
                power: samples.filter(s => s && s.power_w !== undefined && s.power_w !== null).length,
                hr: samples.filter(s => s && s.hr_bpm !== undefined && s.hr_bpm !== null).length,
                speed: samples.filter(s => s && s.speed_mps !== undefined && s.speed_mps !== null).length,
            };

            const bestNet = computeBestNetGainWindow(samples, thresholds);
            const bestNetText = bestNet
                ? `Best net climb window: +${bestNet.net_gain_m.toFixed(0)}m over ${formatOffset(bestNet.duration_s)} (${formatOffset(bestNet.start_offset_s)}→${formatOffset(bestNet.end_offset_s)})`
                : 'Best net climb window: --';

            const hints = [];
            if (coverage.elevation < 2) hints.push('Missing elevation samples → climb detection will always fail.');
            if (coverage.power === 0) hints.push('No power samples found → Strava GPX exports usually omit power. Try a FIT/TCX (Strava “Export Original”) to get power metrics.');
            if (bestNet && bestNet.net_gain_m < thresholds.climb_vert_min_m) {
                hints.push(`Best window is below vert min (${thresholds.climb_vert_min_m}m).`);
            }
            if (!active.patterns) {
                hints.push('Patterns not computed yet → run “Re-detect Patterns”.');
            }

            diagnosticsBox.innerHTML = `
                <div><span class="mono">${active.filename}</span></div>
                <div>Coverage: <span class="mono">elev ${coverage.elevation}/${coverage.total}</span> • <span class="mono">power ${coverage.power}/${coverage.total}</span> • <span class="mono">hr ${coverage.hr}/${coverage.total}</span></div>
                <div>Climb thresholds: <span class="mono">${thresholds.climb_vert_min_m}m</span> • <span class="mono">${Math.round(thresholds.climb_time_min_s / 60)}–${Math.round(thresholds.climb_time_max_s / 60)}min</span> • <span class="mono">smooth ${thresholds.climb_smoothing_window}</span></div>
                <div>${bestNetText}</div>
                ${hints.length ? `<div style="margin-top: 6px; color: #d4a574;">${hints.join('<br>')}</div>` : ''}
            `;
        }

        function displayPatterns(patterns) {
            const patternsList = document.getElementById('patternsList');
            patternsList.innerHTML = '';

            patternsSection.style.display = 'block';

            const active = getActiveFile();
            if (!active) {
                patternsList.innerHTML = '<div class="empty-state"><div class="icon">📄</div><div>Upload a file to view patterns</div></div>';
                updateCalCost(null);
                return;
            }

            if (!patterns) {
                patternsList.innerHTML = '<div class="empty-state"><div class="icon">⏩</div><div>Patterns not computed (toggle off “Skip pattern detection” or click “Re-detect Patterns”)</div></div>';
                updateCalCost(null);
                return;
            }

            if (patterns.total_patterns === 0) {
                patternsList.innerHTML = '<div class="empty-state"><div class="icon">🔍</div><div>No patterns detected</div></div>';
                updateCalCost(patterns);
                return;
            }

            const hint = document.createElement('div');
            hint.style.fontSize = '11px';
            hint.style.color = '#6a6d5a';
            hint.style.marginBottom = '8px';
            hint.textContent = 'Click a pattern to zoom + highlight it on the map.';
            patternsList.appendChild(hint);

            // Climb patterns
            if (patterns.climb_patterns && patterns.climb_patterns.length > 0) {
                patterns.climb_patterns.forEach((climb, idx) => {
                    const card = document.createElement('div');
                    card.className = 'pattern-card';
                    card.innerHTML = `
                        <div class="type climb">⛰️ Climb ${idx + 1}</div>
                        <div class="detail">${climb.vert_m.toFixed(0)}m vert • ${Math.floor(climb.time_s / 60)}min • ${formatOffset(climb.start_offset_s)}→${formatOffset(climb.end_offset_s)}</div>
                        ${climb.avg_power_w ? `<div class="detail">${Math.round(climb.avg_power_w)}W avg${climb.w_per_kg ? ` • ${climb.w_per_kg.toFixed(2)} W/kg` : ''}</div>` : ''}
                        ${climb.avg_hr ? `<div class="detail">${climb.avg_hr} bpm avg HR</div>` : ''}
                        ${climb.vam ? `<div class="detail">${Math.round(climb.vam)} VAM</div>` : ''}
                    `;
                    card.addEventListener('click', () => selectPattern(climb, 'CLIMB'));
                    patternsList.appendChild(card);
                });
            }

            // Steady pattern
            if (patterns.steady_pattern) {
                const steady = patterns.steady_pattern;
                const card = document.createElement('div');
                card.className = 'pattern-card';
                card.innerHTML = `
                    <div class="type steady">🎯 Steady Effort</div>
                    <div class="detail">${Math.floor(steady.duration_s / 60)}min • ${formatOffset(steady.start_offset_s)}→${formatOffset(steady.end_offset_s)}</div>
                    ${steady.avg_power_w ? `<div class="detail">${Math.round(steady.avg_power_w)}W avg • ${steady.np_power_w ? `${Math.round(steady.np_power_w)}W NP` : ''}</div>` : ''}
                    ${steady.avg_hr ? `<div class="detail">${steady.avg_hr} bpm avg HR</div>` : ''}
                    ${steady.intensity_index ? `<div class="detail">IF ${steady.intensity_index.toFixed(2)}${steady.variability_index ? ` • VI ${steady.variability_index.toFixed(2)}` : ''}</div>` : ''}
                `;
                card.addEventListener('click', () => selectPattern(steady, 'STEADY'));
                patternsList.appendChild(card);
            }

            // Exploration pattern
            if (patterns.exploration_pattern) {
                const exp = patterns.exploration_pattern;
                const card = document.createElement('div');
                card.className = 'pattern-card';
                card.innerHTML = `
                    <div class="type exploration">🗺️ Exploration</div>
                    <div class="detail">${exp.new_tiles_wallet} new tiles • ${exp.total_tiles} total • ${formatOffset(exp.start_offset_s)}→${formatOffset(exp.end_offset_s)}</div>
                    ${exp.exploration_ratio !== undefined ? `<div class="detail">${(exp.exploration_ratio * 100).toFixed(0)}% new</div>` : ''}
                    ${exp.night_minutes ? `<div class="detail">${exp.night_minutes} night minutes</div>` : ''}
                `;
                card.addEventListener('click', () => selectPattern(exp, 'EXPLORATION'));
                patternsList.appendChild(card);
            }

            // Update CAL cost
            updateCalCost(patterns);
        }

        // Elevation chart rendering
        function renderElevationChart() {
            const container = document.getElementById('elevationContainer');
            const canvas = document.getElementById('elevationChart');

            const visibleFiles = state.files.filter(f => f.status === 'success' && f.showChart);
            const datasets = [];

            visibleFiles.forEach((file) => {
                const track = file.enriched_track || [];
                const points = track
                    .filter(p => p.elevation_m !== undefined && p.elevation_m !== null && p.dist_m !== undefined && p.dist_m !== null)
                    .map(p => ({
                        x: p.dist_m / 1000,
                        y: Number(p.elevation_m),
                        t: p.t || 0,
                        lat: p.lat,
                        lon: p.lon,
                        fileId: file.id,
                    }));

                if (points.length < 2) return;

                datasets.push({
                    label: file.filename,
                    data: points,
                    borderColor: file.color,
                    backgroundColor: 'rgba(139, 168, 122, 0.10)',
                    fill: false,
                    tension: 0.25,
                    pointRadius: 0,
                    pointHitRadius: 10,
                    borderWidth: file.id === state.activeFileId ? 2.5 : 2,
                });
            });

            if (datasets.length === 0) {
                container.classList.remove('show');
                return;
            }

            container.classList.add('show');

            // Destroy existing chart
            if (elevationChart) {
                elevationChart.destroy();
            }

            const crosshairPlugin = {
                id: 'crosshair',
                afterDraw(chart) {
                    const active = chart.getActiveElements();
                    if (!active || active.length === 0) return;
                    const el = active[0];
                    const raw = chart.data.datasets[el.datasetIndex].data[el.index];
                    if (!raw) return;

                    const x = chart.scales.x.getPixelForValue(raw.x);
                    const ctx = chart.ctx;
                    ctx.save();
                    ctx.beginPath();
                    ctx.moveTo(x, chart.chartArea.top);
                    ctx.lineTo(x, chart.chartArea.bottom);
                    ctx.lineWidth = 1;
                    ctx.strokeStyle = 'rgba(212, 165, 116, 0.6)';
                    ctx.stroke();
                    ctx.restore();
                }
            };

            const patternShadePlugin = {
                id: 'patternShade',
                beforeDatasetsDraw(chart) {
                    const range = state.selectedPatternRange;
                    if (!range || range.startKm === null || range.endKm === null) return;
                    const x1 = Math.min(range.startKm, range.endKm);
                    const x2 = Math.max(range.startKm, range.endKm);
                    const left = chart.scales.x.getPixelForValue(x1);
                    const right = chart.scales.x.getPixelForValue(x2);
                    const top = chart.chartArea.top;
                    const bottom = chart.chartArea.bottom;
                    const ctx = chart.ctx;
                    ctx.save();
                    ctx.fillStyle = 'rgba(212, 165, 116, 0.10)';
                    ctx.fillRect(left, top, right - left, bottom - top);
                    ctx.restore();
                }
            };

            const ctx = canvas.getContext('2d');
            elevationChart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: datasets
                },
                plugins: [patternShadePlugin, crosshairPlugin],
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            intersect: false,
                            mode: 'nearest',
                            callbacks: {
                                title: (items) => {
                                    if (!items || items.length === 0) return '';
                                    const p = items[0].raw;
                                    return `${p.x.toFixed(2)} km`;
                                },
                                label: (item) => {
                                    const p = item.raw;
                                    const elev = Number(p.y).toFixed(1);
                                    return `Elev ${elev} m • Time ${formatOffset(p.t)}`;
                                }
                            }
                        }
                    },
                    interaction: { mode: 'nearest', axis: 'x', intersect: false },
                    scales: {
                        x: {
                            display: true,
                            type: 'linear',
                            title: { display: true, text: 'Distance (km)', color: '#6a6d5a', font: { size: 11 } },
                            ticks: { color: '#6a6d5a', maxTicksLimit: 10 },
                            grid: { color: '#3a3d2e' }
                        },
                        y: {
                            display: true,
                            title: { display: true, text: 'Elevation (m)', color: '#6a6d5a', font: { size: 11 } },
                            ticks: { color: '#6a6d5a' },
                            grid: { color: '#3a3d2e' }
                        }
                    },
                    onHover: (event, activeEls, chart) => {
                        if (!activeEls || activeEls.length === 0) {
                            hoverLayer.clearLayers();
                            state.hoverMarker = null;
                            return;
                        }

                        const el = activeEls[0];
                        const point = chart.data.datasets[el.datasetIndex].data[el.index];
                        if (!point || point.lat === undefined || point.lon === undefined) return;

                        hoverLayer.clearLayers();
                        const marker = L.circleMarker([point.lat, point.lon], {
                            radius: 6,
                            color: '#d4a574',
                            weight: 2,
                            fillColor: '#1a1d12',
                            fillOpacity: 0.9
                        }).addTo(hoverLayer);

                        marker.__chartRef = { datasetIndex: el.datasetIndex, index: el.index, x: point.x, y: point.y };
                        marker.on('mouseover', () => {
                            if (!elevationChart) return;
                            const ref = marker.__chartRef;
                            const px = elevationChart.scales.x.getPixelForValue(ref.x);
                            const py = elevationChart.scales.y.getPixelForValue(ref.y);
                            elevationChart.setActiveElements([{ datasetIndex: ref.datasetIndex, index: ref.index }]);
                            elevationChart.tooltip.setActiveElements([{ datasetIndex: ref.datasetIndex, index: ref.index }], { x: px, y: py });
                            elevationChart.update();
                        });

                        state.hoverMarker = marker;
                    },
                    onClick: (event, activeEls, chart) => {
                        if (!activeEls || activeEls.length === 0) return;
                        const el = activeEls[0];
                        const point = chart.data.datasets[el.datasetIndex].data[el.index];
                        if (!point) return;
                        // Pin marker (persists across hover)
                        pinnedLayer.clearLayers();
                        L.circleMarker([point.lat, point.lon], {
                            radius: 7,
                            color: '#d4a574',
                            weight: 2,
                            fillColor: '#d4a574',
                            fillOpacity: 0.25
                        }).addTo(pinnedLayer);
                    }
                }
            });
        }

        // Redetect patterns with custom thresholds
        async function redetectPatterns() {
            const active = getActiveFile();
            if (!active || !active.tile_samples || active.tile_samples.length === 0) {
                alert('No tile samples available. Upload a file first.');
                return;
            }

            loading.classList.add('show');
            loading.querySelector('div:last-child').textContent = 'Re-detecting patterns...';

            const thresholds = readThresholds();

            try {
                const applyToChecked = document.getElementById('applyThresholdsToChecked').checked;
                const targets = applyToChecked
                    ? state.files.filter(f => f.status === 'success' && f.show && f.tile_samples && f.tile_samples.length > 0)
                    : [active];

                for (let i = 0; i < targets.length; i++) {
                    const file = targets[i];
                    loading.querySelector('div:last-child').textContent =
                        targets.length > 1 ? `Re-detecting patterns (${i + 1}/${targets.length})...` : 'Re-detecting patterns...';

                    const response = await fetch('/dev/tiles/redetect', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            tile_samples: file.tile_samples,
                            thresholds: thresholds,
                            wallet_tile_history: getTileHistory()
                        })
                    });

                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Redetect failed');
                    }

                    const data = await response.json();
                    file.patterns = data.patterns;
                    file.pattern_summary = data.summary;

                    if (file.id === state.activeFileId) {
                        displayPatterns(file.patterns);
                        updatePatternSummaryControl();
                        drawPatternsForActiveFile();
                        updateDiagnostics();
                    }
                }

                renderFilesTable();

            } catch (error) {
                console.error('Redetect error:', error);
                alert('Redetect failed: ' + error.message);
            } finally {
                loading.classList.remove('show');
            }
        }

        // Arena filtering
        function applyArenaFilter() {
            const input = document.getElementById('arenaInput').value.trim();
            if (!input) {
                alert('Enter tile IDs or GeoJSON');
                return;
            }

            const active = getActiveFile();
            if (!active || !active.tile_samples || active.tile_samples.length === 0) {
                alert('No tile samples available. Upload a file first.');
                return;
            }

            let arenaTiles = new Set();

            // Try parsing as JSON first (GeoJSON or array)
            try {
                const parsed = JSON.parse(input);
                if (Array.isArray(parsed)) {
                    parsed.forEach(t => arenaTiles.add(t));
                } else if (parsed.type === 'Feature' || parsed.type === 'Polygon') {
                    // Basic GeoJSON support - just show message for now
                    alert('GeoJSON polygon support coming soon. Use comma-separated tile IDs for now.');
                    return;
                }
            } catch (e) {
                // Parse as comma-separated tile IDs
                input.split(',').forEach(t => {
                    const trimmed = t.trim();
                    if (trimmed) arenaTiles.add(trimmed);
                });
            }

            if (arenaTiles.size === 0) {
                alert('No valid tile IDs found');
                return;
            }

            currentArenaFilter = arenaTiles;

            const inArenaSamples = active.tile_samples.filter(t => arenaTiles.has(t.tile_id)).length;
            const uniqueTiles = new Set(active.tile_samples.map(t => t.tile_id));
            const inArenaTiles = new Set(active.tile_samples.filter(t => arenaTiles.has(t.tile_id)).map(t => t.tile_id));
            alert(`${inArenaTiles.size}/${uniqueTiles.size} tiles (and ${inArenaSamples}/${active.tile_samples.length} samples) are in the arena`);
        }

        function clearArenaFilter() {
            currentArenaFilter = null;
            document.getElementById('arenaInput').value = '';
            // Re-render if we have data
            if (lastFiles) {
                processFiles(lastFiles);
            }
        }

        // Export test case
        function exportTestCase() {
            const active = getActiveFile();
            if (!active || !active.tile_samples || active.tile_samples.length === 0) {
                alert('No data to export. Upload a file first.');
                return;
            }

            const testCase = {
                version: '1.0',
                exported_at: new Date().toISOString(),
                filename: active.filename,
                tile_samples: active.tile_samples,
                thresholds: readThresholds(),
                wallet_tile_history: getTileHistory(),
                expected_patterns: active.patterns || null
            };

            const blob = new Blob([JSON.stringify(testCase, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `test-case-${Date.now()}.json`;
            a.click();
            URL.revokeObjectURL(url);
        }
    </script>
</body>
</html>
"""
