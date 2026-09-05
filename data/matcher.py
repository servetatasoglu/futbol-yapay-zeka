# analysis/isim_eslestir.py
"""
Takım ismi eşleştirme modülü — PRODUCTION v2
GÜNCELLENDİ: rapidfuzz, cache, Süper Lig, 2. Bundesliga, Brasileirao düzeltmeleri.
"""

import os
import re
import json
import logging
from functools import lru_cache

# rapidfuzz yoksa difflib'e fallback
try:
    from rapidfuzz import fuzz, process
    RAPIDFUZZ_AKTIF = True
except ImportError:
    from difflib import SequenceMatcher
    RAPIDFUZZ_AKTIF = False

logger = logging.getLogger("matcher")

# ─── SESSION CACHE: Aynı isim tekrar hesaplanmasın ───────────────────
_eslestirme_cache = {}

MANUEL_ESLESTIRME = {
    # ── Premier League ───────────────────────────────────────
    "Manchester City":          "Manchester City FC",
    "Manchester United":        "Manchester United FC",
    "Arsenal":                  "Arsenal FC",
    "Chelsea":                  "Chelsea FC",
    "Liverpool":                "Liverpool FC",
    "Tottenham Hotspur":        "Tottenham Hotspur FC",
    "Tottenham":                "Tottenham Hotspur FC",
    "Newcastle United":         "Newcastle United FC",
    "Aston Villa":              "Aston Villa FC",
    "West Ham United":          "West Ham United FC",
    "West Ham":                 "West Ham United FC",
    "Brighton and Hove Albion": "Brighton & Hove Albion FC",
    "Brighton":                 "Brighton & Hove Albion FC",
    "Brentford":                "Brentford FC",
    "Fulham":                   "Fulham FC",
    "Crystal Palace":           "Crystal Palace FC",
    "Everton":                  "Everton FC",
    "Nottingham Forest":        "Nottingham Forest FC",
    "Wolverhampton Wanderers":  "Wolverhampton Wanderers FC",
    "Wolves":                   "Wolverhampton Wanderers FC",
    "Bournemouth":              "AFC Bournemouth",
    "Leicester City":           "Leicester City FC",
    "Ipswich Town":             "Ipswich Town FC",
    "Ipswich":                  "Ipswich Town FC",
    "Southampton":              "Southampton FC",
    "Leeds United":             "Leeds United FC",
    "Leeds":                    "Leeds United FC",
    "Sunderland":               "Sunderland AFC",
    "Sheffield United":         "Sheffield United FC",
    "Sheffield Wednesday":      "Sheffield Wednesday FC",
    "Middlesbrough":            "Middlesbrough FC",
    "Burnley":                  "Burnley FC",
    "Coventry City":            "Coventry City FC",
    "Coventry":                 "Coventry City FC",
    "Stoke City":               "Stoke City FC",
    "Stoke":                    "Stoke City FC",
    "Swansea City":             "Swansea City AFC",
    "Swansea":                  "Swansea City AFC",
    "Queens Park Rangers":      "Queens Park Rangers FC",
    "QPR":                      "Queens Park Rangers FC",
    "Millwall":                 "Millwall FC",
    "Preston North End":        "Preston North End FC",
    "Preston":                  "Preston North End FC",
    "Bristol City":             "Bristol City FC",
    "Hull City":                "Hull City AFC",
    "Hull":                     "Hull City AFC",
    "Norwich City":             "Norwich City FC",
    "Norwich":                  "Norwich City FC",
    "Watford":                  "Watford FC",
    "Derby County":             "Derby County FC",
    "Derby":                    "Derby County FC",
    "Oxford United":            "Oxford United FC",
    "Oxford":                   "Oxford United FC",
    "Plymouth Argyle":          "Plymouth Argyle FC",
    "Plymouth":                 "Plymouth Argyle FC",
    "Luton Town":               "Luton Town FC",
    "Luton":                    "Luton Town FC",
    "Blackburn Rovers":         "Blackburn Rovers FC",
    "Blackburn":                "Blackburn Rovers FC",
    "Blackpool":                "Blackpool FC",
    "Cardiff City":             "Cardiff City FC",
    "Cardiff":                  "Cardiff City FC",
    "Portsmouth":               "Portsmouth FC",
    "Wigan Athletic":           "Wigan Athletic FC",
    "Wigan":                    "Wigan Athletic FC",
    "Rotherham United":         "Rotherham United FC",
    "Rotherham":                "Rotherham United FC",
    "Northampton Town":         "Northampton Town FC",
    "Northampton":              "Northampton Town FC",
    "Burton Albion":            "Burton Albion FC",
    "Burton":                   "Burton Albion FC",
    "Bradford City":            "Bradford City AFC",
    "Bradford":                 "Bradford City AFC",
    "Doncaster Rovers":         "Doncaster Rovers FC",
    "Doncaster":                "Doncaster Rovers FC",
    "Bolton Wanderers":         "Bolton Wanderers FC",
    "Bolton":                   "Bolton Wanderers FC",
    "Barnsley":                 "Barnsley FC",
    "Huddersfield Town":        "Huddersfield Town AFC",
    "Huddersfield":             "Huddersfield Town AFC",
    "Charlton Athletic":        "Charlton Athletic FC",
    "Charlton":                 "Charlton Athletic FC",
    "Birmingham City":          "Birmingham City FC",
    "Birmingham":               "Birmingham City FC",
    "Peterborough United":      "Peterborough United FC",
    "Peterborough":             "Peterborough United FC",
    "Reading":                  "Reading FC",
    "Exeter City":              "Exeter City FC",
    "Exeter":                   "Exeter City FC",
    "Cambridge United":         "Cambridge United FC",
    "Wycombe Wanderers":        "Wycombe Wanderers FC",
    "Wycombe":                  "Wycombe Wanderers FC",
    "Shrewsbury Town":          "Shrewsbury Town FC",
    "Shrewsbury":               "Shrewsbury Town FC",
    "Port Vale":                "Port Vale FC",
    "Stevenage":                "Stevenage FC",
    "Wrexham":                  "Wrexham AFC",
    "Stockport County":         "Stockport County FC",
    "Stockport":                "Stockport County FC",
    "Leyton Orient":            "Leyton Orient FC",
    "Fleetwood Town":           "Fleetwood Town FC",
    "Fleetwood":                "Fleetwood Town FC",

    # ── La Liga ──────────────────────────────────────────────
    "Barcelona":                "FC Barcelona",
    "Real Madrid":              "Real Madrid CF",
    "Atletico Madrid":          "Club Atlético de Madrid",
    "Atlético Madrid":          "Club Atlético de Madrid",
    "Athletic Bilbao":          "Athletic Club",
    "Athletic Club":            "Athletic Club",
    "Real Sociedad":            "Real Sociedad de Fútbol",
    "Villarreal":               "Villarreal CF",
    "Real Betis":               "Real Betis Balompié",
    "Sevilla":                  "Sevilla FC",
    "Valencia":                 "Valencia CF",
    "Osasuna":                  "CA Osasuna",
    "Celta Vigo":               "RC Celta de Vigo",
    "Celta":                    "RC Celta de Vigo",
    "Getafe":                   "Getafe CF",
    "Rayo Vallecano":           "Rayo Vallecano de Madrid",
    "Mallorca":                 "RCD Mallorca",
    "Las Palmas":               "UD Las Palmas",
    "Alaves":                   "Deportivo Alavés",
    "Alavés":                   "Deportivo Alavés",
    "Espanyol":                 "RCD Espanyol de Barcelona",
    "Leganes":                  "CD Leganés",
    "Leganés":                  "CD Leganés",
    "Valladolid":               "Real Valladolid CF",
    "Girona":                   "Girona FC",
    "Oviedo":                   "Real Oviedo",
    "Real Oviedo":              "Real Oviedo",
    "Cadiz":                    "Cádiz CF",
    "Cádiz":                    "Cádiz CF",
    "Granada":                  "Granada CF",

    # ── Bundesliga ───────────────────────────────────────────
    "Bayern Munich":            "FC Bayern München",
    "Bayer Leverkusen":         "Bayer 04 Leverkusen",
    "Borussia Dortmund":        "Borussia Dortmund",
    "RB Leipzig":               "RB Leipzig",
    "Eintracht Frankfurt":      "Eintracht Frankfurt",
    "Frankfurt":                "Eintracht Frankfurt",
    "VfB Stuttgart":            "VfB Stuttgart",
    "Stuttgart":                "VfB Stuttgart",
    "SC Freiburg":              "Sport-Club Freiburg",
    "Freiburg":                 "Sport-Club Freiburg",
    "Werder Bremen":            "SV Werder Bremen",
    "Bremen":                   "SV Werder Bremen",
    "Hoffenheim":               "TSG 1899 Hoffenheim",
    "TSG Hoffenheim":           "TSG 1899 Hoffenheim",
    "Mainz 05":                 "1. FSV Mainz 05",
    "Mainz":                    "1. FSV Mainz 05",
    "Borussia Monchengladbach": "Borussia Mönchengladbach",
    "Monchengladbach":          "Borussia Mönchengladbach",
    "FC Augsburg":              "FC Augsburg",
    "Augsburg":                 "FC Augsburg",
    "Union Berlin":             "1. FC Union Berlin",
    "VfL Wolfsburg":            "VfL Wolfsburg",
    "Wolfsburg":                "VfL Wolfsburg",
    "VfL Bochum":               "VfL Bochum 1848",
    "Bochum":                   "VfL Bochum 1848",
    "Heidenheim":               "1. FC Heidenheim 1846",
    "Holstein Kiel":            "Holstein Kiel",
    "St. Pauli":                "FC St. Pauli",
    "FC St. Pauli":             "FC St. Pauli",
    "Hamburger SV":             "Hamburger SV",
    "Hamburg":                  "Hamburger SV",
    "Hertha Berlin":            "Hertha BSC",
    "Hertha":                   "Hertha BSC",
    "Schalke":                  "FC Schalke 04",
    "Fortuna Dusseldorf":       "Fortuna Düsseldorf",
    "Darmstadt":                "SV Darmstadt 98",

    # ── Serie A ──────────────────────────────────────────────
    "AC Milan":                 "AC Milan",
    "Milan":                    "AC Milan",
    "Inter Milan":              "FC Internazionale Milano",
    "Inter":                    "FC Internazionale Milano",
    "Internazionale":           "FC Internazionale Milano",
    "Juventus":                 "Juventus FC",
    "Napoli":                   "SSC Napoli",
    "AS Roma":                  "AS Roma",
    "Roma":                     "AS Roma",
    "Lazio":                    "SS Lazio",
    "Atalanta":                 "Atalanta BC",
    "Fiorentina":               "ACF Fiorentina",
    "Torino":                   "Torino FC",
    "Bologna":                  "Bologna FC 1909",
    "Udinese":                  "Udinese Calcio",
    "Cagliari":                 "Cagliari Calcio",
    "Genoa":                    "Genoa CFC",
    "Empoli":                   "Empoli FC",
    "Lecce":                    "US Lecce",
    "Venezia":                  "Venezia FC",
    "Parma":                    "Parma Calcio 1913",
    "Como":                     "Como 1907",
    "Hellas Verona":            "Hellas Verona FC",
    "Verona":                   "Hellas Verona FC",
    "Monza":                    "AC Monza",
    "Sassuolo":                 "US Sassuolo Calcio",
    "US Sassuolo":              "US Sassuolo Calcio",
    "Cremonese":                "US Cremonese",
    "Spezia":                   "Spezia Calcio",
    "Salernitana":              "US Salernitana 1919",
    "Frosinone":                "Frosinone Calcio",
    "Sampdoria":                "UC Sampdoria",

    # ── Ligue 1 ──────────────────────────────────────────────
    "Paris Saint-Germain":      "Paris Saint-Germain FC",
    "PSG":                      "Paris Saint-Germain FC",
    "Monaco":                   "AS Monaco FC",
    "Marseille":                "Olympique de Marseille",
    "Lyon":                     "Olympique Lyonnais",
    "Lens":                     "RC Lens",
    "Lille":                    "LOSC Lille",
    "Nice":                     "OGC Nice",
    "Rennes":                   "Stade Rennais FC 1901",
    "Strasbourg":               "RC Strasbourg Alsace",
    "Nantes":                   "FC Nantes",
    "Reims":                    "Stade de Reims",
    "Toulouse":                 "Toulouse FC",
    "Le Havre":                 "Le Havre AC",
    "Montpellier":              "Montpellier HSC",
    "Brest":                    "Stade Brestois 29",
    "Saint-Etienne":            "AS Saint-Étienne",
    "Saint-Étienne":            "AS Saint-Étienne",
    "Auxerre":                  "AJ Auxerre",
    "Angers":                   "Angers SCO",
    "Metz":                     "FC Metz",
    "Clermont":                 "Clermont Foot 63",
    "Lorient":                  "FC Lorient",
    "Troyes":                   "ESTAC Troyes",
    "Bordeaux":                 "FC Girondins de Bordeaux",
    "Nimes":                    "Nîmes Olympique",

    # ── Eredivisie ───────────────────────────────────────────
    "Ajax":                     "AFC Ajax",
    "PSV":                      "PSV",
    "PSV Eindhoven":            "PSV",
    "Feyenoord":                "Feyenoord Rotterdam",
    "AZ Alkmaar":               "AZ",
    "AZ":                       "AZ",
    "Utrecht":                  "FC Utrecht",
    "Twente":                   "FC Twente '65",
    "FC Twente":                "FC Twente '65",
    "Sparta Rotterdam":         "Sparta Rotterdam",
    "Go Ahead Eagles":          "Go Ahead Eagles",
    "NEC Nijmegen":             "NEC",
    "NEC":                      "NEC",
    "Heerenveen":               "SC Heerenveen",
    "Groningen":                "FC Groningen",
    "Almere City":              "Almere City FC",
    "RKC Waalwijk":             "RKC Waalwijk",
    "PEC Zwolle":               "PEC Zwolle",
    "Heracles":                 "Heracles Almelo",
    "Fortuna Sittard":          "Fortuna Sittard",
    "NAC Breda":                "NAC Breda",
    "NAC":                      "NAC Breda",
    "Willem II":                "Willem II",
    "Excelsior":                "SBV Excelsior",
    "Volendam":                 "FC Volendam",
    "Vitesse":                  "Vitesse",

    # ── Primeira Liga ────────────────────────────────────────
    "Benfica":                  "Sport Lisboa e Benfica",
    "Porto":                    "FC Porto",
    "Sporting CP":              "Sporting Clube de Portugal",
    "Sporting":                 "Sporting Clube de Portugal",
    "Sporting Lisbon":          "Sporting Clube de Portugal",
    "Sporting Lisboa":          "Sporting Clube de Portugal",
    "Braga":                    "Sporting Clube de Braga",
    "Vitoria Guimaraes":        "Vitória SC",
    "Vitoria SC":               "Vitória SC",
    "Moreirense":               "Moreirense FC",
    "Famalicao":                "FC Famalicão",
    "Famalicão":                "FC Famalicão",
    "Estoril":                  "GD Estoril Praia",
    "Boavista":                 "Boavista FC",
    "Gil Vicente":              "Gil Vicente FC",
    "Casa Pia":                 "Casa Pia AC",
    "Rio Ave":                  "Rio Ave FC",
    "Rio Ave FC":               "Rio Ave FC",
    "Arouca":                   "FC Arouca",
    "Nacional":                 "CD Nacional",
    "Estrela Amadora":          "CF Estrela da Amadora",
    "CF Estrela":               "CF Estrela da Amadora",
    "CF Estrela da Amadora":    "CF Estrela da Amadora",
    "Santa Clara":              "CD Santa Clara",
    "AVS":                      "AVS",
    "AVS Futebol SAD":          "AVS",
    "Tondela":                  "CD Tondela",
    "Chaves":                   "GD Chaves",
    "Vizela":                   "FC Vizela",
    "Penafiel":                 "FC Penafiel",
    "Pacos de Ferreira":        "FC Paços de Ferreira",
    "Academica":                "Associação Académica de Coimbra",

    # ── Brasileirao ──────────────────────────────────────────
    "Atletico Mineiro":         "Clube Atlético Mineiro",
    "Atlético Mineiro":         "Clube Atlético Mineiro",
    "Atletico Paranaense":      "Club Athletico Paranaense",
    "Athletico Paranaense":     "Club Athletico Paranaense",
    "Athletico-PR":             "Club Athletico Paranaense",
    "Flamengo":                 "Clube de Regatas do Flamengo",
    "Fluminense":               "Fluminense FC",
    "Botafogo":                 "Botafogo de Futebol e Regatas",
    "Botafogo FR":              "Botafogo de Futebol e Regatas",
    "Vasco da Gama":            "Club de Regatas Vasco da Gama",
    "Vasco":                    "Club de Regatas Vasco da Gama",
    "Palmeiras":                "Sociedade Esportiva Palmeiras",
    "Corinthians":              "Sport Club Corinthians Paulista",
    "Santos":                   "Santos FC",
    "Sao Paulo":                "São Paulo FC",
    "São Paulo":                "São Paulo FC",
    "Internacional":            "Sport Club Internacional",
    "Gremio":                   "Grêmio Foot-Ball Porto Alegrense",
    "Grêmio":                   "Grêmio Foot-Ball Porto Alegrense",
    "Bahia":                    "Esporte Clube Bahia",
    "EC Bahia":                 "Esporte Clube Bahia",
    "Fortaleza":                "Fortaleza Esporte Clube",
    "Cruzeiro":                 "Cruzeiro Esporte Clube",
    "Bragantino":               "Red Bull Bragantino",
    "Red Bull Bragantino":      "Red Bull Bragantino",
    "Cuiaba":                   "Cuiabá Esporte Clube",
    "Cuiabá":                   "Cuiabá Esporte Clube",
    "Ceara":                    "Ceará Sporting Club",
    "Coritiba":                 "Coritiba Football Club",
    "Avai":                     "Avaí FC",
    "Juventude":                "Esporte Clube Juventude",
    "Goias":                    "Goiás Esporte Clube",
    "América Mineiro":          "América Futebol Clube (MG)",
    "America Mineiro":          "América Futebol Clube (MG)",
    "Sport Recife":             "Sport Club do Recife",
    "Vitoria":                  "Esporte Clube Vitória",
    "Criciuma":                 "Criciúma Esporte Clube",
    "Mirassol":                 "Mirassol FC",
    "Novorizontino":            "Novorizontino",

    # ── Champions League / Europa League ─────────────────────
    "Shakhtar Donetsk":         "FC Shakhtar Donetsk",
    "Celtic":                   "Celtic FC",
    "Rangers":                  "Rangers FC",
    "Red Bull Salzburg":        "FC Red Bull Salzburg",
    "Salzburg":                 "FC Red Bull Salzburg",
    "Club Brugge":              "Club Brugge KV",
    "Anderlecht":               "RSC Anderlecht",
    "Slavia Prague":            "SK Slavia Praha",
    "Viktoria Plzen":           "FC Viktoria Plzeň",
    "Olympiakos":               "Olympiacos FC",
    "PAOK":                     "PAOK FC",
    "Young Boys":               "BSC Young Boys",
    "Basel":                    "FC Basel",
    "Zenit":                    "Zenit St. Petersburg",
    "Dynamo Kyiv":              "FC Dynamo Kyiv",
    "Bodo Glimt":               "FK Bodø/Glimt",
    "Bodo/Glimt":               "FK Bodø/Glimt",
    "Galatasaray":              "Galatasaray SK",
    "Fenerbahce":               "Fenerbahçe SK",
    "Fenerbahçe":               "Fenerbahçe SK",
    "Besiktas":                 "Beşiktaş JK",
    "Beşiktaş":                 "Beşiktaş JK",
    "Porto (CL)":               "FC Porto",
    "Benfica (CL)":             "SL Benfica",
    "Sporting CP (CL)":         "Sporting CP",
    "PSV (CL)":                 "PSV",
    "Feyenoord (CL)":           "Feyenoord",
    "Ajax (CL)":                "AFC Ajax",

    # ── Eksik / Yeni Aliaslar (Otomatik düzeltildi) ───────────────
    # Hollanda
    "FC Twente Enschede":       "FC Twente '65",
    "Twente Enschede":          "FC Twente '65",
    "Feyenoord Rotterdam":      "Feyenoord Rotterdam",

    # Portekiz (farklı Odds API formatları)
    "Sporting de Lisboa":       "Sporting Clube de Portugal",
    "SC Braga":                 "Sporting Clube de Braga",
    "Braga SC":                 "Sporting Clube de Braga",

    # Avrupa Ligler (CL/EL)
    "Ferencváros TC":          "Ferencváros TC",
    "Ferencvaros TC":           "Ferencváros TC",
    "Ferencvaros":              "Ferencváros TC",
    "Ferencváros":             "Ferencváros TC",
    "FC Midtjylland":           "FC Midtjylland",
    "Midtjylland":              "FC Midtjylland",
    "KRC Genk":                 "KRC Genk",
    "Genk":                     "KRC Genk",
    "Panathinaikos FC":         "Panathinaikos FC",
    "Panathinaikos":            "Panathinaikos FC",

    # Brezilya (Odds API kodu farklı)
    "Bragantino-SP":            "Red Bull Bragantino",
    "Bragantino SP":            "Red Bull Bragantino",
    "Remo":                     "Clube do Remo",
    "Chapecoense":              "Associação Chapecoense de Futebol",

    # ── Süper Lig ────────────────────────────────────────────
    "Galatasaray":              "Galatasaray SK",
    "Galatasaray SK":           "Galatasaray SK",
    "Fenerbahce":               "Fenerbahçe SK",
    "Fenerbahçe":               "Fenerbahçe SK",
    "Fenerbahçe SK":            "Fenerbahçe SK",
    "Besiktas":                 "Beşiktaş JK",
    "Beşiktaş":                 "Beşiktaş JK",
    "Beşiktaş JK":              "Beşiktaş JK",
    "Trabzonspor":              "Trabzonspor",
    "Basaksehir":               "İstanbul Başakşehir FK",
    "Istanbul Basaksehir":      "İstanbul Başakşehir FK",
    "Goztepe":                  "Göztepe SK",
    "Göztepe":                  "Göztepe SK",
    "Antalyaspor":              "Antalyaspor",
    "Konyaspor":                "Konyaspor",
    "Torku Konyaspor":          "Konyaspor",
    "Sivasspor":                "Sivasspor",
    "Kasimpasa":                "Kasımpaşa SK",
    "Kasimpasa SK":             "Kasımpaşa SK",
    "Kasımpaşa":                "Kasımpaşa SK",
    "Rizespor":                 "Çaykur Rizespor",
    "Çaykur Rizespor":          "Çaykur Rizespor",
    "Caykur Rizespor":          "Çaykur Rizespor",
    "Gaziantep":                "Gazişehir Gaziantep FK",
    "Gazişehir Gaziantep":      "Gazişehir Gaziantep FK",
    "Gaziantep FK":             "Gazişehir Gaziantep FK",
    "Hatayspor":                "Hatayspor",
    "Samsunspor":               "Samsunspor",
    "Adana Demirspor":          "Adana Demirspor",
    "Eyüpspor":                 "Eyüpspor",
    "Kocaelispor":              "Kocaelispor",
    "Fatih Karagümrük":         "Fatih Karagümrük",
    "Karagümrük":               "Fatih Karagümrük",
    "Pendikspor":               "Pendikspor",
    "Bodrum FK":                "Bodrum FK",
    "Kayserispor":              "Kayserispor",
    "Alanyaspor":               "Alanyaspor",
    "Giresunspor":              "Giresunspor",

    # ── 2. Bundesliga ────────────────────────────────────────
    "1. FC Köln":               "1. FC Köln",
    "FC Köln":                  "1. FC Köln",
    "Köln":                     "1. FC Köln",
    "Elversberg":               "SV 07 Elversberg",
    "SV Elversberg":            "SV 07 Elversberg",
    "SC Paderborn":             "SC Paderborn 07",
    "Paderborn":                "SC Paderborn 07",
    "1. FC Magdeburg":          "1. FC Magdeburg",
    "Magdeburg":                "1. FC Magdeburg",
    "VfL Bochum":               "VfL Bochum 1848",
    "Eintracht Braunschweig":   "Eintracht Braunschweig",
    "Braunschweig":             "Eintracht Braunschweig",
    "FC Schalke 04":            "FC Schalke 04",
    "Schalke 04":               "FC Schalke 04",
    "Schalke":                  "FC Schalke 04",
    "FC Nürnberg":              "1. FC Nürnberg",
    "Nürnberg":                 "1. FC Nürnberg",
    "Greuther Fürth":           "SpVgg Greuther Fürth",
    "Kaiserslautern":           "1. FC Kaiserslautern",
    "Karlsruher SC":            "Karlsruher SC",
    "Karlsruhe":                "Karlsruher SC",
    "Hannover 96":              "Hannover 96",
    "Hannover":                 "Hannover 96",
    "Preußen Münster":          "SC Preußen Münster",
    "SSV Ulm 1846":             "SSV Ulm 1846",

    # ── Ligue 1 düzeltmeler ──────────────────────────────────
    "LOSC Lille":               "LOSC Lille",
    "Lille OSC":                "LOSC Lille",

    # ── Primeira Liga ek ──────────────────────────────────────
    "FC Porto":                 "FC Porto",
    "Alverca":                  "FC Alverca",
}

