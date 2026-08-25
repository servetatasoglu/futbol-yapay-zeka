"""
main.py — Profesyonel Futbol Tahmin Motoru (Minimal & CLV-Pozitif)
===================================================================
Mimari Akış:
  1. Data Segment    : Maç ve gerçek zamanlı kapanış/canlı oranların çekilmesi
  2. Feature Segment : ELO (CACHED), Poisson ve xG hesaplamaları
  3. Model Segment   : LightGBM / XGBoost Ensemble ile ham olasılıkların tahmini
                       → ThreadPoolExecutor ile PARALEL çalışır
  4. Calibration     : Isotonic / Platt Scaling ile ham → kalibre olasılık
  5. Value / Edge    : Edge = (p * odds) - 1 | Sharp sinyal entegrasyonu
  6. Execution       : Sadece maça 30-45 dk kala işlem tetikleme
  7. Risk            : Kelly kriteri (seçilen yönün olasılığıyla)
  8. Tracking        : Otomatik CLV ölçümü
"""

import os
import sys
import logging
import traceback
import json as _json
import numpy as np
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("bet_engine")

try:
    from data.matches       import mac_verisi_cek, veri_yukle
    from data.odds          import canli_oranlar_cek
    from data.matcher       import eslestir
    from features.elo       import elo_hesapla
    from features.poisson   import poisson_tahmin
    from features.team_stats import istatistik_hesapla, lig_ortalamasi_hesapla
    from model.ensemble     import model_birlestir
    from calibration.calibration import apply_probability_pipeline
    from risk.bankroll      import kelly_hesapla
    from value.analiz       import hesapla_alt_ust_kg, analiz_metni_uret
except ImportError as e:
    logger.error(f"Modül entegrasyon hatası (Giderilmesi Gerekiyor): {e}")


# ═══════════════════════════════════════════════════════════════════════
#  COMPONENT 1: FINISHED MATCH FILTER — Bitmiş maçları kesinlikle engelle
# ═══════════════════════════════════════════════════════════════════════

def _mac_gelecekte_mi(mac_tarihi_str: str) -> bool:
    """
    Maç henüz başlamamışsa True, aksi halde False döner.
    Timezone-safe: UTC ve naive datetime'lar desteklenir.
    Güvenli taraf: tarih yoksa veya parse edilemezse False (=filtrelenir).
    """
    if not mac_tarihi_str:
        return False
    try:
        s = str(mac_tarihi_str).strip()
        if "T" in s:
            # ISO format: "2026-04-14T19:00:00Z" veya "+00:00" varyantları
            mt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            # Naive'e çevir (UTC olarak kabul et)
            mt = mt.replace(tzinfo=None)
        else:
            mt = datetime.strptime(s[:10], "%Y-%m-%d")
        return mt > datetime.now(timezone.utc).replace(tzinfo=None)
    except (ValueError, TypeError, AttributeError):
        return False


def _bahis_anahtari(bet: dict) -> str:
    """
    Benzersiz bahis anahtarı üretir — deduplication için.
    Anahtar: ev|dep|tahmin|tarih(YYYY-MM-DD)
    """
    ev = str(bet.get("ev", "")).strip()
    dep = str(bet.get("dep", "")).strip()
    tahmin = str(bet.get("tahmin", "")).strip()
    tarih = str(bet.get("mac_tarihi", ""))[:10]
    return f"{ev}|{dep}|{tahmin}|{tarih}"


def _validation_gate(live_odds: list) -> tuple:
    """
    Data Validation Gate — pipeline çalışmadan önce veri kalitesini kontrol et.
    Returns: (passed: bool, reason: str)
    """
    # 1. Odds verisi var mı?
    if not live_odds:
        return False, "Canlı oran verisi boş"

    # 2. Odds cache taze mi? (maclar.json modificatio time kontrolü)
    base_dir = os.path.dirname(os.path.abspath(__file__))
    maclar_path = os.path.join(base_dir, "data", "maclar.json")
    if os.path.exists(maclar_path):
        mod_time = datetime.fromtimestamp(os.path.getmtime(maclar_path))
        saat_fark = (datetime.now() - mod_time).total_seconds() / 3600
        if saat_fark > 72:  # 3 günden eski
            logger.warning(f"⚠️ maclar.json {saat_fark:.0f} saat önce güncellendi — bayat olabilir")
            # Uyarı ver ama durdurma (cache sistemi zaten güncelliyor)

    # 3. Odds verilerinde kritik alan kontrolü
    gecersiz = 0
    for odd in live_odds:
        if not odd.get("ev") or not odd.get("dep"):
            gecersiz += 1
        if odd.get("ev_oran", 0) <= 1.0 or odd.get("dep_oran", 0) <= 1.0:
            gecersiz += 1
    if gecersiz > len(live_odds) * 0.5:
        return False, f"Odds verilerinin %{gecersiz/len(live_odds)*100:.0f}'i geçersiz"

    # 4. Gelecek veri sızıntısı kontrolü (tüm maçlar geçmişte mi?)
    gelecek_mac = sum(1 for o in live_odds if _mac_gelecekte_mi(o.get("mac_tarihi", "")))
    if gelecek_mac == 0:
        return False, "Hiç gelecek maç bulunamadı — tüm maçlar bitmiş"

    return True, f"OK — {gelecek_mac}/{len(live_odds)} gelecek maç"


# ─── SHARP TIER SİSTEMİ — ANA KARAR MEKANİZMASI ──────────────────────
# Sharp artık BONUS değil, edge filtrelemenin KALBİ.
# Tier'a göre dinamik edge eşiği → sharp uyumlu = düşük edge kabul
from data.sharp_signal import sharp_tier, sharp_edge_esigi, drift_against_model_mi

# Sharp yön haritası: tahmin türü → beklenen sharp sinyal değeri
_SHARP_YON = {
    "Ev Sahibi Kazanır": "EV",
    "Deplasman Kazanır": "DEP",
    "Beraberlik":        "BER",
}

# Tier öncelik sırası (sıralama için)
_TIER_ONCELIK = {"ELITE": 0, "STRONG": 1, "WEAK": 2, "NO_SHARP": 3}


def _is_sharp_uyumlu(tahmin: str, mac: dict) -> bool:
    """Sharp para bu tahminin lehine mi akıyor?"""
    sinyal = str(mac.get("sharp_sinyal") or "").strip().upper()
    if sinyal in ("", "YOK", "NONE"):
        return False
    return _SHARP_YON.get(tahmin, "") == sinyal


def _sharp_ters_mi(tahmin: str, mac: dict) -> bool:
    """Sharp para bu tahminin TERSİNE mi akıyor?"""
    sinyal = str(mac.get("sharp_sinyal") or "").strip().upper()
    if sinyal in ("", "YOK", "NONE"):
        return False  # Sinyal yok = ters de değil
    return _SHARP_YON.get(tahmin, "") != sinyal


def _drift_var_mi(tahmin: str, mac: dict) -> bool:
    """Piyasa tahminimize ZIT yönde hızla hareket ediyor mu?"""
    ev_h = float(mac.get("ev_hareket", 0.0) or 0.0)
    dep_h = float(mac.get("dep_hareket", 0.0) or 0.0)
    return drift_against_model_mi(tahmin, ev_h, dep_h)


