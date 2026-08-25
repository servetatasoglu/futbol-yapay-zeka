# analysis/brier_monitor.py
"""
Brier Score İzleme ve Kalibrasyon Erken Uyarı Sistemi
═══════════════════════════════════════════════════════

Brier Score: model tahminlerinin gerçek sonuçlara ne kadar yakın olduğunu ölçer.
  BS = mean((predicted_p - outcome)^2)
  
  Mükemmel:   BS = 0.00    (her tahmin %100 doğru)
  Rastgele:   BS = 0.333   (1X2 için)
  İyi model:  BS < 0.22
  Kabul:      BS < 0.25
  Tehlikeli:  BS > 0.28    → model kalibrasyonu bozulmuş, bahis durdurulmalı

KULLANIM:
  from tracking.brier_monitor import brier_raporu, brier_kontrol
  rapor = brier_raporu("logs/tahminler_log.csv")
  tehlike = brier_kontrol(rapor)  # True → bahis durdurulmalı

İZLEME:
  - Son 50 bahis üzerinden rolling Brier Score
  - Lig bazlı kalibrasyon kontrolü
  - Trend analizi: son 20 vs önceki 20 bahis
  - Telegram uyarısı entegrasyonu (opsiyonel)
"""

import csv
import os
import json
from datetime import datetime
from typing import Optional


# ── Eşikler ───────────────────────────────────────────────────
BRIER_TEHLIKE_ESIGI   = 0.28    # Bu üstüne çıkarsa bahis durdur
BRIER_UYARI_ESIGI     = 0.25    # Bu üstüne çıkarsa uyar
BRIER_HEDEF           = 0.22    # İdeal kalibrasyon hedefi
ROLLING_PENCERE       = 50      # Kaç bahis üzerinden hesapla
MIN_ORNEKLEM          = 20      # En az bu kadar sonuçlanmış bahis lazım

# Brier log dosyası
BRIER_LOG_DOSYA = os.path.join(
    os.path.dirname(__file__), "..", "data", "brier_log.json"
)


def brier_score(tahminler: list) -> float:
    """
    Brier Score hesapla.
    
    Args:
        tahminler: [ {"predicted_p": 0.62, "won": True}, ... ]
    
    Returns:
        Brier Score (0.0-1.0 arası, düşük daha iyi)
    """
    if not tahminler:
        return 1.0
    toplam = sum(
        (t["predicted_p"] - (1.0 if t["won"] else 0.0)) ** 2
        for t in tahminler
    )
    return round(toplam / len(tahminler), 6)


