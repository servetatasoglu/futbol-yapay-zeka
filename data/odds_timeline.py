# data/odds_timeline.py
"""
Odds Timeline — Tick-Level Odds History (v3.0)
════════════════════════════════════════════════
Stores every odds snapshot per match and computes:
  - Odds velocity   (Δodds/Δt) — how fast is the line moving?
  - Steam move      — all books moving same direction fast → follow or avoid
  - Reverse line    — public on one side, line moves other way → sharp fade
  - Market entropy  — bookmaker disagreement → edge opportunity indicator
  - Entry timing    — optimal bet window based on line movement patterns
"""

import os
import json
import time
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("odds_timeline")

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMELINE_PATH = os.path.join(BASE_DIR, "data", "odds_timeline.json")

# ── Thresholds ────────────────────────────────────────────────────
STEAM_VELOCITY_THRESHOLD = 0.04   # >4% move in <30 min = steam
STEAM_MIN_BOOKS          = 3      # At least 3 books must move together
REVERSE_LINE_THRESHOLD   = 0.02   # >2% against public money = reverse
ENTRY_WINDOW_HOURS       = 4.0    # Consider entry within 4h of kickoff
TIMELINE_MAX_AGE_DAYS    = 7      # Auto-prune entries older than 7 days


# ─────────────────────────────────────────────────────────────────
# 1. STORAGE
# ─────────────────────────────────────────────────────────────────

