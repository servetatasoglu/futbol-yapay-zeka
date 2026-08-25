import logging
import sqlite3
from datetime import datetime
import os

logger = logging.getLogger("data_validator")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "football_advanced.db")

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def validate_match_data(match_dict: dict) -> bool:
    """
    Validates data BEFORE feeding it to the prediction model.
    Checks xG boundaries, missing fields, and basic integrity.
    """
    try:
        # Check critical fields
        critical_fields = ['home_xg', 'away_xg', 'home_team_id', 'away_team_id', 'date']
        for field in critical_fields:
            if match_dict.get(field) is None:
                logger.error(f"Validation Failed: {field} is NULL.")
                return False

        # xG Range Validation (0.0 to 6.0)
        h_xg = match_dict['home_xg']
        a_xg = match_dict['away_xg']
        if not (0.0 <= h_xg <= 6.0) or not (0.0 <= a_xg <= 6.0):
            logger.error(f"Validation Failed: xG out of bounds (Home: {h_xg}, Away: {a_xg}).")
            return False

        # Future Date Validation
        match_date = match_dict['date'][:10]
        today = datetime.now().strftime("%Y-%m-%d")
        if match_date > today:
            logger.warning(f"Validation Note: Match is scheduled in the future ({match_date}).")
                
        return True

    except Exception as e:
        logger.error(f"Validation Exception: {e}")
        return False

def check_global_freshness() -> bool:
    """ Ensure DB actually has recent data. If API failed silently, fail loudly here. """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(date) FROM matches")
        max_date_str = cursor.fetchone()[0]
        conn.close()

        if not max_date_str:
            logger.error("Freshness Failed: Database is empty.")
            return False
            
        max_date = datetime.strptime(max_date_str[:10], "%Y-%m-%d")
        days_stale = (datetime.now() - max_date).days
        
        if days_stale > 3:
            logger.error(f"Freshness Failed: Data is {days_stale} days old! (Max: {max_date_str}).")
            return False
            
        return True
    except Exception as e:
        return False