def brier_log_oku() -> list:
    """Geçmiş Brier kayıtlarını oku."""
    if not os.path.exists(BRIER_LOG_DOSYA):
        return []
    try:
        with open(BRIER_LOG_DOSYA, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def brier_log_yaz(kayitlar: list):
    """Brier kayıtlarını yaz."""
    os.makedirs(os.path.dirname(BRIER_LOG_DOSYA), exist_ok=True)
    with open(BRIER_LOG_DOSYA, "w", encoding="utf-8") as f:
        json.dump(kayitlar[-100:], f, ensure_ascii=False, indent=2)


def brier_raporu(log_dosyasi: str = "logs/tahminler_log.csv") -> dict:
    """
    Log dosyasından Brier Score raporu üret.
    
    Returns:
        {
            "genel_brier": float,
            "rolling_brier": float,     # son 50 bahis
            "trend": str,               # "iyileşiyor" / "kötüleşiyor" / "stabil"
            "lig_brier": dict,          # lig → brier
            "orneklem": int,
            "tehlike": bool,
            "uyari": bool,
            "mesaj": str,
        }
    """
    if not os.path.exists(log_dosyasi):
        return {"genel_brier": 1.0, "orneklem": 0, "mesaj": "Log dosyası yok"}

    tahminler = []

    with open(log_dosyasi, "r", encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            sonuc = satir.get("GercekSonuc", "").strip()
            if sonuc not in ("ev", "dep", "ber"):
                continue

            tahmin_tip = satir.get("Tahmin", "")
            olasilik = float(satir.get("Olasilik", 0) or 0)
            lig = satir.get("Lig", "")

            if olasilik <= 0:
                continue

            # Kazandı mı?
            sonuc_map = {
                "Ev Sahibi Kazanır": "ev",
                "Deplasman Kazanır": "dep",
                "Beraberlik": "ber",
            }
            beklenen = sonuc_map.get(tahmin_tip, "")
            kazandi = beklenen == sonuc

            tahminler.append({
                "predicted_p": olasilik,
                "won": kazandi,
                "lig": lig,
            })

    if len(tahminler) < MIN_ORNEKLEM:
        return {
            "genel_brier": 1.0,
            "orneklem": len(tahminler),
            "mesaj": f"Yetersiz örneklem: {len(tahminler)} (min {MIN_ORNEKLEM})",
        }

    # ── Genel Brier Score ───────────────────────────────────────
    genel = brier_score(tahminler)

    # ── Rolling Brier (son N bahis) ─────────────────────────────
    son_n = tahminler[-ROLLING_PENCERE:]
    rolling = brier_score(son_n)

    # ── Trend: son 20 vs önceki 20 ─────────────────────────────
    trend = "stabil"
    if len(tahminler) >= 40:
        son20 = brier_score(tahminler[-20:])
        onceki20 = brier_score(tahminler[-40:-20])
        fark = son20 - onceki20
        if fark > 0.02:
            trend = "kötüleşiyor ⚠️"
        elif fark < -0.02:
            trend = "iyileşiyor ✅"

    # ── Lig bazlı Brier ────────────────────────────────────────
    lig_gruplari = {}
    for t in tahminler:
        lig = t.get("lig", "Bilinmiyor")
        if lig not in lig_gruplari:
            lig_gruplari[lig] = []
        lig_gruplari[lig].append(t)

    lig_brier = {}
    for lig, grup in lig_gruplari.items():
        if len(grup) >= 10:
            lig_brier[lig] = {
                "brier": brier_score(grup),
                "n": len(grup),
            }

    # ── Tehlike/Uyarı Tespiti ──────────────────────────────────
    tehlike = rolling > BRIER_TEHLIKE_ESIGI
    uyari = rolling > BRIER_UYARI_ESIGI

    if tehlike:
        mesaj = f"🚨 TEHLİKE: Brier Score {rolling:.4f} > {BRIER_TEHLIKE_ESIGI} — BAHİS DURDURULMALI!"
    elif uyari:
        mesaj = f"⚠️  UYARI: Brier Score {rolling:.4f} > {BRIER_UYARI_ESIGI} — kalibrasyon bozuluyor"
    else:
        mesaj = f"✅ Brier Score {rolling:.4f} — kalibrasyon sağlıklı (hedef: <{BRIER_HEDEF})"

    rapor = {
        "genel_brier": genel,
        "rolling_brier": rolling,
        "trend": trend,
        "lig_brier": lig_brier,
        "orneklem": len(tahminler),
        "rolling_pencere": min(len(tahminler), ROLLING_PENCERE),
        "tehlike": tehlike,
        "uyari": uyari,
        "mesaj": mesaj,
        "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    # ── Log'a kaydet ────────────────────────────────────────────
    gecmis = brier_log_oku()
    gecmis.append({
        "tarih": rapor["tarih"],
        "genel": genel,
        "rolling": rolling,
        "orneklem": len(tahminler),
    })
    brier_log_yaz(gecmis)

    return rapor


def brier_kontrol(rapor: dict) -> bool:
    """
    Brier Raporu'nu kontrol et.
    True dönerse bahis durdurulmalı.
    """
    return rapor.get("tehlike", False)


def brier_yazdir(rapor: dict):
    """Brier Score raporunu konsola yazdır."""
    if rapor.get("orneklem", 0) < MIN_ORNEKLEM:
        print(f"  ℹ️  {rapor.get('mesaj', 'Brier verisi yok')}")
        return

    SEP = "═" * 58
    print(f"\n{SEP}")
    print("  🎯  BRIER SCORE KALİBRASYON RAPORU")
    print(SEP)
    print(f"  Genel Brier Score    : {rapor['genel_brier']:.4f}")
    print(f"  Rolling ({rapor['rolling_pencere']} bahis)   : {rapor['rolling_brier']:.4f}")
    print(f"  Trend                : {rapor['trend']}")
    print(f"  Örneklem             : {rapor['orneklem']} sonuçlanmış bahis")
    print()
    print(f"  {rapor['mesaj']}")

    # Lig bazlı
    if rapor.get("lig_brier"):
        print()
        print(f"  {'Lig':<20} {'Brier':>8} {'n':>5}")
        print("  " + "-" * 36)
        for lig, d in sorted(rapor["lig_brier"].items(),
                              key=lambda x: x[1]["brier"]):
            durum = "✅" if d["brier"] < BRIER_UYARI_ESIGI else "⚠️"
            print(f"  {lig:<20} {d['brier']:>8.4f} {d['n']:>5}  {durum}")

    print(SEP)


def kalibrasyon_ozet(log_dosyasi: str = "logs/tahminler_log.csv") -> dict:
    """
    Model olasılık aralıklarında gerçek isabet oranı — kalibrasyon eğrisi.
    İdeal: model %60 dediğinde gerçekte %60 kazanmalı.
    """
    if not os.path.exists(log_dosyasi):
        return {}

    araliklar = [
        (0.25, 0.35), (0.35, 0.45), (0.45, 0.55),
        (0.55, 0.65), (0.65, 0.75), (0.75, 0.85),
    ]

    gruplar = {f"{a:.2f}-{b:.2f}": {"tahminler": [], "kazanan": 0}
               for a, b in araliklar}

    with open(log_dosyasi, "r", encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            sonuc = satir.get("GercekSonuc", "").strip()
            if sonuc not in ("ev", "dep", "ber"):
                continue

            olasilik = float(satir.get("Olasilik", 0) or 0)
            tahmin = satir.get("Tahmin", "")
            sonuc_map = {
                "Ev Sahibi Kazanır": "ev",
                "Deplasman Kazanır": "dep",
                "Beraberlik": "ber",
            }
            beklenen = sonuc_map.get(tahmin, "")
            kazandi = beklenen == sonuc

            for a, b in araliklar:
                etiket = f"{a:.2f}-{b:.2f}"
                if a <= olasilik < b:
                    gruplar[etiket]["tahminler"].append(olasilik)
                    if kazandi:
                        gruplar[etiket]["kazanan"] += 1
                    break

    sonuc = {}
    for etiket, d in gruplar.items():
        n = len(d["tahminler"])
        if n < 5:
            continue
        gercek = d["kazanan"] / n
        beklenen = sum(d["tahminler"]) / n
        sonuc[etiket] = {
            "n": n,
            "beklenen_isabet": round(beklenen, 4),
            "gercek_isabet": round(gercek, 4),
            "sapma": round(gercek - beklenen, 4),
        }

    return sonuc
