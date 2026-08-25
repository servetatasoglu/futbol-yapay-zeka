import json
import logging
import os
import numpy as np
from datetime import datetime

# Asıl pipeline importları
from data.matches import veri_yukle
from data.matcher import eslestir
from features.team_stats import istatistik_hesapla, lig_ortalamasi_hesapla
from features.elo import elo_hesapla
from model.ensemble import model_birlestir
from calibration.calibration import apply_probability_pipeline

from data.live_radar import LiveRadarEngine
from thefuzz import process
from execution.microstructure import MicrostructureSimulator
from tracking.learner import dinamik_stake_hesapla
from execution.validator import ExecutionValidator

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger("run_radar")

def run_advisory_radar():
    logger.info("📡 Live Advisory Radar (Real ML Engine) Başlatılıyor...")
    
    # 1. VERİTABANI YÜKLEMESİ
    logger.info("Veritabanı ve İstatistikler Yükleniyor... (Bu işlem birkaç saniye sürebilir)")
    try:
        raw_matches = veri_yukle()
        stats = istatistik_hesapla()
        league_avgs = lig_ortalamasi_hesapla(stats)
        elo_db = elo_hesapla(raw_matches)
        db_takimlar = list(stats.keys()) if stats else []
    except Exception as e:
        logger.error(f"Veritabanı yüklenirken hata oluştu: {e}")
        return

    # 2. CANLI MAÇLARI ÇEK
    radar = LiveRadarEngine()
    live_matches = radar.fetch_live_matches("pinnacle")
    
    if not live_matches:
        logger.warning("Pinnacle'dan canlı maç bulunamadı. Lütfen API kotasını veya tarihi kontrol edin.")
        with open("live_signals.json", "w") as f:
            json.dump([], f)
        return
        
    signals_found = []
    
    # 3. ML PREDICTION PIPELINE
    logger.info(f"{len(live_matches)} Canlı Maç Yapay Zeka Motorunda Değerlendiriliyor...")
    for match in live_matches:
        ev_ham = match["ev"]
        dep_ham = match["dep"]
        
        # Fuzzy Match ile İstatistik Veritabanından Takım Bul
        ev_takim = eslestir(ev_ham, db_takimlar)
        dep_takim = eslestir(dep_ham, db_takimlar)
        
        # Takım bulunamazsa atla
        if not ev_takim or not dep_takim or ev_takim == "SKIPPED_NO_DATA" or dep_takim == "SKIPPED_NO_DATA":
            logger.debug(f"Veri bulunamadı veya eşleşmedi: {ev_ham} vs {dep_ham}")
            continue
            
        try:
            # Gerçek Prediction Engine Çalıştır
            sonuc = model_birlestir(
                ev_takim_db=ev_takim, dep_takim_db=dep_takim,
                istatistikler=stats, elo_sonuclari=elo_db,
                lig_ortalamasi=league_avgs, lig_kodu=match.get("lig", "?"),
                mac_tarihi=match.get("date", "")
            )
        except Exception as e:
            logger.debug(f"{ev_ham} vs {dep_ham}: model hatası → {e}")
            continue

        if not sonuc:
            continue

        # Kalibrasyon (Isotonic vb.)
        raw_preds = np.array([sonuc.get("home_win", 0.33), sonuc.get("draw", 0.28), sonuc.get("away_win", 0.34)])
        try:
            calib_res = apply_probability_pipeline(raw_preds)
            probs = calib_res["probs"]
        except:
            probs = raw_preds

        calibrated_preds = {
            "Ev Sahibi Kazanır": float(probs[0]),
            "Beraberlik": float(probs[1]),
            "Deplasman Kazanır": float(probs[2])
        }

        # 4. VALUE DETECTION & XAI REASONING (WITH EXECUTION VALIDATOR)
        for tahmin_tipi, model_p in calibrated_preds.items():
            oran = match["odds_current"].get(tahmin_tipi, 1.0)
            if oran <= 1.05:
                continue
                
            # Pipeline: Fake Edge -> Latency -> Shop -> Filter -> Bankroll
            val_result = ExecutionValidator.verify_signal(
                match=match,
                tahmin_tipi=tahmin_tipi,
                model_prob=model_p,
                original_odds=oran,
                ci_width=0.10 # Sabit simüle edildi
            )
            
            if not val_result or val_result["status"] == "REJECTED":
                # Strict mode rejected the signal
                continue
                
            # Approved or Requires Human Confirmation
            edge_pct = val_result["edge_final"] * 100
            
            # XAI Reasoning Üretimi
            ev_elo = sonuc.get('ev_elo', 1500)
            dep_elo = sonuc.get('dep_elo', 1500)
            elo_fark = ev_elo - dep_elo
            
            lam_ev = sonuc.get('lam_ev', 1.0)
            lam_dep = sonuc.get('lam_dep', 1.0)

            reason = f"Piyasa Taraması: {val_result['selected_bookmaker']}. "
            if val_result['fake_edge_score'] > 0.2:
                reason += f"⚠️ Sahte Fırsat Şüphesi: {val_result['fake_edge_score']:.2f}. "
            
            if tahmin_tipi == "Ev Sahibi Kazanır":
                reason += f"Elo Farkı: {elo_fark:+.0f}. xG: {lam_ev:.2f} > {lam_dep:.2f}."
            elif tahmin_tipi == "Deplasman Kazanır":
                reason += f"Elo Farkı: {-elo_fark:+.0f}. xG: {lam_dep:.2f} > {lam_ev:.2f}."
            else:
                reason += f"Dengeli (Elo: {elo_fark:+.0f}). xG: {lam_ev:.1f}-{lam_dep:.1f}."

            if val_result["status"] == "MANUEL ONAY BEKLİYOR":
                reason = "🔴 MANUEL İNCELEME ŞART! " + reason

            signals_found.append({
                "date": match["date"],
                "lig": match["lig"],
                "ev": match["ev"],
                "dep": match["dep"],
                "selection": tahmin_tipi,
                "target_odds": val_result["target_odds"],
                "model_prob": round(model_p * 100, 1),
                "edge_pct": round(edge_pct, 1),
                "edge_raw_pct": round(val_result["edge_raw"] * 100, 1),
                "fake_edge_score": val_result["fake_edge_score"],
                "latency_seconds": val_result["latency_seconds"],
                "selected_bookmaker": val_result["selected_bookmaker"],
                "execution_quality": {}, 
                "recommended_stake_pct": val_result["recommended_stake_pct"],
                "status": val_result["status"],
                "reasoning": reason
            })

    # Sort by Edge Pct
    signals_found = sorted(signals_found, key=lambda x: x["edge_pct"], reverse=True)
    
    out_path = os.path.join(os.path.dirname(__file__), "live_signals.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(signals_found, f, ensure_ascii=False, indent=2)
        
    logger.info(f"✅ Gerçek Zeka (Ensemble ML) Taraması Tamamlandı! {len(signals_found)} Adet Gerçek Fırsat Bulundu.")
    logger.info(f"💾 Dosya Kaydedildi: {out_path}")

if __name__ == "__main__":
    run_advisory_radar()
