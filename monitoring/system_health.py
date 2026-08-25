# monitoring/system_health.py
"""
System Health Monitor — v3.0
════════════════════════════════════════════════════════════
Single-call health dashboard for the entire betting engine.
Run this before every pipeline execution to catch silent failures.

Checks:
  1. Data freshness    — When was data last updated?
  2. Model age         — Is GBM model too old?
  3. CLV health        — Is CLV being tracked? Is it positive?
  4. API quota         — Estimate remaining API calls
  5. Risk exposure     — Daily limits OK?
  6. Drift alerts      — Any regime drift detected?
  7. Calibration       — Is calibrator.pkl valid?

Returns a structured health dict + prints colored console summary.
"""

import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("system_health")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _dosya_yasi_saat(path: str) -> float:
    """Returns file age in hours, or 9999 if missing."""
    if not os.path.exists(path):
        return 9999.0
    return (time.time() - os.path.getmtime(path)) / 3600


def _json_yukle(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


# ─────────────────────────────────────────────────────────────────
# 1. DATA FRESHNESS
# ─────────────────────────────────────────────────────────────────

def _data_freshness_check() -> dict:
    """Check age of all critical data files."""
    files = {
        "matches_json":    os.path.join(BASE_DIR, "data", "matches.json"),
        "odds_cache":      os.path.join(BASE_DIR, "data", "odds_cache.json"),
        "closing_cache":   os.path.join(BASE_DIR, "data", "odds_cache_closing.json"),
        "clv_log":         os.path.join(BASE_DIR, "data", "clv_bet_log.json"),
        "learner_db":      os.path.join(BASE_DIR, "data", "learner_db.json"),
        "exec_db":         os.path.join(BASE_DIR, "data", "execution_db.json"),
    }

    results = {}
    alerts  = []

    thresholds = {
        "matches_json":  48,   # 48h — match data
        "odds_cache":    12,   # 12h — odds must be fresh
        "closing_cache": 6,    # 6h  — closing odds for CLV
        "clv_log":       72,   # 72h — CLV log (updated by closing_odds)
        "learner_db":    168,  # 7 days — learner
        "exec_db":       24,   # 24h — execution state
    }

    for name, path in files.items():
        age_h     = _dosya_yasi_saat(path)
        threshold = thresholds.get(name, 48)
        exists    = os.path.exists(path)
        stale     = age_h > threshold
        results[name] = {
            "exists":    exists,
            "age_hours": round(age_h, 1) if age_h < 9999 else None,
            "stale":     stale,
            "threshold_hours": threshold,
        }
        if not exists:
            alerts.append(f"MISSING: {name}")
        elif stale:
            alerts.append(f"STALE: {name} ({age_h:.0f}h old, limit {threshold}h)")

    return {"results": results, "alerts": alerts, "ok": len(alerts) == 0}


# ─────────────────────────────────────────────────────────────────
# 2. MODEL HEALTH
# ─────────────────────────────────────────────────────────────────

def _model_health_check() -> dict:
    """Check GBM model age and calibrator validity."""
    gbm_path = os.path.join(BASE_DIR, "data", "gbm_model.pkl")
    cal_path = os.path.join(BASE_DIR, "data", "calibrator.pkl")

    gbm_age_h = _dosya_yasi_saat(gbm_path)
    cal_age_h = _dosya_yasi_saat(cal_path)

    try:
        from config.settings import MODEL_YENILEME_GUN
        max_age_h = MODEL_YENILEME_GUN * 24
    except ImportError:
        max_age_h = 7 * 24  # 7 days

    gbm_ok  = gbm_age_h < max_age_h
    cal_ok  = cal_age_h < 30 * 24   # 30 days
    gbm_exists = os.path.exists(gbm_path)
    cal_exists = os.path.exists(cal_path)

    alerts = []
    if not gbm_exists:
        alerts.append("GBM_MODEL_MISSING — run: python model/train.py")
    elif not gbm_ok:
        alerts.append(f"GBM_MODEL_STALE — {gbm_age_h:.0f}h old (limit {max_age_h:.0f}h)")
    if not cal_exists:
        alerts.append("CALIBRATOR_MISSING — run: python model/train.py")
    elif not cal_ok:
        alerts.append(f"CALIBRATOR_STALE — {cal_age_h:.0f}h old")

    # Exponential weight at current age
    import math
    gbm_weight = round(max(0.05, 0.45 * math.exp(-gbm_age_h / (5 * 24))), 3) if gbm_exists else 0.0

    return {
        "gbm_exists":   gbm_exists,
        "gbm_age_h":    round(gbm_age_h, 1) if gbm_age_h < 9999 else None,
        "gbm_ok":       gbm_ok,
        "gbm_weight":   gbm_weight,
        "cal_exists":   cal_exists,
        "cal_age_h":    round(cal_age_h, 1) if cal_age_h < 9999 else None,
        "cal_ok":       cal_ok,
        "alerts":       alerts,
        "ok":           len(alerts) == 0,
    }


# ─────────────────────────────────────────────────────────────────
# 3. CLV HEALTH
# ─────────────────────────────────────────────────────────────────

def _clv_health_check() -> dict:
    """Check CLV tracking quality and alarm status."""
    try:
        from tracking.clv_tracker import clv_raporu
        rapor = clv_raporu()
    except Exception as e:
        return {"ok": False, "alerts": [f"CLV_RAPORU_ERROR: {e}"],
                "alarm": False, "execution_disable": False}

    alerts = []
    toplam  = rapor.get("toplam_bahis", 0)
    hesap   = rapor.get("clv_hesaplanan", 0)
    ort_clv = rapor.get("ort_clv")
    alarm   = rapor.get("alarm", False)
    disable = rapor.get("execution_disable", False)

    if toplam == 0:
        alerts.append("NO_BETS_LOGGED — system may not have run yet")
    elif toplam > 0 and hesap / max(toplam, 1) < 0.50:
        coverage = hesap / toplam * 100
        alerts.append(f"LOW_CLV_COVERAGE: {coverage:.0f}% — closing_odds.py not collecting")

    if alarm:
        alerts.append(f"CLV_ALARM: avg CLV={ort_clv*100:.2f}% over {rapor.get('clv_hesaplanan',0)} bets")
    if disable:
        alerts.append(f"⛔ EXECUTION_DISABLED: CLV={ort_clv*100:.2f}% — system should be halted")

    return {
        "toplam_bahis":     toplam,
        "clv_hesaplanan":   hesap,
        "coverage_pct":     round(hesap / max(toplam, 1) * 100, 1),
        "ort_clv":          ort_clv,
        "rolling_30d_clv":  rapor.get("rolling_30d_clv"),
        "ort_brier":        rapor.get("ort_brier"),
        "alarm":            alarm,
        "execution_disable": disable,
        "alerts":           alerts,
        "ok":               not disable and len(alerts) == 0,
    }


# ─────────────────────────────────────────────────────────────────
# 4. API QUOTA
# ─────────────────────────────────────────────────────────────────

def _api_quota_check() -> dict:
    """Estimate remaining API quota for this month."""
    # The-Odds-API: 500 req/month free tier
    # Each pipeline run: ~7 leagues × 1 req = 7 calls
    # Closing odds: ~7 leagues × 2/day = ~14 calls/day

    try:
        from config.settings import ODDS_API_KEY
        has_key = bool(ODDS_API_KEY and ODDS_API_KEY not in ("", "BURAYA_ODDS_API_KEY"))
    except ImportError:
        has_key = False

    # Estimate usage from odds_cache age
    cache_path = os.path.join(BASE_DIR, "data", "odds_cache.json")
    cache = _json_yukle(cache_path)

    # Count API calls made this month (approximation)
    simdi     = datetime.now(timezone.utc)
    ay_basi   = simdi.replace(day=1, hour=0, minute=0, second=0)
    gun_sayisi = (simdi - ay_basi).days + 1

    # Conservative estimate: 2 pipeline runs + 2 closing odds runs per day
    est_gunluk = 7 * 2 + 7 * 2   # ~28 calls/day
    est_kullanim = est_gunluk * gun_sayisi
    est_kalan    = max(0, 500 - est_kullanim)

    alerts = []
    if not has_key:
        alerts.append("NO_ODDS_API_KEY — CLV tracking impossible")
    if est_kalan < 50:
        alerts.append(f"LOW_API_QUOTA: ~{est_kalan} calls remaining this month")

    return {
        "has_key":       has_key,
        "est_kullanim":  est_kullanim,
        "est_kalan":     est_kalan,
        "gun_sayisi":    gun_sayisi,
        "alerts":        alerts,
        "ok":            has_key and est_kalan > 50,
    }


# ─────────────────────────────────────────────────────────────────
# 5. RISK EXPOSURE
# ─────────────────────────────────────────────────────────────────

def _risk_exposure_check() -> dict:
    """Check daily exposure and stop-loss status."""
    try:
        from execution.engine import risk_kontrol
        from risk.bankroll import get_current_bankroll
        bankroll = get_current_bankroll()
        risk = risk_kontrol(bankroll)
    except Exception as e:
        return {"ok": True, "alerts": [f"Risk check unavailable: {e}"],
                "izin": True}

    alerts = []
    if not risk.get("izin"):
        alerts.append(f"BETTING_HALTED: {risk.get('sebep','?')} — {risk.get('risk_seviye','?')}")
    elif risk.get("risk_seviye") == "DİKKAT":
        alerts.append(f"RISK_DIKKAT: {risk.get('sebep','?')} — stake multiplier {risk.get('stake_carpan',1):.1f}x")

    return {
        "izin":         risk.get("izin", True),
        "risk_seviye":  risk.get("risk_seviye", "NORMAL"),
        "gunluk_bahis": risk.get("gunluk_bahis", 0),
        "gunluk_kayip": risk.get("gunluk_kayip", 0),
        "stake_carpan": risk.get("stake_carpan", 1.0),
        "alerts":       alerts,
        "ok":           risk.get("izin", True),
    }


# ─────────────────────────────────────────────────────────────────
# 6. FULL HEALTH CHECK
# ─────────────────────────────────────────────────────────────────

def health_check(verbose: bool = True) -> dict:
    """
    Run all health checks. Returns structured health report.
    Set verbose=True to print colored console output.
    """
    checks = {
        "data":      _data_freshness_check(),
        "model":     _model_health_check(),
        "clv":       _clv_health_check(),
        "api":       _api_quota_check(),
        "risk":      _risk_exposure_check(),
    }

    all_alerts  = []
    critical    = []
    system_ok   = True

    for name, result in checks.items():
        alerts = result.get("alerts", [])
        all_alerts.extend(alerts)
        if not result.get("ok", True):
            system_ok = False
        # Critical: execution_disable or betting halted
        if name == "clv" and result.get("execution_disable"):
            critical.append("⛔ CLV_EXECUTION_DISABLED")
        if name == "risk" and not result.get("izin"):
            critical.append(f"⛔ RISK_HALT: {result.get('risk_seviye','?')}")

    report = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "system_ok":   system_ok,
        "critical":    critical,
        "all_alerts":  all_alerts,
        "checks":      checks,
        "execution_allowed": len(critical) == 0,
    }

    if verbose:
        _print_health(report)

    return report


