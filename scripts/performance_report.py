"""
PERFORMANCE REPORT — Kantitatif Performans Analiz Sistemi
═══════════════════════════════════════════════════════════
Metrikleri:
  • Toplam bahis, Win/Loss oranı
  • ROI (Return on Investment)
  • CLV performansı
  • Lig bazlı kırılım
  • Model vs Market karşılaştırması
  • Veri tazeliği durumu

Çalıştırma: python scripts/performance_report.py
"""

import os
import json
import logging
from datetime import datetime
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
logger = logging.getLogger("performance_report")

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
CLV_LOG_PATH = os.path.join(BASE_DIR, "data", "clv_bet_log.json")
MACLAR_PATH = os.path.join(BASE_DIR, "data", "maclar.json")
ODDS_CACHE_PATH = os.path.join(BASE_DIR, "data", "odds_cache.json")
REPORT_OUTPUT = os.path.join(BASE_DIR, "data", "performance_report.json")


def _yukle() -> dict:
    if os.path.exists(CLV_LOG_PATH):
        try:
            with open(CLV_LOG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"bahisler": [], "gunluk_raporlar": []}


def generate_report() -> dict:
    """
    clv_bet_log.json'dan tam performans raporu üretir.
    """
    db = _yukle()
    bahisler = db.get("bahisler", [])

    if not bahisler:
        return {"error": "Bahis bulunamadı"}

    # ═══ TEMEL METRİKLER ═══
    toplam = len(bahisler)
    sonuclu = [b for b in bahisler if b.get("sonuc") is not None]
    bekleyen = toplam - len(sonuclu)
    kazanan = [b for b in sonuclu if b.get("sonuc") == "kazandi"]
    kaybeden = [b for b in sonuclu if b.get("sonuc") == "kaybetti"]

    win_rate = len(kazanan) / len(sonuclu) if sonuclu else 0

    # ═══ ROI HESABI & BOOTSTRAP GÜVEN ARALIĞI ═══
    toplam_kar = sum(b.get("profit", 0) for b in sonuclu)
    roi = (toplam_kar / len(sonuclu)) * 100 if sonuclu else 0
    
    boot_lower, boot_upper = 0.0, 0.0
    is_significant = len(sonuclu) >= 250
    
    if len(sonuclu) >= 10:
        import numpy as np
        profits = np.array([b.get("profit", 0) for b in sonuclu])
        n_iterations = 10000
        n_size = len(profits)
        boot_rois = []
        for _ in range(n_iterations):
            sample = np.random.choice(profits, size=n_size, replace=True)
            boot_rois.append((np.sum(sample) / n_size) * 100)
        boot_lower = float(np.percentile(boot_rois, 2.5))
        boot_upper = float(np.percentile(boot_rois, 97.5))

    # ═══ ORTALAMA ODDS ═══
    oranlar = [b.get("oran_alinma", b.get("oran", 0)) for b in bahisler if b.get("oran_alinma", b.get("oran", 0)) > 1.0]
    avg_odds = sum(oranlar) / len(oranlar) if oranlar else 0

    # ═══ EDGE ANALİZİ ═══
    edges = [b.get("edge", 0) for b in bahisler if b.get("edge", 0) > 0]
    avg_edge = sum(edges) / len(edges) if edges else 0

    # ═══ CLV METRİKLERİ ═══
    clv_list = [b.get("clv", 0) for b in bahisler if b.get("clv") is not None and isinstance(b.get("clv"), (int, float))]
    clv_avg = sum(clv_list) / len(clv_list) if clv_list else None
    clv_positive_pct = sum(1 for c in clv_list if c > 0) / len(clv_list) if clv_list else None

    # ═══ LİG BAZLI KIRILIM ═══
    lig_stats = defaultdict(lambda: {
        "toplam": 0, "kazanan": 0, "kaybeden": 0, "bekleyen": 0,
        "toplam_kar": 0.0, "edges": [], "oranlar": [],
    })

    for b in bahisler:
        lig = b.get("lig", "?")
        lig_stats[lig]["toplam"] += 1
        lig_stats[lig]["edges"].append(b.get("edge", 0))
        oran = b.get("oran_alinma", b.get("oran", 0))
        if oran > 1.0:
            lig_stats[lig]["oranlar"].append(oran)

        if b.get("sonuc") == "kazandi":
            lig_stats[lig]["kazanan"] += 1
            lig_stats[lig]["toplam_kar"] += b.get("profit", 0)
        elif b.get("sonuc") == "kaybetti":
            lig_stats[lig]["kaybeden"] += 1
            lig_stats[lig]["toplam_kar"] += b.get("profit", 0)
        else:
            lig_stats[lig]["bekleyen"] += 1

    # Lig bazlı finalize
    lig_rapor = {}
    for lig, s in lig_stats.items():
        gerceklesen = s["kazanan"] + s["kaybeden"]
        lig_rapor[lig] = {
            "toplam": s["toplam"],
            "kazanan": s["kazanan"],
            "kaybeden": s["kaybeden"],
            "bekleyen": s["bekleyen"],
            "win_rate": round(s["kazanan"] / gerceklesen, 4) if gerceklesen > 0 else None,
            "roi": round((s["toplam_kar"] / gerceklesen) * 100, 2) if gerceklesen > 0 else None,
            "avg_edge": round(sum(s["edges"]) / len(s["edges"]) * 100, 2) if s["edges"] else 0,
            "avg_odds": round(sum(s["oranlar"]) / len(s["oranlar"]), 2) if s["oranlar"] else 0,
        }

    # En iyi ve en kötü ligler (ROI bazlı)
    lig_roi_sirali = sorted(
        [(lig, d) for lig, d in lig_rapor.items() if d.get("roi") is not None],
        key=lambda x: x[1]["roi"], reverse=True
    )
    en_iyi_ligler = [(lig, d["roi"]) for lig, d in lig_roi_sirali[:3]] if lig_roi_sirali else []
    en_kotu_ligler = [(lig, d["roi"]) for lig, d in lig_roi_sirali[-3:]] if lig_roi_sirali else []

    # ═══ TIER BAZLI KIRILIM ═══
    tier_stats = defaultdict(lambda: {"toplam": 0, "kazanan": 0, "kaybeden": 0, "kar": 0.0})
    for b in bahisler:
        tier = b.get("tier", b.get("aktif_tier", "?"))
        tier_stats[tier]["toplam"] += 1
        if b.get("sonuc") == "kazandi":
            tier_stats[tier]["kazanan"] += 1
            tier_stats[tier]["kar"] += b.get("profit", 0)
        elif b.get("sonuc") == "kaybetti":
            tier_stats[tier]["kaybeden"] += 1
            tier_stats[tier]["kar"] += b.get("profit", 0)

    tier_rapor = {}
    for tier, s in tier_stats.items():
        g = s["kazanan"] + s["kaybeden"]
        tier_rapor[tier] = {
            "toplam": s["toplam"],
            "kazanan": s["kazanan"],
            "kaybeden": s["kaybeden"],
            "win_rate": round(s["kazanan"] / g, 4) if g > 0 else None,
            "roi": round((s["kar"] / g) * 100, 2) if g > 0 else None,
        }

    # ═══ MODEL vs MARKET ═══
    model_dogru = 0
    market_dogru = 0
    karsilastirma_n = 0
    for b in sonuclu:
        model_p = b.get("model_p", b.get("p_secim", 0))
        market_p = b.get("market_p", 0)
        if model_p <= 0 or market_p <= 0:
            continue
        karsilastirma_n += 1
        tuttu = b.get("sonuc") == "kazandi"
        # Model daha yüksek olasılık verdi VE tuttu
        if model_p > market_p and tuttu:
            model_dogru += 1
        elif market_p >= model_p and not tuttu:
            market_dogru += 1

    # ═══ VERİ TAZELİĞİ ═══
    data_freshness = {}
    if os.path.exists(MACLAR_PATH):
        mod_time = datetime.fromtimestamp(os.path.getmtime(MACLAR_PATH))
        saat_fark = (datetime.now() - mod_time).total_seconds() / 3600
        data_freshness["maclar_json"] = {
            "son_guncelleme": mod_time.strftime("%Y-%m-%d %H:%M"),
            "saat_once": round(saat_fark, 1),
            "taze": saat_fark < 24,
        }
    if os.path.exists(ODDS_CACHE_PATH):
        mod_time = datetime.fromtimestamp(os.path.getmtime(ODDS_CACHE_PATH))
        saat_fark = (datetime.now() - mod_time).total_seconds() / 3600
        data_freshness["odds_cache"] = {
            "son_guncelleme": mod_time.strftime("%Y-%m-%d %H:%M"),
            "saat_once": round(saat_fark, 1),
            "taze": saat_fark < 12,
        }

    # ═══ TAHMIN TİPİ BAZLI ═══
    tip_stats = defaultdict(lambda: {"toplam": 0, "kazanan": 0, "kaybeden": 0})
    for b in bahisler:
        tip = b.get("tahmin", "?")
        tip_stats[tip]["toplam"] += 1
        if b.get("sonuc") == "kazandi":
            tip_stats[tip]["kazanan"] += 1
        elif b.get("sonuc") == "kaybetti":
            tip_stats[tip]["kaybeden"] += 1

    # ═══ RAPOR OLUŞTUR ═══
    rapor = {
        "rapor_tarihi": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "ozet": {
            "toplam_bahis": toplam,
            "sonuclu": len(sonuclu),
            "bekleyen": bekleyen,
            "kazanan": len(kazanan),
            "kaybeden": len(kaybeden),
            "win_rate": round(win_rate, 4),
            "win_rate_pct": f"%{win_rate*100:.1f}",
            "roi": round(roi, 2),
            "roi_str": f"%{roi:+.1f}",
            "toplam_kar_zarar": round(toplam_kar, 2),
            "avg_odds": round(avg_odds, 2),
            "avg_edge_pct": round(avg_edge * 100, 2),
            "bootstrap_ci_95": [round(boot_lower, 2), round(boot_upper, 2)],
            "is_statistically_significant": is_significant,
        },
        "clv": {
            "hesaplanan": len(clv_list),
            "ortalama": round(clv_avg, 4) if clv_avg is not None else None,
            "pozitif_oran": round(clv_positive_pct, 4) if clv_positive_pct is not None else None,
            "durum": "POZİTİF" if clv_avg and clv_avg > 0 else ("NEGATİF" if clv_avg else "VERİ YOK"),
        },
        "lig_bazli": lig_rapor,
        "en_iyi_ligler": en_iyi_ligler,
        "en_kotu_ligler": en_kotu_ligler,
        "tier_bazli": tier_rapor,
        "tahmin_tipi": dict(tip_stats),
        "model_vs_market": {
            "karsilastirma_sayisi": karsilastirma_n,
            "model_basarili": model_dogru,
            "market_basarili": market_dogru,
        },
        "veri_tazeligi": data_freshness,
    }

    return rapor


