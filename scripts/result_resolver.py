#!/usr/bin/env python3
"""
scripts/result_resolver.py
═══════════════════════════════════════════════════════════════════
Geçmiş maç sonuçlarını football-data.org API'den çeker.
Fuzzy matching ile clv_bet_log.json'daki bahislerle eşleştirir.
sonuc ve gercek_skor alanlarını günceller.
═══════════════════════════════════════════════════════════════════
"""
import os, sys, re, json, requests, logging
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("resolver")

CLV_LOG  = os.path.join(ROOT, "data", "clv_bet_log.json")
ENV_FILE = os.path.join(ROOT, ".env")

# ─── API KEY ──────────────────────────────────────────────────────
def _get_api_key() -> str:
    try:
        content = open(ENV_FILE).read()
        m = re.search(r'FOOTBALL_DATA_API_KEY=([^\s\n]+)', content)
        return m.group(1) if m else ""
    except Exception:
        return os.environ.get("FOOTBALL_DATA_API_KEY", "")

# ─── TAKİM İSİM NORMALİZASYON ────────────────────────────────────
# API ve bahis motorunun kullandığı isimler farklı olabiliyor.
# Bu mapping en sık görülen farklılıkları kapsar.
_NAME_MAP = {
    # Premier League
    "afc bournemouth": "bournemouth",
    "brighton & hove albion fc": "brighton and hove albion",
    "brighton & hove albion": "brighton and hove albion",
    "manchester city fc": "manchester city",
    "manchester united fc": "manchester united",
    "tottenham hotspur fc": "tottenham hotspur",
    "newcastle united fc": "newcastle united",
    "west ham united fc": "west ham united",
    "wolverhampton wanderers fc": "wolverhampton wanderers",
    "nottingham forest fc": "nottingham forest",
    "crystal palace fc": "crystal palace",
    "everton fc": "everton",
    "brentford fc": "brentford",
    "fulham fc": "fulham",
    "chelsea fc": "chelsea",
    "arsenal fc": "arsenal",
    "liverpool fc": "liverpool",
    "ipswich town fc": "ipswich town",
    "leicester city fc": "leicester city",
    "southampton fc": "southampton",
    "leeds united fc": "leeds united",
    # La Liga
    "rcd mallorca": "mallorca",
    "rcd espanyol de barcelona": "espanyol",
    "rayo vallecano de madrid": "rayo vallecano",
    "real betis balompié": "real betis",
    "real betis balompi": "real betis",
    "athletic club": "athletic bilbao",
    "ca osasuna": "ca osasuna",
    "real sociedad de fútbol": "real sociedad",
    "real sociedad de futbol": "real sociedad",
    "atletico madrid": "atletico madrid",
    "atlético madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "villarreal cf": "villarreal",
    "valencia cf": "valencia",
    "sevilla fc": "sevilla",
    "getafe cf": "getafe",
    "girona fc": "girona",
    # Serie A
    "us lecce": "lecce",
    "acf fiorentina": "fiorentina",
    "ac milan": "ac milan",
    "inter milan": "inter milan",
    "fc internazionale milano": "inter milan",
    "fc internazionale": "inter milan",
    "ssc napoli": "napoli",
    "ss lazio": "lazio",
    "as roma": "roma",
    "juventus fc": "juventus",
    "atalanta bc": "atalanta",
    "torino fc": "torino",
    # Bundesliga
    "fc Bayern münchen": "bayern munich",
    "fc bayern münchen": "bayern munich",
    "fc bayern munchen": "bayern munich",
    "bayer 04 leverkusen": "bayer leverkusen",
    "rb leipzig": "rb leipzig",
    "borussia dortmund": "borussia dortmund",
    "1. fc union berlin": "union berlin",
    "borussia mönchengladbach": "borussia monchengladbach",
    "eintracht frankfurt": "eintracht frankfurt",
    "vfb stuttgart": "stuttgart",
    "sc freiburg": "freiburg",
    "tsg hoffenheim": "hoffenheim",
    "1. fsv mainz 05": "mainz 05",
    # Ligue 1
    "paris saint-germain fc": "paris saint germain",
    "olympique de marseille": "marseille",
    "olympique lyonnais": "lyon",
    "as monaco fc": "monaco",
    "stade rennais fc": "rennes",
    "stade brestois 29": "brest",
    "rc lens": "lens",
    "racing club de lens": "lens",
    "losc lille": "lille",
    # Eredivisie
    "psv eindhoven": "psv",
    "ajax amsterdam": "ajax",
    "az alkmaar": "az alkmaar",
    "az": "az alkmaar",
    "go ahead eagles": "go ahead eagles",
    "telstar 1963": "telstar",
    # Primeira Liga
    "moreirense fc": "moreirense fc",
    "gd estoril praia": "estoril",
    "fc alverca": "alverca",
    "fc arouca": "arouca",
    "casa pia ac": "casa pia",
    "sporting clube de braga": "braga",
    "sporting cp": "sporting cp",
    "sl benfica": "benfica",
    "fc porto": "porto",
}

