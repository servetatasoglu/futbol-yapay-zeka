# analysis/adaptive_kelly.py
"""
Adaptive Kelly Criterion — Risk Engine v2
══════════════════════════════════════════════════════════════════

Klasik Kelly = f* = (b*p - q) / b

Sorun: Model olasılıkları %100 doğru değil → "Edge overestimation"
Çözüm: Güven aralığına + drawdown'a + CLV geçmişine göre dinamik fraksiyon.

Fraksiyon Mantığı:
  - Paper trading / yeni model  → %5  (1/20-Kelly) — kanıtlanana kadar
  - CLV pozitif + 50+ bah.      → %12 (1/8-Kelly)  — güven artıyor
  - CLV güçlü pozitif + Pinnacle → %20 (1/5-Kelly) — kanıtlanmış edge
  - Drawdown > %20              → Yarıya indir
  - Drawdown > %30              → Stop

Referans: Ed Thorp (Beat the Dealer), Joseph Buchdahl (12 Yards Away)
"""

import os
import json
import math
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ADAPTIVE_STATE_PATH = os.path.join(DATA_DIR, "adaptive_kelly_state.json")


# ════════════════════════════════════════════════════════════════
#  Durum Dosyası
# ════════════════════════════════════════════════════════════════

def _state_yukle() -> dict:
    if not os.path.exists(ADAPTIVE_STATE_PATH):
        return {
            "faz":            "paper_trading",    # paper_trading / gelisme / kanit
            "toplam_bahis":   0,
            "kazanan":        0,
            "roi_serisi":     [],                  # Son 50 bahisin ROI'si
            "max_banka":      0.0,
            "mevcut_banka":   0.0,
            "baslangic_banka":0.0,
        }
    try:
        with open(ADAPTIVE_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _state_kaydet(state: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(ADAPTIVE_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════
#  Dinamik Fraksiyon Hesabı
# ════════════════════════════════════════════════════════════════

def dinamik_fraksiyon_hesapla(
    clv_ort_pct: float = 0.0,    # Ortalama CLV yüzdesi
    toplam_bahis: int  = 0,      # Geçmişteki toplam bahis sayısı
    drawdown_pct: float = 0.0,   # Mevcut drawdown (%)
    pinnacle_var: bool = False,  # Pinnacle referanslı mı?
) -> dict:
    """
    Duruma göre Kelly fraksiyonu hesaplar.
    
    Dönüş: {"fraksiyon": float, "faz": str, "aciklama": str}
    """
    # AUDIT FIX: Hard Stop-Loss based on real Pinnacle ROI
    try:
        rapor_path = os.path.join(DATA_DIR, "gercek_backtest_raporu.json")
        if os.path.exists(rapor_path):
            with open(rapor_path, "r", encoding="utf-8") as f:
                b_rapor = json.load(f)
                p_roi = b_rapor.get("pinnacle_roi", 0.0)
                p_n = b_rapor.get("gercek_pinnacle_n", 0)
                if p_n >= 100 and p_roi < -0.025:
                    raise RuntimeError(f"HARD STOP-LOSS REACHED: Pinnacle ROI = {p_roi*100:.2f}% over {p_n} bets. Execution halted.")
    except json.JSONDecodeError:
        pass

    # ── Başlangıç: Kanıtlama fazı ──────────────────────────────
    if toplam_bahis < 50 or clv_ort_pct < -2.0:
        fraksiyon = 0.0025  # AUDIT FIX: 0.25% Flat Stake
        faz = "paper_trading"
        aciklama = f"Kanıtlama fazı ({toplam_bahis} bahis) — 0.25% Flat Stake"

    # ── Gelişme fazı: CLV +1% ile +2% arası ───────────────────
    elif clv_ort_pct < 2.0 and toplam_bahis < 150:
        fraksiyon = 0.0025  # AUDIT FIX: 0.25% Flat Stake
        faz = "gelisme"
        aciklama = f"Gelişme fazı (CLV: %{clv_ort_pct:+.1f}) — 0.25% Flat Stake"

    # ── Kanıtlanmış: CLV +2% üzeri, 100+ bahis ───────────────
    elif clv_ort_pct >= 2.0 and toplam_bahis >= 100:
        if pinnacle_var and clv_ort_pct >= 5.0:
            fraksiyon = 0.20  # 1/5 Kelly — güçlü kanıt
            faz = "kanit_guclu"
            aciklama = f"Güçlü CLV + Pinnacle (CLV: %{clv_ort_pct:+.1f}) — 1/5 Kelly"
        else:
            fraksiyon = 0.12  # 1/8 Kelly
            faz = "kanit"
            aciklama = f"Kanıtlanmış CLV (CLV: %{clv_ort_pct:+.1f}) — 1/8 Kelly"

    else:
        fraksiyon = 0.0025
        faz = "transition"
        aciklama = f"Geçiş fazı — 0.25% Flat Stake"

    # ── Drawdown Ayarı ─────────────────────────────────────────
    orijinal = fraksiyon
    if drawdown_pct >= 30:
        return {
            "fraksiyon": 0.0,
            "faz":        "stop_loss",
            "aciklama":   f"⛔ STOP — Drawdown %{drawdown_pct:.1f} — Bahis durdu",
        }
    elif drawdown_pct >= 20:
        fraksiyon *= 0.5
        aciklama  += f" | Drawdown %{drawdown_pct:.1f} → fraksiyon yarıya indirildi"
    elif drawdown_pct >= 10:
        fraksiyon *= 0.75
        aciklama  += f" | Drawdown %{drawdown_pct:.1f} → fraksiyon %25 azaltıldı"

    return {
        "fraksiyon":          round(fraksiyon, 4),
        "faz":                faz,
        "orijinal_fraksiyon": round(orijinal, 4),
        "aciklama":           aciklama,
    }


# ════════════════════════════════════════════════════════════════
#  Ana Bahis Hesabı
# ════════════════════════════════════════════════════════════════

def adaptive_kelly_hesapla(
    olasilik:   float,
    oran:       float,
    banka:      float,
    clv_ort_pct: float = 0.0,
    toplam_bahis: int  = 0,
    drawdown_pct: float = 0.0,
    pinnacle_var: bool = False,
    model_guveni: float = 1.0,    # Model güven katsayısı (0.5-1.5)
) -> dict:
    """
    Adaptive Kelly ile bahis miktarı hesaplar.
    
    Parametreler:
      olasilik     : Model tahmin olasılığı
      oran         : Bahis oranı (decimal)
      banka        : Mevcut kasa
      clv_ort_pct  : Geçmiş CLV ortalaması (%)
      toplam_bahis : Geçmişte yapılan toplam bahis sayısı
      drawdown_pct : Başlangıçtan beri düşüş (%)
      pinnacle_var : Pinnacle oranı referans alındı mı?
      model_guveni : Model doğruluk katsayısı (backtest/gerçek ROI oranı)
    """
    if olasilik <= 0 or olasilik >= 1 or oran <= 1 or banka <= 0:
        return {"bahis_miktar": 0, "kelly_tam": 0, "aciklama": "Geçersiz parametre"}

    # ── Kelly hesabı ────────────────────────────────────────────
    b = oran - 1.0
    p = olasilik * model_guveni  # Model güvensizliği için düzelt
    p = max(0.01, min(0.99, p))
    q = 1.0 - p

    kelly_tam = (b * p - q) / b

    if kelly_tam <= 0:
        return {
            "bahis_miktar": 0,
            "kelly_tam":    round(kelly_tam, 4),
            "aciklama":     "Negatif Kelly — edge yok",
        }

    # ── Dinamik fraksiyon ──────────────────────────────────────
    fraksiyon_bilgi = dinamik_fraksiyon_hesapla(
        clv_ort_pct=clv_ort_pct,
        toplam_bahis=toplam_bahis,
        drawdown_pct=drawdown_pct,
        pinnacle_var=pinnacle_var,
    )

    if fraksiyon_bilgi["faz"] == "stop_loss":
        return {
            "bahis_miktar": 0,
            "kelly_tam":    round(kelly_tam, 4),
            "faz":          "stop_loss",
            "aciklama":     fraksiyon_bilgi["aciklama"],
        }

    fraksiyon     = fraksiyon_bilgi["fraksiyon"]
    kelly_fraks   = kelly_tam * fraksiyon

    # ── Sınır kontrolleri ──────────────────────────────────────
    MAX_BET = 0.02   # Max %2 bankroll (güvenlik)
    MIN_BET = 0.005  # Min %0.5 bankroll
    kelly_fraks = max(MIN_BET, min(MAX_BET, kelly_fraks))

    bahis_miktar = round(banka * kelly_fraks, 2)

    # Minimum TL koruması
    if bahis_miktar < 50 and banka >= 50:
        bahis_miktar = 50.0

    # EV onayı
    net_kazanc = oran - 1
    ev = olasilik * net_kazanc - (1 - olasilik)

    return {
        "bahis_miktar":    bahis_miktar,
        "kelly_tam":       round(kelly_tam, 4),
        "kelly_fraksiyon": round(kelly_fraks, 4),
        "kelly_yuzde":     round(kelly_fraks * 100, 2),
        "faz":             fraksiyon_bilgi["faz"],
        "ev":              round(ev, 4),
        "risk_seviye":     "düşük" if kelly_fraks < 0.01 else ("orta" if kelly_fraks < 0.015 else "yüksek"),
        "aciklama":        fraksiyon_bilgi["aciklama"],
    }


# ════════════════════════════════════════════════════════════════
#  Performans Güncelleme
# ════════════════════════════════════════════════════════════════

def performans_guncelle(kazandi: bool, roi: float, banka: float):
    """Her bahis sonucundan sonra çağır — faz kararlarını günceller."""
    state = _state_yukle()

    state["toplam_bahis"] = state.get("toplam_bahis", 0) + 1
    if kazandi:
        state["kazanan"] = state.get("kazanan", 0) + 1

    roi_serisi = state.get("roi_serisi", [])
    roi_serisi.append(round(roi, 4))
    if len(roi_serisi) > 100:
        roi_serisi = roi_serisi[-100:]
    state["roi_serisi"] = roi_serisi

    if banka > state.get("max_banka", 0):
        state["max_banka"] = banka
    state["mevcut_banka"] = banka

    _state_kaydet(state)


def mevcut_faz() -> str:
    """Sistemin mevcut Kelly fazını döndür."""
    state = _state_yukle()
    return state.get("faz", "paper_trading")


def faz_raporu() -> str:
    """Adaptive Kelly faz raporu."""
    state = _state_yukle()
    tb    = state.get("toplam_bahis", 0)
    kaz   = state.get("kazanan", 0)
    acc   = round(kaz / max(tb, 1) * 100, 1)
    roi_s = state.get("roi_serisi", [])
    roi   = round(sum(roi_s) / max(len(roi_s), 1) * 100, 2) if roi_s else 0

    SEP = "═" * 50
    return (
        f"\n{SEP}\n"
        f"  📊  ADAPTIVE KELLY DURUMU\n"
        f"{SEP}\n"
        f"  Toplam bahis  : {tb}\n"
        f"  Accuracy      : %{acc:.1f}\n"
        f"  ROI (son {len(roi_s)}) : %{roi:+.2f}\n"
        f"  Faz           : {state.get('faz', 'bilinmiyor')}\n"
        f"{SEP}"
    )
