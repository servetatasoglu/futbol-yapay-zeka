# analysis/value_bet.py
"""
Value Bet Bulucu
DÜZELTİLDİ:
  1. Beraberlik tahminleri için daha sıkı filtre (221 adet fazlaydı)
  2. Yüksek güven aralığı (0.80-1.00) kalibrasyonu bozuk — CI genişlik filtresi eklendi
  3. MIN_KONSENSUS_KUPON artırıldı

KUPON LOJİĞİ YENİDEN YAZILDI (v2):
  Eski sorunlar:
    - Sadece edge'e göre sıralama → yüksek oranlar birbirine koreleli seçiliyordu
    - Birleşik olasılık %4-10 çok düşük → uzun vadede kaybettiriyor
    - Aynı lig/tarihten birden fazla maç kupona girebiliyordu
    - Kupon başarı oranı %0 çıkıyordu

  Yeni mantık:
    - Minimum birleşik olasılık eşiği (%20 2li, %12 3lü)
    - Korelasyon azaltma: aynı ligden max 1 maç kupon başına
    - Düşük oran tercihi: yüksek olasılıklı seçimler tercih edilir
    - Çeşitlilik skoru: farklı lig kombinasyonları bonus alır
    - Skor: edge ağırlığı düşürüldü, kazanma olasılığı ağırlığı artırıldı
"""

import os
import json
from itertools import combinations
from data.matcher   import eslestir
from model.ensemble import model_birlestir

# ── Kalibrasyon entegrasyonu ─────────────────────────────────────
try:
    from analysis.kalibrasyon_katmani import kalibrasyon_uygula, kalibrasyon_edge_duzelt, LIG_BIAS
    _KALIBRASYON_AKTIF = True
except ImportError:
    _KALIBRASYON_AKTIF = False
    def kalibrasyon_uygula(p, lig=""): return p
    def kalibrasyon_edge_duzelt(e, lig=""): return e

# ── Premier League ve lig bazlı ELO ev avantajı tablosu ──────────
# Gerçek veriler: PL'de ev avantajı büyük ligler arasında en az
# (65 varsayılan → PL için 40, Championship için 35)
LIG_EV_AVANTAJI = {
    "PL":  40,   # Premier League: %23 win rate gösterdi → avantajı düşür
    "ELC": 35,   # Championship: benzer sorun
    "PD":  55,   # La Liga: standart
    "BL1": 60,   # Bundesliga: hafif avantaj
    "SA":  58,   # Serie A
    "FL1": 55,   # Ligue 1
    "DED": 60,   # Eredivisie
    "PPL": 60,   # Primeira Liga
    "CL":  55,   # Champions League: neutral ground etkisi
    "EL":  55,
}

# Lig isim → kod eşlemesi (value_betler için)
LIG_ISIM_KOD = {
    "Premier League": "PL",
    "Championship":   "ELC",
    "La Liga":        "PD",
    "Bundesliga":     "BL1",
    "Serie A":        "SA",
    "Ligue 1":        "FL1",
    "Eredivisie":     "DED",
    "Primeira Liga":  "PPL",
    "Champions League": "CL",
}

def load_league_weights():
    wfile = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "league_weights.json")
    if os.path.exists(wfile):
        try:
            with open(wfile, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}
# sentiment_analysis modülü devre dışı — gerçek haber entegrasyonu yapılana kadar
# from scrapers.sentiment_analysis import fetch_team_news_sentiment
def _sentiment_sifir(_): return 0.0  # Placeholder — gerçek data gelene kadar şablon
from config.settings import (
    VALUE_BET_ESIGI, MIN_ORAN, MAX_ORAN,
    KUPON_MIN_EDGE, KUPON_2LI_ADET, KUPON_3LU_ADET,
    MIN_MAC_SAYISI
)

# v3.0: Beraberlik için çok daha yüksek edge eşiği
BERABERLIK_EDGE_ESIGI  = 0.06   # v3.0: 0.15 → 0.06 (VALUE_BET_ESIGI x 2, from settings.DRAW_EDGE_CARPAN)
MIN_KONSENSUS          = 0.70   # v3.0: 0.68 → 0.70 — daha seçici
MIN_KONSENSUS_KUPON    = 0.75   # v3.0: 0.72 → 0.75
MIN_MC_UYUM_KUPON      = 0.75   # v3.0: 0.72 → 0.75
SHARP_OVERROUND_ESIGI  = 1.06
MAX_CI_GENISLIK        = 0.25   # v3.0: 0.35 → 0.25 — tighter CI requirement

# v3.0: INSTITUTIONAL-GRADE EDGE CAPS
# Based on academic literature and Pinnacle market efficiency analysis.
# Even the best quantitative models achieve 2-5% edge against sharp markets.
MAX_EDGE               = 0.08   # v3.0: 0.12 → 0.08 — anything higher is hallucination
MAX_EDGE_NO_PINNACLE   = 0.05   # v3.0: 0.08 → 0.05 — no Pinnacle = less reliable
MAX_PIYASA_SAPMA       = 0.12   # v3.0: 0.22 → 0.12 — model vs market max 12% divergence
MIN_PIYASA_OLASILIK    = 0.20   # v3.0: 0.18 → 0.20 — don't bet where market gives <20%

