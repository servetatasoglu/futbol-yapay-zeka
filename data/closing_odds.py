# data/closing_odds.py
"""
Closing Odds Collector — v3.0 (CLV Foundation)
═══════════════════════════════════════════════════
FIXES from v2.0:
  1. mac_id format was "_" separator → broke on team names with "_"
     → Now uses "|" separator (consistent with rest of system)
  2. Only captured 2h window → missed many closing lines
     → Now polls 4h window, every 30min schedule-friendly
  3. No timeline integration → CLV was blind to line movement
     → Now feeds odds_timeline.py on every fetch
  4. CLV tracker auto-update had broken matching logic
     → Fixed to use exact same mac_id format as clv_tracker

Closing odds = odds at market close (60-90 min before kickoff).
Pinnacle closing line is the gold standard for CLV calculation.
"""

import requests
import json
import os
import time
import logging
from datetime import datetime, timezone, timedelta
from config.settings import ODDS_API_KEY, LIGLER

logger = logging.getLogger("closing_odds")

BASE_DIR       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLOSING_CACHE  = os.path.join(BASE_DIR, "data", "odds_cache_closing.json")
TIMELINE_AKTIF = True   # Set False to disable timeline integration

# ── Collection window ─────────────────────────────────────────────
# Poll windows: matches within this many hours before kickoff
CLOSING_WINDOW_H = 4.0   # Start collecting closing odds 4h before kickoff
CLOSING_CUTOFF_H = -0.5  # Stop 30min after kickoff (avoids in-play odds)

# ── Sharp bookmakers in priority order ───────────────────────────
SHARP_PRIORITY = ["pinnacle", "betfair_ex_eu", "betfair", "matchbook"]


def _mac_id(ev: str, dep: str, tarih: str) -> str:
    """v3.0: Use | separator to avoid splitting on team names."""
    return f"{ev}|{dep}|{str(tarih)[:10]}"


