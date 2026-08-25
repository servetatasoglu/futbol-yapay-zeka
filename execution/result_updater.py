# analysis/sonuc_guncelle.py
import csv
import os
import json
import time
import requests
import warnings
from datetime import datetime, timezone, timedelta
from config.settings import FOOTBALL_DATA_API_KEY, LIGLER

LOG_FILE   = os.path.join("logs", "tahminler_log.csv")
CACHE_PATH = os.path.join("data", "sonuc_cache.json")
CACHE_DAKIKA = 720  # Football-Data API günde 10 istek limiti — API israfını önlemek için 12 saatte bir yenilenir


# ── Cache Sistemi ──────────────────────────────────────────────

def _cache_guncelse_mi() -> bool:
    if not os.path.exists(CACHE_PATH):
        return False
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        gecen_dakika = (time.time() - cache.get("zaman", 0)) / 60
        return gecen_dakika < CACHE_DAKIKA
    except Exception as e:
        print(f"  ⚠️  [sonuc_guncelle] Cache okuma hatası: {e}")
        return False


def _cache_oku() -> dict:
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            cache = json.load(f)
        gecen = int((time.time() - cache.get("zaman", 0)) / 60)
        print(f"  ♻️  Sonuç cache kullanılıyor ({gecen} dakika önce çekildi — API isteği korundu)")
        return cache.get("sonuclar", {})
    except Exception as e:
        print(f"  ⚠️  [sonuc_guncelle] API dilleri çekilirken hata: {e}")
        return {}


def _cache_yaz(sonuclar: dict):
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"zaman": time.time(), "sonuclar": sonuclar}, f, ensure_ascii=False)
    except Exception as e:
        print(f"  ⚠️  [sonuc_guncelle] Cache yazma hatası: {e}")
        pass


# ── API ────────────────────────────────────────────────────────