def print_report(rapor: dict):
    """Raporu konsola yazdır."""
    o = rapor.get("ozet", {})
    clv = rapor.get("clv", {})

    sep = "═" * 60
    print(f"\n{sep}")
    print(f"  📊 QUANTBET AI — PERFORMANS RAPORU")
    print(f"  {rapor.get('rapor_tarihi', '')}")
    print(sep)

    print(f"\n  📋 GENEL ÖZET")
    print(f"  {'─' * 40}")
    print(f"  Toplam Bahis    : {o.get('toplam_bahis', 0)}")
    print(f"  Sonuçlanan      : {o.get('sonuclu', 0)} (Bekleyen: {o.get('bekleyen', 0)})")
    print(f"  Kazanan         : {o.get('kazanan', 0)}")
    print(f"  Kaybeden        : {o.get('kaybeden', 0)}")
    print(f"  Win Rate        : {o.get('win_rate_pct', 'N/A')}")
    emoji_roi = "📈" if o.get("roi", 0) > 0 else "📉"
    ci_gosterim = f"[%{o.get('bootstrap_ci_95', [0,0])[0]:+.1f} / %{o.get('bootstrap_ci_95', [0,0])[1]:+.1f}]"
    print(f"  {emoji_roi} Pinnacle ROI   : {o.get('roi_str', 'N/A')} (95% CI: {ci_gosterim})")
    if not o.get("is_statistically_significant"):
        print(f"  ⚠️ UYARI         : Örneklem boyutu (<250 maç) istatistiksel geçerlilik için çok düşük.")
    print(f"  Kar/Zarar       : {o.get('toplam_kar_zarar', 0):+.2f} birim")
    print(f"  Ort. Pinnacle Odds: {o.get('avg_odds', 0):.2f}")
    print(f"  Ort. Edge       : %{o.get('avg_edge_pct', 0):.1f} (Capped at 15%)")

    print(f"\n  📊 CLV PERFORMANSI (STRICT PINNACLE MATCHING)")
    print(f"  {'─' * 40}")
    if clv.get("hesaplanan", 0) > 0:
        clv_emoji = "✅" if clv.get("ortalama", 0) and clv["ortalama"] > 0 else "❌"
        print(f"  {clv_emoji} Durum        : {clv.get('durum', 'N/A')}")
        print(f"  Hesaplanan     : {clv.get('hesaplanan', 0)} maç")
        print(f"  Ortalama CLV   : %{(clv.get('ortalama', 0) or 0)*100:.2f}")
        print(f"  Pozitif Oran   : %{(clv.get('pozitif_oran', 0) or 0)*100:.0f}")
    else:
        print(f"  ⚠️ CLV verisi yok — closing odds henüz toplanmadı")

    print(f"\n  🏆 LİG BAZLI KIRILIM")
    print(f"  {'─' * 40}")
    for lig, d in sorted(rapor.get("lig_bazli", {}).items(), key=lambda x: x[1].get("toplam", 0), reverse=True):
        wr = f"%{d.get('win_rate',0)*100:.0f}" if d.get("win_rate") is not None else "N/A"
        roi_l = f"%{d.get('roi',0):+.0f}" if d.get("roi") is not None else "~"
        print(f"  {lig:6s} → {d['toplam']:3d} bahis | WR: {wr:5s} | ROI: {roi_l:6s} | Edge: %{d.get('avg_edge_pct', d.get('avg_edge',0)):.1f}")

    print(f"\n  🎯 EN İYİ LİGLER: {rapor.get('en_iyi_ligler', [])}")
    print(f"  💀 EN KÖTÜ LİGLER: {rapor.get('en_kotu_ligler', [])}")

    print(f"\n  🔴 TIER KIRILIMI")
    print(f"  {'─' * 40}")
    for tier, d in rapor.get("tier_bazli", {}).items():
        g = d.get("kazanan", 0) + d.get("kaybeden", 0)
        wr = f"%{d.get('win_rate', 0)*100:.0f}" if d.get("win_rate") is not None else "N/A"
        roi_t = f"%{d.get('roi', 0):+.0f}" if d.get("roi") is not None else "~"
        print(f"  {tier:10s} → {d['toplam']:3d} bahis | G:{g:3d} | WR: {wr:5s} | ROI: {roi_t}")

    # Veri tazeliği
    print(f"\n  🕐 VERİ TAZELİĞİ")
    print(f"  {'─' * 40}")
    for key, val in rapor.get("veri_tazeligi", {}).items():
        emoji = "✅" if val.get("taze") else "❌"
        print(f"  {emoji} {key}: {val.get('son_guncelleme', '?')} ({val.get('saat_once', '?')}h)")

    print(sep)


def main():
    rapor = generate_report()

    if "error" in rapor:
        logger.error(rapor["error"])
        return

    # Konsola yazdır
    print_report(rapor)

    # JSON olarak kaydet
    try:
        with open(REPORT_OUTPUT, "w", encoding="utf-8") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=2)
        logger.info(f"📁 Rapor kaydedildi: {REPORT_OUTPUT}")
    except Exception as e:
        logger.error(f"Rapor kaydetme hatası: {e}")


if __name__ == "__main__":
    main()
