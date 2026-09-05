# analysis/takim_istatistik.py
"""
Takım İstatistikleri — ÇOK SEZONLU VERSİYON
════════════════════════════════════════════════════════════════
DEĞİŞİKLİKLER:
  • Poisson/ELO için tüm sezonlar kullanılır — ama eski sezonlar
    daha az ağırlıklı (sezon ağırlığı: aktif=1.0, geçen=0.6, iki önce=0.35)
  • Puan tablosu / lig sıralaması SADECE aktif sezon maçlarından hesaplanır
  • Aktif sezon tespiti: utcDate'e göre 2025-07-01 sonrası = aktif sezon
"""

import numpy as np
from collections import defaultdict
from data.matches import veri_yukle
from config.settings import SON_MAC_SAYISI
from features.feature_engine import attack_strength, defense_strength, goal_difference

# Sezon başlangıç tarihleri (YYYY-MM-DD) — bu tarihten büyük = o sezon
AKTIF_SEZON_BASLANGIC  = "2025-07-01"   # 2025-26 sezonu
GECEN_SEZON_BASLANGIC  = "2024-07-01"   # 2024-25 sezonu

# Poisson için sezon ağırlıkları — eski maçlar daha az etkili
AGIRLIK_AKTIF  = 1.00   # bu sezon
AGIRLIK_GECEN  = 0.60   # geçen sezon
AGIRLIK_ESKI   = 0.35   # iki sezon öncesi

ANA_LIGLER = {"PL", "PD", "BL1", "SA", "FL1", "DED", "PPL", "ELC", "BSA"}


def _sezon_agirligi(utc_date: str) -> float:
    """Maç tarihine göre sezon ağırlığı döndür."""
    if utc_date >= AKTIF_SEZON_BASLANGIC:
        return AGIRLIK_AKTIF
    elif utc_date >= GECEN_SEZON_BASLANGIC:
        return AGIRLIK_GECEN
    else:
        return AGIRLIK_ESKI


def _aktif_sezon_mu(utc_date: str) -> bool:
    return utc_date >= AKTIF_SEZON_BASLANGIC