def _yukle() -> dict:
    if os.path.exists(TIMELINE_PATH):
        try:
            with open(TIMELINE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _kaydet(db: dict):
    os.makedirs(os.path.dirname(TIMELINE_PATH), exist_ok=True)
    with open(TIMELINE_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


def _mac_id(ev: str, dep: str, tarih: str) -> str:
    """Consistent match ID using | separator."""
    return f"{ev}|{dep}|{str(tarih)[:10]}"


# ─────────────────────────────────────────────────────────────────
# 2. SNAPSHOT INSERTION
# ─────────────────────────────────────────────────────────────────

def odds_snapshot_ekle(ev: str, dep: str, tarih: str,
                       bookmaker: str,
                       home_odds: float, draw_odds: float, away_odds: float,
                       market: str = "h2h") -> None:
    """
    Insert a single odds snapshot into the timeline.
    Call this every time odds are fetched from the API.
    """
    mac_id = _mac_id(ev, dep, tarih)
    db = _yukle()

    if mac_id not in db:
        db[mac_id] = {
            "ev": ev, "dep": dep, "tarih": tarih,
            "snapshots": []
        }

    snapshot = {
        "ts":       datetime.now(timezone.utc).isoformat(),
        "book":     bookmaker,
        "market":   market,
        "home":     round(float(home_odds), 3),
        "draw":     round(float(draw_odds), 3),
        "away":     round(float(away_odds), 3),
        "overround": round(1/home_odds + 1/draw_odds + 1/away_odds, 4)
                     if home_odds > 1 and draw_odds > 1 and away_odds > 1 else 0,
    }
    db[mac_id]["snapshots"].append(snapshot)

    # Keep last 200 snapshots per match (safety limit)
    if len(db[mac_id]["snapshots"]) > 200:
        db[mac_id]["snapshots"] = db[mac_id]["snapshots"][-200:]

    _kaydet(db)


def bulk_snapshot_ekle(mac_listesi: list, bookmaker_data: dict) -> int:
    """
    Batch insert: mac_listesi = [{ev, dep, tarih, ...}]
    bookmaker_data = {bookmaker_key: {ev_odds, draw_odds, away_odds}}
    Returns count of snapshots inserted.
    """
    count = 0
    for mac in mac_listesi:
        ev    = mac.get("ev", "")
        dep   = mac.get("dep", "")
        tarih = mac.get("mac_tarihi", "")[:10]
        for book, odds in bookmaker_data.items():
            try:
                odds_snapshot_ekle(
                    ev=ev, dep=dep, tarih=tarih, bookmaker=book,
                    home_odds=odds.get("home", 0),
                    draw_odds=odds.get("draw", 0),
                    away_odds=odds.get("away", 0),
                )
                count += 1
            except Exception as e:
                logger.debug(f"Snapshot error {ev} vs {dep} / {book}: {e}")
    return count


# ─────────────────────────────────────────────────────────────────
# 3. ODDS VELOCITY (Δodds/Δt)
# ─────────────────────────────────────────────────────────────────

def odds_velocity_hesapla(ev: str, dep: str, tarih: str,
                           tahmin: str = "home",
                           window_min: int = 30) -> dict:
    """
    Compute how fast the line is moving in the last `window_min` minutes.

    Returns:
        {
            "velocity":       float,  # odds/hour (positive = odds rising)
            "pct_change":     float,  # % change from window start to now
            "direction":      str,    # "UP" | "DOWN" | "STABLE"
            "n_snapshots":    int,    # how many data points
            "confidence":     float,  # 0-1 based on n_snapshots
        }
    """
    mac_id = _mac_id(ev, dep, tarih)
    db = _yukle()
    entry = db.get(mac_id, {})
    snapshots = entry.get("snapshots", [])

    if len(snapshots) < 2:
        return {"velocity": 0, "pct_change": 0, "direction": "STABLE",
                "n_snapshots": len(snapshots), "confidence": 0}

    idx_map = {"home": "home", "draw": "draw", "away": "away"}
    key = idx_map.get(tahmin, "home")

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_min)
    recent = []
    for s in snapshots:
        try:
            ts = datetime.fromisoformat(s["ts"])
            if ts >= cutoff:
                recent.append((ts, s.get(key, 0)))
        except Exception:
            continue

    if len(recent) < 2:
        # Use last 2 snapshots regardless of window
        last2 = [(None, s.get(key, 0)) for s in snapshots[-2:]]
        if last2[-1][1] == 0 or last2[0][1] == 0:
            return {"velocity": 0, "pct_change": 0, "direction": "STABLE",
                    "n_snapshots": 0, "confidence": 0}
        pct = (last2[-1][1] - last2[0][1]) / last2[0][1]
        direction = "UP" if pct > 0.005 else ("DOWN" if pct < -0.005 else "STABLE")
        return {"velocity": 0, "pct_change": round(pct, 4), "direction": direction,
                "n_snapshots": 2, "confidence": 0.2}

    recent.sort(key=lambda x: x[0])
    start_odds = recent[0][1]
    end_odds   = recent[-1][1]
    elapsed_h  = (recent[-1][0] - recent[0][0]).total_seconds() / 3600

    if start_odds <= 0 or elapsed_h <= 0:
        return {"velocity": 0, "pct_change": 0, "direction": "STABLE",
                "n_snapshots": len(recent), "confidence": 0}

    velocity  = (end_odds - start_odds) / elapsed_h  # odds per hour
    pct_change = (end_odds - start_odds) / start_odds
    direction = "UP" if pct_change > 0.005 else ("DOWN" if pct_change < -0.005 else "STABLE")
    confidence = min(1.0, len(recent) / 10)

    return {
        "velocity":    round(velocity, 4),
        "pct_change":  round(pct_change, 4),
        "direction":   direction,
        "n_snapshots": len(recent),
        "confidence":  round(confidence, 2),
        "start_odds":  round(start_odds, 3),
        "end_odds":    round(end_odds, 3),
    }


# ─────────────────────────────────────────────────────────────────
# 4. STEAM MOVE DETECTION
# ─────────────────────────────────────────────────────────────────

def steam_move_tespit(ev: str, dep: str, tarih: str,
                       tahmin: str = "home",
                       window_min: int = 30) -> dict:
    """
    Steam move: ALL or most books moving same direction quickly.
    Strong signal to follow (or avoid if you already bet that side).

    Returns:
        {"steam": bool, "direction": str, "strength": float, "books_moving": int}
    """
    mac_id = _mac_id(ev, dep, tarih)
    db = _yukle()
    snapshots = db.get(mac_id, {}).get("snapshots", [])

    if not snapshots:
        return {"steam": False, "direction": "NONE", "strength": 0, "books_moving": 0}

    key = {"home": "home", "draw": "draw", "away": "away"}.get(tahmin, "home")
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_min)

    # Group by bookmaker
    book_timelines: dict = {}
    for s in snapshots:
        try:
            ts = datetime.fromisoformat(s["ts"])
        except Exception:
            continue
        book = s.get("book", "?")
        if book not in book_timelines:
            book_timelines[book] = []
        book_timelines[book].append((ts, s.get(key, 0)))

    # Per-book direction in window
    moves = []
    for book, pts in book_timelines.items():
        pts.sort(key=lambda x: x[0])
        recent = [p for p in pts if p[0] >= cutoff]
        if len(recent) < 2:
            continue
        start = recent[0][1]
        end   = recent[-1][1]
        if start <= 0:
            continue
        pct = (end - start) / start
        if abs(pct) >= STEAM_VELOCITY_THRESHOLD:
            moves.append(pct)

    if len(moves) < STEAM_MIN_BOOKS:
        return {"steam": False, "direction": "NONE", "strength": 0,
                "books_moving": len(moves)}

    ups   = sum(1 for m in moves if m > 0)
    downs = sum(1 for m in moves if m < 0)
    is_steam = ups >= STEAM_MIN_BOOKS or downs >= STEAM_MIN_BOOKS
    direction = "UP" if ups > downs else "DOWN"
    strength  = abs(sum(moves) / len(moves)) if moves else 0

    return {
        "steam":        is_steam,
        "direction":    direction if is_steam else "NONE",
        "strength":     round(strength, 4),
        "books_moving": len(moves),
    }


