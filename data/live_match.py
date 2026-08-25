import os
import requests
import json
from config.settings import API_FOOTBALL_KEY

# API-Football Live Fixtures Endpoint
URL_LIVE = "https://v3.football.api-sports.io/fixtures?live=all"

def canli_istatistikleri_cek():
    """
    API-Football üzerinden şu anda canlı oynanan maçları ve momentum (istatistik) verilerini çeker.
    Tehlikeli ataklar, isabetli şutlar ve topa sahip olma gibi verilerle canlı momentum hesaplanır.
    """
    if not API_FOOTBALL_KEY or API_FOOTBALL_KEY == "YOK":
        print("  ⚠️ API_FOOTBALL_KEY eksik. Canlı maç verisi alınamadı.")
        return []

    headers = {
        "x-apisports-key": API_FOOTBALL_KEY,
        "x-rapidapi-host": "v3.football.api-sports.io"
    }

    try:
        req = requests.get(URL_LIVE, headers=headers, timeout=15)
        req.raise_for_status()
        data = req.json()
        
        matches = data.get("response", [])
        live_matches = []
        
        for m in matches:
            # Sadece istatistiği olan ana ligleri veya favori maçları filtreleyebiliriz
            # Şimdilik tüm canlı maçları alıyoruz
            fixture = m.get("fixture", {})
            teams = m.get("teams", {})
            goals = m.get("goals", {})
            
            # Canlı istatistikler API v3'te fixtures/statistics endpoint'inden veya doğrudan fixture ile gelebilir.
            # Canlı maç durumunda bazen events ve statistics payload'da bulunur.
            
            ev_takim = teams.get("home", {}).get("name", "Bilinmiyor")
            dep_takim = teams.get("away", {}).get("name", "Bilinmiyor")
            
            dk = fixture.get("status", {}).get("elapsed", 0)
            
            # İstatistikleri bul
            stats_list = m.get("statistics", [])
            ev_stats = {}
            dep_stats = {}
            
            # Eğer statlar fixture/live ile geliyorsa
            if stats_list and len(stats_list) >= 2:
                for s in stats_list[0].get("statistics", []):
                    ev_stats[str(s["type"])] = s["value"]
                for s in stats_list[1].get("statistics", []):
                    dep_stats[str(s["type"])] = s["value"]
            
            live_matches.append({
                "id": fixture.get("id"),
                "ev": ev_takim,
                "dep": dep_takim,
                "dk": dk,
                "skor": f"{goals.get('home', 0)} - {goals.get('away', 0)}",
                "ev_istatistik": ev_stats,
                "dep_istatistik": dep_stats
            })
            
        return live_matches
        
    except Exception as e:
        print(f"  ❌ Canlı maçlar çekilirken hata: {e}")
        return []

def canli_momentum_analizi(mac):
    """
    Maç objesi içindeki istatistiklere bakarak momentum kimde (Hangi takım baskılı oynuyor) hesaplar.
    """
    ev_stats = mac.get("ev_istatistik", {})
    dep_stats = mac.get("dep_istatistik", {})
    
    if not ev_stats or not dep_stats:
        return "Veri Yok"
        
    def val_to_float(v):
        if v is None: return 0.0
        if isinstance(v, str) and '%' in v: return float(v.replace('%', ''))
        try: return float(v)
        except: return 0.0

    ev_tehlikeli = val_to_float(ev_stats.get("Dangerous Attacks", 0))
    dep_tehlikeli = val_to_float(dep_stats.get("Dangerous Attacks", 0))
    
    ev_sut = val_to_float(ev_stats.get("Shots on Goal", 0)) + val_to_float(ev_stats.get("Shots off Goal", 0))
    dep_sut = val_to_float(dep_stats.get("Shots on Goal", 0)) + val_to_float(dep_stats.get("Shots off Goal", 0))
    
    ev_momentum = (ev_tehlikeli * 0.4) + (ev_sut * 1.5)
    dep_momentum = (dep_tehlikeli * 0.4) + (dep_sut * 1.5)
    
    if ev_momentum > dep_momentum * 1.5:
        return f"Ev Sahibi Baskılı (Skor: {mac['skor']})"
    elif dep_momentum > ev_momentum * 1.5:
        return f"Deplasman Baskılı (Skor: {mac['skor']})"
    else:
        return f"Dengeli (Skor: {mac['skor']})"

if __name__ == "__main__":
    print("📡 Canlı Maçlar İzleniyor...")
    canli = canli_istatistikleri_cek()
    print(f"Bulunan Canlı Maç Sayısı: {len(canli)}\n")
    
    for m in canli[:10]:
        momentum = canli_momentum_analizi(m)
        print(f"[{m['dk']}'. Dk] {m['ev']} vs {m['dep']} | {momentum}")
