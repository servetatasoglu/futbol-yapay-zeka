# tracking/learner.py
"""
Self-Learning Betting Engine — CLOSED-LOOP SYSTEM
══════════════════════════════════════════════════════
Pipeline: Predict → Bet → Result → CLV → Weight Update → Better Predictions

Bu modül sistemin BEYNİDİR:
  1. CLV performansını analiz eder
  2. Lig bazında ROI takibi yapar
  3. Model ağırlıklarını CLV'ye göre günceller
  4. Dinamik stake hesaplar
  5. Zayıf ligleri/bahis tiplerini otomatik filtreler
"""

import os
import json
import logging
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger("learner")

LEARNER_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "learner_db.json")


def _yukle() -> dict:
    if os.path.exists(LEARNER_DB_PATH):
        try:
            with open(LEARNER_DB_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "lig_performans": {},
        "tier_performans": {},
        "tahmin_tipi_performans": {},
        "model_agirlik_gecmisi": [],
        "clv_feedback": {
            "toplam_bahis": 0,
            "clv_pozitif": 0,
            "clv_ortalama": 0.0,
            "son_guncelleme": None,
        },
        "ogrenme_parametreleri": {
            "elo_guven": 1.0,
            "poisson_guven": 1.0,
            "form_guven": 1.0,
            "global_edge_carpan": 1.0,
            "advanced_stats_weight": 1.0,
            "lineup_impact_weight": 1.0,
        },
    }


