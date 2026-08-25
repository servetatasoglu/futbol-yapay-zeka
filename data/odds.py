# scrapers/canli_oranlar.py
"""
Canlı Oran Çekici — GELİŞTİRİLMİŞ v2
══════════════════════════════════════════════════════════════
Öncelik sırası:
  1. The-Odds-API  (kredi varsa — Pinnacle dahil, en kaliteli)
  2. API-Football  (key varsa — günde 100 istek)
  3. Betexplorer   (ücretsiz, kayıt yok — gerçek piyasa oranları)
  4. Football-data + GELİŞMİŞ model (Poisson + ELO + Form hibrit)
  5. Demo oranlar  (son çare)

YENİLİKLER v2:
  • Betexplorer scraper eklendi (gerçek odds, ücretsiz)
  • Gelişmiş ELO: form + h2h + gol ortalaması hibrit model
  • Oran güven skoru: kaç kaynaktan doğrulandı
  • Daha akıllı cache yönetimi
"""

import requests
import warnings
import json
import os
import re
import time
from datetime import datetime, timezone, timedelta
from config.settings import (
    ODDS_API_KEY, API_FOOTBALL_KEY, SPORTMONKS_API_KEY, LIGLER,
    MIN_ORAN, MAX_ORAN, ODDS_GUN_PENCERESI, ODDS_CACHE_DAKIKA,
    FOOTBALL_DATA_API_KEY
)
from data.proxy import get_working_session
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH   = os.path.join(BASE_DIR, "data", "odds_cache.json")
HAREKET_PATH = os.path.join(BASE_DIR, "data", "odds_hareket.json")

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"

# Betexplorer lig URL eşleşmeleri
BETEXPLORER_LIGLER = {
    "PL":  "soccer/england/premier-league",
    "PD":  "soccer/spain/laliga",
    "BL1": "soccer/germany/bundesliga",
    "SA":  "soccer/italy/serie-a",
    "FL1": "soccer/france/ligue-1",
    "DED": "soccer/netherlands/eredivisie",
    "PPL": "soccer/portugal/superliga",
    "ELC": "soccer/england/championship",
    "CL":  "soccer/europe/champions-league",
}


# ══════════════════════════════════════════════════════════════
#  CACHE SİSTEMİ
# ══════════════════════════════════════════════════════════════

def _cache_guncelse_mi() -> bool:
    if not os.path.exists(CACHE_PATH):
        return False
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        gecen_dakika = (time.time() - cache.get("zaman", 0)) / 60
        if gecen_dakika >= ODDS_CACHE_DAKIKA:
            return False
        cekilen_gun = cache.get("takvim_gunu", "")
        bugun = datetime.now().strftime("%Y-%m-%d")
        if cekilen_gun != bugun:
            return False
        return True
    except Exception as e:
        print(f"  ⚠️  [canli_oranlar] Cache okuma hatası (_cache_guncelse_mi): {e}")
        return False


def _cache_oku() -> list:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        maclar = cache.get("maclar", [])
        gecen  = int((time.time() - cache.get("zaman", 0)) / 60)
        saat   = gecen // 60
        dakika = gecen % 60
        sure_str  = f"{saat}s {dakika}dk" if saat > 0 else f"{dakika} dakika"
        kalan_dk  = max(0, int(ODDS_CACHE_DAKIKA - gecen))
        kalan_saat = kalan_dk // 60
        kalan_str  = f"{kalan_saat}s {kalan_dk%60}dk" if kalan_saat > 0 else f"{kalan_dk}dk"
        kaynak = cache.get("kaynak", "bilinmiyor")
        print(f"  ♻️  Oran cache kullanılıyor ({sure_str} önce çekildi | "
              f"sonraki yenileme: {kalan_str} sonra | {len(maclar)} maç | kaynak: {kaynak})")
        return maclar
    except Exception as e:
        print(f"  ⚠️  [canli_oranlar] Cache okuma hatası (_cache_oku): {e}")
        return []


def _cache_yaz(maclar: list, kaynak: str = ""):
    if not maclar:
        return
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({
                "zaman":       time.time(),
                "takvim_gunu": datetime.now().strftime("%Y-%m-%d"),
                "kaynak":      kaynak,
                "maclar":      maclar,
            }, f, ensure_ascii=False)
    except Exception as e:
        print(f"  ⚠️  [canli_oranlar] Cache yazma hatası (_cache_yaz): {e}")
        pass


def _cache_temizle():
    if os.path.exists(CACHE_PATH):
        os.remove(CACHE_PATH)


# ══════════════════════════════════════════════════════════════
#  ERKEN ORAN ANLIKI (CLV İÇİN)
#  Maç 48-72 saat içinde oynanacaksa açılış oranlarını yakala.
#  Bu veriler clv_tracker'ın "gerçek CLV = alınan oran / kapanış"
#  yerine "alınan oran / açılış" hesabı yapmasını sağlar.
# ══════════════════════════════════════════════════════════════

ERKEN_ORAN_PATH = os.path.join(BASE_DIR, "data", "early_odds_snapshot.json")