def istatistik_hesapla(veri: dict = None, cutoff_date: str = None) -> dict:
    """
    Takım istatistiklerini hesaplar.
    cutoff_date verilirse, SADECE bu tarihten önceki maçlar kullanılır (Point-in-Time, Zero Leakage).
    """
    if veri is None:
        veri = veri_yukle()

    # ── Genel istatistikler (tüm sezonlar, ağırlıklı) ─────────────
    stats = defaultdict(lambda: {
        "ev_gol_agirlikli": 0.0, "ev_yenen_agirlikli": 0.0, "ev_mac_agirlik": 0.0,
        "dep_gol_agirlikli": 0.0, "dep_yenen_agirlikli": 0.0, "dep_mac_agirlik": 0.0,
        "toplam_gol_agirlikli": 0.0, "toplam_yenen_agirlikli": 0.0, "toplam_agirlik": 0.0,
        # Ham sayılar (mac_sayisi için)
        "ev_mac": 0, "dep_mac": 0, "toplam_mac": 0,
        "son_goller": [], "lig": "?",
        "h2h": defaultdict(lambda: {"ev_gol": 0, "dep_gol": 0, "mac": 0, "ev_galibiyet": 0, "dep_galibiyet": 0, "beraberlik": 0}),
        # Clean sheet — sadece aktif sezon
        "ev_clean_sheet": 0, "dep_clean_sheet": 0,
        "ev_gol_yemedi": 0,  "dep_gol_yemedi": 0,
        # İlk yarı
        "iy_gol": 0, "iy_yenen": 0, "iy_mac": 0,
        "son_mac_tarihi": "2000-01-01T00:00:00Z",
        "mac_tarihleri": [],
    })

    # ── Aktif sezon puan tablosu (sadece bu sezon) ─────────────────
    aktif_puan = defaultdict(lambda: {
        "puan": 0, "galibiyet": 0, "beraberlik": 0, "maglubiyet": 0
    })
    lig_takimlar = defaultdict(set)   # sadece aktif sezon takımları

    for lig_kodu, maclar in veri.items():
        maclar_sirali = sorted(maclar, key=lambda m: m.get("utcDate", ""))

        for mac in maclar_sirali:
            try:
                ev      = mac["homeTeam"]["name"]
                dep     = mac["awayTeam"]["name"]
                ev_gol  = int(mac["score"]["fullTime"]["home"])
                dep_gol = int(mac["score"]["fullTime"]["away"])
                tarih   = mac.get("utcDate", "")
            except (KeyError, TypeError, ValueError):
                continue

            # Point-in-Time koruması: cutoff_date sonrasındaki maçları ASLA okuma
            if cutoff_date and tarih and tarih >= cutoff_date:
                continue

            agirlik = _sezon_agirligi(tarih)
            aktif   = _aktif_sezon_mu(tarih)

            # ── Ağırlıklı temel istatistikler (tüm sezonlar) ──────
            stats[ev]["ev_gol_agirlikli"]    += ev_gol  * agirlik
            stats[ev]["ev_yenen_agirlikli"]  += dep_gol * agirlik
            stats[ev]["ev_mac_agirlik"]      += agirlik
            stats[ev]["ev_mac"]              += 1
            stats[ev]["toplam_gol_agirlikli"]   += ev_gol  * agirlik
            stats[ev]["toplam_yenen_agirlikli"] += dep_gol * agirlik
            stats[ev]["toplam_agirlik"]         += agirlik
            stats[ev]["toplam_mac"]             += 1
            stats[ev]["son_goller"].append((tarih, ev_gol))
            stats[ev]["son_mac_tarihi"]         = tarih
            stats[ev]["mac_tarihleri"].append(tarih)
            if lig_kodu in ANA_LIGLER or stats[ev]["lig"] == "?":
                stats[ev]["lig"] = lig_kodu

            stats[dep]["dep_gol_agirlikli"]   += dep_gol * agirlik
            stats[dep]["dep_yenen_agirlikli"] += ev_gol  * agirlik
            stats[dep]["dep_mac_agirlik"]     += agirlik
            stats[dep]["dep_mac"]             += 1
            stats[dep]["toplam_gol_agirlikli"]   += dep_gol * agirlik
            stats[dep]["toplam_yenen_agirlikli"] += ev_gol  * agirlik
            stats[dep]["toplam_agirlik"]         += agirlik
            stats[dep]["toplam_mac"]             += 1
            stats[dep]["son_goller"].append((tarih, dep_gol))
            stats[dep]["son_mac_tarihi"]         = tarih
            stats[dep]["mac_tarihleri"].append(tarih)
            if lig_kodu in ANA_LIGLER or stats[dep]["lig"] == "?":
                stats[dep]["lig"] = lig_kodu

            # ── Clean sheet — sadece aktif sezon ──────────────────
            if aktif:
                if dep_gol == 0: stats[ev]["ev_clean_sheet"]  += 1
                if ev_gol  == 0: stats[ev]["ev_gol_yemedi"]   += 1
                if ev_gol  == 0: stats[dep]["dep_clean_sheet"] += 1
                if dep_gol == 0: stats[dep]["dep_gol_yemedi"]  += 1

            # ── İlk yarı — tüm sezonlar ───────────────────────────
            try:
                iy_ev  = int(mac["score"]["halfTime"]["home"])
                iy_dep = int(mac["score"]["halfTime"]["away"])
                stats[ev]["iy_gol"]    += iy_ev
                stats[ev]["iy_yenen"]  += iy_dep
                stats[ev]["iy_mac"]    += 1
                stats[dep]["iy_gol"]   += iy_dep
                stats[dep]["iy_yenen"] += iy_ev
                stats[dep]["iy_mac"]   += 1
            except (KeyError, TypeError, ValueError):
                pass

            # ── Puan tablosu — SADECE aktif sezon, ana lig ────────
            if aktif and lig_kodu in ANA_LIGLER:
                lig_takimlar[lig_kodu].add(ev)
                lig_takimlar[lig_kodu].add(dep)
                if ev_gol > dep_gol:
                    aktif_puan[ev]["puan"]        += 3
                    aktif_puan[ev]["galibiyet"]   += 1
                    aktif_puan[dep]["maglubiyet"] += 1
                elif ev_gol == dep_gol:
                    aktif_puan[ev]["puan"]        += 1
                    aktif_puan[dep]["puan"]       += 1
                    aktif_puan[ev]["beraberlik"]  += 1
                    aktif_puan[dep]["beraberlik"] += 1
                else:
                    aktif_puan[dep]["puan"]       += 3
                    aktif_puan[dep]["galibiyet"]  += 1
                    aktif_puan[ev]["maglubiyet"]  += 1

            # ── H2H — tüm sezonlar (Doğru Maç Sonucu + Gol Takibi) ─
            stats[ev]["h2h"][dep]["ev_gol"]  += ev_gol
            stats[ev]["h2h"][dep]["dep_gol"] += dep_gol
            stats[ev]["h2h"][dep]["mac"]     += 1
            stats[ev]["h2h"][dep]["ev_galibiyet"] += 1 if ev_gol > dep_gol else 0
            stats[ev]["h2h"][dep]["dep_galibiyet"] += 1 if dep_gol > ev_gol else 0
            stats[ev]["h2h"][dep]["beraberlik"] += 1 if ev_gol == dep_gol else 0

            stats[dep]["h2h"][ev]["ev_gol"]  += dep_gol
            stats[dep]["h2h"][ev]["dep_gol"] += ev_gol
            stats[dep]["h2h"][ev]["mac"]     += 1
            stats[dep]["h2h"][ev]["ev_galibiyet"] += 1 if dep_gol > ev_gol else 0
            stats[dep]["h2h"][ev]["dep_galibiyet"] += 1 if ev_gol > dep_gol else 0
            stats[dep]["h2h"][ev]["beraberlik"] += 1 if ev_gol == dep_gol else 0


    # ── Lig sıralaması — sadece aktif sezon ───────────────────────
    lig_siralama = {}
    for lig_kodu, takimlar in lig_takimlar.items():
        sirali = sorted(
            takimlar,
            key=lambda t: aktif_puan[t]["puan"],
            reverse=True
        )
        for sira, takim in enumerate(sirali, 1):
            lig_siralama[takim] = {
                "sira":   sira,
                "toplam": len(sirali),
                "lig":    lig_kodu,
            }

    # ── Sonuç dict ────────────────────────────────────────────────
    sonuc = {}
    for takim, s in stats.items():
        ev_agirlik     = max(s["ev_mac_agirlik"],  0.1)
        dep_agirlik    = max(s["dep_mac_agirlik"], 0.1)
        toplam_agirlik = max(s["toplam_agirlik"],  0.1)
        ev_mac_ham     = max(s["ev_mac"],     1)
        dep_mac_ham    = max(s["dep_mac"],    1)
        iy_mac         = max(s["iy_mac"],     1)

        # Son N maç için sıralı goller (forma için)
        son_goller_sirali = sorted(s["son_goller"], key=lambda x: x[0])
        son_goller = [g for _, g in son_goller_sirali[-SON_MAC_SAYISI:]]
        if not son_goller:
            son_goller = [1.0]

        sira_bilgi = lig_siralama.get(takim, {"sira": 0, "toplam": 1, "lig": s["lig"]})
        sira_oran  = round(1.0 - (sira_bilgi["sira"] - 1) / max(sira_bilgi["toplam"] - 1, 1), 3)

        ap = aktif_puan.get(takim, {"puan": 0, "galibiyet": 0, "beraberlik": 0, "maglubiyet": 0})

        sonuc[takim] = {
            # Ağırlıklı ortalamalar — Poisson için
            "ev_hucum":      s["ev_gol_agirlikli"]    / ev_agirlik,
            "ev_savunma":    s["ev_yenen_agirlikli"]  / ev_agirlik,
            "dep_hucum":     s["dep_gol_agirlikli"]   / dep_agirlik,
            "dep_savunma":   s["dep_yenen_agirlikli"] / dep_agirlik,
            "hucum_genel":   s["toplam_gol_agirlikli"]    / toplam_agirlik,
            "savunma_genel": s["toplam_yenen_agirlikli"]  / toplam_agirlik,
            "form":          sum(son_goller) / len(son_goller),
            "mac_sayisi":    s["toplam_mac"],
            "ev_mac":        s["ev_mac"],
            "dep_mac":       s["dep_mac"],
            "lig":           s["lig"],
            "h2h":           dict(s["h2h"]),
            # Clean sheet — aktif sezon
            "ev_clean_sheet_oran":  round(s["ev_clean_sheet"]  / ev_mac_ham,  3),
            "dep_clean_sheet_oran": round(s["dep_clean_sheet"] / dep_mac_ham, 3),
            "ev_skorsuz_oran":      round(s["ev_gol_yemedi"]   / ev_mac_ham,  3),
            "dep_skorsuz_oran":     round(s["dep_gol_yemedi"]  / dep_mac_ham, 3),
            # İlk yarı
            "iy_gol_oran":   round(s["iy_gol"]   / iy_mac, 3),
            "iy_yenen_oran": round(s["iy_yenen"] / iy_mac, 3),
            "iy_mac":        s["iy_mac"],
            # Puan tablosu — SADECE aktif sezon
            "puan":          ap["puan"],
            "galibiyet":     ap["galibiyet"],
            "beraberlik":    ap["beraberlik"],
            "maglubiyet":    ap["maglubiyet"],
            "lig_sira":      sira_bilgi["sira"],
            "lig_takim_sayisi": sira_bilgi["toplam"],
            "lig_sira_oran": sira_oran,
            "son_mac_tarihi": s["son_mac_tarihi"],
            "mac_tarihleri": s["mac_tarihleri"],
        }

    return sonuc


