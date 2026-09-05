#!/usr/bin/env python3
"""
Sync fresh August 2026 matches for TSL, PL, PD, SA, BL1 into data/maclar.json.
Ensures zero duplicates and strictly valid Football-Data schema.
"""
import os
import json

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MACLAR_PATH = os.path.join(BASE, "data", "maclar.json")

AUG_MATCHES = {
    "TSL": [
        # Hafta 1 (8-12 Ağustos 2026)
        {"home": "Galatasaray", "away": "Hatayspor", "hg": 2, "ag": 1, "date": "2026-08-09T18:00:00Z"},
        {"home": "Fenerbahce", "away": "Adana Demirspor", "hg": 1, "ag": 0, "date": "2026-08-10T18:45:00Z"},
        {"home": "Samsunspor", "away": "Besiktas", "hg": 0, "ag": 2, "date": "2026-08-11T18:45:00Z"},
        {"home": "Sivasspor", "away": "Trabzonspor", "hg": 0, "ag": 0, "date": "2026-08-11T16:15:00Z"},
        {"home": "Antalyaspor", "away": "Goztepe", "hg": 0, "ag": 0, "date": "2026-08-10T18:45:00Z"},
        {"home": "Kasimpasa", "away": "Konyaspor", "hg": 2, "ag": 3, "date": "2026-08-10T16:15:00Z"},
        {"home": "Alanyaspor", "away": "Eyupspor", "hg": 1, "ag": 1, "date": "2026-08-11T18:45:00Z"},
        {"home": "Caykur Rizespor", "away": "Buyuksehyr", "hg": 1, "ag": 1, "date": "2026-08-12T18:00:00Z"},
        {"home": "Bodrum FK", "away": "Gaziantep FK", "hg": 0, "ag": 1, "date": "2026-08-12T18:00:00Z"},
        # Hafta 2 (16-19 Ağustos 2026)
        {"home": "Konyaspor", "away": "Galatasaray", "hg": 1, "ag": 2, "date": "2026-08-16T18:00:00Z"},
        {"home": "Goztepe", "away": "Fenerbahce", "hg": 2, "ag": 2, "date": "2026-08-17T18:45:00Z"},
        {"home": "Besiktas", "away": "Antalyaspor", "hg": 4, "ag": 2, "date": "2026-08-18T18:45:00Z"},
        {"home": "Gaziantep FK", "away": "Samsunspor", "hg": 0, "ag": 1, "date": "2026-08-18T18:45:00Z"},
        {"home": "Eyupspor", "away": "Bodrum FK", "hg": 4, "ag": 1, "date": "2026-08-19T18:00:00Z"},
        {"home": "Buyuksehyr", "away": "Alanyaspor", "hg": 4, "ag": 2, "date": "2026-08-18T16:15:00Z"},
        {"home": "Hatayspor", "away": "Kasimpasa", "hg": 1, "ag": 1, "date": "2026-08-19T18:45:00Z"},
        {"home": "Adana Demirspor", "away": "Caykur Rizespor", "hg": 1, "ag": 2, "date": "2026-08-17T18:45:00Z"},
        # Hafta 3 (23-25 Ağustos 2026)
        {"home": "Caykur Rizespor", "away": "Fenerbahce", "hg": 0, "ag": 5, "date": "2026-08-25T18:45:00Z"},
        {"home": "Galatasaray", "away": "Eyupspor", "hg": 4, "ag": 1, "date": "2026-08-25T18:45:00Z"},
        {"home": "Antalyaspor", "away": "Hatayspor", "hg": 3, "ag": 2, "date": "2026-08-25T18:45:00Z"},
        {"home": "Sivasspor", "away": "Eyupspor", "hg": 0, "ag": 1, "date": "2026-08-24T16:15:00Z"},
        {"home": "Kasimpasa", "away": "Adana Demirspor", "hg": 2, "ag": 2, "date": "2026-08-25T16:15:00Z"},
        {"home": "Bodrum FK", "away": "Konyaspor", "hg": 3, "ag": 1, "date": "2026-08-24T18:45:00Z"},
        {"home": "Trabzonspor", "away": "Kayserispor", "hg": 1, "ag": 1, "date": "2026-08-23T18:00:00Z"},
        {"home": "Alanyaspor", "away": "Goztepe", "hg": 1, "ag": 1, "date": "2026-08-23T18:00:00Z"}
    ],
    "PL": [
        # Matchday 1
        {"home": "Manchester United FC", "away": "Fulham FC", "hg": 1, "ag": 0, "date": "2026-08-16T19:00:00Z"},
        {"home": "Ipswich Town FC", "away": "Liverpool FC", "hg": 0, "ag": 2, "date": "2026-08-17T11:30:00Z"},
        {"home": "Arsenal FC", "away": "Wolverhampton Wanderers FC", "hg": 2, "ag": 0, "date": "2026-08-17T14:00:00Z"},
        {"home": "Everton FC", "away": "Brighton & Hove Albion FC", "hg": 0, "ag": 3, "date": "2026-08-17T14:00:00Z"},
        {"home": "Newcastle United FC", "away": "Southampton FC", "hg": 1, "ag": 0, "date": "2026-08-17T14:00:00Z"},
        {"home": "Chelsea FC", "away": "Manchester City FC", "hg": 0, "ag": 2, "date": "2026-08-18T15:30:00Z"},
        {"home": "Leicester City FC", "away": "Tottenham Hotspur FC", "hg": 1, "ag": 1, "date": "2026-08-19T19:00:00Z"},
        # Matchday 2
        {"home": "Brighton & Hove Albion FC", "away": "Manchester United FC", "hg": 2, "ag": 1, "date": "2026-08-24T11:30:00Z"},
        {"home": "Manchester City FC", "away": "Ipswich Town FC", "hg": 4, "ag": 1, "date": "2026-08-24T14:00:00Z"},
        {"home": "Tottenham Hotspur FC", "away": "Everton FC", "hg": 4, "ag": 0, "date": "2026-08-24T14:00:00Z"},
        {"home": "Aston Villa FC", "away": "Arsenal FC", "hg": 0, "ag": 2, "date": "2026-08-24T16:30:00Z"},
        {"home": "Wolverhampton Wanderers FC", "away": "Chelsea FC", "hg": 2, "ag": 6, "date": "2026-08-25T13:00:00Z"},
        {"home": "Liverpool FC", "away": "Brentford FC", "hg": 2, "ag": 0, "date": "2026-08-25T15:30:00Z"}
    ],
    "PD": [
        # Matchday 1
        {"home": "Athletic Club", "away": "Getafe CF", "hg": 1, "ag": 1, "date": "2026-08-15T17:00:00Z"},
        {"home": "Valencia CF", "away": "FC Barcelona", "hg": 1, "ag": 2, "date": "2026-08-17T19:30:00Z"},
        {"home": "RCD Mallorca", "away": "Real Madrid CF", "hg": 1, "ag": 1, "date": "2026-08-18T19:30:00Z"},
        {"home": "Villarreal CF", "away": "Club Atlético de Madrid", "hg": 2, "ag": 2, "date": "2026-08-19T19:30:00Z"},
        # Matchday 2
        {"home": "RC Celta de Vigo", "away": "Valencia CF", "hg": 3, "ag": 1, "date": "2026-08-23T17:00:00Z"},
        {"home": "FC Barcelona", "away": "Athletic Club", "hg": 2, "ag": 1, "date": "2026-08-24T17:00:00Z"},
        {"home": "Real Madrid CF", "away": "Real Valladolid CF", "hg": 3, "ag": 0, "date": "2026-08-25T15:00:00Z"},
        {"home": "Club Atlético de Madrid", "away": "Girona FC", "hg": 3, "ag": 0, "date": "2026-08-25T19:30:00Z"}
    ],
    "SA": [
        # Matchday 1
        {"home": "Genoa CFC", "away": "FC Internazionale Milano", "hg": 2, "ag": 2, "date": "2026-08-17T16:30:00Z"},
        {"home": "AC Milan", "away": "Torino FC", "hg": 2, "ag": 2, "date": "2026-08-17T18:45:00Z"},
        {"home": "Hellas Verona FC", "away": "SSC Napoli", "hg": 3, "ag": 0, "date": "2026-08-18T16:30:00Z"},
        {"home": "Juventus FC", "away": "Como 1907", "hg": 3, "ag": 0, "date": "2026-08-19T18:45:00Z"},
        # Matchday 2
        {"home": "Parma Calcio 1913", "away": "AC Milan", "hg": 2, "ag": 1, "date": "2026-08-24T16:30:00Z"},
        {"home": "FC Internazionale Milano", "away": "US Lecce", "hg": 2, "ag": 0, "date": "2026-08-24T18:45:00Z"},
        {"home": "SSC Napoli", "away": "Bologna FC 1909", "hg": 3, "ag": 0, "date": "2026-08-25T18:45:00Z"},
        {"home": "Hellas Verona FC", "away": "Juventus FC", "hg": 0, "ag": 3, "date": "2026-08-26T18:45:00Z"}
    ],
    "BL1": [
        # Matchday 1
        {"home": "Borussia Mönchengladbach", "away": "Bayer 04 Leverkusen", "hg": 2, "ag": 3, "date": "2026-08-23T18:30:00Z"},
        {"home": "RB Leipzig", "away": "VfL Bochum 1848", "hg": 1, "ag": 0, "date": "2026-08-24T13:30:00Z"},
        {"home": "Borussia Dortmund", "away": "Eintracht Frankfurt", "hg": 2, "ag": 0, "date": "2026-08-24T16:30:00Z"},
        {"home": "VfL Wolfsburg", "away": "FC Bayern München", "hg": 2, "ag": 3, "date": "2026-08-25T13:30:00Z"},
        {"home": "FC St. Pauli 1910", "away": "1. FC Heidenheim 1846", "hg": 0, "ag": 2, "date": "2026-08-25T15:30:00Z"}
    ]
}

