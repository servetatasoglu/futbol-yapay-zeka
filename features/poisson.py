# analysis/poisson_model.py
"""
Poisson Tahmin Modeli — xG + Lig Bazında Dixon-Coles rho
─────────────────────────────────────────────────────────
DEĞİŞİKLİKLER:
  • dixon_coles_duzelt() artık lig_kodu alıyor → LIG_RHO dict'ten
    lig'e özel rho kullanıyor (sabit -0.10 yerine)
  • beklenen_goller() artık lig_kodu bazında xG karışım oranı kullanıyor
    (LIG_XG_KARISIM — PL için %70, ELC için %40)
  • Her iki değişiklik geriye dönük uyumlu:
    lig_kodu bilinmiyorsa varsayılan değerlere düşer
"""

import math
from config.settings import (
    EV_SAHIBI_AVANTAJI, REGRESS_FAKTOR,
    LIG_RHO, LIG_RHO_VARSAYILAN,
    LIG_XG_KARISIM, LIG_XG_KARISIM_VARSAYILAN,
)

# Geriye dönük uyumluluk için — dışarıdan import edenler bozulmasın
XG_KARISIM_ORANI = LIG_XG_KARISIM_VARSAYILAN

_DINAMIK_RHO_CACHE = {}

def guncelle_dinamik_rho(ham_veri: dict):
    from features.dixon_coles import dinamik_rho_hesapla
    for lig_kodu, maclar in ham_veri.items():
        _DINAMIK_RHO_CACHE[lig_kodu] = dinamik_rho_hesapla(lig_kodu, maclar)
    print("  ✅ Dixon-Coles dinamik rho parametreleri hesaplandı ve cache'lendi.")


def poisson_olasilik(lam: float, k: int) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k * math.exp(-lam)) / math.factorial(k)


def dixon_coles_duzelt(p, lam_ev, lam_dep, ev_gol, dep_gol, rho=None, lig_kodu: str = ""):
    """
    Dixon-Coles düzeltmesi — düşük skorlu maçlarda Poisson bağımsızlık
    varsayımını kırarak daha gerçekçi olasılıklar üretir.

    DEĞİŞİKLİK: rho artık lig bazında settings.py'den okunuyor.
      - rho parametresi hâlâ dışarıdan verilebilir (geriye dönük uyumluluk)
      - rho=None ise lig_kodu'na göre LIG_RHO'dan otomatik seçilir
    """
    if rho is None:
        if lig_kodu in _DINAMIK_RHO_CACHE:
            rho = _DINAMIK_RHO_CACHE[lig_kodu]
        else:
            rho = LIG_RHO.get(lig_kodu, LIG_RHO_VARSAYILAN)

    if ev_gol == 0 and dep_gol == 0:
        tau = 1 - lam_ev * lam_dep * rho
    elif ev_gol == 1 and dep_gol == 0:
        tau = 1 + lam_dep * rho
    elif ev_gol == 0 and dep_gol == 1:
        tau = 1 + lam_ev * rho
    elif ev_gol == 1 and dep_gol == 1:
        tau = 1 - rho
    else:
        tau = 1.0
    return max(p * tau, 0.0)


def _regress(deger: float, lig_ort: float) -> float:
    return deger * (1 - REGRESS_FAKTOR) + lig_ort * REGRESS_FAKTOR


def beklenen_goller(ev_istatistik, dep_istatistik, lig_ortalamasi, lig_kodu,
                    ev_xg: dict = None, dep_xg: dict = None):
    """
    xG verisi varsa ham gol + xG karışımı kullan.
    xG yoksa eski yöntem (geriye dönük uyumlu).

    DEĞİŞİKLİK: xG karışım oranı artık lig'e özel (LIG_XG_KARISIM).
      PL: %70 xG, ELC: %40 xG
    """
    lig_ort = lig_ortalamasi.get(lig_kodu, {"hucum": 1.35})
    lig_gol = max(lig_ort["hucum"], 0.1)

    ev_huc  = _regress(ev_istatistik.get("hucum_genel",   lig_gol), lig_gol)
    ev_sav  = _regress(ev_istatistik.get("savunma_genel", lig_gol), lig_gol)
    dep_huc = _regress(dep_istatistik.get("hucum_genel",  lig_gol), lig_gol)
    dep_sav = _regress(dep_istatistik.get("savunma_genel",lig_gol), lig_gol)

    # xG entegrasyonu: xG varsa ham gol ile karıştır
    if ev_xg and dep_xg:
        # Lig bazında xG karışım oranı
        a = LIG_XG_KARISIM.get(lig_kodu, LIG_XG_KARISIM_VARSAYILAN)

        ev_xg_huc  = ev_xg.get("xg",  ev_huc)
        ev_xg_sav  = ev_xg.get("xga", ev_sav)
        dep_xg_huc = dep_xg.get("xg",  dep_huc)
        dep_xg_sav = dep_xg.get("xga", dep_sav)

        # Regress xG değerlerini de
        ev_xg_huc  = _regress(ev_xg_huc,  lig_gol)
        ev_xg_sav  = _regress(ev_xg_sav,  lig_gol)
        dep_xg_huc = _regress(dep_xg_huc, lig_gol)
        dep_xg_sav = _regress(dep_xg_sav, lig_gol)

        # Karışım: a * xG + (1-a) * ham gol
        ev_huc  = a * ev_xg_huc  + (1 - a) * ev_huc
        ev_sav  = a * ev_xg_sav  + (1 - a) * ev_sav
        dep_huc = a * dep_xg_huc + (1 - a) * dep_huc
        dep_sav = a * dep_xg_sav + (1 - a) * dep_sav

    atk_ev  = ev_huc  / lig_gol
    atk_dep = dep_huc / lig_gol
    def_ev  = ev_sav  / lig_gol
    def_dep = dep_sav / lig_gol

    lam_ev  = max(0.5, min(atk_ev  * def_dep * lig_gol * EV_SAHIBI_AVANTAJI, 3.0))
    lam_dep = max(0.5, min(atk_dep * def_ev  * lig_gol,                       3.0))

    return lam_ev, lam_dep


