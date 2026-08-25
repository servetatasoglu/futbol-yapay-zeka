# validation/edge_validator.py
"""
Market-Aware Edge Validator — v3.0
════════════════════════════════════════════════════════════
Every bet must pass this pipeline before reaching execution:

  1. League noise floor test   — Is edge above random variation?
  2. Bayesian shrinkage check  — After shrinkage, is edge still positive?
  3. Model trap detection      — Is this a known false-edge pattern?
  4. CI coverage check         — Does confidence interval include zero?
  5. Historical CLV gate       — Does this pattern historically produce +CLV?
  6. Global sanity cap         — Is edge within realistic bounds?

Returns: {valid, adjusted_edge, confidence, reasons, warnings}

A bet is REJECTED if any mandatory check fails.
A bet is WARNED if any advisory check triggers (still allowed).
"""

import os
import json
import logging
import math

logger = logging.getLogger("edge_validator")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Validation thresholds ──────────────────────────────────────────
NOISE_FLOOR_SIGMA   = 1.5    # Edge must be > 1.5σ above market noise
MIN_CLV_BETS        = 20     # Need 20+ historical bets to use CLV gate
CLV_GATE_THRESHOLD  = -0.01  # Historical CLV < -1% = reject this pattern


# ─────────────────────────────────────────────────────────────────
# 1. LEAGUE NOISE FLOOR
# ─────────────────────────────────────────────────────────────────

# Pinnacle overround ≈ 1.5-2% → that's the noise floor.
# Your model edge must exceed this to be statistically meaningful.
LIG_NOISE_FLOOR = {
    "PL":  0.018,  # 1.8% noise — very low overround, very efficient
    "PD":  0.020,
    "BL1": 0.020,
    "SA":  0.020,
    "CL":  0.019,
    "FL1": 0.022,
    "DED": 0.025,
    "PPL": 0.025,
    "BSA": 0.028,
    "TSL": 0.027,
    "BL2": 0.025,
    "ELC": 0.999,  # Disabled — 0% win rate, reject all
}
LIG_NOISE_FLOOR_DEFAULT = 0.025


# ─────────────────────────────────────────────────────────────────
# 2. KNOWN FALSE-EDGE PATTERNS (Market Traps)
# ─────────────────────────────────────────────────────────────────

def _market_trap_check(edge: float, oran: float, model_p: float,
                        fair_p: float, tahmin: str) -> dict:
    """
    Detect common model traps that produce systematic false edges.

    Returns: {"trap": bool, "trap_type": str, "severity": float}
    """
    warnings = []

    # Trap 1: Very high odds with high model confidence
    # Model says 65% but odds are 5.0 (implies 20%) → almost certainly wrong
    implied_p = 1.0 / oran if oran > 1 else 0
    if model_p > 0.55 and implied_p < 0.25:
        warnings.append({
            "trap": True,
            "trap_type": "CONFIDENCE_ODDS_MISMATCH",
            "severity": 0.9,
            "detail": f"model_p={model_p:.2f} vs implied_p={implied_p:.2f}"
        })

    # Trap 2: High edge but small market divergence from fair
    # Edge=8% but (model-fair) gap is only 2% → edge came from shrinkage artifact
    if edge > 0.05 and abs(model_p - fair_p) < 0.03:
        warnings.append({
            "trap": True,
            "trap_type": "EDGE_WITHOUT_DIVERGENCE",
            "severity": 0.7,
            "detail": f"edge={edge:.3f} but model-fair gap={abs(model_p-fair_p):.3f}"
        })

    # Trap 3: Draw with high edge — Poisson systematically fails on draws
    if tahmin == "Beraberlik" and edge > 0.04:
        warnings.append({
            "trap": True,
            "trap_type": "DRAW_EDGE_UNRELIABLE",
            "severity": 0.6,
            "detail": "Poisson models systematically overestimate draw edge"
        })

    # Trap 4: Home edge > 7% — home advantage already priced in by Pinnacle
    if tahmin == "Ev Sahibi Kazanır" and edge > 0.07:
        warnings.append({
            "trap": True,
            "trap_type": "HOME_BIAS_INFLATION",
            "severity": 0.5,
            "detail": f"Home edge {edge:.3f} likely includes home-bias artifact"
        })

    # Trap 5: Under/No-goal bet with no sharp signal — Poisson over-estimates Under edge
    # Under bets look attractive but the model systematically over-rates them without market confirmation
    if tahmin in ("2.5 Alt", "KG Yok") and edge > 0.04:
        warnings.append({
            "trap": True,
            "trap_type": "UNDER_NO_SHARP_BIAS",
            "severity": 0.75,
            "detail": f"Under/No-goal edge={edge:.3f} without sharp signal — known false-edge pattern"
        })

    # Trap 6: Sharp signal contradicts selection (e.g. model says Draw but sharp money on Home)
    # This only applies to MS bets
    ms_tahminler = {"Ev Sahibi Kazanır", "Beraberlik", "Deplasman Kazanır"}
    if tahmin == "Beraberlik" and fair_p < 0.30 and model_p < 0.35 and edge > 0.05:
        warnings.append({
            "trap": True,
            "trap_type": "DRAW_LOW_PROB_HIGH_EDGE",
            "severity": 0.65,
            "detail": f"Draw with low probability ({model_p:.2f}) showing suspicious edge"
        })

    if not warnings:
        return {"trap": False, "trap_type": "NONE", "severity": 0}

    # Return highest severity trap
    worst = max(warnings, key=lambda x: x["severity"])
    return worst


