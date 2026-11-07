"""Admin endpoints for significance scoring dashboard."""

import logging
import math
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..dependencies import get_repository
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository
from ..utils.postgrest_paging import window
from .admin import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/significance", tags=["admin-significance"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_histogram(values: list, bin_min: float, bin_max: float, n_bins: int) -> list:
    """Build a histogram from a list of float values."""
    if not values:
        return []
    step = (bin_max - bin_min) / n_bins
    bins = [{"bin": round(bin_min + i * step, 3), "count": 0} for i in range(n_bins)]
    for v in values:
        idx = int((v - bin_min) / step)
        idx = max(0, min(n_bins - 1, idx))
        bins[idx]["count"] += 1
    return bins


# ---------------------------------------------------------------------------
# GET /admin/significance/overview
# ---------------------------------------------------------------------------

@router.get("/overview")
@rate_limit(category="general")
async def get_significance_overview(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Aggregate dashboard data: cell stats, GPD distributions, score distributions."""

    # --- Terrain cells ---
    cells_resp = repo.client.from_("terrain_cells").select("*").execute()
    cells = cells_resp.data or []

    tier_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    res_counts = {}
    diag_pass = 0
    diag_fail = 0
    oldest_bootstrap = None
    newest_bootstrap = None
    xi_values = []
    sigma_values = []
    diversity_tier_counts = {0: 0, 1: 0, 2: 0, 3: 0}
    single_rider_cells = 0
    effective_n_values = []

    for c in cells:
        tier = c.get("confidence_tier", 0)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

        res = c.get("h3_resolution", 5)
        res_counts[str(res)] = res_counts.get(str(res), 0) + 1

        if c.get("tail_diag_pass"):
            diag_pass += 1
        else:
            diag_fail += 1

        bs = c.get("bootstrapped_at")
        if bs:
            if oldest_bootstrap is None or bs < oldest_bootstrap:
                oldest_bootstrap = bs
            if newest_bootstrap is None or bs > newest_bootstrap:
                newest_bootstrap = bs

        if c.get("gpd_xi") is not None:
            xi_values.append(c["gpd_xi"])
        if c.get("gpd_sigma") is not None:
            sigma_values.append(c["gpd_sigma"])

        # Diversity stats
        d_tier = c.get("diversity_tier", 0)
        diversity_tier_counts[d_tier] = diversity_tier_counts.get(d_tier, 0) + 1
        n_riders = c.get("n_unique_riders", 0)
        if n_riders <= 1:
            single_rider_cells += 1
        eff_n = c.get("effective_n")
        if eff_n is not None:
            effective_n_values.append(eff_n)

    # GPD histograms — adaptive bin count (avoids empty-bar spam with few data points)
    xi_n_bins = max(3, min(20, len(xi_values) // 2)) if xi_values else 3
    xi_histogram = _build_histogram(xi_values, -0.5, 0.5, xi_n_bins) if xi_values else []
    sigma_max = max(sigma_values) * 1.1 if sigma_values else 100
    sigma_n_bins = max(3, min(20, len(sigma_values) // 2)) if sigma_values else 3
    sigma_histogram = _build_histogram(sigma_values, 0, sigma_max, sigma_n_bins) if sigma_values else []

    xi_stats = {}
    if xi_values:
        xi_sorted = sorted(xi_values)
        xi_stats = {
            "min": round(xi_sorted[0], 4),
            "max": round(xi_sorted[-1], 4),
            "mean": round(sum(xi_values) / len(xi_values), 4),
            "median": round(xi_sorted[len(xi_sorted) // 2], 4),
        }

    sigma_stats = {}
    if sigma_values:
        sigma_sorted = sorted(sigma_values)
        sigma_stats = {
            "min": round(sigma_sorted[0], 2),
            "max": round(sigma_sorted[-1], 2),
            "mean": round(sum(sigma_values) / len(sigma_values), 2),
            "median": round(sigma_sorted[len(sigma_sorted) // 2], 2),
        }

    # --- Climb scores ---
    scored_resp = repo.client.from_("patterns_climb") \
        .select("significance_g, significance_percentile, significance_confidence_tier") \
        .not_.is_("significance_g", "null") \
        .execute()
    scored = scored_resp.data or []

    unscored_resp = repo.client.from_("patterns_climb") \
        .select("id", count="exact") \
        .is_("significance_g", "null") \
        .execute()
    unscored_count = unscored_resp.count or 0

    g_values = [r["significance_g"] for r in scored if r.get("significance_g") is not None]
    pct_values = [r["significance_percentile"] for r in scored if r.get("significance_percentile") is not None]

    g_n_bins = max(3, min(10, len(g_values))) if g_values else 3
    g_histogram = _build_histogram(g_values, 0, 1.0, g_n_bins) if g_values else []
    pct_n_bins = max(3, min(10, len(pct_values))) if pct_values else 3
    pct_histogram = _build_histogram(pct_values, 0, 100, pct_n_bins) if pct_values else []

    # Effective N stats
    effective_n_stats = {}
    if effective_n_values:
        eff_sorted = sorted(effective_n_values)
        effective_n_stats = {
            "min": round(eff_sorted[0], 2),
            "max": round(eff_sorted[-1], 2),
            "median": round(eff_sorted[len(eff_sorted) // 2], 2),
        }

    return {
        "terrainCells": {
            "total": len(cells),
            "byConfidenceTier": tier_counts,
            "byResolution": res_counts,
            "diagPassCount": diag_pass,
            "diagFailCount": diag_fail,
            "oldestBootstrap": oldest_bootstrap,
            "newestBootstrap": newest_bootstrap,
            "byDiversityTier": diversity_tier_counts,
            "singleRiderCells": single_rider_cells,
            "effectiveNStats": effective_n_stats,
        },
        "gpdParams": {
            "xiHistogram": xi_histogram,
            "sigmaHistogram": sigma_histogram,
            "xiStats": xi_stats,
            "sigmaStats": sigma_stats,
        },
        "climbScores": {
            "total": len(scored) + unscored_count,
            "scored": len(scored),
            "unscored": unscored_count,
            "gHistogram": g_histogram,
            "percentileHistogram": pct_histogram,
        },
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/climbs
# ---------------------------------------------------------------------------

@router.get("/climbs")
@rate_limit(category="general")
async def get_significance_climbs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    min_g: Optional[float] = None,
    confidence_tier: Optional[int] = None,
    sort: str = "g_desc",
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Ranked table of scored climbs."""
    query = repo.client.from_("patterns_climb") \
        .select(
            "id, activity_id, road_name, vert_m, distance_m, avg_gradient_pct, "
            "persistence_m, significance_g, significance_percentile, "
            "significance_return_period, significance_confidence_tier, "
            "significance_bootstrapped, significance_cell_h3, "
            "signature_hex, review_status, reviewed_at, created_at",
            count="exact",
        ) \
        .not_.is_("significance_g", "null")

    if min_g is not None:
        query = query.gte("significance_g", min_g)
    if confidence_tier is not None:
        query = query.eq("significance_confidence_tier", confidence_tier)

    sort_map = {
        "g_desc": ("significance_g", True),
        "g_asc": ("significance_g", False),
        "percentile_desc": ("significance_percentile", True),
        "return_period_desc": ("significance_return_period", True),
        "vert_desc": ("vert_m", True),
        "persistence_desc": ("persistence_m", True),
    }
    col, desc = sort_map.get(sort, ("significance_g", True))
    query = window(query.order(col, desc=desc), offset, limit)

    result = query.execute()

    return {
        "climbs": result.data or [],
        "total": result.count or 0,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/cells
# ---------------------------------------------------------------------------

@router.get("/cells")
@rate_limit(category="general")
async def get_significance_cells(
    request: Request,
    limit: int = 200,
    confidence_tier: Optional[int] = None,
    resolution: Optional[int] = None,
    diversity_tier: Optional[int] = None,
    min_unique_riders: Optional[int] = None,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """List all terrain cells."""
    query = repo.client.from_("terrain_cells") \
        .select("*", count="exact")

    if confidence_tier is not None:
        query = query.eq("confidence_tier", confidence_tier)
    if resolution is not None:
        query = query.eq("h3_resolution", resolution)
    if diversity_tier is not None:
        query = query.eq("diversity_tier", diversity_tier)
    if min_unique_riders is not None:
        query = query.gte("n_unique_riders", min_unique_riders)

    query = query.order("bootstrapped_at", desc=True).limit(limit)
    result = query.execute()

    return {
        "cells": result.data or [],
        "total": result.count or 0,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/cells/{h3_index}
# ---------------------------------------------------------------------------

@router.get("/cells/{h3_index}")
@rate_limit(category="general")
async def get_significance_cell_detail(
    h3_index: str,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Detail view for a single terrain cell + climbs scored against it."""
    cell_resp = repo.client.from_("terrain_cells") \
        .select("*") \
        .eq("h3_index", h3_index) \
        .limit(1) \
        .execute()

    if not cell_resp.data:
        raise HTTPException(status_code=404, detail=f"Terrain cell {h3_index} not found")

    cell = cell_resp.data[0]

    # Find climbs scored against this cell
    climbs_resp = repo.client.from_("patterns_climb") \
        .select(
            "id, activity_id, road_name, vert_m, persistence_m, "
            "significance_g, significance_percentile, significance_return_period"
        ) \
        .eq("significance_cell_h3", h3_index) \
        .order("significance_g", desc=True) \
        .limit(50) \
        .execute()

    # Build explicit diversity metrics for the detail panel
    diversity_tier_names = {0: "suspect", 1: "thin", 2: "adequate", 3: "rich"}
    diversity_metrics = {
        "nUniqueRiders": cell.get("n_unique_riders", 0),
        "effectiveN": cell.get("effective_n"),
        "topRiderPct": cell.get("top_rider_pct"),
        "diversityTier": cell.get("diversity_tier", 0),
        "diversityTierName": diversity_tier_names.get(cell.get("diversity_tier", 0), "unknown"),
        "nUniqueRoutes": cell.get("n_unique_routes"),
    }

    return {
        "cell": cell,
        "climbsInCell": climbs_resp.data or [],
        "diversityMetrics": diversity_metrics,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/cells/{h3_index}/fit
# ---------------------------------------------------------------------------

@router.get("/cells/{h3_index}/fit")
@rate_limit(category="general")
async def get_cell_fit_data(
    h3_index: str,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """GPD fit visualization data: empirical + fitted survival curves, climb positions."""
    import numpy as np

    # Fetch cell
    cell_resp = repo.client.from_("terrain_cells") \
        .select("*") \
        .eq("h3_index", h3_index) \
        .limit(1) \
        .execute()

    if not cell_resp.data:
        raise HTTPException(status_code=404, detail=f"Terrain cell {h3_index} not found")

    cell = cell_resp.data[0]
    xi = cell.get("gpd_xi", 0.0)
    sigma = cell.get("gpd_sigma", 1.0)
    threshold_m = cell.get("threshold_m", 3.0)

    # Get all climbs in this cell with persistence values
    climbs_resp = repo.client.from_("patterns_climb") \
        .select("id, persistence_m, significance_g, road_name") \
        .eq("significance_cell_h3", h3_index) \
        .not_.is_("persistence_m", "null") \
        .order("persistence_m", desc=True) \
        .limit(200) \
        .execute()

    climbs_data = climbs_resp.data or []
    persistence_values = [r["persistence_m"] for r in climbs_data if r.get("persistence_m") is not None]

    # Build empirical + fitted curves
    fitted_curve = []
    if persistence_values:
        sorted_vals = sorted(persistence_values)
        n = len(sorted_vals)
        x_min = max(0, min(sorted_vals) - 5)
        x_max = max(sorted_vals) * 1.1

        # Generate evenly spaced x points
        x_points = np.linspace(x_min, x_max, min(50, max(20, n))).tolist()

        for x in x_points:
            # Empirical survival: fraction of values > x
            empirical_cdf = sum(1 for v in sorted_vals if v <= x) / n

            # GPD survival above threshold
            if x <= threshold_m:
                gpd_cdf = 0.0  # Below threshold, GPD not applicable
            else:
                y = x - threshold_m
                if abs(xi) > 1e-10 and sigma > 0:
                    inner = 1.0 + xi * y / sigma
                    if inner <= 0:
                        gpd_survival = 0.0
                    else:
                        gpd_survival = inner ** (-1.0 / xi)
                else:
                    gpd_survival = math.exp(-y / sigma) if sigma > 0 else 0.0

                # Scale by exceedance rate
                k = cell.get("k_exceedances", 0)
                n_features = cell.get("n_features", 1)
                exc_rate = k / n_features if n_features > 0 else 0.0
                gpd_cdf = 1.0 - (exc_rate * gpd_survival)

            fitted_curve.append({
                "x": round(x, 2),
                "empiricalCdf": round(empirical_cdf, 4),
                "gpdCdf": round(max(0.0, min(1.0, gpd_cdf)), 4),
            })

    # Climb positions
    climb_positions = [
        {
            "id": r["id"],
            "persistenceM": r["persistence_m"],
            "gScore": r.get("significance_g", 0.0) or 0.0,
            "roadName": r.get("road_name"),
        }
        for r in climbs_data
    ]

    return {
        "cell": cell,
        "persistenceValues": persistence_values,
        "thresholdM": threshold_m,
        "fittedCurve": fitted_curve,
        "climbPositions": climb_positions,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/climb/{climb_id}/trace
# ---------------------------------------------------------------------------

@router.get("/climb/{climb_id}/trace")
@rate_limit(category="general")
async def get_climb_scoring_trace(
    climb_id: str,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Full scoring trace for a single climb — exposes every intermediate calculation."""
    from ..services.terrain_bootstrap import (
        _cache_loaded,
        _terrain_cache,
        compute_significance_traced,
        load_terrain_cache,
        lookup_cell_traced,
        ConfidenceTier,
        TerrainCellFit,
        NOISE_GATE_M,
    )

    # Fetch the climb record
    climb_resp = repo.client.from_("patterns_climb") \
        .select("*") \
        .eq("id", climb_id) \
        .limit(1) \
        .execute()

    if not climb_resp.data:
        raise HTTPException(status_code=404, detail=f"Climb {climb_id} not found")

    climb = climb_resp.data[0]

    # Fetch the terrain cell (if scored)
    cell_data = None
    cell_h3 = climb.get("significance_cell_h3")
    if cell_h3:
        cell_resp = repo.client.from_("terrain_cells") \
            .select("*") \
            .eq("h3_index", cell_h3) \
            .limit(1) \
            .execute()
        if cell_resp.data:
            cell_data = cell_resp.data[0]

    # Ensure terrain cache is loaded for tracing
    if not _cache_loaded:
        await load_terrain_cache(repo.client)

    # Build the trace
    persistence_m = climb.get("persistence_m")
    tile_ids = climb.get("tile_ids") or []
    midpoint_tile = tile_ids[len(tile_ids) // 2] if tile_ids else None

    # Trace the cell lookup path
    cell_lookup = lookup_cell_traced(midpoint_tile)

    # If we have a cell, compute the full scoring trace
    trace = None
    if persistence_m is not None and cell_lookup.get("cellH3"):
        resolved_h3 = cell_lookup["cellH3"]
        if resolved_h3 in _terrain_cache:
            cell_fit = _terrain_cache[resolved_h3]

            # Check if this is a fallback (res-4) and reduce confidence
            is_fallback = cell_lookup.get("res4Fallback", False)
            if is_fallback and cell_fit.confidence_tier > ConfidenceTier.EMPIRICAL:
                from datetime import datetime, timezone
                cell_fit = TerrainCellFit(
                    h3_index=cell_fit.h3_index,
                    h3_resolution=cell_fit.h3_resolution,
                    n_features=cell_fit.n_features,
                    k_exceedances=cell_fit.k_exceedances,
                    threshold_m=cell_fit.threshold_m,
                    threshold_quantile=cell_fit.threshold_quantile,
                    gpd_xi=cell_fit.gpd_xi,
                    gpd_sigma=cell_fit.gpd_sigma,
                    xi_ci_hi=cell_fit.xi_ci_hi,
                    g_cap=cell_fit.g_cap,
                    confidence_tier=ConfidenceTier(max(0, int(cell_fit.confidence_tier) - 1)),
                    tail_diag_pass=cell_fit.tail_diag_pass,
                    bootstrapped_at=cell_fit.bootstrapped_at,
                    osm_road_km=cell_fit.osm_road_km,
                    parent_h3_index=cell_fit.parent_h3_index,
                )

            trace = compute_significance_traced(persistence_m, cell_fit)
            trace["cellLookup"] = cell_lookup
    elif persistence_m is not None:
        # No cell found — return a minimal trace showing where it stopped
        trace = {
            "persistenceM": round(persistence_m, 3),
            "noiseGateM": NOISE_GATE_M,
            "passedNoiseGate": persistence_m > NOISE_GATE_M,
            "cellLookup": cell_lookup,
            "gFinal": None,
            "reason": "No terrain cell found for climb location",
        }

    return {
        "climb": climb,
        "cell": cell_data,
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/pipeline-stats
# ---------------------------------------------------------------------------

@router.get("/pipeline-stats")
@rate_limit(category="general")
async def get_pipeline_stats(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Pipeline funnel stats: how many climbs survive each scoring stage."""

    # Total climbs detected
    total_resp = repo.client.from_("patterns_climb") \
        .select("id", count="exact") \
        .execute()
    climbs_detected = total_resp.count or 0

    # Climbs with persistence_m
    persist_resp = repo.client.from_("patterns_climb") \
        .select("id", count="exact") \
        .not_.is_("persistence_m", "null") \
        .execute()
    climbs_with_persistence = persist_resp.count or 0

    # Climbs matched to a terrain cell
    cell_resp = repo.client.from_("patterns_climb") \
        .select("id", count="exact") \
        .not_.is_("significance_cell_h3", "null") \
        .execute()
    climbs_in_terrain_cell = cell_resp.count or 0

    # Climbs with a final score
    scored_resp = repo.client.from_("patterns_climb") \
        .select("id", count="exact") \
        .not_.is_("significance_g", "null") \
        .execute()
    climbs_scored = scored_resp.count or 0

    climbs_unscored = climbs_with_persistence - climbs_scored

    # Build dropoff explanations
    dropoffs = []

    if climbs_with_persistence < climbs_detected:
        dropoffs.append({
            "stage": "detected_to_persistence",
            "from": climbs_detected,
            "to": climbs_with_persistence,
            "reason": "Climb too small or no persistence computed",
        })

    if climbs_in_terrain_cell < climbs_with_persistence:
        dropoffs.append({
            "stage": "persistence_to_cell",
            "from": climbs_with_persistence,
            "to": climbs_in_terrain_cell,
            "reason": "No terrain cell for climb location",
        })

    if climbs_scored < climbs_in_terrain_cell:
        dropoffs.append({
            "stage": "cell_to_scored",
            "from": climbs_in_terrain_cell,
            "to": climbs_scored,
            "reason": "Scoring not yet run (backfill pending)",
        })
    else:
        dropoffs.append({
            "stage": "cell_to_scored",
            "from": climbs_in_terrain_cell,
            "to": climbs_scored,
            "reason": "All scored",
        })

    return {
        "climbsDetected": climbs_detected,
        "climbsWithPersistence": climbs_with_persistence,
        "climbsInTerrainCell": climbs_in_terrain_cell,
        "climbsScored": climbs_scored,
        "climbsUnscored": climbs_unscored,
        "dropoffs": dropoffs,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/backfill-candidates
# ---------------------------------------------------------------------------

@router.get("/backfill-candidates")
@rate_limit(category="general")
async def get_backfill_candidates(
    request: Request,
    limit: int = 100,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Climbs with persistence but no significance score."""
    candidates_resp = repo.client.from_("patterns_climb") \
        .select(
            "id, activity_id, road_name, vert_m, persistence_m, created_at",
            count="exact",
        ) \
        .not_.is_("persistence_m", "null") \
        .is_("significance_g", "null") \
        .order("persistence_m", desc=True) \
        .limit(limit) \
        .execute()

    return {
        "candidates": candidates_resp.data or [],
        "totalMissing": candidates_resp.count or 0,
    }


# ---------------------------------------------------------------------------
# POST /admin/significance/bootstrap
# ---------------------------------------------------------------------------

@router.post("/bootstrap")
@rate_limit(category="general")
async def trigger_bootstrap(
    request: Request,
    min_rides_per_cell: int = 5,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Bootstrap terrain cells from accumulated ride data."""
    from ..services.terrain_bootstrap import bootstrap_from_rides

    admin_id, _role = admin_ctx

    cells_fitted = await bootstrap_from_rides(
        repo.client,
        min_rides_per_cell=min_rides_per_cell,
    )

    return {
        "cellsFitted": cells_fitted,
        "message": f"Bootstrapped {cells_fitted} terrain cells from ride data",
    }


# ---------------------------------------------------------------------------
# POST /admin/significance/backfill-scores
# ---------------------------------------------------------------------------

@router.post("/backfill-scores")
@rate_limit(category="general")
async def backfill_scores(
    request: Request,
    limit: int = 50,
    dry_run: bool = False,
    stale_only: bool = False,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Score unscored climbs against existing terrain cells.

    When stale_only=True, re-scores climbs flagged stale by drift detection
    instead of the normal unscored query. Clears the stale flag after scoring.
    """
    from ..services.terrain_bootstrap import load_terrain_cache, score_climb, _cache_loaded

    admin_id, _role = admin_ctx

    # Ensure cache is loaded
    if not _cache_loaded:
        await load_terrain_cache(repo.client)

    # Get candidates: either unscored or stale
    if stale_only:
        candidates = repo.client.from_("patterns_climb") \
            .select("id, persistence_m, tile_ids") \
            .not_.is_("persistence_m", "null") \
            .eq("significance_stale", True) \
            .order("persistence_m", desc=True) \
            .limit(limit) \
            .execute()
    else:
        candidates = repo.client.from_("patterns_climb") \
            .select("id, persistence_m, tile_ids") \
            .not_.is_("persistence_m", "null") \
            .is_("significance_g", "null") \
            .order("persistence_m", desc=True) \
            .limit(limit) \
            .execute()

    processed = 0
    scored = 0
    no_terrain = 0

    for row in candidates.data or []:
        tile_ids = row.get("tile_ids") or []
        if not tile_ids:
            no_terrain += 1
            continue

        midpoint = tile_ids[len(tile_ids) // 2]
        result = score_climb(row["persistence_m"], midpoint)
        processed += 1

        if result is None:
            no_terrain += 1
            continue

        scored += 1
        if not dry_run:
            # Resolve cell H3 for reference
            try:
                import h3
                cell_h3 = h3.cell_to_parent(midpoint, 5)
            except Exception:
                cell_h3 = None

            update_data = {
                "significance_g": result.g_score,
                "significance_percentile": result.percentile,
                "significance_return_period": result.return_period,
                "significance_confidence_tier": int(result.confidence_tier),
                "significance_bootstrapped": result.bootstrapped,
                "significance_cell_h3": cell_h3,
            }
            # Clear stale flag when re-scoring
            if stale_only:
                update_data["significance_stale"] = False

            repo.client.from_("patterns_climb") \
                .update(update_data) \
                .eq("id", row["id"]) \
                .execute()

    return {
        "processed": processed,
        "scored": scored,
        "noTerrainData": no_terrain,
        "dryRun": dry_run,
        "staleOnly": stale_only,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/climb/{climb_id}/profile
# ---------------------------------------------------------------------------

@router.get("/climb/{climb_id}/profile")
@rate_limit(category="general")
async def get_climb_elevation_profile(
    climb_id: str,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Elevation profile with persistence pairs for a single climb.

    Returns raw + smoothed elevation, tile samples with context padding,
    and all persistence pairs (including sub-noise-gate ones) for
    the admin elevation profile visualisation.
    """

    CONTEXT_BEFORE_S = 30
    CONTEXT_AFTER_S = 30
    SMOOTHING_WINDOW = 5
    NOISE_GATE_M = 3.0

    # 1. Fetch the climb record
    climb_resp = repo.client.from_("patterns_climb") \
        .select(
            "id, activity_id, road_name, vert_m, distance_m, avg_gradient_pct, "
            "persistence_m, significance_g, start_offset_s, end_offset_s"
        ) \
        .eq("id", climb_id) \
        .limit(1) \
        .execute()

    if not climb_resp.data:
        raise HTTPException(status_code=404, detail=f"Climb {climb_id} not found")

    climb = climb_resp.data[0]
    activity_id = climb.get("activity_id")
    start_s = climb.get("start_offset_s", 0) or 0
    end_s = climb.get("end_offset_s", 0) or 0

    if not activity_id:
        raise HTTPException(status_code=404, detail="Climb has no associated activity")

    # 2. Fetch tile samples with context padding
    t_min = max(0, start_s - CONTEXT_BEFORE_S)
    t_max = end_s + CONTEXT_AFTER_S

    samples_resp = repo.client.from_("activity_tile_samples") \
        .select("t, elevation_m, power_w, speed_mps") \
        .eq("activity_id", activity_id) \
        .gte("t", t_min) \
        .lte("t", t_max) \
        .order("t") \
        .limit(5000) \
        .execute()

    samples = samples_resp.data or []

    if not samples:
        return {
            "climb": {
                "id": climb["id"],
                "roadName": climb.get("road_name"),
                "vertM": climb.get("vert_m"),
                "distanceM": climb.get("distance_m"),
                "persistenceM": climb.get("persistence_m"),
                "significanceG": climb.get("significance_g"),
                "startOffsetS": start_s,
                "endOffsetS": end_s,
            },
            "profile": {
                "contextBeforeS": CONTEXT_BEFORE_S,
                "contextAfterS": CONTEXT_AFTER_S,
                "samples": [],
                "smoothed": [],
                "smoothingWindow": SMOOTHING_WINDOW,
            },
            "persistence": {
                "noiseGateM": NOISE_GATE_M,
                "pairs": [],
            },
        }

    # 3. Extract elevations and compute SMA(5) smoothed values
    elevations = [
        float(s.get("elevation_m", 0) or 0) for s in samples
    ]

    # SMA smoothing (centered window, matching Rust smooth_elevations)
    smoothed = []
    half_w = SMOOTHING_WINDOW // 2
    for i in range(len(elevations)):
        start_idx = max(0, i - half_w)
        end_idx = min(len(elevations), i + half_w + 1)
        window_slice = elevations[start_idx:end_idx]
        smoothed.append(round(sum(window_slice) / len(window_slice), 3))

    # 4. Compute persistence pairs via Rust (all pairs, tagged)
    pairs = []
    try:
        import workout_parse
        raw_pairs = workout_parse.compute_persistence_pairs(
            [float(e) for e in smoothed],
            noise_gate=NOISE_GATE_M,
        )
        pairs = [
            {
                "birthIdx": p["birth_idx"],
                "deathIdx": p["death_idx"],
                "birthElev": round(p["birth_elev"], 3),
                "deathElev": round(p["death_elev"], 3),
                "persistenceM": round(p["persistence"], 3),
                "aboveNoiseGate": p["above_noise_gate"],
            }
            for p in raw_pairs
        ]
    except Exception as e:
        logger.warning(f"compute_persistence_pairs failed for climb {climb_id}: {e}")

    # 5. Build response
    formatted_samples = [
        {
            "t": s.get("t"),
            "elevationM": float(s.get("elevation_m", 0) or 0),
            "powerW": s.get("power_w"),
            "speedMps": s.get("speed_mps"),
        }
        for s in samples
    ]

    return {
        "climb": {
            "id": climb["id"],
            "roadName": climb.get("road_name"),
            "vertM": climb.get("vert_m"),
            "distanceM": climb.get("distance_m"),
            "persistenceM": climb.get("persistence_m"),
            "significanceG": climb.get("significance_g"),
            "startOffsetS": start_s,
            "endOffsetS": end_s,
        },
        "profile": {
            "contextBeforeS": CONTEXT_BEFORE_S,
            "contextAfterS": CONTEXT_AFTER_S,
            "samples": formatted_samples,
            "smoothed": smoothed,
            "smoothingWindow": SMOOTHING_WINDOW,
        },
        "persistence": {
            "noiseGateM": NOISE_GATE_M,
            "pairs": pairs,
        },
    }


# ---------------------------------------------------------------------------
# Review Models
# ---------------------------------------------------------------------------

VALID_VERDICTS = {"confirmed", "false_positive", "disputed"}
VALID_CATEGORIES = {
    "noise", "too_short", "duplicate", "sensor_error",
    "misattributed", "borderline", "other",
}


class ReviewClimbBody(BaseModel):
    verdict: str
    reason: Optional[str] = None
    category: Optional[str] = None
    confidence_note: Optional[str] = None


class BulkReviewBody(BaseModel):
    climb_ids: list[str]
    verdict: str
    reason: Optional[str] = None
    category: Optional[str] = None


# ---------------------------------------------------------------------------
# POST /admin/significance/climbs/{climb_id}/review
# ---------------------------------------------------------------------------

@router.post("/climbs/{climb_id}/review")
@rate_limit(category="general")
async def review_climb(
    climb_id: str,
    body: ReviewClimbBody,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Submit a human review verdict for a single climb."""
    admin_id, _role = admin_ctx

    if body.verdict not in VALID_VERDICTS:
        raise HTTPException(status_code=400, detail=f"Invalid verdict. Must be one of: {VALID_VERDICTS}")
    if body.category and body.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {VALID_CATEGORIES}")

    # Fetch current review_status
    climb_resp = repo.client.from_("patterns_climb") \
        .select("id, review_status") \
        .eq("id", climb_id) \
        .limit(1) \
        .execute()

    if not climb_resp.data:
        raise HTTPException(status_code=404, detail=f"Climb {climb_id} not found")

    previous_status = climb_resp.data[0].get("review_status")

    # Insert review record
    repo.client.from_("climb_reviews").insert({
        "climb_id": climb_id,
        "reviewer_id": str(admin_id),
        "verdict": body.verdict,
        "previous_status": previous_status,
        "reason": body.reason,
        "category": body.category,
        "confidence_note": body.confidence_note,
    }).execute()

    # Update patterns_climb
    repo.client.from_("patterns_climb") \
        .update({
            "review_status": body.verdict,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_by": str(admin_id),
        }) \
        .eq("id", climb_id) \
        .execute()

    return {
        "climbId": climb_id,
        "verdict": body.verdict,
        "previousStatus": previous_status,
    }


# ---------------------------------------------------------------------------
# POST /admin/significance/climbs/bulk-review
# ---------------------------------------------------------------------------

@router.post("/climbs/bulk-review")
@rate_limit(category="general")
async def bulk_review_climbs(
    body: BulkReviewBody,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Submit a batch of review verdicts."""
    admin_id, _role = admin_ctx

    if body.verdict not in VALID_VERDICTS:
        raise HTTPException(status_code=400, detail=f"Invalid verdict. Must be one of: {VALID_VERDICTS}")
    if body.category and body.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {VALID_CATEGORIES}")
    if len(body.climb_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 climbs per batch")
    if not body.climb_ids:
        raise HTTPException(status_code=400, detail="climb_ids must not be empty")

    batch_id = str(uuid_mod.uuid4())
    reviewed = 0
    now_iso = datetime.now(timezone.utc).isoformat()

    for cid in body.climb_ids:
        # Fetch previous status
        climb_resp = repo.client.from_("patterns_climb") \
            .select("id, review_status") \
            .eq("id", cid) \
            .limit(1) \
            .execute()

        if not climb_resp.data:
            continue

        previous_status = climb_resp.data[0].get("review_status")

        repo.client.from_("climb_reviews").insert({
            "climb_id": cid,
            "reviewer_id": str(admin_id),
            "verdict": body.verdict,
            "previous_status": previous_status,
            "reason": body.reason,
            "category": body.category,
            "batch_id": batch_id,
        }).execute()

        repo.client.from_("patterns_climb") \
            .update({
                "review_status": body.verdict,
                "reviewed_at": now_iso,
                "reviewed_by": str(admin_id),
            }) \
            .eq("id", cid) \
            .execute()

        reviewed += 1

    return {
        "batchId": batch_id,
        "reviewed": reviewed,
        "total": len(body.climb_ids),
        "verdict": body.verdict,
    }


# ---------------------------------------------------------------------------
# POST /admin/significance/climbs/{climb_id}/revert
# ---------------------------------------------------------------------------

@router.post("/climbs/{climb_id}/revert")
@rate_limit(category="general")
async def revert_climb_review(
    climb_id: str,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Revert a climb's review status to unreviewed."""
    admin_id, _role = admin_ctx

    # Fetch current
    climb_resp = repo.client.from_("patterns_climb") \
        .select("id, review_status") \
        .eq("id", climb_id) \
        .limit(1) \
        .execute()

    if not climb_resp.data:
        raise HTTPException(status_code=404, detail=f"Climb {climb_id} not found")

    previous_status = climb_resp.data[0].get("review_status")

    # Insert revert record
    repo.client.from_("climb_reviews").insert({
        "climb_id": climb_id,
        "reviewer_id": str(admin_id),
        "verdict": "reverted",
        "previous_status": previous_status,
    }).execute()

    # Clear review fields
    repo.client.from_("patterns_climb") \
        .update({
            "review_status": None,
            "reviewed_at": None,
            "reviewed_by": None,
        }) \
        .eq("id", climb_id) \
        .execute()

    return {
        "climbId": climb_id,
        "previousStatus": previous_status,
        "verdict": "reverted",
    }


# ---------------------------------------------------------------------------
# POST /admin/significance/auto-confirm
# ---------------------------------------------------------------------------

@router.post("/auto-confirm")
@rate_limit(category="general")
async def auto_confirm_climbs(
    request: Request,
    min_g: float = 0.5,
    min_persistence: float = 15.0,
    min_confidence_tier: int = 2,
    dry_run: bool = False,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Auto-confirm high-confidence climbs that meet threshold criteria."""
    admin_id, _role = admin_ctx

    # Find candidates
    query = repo.client.from_("patterns_climb") \
        .select("id", count="exact") \
        .is_("review_status", "null") \
        .gte("significance_g", min_g) \
        .gte("persistence_m", min_persistence) \
        .gte("significance_confidence_tier", min_confidence_tier)

    result = query.execute()
    candidates = result.count or 0

    confirmed = 0
    if not dry_run and candidates > 0:
        now_iso = datetime.now(timezone.utc).isoformat()
        # Perform the bulk update
        repo.client.from_("patterns_climb") \
            .update({
                "review_status": "auto_confirmed",
                "reviewed_at": now_iso,
            }) \
            .is_("review_status", "null") \
            .gte("significance_g", min_g) \
            .gte("persistence_m", min_persistence) \
            .gte("significance_confidence_tier", min_confidence_tier) \
            .execute()
        confirmed = candidates

    return {
        "candidates": candidates,
        "confirmed": confirmed,
        "dryRun": dry_run,
        "thresholds": {
            "minG": min_g,
            "minPersistence": min_persistence,
            "minConfidenceTier": min_confidence_tier,
        },
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/review-queue
# ---------------------------------------------------------------------------

@router.get("/review-queue")
@rate_limit(category="general")
async def get_review_queue(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    cell_h3: Optional[str] = None,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Paginated list of climbs needing review, sorted by significance."""
    query = repo.client.from_("patterns_climb") \
        .select(
            "id, activity_id, road_name, vert_m, distance_m, avg_gradient_pct, "
            "persistence_m, significance_g, significance_percentile, "
            "significance_return_period, significance_confidence_tier, "
            "significance_cell_h3, signature_hex, review_status, reviewed_at, "
            "reviewed_by, created_at",
            count="exact",
        ) \
        .not_.is_("significance_g", "null")

    if status:
        query = query.eq("review_status", status)
    else:
        # Default: unreviewed climbs
        query = query.is_("review_status", "null")

    if cell_h3:
        query = query.eq("significance_cell_h3", cell_h3)

    query = window(query.order("significance_g", desc=True), offset, limit)
    result = query.execute()

    return {
        "climbs": result.data or [],
        "total": result.count or 0,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/cells-needing-refit
# ---------------------------------------------------------------------------

@router.get("/cells-needing-refit")
@rate_limit(category="general")
async def get_cells_needing_refit(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Cells with 3+ false positive flags that need GPD refit."""
    result = repo.client.from_("v_cell_feedback_summary") \
        .select("*") \
        .eq("needs_refit", True) \
        .execute()

    return {
        "cells": result.data or [],
        "total": len(result.data or []),
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/climbs/{climb_id}/reviews
# ---------------------------------------------------------------------------

@router.get("/climbs/{climb_id}/reviews")
@rate_limit(category="general")
async def get_climb_review_history(
    climb_id: str,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Full review history for a single climb."""
    # Verify climb exists
    climb_resp = repo.client.from_("patterns_climb") \
        .select("id") \
        .eq("id", climb_id) \
        .limit(1) \
        .execute()

    if not climb_resp.data:
        raise HTTPException(status_code=404, detail=f"Climb {climb_id} not found")

    result = repo.client.from_("climb_reviews") \
        .select("*") \
        .eq("climb_id", climb_id) \
        .order("created_at", desc=True) \
        .execute()

    return {
        "climbId": climb_id,
        "reviews": result.data or [],
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/cells/{h3_index}/history
# ---------------------------------------------------------------------------

@router.get("/cells/{h3_index}/history")
@rate_limit(category="general")
async def get_cell_history(
    h3_index: str,
    request: Request,
    limit: int = 20,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Parameter history and convergence status for a terrain cell."""

    history_resp = repo.client.from_("terrain_cell_history") \
        .select("*") \
        .eq("h3_index", h3_index) \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()

    history = history_resp.data or []

    # Compute convergence status from last 3 snapshots
    convergence_status = "insufficient_history"
    if len(history) >= 3:
        last3 = history[:3]  # Already desc by created_at
        deltas_xi = [abs(h.get("delta_xi") or 0) for h in last3 if h.get("delta_xi") is not None]
        deltas_sigma_rel = []
        for h in last3:
            d_sigma = h.get("delta_sigma")
            prev_sigma = h.get("prev_gpd_sigma")
            if d_sigma is not None and prev_sigma and prev_sigma > 0:
                deltas_sigma_rel.append(abs(d_sigma / prev_sigma))

        tier_changes = any(h.get("tier_changed", False) for h in last3)

        if len(deltas_xi) >= 3 and len(deltas_sigma_rel) >= 3:
            all_xi_small = all(d < 0.03 for d in deltas_xi)
            all_sigma_small = all(d < 0.10 for d in deltas_sigma_rel)

            if all_xi_small and all_sigma_small and not tier_changes:
                convergence_status = "stable"
            else:
                # Check if deltas are getting larger (diverging) or smaller (converging)
                # last3[0] is most recent, last3[2] is oldest
                if len(deltas_xi) >= 3:
                    if deltas_xi[0] > deltas_xi[1] > deltas_xi[2]:
                        convergence_status = "diverging"
                    elif deltas_xi[0] < deltas_xi[1] or deltas_xi[1] < deltas_xi[2]:
                        convergence_status = "converging"
                    else:
                        convergence_status = "converging"  # Default to converging if mixed

    return {
        "h3Index": h3_index,
        "history": history,
        "convergenceStatus": convergence_status,
        "snapshotCount": len(history),
    }


# ---------------------------------------------------------------------------
# GET /admin/significance/drift-summary
# ---------------------------------------------------------------------------

@router.get("/drift-summary")
@rate_limit(category="general")
async def get_drift_summary(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Summary of the most recent bootstrap run's drift detection results."""

    # Get most recent run_id
    latest_resp = repo.client.from_("terrain_cell_history") \
        .select("run_id, trigger_reason") \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()

    if not latest_resp.data:
        return {
            "runId": None,
            "totalCells": 0,
            "driftedCells": 0,
            "staleClimbs": 0,
            "driftedCellDetails": [],
            "triggerReason": None,
        }

    run_id = latest_resp.data[0]["run_id"]
    trigger_reason = latest_resp.data[0].get("trigger_reason")

    # Fetch all cells from that run
    run_resp = repo.client.from_("terrain_cell_history") \
        .select("h3_index, delta_xi, delta_sigma, max_score_impact, drift_flagged, "
                "tier_changed, diag_changed, confidence_tier, n_features") \
        .eq("run_id", run_id) \
        .execute()

    run_cells = run_resp.data or []
    total_cells = len(run_cells)
    drifted = [c for c in run_cells if c.get("drift_flagged")]
    drifted_cells = len(drifted)

    # Count stale climbs
    stale_resp = repo.client.from_("patterns_climb") \
        .select("id", count="exact") \
        .eq("significance_stale", True) \
        .execute()
    stale_climbs = stale_resp.count or 0

    # Build drifted cell details
    drifted_details = [
        {
            "h3Index": c["h3_index"],
            "deltaXi": c.get("delta_xi"),
            "deltaSigma": c.get("delta_sigma"),
            "maxScoreImpact": c.get("max_score_impact"),
            "tierChanged": c.get("tier_changed", False),
            "diagChanged": c.get("diag_changed", False),
            "confidenceTier": c.get("confidence_tier"),
            "nFeatures": c.get("n_features"),
        }
        for c in drifted
    ]

    return {
        "runId": run_id,
        "totalCells": total_cells,
        "driftedCells": drifted_cells,
        "staleClimbs": stale_climbs,
        "driftedCellDetails": drifted_details,
        "triggerReason": trigger_reason,
    }
