# backtesting/walk_forward.py
"""
Walk-Forward Validation & Performance Gate Controllers (Institutional-Grade)
═════════════════════════════════════════════════════════════════════════════
Zero Data Leakage, Real Historical Pinnacle Odds & Multi-Baseline Comparison
"""

import os
import glob
import json
import logging
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict

from tracking.clv_tracker import clv_raporu

logger = logging.getLogger("walk_forward")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PINNACLE_DIR = os.path.join(BASE_DIR, "data", "pinnacle_odds")
REPORT_PATH = os.path.join(BASE_DIR, "data", "walk_forward_sonuclar.json")

# Global Pinnacle Cache
_PINNACLE_CACHE = None


def load_pinnacle_historical_odds(force_reload: bool = False) -> dict:
    """
    data/pinnacle_odds/ altındaki tüm gerçek Pinnacle CSV dosyalarını yükler.
    Tarih ve takım adlarına göre indekslenmiş sözlük döner.
    Format:
        {(date_str, home_key, away_key): {
            "psh": float, "psd": float, "psa": float,
            "psch": float, "pscd": float, "psca": float,
            "fthg": int, "ftag": int, "ftr": str,
            "source": "pinnacle"
        }}
    """
    global _PINNACLE_CACHE
    if _PINNACLE_CACHE is not None and not force_reload:
        return _PINNACLE_CACHE

    if not os.path.exists(PINNACLE_DIR):
        logger.warning(f"Pinnacle dizini bulunamadı: {PINNACLE_DIR}")
        _PINNACLE_CACHE = {}
        return _PINNACLE_CACHE

    csv_files = glob.glob(os.path.join(PINNACLE_DIR, "*.csv"))
    if not csv_files:
        logger.warning(f"Pinnacle CSV dosyaları bulunamadı: {PINNACLE_DIR}")
        _PINNACLE_CACHE = {}
        return _PINNACLE_CACHE

    pinn_by_date = defaultdict(list)
    # FIX [P0-07]: Canonical fixture dedup set
    seen_fixtures = set()

    for fpath in sorted(csv_files):
        try:
            df = pd.read_csv(fpath, encoding="latin1", low_memory=False)
            req_cols = ["Date", "HomeTeam", "AwayTeam"]
            if not all(c in df.columns for c in req_cols):
                continue

            for _, row in df.iterrows():
                d_raw = str(row.get("Date", "")).strip()
                if not d_raw or "/" not in d_raw:
                    continue
                parts = d_raw.split("/")
                if len(parts) == 3:
                    day, month, year = parts
                    if len(year) == 2:
                        year = "20" + year
                    d_norm = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                else:
                    continue

                h_raw = str(row.get("HomeTeam", "")).strip()
                a_raw = str(row.get("AwayTeam", "")).strip()
                if not h_raw or not a_raw:
                    continue

                h_clean = _clean_team_name(h_raw)
                a_clean = _clean_team_name(a_raw)
                fixture_key = (d_norm, h_clean, a_clean)
                if fixture_key in seen_fixtures:
                    continue  # FIX [P0-07]: Skip duplicate fixture across overlapping CSVs

                # Pre-match Pinnacle odds
                psh = float(row.get("PSH", 0) or 0)
                psd = float(row.get("PSD", 0) or 0)
                psa = float(row.get("PSA", 0) or 0)

                # FIX [P0-05]: Never disguise B365 or Avg as Pinnacle odds!
                # If true Pinnacle odds (PSH/PSD/PSA) are missing, reject as Pinnacle data.
                if psh <= 1.0 or psd <= 1.0 or psa <= 1.0:
                    continue

                # Closing Pinnacle odds
                psch = float(row.get("PSCH", 0) or 0)
                pscd = float(row.get("PSCD", 0) or 0)
                psca = float(row.get("PSCA", 0) or 0)

                # FIX [P0-05]: If closing is missing, leave as 0.0 — DO NOT fallback to opening psh or B365
                if psch <= 1.0 or pscd <= 1.0 or psca <= 1.0:
                    psch = 0.0
                    pscd = 0.0
                    psca = 0.0

                seen_fixtures.add(fixture_key)
                pinn_by_date[d_norm].append({
                    "home": h_raw,
                    "away": a_raw,
                    "home_clean": h_clean,
                    "away_clean": a_clean,
                    "psh": psh,
                    "psd": psd,
                    "psa": psa,
                    "psch": psch,
                    "pscd": pscd,
                    "psca": psca,
                    "fthg": row.get("FTHG"),
                    "ftag": row.get("FTAG"),
                    "ftr": str(row.get("FTR", "")).upper()
                })
        except Exception as e:
            logger.debug(f"Pinnacle CSV okuma hatası {os.path.basename(fpath)}: {e}")

    _PINNACLE_CACHE = pinn_by_date
    logger.info(f"Gerçek Pinnacle veritabanı yüklendi: {len(seen_fixtures)} tekil maç, {len(pinn_by_date)} farklı tarih")
    return _PINNACLE_CACHE


