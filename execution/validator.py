import math
import random
import os
import json
from datetime import datetime

# Risk Data state storage
RISK_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "risk_state.json")

def _load_risk_state():
    if os.path.exists(RISK_DB_PATH):
        try:
            with open(RISK_DB_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
                if state.get("date") == datetime.now().strftime("%Y-%m-%d"):
                    return state
        except:
            pass
    return {"date": datetime.now().strftime("%Y-%m-%d"), "daily_exposure_pct": 0.0, "rolling_drawdown": 0.0}

def _save_risk_state(state):
    os.makedirs(os.path.dirname(RISK_DB_PATH), exist_ok=True)
    with open(RISK_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

class ExecutionValidator:
    """
    Advanced Execution + Validation + Filtering Layer
    Translates advisory edge into executed real-money safety.
    """
    
    @staticmethod
    def calculate_fake_edge_score(match, odds_current, edge_raw):
        """0-1 range. Estimates probability of a 'Phantom Edge' due to missing info."""
        score = 0.0
        
        try:
            match_t = datetime.strptime(match.get("date", ""), "%Y-%m-%dT%H:%M:%SZ")
            mins_to_kickoff = (match_t - datetime.utcnow()).total_seconds() / 60
        except:
            mins_to_kickoff = 120 # Default

        # 1. Missing Lineup Penalty
        if mins_to_kickoff < 60 and not match.get("lineup_confirmed", False):
            score += 0.35
            
        # 2. Huge Unexplained Edge (Usually means market knows an asymmetry)
        if edge_raw > 0.12: 
            score += 0.20
            
        # 3. Odds Drift logic (simulated by looking at missing historic snapshots vs current)
        latest_odd = odds_current
        # Because we don't hold constant websockets yet, we approximate drift through spread volatility
        if match.get("volatility", 0) > 0.05: 
            score += 0.40
            
        return min(1.0, score)

    @staticmethod
    def apply_latency_decay(edge_raw, latency_seconds, decay_constant=60):
        """Exponential decay function for execution latency."""
        return edge_raw * math.exp(-latency_seconds / decay_constant)

    @staticmethod
    def simulate_line_shopping(market_implied_prob):
        """Finds the best odds simulating multi-book liquidity"""
        books = {"FanDuel": 0.040, "DraftKings": 0.045, "BetMGM": 0.050, "Pinnacle": 0.025, "BetfairEx": 0.015}
        best_odds = 0
        selected_book = "Unknown"
        
        for book, vig in books.items():
            # Add micro-noise
            sim_book_implied = market_implied_prob + (random.uniform(-0.01, 0.01))
            if sim_book_implied <= 0.05: sim_book_implied = 0.05
            
            sim_odds = (1.0 / sim_book_implied) * (1 - vig)
            if sim_odds > best_odds:
                best_odds = round(sim_odds, 2)
                selected_book = book
                
        return best_odds, selected_book

    @staticmethod
    def safeguard_bankroll(base_kelly, edge_final):
        """Enhanced Kelly Protection Layer"""
        risk_state = _load_risk_state()
        
        # Stop Betting Logic
        if risk_state.get("rolling_drawdown", 0) > 0.15:
            return 0.0, "REJECTED_DRAWDOWN_LIMIT"
            
        # Fractional Kelly (0.25 - 0.5 multipliers to heavily smooth variance)
        multiplier = 0.5 if edge_final > 0.05 else 0.25
        fraction_kelly = base_kelly * multiplier
        
        # Hard Caps per bet
        fraction_kelly = min(fraction_kelly, 0.02)
        
        # Daily Limit check
        if risk_state["daily_exposure_pct"] + fraction_kelly > 0.10:
            return 0.0, "REJECTED_DAILY_LIMIT"
            
        return fraction_kelly, "OK"

    @classmethod
    def verify_signal(cls, match, tahmin_tipi, model_prob, original_odds, ci_width=0.10):
        """
        Master Pipeline Processor.
        Runs fake edge detection -> decay -> line shopping -> bankroll protection
        """
        
        edge_raw = model_prob - (1.0 / original_odds)
        if edge_raw < 0:
            return None # Instant reject
            
        # 1. Fake Edge Score
        fake_score = cls.calculate_fake_edge_score(match, original_odds, edge_raw)
        
        # 2. Line Shopping Improvement
        market_prob = 1.0 / original_odds
        best_shop_odds, selected_book = cls.simulate_line_shopping(market_prob)
        best_odds = max(original_odds, best_shop_odds)
        
        # 3. Latency Decay
        latency = random.uniform(0.5, 3.5) # Simulated latency to exchange
        edge_final = cls.apply_latency_decay(model_prob - (1.0 / best_odds), latency)
        
        # 4. Strict Quality Filter Validations
        val_status = "ONAYLANDI"
        reject_reason = ""
        
        if edge_raw < 0.06 or edge_final < 0.03:
            val_status = "REDDEDİLDİ"
            reject_reason = "EDGE_YETERSIZ_KATI_MOD"
        if ci_width > 0.15:
            val_status = "REDDEDİLDİ" 
            reject_reason = "GUVEN_ARALIGI_COK_GENIS"
        if fake_score > 0.6:
            val_status = "REDDEDİLDİ"
            reject_reason = "SAHTE_FIRSAT_ALGILANDI"
            
        # 5. Human-in-the-Loop Triggers
        if val_status == "ONAYLANDI" and (edge_final > 0.10 or 0.4 <= fake_score <= 0.6):
            val_status = "MANUEL ONAY BEKLİYOR"
            
        # 6. Bankroll Allocation
        kelly_fraction, bankroll_msg = 0.0, ""
        if val_status != "REDDEDİLDİ":
            raw_kelly = ((model_prob * best_odds - 1) / (best_odds - 1)) if best_odds > 1 else 0
            if raw_kelly > 0:
                kelly_fraction, bankroll_msg = cls.safeguard_bankroll(raw_kelly, edge_final)
                if bankroll_msg != "OK":
                    val_status = "REDDEDİLDİ"
                    reject_reason = bankroll_msg
            else:
                val_status = "REDDEDİLDİ"
                reject_reason = "NEGATIF_KELLY"
                
        # Register Exposure if Approved
        if val_status == "ONAYLANDI":
            r_state = _load_risk_state()
            r_state["daily_exposure_pct"] += kelly_fraction
            _save_risk_state(r_state)

        return {
            "edge_raw": round(edge_raw, 4),
            "edge_final": round(edge_final, 4),
            "fake_edge_score": round(fake_score, 3),
            "latency_seconds": round(latency, 2),
            "selected_bookmaker": selected_book,
            "target_odds": best_odds,
            "status": val_status,
            "reject_reason": reject_reason,
            "recommended_stake_pct": round(kelly_fraction * 100, 2)
        }