def _load_cache() -> dict:
    if os.path.exists(CLOSING_CACHE):
        try:
            with open(CLOSING_CACHE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    os.makedirs(os.path.dirname(CLOSING_CACHE), exist_ok=True)
    with open(CLOSING_CACHE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _get_sharp_odds(bookmakers: list, ev_name: str, dep_name: str) -> dict:
    """
    Extract odds from sharpest available bookmaker.
    Returns {"ev": float, "ber": float, "dep": float, "source": str}
    or empty dict if nothing found.
    """
    # Try sharp books in priority order first
    for priority_book in SHARP_PRIORITY:
        for bk in bookmakers:
            if bk.get("key") != priority_book:
                continue
            for m in bk.get("markets", []):
                if m.get("key") != "h2h":
                    continue
                ev_o = ber_o = dep_o = 0.0
                for out in m.get("outcomes", []):
                    name = out.get("name", "")
                    price = float(out.get("price", 0))
                    if name == ev_name:
                        ev_o = price
                    elif name == dep_name:
                        dep_o = price
                    else:
                        ber_o = price
                if ev_o > 1.01 and dep_o > 1.01:
                    return {"ev": ev_o, "ber": ber_o, "dep": dep_o, "source": priority_book}

    # Fallback: use first available bookmaker
    for bk in bookmakers:
        for m in bk.get("markets", []):
            if m.get("key") != "h2h":
                continue
            ev_o = ber_o = dep_o = 0.0
            for out in m.get("outcomes", []):
                name = out.get("name", "")
                price = float(out.get("price", 0))
                if name == ev_name:
                    ev_o = price
                elif name == dep_name:
                    dep_o = price
                else:
                    ber_o = price
            if ev_o > 1.01 and dep_o > 1.01:
                return {"ev": ev_o, "ber": ber_o, "dep": dep_o,
                        "source": bk.get("key", "unknown")}

    return {}


def kapanis_oranlarini_getir() -> int:
    """
    Fetch closing odds for all matches within the collection window.
    Returns count of new closing odds records captured.

    Designed to be called by a scheduler (e.g., cron every 30min).
    API budget: ~14 calls per run × 2 runs/day = 28 calls/day.
    """
    logger.info("🔌 Closing odds (CLV) fetch started...")

    if not ODDS_API_KEY or ODDS_API_KEY in ("", "BURAYA_ODDS_API_KEY"):
        logger.warning("No ODDS_API_KEY — closing odds collection skipped.")
        return 0

    mevcut_cache = _load_cache()
    session = requests.Session()
    session.headers.update({"Accept": "application/json"})
    simdi = datetime.now(timezone.utc)
    yeni_kayitlar = 0

    for kod, bilgi in LIGLER.items():
        odds_key = bilgi["odds_key"]
        url = (
            f"https://api.the-odds-api.com/v4/sports/{odds_key}/odds/"
            f"?apiKey={ODDS_API_KEY}&regions=eu,uk&markets=h2h&oddsFormat=decimal"
        )

        try:
            r = session.get(url, timeout=20)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning(f"API error for {kod}: {e}")
            time.sleep(2)
            continue

        for game in data:
            if not isinstance(game, dict):
                continue

            commence_str = game.get("commence_time", "")
            if not commence_str:
                continue

            try:
                mac_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
            except Exception:
                continue

            saat_farki = (mac_dt - simdi).total_seconds() / 3600

            # Skip matches outside our collection window
            if not (CLOSING_CUTOFF_H <= saat_farki <= CLOSING_WINDOW_H):
                continue

            ev_name  = game.get("home_team", "")
            dep_name = game.get("away_team", "")
            tarih    = str(commence_str)[:10]
            mac_id   = _mac_id(ev_name, dep_name, tarih)

            bookmakers = game.get("bookmakers", [])
            sharp_odds = _get_sharp_odds(bookmakers, ev_name, dep_name)

            if not sharp_odds:
                continue

            # Store per-bookmaker odds for timeline (all books, not just sharp)
            if TIMELINE_AKTIF:
                try:
                    from data.odds_timeline import odds_snapshot_ekle
                    for bk in bookmakers:
                        bk_ev = bk_ber = bk_dep = 0.0
                        for m in bk.get("markets", []):
                            if m.get("key") != "h2h":
                                continue
                            for out in m.get("outcomes", []):
                                name = out.get("name", "")
                                price = float(out.get("price", 0))
                                if name == ev_name:
                                    bk_ev = price
                                elif name == dep_name:
                                    bk_dep = price
                                else:
                                    bk_ber = price
                        if bk_ev > 1.01 and bk_dep > 1.01:
                            odds_snapshot_ekle(
                                ev=ev_name, dep=dep_name, tarih=tarih,
                                bookmaker=bk.get("key", "?"),
                                home_odds=bk_ev, draw_odds=bk_ber, away_odds=bk_dep,
                            )
                except Exception as te:
                    logger.debug(f"Timeline update error: {te}")

            # Update cache with closing odds
            mevcut_cache[mac_id] = {
                "ev":        sharp_odds["ev"],
                "ber":       sharp_odds["ber"],
                "dep":       sharp_odds["dep"],
                "source":    sharp_odds["source"],
                "saat_kala": round(saat_farki, 2),
                "timestamp": simdi.isoformat(),
            }
            yeni_kayitlar += 1
            logger.info(
                f"  📸 CLV Snapshot: {ev_name} vs {dep_name} "
                f"({saat_farki:.1f}h) [{sharp_odds['source']}] "
                f"{sharp_odds['ev']:.2f} / {sharp_odds['ber']:.2f} / {sharp_odds['dep']:.2f}"
            )

        time.sleep(1.5)  # Rate limit protection

    if yeni_kayitlar > 0:
        _save_cache(mevcut_cache)
        logger.info(f"✅ {yeni_kayitlar} closing odds records saved.")

        # ── Auto-update CLV tracker ───────────────────────────────
        _clv_tracker_guncelle(mevcut_cache)

    return yeni_kayitlar


def _clv_tracker_guncelle(cache: dict) -> int:
    """
    Push cached closing odds to clv_tracker for every matching bet.
    Returns count of bets updated.
    """
    try:
        from tracking.clv_tracker import closing_odds_guncelle
    except ImportError:
        return 0

    guncellenen = 0
    for mac_id, odds in cache.items():
        # mac_id format: "ev|dep|YYYY-MM-DD"
        parts = mac_id.split("|")
        if len(parts) != 3:
            continue
        ev_t, dep_t, _ = parts
        try:
            updated = closing_odds_guncelle(ev_t, dep_t, {
                "ev":  odds.get("ev",  0.0),
                "ber": odds.get("ber", 0.0),
                "dep": odds.get("dep", 0.0),
            })
            if updated:
                guncellenen += 1
        except Exception as e:
            logger.debug(f"CLV tracker update error {mac_id}: {e}")

    if guncellenen > 0:
        logger.info(f"  ✅ CLV tracker: {guncellenen} bets updated with closing odds.")

    return guncellenen


def closing_odds_getir(ev: str, dep: str, tarih: str) -> dict:
    """
    Retrieve stored closing odds for a specific match.
    Returns {"ev", "ber", "dep", "source", "saat_kala"} or {}.
    """
    cache = _load_cache()
    mac_id = _mac_id(ev, dep, tarih)
    return cache.get(mac_id, {})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    n = kapanis_oranlarini_getir()
    print(f"\nToplam: {n} closing odds kaydı")
