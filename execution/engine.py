# execution/engine.py
"""
PROFESSIONAL EXECUTION ENGINE — v5
═══════════════════════════════════════════════════════════════
8 modül tek dosyada:
  1. Line Shopping       — En iyi oranı bul
  2. Market Microstructure — Sharp vs soft fark analizi
  3. Bet Timing          — Oran hareket analizi
  4. CLV Expectation     — Bahis öncesi CLV tahmini
  5. Advanced Stake      — 7 çarpanlı Kelly
  6. Bet Fragmentation   — Büyük bahisleri parçala
  7. Real-Time Risk      — Günlük stop-loss + drawdown
  8. Meta Learning       — Lig/odds/tip bazında öğrenme
"""

import os
import json
import logging
import math
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("execution")

# ─── Sabitler ──────────────────────────────────────────────────
SHARP_BOOKS = {"pinnacle", "betfair_ex_eu", "betfair", "matchbook", "betclic"}
SOFT_BOOKS = {"bet365", "unibet", "williamhill", "1xbet", "betsson", "marathonbet"}

EXEC_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "execution_db.json")
RISK_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "risk_state.json")


def _exec_db_yukle() -> dict:
    if os.path.exists(EXEC_DB_PATH):
        try:
            with open(EXEC_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"gunluk_bahisler": [], "gunluk_pnl": 0.0, "son_tarih": "", "ardisik_kayip": 0}


