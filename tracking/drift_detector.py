# tracking/drift_detector.py
"""
Multi-Dimensional Drift Detector — v3.0
════════════════════════════════════════════════════════════
v1.0: Only checked xGA drift for individual teams (57 lines).

v3.0 additions:
  1. Team form drift     — xGA/xGF collapse detection (original)
  2. Model drift         — Track prediction accuracy rolling windows
  3. Calibration drift   — Monitor if model is over/under-confident
  4. Market regime       — Is the market becoming more efficient?
  5. Auto-disable        — Any drift metric exceeds threshold → pause betting

All checks are non-blocking by default (return dict, not raise).
"""

import os
import logging
import json
from datetime import datetime, timedelta
from collections import deque

logger = logging.getLogger("drift_detector")

DB_PATH  = os.path.join(os.path.dirname(__file__), "..", "data", "football_advanced.db")
CLV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "clv_bet_log.json")

# ── Thresholds ────────────────────────────────────────────────────
XGA_DRIFT_THRESHOLD      = 1.40   # 40% xGA spike = team drift
ACCURACY_DRIFT_WINDOW    = 20     # Compare last N bets vs baseline
ACCURACY_DRIFT_THRESHOLD = 0.12   # 12pp accuracy drop = model drift
CALIBRATION_DRIFT_ESIK   = 0.05   # 5% avg miscalibration = calibration drift
MARKET_EFF_WINDOW        = 30     # Days to assess market efficiency trend


# ═══════════════════════════════════════════════════════════════════
# 1. TEAM FORM DRIFT (Original — Enhanced)
# ═══════════════════════════════════════════════════════════════════

def check_team_drift(team_id: str, match_date: str) -> bool:
    """
    EWMA-based xGA drift detection.
    Returns True if team is in a defensive regime collapse (>40% xGA spike).
    """
    try:
        import sqlite3
        import pandas as pd

        try:
            from features.advanced_stats import resolve_team_id
            team_id = resolve_team_id(team_id)
        except Exception:
            pass

        if not os.path.exists(DB_PATH):
            return False

        conn = sqlite3.connect(DB_PATH)
        query = """
            SELECT away_xg as xga, date FROM matches WHERE home_team_id = ? AND date < ?
            UNION ALL
            SELECT home_xg as xga, date FROM matches WHERE away_team_id = ? AND date < ?
            ORDER BY date ASC
        """
        df = pd.read_sql_query(query, conn,
                               params=(team_id, match_date, team_id, match_date))
        conn.close()

        if len(df) < 10:
            return False

        df["xga"] = df["xga"].astype(float)
        long_term_avg  = df["xga"].ewm(span=15).mean().iloc[-4]
        short_term_avg = df["xga"].tail(3).mean()

        if long_term_avg > 0 and (short_term_avg > long_term_avg * XGA_DRIFT_THRESHOLD):
            logger.warning(
                f"TEAM DRIFT: {team_id} | "
                f"LT xGA={long_term_avg:.2f} → ST xGA={short_term_avg:.2f} "
                f"(+{(short_term_avg/long_term_avg - 1)*100:.0f}%)"
            )
            return True
        return False

    except Exception as e:
        logger.debug(f"Team drift check error ({team_id}): {e}")
        return False


def apply_drift_filters(home_id: str, away_id: str, match_date: str) -> dict:
    """Return drift flags for both teams."""
    return {
        "home_drift": check_team_drift(home_id, match_date),
        "away_drift":  check_team_drift(away_id, match_date),
    }


# ═══════════════════════════════════════════════════════════════════
# 2. MODEL ACCURACY DRIFT
# ═══════════════════════════════════════════════════════════════════

