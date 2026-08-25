"""
RESULT TRACKER — Otomatik Sonuç Güncelleme Sistemi
═══════════════════════════════════════════════════════
Sorumluluklar:
  1. clv_bet_log.json'daki bahisleri tarar
  2. Bitmiş maçların sonuçlarını API'den çeker
  3. sonuc, clv, profit alanlarını günceller
  4. Temiz log üretir

Çalıştırma: python scripts/result_tracker.py
Zamanlama: Günde 2x (sabah + akşam) cron/scheduler ile
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("result_tracker")

# .env desteği
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))
except Exception:
    pass

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
CLV_LOG_PATH = os.path.join(BASE_DIR, "data", "clv_bet_log.json")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "")
FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")


# ═══════════════════════════════════════════════════════
#  CLV LOG I/O
# ═══════════════════════════════════════════════════════

def _yukle() -> dict:
    if os.path.exists(CLV_LOG_PATH):
        try:
            with open(CLV_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"bahisler": [], "gunluk_raporlar": []}


def _kaydet(db: dict):
    os.makedirs(os.path.dirname(CLV_LOG_PATH), exist_ok=True)
    with open(CLV_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════
#  API RESULT FETCHING
# ═══════════════════════════════════════════════════════

def _fetch_results_football_data(tarih: str) -> dict:
    """
    football-data.org'dan bitmiş maç sonuçlarını çek.
    Returns: {(ev_isim, dep_isim): {"sonuc": "ev"|"dep"|"ber", "ev_gol": int, "dep_gol": int}}
    """
    if not FOOTBALL_DATA_KEY:
        return {}

    sonuclar = {}
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}

    # Birden fazla lig
    ligler = ["PL", "PD", "BL1", "SA", "FL1", "DED", "PPL", "CL", "EL"]
    for lig in ligler:
        url = (f"https://api.football-data.org/v4/competitions/{lig}/matches"
               f"?status=FINISHED&dateFrom={tarih}&dateTo={tarih}")
        try:
            r = requests.get(url, headers=headers, timeout=15, verify=False)
            if r.status_code == 429:
                logger.warning("Rate limit — 60s bekleniyor...")
                import time; time.sleep(60)
                r = requests.get(url, headers=headers, timeout=15, verify=False)
            if r.status_code != 200:
                continue
            data = r.json()
            for mac in data.get("matches", []):
                try:
                    ev = mac["homeTeam"]["name"]
                    dep = mac["awayTeam"]["name"]
                    ev_gol = mac["score"]["fullTime"]["home"]
                    dep_gol = mac["score"]["fullTime"]["away"]
                    if ev_gol is None or dep_gol is None:
                        continue
                    if ev_gol > dep_gol:
                        sonuc = "ev"
                    elif dep_gol > ev_gol:
                        sonuc = "dep"
                    else:
                        sonuc = "ber"
                    sonuclar[(ev, dep)] = {
                        "sonuc": sonuc,
                        "ev_gol": ev_gol,
                        "dep_gol": dep_gol,
                    }
                except (KeyError, TypeError):
                    continue
        except Exception as e:
            logger.debug(f"football-data {lig} hatası: {e}")
        import time; time.sleep(6.5)  # Rate limit

    return sonuclar


def _fetch_results_api_football(tarih: str) -> dict:
    """
    API-Football'dan bitmiş maç sonuçlarını çek.
    """
    if not API_FOOTBALL_KEY:
        return {}

    sonuclar = {}
    headers = {
        "x-rapidapi-host": "v3.football.api-sports.io",
        "x-rapidapi-key": API_FOOTBALL_KEY,
    }
    url = f"https://v3.football.api-sports.io/fixtures?date={tarih}&status=FT"

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return {}
        data = r.json()
        for fix in data.get("response", []):
            try:
                ev = fix["teams"]["home"]["name"]
                dep = fix["teams"]["away"]["name"]
                ev_gol = fix["goals"]["home"]
                dep_gol = fix["goals"]["away"]
                if ev_gol is None or dep_gol is None:
                    continue
                if ev_gol > dep_gol:
                    sonuc = "ev"
                elif dep_gol > ev_gol:
                    sonuc = "dep"
                else:
                    sonuc = "ber"
                sonuclar[(ev, dep)] = {
                    "sonuc": sonuc,
                    "ev_gol": ev_gol,
                    "dep_gol": dep_gol,
                }
            except (KeyError, TypeError):
                continue
    except Exception as e:
        logger.debug(f"API-Football hatası: {e}")

    return sonuclar


# ═══════════════════════════════════════════════════════
#  FUZZY MATCHING — İsim farklılıklarını çöz
# ═══════════════════════════════════════════════════════

def _fuzzy_match(bet_ev: str, bet_dep: str, sonuclar: dict) -> dict | None:
    """
    Tam eşleşme + kısmi eşleşme dener.
    """
    # Tam eşleşme
    key = (bet_ev, bet_dep)
    if key in sonuclar:
        return sonuclar[key]

    # Kısmi eşleşme (ilk 10 karakter)
    bet_ev_lower = bet_ev.lower().strip()
    bet_dep_lower = bet_dep.lower().strip()

    for (api_ev, api_dep), val in sonuclar.items():
        api_ev_l = api_ev.lower().strip()
        api_dep_l = api_dep.lower().strip()

        # Substring match
        if ((bet_ev_lower in api_ev_l or api_ev_l in bet_ev_lower) and
            (bet_dep_lower in api_dep_l or api_dep_l in bet_dep_lower)):
            return val

        # İlk N karakter match
        if (api_ev_l[:12] == bet_ev_lower[:12] and
            api_dep_l[:12] == bet_dep_lower[:12]):
            return val

    return None


# ═══════════════════════════════════════════════════════
#  SONUC→TAHMIN EŞLEŞTİRME
# ═══════════════════════════════════════════════════════

_TAHMIN_MAP = {
    "Ev Sahibi Kazanır": "ev",
    "Deplasman Kazanır": "dep",
    "Beraberlik": "ber",
}


def _tahmin_tuttu_mu(tahmin: str, sonuc: str) -> bool:
    """Tahmin doğru mu?"""
    beklenen = _TAHMIN_MAP.get(tahmin, "")
    return beklenen == sonuc


# ═══════════════════════════════════════════════════════
#  MAIN TRACKER
# ═══════════════════════════════════════════════════════

def update_results(gun_sayisi: int = 7):
    """
    Son N günün bahislerini tarar, sonuçları günceller.
    """
    db = _yukle()
    bahisler = db.get("bahisler", [])

    if not bahisler:
        logger.info("Bahis bulunamadı.")
        return

    # Sonucu olmayan bahisleri bul
    bekleyen = [b for b in bahisler if b.get("sonuc") is None]
    logger.info(f"📋 Toplam {len(bahisler)} bahis, {len(bekleyen)} sonuç bekliyor.")

    if not bekleyen:
        logger.info("✅ Tüm bahisler güncel.")
        return

    # Hangi tarihleri çekmemiz gerekiyor?
    tarihler = set()
    for b in bekleyen:
        mac_tarihi = str(b.get("mac_tarihi", b.get("tarih", "")))[:10]
        if mac_tarihi and mac_tarihi <= datetime.now().strftime("%Y-%m-%d"):
            tarihler.add(mac_tarihi)

    if not tarihler:
        logger.info("Henüz bitmiş maç tarihi yok.")
        return

    logger.info(f"📅 {len(tarihler)} tarih için sonuçlar çekilecek: {sorted(tarihler)}")

    # API'den sonuçları çek
    tum_sonuclar = {}
    for tarih in sorted(tarihler):
        logger.info(f"  🌐 {tarih} sonuçları çekiliyor...")
        # football-data.org öncelikli
        sonuc = _fetch_results_football_data(tarih)
        if sonuc:
            tum_sonuclar.update(sonuc)
            logger.info(f"    ✅ football-data: {len(sonuc)} maç")

        # API-Football fallback
        sonuc2 = _fetch_results_api_football(tarih)
        if sonuc2:
            # Sadece eksikleri ekle
            for k, v in sonuc2.items():
                if k not in tum_sonuclar:
                    tum_sonuclar[k] = v
            logger.info(f"    ✅ API-Football: {len(sonuc2)} maç")

    if not tum_sonuclar:
        logger.warning("⚠️ API'den sonuç çekilemedi.")
        return

    logger.info(f"📊 Toplam {len(tum_sonuclar)} maç sonucu elde edildi.")

    # Bahisleri güncelle
    guncellenen = 0
    kazanan = 0
    kaybeden = 0

    for bet in bahisler:
        if bet.get("sonuc") is not None:
            continue

        ev = bet.get("ev", "")
        dep = bet.get("dep", "")
        mac_tarihi = str(bet.get("mac_tarihi", bet.get("tarih", "")))[:10]

        # Maç henüz bitmemiş olabilir
        if mac_tarihi > datetime.now().strftime("%Y-%m-%d"):
            continue

        # Sonucu bul
        sonuc_data = _fuzzy_match(ev, dep, tum_sonuclar)
        if sonuc_data is None:
            continue

        sonuc = sonuc_data["sonuc"]
        tahmin = bet.get("tahmin", "")
        tuttu = _tahmin_tuttu_mu(tahmin, sonuc)

        # Güncelle
        bet["sonuc"] = "kazandi" if tuttu else "kaybetti"
        bet["gercek_sonuc"] = sonuc
        bet["ev_gol"] = sonuc_data.get("ev_gol")
        bet["dep_gol"] = sonuc_data.get("dep_gol")

        # Profit hesabı (1 birim bahis varsayımı)
        if tuttu:
            oran = bet.get("oran_alinma", bet.get("oran", 2.0))
            bet["profit"] = round(oran - 1, 4)
            kazanan += 1
        else:
            bet["profit"] = -1.0
            kaybeden += 1

        guncellenen += 1

    # Kaydet
    db["bahisler"] = bahisler
    _kaydet(db)

    logger.info(f"✅ {guncellenen} bahis güncellendi:")
    logger.info(f"   ✅ Kazanan: {kazanan}")
    logger.info(f"   ❌ Kaybeden: {kaybeden}")
    logger.info(f"   ⏳ Bekleyen: {len([b for b in bahisler if b.get('sonuc') is None])}")


# ═══════════════════════════════════════════════════════
#  CLV BET LOG TEMİZLİĞİ — Mevcut duplikatları temizle
# ═══════════════════════════════════════════════════════

def clean_duplicates():
    """
    Mevcut clv_bet_log.json'daki duplikatları temizler.
    Anahtar: ev|dep|tahmin|mac_tarihi
    """
    db = _yukle()
    bahisler = db.get("bahisler", [])
    onceki = len(bahisler)

    seen = set()
    temiz = []
    for b in bahisler:
        key = f"{b.get('ev','')}|{b.get('dep','')}|{b.get('tahmin','')}|{str(b.get('mac_tarihi', b.get('tarih','')))[:10]}"
        if key not in seen:
            seen.add(key)
            temiz.append(b)

    db["bahisler"] = temiz
    _kaydet(db)
    silinen = onceki - len(temiz)
    logger.info(f"🧹 Duplikat temizliği: {onceki} → {len(temiz)} ({silinen} duplikat silindi)")


# ═══════════════════════════════════════════════════════
#  CLI ENTRY POINT
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if "--clean" in sys.argv:
        clean_duplicates()
    else:
        # Önce duplikatları temizle, sonra sonuçları güncelle
        clean_duplicates()
        update_results(gun_sayisi=7)
