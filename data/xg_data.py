# data/xg_data.py
import os
import json
import logging
from datetime import datetime
import soccerdata as sd

logger = logging.getLogger("xg_data")

# Map our league codes to soccerdata FBref league names
FBREF_LEAGUE_MAP = {
    "PL": "ENG-Premier League",
    "PD": "ESP-La Liga",
    "SA": "ITA-Serie A",
    "BL1": "GER-Bundesliga",
    "FL1": "FRA-Ligue 1",
    "DED": "NED-Eredivisie",
    "PPL": "POR-Primeira Liga",
    "ELC": "ENG-Championship"
}

XG_CACHE_FILE = os.path.join(os.path.dirname(__file__), "xg_cache.json")

def fetch_xg_data(season="2023/2024", force_update=False):
    """
    soccerdata kütüphanesini kullanarak FBref'ten xG ve xGA verilerini çeker.
    Bunu bir JSON önbelleğine kaydeder (her gün 1 kez yenilenir).
    """
    if not force_update and os.path.exists(XG_CACHE_FILE):
        try:
            with open(XG_CACHE_FILE, "r") as f:
                data = json.load(f)
                # Check age (1 day limit)
                last_update = datetime.fromisoformat(data.get("last_update", "2000-01-01"))
                if (datetime.now() - last_update).days < 1:
                    print("  ✅ xG verileri cache'den yüklendi.")
                    return data.get("teams", {})
        except Exception as e:
            logger.warning(f"xG cache okuma hatası: {e}")

    print("  🌐 soccerdata (FBref) ile xG verileri çekiliyor... Bu biraz sürebilir.")
    
    teams_xg = {}
    
    for lig_kodu, fbref_name in FBREF_LEAGUE_MAP.items():
        print(f"     -> {fbref_name} xG verileri indiriliyor...")
        try:
            # Initialize FBref scraper for the league
            fbref = sd.FBref(leagues=fbref_name, seasons=season)
            # We want season stats for teams to get xG and xGA per game
            stats = fbref.read_team_season_stats(stat_type="standard")
            
            # stats is a pandas DataFrame with multi-index
            # Let's extract xG and xGA for each team
            for index, row in stats.iterrows():
                team_name = index[2] # usually (league, season, team)
                # FBref standard stats might have different column names depending on the version
                # Usually it's under ('Expected', 'xG') and ('Expected', 'xGA')
                # For safety, let's convert the row to dict and parse
                row_dict = row.to_dict()
                
                # Try to extract 90min xG
                xg_90 = None
                xga_90 = None
                
                for col_name, value in row_dict.items():
                    col_str = str(col_name).lower()
                    if 'expected' in col_str or 'xg' in col_str:
                        if 'xg90' in col_str or ('xg' in col_str and '90' in col_str):
                            xg_90 = float(value)
                        elif 'xga90' in col_str or ('xga' in col_str and '90' in col_str):
                            xga_90 = float(value)
                            
                # Fallback to total xG divided by games played
                if xg_90 is None or xga_90 is None:
                    mp = 1.0 # matches played
                    for col_name, value in row_dict.items():
                        if 'mp' in str(col_name).lower() or 'matches played' in str(col_name).lower():
                            mp = max(1.0, float(value))
                    
                    for col_name, value in row_dict.items():
                        col_str = str(col_name).lower()
                        if ('xg' in col_str or 'expected goals' in col_str) and xg_90 is None:
                            xg_90 = float(value) / mp
                        if ('xga' in col_str or 'expected goals allowed' in col_str) and xga_90 is None:
                            xga_90 = float(value) / mp

                if xg_90 is not None and xga_90 is not None:
                    # Clean team name to match our system's names
                    team_clean = str(team_name).replace(" FC", "").replace(" AFC", "").strip()
                    teams_xg[team_clean] = {
                        "xg": round(xg_90, 3),
                        "xga": round(xga_90, 3),
                        "xg_diff": round(xg_90 - xga_90, 3),
                        "league": lig_kodu
                    }
        except Exception as e:
            print(f"     ⚠️ {fbref_name} xG çekilemedi: {e}")
            continue

    if teams_xg:
        cache_data = {
            "last_update": datetime.now().isoformat(),
            "teams": teams_xg
        }
        os.makedirs(os.path.dirname(XG_CACHE_FILE), exist_ok=True)
        with open(XG_CACHE_FILE, "w") as f:
            json.dump(cache_data, f, indent=2)
        print(f"  ✅ FBref xG verileri başarıyla kaydedildi ({len(teams_xg)} takım).")
    
    return teams_xg

if __name__ == "__main__":
    fetch_xg_data(force_update=True)