def _tahmin_isle(odd: dict, stats: dict, elo_db: dict,
                 league_avgs: dict, db_takimlar, xg_db: dict) -> dict | None:
    """Tek bir maç için tahmin üretir. ThreadPoolExecutor'dan çağrılır."""
    ev_ham  = odd.get("ev", "Bilinmeyen")
    dep_ham = odd.get("dep", "Bilinmeyen")

    ev_takim  = eslestir(ev_ham,  db_takimlar)
    dep_takim = eslestir(dep_ham, db_takimlar)

    # ═══ FALLBACK: SKIPPED_NO_DATA → matcher eşleşti ama DB'de veri yok ═══
    # HARD RULE: NO SYNTHETIC DATA. If missing, return None.
    if ev_takim == "SKIPPED_NO_DATA" or dep_takim == "SKIPPED_NO_DATA":
        logger.debug(f"  [STRICT RULE] Eksik veri: {ev_ham} vs {dep_ham} — SENTETİK VERİ REDDEDİLDİ")
        return None

    # ═══ KÜMEDEKİ TAKIM (BLACKLIST) FİLTRESİ ═══
    # The-Odds-API zaman zaman eski sezondaki ya da yanlış ligdeki
    # takımları güncel lig altında listeleyebiliyor (örn: Elche CF → PD, 
    # Burnley → PL). Bu whitelist sistemi bilinen büyük lig takımlarını doğrular.
    _WHITELIST = {
        "PL":  {"Arsenal","Aston Villa","Bournemouth","Brentford","Brighton and Hove Albion",
                "Chelsea","Crystal Palace","Everton","Fulham","Ipswich Town","Leicester City",
                "Liverpool","Manchester City","Manchester United","Newcastle United",
                "Nottingham Forest","Southampton","Tottenham Hotspur","West Ham United",
                "Wolverhampton Wanderers","Leeds United"},
        "PD":  {"Alaves","Athletic Bilbao","Atletico Madrid","Atlético Madrid","Barcelona",
                "Celta Vigo","Espanyol","Getafe","Girona","Las Palmas","Leganes",
                "Mallorca","Osasuna","CA Osasuna","Rayo Vallecano","Real Betis",
                "Real Madrid","Real Sociedad","Sevilla","Valencia","Valladolid",
                "Villarreal"},
        "BL1": {"Augsburg","Bayer Leverkusen","Bayern Munich","Bochum","Borussia Dortmund",
                "Borussia Monchengladbach","Eintracht Frankfurt","Freiburg","Hamburger SV",
                "Heidenheim","Hoffenheim","Holstein Kiel","Mainz 05","RB Leipzig",
                "St. Pauli","Stuttgart","Union Berlin","Werder Bremen"},
        "SA":  {"AC Milan","Atalanta","Bologna","Cagliari","Como","Empoli","Fiorentina",
                "Genoa","Inter Milan","Juventus","Lazio","Lecce","Monza","Napoli",
                "Parma","Roma","Torino","Udinese","Venezia","Verona"},
        "FL1": {"Angers","Auxerre","Brest","Havre","Lens","Lille","Lyon","Marseille",
                "Monaco","Montpellier","Nantes","Nice","Paris Saint Germain","Reims",
                "Rennes","Saint Etienne","Strasbourg","Toulouse"},
    }
    lig_kodu_odd = odd.get("lig", "?")
    if lig_kodu_odd in _WHITELIST:
        wl = _WHITELIST[lig_kodu_odd]
        ev_ok  = any(ev_ham in t or t in ev_ham for t in wl)
        dep_ok = any(dep_ham in t or t in dep_ham for t in wl)
        if not ev_ok or not dep_ok:
            logger.debug(f"  [BLACKLIST] {ev_ham} vs {dep_ham} — lig {lig_kodu_odd}'da tanınmıyor, atlandı")
            return None

    if not ev_takim or not dep_takim:
        return None

    try:
        sonuc = model_birlestir(
            ev_takim_db=ev_takim, dep_takim_db=dep_takim,
            istatistikler=stats, elo_sonuclari=elo_db,
            lig_ortalamasi=league_avgs, lig_kodu=odd.get("lig", "?"),
            mac_tarihi=odd.get("mac_tarihi", "")
        )
    except Exception as e:
        logger.debug(f"{ev_ham} vs {dep_ham}: model hatası → {e}")
        return None

    if not sonuc:
        return None

    veri_kaynak = "TAM"

    result = {
        "ev":       ev_ham,  "dep":      dep_ham,
        "ev_takim": ev_takim, "dep_takim": dep_takim,
        "p_ev":     sonuc.get("home_win", 0.33),
        "p_ber":    sonuc.get("draw",     0.28),
        "p_dep":    sonuc.get("away_win", 0.34),
        "ev_oran":  odd.get("ev_oran",  1.0),
        "ber_oran": odd.get("ber_oran", 3.20),
        "dep_oran": odd.get("dep_oran", 1.0),
        "lig":      odd.get("lig",      "?"),
        "lig_isim": odd.get("lig_isim", "Bilinmiyor"),
        "mac_tarihi": odd.get("mac_tarihi", ""),
        # Sharp money verileri
        "sharp_sinyal":  odd.get("sharp_sinyal",  "YOK"),
        "hareket_gucu":  odd.get("hareket_gucu",  0.0),
        "pinnacle_var":  odd.get("pinnacle_var",  False),
        "kitap_sayisi":  odd.get("kitap_sayisi",  1),
        "over_round":    odd.get("over_round",    1.08),
        # TIER sistemi
        "sharp_tier":    odd.get("sharp_tier",    "NO_SHARP"),
        "max_fark":      odd.get("max_fark",      0.0),
        # Veri kaynağı
        "veri_kaynak":   veri_kaynak,
    }

    # xG ve Alt/Üst/KG verilerini ekle
    # xG DB içindeki isimler genelde ham API isimleri (örn: Arsenal FC) oluyor.
    ev_xg_data = xg_db.get(ev_ham, xg_db.get(ev_takim, {}))
    dep_xg_data = xg_db.get(dep_ham, xg_db.get(dep_takim, {}))
    
    ev_xg = ev_xg_data.get("xg", 1.3)
    ev_xga = ev_xg_data.get("xga", 1.3)
    dep_xg = dep_xg_data.get("xg", 1.2)
    dep_xga = dep_xg_data.get("xga", 1.3)

    # Lig bazlı Dixon-Coles rho parametresini al
    from config.settings import LIG_RHO, LIG_RHO_VARSAYILAN
    lig_kodu = odd.get("lig", "?")
    rho = LIG_RHO.get(lig_kodu, LIG_RHO_VARSAYILAN)
    
    ou_btts = hesapla_alt_ust_kg(ev_xg, dep_xg, ev_xga, dep_xga, rho=rho)
    result.update(ou_btts)
    print(f"DEBUG_TAHMIN {ev_ham}: ou_btts={ou_btts}")
    
    # Goal Market oranlarını ve sharp sinyallerini ilet
    result["over25_oran"]      = odd.get("over25_oran", 0)
    result["under25_oran"]     = odd.get("under25_oran", 0)
    result["btts_yes_oran"]    = odd.get("btts_yes_oran", 0)
    result["btts_no_oran"]     = odd.get("btts_no_oran", 0)
    result["ou_sharp_sinyal"]  = odd.get("ou_sharp_sinyal", "YOK")
    result["ou_sharp_tier"]    = odd.get("ou_sharp_tier", "NO_SHARP")
    result["ou_sharp_fark"]    = odd.get("ou_sharp_fark", 0.0)
    result["ou_sharp_guc"]     = odd.get("ou_sharp_guc", 0.0)
    result["btts_sharp_sinyal"] = odd.get("btts_sharp_sinyal", "YOK")
    result["btts_sharp_tier"]  = odd.get("btts_sharp_tier", "NO_SHARP")
    result["btts_sharp_fark"]  = odd.get("btts_sharp_fark", 0.0)
    result["btts_sharp_guc"]   = odd.get("btts_sharp_guc", 0.0)
    return result