def poisson_tahmin(ev_istatistik, dep_istatistik, lig_ortalamasi, lig_kodu,
                   ev_xg: dict = None, dep_xg: dict = None):
    lam_ev, lam_dep = beklenen_goller(
        ev_istatistik, dep_istatistik, lig_ortalamasi, lig_kodu,
        ev_xg=ev_xg, dep_xg=dep_xg
    )

    ev_kazan = beraberlik = dep_kazan = bts_p = 0.0
    over15_p = over25_p = over35_p = 0.0
    MAX_GOL = 9
    skor_matrisi = {}

    for hg in range(MAX_GOL + 1):
        for dg in range(MAX_GOL + 1):
            p = poisson_olasilik(lam_ev, hg) * poisson_olasilik(lam_dep, dg)
            # DEĞİŞİKLİK: lig_kodu parametresi eklendi → lig bazında rho
            p = dixon_coles_duzelt(p, lam_ev, lam_dep, hg, dg, lig_kodu=lig_kodu)
            skor_matrisi[(hg, dg)] = p

            if hg > dg:    ev_kazan   += p
            elif hg == dg: beraberlik += p
            else:          dep_kazan  += p

            if hg >= 1 and dg >= 1: bts_p    += p
            if hg + dg > 1:         over15_p += p
            if hg + dg > 2:         over25_p += p
            if hg + dg > 3:         over35_p += p

    toplam = ev_kazan + beraberlik + dep_kazan
    if toplam > 0:
        ev_kazan   /= toplam
        beraberlik /= toplam
        dep_kazan  /= toplam
        bts_p      /= toplam
        over15_p   /= toplam
        over25_p   /= toplam
        over35_p   /= toplam

    sirali_skorlar   = sorted(skor_matrisi.items(), key=lambda x: x[1], reverse=True)
    en_olasi_skorlar = [
        {"skor": f"{hg}-{dg}", "olasilik": round(p / (toplam if toplam > 0 else 1.0), 4)}
        for (hg, dg), p in sirali_skorlar[:5]
    ]

    lam_iy_ev  = round(lam_ev  * 0.42, 3)
    lam_iy_dep = round(lam_dep * 0.42, 3)

    iy_ev_kazan = iy_ber = iy_dep_kazan = 0.0
    for hg in range(5):
        for dg in range(5):
            p = poisson_olasilik(lam_iy_ev, hg) * poisson_olasilik(lam_iy_dep, dg)
            if hg > dg:    iy_ev_kazan  += p
            elif hg == dg: iy_ber       += p
            else:          iy_dep_kazan += p

    iy_toplam = iy_ev_kazan + iy_ber + iy_dep_kazan
    if iy_toplam > 0:
        iy_ev_kazan  /= iy_toplam
        iy_ber       /= iy_toplam
        iy_dep_kazan /= iy_toplam

    return {
        "home_win":  round(ev_kazan,   4),
        "draw":      round(beraberlik, 4),
        "away_win":  round(dep_kazan,  4),
        "lam_ev":    round(lam_ev,     3),
        "lam_dep":   round(lam_dep,    3),
        "bts_p":     round(bts_p,      4),
        "over15_p":  round(over15_p,   4),
        "over25_p":  round(over25_p,   4),
        "over35_p":  round(over35_p,   4),
        "en_olasi_skorlar": en_olasi_skorlar,
        "iy_ev_p":   round(iy_ev_kazan,  3),
        "iy_ber_p":  round(iy_ber,       3),
        "iy_dep_p":  round(iy_dep_kazan, 3),
        "lam_iy_ev": lam_iy_ev,
        "lam_iy_dep": lam_iy_dep,
        "xg_kullanildi": ev_xg is not None and dep_xg is not None,
        "lig_rho": LIG_RHO.get(lig_kodu, LIG_RHO_VARSAYILAN),   # debug için
    }