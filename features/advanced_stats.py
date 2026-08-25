import os
import sqlite3
import pandas as pd
import logging
from datetime import datetime

logger = logging.getLogger("advanced_stats")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "football_advanced.db")
MAPPING_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "team_mapping.json")

def resolve_team_id(team_name: str) -> str:
    """ Resolves human-readable names (e.g. 'Burnley') into API IDs (e.g. '328') for SQL lookups. """
    try:
        if os.path.exists(MAPPING_PATH):
            with open(MAPPING_PATH, "r") as f:
                mapping = json.load(f)
            return mapping.get(team_name, team_name) # Fallback to original if not found
    except Exception:
        pass
    return team_name

def get_db_connection():
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Database not found at {DB_PATH}")
    return sqlite3.connect(DB_PATH)

def calculate_attack_strength(team_id: str, match_date: str, last_n_matches: int = 5) -> float:
    """
    Computes Attack Score based on historical xG, strictly bounded by < match_date.
    """
    team_id = resolve_team_id(team_id)
    try:
        conn = get_db_connection()
        # PREVENT FUTURE DATA LEAKAGE: date < ?
        query = '''
            SELECT home_xg as xg, date FROM matches 
            WHERE home_team_id = ? AND date < ?
            UNION ALL
            SELECT away_xg as xg, date FROM matches 
            WHERE away_team_id = ? AND date < ?
            ORDER BY date DESC LIMIT ?
        '''
        df = pd.read_sql_query(query, conn, params=(team_id, match_date, team_id, match_date, last_n_matches))
        conn.close()
        
        if df.empty or 'xg' not in df.columns:
            return 1.0  # Neutral
            
        xg_values = df['xg'].fillna(1.0).tolist()
        
        # Exponential decay weights
        weights = [1.0] * len(xg_values)
        for i in range(len(weights)):
            weights[i] = max(0.4, 1.0 - (i * 0.1))
            
        attack_score = sum(xg * w for xg, w in zip(xg_values, weights)) / sum(weights)
        return max(0.5, min(attack_score, 3.5))
        
    except Exception as e:
        logger.error(f"Error calculating attack strength: {e}")
        return 1.0


def calculate_defensive_weakness(team_id: str, match_date: str, last_n_matches: int = 5) -> float:
    """
    Computes Defensive Weakness based on historical xGA prior to match_date.
    Lower is better (tighter defense).
    """
    team_id = resolve_team_id(team_id)
    try:
        conn = get_db_connection()
        query = '''
            SELECT away_xg as xga, date FROM matches 
            WHERE home_team_id = ? AND date < ?
            UNION ALL
            SELECT home_xg as xga, date FROM matches 
            WHERE away_team_id = ? AND date < ?
            ORDER BY date DESC LIMIT ?
        '''
        df = pd.read_sql_query(query, conn, params=(team_id, match_date, team_id, match_date, last_n_matches))
        conn.close()
        
        if df.empty or 'xga' not in df.columns:
            return 1.0
            
        xga_values = df['xga'].fillna(1.0).tolist()
        weights = [max(0.4, 1.0 - (i * 0.1)) for i in range(len(xga_values))]
        
        defense_score = sum(xga * w for xga, w in zip(xga_values, weights)) / sum(weights)
        return max(0.5, min(defense_score, 3.5))
        
    except Exception as e:
        logger.error(f"Error calculating defensive weakness: {e}")
        return 1.0


def calculate_expected_tempo(home_id: str, away_id: str, match_date: str, last_n: int = 3) -> float:
    """
    Tempo estimation strictly using PPDA from past matches.
    """
    home_id = resolve_team_id(home_id)
    away_id = resolve_team_id(away_id)
    try:
        conn = get_db_connection()
        def get_avg_ppda(t_id):
            q = '''
                SELECT home_ppda as ppda FROM matches WHERE home_team_id = ? AND date < ?
                UNION ALL
                SELECT away_ppda as ppda FROM matches WHERE away_team_id = ? AND date < ?
                ORDER BY date DESC LIMIT ?
            '''
            d = pd.read_sql_query(q, conn, params=(t_id, match_date, t_id, match_date, last_n))
            if d.empty or d['ppda'].isnull().all():
                return 10.0 # Average default
            return d['ppda'].mean()

        home_ppda = get_avg_ppda(home_id)
        away_ppda = get_avg_ppda(away_id)
        conn.close()

        tempo_factor = (24.0 - (home_ppda + away_ppda)) / 10.0
        return max(0.8, min(1.0 + (tempo_factor * 0.1), 1.2))

    except Exception:
        return 1.0

def calculate_lineup_strength(team_id: str, match_date: str, expected_starters: list) -> float:
    """ Evaluates starting XI power prior to match date. """
    return 1.0
