"""
scrapers/kadro_verisi.py
════════════════════════════════════════════════════════════
Kadro / Sakatlık Etkisi Hesaplayıcı — Cache Tabanlı

MANTIK:
  - data/transfermarkt_cache.json ve data/ilk_11_cache.json'ı okur
  - Eksik kilit oyuncular (forvet, merkez saha) → lambda ceza çarpanı
  - API gerektirmez — mevcut cache üzerinden çalışır
  - ensemble.py'de _KADRO_VAR = True olduğunda devreye girer

ÇARPAN MANTIGI:
  - Kilit oyuncu yokluğu → lam *= 0.85–0.95
  - Çok sayıda eksik → maximum %20 ceza
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger("kadro_verisi")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TRANSFERMARKT_CACHE = os.path.join(ROOT, "data", "transfermarkt_cache.json")
ILK_11_CACHE        = os.path.join(ROOT, "data", "ilk_11_cache.json")
KADRO_CACHE         = os.path.join(ROOT, "data", "kadro_cache.json")

# Pozisyon ağırlıkları — eksik oyuncunun lambda etkisi
POZISYON_AGIRLIK = {
    "FW":  0.08,   # Forvet eksiği → %8 gol cezası
    "MF":  0.05,   # Merkez saha → %5
    "GK":  0.03,   # Kaleci → %3 (yedek genellikle hazır)
    "DF":  0.04,   # Defans → %4 (savunma etkisi)
}
MAKS_CEZA   = 0.20   # Maksimum %20 lambda cezası
TAZELIK_GUN = 3      # 3 günden eski cache yenilenmesi önerilir (uyarı)


def _cache_yukle(dosya: str) -> dict:
    if os.path.exists(dosya):
        try:
            with open(dosya, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _takim_normalize(isim: str) -> str:
    """Takım ismini arama için normalize et."""
    return isim.lower().replace(" ", "").replace("-", "")


def _takim_bul(isim: str, cache: dict) -> dict | None:
    """Cache'de takımı bul (fuzzy)."""
    norm = _takim_normalize(isim)
    for key, data in cache.items():
        if _takim_normalize(key) == norm:
            return data
    # Kısmi eşleşme
    for key, data in cache.items():
        k_norm = _takim_normalize(key)
        if norm[:5] in k_norm or k_norm[:5] in norm:
            return data
    return None


def _eksik_oyuncu_cezasi(eksik_oyuncular: list) -> float:
    """
    Eksik oyuncu listesinden lambda ceza çarpanı hesapla.
    
    Args:
        eksik_oyuncular: [{"isim": "X", "pozisyon": "FW", "onem": "yuksek"}, ...]
    
    Returns:
        carpan: 0.80–1.00 arası float (1.0 = ceza yok)
    """
    toplam_ceza = 0.0
    for oyuncu in eksik_oyuncular:
        pozisyon = str(oyuncu.get("pozisyon", "MF")).upper()[:2]
        onem     = str(oyuncu.get("onem", "orta")).lower()
        
        base_ceza = POZISYON_AGIRLIK.get(pozisyon, 0.04)
        
        # Önem çarpanı
        if "yuksek" in onem or "kilit" in onem or "star" in onem:
            ceza = base_ceza * 1.5
        elif "dusuk" in onem or "yedek" in onem:
            ceza = base_ceza * 0.3
        else:
            ceza = base_ceza
        
        toplam_ceza += ceza
    
    # Maksimum ceza uygula
    toplam_ceza = min(toplam_ceza, MAKS_CEZA)
    return round(1.0 - toplam_ceza, 3)


def _ilk_11_guc(takim_isim: str, ilk_11_cache: dict) -> float:
    """
    İlk 11 verisi varsa kadro güç skoru hesapla.
    Oyuncuların değer toplamını lig ortalamasıyla kıyasla.
    """
    takim_data = _takim_bul(takim_isim, ilk_11_cache)
    if not takim_data:
        return 1.0
    
    oyuncular = takim_data.get("oyuncular", [])
    if not oyuncular:
        return 1.0
    
    # Değer tabanlı güç (Transfermarkt market value)
    degerler = [
        float(o.get("deger_milyon", 0) or 0)
        for o in oyuncular
    ]
    if not degerler or sum(degerler) == 0:
        return 1.0
    
    # Lig ortalamasını tüm cache'den hesapla
    tum_degerler = []
    for _, t_data in ilk_11_cache.items():
        for o in t_data.get("oyuncular", []):
            d = float(o.get("deger_milyon", 0) or 0)
            if d > 0:
                tum_degerler.append(d)
    
    if not tum_degerler:
        return 1.0
    
    lig_ort = sum(tum_degerler) / len(tum_degerler)
    takim_ort = sum(degerler) / len(degerler)
    
    # Normalize: 1.0 = lig ortalaması, >1 = güçlü, <1 = zayıf
    guc = round(min(1.20, max(0.80, takim_ort / max(lig_ort, 0.01))), 3)
    return guc


