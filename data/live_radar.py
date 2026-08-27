import os
import time
import requests
import sqlite3
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

logger = logging.getLogger("live_radar")
DB_PATH = os.path.join(os.path.dirname(__file__), "football_advanced.db")

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

def init_closing_odds_schema():
    """ Alters the SQLite schema to hold true closing odds. """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("ALTER TABLE matches ADD COLUMN closing_odds_home REAL")
        c.execute("ALTER TABLE matches ADD COLUMN closing_odds_draw REAL")
        c.execute("ALTER TABLE matches ADD COLUMN closing_odds_away REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass # Columns already exist
    finally:
        conn.close()

class LiveRadarEngine:
    """
    Live Radar Engine for querying real-time market lines.
    Integrates with live odds feeds and returns standardized match payloads.
    """
    def __init__(self):
        self.api_key = os.environ.get("ODDS_API_KEY")

    def fetch_live_matches(self, preferred_bookmaker: str = "pinnacle") -> list:
        """
        Fetches live scheduled matches and formats them for the quantitative engine.
        Returns empty list if no real data is available.
        """
        try:
            from data.odds import canli_oranlar_cek
            raw_odds = canli_oranlar_cek(gun=3, zorla_yenile=False)
        except Exception as e:
            logger.error(f"Error calling canli_oranlar_cek: {e}")
            raw_odds = []

        formatted = []
        for m in raw_odds:
            ev = m.get("ev")
            dep = m.get("dep")
            if not ev or not dep:
                continue

            ev_oran = float(m.get("ev_oran", 0.0) or 0.0)
            ber_oran = float(m.get("ber_oran", 0.0) or 0.0)
            dep_oran = float(m.get("dep_oran", 0.0) or 0.0)

            if ev_oran <= 1.0 or dep_oran <= 1.0:
                continue

            formatted.append({
                "ev": ev,
                "dep": dep,
                "date": m.get("mac_tarihi", datetime.now(timezone.utc).isoformat()),
                "lig": m.get("lig", "?"),
                "lig_isim": m.get("lig_isim", "Bilinmiyor"),
                "sharp_tier": m.get("sharp_tier", "NO_SHARP"),
                "pinnacle_var": m.get("pinnacle_var", False),
                "kitap_sayisi": m.get("kitap_sayisi", 1),
                "odds_current": {
                    "Ev Sahibi Kazanır": ev_oran,
                    "Beraberlik": ber_oran,
                    "Deplasman Kazanır": dep_oran,
                    "2.5 Üst": float(m.get("over25_oran", 0.0) or 0.0),
                    "2.5 Alt": float(m.get("under25_oran", 0.0) or 0.0),
                    "KG Var": float(m.get("btts_yes_oran", 0.0) or 0.0),
                    "KG Yok": float(m.get("btts_no_oran", 0.0) or 0.0),
                },
                "kitap_oranlari": {
                    preferred_bookmaker: (ev_oran, ber_oran, dep_oran)
                }
            })
        return formatted

def fetch_live_odds():
    """ 
    Connects to The Odds API to fetch live lines for soccer matches.
    """
    if not ODDS_API_KEY:
        logger.error("ODDS_API_KEY bulunamadi! (.env icinde yok)")
        return {}
        
    try:
        url = "https://api.the-odds-api.com/v4/sports/soccer/odds/"
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu,uk",
            "markets": "h2h",
            "oddsFormat": "decimal"
        }
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        parsed_odds = {}
        for match in data:
            home = match.get("home_team")
            bookmakers = match.get("bookmakers", [])
            if not bookmakers: continue
            
            target_bookmaker = next((b for b in bookmakers if b.get('key') == 'pinnacle'), bookmakers[0])
            markets = target_bookmaker.get("markets", [])
            if not markets: continue
            
            h2h_market = markets[0]
            outcomes = h2h_market.get("outcomes", [])
            
            odds_dict = {"1": 0.0, "X": 0.0, "2": 0.0}
            for o in outcomes:
                if o.get("name") == home:
                    odds_dict["1"] = o.get("price")
                elif o.get("name") == "Draw":
                    odds_dict["X"] = o.get("price")
                else:
                    odds_dict["2"] = o.get("price")
                    
            parsed_odds[home] = odds_dict
            
        logger.info(f"API'den {len(parsed_odds)} canli mac orani cekildi.")
        return parsed_odds
    except Exception as e:
        logger.error(f"Live Odds Fetch Error: {e}")
        return {}

def update_closing_odds():
    """ Run via cron every 5 minutes """
    init_closing_odds_schema()
    odds_data = fetch_live_odds()
    
    if not odds_data:
        return
        
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    from features.advanced_stats import resolve_team_id
    
    for home_name, odds in odds_data.items():
        home_id = resolve_team_id(home_name)
        c.execute('''
            UPDATE matches 
            SET closing_odds_home = ?, closing_odds_draw = ?, closing_odds_away = ?
            WHERE home_team_id = ? AND date >= date('now', '-1 day')
        ''', (odds["1"], odds["X"], odds["2"], home_id))
        
        if c.rowcount > 0:
            logger.info(f"Recorded TRUE CLOSING LINE for {home_name}: {odds}")
            
    conn.commit()
    conn.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Polling latest closing lines...")
    update_closing_odds()

