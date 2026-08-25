import logging

logger = logging.getLogger("confidence_filter")

def check_confidence(model_prob: float, market_prob: float, drift_flags: dict, data_valid: bool) -> dict:
    """
    Final Gatekeeper before placing a bet.
    """
    if not data_valid:
        return {"approved": False, "reason": "Data Incomplete or Stale"}

    if drift_flags.get("home_drift") or drift_flags.get("away_drift"):
        return {"approved": False, "reason": "Team Performance Drift (EWMA Shock)"}

    # Sharp Market Alignment: If our model is massively different than Pinnacle, we are likely wrong.
    # Ex: Market says 20%, we say 45%. Someone is injured that we don't know about.
    if market_prob > 0 and abs(model_prob - market_prob) > 0.15:
        return {"approved": False, "reason": "Model vs Market diverge > 15% (Asymmetrical Info Risk)"}

    return {"approved": True, "reason": "Clear to Execute"}