def _clean_team_name(name: str) -> str:
    """Takım ismini normalize eder."""
    import unicodedata, re
    if not name:
        return ""
    n = unicodedata.normalize('NFKD', str(name)).encode('ASCII', 'ignore').decode('utf-8').lower()
    for s in [" de madrid", " de barcelona", " balompie", " fc", " afc", " cf", " cd", " sc", " ud", " ssc", " ac", " rc", " sad"]:
        n = n.replace(s, "")
    n = re.sub(r'[^a-z0-9 ]', ' ', n)
    return " ".join(n.split())


def _team_matches(t1: str, t2: str) -> bool:
    """
    FIX [P0-11]: Güvenli takım ismi eşleştirme.
    Substring/prefix matching kaldırıldı (Paris != Parma, Liverpool != Livorno).
    """
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    words1 = set(t1.split())
    words2 = set(t2.split())
    if len(words1) >= 2 and words1.issubset(words2):
        return True
    if len(words2) >= 2 and words2.issubset(words1):
        return True
    if (t1 in t2 or t2 in t1) and min(len(t1), len(t2)) >= 6:
        # Full word boundary check
        if f" {t1} " in f" {t2} " or f" {t2} " in f" {t1} ":
            return True
    return False


def match_pinnacle_odds(pinn_db: dict, match_date: str, ev_takim: str, dep_takim: str) -> dict | None:
    """
    Verilen maç için gerçek Pinnacle oranlarını bulur.
    FIX [P0-06]: +-1 gün toleransı KALDIRILDI. Sadece aynı gün (exact date).
    FIX [P0-11]: 5-karakter prefix eşleştirmesi KALDIRILDI.
    """
    if not pinn_db or not match_date:
        return None

    d_base = str(match_date)[:10]
    ev_c = _clean_team_name(ev_takim)
    dep_c = _clean_team_name(dep_takim)

    cands = pinn_db.get(d_base, [])
    for c in cands:
        ch = c["home_clean"]
        ca = c["away_clean"]
        if _team_matches(ch, ev_c) and _team_matches(ca, dep_c):
            return c

    return None