# ─────────────────────────────────────────────────────────────────
# 3. CONFIDENCE INTERVAL CHECK
# ─────────────────────────────────────────────────────────────────

def _ci_coverage_check(edge: float, ci_width: float,
                        uncertainty: float) -> dict:
    """
    Does the confidence interval include zero?
    If CI includes zero, edge is not statistically significant.

    Also computes uncertainty-adjusted edge:
        edge_adj = edge - SHRINKAGE_UNCERTAINTY_K * uncertainty
    """
    try:
        from config.settings import SHRINKAGE_UNCERTAINTY_K
    except ImportError:
        SHRINKAGE_UNCERTAINTY_K = 1.5

    # Uncertainty-adjusted edge
    edge_adj = edge - SHRINKAGE_UNCERTAINTY_K * uncertainty
    ci_includes_zero = (edge - ci_width / 2) < 0

    return {
        "edge_adj":        round(edge_adj, 4),
        "ci_includes_zero": ci_includes_zero,
        "uncertainty":     round(uncertainty, 4),
        "ci_width":        round(ci_width, 4),
    }


# ─────────────────────────────────────────────────────────────────
# 4. HISTORICAL CLV GATE
# ─────────────────────────────────────────────────────────────────

def _clv_history_gate(lig: str, tahmin: str, tier: str) -> dict:
    """
    Check if this pattern (league + bet type + tier) has historically
    produced positive CLV. If not enough data → allow (learning phase).
    """
    try:
        from tracking.clv_tracker import clv_raporu
        rapor = clv_raporu()
        lig_bazli  = rapor.get("lig_bazli",  {})
        tier_bazli = rapor.get("tier_bazli", {})

        lig_info  = lig_bazli.get(lig,  {})
        tier_info = tier_bazli.get(tier, {})

        lig_n     = lig_info.get("bahis_n",  0)
        tier_n    = tier_info.get("bahis_n", 0)
        lig_clv   = lig_info.get("ort_clv",  0)
        tier_clv  = tier_info.get("ort_clv", 0)

        # Not enough data → allow (learning phase)
        if lig_n < MIN_CLV_BETS:
            return {"gate": True, "reason": "insufficient_data",
                    "lig_clv": None, "tier_clv": None}

        # League historically negative CLV → reject
        if lig_clv < CLV_GATE_THRESHOLD:
            return {
                "gate": False,
                "reason": f"historical_lig_clv_negative: {lig}={lig_clv*100:.2f}%",
                "lig_clv": lig_clv,
                "tier_clv": tier_clv,
            }

        # Tier historically negative (enough data) → reduce confidence
        tier_warn = tier_n >= MIN_CLV_BETS and tier_clv < CLV_GATE_THRESHOLD

        return {
            "gate":     True,
            "reason":   "passed" if not tier_warn else "tier_warning",
            "lig_clv":  lig_clv,
            "tier_clv": tier_clv,
            "tier_warn": tier_warn,
        }

    except Exception as e:
        logger.debug(f"CLV history gate error: {e}")
        return {"gate": True, "reason": "gate_error", "lig_clv": None, "tier_clv": None}


