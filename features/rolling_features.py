#!/usr/bin/env python3
"""
features/rolling_features.py
════════════════════════════════════════════════════════════════
Gelişmiş Rolling İstatistik Feature Motoru
──────────────────────────────────────────
Piyasayı yenmek için gereken "gizli" bilgi sinyalleri:

  1. Son 5/10 maç rolling ortalaması (sezon ortalaması değil)
  2. Ev/Deplasman form AYRIMLI (combined form yanıltıcı)
  3. xG Over/Underperformance (şans mı güç mü?)
  4. Clean sheet trend (son 5 maçta gol yeme oranı)
  5. Rakip gücü düzeltmeli form (SoS - Strength of Schedule)
  6. Gol atma/yeme tutarsızlığı (variance = güvensiz takım)
  7. Son maç skoru şoku (büyük kayıp/galibiyet psikoloji etkisi)

KULLANIM:
  from features.rolling_features import rolling_features_uret, rolling_features_mac_oncesi
"""

import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Tuple


# ─── Yardımcı Fonksiyonlar ───────────────────────────────────

def _tarih_parse(tarih_str: str) -> datetime | None:
    """ISO tarih string'ini datetime'a çevirir."""
    if not tarih_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(tarih_str[:len(fmt)-2] if "T" in tarih_str else tarih_str, fmt)
        except ValueError:
            continue
    return None


def _puan(ev_gol: int, dep_gol: int, konum: str) -> int:
    """Maç puanını döndür (konum: 'ev' veya 'dep')."""
    if konum == "ev":
        if ev_gol > dep_gol:   return 3
        elif ev_gol == dep_gol: return 1
        return 0
    else:
        if dep_gol > ev_gol:   return 3
        elif dep_gol == ev_gol: return 1
        return 0


def _xg_proxy(sut: float, isabet: float, konum_lambda: float = 1.35) -> float:
    """İsabetli şut tabanlı xG proxy hesapla."""
    return min(sut * 0.10 + isabet * 0.22, 3.5)


# ─── Ana Rolling Feature Motoru ──────────────────────────────

