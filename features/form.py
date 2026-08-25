# analysis/form_analysis.py
"""
Form & Momentum Motoru — FAZ 3
════════════════════════════════════════════════════════════════
Faz 2'deki tek satırlık form fonksiyonunu tamamen yeniden yazıyoruz.

Ne hesaplar:
  1. Ağırlıklı form skoru       — son maçlar daha önemli (exponential decay)
  2. Momentum                   — form trendi: iyileşiyor mu, kötüleşiyor mu?
  3. Gol form lambdası          — son N maçtaki ortalama gol/yenilen (Poisson için)
  4. Ev/Dep ayrı form           — ev formu ile deplasman formu farklı olabilir
  5. Form güven skoru           — az maçta form güvenilmez, bunu işaretle

Teorik altyapı:
  • Exponential decay: son maç ağırlığı=1.0, 1 önceki=0.85, 2 önceki=0.72...
  • Momentum: son 3 maç formu vs önceki 3 maç farkı
  • Lambda düzeltici: form'u Poisson lambda'sına [LAMBDA_MIN, LAMBDA_MAX] içinde çarp
"""

import math
from typing import Literal

# ─── Sabitler ─────────────────────────────────────────────────
DECAY_RATE       = 0.85
MIN_FORM_MAC     = 4
LAMBDA_MIN       = 0.75
LAMBDA_MAX       = 1.30
MOMENTUM_PENCERE = 3


def _mac_sonucu(attik: int, yedik: int) -> float:
    if attik > yedik:  return 1.0
    if attik == yedik: return 0.5
    return 0.0


def _agirlikli_ortalama(degerler: list, decay: float = DECAY_RATE) -> float:
    if not degerler:
        return 0.0
    agirliklar = [decay ** (len(degerler) - 1 - i) for i in range(len(degerler))]
    return sum(d * a for d, a in zip(degerler, agirliklar)) / sum(agirliklar)


def _momentum_hesapla(sonuclar: list) -> float:
    if len(sonuclar) < MOMENTUM_PENCERE * 2:
        return 0.0
    son    = sonuclar[-MOMENTUM_PENCERE:]
    onceki = sonuclar[-MOMENTUM_PENCERE * 2: -MOMENTUM_PENCERE]
    return sum(son) / len(son) - sum(onceki) / len(onceki)


def _lambda_duzeltici(gol_listesi: list, yenilen_listesi: list,
                      lig_hucum_ort: float = 1.35):
    if not gol_listesi:
        return 1.0, 1.0
    ag_gol     = _agirlikli_ortalama([float(g) for g in gol_listesi])
    ag_yenilen = _agirlikli_ortalama([float(g) for g in yenilen_listesi])
    hucum_d   = max(LAMBDA_MIN, min(ag_gol    / max(lig_hucum_ort, 0.5), LAMBDA_MAX))
    savunma_d = max(LAMBDA_MIN, min(ag_yenilen / max(lig_hucum_ort, 0.5), LAMBDA_MAX))
    return round(hucum_d, 4), round(savunma_d, 4)