# ─────────────────────────────────────────────────────────────────
# 5. MAIN VALIDATOR
# ─────────────────────────────────────────────────────────────────

def validate_edge(
    edge:       float,
    model_p:    float,
    fair_p:     float,
    oran:       float,
    lig:        str,
    tahmin:     str,
    tier:       str     = "NO_SHARP",
    uncertainty: float  = 0.10,
    ci_width:   float   = 0.20,
    pinnacle_var: bool  = False,
) -> dict:
    """
    Full edge validation pipeline. Call before every execution decision.

    Returns:
    {
        "valid":          bool,    # True = bet is allowed
        "adjusted_edge":  float,   # Uncertainty-shrunk edge (use this, not raw)
        "confidence":     float,   # 0-1 composite confidence score
        "reject_reasons": list,    # Why bet was REJECTED (mandatory failures)
        "warnings":       list,    # Advisory warnings (bet still allowed)
        "checks":         dict,    # Full check results for logging
    }
    """
    reject_reasons = []
    warnings_list  = []

    # ── Load global params ────────────────────────────────────────
    try:
        from config.settings import GLOBAL_MAX_EDGE, GLOBAL_MIN_EDGE, ELC_AKTIF, LIG_MAX_EDGE
        LIG_MAX_EDGE_MAP = LIG_MAX_EDGE
    except ImportError:
        GLOBAL_MAX_EDGE = 0.12
        GLOBAL_MIN_EDGE = 0.015
        ELC_AKTIF = True
        LIG_MAX_EDGE_MAP = {}

    # Effective max edge: use league-specific cap if available, else global
    effective_max_edge = LIG_MAX_EDGE_MAP.get(lig, GLOBAL_MAX_EDGE)

    # ── Check 0: ELC disabled ────────────────────────────────────
    if not ELC_AKTIF and lig == "ELC":
        return {
            "valid": False,
            "adjusted_edge": edge,
            "confidence": 0,
            "reject_reasons": ["ELC_DISABLED"],
            "warnings": [],
            "checks": {},
        }

    # ── Check 1: Global sanity cap (now lig-specific) ─────────────
    if edge > effective_max_edge:
        reject_reasons.append(f"EDGE_EXCEEDS_CAP: {edge:.3f} > {effective_max_edge:.3f} ({lig})")
    if edge < GLOBAL_MIN_EDGE:
        reject_reasons.append(f"EDGE_BELOW_FLOOR: {edge:.3f} < {GLOBAL_MIN_EDGE:.3f}")

    # ── Check 2: League noise floor ───────────────────────────────
    noise_floor = LIG_NOISE_FLOOR.get(lig, LIG_NOISE_FLOOR_DEFAULT)
    noise_ok = edge > noise_floor
    if not noise_ok:
        reject_reasons.append(
            f"BELOW_NOISE_FLOOR: edge={edge:.3f} < {lig}_floor={noise_floor:.3f}"
        )

    # ── Check 3: CI coverage ──────────────────────────────────────
    ci_check = _ci_coverage_check(edge, ci_width, uncertainty)
    edge_adj = ci_check["edge_adj"]
    if ci_check["ci_includes_zero"]:
        reject_reasons.append(
            f"CI_INCLUDES_ZERO: edge={edge:.3f} ci_width={ci_width:.3f}"
        )
    if edge_adj < GLOBAL_MIN_EDGE:
        reject_reasons.append(
            f"ADJ_EDGE_BELOW_FLOOR: adj={edge_adj:.3f} < {GLOBAL_MIN_EDGE:.3f}"
        )

    # ── Check 4: Market trap detection ────────────────────────────
    trap = _market_trap_check(edge, oran, model_p, fair_p, tahmin)
    if trap.get("trap"):
        if trap["severity"] >= 0.8:
            reject_reasons.append(f"MARKET_TRAP({trap['trap_type']})")
        else:
            warnings_list.append(f"TRAP_WARNING({trap['trap_type']}): {trap.get('detail','')}")

    # ── Check 5: Historical CLV gate ──────────────────────────────
    clv_gate = _clv_history_gate(lig, tahmin, tier)
    if not clv_gate.get("gate", True):
        reject_reasons.append(f"CLV_GATE_FAILED: {clv_gate.get('reason','')}")
    if clv_gate.get("tier_warn"):
        warnings_list.append(f"TIER_CLV_WARNING: {tier} has negative historical CLV")

    # ── Check 6: Pinnacle alignment ───────────────────────────────
    if not pinnacle_var and edge > 0.05:
        warnings_list.append(
            f"NO_PINNACLE: edge={edge:.3f} without Pinnacle reference is less reliable"
        )

    # ── Composite confidence score ────────────────────────────────
    confidence_factors = [
        1.0 if noise_ok else 0.0,
        1.0 if not ci_check["ci_includes_zero"] else 0.3,
        1.0 if not trap.get("trap") else (1 - trap.get("severity", 0)),
        1.0 if clv_gate.get("gate", True) else 0.0,
        1.0 if pinnacle_var else 0.7,
    ]
    confidence = round(
        math.prod(confidence_factors) if confidence_factors else 0, 3
    )

    valid = len(reject_reasons) == 0

    if not valid:
        logger.debug(
            f"REJECTED: edge={edge:.3f} adj={edge_adj:.3f} | "
            f"reasons={reject_reasons}"
        )

    return {
        "valid":          valid,
        "adjusted_edge":  round(edge_adj, 4),
        "confidence":     confidence,
        "reject_reasons": reject_reasons,
        "warnings":       warnings_list,
        "checks": {
            "noise_floor":  noise_ok,
            "ci_check":     ci_check,
            "trap":         trap,
            "clv_gate":     clv_gate,
            "pinnacle":     pinnacle_var,
        },
    }


