# scrapers/mac_verisi.py
"""
Maç Verisi Çekici — ÇOK SEZONLU VERSİYON
══════════════════════════════════════════════════════════════
DEĞİŞİKLİKLER:
  • Sadece bu sezon değil, 3 sezon birden çekiliyor
    (2023, 2024, 2025 → ~1500-2000 maç/lig yerine 400-700)
  • Sezon cache'i: her sezon ayrı dosyada saklanır
    - Biten sezonlar (2023, 2024) → bir kez çekilir, tekrar çekilmez
    - Aktif sezon (2025) → her gün güncellenir
  • football_data: False olan ligler atlanır
  • Hata yönetimi: 429 (rate limit) için bekleme eklendi
  • Veri kalitesi: score=None olan maçlar temizlenir

SEZON MANTIĞI:
  football-data.org'da sezon yılı = başlangıç yılı
  2023 → 2023-24 sezonu
  2024 → 2024-25 sezonu
  2025 → 2025-26 sezonu (aktif)
"""

import requests
import json
import os
import time
import warnings
from datetime import datetime
from config.settings import FOOTBALL_DATA_API_KEY, LIGLER
from data.proxy import get_working_session

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.path.join(BASE_DIR, "data")
DATA_PATH  = os.path.join(DATA_DIR, "maclar.json")          # birleşik veri
CACHE_DIR  = os.path.join(DATA_DIR, "sezon_cache")          # sezon başına ayrı cache

# Çekilecek sezonlar — biten sezonlar bir kez çekilir, aktif sezon her gün güncellenir
AKTIF_SEZON   = 2026
GECMIS_SEZONLAR = [2023, 2024, 2025]   # bu sezonlar bir kez çekilip cache'e yazılır


warnings.filterwarnings("ignore", message="Unverified HTTPS request")


# ══════════════════════════════════════════════════════════════
#  CACHE YÖNETİMİ
# ══════════════════════════════════════════════════════════════

def _sezon_cache_yolu(lig_kodu: str, sezon: int) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{lig_kodu}_{sezon}.json")


def _sezon_cache_var_mi(lig_kodu: str, sezon: int) -> bool:
    """Geçmiş sezon zaten çekilmiş mi? Varsa tekrar çekme."""
    if sezon == AKTIF_SEZON:
        # Aktif sezon için bugün çekilmiş mi kontrol et
        yol = _sezon_cache_yolu(lig_kodu, sezon)
        if not os.path.exists(yol):
            return False
        try:
            with open(yol, "r", encoding="utf-8") as f:
                cache = json.load(f)
            cekilen_zaman = cache.get("tarih_saat", cache.get("tarih", ""))
            if not cekilen_zaman: return False
            try:
                # Force refresh if it is the old cache format so it fetches today's latest data
                if len(cekilen_zaman) == 10:
                    return False
                # Handle new cache format (YYYY-MM-DD HH:MM:SS)
                cekilen_dt = datetime.strptime(cekilen_zaman, "%Y-%m-%d %H:%M:%S")
                fark_saat = (datetime.now() - cekilen_dt).total_seconds() / 3600
                return fark_saat < 3.0 # 3 saatte bir yenile
            except Exception:
                return False
        except Exception as e:
            print(f"  ⚠️  [mac_verisi] Geçmiş sezon okuma hatası: {e}")
            return False
    else:
        # Geçmiş sezon — dosya varsa yeter, tekrar çekme
        return os.path.exists(_sezon_cache_yolu(lig_kodu, sezon))


def _sezon_cache_oku(lig_kodu: str, sezon: int) -> list:
    yol = _sezon_cache_yolu(lig_kodu, sezon)
    try:
        with open(yol, "r", encoding="utf-8") as f:
            cache = json.load(f)
        return cache.get("maclar", [])
    except Exception as e:
        print(f"  ⚠️  [mac_verisi] Sezon cache okuma hatası: {e}")
        return []


def _sezon_cache_yaz(lig_kodu: str, sezon: int, maclar: list):
    if not maclar:
        return
    yol = _sezon_cache_yolu(lig_kodu, sezon)
    try:
        with open(yol, "w", encoding="utf-8") as f:
            json.dump({
                "lig":    lig_kodu,
                "sezon":  sezon,
                "tarih":  datetime.now().strftime("%Y-%m-%d"),
                "tarih_saat": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "maclar": maclar,
            }, f, ensure_ascii=False)
    except Exception as e:
        print(f"  ⚠️  [mac_verisi] Sezon cache yazma hatası: {e}")
        pass


# ══════════════════════════════════════════════════════════════
#  VERİ TEMİZLEME
# ══════════════════════════════════════════════════════════════

def _mac_gecerli_mi(mac: dict) -> bool:
    """Skoru eksik veya None olan maçları filtrele."""
    try:
        ev_g  = mac["score"]["fullTime"]["home"]
        dep_g = mac["score"]["fullTime"]["away"]
        return ev_g is not None and dep_g is not None
    except (KeyError, TypeError):
        return False


def _mac_temizle(maclar: list) -> list:
    """Sadece tamamlanmış, geçerli skorlu maçları al."""
    return [m for m in maclar if _mac_gecerli_mi(m)]


# ══════════════════════════════════════════════════════════════
#  API ÇEKME
# ══════════════════════════════════════════════════════════════

