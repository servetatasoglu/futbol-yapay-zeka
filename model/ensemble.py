# analysis/model_birlestir.py
"""
Model Birleştirici v3 — Hava Durumu + Yorgunluk + Dinamik Edge
───────────────────────────────────────────────────────────────
DEĞİŞİKLİKLER:
  • Katman 4.6: Hava Durumu (OpenMeteo — ücretsiz)
    lam_ev ve lam_dep yağış + soğukta düşürülüyor
  • Katman 4.7: Yorgunluk
    Son 7 günde 2+ maç → λ × 0.95
    Championship: Son 5 günde 2+ maç → λ × 0.93
  • Dinamik edge eşiği: get_edge_esigi(lig_kodu, tahmin_tipi)
    — value_bet.py bu fonksiyonu kullanabilir
  Tüm yeni katmanlar opsiyonel (try/except) — sistem mevcut
  şekliyle çalışmaya devam eder.
"""

import os as _os_ensemble
import time as _time_ensemble
import logging as _log_ensemble

_logger_ens = _log_ensemble.getLogger(__name__)

from features.elo    import elo_olasilik
from features.poisson import poisson_tahmin
from features.monte_carlo   import monte_carlo_simule
from features.form import form_hesapla, form_lambda_uygula
from features.h2h_model     import h2h_analiz, h2h_lambda_uygula, beraberlik_kalibrasyon
from model.meta_learner  import adaptif_agirlik_hesapla, model_birlestir_v3, feature_vektor
from config.settings        import ELO_AGIRLIK_YETERLI, ELO_AGIRLIK_VARSAYILAN, BER_KALIBRASYON_AGIRLIK

# xG modülünü opsiyonel yükle
try:
    from data.xg import xg_yukle, xg_ara
    _XG_MODULU_VAR = True
except ImportError:
    _XG_MODULU_VAR = False

# GBM meta-learner opsiyonel
try:
    from model.train import tahmin_yap as gbm_tahmin_yap
    _GBM_VAR = True
except ImportError:
    _GBM_VAR = False

# Standart 3 sınıflı eşleştirme: 0 = Ev Sahibi (1), 1 = Beraberlik (X), 2 = Deplasman (2)
SINIF_ESLESTIRME = {0: "1", 1: "X", 2: "2"}



def _gbm_saglik_kontrol() -> bool:
    """
    GBM model dosyasının varlığını ve tazeliğini kontrol eder.
    Dosya varsa ve okunabiliyorsa True döner. Yaş durumunda uyarı verir ama modeli sessizce kapatmaz.
    """
    path = _os_ensemble.path.join(_os_ensemble.path.dirname(_os_ensemble.path.dirname(_os_ensemble.path.abspath(__file__))), "data", "gbm_model.pkl")
    if not _os_ensemble.path.exists(path):
        # Fallback path
        path = _os_ensemble.path.join("data", "gbm_model.pkl")
    if not _os_ensemble.path.exists(path):
        _logger_ens.warning("[GBM] Model dosyası (gbm_model.pkl) bulunamadı — GBM devre dışı")
        return False
    try:
        age_days = (_time_ensemble.time() - _os_ensemble.path.getmtime(path)) / 86400
        if age_days > 7:
            _logger_ens.info(
                "[GBM] Model %.1f gün önce eğitilmiş — candidate refresh planlanmalı (aktif kullanım devam ediyor)", age_days
            )
        return True
    except Exception as _e:
        _logger_ens.warning(f"[GBM] Model kontrol hatası: {_e}")
        return False


# Başlangıçta GBM sağlığını kontrol et ve override et
if _GBM_VAR and not _gbm_saglik_kontrol():
    _GBM_VAR = False



# Lig kalibrasyonu opsiyonel
try:
    from calibration.isotonic_calibrator import apply_probability_pipeline
    _KALIBRASYON_VAR = True
except ImportError:
    _KALIBRASYON_VAR = False