# ─────────────────────────────────────────────────────────────────
# 6. BATCH VALIDATOR — For use in value_betleri_bul output
# ─────────────────────────────────────────────────────────────────

def validate_bet_list(bets: list) -> list:
    """
    Run validate_edge on a list of bet dicts from value_betleri_bul.
    Adds "validation" key to each bet. Filters out invalid bets.
    Returns only valid bets with validation results attached.
    """
    valid_bets = []
    for bet in bets:
        result = validate_edge(
            edge        = bet.get("efektif_edge", bet.get("edge", 0)),
            model_p     = bet.get("olasilik", 0.5),
            fair_p      = bet.get("fair_p", 0.5),
            oran        = bet.get("oran", 2.0),
            lig         = bet.get("lig_kodu", bet.get("lig", "")),
            tahmin      = bet.get("tahmin", ""),
            tier        = bet.get("aktif_tier", "NO_SHARP"),
            uncertainty = bet.get("uncertainty", 0.10),
            ci_width    = bet.get("ci_width", 0.20),
            pinnacle_var = bet.get("pinnacle_var", False),
        )
        bet["validation"] = result

        if result["valid"]:
            bet["efektif_edge"] = result["adjusted_edge"]  # Use uncertainty-adjusted
            valid_bets.append(bet)
        else:
            logger.info(
                f"  ❌ FILTERED: {bet.get('ev','')} vs {bet.get('dep','')} "
                f"[{bet.get('tahmin','')}] — {result['reject_reasons']}"
            )

    logger.info(
        f"Validation: {len(valid_bets)}/{len(bets)} bets passed "
        f"({len(bets)-len(valid_bets)} rejected)"
    )
    return valid_bets