def _exec_db_kaydet(db: dict):
    os.makedirs(os.path.dirname(EXEC_DB_PATH), exist_ok=True)
    with open(EXEC_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
#  1. LINE SHOPPING — Her maç için en iyi oranı bul
# ═══════════════════════════════════════════════════════════════

def line_shopping(kitap_oranlari: dict, tahmin: str) -> dict:
    """
    Tüm bookmaker oranlarını karşılaştır, en iyisini seç.
    
    Args:
        kitap_oranlari: {"pinnacle": (ev, ber, dep), "bet365": (ev, ber, dep), ...}
        tahmin: "Ev Sahibi Kazanır" | "Beraberlik" | "Deplasman Kazanır"
    
    Returns:
        {
            "best_odds": float,
            "best_book": str,
            "avg_odds": float,
            "market_spread": float,       # max-min / min (fırsat göstergesi)
            "books_count": int,
            "edge_vs_avg": float,         # best vs avg farkı
            "sharp_best": bool,           # en iyi oran sharp book'tan mı?
        }
    """
    if not kitap_oranlari:
        return {"best_odds": 0, "best_book": "?", "avg_odds": 0,
                "market_spread": 0, "books_count": 0, "edge_vs_avg": 0, "sharp_best": False}
    
    idx = {"Ev Sahibi Kazanır": 0, "Beraberlik": 1, "Deplasman Kazanır": 2}.get(tahmin, 0)
    
    oranlar = {}
    for book, vals in kitap_oranlari.items():
        if isinstance(vals, (list, tuple)) and len(vals) > idx:
            oranlar[book] = vals[idx]
    
    if not oranlar:
        return {"best_odds": 0, "best_book": "?", "avg_odds": 0,
                "market_spread": 0, "books_count": 0, "edge_vs_avg": 0, "sharp_best": False}
    
    best_book = max(oranlar, key=oranlar.get)
    best_odds = oranlar[best_book]
    vals_list = list(oranlar.values())
    avg_odds = sum(vals_list) / len(vals_list)
    min_odds = min(vals_list)
    max_odds = max(vals_list)
    
    spread = (max_odds - min_odds) / min_odds if min_odds > 0 else 0
    edge_vs_avg = (best_odds - avg_odds) / avg_odds if avg_odds > 0 else 0
    
    return {
        "best_odds": round(best_odds, 3),
        "best_book": best_book,
        "avg_odds": round(avg_odds, 3),
        "market_spread": round(spread, 4),
        "books_count": len(oranlar),
        "edge_vs_avg": round(edge_vs_avg, 4),
        "sharp_best": best_book in SHARP_BOOKS,
    }


# ═══════════════════════════════════════════════════════════════
#  2. MARKET MICROSTRUCTURE — Piyasa davranış analizi
# ═══════════════════════════════════════════════════════════════

def market_microstructure(kitap_oranlari: dict, tahmin: str) -> dict:
    """
    Sharp vs Soft bookmaker farkını analiz et.
    
    Returns:
        {
            "sharp_avg": float,           # Sharp kitapların ortalaması
            "soft_avg": float,            # Soft kitapların ortalaması
            "sharp_soft_gap": float,      # Fark (pozitif = soft yüksek = fırsat)
            "market_confidence": float,   # 0-1 arası (1=tüm kitaplar uyumlu)
            "sharp_alignment": float,     # Model vs sharp uyumu
            "liquidity_proxy": float,     # Kitap sayısı bazlı likidite
        }
    """
    if not kitap_oranlari:
        return {"sharp_avg": 0, "soft_avg": 0, "sharp_soft_gap": 0,
                "market_confidence": 0.5, "sharp_alignment": 0, "liquidity_proxy": 0}
    
    idx = {"Ev Sahibi Kazanır": 0, "Beraberlik": 1, "Deplasman Kazanır": 2}.get(tahmin, 0)
    
    sharp_vals = []
    soft_vals = []
    all_vals = []
    
    for book, vals in kitap_oranlari.items():
        if isinstance(vals, (list, tuple)) and len(vals) > idx:
            v = vals[idx]
            all_vals.append(v)
            if book in SHARP_BOOKS:
                sharp_vals.append(v)
            elif book in SOFT_BOOKS:
                soft_vals.append(v)
    
    sharp_avg = sum(sharp_vals) / len(sharp_vals) if sharp_vals else 0
    soft_avg = sum(soft_vals) / len(soft_vals) if soft_vals else 0
    gap = (soft_avg - sharp_avg) / sharp_avg if sharp_avg > 0 else 0
    
    # Market confidence: tüm kitaplar ne kadar yakın?
    if len(all_vals) >= 2:
        mean_v = sum(all_vals) / len(all_vals)
        variance = sum((v - mean_v) ** 2 for v in all_vals) / len(all_vals)
        std = math.sqrt(variance)
        cv = std / mean_v if mean_v > 0 else 0
        market_confidence = round(max(0, min(1, 1.0 - cv * 10)), 3)
    else:
        market_confidence = 0.5
    
    liquidity_proxy = min(1.0, len(all_vals) / 10.0)
    
    return {
        "sharp_avg": round(sharp_avg, 3),
        "soft_avg": round(soft_avg, 3),
        "sharp_soft_gap": round(gap, 4),
        "market_confidence": market_confidence,
        "sharp_alignment": 0.0,  # model_p ile karşılaştırma main.py'de yapılacak
        "liquidity_proxy": round(liquidity_proxy, 2),
    }


# ═══════════════════════════════════════════════════════════════
#  3. BET TIMING — Oran hareket analizi
# ═══════════════════════════════════════════════════════════════

def timing_score(kitap_oranlari: dict, tahmin: str, hareket_db: dict = None) -> dict:
    """
    Oran hareketlerinden timing skoru hesapla.
    
    Sharp move: Pinnacle düşüyor + soft düşmemiş = ERKEN GİR
    Steam move: Tüm kitaplar düşüyor = GEÇ KALDIN
    
    Returns:
        {
            "timing_score": float,    # 0-1 (1=mükemmel zamanlama)
            "sharp_moved": bool,      # sharp kitaplar hareket ettiyse
            "soft_lag": bool,         # soft kitaplar geciktiyse
            "entry_signal": str,      # "ERKEN" | "NORMAL" | "GEC"
        }
    """
    if not kitap_oranlari:
        return {"timing_score": 0.5, "sharp_moved": False, "soft_lag": False, "entry_signal": "NORMAL"}
    
    idx = {"Ev Sahibi Kazanır": 0, "Beraberlik": 1, "Deplasman Kazanır": 2}.get(tahmin, 0)
    
    sharp_vals = []
    soft_vals = []
    for book, vals in kitap_oranlari.items():
        if isinstance(vals, (list, tuple)) and len(vals) > idx:
            v = vals[idx]
            if book in SHARP_BOOKS:
                sharp_vals.append(v)
            elif book in SOFT_BOOKS:
                soft_vals.append(v)
    
    if not sharp_vals or not soft_vals:
        return {"timing_score": 0.5, "sharp_moved": False, "soft_lag": False, "entry_signal": "NORMAL"}
    
    sharp_avg = sum(sharp_vals) / len(sharp_vals)
    soft_avg = sum(soft_vals) / len(soft_vals)
    
    # Soft kitaplar sharp'tan yüksekse → soft henüz düşmemiş → FIRSAT
    gap_pct = (soft_avg - sharp_avg) / sharp_avg if sharp_avg > 0 else 0
    
    # Hareket verisi varsa kullan
    if hareket_db:
        # Geçmiş oranlarla karşılaştır
        pass  # TODO: hareket_db entegrasyonu
    
    if gap_pct > 0.03:
        # Soft kitaplar %3+ geride → mükemmel zamanlama
        entry = "ERKEN"
        score = min(1.0, 0.7 + gap_pct * 5)
    elif gap_pct > 0.01:
        entry = "NORMAL"
        score = 0.5 + gap_pct * 10
    elif gap_pct < -0.01:
        # Sharp yükseldi ama soft düştü → piyasa bize TERSİNE gidiyor
        entry = "GEC"
        score = max(0.1, 0.5 + gap_pct * 10)
    else:
        entry = "NORMAL"
        score = 0.5
    
    return {
        "timing_score": round(score, 3),
        "sharp_moved": gap_pct > 0.02,
        "soft_lag": gap_pct > 0.03,
        "entry_signal": entry,
    }


# ═══════════════════════════════════════════════════════════════
#  4. CLV EXPECTATION — Bahis öncesi CLV tahmini
# ═══════════════════════════════════════════════════════════════

def clv_beklenti(edge: float, tier: str, lig: str, tahmin: str,
                 market_spread: float, sharp_alignment: float) -> dict:
    """
    Geçmiş CLV verisinden bahis önce beklenen CLV'yi tahmin et.
    
    expected_clv < 0 → bahis YAPMA
    
    Returns:
        {"expected_clv": float, "clv_confidence": float, "veto": bool}
    """
    try:
        from tracking.learner import _yukle
        db = _yukle()
    except Exception:
        db = {}
    
    lig_perf = db.get("lig_performans", {})
    tier_perf = db.get("tier_performans", {})
    tip_perf = db.get("tahmin_tipi_performans", {})
    
    # Base CLV expectation: edge'in bir kısmı CLV olarak realize olur
    # Tipik olarak edge'in %30-50'si CLV'ye dönüşür
    base_clv = edge * 0.35
    
    # Lig bonus/ceza
    lig_info = lig_perf.get(lig, {})
    if lig_info.get("n", 0) >= 5:
        lig_clv = lig_info.get("ort_clv", 0)
        base_clv += lig_clv * 0.3  # Geçmiş lig CLV'sinin %30'u
    
    # Tier bonus
    tier_info = tier_perf.get(tier, {})
    if tier_info.get("n", 0) >= 5:
        tier_clv = tier_info.get("ort_clv", 0)
        base_clv += tier_clv * 0.2
    
    # Tahmin tipi bonus
    tip_info = tip_perf.get(tahmin, {})
    if tip_info.get("n", 0) >= 5:
        tip_clv = tip_info.get("ort_clv", 0)
        base_clv += tip_clv * 0.2
    
    # Market spread yüksekse → fırsat fazla → CLV daha olası
    if market_spread > 0.05:
        base_clv *= 1.1
    
    # Sharp alignment yüksekse → daha güvenilir
    if sharp_alignment > 0.7:
        base_clv *= 1.05
    
    # Confidence: ne kadar veriye dayanıyor?
    data_points = (lig_info.get("n", 0) + tier_info.get("n", 0) + tip_info.get("n", 0))
    clv_conf = min(1.0, data_points / 50)
    
    # VETO: Beklenen CLV negatifse VE yeterli veri varsa → bahis yapma
    veto = base_clv < -0.005 and data_points >= 15
    
    return {
        "expected_clv": round(base_clv, 4),
        "clv_confidence": round(clv_conf, 3),
        "veto": veto,
    }


# ═══════════════════════════════════════════════════════════════
#  5. ADVANCED STAKE — 7 çarpanlı Kelly
# ═══════════════════════════════════════════════════════════════

def advanced_stake(
    base_kelly: float,
    edge: float,
    tier: str,
    veri_kaynak: str,
    lig: str,
    uncertainty: float,
    expected_clv: float,
    market_confidence: float,
    timing_score_val: float,
) -> dict:
    """
    Stake = Kelly × Tier × Veri × CLV × Lig × Edge × Uncertainty × Market × Timing × Drawdown
    
    Returns:
        {"final_stake": float, "carpanlar": dict, "aciklama": str}
    """
    try:
        from tracking.learner import _yukle
        db = _yukle()
    except Exception:
        db = {}
    
    params = db.get("ogrenme_parametreleri", {})
    lig_perf = db.get("lig_performans", {})
    clv_fb = db.get("clv_feedback", {})
    
    # 1. Tier
    tier_c = {"ELITE": 1.5, "STRONG": 1.2, "WEAK": 1.0, "NO_SHARP": 0.7}.get(tier, 0.7)
    
    # 2. Veri kalitesi
    veri_c = {"TAM": 1.0, "KARMA": 0.4, "SENTETİK": 0.0}.get(veri_kaynak, 0.5)
    
    # 3. CLV-öğrenilmiş
    clv_c = params.get("global_edge_carpan", 1.0)
    
    # 4. Lig performans
    lig_info = lig_perf.get(lig, {})
    lig_c = 1.0
    if lig_info and lig_info.get("n", 0) >= 5:
        durum = lig_info.get("durum", "NOTR")
        lig_c = 1.15 if durum == "KARLI" else (0.6 if durum == "ZARARLI" else 1.0)
    
    # 5. Edge büyüklüğü
    edge_c = 0.8 if edge > 0.15 else (1.1 if edge > 0.08 else (0.9 if edge < 0.04 else 1.0))
    
    # 6. Uncertainty (YENİ)
    unc_c = max(0.6, 1.0 - uncertainty * 2)  # CI=0.15 → 0.70
    
    # 7. Market confidence (YENİ)
    mkt_c = max(0.7, min(1.1, market_confidence))
    
    # 8. Timing (YENİ)
    tim_c = max(0.7, min(1.2, 0.8 + timing_score_val * 0.4))
    
    # 9. Expected CLV (YENİ) 
    eclv_c = 1.0
    if expected_clv > 0.02:
        eclv_c = 1.15
    elif expected_clv < -0.005:
        eclv_c = 0.5

    # 10. Drawdown
    dd_c = 1.0
    clv_n = clv_fb.get("toplam_bahis", 0)
    clv_ort = clv_fb.get("clv_ortalama", 0)
    if clv_n >= 10:
        if clv_ort < -0.03:
            dd_c = 0.5
        elif clv_ort < -0.01:
            dd_c = 0.75
        elif clv_ort > 0.02:
            dd_c = 1.1
    
    final = base_kelly * tier_c * veri_c * clv_c * lig_c * edge_c * unc_c * mkt_c * tim_c * eclv_c * dd_c
    final = round(min(0.025, max(0.002, final)), 4)
    
    parts = []
    for name, val in [("tier",tier_c),("veri",veri_c),("clv",clv_c),("lig",lig_c),
                      ("edge",edge_c),("unc",unc_c),("mkt",mkt_c),("tim",tim_c),
                      ("eclv",eclv_c),("dd",dd_c)]:
        if val != 1.0:
            parts.append(f"{name}:{val:.2f}")
    
    return {
        "final_stake": final,
        "carpanlar": {
            "tier": tier_c, "veri": veri_c, "clv": clv_c, "lig": lig_c,
            "edge": edge_c, "uncertainty": unc_c, "market": mkt_c,
            "timing": tim_c, "expected_clv": eclv_c, "drawdown": dd_c,
        },
        "aciklama": " × ".join(parts) if parts else "standart",
    }


# ═══════════════════════════════════════════════════════════════
#  6. BET FRAGMENTATION — Büyük bahisleri parçala
# ═══════════════════════════════════════════════════════════════

def fragment_bet(stake_pct: float, bankroll: float, kitap_oranlari: dict, tahmin: str) -> list:
    """
    Büyük bahisleri birden fazla kitapçıya dağıt.
    
    Returns:
        [{"book": str, "stake": float, "odds": float}, ...]
    """
    tutar = stake_pct * bankroll
    FRAGMENT_ESIK = bankroll * 0.01  # Kasa'nın %1'inden büyükse parçala
    
    if tutar <= FRAGMENT_ESIK or not kitap_oranlari:
        return [{"book": "best", "stake": round(tutar, 2), "odds": 0, "fragment": False}]
    
    idx = {"Ev Sahibi Kazanır": 0, "Beraberlik": 1, "Deplasman Kazanır": 2}.get(tahmin, 0)
    
    # En iyi 3 kitabı bul
    book_odds = {}
    for book, vals in kitap_oranlari.items():
        if isinstance(vals, (list, tuple)) and len(vals) > idx:
            book_odds[book] = vals[idx]
    
    if len(book_odds) < 2:
        return [{"book": "best", "stake": round(tutar, 2), "odds": 0, "fragment": False}]
    
    # En iyi 3 kitaba dağıt: %50 / %30 / %20
    sirali = sorted(book_odds.items(), key=lambda x: x[1], reverse=True)[:3]
    dagitim = [0.50, 0.30, 0.20]
    
    fragments = []
    for i, (book, odds) in enumerate(sirali):
        pct = dagitim[i] if i < len(dagitim) else 0
        fragments.append({
            "book": book,
            "stake": round(tutar * pct, 2),
            "odds": odds,
            "fragment": True,
        })
    
    return fragments


# ═══════════════════════════════════════════════════════════════
#  7. REAL-TIME RISK CONTROL
# ═══════════════════════════════════════════════════════════════

def risk_kontrol(bankroll: float = 1000.0) -> dict:
    """
    Günlük risk durumunu kontrol et.
    
    Returns:
        {
            "izin": bool,
            "sebep": str,
            "gunluk_bahis": int,
            "gunluk_kayip": float,
            "risk_seviye": str,   # "NORMAL" | "DİKKAT" | "DURDUR"
            "stake_carpan": float, # 1.0, 0.5, veya 0.0
        }
    """
    db = _exec_db_yukle()
    bugun = datetime.now().strftime("%Y-%m-%d")
    
    # Gün değiştiyse sıfırla
    if db.get("son_tarih", "") != bugun:
        db["gunluk_bahisler"] = []
        db["gunluk_pnl"] = 0.0
        db["son_tarih"] = bugun
        db["ardisik_kayip"] = 0
        _exec_db_kaydet(db)
    
    n_bahis = len(db.get("gunluk_bahisler", []))
    pnl = db.get("gunluk_pnl", 0.0)
    ardisik = db.get("ardisik_kayip", 0)
    
    # Stop-loss: günlük %5 kayıp
    if pnl < -(bankroll * 0.05):
        return {"izin": False, "sebep": "gunluk_stop_loss",
                "gunluk_bahis": n_bahis, "gunluk_kayip": pnl,
                "risk_seviye": "DURDUR", "stake_carpan": 0.0}
    
    # Ardışık 5+ kayıp → yarı Kelly
    if ardisik >= 5:
        return {"izin": True, "sebep": "ardisik_kayip",
                "gunluk_bahis": n_bahis, "gunluk_kayip": pnl,
                "risk_seviye": "DİKKAT", "stake_carpan": 0.5}
    
    # Günde max 10 bahis
    if n_bahis >= 10:
        return {"izin": False, "sebep": "gunluk_limit",
                "gunluk_bahis": n_bahis, "gunluk_kayip": pnl,
                "risk_seviye": "DURDUR", "stake_carpan": 0.0}
    
    # Hafif kayıp → temkinli
    if pnl < -(bankroll * 0.02):
        return {"izin": True, "sebep": "hafif_kayip",
                "gunluk_bahis": n_bahis, "gunluk_kayip": pnl,
                "risk_seviye": "DİKKAT", "stake_carpan": 0.75}
    
    return {"izin": True, "sebep": "normal",
            "gunluk_bahis": n_bahis, "gunluk_kayip": pnl,
            "risk_seviye": "NORMAL", "stake_carpan": 1.0}


def risk_bahis_kaydet(sonuc: str = "bekliyor", tutar: float = 0.0):
    """Günlük bahis kaydı."""
    db = _exec_db_yukle()
    bugun = datetime.now().strftime("%Y-%m-%d")
    if db.get("son_tarih", "") != bugun:
        db["gunluk_bahisler"] = []
        db["gunluk_pnl"] = 0.0
        db["son_tarih"] = bugun
        db["ardisik_kayip"] = 0
    
    db["gunluk_bahisler"].append({
        "zaman": datetime.now().isoformat(),
        "tutar": tutar,
        "sonuc": sonuc,
    })
    
    if sonuc == "kayip":
        db["gunluk_pnl"] -= abs(tutar)
        db["ardisik_kayip"] = db.get("ardisik_kayip", 0) + 1
    elif sonuc == "kazanc":
        db["gunluk_pnl"] += abs(tutar)
        db["ardisik_kayip"] = 0
    
    _exec_db_kaydet(db)


# ═══════════════════════════════════════════════════════════════
#  8. FULL EXECUTION PIPELINE — Tek fonksiyon
# ═══════════════════════════════════════════════════════════════

def execute_bet_analysis(bet: dict, bankroll: float = 1000.0) -> dict:
    """
    Tüm execution analizlerini tek seferde çalıştır.
    
    Args:
        bet: pipeline'dan gelen bet_obj 
             (kitap_oranlari, tahmin, edge, lig, aktif_tier, veri_kaynak, 
              p_secim, market_p, uncertainty)
    
    Returns:
        Zenginleştirilmiş bet objesi (tüm execution metrikleri eklenmiş)
    """
    kitap = bet.get("kitap_oranlari", {})
    tahmin = bet.get("tahmin", "?")
    
    # 1. Line Shopping
    ls = line_shopping(kitap, tahmin)
    
    # 2. Market Microstructure
    mm = market_microstructure(kitap, tahmin)
    
    # Model vs sharp alignment
    if mm["sharp_avg"] > 0:
        model_implied = bet.get("p_secim", 0.5)
        sharp_implied = 1.0 / mm["sharp_avg"] if mm["sharp_avg"] > 1 else 0.5
        mm["sharp_alignment"] = round(1.0 - abs(model_implied - sharp_implied) * 3, 3)
        mm["sharp_alignment"] = max(0, min(1, mm["sharp_alignment"]))
    
    # 3. Timing
    ts = timing_score(kitap, tahmin)
    
    # 4. CLV Expectation
    clv_exp = clv_beklenti(
        edge=bet.get("edge", 0),
        tier=bet.get("aktif_tier", "NO_SHARP"),
        lig=bet.get("lig", "?"),
        tahmin=tahmin,
        market_spread=ls.get("market_spread", 0),
        sharp_alignment=mm.get("sharp_alignment", 0),
    )
    
    # 5. Risk kontrolü
    risk = risk_kontrol(bankroll)
    
    # 6. Advanced Stake
    from risk.bankroll import kelly_hesapla
    k_sonuc = kelly_hesapla(bet.get("p_shrunk", bet.get("p_secim", 0.5)), 
                            ls.get("best_odds", bet.get("oran", 2.0)), bankroll)
    base_k = k_sonuc.get("kelly_fraksiyon", 0.01)
    
    stake = advanced_stake(
        base_kelly=base_k,
        edge=bet.get("edge", 0),
        tier=bet.get("aktif_tier", "NO_SHARP"),
        veri_kaynak=bet.get("veri_kaynak", "TAM"),
        lig=bet.get("lig", "?"),
        uncertainty=bet.get("uncertainty", 0.10),
        expected_clv=clv_exp.get("expected_clv", 0),
        market_confidence=mm.get("market_confidence", 0.5),
        timing_score_val=ts.get("timing_score", 0.5),
    )
    
    # Risk çarpanı uygula
    stake["final_stake"] = round(stake["final_stake"] * risk.get("stake_carpan", 1.0), 4)
    
    # 7. Fragmentation
    frags = fragment_bet(stake["final_stake"], bankroll, kitap, tahmin)
    
    # Sonucu zenginleştir
    bet["exec"] = {
        "line_shopping": ls,
        "microstructure": mm,
        "timing": ts,
        "clv_expectation": clv_exp,
        "risk": risk,
        "stake": stake,
        "fragments": frags,
        "best_odds": ls.get("best_odds", bet.get("oran", 0)),
        "best_book": ls.get("best_book", "?"),
    }
    
    # Ana metrikleri üst seviyeye ekle
    bet["best_odds"] = ls.get("best_odds", bet.get("oran", 0))
    bet["best_book"] = ls.get("best_book", "?")
    bet["timing_score"] = ts.get("timing_score", 0.5)
    bet["entry_signal"] = ts.get("entry_signal", "NORMAL")
    bet["expected_clv"] = clv_exp.get("expected_clv", 0)
    bet["clv_veto"] = clv_exp.get("veto", False)
    bet["market_conf"] = mm.get("market_confidence", 0.5)
    bet["market_spread"] = ls.get("market_spread", 0)
    bet["size"] = stake["final_stake"]
    bet["stake_aciklama"] = stake["aciklama"]
    bet["risk_seviye"] = risk.get("risk_seviye", "NORMAL")
    
    return bet
