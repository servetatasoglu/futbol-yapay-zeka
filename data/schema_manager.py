import sqlite3
import json
import os
import logging
from datetime import datetime

logger = logging.getLogger("schema_manager")

DB_PATH = os.path.join(os.path.dirname(__file__), "football_advanced.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Teams
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS teams (
        team_id TEXT PRIMARY KEY,
        team_name TEXT,
        season TEXT
    )
    ''')
    
    # Matches (Team Level Data & Match Context)
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
    
    # Players
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS players (
        player_id TEXT PRIMARY KEY,
        team_id TEXT,
        name TEXT,
        position TEXT,
        status TEXT
    )
    ''')
    
    # Player Match Stats (Player Level Data)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS player_match_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player_id TEXT,
        match_id TEXT,
        minutes_played INTEGER,
        goals INTEGER,
        assists INTEGER,
        xg REAL,
        xa REAL,
        shots INTEGER,
        yellow_cards INTEGER,
        red_cards INTEGER,
        xg_prevented REAL,
        save_percentage REAL,
        UNIQUE(player_id, match_id)
    )
    ''')

    conn.commit()
    conn.close()
    logger.info("Advanced Database schema initialized.")

def insert_match_data(match_dict):
    """
    Örnek dict:
    {
        "match_id": "M001", "date": "2026-04-10", "home_team_id": "T1", "away_team_id": "T2",
        "home_goals": 2, "away_goals": 1, "home_xg": 2.1, "away_xg": 0.5,
        "home_possession": 60, "away_possession": 40, "home_shots": 12, "away_shots": 4,
        "home_shots_target": 6, "away_shots_target": 2, "home_ppda": 8.0, "away_ppda": 15.0,
        "weather_type": "Clear", "weather_temp": 18.0, "referee_name": "Oliver"
    }
    """
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO matches 
        (match_id, date, home_team_id, away_team_id, home_goals, away_goals, home_xg, away_xg, 
         home_possession, away_possession, home_shots, away_shots, home_shots_target, away_shots_target,
         home_ppda, away_ppda, weather_type, weather_temp, referee_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_dict.get('match_id'), match_dict.get('date'), match_dict.get('home_team_id'), match_dict.get('away_team_id'),
        match_dict.get('home_goals'), match_dict.get('away_goals'), match_dict.get('home_xg'), match_dict.get('away_xg'),
        match_dict.get('home_possession'), match_dict.get('away_possession'), match_dict.get('home_shots'), match_dict.get('away_shots'),
        match_dict.get('home_shots_target'), match_dict.get('away_shots_target'), match_dict.get('home_ppda'), match_dict.get('away_ppda'),
        match_dict.get('weather_type'), match_dict.get('weather_temp'), match_dict.get('referee_name')
    ))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