# Ters eşleşme tablosu (DB ismi → API ismi)
_TERS = {v: k for k, v in MANUEL_ESLESTIRME.items()}

# ─── Normalize fonksiyonu (prefix/suffix temizleme) ─────────────────
def _normalize(isim):
    """İsmi normalize et: küçük harf, özel karakter temizle, prefix sil."""
    isim = isim.lower().strip()
    # FC, SC, AC gibi prefix/suffix'leri temizle
    isim = re.sub(r'\b(fc|cf|ac|sc|rc|ss|as|us|ud|cd|ca|vfl|vfb|sv|fsv|1\.|afc|rcd|og[cm]|hsc|sk|jk|fk|ssc|sbc)\b', '', isim)
    # Özel karakterleri boşluğa çevir
    isim = re.sub(r'[^a-z0-9 ]', ' ', isim)
    isim = re.sub(r'\s+', ' ', isim).strip()
    return isim


def _fuzzy_skor(a, b):
    """İki isim arası benzerlik skoru (0-100). rapidfuzz varsa kullan."""
    if RAPIDFUZZ_AKTIF:
        # token_sort_ratio: kelime sırası farklı olsa da eşleştirir
        return fuzz.token_sort_ratio(_normalize(a), _normalize(b))
    else:
        from difflib import SequenceMatcher
        return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio() * 100