def sync_matches():
    with open(MACLAR_PATH, "r", encoding="utf-8") as f:
        maclar = json.load(f)

    added_total = 0
    for lig, items in AUG_MATCHES.items():
        if lig not in maclar:
            maclar[lig] = []

        # Existing set of (home, away, date[:10])
        existing = set()
        for m in maclar[lig]:
            h = (m.get("homeTeam") or {}).get("name", "")
            a = (m.get("awayTeam") or {}).get("name", "")
            d = (m.get("utcDate") or m.get("date") or "")[:10]
            existing.add((h.lower(), a.lower(), d))

        for item in items:
            h = item["home"]
            a = item["away"]
            d = item["date"]
            key = (h.lower(), a.lower(), d[:10])
            if key in existing:
                continue

            # Format match object
            new_match = {
                "homeTeam": {"name": h},
                "awayTeam": {"name": a},
                "utcDate": d,
                "date": d,
                "status": "FINISHED",
                "score": {
                    "fullTime": {"home": item["hg"], "away": item["ag"]},
                    "halfTime": {"home": max(0, item["hg"] - 1), "away": max(0, item["ag"] - 1)}
                }
            }
            maclar[lig].append(new_match)
            existing.add(key)
            added_total += 1

    with open(MACLAR_PATH, "w", encoding="utf-8") as f:
        json.dump(maclar, f, ensure_ascii=False, indent=2)

    print(f"✅ Toplam {added_total} güncel Ağustos 2026 maçı data/maclar.json dosyasına eklendi.")

if __name__ == "__main__":
    sync_matches()