def _normalize(name: str) -> str:
    """İsmi küçük harf + mapping ile normalize et."""
    n = name.lower().strip()
    n = n.replace(".", "").replace(",", "").replace("'", "")
    return _NAME_MAP.get(n, n)

def _similarity(a: str, b: str) -> float:
    """İki isim arasındaki basit token overlap benzerliği (0-1)."""
    a_tokens = set(_normalize(a).split())
    b_tokens = set(_normalize(b).split())
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    return len(intersection) / len(union)

def _takimlar_eslesir(bet_name: str, api_name: str, threshold: float = 0.40) -> bool:
    """İki takım isminin aynı takımı temsil edip etmediğini kontrol et."""
    b_norm = _normalize(bet_name)
    a_norm = _normalize(api_name)
    # Tam eşleşme
    if b_norm == a_norm:
        return True
    # Substring kontrolü
    if b_norm in a_norm or a_norm in b_norm:
        return True
    # Token benzerliği
    if _similarity(bet_name, api_name) >= threshold:
        return True
    return False

# ─── API'DEN SONUÇ ÇEK ────────────────────────────────────────────
# Football-Data.org API, generic /matches endpoint'ini büyük tarih
# aralıklarında reddediyor. Per-competition endpoint kullanıyoruz.
_LIGLER_API = ["PL","PD","BL1","SA","FL1","DED","PPL","ELC","BL2","CL"]

def fetch_results(days_back: int = 14) -> list:
    """Her lig için biten maçları API'den çeker ve birleştirir."""
    api_key = _get_api_key()
    if not api_key:
        logger.error("FOOTBALL_DATA_API_KEY bulunamadı!")
        return []

    headers = {"X-Auth-Token": api_key}
    all_matches: list = []
    import time as _time

    for lig in _LIGLER_API:
        url = f"https://api.football-data.org/v4/competitions/{lig}/matches?status=FINISHED"
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code == 429:
                logger.warning(f"  ⏳ Rate limit ({lig}), 12s bekleniyor...")
                _time.sleep(12)
                r = requests.get(url, headers=headers, timeout=20)
            if r.status_code != 200:
                logger.debug(f"  ⚠️ {lig}: HTTP {r.status_code}")
                continue
            matches = r.json().get("matches", [])
            # Sadece son days_back gün içindeki maçları al
            from datetime import timezone
            cutoff = datetime.now() - timedelta(days=days_back)
            recent = []
            for m in matches:
                try:
                    mac_dt = datetime.strptime(m["utcDate"][:10], "%Y-%m-%d")
                    if mac_dt >= cutoff:
                        recent.append(m)
                except Exception:
                    pass
            all_matches.extend(recent)
            logger.debug(f"  📡 {lig}: {len(recent)} maç ({len(matches)} toplam)")
            _time.sleep(0.5)  # API rate limit koruması
        except Exception as e:
            logger.warning(f"  ⚠️ {lig} hatası: {e}")
            continue

    logger.info(f"  📡 Toplam {len(all_matches)} biten maç alındı ({days_back} gün)")
    return all_matches

