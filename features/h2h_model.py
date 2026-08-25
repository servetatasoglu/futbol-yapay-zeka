# analysis/h2h_model.py
"""
H2H (Head-to-Head) Modeli + Beraberlik Düzelticisi — FAZ 3
════════════════════════════════════════════════════════════
Faz 2'de h2h_faktor() hesaplanıp lambda'ya uygulanmıyordu.
Bu dosya h2h'yi hem Poisson'a hem de beraberlik olasılığına entegre eder.
"""

import math
from config.settings import ELO_EV_AVANTAJI

# ─── Sabitler ─────────────────────────────────────────────────
H2H_MIN_MAC        = 2
H2H_MAX_MAC        = 6
H2H_DECAY          = 0.80
BER_TEMEL          = 0.230
BER_DUSUK_GOL_ESIK = 2.2


def h2h_analiz(istatistikler: dict, ev_takim: str, dep_takim: str,
               lig_hucum_ort: float = 1.35) -> dict:
    ev_s = istatistikler.get(ev_takim, {})
    h2h  = ev_s.get("h2h", {}).get(dep_takim)

    if not h2h or h2h.get("mac", 0) < H2H_MIN_MAC:
        return _notr_h2h()

    mac         = min(h2h["mac"], H2H_MAX_MAC)
    ev_gol      = h2h["ev_gol"]
    dep_gol     = h2h["dep_gol"]
    ev_gol_ort  = ev_gol  / h2h["mac"]
    dep_gol_ort = dep_gol / h2h["mac"]

    ev_lambda_d  = max(0.80, min(ev_gol_ort  / max(lig_hucum_ort, 0.5), 1.25))
    dep_lambda_d = max(0.80, min(dep_gol_ort / max(lig_hucum_ort, 0.5), 1.25))

    toplam_gol_ort = ev_gol_ort + dep_gol_ort
    ber_egilim     = max(-0.05, min(0.05, (2.5 - toplam_gol_ort) * 0.02))

    ev_kaz_orani  = ev_gol  / max(ev_gol + dep_gol, 1)
    dep_kaz_orani = dep_gol / max(ev_gol + dep_gol, 1)
    ber_orani     = max(0.0, 1.0 - ev_kaz_orani - dep_kaz_orani + 0.25)
    guven         = min(1.0, mac / H2H_MAX_MAC)

    return {
        "ev_lambda_d":       round(ev_lambda_d,  4),
        "dep_lambda_d":      round(dep_lambda_d, 4),
        "ber_egilim":        round(ber_egilim,   4),
        "mac_sayisi":        mac,
        "guven":             round(guven, 3),
        "ev_gol_ort":        round(ev_gol_ort,   3),
        "dep_gol_ort":       round(dep_gol_ort,  3),
        "ev_kazanma_orani":  round(ev_kaz_orani, 3),
        "ber_orani":         round(ber_orani,     3),
        "dep_kazanma_orani": round(dep_kaz_orani, 3),
    }


def _notr_h2h() -> dict:
    return {
        "ev_lambda_d": 1.0, "dep_lambda_d": 1.0, "ber_egilim": 0.0,
        "mac_sayisi": 0, "guven": 0.0, "ev_gol_ort": 0.0, "dep_gol_ort": 0.0,
        "ev_kazanma_orani": 0.5, "ber_orani": 0.25, "dep_kazanma_orani": 0.5,
    }


def h2h_lambda_uygula(lam_ev: float, lam_dep: float, h2h: dict,
                       h2h_etkisi: float = 0.15) -> tuple:
    etki     = h2h_etkisi * h2h.get("guven", 0.0)
    yeni_ev  = lam_ev  * (1 - etki) + lam_ev  * h2h["ev_lambda_d"]  * etki
    yeni_dep = lam_dep * (1 - etki) + lam_dep * h2h["dep_lambda_d"] * etki
    return round(max(0.4, min(yeni_ev, 3.2)), 3), round(max(0.4, min(yeni_dep, 3.2)), 3)