# ── YENİ: Kupon parametreleri ─────────────────────────────────
# Kombine kuponu devre dışı bırakmak için False yapın (tavsiye edilen)
# Matematiksel kanıt: 3 seçim × %60 × %60 × %60 = %21.6 kazanma şansı
# Her seçim pozitif EV olsa bile parlay genellikle negatif EV biriktirir
ENABLE_PARLAY = False  # Varsayılan: kombine kupon KAPALI
# Birleşik kazanma olasılığı bu eşiğin altındaysa kupon önerilmez
KUPON_2LI_MIN_BIRLESIK_P  = 0.18   # 2'li kuponda min %18 kazanma şansı
KUPON_3LU_MIN_BIRLESIK_P  = 0.10   # 3'lü kuponda min %10 kazanma şansı
# Kupon içinde tek bir seçimin max oranı — çok yüksek oranlar kupona girmesin
KUPON_MAX_TEK_ORAN        = 4.50
# Kupon içinde tek bir seçimin min olasılığı
KUPON_MIN_TEK_OLASILIK    = 0.28   # her seçim en az %28 olasılıklı olmalı
# Aynı ligden max kaç maç bir kupona girebilir
KUPON_MAX_AYNI_LIG        = 1


def value_hesapla(olasilik: float, oran: float, fair_p: float = None,
                  lig_kodu: str = "", over_round: float = None) -> float:
    """
    v4.0: Vig-Normalized Fair Market Edge Calculation.

    Edge = p_shrunk - p_fair_market
    p_fair_market = (1/odds) / overround  (vig kaldırılmış gerçek piyasa olasılığı)
    p_shrunk = α * p_model + (1-α) * p_fair_market
    α is league-efficiency-adjusted (more efficient market → more shrinkage)

    KRİTİK:
    - %20'nin üzerindeki edge → veri hatası/bad odds → NO BET (return 0.0)
    - Oran <= 1.0 → NO BET
    - Vig normalize edilmemiş ham implied probability kullanılMAZ
    """
    if oran <= 1.0:
        return 0.0

    # Raw implied probability (vig dahil)
    raw_implied = 1.0 / oran

    # Vig-normalized fair market probability
    if fair_p is not None and 0.0 < fair_p < 1.0:
        p_market = fair_p  # Zaten vig normalize edilmiş
    elif over_round is not None and over_round > 1.0:
        p_market = raw_implied / over_round  # Vig'i kaldır
    else:
        p_market = raw_implied  # Fallback: vig yok varsay

    # Import shrinkage parameters from settings
    try:
        from config.settings import (
            SHRINKAGE_MODEL_WEIGHT, LIG_VERIMLILIK,
            LIG_VERIMLILIK_VARSAYILAN, LIG_MAX_EDGE, LIG_MAX_EDGE_VARSAYILAN
        )
    except ImportError:
        SHRINKAGE_MODEL_WEIGHT = 0.55
        LIG_VERIMLILIK = {}
        LIG_VERIMLILIK_VARSAYILAN = 0.85
        LIG_MAX_EDGE = {}
        LIG_MAX_EDGE_VARSAYILAN = 0.05

    # League-adjusted model weight
    # More efficient league → lower α → more trust in market
    league_eff = LIG_VERIMLILIK.get(lig_kodu, LIG_VERIMLILIK_VARSAYILAN)
    alpha = SHRINKAGE_MODEL_WEIGHT * (1.0 - league_eff * 0.3)
    alpha = max(0.30, min(0.60, alpha))  # Clamp to [0.30, 0.60]

    p_shrunk = alpha * olasilik + (1.0 - alpha) * p_market
    edge = p_shrunk - p_market

    # KRİTİK: %20 üzeri edge → veri hatası veya bad odds → NO BET
    if edge > 0.20:
        import warnings as _w
        _w.warn(
            f"[value_bet] Aşırı edge tespit edildi: {edge:.3f} (>{0.20}) — "
            f"muhtemelen veri hatası veya bad odds. NO BET.",
            RuntimeWarning, stacklevel=2
        )
        return 0.0

    # League-specific max edge cap
    max_edge = LIG_MAX_EDGE.get(lig_kodu, LIG_MAX_EDGE_VARSAYILAN)
    edge = min(max_edge, edge)

    return edge


def _ci_genislik(ci: tuple) -> float:
    if not ci or len(ci) < 2:
        return 1.0
    return ci[1] - ci[0]


def _piyasa_uyumu(model_p: float, fair_p: float) -> float:
    fark = abs(model_p - fair_p)
    if fark < 0.03:
        return 0.5
    if model_p > fair_p:
        return min(1.0, 0.5 + fark * 3)
    return max(0.0, 0.5 - fark * 2)


def _efektif_edge(edge: float, ci_w: float, piyasa_uyum: float,
                  over_round: float, tahmin: str,
                  pinnacle_var: bool = False,
                  sharp_sinyal: str = "YOK",
                  hareket_gucu: float = 0.0,
                  kitap_sayisi: int = 1) -> float:
    """
    GÜÇLENDIRILMIŞ (Audit v2):
    - Sharp uyumlu: bonus 0.004 → 0.015 (audit: %63 vs %44 isabet)
    - Sharp ters yön: ceza -0.010 uygulanır
    - Pinnacle referansı: bonus 0.008 (daha güçlü referans)
    - Çok kitaplı (5+): bonus 0.005 (konsensus artar)
    """
    bonus_skor = 0.0

    # Referans kalitesi bonusları
    if pinnacle_var:
        bonus_skor += 0.008   # YÜKSELTİLDİ: 0.005 → 0.008
    if over_round <= 1.05:
        bonus_skor += 0.005
    if kitap_sayisi >= 5:
        bonus_skor += 0.005   # YÜKSELTİLDİ: 0.002 → 0.005 (5+ kitap = yüksek konsensus)
    elif kitap_sayisi >= 3:
        bonus_skor += 0.002

    # Geniş güven aralığı → bonus cezası
    if ci_w > 0.20:
        bonus_skor *= max(0.35, 1.0 - min(ci_w, 0.9))

    # Model–piyasa uyumu
    if piyasa_uyum > 0.55:
        bonus_skor += min(0.003, (piyasa_uyum - 0.5) * 0.010)

    # ── SHARP MONEY ENTEGRASYONU (Audit Bulgusu: +19pp avantaj) ──────────
    _bek_sharp = {
        "Ev Sahibi Kazanır": "EV",
        "Deplasman Kazanır": "DEP",
        "Beraberlik":        "BER",
    }
    _ss = str(sharp_sinyal or "").strip().upper()
    beklenen = _bek_sharp.get(tahmin, "")

    if _ss not in ("", "YOK", "NONE"):
        if beklenen == _ss:
            # Sharp AYNI yönde → güçlü pozitif sinyal
            # Audit: sharp uyumlu %63.1 isabet
            hareket_bonus = min(0.015, float(hareket_gucu) * 0.025)
            bonus_skor += max(0.008, hareket_bonus)  # Min 0.8pp garantili
        else:
            # Sharp TERS yönde → negatif sinyal, ceza uygula
            # Audit: sharp çelişen %43.7 isabet (piyasanın %44'ü)
            ceza = min(0.010, float(hareket_gucu) * 0.015)
            bonus_skor -= max(0.005, ceza)
    # ─────────────────────────────────────────────────────────────────────

    final_edge = edge + min(0.015, bonus_skor)   # Cap 0.010 → 0.015
    return min(0.12, max(-0.05, final_edge))      # Alt sınır da koru