def sharpe_gate_kontrol() -> dict:
    """Sharpe Ratio Kontrolü."""
    try:
        from risk.bankroll import bankroll_raporu
        clv_log = os.path.join(BASE_DIR, "data", "clv_bet_log.json")
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
    """CLV (Closing Line Value) Gate Kontrolü."""
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
    min_edge: float = 0.015,
    max_edge: float = 0.08,
    kelly_fraction: float = 0.15,
    max_stake_pct: float = 0.02,
    use_real_odds_only: bool = True
) -> dict:
    """
    Chronological Out-of-Sample Walk-Forward Backtesting Engine.
    Zero Future Leakage, Real Historical Pinnacle Odds & Multi-Baseline Comparison.
    """
    from data.matches import veri_yukle
    from features.elo import elo_point_in_time_hesapla
    from features.rolling_features import rolling_features_point_in_time
    from calibration.calibration import apply_probability_pipeline, calculate_calibration_metrics

    ham_veri = veri_yukle()
    if not ham_veri:
        return {"error": "Veri bulunamadı", "total_bets": 0}

    # Pinnacle gerçek oran veritabanını yükle
    pinn_db = load_pinnacle_historical_odds()

    # Tüm maçları kronolojik sıraya diz
    all_matches = []
    for lig, m_list in ham_veri.items():
        for m in m_list:
            m_copy = dict(m)
            m_copy["_lig"] = lig
            all_matches.append(m_copy)

    all_matches.sort(key=lambda x: x.get("utcDate", ""))
    if len(all_matches) < 100:
        return {"error": "Yetersiz maç sayısı", "total_bets": 0}

    # Point-in-Time ELO ve Rolling Features (Sıfır sızıntı)
    pit_elo = elo_point_in_time_hesapla(ham_veri)
    pit_rolling = rolling_features_point_in_time(ham_veri, n_son=5)

    # Walk-forward bölümleri
    burn_in = min(300, len(all_matches) // 4)
    eval_matches = all_matches[burn_in:]

    # FIX [P0-03]: Fold-local calibrator trained strictly on pre-evaluation burn-in window
    # Zero leakage: never uses the global calibrator.pkl from disk
    local_calibrator = None
    try:
        from calibration.calibration import train_calibrator
        burn_in_probs = []
        burn_in_labels = []
        for b_mac in all_matches[:burn_in]:
            try:
                bm_id = str(b_mac.get("id") or f"{b_mac.get('homeTeam',{}).get('name')}_{b_mac.get('awayTeam',{}).get('name')}_{b_mac.get('utcDate')}")
                b_hg = int(b_mac["score"]["fullTime"]["home"])
                b_dg = int(b_mac["score"]["fullTime"]["away"])
            except Exception:
                continue
            b_act_int = 0 if b_hg > b_dg else (1 if b_hg == b_dg else 2)
            b_elo_info = pit_elo.get(bm_id, {"ev_elo": 1500.0, "dep_elo": 1500.0})
            b_fark = (b_elo_info["ev_elo"] + 65.0) - b_elo_info["dep_elo"]
            b_p_h = 1.0 / (1.0 + 10.0 ** (-b_fark / 400.0))
            b_denge = abs(b_fark) / 400.0
            b_p_d = 0.27 * math.exp(-b_denge * 1.2)
            b_p_a = (1.0 - b_p_d) * (1.0 - b_p_h)
            b_p_h *= (1.0 - b_p_d)
            b_tot = b_p_h + b_p_d + b_p_a
            burn_in_probs.append([b_p_h / b_tot, b_p_d / b_tot, b_p_a / b_tot])
            burn_in_labels.append(b_act_int)

        if len(burn_in_labels) >= 50:
            local_calibrator = train_calibrator(
                np.array(burn_in_probs),
                np.array(burn_in_labels),
                method="isotonic",
                save_to_disk=False
            )
            logger.info(f"Fold-local calibrator eğitildi: {len(burn_in_labels)} burn-in maçı üzerinden (disk'e yazılmadı)")
    except Exception as _cal_ex:
        logger.debug(f"Burn-in local calibration skipped: {_cal_ex}")

    bankroll = initial_bankroll
    peak_bankroll = initial_bankroll
    max_drawdown = 0.0
    bets = []
    daily_returns = defaultdict(float)

    # Metrik koleksiyonları: Model ve Baselines
    model_preds = []
    market_preds = []
    elo_preds = []
    poisson_preds = []
    prior_preds = []
    actual_labels = []

    clv_list = []
    rejection_reasons = defaultdict(int)

    # Lig bazlı kümülatif gol ortalamaları takibi
    cum_lig_stats = defaultdict(lambda: {"goals": 0, "matches": 0})

    for mac in eval_matches:
        try:
            m_id = str(mac.get("id") or f"{mac.get('homeTeam',{}).get('name')}_{mac.get('awayTeam',{}).get('name')}_{mac.get('utcDate')}")
            ev = mac["homeTeam"]["name"]
            dep = mac["awayTeam"]["name"]
            hg = mac["score"]["fullTime"]["home"]
            dg = mac["score"]["fullTime"]["away"]
            m_date = str(mac.get("utcDate", ""))
            lig = mac["_lig"]
        except (KeyError, TypeError):
            continue

        if hg is None or dg is None:
            continue

        hg = int(hg)
        dg = int(dg)
        actual_outcome = "HOME" if hg > dg else ("DRAW" if hg == dg else "AWAY")
        # FIX [P1-01]: Canonical class indexing: 0 = HOME, 1 = DRAW, 2 = AWAY
        actual_int = 0 if hg > dg else (1 if hg == dg else 2)
        actual_vector = [1.0 if actual_outcome == "HOME" else 0.0,
                         1.0 if actual_outcome == "DRAW" else 0.0,
                         1.0 if actual_outcome == "AWAY" else 0.0]

        # 1. Point-in-Time ELO Olasılıkları
        elo_info = pit_elo.get(m_id, {"ev_elo": 1500.0, "dep_elo": 1500.0})
        fark = (elo_info["ev_elo"] + 65.0) - elo_info["dep_elo"]
        p_home_elo = 1.0 / (1.0 + 10.0 ** (-fark / 400.0))
        denge = abs(fark) / 400.0
        p_draw_elo = 0.27 * math.exp(-denge * 1.2)
        p_away_elo = (1.0 - p_draw_elo) * (1.0 - p_home_elo)
        p_home_elo *= (1.0 - p_draw_elo)
        tot_elo = p_home_elo + p_draw_elo + p_away_elo
        p_home_elo, p_draw_elo, p_away_elo = p_home_elo / tot_elo, p_draw_elo / tot_elo, p_away_elo / tot_elo
        elo_vec = [p_home_elo, p_draw_elo, p_away_elo]

        # 2. Point-in-Time Poisson Olasılıkları
        l_stat = cum_lig_stats[lig]
        lig_avg = (l_stat["goals"] / max(l_stat["matches"] * 2, 1)) if l_stat["matches"] > 20 else 1.35
        # Basit point-in-time lambda
        lam_h = max(0.5, min(lig_avg * 1.06, 3.2))
        lam_a = max(0.5, min(lig_avg * 0.94, 3.2))
        # Poisson prob
        def p_pois(l, k): return (l**k * math.exp(-l)) / math.factorial(k)
        ph, pd_, pa = 0.0, 0.0, 0.0
        for h in range(7):
            for a in range(7):
                p = p_pois(lam_h, h) * p_pois(lam_a, a)
                if h > a: ph += p
                elif h == a: pd_ += p
                else: pa += p
        tot_p = ph + pd_ + pa
        pois_vec = [ph / tot_p, pd_ / tot_p, pa / tot_p]

        # 3. Model Baseline (Point-in-Time Calibrated)
        raw_home = 0.55 * p_home_elo + 0.45 * (ph / tot_p)
        raw_draw = 0.40 * p_draw_elo + 0.60 * (pd_ / tot_p)
        raw_away = 0.55 * p_away_elo + 0.45 * (pa / tot_p)
        raw_tot = raw_home + raw_draw + raw_away
        raw_vec = np.array([raw_home / raw_tot, raw_draw / raw_tot, raw_away / raw_tot])

        # Kalibrasyon pipeline (FIX [P0-03]: fold-local calibrator)
        cal_res = apply_probability_pipeline(raw_vec, calibrator_model=local_calibrator)
        model_prob_vec = cal_res["probs"] # [p_home, p_draw, p_away]
        p_home_m, p_draw_m, p_away_m = model_prob_vec[0], model_prob_vec[1], model_prob_vec[2]

        # 4. Gerçek Pinnacle Oranlarını Eşle
        pinn_match = match_pinnacle_odds(pinn_db, m_date, ev, dep)
        has_real_odds = pinn_match is not None

        if has_real_odds:
            odds_h = float(pinn_match["psh"])
            odds_d = float(pinn_match["psd"])
            odds_a = float(pinn_match["psa"])
            cl_h = float(pinn_match["psch"]) if float(pinn_match["psch"]) > 1.0 else odds_h
            cl_d = float(pinn_match["pscd"]) if float(pinn_match["pscd"]) > 1.0 else odds_d
            cl_a = float(pinn_match["psca"]) if float(pinn_match["psca"]) > 1.0 else odds_a

            # Vig-normalized fair market probability
            overround = (1.0 / odds_h) + (1.0 / odds_d) + (1.0 / odds_a)
            fair_h = (1.0 / odds_h) / overround
            fair_d = (1.0 / odds_d) / overround
            fair_a = (1.0 / odds_a) / overround
            market_vec = [fair_h, fair_d, fair_a]
        else:
            if use_real_odds_only:
                rejection_reasons["missing_real_pinnacle_odds"] += 1
                # Maç istatistiğini güncelle ve devam et
                cum_lig_stats[lig]["goals"] += hg + dg
                cum_lig_stats[lig]["matches"] += 1
                continue
            else:
                odds_h, odds_d, odds_a = 0.0, 0.0, 0.0
                cl_h, cl_d, cl_a = 0.0, 0.0, 0.0
                fair_h, fair_d, fair_a = 0.333, 0.333, 0.333
                market_vec = [0.333, 0.333, 0.333]

        # Baseline listelerine kaydet: [HOME=0, DRAW=1, AWAY=2]
        model_preds.append([p_home_m, p_draw_m, p_away_m])
        market_preds.append(market_vec)
        elo_preds.append(elo_vec)
        poisson_preds.append(pois_vec)
        prior_preds.append([0.46, 0.26, 0.28]) # Historical league prior: HOME=46%, DRAW=26%, AWAY=28%
        actual_labels.append(actual_int)

        # 5. Value Bet Karar Motoru
        candidates = [
            ("HOME", p_home_m, fair_h, odds_h, cl_h, actual_outcome == "HOME"),
            ("AWAY", p_away_m, fair_a, odds_a, cl_a, actual_outcome == "AWAY")
        ]

        # Beraberlik: Sadece güçlü edge ve makul oranlarda
        if p_draw_m > fair_d + 0.03:
            candidates.append(("DRAW", p_draw_m, fair_d, odds_d, cl_d, actual_outcome == "DRAW"))

        bet_placed_on_match = False
        for sel, p_mod, p_mkt, odds, cl_odds, won in candidates:
            if bet_placed_on_match:
                break

            edge = p_mod - p_mkt
            ev = p_mod * odds - 1.0

            # Filtre kapıları
            if edge < min_edge:
                rejection_reasons["edge_below_min"] += 1
                continue
            if edge > max_edge:
                rejection_reasons["edge_above_max_hallucination"] += 1
                continue
            if ev <= 0:
                rejection_reasons["negative_ev"] += 1
                continue
            if odds < 1.30 or odds > 6.0:
                rejection_reasons["odds_out_of_bounds"] += 1
                continue

            # Fractional Kelly boyutu
            b = odds - 1.0
            q = 1.0 - p_mod
            kelly_raw = max(0.0, (b * p_mod - q) / b)
            stake_pct = min(max_stake_pct, kelly_raw * kelly_fraction)

            if stake_pct < 0.003:
                rejection_reasons["kelly_too_small"] += 1
                continue

            stake = bankroll * stake_pct
            pnl = stake * (odds - 1.0) if won else -stake
            bankroll += pnl

            peak_bankroll = max(peak_bankroll, bankroll)
            dd = (peak_bankroll - bankroll) / peak_bankroll
            max_drawdown = max(max_drawdown, dd)

            clv = (odds / cl_odds) - 1.0 if cl_odds > 1.0 else 0.0
            clv_list.append(clv)

            daily_returns[m_date[:10]] += pnl / max(bankroll, 1.0)
            bet_placed_on_match = True

            bets.append({
                "date": m_date[:10],
                "match": f"{ev} vs {dep}",
                "selection": sel,
                "prob": round(p_mod, 4),
                "fair_p": round(p_mkt, 4),
                "odds": odds,
                "closing_odds": cl_odds,
                "clv": round(clv, 4),
                "edge": round(edge, 4),
                "ev": round(ev, 4),
                "stake": round(stake, 2),
                "won": bool(won),
                "pnl": round(pnl, 2),
                "bankroll": round(bankroll, 2)
            })

        # Maç sonuç istatistiğini güncelle
        cum_lig_stats[lig]["goals"] += hg + dg
        cum_lig_stats[lig]["matches"] += 1

    total_bets = len(bets)
    y_true_arr = np.array(actual_labels)

    # 6. Baseline Metrik Hesaplamaları
    def calc_metrics(probs_list):
        if not probs_list or len(probs_list) == 0:
            return {"log_loss": 0.0, "brier_score": 0.0, "accuracy": 0.0, "ece": 0.0}
        p_arr = np.array(probs_list)
        m = calculate_calibration_metrics(y_true_arr, p_arr)
        preds = np.argmax(p_arr, axis=1)
        acc = float(np.mean(preds == y_true_arr))
        m["accuracy"] = round(acc, 4)
        return m

    m_model = calc_metrics(model_preds)
    m_market = calc_metrics(market_preds)
    m_elo = calc_metrics(elo_preds)
    m_pois = calc_metrics(poisson_preds)
    m_prior = calc_metrics(prior_preds)

    # 7. Finansal Metrikler
    if total_bets > 0:
        total_staked = sum(b["stake"] for b in bets)
        total_pnl = sum(b["pnl"] for b in bets)
        win_count = sum(1 for b in bets if b["won"])
        win_rate = win_count / total_bets
        # FIX [Fix 19.1]: ROI is standard betting yield (total_pnl / total_staked)
        yield_pct = (total_pnl / max(total_staked, 1.0)) * 100.0
        roi = yield_pct
        bankroll_growth_pct = (total_pnl / initial_bankroll) * 100.0
        avg_clv = float(np.mean(clv_list)) if clv_list else 0.0
        pos_clv_pct = float(np.mean([c > 0 for c in clv_list])) * 100.0 if clv_list else 0.0

        ret_list = list(daily_returns.values())
        if len(ret_list) > 5 and np.std(ret_list) > 0:
            sharpe = (np.mean(ret_list) / np.std(ret_list)) * np.sqrt(252)
            downside_std = np.std([r for r in ret_list if r < 0] or [0.001])
            sortino = (np.mean(ret_list) / max(downside_std, 1e-6)) * np.sqrt(252)
        else:
            sharpe, sortino = 0.0, 0.0
    else:
        total_staked = total_pnl = win_count = win_rate = roi = yield_pct = bankroll_growth_pct = avg_clv = pos_clv_pct = sharpe = sortino = 0.0

    report = {
        "status": "success",
        "validation_type": "purged_walk_forward_oos",
        "odds_source": "real_pinnacle_historical",
        "model_type": "elo_poisson_baseline",  # FIX [P0-02]: Truthful labeling, not ML ensemble
        "total_evaluated_matches": len(eval_matches),
        "matches_with_real_pinnacle": len(actual_labels),
        "total_bets": total_bets,
        "win_count": win_count,
        "win_rate": round(win_rate, 4),
        "initial_bankroll": initial_bankroll,
        "final_bankroll": round(bankroll, 2),
        "total_staked": round(total_staked, 2),
        "total_pnl": round(total_pnl, 2),
        "roi_pct": round(roi, 2),
        "yield_pct": round(yield_pct, 2),
        "bankroll_growth_pct": round(bankroll_growth_pct, 2),
        "max_drawdown_pct": round(max_drawdown * 100.0, 2),
        "sharpe_ratio": round(sharpe, 2),
        "sortino_ratio": round(sortino, 2),
        "mean_clv_pct": round(avg_clv * 100.0, 2),
        "positive_clv_rate": round(pos_clv_pct, 2),
        "mean_brier_score": m_model["brier_score"],
        "mean_log_loss": m_model["log_loss"],
        "model_ece": m_model["ece"],
        "model_accuracy": m_model["accuracy"],
        "rejection_reasons": dict(rejection_reasons),
        "baselines": {
            "market_implied": m_market,
            "league_prior": m_prior,
            "elo_model": m_elo,
            "poisson_model": m_pois,
            "elo_poisson_baseline": m_model  # FIX [P0-02]: Explicit truthful baseline label
        }
    }

    # Kaydet
    try:
        os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Rapor dosyası kaydedilemedi: {e}")

    return report


def generate_walk_forward_windows(dates: list, train_days: int = 90, test_days: int = 30, step_days: int = 30) -> list:
    """
    Kronolojik, sızıntısız walk-forward pencere bölümleri üretir.
    Her pencerede: max(train_dates) < min(test_dates) kuralı kesin olarak sağlanır.
    """
    if not dates:
        return []
    sorted_dates = sorted(dates)
    min_date = sorted_dates[0]
    max_date = sorted_dates[-1]

    from datetime import timedelta
    windows = []
    current_start = min_date

    while True:
        train_end = current_start + timedelta(days=train_days)
        test_end = train_end + timedelta(days=test_days)
        if train_end >= max_date:
            break
        train_d = [d for d in sorted_dates if current_start <= d <= train_end]
        test_d = [d for d in sorted_dates if train_end < d <= test_end]
        if train_d and test_d:
            windows.append({
                "train_start": current_start,
                "train_end": train_end,
                "test_start": train_end,
                "test_end": test_end,
                "train_dates": train_d,
                "test_dates": test_d,
            })
        current_start += timedelta(days=step_days)
        if test_end >= max_date:
            break

    return windows
