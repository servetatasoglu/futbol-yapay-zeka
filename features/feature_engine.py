# analysis/feature_engine.py
"""
Gelişmiş Feature Hesaplama Modülü v2
─────────────────────────────────────────────────────────
DEĞİŞİKLİKLER:
  Mevcut 6 feature korundu + 7 yeni kritik feature eklendi:
    • fatigue_index()         → Son N günde oynanan maç sayısı
    • match_importance()      → Küme düşme / şampiyonluk baskısı skoru
    • dynamic_home_advantage()→ Statik 1.06 yerine gerçek ev avantajı
    • travel_fatigue()        → Uzak deplasman yorgunluğu (km bazlı)
    • momentum_multi()        → Çoklu pencere momentum (son3/son5/son10)
    • weather_lambda_adjust() → Hava durumu λ düzeltmesi
    • elc_fatigue_carpani()   → Championship yoğun takvim özel durumu
"""

from datetime import datetime, timedelta
from config.settings import (
    YORGUNLUK_PENCERE_GUN, YORGUNLUK_ESIK_MAC, YORGUNLUK_CARPANI,
    ELC_YORGUNLUK_ESIK, ELC_YORGUNLUK_CARPANI,
    HAVA_YAGMUR_ESIK_MM, HAVA_YAGMUR_CARPANI,
    HAVA_SOGUK_ESIK_C, HAVA_SOGUK_CARPANI,
)


# ══════════════════════════════════════════════════════════════
#  ESKİ FEATURELER — Geriye dönük uyumlu, değişmedi
# ══════════════════════════════════════════════════════════════

def attack_strength(goals_scored, league_avg):
    if league_avg == 0:
        return 0
    return goals_scored / league_avg


def defense_strength(goals_conceded, league_avg):
    if league_avg == 0:
        return 0
    return goals_conceded / league_avg


def form_points(results):
    """
    results example: ['W','D','L','W','W']
    """
    score = 0
    for r in results:
        if r == "W":
            score += 3
        elif r == "D":
            score += 1
    return score


def clean_sheet_rate(clean_sheets, matches):
    if matches == 0:
        return 0
    return clean_sheets / matches


def goal_difference(goals_for, goals_against):
    return goals_for - goals_against


def matchup_strength(attack, defense):
    if defense == 0:
        return 0
    return attack / defense


# ══════════════════════════════════════════════════════════════
#  YENİ FEATURE 1 — Yorgunluk İndeksi
# ══════════════════════════════════════════════════════════════

def fatigue_index(mac_tarihleri: list, referans_tarih=None,
                  pencere_gun: int = None, esik: int = None) -> dict:
    """
    Son N günde oynanan maç sayısına göre yorgunluk hesaplar.

    Parametreler:
        mac_tarihleri : ['2026-03-05', '2026-03-08', ...] formatında
                        takımın son maç tarihleri listesi
        referans_tarih: maç günü (None ise bugün)
        pencere_gun   : kaç günlük pencere (varsayılan: settings'ten)
        esik          : kaç maç üstünde yorgunluk (varsayılan: settings'ten)

    Döndürür:
        {
          'mac_sayisi'  : 2,        # pencere içindeki maç sayısı
          'yorgun'      : True,     # esik aşıldı mı
          'carpan'      : 0.95,     # λ'ya uygulanacak çarpan (1.0 = etkisiz)
          'skor'        : 0.30,     # 0-1 yorgunluk skoru
        }
    """
    if pencere_gun is None:
        pencere_gun = YORGUNLUK_PENCERE_GUN
    if esik is None:
        esik = YORGUNLUK_ESIK_MAC

    if referans_tarih is None:
        referans_tarih = datetime.now().date()
    elif isinstance(referans_tarih, str):
        referans_tarih = datetime.fromisoformat(referans_tarih[:10]).date()

    sinir = referans_tarih - timedelta(days=pencere_gun)

    sayac = 0
    for t in mac_tarihleri:
        try:
            if isinstance(t, str):
                tarih = datetime.fromisoformat(t[:10]).date()
            else:
                tarih = t
            if sinir < tarih < referans_tarih:
                sayac += 1
        except Exception:
            continue

    yorgun = sayac >= esik
    # Skor: 0 (dinlenmiş) → 1 (çok yorgun)
    skor = min(1.0, sayac / max(esik * 2, 1))
    # Çarpan: yorgun değilse 1.0, yorgunsa YORGUNLUK_CARPANI
    carpan = YORGUNLUK_CARPANI if yorgun else 1.0

    return {
        "mac_sayisi": sayac,
        "yorgun":     yorgun,
        "carpan":     carpan,
        "skor":       round(skor, 3),
    }