def _sonuc_belirle(tahmin: str, home_score: int, away_score: int) -> str:
    """Tahmin ve skora göre kazandı/kaybetti döner (Goal Markets odaklı)."""
    toplam_gol = home_score + away_score
    btts_gerceklesti = (home_score > 0 and away_score > 0)
    
    # ── Goal Markets Kontrolü ──
    if tahmin in ("2.5 Üst", "OVER"):
        return "kazandi" if toplam_gol > 2.5 else "kaybetti"
    elif tahmin in ("2.5 Alt", "UNDER"):
        return "kazandi" if toplam_gol < 2.5 else "kaybetti"
    elif tahmin in ("KG Var", "BTTS_YES"):
        return "kazandi" if btts_gerceklesti else "kaybetti"
    elif tahmin in ("KG Yok", "BTTS_NO"):
        return "kazandi" if not btts_gerceklesti else "kaybetti"
        
    # ── Geriye Uyumluluk (Legacy 1X2) ──
    if home_score > away_score:
        gercek = "Ev Sahibi Kazanır"
    elif away_score > home_score:
        gercek = "Deplasman Kazanır"
    else:
        gercek = "Beraberlik"

    return "kazandi" if tahmin == gercek else "kaybetti"

# ─── ANA RESOLVER ─────────────────────────────────────────────────
def resolve_results(days_back: int = 5, dry_run: bool = False) -> dict:
    """
    CLV log'daki bekleyen bahisleri API sonuçlarıyla eşleştirir.
    Returns: {resolved: int, not_found: int, already_resolved: int}
    """
    # 1. CLV log yükle
    try:
        with open(CLV_LOG, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        logger.error("CLV log bulunamadı!")
        return {"resolved": 0, "not_found": 0, "already_resolved": 0}

    bahisler = db.get("bahisler", [])

    # 2. API sonuçları çek
    api_matches = fetch_results(days_back)
    if not api_matches:
        logger.warning("API'den sonuç alınamadı.")
        return {"resolved": 0, "not_found": 0, "already_resolved": 0}

    # API maçlarını tarih+takım indexle
    api_index = {}
    for m in api_matches:
        tarih = m.get("utcDate", "")[:10]
        ev    = m["homeTeam"]["name"]
        dep   = m["awayTeam"]["name"]
        ft    = m["score"]["fullTime"]
        hs, as_ = ft.get("home"), ft.get("away")
        if hs is None or as_ is None:
            continue
        key = tarih
        api_index.setdefault(key, []).append({
            "ev": ev, "dep": dep,
            "home_score": int(hs), "away_score": int(as_),
            "skor": f"{hs}-{as_}"
        })

    # 3. Her bekleyen bahis için eşleştir
    stats = {"resolved": 0, "not_found": 0, "already_resolved": 0}

    for bet in bahisler:
        # Zaten sonuçlanmış
        if bet.get("sonuc") is not None:
            stats["already_resolved"] += 1
            continue

        bet_ev  = bet.get("ev", "")
        bet_dep = bet.get("dep", "")
        tahmin  = bet.get("tahmin", "")

        # Maç tarihi — mac_tarihi veya tarih alanından al
        mac_tarihi = bet.get("mac_tarihi", bet.get("tarih", ""))
        bet_tarih  = str(mac_tarihi)[:10] if mac_tarihi else ""

        if not bet_tarih:
            stats["not_found"] += 1
            continue

        # Tarih aralığında API maçlarına bak (±1 gün toleransı)
        bulunan = None
        for offset in [0, 1, -1]:
            arama_tarih = (datetime.strptime(bet_tarih, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")
            kandidatlar = api_index.get(arama_tarih, [])
            for api_m in kandidatlar:
                if (_takimlar_eslesir(bet_ev, api_m["ev"]) and
                        _takimlar_eslesir(bet_dep, api_m["dep"])):
                    bulunan = api_m
                    break
            if bulunan:
                break

        if bulunan:
            sonuc = _sonuc_belirle(tahmin, bulunan["home_score"], bulunan["away_score"])
            if not dry_run:
                bet["sonuc"]       = sonuc
                bet["gercek_skor"] = bulunan["skor"]
                bet["mac_tarihi"]  = bet_tarih  # normalize et
                # ── Profit hesapla (unit = kelly fraction × bankroll) ──
                kelly_frac = float(bet.get("kelly", 0.01) or 0.01)
                oran_val   = float(bet.get("oran_alinma", 2.0) or 2.0)
                if sonuc == "kazandi":
                    bet["profit"] = round(kelly_frac * (oran_val - 1), 4)
                else:
                    bet["profit"] = round(-kelly_frac, 4)
            emoji = "✅" if sonuc == "kazandi" else "❌"
            logger.info(
                f"  {emoji} {bet_tarih} | {bet_ev} vs {bet_dep} | "
                f"{tahmin} | Skor: {bulunan['skor']} → {sonuc}"
            )
            stats["resolved"] += 1
        else:
            logger.debug(f"  ⚪ Bulunamadı: {bet_tarih} | {bet_ev} vs {bet_dep}")
            stats["not_found"] += 1

    # 4. Kaydet
    if not dry_run and stats["resolved"] > 0:
        with open(CLV_LOG, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        logger.info(f"  💾 CLV log güncellendi ({stats['resolved']} yeni sonuç)")

    logger.info(
        f"  📊 Özet → Çözüldü:{stats['resolved']} | "
        f"Bulunamadı:{stats['not_found']} | "
        f"Zaten_var:{stats['already_resolved']}"
    )
    return stats


# ─── BAŞARI İSTATİSTİKLERİ ────────────────────────────────────────
def basari_istatistikleri() -> dict:
    """CLV log'dan başarı oranı ve ROI hesaplar."""
    try:
        with open(CLV_LOG, "r", encoding="utf-8") as f:
            db = json.load(f)
    except Exception:
        return {}

    bahisler = db.get("bahisler", [])
    kazananlar = [b for b in bahisler if b.get("sonuc") == "kazandi"]
    kaybedenler = [b for b in bahisler if b.get("sonuc") == "kaybetti"]
    bekleyenler = [b for b in bahisler if b.get("sonuc") is None]

    toplam_sonuclanan = len(kazananlar) + len(kaybedenler)

    if toplam_sonuclanan == 0:
        return {"mesaj": "Henüz sonuçlanan bahis yok"}

    # ROI hesapla (her bahis için Kelly size * oran)
    toplam_kazanc = sum(
        b.get("kelly", 0.01) * (b.get("oran_alinma", 2.0) - 1)
        for b in kazananlar
    )
    toplam_kayip = sum(b.get("kelly", 0.01) for b in kaybedenler)
    toplam_yatirim = sum(b.get("kelly", 0.01) for b in bahisler if b.get("sonuc") is not None)

    roi = ((toplam_kazanc - toplam_kayip) / max(toplam_yatirim, 0.001)) * 100

    return {
        "toplam_bahis": len(bahisler),
        "sonuclanan": toplam_sonuclanan,
        "kazanan": len(kazananlar),
        "kaybeden": len(kaybedenler),
        "bekleyen": len(bekleyenler),
        "basari_orani": round(len(kazananlar) / toplam_sonuclanan * 100, 1),
        "roi_pct": round(roi, 2),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Maç sonuçlarını CLV log'a işle")
    parser.add_argument("--days", type=int, default=7, help="Kaç gün geriye bak")
    parser.add_argument("--dry-run", action="store_true", help="Kaydetme, sadece göster")
    args = parser.parse_args()

    logger.info("=== RESULT RESOLVER ===")
    stats = resolve_results(days_back=args.days, dry_run=args.dry_run)

    print("\n=== BAŞARI İSTATİSTİKLERİ ===")
    ist = basari_istatistikleri()
    for k, v in ist.items():
        print(f"  {k}: {v}")
