import json
import os
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("team_mapping")

def create_mapping():
    json_path = os.path.join(os.path.dirname(__file__), "maclar.json")
    mapping_path = os.path.join(os.path.dirname(__file__), "team_mapping.json")
    
    if not os.path.exists(json_path):
        logger.error("maclar.json bulunamadı.")
        return
        
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    mapping = {}
    for lig, lig_maclari in data.items():
        if isinstance(lig_maclari, list):
            for match in lig_maclari:
                home = match.get("homeTeam", {})
                away = match.get("awayTeam", {})
                
                h_id = str(home.get("id", ""))
                h_name = home.get("shortName", "") or home.get("name", "")
                
                a_id = str(away.get("id", ""))
                a_name = away.get("shortName", "") or away.get("name", "")
                
                if h_id and h_name:
                    mapping[h_name] = h_id
                if a_id and a_name:
                    mapping[a_name] = a_id
                    
    with open(mapping_path, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2, ensure_ascii=False)
        
    logger.info(f"Team mapping oluşturuldu. {len(mapping)} takım kaydedildi -> {mapping_path}")

if __name__ == "__main__":
    create_mapping()
