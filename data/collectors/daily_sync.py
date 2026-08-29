import os
import json
import logging
import time
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("KRITIK HATA: 'requests' kütüphanesi eksik. Lütfen 'pip install requests' komutunu çalıştırın.")
    exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("KRITIK HATA: 'python-dotenv' eksik. 'pip install python-dotenv' çalıştırın.")
    exit(1)

# .env dosyasını sisteme yükle (Gizli key oradan alınacak)
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from data.schema_manager import init_db, insert_match_data

logger = logging.getLogger("daily_sync")

# API-Football endpoint ve header ayarları
API_URL = "https://v3.football.api-sports.io"
API_KEY = os.environ.get("API_FOOTBALL_KEY")

headers = {
    "x-rapidapi-host": "v3.football.api-sports.io",
    "x-rapidapi-key": API_KEY
}

def sync_recent_matches():
    if not API_KEY:
        logger.error("API_FOOTBALL_KEY bulunamadı! Lütfen .env dosyasını kontrol edin.")
        return

    init_db()  # Veritabanı tablolarının hazır olduğundan emin ol
    
    # Dünün tarihi
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    logger.info(f"[{yesterday}] için eşitleme başlatılıyor (API-Football)...")
    
    try:
        # API-Football üzerinden dün oynanmış BİTMİŞ (status=FT) maçları getir.
        url = f"{API_URL}/fixtures?date={yesterday}&status=FT"
        
        # Retry Logic
        max_retries = 3
        response = None
        for attempt in range(max_retries):
            try:
                response = requests.get(url, headers=headers, timeout=10)
                if response.status_code == 200:
                    break
            except requests.RequestException as e:
                logger.warning(f"Baglanti hatasi (Deneme {attempt+1}/{max_retries}): {e}")
                time.sleep(5)
                
        if not response or response.status_code != 200:
            logger.error("API'ye ulaşılamadı. Retry limit aşıldı.")
            return

        data = response.json()
        
        if not data.get("response"):
            logger.warning("Dün için veri bulunamadı veya API limitinize (günde belli miktar istek) ulaştınız.")
            return
            
        logger.info(f"Toplam {len(data['response'])} maç bulundu. Veritabanına işleniyor...")
        
        # Her maçı sırayla işle:
        for fixtures in data["response"]:
            match_id = str(fixtures["fixture"]["id"])
            home_team_id = str(fixtures["teams"]["home"]["id"])
            away_team_id = str(fixtures["teams"]["away"]["id"])
            
            # Temel istatistikler
            home_goals = fixtures["goals"]["home"]
            away_goals = fixtures["goals"]["away"]
            
            # Gerçek veri saklama: Eksik istatistikler için ASLA sahte/dummy veri üretme
            m = {
                "match_id": match_id,
                "date": yesterday,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "home_goals": home_goals,
                "away_goals": away_goals,
                "home_xg": None,
                "away_xg": None,
                "home_possession": None,
                "away_possession": None,
                "home_shots": None,
                "away_shots": None,
                "home_shots_target": None,
                "away_shots_target": None,
                "home_ppda": None,
                "away_ppda": None,
                "weather_type": None,
                "weather_temp": None,
                "referee_name": fixtures["fixture"].get("referee")
            }
            
            insert_match_data(m)
            
        logger.info(f"Başarı! {yesterday} tarihi için maçlar sisteme işlendi.")
            
    except Exception as e:
        logger.error(f"Eşitleme hatası (Sync failed): {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    sync_recent_matches()