def lig_ortalamasi_hesapla(istatistikler: dict) -> dict:
    lig_goller = defaultdict(list)
    for takim, s in istatistikler.items():
        lig = s["lig"]
        lig_goller[lig].append(s["hucum_genel"])

    lig_ort = {}
    for lig, goller in lig_goller.items():
        ort = sum(goller) / len(goller) if goller else 1.35
        lig_ort[lig] = {
            "hucum":   round(ort, 4),
            "savunma": round(ort, 4),
        }
    return lig_ort


def h2h_faktor(ev_takim: str, dep_takim: str, istatistikler: dict) -> tuple:
    ev_s = istatistikler.get(ev_takim, {})
    h2h  = ev_s.get("h2h", {}).get(dep_takim)

    if not h2h or h2h.get("mac", 0) < 2:
        return 1.0, 1.0

    mac    = h2h["mac"]
    ev_ort = h2h["ev_gol"]  / mac
    dp_ort = h2h["dep_gol"] / mac
    toplam = ev_ort + dp_ort

    if toplam == 0:
        return 1.0, 1.0

    ev_pay = ev_ort / toplam
    fark   = (ev_pay - 0.5) * 0.16

    ev_f  = max(0.92, min(1.0 + fark,       1.08))
    dep_f = max(0.92, min(1.0 - fark * 0.5, 1.08))

    return ev_f, dep_f


