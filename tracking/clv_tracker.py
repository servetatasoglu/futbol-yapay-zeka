# tracking/clv_tracker.py
"""
CLV (Closing Line Value) Takip Sistemi — v3.0
═══════════════════════════════════════════════════════
CLV = bahis_anindaki_oran / closing_oran - 1

CLV > 0  → Piyasadan önce doğru hareket ettik → GERÇEK EDGE
CLV < 0  → Piyasa aleyhimize hareket etti     → YANLIŞ EDGE
CLV ≈ 0  → Rastgele                           → Komisyon yiyeceğiz

v3.0 İyileştirmeleri:
  - | separator (closing_odds.py ile tutarlı)
  - CLV decomposition: timing_clv vs edge_clv
  - Rolling 30-day alarm: CLV < -2% over 50+ bets → auto-disable
  - Brier score trend tracking
  - Entry hour analysis (when do we get best CLV?)
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("clv_tracker")

CLV_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "clv_bet_log.json")

# ── Auto-disable thresholds ───────────────────────────────────────
CLV_ALARM_ESIK      = -0.02   # -2% CLV average triggers alarm
CLV_ALARM_MIN_BAHIS = 50      # Minimum bets before alarm fires
CLV_DISABLE_ESIK    = -0.03   # -3% CLV average triggers execution disable
CLV_DISABLE_MIN_BAHIS = 100   # Minimum bets before disable fires


def _yukle() -> dict:
    """CLV veritabanını yükle."""
    if os.path.exists(CLV_LOG_PATH):
        try:
            with open(CLV_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"bahisler": [], "gunluk_raporlar": [], "clv_ozet": {}}


def _kaydet(db: dict):
    """CLV veritabanını kaydet."""
    os.makedirs(os.path.dirname(CLV_LOG_PATH), exist_ok=True)
    with open(CLV_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def bahis_kaydet(bahis: dict) -> None:
    """
    Bahis anındaki verileri CLV loguna kaydet.
    
    Gerekli alanlar:
        ev, dep, tahmin, oran, edge, p_secim, aktif_tier,
        veri_kaynak, confidence, lig, mac_tarihi
    """
    db = _yukle()
    
    kayit = {
        "tarih":        datetime.now().strftime("%Y-%m-%dT%H:%M"),
        "mac_tarihi":   bahis.get("mac_tarihi", ""),
        "ev":           bahis.get("ev", ""),
        "dep":          bahis.get("dep", ""),
        "tahmin":       bahis.get("tahmin", ""),
        "oran_bahis":   bahis.get("oran", 0),
        "edge":         bahis.get("edge", 0),
        "model_p":      bahis.get("p_secim", 0),
        "market_p":     bahis.get("market_p", 0),
        "aktif_tier":   bahis.get("aktif_tier", "NO_SHARP"),
        "veri_kaynak":  bahis.get("veri_kaynak", "TAM"),
        "confidence":   bahis.get("confidence", 0),
        "kelly_size":   bahis.get("size", 0),
        "lig":          bahis.get("lig", "?"),
        "oran_alinma":  bahis.get("oran_alinma", bahis.get("oran", 0)),
        # Closing odds — maç başlamadan önce doldurulacak
        "oran_closing": None,
        "oran_kapanis": None,
        "clv":          None,
        "sonuc":        None,
        "model_version": bahis.get("model_version", "v4.0-institutional"),
        "feature_version": bahis.get("feature_version", "v4.0-pit"),
        "calibrator_version": bahis.get("calibrator_version", "v4.0-oof"),
    }
    
    db["bahisler"].append(kayit)
    _kaydet(db)


def closing_odds_guncelle(ev: str, dep: str, closing_oranlar: dict) -> bool:
    """
    v3.0: Maç başlamadan önce closing odds'u güncelle.
    Matching: tries exact name match, then partial (handles API name variations).
    closing_oranlar: {"ev": float, "ber": float, "dep": float}
    """
    db = _yukle()
    guncellendi = False

    def _isim_esles(b_ev: str, b_dep: str) -> bool:
        """Fuzzy team name matching (handles API vs DB name differences)."""
        if b_ev == ev and b_dep == dep:
            return True
        # Partial match: check if one is substring of the other
        if (ev.lower() in b_ev.lower() or b_ev.lower() in ev.lower()) and \
           (dep.lower() in b_dep.lower() or b_dep.lower() in dep.lower()):
            return True
        return False

    for b in db["bahisler"]:
        if not _isim_esles(b.get("ev", ""), b.get("dep", "")):
            continue
        if b.get("oran_closing") is not None or b.get("oran_kapanis") is not None:
            continue  # Already has closing odds

        tahmin = str(b.get("tahmin", "")).strip()
        closing_oran = 0.0

        if tahmin in ["Ev Sahibi Kazanır", "1", "Ev Sahibi", "HOME"]:
            closing_oran = closing_oranlar.get("ev", 0.0)
        elif tahmin in ["Beraberlik", "X", "0", "DRAW"]:
            closing_oran = closing_oranlar.get("ber", 0.0)
        elif tahmin in ["Deplasman Kazanır", "2", "Deplasman", "AWAY"]:
            closing_oran = closing_oranlar.get("dep", 0.0)
        elif "2.5 Üst" in tahmin or "OVER" in tahmin:
            closing_oran = closing_oranlar.get("over25_oran", closing_oranlar.get("over", 0.0))
        elif "2.5 Alt" in tahmin or "UNDER" in tahmin:
            closing_oran = closing_oranlar.get("under25_oran", closing_oranlar.get("under", 0.0))
        elif "KG Var" in tahmin or "BTTS_YES" in tahmin:
            closing_oran = closing_oranlar.get("btts_yes_oran", 0.0)
        elif "KG Yok" in tahmin or "BTTS_NO" in tahmin:
            closing_oran = closing_oranlar.get("btts_no_oran", 0.0)
        else:
            closing_oran = closing_oranlar.get("ev", 0.0)

        if closing_oran > 1.01:
            b["oran_closing"] = round(float(closing_oran), 3)
            b["oran_kapanis"] = b["oran_closing"]
            # CLV = (odds_at_bet / closing_odds) - 1
            # Positive = we got better than closing line = real edge
            oran_b = float(b.get("oran_bahis") or b.get("oran_alinma") or b.get("oran", 0.0))
            clv_raw = (oran_b / closing_oran) - 1
            b["clv"] = round(clv_raw, 4)

            # v3.0: CLV decomposition
            # timing_clv: how much of CLV came from entry timing
            # edge_clv: how much from model edge vs market
            model_p  = b.get("model_p", 0)
            market_p = b.get("market_p", 0)
            if model_p > 0 and market_p > 0:
                fair_closing = 1.0 / closing_oran
                b["edge_clv"]   = round(model_p - market_p, 4)
                b["timing_clv"] = round(fair_closing - market_p, 4)

            logger.info(
                f"  📈 CLV Güncellendi: {b.get('ev')} vs {b.get('dep')} | "
                f"bahis={oran_b:.2f} kapanış={closing_oran:.2f} "
                f"→ CLV={b['clv']*100:+.2f}%"
            )
            guncellendi = True

    if guncellendi:
        _kaydet(db)
    return guncellendi


def mac_sonucu_guncelle(ev: str, dep: str, sonuc: str) -> bool:
    """Maç sonucunu güncelle (ev/dep/ber)."""
    db = _yukle()
    guncellendi = False
    
    for b in db["bahisler"]:
        if b.get("ev") == ev and b.get("dep") == dep and b.get("sonuc") is None:
            # AUDIT FIX: Mandatory CLV Validation. If closing odds are missing, invalidate the bet.
            if (b.get("oran_closing") is None and b.get("oran_kapanis") is None) or b.get("clv") is None:
                logger.warning(f"🚨 Bet {ev} vs {dep} missing closing odds! Marking as INVALID_NO_CLV.")
                b["sonuc"] = "INVALID_NO_CLV"
            else:
                b["sonuc"] = sonuc
            guncellendi = True
    
    if guncellendi:
        _kaydet(db)
    return guncellendi


def clv_raporu() -> dict:
    """
    v3.0: CLV performans raporu + auto-disable alarm.

    Döndürür:
        {
            "toplam_bahis": int,
            "clv_hesaplanan": int,
            "ort_clv": float,
            "clv_pozitif_oran": float,
            "alarm": bool,           # CLV < -2% over 50+ bets
            "execution_disable": bool, # CLV < -3% over 100+ bets
            "rolling_30d_clv": float,  # Last 30 days CLV
            "ort_timing_clv": float,   # Timing component
            "ort_edge_clv": float,     # Model edge component
            "ort_brier": float,
            "lig_bazli": dict,
            "tier_bazli": dict,
        }
    """
    db = _yukle()
    bahisler = db.get("bahisler", [])

    if not bahisler:
        return {"toplam_bahis": 0, "mesaj": "Henüz bahis yok",
                "alarm": False, "execution_disable": False}

    clv_list = [b["clv"] for b in bahisler if b.get("clv") is not None]

    # ── CLV Coverage Alert ───────────────────────────────────────
    if len(bahisler) >= 10:
        missing_clv = sum(1 for b in bahisler if b.get("clv") is None)
        missing_pct = missing_clv / len(bahisler)
        if missing_pct > 0.10:
            logger.error(
                f"🚨 CLV Tracking Failure! "
                f"{missing_clv}/{len(bahisler)} bets missing closing odds. "
                f"Check closing_odds.py scheduler."
            )

    # ── Rolling 30-Day CLV ───────────────────────────────────────
    cutoff_30d = (datetime.now() - timedelta(days=30)).isoformat()[:16]
    son_30d = [
        b["clv"] for b in bahisler
        if b.get("clv") is not None and b.get("tarih", "") >= cutoff_30d
    ]
    rolling_30d = round(sum(son_30d) / len(son_30d), 4) if son_30d else None

    # ── Auto-Disable Alarm ───────────────────────────────────────
    ort_clv = sum(clv_list) / len(clv_list) if clv_list else 0
    n_clv   = len(clv_list)
    alarm            = n_clv >= CLV_ALARM_MIN_BAHIS and ort_clv < CLV_ALARM_ESIK
    execution_disable = n_clv >= CLV_DISABLE_MIN_BAHIS and ort_clv < CLV_DISABLE_ESIK

    if alarm:
        logger.warning(
            f"⚠️  CLV ALARM: Ortalama CLV={ort_clv*100:.2f}% "
            f"({n_clv} bahis) — eşik {CLV_ALARM_ESIK*100:.1f}%"
        )
    if execution_disable:
        logger.critical(
            f"🛑 CLV DISABLE: Ortalama CLV={ort_clv*100:.2f}% "
            f"({n_clv} bahis) — Execution engine should HALT."
        )

    # ── CLV Decomposition ────────────────────────────────────────
    timing_list = [b.get("timing_clv", 0) for b in bahisler if b.get("clv") is not None]
    edge_list   = [b.get("edge_clv",   0) for b in bahisler if b.get("clv") is not None]
    ort_timing  = round(sum(timing_list) / len(timing_list), 4) if timing_list else None
    ort_edge    = round(sum(edge_list)   / len(edge_list),   4) if edge_list   else None

    # ── Brier Score ──────────────────────────────────────────────
    brier_scores = []
    for b in bahisler:
        if b.get("sonuc") is None or b.get("model_p") is None:
            continue
        sonuc_str = str(b["sonuc"]).lower()
        if sonuc_str in ("iade", "void", "v", "invalid_no_clv"):
            continue
        gercek = 1.0 if sonuc_str in ("kazandi", "kazandı", "w", "win", "true") else 0.0
        brier_scores.append((b["model_p"] - gercek) ** 2)
    ort_brier = round(sum(brier_scores) / len(brier_scores), 4) if brier_scores else None

    # ── Lig / Tier breakdown ─────────────────────────────────────
    lig_clv: dict  = {}
    tier_clv: dict = {}
    saat_clv: dict = {}  # Entry hour analysis
    for b in bahisler:
        if b.get("clv") is None:
            continue
        lig_clv.setdefault(b.get("lig", "?"),        []).append(b["clv"])
        tier_clv.setdefault(b.get("aktif_tier", "?"), []).append(b["clv"])
        # Entry hour → which hour gives best CLV?
        try:
            saat = datetime.fromisoformat(b.get("tarih", "")).hour
            saat_clv.setdefault(saat, []).append(b["clv"])
        except Exception:
            pass

    best_saat = None
    if saat_clv:
        best_saat = max(saat_clv, key=lambda s: sum(saat_clv[s]) / len(saat_clv[s]))

    return {
        "toplam_bahis":      len(bahisler),
        "clv_hesaplanan":    len(clv_list),
        "ort_clv":           round(ort_clv, 4) if clv_list else None,
        "clv_pozitif_oran":  round(sum(1 for c in clv_list if c > 0) / n_clv, 3) if clv_list else None,
        "rolling_30d_clv":   rolling_30d,
        "ort_timing_clv":    ort_timing,
        "ort_edge_clv":      ort_edge,
        "alarm":             alarm,
        "execution_disable": execution_disable,
        "ort_brier":         ort_brier,
        "best_entry_hour":   best_saat,
        "lig_bazli": {
            lig: {"ort_clv": round(sum(v)/len(v), 4), "bahis_n": len(v)}
            for lig, v in lig_clv.items()
        },
        "tier_bazli": {
            tier: {"ort_clv": round(sum(v)/len(v), 4), "bahis_n": len(v)}
            for tier, v in tier_clv.items()
        },
    }