def rolling_features_uret(ham_veri: dict, n_son: int = 5) -> dict:
    """
    Tüm maç verisinden her takım için rolling feature sözlüğü üretir.
    
    Args:
        ham_veri: {lig_kodu: [mac_dict, ...]} yapısında ham maç verisi
        n_son:    Son kaç maç baz alınacak (varsayılan: 5)
    
    Returns:
        {takim_adi: {
            "ev_gol_ort5":    float,  # Son 5 ev maçı gol ortalaması
            "dep_gol_ort5":   float,  # Son 5 dep maçı gol ortalaması
            "ev_yenen_ort5":  float,  # Son 5 ev maçı yenen gol
            "dep_yenen_ort5": float,  # Son 5 dep maçı yenen gol
            "ev_puan_ort5":   float,  # Son 5 ev maçı puan ort.
            "dep_puan_ort5":  float,  # Son 5 dep maçı puan ort.
            "ev_clean_sheet": float,  # Son 5 ev maçı clean sheet oranı
            "dep_clean_sheet":float,
            "gol_var_ort5":   float,  # Son 5 her iki taraf gol attı oranı
            "xg_diff_ort5":   float,  # xG over/underperformance (gol - proxy_xG)
            "form_tutarsizlik": float, # Skor varyansı (tutarsız takım = riskli)
            "son_mac_soku":   float,  # Son maç büyük skor şoku (-1 ile +1)
            "sos_ev":         float,  # Ev maçı rakip güç skoru (SoS)
            "sos_dep":        float,  # Dep maçı rakip güç skoru (SoS)
            "trend":          float,  # Son 3 vs önceki 3 maç puan farkı (trend)
            "mac_sayisi":     int,
        }}
    """
    # Her takım için sıralı maç geçmişi {takim: [(tarih, mac_dict, konum), ...]}
    takim_maclar: dict = defaultdict(list)
    
    # Tüm ligleri birleştir ve tarihe göre sırala
    tum_maclar = []
    for lig_kodu, maclar in ham_veri.items():
        for mac in maclar:
            tarih = mac.get("utcDate", "")
            tum_maclar.append((tarih, lig_kodu, mac))
    
    tum_maclar.sort(key=lambda x: x[0])
    
    # ELO tabanlı basit güç skoru (rakip güç için kullanılacak)
    takim_gucu: dict = defaultdict(lambda: 1500.0)
    
    for tarih, lig_kodu, mac in tum_maclar:
        try:
            ev  = mac["homeTeam"]["name"]
            dep = mac["awayTeam"]["name"]
            ev_gol  = int(mac["score"]["fullTime"]["home"])
            dep_gol = int(mac["score"]["fullTime"]["away"])
        except (KeyError, TypeError, ValueError):
            continue
        
        # Rakip güç bilgisini ekle
        ev_guc_o  = takim_gucu[ev]
        dep_guc_o = takim_gucu[dep]
        
        mac_bilgi = {
            "tarih":    tarih,
            "ev_gol":   ev_gol,
            "dep_gol":  dep_gol,
            "lig":      lig_kodu,
            "rakip_guc": dep_guc_o,  # ev için rakip = dep
        }
        takim_maclar[ev].append(("ev", mac_bilgi, dep_guc_o))
        
        mac_bilgi_dep = {**mac_bilgi, "rakip_guc": ev_guc_o}
        takim_maclar[dep].append(("dep", mac_bilgi_dep, ev_guc_o))
        
        # Basit ELO güncelleme
        K = 20
        ev_beklenti = 1 / (1 + 10 ** ((dep_guc_o - ev_guc_o) / 400))
        sonuc_ev = 1.0 if ev_gol > dep_gol else (0.5 if ev_gol == dep_gol else 0.0)
        takim_gucu[ev]  += K * (sonuc_ev - ev_beklenti)
        takim_gucu[dep] += K * ((1 - sonuc_ev) - (1 - ev_beklenti))
    
    # Her takım için rolling feature hesapla
    sonuc: dict = {}
    
    for takim, mac_listesi in takim_maclar.items():
        ev_maclar   = [(k, m) for k, m, _ in mac_listesi if k == "ev"]
        dep_maclar  = [(k, m) for k, m, _ in mac_listesi if k == "dep"]
        tum_son     = mac_listesi[-10:]  # Son 10 maç (her konumdan)
        
        ev_son  = ev_maclar[-n_son:]
        dep_son = dep_maclar[-n_son:]
        tum_son5 = mac_listesi[-(n_son * 2):]
        
        def _ort(liste, key_fn, fallback=0.0):
            vals = [key_fn(m) for _, m, _ in liste if key_fn(m) is not None]
            return sum(vals) / len(vals) if vals else fallback
        
        def _ev_gol(m): return m.get("ev_gol", 0)
        def _dep_gol(m): return m.get("dep_gol", 0)
        
        # Ev istatistikleri
        ev_gol_ort  = sum(m["ev_gol"] for _, m in ev_son) / max(len(ev_son), 1)
        ev_yed_ort  = sum(m["dep_gol"] for _, m in ev_son) / max(len(ev_son), 1)
        ev_puan_ort = sum(_puan(m["ev_gol"], m["dep_gol"], "ev") for _, m in ev_son) / max(len(ev_son), 1)
        ev_clean    = sum(1 for _, m in ev_son if m["dep_gol"] == 0) / max(len(ev_son), 1)
        ev_sos      = sum(m.get("rakip_guc", 1500) for _, m in ev_son) / max(len(ev_son), 1500)
        
        # Deplasman istatistikleri
        dep_gol_ort  = sum(m["dep_gol"] for _, m in dep_son) / max(len(dep_son), 1)
        dep_yed_ort  = sum(m["ev_gol"] for _, m in dep_son) / max(len(dep_son), 1)
        dep_puan_ort = sum(_puan(m["ev_gol"], m["dep_gol"], "dep") for _, m in dep_son) / max(len(dep_son), 1)
        dep_clean    = sum(1 for _, m in dep_son if m["ev_gol"] == 0) / max(len(dep_son), 1)
        dep_sos      = sum(m.get("rakip_guc", 1500) for _, m in dep_son) / max(len(dep_son), 1500)
        
        # KG Var oranı (her iki taraf gol attı)
        kg_var_5 = 0.0
        if tum_son5:
            kg = sum(1 for k, m, _ in tum_son5
                     if (k == "ev"  and m["ev_gol"] >= 1 and m["dep_gol"] >= 1) or
                        (k == "dep" and m["dep_gol"] >= 1 and m["ev_gol"] >= 1))
            kg_var_5 = kg / len(tum_son5)
        
        # xG Over/Underperformance (gol - beklenen gol)
        # Proxy: Ortalama gol, lig ortalamasına kıyasla
        gol_fark_listesi = []
        for k, m, _ in tum_son5:
            att = m["ev_gol"] if k == "ev" else m["dep_gol"]
            beklenen = 1.35  # Lig ortalaması proxy
            gol_fark_listesi.append(att - beklenen)
        xg_diff_ort = sum(gol_fark_listesi) / max(len(gol_fark_listesi), 1)
        
        # Form tutarsızlığı (yüksek varyans = güvenilmez takım)
        tum_goller = [m["ev_gol"] if k == "ev" else m["dep_gol"]
                      for k, m, _ in tum_son5]
        if len(tum_goller) >= 3:
            ort = sum(tum_goller) / len(tum_goller)
            var = sum((g - ort) ** 2 for g in tum_goller) / len(tum_goller)
            tutarsizlik = math.sqrt(var)
        else:
            tutarsizlik = 1.0
        
        # Son maç şoku (-1: büyük kayıp, +1: büyük galibiyet)
        son_mac_soku = 0.0
        if mac_listesi:
            k_son, m_son, _ = mac_listesi[-1]
            att = m_son["ev_gol"] if k_son == "ev" else m_son["dep_gol"]
            yed = m_son["dep_gol"] if k_son == "ev" else m_son["ev_gol"]
            fark = att - yed
            son_mac_soku = max(-1.0, min(1.0, fark / 3.0))
        
        # Trend: Son 3 maç vs önceki 3 maç puan farkı
        trend = 0.0
        if len(mac_listesi) >= 6:
            son3 = mac_listesi[-3:]
            prev3 = mac_listesi[-6:-3]
            
            def _puan_listesi(ml):
                puanlar = []
                for k, m, _ in ml:
                    p = _puan(m["ev_gol"], m["dep_gol"], k)
                    puanlar.append(p)
                return puanlar
            
            son3_p  = sum(_puan_listesi(son3))  / 3
            prev3_p = sum(_puan_listesi(prev3)) / 3
            trend   = son3_p - prev3_p  # pozitif = yükselen form
        
        # SoS normalize (1500 = ortalama güç)
        sos_ev_norm  = (ev_sos - 1500) / 200.0   # -1 ile +1 arasında
        sos_dep_norm = (dep_sos - 1500) / 200.0
        
        sonuc[takim] = {
            "ev_gol_ort5":     round(ev_gol_ort, 3),
            "dep_gol_ort5":    round(dep_gol_ort, 3),
            "ev_yenen_ort5":   round(ev_yed_ort, 3),
            "dep_yenen_ort5":  round(dep_yed_ort, 3),
            "ev_puan_ort5":    round(ev_puan_ort, 3),
            "dep_puan_ort5":   round(dep_puan_ort, 3),
            "ev_clean_sheet":  round(ev_clean, 3),
            "dep_clean_sheet": round(dep_clean, 3),
            "kg_var_ort5":     round(kg_var_5, 3),
            "xg_diff_ort5":    round(xg_diff_ort, 3),
            "form_tutarsizlik": round(tutarsizlik, 3),
            "son_mac_soku":    round(son_mac_soku, 3),
            "sos_ev_norm":     round(max(-2.0, min(2.0, sos_ev_norm)), 3),
            "sos_dep_norm":    round(max(-2.0, min(2.0, sos_dep_norm)), 3),
            "trend":           round(max(-3.0, min(3.0, trend)), 3),
            "ev_mac_sayisi":   len(ev_maclar),
            "dep_mac_sayisi":  len(dep_maclar),
            "toplam_mac":      len(mac_listesi),
            "takim_gucu":      round(takim_gucu[takim], 1),
        }
    
    return sonuc


