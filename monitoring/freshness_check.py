import sqlite3
import os
import argparse
from datetime import datetime

# DB_PATH = "data/football_advanced.db" (assume running from root)

def run_freshness_checks():
    db_path = os.path.join(os.path.dirname(__file__), "..", "data", "football_advanced.db")
    try:
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        c.execute("SELECT MAX(date) FROM matches;")
        max_date = c.fetchone()[0]
        
        c.execute("SELECT COUNT(*) FROM matches;")
        num_rows = c.fetchone()[0]
        
        conn.close()
        
        print("=== DATA FRESHNESS VERIFICATION ===")
        print(f"Total Matches in DB : {num_rows}")
        
        if not max_date:
            print("Status            : DEAD (Empty DB)")
            return
            
        print(f"Latest Match Date : {max_date}")
        
        latest = datetime.strptime(max_date[:10], "%Y-%m-%d")
        days_stale = (datetime.now() - latest).days
        
        if days_stale <= 2:
            print("Health Score      : 100/100 (FRESH)")
        elif days_stale <= 7:
            print(f"Health Score      : 60/100 (WARN: Sync is {days_stale} days late)")
        else:
            print(f"Health Score      : 0/100 (CRITICAL: Data is {days_stale} days stale)")
            
    except Exception as e:
        print(f"FATAL ERROR reading SQLite: {e}")

if __name__ == "__main__":
    run_freshness_checks()