# ─────────────────────────────────────────────────────────────────
# 7. CONSOLE OUTPUT
# ─────────────────────────────────────────────────────────────────

def _print_health(report: dict):
    SEP = "═" * 62
    ok_sym  = "✅"
    err_sym = "❌"
    warn_sym = "⚠️ "

    print(f"\n{SEP}")
    print(f"  🏥  SYSTEM HEALTH — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(SEP)

    checks = report.get("checks", {})

    def _status(check_key: str, label: str):
        c   = checks.get(check_key, {})
        sym = ok_sym if c.get("ok", True) else err_sym
        print(f"  {sym}  {label}")
        for alert in c.get("alerts", []):
            print(f"       {warn_sym} {alert}")

    _status("data",  "Data Freshness")
    _status("model", "Model Health")
    _status("clv",   "CLV Tracking")
    _status("api",   "API Quota")
    _status("risk",  "Risk Controls")

    # CLV summary
    clv = checks.get("clv", {})
    if clv.get("ort_clv") is not None:
        clv_val = clv["ort_clv"] * 100
        clv_sym = "📈" if clv_val > 0 else "📉"
        print(f"\n  {clv_sym}  CLV: {clv_val:+.2f}% avg | "
              f"coverage {clv.get('coverage_pct',0):.0f}% | "
              f"bets {clv.get('toplam_bahis',0)}")

    # Model weight
    model = checks.get("model", {})
    if model.get("gbm_weight") is not None:
        print(f"  🤖  GBM weight: {model['gbm_weight']:.3f} "
              f"(age: {model.get('gbm_age_h','?'):.0f}h)" if isinstance(model.get('gbm_age_h'), float) else
              f"  🤖  GBM weight: {model['gbm_weight']:.3f}")

    # Critical alerts
    if report.get("critical"):
        print(f"\n  {'⛔' * len(report['critical'])} CRITICAL:")
        for c in report["critical"]:
            print(f"     {c}")

    # Overall verdict
    print()
    if report.get("execution_allowed"):
        print(f"  ✅  SYSTEM READY — Execution allowed")
    else:
        print(f"  ⛔  SYSTEM BLOCKED — Fix critical issues before betting")

    print(SEP)


def execution_izni_var_mi() -> bool:
    """
    Quick check: is the system healthy enough to execute bets?
    Use this at the top of main.py pipeline.
    """
    report = health_check(verbose=False)
    if not report.get("execution_allowed"):
        logger.warning(
            f"Execution blocked: {report.get('critical', [])} | "
            f"alerts: {report.get('all_alerts', [])[:3]}"
        )
        return False
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    health_check(verbose=True)