def eslestir(odds_isim: str, veritabani_isimleri) -> str | None:
    """
    Odds API ismini veritabanı ismine eşleştirir.
    
    Sıralama:
        1. Direkt eşleşme (O(1) lookup)
        2. Manuel sözlük
        3. Normalize direkt eşleşme
        4. rapidfuzz fuzzy matching (threshold: 75)
    
    Cache: Session boyunca aynı isim tekrar hesaplanmaz.
    """
    if not odds_isim:
        return None
        
    # ── CACHE KONTROLÜ ────────────────────────────────────────────
    cache_key = odds_isim
    if cache_key in _eslestirme_cache:
        return _eslestirme_cache[cache_key]
    
    # ── 1. Direkt eşleşme ──────────────────────────────────────────
    if odds_isim in veritabani_isimleri:
        _eslestirme_cache[cache_key] = odds_isim
        return odds_isim

    # ── 2. Manuel sözlük ──────────────────────────────────────────
    if odds_isim in MANUEL_ESLESTIRME:
        eslesen = MANUEL_ESLESTIRME[odds_isim]
        if eslesen in veritabani_isimleri:
            _eslestirme_cache[cache_key] = eslesen
            return eslesen
        # DB'de tam isim yoksa normalize karşılaştır
        norm_eslesen = _normalize(eslesen)
        for db_isim in veritabani_isimleri:
            if _normalize(db_isim) == norm_eslesen:
                _eslestirme_cache[cache_key] = db_isim
                return db_isim
        # Manuel eşleşme var ama DB'de bu takım yok → veri eksik
        _eslestirme_cache[cache_key] = "SKIPPED_NO_DATA"
        return "SKIPPED_NO_DATA"

    # ── 3. Normalize edilmiş direkt eşleşme ───────────────────────
    norm_odds = _normalize(odds_isim)
    for db_isim in veritabani_isimleri:
        if _normalize(db_isim) == norm_odds:
            _eslestirme_cache[cache_key] = db_isim
            return db_isim

    # ── 4. Fuzzy matching ─────────────────────────────────────────
    FUZZY_ESIK = 75  # %75 benzerlik (rapidfuzz 0-100 arası)
    en_iyi = None
    en_iyi_skor = 0.0

    if RAPIDFUZZ_AKTIF:
        # rapidfuzz.process.extractOne → O(n) ama C seviyesinde hızlı
        sonuc = process.extractOne(
            _normalize(odds_isim),
            {db: _normalize(db) for db in veritabani_isimleri},
            scorer=fuzz.token_sort_ratio,
            score_cutoff=FUZZY_ESIK
        )
        if sonuc:
            en_iyi = sonuc[2]  # key (orijinal DB ismi)
            en_iyi_skor = sonuc[1]
    else:
        # difflib fallback
        for db_isim in veritabani_isimleri:
            skor = _fuzzy_skor(odds_isim, db_isim)
            if skor > en_iyi_skor:
                en_iyi_skor = skor
                en_iyi = db_isim

    if en_iyi and en_iyi_skor >= FUZZY_ESIK:
        _eslestirme_cache[cache_key] = en_iyi
        return en_iyi

    # ── Eşleşme BAŞARISIZ ─────────────────────────────────────────
    _eslestirme_cache[cache_key] = None
    return None