def early_odds_snapshot(maclar: list):
    """
    Maç 48-72 saat içindeyse açılış oranlarını yakalar.
    Zaten yakalanmış maçları tekrar kaydetmez (çift kayıt önleme).
    """
    if not maclar:
        return

    try:
        with open(ERKEN_ORAN_PATH, "r", encoding="utf-8") as f:
            snapshot_db = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        snapshot_db = {}

    simdi = datetime.now()
    yeni_kayit = 0

    for mac in maclar:
        mac_tarihi_str = mac.get("mac_tarihi", "")
        if not mac_tarihi_str:
            continue

        try:
            # ISO format veya basit date formatını parse et
            if "T" in str(mac_tarihi_str):
                mac_dt = datetime.fromisoformat(str(mac_tarihi_str).replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                mac_dt = datetime.strptime(str(mac_tarihi_str)[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            continue

        saat_fark = (mac_dt - simdi).total_seconds() / 3600

        # Sadece 24-80 saat arasındaki maçları yakala (erken oran penceresi)
        if not (24 <= saat_fark <= 80):
            continue

        mac_key = f"{mac.get('ev','')}|{mac.get('dep','')}|{str(mac_tarihi_str)[:10]}"

        # Zaten yaklanmışsa atla
        if mac_key in snapshot_db:
            continue

        snapshot_db[mac_key] = {
            "ev_oran":        mac.get("ev_oran",   0),
            "dep_oran":       mac.get("dep_oran",  0),
            "ber_oran":       mac.get("ber_oran",  0),
            "over25_oran":    mac.get("over25_oran", 0),
            "under25_oran":   mac.get("under25_oran", 0),
            "yakala_zamani":  simdi.strftime("%Y-%m-%dT%H:%M"),
            "mac_tarihi":     str(mac_tarihi_str)[:16],
            "saat_once":      round(saat_fark, 1),
            "kaynak":         mac.get("kaynak", ""),
        }
        yeni_kayit += 1

    if yeni_kayit > 0:
        os.makedirs(os.path.dirname(ERKEN_ORAN_PATH), exist_ok=True)
        with open(ERKEN_ORAN_PATH, "w", encoding="utf-8") as f:
            json.dump(snapshot_db, f, ensure_ascii=False, indent=2)
        print(f"  📸 {yeni_kayit} maç için erken oran snapshot'ı kaydedildi (CLV için)")



# ══════════════════════════════════════════════════════════════
#  ORAN HAREKETİ TAKİBİ
# ══════════════════════════════════════════════════════════════

def _hareket_yukle() -> dict:
    if not os.path.exists(HAREKET_PATH):
        return {}
    try:
        with open(HAREKET_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ⚠️  [canli_oranlar] Hareket db okuma hatası: {e}")
        return {}


def _hareket_kaydet(hareket: dict):
    os.makedirs(os.path.dirname(HAREKET_PATH), exist_ok=True)
    try:
        with open(HAREKET_PATH, "w", encoding="utf-8") as f:
            json.dump(hareket, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ⚠️  [canli_oranlar] Hareket db yazma hatası: {e}")
        pass


def _oran_hareketi_hesapla(mac_key, ev_oran, dep_oran, hareket_db):
    try:
        from data.odds_movement import oran_hareketi_hesapla_v2
        return oran_hareketi_hesapla_v2(mac_key, ev_oran, dep_oran, hareket_db)
    except Exception as e:
        print(f"  ⚠️  [odds_v2_error] {e}")
        return {
            "ev_hareket": 0.0, "dep_hareket": 0.0,
            "sharp_sinyal": "YOK", "hareket_gucu": 0.0,
            "ilk_oran": True, "ilk_ev_oran": ev_oran, "ilk_dep_oran": dep_oran
        }


# ══════════════════════════════════════════════════════════════
#  ORTAK YARDIMCI
# ══════════════════════════════════════════════════════════════

SHARP_KITAPLAR    = {"pinnacle", "betfair_ex_eu", "betfair"}
REFERANS_KITAPLAR = {
    "pinnacle": 3.0, "betfair_ex_eu": 2.5, "betfair": 2.5,
    "williamhill": 1.5, "bet365": 1.5, "unibet": 1.0,
    "bwin": 1.0, "marathonbet": 1.5,
}


def _bugun_yarin_filtresi(commence_time_str: str, gun: int = 7) -> bool:
    if not commence_time_str:
        return True
    try:
        mac_zamani = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
        simdi = datetime.now(timezone.utc)
        bitis = simdi + timedelta(days=gun)
        return simdi <= mac_zamani <= bitis
    except Exception:
        return True


def _mac_satiri(ev, dep, lig_kodu, lig_isim, ev_oran, ber_oran, dep_oran,
                fair_ev, fair_ber, fair_dep, over_round, kitap_sayisi,
                kitap_fark, pinnacle_var, sharp_ev_value, sharp_dep_value,
                commence, hareket_db, sharp=False, hakem="", over25_oran=0, under25_oran=0,
                btts_yes_oran=0, btts_no_oran=0, **kwargs):
    kitap_marji = (over_round - 1.0) * 100
    mac_key  = f"{ev}|{dep}|{str(commence)[:10]}"
    hareket  = _oran_hareketi_hesapla(mac_key, ev_oran, dep_oran, hareket_db)

    # ── CROSS-SECTIONAL SHARP MONEY ANALİZİ ──────────────────────────
    # Zaman serisi (hareket) + kitaplar arası fark (sharp_signal) birleşimi
    # İlk run'da bile sinyal üretir — Pinnacle vs soft kitap karşılaştırması
    sharp_data = {"sharp_sinyal": "YOK", "hareket_gucu": 0.0}
    kitap_oranlari = kwargs.get("kitap_oranlari")
    if kitap_oranlari and len(kitap_oranlari) >= 2:
        try:
            from data.sharp_signal import sharp_sinyal_hesapla
            sharp_data = sharp_sinyal_hesapla(kitap_oranlari, pinnacle_var)
        except Exception:
            pass

    # Öncelik: cross-sectional sinyal > zaman serisi hareket
    # Cross-sectional her zaman çalışır; zaman serisi sadece 2+ noktada
    final_sinyal = sharp_data.get("sharp_sinyal", "YOK")
    final_guc    = sharp_data.get("hareket_gucu", 0.0)
    # Eğer zaman serisi de sinyal üretmişse ve daha güçlüyse onu kullan
    if hareket["sharp_sinyal"] != "YOK" and hareket["hareket_gucu"] > final_guc:
        final_sinyal = hareket["sharp_sinyal"]
        final_guc    = hareket["hareket_gucu"]

    # ── GOAL MARKET SHARP ANALİZİ (2-way O/U ve BTTS) ─────────────
    ou_sharp   = {"sharp_sinyal": "YOK", "hareket_gucu": 0.0, "sharp_tier": "NO_SHARP", "max_fark": 0.0}
    btts_sharp = {"sharp_sinyal": "YOK", "hareket_gucu": 0.0, "sharp_tier": "NO_SHARP", "max_fark": 0.0}
    ou_oranlari_dict   = kwargs.get("ou_oranlari", {})
    btts_oranlari_dict = kwargs.get("btts_oranlari", {})

    if ou_oranlari_dict and len(ou_oranlari_dict) >= 2:
        try:
            from data.sharp_signal import sharp_sinyal_hesapla_2way
            ou_sharp = sharp_sinyal_hesapla_2way(
                ou_oranlari_dict, pinnacle_var,
                opt1_name="OVER", opt2_name="UNDER"
            )
        except Exception:
            pass

    if btts_oranlari_dict and len(btts_oranlari_dict) >= 2:
        try:
            from data.sharp_signal import sharp_sinyal_hesapla_2way
            btts_sharp = sharp_sinyal_hesapla_2way(
                btts_oranlari_dict, pinnacle_var,
                opt1_name="BTTS_YES", opt2_name="BTTS_NO"
            )
        except Exception:
            pass

    return {
        "ev": ev, "dep": dep,
        "lig": lig_kodu, "lig_isim": lig_isim,
        "ev_oran": ev_oran, "ber_oran": ber_oran, "dep_oran": dep_oran,
        "over25_oran": over25_oran, "under25_oran": under25_oran,
        "btts_yes_oran": btts_yes_oran, "btts_no_oran": btts_no_oran,
        "over_round": round(over_round, 4),
        "kitap_marji": round(kitap_marji, 2),
        "fair_ev": round(fair_ev, 4), "fair_ber": round(fair_ber, 4),
        "fair_dep": round(fair_dep, 4),
        "mac_tarihi": commence,
        "sharp": sharp,
        "kitap_sayisi": kitap_sayisi,
        "kitap_fark": kitap_fark,
        "pinnacle_var": pinnacle_var,
        "sharp_ev_value": sharp_ev_value,
        "sharp_dep_value": sharp_dep_value,
        "ev_hareket":    hareket["ev_hareket"],
        "dep_hareket":   hareket["dep_hareket"],
        "sharp_sinyal":  final_sinyal,
        "hareket_gucu":  final_guc,
        "ilk_ev_oran":   hareket.get("ilk_ev_oran",  ev_oran),
        "ilk_dep_oran":  hareket.get("ilk_dep_oran", dep_oran),
        "hakem":         hakem,
        "bf_ev_oran":    kwargs.get("bf_ev_oran"),
        "bf_dep_oran":   kwargs.get("bf_dep_oran"),
        "bf_ber_oran":   kwargs.get("bf_ber_oran"),
        # H2H Sharp
        "sharp_fark_ev":  sharp_data.get("sharp_fark_ev",  0.0),
        "sharp_fark_dep": sharp_data.get("sharp_fark_dep", 0.0),
        "sharp_kitap":    sharp_data.get("sharp_kitap",    ""),
        "sharp_tier":     sharp_data.get("sharp_tier",     "NO_SHARP"),
        "max_fark":       sharp_data.get("max_fark",       0.0),
        # Goal Market Sharp (YENİ)
        "ou_sharp_sinyal":   ou_sharp.get("sharp_sinyal", "YOK"),
        "ou_sharp_tier":     ou_sharp.get("sharp_tier", "NO_SHARP"),
        "ou_sharp_fark":     ou_sharp.get("max_fark", 0.0),
        "ou_sharp_guc":      ou_sharp.get("hareket_gucu", 0.0),
        "btts_sharp_sinyal": btts_sharp.get("sharp_sinyal", "YOK"),
        "btts_sharp_tier":   btts_sharp.get("sharp_tier", "NO_SHARP"),
        "btts_sharp_fark":   btts_sharp.get("max_fark", 0.0),
        "btts_sharp_guc":    btts_sharp.get("hareket_gucu", 0.0),
    }


# ══════════════════════════════════════════════════════════════
#  1. THE-ODDS-API
# ══════════════════════════════════════════════════════════════

def _cok_kitap_analiz(game: dict) -> dict:
    ev_adi  = game.get("home_team", "")
    dep_adi = game.get("away_team", "")
    kitap_oranlari = {}
    ou_oranlari = {}
    btts_oranlari = {}

    for bookmaker in game.get("bookmakers", []):
        bk_key = bookmaker.get("key", "").lower()
        ev_o = ber_o = dep_o = None
        o25 = u25 = b_yes = b_no = None
        
        for market in bookmaker.get("markets", []):
            m_key = market.get("key")
            if m_key == "totals":
                for outcome in market.get("outcomes", []):
                    if outcome.get("point") == 2.5:
                        if outcome.get("name") == "Over":
                            o25 = outcome.get("price")
                        elif outcome.get("name") == "Under":
                            u25 = outcome.get("price")
            elif m_key == "btts":
                for outcome in market.get("outcomes", []):
                    if outcome.get("name") == "Yes":
                        b_yes = outcome.get("price")
                    elif outcome.get("name") == "No":
                        b_no = outcome.get("price")
            elif m_key == "h2h":
                for outcome in market.get("outcomes", []):
                    isim  = outcome.get("name", "")
                    fiyat = outcome.get("price", 0)
                    if fiyat <= 1.0:
                        continue
                    if isim == ev_adi:
                        ev_o = fiyat
                    elif isim == dep_adi:
                        dep_o = fiyat
                    elif isim in ("Draw", "Beraberlik"):
                        ber_o = fiyat

        # H2H (Taraf) kaydet (Eski sistemin çökmemesi için)
        if ev_o and dep_o:
            kitap_oranlari[bk_key] = (ev_o, ber_o or 3.20, dep_o)
            
        # O/U kaydet
        if o25 and u25:
            ou_oranlari[bk_key] = (o25, u25)
            
        # BTTS kaydet
        if b_yes and b_no:
            btts_oranlari[bk_key] = (b_yes, b_no)

    if not kitap_oranlari:
        return None

    pinnacle_oran = None
    for sharp in ["pinnacle", "betfair_ex_eu", "betfair"]:
        if sharp in kitap_oranlari:
            pinnacle_oran = kitap_oranlari[sharp]
            break

    toplam_agirlik = agirlikli_ev = agirlikli_ber = agirlikli_dep = 0
    for kitap, (ev_o, ber_o, dep_o) in kitap_oranlari.items():
        agirlik = REFERANS_KITAPLAR.get(kitap, 0.8)
        agirlikli_ev  += (1/ev_o)  * agirlik
        agirlikli_ber += (1/ber_o) * agirlik
        agirlikli_dep += (1/dep_o) * agirlik
        toplam_agirlik += agirlik

    if toplam_agirlik == 0:
        return None

    ort_imp_ev  = agirlikli_ev  / toplam_agirlik
    ort_imp_ber = agirlikli_ber / toplam_agirlik
    ort_imp_dep = agirlikli_dep / toplam_agirlik
    toplam_imp  = ort_imp_ev + ort_imp_ber + ort_imp_dep

    ref_fair_ev  = ort_imp_ev  / toplam_imp
    ref_fair_ber = ort_imp_ber / toplam_imp
    ref_fair_dep = ort_imp_dep / toplam_imp

    if pinnacle_oran:
        pin_ev, pin_ber, pin_dep = pinnacle_oran
        pin_toplam = (1/pin_ev) + (1/pin_ber) + (1/pin_dep)
        ref_fair_ev  = (1/pin_ev)  / pin_toplam
        ref_fair_ber = (1/pin_ber) / pin_toplam
        ref_fair_dep = (1/pin_dep) / pin_toplam

    en_iyi_ev  = max(v[0] for v in kitap_oranlari.values())
    en_iyi_ber = max(v[1] for v in kitap_oranlari.values())
    en_iyi_dep = max(v[2] for v in kitap_oranlari.values())

    ev_oranlar  = [v[0] for v in kitap_oranlari.values()]
    kitap_fark  = (max(ev_oranlar) - min(ev_oranlar)) / min(ev_oranlar) if ev_oranlar else 0

    en_iyi_kitap_ev  = max(kitap_oranlari, key=lambda k: kitap_oranlari[k][0])
    en_iyi_kitap_dep = max(kitap_oranlari, key=lambda k: kitap_oranlari[k][2])
    sharp_ev_value   = any(s in en_iyi_kitap_ev  for s in SHARP_KITAPLAR)
    sharp_dep_value  = any(s in en_iyi_kitap_dep for s in SHARP_KITAPLAR)

    ort_ev  = sum(v[0] for v in kitap_oranlari.values()) / len(kitap_oranlari)
    ort_ber = sum(v[1] for v in kitap_oranlari.values()) / len(kitap_oranlari)
    ort_dep = sum(v[2] for v in kitap_oranlari.values()) / len(kitap_oranlari)
    over_round = (1/ort_ev) + (1/ort_ber) + (1/ort_dep)

    # O/U ve BTTS için en iyi oranları bul
    en_iyi_o25 = max([v[0] for v in ou_oranlari.values()]) if ou_oranlari else 0
    en_iyi_u25 = max([v[1] for v in ou_oranlari.values()]) if ou_oranlari else 0
    en_iyi_btts_yes = max([v[0] for v in btts_oranlari.values()]) if btts_oranlari else 0
    en_iyi_btts_no = max([v[1] for v in btts_oranlari.values()]) if btts_oranlari else 0

    return {
        "ev_oran": en_iyi_ev, "ber_oran": en_iyi_ber, "dep_oran": en_iyi_dep,
        "over25_oran": en_iyi_o25, "under25_oran": en_iyi_u25,
        "btts_yes_oran": en_iyi_btts_yes, "btts_no_oran": en_iyi_btts_no,
        "fair_ev": round(ref_fair_ev, 4), "fair_ber": round(ref_fair_ber, 4),
        "fair_dep": round(ref_fair_dep, 4),
        "over_round": round(over_round, 4),
        "kitap_sayisi": len(kitap_oranlari),
        "kitap_fark": round(kitap_fark, 3),
        "pinnacle_var": pinnacle_oran is not None,
        "sharp_ev_value": sharp_ev_value,
        "sharp_dep_value": sharp_dep_value,
        "kitap_oranlari": kitap_oranlari,
        "ou_oranlari": ou_oranlari,
        "btts_oranlari": btts_oranlari,
    }


def _sharp_mi(analiz: dict) -> bool:
    return analiz.get("pinnacle_var", False) or analiz.get("kitap_sayisi", 0) >= 4


def _the_odds_api_cek(gun: int, hareket_db: dict) -> list:
    if not ODDS_API_KEY or ODDS_API_KEY == "BURAYA_ODDS_API_KEY":
        return []

    tum_maclar = []
    atlanan    = []
    pinnacle_sayisi  = 0
    cok_kitap_sayisi = 0


    print("🔌 The-Odds-API'ye bağlanıyor (Anti-Ban & Retry Aktif)...")
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    
    # 3 defa artan bekleme süreleriyle (backoff_factor=1) otomatik tekrar deneme
    retry_strategy = Retry(
        total=3,
        backoff_factor=1.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/json"
    })


    for kod, bilgi in LIGLER.items():
        odds_key = bilgi["odds_key"]
        # ── Pinnacle dahil istek: bookmakers=pinnacle ile direkt çek ──
        # Bu yöntem Pinnacle'ın listede olup olmadığına bakmaksızın
        # kesinlikle Pinnacle oranlarını getirir.
        url = (
            f"https://api.the-odds-api.com/v4/sports/{odds_key}/odds/"
            f"?apiKey={ODDS_API_KEY}"
            f"&regions=eu,uk"
            f"&markets=h2h,totals"
            f"&oddsFormat=decimal"
        )
        try:
            r = session.get(url, verify=False, timeout=30)  # Timeout 10'dan 30'a uzatıldı (VPN Direnci)
        except Exception as e:
            print(f"  ⚠️  The-Odds-API bağlantı hatası (Timeout): {e}")
            continue

        kalan = r.headers.get("x-requests-remaining", "?")

        if r.status_code == 401:
            print("  ❌ The-Odds-API: Geçersiz API anahtarı.")
            return []
        if r.status_code == 422:
            atlanan.append(bilgi["isim"])
            continue
        if r.status_code == 429:
            print(f"  ⚠️  The-Odds-API: Rate limit (geçici) — 5 saniye bekleniyor...")
            import time as _t; _t.sleep(5)
            continue   # Bu liği atla, sonrakine geç
        if r.status_code != 200:
            print(f"  ⚠️  {bilgi['isim']}: HTTP {r.status_code}")
            continue

        try:
            data = r.json()
        except Exception:
            continue

        lig_mac = 0
        for game in data:
            if not isinstance(game, dict):
                continue
            commence = game.get("commence_time", "")
            if not _bugun_yarin_filtresi(commence, gun):
                continue
            ev  = game.get("home_team")
            dep = game.get("away_team")
            if not ev or not dep:
                continue

            analiz = _cok_kitap_analiz(game)
            if not analiz:
                continue

            if (analiz["over_round"] - 1.0) * 100 > 18.0:
                continue

            if analiz["pinnacle_var"]:
                pinnacle_sayisi += 1
            if analiz["kitap_sayisi"] >= 3:
                cok_kitap_sayisi += 1

            bf = analiz.get("kitap_oranlari", {}).get("betfair_ex_eu") or analiz.get("kitap_oranlari", {}).get("betfair")
            bf_ev, bf_ber, bf_dep = bf if bf else (None, None, None)

            satir = _mac_satiri(
                ev=ev, dep=dep,
                lig_kodu=kod, lig_isim=bilgi["isim"],
                ev_oran=analiz["ev_oran"], ber_oran=analiz["ber_oran"],
                dep_oran=analiz["dep_oran"],
                fair_ev=analiz["fair_ev"], fair_ber=analiz["fair_ber"],
                fair_dep=analiz["fair_dep"],
                over_round=analiz["over_round"],
                kitap_sayisi=analiz["kitap_sayisi"],
                kitap_fark=analiz["kitap_fark"],
                pinnacle_var=analiz["pinnacle_var"],
                sharp_ev_value=analiz["sharp_ev_value"],
                sharp_dep_value=analiz["sharp_dep_value"],
                commence=commence, hareket_db=hareket_db,
                sharp=_sharp_mi(analiz),
                hakem="",
                bf_ev_oran=bf_ev, bf_ber_oran=bf_ber, bf_dep_oran=bf_dep,
                over25_oran=analiz.get("over25_oran", 0),
                under25_oran=analiz.get("under25_oran", 0),
                btts_yes_oran=analiz.get("btts_yes_oran", 0),
                btts_no_oran=analiz.get("btts_no_oran", 0),
                kitap_oranlari=analiz.get("kitap_oranlari", {}),
                ou_oranlari=analiz.get("ou_oranlari", {}),
                btts_oranlari=analiz.get("btts_oranlari", {}),
            )
            tum_maclar.append(satir)
            lig_mac += 1

        if lig_mac > 0:
            print(f"  ✅ {bilgi['isim']}: {lig_mac} maç  (kalan: {kalan})")
        import time as _t; _t.sleep(0.3)  # Rate limit koruması

    if atlanan:
        print(f"  ℹ️  Atlandı (plan dışı): {', '.join(atlanan)}")
    if tum_maclar:
        print(f"  📊 Pinnacle referansı: {pinnacle_sayisi} maç  |  "
              f"Çok bahisçi (3+): {cok_kitap_sayisi} maç")
        print(f"  ✅ Toplam {len(tum_maclar)} maç oranı alındı — 24 saat cache'e kaydedildi")
    return tum_maclar


# ══════════════════════════════════════════════════════════════
#  2. API-FOOTBALL ODDS (ücretsiz fallback)
# ══════════════════════════════════════════════════════════════

def _api_football_oranlar(gun: int, hareket_db: dict) -> list:
    if not API_FOOTBALL_KEY or API_FOOTBALL_KEY.startswith("BURAYA") or len(API_FOOTBALL_KEY) < 32:
        return []

    headers      = {"x-apisports-key": API_FOOTBALL_KEY}
    tum_maclar   = []
    toplam_istek = 0

    print("🔌 API-Football bağlantısı hazırlanıyor...")
    session = get_working_session("https://v3.football.api-sports.io")

    for lig_kodu, bilgi in LIGLER.items():
        lig_id = bilgi.get("api_football_id")
        if not lig_id:
            continue

        sezon_yil = datetime.now().year
        url = f"{API_FOOTBALL_BASE}/odds?league={lig_id}&season={sezon_yil}&bookmaker=8&next=20"

        try:
            r = session.get(url, headers=headers, verify=False, timeout=15)
        except Exception as e:
            print(f"  ⚠️  API-Football {bilgi['isim']}: bağlantı hatası ({e})")
            continue

        toplam_istek += 1
        kalan = r.headers.get("x-ratelimit-requests-remaining", "?")

        if r.status_code == 401:
            print("  ❌ API-Football: Geçersiz API anahtarı.")
            return tum_maclar
        if r.status_code == 429:
            print(f"  ⚠️  API-Football: Günlük istek limiti doldu! (kalan: {kalan})")
            break
        if r.status_code != 200:
            continue

        try:
            data = r.json()
        except Exception:
            continue

        errors = data.get("errors", {})
        if errors:
            print(f"  ⚠️  API-Football {bilgi['isim']}: {errors}")
            continue

        fixtures = data.get("response", [])
        lig_mac  = 0

        for item in fixtures:
            try:
                fixture    = item["fixture"]
                teams      = item["teams"]
                bookmakers = item.get("bookmakers", [])
                ev_adi     = teams["home"]["name"]
                dep_adi    = teams["away"]["name"]
                tarih      = fixture.get("date", "")

                if not _bugun_yarin_filtresi(tarih, gun):
                    continue

                ev_o = ber_o = dep_o = None
                for bk in bookmakers:
                    for bet in bk.get("bets", []):
                        if bet.get("name") not in ("Match Winner", "1X2"):
                            continue
                        for v in bet.get("values", []):
                            val   = v.get("value", "")
                            price = float(v.get("odd", 0))
                            if price <= 1.0:
                                continue
                            if val == "Home":
                                ev_o  = price
                            elif val == "Draw":
                                ber_o = price
                            elif val == "Away":
                                dep_o = price

                if not ev_o or not dep_o:
                    continue

                ber_o = ber_o or 3.20
                imp_ev  = 1/ev_o
                imp_ber = 1/ber_o
                imp_dep = 1/dep_o
                toplam  = imp_ev + imp_ber + imp_dep
                over_round = toplam

                if over_round > 1.18:
                    continue

                fair_ev  = imp_ev  / toplam
                fair_ber = imp_ber / toplam
                fair_dep = imp_dep / toplam

                satir = _mac_satiri(
                    ev=ev_adi, dep=dep_adi,
                    lig_kodu=lig_kodu, lig_isim=bilgi["isim"],
                    ev_oran=ev_o, ber_oran=ber_o, dep_oran=dep_o,
                    fair_ev=fair_ev, fair_ber=fair_ber, fair_dep=fair_dep,
                    over_round=over_round,
                    kitap_sayisi=1, kitap_fark=0,
                    pinnacle_var=False,
                    sharp_ev_value=False, sharp_dep_value=False,
                    commence=tarih, hareket_db=hareket_db, sharp=False,
                    hakem=fixture.get("referee", "") or ""
                )
                tum_maclar.append(satir)
                lig_mac += 1

            except (KeyError, TypeError, ValueError):
                continue

        if lig_mac > 0:
            print(f"  ✅ [API-Football] {bilgi['isim']}: {lig_mac} maç  (kalan istek: {kalan})")

    print(f"  📊 API-Football toplam: {len(tum_maclar)} maç  ({toplam_istek} istek kullanıldı)")
    return tum_maclar


# ══════════════════════════════════════════════════════════════
#  3. BETEXPLORER SCRAPER (YENİ — ücretsiz gerçek oranlar)
# ══════════════════════════════════════════════════════════════

def _betexplorer_oranlar(gun: int, hareket_db: dict) -> list:
    """
    Betexplorer.com'dan JSON API ile oran çeker.
    Kayıt gerekmez, tamamen ücretsiz.
    Bet365, William Hill, Pinnacle oranlarını barındırır.
    """
    tum_maclar = []

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.betexplorer.com/",
    }

    print("🔌 Betexplorer bağlantısı hazırlanıyor...")
    session = get_working_session("https://www.betexplorer.com")

    for lig_kodu, yol in BETEXPLORER_LIGLER.items():
        bilgi    = LIGLER.get(lig_kodu, {})
        lig_isim = bilgi.get("isim", lig_kodu)

        url = f"https://www.betexplorer.com/soccer-api/{yol}/next/"

        try:
            r = session.get(url, headers=headers, verify=False, timeout=12)
        except Exception:
            continue

        if r.status_code != 200:
            continue

        try:
            data = r.json()
        except Exception:
            continue

        maclar_raw = data.get("matches", data.get("data", []))
        lig_mac = 0

        for mac in maclar_raw:
            try:
                ev_adi  = mac.get("home-name", mac.get("home", ""))
                dep_adi = mac.get("away-name", mac.get("away", ""))
                tarih   = mac.get("start-utc", mac.get("start", ""))

                if not ev_adi or not dep_adi:
                    continue

                odds  = mac.get("odds", {})
                ev_o  = float(odds.get("1", 0) or 0)
                ber_o = float(odds.get("X", 0) or 0)
                dep_o = float(odds.get("2", 0) or 0)

                if ev_o == 0:
                    ev_o  = float(mac.get("odd1", 0) or 0)
                    ber_o = float(mac.get("oddX", 0) or 0)
                    dep_o = float(mac.get("odd2", 0) or 0)

                if ev_o < 1.01 or dep_o < 1.01:
                    continue

                ber_o = ber_o if ber_o > 1.01 else 3.30

                imp_ev  = 1/ev_o
                imp_ber = 1/ber_o
                imp_dep = 1/dep_o
                toplam  = imp_ev + imp_ber + imp_dep
                over_round = toplam

                if over_round > 1.20:
                    continue

                fair_ev  = imp_ev  / toplam
                fair_ber = imp_ber / toplam
                fair_dep = imp_dep / toplam

                satir = _mac_satiri(
                    ev=ev_adi, dep=dep_adi,
                    lig_kodu=lig_kodu, lig_isim=lig_isim,
                    ev_oran=ev_o, ber_oran=ber_o, dep_oran=dep_o,
                    fair_ev=fair_ev, fair_ber=fair_ber, fair_dep=fair_dep,
                    over_round=over_round,
                    kitap_sayisi=1, kitap_fark=0,
                    pinnacle_var=False,
                    sharp_ev_value=False, sharp_dep_value=False,
                    commence=str(tarih), hareket_db=hareket_db, sharp=False,
                )
                tum_maclar.append(satir)
                lig_mac += 1

            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                continue

        if lig_mac > 0:
            print(f"  ✅ [Betexplorer] {lig_isim}: {lig_mac} maç")

    if tum_maclar:
        print(f"  📊 Betexplorer toplam: {len(tum_maclar)} maç oranı alındı")
    return tum_maclar


# ══════════════════════════════════════════════════════════════
#  4. GELİŞMİŞ FOOTBALL-DATA FALLBACK
#     (ELO + Poisson + Form hibrit — daha güvenilir tahmini oran)
# ══════════════════════════════════════════════════════════════

def _gelismis_elo_oran(ev_adi: str, dep_adi: str, elo_sonuclari: dict,
                       istatistikler: dict, lig_ortalamalari: dict,
                       lig_kodu: str) -> dict:
    """
    ELO + gol ortalaması + form birleşik model.
    Tek ELO'ya göre çok daha gerçekçi oran üretir.
    """
    import math

    ev_elo  = elo_sonuclari.get(ev_adi,  {}).get("elo", 1500)
    dep_elo = elo_sonuclari.get(dep_adi, {}).get("elo", 1500)
    fark = ev_elo - dep_elo + 65
    ev_beklenti_elo  = 1 / (1 + 10 ** (-fark / 400))
    dep_beklenti_elo = 1 - ev_beklenti_elo

    ev_p_tahmin  = ev_beklenti_elo
    dep_p_tahmin = dep_beklenti_elo
    ber_p_tahmin = 0.26

    ev_ist  = istatistikler.get(ev_adi, {})
    dep_ist = istatistikler.get(dep_adi, {})

    if ev_ist and dep_ist:
        lig_ort     = lig_ortalamalari.get(lig_kodu, {})
        lig_gol_ort = lig_ort.get("gol_ort", 1.4)

        ev_hucum    = ev_ist.get("ev_gol_ort",    lig_gol_ort)
        ev_savunma  = ev_ist.get("ev_yenilen_ort", lig_gol_ort)
        dep_hucum   = dep_ist.get("dep_gol_ort",  lig_gol_ort)
        dep_savunma = dep_ist.get("dep_yenilen_ort", lig_gol_ort)

        lambda_ev  = ev_hucum  * dep_savunma / max(lig_gol_ort, 0.01)
        lambda_dep = dep_hucum * ev_savunma  / max(lig_gol_ort, 0.01)

        def poisson_p(lam, k):
            return (lam**k * math.exp(-lam)) / math.factorial(k)

        ev_kazanir = dep_kazanir = berabere = 0.0
        for i in range(8):
            for j in range(8):
                p = poisson_p(lambda_ev, i) * poisson_p(lambda_dep, j)
                if i > j:
                    ev_kazanir += p
                elif i < j:
                    dep_kazanir += p
                else:
                    berabere += p

        kalan = 1 - ev_kazanir - dep_kazanir - berabere
        ev_kazanir  += kalan * 0.33
        dep_kazanir += kalan * 0.33
        berabere    += kalan * 0.34

        ev_p_tahmin  = 0.5 * ev_beklenti_elo  + 0.5 * ev_kazanir
        dep_p_tahmin = 0.5 * dep_beklenti_elo + 0.5 * dep_kazanir
        ber_p_tahmin = max(0.10, min(0.38, berabere))

    toplam = ev_p_tahmin + ber_p_tahmin + dep_p_tahmin
    ev_p  = ev_p_tahmin  / toplam
    ber_p = ber_p_tahmin / toplam
    dep_p = dep_p_tahmin / toplam

    marj = 1.05
    return {
        "ev_oran":     round(marj / ev_p,  2),
        "ber_oran":    round(marj / ber_p, 2),
        "dep_oran":    round(marj / dep_p, 2),
        "fair_ev":     round(ev_p,  4),
        "fair_ber":    round(ber_p, 4),
        "fair_dep":    round(dep_p, 4),
        "over_round":  round(marj,  4),
        "kitap_marji": round((marj - 1) * 100, 2),
    }


def _football_data_yaklaşan_maclar(gun: int = 7) -> list:
    if not FOOTBALL_DATA_API_KEY or FOOTBALL_DATA_API_KEY.startswith("BURAYA"):
        return []

    headers   = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    simdi     = datetime.now(timezone.utc)
    date_from = simdi.strftime("%Y-%m-%d")
    date_to   = (simdi + timedelta(days=gun)).strftime("%Y-%m-%d")

    elo_sonuclari    = {}
    istatistikler    = {}
    lig_ortalamalari = {}
    try:
        from features.elo       import elo_hesapla
        from features.team_stats import istatistik_hesapla, lig_ortalamasi_hesapla
        from data.matches        import veri_yukle
        ham_veri         = veri_yukle()
        elo_sonuclari    = elo_hesapla(ham_veri)
        istatistikler    = istatistik_hesapla()
        lig_ortalamalari = lig_ortalamasi_hesapla(istatistikler)
    except Exception:
        pass

    hareket_db = _hareket_yukle()
    tum_maclar = []

    for lig_kodu, bilgi in LIGLER.items():
        if not bilgi.get("football_data", True):
            continue
        url = (
            f"https://api.football-data.org/v4/competitions/{lig_kodu}/matches"
            f"?status=SCHEDULED&dateFrom={date_from}&dateTo={date_to}"
        )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = requests.get(url, headers=headers, verify=False, timeout=15)
        except Exception:
            continue
        if r.status_code != 200:
            continue
        try:
            maclar = r.json().get("matches", [])
        except Exception:
            continue

        lig_mac = 0
        for mac in maclar:
            try:
                ev_adi  = mac["homeTeam"]["name"]
                dep_adi = mac["awayTeam"]["name"]
                tarih   = mac.get("utcDate", "")
            except (KeyError, TypeError):
                continue

            oran = _gelismis_elo_oran(
                ev_adi, dep_adi,
                elo_sonuclari, istatistikler,
                lig_ortalamalari, lig_kodu
            )

            tum_maclar.append({
                "ev": ev_adi, "dep": dep_adi,
                "lig": lig_kodu, "lig_isim": bilgi["isim"],
                "mac_tarihi": tarih,
                "sharp": False, "kitap_sayisi": 0, "kitap_fark": 0,
                "pinnacle_var": False, "sharp_ev_value": False, "sharp_dep_value": False,
                "ev_hareket": 0, "dep_hareket": 0,
                "sharp_sinyal": "YOK", "hareket_gucu": 0,
                "ilk_ev_oran": oran["ev_oran"], "ilk_dep_oran": oran["dep_oran"],
                **oran,
            })
            lig_mac += 1

        if lig_mac > 0:
            print(f"  📅 [Football-data] {bilgi['isim']}: {lig_mac} yaklaşan maç (hibrit model)")

    return tum_maclar


# ══════════════════════════════════════════════════════════════
#  DEMO ORANLAR (son çare)
# ══════════════════════════════════════════════════════════════

def _demo_oranlar():
    yarinki_tarih = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT20:00:00Z")
    return [
        {"ev": "Arsenal FC", "dep": "Chelsea FC", "lig": "PL", "lig_isim": "Premier League",
         "ev_oran": 2.10, "ber_oran": 3.40, "dep_oran": 3.20, "over_round": 1.04,
         "kitap_marji": 4.0, "fair_ev": 0.46, "fair_ber": 0.28, "fair_dep": 0.30,
         "mac_tarihi": yarinki_tarih, "sharp": False, "kitap_sayisi": 1, "kitap_fark": 0,
         "pinnacle_var": False, "sharp_ev_value": False, "sharp_dep_value": False,
         "ev_hareket": 0, "dep_hareket": 0, "sharp_sinyal": "YOK", "hareket_gucu": 0,
         "ilk_ev_oran": 2.10, "ilk_dep_oran": 3.20},
    ]



# ══════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════
#  6. SPORTMONKS (Yeni Entegrasyon)
# ══════════════════════════════════════════════════════════════

SPORTMONKS_LIG_MAP = {
    "PL": 8, "PD": 564, "BL1": 82, "SA": 384, "FL1": 301,
    "DED": 72, "PPL": 462, "CL": 2, "EL": 5, "TSL": 600
}

def _sportmonks_oranlar(gun: int, hareket_db: dict) -> list:
    if not SPORTMONKS_API_KEY or len(SPORTMONKS_API_KEY) < 10:
        return []

    print("🔌 Sportmonks API'ye bağlanıyor...")
    tum_maclar = []
    
    for lig_kodu, sm_id in SPORTMONKS_LIG_MAP.items():
        bilgi = LIGLER.get(lig_kodu)
        if not bilgi: continue
        
        url = f"https://api.sportmonks.com/v3/football/fixtures?api_token={SPORTMONKS_API_KEY}&include=odds;participants;league&filters=fixtureLeagues:{sm_id}"
        try:
            # Sportmonks v3: include parametreleri virgülle ayrılır
            # filters: lig filtresi
            r = requests.get(url, verify=False, timeout=20)
            if r.status_code != 200:
                continue
            data = r.json().get("data", [])
            if not data:
                continue
            
            for fixture in data:
                participants = fixture.get("participants", [])
                if len(participants) < 2: continue
                
                ev_adi = participants[0].get("name", "Unknown")
                dep_adi = participants[1].get("name", "Unknown")
                tarih = fixture.get("starting_at")
                
                if not _bugun_yarin_filtresi(tarih, gun): 
                    continue
                
                # Odds ayıklama logic (Market 1 = 1X2)
                odds_data = fixture.get("odds", [])
                ev_o = ber_o = dep_o = None
                
                # Sportmonks v3 odds yapısı nested olabilir
                for market in odds_data:
                    # Market ID 1 genelde Fulltime Result (1X2)
                    if market.get("market_id") == 1 or "Fulltime Result" in str(market.get("name")):
                        for selection in market.get("selections", []):
                            label = str(selection.get("label")).upper()
                            val = float(selection.get("value", 0))
                            if val <= 1.0: continue
                            
                            if label in ("1", "HOME"): ev_o = val
                            elif label in ("X", "DRAW"): ber_o = val
                            elif label in ("2", "AWAY"): dep_o = val
                
                if ev_o and dep_o:
                    ber_o = ber_o or 3.20
                    toplam = (1/ev_o) + (1/ber_o) + (1/dep_o)
                    tum_maclar.append(_mac_satiri(
                        ev=ev_adi, dep=dep_adi, lig_kodu=lig_kodu, lig_isim=bilgi["isim"],
                        ev_oran=ev_o, ber_oran=ber_o, dep_oran=dep_o,
                        fair_ev=(1/ev_o)/toplam, fair_ber=(1/ber_o)/toplam, fair_dep=(1/dep_o)/toplam,
                        over_round=toplam, kitap_sayisi=1, kitap_fark=0, pinnacle_var=False,
                        sharp_ev_value=False, sharp_dep_value=False, commence=tarih, hareket_db=hareket_db
                    ))
        except Exception as e:
            print(f"  ⚠️ Sportmonks {bilgi['isim']} hatası: {e}")
            
    if tum_maclar:
        print(f"  📊 Sportmonks toplam: {len(tum_maclar)} maç oranı alındı")
    return tum_maclar


#  ANA FONKSİYON
# ══════════════════════════════════════════════════════════════

def canli_oranlar_cek(gun: int = None, zorla_yenile: bool = False) -> list:
    if gun is None:
        gun = ODDS_GUN_PENCERESI

    if zorla_yenile:
        _cache_temizle()
    elif _cache_guncelse_mi():
        return _cache_oku()

    hareket_db = _hareket_yukle()

    # ── 1. The-Odds-API ──────────────────────────────────────
    tum_maclar = _the_odds_api_cek(gun, hareket_db)
    if tum_maclar:
        _hareket_kaydet(hareket_db)
        _cache_yaz(tum_maclar, kaynak="the-odds-api")
        return tum_maclar

    # ── 2. SPORTMONKS (YENİ ÖNCELİK) ──────────────────────────
    print("  ℹ️  The-Odds-API kullanılamıyor — Sportmonks deneniyor...")
    tum_maclar = _sportmonks_oranlar(gun, hareket_db)
    if tum_maclar:
        _hareket_kaydet(hareket_db)
        _cache_yaz(tum_maclar, kaynak="sportmonks")
        print(f"  ✅ Sportmonks: {len(tum_maclar)} maç oranı alındı")
        return tum_maclar

    # ── 3. API-Football ──────────────────────────────────────

    # ── 3. Betexplorer (ücretsiz gerçek oranlar) ─────────────
    print("  ℹ️  API-Football kullanılamıyor — Betexplorer deneniyor...")
    tum_maclar = _betexplorer_oranlar(gun, hareket_db)
    if tum_maclar:
        _hareket_kaydet(hareket_db)
        _cache_yaz(tum_maclar, kaynak="betexplorer")
        print(f"  ✅ Betexplorer: {len(tum_maclar)} maç oranı alındı — cache'e kaydedildi")
        return tum_maclar

    # ── 4. Football-data + Hibrit Model ──────────────────────
    print("  ⚠️  Betexplorer kullanılamadı — football-data hibrit model deneniyor...")
    fallback = _football_data_yaklaşan_maclar(gun)
    if fallback:
        print(f"  ✅ Fallback: {len(fallback)} yaklaşan maç (ELO+Poisson hibrit oranlarla)")
        _cache_yaz(fallback, kaynak="football-data-hibrit")
        return fallback

    # ── 5. Demo ──────────────────────────────────────────────
    print("  ⚠️  Tüm kaynaklar başarısız — demo oranlar kullanılıyor.")
    return _demo_oranlar()