# ─────────────────────────────────────────────────────────────────
# 5. REVERSE LINE MOVEMENT
# ─────────────────────────────────────────────────────────────────

def reverse_line_tespit(ev: str, dep: str, tarih: str,
                          tahmin: str = "home",
                          public_bet_pct: float = 0.60) -> dict:
    """
    Reverse Line Movement (RLM):
    Public money on one side (>60%) but line moves AGAINST them.
    = Sharp money is on the other side. Strong fade signal.

    Returns:
        {"rlm_detected": bool, "fade_side": str, "confidence": float}
    """
    velocity = odds_velocity_hesapla(ev, dep, tarih, tahmin=tahmin)
    direction = velocity.get("direction", "STABLE")

    # Public heavily favors `tahmin` side but odds moving UP for them
    # = public money is pushing odds UP (books balancing)
    # Actually: if public money heavy on home, odds should DROP (books balance)
    # If odds are going UP despite public money → sharps betting against public
    public_on_tahmin = public_bet_pct > 0.55

    if public_on_tahmin and direction == "UP":
        # Public on home, but home odds going up (= books expect more losses on home)
        # Wait — odds going up = less money on it. Public may be wrong.
        rlm = True
        fade_side = "away" if tahmin == "home" else "home"
        confidence = min(1.0, velocity.get("confidence", 0) * (public_bet_pct - 0.5) * 4)
    else:
        rlm = False
        fade_side = "none"
        confidence = 0.0

    return {
        "rlm_detected": rlm,
        "fade_side":    fade_side,
        "confidence":   round(confidence, 3),
        "odds_direction": direction,
        "velocity_pct":   velocity.get("pct_change", 0),
    }


# ─────────────────────────────────────────────────────────────────
# 6. MARKET ENTROPY
# ─────────────────────────────────────────────────────────────────