def elc_fatigue_carpani(mac_tarihleri: list, referans_tarih=None) -> float:
    """
    Championship özel yorgunluk çarpanı.
    Son 5 gün içinde 2+ maç → ELC_YORGUNLUK_CARPANI uygula.
    """
    sonuc = fatigue_index(
        mac_tarihleri, referans_tarih,
        pencere_gun=5,
        esik=ELC_YORGUNLUK_ESIK,
    )
    return ELC_YORGUNLUK_CARPANI if sonuc["yorgun"] else 1.0


# ══════════════════════════════════════════════════════════════
#  YENİ FEATURE 2 — Maç Önemi Skoru
# ══════════════════════════════════════════════════════════════

def match_importance(puan: int, lig_sira: int, takim_sayisi: int,
                     goal_diff: int = 0, hafta: int = 20) -> float:
    """
    Takımın bu maçtaki motivasyon / baskı skorunu hesaplar.
    0.0 = nötr | pozitif = şampiyonluk baskısı | negatif = küme düşme baskısı

    Mantık:
      - Şampiyon yarışında (ilk 3): puan farkı azsa yüksek motivasyon
      - Küme düşme savaşında (son 3): baskı altında yüksek performans
      - Ortada: nötr
    """
    if takim_sayisi <= 0:
        return 0.0

    # Sıra oranı: 0 (1.sıra) → 1 (son sıra)
    sira_oran = (lig_sira - 1) / (takim_sayisi - 1) if takim_sayisi > 1 else 0.5

    # Sezon ilerlemesi
    ilerleme = min(1.0, hafta / 38.0)

    # Şampiyonluk baskısı (üst %15)
    if sira_oran <= 0.15:
        puan_baskisi = max(0, 1.0 - (puan / max(puan * 1.2, 1))) * ilerleme
        return round(puan_baskisi * 0.5, 3)

    # Küme düşme baskısı (alt %15)
    if sira_oran >= 0.85:
        kume_baskisi = (1.0 - (puan / max(50.0, puan + 20))) * ilerleme
        return round(-kume_baskisi * 0.8, 3)   # negatif = kurtarma savaşı

    return 0.0


# ══════════════════════════════════════════════════════════════
#  YENİ FEATURE 3 — Dinamik Ev Avantajı
# ══════════════════════════════════════════════════════════════

def dynamic_home_advantage(ev_beklenen_goller: list,
                            ev_gercek_goller: list,
                            varsayilan: float = 1.06) -> float:
    """
    Son N ev maçındaki gerçek gol / beklenen gol oranından
    dinamik ev avantajı hesaplar.

    Parametreler:
        ev_beklenen_goller : [1.4, 1.2, 1.8, ...]  model λ değerleri
        ev_gercek_goller   : [2,   1,   3,   ...]  gerçek gol sayıları
        varsayilan         : veri yoksa bu değeri döndür

    Döndürür:
        float — statik 1.06 yerine kullanılacak çarpan
    """
    if not ev_beklenen_goller or not ev_gercek_goller:
        return varsayilan

    n = min(len(ev_beklenen_goller), len(ev_gercek_goller), 5)
    if n < 2:
        return varsayilan

    beklenen = sum(ev_beklenen_goller[-n:])
    gercek   = sum(ev_gercek_goller[-n:])

    if beklenen <= 0:
        return varsayilan

    oran = gercek / beklenen
    # Ekstrem değerleri sınırla: [0.80, 1.40]
    oran = max(0.80, min(1.40, oran))

    # Varsayılan ile ağırlıklı karıştır (son veriye %40 ağırlık)
    return round(varsayilan * 0.60 + oran * 0.40, 4)


# ══════════════════════════════════════════════════════════════
#  YENİ FEATURE 4 — Seyahat Yorgunluğu
# ══════════════════════════════════════════════════════════════