def form_hesapla(mac_listesi, takim_adi: str,
                 konum: str = "genel",
                 lig_hucum_ort: float = 1.35,
                 son_n: int = 8) -> dict:
    """
    Takımın son maçlarından form + momentum + lambda düzeltici hesaplar.

    Returns:
        skor, momentum, hucum_duzeltici, savunma_duzeltici,
        mac_sayisi, guven (0-1), ev_skor, dep_skor, son_5_seri
    """
    takim_maclari = []

    kaynak = mac_listesi.items() if isinstance(mac_listesi, dict) else [("?", mac_listesi)]
    for lig_kodu, maclar in kaynak:
        for mac in maclar:
            try:
                ev   = mac["homeTeam"]["name"]
                dep  = mac["awayTeam"]["name"]
                ev_g = mac["score"]["fullTime"]["home"]
                dp_g = mac["score"]["fullTime"]["away"]
            except (KeyError, TypeError):
                continue
            if ev_g is None or dp_g is None:
                continue
            ev_g, dp_g = int(ev_g), int(dp_g)

            if takim_adi == ev and konum in ("ev", "genel"):
                takim_maclari.append({"tarih": mac.get("utcDate",""), "attik": ev_g, "yedik": dp_g, "konum": "ev"})
            elif takim_adi == dep and konum in ("dep", "genel"):
                takim_maclari.append({"tarih": mac.get("utcDate",""), "attik": dp_g, "yedik": ev_g, "konum": "dep"})

    takim_maclari.sort(key=lambda m: m["tarih"])
    son_maclar = takim_maclari[-son_n:]

    if not son_maclar:
        return _notr_form()

    sonuclar        = [_mac_sonucu(m["attik"], m["yedik"]) for m in son_maclar]
    gol_listesi     = [m["attik"] for m in son_maclar]
    yenilen_listesi = [m["yedik"] for m in son_maclar]
    ev_s  = [_mac_sonucu(m["attik"], m["yedik"]) for m in son_maclar if m["konum"] == "ev"]
    dep_s = [_mac_sonucu(m["attik"], m["yedik"]) for m in son_maclar if m["konum"] == "dep"]

    form_skoru = _agirlikli_ortalama(sonuclar)
    momentum   = _momentum_hesapla(sonuclar)
    hucum_d, sav_d = _lambda_duzeltici(gol_listesi, yenilen_listesi, lig_hucum_ort)
    guven      = min(1.0, len(son_maclar) / MIN_FORM_MAC)

    son5 = []
    for m in son_maclar[-5:]:
        s = _mac_sonucu(m["attik"], m["yedik"])
        son5.append("G" if s == 1.0 else ("B" if s == 0.5 else "M"))

    return {
        "skor":              round(form_skoru, 4),
        "momentum":          round(momentum,   4),
        "hucum_duzeltici":   hucum_d,
        "savunma_duzeltici": sav_d,
        "mac_sayisi":        len(son_maclar),
        "guven":             round(guven, 3),
        "ev_skor":           round(_agirlikli_ortalama(ev_s),  4) if ev_s  else 0.5,
        "dep_skor":          round(_agirlikli_ortalama(dep_s), 4) if dep_s else 0.5,
        "son_5_seri":        "".join(son5),
    }


def _notr_form() -> dict:
    return {"skor": 0.5, "momentum": 0.0, "hucum_duzeltici": 1.0,
            "savunma_duzeltici": 1.0, "mac_sayisi": 0, "guven": 0.0,
            "ev_skor": 0.5, "dep_skor": 0.5, "son_5_seri": "?????"}


def form_lambda_uygula(lam_ev: float, lam_dep: float,
                       ev_form: dict, dep_form: dict,
                       form_etkisi: float = 0.20):
    """
    Form düzelticilerini Poisson lambda değerlerine uygular.
    form_etkisi=0.20 → formun lambdaya max %20 etkisi.
    Güven düşükse etki otomatik azalır.
    """
    ev_etki  = form_etkisi * ev_form.get("guven",  0.0)
    dep_etki = form_etkisi * dep_form.get("guven", 0.0)

    ev_hucum_d  = ev_form.get("hucum_duzeltici",    1.0)
    dep_sav_d   = dep_form.get("savunma_duzeltici", 1.0)
    dep_hucum_d = dep_form.get("hucum_duzeltici",   1.0)
    ev_sav_d    = ev_form.get("savunma_duzeltici",  1.0)

    yeni_lam_ev  = lam_ev  * (1 - ev_etki)  + lam_ev  * ev_hucum_d  * dep_sav_d  * ev_etki
    yeni_lam_dep = lam_dep * (1 - dep_etki) + lam_dep * dep_hucum_d * ev_sav_d   * dep_etki

    return round(max(0.4, min(yeni_lam_ev, 3.2)), 3), round(max(0.4, min(yeni_lam_dep, 3.2)), 3)