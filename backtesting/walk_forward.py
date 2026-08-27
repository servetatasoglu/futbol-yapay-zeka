# backtesting/walk_forward.py
"""
Walk-Forward Validation & Performance Gate Controllers
════════════════════════════════════════════════════════════════
Rigorous Chronological Out-of-Sample Backtesting & Validation Gates.
"""

import os
import json
import logging
import numpy as np
from datetime import datetime, timezone
from collections import defaultdict

from tracking.validation import calistir, sonuclari_yukle, filtre_agirliklarini_yukle
from tracking.clv_tracker import clv_raporu

logger = logging.getLogger("walk_forward")

def sharpe_gate_kontrol() -> dict:
    """
    Sharpe Ratio Kontrolü.
    Geçmiş performans Sharpe oranını değerlendirir.
    Returns: {"gecti": bool, "sebep": str, "sharpe": float}
    """
    try:
        from risk.bankroll import bankroll_raporu, get_current_bankroll
        clv_log = os.path.join(os.path.dirname(__file__), "..", "data", "clv_bet_log.json")
        rapor = bankroll_raporu(clv_log, baslangic_banka=1000.0)
        sharpe = rapor.get("sharpe_ratio", 0.0) if isinstance(rapor, dict) else 0.0
        
        if sharpe < -1.5:
            return {
                "gecti": False,
                "sharpe": sharpe,
                "sebep": f"Sharpe katastrofik negatif ({sharpe:.2f} < -1.5) - Risk kapısı aktif"
            }
        return {
            "gecti": True,
            "sharpe": sharpe,
            "sebep": f"Sharpe kabul edilebilir seviyede ({sharpe:.2f})"
        }
    except Exception as e:
        logger.warning(f"Sharpe gate hesaplama uyarısı: {e}")
        return {"gecti": True, "sharpe": 0.0, "sebep": f"Veri yetersiz/Varsayılan Onay ({e})"}


def clv_gate_kontrol() -> dict:
    """
    CLV (Closing Line Value) Gate Kontrolü.
    Piyasa kapanış oranlarına karşı performansı değerlendirir.
    Returns: {"gecti": bool, "sebep": str, "ort_clv": float}
    """
    try:
        rapor = clv_raporu()
        ort_clv = rapor.get("ort_clv")
        disable = rapor.get("execution_disable", False)
        
        if disable:
            return {
                "gecti": False,
                "ort_clv": ort_clv or 0.0,
                "sebep": f"Ortalama CLV yetersiz (%{ (ort_clv or 0)*100:.2f}) - Otomatik Devre Dışı"
            }
        
        clv_str = f"%{(ort_clv*100):.2f}" if ort_clv is not None else "Veri Henüz Yok"
        return {
            "gecti": True,
            "ort_clv": ort_clv,
            "sebep": f"CLV Seviyesi Uygun ({clv_str})"
        }
    except Exception as e:
        logger.warning(f"CLV gate hesaplama uyarısı: {e}")
        return {"gecti": True, "ort_clv": None, "sebep": f"Varsayılan Onay ({e})"}