# ═══════════════════════════════════════════════════════════════════════
#  FALLBACK: DB'de verisi olmayan takımlar için sentetik stats üret
# ═══════════════════════════════════════════════════════════════════════
# SKIPPED_NO_DATA problemini çözer: lig ortalamasından statlar üretir
# Bu takımlar için model "ortalama bir takım" olarak tahmin yapar
# Confidence düşer ama KAPSAMLI tahmin yapabilme yeteneği artar

import logging as _logging
_stats_logger = _logging.getLogger("team_stats")

# Global lig ortalamalarını hesapla (lazy, bir kez)
_global_lig_cache = {}

def _global_ortalama(istatistikler: dict) -> dict:
    """Tüm ligler için ortalama stat değerlerini hesapla."""
    global _global_lig_cache
    if _global_lig_cache:
        return _global_lig_cache

    lig_vals = defaultdict(lambda: {
        "ev_hucum": [], "ev_savunma": [], "dep_hucum": [], "dep_savunma": [],
        "hucum_genel": [], "savunma_genel": [], "form": [],
    })

    for takim, s in istatistikler.items():
        lig = s.get("lig", "?")
        for key in lig_vals[lig]:
            if key in s and isinstance(s[key], (int, float)):
                lig_vals[lig][key].append(s[key])

    for lig, vals in lig_vals.items():
        ort = {}
        for key, lst in vals.items():
            ort[key] = round(sum(lst) / len(lst), 3) if lst else 1.2
        _global_lig_cache[lig] = ort

    # "?" ligsiz takımlar için tüm liglerin ortalaması
    if _global_lig_cache:
        all_vals = defaultdict(list)
        for vals in _global_lig_cache.values():
            for k, v in vals.items():
                all_vals[k].append(v)
        _global_lig_cache["_GLOBAL"] = {
            k: round(sum(v) / len(v), 3) for k, v in all_vals.items()
        }

    return _global_lig_cache