def run_pipeline(mock_mode=False):
    logger.info("=== KANTİTATİF BAHİS MOTORU v3.0 (INSTITUTIONAL-GRADE) ===")

    # ─── 0a. SYSTEM HEALTH CHECK ──────────────────────────────────────
    # v3.0: Check all system components before doing anything
    try:
        from monitoring.system_health import health_check
        health = health_check(verbose=True)
        if not health.get("execution_allowed"):
            logger.critical(
                f"⛔ SYSTEM BLOCKED by health check: {health.get('critical')}"
            )
            # Still run pipeline in analysis mode, but flag it
            _system_blocked = True
        else:
            _system_blocked = False
    except Exception as _hc_ex:
        logger.warning(f"Health check unavailable: {_hc_ex}")
        _system_blocked = False

    # ─── 0b. GATE KONTROLÜ (Sharpe + CLV) ─────────────────────────────
    try:
        from backtesting.walk_forward import sharpe_gate_kontrol, clv_gate_kontrol
        sharpe_g = sharpe_gate_kontrol()
        clv_g    = clv_gate_kontrol()
        logger.info(f"[GATE] Sharpe: {sharpe_g['sebep']}")
        logger.info(f"[GATE] CLV   : {clv_g['sebep']}")
        if not sharpe_g["gecti"]:
            logger.warning("[GATE] SHARPE GATE BAŞARISIZ — Paper Mode aktif: Sinyal üretimine devam ediliyor.")
        if not clv_g["gecti"]:
            logger.warning("[GATE] CLV GATE BAŞARISIZ — Paper Mode aktif: Sinyal üretimine devam ediliyor.")
    except Exception as _gate_ex:
        logger.warning(f"[GATE] Gate kontrolü atlandı: {_gate_ex}")


    logger.info("[1/8] Veriler Çekiliyor (Maç + Oranlar)...")
    if mock_mode:
        raw_matches = {"mock_league": [
            {"homeTeam": {"name": f"Home_{i}"},
             "awayTeam": {"name": f"Away_{i}"},
             "score": {"fullTime": {"home": 1, "away": 0}}}
            for i in range(100)
        ]}
        future_date_str = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT21:00:00Z")
        live_odds = [
            {"ev": f"Home_{i}", "dep": f"Away_{i}",
             "ev_oran": 2.15, "ber_oran": 3.20, "dep_oran": 3.50,
             "mac_tarihi": future_date_str,
             "sharp_sinyal": "EV", "hareket_gucu": 0.06,
             "pinnacle_var": True, "kitap_sayisi": 5, "over_round": 1.04,
             "sharp_tier": "STRONG", "max_fark": 0.015}
            for i in range(100)
        ]

    else:
        mac_verisi_cek()
        raw_matches = veri_yukle()
        live_odds = canli_oranlar_cek(gun=3, zorla_yenile=False)

    if not live_odds:
        logger.warning("‼ Canlı oran bulunamadı! İşlem durduruluyor.")
        return []

    # ═══ VALIDATION GATE — Veri kalitesi kontrolü ═══
    gate_ok, gate_msg = _validation_gate(live_odds)
    if not gate_ok:
        logger.error(f"🛑 VALIDATION GATE FAILED: {gate_msg}")
        logger.error("Pipeline durduruluyor — veri kalitesi yetersiz.")
        return []
    logger.info(f"  ✅ Validation Gate: {gate_msg}")

    # ═══ COMPONENT 1: BİTMİŞ MAÇ FİLTRESİ ═══
    onceki_sayi = len(live_odds)
    live_odds = [o for o in live_odds if _mac_gelecekte_mi(o.get("mac_tarihi", ""))]
    filtrelenen = onceki_sayi - len(live_odds)
    if filtrelenen > 0:
        logger.info(f"  🕐 Bitmiş maç filtresi: {filtrelenen} maç çıkarıldı, {len(live_odds)} gelecek maç kaldı")

    if not live_odds:
        logger.warning("‼ Tüm maçlar bitmiş! Gelecek maç yok.")
        return []

    # Sharp tier dağılımı (bilgi)
    tier_dagilim = {}
    for o in live_odds:
        t = o.get("sharp_tier", "NO_SHARP")
        tier_dagilim[t] = tier_dagilim.get(t, 0) + 1
    tier_str = " | ".join(f"{k}:{v}" for k, v in sorted(tier_dagilim.items()))
    logger.info(f"  ✅ {len(live_odds)} maç | Sharp dağılım: {tier_str}")

    # ─── 2. FEATURE AŞAMASI ──────────────────────────────────────────────
    logger.info("[2/8] Feature'lar Hesaplanıyor...")
    if not mock_mode:
        stats       = istatistik_hesapla()
        league_avgs = lig_ortalamasi_hesapla(stats)
        elo_db      = elo_hesapla(raw_matches)
        
        # NEXT LEVEL (Option C): Dinamik Dixon-Coles rho hesapla
        from features.poisson import guncelle_dinamik_rho
        guncelle_dinamik_rho(raw_matches)
    else:
        stats = league_avgs = elo_db = {}

    db_takimlar = list(stats.keys()) if stats else []

    # xG Verilerini Yükle
    xg_db = {}
    if not mock_mode:
        try:
            with open('data/xg_proxy_cache.json') as f:
                xg_cache = _json.load(f)
                if isinstance(xg_cache, dict) and "takimlar" in xg_cache:
                    xg_db = xg_cache["takimlar"]
        except Exception as e:
            logger.warning(f"xG cache yüklenemedi: {e}")

    # ─── 3. MODEL AŞAMASI — PARALEL TAHMIN ──────────────────────────────
    logger.info("[3/8] Ensemble Olasılık Üretiyor (Paralel)...")
    raw_predictions = []

    if mock_mode:
        for odd in live_odds:
            raw_predictions.append({
                "ev": odd["ev"], "dep": odd["dep"],
                "p_ev": 0.48, "p_ber": 0.27, "p_dep": 0.25,
                "ev_oran": odd["ev_oran"], "ber_oran": odd["ber_oran"],
                "dep_oran": odd["dep_oran"],
                "lig": "MOCK", "lig_isim": "Mock League",
                "mac_tarihi": odd.get("mac_tarihi", ""),
                "sharp_sinyal": odd.get("sharp_sinyal", "YOK"),
                "hareket_gucu": odd.get("hareket_gucu", 0.0),
                "pinnacle_var": odd.get("pinnacle_var", False),
                "kitap_sayisi": odd.get("kitap_sayisi", 1),
                "over_round": odd.get("over_round", 1.08),
                "sharp_tier": odd.get("sharp_tier", "NO_SHARP"),
                "max_fark": odd.get("max_fark", 0.0),
            })
    else:
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(
                    _tahmin_isle, odd, stats, elo_db, league_avgs, db_takimlar, xg_db
                ): odd
                for odd in live_odds
            }
            for future in as_completed(futures):
                try:
                    sonuc = future.result()
                    if sonuc:
                        raw_predictions.append(sonuc)
                except Exception as e:
                    logger.debug(f"Paralel tahmin hatası: {e}")

    # Veri kaynağı dağılımı
    kaynak_dag = {"TAM": 0, "KARMA": 0, "SENTETİK": 0}
    for p in raw_predictions:
        kaynak_dag[p.get("veri_kaynak", "TAM")] += 1
    logger.info(f"  ✅ {len(raw_predictions)}/{len(live_odds)} maç eşleşti "
                f"(TAM:{kaynak_dag['TAM']} KARMA:{kaynak_dag['KARMA']} SENTETİK:{kaynak_dag['SENTETİK']})")

    # ─── 4. KALİBRASYON ─────────────────────────────────────────────────
    logger.info("[4/8] Olasılıklar Kalibre Ediliyor...")
    calibrated_preds = []
    cal_sayac = 0
    for pred in raw_predictions:
        raw = np.array([pred["p_ev"], pred["p_ber"], pred["p_dep"]])
        try:
            result = apply_probability_pipeline(raw)
            probs  = result["probs"]
            pred["p_ev"]  = float(probs[0])
            pred["p_ber"] = float(probs[1])
            pred["p_dep"] = float(probs[2])
            if result.get("calibration_used"):
                cal_sayac += 1
        except Exception:
            pass
        calibrated_preds.append(pred)

    logger.info(f"  ✅ Kalibrasyon: {cal_sayac}/{len(calibrated_preds)} isotonic aktif.")

    # ─── 5. VALUE BETTING ENGINE (PRODUCTION v4 — AUDIT FIXES) ──────────────
    # AUDIT FIX-1: Real edge thresholds via sharp_edge_esigi() — no more edge<=0 gate
    # AUDIT FIX-2: Fake odds gate — 4.68 default odds → REJECT
    # AUDIT FIX-3: Composite confidence score — replaces constant 40% fake
    # AUDIT FIX-4: model_p floor raised 0.25→0.30
    # AUDIT FIX-5: Odds range tightened: 1.30–5.00
    # AUDIT FIX-6: NO_SHARP under markets get +4% extra edge penalty
    # AUDIT FIX-7: Past matches hard-filtered (was commented out)

    # Known fake default odds (data/odds.py fills these when no market data)
    _FAKE_ODDS = {4.68, 0.0}
    def _is_fake_odds(o: float) -> bool:
        return any(abs(o - f) < 0.005 for f in _FAKE_ODDS)

    # Real composite confidence — replaces constant 40%/34% fake score
    def _confidence(pred: dict) -> float:
        tier = pred.get("sharp_tier", "NO_SHARP")
        mov  = float(pred.get("hareket_gucu", 0.0) or 0.0)
        if tier == "ELITE":   sharp_c = min(1.0, 0.70 + mov * 0.30)
        elif tier == "STRONG": sharp_c = min(0.80, 0.50 + mov * 0.30)
        elif tier == "WEAK":   sharp_c = min(0.55, 0.30 + mov * 0.25)
        else:                  sharp_c = min(0.25, mov)
        agree_c = max(0.0, 1.0 - float(pred.get("elo_pois_fark", 0.15) or 0.15) * 3)
        xg_c    = 0.80 if pred.get("xg_kullanildi") else 0.40
        kitap_c = min(1.0, int(pred.get("kitap_sayisi", 1) or 1) / 5.0)
        return round(max(0.10, min(1.0,
            sharp_c * 0.40 + agree_c * 0.30 + xg_c * 0.20 + kitap_c * 0.10)), 4)

    logger.info("[5/8] ⚡ VALUE BETTING ENGINE (PRODUCTION v4 — AUDIT FIXES) ⚡")
    all_bets = []
    display_bets = []
    red_counter = {"sharp_ters": 0, "edge_yetersiz": 0, "oran_gecersiz": 0,
                   "fake_odds": 0, "ber_filtre": 0, "model_p_dusuk": 0,
                   "sentetik": 0, "lig_limit": 0}

    for c_pred in calibrated_preds:
        # Market odds
        ev_oran    = c_pred.get("ev_oran", 0)
        ber_oran   = c_pred.get("ber_oran", 0)
        dep_oran   = c_pred.get("dep_oran", 0)
        o25_oran   = c_pred.get("over25_oran",  0)
        u25_oran   = c_pred.get("under25_oran", 0)
        b_yes_oran = c_pred.get("btts_yes_oran", 0)
        b_no_oran  = c_pred.get("btts_no_oran",  0)
        veri_kaynak = c_pred.get("veri_kaynak", "TAM")

        # AUDIT FIX: Strict Pinnacle verification
        if not c_pred.get("pinnacle_var"):
            red_counter["no_pinnacle"] = red_counter.get("no_pinnacle", 0) + 1
            continue

        if veri_kaynak == "SENTETİK":
            red_counter["sentetik"] += 1
            continue

        # FIX-2: Fake odds gate — reject any 4.68 placeholder
        if any(_is_fake_odds(o) for o in [ev_oran, ber_oran, dep_oran, o25_oran, u25_oran, b_yes_oran, b_no_oran] if o > 0):
            red_counter["fake_odds"] += 1
            continue

        # FIX-5.1: Liquidity gate — reject if fewer than 3 bookmakers pricing the market
        kitap_c = int(c_pred.get("kitap_sayisi", 1) or 1)
        if kitap_c < 3:
            red_counter["oran_gecersiz"] += 1
            continue

        if ev_oran <= 1.01 or dep_oran <= 1.01 or o25_oran <= 1.01 or u25_oran <= 1.01:
            red_counter["oran_gecersiz"] += 1
            continue

        # Model Poisson probabilities
        p_ev    = c_pred.get("p_ev", 0.0)
        p_ber   = c_pred.get("p_ber", 0.0)
        p_dep   = c_pred.get("p_dep", 0.0)
        p_o25   = c_pred.get("p_over25",   0.0)
        p_u25   = c_pred.get("p_under25",  0.0)
        p_b_yes = c_pred.get("p_btts_yes", 0.0)
        p_b_no  = c_pred.get("p_btts_no",  0.0)
        if p_u25 == 0 and p_o25 > 0:  p_u25  = round(1.0 - p_o25,   4)
        if p_b_no == 0 and p_b_yes > 0: p_b_no = round(1.0 - p_b_yes, 4)

        # Sharp signal data
        ou_sinyal   = c_pred.get("ou_sharp_sinyal",   "YOK")
        btts_sinyal = c_pred.get("btts_sharp_sinyal", "YOK")
        ou_tier     = c_pred.get("ou_sharp_tier",   "NO_SHARP")
        btts_tier   = c_pred.get("btts_sharp_tier", "NO_SHARP")
        h2h_tier    = c_pred.get("sharp_tier",      "NO_SHARP")

        opsiyonlar = [
            ("Ev Sahibi Kazanır", ev_oran, p_ev, h2h_tier),
            ("Beraberlik",        ber_oran, p_ber, h2h_tier),
            ("Deplasman Kazanır", dep_oran, p_dep, h2h_tier),
            ("2.5 Üst", o25_oran,   p_o25,   ou_tier   if ou_sinyal   == "OVER"     else h2h_tier),
            ("2.5 Alt", u25_oran,   p_u25,   ou_tier   if ou_sinyal   == "UNDER"    else h2h_tier),
            ("KG Var",  b_yes_oran, p_b_yes, btts_tier if btts_sinyal == "BTTS_YES" else h2h_tier),
            ("KG Yok",  b_no_oran,  p_b_no,  btts_tier if btts_sinyal == "BTTS_NO"  else h2h_tier),
        ]

        # FIX-3: Build composite confidence once per match
        confidence = _confidence(c_pred)

        best_option = None
        best_score  = -999.0
        
        display_option = None
        display_score = -999.0

        for isim, oran, p_model, aktif_tier in opsiyonlar:
            if oran <= 1.0 or _is_fake_odds(oran):
                continue

            market_p = 1.0 / oran if oran > 0 else 0
            edge = (p_model - market_p) * oran

            # Display için en iyi seçeneği her zaman kaydet
            _d_score = (edge * 100.0) * confidence
            if _d_score > display_score:
                display_score = _d_score
                display_option = (isim, oran, p_model, edge, aktif_tier)

            # --- SIKI KURUMSAL FİLTRELER (Sadece Bahis İçin) ---
            if oran < 1.30 or oran > 5.00:
                continue
            if p_model < 0.30:
                red_counter["model_p_dusuk"] = red_counter.get("model_p_dusuk", 0) + 1
                continue
            
            # 🔧 DÜZELTİLDİ: Hard-coded 0.15 → config'den GLOBAL_MAX_EDGE * 1.5
            # Eski 0.15 ile main.py'de bir ön filtre uygulanıyordu ama
            # edge_validator.py GLOBAL_MAX_EDGE=0.08 ile çelişiyordu.
            try:
                from config.settings import GLOBAL_MAX_EDGE as _GMAX
            except ImportError:
                _GMAX = 0.12
            if edge > _GMAX * 1.5:  # 0.12 * 1.5 = 0.18 — gerçek anlamda imkansız edge
                red_counter["edge_too_high"] = red_counter.get("edge_too_high", 0) + 1
                continue

            # 🆕 YENİ: Sharp çelişki filtresi
            # Sharp para EV/DEP'e akarırken model beraberlik seçiyorsa bu bahis güvenilmez
            sharp_sinyal = c_pred.get("sharp_sinyal", c_pred.get("sharp_ms_sinyal", "YOK"))
            if isim == "Beraberlik" and sharp_sinyal in ("EV", "DEP"):
                red_counter["sharp_celisik"] = red_counter.get("sharp_celisik", 0) + 1
                continue
            # Sharp EV varken DEP seçme, Sharp DEP varken EV seçme
            if isim == "Ev Sahibi Kazanır" and sharp_sinyal == "DEP" and aktif_tier in ("ELITE", "STRONG"):
                red_counter["sharp_celisik"] = red_counter.get("sharp_celisik", 0) + 1
                continue
            if isim == "Deplasman Kazanır" and sharp_sinyal == "EV" and aktif_tier in ("ELITE", "STRONG"):
                red_counter["sharp_celisik"] = red_counter.get("sharp_celisik", 0) + 1
                continue

            min_edge = sharp_edge_esigi(aktif_tier, isim)
            if isim == "Beraberlik":
                min_edge *= 1.5 
                
            if edge < min_edge:
                red_counter["edge_yetersiz"] += 1
                continue

            # 🔧 DÜZELTİLDİ: Önce "Alt/Yok" için extra edge buffer 
            # Sharp sinyal yoksa 2.5 Alt ve KG Yok için ek %4 buffer iste
            # (Bilinen Poisson bias: Under edge'leri genellikle yanlara çeker)
            if aktif_tier == "NO_SHARP" and isim in ("2.5 Alt", "KG Yok"):
                if edge < min_edge + 0.04:
                    red_counter["nogoal_nosharpe"] = red_counter.get("nogoal_nosharpe", 0) + 1
                    continue

            _tb = {"ELITE": 1.40, "STRONG": 1.20, "WEAK": 1.05, "NO_SHARP": 1.00}.get(aktif_tier, 1.0)
            bet_score = (edge * 100.0) * confidence * _tb

            if bet_score > best_score:
                best_score  = bet_score
                best_option = (isim, oran, p_model, edge, aktif_tier)

        # Dashboard UI için Display Bet
        if display_option:
            d_isim, d_oran, d_p_model, d_edge, d_aktif_tier = display_option
            d_obj = c_pred.copy()
            d_obj["tahmin"]       = d_isim
            d_obj["edge"]         = round(d_edge, 4)
            d_obj["oran"]         = d_oran
            d_obj["p_secim"]      = round(d_p_model, 4)
            d_obj["p_shrunk"]     = round(d_p_model, 4)
            d_obj["market_p"]     = round(1.0 / d_oran, 4) if d_oran > 0 else 0
            d_obj["p_fark"]       = round(d_p_model - (1.0 / d_oran if d_oran > 0 else 0), 4)
            d_obj["overround"]    = round(c_pred.get("over_round", 1.05), 4)
            d_obj["uncertainty"]  = round(1.0 - confidence, 4)
            d_obj["sharp_uyumlu"] = d_aktif_tier in ("ELITE", "STRONG")
            d_obj["aktif_tier"]   = d_aktif_tier
            d_obj["bet_score"]    = round(display_score, 4)
            d_obj["confidence"]   = round(confidence * 100, 2)
            d_obj["veri_kaynak"]  = "MARKET_DRIVEN_GOALS"
            d_obj["analiz"]       = analiz_metni_uret(
                d_isim, d_p_model, 1.0 / d_oran if d_oran > 0 else 0, d_edge, d_aktif_tier,
                c_pred.get("lambda_top", 0), 0.0
            )
            d_obj["zaman"] = datetime.now().strftime("%Y-%m-%dT%H:%M")
            
            # Daha önce tanımlanmamışsa başlat
            if 'display_bets' not in locals():
                display_bets = []
            display_bets.append(d_obj)

        if not best_option:
            continue

        isim, oran, p_model, edge, aktif_tier = best_option

        bet_obj = c_pred.copy()
        bet_obj["tahmin"]       = isim
        bet_obj["edge"]         = round(edge, 4)
        bet_obj["oran"]         = oran
        bet_obj["p_secim"]      = round(p_model, 4)
        bet_obj["p_shrunk"]     = round(p_model, 4)
        bet_obj["market_p"]     = round(1.0 / oran, 4) if oran > 0 else 0
        bet_obj["p_fark"]       = round(p_model - (1.0 / oran if oran > 0 else 0), 4)
        bet_obj["overround"]    = round(c_pred.get("over_round", 1.05), 4)
        bet_obj["uncertainty"]  = round(1.0 - confidence, 4)
        bet_obj["sharp_uyumlu"] = aktif_tier in ("ELITE", "STRONG")
        bet_obj["aktif_tier"]   = aktif_tier
        bet_obj["bet_score"]    = round(best_score, 4)
        bet_obj["confidence"]   = round(confidence * 100, 2)
        bet_obj["veri_kaynak"]  = "MARKET_DRIVEN_GOALS"
        bet_obj["analiz"]       = analiz_metni_uret(
            isim, p_model, 1.0 / oran, edge, aktif_tier,
            c_pred.get("lambda_top", 0), 0.0
        )
        bet_obj["zaman"] = datetime.now().strftime("%Y-%m-%dT%H:%M")
        all_bets.append(bet_obj)



    # --- RANKING & DEDUP (FIX-7: hard past-match filter) ---------------
    all_bets.sort(key=lambda x: x.get("bet_score", 0), reverse=True)

    gosterilen_maclar = set()
    filtered_bets = []
    for b in all_bets:
        if not _mac_gelecekte_mi(b.get("mac_tarihi", "")):
            red_counter["bitmis_mac"] = red_counter.get("bitmis_mac", 0) + 1
            continue  # Hard-filter: never show past matches
        mac_key = "{}|{}|{}".format(b.get("ev",""), b.get("dep",""), str(b.get("mac_tarihi",""))[:10])
        if mac_key in gosterilen_maclar:
            red_counter["cakisan_sinyal"] = red_counter.get("cakisan_sinyal", 0) + 1
            continue
        gosterilen_maclar.add(mac_key)
        filtered_bets.append(b)
        if len(filtered_bets) >= 3:
            break

    value_bets = filtered_bets

    # ─── v3.0: EDGE VALIDATION PIPELINE ──────────────────────────────
    # Every bet must pass the institutional edge validator before execution.
    # This catches fake edges, CI violations, market traps, and CLV-negative patterns.
    try:
        from validation.edge_validator import validate_bet_list
        pre_validation_count = len(value_bets)
        value_bets = validate_bet_list(value_bets)
        logger.info(
            f"  🔬 Edge Validation: {len(value_bets)}/{pre_validation_count} passed "
            f"({pre_validation_count - len(value_bets)} rejected by validator)"
        )
    except Exception as _val_ex:
        logger.warning(f"  ⚠️  Edge validator error (skipped): {_val_ex}")

    # ─── v3.0: PORTFOLIO OPTIMIZER ────────────────────────────────────
    # Select optimal correlated-adjusted subset (max 3 bets, max 1 per league).
    if value_bets:
        try:
            from risk.portfolio_optimizer import optimize_portfolio
            port_result = optimize_portfolio(
                candidate_bets=value_bets,
                bankroll=1000.0,
            )
            value_bets = port_result["secilen_bahisler"]
            _port_rejected = port_result["red_edilenler"]
            logger.info(
                f"  📊 Portfolio: {len(value_bets)} selected | "
                f"corr={port_result['korelasyon_carpan']:.2f} | "
                f"ev={port_result['portfoy_ev']:.4f}"
            )
            for r in _port_rejected:
                red_counter["portfoy"] = red_counter.get("portfoy", 0) + 1
        except Exception as _port_ex:
            logger.warning(f"  ⚠️  Portfolio optimizer error (skipped): {_port_ex}")

    tier_sayac = {"ELITE": 0, "STRONG": 0, "WEAK": 0, "NO_SHARP": 0}
    kaynak_sayac = {"TAM": 0, "KARMA": 0}
    for b in value_bets:
        tier_sayac[b.get("aktif_tier", "NO_SHARP")] += 1
        k = b.get("veri_kaynak", "TAM")
        kaynak_sayac[k] = kaynak_sayac.get(k, 0) + 1

    sharp_toplam = tier_sayac["ELITE"] + tier_sayac["STRONG"] + tier_sayac["WEAK"]
    logger.info(f"  📊 Kabul: {len(all_bets)} | Red: {sum(red_counter.values())} "
                f"Tüm RED Nedenleri: {red_counter}")
    logger.info(f"  📊 Final: E:{tier_sayac['ELITE']} S:{tier_sayac['STRONG']} "
                f"W:{tier_sayac['WEAK']} NS:{tier_sayac['NO_SHARP']} | "
                f"TAM:{kaynak_sayac.get('TAM',0)} KARMA:{kaynak_sayac.get('KARMA',0)}")

    # ─── 6 & 7. PROFESSIONAL EXECUTION ENGINE ─────────────────────────
    logger.info("[6/8 & 7/8] Professional Execution (Timing, Spread, CLV Exp, Risk)...")

    # ── v3.0: CLV Auto-Disable Gate ───────────────────────────────────
    # If CLV is proven negative over 100+ bets, halt execution completely.
    _CLV_EXECUTION_BLOCKED = _system_blocked
    _EXEC_ENGINE_VAR = False
    _clv = {}
    try:
        from execution.engine import execute_bet_analysis, risk_bahis_kaydet
        from tracking.clv_tracker import clv_raporu

        _clv = clv_raporu()

        # v3.0: Hard stop if CLV proven negative
        if _clv.get("execution_disable"):
            _CLV_EXECUTION_BLOCKED = True
            logger.critical(
                f"⛔ CLV AUTO-DISABLE: avg CLV={_clv.get('ort_clv',0)*100:.2f}% "
                f"over {_clv.get('clv_hesaplanan',0)} bets — execution halted."
            )

        # CLV gate: execution active only if CLV proven positive
        _clv_data = _clv.get("ort_clv")
        if not _CLV_EXECUTION_BLOCKED and _clv_data is not None and _clv_data > 0:
            _EXEC_ENGINE_VAR = True
            logger.info(f"  ✅ Execution Engine AKTİF — CLV={_clv_data:.4f} pozitif")
        elif not _CLV_EXECUTION_BLOCKED:
            logger.info("  ⏸️  Execution Engine DEVRE DIŞI — CLV henüz kanıtlanmadı (fallback Kelly)")
    except ImportError as e:
        logger.warning(f"  ⚠️ Execution engine bulunamadı, fallback: {e}")
    except Exception as e:
        logger.warning(f"  ⚠️ Execution engine başlatılırken hata: {e}")
        
    final_executed = []
    bankroll = 1000.0
    
    for bet in value_bets:
        if _EXEC_ENGINE_VAR:
            try:
                # Execution Engine tüm timing, staking, risk ve clv analizlerini yapar
                bet = execute_bet_analysis(bet, bankroll)
                
                # Risk engine bet'i veto etmişse veya CLV exception veto etmişse pas geç
                if bet.get("clv_veto"):
                    red_counter["clv_veto"] = red_counter.get("clv_veto", 0) + 1
                    continue
                if bet.get("risk_seviye") == "DURDUR":
                    red_counter["risk_limit"] = red_counter.get("risk_limit", 0) + 1
                    continue
                    
                risk_bahis_kaydet("bekliyor", bet.get("size", 0.005) * bankroll)
                bet["kelly_carpan"] = 1.0  # fallback uyum
                final_executed.append(bet)
            except Exception as e:
                logger.error(f"  ❌ Execution error: {e}")
                bet["size"] = 0.005
                bet["kelly_carpan"] = 0.5
                bet["stake_aciklama"] = "exec_hata"
                final_executed.append(bet)
        else:
            try:
                oran_val = bet.get("oran", 2.0)
                edge_val = bet.get("edge", 0.0)
                p_model  = bet.get("p_secim", 0.5)

                # AUDIT FIX: Freeze Kelly Staking due to negative True EV.
                # Hardcoded to 0.25% flat unit stake (Paper Trading Mode).
                final_size = 0.0025

                bet["size"]           = round(final_size, 4)
                bet["kelly_carpan"]   = round(final_size * 100, 2)
                bet["stake_aciklama"] = "flat_0.25_percent"
            except Exception:
                bet["size"] = 0.0025
                bet["kelly_carpan"] = 0.25
                bet["stake_aciklama"] = "hata"
            final_executed.append(bet)
                
    executed_bets = final_executed

    # ─── 8. CLV TRACKING + RAPOR (DEDUPLİKASYONLU) ────────────────
    logger.info("[8/8] CLV Tracking & Günlük Rapor...")

    try:
        from tracking.clv_tracker import clv_raporu
        _clv = clv_raporu()
    except Exception:
        _clv = {}

    CLV_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "clv_bet_log.json")
    try:
        with open(CLV_LOG, "r", encoding="utf-8") as f:
            clv_db = _json.load(f)
    except (FileNotFoundError, _json.JSONDecodeError):
        clv_db = {"bahisler": [], "gunluk_raporlar": []}

    bugun = datetime.now().strftime("%Y-%m-%d")
    saat  = datetime.now().strftime("%H:%M")

    # ═══ COMPONENT 4: DEDUPLİKASYON — Aynı bahis tekrar loglanmasın ═══
    mevcut_anahtarlar = set()
    for b in clv_db["bahisler"]:
        key = f"{b.get('ev','')}|{b.get('dep','')}|{b.get('tahmin','')}|{str(b.get('mac_tarihi', b.get('tarih','')))[:10]}"
        mevcut_anahtarlar.add(key)

    yeni_eklenen = 0
    for bet in executed_bets:
        anahtar = _bahis_anahtari(bet)
        if anahtar in mevcut_anahtarlar:
            continue  # Zaten loglanmış — atla
        mevcut_anahtarlar.add(anahtar)
        yeni_eklenen += 1
        clv_db["bahisler"].append({
            "tarih": bugun, "saat": saat,
            "ev": bet.get("ev",""), "dep": bet.get("dep",""),
            "tahmin": bet.get("tahmin",""),
            "mac_tarihi": bet.get("mac_tarihi",""),
            "oran_alinma": bet.get("oran",0), "oran_kapanis": None,
            "edge": bet.get("edge",0),
            "model_p": bet.get("p_secim",0), "market_p": bet.get("market_p",0),
            "p_fark": bet.get("p_fark",0),
            "tier": bet.get("aktif_tier","NO_SHARP"),
            "veri_kaynak": bet.get("veri_kaynak","TAM"),
            "kelly": bet.get("size",0), "kelly_carpan": bet.get("kelly_carpan",1.0),
            "confidence": bet.get("confidence",0),
            "lig": bet.get("lig",""), "sonuc": None, "clv": None,
            "analiz": bet.get("analiz", ""),
        })

    if yeni_eklenen < len(executed_bets):
        logger.info(f"  🧹 Dedup: {len(executed_bets) - yeni_eklenen} duplikat engellendi, {yeni_eklenen} yeni bahis loglandı")

    b_bugun = [b for b in clv_db["bahisler"] if b.get("tarih") == bugun]
    b_sharp = [b for b in b_bugun if b.get("tier") != "NO_SHARP"]
    b_edge  = [b["edge"] for b in b_bugun if b.get("edge")]
    b_kelly = [b["kelly"] for b in b_bugun if b.get("kelly")]
    clv_lst = [b["clv"] for b in clv_db["bahisler"]
               if b.get("clv") is not None and isinstance(b["clv"], (int, float))]

    brier_val = _clv.get("ort_brier")
    rapor = {
        "tarih": bugun, "saat": saat,
        "toplam_bahis": len(b_bugun), "sharp_bahis": len(b_sharp),
        "sharp_oran": round(len(b_sharp)/max(1,len(b_bugun)), 2),
        "ort_edge": round(sum(b_edge)/max(1,len(b_edge)), 4) if b_edge else 0,
        "ort_kelly": round(sum(b_kelly)/max(1,len(b_kelly)), 4) if b_kelly else 0,
        "clv_ort": round(sum(clv_lst)/max(1,len(clv_lst)), 4) if clv_lst else None,
        "ort_brier": brier_val,
        "clv_n": len(clv_lst),
        "tier_dag": tier_sayac,
        "sentetik_red": red_counter.get("sentetik", 0),
    }

    clv_db["gunluk_raporlar"] = [
        r for r in clv_db.get("gunluk_raporlar", []) if r.get("tarih") != bugun
    ]
    clv_db["gunluk_raporlar"].append(rapor)
    clv_db["bahisler"] = [
        b for b in clv_db["bahisler"]
        if b.get("tarih", "") >= (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    ]
    clv_db["gunluk_raporlar"] = clv_db["gunluk_raporlar"][-30:]

    os.makedirs(os.path.dirname(CLV_LOG), exist_ok=True)
    with open(CLV_LOG, "w", encoding="utf-8") as f:
        _json.dump(clv_db, f, ensure_ascii=False, indent=2)

    # ─── RAPOR ────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  ⚡ INSTITUTIONAL QUANT ENGINE (v2.0) ⚡")
    logger.info("=" * 60)

    for b in executed_bets:
        tahmin = b.get('tahmin', '?')
        
        # Market type mapping
        m_type = "1X2"
        if "KG" in tahmin: m_type = "KG"
        elif "2.5" in tahmin or "Alt" in tahmin or "Üst" in tahmin: m_type = "O-U"
        
        edge = b.get("edge", 0)
        p_model = b.get("p_secim", 0)
        p_market = b.get("market_p", 0)
        oran = b.get("oran", 0)
        ev = (p_model - p_market) * oran  # Explicit EV display
        
        lam_ev = b.get("lambda_ev", b.get("lam_ev", 0.0))
        lam_dep = b.get("lambda_dep", b.get("lam_dep", 0.0))
        
        logger.info(f"MATCH: {b.get('ev', '?')} vs {b.get('dep', '?')}")
        logger.info(f"MARKET TYPE: {m_type} ({tahmin})")
        logger.info(f"P_MODEL: {p_model:.4f}")
        logger.info(f"P_MARKET: {p_market:.4f}")
        logger.info(f"EDGE: {edge:.4f}")
        logger.info(f"EV: {ev:.4f}")
        logger.info(f"λ_HOME: {lam_ev:.2f}")
        logger.info(f"λ_AWAY: {lam_dep:.2f}")
        logger.info(f"CONFIDENCE: {b.get('confidence', 0):.2f}%")
        logger.info(f"BET DECISION: YES (Kelly: {b.get('size', 0)*100:.2f}%)")
        logger.info("-" * 40)

    logger.info("=" * 100)
    logger.info(f"  TOPLAM: {len(executed_bets)} bahis | "
                f"Sharp: {sharp_toplam} | NS: {tier_sayac['NO_SHARP']} | "
                f"Sentetik RED: {red_counter['sentetik']}")
    logger.info(f"  ━━━ GÜNLÜK RAPOR ━━━")
    logger.info(f"  📈 Bahis:{rapor['toplam_bahis']} | Sharp:%{rapor['sharp_oran']*100:.0f} | "
                f"Ort.Edge:%{rapor['ort_edge']*100:.1f} | Ort.Kelly:%{rapor['ort_kelly']*100:.2f}")
    if rapor["clv_ort"] is not None:
        logger.info(f"  📊 CLV: %{rapor['clv_ort']*100:.2f} ({rapor['clv_n']} maç)")
    else:
        logger.info(f"  📊 CLV: Henüz closing odds yok")
    logger.info(f"  🛡 Sentetik:{red_counter['sentetik']} | Lig:{red_counter['lig_limit']} | "
                f"Cap:{red_counter.get('edge_cap',0)}")

    # ─── CLV FEEDBACK LOOP — Öğrenme sistemi ──────────────────────────
    try:
        from tracking.learner import clv_feedback_guncelle, performans_raporu
        # CLV verisi olan bahisleri topla
        clv_kayitlar = [b for b in clv_db.get("bahisler", []) 
                        if b.get("clv") is not None]
        if clv_kayitlar:
            clv_feedback_guncelle(clv_kayitlar)
        # Performans raporu
        rapor_txt = performans_raporu()
        for line in rapor_txt.split("\n"):
            logger.info(line)
    except Exception as _e:
        logger.debug(f"Learner henüz aktif değil: {_e}")

    logger.info("=" * 100)

    # ─── OTOMATİK SONUÇ RESOLVER — Biten maçları işle ─────────────────
    try:
        from scripts.result_resolver import resolve_results
        _rez = resolve_results(days_back=7)
        if _rez.get("resolved", 0) > 0:
            logger.info(f"  ✅ Result Resolver: {_rez['resolved']} yeni maç sonucu işlendi")
        else:
            logger.info(f"  ℹ️  Result Resolver: Yeni sonuç yok ({_rez.get('not_found',0)} bekleniyor)")
    except Exception as _re:
        logger.warning(f"  ⚠️ Result Resolver çalışamadı: {_re}")

    # ─── CLV AUTO-FETCH — Geçmiş bahisler için closing odds hesapla ────
    try:
        _clv_updated = 0
        CLV_LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "clv_bet_log.json")
        with open(CLV_LOG_PATH, "r", encoding="utf-8") as f:
            _clv_db = _json.load(f)
        
        # Mevcut odds cache'inden güncel oranları al
        _odds_cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "odds_cache.json")
        _current_odds = {}
        if os.path.exists(_odds_cache_path):
            with open(_odds_cache_path, "r", encoding="utf-8") as f:
                _oc = _json.load(f)
            for _m in _oc.get("maclar", []):
                _key = f"{_m.get('ev','')}|{_m.get('dep','')}"
                _current_odds[_key] = {
                    "ev_oran": _m.get("ev_oran", 0),
                    "ber_oran": _m.get("ber_oran", 0),
                    "dep_oran": _m.get("dep_oran", 0),
                    "over25_oran": _m.get("over25_oran", 0),
                    "under25_oran": _m.get("under25_oran", 0),
                    "btts_yes_oran": _m.get("btts_yes_oran", 0),
                    "btts_no_oran": _m.get("btts_no_oran", 0),
                }
        
        for _b in _clv_db.get("bahisler", []):
            if _b.get("clv") is not None:
                continue  # Zaten CLV hesaplanmış
            
            _bkey = f"{_b.get('ev','')}|{_b.get('dep','')}"
            _odds = _current_odds.get(_bkey)
            if not _odds:
                continue
            
            _tahmin = _b.get("tahmin", "")
            _placed = _b.get("oran_alinma", 0)
            if not _placed or _placed <= 1.0:
                continue
            
            # Tahmin tipine göre closing oran seç
            if "2.5 Üst" in _tahmin or _tahmin == "OVER":
                _closing = _odds.get("over25_oran", 0)
            elif "2.5 Alt" in _tahmin or _tahmin == "UNDER":
                _closing = _odds.get("under25_oran", 0)
            elif "KG Var" in _tahmin or _tahmin == "BTTS_YES":
                _closing = _odds.get("btts_yes_oran", 0)
            elif "KG Yok" in _tahmin or _tahmin == "BTTS_NO":
                _closing = _odds.get("btts_no_oran", 0)
            else:
                continue
            
            if _closing and _closing > 1.0:
                _b["oran_kapanis"] = _closing
                _b["clv"] = round(_placed / _closing - 1, 4)
                _clv_updated += 1
        
        if _clv_updated > 0:
            with open(CLV_LOG_PATH, "w", encoding="utf-8") as f:
                _json.dump(_clv_db, f, ensure_ascii=False, indent=2)
            
            # CLV özet raporu
            _all_clv = [b["clv"] for b in _clv_db["bahisler"] if b.get("clv") is not None]
            _avg_clv = sum(_all_clv) / len(_all_clv) if _all_clv else 0
            _pct_pos = sum(1 for c in _all_clv if c > 0) / len(_all_clv) * 100 if _all_clv else 0
            logger.info(f"  📊 CLV Auto-Update: {_clv_updated} bahis güncellendi")
            logger.info(f"  📊 CLV Özet: Ort={_avg_clv*100:+.2f}% | Pozitif={_pct_pos:.0f}% | N={len(_all_clv)}")
        else:
            logger.info(f"  ℹ️  CLV: Güncellenecek bahis yok")
    except Exception as _clv_ex:
        logger.warning(f"  ⚠️ CLV Auto-Fetch hatası: {_clv_ex}")

    # ─── DASHBOARD DATA GENERATION ─────────────────────────────────────
    try:
        from generate_dashboard import generate_live_signals, generate_dashboard_data
        
        exec_keys = { _bahis_anahtari(b) for b in executed_bets }
        for b in display_bets:
            if _bahis_anahtari(b) in exec_keys:
                b["status"] = "SİSTEM ONAYI"
            else:
                b["status"] = "RİSK FİLTRESİ (DEĞER YOK)"
                
        generate_live_signals(display_bets)
        generate_dashboard_data()
        logger.info("  ✅ Dashboard verileri güncellendi")
    except Exception as _de:
        logger.warning(f"  ⚠️ Dashboard güncellenemedi: {_de}")

    return executed_bets


if __name__ == "__main__":
    run_pipeline()
