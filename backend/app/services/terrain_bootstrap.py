"""
Terrain Bootstrap — GPD Significance Scoring for Climbs

Fits a Generalized Pareto Distribution (GPD) to persistence values per H3 cell,
then scores individual climbs relative to their local terrain context.

A 30m hill in the Netherlands is more remarkable than a 30m hill in the Alps.
The GPD shape parameter xi encodes this automatically:
  xi > 0.1  => mountainous (heavy-tailed, always a bigger climb)
  -0.05..0.1 => rolling (exponential decay)
  xi < -0.05 => flat (bounded, finite maximum possible climb)

Estimation: PWM (L-moments) only. No MLE (avoids Newton-Raphson convergence issues).
Scoring: conservative (profile-likelihood CI upper bound on xi).

Reference: CLIMB_DETECTION_V2_SPEC.md, Section 5.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NOISE_GATE_M = 3.0          # Gumbel EVT noise floor (spec section 4)
MIN_EXCEEDANCES_GPD = 12    # Minimum k for PWM estimation
MIN_EXCEEDANCES_EMPIRICAL = 8  # Below this, no scoring at all
THRESHOLD_FLOOR_QUANTILE = 0.80  # Never go below 80th percentile
THRESHOLD_CANDIDATES = [0.80, 0.85, 0.90, 0.95]
XI_CLAMP = 0.49             # Clamp xi to [-0.49, 0.49]
DIAG_FAIL_SCORE_CAP = 0.60  # Cap scores when diagnostics fail
DIAG_FAIL_UNCERTAINTY_ADD = 0.10


class ConfidenceTier(IntEnum):
    """Confidence in GPD fit quality."""
    EMPIRICAL = 0   # k < 12, empirical quantiles + cap
    LOW = 1         # 12 <= k < 20, PWM + cap
    MODERATE = 2    # 20 <= k < 30, PWM, uncapped if diagnostics pass
    FULL = 3        # k >= 30, PWM + full uncertainty propagation


# ---------------------------------------------------------------------------
# Rider Diversity
# ---------------------------------------------------------------------------

def compute_diversity_metrics(wallets: List[str], signatures: List[Optional[str]]) -> dict:
    """
    Compute Kish effective sample size and diversity tier.

    The Kish effective sample size measures how many "independent" observations
    we effectively have, accounting for repeat-rider dominance. If one rider
    contributes 90% of observations, effective_n will be close to 1 regardless
    of total sample count.

    Diversity tiers:
        0 (suspect)  - single rider or effective_n < 3
        1 (thin)     - 2-4 unique riders or effective_n < 8
        2 (adequate) - 5-9 riders with effective_n >= 8
        3 (rich)     - 10+ riders with effective_n >= 15
    """
    from collections import Counter

    wallet_counts = Counter(wallets)
    n_unique_riders = len(wallet_counts)
    counts = list(wallet_counts.values())
    total = sum(counts)
    sum_sq = sum(c * c for c in counts)
    effective_n = (total * total) / sum_sq if sum_sq > 0 else 0.0
    top_rider_pct = max(counts) / total if total > 0 else 1.0
    n_unique_routes = len(set(s for s in signatures if s)) or None

    if n_unique_riders <= 1 or effective_n < 3.0:
        diversity_tier = 0  # suspect
    elif n_unique_riders < 5 or effective_n < 8.0:
        diversity_tier = 1  # thin
    elif n_unique_riders >= 10 and effective_n >= 15.0:
        diversity_tier = 3  # rich
    else:
        diversity_tier = 2  # adequate

    return {
        "n_unique_riders": n_unique_riders,
        "effective_n": round(effective_n, 2),
        "top_rider_pct": round(top_rider_pct, 4),
        "diversity_tier": diversity_tier,
        "n_unique_routes": n_unique_routes,
    }


def adjusted_confidence_tier(
    raw_tier: ConfidenceTier,
    diversity_tier: int,
) -> ConfidenceTier:
    """
    Cap confidence tier based on rider diversity.

    No matter how good the GPD fit looks statistically, if all the data
    comes from one rider we can't trust it to generalize.

    Mapping:
        diversity_tier 0 (suspect)  -> max EMPIRICAL (0)
        diversity_tier 1 (thin)     -> max LOW (1)
        diversity_tier 2 (adequate) -> max MODERATE (2)
        diversity_tier 3 (rich)     -> max FULL (3)
    """
    max_tier = min(diversity_tier, int(ConfidenceTier.FULL))
    return ConfidenceTier(min(int(raw_tier), max_tier))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TerrainCellFit:
    """Fitted GPD parameters for a single H3 cell."""
    h3_index: str
    h3_resolution: int
    n_features: int
    k_exceedances: int
    threshold_m: float
    threshold_quantile: float
    gpd_xi: float
    gpd_sigma: float
    xi_ci_hi: float
    g_cap: float
    confidence_tier: ConfidenceTier
    tail_diag_pass: bool
    bootstrapped_at: Optional[datetime] = None
    osm_road_km: Optional[float] = None
    parent_h3_index: Optional[str] = None
    # Rider diversity fields
    n_unique_riders: int = 0
    effective_n: Optional[float] = None
    top_rider_pct: Optional[float] = None
    diversity_tier: int = 0
    n_unique_routes: Optional[int] = None

    def to_db_dict(self) -> dict:
        """Convert to dict for Supabase upsert."""
        return {
            "h3_index": self.h3_index,
            "h3_resolution": self.h3_resolution,
            "n_features": self.n_features,
            "k_exceedances": self.k_exceedances,
            "threshold_m": round(self.threshold_m, 3),
            "threshold_quantile": round(self.threshold_quantile, 3),
            "gpd_xi": round(self.gpd_xi, 6),
            "gpd_sigma": round(self.gpd_sigma, 6),
            "xi_ci_hi": round(self.xi_ci_hi, 6),
            "g_cap": round(self.g_cap, 4),
            "confidence_tier": int(self.confidence_tier),
            "tail_diag_pass": self.tail_diag_pass,
            "bootstrapped_at": (self.bootstrapped_at or datetime.now(timezone.utc)).isoformat(),
            "osm_road_km": round(self.osm_road_km, 2) if self.osm_road_km else None,
            "parent_h3_index": self.parent_h3_index,
            "n_unique_riders": self.n_unique_riders,
            "effective_n": round(self.effective_n, 2) if self.effective_n is not None else None,
            "top_rider_pct": round(self.top_rider_pct, 4) if self.top_rider_pct is not None else None,
            "diversity_tier": self.diversity_tier,
            "n_unique_routes": self.n_unique_routes,
        }


@dataclass
class SignificanceResult:
    """Significance score for a single climb."""
    g_score: float          # Conservative score (use for decisions), 0-1
    g_point: float          # Point estimate (reference only)
    g_uncertainty: float    # Score uncertainty width (g_point - g_score)
    percentile: float       # Local percentile (0-100)
    return_period: float    # Expected return period (1-in-N climbs)
    confidence_tier: ConfidenceTier
    bootstrapped: bool      # True if scored against DEM-fitted cell
    source_resolution: int  # H3 resolution of the cell used (4 or 5)


# ---------------------------------------------------------------------------
# GPD Estimation: PWM (L-moments)
# ---------------------------------------------------------------------------

def fit_gpd_pwm(exceedances: np.ndarray) -> Tuple[float, float]:
    """
    Fit GPD via Probability-Weighted Moments (L-moments).

    Given sorted exceedances y_1 <= y_2 <= ... <= y_k above threshold u:
        b0 = mean(y)
        b1 = mean(((i-1)/(k-1)) * y_i)
        xi = 2 - b0 / (b0 - 2*b1)
        sigma = 2 * b0 * b1 / (b0 - 2*b1)

    Returns (xi, sigma). Clamps xi to [-0.49, 0.49].
    """
    y = np.sort(exceedances)
    k = len(y)
    if k < 2:
        return (0.0, float(np.mean(y)) if k > 0 else 1.0)

    b0 = np.mean(y)
    # Hosking & Wallis (1987): a_1 uses DESCENDING weights (k-1-i)/(k-1)
    # so the smallest value gets weight 1, largest gets weight 0
    weights = (k - 1 - np.arange(k)) / (k - 1)
    b1 = np.mean(weights * y)

    denom = b0 - 2.0 * b1
    if abs(denom) < 1e-12:
        # Degenerate: all exceedances identical
        return (0.0, max(b0, 1e-6))

    xi = 2.0 - b0 / denom
    sigma = 2.0 * b0 * b1 / denom

    # Clamp xi to valid range
    xi = max(-XI_CLAMP, min(XI_CLAMP, xi))
    sigma = max(sigma, 1e-6)

    return (xi, sigma)


def xi_confidence_interval(xi: float, k: int) -> float:
    """
    90% upper confidence bound on xi (analytic asymptotic variance).

    Var(xi) ~ (1 + xi)^2 * (1 + 2*xi)^2 / (k * (3 + 2*xi)^2 * (4 + 2*xi))
    xi_hi = xi + 1.645 * sqrt(Var(xi))
    """
    if k < 2:
        return xi + 0.5

    denom = k * (3.0 + 2.0 * xi) ** 2 * (4.0 + 2.0 * xi)
    if denom <= 0:
        return xi + 0.5

    var_xi = (1.0 + xi) ** 2 * (1.0 + 2.0 * xi) ** 2 / denom
    if var_xi < 0:
        var_xi = 0.0

    return xi + 1.645 * math.sqrt(var_xi)


def compute_score_cap(k: int, threshold_quantile: float) -> float:
    """
    Sample-size score cap from Beta(1, k) posterior at 90% confidence.

    G_cap(k) = -log10((1 - q) * (1 - 0.10^(1/k))) / 3
    """
    if k < 1:
        return 0.0

    q = threshold_quantile
    p_tail = 1.0 - 0.10 ** (1.0 / k)
    survival = (1.0 - q) * p_tail

    if survival <= 0:
        return 1.0

    return min(1.0, -math.log10(survival) / 3.0)


# ---------------------------------------------------------------------------
# Threshold Selection
# ---------------------------------------------------------------------------

def select_threshold(
    persistence_values: np.ndarray,
) -> Tuple[float, float, np.ndarray]:
    """
    Adaptive threshold selection: search quantiles 0.80-0.95 for parameter stability.

    Returns (threshold_m, threshold_quantile, exceedances).
    """
    n = len(persistence_values)
    if n < MIN_EXCEEDANCES_EMPIRICAL:
        # Too few values — use noise floor as threshold
        mask = persistence_values > NOISE_GATE_M
        return (NOISE_GATE_M, 0.0, persistence_values[mask])

    # Fit at each candidate quantile
    fits = []
    for q in THRESHOLD_CANDIDATES:
        u_q = float(np.quantile(persistence_values, q))
        u_q = max(u_q, NOISE_GATE_M)  # Never below noise floor
        exc = persistence_values[persistence_values > u_q]
        k_q = len(exc)
        if k_q < MIN_EXCEEDANCES_GPD:
            fits.append((q, u_q, k_q, None, None))
            continue
        xi_q, sigma_q = fit_gpd_pwm(exc - u_q)
        fits.append((q, u_q, k_q, xi_q, sigma_q))

    # Find stability region: lowest q where xi range < 0.15 across all higher qs
    valid_fits = [(q, u, k, xi, sig) for q, u, k, xi, sig in fits if xi is not None]

    if not valid_fits:
        # No valid fits — fall back to 80th percentile
        u = max(float(np.quantile(persistence_values, 0.80)), NOISE_GATE_M)
        exc = persistence_values[persistence_values > u]
        return (u, 0.80, exc)

    best_q = valid_fits[0][0]  # Default to lowest valid quantile

    for i, (q_i, _, _, xi_i, _) in enumerate(valid_fits):
        higher = valid_fits[i:]
        if len(higher) < 2:
            break
        xi_range = max(f[3] for f in higher) - min(f[3] for f in higher)
        if xi_range < 0.15:
            best_q = q_i
            break

    # Use the selected quantile
    selected = [f for f in fits if f[0] == best_q][0]
    u = selected[1]
    exc = persistence_values[persistence_values > u]

    return (u, best_q, exc)


# ---------------------------------------------------------------------------
# Tail Diagnostics
# ---------------------------------------------------------------------------

def run_tail_diagnostics(
    exceedances: np.ndarray,
    xi: float,
    sigma: float,
) -> bool:
    """
    Three diagnostics — cell passes if >= 2 of 3 pass.

    1. Hill Stability (tests tail index directly)
    2. Tail Ratio (tests tail density)
    3. Mean Excess Linearity (tests GPD assumption)
    """
    k = len(exceedances)
    if k < 5:
        return False

    passes = 0

    # 1. Hill Stability
    sorted_exc = np.sort(exceedances)[::-1]  # Descending
    m_max = max(5, k // 3)
    hill_ok = True
    for m in range(5, min(m_max + 1, k)):
        if m < 2:
            continue
        top_m = sorted_exc[:m]
        if top_m[-1] <= 0:
            hill_ok = False
            break
        h_m = np.mean(np.log(top_m / top_m[-1]))
        if abs(h_m - xi) > 0.3:
            hill_ok = False
            break
    if hill_ok:
        passes += 1

    # 2. Tail Ratio
    if k >= 5:
        # GPD quantile at 10% survival
        if abs(xi) > 1e-10:
            q90 = sigma * ((0.10 ** (-xi)) - 1.0) / xi
        else:
            q90 = -sigma * math.log(0.10)

        count_above = np.sum(exceedances > q90)
        expected = k * 0.10
        if expected > 0:
            t_r = count_above / expected
            if k >= 20:
                if 0.3 <= t_r <= 2.5:
                    passes += 1
            else:
                if 0.1 <= t_r <= 4.0:
                    passes += 1

    # 3. Mean Excess Linearity
    if k >= 10:
        q75 = float(np.quantile(exceedances, 0.75))
        thresholds = np.linspace(0, q75, min(20, k // 2))
        me_values = []
        th_values = []
        for u in thresholds:
            above = exceedances[exceedances > u]
            if len(above) >= 3:
                me_values.append(np.mean(above - u))
                th_values.append(u)
        if len(me_values) >= 4:
            # Linear fit R^2
            th_arr = np.array(th_values)
            me_arr = np.array(me_values)
            coeffs = np.polyfit(th_arr, me_arr, 1)
            fitted = np.polyval(coeffs, th_arr)
            ss_res = np.sum((me_arr - fitted) ** 2)
            ss_tot = np.sum((me_arr - np.mean(me_arr)) ** 2)
            r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
            if r_squared > 0.80:
                passes += 1

    return passes >= 2


# ---------------------------------------------------------------------------
# Score Computation
# ---------------------------------------------------------------------------

def compute_significance(
    persistence: float,
    cell: TerrainCellFit,
) -> SignificanceResult:
    """
    Score a single climb's persistence against its terrain cell's GPD fit.

    Uses conservative scoring (xi_ci_hi) for decisions.
    Returns G_conservative in [0, 1] where 0.33 = 1-in-10, 0.67 = 1-in-100, 1.0 = 1-in-1000.
    """
    u = cell.threshold_m
    xi = cell.gpd_xi
    sigma = cell.gpd_sigma
    xi_hi = cell.xi_ci_hi
    k = cell.k_exceedances
    n = cell.n_features

    if n == 0 or persistence <= NOISE_GATE_M:
        return SignificanceResult(
            g_score=0.0, g_point=0.0, g_uncertainty=0.0,
            percentile=0.0, return_period=1.0,
            confidence_tier=cell.confidence_tier,
            bootstrapped=cell.bootstrapped_at is not None,
            source_resolution=cell.h3_resolution,
        )

    exceedance_rate = k / n if n > 0 else 0.0

    if persistence <= u:
        # Below threshold: linear interpolation
        survival = exceedance_rate + (1.0 - exceedance_rate) * (1.0 - persistence / u)
        survival = max(survival, 1e-10)
        g_point = min(1.0, -math.log10(survival) / 3.0)
        g_score = g_point  # No GPD uncertainty below threshold
        g_uncertainty = 0.0
    else:
        # Above threshold: GPD regime
        y = persistence - u

        # Point estimate
        if abs(xi) > 1e-10 and sigma > 0:
            inner = 1.0 + xi * y / sigma
            if inner <= 0:
                # Beyond GPD support (for xi < 0)
                s_gpd_point = 0.0
            else:
                s_gpd_point = inner ** (-1.0 / xi)
        else:
            s_gpd_point = math.exp(-y / sigma) if sigma > 0 else 0.0

        survival_point = exceedance_rate * s_gpd_point
        survival_point = max(survival_point, 1e-10)
        g_point = min(1.0, -math.log10(survival_point) / 3.0)

        # Conservative estimate (using xi_hi = upper CI bound)
        # Higher xi = heavier tail = less surprising = lower score
        sigma_hi = sigma  # Keep sigma fixed for conservative estimate
        if abs(xi_hi) > 1e-10 and sigma_hi > 0:
            inner_hi = 1.0 + xi_hi * y / sigma_hi
            if inner_hi <= 0:
                s_gpd_cons = 0.0
            else:
                s_gpd_cons = inner_hi ** (-1.0 / xi_hi)
        else:
            s_gpd_cons = math.exp(-y / sigma_hi) if sigma_hi > 0 else 0.0

        survival_cons = exceedance_rate * s_gpd_cons
        survival_cons = max(survival_cons, 1e-10)
        g_score = min(1.0, -math.log10(survival_cons) / 3.0)
        g_uncertainty = g_point - g_score

    # Apply score cap
    g_score = min(g_score, cell.g_cap)
    g_point = min(g_point, cell.g_cap + g_uncertainty)

    # Apply diagnostic failure penalty
    if not cell.tail_diag_pass:
        g_score = min(g_score, DIAG_FAIL_SCORE_CAP)
        g_uncertainty += DIAG_FAIL_UNCERTAINTY_ADD

    # Compute percentile and return period from point survival
    if persistence > u:
        survival_for_pct = exceedance_rate * s_gpd_point
    else:
        survival_for_pct = survival
    percentile = (1.0 - survival_for_pct) * 100.0
    return_period = 1.0 / max(survival_for_pct, 1e-10)

    return SignificanceResult(
        g_score=round(g_score, 4),
        g_point=round(g_point, 4),
        g_uncertainty=round(max(0, g_uncertainty), 4),
        percentile=round(percentile, 1),
        return_period=round(return_period, 1),
        confidence_tier=cell.confidence_tier,
        bootstrapped=cell.bootstrapped_at is not None,
        source_resolution=cell.h3_resolution,
    )


# ---------------------------------------------------------------------------
# Traced Scoring (for admin dashboard)
# ---------------------------------------------------------------------------

def lookup_cell_traced(midpoint_h3_res10: Optional[str]) -> dict:
    """
    Trace the cell lookup path for a given H3 res-10 index.

    Returns a dict describing which cells were checked and what was found.
    """
    result = {
        "midpointTile": midpoint_h3_res10,
        "res5Parent": None,
        "res5Found": False,
        "res5ConfidenceTier": None,
        "res4Parent": None,
        "res4Fallback": False,
        "cellH3": None,
        "cellResolution": None,
    }

    if not midpoint_h3_res10 or not _cache_loaded:
        return result

    try:
        import h3
        res5 = h3.cell_to_parent(midpoint_h3_res10, 5)
        result["res5Parent"] = res5

        res4 = h3.cell_to_parent(midpoint_h3_res10, 4)
        result["res4Parent"] = res4

        # Check res-5 with moderate+ confidence first
        if res5 in _terrain_cache:
            cell = _terrain_cache[res5]
            result["res5Found"] = True
            result["res5ConfidenceTier"] = int(cell.confidence_tier)
            if cell.confidence_tier >= ConfidenceTier.MODERATE:
                result["cellH3"] = res5
                result["cellResolution"] = cell.h3_resolution
                return result

        # Fallback to res-4
        if res4 in _terrain_cache:
            result["res4Fallback"] = True
            result["cellH3"] = res4
            result["cellResolution"] = _terrain_cache[res4].h3_resolution
            return result

        # Low-confidence res-5 is still usable
        if res5 in _terrain_cache:
            result["cellH3"] = res5
            result["cellResolution"] = _terrain_cache[res5].h3_resolution
            return result

    except Exception:
        pass

    return result


def compute_significance_traced(
    persistence: float,
    cell: TerrainCellFit,
) -> dict:
    """
    Traced version of compute_significance — returns all intermediate values.

    Same math as compute_significance(), but exposes every calculation step
    for the admin dashboard's ScoringTrace component.
    """
    u = cell.threshold_m
    xi = cell.gpd_xi
    sigma = cell.gpd_sigma
    xi_hi = cell.xi_ci_hi
    k = cell.k_exceedances
    n = cell.n_features

    trace = {
        "persistenceM": round(persistence, 3),
        "noiseGateM": NOISE_GATE_M,
        "passedNoiseGate": persistence > NOISE_GATE_M,
        "cellH3": cell.h3_index,
        "nFeatures": n,
        "kExceedances": k,
        "thresholdM": round(u, 3),
        "thresholdQuantile": round(cell.threshold_quantile, 4),
        "exceedanceM": round(max(0, persistence - u), 3),
        "aboveThreshold": persistence > u,
        "exceedanceRate": round(k / n, 6) if n > 0 else 0.0,
        "gpdXi": round(xi, 6),
        "gpdSigma": round(sigma, 6),
        "xiCiHi": round(xi_hi, 6),
        "survivalPoint": None,
        "survivalConservative": None,
        "gPoint": 0.0,
        "gConservative": 0.0,
        "gCap": round(cell.g_cap, 4),
        "gCapApplied": False,
        "diagPass": cell.tail_diag_pass,
        "diagPenaltyApplied": False,
        "gFinal": 0.0,
        "confidenceTier": int(cell.confidence_tier),
        "confidenceTierName": cell.confidence_tier.name,
        "percentile": 0.0,
        "returnPeriod": 1.0,
    }

    if n == 0 or persistence <= NOISE_GATE_M:
        return trace

    exceedance_rate = k / n if n > 0 else 0.0

    if persistence <= u:
        # Below threshold: linear interpolation
        survival = exceedance_rate + (1.0 - exceedance_rate) * (1.0 - persistence / u)
        survival = max(survival, 1e-10)
        g_point = min(1.0, -math.log10(survival) / 3.0)
        g_score = g_point
        g_uncertainty = 0.0

        trace["survivalPoint"] = round(survival, 10)
        trace["survivalConservative"] = round(survival, 10)
        trace["gPoint"] = round(g_point, 6)
        trace["gConservative"] = round(g_score, 6)

        survival_for_pct = survival
    else:
        # Above threshold: GPD regime
        y = persistence - u

        # Point estimate
        if abs(xi) > 1e-10 and sigma > 0:
            inner = 1.0 + xi * y / sigma
            if inner <= 0:
                s_gpd_point = 0.0
            else:
                s_gpd_point = inner ** (-1.0 / xi)
        else:
            s_gpd_point = math.exp(-y / sigma) if sigma > 0 else 0.0

        survival_point = exceedance_rate * s_gpd_point
        survival_point = max(survival_point, 1e-10)
        g_point = min(1.0, -math.log10(survival_point) / 3.0)

        # Conservative estimate (using xi_hi = upper CI bound)
        sigma_hi = sigma
        if abs(xi_hi) > 1e-10 and sigma_hi > 0:
            inner_hi = 1.0 + xi_hi * y / sigma_hi
            if inner_hi <= 0:
                s_gpd_cons = 0.0
            else:
                s_gpd_cons = inner_hi ** (-1.0 / xi_hi)
        else:
            s_gpd_cons = math.exp(-y / sigma_hi) if sigma_hi > 0 else 0.0

        survival_cons = exceedance_rate * s_gpd_cons
        survival_cons = max(survival_cons, 1e-10)
        g_score = min(1.0, -math.log10(survival_cons) / 3.0)
        g_uncertainty = g_point - g_score

        trace["survivalPoint"] = round(survival_point, 10)
        trace["survivalConservative"] = round(survival_cons, 10)
        trace["gPoint"] = round(g_point, 6)
        trace["gConservative"] = round(g_score, 6)

        survival_for_pct = exceedance_rate * s_gpd_point

    # Apply score cap
    g_before_cap = g_score
    g_score = min(g_score, cell.g_cap)
    g_point = min(g_point, cell.g_cap + g_uncertainty)
    trace["gCapApplied"] = g_before_cap > cell.g_cap

    # Apply diagnostic failure penalty
    if not cell.tail_diag_pass:
        g_before_diag = g_score
        g_score = min(g_score, DIAG_FAIL_SCORE_CAP)
        g_uncertainty += DIAG_FAIL_UNCERTAINTY_ADD
        trace["diagPenaltyApplied"] = g_before_diag > DIAG_FAIL_SCORE_CAP

    # Final values
    percentile = (1.0 - survival_for_pct) * 100.0
    return_period = 1.0 / max(survival_for_pct, 1e-10)

    trace["gFinal"] = round(g_score, 4)
    trace["percentile"] = round(percentile, 1)
    trace["returnPeriod"] = round(return_period, 1)

    return trace


# ---------------------------------------------------------------------------
# Cell Fitting
# ---------------------------------------------------------------------------

def fit_terrain_cell(
    h3_index: str,
    h3_resolution: int,
    persistence_values: List[float],
    parent_h3_index: Optional[str] = None,
    osm_road_km: Optional[float] = None,
) -> Optional[TerrainCellFit]:
    """
    Fit GPD to persistence values for a single H3 cell.

    Steps:
    1. Filter to above noise floor
    2. Select threshold adaptively
    3. Fit GPD via PWM
    4. Compute confidence interval, score cap
    5. Run tail diagnostics
    6. Assign confidence tier
    """
    values = np.array([v for v in persistence_values if v > NOISE_GATE_M], dtype=np.float64)
    n_features = len(values)

    if n_features < MIN_EXCEEDANCES_EMPIRICAL:
        logger.info(
            f"[TerrainBootstrap] Cell {h3_index}: only {n_features} features "
            f"above noise floor (need {MIN_EXCEEDANCES_EMPIRICAL})"
        )
        return None

    # Threshold selection
    threshold_m, threshold_quantile, exceedances = select_threshold(values)

    k = len(exceedances)
    if k < 2:
        return None

    # Fit GPD via PWM
    exc_above = exceedances - threshold_m
    exc_above = exc_above[exc_above > 0]
    k = len(exc_above)

    if k < MIN_EXCEEDANCES_EMPIRICAL:
        # Not enough exceedances for GPD — empirical mode
        xi, sigma = 0.0, float(np.mean(exc_above)) if len(exc_above) > 0 else 1.0
        xi_hi = xi + 0.5
        confidence_tier = ConfidenceTier.EMPIRICAL
        tail_diag_pass = False
    else:
        xi, sigma = fit_gpd_pwm(exc_above)
        xi_hi = xi_confidence_interval(xi, k)
        xi_hi = max(-XI_CLAMP, min(XI_CLAMP, xi_hi))

        # Run tail diagnostics
        tail_diag_pass = run_tail_diagnostics(exc_above, xi, sigma)

        # Assign confidence tier
        if k < MIN_EXCEEDANCES_GPD:
            confidence_tier = ConfidenceTier.EMPIRICAL
        elif k < 20:
            confidence_tier = ConfidenceTier.LOW
        elif k < 30:
            confidence_tier = ConfidenceTier.MODERATE
        else:
            confidence_tier = ConfidenceTier.FULL

    # Score cap from Beta posterior
    g_cap = compute_score_cap(k, threshold_quantile)

    cell_fit = TerrainCellFit(
        h3_index=h3_index,
        h3_resolution=h3_resolution,
        n_features=n_features,
        k_exceedances=k,
        threshold_m=threshold_m,
        threshold_quantile=threshold_quantile,
        gpd_xi=xi,
        gpd_sigma=sigma,
        xi_ci_hi=xi_hi,
        g_cap=g_cap,
        confidence_tier=confidence_tier,
        tail_diag_pass=tail_diag_pass,
        bootstrapped_at=datetime.now(timezone.utc),
        osm_road_km=osm_road_km,
        parent_h3_index=parent_h3_index,
    )

    logger.info(
        f"[TerrainBootstrap] Cell {h3_index} (res={h3_resolution}): "
        f"n={n_features}, k={k}, u={threshold_m:.1f}m (q={threshold_quantile:.2f}), "
        f"xi={xi:.3f}, sigma={sigma:.1f}, tier={confidence_tier.name}, "
        f"diag={'PASS' if tail_diag_pass else 'FAIL'}, g_cap={g_cap:.3f}"
    )

    return cell_fit


# ---------------------------------------------------------------------------
# Climb Scoring (ride-time entry point)
# ---------------------------------------------------------------------------

# In-memory cache of terrain cells (loaded from DB at startup)
_terrain_cache: Dict[str, TerrainCellFit] = {}
_cache_loaded: bool = False


async def load_terrain_cache(supabase_client) -> int:
    """Load all terrain cells from database into memory cache."""
    global _terrain_cache, _cache_loaded
    try:
        response = supabase_client.from_("terrain_cells").select("*").execute()
        _terrain_cache.clear()
        for row in response.data or []:
            cell = TerrainCellFit(
                h3_index=row["h3_index"],
                h3_resolution=row["h3_resolution"],
                n_features=row.get("n_features", 0),
                k_exceedances=row.get("k_exceedances", 0),
                threshold_m=row.get("threshold_m", NOISE_GATE_M),
                threshold_quantile=row.get("threshold_quantile", 0.85),
                gpd_xi=row.get("gpd_xi", 0.0),
                gpd_sigma=row.get("gpd_sigma", 1.0),
                xi_ci_hi=row.get("xi_ci_hi", 0.5),
                g_cap=row.get("g_cap", 0.5),
                confidence_tier=ConfidenceTier(row.get("confidence_tier", 0)),
                tail_diag_pass=row.get("tail_diag_pass", False),
                bootstrapped_at=datetime.fromisoformat(
                    row["bootstrapped_at"].replace("Z", "+00:00")
                ) if row.get("bootstrapped_at") else None,
                osm_road_km=row.get("osm_road_km"),
                parent_h3_index=row.get("parent_h3_index"),
                n_unique_riders=row.get("n_unique_riders", 0),
                effective_n=row.get("effective_n"),
                top_rider_pct=row.get("top_rider_pct"),
                diversity_tier=row.get("diversity_tier", 0),
                n_unique_routes=row.get("n_unique_routes"),
            )
            _terrain_cache[cell.h3_index] = cell

        _cache_loaded = True
        logger.info(f"[TerrainBootstrap] Loaded {len(_terrain_cache)} terrain cells")
        return len(_terrain_cache)
    except Exception as e:
        logger.warning(f"[TerrainBootstrap] Failed to load terrain cache: {e}")
        return 0


def _lookup_cell(h3_res10_index: str) -> Optional[Tuple[TerrainCellFit, bool]]:
    """
    Look up terrain cell for an H3 res-10 index.

    Precedence:
    1. Res-5 parent cell (if available and confidence_tier >= 2)
    2. Res-4 grandparent cell (fallback, with reduced confidence)
    3. None (no terrain data for this area)

    Returns (cell_fit, is_primary) where is_primary=True means res-5 match.
    """
    if not _cache_loaded:
        return None

    try:
        import h3
        # Get res-5 parent
        res5 = h3.cell_to_parent(h3_res10_index, 5)
        if res5 in _terrain_cache:
            cell = _terrain_cache[res5]
            if cell.confidence_tier >= ConfidenceTier.MODERATE:
                return (cell, True)

        # Fallback to res-4
        res4 = h3.cell_to_parent(h3_res10_index, 4)
        if res4 in _terrain_cache:
            return (_terrain_cache[res4], False)

        # Also check if the res-5 cell exists but with lower confidence
        if res5 in _terrain_cache:
            return (_terrain_cache[res5], True)

        return None
    except Exception:
        return None


def score_climb(
    persistence_m: float,
    midpoint_h3_res10: Optional[str],
) -> Optional[SignificanceResult]:
    """
    Score a single climb's significance relative to local terrain.

    Entry point for ride-time scoring in ride_processor.py.

    Args:
        persistence_m: Topological persistence in meters
        midpoint_h3_res10: H3 res-10 cell at climb midpoint

    Returns:
        SignificanceResult or None if no terrain data available
    """
    if persistence_m <= NOISE_GATE_M:
        return None

    if not midpoint_h3_res10:
        return None

    result = _lookup_cell(midpoint_h3_res10)
    if result is None:
        return None

    cell, is_primary = result

    # For fallback (res-4), reduce confidence tier by 1
    if not is_primary and cell.confidence_tier > ConfidenceTier.EMPIRICAL:
        # Create a copy with reduced confidence
        cell = TerrainCellFit(
            h3_index=cell.h3_index,
            h3_resolution=cell.h3_resolution,
            n_features=cell.n_features,
            k_exceedances=cell.k_exceedances,
            threshold_m=cell.threshold_m,
            threshold_quantile=cell.threshold_quantile,
            gpd_xi=cell.gpd_xi,
            gpd_sigma=cell.gpd_sigma,
            xi_ci_hi=cell.xi_ci_hi,
            g_cap=cell.g_cap,
            confidence_tier=ConfidenceTier(max(0, int(cell.confidence_tier) - 1)),
            tail_diag_pass=cell.tail_diag_pass,
            bootstrapped_at=cell.bootstrapped_at,
            osm_road_km=cell.osm_road_km,
            parent_h3_index=cell.parent_h3_index,
        )

    return compute_significance(persistence_m, cell)


# ---------------------------------------------------------------------------
# Bootstrap from Ride Data (alpha alternative to FABDEM)
# ---------------------------------------------------------------------------

async def bootstrap_from_rides(
    supabase_client,
    min_rides_per_cell: int = 5,
) -> int:
    """
    Bootstrap terrain cells from accumulated ride data.

    For alpha, we may not have FABDEM/OSM data processed yet. This function
    extracts persistence values from existing patterns_climb rows and fits
    GPD parameters per H3 res-5 cell.

    Returns number of cells fitted.
    """
    import h3

    # Generate a unique run_id for this bootstrap invocation
    run_id = str(uuid.uuid4())
    logger.info(f"[TerrainBootstrap] Starting bootstrap run {run_id}")

    # Get all climbs with persistence data, including wallet and signature for diversity
    # Exclude false_positive climbs from fitting (human feedback loop)
    response = supabase_client.from_("patterns_climb") \
        .select("persistence_m, tile_ids, wallet, signature_hex") \
        .not_.is_("persistence_m", "null") \
        .gt("persistence_m", NOISE_GATE_M) \
        .or_("review_status.is.null,review_status.neq.false_positive") \
        .execute()

    if not response.data:
        logger.info("[TerrainBootstrap] No climb data with persistence for bootstrapping")
        return 0

    # Group persistence values, wallets, and signatures by H3 res-5 cell
    cell_values: Dict[str, List[float]] = {}
    cell_wallets: Dict[str, List[str]] = {}
    cell_signatures: Dict[str, List[Optional[str]]] = {}
    for row in response.data:
        tile_ids = row.get("tile_ids") or []
        if not tile_ids:
            continue
        # Use middle tile as representative
        mid_tile = tile_ids[len(tile_ids) // 2]
        try:
            res5 = h3.cell_to_parent(mid_tile, 5)
            cell_values.setdefault(res5, []).append(row["persistence_m"])
            cell_wallets.setdefault(res5, []).append(row.get("wallet", "unknown"))
            cell_signatures.setdefault(res5, []).append(row.get("signature_hex"))
        except Exception:
            continue

    # Fit each cell with enough data
    cells_fitted = 0
    for h3_index, values in cell_values.items():
        if len(values) < min_rides_per_cell:
            continue

        try:
            res4 = h3.cell_to_parent(h3_index, 4)
        except Exception:
            res4 = None

        # Fetch previous cell params before fitting (for drift detection)
        old_cell = _fetch_old_cell_params(supabase_client, h3_index)

        cell_fit = fit_terrain_cell(
            h3_index=h3_index,
            h3_resolution=5,
            persistence_values=values,
            parent_h3_index=res4,
        )

        if cell_fit:
            # Compute rider diversity metrics
            wallets = cell_wallets.get(h3_index, [])
            signatures = cell_signatures.get(h3_index, [])
            diversity = compute_diversity_metrics(wallets, signatures)

            cell_fit.n_unique_riders = diversity["n_unique_riders"]
            cell_fit.effective_n = diversity["effective_n"]
            cell_fit.top_rider_pct = diversity["top_rider_pct"]
            cell_fit.diversity_tier = diversity["diversity_tier"]
            cell_fit.n_unique_routes = diversity["n_unique_routes"]

            # Cap confidence tier based on diversity
            cell_fit.confidence_tier = adjusted_confidence_tier(
                cell_fit.confidence_tier, diversity["diversity_tier"]
            )

            # Cap g_cap using effective_n instead of raw k
            effective_k = min(cell_fit.k_exceedances, int(diversity["effective_n"]))
            cell_fit.g_cap = compute_score_cap(effective_k, cell_fit.threshold_quantile)

            logger.info(
                f"[TerrainBootstrap] Cell {h3_index} diversity: "
                f"riders={diversity['n_unique_riders']}, "
                f"eff_n={diversity['effective_n']}, "
                f"top_pct={diversity['top_rider_pct']:.2f}, "
                f"tier={diversity['diversity_tier']}, "
                f"adjusted_conf={cell_fit.confidence_tier.name}, "
                f"adjusted_g_cap={cell_fit.g_cap:.3f}"
            )

            # Compute max_score_impact for drift detection
            max_score_impact = _compute_max_score_impact(
                supabase_client, cell_fit, old_cell
            )

            # Extract old param values for delta computation
            old_xi = old_cell.get("gpd_xi") if old_cell else None
            old_sigma = old_cell.get("gpd_sigma") if old_cell else None
            old_n = old_cell.get("n_features") if old_cell else None
            old_k = old_cell.get("k_exceedances") if old_cell else None
            old_tier = old_cell.get("confidence_tier") if old_cell else None
            old_diag = old_cell.get("tail_diag_pass") if old_cell else None
            old_history_count = old_cell.get("history_count", 0) if old_cell else 0

            # Insert into terrain_cell_history
            history_row = {
                "run_id": run_id,
                "h3_index": cell_fit.h3_index,
                "h3_resolution": cell_fit.h3_resolution,
                "n_features": cell_fit.n_features,
                "k_exceedances": cell_fit.k_exceedances,
                "threshold_m": round(cell_fit.threshold_m, 3) if cell_fit.threshold_m else None,
                "threshold_quantile": round(cell_fit.threshold_quantile, 3) if cell_fit.threshold_quantile else None,
                "gpd_xi": round(cell_fit.gpd_xi, 6) if cell_fit.gpd_xi is not None else None,
                "gpd_sigma": round(cell_fit.gpd_sigma, 6) if cell_fit.gpd_sigma is not None else None,
                "xi_ci_hi": round(cell_fit.xi_ci_hi, 6) if cell_fit.xi_ci_hi is not None else None,
                "g_cap": round(cell_fit.g_cap, 4) if cell_fit.g_cap is not None else None,
                "confidence_tier": int(cell_fit.confidence_tier),
                "tail_diag_pass": cell_fit.tail_diag_pass,
                "n_unique_riders": cell_fit.n_unique_riders,
                "effective_n": round(cell_fit.effective_n, 2) if cell_fit.effective_n is not None else None,
                "diversity_tier": cell_fit.diversity_tier,
                # Deltas
                "prev_gpd_xi": old_xi,
                "prev_gpd_sigma": old_sigma,
                "delta_xi": round(cell_fit.gpd_xi - old_xi, 6) if old_xi is not None and cell_fit.gpd_xi is not None else None,
                "delta_sigma": round(cell_fit.gpd_sigma - old_sigma, 6) if old_sigma is not None and cell_fit.gpd_sigma is not None else None,
                "delta_n_features": (cell_fit.n_features - old_n) if old_n is not None else None,
                "delta_k_exceedances": (cell_fit.k_exceedances - old_k) if old_k is not None else None,
                "tier_changed": old_tier is not None and int(cell_fit.confidence_tier) != old_tier,
                "diag_changed": old_diag is not None and cell_fit.tail_diag_pass != old_diag,
                "max_score_impact": round(max_score_impact, 4),
                "drift_flagged": max_score_impact > 0.05,
                "trigger_reason": "manual_bootstrap",
            }
            try:
                supabase_client.from_("terrain_cell_history").insert(history_row).execute()
            except Exception as e:
                logger.warning(f"[TerrainBootstrap] Failed to insert history for {h3_index}: {e}")

            # If drift detected, mark climbs stale
            if max_score_impact > 0.05:
                logger.info(
                    f"[TerrainBootstrap] Drift detected in {h3_index}: "
                    f"max_score_impact={max_score_impact:.4f}, marking climbs stale"
                )
                try:
                    supabase_client.from_("patterns_climb") \
                        .update({"significance_stale": True}) \
                        .eq("significance_cell_h3", cell_fit.h3_index) \
                        .execute()
                except Exception as e:
                    logger.warning(f"[TerrainBootstrap] Failed to mark stale climbs for {h3_index}: {e}")

            # Store to database with run_id and history_count
            db_dict = cell_fit.to_db_dict()
            db_dict["run_id"] = run_id
            db_dict["history_count"] = (old_history_count or 0) + 1
            supabase_client.from_("terrain_cells") \
                .upsert(db_dict) \
                .execute()
            cells_fitted += 1

    logger.info(f"[TerrainBootstrap] Bootstrapped {cells_fitted} terrain cells from ride data (run={run_id})")

    # Reload cache
    await load_terrain_cache(supabase_client)
    return cells_fitted


def _fetch_old_cell_params(supabase_client, h3_index: str) -> Optional[dict]:
    """Fetch the current terrain cell params before re-fitting."""
    try:
        resp = supabase_client.from_("terrain_cells") \
            .select("gpd_xi, gpd_sigma, n_features, k_exceedances, "
                    "confidence_tier, tail_diag_pass, history_count") \
            .eq("h3_index", h3_index) \
            .limit(1) \
            .execute()
        if resp.data:
            return resp.data[0]
    except Exception as e:
        logger.warning(f"[TerrainBootstrap] Failed to fetch old cell {h3_index}: {e}")
    return None


def _compute_max_score_impact(
    supabase_client,
    new_cell: TerrainCellFit,
    old_cell: Optional[dict],
) -> float:
    """
    Compute the maximum absolute score change for top climbs in this cell.

    Fetches the top 5 climbs by persistence_m, scores each under both old
    and new params, and returns the max absolute difference.
    """
    if old_cell is None:
        return 0.0

    old_xi = old_cell.get("gpd_xi")
    old_sigma = old_cell.get("gpd_sigma")
    if old_xi is None or old_sigma is None:
        return 0.0

    try:
        resp = supabase_client.from_("patterns_climb") \
            .select("persistence_m") \
            .eq("significance_cell_h3", new_cell.h3_index) \
            .not_.is_("persistence_m", "null") \
            .order("persistence_m", desc=True) \
            .limit(5) \
            .execute()
    except Exception as e:
        logger.warning(f"[TerrainBootstrap] Failed to fetch climbs for drift check: {e}")
        return 0.0

    if not resp.data:
        return 0.0

    # Build an old TerrainCellFit for scoring
    old_fit = TerrainCellFit(
        h3_index=new_cell.h3_index,
        h3_resolution=new_cell.h3_resolution,
        n_features=old_cell.get("n_features", new_cell.n_features),
        k_exceedances=old_cell.get("k_exceedances", new_cell.k_exceedances),
        threshold_m=new_cell.threshold_m,
        threshold_quantile=new_cell.threshold_quantile,
        gpd_xi=old_xi,
        gpd_sigma=old_sigma,
        xi_ci_hi=old_xi + 0.1,  # Approximate old CI
        g_cap=new_cell.g_cap,
        confidence_tier=ConfidenceTier(old_cell.get("confidence_tier", 0)),
        tail_diag_pass=old_cell.get("tail_diag_pass", False),
    )

    max_impact = 0.0
    for row in resp.data:
        persistence = row["persistence_m"]
        old_result = compute_significance(persistence, old_fit)
        new_result = compute_significance(persistence, new_cell)
        impact = abs(new_result.g_score - old_result.g_score)
        if impact > max_impact:
            max_impact = impact

    return max_impact