def _kaydet(db: dict):
    os.makedirs(os.path.dirname(LEARNER_DB_PATH), exist_ok=True)
    with open(LEARNER_DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════
#  1. CLV FEEDBACK LOOP — Model güvenini CLV'ye göre güncelle
# ═══════════════════════════════════════════════════════════════════════

def clv_feedback_guncelle(clv_veri: list) -> dict:
    """
    CLV verilerinden model güven parametrelerini güncelle.
    
    Args:
        clv_veri: [{"clv": float, "tier": str, "lig": str, "tahmin": str, 
                     "model_p": float, "market_p": float, "sonuc": str}, ...]
    
    Returns:
        Güncellenmiş öğrenme parametreleri
    """
    db = _yukle()
    
    if not clv_veri:
        return db.get("ogrenme_parametreleri", {})
    
    # CLV dağılımını analiz et
    clv_values = [v["clv"] for v in clv_veri if v.get("clv") is not None]
    if not clv_values:
        return db.get("ogrenme_parametreleri", {})
    
    ort_clv = sum(clv_values) / len(clv_values)
    pozitif_oran = sum(1 for c in clv_values if c > 0) / len(clv_values)
    
    # ── Global Edge Çarpanı ──────────────────────────────────
    # CLV sürekli negatifse → model çok iddialı → edge'i aşağı çek
    # CLV pozitifse → model doğru yönde → güveni koru
    if len(clv_values) >= 10:
        if ort_clv < -0.02:
            # Model piyasadan kötü → edge eşiklerini yükselt
            edge_carpan = max(0.7, 1.0 + ort_clv * 5)  # CLV=-0.04 → carpan=0.80
        elif ort_clv > 0.01:
            # Model piyasadan iyi → edge eşiklerini az düşür (ama dikkatli)
            edge_carpan = min(1.15, 1.0 + ort_clv * 2)  # CLV=+0.03 → carpan=1.06
        else:
            edge_carpan = 1.0
    else:
        edge_carpan = 1.0  # Yetersiz veri → nötr
    
    # ── Tier Bazında CLV ─────────────────────────────────────
    tier_clv = defaultdict(list)
    for v in clv_veri:
        if v.get("clv") is not None:
            tier_clv[v.get("tier", "NO_SHARP")].append(v["clv"])
    
    tier_perf = {}
    for tier, vals in tier_clv.items():
        ort = sum(vals) / len(vals) if vals else 0
        tier_perf[tier] = {
            "ort_clv": round(ort, 4),
            "n": len(vals),
            "pozitif_oran": round(sum(1 for c in vals if c > 0) / max(1, len(vals)), 3),
        }
    
    # ── Lig Bazında Performans ───────────────────────────────
    lig_clv = defaultdict(list)
    for v in clv_veri:
        if v.get("clv") is not None:
            lig_clv[v.get("lig", "?")].append(v["clv"])
    
    lig_perf = {}
    for lig, vals in lig_clv.items():
        ort = sum(vals) / len(vals) if vals else 0
        lig_perf[lig] = {
            "ort_clv": round(ort, 4),
            "n": len(vals),
            "pozitif_oran": round(sum(1 for c in vals if c > 0) / max(1, len(vals)), 3),
            "durum": "KARLI" if ort > 0.005 else ("ZARARLI" if ort < -0.01 else "NOTR"),
        }
    
    # ── Tahmin Tipi Performans ───────────────────────────────
    tip_clv = defaultdict(list)
    for v in clv_veri:
        if v.get("clv") is not None:
            tip_clv[v.get("tahmin", "?")].append(v["clv"])
    
    tip_perf = {}
    for tip, vals in tip_clv.items():
        ort = sum(vals) / len(vals) if vals else 0
        tip_perf[tip] = {
            "ort_clv": round(ort, 4),
            "n": len(vals),
            "durum": "KARLI" if ort > 0 else "ZARARLI",
        }
    
    # Veritabanını güncelle
    db["lig_performans"] = lig_perf
    db["tier_performans"] = tier_perf
    db["tahmin_tipi_performans"] = tip_perf
    db["clv_feedback"] = {
        "toplam_bahis": len(clv_values),
        "clv_pozitif": sum(1 for c in clv_values if c > 0),
        "clv_ortalama": round(ort_clv, 4),
        "pozitif_oran": round(pozitif_oran, 3),
        "son_guncelleme": datetime.now().isoformat(),
    }
    db["ogrenme_parametreleri"]["global_edge_carpan"] = round(edge_carpan, 3)
    
    # ═══ BİREYSEL MODEL AĞIRLIK GÜNCELLEMESİ ═══
    # CLV verilerinden hangi modelin daha isabetli olduğunu çıkar
    if len(clv_values) >= 20:
        # ELO ve Poisson tahminleri CLV ile korelasyonunu kontrol et
        elo_sapma = []
        poisson_sapma = []
        for v in clv_veri:
            if v.get("clv") is None:
                continue
            # Model tahminlerinden ELO ve Poisson ayrı ayrı saklanmıyorsa
            # CLV pozitifliğini genel güven ölçüsü olarak kullan
            clv_val = v["clv"]
            model_p = v.get("model_p", 0)
            market_p = v.get("market_p", 0)
            if model_p > 0 and market_p > 0:
                # Fazla iddialı mı? (model >> market ama CLV negatif)
                if model_p > market_p + 0.05 and clv_val < -0.01:
                    elo_sapma.append(-1)     # Model aşırı iddialı → ELO muhtemelen saptı
                    poisson_sapma.append(0)
                elif clv_val > 0.01:
                    elo_sapma.append(1)
                    poisson_sapma.append(1)
                else:
                    elo_sapma.append(0)
                    poisson_sapma.append(0)
        
        if elo_sapma:
            elo_skor = sum(elo_sapma) / len(elo_sapma)  # -1 ile +1 arası
            # Skor negatifse ELO güveni düşür, pozitifse artır
            elo_guven = max(0.8, min(1.2, 1.0 + elo_skor * 0.15))
            db["ogrenme_parametreleri"]["elo_guven"] = round(elo_guven, 3)
        
        if poisson_sapma:
            pois_skor = sum(poisson_sapma) / len(poisson_sapma)
            pois_guven = max(0.8, min(1.2, 1.0 + pois_skor * 0.15))
            db["ogrenme_parametreleri"]["poisson_guven"] = round(pois_guven, 3)

        # YENI: Advanced Stats CLV Feedback
        if pozitif_oran > 0.55:
            # If we are beating the market well, our new advanced stats & lineup weights are working
            db["ogrenme_parametreleri"]["advanced_stats_weight"] = round(min(1.2, db["ogrenme_parametreleri"].get("advanced_stats_weight", 1.0) * 1.02), 3)
            db["ogrenme_parametreleri"]["lineup_impact_weight"] = round(min(1.2, db["ogrenme_parametreleri"].get("lineup_impact_weight", 1.0) * 1.02), 3)
        elif pozitif_oran < 0.45:
            db["ogrenme_parametreleri"]["advanced_stats_weight"] = round(max(0.8, db["ogrenme_parametreleri"].get("advanced_stats_weight", 1.0) * 0.98), 3)
            db["ogrenme_parametreleri"]["lineup_impact_weight"] = round(max(0.8, db["ogrenme_parametreleri"].get("lineup_impact_weight", 1.0) * 0.98), 3)


    
    _kaydet(db)
    logger.info(f"  🧠 CLV Feedback: ort={ort_clv*100:.2f}% | pozitif={pozitif_oran*100:.0f}% | "
                f"edge_carpan={edge_carpan:.3f} | "
                f"elo_g={db['ogrenme_parametreleri'].get('elo_guven',1.0):.2f} | "
                f"pois_g={db['ogrenme_parametreleri'].get('poisson_guven',1.0):.2f}")
    
    return db["ogrenme_parametreleri"]


# ═══════════════════════════════════════════════════════════════════════
#  2. DİNAMİK STAKE HESAPLAMA
# ═══════════════════════════════════════════════════════════════════════

def dinamik_stake_hesapla(
    base_kelly: float,
    edge: float,
    confidence: float,
    tier: str,
    veri_kaynak: str,
    lig: str,
) -> dict:
    """
    Stake = f(Kelly, edge, CLV_history, confidence, data_quality, league_perf)
    
    Returns:
        {"final_stake": float, "carpanlar": dict, "aciklama": str}
    """
    db = _yukle()
    params = db.get("ogrenme_parametreleri", {})
    lig_perf = db.get("lig_performans", {})
    
    # ── 1. Tier çarpanı ──────────────────────────────────────
    tier_c = {"ELITE": 1.5, "STRONG": 1.2, "WEAK": 1.0, "NO_SHARP": 0.7}.get(tier, 0.7)
    
    # ── 2. Veri kalitesi çarpanı ─────────────────────────────
    veri_c = {"TAM": 1.0, "KARMA": 0.4, "SENTETİK": 0.0}.get(veri_kaynak, 0.5)
    
    # ── 3. CLV-öğrenilmiş global çarpan ──────────────────────
    clv_c = params.get("global_edge_carpan", 1.0)
    
    # ── 4. Lig performans çarpanı ────────────────────────────
    lig_info = lig_perf.get(lig, {})
    lig_c = 1.0
    if lig_info:
        durum = lig_info.get("durum", "NOTR")
        if durum == "KARLI" and lig_info.get("n", 0) >= 5:
            lig_c = 1.15  # Kârlı lig → biraz daha agresif
        elif durum == "ZARARLI" and lig_info.get("n", 0) >= 5:
            lig_c = 0.6   # Zararlı lig → çok temkinli
    
    # ── 5. Edge büyüklüğü çarpanı ────────────────────────────
    edge_c = 1.0
    if edge > 0.15:
        edge_c = 0.8  # Çok yüksek edge → şüpheli, küçült
    elif edge > 0.08:
        edge_c = 1.1  # Orta edge → sağlıklı
    elif edge < 0.04:
        edge_c = 0.9  # Düşük edge → temkinli
    
    # ── 6. Drawdown çarpanı (DÜZELTME 7) ─────────────────────
    # Kasa eriyorsa Kelly otomatik küçülür
    drawdown_c = 1.0
    clv_fb = db.get("clv_feedback", {})
    clv_n = clv_fb.get("toplam_bahis", 0)
    clv_ort = clv_fb.get("clv_ortalama", 0)
    if clv_n >= 10:
        if clv_ort < -0.03:
            drawdown_c = 0.5   # Ağır kayıp → yarı Kelly
        elif clv_ort < -0.01:
            drawdown_c = 0.75  # Hafif kayıp → %75 Kelly
        elif clv_ort > 0.02:
            drawdown_c = 1.1   # İyi performans → hafif artır
    
    # ── Final stake ──────────────────────────────────────────
    final = base_kelly * tier_c * veri_c * clv_c * lig_c * edge_c * drawdown_c
    final = round(min(0.025, max(0.003, final)), 4)
    
    aciklama = []
    if tier_c != 1.0: aciklama.append(f"tier:{tier_c:.1f}")
    if veri_c != 1.0: aciklama.append(f"veri:{veri_c:.1f}")
    if clv_c != 1.0: aciklama.append(f"clv:{clv_c:.2f}")
    if lig_c != 1.0: aciklama.append(f"lig:{lig_c:.1f}")
    if edge_c != 1.0: aciklama.append(f"edge:{edge_c:.1f}")
    if drawdown_c != 1.0: aciklama.append(f"dd:{drawdown_c:.2f}")
    
    return {
        "final_stake": final,
        "carpanlar": {
            "tier": tier_c, "veri": veri_c, "clv": clv_c,
            "lig": lig_c, "edge": edge_c,
        },
        "aciklama": " × ".join(aciklama) if aciklama else "standart",
    }


# ═══════════════════════════════════════════════════════════════════════
#  3. ZAYIF LİG/TAHMİN FİLTRESİ — Öğrenilen performansa göre
# ═══════════════════════════════════════════════════════════════════════

def lig_filtre_kontrol(lig: str, tahmin: str) -> dict:
    """
    CLV geçmişine göre bir lig/tahmin kombinasyonunun bahis yapılıp yapılmayacağını belirle.
    
    Returns:
        {"izin": True/False, "sebep": str, "esik_carpan": float}
    """
    db = _yukle()
    lig_perf = db.get("lig_performans", {})
    tip_perf = db.get("tahmin_tipi_performans", {})
    
    lig_info = lig_perf.get(lig, {})
    tip_info = tip_perf.get(tahmin, {})
    
    # Yeterli veri yoksa → izin ver (öğrenme aşaması)
    if not lig_info or lig_info.get("n", 0) < 5:
        return {"izin": True, "sebep": "yeni_lig", "esik_carpan": 1.0}
    
    # Lig sürekli zarardaysa ve yeterli veri varsa → edge eşiğini yükselt
    if lig_info.get("durum") == "ZARARLI" and lig_info.get("n", 0) >= 10:
        if lig_info.get("ort_clv", 0) < -0.03:
            return {"izin": False, "sebep": f"lig_zararli(CLV:{lig_info['ort_clv']*100:.1f}%)", "esik_carpan": 0}
        return {"izin": True, "sebep": "lig_riskli", "esik_carpan": 1.5}
    
    # Tahmin tipi zarardaysa → eşik artır
    if tip_info and tip_info.get("n", 0) >= 10 and tip_info.get("durum") == "ZARARLI":
        return {"izin": True, "sebep": "tahmin_tipi_riskli", "esik_carpan": 1.3}
    
    # Lig kârlıysa → eşik düşür (daha fazla fırsat)
    if lig_info.get("durum") == "KARLI" and lig_info.get("n", 0) >= 10:
        return {"izin": True, "sebep": "lig_karli", "esik_carpan": 0.85}
    
    return {"izin": True, "sebep": "standart", "esik_carpan": 1.0}


# ═══════════════════════════════════════════════════════════════════════
#  4. MODEL AĞIRLIK GÜNCELLEMESİ — CLV performansına göre
# ═══════════════════════════════════════════════════════════════════════

def model_agirlik_onerisi() -> dict:
    """
    CLV verisine dayanarak ELO/Poisson/Form ağırlık önerisi üret.
    
    Bu fonksiyon adaptif_agirlik_hesapla()'ya feed edilir.
    Yeterli veri yoksa nötr değerler döndürür.
    
    Returns:
        {"elo_guven": float, "poisson_guven": float, "form_guven": float}
    """
    db = _yukle()
    params = db.get("ogrenme_parametreleri", {})
    clv_fb = db.get("clv_feedback", {})
    
    # Yeterli veri yoksa nötr
    if clv_fb.get("toplam_bahis", 0) < 20:
        return {"elo_guven": 1.0, "poisson_guven": 1.0, "form_guven": 1.0}
    
    return {
        "elo_guven": params.get("elo_guven", 1.0),
        "poisson_guven": params.get("poisson_guven", 1.0),
        "form_guven": params.get("form_guven", 1.0),
    }


# ═══════════════════════════════════════════════════════════════════════
#  5. PERFORMANS RAPORU
# ═══════════════════════════════════════════════════════════════════════

def performans_raporu() -> str:
    """Öğrenme sisteminin tam performans raporunu döndür."""
    db = _yukle()
    clv = db.get("clv_feedback", {})
    params = db.get("ogrenme_parametreleri", {})
    lig_p = db.get("lig_performans", {})
    tier_p = db.get("tier_performans", {})
    tip_p = db.get("tahmin_tipi_performans", {})
    
    lines = []
    lines.append("=" * 70)
    lines.append("  🧠 SELF-LEARNING ENGINE — PERFORMANS RAPORU")
    lines.append("=" * 70)
    
    if clv.get("toplam_bahis", 0) > 0:
        lines.append(f"  CLV: ort={clv.get('clv_ortalama',0)*100:.2f}% | "
                     f"pozitif={clv.get('pozitif_oran',0)*100:.0f}% | "
                     f"n={clv.get('toplam_bahis',0)}")
        lines.append(f"  Edge çarpanı: {params.get('global_edge_carpan', 1.0):.3f}")
    else:
        lines.append("  ⏳ Henüz CLV verisi yok — öğrenme aşaması")
    
    if lig_p:
        lines.append("\n  ── Lig Performansı ──")
        for lig, info in sorted(lig_p.items(), key=lambda x: x[1].get("ort_clv", 0), reverse=True):
            emoji = "✅" if info.get("durum") == "KARLI" else ("❌" if info.get("durum") == "ZARARLI" else "➖")
            lines.append(f"    {emoji} {lig:6s} CLV:{info.get('ort_clv',0)*100:+6.2f}% "
                        f"({info.get('n',0)} bahis) [{info.get('durum','?')}]")
    
    if tier_p:
        lines.append("\n  ── Tier Performansı ──")
        for tier in ["ELITE", "STRONG", "WEAK", "NO_SHARP"]:
            info = tier_p.get(tier, {})
            if info:
                lines.append(f"    {tier:10s} CLV:{info.get('ort_clv',0)*100:+6.2f}% ({info.get('n',0)} bahis)")
    
    if tip_p:
        lines.append("\n  ── Tahmin Tipi ──")
        for tip, info in tip_p.items():
            emoji = "✅" if info.get("durum") == "KARLI" else "❌"
            lines.append(f"    {emoji} {tip:22s} CLV:{info.get('ort_clv',0)*100:+6.2f}% ({info.get('n',0)})")
    
    lines.append("=" * 70)
    return "\n".join(lines)