def market_entropy_hesapla(ev: str, dep: str, tarih: str,
                             tahmin: str = "home") -> dict:
    """
    Market entropy: how much do bookmakers disagree?
    High entropy = possible mispricing = opportunity.
    Low entropy  = consensus = harder to find edge.

    Returns entropy in [0, 1] (1 = maximum disagreement).
    """
    import math
    mac_id = _mac_id(ev, dep, tarih)
    db = _yukle()
    snapshots = db.get(mac_id, {}).get("snapshots", [])

    key = {"home": "home", "draw": "draw", "away": "away"}.get(tahmin, "home")

    # Get latest snapshot per bookmaker
    latest: dict = {}
    for s in snapshots:
        book = s.get("book", "?")
        if book not in latest or s["ts"] > latest[book]["ts"]:
            latest[book] = s

    odds_vals = [s.get(key, 0) for s in latest.values() if s.get(key, 0) > 1]

    if len(odds_vals) < 2:
        return {"entropy": 0, "n_books": len(odds_vals), "spread_pct": 0}

    min_odds = min(odds_vals)
    max_odds = max(odds_vals)
    mean_odds = sum(odds_vals) / len(odds_vals)
    spread_pct = (max_odds - min_odds) / mean_odds if mean_odds > 0 else 0

    # Normalize to [0, 1]: 10% spread = entropy 1.0
    entropy = min(1.0, spread_pct / 0.10)

    return {
        "entropy":    round(entropy, 3),
        "n_books":    len(odds_vals),
        "spread_pct": round(spread_pct, 4),
        "min_odds":   round(min_odds, 3),
        "max_odds":   round(max_odds, 3),
    }


# ─────────────────────────────────────────────────────────────────
# 7. FULL ANALYSIS — Single call for all signals
# ─────────────────────────────────────────────────────────────────

def tam_analiz(ev: str, dep: str, tarih: str, tahmin: str = "home") -> dict:
    """
    Run all timeline analyses for a match/selection.
    Use this in main.py before execution decision.

    Returns combined signal dict for the execution engine.
    """
    velocity = odds_velocity_hesapla(ev, dep, tarih, tahmin=tahmin)
    steam    = steam_move_tespit(ev, dep, tarih, tahmin=tahmin)
    entropy  = market_entropy_hesapla(ev, dep, tarih, tahmin=tahmin)

    # Entry signal synthesis
    if steam["steam"] and steam["direction"] == "DOWN":
        entry_signal = "ERKEN"   # Sharp money just caused steam drop → enter now
        entry_score  = 0.85
    elif velocity["direction"] == "DOWN" and velocity["confidence"] > 0.5:
        entry_signal = "ERKEN"   # Line drifting down → enter before it drops more
        entry_score  = 0.70
    elif velocity["direction"] == "UP" and velocity["pct_change"] > 0.03:
        entry_signal = "GEC"     # Odds rising → might get better odds, or market knows something
        entry_score  = 0.30
    else:
        entry_signal = "NORMAL"
        entry_score  = 0.50

    return {
        "velocity":     velocity,
        "steam":        steam,
        "entropy":      entropy,
        "entry_signal": entry_signal,
        "entry_score":  round(entry_score, 2),
    }


# ─────────────────────────────────────────────────────────────────
# 8. MAINTENANCE
# ─────────────────────────────────────────────────────────────────

def eski_kayitlari_temizle() -> int:
    """Remove match entries older than TIMELINE_MAX_AGE_DAYS."""
    db = _yukle()
    cutoff = datetime.now(timezone.utc) - timedelta(days=TIMELINE_MAX_AGE_DAYS)
    silinecek = []

    for mac_id, entry in db.items():
        tarih_str = entry.get("tarih", "")
        try:
            tarih = datetime.fromisoformat(tarih_str + "T00:00:00+00:00")
            if tarih < cutoff:
                silinecek.append(mac_id)
        except Exception:
            pass

    for mid in silinecek:
        del db[mid]

    if silinecek:
        _kaydet(db)
        logger.info(f"Timeline: {len(silinecek)} old entries pruned.")

    return len(silinecek)