# Kadro/sakatlık verisi opsiyonel
try:
    from scrapers.kadro_verisi import kadro_etkisi_hesapla, kadro_lambda_duzenle
    _KADRO_VAR = True
except ImportError:
    _KADRO_VAR = False

# YENİ: Hava durumu opsiyonel
try:
    from scrapers.hava_durumu import hava_getir, hava_lambda_uygula, takim_sehri
    _HAVA_VAR = True
except ImportError:
    _HAVA_VAR = False

# YENİ: Yorgunluk feature opsiyonel
try:
    from features.feature_engine import (
        fatigue_index, elc_fatigue_carpani,
        YORGUNLUK_CARPANI,
    )
    _YORGUNLUK_VAR = True
except (ImportError, Exception):
    _YORGUNLUK_VAR = False

# YENİ: Taktiksel Hakem Opsiyonel (Modül eksikse atla)
_TAKTIK_VAR = False
_MOTIVASYON_VAR = False
_GOALS_ML_VAR = False
_CORNER_CARD_VAR = False

# YENİ: Advanced Stats Opsiyonel
try:
    from features.advanced_stats import (
        calculate_attack_strength,
        calculate_defensive_weakness,
        calculate_expected_tempo,
        calculate_lineup_strength
    )
    from tracking.drift_detector import apply_drift_filters
    from validation.confidence_filter import check_confidence
    _ADVANCED_STATS_VAR = True
except ImportError:
    _ADVANCED_STATS_VAR = False

# Global xG cache
_xg_db = None

def _xg_yukle_eger_gerekirse():
    global _xg_db
    if not _XG_MODULU_VAR:
        return {}
    if _xg_db is None:
        try:
            _xg_db = xg_yukle()
        except Exception:
            _xg_db = {}
    return _xg_db or {}