def kadro_etkisi_hesapla(
    ev_takim: str,
    dep_takim: str,
    sessiz: bool = False,
) -> dict:
    """
    Kadro etkisini hesapla ve ensemble'a gönder.
    
    Returns:
        {
            "veri_var": bool,
            "ev_guc": float,      # 0.80–1.20 arası lambda çarpanı
            "dep_guc": float,
            "ev_eksik": str,      # Eksik oyuncu özeti
            "dep_eksik": str,
        }
    """
    transfermarkt = _cache_yukle(TRANSFERMARKT_CACHE)
    ilk_11        = _cache_yukle(ILK_11_CACHE)
    kadro         = _cache_yukle(KADRO_CACHE)

    if not transfermarkt and not ilk_11 and not kadro:
        return {"veri_var": False, "ev_guc": 1.0, "dep_guc": 1.0,
                "ev_eksik": "", "dep_eksik": ""}

    ev_guc  = 1.0
    dep_guc = 1.0
    ev_eksik_str  = ""
    dep_eksik_str = ""

    # ── İlk 11 kadro gücü ────────────────────────────────────────────
    if ilk_11:
        ev_guc  = _ilk_11_guc(ev_takim,  ilk_11)
        dep_guc = _ilk_11_guc(dep_takim, ilk_11)

    # ── Sakatlık/kadro dışı oyuncular (kadro_cache.json) ─────────────
    ev_kadro  = _takim_bul(ev_takim,  kadro)
    dep_kadro = _takim_bul(dep_takim, kadro)

    if ev_kadro:
        eksik_liste = ev_kadro.get("eksik_oyuncular", [])
        if eksik_liste:
            ceza_carpan = _eksik_oyuncu_cezasi(eksik_liste)
            ev_guc = round(ev_guc * ceza_carpan, 3)
            ev_eksik_str = ", ".join(
                o.get("isim", "?") for o in eksik_liste[:3]
            )
            if not sessiz:
                logger.info(f"  🏥 {ev_takim}: {len(eksik_liste)} eksik → λ çarpan {ceza_carpan:.2f}")

    if dep_kadro:
        eksik_liste = dep_kadro.get("eksik_oyuncular", [])
        if eksik_liste:
            ceza_carpan = _eksik_oyuncu_cezasi(eksik_liste)
            dep_guc = round(dep_guc * ceza_carpan, 3)
            dep_eksik_str = ", ".join(
                o.get("isim", "?") for o in eksik_liste[:3]
            )
            if not sessiz:
                logger.info(f"  🏥 {dep_takim}: {len(eksik_liste)} eksik → λ çarpan {ceza_carpan:.2f}")

    veri_var = (ev_guc != 1.0 or dep_guc != 1.0 or
                bool(ev_eksik_str) or bool(dep_eksik_str))

    return {
        "veri_var":  veri_var,
        "ev_guc":    ev_guc,
        "dep_guc":   dep_guc,
        "ev_eksik":  ev_eksik_str,
        "dep_eksik": dep_eksik_str,
    }


def kadro_lambda_duzenle(
    lam_ev: float,
    lam_dep: float,
    kadro_etki: dict,
) -> tuple:
    """
    Kadro etkisini Poisson lambda'larına uygula.
    Sadece güçlü veri varsa (veri_var=True) uygular.
    """
    if not kadro_etki.get("veri_var"):
        return lam_ev, lam_dep

    yeni_ev  = round(max(0.4, lam_ev  * kadro_etki.get("ev_guc",  1.0)), 3)
    yeni_dep = round(max(0.4, lam_dep * kadro_etki.get("dep_guc", 1.0)), 3)
    return yeni_ev, yeni_dep


if __name__ == "__main__":
    # Test
    logging.basicConfig(level=logging.INFO)
    sonuc = kadro_etkisi_hesapla("Manchester City", "Liverpool")
    print(f"Kadro etkisi: {sonuc}")