def value_betleri_bul(mac_listesi: list, istatistikler: dict,
                       lig_ortalamasi: dict, elo_sonuclari: dict,
                       ham_veri=None, hakem_db: dict = None) -> list:
    db_isimleri   = set(istatistikler.keys())
    sonuclar      = []
    eslesmeyenler = set()
    league_weights = load_league_weights()

    # v3.0: Import institutional parameters
    try:
        from config.settings import (
            ELC_AKTIF, GLOBAL_MAX_EDGE, GLOBAL_MIN_EDGE,
            DRAW_MAX_GUNLUK, DRAW_EDGE_CARPAN,
            LIG_MAX_EDGE, LIG_MAX_EDGE_VARSAYILAN
        )
    except ImportError:
        ELC_AKTIF = True
        GLOBAL_MAX_EDGE = 0.08
        GLOBAL_MIN_EDGE = 0.02
        DRAW_MAX_GUNLUK = 1
        DRAW_EDGE_CARPAN = 2.0
        LIG_MAX_EDGE = {}
        LIG_MAX_EDGE_VARSAYILAN = 0.05
    
    # v3.0: Draw daily counter
    draw_count = 0

    for mac in mac_listesi:
        ev_odds  = mac["ev"]
        dep_odds = mac["dep"]
        lig_kodu = mac["lig"]

        # v3.0: Skip Championship — 0% win rate, negative ROI
        if not ELC_AKTIF and lig_kodu == "ELC":
            continue

        ev_db  = eslestir(ev_odds,  db_isimleri)
        dep_db = eslestir(dep_odds, db_isimleri)

        ev_bilinmiyor  = ev_db  is None
        dep_bilinmiyor = dep_db is None

        if ev_bilinmiyor:
            eslesmeyenler.add(ev_odds)
            ev_db = ev_odds
        if dep_bilinmiyor:
            eslesmeyenler.add(dep_odds)
            dep_db = dep_odds

        ev_mac  = istatistikler.get(ev_db,  {}).get("mac_sayisi", 0)
        dep_mac = istatistikler.get(dep_db, {}).get("mac_sayisi", 0)
        if ev_mac < MIN_MAC_SAYISI or dep_mac < MIN_MAC_SAYISI:
            continue

        ev_oran    = mac["ev_oran"]
        ber_oran   = mac["ber_oran"]
        dep_oran   = mac["dep_oran"]
        over_round = mac.get("over_round",  1.07)
        fair_ev    = mac.get("fair_ev",     1.0 / ev_oran)
        fair_ber   = mac.get("fair_ber",    1.0 / ber_oran)
        fair_dep   = mac.get("fair_dep",    1.0 / dep_oran)

        hakem_ismi = mac.get("hakem", "")
        hakem_agresifligi = 1.0
        if hakem_db and hakem_ismi:
            try:
                from scrapers.hakem_verisi import hakem_etkisi_bul
                hakem_agresifligi = hakem_etkisi_bul(hakem_ismi, hakem_db)
            except Exception:
                pass

        # Sentiment devre dışı (0.0 sabit) — gerçek haber entegrasyonu yapılana kadar
        sentiment_ev  = 0.0
        sentiment_dep = 0.0
        
        try:
            sonuc = model_birlestir(
                ev_db, dep_db,
                istatistikler, elo_sonuclari,
                lig_ortalamasi, lig_kodu,
                ham_veri=ham_veri,
                mac_tarihi=mac.get("mac_tarihi", ""),
                ev_mac_tarihleri=istatistikler.get(ev_db, {}).get("mac_tarihleri", []),
                dep_mac_tarihleri=istatistikler.get(dep_db, {}).get("mac_tarihleri", []),
                hakem_agresifligi=hakem_agresifligi,
                sentiment_ev=sentiment_ev,
                sentiment_dep=sentiment_dep,
                kadro_etki=mac.get("kadro_etki")
            )
        except Exception:
            continue

        if sonuc is None:
            continue

        ev_p  = sonuc["home_win"]
        ber_p = sonuc["draw"]
        dep_p = sonuc["away_win"]

        # ── FAKE EDGE FİLTRESİ: p_final ağırlıklı formül ─────────────────
        # Model tek başına yetmez. Model + piyasa + sharp 3'ü birleştirilir.
        # sharp_sinyal yoksa ağırlık model+piyasa'ya paylaştırılır.
        _sharp_p_ev  = 0.0
        _sharp_p_dep = 0.0
        _sharp_p_ber = 0.0
        _has_sharp   = mac.get("sharp_sinyal", "YOK") not in ("", "YOK", "NONE")
        if _has_sharp:
            _ss = str(mac.get("sharp_sinyal", "")).strip().upper()
            if _ss == "EV":
                _sharp_p_ev = min(0.90, fair_ev * 1.05)
                _sharp_p_dep = (1 - _sharp_p_ev) * (fair_dep / (fair_dep + fair_ber + 1e-9))
                _sharp_p_ber = 1 - _sharp_p_ev - _sharp_p_dep
            elif _ss == "DEP":
                _sharp_p_dep = min(0.90, fair_dep * 1.05)
                _sharp_p_ev = (1 - _sharp_p_dep) * (fair_ev / (fair_ev + fair_ber + 1e-9))
                _sharp_p_ber = 1 - _sharp_p_dep - _sharp_p_ev
            else:
                _sharp_p_ev, _sharp_p_ber, _sharp_p_dep = fair_ev, fair_ber, fair_dep
        # Ağırlıklar: model=0.40, piyasa=0.40, sharp=0.20
        _w_model  = 0.40
        _w_piyasa = 0.40 if not _has_sharp else 0.40
        _w_sharp  = 0.20 if _has_sharp else 0.00
        _w_model_eff  = _w_model  / (_w_model + _w_piyasa + _w_sharp + 1e-9) * 1.0
        _w_piyasa_eff = _w_piyasa / (_w_model + _w_piyasa + _w_sharp + 1e-9) * 1.0
        _w_sharp_eff  = _w_sharp  / (_w_model + _w_piyasa + _w_sharp + 1e-9) * 1.0
        ev_p_final  = _w_model_eff * ev_p  + _w_piyasa_eff * fair_ev  + _w_sharp_eff * _sharp_p_ev
        ber_p_final = _w_model_eff * ber_p + _w_piyasa_eff * fair_ber + _w_sharp_eff * _sharp_p_ber
        dep_p_final = _w_model_eff * dep_p + _w_piyasa_eff * fair_dep + _w_sharp_eff * _sharp_p_dep
        _sum_final  = ev_p_final + ber_p_final + dep_p_final
        if _sum_final > 0:
            ev_p_final /= _sum_final
            dep_p_final /= _sum_final
            ber_p_final /= _sum_final
        # p_final kullan — ham model değerinden daha muhafazakar
        ev_p  = ev_p_final
        dep_p = dep_p_final
        ber_p = ber_p_final
        # ────────────────────────────────────────────────────────────────────

        # 🧠 ŞAMPİYON DOKUNUŞU (FAZ 12 - AUTO-ML LİG KATSAYISI)
        lig_isim_test = mac.get("lig_isim", "")
        isabet_carpani = league_weights.get(lig_isim_test, 1.0)
        
        # Eğer bu ligde makine eziyorsa olasılıklar şişer (Edge artar), kaybediyorsa ufalanır (Elit filtreden düşer)
        ev_p = min(0.99, ev_p * isabet_carpani)
        ber_p = min(0.99, ber_p * isabet_carpani)
        dep_p = min(0.99, dep_p * isabet_carpani)

        # 🔴 DENETİM (31.03.2026): Kalibrasyon katmanı kaldırıldı.
        # apply_probability_pipeline() tek kaynak olarak yeterli.
        # Eski: kalibrasyon_uygula(ev_p/ber_p/dep_p, lig_isim)

        if not (0.05 <= ev_p  <= 0.95): continue
        if not (0.02 <= ber_p <= 0.55): continue
        if not (0.05 <= dep_p <= 0.95): continue

        piyasa_map = {
            "Ev Sahibi Kazanır": ("home_win_ci", ev_p,  ev_oran,  fair_ev),
            # 🔴 DENETİM (31.03.2026): Beraberlik kaldırıldı — %14.3 isabet, -%38 ROI.
            # Poisson modelleri beraberlik tahmininde sistematik olarak başarısız.
            # "Beraberlik":        ("draw_ci",      ber_p, ber_oran, fair_ber),
            "Deplasman Kazanır": ("away_win_ci",  dep_p, dep_oran, fair_dep),
        }

        for tahmin, (ci_key, olasilik, oran, fair_p) in piyasa_map.items():
            if not (MIN_ORAN <= oran <= MAX_ORAN):
                continue
            
            # 🔴 DENETİM (31.03.2026): %55 minimum filtresi kaldırıldı.
            # Edge hesabı + MAX_ORAN zaten düşük şanslı bahisleri filtreler.
            # Bu filtre kârlı deplasman galibiyetlerini (%43 model güveni,
            # 2.80 oran = gerçek değer) engelliyordu.
            # Eski: if olasilik < 0.55: continue

            # v3.0: Draw daily limit check
            if tahmin == "Beraberlik" and draw_count >= DRAW_MAX_GUNLUK:
                continue

            edge = value_hesapla(olasilik, oran, fair_p=fair_p, lig_kodu=lig_kodu)

            # v3.0: Global hard cap — anything above GLOBAL_MAX_EDGE is model hallucination
            if edge > GLOBAL_MAX_EDGE:
                continue

            # v3.0: Minimum edge noise floor
            if edge < GLOBAL_MIN_EDGE:
                continue

            esik = BERABERLIK_EDGE_ESIGI * DRAW_EDGE_CARPAN if tahmin == "Beraberlik" else VALUE_BET_ESIGI
            
            # YENİ: Kendi Hatasından Öğrenen Meta-Learner Cezası
            try:
                from model.meta_learner import meta_ceza_uygula
                esik = meta_ceza_uygula(mac.get("lig_isim", ""), tahmin, esik)
            except Exception:
                pass

            if edge < esik:
                continue

            max_edge_esik = MAX_EDGE if mac.get("pinnacle_var") else MAX_EDGE_NO_PINNACLE
            if edge > max_edge_esik:
                continue

            if fair_p < MIN_PIYASA_OLASILIK:
                continue

            if abs(olasilik - fair_p) > MAX_PIYASA_SAPMA:
                continue

            ci    = sonuc.get(ci_key, (0, 1))
            ci_w  = _ci_genislik(ci)

            if ci_w > MAX_CI_GENISLIK:
                continue

            piyasa_uyum = _piyasa_uyumu(olasilik, fair_p)
            efektif     = _efektif_edge(
                edge, ci_w, piyasa_uyum, over_round, tahmin,
                pinnacle_var  = mac.get("pinnacle_var",  False),
                sharp_sinyal  = mac.get("sharp_sinyal",  "YOK"),
                hareket_gucu  = mac.get("hareket_gucu",  0.0),
                kitap_sayisi  = mac.get("kitap_sayisi",  1),
            )

            # v3.0: GLOBAL HARD CAP on efektif edge (post-bonus)
            if efektif > GLOBAL_MAX_EDGE:
                efektif = GLOBAL_MAX_EDGE

            # ANOMALİ TESPİTİ: Efektif edge, ham edge'den %50'den fazla büyükse uyar
            if efektif > edge * 1.40:
                import warnings as _w
                _w.warn(
                    f"[value_bet] Şüpheli efektif edge: {ev_odds} vs {dep_odds} "
                    f"edge={edge:.3f} → efektif={efektif:.3f} ({tahmin})",
                    RuntimeWarning, stacklevel=2
                )

            if efektif < esik:
                continue

            if sonuc.get("konsensus", 0) < MIN_KONSENSUS:
                continue

            # v3.0: Draw counter increment (happens just before appending)
            if tahmin == "Beraberlik":
                draw_count += 1

            # Erken Uyarı (Early Alert) tespiti:
            # - Maçın başlamasına 36 saatten fazla var ise
            # - Ve efektif değer (edge) normal eşiğin (örn %10) üstünde ise
            erken_uyari = False
            tarih_str = str(mac.get("mac_tarihi", ""))
            if tarih_str:
                from datetime import datetime
                try:
                    if "T" in tarih_str:
                        m_dt = datetime.fromisoformat(tarih_str.replace("Z", "+00:00")).replace(tzinfo=None)
                    else:
                        m_dt = datetime.strptime(tarih_str[:10], "%Y-%m-%d")
                    saat_fark = (m_dt - datetime.now()).total_seconds() / 3600
                    # Normal esigin x1.2 ustu degerli secimler + 36 saat ilerisi
                    if saat_fark > 36.0 and efektif >= VALUE_BET_ESIGI * 1.2:
                        erken_uyari = True
                except Exception:
                    pass

            sonuclar.append({
                "ev":             ev_odds,
                "dep":            dep_odds,
                "erken_uyari":    erken_uyari,
                "mac_id":         f"{ev_odds}|{dep_odds}|{str(mac.get('mac_tarihi',''))[:10]}",
                "ev_db":          ev_db,
                "dep_db":         dep_db,
                "lig":            mac["lig_isim"],
                "lig_kodu":       lig_kodu,
                "mac_tarihi":     mac.get("mac_tarihi", ""),
                "ev_bilinmiyor":  ev_bilinmiyor,
                "dep_bilinmiyor": dep_bilinmiyor,
                "tahmin":         tahmin,
                "oran":           oran,
                "olasilik":       round(olasilik,    4),
                "p_model":        round(olasilik,    4),
                "edge":           round(edge,         4),
                "ev":             round((olasilik * oran) - 1.0, 4),
                "efektif_edge":   round(efektif,      4),
                "fair_p":         round(fair_p,       4),
                "p_fair":         round(fair_p,       4),
                "piyasa_sapma":   round(olasilik - fair_p, 4),
                "piyasa_uyum":    round(piyasa_uyum,  3),
                "over_round":     round(over_round,   4),
                "kitap_marji":    mac.get("kitap_marji", 0),
                "sharp_piyasa":   over_round <= SHARP_OVERROUND_ESIGI,
                "lam_ev":         sonuc["lam_ev"],
                "lam_dep":        sonuc["lam_dep"],
                "ev_p":           ev_p,
                "ber_p":          ber_p,
                "dep_p":          dep_p,
                "over15_p":       sonuc.get("over15_p", 0),
                "over25_p":       sonuc.get("over25_p", 0),
                "over35_p":       sonuc.get("over35_p", 0),
                "bts_p":          sonuc.get("bts_p",    0),
                "ev_elo":         sonuc["ev_elo"],
                "dep_elo":        sonuc["dep_elo"],
                "konsensus":        sonuc["konsensus"],
                "mc_analitik_uyum": sonuc.get("mc_analitik_uyum", 1.0),
                ci_key:             ci,
                "elo_ev_p":         sonuc["elo_ev_p"],
                "poisson_ev_p":     sonuc["poisson_ev_p"],
                "mc_ev_p":          sonuc["mc_ev_p"],
                "ev_form_skor":    sonuc.get("ev_form_skor",    0.5),
                "dep_form_skor":   sonuc.get("dep_form_skor",   0.5),
                "ev_momentum":     sonuc.get("ev_momentum",     0.0),
                "dep_momentum":    sonuc.get("dep_momentum",    0.0),
                "ev_seri":         sonuc.get("ev_seri",         "?????"),
                "dep_seri":        sonuc.get("dep_seri",        "?????"),
                "h2h_guven":       sonuc.get("h2h_guven",       0.0),
                "h2h_mac":         sonuc.get("h2h_mac",         0),
                "agirlik_elo":     sonuc.get("agirlik_elo",     0.4),
                "agirlik_poisson": sonuc.get("agirlik_poisson", 0.3),
                "agirlik_form":    sonuc.get("agirlik_form",    0.0),
                "agirlik_h2h":     sonuc.get("agirlik_h2h",     0.0),
                "kitap_sayisi":    mac.get("kitap_sayisi",   1),
                "kitap_fark":      mac.get("kitap_fark",     0),
                "pinnacle_var":    mac.get("pinnacle_var",   False),
                "sharp_ev_value":  mac.get("sharp_ev_value", False),
                "sharp_dep_value": mac.get("sharp_dep_value",False),
                "ev_hareket":      mac.get("ev_hareket",    0),
                "dep_hareket":     mac.get("dep_hareket",   0),
                "sharp_sinyal":    mac.get("sharp_sinyal",  "YOK"),
                "hareket_gucu":    mac.get("hareket_gucu",  0.0),
                "ilk_ev_oran":     mac.get("ilk_ev_oran",   0),
                "ilk_dep_oran":    mac.get("ilk_dep_oran",  0),
                "en_olasi_skorlar": sonuc.get("en_olasi_skorlar", []),
                "iy_ev_p":   sonuc.get("iy_ev_p",  0),
                "iy_ber_p":  sonuc.get("iy_ber_p", 0),
                "iy_dep_p":  sonuc.get("iy_dep_p", 0),
                "ev_clean_sheet":   sonuc.get("ev_clean_sheet",  0),
                "dep_clean_sheet":  sonuc.get("dep_clean_sheet", 0),
                "ev_lig_sira":      sonuc.get("ev_lig_sira",      0),
                "dep_lig_sira":     sonuc.get("dep_lig_sira",     0),
                "ev_lig_sira_oran": sonuc.get("ev_lig_sira_oran", 0.5),
                "dep_lig_sira_oran":sonuc.get("dep_lig_sira_oran",0.5),
                "ev_puan":          sonuc.get("ev_puan",  0),
                "dep_puan":         sonuc.get("dep_puan", 0),
            })

    # ── Risksiz Pazarlar KALDIRILDI ─────────────────────────────────────────────
    # 🔴 DENETİM SONUCU (31.03.2026): KG Var, 1.5 Üst, Çifte Şans bahisleri
    # SAHTE sabit oranlar (1.30, 1.85, 1.22) kullanıyordu ve sonuç eşleştirmesi
    # tamamen bozuktu (sonuc_guncelle.py sadece ev/dep/ber yazıyor).
    # 85 bahiste 0 kazanma = -%100 ROI → tüm 1X2 kârını yok ediyordu.
    # Temel 1X2 modeli kaldırma sonrası: 191 bahis, %50.8 isabet, +%23 ROI.
    #
    # Gerçek piyasa oranları API'den çekilmeden ve sonuç doğrulaması
    # düzgün çalışmadan bu bahis tipleri tekrar eklenmemeli.

    # ── Over/Under value betler ────────────────────────────────
    for mac in mac_listesi:
        ev_odds  = mac["ev"]
        dep_odds = mac["dep"]
        lig_kodu = mac["lig"]

        ev_db  = eslestir(ev_odds,  db_isimleri)
        dep_db = eslestir(dep_odds, db_isimleri)
        if ev_db is None or dep_db is None:
            continue

        ev_mac  = istatistikler.get(ev_db,  {}).get("mac_sayisi", 0)
        dep_mac = istatistikler.get(dep_db, {}).get("mac_sayisi", 0)
        if ev_mac < MIN_MAC_SAYISI or dep_mac < MIN_MAC_SAYISI:
            continue

        hakem_ismi = mac.get("hakem", "")
        hakem_agresifligi = 1.0
        if hakem_db and hakem_ismi:
            try:
                from scrapers.hakem_verisi import hakem_etkisi_bul
                hakem_agresifligi = hakem_etkisi_bul(hakem_ismi, hakem_db)
            except Exception:
                pass

        # Sentiment devre dışı (0.0 sabit) — gerçek haber entegrasyonu yapılana kadar
        sentiment_ev  = 0.0
        sentiment_dep = 0.0
        
        try:
            sonuc = model_birlestir(
                ev_db, dep_db,
                istatistikler, elo_sonuclari,
                lig_ortalamasi, lig_kodu,
                ham_veri=ham_veri,
                mac_tarihi=mac.get("mac_tarihi", ""),
                ev_mac_tarihleri=istatistikler.get(ev_db, {}).get("mac_tarihleri", []),
                dep_mac_tarihleri=istatistikler.get(dep_db, {}).get("mac_tarihleri", []),
                hakem_agresifligi=hakem_agresifligi,
                sentiment_ev=sentiment_ev,
                sentiment_dep=sentiment_dep
            )
        except Exception:
            continue

        if sonuc is None:
            continue

        over_round = mac.get("over_round", 1.07)

        for ou_tip, model_p_key, oran_key in [
            ("2.5 Üst", "over25_p", "over25_oran"),
            ("2.5 Alt", "under25_p", "under25_oran"),
        ]:
            oran = mac.get(oran_key, 0)
            if not oran or not (MIN_ORAN <= oran <= MAX_ORAN):
                continue

            if ou_tip == "2.5 Üst":
                model_p = sonuc.get("over25_p", 0)
            else:
                model_p = 1.0 - sonuc.get("over25_p", 0)

            if model_p < 0.15 or model_p > 0.90:
                continue

            fair_p = 1.0 / oran
            # O/U için daha düşük eşik: 1X2'ye göre daha güvenilir piyasa — %30 daha kolay geçer
            ou_edge_esigi = VALUE_BET_ESIGI * 0.70
            edge   = (model_p * oran) - 1
            if edge < ou_edge_esigi:
                continue

            piyasa_uyum = _piyasa_uyumu(model_p, fair_p)
            ci_w_ou = 0.20  # O/U için varsayılan CI genişliği
            efektif     = edge * max(0.6, 1.0 - ci_w_ou) * (0.85 + piyasa_uyum * 0.30)

            if efektif < VALUE_BET_ESIGI:
                continue

            sonuclar.append({
                "ev":             ev_odds,
                "dep":            dep_odds,
                "mac_id":         f"{ev_odds}|{dep_odds}|{str(mac.get('mac_tarihi',''))[:10]}",
                "ev_db":          ev_db,
                "dep_db":         dep_db,
                "lig":            mac["lig_isim"],
                "lig_kodu":       lig_kodu,
                "mac_tarihi":     mac.get("mac_tarihi", ""),
                "ev_bilinmiyor":  False,
                "dep_bilinmiyor": False,
                "tahmin":         ou_tip,
                "oran":           oran,
                "olasilik":       round(model_p, 4),
                "edge":           round(edge, 4),
                "efektif_edge":   round(efektif, 4),
                "fair_p":         round(fair_p, 4),
                "piyasa_sapma":   round(model_p - fair_p, 4),
                "piyasa_uyum":    round(piyasa_uyum, 3),
                "over_round":     round(over_round, 4),
                "kitap_marji":    mac.get("kitap_marji", 0),
                "sharp_piyasa":   over_round <= SHARP_OVERROUND_ESIGI,
                "lam_ev":         sonuc.get("lam_ev", 0),
                "lam_dep":        sonuc.get("lam_dep", 0),
                "ev_p":  sonuc.get("home_win", 0),
                "ber_p": sonuc.get("draw", 0),
                "dep_p": sonuc.get("away_win", 0),
                "over15_p":  sonuc.get("over15_p", 0),
                "over25_p":  sonuc.get("over25_p", 0),
                "over35_p":  sonuc.get("over35_p", 0),
                "bts_p":     sonuc.get("bts_p",    0),
                "ev_elo":    sonuc.get("ev_elo", 1500),
                "dep_elo":   sonuc.get("dep_elo", 1500),
                "konsensus":        sonuc.get("konsensus", 0.7),
                "mc_analitik_uyum": sonuc.get("mc_analitik_uyum", 0.7),
                "home_win_ci": sonuc.get("home_win_ci", (0, 1)),
                "draw_ci":     sonuc.get("draw_ci",     (0, 1)),
                "away_win_ci": sonuc.get("away_win_ci", (0, 1)),
                "elo_ev_p":     sonuc.get("elo_ev_p",     0),
                "poisson_ev_p": sonuc.get("poisson_ev_p", 0),
                "mc_ev_p":      sonuc.get("mc_ev_p",      0),
                "ev_form_skor":  sonuc.get("ev_form_skor",  0.5),
                "dep_form_skor": sonuc.get("dep_form_skor", 0.5),
                "ev_momentum":   sonuc.get("ev_momentum",   0.0),
                "dep_momentum":  sonuc.get("dep_momentum",  0.0),
                "ev_seri":   sonuc.get("ev_seri",  "?????"),
                "dep_seri":  sonuc.get("dep_seri", "?????"),
                "h2h_guven": sonuc.get("h2h_guven", 0.0),
                "h2h_mac":   sonuc.get("h2h_mac",   0),
                "agirlik_elo":     sonuc.get("agirlik_elo",     0.4),
                "agirlik_poisson": sonuc.get("agirlik_poisson", 0.3),
                "agirlik_form":    sonuc.get("agirlik_form",    0.0),
                "agirlik_h2h":     sonuc.get("agirlik_h2h",    0.0),
                "en_olasi_skorlar": sonuc.get("en_olasi_skorlar", []),
                "iy_ev_p":   sonuc.get("iy_ev_p",  0),
                "iy_ber_p":  sonuc.get("iy_ber_p", 0),
                "iy_dep_p":  sonuc.get("iy_dep_p", 0),
                "ev_clean_sheet":  sonuc.get("ev_clean_sheet",  0),
                "dep_clean_sheet": sonuc.get("dep_clean_sheet", 0),
                "ev_lig_sira":      sonuc.get("ev_lig_sira",      0),
                "dep_lig_sira":     sonuc.get("dep_lig_sira",     0),
                "ev_lig_sira_oran": sonuc.get("ev_lig_sira_oran", 0.5),
                "dep_lig_sira_oran": sonuc.get("dep_lig_sira_oran", 0.5),
                "ev_puan":   sonuc.get("ev_puan",  0),
                "dep_puan":  sonuc.get("dep_puan", 0),
                "kitap_sayisi": mac.get("kitap_sayisi", 1),
                "kitap_fark":   mac.get("kitap_fark",   0),
                "pinnacle_var": mac.get("pinnacle_var", False),
                "sharp_ev_value":  mac.get("sharp_ev_value",  False),
                "sharp_dep_value": mac.get("sharp_dep_value", False),
                "ev_hareket":  mac.get("ev_hareket",  0),
                "dep_hareket": mac.get("dep_hareket", 0),
                "sharp_sinyal":  mac.get("sharp_sinyal",  "YOK"),
                "hareket_gucu":  mac.get("hareket_gucu",  0.0),
                "ilk_ev_oran":   mac.get("ilk_ev_oran",   0),
                "ilk_dep_oran":  mac.get("ilk_dep_oran",  0),
            })

    sonuclar.sort(key=lambda x: x["efektif_edge"], reverse=True)

    if eslesmeyenler:
        print(f"  ⚠️  {len(eslesmeyenler)} takım eşleşmedi: "
              f"{', '.join(sorted(eslesmeyenler)[:8])}")

    return sonuclar