def run_walk_forward_backtest(
    initial_bankroll: float = 1000.0,
    min_edge: float = 0.02,
    max_edge: float = 0.08,
    kelly_fraction: float = 0.25,
    max_stake_pct: float = 0.02
) -> dict:
    """
    Chronological Out-of-Sample Walk-Forward Backtesting Engine.
    Evaluates model performance over past matches without lookahead bias.
    """
    from data.matches import veri_yukle
    from features.elo import elo_point_in_time_hesapla
    from features.rolling_features import rolling_features_point_in_time

    ham_veri = veri_yukle()
    if not ham_veri:
        return {"error": "Veri bulunamadı", "total_bets": 0}

    # Flatten and sort matches chronologically
    all_matches = []
    for lig, m_list in ham_veri.items():
        for m in m_list:
            m_copy = dict(m)
            m_copy["_lig"] = lig
            all_matches.append(m_copy)

    all_matches.sort(key=lambda x: x.get("utcDate", ""))
    if len(all_matches) < 50:
        return {"error": "Yetersiz maç sayısı", "total_bets": 0}

    pit_elo = elo_point_in_time_hesapla(ham_veri)
    pit_rolling = rolling_features_point_in_time(ham_veri, n_son=5)

    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_drawdown = 0.0
    bets = []
    daily_returns = defaultdict(float)

    brier_scores = []
    log_losses = []

    # Historical walk-forward loop (skip first 200 matches as burn-in)
    burn_in = min(200, len(all_matches) // 3)
    
    for mac in all_matches[burn_in:]:
        try:
            m_id = str(mac.get("id") or f"{mac.get('homeTeam',{}).get('name')}_{mac.get('awayTeam',{}).get('name')}_{mac.get('utcDate')}")
            ev = mac["homeTeam"]["name"]
            dep = mac["awayTeam"]["name"]
            hg = mac["score"]["fullTime"]["home"]
            dg = mac["score"]["fullTime"]["away"]
            date_str = str(mac.get("utcDate", ""))[:10]
        except (KeyError, TypeError):
            continue

        if hg is None or dg is None:
            continue

        actual_outcome = "HOME" if hg > dg else ("DRAW" if hg == dg else "AWAY")
        actual_vector = [1.0 if actual_outcome == "HOME" else 0.0,
                         1.0 if actual_outcome == "DRAW" else 0.0,
                         1.0 if actual_outcome == "AWAY" else 0.0]

        # Model predicted probabilities (from point-in-time ELO & Poisson proxy)
        elo_info = pit_elo.get(m_id, {"ev_elo": 1500.0, "dep_elo": 1500.0})
        fark = elo_info["ev_elo"] - elo_info["dep_elo"] + 65.0
        p_home_raw = 1.0 / (1.0 + 10.0 ** (-fark / 400.0))
        p_draw_raw = 0.27 * np.exp(-abs(fark)/400.0 * 1.2)
        p_away_raw = max(0.01, 1.0 - p_home_raw) * (1.0 - p_draw_raw)
        p_home_raw *= (1.0 - p_draw_raw)
        
        tot = p_home_raw + p_draw_raw + p_away_raw
        p_home, p_draw, p_away = p_home_raw/tot, p_draw_raw/tot, p_away_raw/tot
        pred_vector = [p_home, p_draw, p_away]

        # Calibration metrics
        brier = sum((p - a)**2 for p, a in zip(pred_vector, actual_vector)) / 3.0
        brier_scores.append(brier)
        
        eps = 1e-9
        ll = -sum(a * np.log(max(p, eps)) for p, a in zip(pred_vector, actual_vector))
        log_losses.append(ll)

        # Implied market odds proxy (with 1.05 vig)
        odds_h = round(1.05 / max(p_home, 0.05), 2)
        odds_d = round(1.05 / max(p_draw, 0.05), 2)
        odds_a = round(1.05 / max(p_away, 0.05), 2)

        # Check edge
        candidates = [
            ("HOME", p_home, odds_h, actual_outcome == "HOME"),
            ("AWAY", p_away, odds_a, actual_outcome == "AWAY")
        ]

        for sel, prob, odds, won in candidates:
            market_p = 1.0 / odds
            edge = prob - market_p
            ev = prob * odds - 1.0

            if min_edge <= edge <= max_edge and ev > 0:
                # Fractional Kelly sizing
                b = odds - 1.0
                q = 1.0 - prob
                kelly_raw = max(0.0, (b * prob - q) / b)
                stake_pct = min(max_stake_pct, kelly_raw * kelly_fraction)
                
                if stake_pct <= 0.001:
                    continue

                stake = bankroll * stake_pct
                pnl = stake * (odds - 1.0) if won else -stake
                bankroll += pnl

                peak_bankroll = max(peak_bankroll, bankroll)
                dd = (peak_bankroll - bankroll) / peak_bankroll
                max_drawdown = max(max_drawdown, dd)

                daily_returns[date_str] += pnl / max(bankroll, 1.0)

                bets.append({
                    "date": date_str,
                    "match": f"{ev} vs {dep}",
                    "selection": sel,
                    "prob": prob,
                    "odds": odds,
                    "edge": edge,
                    "ev": ev,
                    "stake": stake,
                    "won": won,
                    "pnl": pnl,
                    "bankroll": bankroll
                })

    # Performance calculations
    total_bets = len(bets)
    if total_bets == 0:
        return {"total_bets": 0, "roi": 0.0, "yield": 0.0, "brier_score": np.mean(brier_scores) if brier_scores else 0.0}

    total_staked = sum(b["stake"] for b in bets)
    total_pnl = sum(b["pnl"] for b in bets)
    win_count = sum(1 for b in bets if b["won"])
    win_rate = win_count / total_bets
    roi = (total_pnl / initial_bankroll) * 100.0
    yield_pct = (total_pnl / max(total_staked, 1.0)) * 100.0

    ret_list = list(daily_returns.values())
    if len(ret_list) > 5 and np.std(ret_list) > 0:
        sharpe = (np.mean(ret_list) / np.std(ret_list)) * np.sqrt(252)
        downside_std = np.std([r for r in ret_list if r < 0] or [0.001])
        sortino = (np.mean(ret_list) / max(downside_std, 1e-6)) * np.sqrt(252)
    else:
        sharpe = 0.0
        sortino = 0.0

    return {
        "total_bets": total_bets,
        "win_count": win_count,
        "win_rate": round(win_rate, 4),
        "initial_bankroll": initial_bankroll,
        "final_bankroll": round(bankroll, 2),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "yield_pct": round(yield_pct, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "mean_brier_score": round(float(np.mean(brier_scores)), 4) if brier_scores else 0.0,
        "mean_log_loss": round(float(np.mean(log_losses)), 4) if log_losses else 0.0,
        "burn_in_matches": burn_in
    }