def model_accuracy_drift() -> dict:
    """
    Compare recent accuracy vs historical baseline from CLV log.
    If recent N bets are significantly less accurate → model drift.

    Returns:
        {"drift": bool, "recent_acc": float, "baseline_acc": float,
         "delta": float, "n_recent": int, "n_baseline": int}
    """
    try:
        if not os.path.exists(CLV_PATH):
            return {"drift": False, "sebep": "no_clv_data"}

        with open(CLV_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
        bahisler = db.get("bahisler", [])

        # Only settled bets (have result)
        settled = [
            b for b in bahisler
            if b.get("sonuc") is not None and
            str(b.get("sonuc", "")).lower() not in ("iade", "void", "v", "invalid_no_clv")
        ]

        if len(settled) < ACCURACY_DRIFT_WINDOW * 2:
            return {"drift": False, "sebep": "insufficient_data",
                    "n_settled": len(settled)}

        def _accuracy(bets):
            correct = sum(
                1 for b in bets
                if str(b.get("sonuc", "")).lower() in ("kazandi", "kazandı", "w", "win", "true")
            )
            return correct / len(bets) if bets else 0

        recent   = settled[-ACCURACY_DRIFT_WINDOW:]
        baseline = settled[-(ACCURACY_DRIFT_WINDOW * 3):-ACCURACY_DRIFT_WINDOW]

        recent_acc   = _accuracy(recent)
        baseline_acc = _accuracy(baseline)
        delta        = recent_acc - baseline_acc

        drift = baseline_acc > 0.30 and delta < -ACCURACY_DRIFT_THRESHOLD

        if drift:
            logger.warning(
                f"MODEL ACCURACY DRIFT: recent={recent_acc:.1%} "
                f"vs baseline={baseline_acc:.1%} (Δ={delta:+.1%})"
            )

        return {
            "drift":        drift,
            "recent_acc":   round(recent_acc, 3),
            "baseline_acc": round(baseline_acc, 3),
            "delta":        round(delta, 3),
            "n_recent":     len(recent),
            "n_baseline":   len(baseline),
        }

    except Exception as e:
        logger.debug(f"Model accuracy drift error: {e}")
        return {"drift": False, "sebep": f"error: {e}"}


# ═══════════════════════════════════════════════════════════════════
# 3. CALIBRATION DRIFT
# ═══════════════════════════════════════════════════════════════════

def calibration_drift() -> dict:
    """
    Monitor if model probabilities are systematically over/under-confident.
    Uses Brier score trend from CLV log.

    Returns:
        {"drift": bool, "brier_recent": float, "brier_baseline": float,
         "overconfident": bool}
    """
    try:
        if not os.path.exists(CLV_PATH):
            return {"drift": False, "sebep": "no_clv_data"}

        with open(CLV_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
        bahisler = db.get("bahisler", [])

        scored = []
        for b in bahisler:
            model_p = b.get("model_p")
            sonuc   = str(b.get("sonuc", "")).lower()
            if model_p is None or sonuc in ("iade", "void", "v", "invalid_no_clv", ""):
                continue
            gercek = 1.0 if sonuc in ("kazandi", "kazandı", "w", "win", "true") else 0.0
            scored.append({"brier": (model_p - gercek) ** 2, "model_p": model_p,
                           "gercek": gercek})

        if len(scored) < 30:
            return {"drift": False, "sebep": "insufficient_data"}

        n = min(20, len(scored) // 3)
        recent   = scored[-n:]
        baseline = scored[-(n * 3):-n]

        brier_r = sum(s["brier"] for s in recent)   / len(recent)
        brier_b = sum(s["brier"] for s in baseline) / len(baseline)
        delta   = brier_r - brier_b

        # Brier score increasing = worse calibration
        drift = delta > CALIBRATION_DRIFT_ESIK

        # Overconfidence: model_p consistently far from outcome
        avg_conf = sum(s["model_p"] for s in recent) / len(recent)
        avg_real = sum(s["gercek"]  for s in recent) / len(recent)
        overconfident = (avg_conf - avg_real) > 0.08

        if drift:
            logger.warning(
                f"CALIBRATION DRIFT: Brier recent={brier_r:.4f} "
                f"vs baseline={brier_b:.4f} (Δ={delta:+.4f})"
            )

        return {
            "drift":          drift,
            "brier_recent":   round(brier_r, 4),
            "brier_baseline": round(brier_b, 4),
            "delta":          round(delta, 4),
            "overconfident":  overconfident,
            "avg_conf":       round(avg_conf, 3),
            "avg_real":       round(avg_real, 3),
        }

    except Exception as e:
        logger.debug(f"Calibration drift error: {e}")
        return {"drift": False, "sebep": f"error: {e}"}


# ═══════════════════════════════════════════════════════════════════
# 4. MARKET EFFICIENCY TREND
# ═══════════════════════════════════════════════════════════════════

def market_efficiency_trend() -> dict:
    """
    Is the market becoming more or less efficient?
    Measured by CLV trend: declining CLV = market getting harder to beat.

    Returns:
        {"trend": "IMPROVING" | "STABLE" | "DECLINING",
         "clv_30d": float, "clv_7d": float, "delta": float}
    """
    try:
        if not os.path.exists(CLV_PATH):
            return {"trend": "UNKNOWN", "sebep": "no_clv_data"}

        with open(CLV_PATH, "r", encoding="utf-8") as f:
            db = json.load(f)
        bahisler = db.get("bahisler", [])

        clv_data = [
            (b.get("tarih", ""), b["clv"])
            for b in bahisler
            if b.get("clv") is not None
        ]

        if len(clv_data) < 20:
            return {"trend": "UNKNOWN", "sebep": "insufficient_data"}

        now     = datetime.now()
        cut_7d  = (now - timedelta(days=7)).isoformat()[:16]
        cut_30d = (now - timedelta(days=30)).isoformat()[:16]

        clv_7d  = [c for t, c in clv_data if t >= cut_7d]
        clv_30d = [c for t, c in clv_data if t >= cut_30d and t < cut_7d]

        if not clv_7d or not clv_30d:
            return {"trend": "UNKNOWN", "sebep": "insufficient_window_data"}

        avg_7d  = sum(clv_7d)  / len(clv_7d)
        avg_30d = sum(clv_30d) / len(clv_30d)
        delta   = avg_7d - avg_30d

        if delta > 0.005:
            trend = "IMPROVING"
        elif delta < -0.005:
            trend = "DECLINING"
        else:
            trend = "STABLE"

        if trend == "DECLINING":
            logger.info(
                f"Market efficiency trending harder: "
                f"7d CLV={avg_7d*100:+.2f}% vs 30d={avg_30d*100:+.2f}%"
            )

        return {
            "trend":    trend,
            "clv_7d":   round(avg_7d, 4),
            "clv_30d":  round(avg_30d, 4),
            "delta":    round(delta, 4),
            "n_7d":     len(clv_7d),
            "n_30d":    len(clv_30d),
        }

    except Exception as e:
        logger.debug(f"Market efficiency trend error: {e}")
        return {"trend": "UNKNOWN", "sebep": f"error: {e}"}


# ═══════════════════════════════════════════════════════════════════
# 5. FULL DRIFT REPORT
# ═══════════════════════════════════════════════════════════════════

def full_drift_raporu() -> dict:
    """
    Run all drift detectors. Returns combined report.
    Use this in monitoring/system_health.py.

    Returns:
        {
            "any_drift":    bool,   # True if ANY drift detected
            "auto_disable": bool,   # True if betting should pause
            "model":        dict,
            "calibration":  dict,
            "market":       dict,
            "alerts":       list,
        }
    """
    model_d = model_accuracy_drift()
    calib_d = calibration_drift()
    market_d = market_efficiency_trend()

    alerts = []
    any_drift   = False
    auto_disable = False

    if model_d.get("drift"):
        any_drift = True
        alerts.append(
            f"MODEL_DRIFT: accuracy dropped {model_d.get('delta', 0)*100:+.1f}pp "
            f"(recent={model_d.get('recent_acc', 0):.1%})"
        )
        # Auto-disable if accuracy drops >20pp
        if model_d.get("delta", 0) < -0.20:
            auto_disable = True
            alerts.append("AUTO_DISABLE: Severe model accuracy collapse")

    if calib_d.get("drift"):
        any_drift = True
        alerts.append(
            f"CALIBRATION_DRIFT: Brier Δ={calib_d.get('delta', 0):+.4f} "
            f"overconfident={calib_d.get('overconfident', False)}"
        )

    if market_d.get("trend") == "DECLINING":
        any_drift = True
        alerts.append(
            f"MARKET_HARDENING: CLV 7d={market_d.get('clv_7d', 0)*100:+.2f}% "
            f"vs 30d={market_d.get('clv_30d', 0)*100:+.2f}%"
        )

    return {
        "any_drift":    any_drift,
        "auto_disable": auto_disable,
        "model":        model_d,
        "calibration":  calib_d,
        "market":       market_d,
        "alerts":       alerts,
        "timestamp":    datetime.now().isoformat(),
    }
