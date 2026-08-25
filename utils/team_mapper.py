import re
from difflib import SequenceMatcher

# Yaygın varyasyonların manuel haritası
COMMON_MAPPINGS = {
    "Man Utd": "Manchester United",
    "Man United": "Manchester United",
    "Man City": "Manchester City",
    "Spurs": "Tottenham Hotspur",
    "Tottenham": "Tottenham Hotspur",
    "Wolves": "Wolverhampton Wanderers",
    "Nottm Forest": "Nottingham Forest",
    "Sheff Utd": "Sheffield United",
    "Spalding": "Spalding United",
    "Boca Jrs": "Boca Juniors",
    "River": "River Plate",
    "PSV Eindhoven": "PSV",
    "Bayern": "Bayern Munich",
    "Inter": "Inter Milan",
    "Juve": "Juventus",
    "BVB": "Borussia Dortmund",
    "Gladbach": "Dortmund",
    "Milan": "AC Milan"
}

def _normalize(name: str) -> str:
    name = name.lower()
    # Kaldırılacak kelimeler
    name = re.sub(r'\b(fc|cf|ac|sc|rc|ss|as|us|ud|cd|ca|vfl|vfb|sv|fsv|1\.|afc|rcd|og[cm]|hsc|sk|jk|fk|ssc|sbc)\b', '', name)
    name = re.sub(r'[^a-z0-9 ]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()

def normalize_team_name(name: str, valid_names: list[str] = None) -> str:
    """
    Takım adlarını fuzzy string matching kullanarak normalize eder.
    Man United -> Manchester United gibi durumlarda birleştirme yapar.
    """
    if not name:
        return name

    # 1. Direkt Manuel Eşleştirme
    for key, mapped in COMMON_MAPPINGS.items():
        if name.lower() == key.lower():
            return mapped

    if not valid_names:
        return name

    # 2. Birebir Eşleşme (Büyük-Küçük harfe duyarsız)
    for v_name in valid_names:
        if name.lower() == v_name.lower():
            return v_name
            
    # 3. Fuzzy Eşleştirme
    best_match = name
    best_score = 0.0
    
    for v_name in valid_names:
        score = _similarity(name, v_name)
        if score > best_score:
            best_score = score
            best_match = v_name
            
    if best_score > 0.8:  # Yüksek eşik değeri
        return best_match
        
    return name
