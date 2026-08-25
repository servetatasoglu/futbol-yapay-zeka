#!/usr/bin/env python3
"""
data/xg.py — xG Veri Arayüzü
════════════════════════════════════════════
Eski Playwright tabanlı Understat veri çekicisinin yerini aldı.
Artık doğrudan scrapers/fbref_xg.py üzerinden 
(football-data.co.uk + FBref Hibrid) çekilen verileri okur.

Bu dosya, projenin geri kalanının (model/ensemble.py)
arayüzünü bozmamak için bir proxy görevi görür.
"""

import sys, os
import logging

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scrapers.fbref_xg import fbref_xg_cek, fbref_takim_xg

logger = logging.getLogger("xg_arayuzu")


def xg_yukle(zorla_yenile: bool = False) -> dict:
    """
    Projeye genel xG/Advanced Stats verisini döner.
    fbref_xg_cek zaten cache mekanizmasına sahiptir.
    """
    try:
        takimlar = fbref_xg_cek(zorla=zorla_yenile)
        
        # Geriye dönük uyumluluk: "xg", "xga", "mac" alanlarını bekleme ihtimali
        # olan modüller için fbref_cache içerisindeki yeni alanları mapliyoruz.
        uyumlu_takimlar = {}
        for takim_adi, v in takimlar.items():
            uyumlu_takimlar[takim_adi] = {
                "xg":  v.get("xG90", 1.0),
                "xga": v.get("xGA90", 1.0),
                "mac": v.get("mac_sayisi", 30),
                "sut90": v.get("sut90", 10.0),
                "sot90": v.get("sot90", 4.0),
                "isabet_yuzdesi": v.get("sut_isabet_yuzde", 30.0),
                "lig": v.get("lig", "Bilinmiyor"),
                "kaynak": "football-data.co.uk (advanced_xg)"
            }
        return uyumlu_takimlar
    except Exception as e:
        logger.error(f"xG Yükleme Hatası: {e}")
        return {}


def xg_ara(takim_adi: str, xg_db: dict) -> dict | None:
    """
    Belirli bir takımın xG verisini bulan arayüz (fuzzy search destekler).
    """
    if not xg_db or not takim_adi:
        return None
        
    # Eski kodun beklediği basit fuzzy arama (fbref_takim_xg kendi başına yapar ama 
    # xg_db parametresi üzerinden filtreleme yapalım)
    from scrapers.fbref_xg import _takim_normalize
    norm = _takim_normalize(takim_adi)
    
    if norm in xg_db:
        return xg_db[norm]
        
    for key, veri in xg_db.items():
        if norm[:6] in key or key[:6] in norm:
            return veri
            
    for key, veri in xg_db.items():
        if norm[:4] == key[:4]:
            return veri
            
    return None