def model_birlestir(ev_takim_db, dep_takim_db=None,
                    istatistikler=None, elo_sonuclari=None,
                    lig_ortalamasi=None, lig_kodu="?",
                    ham_veri=None,
                    mac_tarihi: str = "",
                    ev_mac_tarihleri: list = None,
                    dep_mac_tarihleri: list = None,
                    hakem_agresifligi: float = 1.0,
                    sentiment_ev: float = 0.0,
                    sentiment_dep: float = 0.0,
                    kadro_etki: dict = None,
                    lig: str = None,
                    **kwargs):
    """
    Parametreler:
        ev_takim_db       : Ev takımı adı (veya doğrudan olasılık dict'i)
        dep_takim_db      : Deplasman takımı adı (veya doğrudan ELO olasılık dict'i)
        istatistikler     : Takım istatistikleri DB'si
        elo_sonuclari     : ELO puanları DB'si
        lig_ortalamasi    : Lig ortalamaları
        lig_kodu          : Lig kodu ('PL', 'PD' vs.)
    """
    if lig:
        lig_kodu = lig

    # Polimorfik destek: Eğer doğrudan olasılık sözlükleri verilmişse (test/blend modu)
    if isinstance(ev_takim_db, dict):
        p1 = ev_takim_db
        p2 = dep_takim_db if isinstance(dep_takim_db, dict) else {}
        p1_ev = p1.get("home_win", p1.get("ev", 0.33))
        p1_ber = p1.get("draw", p1.get("ber", 0.34))
        p1_dep = p1.get("away_win", p1.get("dep", 0.33))
        p2_ev = p2.get("home_win", p2.get("ev", p1_ev))
        p2_ber = p2.get("draw", p2.get("ber", p1_ber))
        p2_dep = p2.get("away_win", p2.get("dep", p1_dep))

        p_ev = 0.5 * p1_ev + 0.5 * p2_ev
        p_ber = 0.5 * p1_ber + 0.5 * p2_ber
        p_dep = 0.5 * p1_dep + 0.5 * p2_dep
        tot = p_ev + p_ber + p_dep
        if tot > 0:
            p_ev /= tot
            p_ber /= tot
            p_dep /= tot

        best = "1" if p_ev >= p_dep and p_ev >= p_ber else ("X" if p_ber >= p_dep else "2")
        return {
            "home_win": round(p_ev, 4),
            "draw": round(p_ber, 4),
            "away_win": round(p_dep, 4),
            "olasiliklar": {"ev": round(p_ev, 4), "ber": round(p_ber, 4), "dep": round(p_dep, 4)},
            "guven": 0.85,
            "tahmin_1x2": best
        }

    if istatistikler is None:
        istatistikler = {}
    ev_ist  = istatistikler.get(ev_takim_db)
    dep_ist = istatistikler.get(dep_takim_db)

    # ═══ FALLBACK: Sentetik stats (DB'de veri yoksa lig ort.) ═══
    _sentetik_kullanildi = False
    if ev_ist is None or dep_ist is None:
        try:
            from features.team_stats import sentetik_stats_uret
            if ev_ist is None:
                ev_ist = sentetik_stats_uret(ev_takim_db, lig_kodu, istatistikler)
                _sentetik_kullanildi = True
            if dep_ist is None:
                dep_ist = sentetik_stats_uret(dep_takim_db, lig_kodu, istatistikler)
                _sentetik_kullanildi = True
        except Exception:
            return None  # Fallback da başarısızsa çık

    ev_elo_b  = elo_sonuclari.get(ev_takim_db,  {"elo": 1500, "mac_sayisi": 0}).copy()
    dep_elo_b = elo_sonuclari.get(dep_takim_db, {"elo": 1500, "mac_sayisi": 0}).copy()

    # Kadro etkisi pure feature olarak kullanılacak, ELO'yu doğrudan çarpmayacağız
    ev_guc = 1.0
    dep_guc = 1.0
    if kadro_etki and kadro_etki.get("veri_var"):
        ev_guc  = kadro_etki.get("ev_guc", 1.0)
        dep_guc = kadro_etki.get("dep_guc", 1.0)

    lig_ort     = lig_ortalamasi.get(lig_kodu, {})
    lig_gol_ort = lig_ort.get("hucum", 1.35)

    # Katman 1: ELO
    elo_p = elo_olasilik(ev_elo_b["elo"], dep_elo_b["elo"])

    # xG verisini yükle + güvenilirlik skoru hesapla
    xg_db  = _xg_yukle_eger_gerekirse()
    ev_xg  = xg_ara(ev_takim_db,  xg_db) if xg_db else None
    dep_xg = xg_ara(dep_takim_db, xg_db) if xg_db else None

    # xG GÜVENİLİRLİK SKORU: Veri az/eksikse xG'yi devre dışı bırak
    # Son 3 maçta xG yoksa o takım için xG kullanma (ham gol istatistiğine geri dön)
    def _xg_guvenilir_mi(xg_dict: dict | None, min_oran: float = 0.5) -> bool:
        if not xg_dict:
            return False
        # Eğer Understat üzerinden tam sezon xG (mac sayısı belli) gelmişse güvenilirdir
        if xg_dict.get("mac", 0) >= 3:
            return True
            
        son_maclar = xg_dict.get("son_maclar", [])
        if len(son_maclar) < 2:
            return False
        veri_var = sum(1 for m in son_maclar[:3] if m.get("xg") is not None)
        return (veri_var / min(3, len(son_maclar))) >= min_oran

    ev_xg_guvenilir  = _xg_guvenilir_mi(ev_xg)
    dep_xg_guvenilir = _xg_guvenilir_mi(dep_xg)
    # Her iki takım da güvenilir xG'ye sahipse kullan, aksi hâlde None geç
    ev_xg_kullan  = ev_xg  if ev_xg_guvenilir  else None
    dep_xg_kullan = dep_xg if dep_xg_guvenilir else None

    # Katman 2: Poisson (xG + lig bazında rho destekli)
    poisson_p = poisson_tahmin(
        ev_ist, dep_ist, lig_ortalamasi, lig_kodu,
        ev_xg=ev_xg_kullan, dep_xg=dep_xg_kullan
    )

    lam_ev  = poisson_p["lam_ev"]
    lam_dep = poisson_p["lam_dep"]

    # Kadro etkisi lambda'larına doğrudan çarpılmıyor — feature olarak kullanılacak
    # (ensemble scoring'e giriyor, deterministic lambda manipülasyonu yok)

    # Katman 3: Form
    if ham_veri is not None:
        ev_form  = form_hesapla(ham_veri, ev_takim_db,  konum="ev",  lig_hucum_ort=lig_gol_ort)
        dep_form = form_hesapla(ham_veri, dep_takim_db, konum="dep", lig_hucum_ort=lig_gol_ort)
    else:
        from features.form import _notr_form
        ev_form = dep_form = _notr_form()

    lam_ev, lam_dep = form_lambda_uygula(lam_ev, lam_dep, ev_form, dep_form)

    # Katman 4: H2H
    h2h = h2h_analiz(istatistikler, ev_takim_db, dep_takim_db, lig_gol_ort)
    lam_ev, lam_dep = h2h_lambda_uygula(lam_ev, lam_dep, h2h)

    # Katman 4.5: Kadro/Sakatlık Etkisi (Sadece feature olarak alınacak)
    if _KADRO_VAR:
        try:
            kadro_etki = kadro_etkisi_hesapla(ev_takim_db, dep_takim_db, sessiz=True)
        except Exception:
            kadro_etki = {}
    else:
        kadro_etki = {}

    # ── YENİ Katman 4.6: Yorgunluk (Lambda Çarpanı YOK) ─────────────────────────────
    yorgunluk_ev  = {"carpan": 1.0, "skor": 0.0, "yorgun": False}
    yorgunluk_dep = {"carpan": 1.0, "skor": 0.0, "yorgun": False}

    if _YORGUNLUK_VAR and (ev_mac_tarihleri or dep_mac_tarihleri):
        try:
            ref_tarih = mac_tarihi[:10] if mac_tarihi else None
            
            if ev_mac_tarihleri:
                if lig_kodu == "ELC":
                    ev_carp = elc_fatigue_carpani(ev_mac_tarihleri, ref_tarih)
                    yorgunluk_ev = {"carpan": ev_carp, "skor": 0 if ev_carp == 1.0 else 0.7, "yorgun": ev_carp < 1.0}
                else:
                    yorgunluk_ev = fatigue_index(ev_mac_tarihleri, ref_tarih)

            if dep_mac_tarihleri:
                if lig_kodu == "ELC":
                    dep_carp = elc_fatigue_carpani(dep_mac_tarihleri, ref_tarih)
                    yorgunluk_dep = {"carpan": dep_carp, "skor": 0 if dep_carp == 1.0 else 0.7, "yorgun": dep_carp < 1.0}
                else:
                    yorgunluk_dep = fatigue_index(dep_mac_tarihleri, ref_tarih)
        except Exception:
            pass

    # ── YENİ Katman 4.7: Hava Durumu (Lambda Çarpanı YOK) ───────────────────────────
    hava_carpan = 1.0
    hava_bilgi  = {}

    if _HAVA_VAR and mac_tarihi:
        try:
            ev_sehir = takim_sehri(ev_takim_db)
            hava_bilgi = hava_getir(ev_sehir, mac_tarihi, sessiz=True)
            # Hava verileri alındı ancak lambda çarpılmadı
        except Exception:
            pass

    # ── Katman 4.8: Hakem & Taktiksel Etki ────────────────────────────────
    # Modül eksik — scrapers/hakem_verisi.py henüz entegre edilmedi.
    # Devreye alındığında: hakem_agresiflik * kart_egilimi → foul_factor
    _logger_ens.debug("[4.8] Hakem modülü pasif — modül entegre edilmedi")
        
    # ── YENİ Katman 4.9: Advanced Data Engineering (Çarpan iptal) ───────────
    ev_att = dep_att = ev_def = dep_def = tempo = 1.0
    if _ADVANCED_STATS_VAR:
        try:
            m_date = mac_tarihi[:10] if mac_tarihi else "2030-01-01"
            ev_att = calculate_attack_strength(ev_takim_db, m_date)
            dep_att = calculate_attack_strength(dep_takim_db, m_date)
            ev_def = calculate_defensive_weakness(ev_takim_db, m_date)
            dep_def = calculate_defensive_weakness(dep_takim_db, m_date)
            tempo = calculate_expected_tempo(ev_takim_db, dep_takim_db, m_date)
        except Exception:
            pass

    # ── Katman 5.0: Motivasyon Faktörü ────────────────────────────────────
    # Sezon sonu / şampiyonluk baskısı / düşme korkusu modülü planlandı.
    # Devreye alındığında: motivation_score → lam_ev/dep ağırlık düzeltmesi
    _logger_ens.debug("[5.0] Motivasyon modülü pasif — yakında entegre edilecek")

    poisson_p["lam_ev"]  = lam_ev
    poisson_p["lam_dep"] = lam_dep

    # Katman 5: Monte Carlo
    mc_p = monte_carlo_simule(lam_ev, lam_dep)

    # Adaptif ağırlıklar
    agirliklar = adaptif_agirlik_hesapla(
        ev_mac  = ev_elo_b["mac_sayisi"],
        dep_mac = dep_elo_b["mac_sayisi"],
        ev_elo  = ev_elo_b["elo"],
        dep_elo = dep_elo_b["elo"],
        lam_ev  = lam_ev,
        lam_dep = lam_dep,
        ev_form = ev_form,
        dep_form= dep_form,
        h2h     = h2h,
    )

    # ── YENİ: Goal Market Ağırlıklarının Ayrılması ──
    from config.settings import GOL_AGIRLIK_POISSON, GOL_AGIRLIK_ELO, GOL_AGIRLIK_MC, GOL_AGIRLIK_FORM, GOL_AGIRLIK_H2H
    gol_agirliklar = {
        "poisson": GOL_AGIRLIK_POISSON,
        "elo":     GOL_AGIRLIK_ELO,
        "mc":      GOL_AGIRLIK_MC,
        "form":    GOL_AGIRLIK_FORM,
        "h2h":     GOL_AGIRLIK_H2H,
    }

    # Beraberlik kalibrasyonu
    ber_kalibrasyon = beraberlik_kalibrasyon(
        ev_p    = elo_p["home_win"] * agirliklar["elo"] + poisson_p["home_win"] * agirliklar["poisson"],
        ber_p   = elo_p["draw"]     * agirliklar["elo"] + poisson_p["draw"]     * agirliklar["poisson"],
        dep_p   = elo_p["away_win"] * agirliklar["elo"] + poisson_p["away_win"] * agirliklar["poisson"],
        lam_ev  = lam_ev, lam_dep = lam_dep,
        ev_elo  = ev_elo_b["elo"],  dep_elo = dep_elo_b["elo"],
        h2h     = h2h,
        ber_agirlik = BER_KALIBRASYON_AGIRLIK,
    )

    # FAZ 3 birleştirici
    sonuc = model_birlestir_v3(
        elo_p=elo_p, poisson_p=poisson_p, mc_p=mc_p,
        ev_form=ev_form, dep_form=dep_form, h2h=h2h,
        agirliklar=agirliklar, ber_kalibrasyon=ber_kalibrasyon,
    )

    # ── Goal Market için de ayrı hibrit hesapla (Ağırlıklar GOL_AGIRLIK_X tabanlı) ──
    # Not: model_birlestir_v3 şimdilik 1X2 üretiyor, biz bts_p ve over25_p'yi de hibritleyeceğiz
    bts_p_hybrid = mc_p.get("bts_p", 0.5) * gol_agirliklar["mc"] + poisson_p.get("bts_p", 0.5) * gol_agirliklar["poisson"]
    # ELO formülü gol üretmez, bu yüzden kalanı poisson/mc'ye dağıt
    t_gol_ag = gol_agirliklar["poisson"] + gol_agirliklar["mc"]
    bts_p_son = bts_p_hybrid / t_gol_ag if t_gol_ag > 0 else poisson_p.get("bts_p", 0.5)
    
    over25_hybrid = mc_p.get("over25_p", 0.5) * gol_agirliklar["mc"] + poisson_p.get("over25_p", 0.5) * gol_agirliklar["poisson"]
    over25_p_son = over25_hybrid / t_gol_ag if t_gol_ag > 0 else poisson_p.get("over25_p", 0.5)


    # ═══ v3.0: PROBABILITY FLOORS/CEILINGS REMOVED ═══
    # AUDIT: Hard-coded floors (HOME_FLOOR=0.25, AWAY_FLOOR=0.20, DRAW_CEILING=0.25)
    # were creating artificial edge by compressing probabilities into unrealistic ranges.
    # The model should output honest probabilities; calibration handles the rest.
    # Bayesian shrinkage toward market prior is applied in main.py instead.
    t_n = sonuc["home_win"] + sonuc["draw"] + sonuc["away_win"]
    if t_n > 0:
        sonuc["home_win"] /= t_n
        sonuc["draw"] /= t_n
        sonuc["away_win"] /= t_n

    # v3.0: Calibration removed from ensemble — single calibration point in main.py
    # Double calibration (here + main.py pipeline) was causing overconfidence oscillation.
    sonuc["home_win"] = round(sonuc["home_win"], 4)
    sonuc["draw"]     = round(sonuc["draw"],     4)
    sonuc["away_win"] = round(sonuc["away_win"], 4)

    # ── Katman 4.9: Sentiment — DEVRE DIŞI ────────────────────────
    # Gerçek haber verisi olmadan sentiment=0.0 olduğu için bu blok
    # zaten hiç devreye girmiyordu. Gerçek haberler entegre edilene
    # kadar kapalı tutulacak → model olasılıklarına gürültü eklemez.
    # sentiment_ev / sentiment_dep parametreleri arayüzde kalmaya devam eder
    # (çağıran kod değişmesin) ama etkisi sıfır.
    # ──────────────────────────────────────────────────────────────

    # Katman 6: GBM
    gbm_sonuc = None
    if _GBM_VAR:
        try:
            gbm_sonuc = gbm_tahmin_yap(
                ev_ist=istatistikler.get(ev_takim_db, {}),
                dep_ist=istatistikler.get(dep_takim_db, {}),
                ev_elo=ev_elo_b["elo"], dep_elo=dep_elo_b["elo"],
                ev_form=ev_form, dep_form=dep_form,
                lig_kodu=lig_kodu, h2h_mac=h2h,
                ev_takim=ev_takim_db, dep_takim=dep_takim_db
            )
            if gbm_sonuc:
                # v3.0: EXPONENTIAL GBM DECAY (was linear)
                # Linear decay: 1% per day was too generous for stale models.
                # Exponential: half-life = 5 days, effectively zero at 15 days.
                import os as _os, time as _time, math as _math
                _gbm_path = _os.path.join("data", "gbm_model.pkl")
                if _os.path.exists(_gbm_path):
                    _model_yasi_gun = (_time.time() - _os.path.getmtime(_gbm_path)) / 86400
                else:
                    _model_yasi_gun = 0.0
                GBM_W = max(0.05, 0.45 * _math.exp(-_model_yasi_gun / 5.0))  # Exponential decay, half-life=5d
                ev_final  = sonuc["home_win"] * (1-GBM_W) + gbm_sonuc["ev_p"]  * GBM_W
                ber_final = sonuc["draw"]     * (1-GBM_W) + gbm_sonuc["ber_p"] * GBM_W
                dep_final = sonuc["away_win"] * (1-GBM_W) + gbm_sonuc["dep_p"] * GBM_W
                t = ev_final + ber_final + dep_final
                if t > 0:
                    sonuc["home_win"] = round(ev_final  / t, 4)
                    sonuc["draw"]     = round(ber_final / t, 4)
                    sonuc["away_win"] = round(dep_final / t, 4)
        except RuntimeError:
            raise
        except Exception:
            gbm_sonuc = None

    # 🔴 DENETİM (31.03.2026): Lig kalibrasyonu kaldırıldı.
    # Küçük örneklemlerle (bazen 5 maç) kalibrasyon güvenilmez.
    # apply_probability_pipeline() tek kalibrasyon kaynağı.
    # Eski kod:
    # global _kalibrasyon_cache
    # if _KALIBRASYON_VAR:
    #     [lig kalibrasyonu kodu]
    # ────────────────────────────────────────────────────────

    for ci_key in ("home_win_ci", "draw_ci", "away_win_ci"):
        if ci_key in sonuc:
            ci = sonuc[ci_key]
            sonuc[ci_key] = (round(ci[0]*1.05, 3), round(ci[1]*1.05, 3))

    mc_analitik_uyum = sonuc.get("konsensus", 1.0)
    elo_pois_fark    = abs(elo_p["home_win"] - poisson_p["home_win"])

    fv = feature_vektor(
        ev_takim_db, dep_takim_db, elo_p, poisson_p, mc_p,
        ev_form, dep_form, h2h, ev_elo_b["elo"], dep_elo_b["elo"], agirliklar
    )

    ev_ist_db  = istatistikler.get(ev_takim_db,  {})
    dep_ist_db = istatistikler.get(dep_takim_db, {})

    # ML ve Ek Modüller Eksik - Fallback
    mc_bts  = mc_p.get("bts_p", poisson_p.get("bts_p", 0.52))
    mc_o25  = mc_p.get("over25_p", poisson_p.get("over25_p", 0.48))
    bts_p_son = mc_bts
    over25_p_son = mc_o25
    
    # Drift Durumu Hesapla
    drift_flag = {"home_drift": False, "away_drift": False}
    if _ADVANCED_STATS_VAR:
        m_date = mac_tarihi[:10] if mac_tarihi else "2030-01-01"
        drift_flag = apply_drift_filters(ev_takim_db, dep_takim_db, m_date)
        
    # Güven Filtresi Hesapla (Market P yerine şimdilik 1/Odds eklenebilir. Burada proxy olarak elo'yu kullanıyoruz mock olarak)
    guven_filt = {"approved": True, "reason": "Clear"}
    if _ADVANCED_STATS_VAR:
        guven_filt = check_confidence(model_prob=sonuc["home_win"], market_prob=sonuc["home_win"], drift_flags=drift_flag, data_valid=True)

    return {
        **sonuc,
        "lam_ev": lam_ev, "lam_dep": lam_dep,
        "ev_elo": ev_elo_b["elo"],  "dep_elo": dep_elo_b["elo"],
        "ev_elo_mac": ev_elo_b["mac_sayisi"], "dep_elo_mac": dep_elo_b["mac_sayisi"],
        "elo_ev_p":     elo_p["home_win"],
        "elo_ber_p":    elo_p["draw"],
        "elo_dep_p":    elo_p["away_win"],
        "poisson_ev_p": poisson_p["home_win"],
        "poisson_ber_p":poisson_p["draw"],
        "poisson_dep_p":poisson_p["away_win"],
        "mc_ev_p":      mc_p["home_win"],
        "mc_ber_p":     mc_p["draw"],
        "mc_dep_p":     mc_p["away_win"],
        # KG Var ve Üst/Alt için ML destekli Monte Carlo hibridi
        "bts_p":        bts_p_son,
        "over15_p":     mc_p.get("over15_p", poisson_p.get("over15_p", 0)),
        "over25_p":     over25_p_son,
        "over35_p":     mc_p.get("over35_p", poisson_p.get("over35_p", 0)),
        "elo_pois_fark":     round(elo_pois_fark, 3),
        "yuksek_uyumsuzluk": elo_pois_fark > 0.30,
        "mc_analitik_uyum":  round(mc_analitik_uyum, 3),
        "fv_advanced": {
            "ev_att": ev_att, "dep_att": dep_att,
            "ev_def": ev_def, "dep_def": dep_def,
            "tempo": tempo
        },
        "feature_vektor":    fv,
        "xg_kullanildi":     poisson_p.get("xg_kullanildi", False),
        "en_olasi_skorlar":  poisson_p.get("en_olasi_skorlar", []),
        "iy_ev_p":   poisson_p.get("iy_ev_p",  0),
        "iy_ber_p":  poisson_p.get("iy_ber_p", 0),
        "iy_dep_p":  poisson_p.get("iy_dep_p", 0),
        "lam_iy_ev": poisson_p.get("lam_iy_ev", 0),
        "lam_iy_dep": poisson_p.get("lam_iy_dep", 0),
        "ev_clean_sheet":  ev_ist_db.get("ev_clean_sheet_oran",  0),
        "dep_clean_sheet": dep_ist_db.get("dep_clean_sheet_oran", 0),
        "ev_lig_sira":      ev_ist_db.get("lig_sira", 0),
        "dep_lig_sira":     dep_ist_db.get("lig_sira", 0),
        "ev_lig_sira_oran": ev_ist_db.get("lig_sira_oran", 0.5),
        "dep_lig_sira_oran":dep_ist_db.get("lig_sira_oran", 0.5),
        "ev_puan":          ev_ist_db.get("puan", 0),
        "dep_puan":         dep_ist_db.get("puan", 0),
        # Kadro/sakatlık
        "kadro_ev_guc":     kadro_etki.get("ev_guc",   1.0),
        "kadro_dep_guc":    kadro_etki.get("dep_guc",  1.0),
        "kadro_ev_eksik":   kadro_etki.get("ev_eksik", ""),
        "kadro_dep_eksik":  kadro_etki.get("dep_eksik",""),
        "kadro_veri_var":   kadro_etki.get("veri_var", False),
        # YENİ: Yorgunluk
        "ev_yorgunluk_skor":   yorgunluk_ev.get("skor",  0.0),
        "dep_yorgunluk_skor":  yorgunluk_dep.get("skor", 0.0),
        "ev_yorgun":           yorgunluk_ev.get("yorgun",  False),
        "dep_yorgun":          yorgunluk_dep.get("yorgun", False),
        "ev_yorgunluk_carpan": yorgunluk_ev.get("carpan",  1.0),
        "dep_yorgunluk_carpan":yorgunluk_dep.get("carpan", 1.0),
        # YENİ: Sentiment
        "sentiment_ev":     sentiment_ev,
        "sentiment_dep":    sentiment_dep,
        # YENİ: Hava durumu
        "hava_carpan":     hava_carpan,
        "hava_yagis_mm":   hava_bilgi.get("yagis_mm",   0.0),
        "hava_sicaklik_c": hava_bilgi.get("sicaklik_c", 15.0),
        "hava_kaynak":     hava_bilgi.get("kaynak",     "yok"),
        # Gatekeeper / Güven Filtresi
        "onay_durumu":     guven_filt["approved"],
        "red_sebebi":      guven_filt["reason"],
        # Lig bazında rho (debug)
        "lig_rho":         poisson_p.get("lig_rho", -0.10),
    }