def cache_temizle():
    """Session cache'ini temizle (test/debug için)."""
    global _eslestirme_cache
    _eslestirme_cache = {}


def eslestirme_raporu(mac_listesi: list, istatistikler: dict) -> dict:
    """
    Eşleşme başarı raporunu üretir ve eşleşmeyen takımları loglar.
    
    Döndürür:
        {"eslesen": int, "toplam": int, "oran": float, "eslesmeyenler": [str]}
    """
    eslesen = 0
    atlanan = 0
    eslesmeen = []
    db_isimleri = list(istatistikler.keys())

    for mac in mac_listesi:
        for takim in [mac.get("ev", ""), mac.get("dep", "")]:
            if not takim:
                continue
            sonuc = eslestir(takim, db_isimleri)
            if sonuc == "SKIPPED_NO_DATA":
                atlanan += 1
            elif sonuc:
                eslesen += 1
            else:
                eslesmeen.append(takim)

    toplam = (len(mac_listesi) * 2) - atlanan
    oran = eslesen / max(1, toplam)
    unique_miss = sorted(set(eslesmeen))
    
    if unique_miss:
        logger.warning(f"  ⚠️  Eşleşmeyen takımlar ({len(unique_miss)}): {', '.join(unique_miss[:10])}")

    return {
        "eslesen": eslesen,
        "toplam": toplam,
        "oran": round(oran, 3),
        "eslesmeyenler": unique_miss,
        "atlanan": atlanan,
    }