# ══════════════════════════════════════════════════════════════════
#  KUPON OLUŞTURMA — YENİDEN YAZILDI v2
#
#  Eski sorun: %0 isabet — her sefer 10 kupon kaybetti
#  Yeni yaklaşım:
#    1. Her seçim minimum %28 bireysel olasılık (zayıf seçim girmesin)
#    2. Birleşik olasılık minimum eşiği (%18 2li, %10 3lü)
#    3. Aynı ligden max 1 maç (korelasyon azalt)
#    4. Sıralama kriteri: %60 kazanma olasılığı + %40 edge
#       (eskisi: sadece edge → gerçekçi olmayan yüksek oranlar)
#    5. Oran sınırı daraltıldı: max 3.80 (eski 50.0 çok geniş)
# ══════════════════════════════════════════════════════════════════

def kupon_olustur(value_betler: list) -> tuple:
    """
    Gerçekçi kupon önerileri oluşturur.

    Seçim kriterleri (her bet için):
      - efektif_edge >= KUPON_MIN_EDGE
      - konsensus >= MIN_KONSENSUS_KUPON
      - mc_analitik_uyum >= MIN_MC_UYUM_KUPON
      - Beraberlik tahmini kabul edilmez
      - piyasa_uyum >= 0.45
      - Bireysel olasılık >= KUPON_MIN_TEK_OLASILIK (%28)  ← YENİ
      - Tek oran <= KUPON_MAX_TEK_ORAN (4.50)              ← YENİ

    Kupon kriterleri:
      - Aynı ligden max 1 maç                              ← YENİ
      - Birleşik olasılık >= eşik                          ← YENİ
      - Sıralama: kazanma olasılığı ağırlıklı              ← YENİ
    """
    # 1. Uygun betleri filtrele
    uygun = [b for b in value_betler
             if b["efektif_edge"]      >= KUPON_MIN_EDGE
             and not b["ev_bilinmiyor"]
             and not b["dep_bilinmiyor"]
             and b["konsensus"]         >= MIN_KONSENSUS_KUPON
             and b["mc_analitik_uyum"]  >= MIN_MC_UYUM_KUPON
             and b["tahmin"]            != "Beraberlik"
             and b["piyasa_uyum"]       >= 0.45
             # YENİ: bireysel olasılık filtresi
             and b["olasilik"]          >= KUPON_MIN_TEK_OLASILIK
             # YENİ: tek oran üst sınırı
             and b["oran"]              <= KUPON_MAX_TEK_ORAN]

    # 2. Aynı maçtan en iyi beti al
    mac_baz = {}
    for bet in uygun:
        anahtar = (bet["ev_db"], bet["dep_db"])
        if anahtar not in mac_baz or bet["efektif_edge"] > mac_baz[anahtar]["efektif_edge"]:
            mac_baz[anahtar] = bet

    secimler = sorted(mac_baz.values(), key=lambda x: x["efektif_edge"], reverse=True)

    def _lig_cakisimi_var_mi(kombo: tuple) -> bool:
        """Aynı ligden 2+ maç varsa True döner."""
        ligler = [b["lig_kodu"] for b in kombo]
        return len(ligler) != len(set(ligler))

    def _kupon_skoru(birlesik_p: float, edge: float) -> float:
        """
        Kupon sıralama skoru.
        %60 kazanma olasılığı + %40 edge — eski: sadece edge
        """
        return birlesik_p * 0.60 + edge * 0.40

    def _kombo(n: int, min_birlesik_p: float) -> list:
        kuponlar = []
        for kombo in combinations(secimler, n):
            # YENİ: aynı lig kontrolü
            if _lig_cakisimi_var_mi(kombo):
                continue

            toplam_oran = 1.0
            birlesik_p  = 1.0
            toplam_edge = 0.0

            for b in kombo:
                toplam_oran *= b["oran"]
                birlesik_p  *= b["olasilik"]
                toplam_edge += b["efektif_edge"]

            edge = (birlesik_p * toplam_oran) - 1
            if edge <= 0:
                continue

            # Oran aralığı — daraltıldı
            if toplam_oran < 2.00 or toplam_oran > 20.0:
                continue

            # YENİ: minimum birleşik olasılık kontrolü
            if birlesik_p < min_birlesik_p:
                continue

            skor = _kupon_skoru(birlesik_p, edge)

            kuponlar.append({
                "bahisler":    list(kombo),
                "toplam_oran": round(toplam_oran, 2),
                "birlesik_p":  round(birlesik_p,  4),
                "kazanma_olasiligi": round(birlesik_p * 100, 1),
                "edge":        round(edge,         4),
                "skor":        round(skor,          4),
            })

        # YENİ: skor'a göre sırala (eski: sadece edge)
        return sorted(kuponlar, key=lambda x: x["skor"], reverse=True)

    kupon_2li = []
    kupon_3lu = []

    if ENABLE_PARLAY:
        kupon_2li = _kombo(2, KUPON_2LI_MIN_BIRLESIK_P)[:KUPON_2LI_ADET]
        kupon_3lu = _kombo(3, KUPON_3LU_MIN_BIRLESIK_P)[:KUPON_3LU_ADET]
    else:
        import logging as _log_vb
        _log_vb.getLogger(__name__).info(
            "[kupon] ENABLE_PARLAY=False — kombine kupon üretilmedi, single bet önerilir"
        )

    # Özet bilgi
    if kupon_2li:
        ort_p = sum(k["birlesik_p"] for k in kupon_2li) / len(kupon_2li)
        print(f"  📋 2'li kupon: {len(kupon_2li)} adet  |  Ort. kazanma: %{ort_p*100:.0f}")
    if kupon_3lu:
        ort_p = sum(k["birlesik_p"] for k in kupon_3lu) / len(kupon_3lu)
        print(f"  📋 3'lü kupon: {len(kupon_3lu)} adet  |  Ort. kazanma: %{ort_p*100:.0f}")

    return kupon_2li, kupon_3lu