# Büyük Avrupa şehirlerinin yaklaşık koordinatları
_SEHIR_KOORDINAT = {
    # İngiltere
    "london":     (51.51, -0.12), "manchester": (53.48, -2.24),
    "liverpool":  (53.41, -2.99), "birmingham": (52.48, -1.90),
    "leeds":      (53.80, -1.55), "newcastle":  (54.97, -1.62),
    "sheffield":  (53.38, -1.47), "nottingham": (52.95, -1.15),
    # İspanya
    "madrid":     (40.42, -3.70), "barcelona":  (41.39,  2.15),
    "seville":    (37.39, -5.99), "valencia":   (39.47, -0.38),
    "bilbao":     (43.26, -2.93), "madrid":     (40.42, -3.70),
    # Almanya
    "munich":     (48.14, 11.58), "berlin":     (52.52, 13.41),
    "dortmund":   (51.51,  7.47), "hamburg":    (53.57,  9.99),
    "frankfurt":  (50.11,  8.68), "cologne":    (50.94,  6.96),
    # İtalya
    "rome":       (41.90, 12.50), "milan":      (45.47,  9.19),
    "naples":     (40.84, 14.25), "turin":      (45.07,  7.69),
    # Fransa
    "paris":      (48.86,  2.35), "lyon":       (45.75,  4.83),
    "marseille":  (43.30,  5.37), "lille":      (50.63,  3.07),
    # Hollanda
    "amsterdam":  (52.37,  4.90), "rotterdam":  (51.92,  4.48),
    "eindhoven":  (51.44,  5.48), "utrecht":    (52.09,  5.12),
    # Portekiz
    "lisbon":     (38.72, -9.14), "porto":      (41.16, -8.63),
    # Türkiye
    "istanbul":   (41.01, 28.95), "ankara":     (39.93, 32.85),
}


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    """İki koordinat arası mesafe (km)."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def travel_fatigue(ev_sehir: str, dep_sehir: str) -> dict:
    """
    Deplasman takımının seyahat mesafesine göre yorgunluk çarpanı.

    Döndürür:
        {
          'km'    : 1200,
          'carpan': 0.97,   # λ'ya uygulanacak (sadece dep takımına)
          'seviye': 'uzak', # 'yakin' | 'orta' | 'uzak' | 'cok_uzak'
        }
    """
    ev_k  = _SEHIR_KOORDINAT.get(ev_sehir.lower())
    dep_k = _SEHIR_KOORDINAT.get(dep_sehir.lower())

    if not ev_k or not dep_k:
        return {"km": 0, "carpan": 1.0, "seviye": "bilinmiyor"}

    km = _haversine_km(ev_k[0], ev_k[1], dep_k[0], dep_k[1])

    if km < 200:
        return {"km": round(km), "carpan": 1.00, "seviye": "yakin"}
    elif km < 500:
        return {"km": round(km), "carpan": 0.99, "seviye": "orta"}
    elif km < 1000:
        return {"km": round(km), "carpan": 0.97, "seviye": "uzak"}
    else:
        return {"km": round(km), "carpan": 0.94, "seviye": "cok_uzak"}


# ══════════════════════════════════════════════════════════════
#  YENİ FEATURE 5 — Çoklu Pencere Momentum
# ══════════════════════════════════════════════════════════════

def momentum_multi(sonuclar: list) -> dict:
    """
    Son 3, son 5 ve son 10 maç üzerinden ayrı momentum değerleri hesaplar.
    Tek pencereden çok daha güçlü sinyal.

    sonuclar: ['G','G','M','B','G','M','G','G','M','G']  (G=kazandı, B=beraberlik, M=kaybetti)
    eski format da destekleniyor: ['W','D','L',...]

    Döndürür:
        {
          'son3'  : 0.78,   # 0-1 arası normalize edilmiş
          'son5'  : 0.60,
          'son10' : 0.55,
          'trend' : 'yukari',  # 'yukari' | 'asagi' | 'duz'
          'kompozit': 0.64,
        }
    """
    def _puan(r):
        r = r.upper()
        if r in ("G", "W", "WIN"):  return 3
        if r in ("B", "D", "DRAW"): return 1
        return 0

    def _norm(sonuc_list):
        if not sonuc_list:
            return 0.5
        maks = len(sonuc_list) * 3
        return sum(_puan(r) for r in sonuc_list) / maks if maks > 0 else 0.5

    rev = list(reversed(sonuclar))  # en yeni en başta
    son3  = _norm(rev[:3])
    son5  = _norm(rev[:5])
    son10 = _norm(rev[:10])

    # Trend: son3 ile son10 karşılaştır
    fark = son3 - son10
    if fark > 0.10:
        trend = "yukari"
    elif fark < -0.10:
        trend = "asagi"
    else:
        trend = "duz"

    # Ağırlıklı kompozit: son3 en önemli
    kompozit = round(son3 * 0.50 + son5 * 0.30 + son10 * 0.20, 3)

    return {
        "son3":     round(son3,  3),
        "son5":     round(son5,  3),
        "son10":    round(son10, 3),
        "trend":    trend,
        "kompozit": kompozit,
    }


# ══════════════════════════════════════════════════════════════
#  YENİ FEATURE 6 — Hava Durumu λ Düzeltmesi
# ══════════════════════════════════════════════════════════════

def weather_lambda_adjust(lam_ev: float, lam_dep: float,
                           yagis_mm: float = 0.0,
                           sicaklik_c: float = 15.0) -> tuple:
    """
    Hava durumuna göre gol beklentisini (λ) düzeltir.

    Parametreler:
        lam_ev     : ev takımı gol beklentisi
        lam_dep    : deplasman takımı gol beklentisi
        yagis_mm   : mm/saat yağış (OpenMeteo'dan)
        sicaklik_c : °C (OpenMeteo'dan)

    Döndürür:
        (lam_ev_duzeltilmis, lam_dep_duzeltilmis)
    """
    carpan = 1.0

    if yagis_mm >= HAVA_YAGMUR_ESIK_MM:
        carpan *= HAVA_YAGMUR_CARPANI

    if sicaklik_c < HAVA_SOGUK_ESIK_C:
        carpan *= HAVA_SOGUK_CARPANI

    if carpan == 1.0:
        return lam_ev, lam_dep

    return round(lam_ev * carpan, 4), round(lam_dep * carpan, 4)


# ══════════════════════════════════════════════════════════════
#  YENİ FEATURE 7 — Tüm Featureları Birleştir (GBM için)
# ══════════════════════════════════════════════════════════════

def feature_vektor_genisletilmis(
    ev_ist: dict,
    dep_ist: dict,
    ev_elo: float,
    dep_elo: float,
    ev_form: dict,
    dep_form: dict,
    lig_kodu: str,
    ev_mac_tarihleri: list = None,
    dep_mac_tarihleri: list = None,
    referans_tarih=None,
    hava: dict = None,
) -> dict:
    """
    GBM modeli için genişletilmiş feature vektörü.
    Mevcut feature_vektor() ile aynı interface, ek featureler içeriyor.
    """
    ev_mac_tarihleri  = ev_mac_tarihleri  or []
    dep_mac_tarihleri = dep_mac_tarihleri or []
    hava = hava or {}

    # Yorgunluk
    ev_yorg  = fatigue_index(ev_mac_tarihleri,  referans_tarih)
    dep_yorg = fatigue_index(dep_mac_tarihleri, referans_tarih)

    # ELC özel
    ev_elc_carpan  = elc_fatigue_carpani(ev_mac_tarihleri,  referans_tarih) if lig_kodu == "ELC" else 1.0
    dep_elc_carpan = elc_fatigue_carpani(dep_mac_tarihleri, referans_tarih) if lig_kodu == "ELC" else 1.0

    # Maç önemi
    ev_onem  = match_importance(
        ev_ist.get("puan", 0),
        ev_ist.get("lig_sira", 10),
        ev_ist.get("lig_takim_sayisi", 20),
    )
    dep_onem = match_importance(
        dep_ist.get("puan", 0),
        dep_ist.get("lig_sira", 10),
        dep_ist.get("lig_takim_sayisi", 20),
    )

    # Hava çarpanı
    yagis = hava.get("yagis_mm", 0.0)
    sicak = hava.get("sicaklik_c", 15.0)
    hava_carpan = 1.0
    if yagis >= HAVA_YAGMUR_ESIK_MM:
        hava_carpan *= HAVA_YAGMUR_CARPANI
    if sicak < HAVA_SOGUK_ESIK_C:
        hava_carpan *= HAVA_SOGUK_CARPANI

    return {
        # Temel featureler
        "ev_hucum":          ev_ist.get("hucum_genel", 1.35),
        "ev_savunma":        ev_ist.get("savunma_genel", 1.35),
        "dep_hucum":         dep_ist.get("hucum_genel", 1.35),
        "dep_savunma":       dep_ist.get("savunma_genel", 1.35),
        "ev_elo":            ev_elo,
        "dep_elo":           dep_elo,
        "elo_fark":          ev_elo - dep_elo,
        "ev_form_skor":      ev_form.get("form_skor", 0.5),
        "dep_form_skor":     dep_form.get("form_skor", 0.5),
        "ev_momentum":       ev_form.get("momentum", 0.0),
        "dep_momentum":      dep_form.get("momentum", 0.0),
        # YENİ: Yorgunluk
        "ev_yorgunluk":      ev_yorg["skor"],
        "dep_yorgunluk":     dep_yorg["skor"],
        "ev_yorgunluk_mac":  ev_yorg["mac_sayisi"],
        "dep_yorgunluk_mac": dep_yorg["mac_sayisi"],
        # YENİ: ELC özel
        "ev_elc_carpan":     ev_elc_carpan,
        "dep_elc_carpan":    dep_elc_carpan,
        # YENİ: Maç önemi
        "ev_mac_onemi":      ev_onem,
        "dep_mac_onemi":     dep_onem,
        # YENİ: Hava durumu
        "hava_carpan":       hava_carpan,
        "yagis_mm":          yagis,
        "sicaklik_c":        sicak,
        # Lig kodu (kategorik — GBM one-hot ile işler)
        "lig_kodu":          lig_kodu,
    }