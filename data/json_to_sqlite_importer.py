import os
import json
import logging
import sqlite3
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("importer")

DB_PATH = os.path.join(os.path.dirname(__file__), "football_advanced.db")
JSON_PATH = os.path.join(os.path.dirname(__file__), "maclar.json")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    # Matches table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        match_id TEXT PRIMARY KEY,
        date TEXT,
        home_team_id TEXT,
        away_team_id TEXT,
        home_goals INTEGER,
        away_goals INTEGER,
        home_xg REAL,
        away_xg REAL,
        home_possession REAL,
        away_possession REAL,
        home_shots INTEGER,
        away_shots INTEGER,
        home_shots_target INTEGER,
        away_shots_target INTEGER,
        home_ppda REAL,
        away_ppda REAL,
        weather_type TEXT,
        weather_temp REAL,
        referee_name TEXT
    )
    ''')
    conn.commit()
    conn.close()

def backfill_data():
    if not os.path.exists(JSON_PATH):
        logger.error(f"{JSON_PATH} bulunamadı!")
        return

    init_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    try:
        with open(JSON_PATH, "r") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"JSON Okuma hatası: {e}")
        return

    count = 0
    # maclar.json yapısı liglere ayrılmış olabilir, örn: data["PL"]
    for lig, lig_maclari in data.items():
        if isinstance(lig_maclari, list):
            for match in lig_maclari:
                if match.get("status") != "FINISHED":
                    continue

                m_id = str(match["id"])
                
                # Check if exists
                c.execute("SELECT match_id FROM matches WHERE match_id = ?", (m_id,))
                if c.fetchone():
                    continue

                m_date = match.get("utcDate", "")[:10]  # Sadece YYYY-MM-DD
                
                home_id = str(match.get("homeTeam", {}).get("id", ""))
                away_id = str(match.get("awayTeam", {}).get("id", ""))
                
                score = match.get("score", {}).get("fullTime", {})
                h_goals = score.get("home", 0) if score.get("home") is not None else 0
                a_goals = score.get("away", 0) if score.get("away") is not None else 0

                # Data Validation: Ensure we don't insert NULL for critical fields
                if not home_id or not away_id:
                    continue

                # xG PROXY LOGIC (Temporary goal-based proxy until API integration)
                h_xg = round(h_goals * 1.05 + 0.2, 2)
                a_xg = round(a_goals * 1.05 + 0.2, 2)
                
                # PPDA proxy
                h_ppda = 10.0
                a_ppda = 10.0

                c.execute('''
                    INSERT INTO matches (
                        match_id, date, home_team_id, away_team_id, 
                        home_goals, away_goals, home_xg, away_xg,
                        home_ppda, away_ppda
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (m_id, m_date, home_id, away_id, h_goals, a_goals, h_xg, a_xg, h_ppda, a_ppda))
                count += 1

    conn.commit()
    conn.close()
    logger.info(f"Backfill tamamlandı. Toplam {count} tarihsel maç SQLite'a eklendi.")

if __name__ == "__main__":
    backfill_data()