def _api_sonuclari_cek() -> dict:
    if not FOOTBALL_DATA_API_KEY or FOOTBALL_DATA_API_KEY == "BURAYA_FOOTBALL_DATA_API_KEY":
        print("  ⚠️  API anahtarı yok — otomatik güncelleme yapılamıyor.")
        return {}

    # Cache varsa API'ye gitme
    if _cache_guncelse_mi():
        return _cache_oku()

    headers  = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    sonuclar = {}

    for lig_kodu in LIGLER:
        url = f"https://api.football-data.org/v4/competitions/{lig_kodu}/matches?status=FINISHED"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                r = requests.get(url, headers=headers, verify=False, timeout=15)
        except Exception as e:
            print(f"  ⚠️  {lig_kodu} sonuçları çekilemedi: {e}")
            continue

        if r.status_code != 200:
            continue

        for mac in r.json().get("matches", []):
            try:
                ev   = mac["homeTeam"]["name"]
                dep  = mac["awayTeam"]["name"]
                ev_g = int(mac["score"]["fullTime"]["home"])
                dp_g = int(mac["score"]["fullTime"]["away"])

                mac_tarihi_str = mac.get("utcDate", "")
                if mac_tarihi_str:
                    mac_tarihi = datetime.fromisoformat(
                        mac_tarihi_str.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                else:
                    mac_tarihi = None

            except (KeyError, TypeError, ValueError):
                continue

            if ev_g > dp_g:    sonuc = "ev"
            elif ev_g == dp_g: sonuc = "ber"
            else:              sonuc = "dep"

            tarih_kisa = mac_tarihi.strftime("%Y-%m-%d") if mac_tarihi else ""
            sonuclar[f"{ev}||{dep}"] = {
                "sonuc": sonuc,
                "tarih": tarih_kisa,
                "ev_gol": ev_g,      # O/U ve BTTS doğrulaması için
                "dep_gol": dp_g,     # O/U ve BTTS doğrulaması için
            }

    print(f"  ✅ API'den {len(sonuclar)} maç sonucu alındı — cache'e kaydedildi")
    _cache_yaz(sonuclar)
    return sonuclar


# ── Yardımcı Fonksiyonlar ──────────────────────────────────────

def _mac_tarihi_parse(tarih_str: str):
    """ISO 8601 veya DD.MM.YYYY formatındaki tarihi datetime'a çevirir."""
    if not tarih_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S+00:00", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
        try:
            return datetime.strptime(tarih_str.strip()[:19], fmt[:len(tarih_str.strip()[:19])])
        except ValueError:
            continue
    return None


def _isim_eslesir(log_ev: str, log_dep: str, api_sonuclar: dict, mac_tarihi_log=None):
    """
    Takım adı + tarih doğrulaması ile eşleştirme yapar.
    Gelecekteki maçlara veya tarihi belirsiz maçlara sonuç ATAMAZ.
    """
    bugun = datetime.utcnow().date()

    # MacTarihi bilgisi yoksa (eski kayıtlar) — tarihe bakmadan eşleştirmeyi dene
    if mac_tarihi_log is not None and mac_tarihi_log.date() > bugun:
        return None

    def _api_tarihi_gecmiste(api_tarih_str: str) -> bool:
        if not api_tarih_str:
            return False
        try:
            return datetime.strptime(api_tarih_str, "%Y-%m-%d").date() <= bugun
        except ValueError:
            return False

    # Tam eşleşme
    anahtar = f"{log_ev}||{log_dep}"
    if anahtar in api_sonuclar:
        kayit = api_sonuclar[anahtar]
        # MacTarihi yoksa (eski kayıt) tarih kontrolü atlansın
        if mac_tarihi_log is None or _api_tarihi_gecmiste(kayit.get("tarih", "")):
            return kayit["sonuc"]
        return None

    # Bulanık eşleştirme
    for api_anahtar, kayit in api_sonuclar.items():
        api_ev, api_dep = api_anahtar.split("||")
        if (log_ev in api_ev or api_ev in log_ev) and \
           (log_dep in api_dep or api_dep in log_dep):
            if mac_tarihi_log is None or _api_tarihi_gecmiste(kayit.get("tarih", "")):
                return kayit["sonuc"]

    return None


# ── Ana Fonksiyon ──────────────────────────────────────────────

def sonuclari_guncelle(log_dosyasi: str = LOG_FILE) -> int:
    if not os.path.exists(log_dosyasi):
        print(f"  ⚠️  Log dosyası bulunamadı: {log_dosyasi}")
        return 0

    print("\n🔄 Maç sonuçları güncelleniyor...")
    api_sonuclar = _api_sonuclari_cek()
    if not api_sonuclar:
        return 0

    with open(log_dosyasi, "r", encoding="utf-8") as f:
        reader     = csv.DictReader(f)
        satirlar   = list(reader)
        fieldnames = [f for f in (reader.fieldnames or []) if f is not None]

    if "GercekSonuc" not in fieldnames:
        fieldnames.append("GercekSonuc")

    bugun          = datetime.utcnow().date()
    guncellenen    = 0
    atlanan        = 0
    temiz_satirlar = []

    for satir in satirlar:
        temiz = {k: v for k, v in satir.items() if k in fieldnames}
        temiz.setdefault("GercekSonuc", "")

        if not temiz.get("GercekSonuc", "").strip():
            ev  = temiz.get("Ev", "")
            dep = temiz.get("Dep") or temiz.get("Deplasman", "")

            mac_tarihi_str = (
                temiz.get("MacTarihi", "")
                or temiz.get("mac_tarihi", "")
                or temiz.get("Tarih", "")
            )
            mac_tarihi_dt = _mac_tarihi_parse(mac_tarihi_str)

            if mac_tarihi_dt is not None and mac_tarihi_dt.date() > bugun:
                atlanan += 1
                temiz_satirlar.append(temiz)
                continue

            # MacTarihi boşsa (eski kayıtlar) — yine de eşleştirmeyi dene
            sonuc = _isim_eslesir(ev, dep, api_sonuclar, mac_tarihi_dt)
            if sonuc and sonuc in ("ev", "dep", "ber"):
                temiz["GercekSonuc"] = sonuc
                guncellenen += 1

        temiz_satirlar.append(temiz)

    with open(log_dosyasi, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(temiz_satirlar)

    if atlanan > 0:
        print(f"  ℹ️  {atlanan} gelecek maç atlandı (henüz oynanmadı)")
    print(f"  ✅ {guncellenen} maç sonucu güncellendi → {log_dosyasi}")
    return guncellenen