def sentetik_stats_uret(takim_isim: str, lig_kodu: str,
                         istatistikler: dict) -> dict:
    """
    DB'de verisi olmayan bir takım için lig ortalamasından sentetik stats üretir.
    
    Bu, tam doğrulukta bir analiz değildir ama:
    - Takımı pipeline'dan düşürmez
    - Oran bazlı edge hesaplaması yapılabilir
    - Sharp sinyali hâlâ geçerlidir
    
    Returns:
        istatistikler dict'iyle uyumlu bir stats dict
    """
    ort_db = _global_ortalama(istatistikler)
    ort = ort_db.get(lig_kodu, ort_db.get("_GLOBAL", {}))

    if not ort:
        ort = {"ev_hucum": 1.3, "ev_savunma": 1.1, "dep_hucum": 1.1,
               "dep_savunma": 1.4, "hucum_genel": 1.2, "savunma_genel": 1.25,
               "form": 1.2}

    _stats_logger.debug(f"  📦 Sentetik stats: {takim_isim} (lig:{lig_kodu})")

    return {
        "ev_hucum":       ort.get("ev_hucum", 1.3),
        "ev_savunma":     ort.get("ev_savunma", 1.1),
        "dep_hucum":      ort.get("dep_hucum", 1.1),
        "dep_savunma":    ort.get("dep_savunma", 1.4),
        "hucum_genel":    ort.get("hucum_genel", 1.2),
        "savunma_genel":  ort.get("savunma_genel", 1.25),
        "form":           ort.get("form", 1.2),
        "mac_sayisi":     0,   # Önemli: confidence için
        "ev_mac":         0,
        "dep_mac":        0,
        "lig":            lig_kodu,
        "h2h":            {},
        "ev_clean_sheet_oran":  0.30,
        "dep_clean_sheet_oran": 0.25,
        "ev_skorsuz_oran":      0.25,
        "dep_skorsuz_oran":     0.30,
        "iy_gol_oran":    0.50,
        "iy_yenen_oran":  0.50,
        "iy_mac":         0,
        "puan":           0,
        "galibiyet":      0,
        "beraberlik":     0,
        "maglubiyet":     0,
        "lig_sira":       10,
        "lig_takim_sayisi": 20,
        "lig_sira_oran":  0.5,
        "son_mac_tarihi": "2000-01-01T00:00:00Z",
        "mac_tarihleri":  [],
        "_sentetik":      True,  # Bu bayrak ile pipeline 'sentetik' olduğunu bilir
    }