# Eski fonksiyon geriye uyumlu (eski API imzası)
def eslestirme_orani_raporu(mac_listesi, istatistikler):
    r = eslestirme_raporu(mac_listesi, istatistikler)
    return r["eslesen"], r["toplam"], r["eslesmeyenler"]


def odds_timestamp_gecerli_mi(odds_timestamp: str, kickoff_timestamp: str) -> bool:
    """
    Oran zaman damgasının maç başlama saatinden önce olup olmadığını doğrular.
    Maç başladıktan sonra çekilen oranlar data leakage yaratır ve geçersizdir.
    """
    if not odds_timestamp or not kickoff_timestamp:
        return False
    try:
        # ISO format standardizasyonu
        o_str = str(odds_timestamp).replace("Z", "+00:00")
        k_str = str(kickoff_timestamp).replace("Z", "+00:00")
        from datetime import datetime
        dt_odds = datetime.fromisoformat(o_str)
        dt_kickoff = datetime.fromisoformat(k_str)
        return dt_odds <= dt_kickoff
    except Exception:
        return str(odds_timestamp) <= str(kickoff_timestamp)


def fikstur_tekillestir(fixtures: list) -> list:
    """
    Aynı gün ve aynı takımlara ait duplike fikstürleri tekilleştirir.
    """
    seen = set()
    deduped = []
    for f in fixtures:
        ev = f.get("ev") or (f.get("homeTeam", {}).get("name") if isinstance(f.get("homeTeam"), dict) else "")
        dep = f.get("dep") or (f.get("awayTeam", {}).get("name") if isinstance(f.get("awayTeam"), dict) else "")
        tarih = str(f.get("tarih") or f.get("utcDate") or "")[:10]
        key = f"{ev}|{dep}|{tarih}"
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    return deduped


def gelecek_mac_filtrele(fixtures: list, reference_time: str = None) -> list:
    """
    Geçmişte kalmış veya bitmiş maçları filtreler, sadece gelecekte oynanacak maçları döndürür.
    """
    from datetime import datetime
    if not reference_time:
        reference_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    gelecek = []
    for f in fixtures:
        m_tarih = str(f.get("utcDate") or f.get("tarih") or "")
        if m_tarih > reference_time:
            gelecek.append(f)
    return gelecek