def rolling_feature_vektoru(ev_takim: str, dep_takim: str,
                              rolling_db: dict,
                              konum: str = "ev") -> list:
    """
    Belirli bir maç için ev/dep rolling feature vektörü üretir.
    train.py'deki _feature_uret ile birleştirmek için kullanılır.
    
    Returns: 30 elemanlı liste (yeni feature'lar)
    """
    ev_r  = rolling_db.get(ev_takim,  {})
    dep_r = rolling_db.get(dep_takim, {})
    
    def _g(d, key, fallback=0.0):
        return float(d.get(key, fallback))
    
    return [
        # Ev takımı EV maçı rolling stats
        _g(ev_r, "ev_gol_ort5",    1.35),
        _g(ev_r, "ev_yenen_ort5",  1.35),
        _g(ev_r, "ev_puan_ort5",   1.0),
        _g(ev_r, "ev_clean_sheet", 0.3),
        _g(ev_r, "sos_ev_norm",    0.0),
        
        # Dep takımı DEPLASMAN rolling stats
        _g(dep_r, "dep_gol_ort5",    1.35),
        _g(dep_r, "dep_yenen_ort5",  1.35),
        _g(dep_r, "dep_puan_ort5",   1.0),
        _g(dep_r, "dep_clean_sheet", 0.3),
        _g(dep_r, "sos_dep_norm",    0.0),
        
        # Karşılaştırmalı metrikler
        _g(ev_r, "ev_gol_ort5", 1.35) - _g(dep_r, "dep_yenen_ort5", 1.35),   # Hücum vs Savunma farkı
        _g(dep_r, "dep_gol_ort5", 1.35) - _g(ev_r, "ev_yenen_ort5", 1.35),   # Dep hücum vs Ev savunma
        _g(ev_r, "ev_puan_ort5", 1.0) - _g(dep_r, "dep_puan_ort5", 1.0),     # Form farkı
        
        # xG overperformance (şans vs gerçek güç)
        _g(ev_r, "xg_diff_ort5", 0.0),
        _g(dep_r, "xg_diff_ort5", 0.0),
        
        # KG Var / Gol beklentisi
        _g(ev_r, "kg_var_ort5", 0.5),
        _g(dep_r, "kg_var_ort5", 0.5),
        
        # Tutarsızlık (düşük = güvenilir, yüksek = sürpriz ihtimali)
        _g(ev_r, "form_tutarsizlik", 1.0),
        _g(dep_r, "form_tutarsizlik", 1.0),
        
        # Son maç şoku (psikoloji etkisi)
        _g(ev_r, "son_mac_soku", 0.0),
        _g(dep_r, "son_mac_soku", 0.0),
        
        # Trend (yükselen/düşen form)
        _g(ev_r, "trend", 0.0),
        _g(dep_r, "trend", 0.0),
        
        # Rakip güç skoru (SoS)
        _g(ev_r, "sos_ev_norm", 0.0) - _g(dep_r, "sos_dep_norm", 0.0),
        
        # Takım gücü (tüm sezon ELO)
        (_g(ev_r, "takim_gucu", 1500) - _g(dep_r, "takim_gucu", 1500)) / 400,
        
        # Veri güvenilirliği (kaç maç var)
        min(_g(ev_r, "ev_mac_sayisi", 0) / 20, 1.0),
        min(_g(dep_r, "dep_mac_sayisi", 0) / 20, 1.0),
        
        # Birleşik skor (hücum toplamı)
        _g(ev_r, "ev_gol_ort5", 1.35) + _g(dep_r, "dep_gol_ort5", 1.35),
        
        # Savunma toplamı (düşük = düşük gol maçı)
        _g(ev_r, "ev_yenen_ort5", 1.35) + _g(dep_r, "dep_yenen_ort5", 1.35),
        
        # Ev avantajı skoru (ev puan ort - dep puan ort, aynı takım için)
        _g(ev_r, "ev_puan_ort5", 1.0) - _g(ev_r, "dep_puan_ort5", 1.0),
    ]


ROLLING_FEATURE_ISIMLERI = [
    "rol_ev_gol5", "rol_ev_yed5", "rol_ev_puan5", "rol_ev_clean", "rol_ev_sos",
    "rol_dep_gol5", "rol_dep_yed5", "rol_dep_puan5", "rol_dep_clean", "rol_dep_sos",
    "rol_hucum_avantaj", "rol_dep_hucum_savunma", "rol_form_fark",
    "rol_ev_xg_diff", "rol_dep_xg_diff",
    "rol_ev_kg", "rol_dep_kg",
    "rol_ev_tutarsiz", "rol_dep_tutarsiz",
    "rol_ev_soku", "rol_dep_soku",
    "rol_ev_trend", "rol_dep_trend",
    "rol_sos_fark", "rol_guc_fark",
    "rol_ev_veri_guveni", "rol_dep_veri_guveni",
    "rol_gol_toplam", "rol_yed_toplam",
    "rol_ev_avantaj_skoru",
]
