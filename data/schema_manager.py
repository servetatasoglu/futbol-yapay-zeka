import sqlite3
import json
import os
import logging
from datetime import datetime, timezone

logger = logging.getLogger("schema_manager")

DB_PATH = os.path.join(os.path.dirname(__file__), "football_advanced.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Teams
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS teams (
        team_id TEXT PRIMARY KEY,
        team_name TEXT,
        league TEXT,
        season TEXT
    )
    ''')
    
    # 2. Matches
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS matches (
        match_id TEXT PRIMARY KEY,
        date TEXT,
        league TEXT,
        season TEXT,
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
        referee_name TEXT,
        closing_odds_home REAL,
        closing_odds_draw REAL,
        closing_odds_away REAL,
        status TEXT DEFAULT 'FINISHED'
    )
    ''')
    
    # 3. Odds Snapshots
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS odds_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT,
        timestamp_utc TEXT,
        bookmaker TEXT,
        market TEXT,
        selection TEXT,
        decimal_odds REAL,
        vig_free_prob REAL,
        is_sharp INTEGER DEFAULT 0,
        is_closing INTEGER DEFAULT 0
    )
    ''')

    # 4. Predictions Log
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT,
        timestamp_utc TEXT,
        model_version TEXT,
        feature_version TEXT,
        market TEXT,
        selection TEXT,
        model_prob REAL,
        fair_market_prob REAL,
        edge REAL,
        ev REAL,
        confidence REAL,
        random_seed INTEGER,
        UNIQUE(match_id, model_version, market, selection)
    )
    ''')

    # 5. Bets (Executed / Paper)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS bets (
        bet_id TEXT PRIMARY KEY,
        match_id TEXT,
        timestamp_utc TEXT,
        market TEXT,
        selection TEXT,
        entry_odds REAL,
        closing_odds REAL,
        model_prob REAL,
        market_prob REAL,
        edge REAL,
        ev REAL,
        stake REAL,
        stake_pct REAL,
        bankroll REAL,
        risk_phase TEXT,
        status TEXT DEFAULT 'PENDING'
    )
    ''')

    # 6. Settlement Results
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bet_id TEXT UNIQUE,
        match_id TEXT,
        settlement_timestamp_utc TEXT,
        score_home INTEGER,
        score_away INTEGER,
        result_outcome TEXT,
        profit_loss REAL,
        clv_odds REAL,
        clv_prob REAL
    )
    ''')

    # 7. Model Versions
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS model_versions (
        version_id TEXT PRIMARY KEY,
        trained_at_utc TEXT,
        train_window_start TEXT,
        train_window_end TEXT,
        oos_brier REAL,
        oos_logloss REAL,
        oos_roi REAL,
        oos_clv REAL,
        active INTEGER DEFAULT 1
    )
    ''')

    # 8. System Events & Audit Log
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS system_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_utc TEXT,
        run_id TEXT,
        component TEXT,
        severity TEXT,
        message TEXT,
        details TEXT
    )
    ''')

    conn.commit()
    conn.close()
    logger.info("Canonical Database schema initialized.")

def insert_match_data(match_dict):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO matches 
        (match_id, date, league, season, home_team_id, away_team_id, home_goals, away_goals, home_xg, away_xg, 
         home_possession, away_possession, home_shots, away_shots, home_shots_target, away_shots_target,
         home_ppda, away_ppda, weather_type, weather_temp, referee_name, closing_odds_home, closing_odds_draw, closing_odds_away, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        match_dict.get('match_id'),
        match_dict.get('date'),
        match_dict.get('league'),
        match_dict.get('season'),
        match_dict.get('home_team_id'),
        match_dict.get('away_team_id'),
        match_dict.get('home_goals'),
        match_dict.get('away_goals'),
        match_dict.get('home_xg'),
        match_dict.get('away_xg'),
        match_dict.get('home_possession'),
        match_dict.get('away_possession'),
        match_dict.get('home_shots'),
        match_dict.get('away_shots'),
        match_dict.get('home_shots_target'),
        match_dict.get('away_shots_target'),
        match_dict.get('home_ppda'),
        match_dict.get('away_ppda'),
        match_dict.get('weather_type'),
        match_dict.get('weather_temp'),
        match_dict.get('referee_name'),
        match_dict.get('closing_odds_home'),
        match_dict.get('closing_odds_draw'),
        match_dict.get('closing_odds_away'),
        match_dict.get('status', 'FINISHED')
    ))
    conn.commit()
    conn.close()

def log_system_event(run_id: str, component: str, severity: str, message: str, details: str = ""):
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''
            INSERT INTO system_events (timestamp_utc, run_id, component, severity, message, details)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            datetime.now(timezone.utc).isoformat(),
            run_id,
            component,
            severity,
            message,
            details
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to log system event: {e}")

if __name__ == "__main__":
    init_db()