def point_in_time_stats(team: str, timestamp: str, match_history: list = None, veri: dict = None) -> dict:
    """
    Belirli bir timestamp öncesindeki maçlardan takım istatistiklerini hesaplar.
    t >= timestamp olan hiçbir gelecekteki maç istatistiklere dahil edilmez (Zero Leakage).
    """
    if match_history is None and veri is not None:
        match_history = []
        for lig, maclar in veri.items():
            for m in maclar:
                try:
                    match_history.append({
                        "home": m["homeTeam"]["name"],
                        "away": m["awayTeam"]["name"],
                        "home_goals": int(m["score"]["fullTime"]["home"]),
                        "away_goals": int(m["score"]["fullTime"]["away"]),
                        "date": m.get("utcDate", ""),
                    })
                except (KeyError, TypeError, ValueError):
                    continue

    if not match_history:
        return {"mac_sayisi": 0, "attigi_gol": 0, "yedigi_gol": 0, "galibiyet": 0, "beraberlik": 0, "maglubiyet": 0}

    attigi = 0
    yedigi = 0
    mac_sayisi = 0
    galibiyet = 0
    beraberlik = 0
    maglubiyet = 0

    for m in match_history:
        m_date = m.get("date", m.get("utcDate", ""))
        if timestamp and m_date and m_date >= timestamp:
            continue

        h_team = m.get("home", m.get("homeTeam", {}).get("name", "")) if isinstance(m.get("homeTeam"), dict) else m.get("home", "")
        a_team = m.get("away", m.get("awayTeam", {}).get("name", "")) if isinstance(m.get("awayTeam"), dict) else m.get("away", "")

        if h_team == team:
            hg = m.get("home_goals", 0)
            ag = m.get("away_goals", 0)
            attigi += hg
            yedigi += ag
            mac_sayisi += 1
            if hg > ag:
                galibiyet += 1
            elif hg == ag:
                beraberlik += 1
            else:
                maglubiyet += 1
        elif a_team == team:
            hg = m.get("home_goals", 0)
            ag = m.get("away_goals", 0)
            attigi += ag
            yedigi += hg
            mac_sayisi += 1
            if ag > hg:
                galibiyet += 1
            elif ag == hg:
                beraberlik += 1
            else:
                maglubiyet += 1

    return {
        "mac_sayisi": mac_sayisi,
        "attigi_gol": attigi,
        "yedigi_gol": yedigi,
        "galibiyet": galibiyet,
        "beraberlik": beraberlik,
        "maglubiyet": maglubiyet,
    }


def point_in_time_xg(team: str, timestamp: str, xg_history: list = None) -> dict:
    """
    Belirli bir timestamp öncesindeki maçlardan rolling xG değerlerini hesaplar.
    """
    if not xg_history:
        return {"matches_count": 0, "mean_xg": 1.25, "mean_xg_conceded": 1.25}

    xgs = []
    xgs_conceded = []

    for m in xg_history:
        m_date = m.get("date", "")
        if timestamp and m_date and m_date >= timestamp:
            continue
        if m.get("team") == team:
            if "xg" in m:
                xgs.append(float(m["xg"]))
            if "xg_conceded" in m:
                xgs_conceded.append(float(m["xg_conceded"]))

    count = len(xgs)
    mean_xg = float(np.mean(xgs)) if count > 0 else 1.25
    mean_xg_c = float(np.mean(xgs_conceded)) if len(xgs_conceded) > 0 else 1.25

    return {
        "matches_count": count,
        "mean_xg": mean_xg,
        "mean_xg_conceded": mean_xg_c,
    }