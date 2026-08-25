# validation/self_critique.py
"""
Self-Critique Engine — v3.0
════════════════════════════════════════════════════════════
Institutional betting requires playing devil's advocate.
Before placing a bet, this module generates the arguments for
WHY the bet might lose, forcing a final heuristic check.

If the critique identifies a "Fatal Flaw", the bet is vetoed.
Otherwise, it returns a risk summary for the dashboard/Telegram.
"""

import logging

logger = logging.getLogger("self_critique")

def generate_critique(bet: dict) -> dict:
    """
    Critiques a value bet candidate.
    Returns: {"veto": bool, "reason": str, "critique_points": list}
    """
    points = []
    veto = False
    veto_reason = ""

    ev_takim = bet.get("ev", "Home")
    dep_takim = bet.get("dep", "Away")
    tahmin = bet.get("tahmin", "")
    oran = bet.get("oran", 1.0)
    edge = bet.get("efektif_edge", bet.get("edge", 0))
    tier = bet.get("aktif_tier", "NO_SHARP")
    validation = bet.get("validation", {})
    
    # 1. Odds vs Edge sanity
    if oran > 4.0 and edge > 0.05:
        points.append(f"High Odds Illusion: At odds of {oran}, a 5%+ edge is mathematically improbable without insider info.")
        if tier == "NO_SHARP":
            veto = True
            veto_reason = "High odds + High edge + No sharp support = Hallucination"

    # 2. Draw bias check
    if tahmin == "Beraberlik":
        points.append("Draw Bias: Poisson models systematically overvalue draws. Variance is extremely high.")
        if edge < 0.04:
            veto = True
            veto_reason = "Draw edge too low to overcome Poisson bias"

    # 3. Validation warnings
    warnings = validation.get("warnings", [])
    for w in warnings:
        points.append(f"Validator Warning: {w}")
        
    # 4. Market consensus
    if tier == "NO_SHARP":
        points.append("Market Disagreement: No sharp money supports this position. We are betting against the efficient market.")

    # 5. Volatility / Uncertainty
    uncertainty = bet.get("uncertainty", 0.0)
    if uncertainty > 0.15:
        points.append(f"High Uncertainty: Model is very unsure about this prediction (uncertainty={uncertainty:.2f}).")

    if veto:
        logger.warning(f"  🛑 CRITIQUE VETO: {ev_takim} vs {dep_takim} [{tahmin}] - {veto_reason}")

    return {
        "veto": veto,
        "veto_reason": veto_reason,
        "critique_points": points
    }
