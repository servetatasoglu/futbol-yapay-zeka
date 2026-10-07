# value/value_engine.py
"""
Canonical Value & Edge Engine — Institutional Grade
═════════════════════════════════════════════════════
Unified mathematical formulas for:
1. Vig-normalized fair market probability
2. Model vs Market edge with empirical Bayes shrinkage
3. Expected Value (EV)
4. Comprehensive 1X2 market evaluation

FIX [P0-08]: Replaces fragmented and conflicting edge implementations across the codebase.
"""

from typing import Tuple, Dict, Any
import logging

logger = logging.getLogger("value_engine")


def calculate_market_fair_probability(
    odds_h: float, odds_d: float, odds_a: float
) -> Tuple[float, float, float]:
    """
    Remove margin/vig using standard multi-way normalization.
    Returns (fair_h, fair_d, fair_a) summing exactly to 1.0.
    """
    if odds_h <= 1.0 or odds_d <= 1.0 or odds_a <= 1.0:
        return (0.33333, 0.33333, 0.33334)

    overround = (1.0 / odds_h) + (1.0 / odds_d) + (1.0 / odds_a)
    if overround <= 0.0:
        return (0.33333, 0.33333, 0.33334)

    fair_h = (1.0 / odds_h) / overround
    fair_d = (1.0 / odds_d) / overround
    fair_a = (1.0 / odds_a) / overround

    return (fair_h, fair_d, fair_a)


def calculate_two_way_fair_probability(
    odds_1: float, odds_2: float
) -> Tuple[float, float]:
    """
    Vig-normalized probabilities for 2-way markets (e.g. Over/Under 2.5, BTTS).
    """
    if odds_1 <= 1.0 or odds_2 <= 1.0:
        return (0.5, 0.5)

    overround = (1.0 / odds_1) + (1.0 / odds_2)
    if overround <= 0.0:
        return (0.5, 0.5)

    fair_1 = (1.0 / odds_1) / overround
    fair_2 = (1.0 / odds_2) / overround
    return (fair_1, fair_2)


def calculate_expected_value(p_model: float, odds: float) -> float:
    """
    Expected Value = (p_model * odds) - 1.0
    Returns decimal EV (e.g. 0.05 for +5% EV).
    """
    if odds <= 1.0 or p_model <= 0.0:
        return -1.0
    return (p_model * odds) - 1.0


def calculate_model_market_edge(
    p_model: float, fair_p: float, lig_kodu: str = ""
) -> float:
    """
    Calculates Bayesian shrinkage edge against vig-normalized market fair price.
    Edge = p_shrunk - fair_p
    p_shrunk = alpha * p_model + (1 - alpha) * fair_p

    - alpha depends on league market efficiency (higher efficiency = lower alpha)
    - If edge > 0.20, considered anomalous / bad odds -> returns 0.0 (NO BET)
    - Capped at league maximum edge
    """
    if fair_p <= 0.0 or fair_p >= 1.0 or p_model <= 0.0 or p_model >= 1.0:
        return 0.0

    try:
        from config.settings import (
            SHRINKAGE_MODEL_WEIGHT,
            LIG_VERIMLILIK,
            LIG_VERIMLILIK_VARSAYILAN,
            LIG_MAX_EDGE,
            LIG_MAX_EDGE_VARSAYILAN,
        )
    except ImportError:
        SHRINKAGE_MODEL_WEIGHT = 0.55
        LIG_VERIMLILIK = {}
        LIG_VERIMLILIK_VARSAYILAN = 0.85
        LIG_MAX_EDGE = {}
        LIG_MAX_EDGE_VARSAYILAN = 0.05

    league_eff = LIG_VERIMLILIK.get(lig_kodu, LIG_VERIMLILIK_VARSAYILAN)
    alpha = SHRINKAGE_MODEL_WEIGHT * (1.0 - league_eff * 0.3)
    alpha = max(0.30, min(0.60, alpha))

    p_shrunk = alpha * p_model + (1.0 - alpha) * fair_p
    raw_edge = p_shrunk - fair_p

    # Anomalous edge guard (> 20% edge is bad data)
    if raw_edge > 0.20:
        import warnings as _w
        _w.warn(
            f"[value_bet] Aşırı edge tespit edildi: {raw_edge:.3f} (>{0.20}) — "
            f"muhtemelen veri hatası veya bad odds. NO BET.",
            RuntimeWarning, stacklevel=2
        )
        return 0.0

    # Cap at league maximum edge
    max_edge = LIG_MAX_EDGE.get(lig_kodu, LIG_MAX_EDGE_VARSAYILAN)
    return min(max_edge, raw_edge)


def evaluate_bet_opportunity(
    p_model: float,
    odds: float,
    fair_p: float,
    lig_kodu: str = "",
    min_edge: float = 0.015,
) -> Dict[str, Any]:
    """
    Complete institutional evaluation of a bet opportunity.
    Returns:
    {
        "approved": bool,
        "edge": float,
        "ev": float,
        "p_model": float,
        "fair_p": float,
        "odds": float,
        "rejection_reason": str | None
    }
    """
    if odds <= 1.0:
        return {
            "approved": False,
            "edge": 0.0,
            "ev": -1.0,
            "p_model": p_model,
            "fair_p": fair_p,
            "odds": odds,
            "rejection_reason": "INVALID_ODDS"
        }

    ev = calculate_expected_value(p_model, odds)
    edge = calculate_model_market_edge(p_model, fair_p, lig_kodu=lig_kodu)

    if ev <= 0.0:
        return {
            "approved": False,
            "edge": edge,
            "ev": ev,
            "p_model": p_model,
            "fair_p": fair_p,
            "odds": odds,
            "rejection_reason": "NEGATIVE_EV"
        }

    if edge < min_edge:
        return {
            "approved": False,
            "edge": edge,
            "ev": ev,
            "p_model": p_model,
            "fair_p": fair_p,
            "odds": odds,
            "rejection_reason": "EDGE_BELOW_MINIMUM"
        }

    return {
        "approved": True,
        "edge": round(edge, 4),
        "ev": round(ev, 4),
        "p_model": round(p_model, 4),
        "fair_p": round(fair_p, 4),
        "odds": round(odds, 3),
        "rejection_reason": None
    }