def _lig_sezon_cek(lig_kodu: str, sezon: int, headers: dict, session: requests.Session) -> list | None:
    """
    Tek bir lig + sezon için API isteği atar.
    Dönüş: maç listesi | None (hata)
    """
    url = (f"https://api.football-data.org/v4/competitions/{lig_kodu}/matches"
           f"?status=FINISHED&season={sezon}")
    try:
        r = session.get(url, headers=headers, verify=False, timeout=20)
    except Exception as e:
        print(f"      ⚠️  Bağlantı hatası: {e}")
        return None

    if r.status_code == 200:
        maclar = r.json().get("matches", [])
        return _mac_temizle(maclar)
    elif r.status_code == 429:
        print(f"      ⏳ Rate limit (429) — {lig_kodu} için 65 saniye bekleniyor...")
        time.sleep(65)
        try:
            r2 = session.get(url, headers=headers, verify=False, timeout=20)
            if r2.status_code == 200:
                maclar = r2.json().get("matches", [])
                return _mac_temizle(maclar)
            elif r2.status_code == 429:
                print(f"      ❌ İkinci denemede de rate limit! Sezon atlanıyor...")
        except Exception as e:
            print(f"      ⚠️  [mac_verisi] Tekrar deneme hatası: {e}")
        return None
    elif r.status_code in (403, 422):
        # Ücretsiz planda bu lig/sezon yok
        return []
    else:
        print(f"      ⚠️  HTTP {r.status_code}")
        return None


# ══════════════════════════════════════════════════════════════
#  ANA FONKSİYON
# ══════════════════════════════════════════════════════════════

def mac_verisi_cek():
    os.makedirs(DATA_DIR, exist_ok=True)

    if not FOOTBALL_DATA_API_KEY or FOOTBALL_DATA_API_KEY == "BURAYA_FOOTBALL_DATA_API_KEY":
        if os.path.exists(DATA_PATH):
            print("  ℹ️  API anahtarı yok — mevcut veri kullanılıyor.")
        else:
            _ornek_veri_olustur()
        return

    headers    = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    tum_maclar = {}   # {lig_kodu: [maç, maç, ...]}
    toplam     = 0
    atlanan    = []
    tum_sezonlar = GECMIS_SEZONLAR + [AKTIF_SEZON]

    print("🔌 API bağlantısı hazırlanıyor...")
    session = get_working_session("https://api.football-data.org/v4/")
    
    try:
        from data.collectors.csv_collector import csv_sezon_cek
    except ImportError:
        csv_sezon_cek = None

    for lig_kodu, bilgi in LIGLER.items():
        lig_maclar = []
        cache_sayisi = 0
        api_sayisi   = 0

        kullan_api = bilgi.get("football_data", True)

        # Çok fazla lig/sezon olduğu için API sınırını aşmamak adına dinamik bekleme
        bekleme_suresi = 6.5 # football-data dakikada 10 istek kabul eder = 6 saniye per istek
        
        for sezon in tum_sezonlar:
            if _sezon_cache_var_mi(lig_kodu, sezon):
                mac = _sezon_cache_oku(lig_kodu, sezon)
                if mac:
                    is_bugun = "bugün" if sezon == AKTIF_SEZON else ""
                    print(f"  📂 [CACHE] {bilgi['isim']:<18} ({sezon}): {len(mac)} maç {is_bugun}")
                    lig_maclar.extend(mac)
                    cache_sayisi += len(mac)
                continue

            if kullan_api:
                print(f"  🌐 [API]   {bilgi['isim']:<18} ({sezon}) çekiliyor...")
                mac = _lig_sezon_cek(lig_kodu, sezon, headers, session)
                time.sleep(bekleme_suresi)
            else:
                if csv_sezon_cek:
                    print(f"  🌐 [CSV]   {bilgi['isim']:<18} ({sezon}) çekiliyor (CSV)...")
                    mac = csv_sezon_cek(lig_kodu, sezon)
                else:
                    mac = None

            if mac:
                _sezon_cache_yaz(lig_kodu, sezon, mac)
                lig_maclar.extend(mac)
                api_sayisi += len(mac)
                print(f"        └─ Başarılı: {len(mac)} maç.")
            else:
                print(f"        └─ Başarısız: veri yok.")
                if not kullan_api and not csv_sezon_cek:
                    if bilgi["isim"] not in atlanan:
                        atlanan.append(bilgi["isim"])

        if lig_maclar:
            tum_maclar[lig_kodu] = lig_maclar
            toplam += len(lig_maclar)
            cache_str = f" (cache: {cache_sayisi}, API: {api_sayisi})" if api_sayisi > 0 else f" (cache: {cache_sayisi})"
            print(f"  ✅ {bilgi['isim']}: {len(lig_maclar)} maç{cache_str}")

    if atlanan:
        print(f"  ℹ️  Atlandı (football_data:False veya ücretsiz plan): {', '.join(atlanan)}")

    if tum_maclar:
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(tum_maclar, f, ensure_ascii=False, indent=2)
        print(f"\n  📁 Toplam {toplam} maç verisi kaydedildi.")
    else:
        print("  ⚠️  Hiç veri çekilemedi — mevcut veri kullanılıyor.")
        if not os.path.exists(DATA_PATH):
            _ornek_veri_olustur()


def veri_yukle() -> dict:
    if not os.path.exists(DATA_PATH):
        _ornek_veri_olustur()
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _ornek_veri_olustur():
    ornek = {
        "PL": [
            {"homeTeam": {"name": "Arsenal FC"}, "awayTeam": {"name": "Chelsea FC"},
             "score": {"fullTime": {"home": 2, "away": 1}, "halfTime": {"home": 1, "away": 0}},
             "utcDate": "2025-01-15T20:00:00Z"},
            {"homeTeam": {"name": "Manchester City FC"}, "awayTeam": {"name": "Liverpool FC"},
             "score": {"fullTime": {"home": 3, "away": 1}, "halfTime": {"home": 1, "away": 1}},
             "utcDate": "2025-01-22T20:00:00Z"},
        ]
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(ornek, f, ensure_ascii=False, indent=2)
    print("  ℹ️  Örnek maç verisi oluşturuldu.")