def beraberlik_kalibrasyon(
    ev_p: float, ber_p: float, dep_p: float,
    lam_ev: float, lam_dep: float,
    ev_elo: float, dep_elo: float,
    h2h: dict = None,
    ber_agirlik: float = 0.30,
) -> dict:
    """
    Beraberlik Kalibrasyonu — Düzeltilmiş v2
    ═══════════════════════════════════════════
    Değişiklikler (KRİTİK DÜZELTMESİ):
      - Dixon-Coles rho: toplam gol < 2.2 iken beraberlik güçlü artış
      - Logistic blend: model ber_p ile kalibrasyon arası ağırlıklı blend
      - draw_ci: her zaman dolu döner (güven aralığı)
      - Hard cap: beraberlik asla > 0.40 veya < 0.15 olamaz (absürd öneriler engeli)
      - ELO dengesi: takımlar çok eşit → beraberlik +3%
    """
    if h2h is None:
        h2h = _notr_h2h()

    toplam_lam = lam_ev + lam_dep

    # ── Dixon-Coles rho düzeltmesi: düşük gol beklentisi → beraberlik artar ──
    # Orijinal Dixon-Coles: rho negatif (ev-dep korelasyonu)
    # Gol ortalaması < 2.0 ise beraberlik ihtimali gerçekten yükselir
    if toplam_lam < 1.8:
        dusuk_gol_boost = 0.02   # Çok düşük gol maçı (eski: 0.04 — aşırı şişiriyordu)
    elif toplam_lam < 2.2:
        dusuk_gol_boost = (BER_DUSUK_GOL_ESIK - toplam_lam) * 0.015  # eski: 0.025
    else:
        dusuk_gol_boost = 0.0

    # ── ELO dengesi: takımlar eşit → beraberlik olası ──────────────────────
    elo_fark        = abs((ev_elo + ELO_EV_AVANTAJI) - dep_elo)
    elo_denge_boost = max(0.0, (150 - elo_fark) / 150) * 0.015  # eski: 0.03 — draw'u aşırı şişiriyordu

    # ── H2H beraberlik eğilimi ──────────────────────────────────────────────
    h2h_boost = h2h.get("ber_egilim", 0.0) * h2h.get("guven", 0.0)

    # ── Hedef kalibrasyon değeri (lig bazı %25.5 temel) ────────────────────
    ber_hedef = BER_TEMEL + dusuk_gol_boost + elo_denge_boost + h2h_boost
    ber_hedef = max(0.18, min(ber_hedef, 0.32))  # eski: 0.38 → 0.32 hard cap

    # ── Logistic blend: model p ile hedef arasında ağırlıklı blend ─────────
    # ber_agirlik=0.30 → %70 model, %30 kalibrasyon hedefi
    yeni_ber = ber_p * (1.0 - ber_agirlik) + ber_hedef * ber_agirlik

    # ── Beraberlik hard cap: absürd değerleri engelle ──────────────────────
    # Beraberlik ASLA %15 altında veya %40 üstünde olamaz
    yeni_ber = max(0.15, min(yeni_ber, 0.32))  # eski: 0.40 → 0.32 — piyasa gerçekliği

    kalan = 1.0 - yeni_ber
    oran  = ev_p / (ev_p + dep_p) if (ev_p + dep_p) > 0 else 0.5

    # ── draw_ci: güven aralığı — artık HER ZAMAN dolu döner ───────────────
    # Genişlik: veri güvenine göre (h2h güveni yoksa geniş aralık)
    h2h_guven   = h2h.get("guven", 0.0)
    ci_genislik = max(0.04, 0.12 - h2h_guven * 0.06)  # 0.04–0.12 arası
    draw_ci     = (
        round(max(0.10, yeni_ber - ci_genislik / 2), 3),
        round(min(0.45, yeni_ber + ci_genislik / 2), 3),
    )

    return {
        "home_win":      round(kalan * oran,        4),
        "draw":          round(yeni_ber,            4),
        "away_win":      round(kalan * (1 - oran),  4),
        "draw_ci":       draw_ci,
        "ber_boost_gol": round(dusuk_gol_boost,     4),
        "ber_boost_elo": round(elo_denge_boost,     4),
        "ber_boost_h2h": round(h2h_boost,           4),
        "ber_hedef":     round(ber_hedef,            4),
    }