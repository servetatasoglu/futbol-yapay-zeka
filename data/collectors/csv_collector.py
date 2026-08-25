import csv
import io
import requests
from datetime import datetime

# Eşleştirme tablosu. TSL -> T1, BL2 -> D2 vb.
CSV_LIG_MAP = {
    "TSL": "T1",
    "BL2": "D2"
}

def csv_sezon_cek(lig_kodu: str, sezon: int) -> list:
    if lig_kodu not in CSV_LIG_MAP:
        return []
    
    # Sezon yılını klasör adına çevir (2023 -> 2324, 2024 -> 2425, 2025 -> 2526)
    yil1 = str(sezon)[-2:]
    yil2 = str(sezon + 1)[-2:]
    klasor = f"{yil1}{yil2}"
    dosya = CSV_LIG_MAP[lig_kodu]
    
    url = f"https://www.football-data.co.uk/mmz4281/{klasor}/{dosya}.csv"
    try:
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
            
        maclar = []
        # Parse CSV
        reader = csv.DictReader(io.StringIO(r.text))
        for row in reader:
            if not row.get("HomeTeam") or not row.get("AwayTeam") or not row.get("FTHG"):
                continue
            
            # Tarih formatı: DD/MM/YYYY veya DD/MM/YY
            tarih_str = row.get("Date", "")
            saat_str = row.get("Time", "00:00")
            
            try:
                if len(tarih_str) == 8: # DD/MM/YY
                    dt = datetime.strptime(f"{tarih_str} {saat_str}", "%d/%m/%y %H:%M")
                else: # DD/MM/YYYY
                    dt = datetime.strptime(f"{tarih_str} {saat_str}", "%d/%m/%Y %H:%M")
                utc_date = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except:
                utc_date = "2000-01-01T00:00:00Z"
                
            try:
                fthg = int(float(row.get("FTHG", 0)))
                ftag = int(float(row.get("FTAG", 0)))
                
                # Halftime score might be missing
                hthg = int(float(row.get("HTHG", 0))) if row.get("HTHG") else 0
                htag = int(float(row.get("HTAG", 0))) if row.get("HTAG") else 0
            except ValueError:
                continue

            mac = {
                "homeTeam": {"name": row["HomeTeam"]},
                "awayTeam": {"name": row["AwayTeam"]},
                "score": {
                    "fullTime": {"home": fthg, "away": ftag},
                    "halfTime": {"home": hthg, "away": htag}
                },
                "utcDate": utc_date
            }
            maclar.append(mac)
            
        return maclar
    except Exception as e:
        print(f"  ⚠️ CSV çekme hatası ({lig_kodu} {sezon}): {e}")
        return []

if __name__ == "__main__":
    maclar = csv_sezon_cek("TSL", 2025)
    print(f"TSL 2025: {len(maclar)} maç")
    if maclar:
        print(maclar[0])
