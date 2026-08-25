# analysis/lig_kalibrasyon.py
"""
Lig Bazlı Kalibrasyon Sistemi
══════════════════════════════════════════════════════════════
Problem: Model bazı liglerde sistematik hata yapıyor.
Çözüm: Her lig için ayrı kalibrasyon faktörü hesapla.

Kalibrasyon: Eğer model "ev %60" diyor ama Premier League'de
gerçek oran %50 ise → ev için 0.50/0.60 = 0.83 faktörü uygula.

Yeterli veri (≥30 maç) olmadan varsayılan 1.0 kullanılır.
"""

import os
import csv
import json
from collections import defaultdict

KALIBRASYON_DOSYASI = os.path.join(
    os.path.dirname(__file__), "..", "data", "lig_kalibrasyon.json"
)
MIN_KALIBRASYON_MAC = 15   # En az bu kadar maç yoksa kalibre etme


def kalibrasyon_hesapla(log_dosyasi: str) -> dict:
    """
    Log dosyasından lig+tahmin_türü bazlı kalibrasyon faktörleri hesapla.
    Sonucu JSON'a kaydet.
    """
    if not os.path.exists(log_dosyasi):
        return {}

    sonuc_map = {
        "Ev Sahibi Kazanır": "ev",
        "Deplasman Kazanır": "dep",
        "Beraberlik":        "ber",
    }

    # lig → tahmin_türü → {toplam, dogru, model_p_toplam, oran_toplam}
    stats = defaultdict(lambda: defaultdict(lambda: {
        "toplam": 0, "dogru": 0, "model_p": 0.0, "oran_toplam": 0.0
    }))

    try:
        with open(log_dosyasi, "r", encoding="utf-8") as f:
            for satir in csv.DictReader(f):
                gercek = satir.get("GercekSonuc", "").strip()
                if not gercek or gercek in ("bekliyor", ""):
                    continue

                tahmin = satir.get("Tahmin", "").strip()
                lig    = satir.get("Lig",    "").strip()
                beklenen = sonuc_map.get(tahmin, "")
                dogru    = (beklenen == gercek)

                try:
                    model_p = float(satir.get("Olasilik", 0) or 0)
                    oran    = float(satir.get("Oran",     1) or 1)
                except ValueError:
                    continue

                stats[lig][tahmin]["toplam"]      += 1
                stats[lig][tahmin]["dogru"]       += int(dogru)
                stats[lig][tahmin]["model_p"]     += model_p
                stats[lig][tahmin]["oran_toplam"] += oran

    except Exception:
        return {}

    kalibrasyon = {}
    for lig, tahmin_stats in stats.items():
        kalibrasyon[lig] = {}
        for tahmin, s in tahmin_stats.items():
            n = s["toplam"]
            if n < MIN_KALIBRASYON_MAC:
                kalibrasyon[lig][tahmin] = {
                    "faktor": 1.0,
                    "mac": n,
                    "gercek_oran": None,
                    "model_oran": None,
                    "not": "yetersiz_veri"
                }
                continue

            gercek_oran = s["dogru"] / n
            model_oran  = s["model_p"] / n

            # Kalibrasyon faktörü: gercek / model
            # 0.7 ile 1.4 arasında sınırla — aşırı düzeltme yapma
            if model_oran > 0.01:
                faktor = max(0.70, min(gercek_oran / model_oran, 1.40))
            else:
                faktor = 1.0

            kalibrasyon[lig][tahmin] = {
                "faktor":      round(faktor, 4),
                "mac":         n,
                "gercek_oran": round(gercek_oran, 4),
                "model_oran":  round(model_oran, 4),
            }

    # Kaydet
    os.makedirs(os.path.dirname(KALIBRASYON_DOSYASI), exist_ok=True)
    with open(KALIBRASYON_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(kalibrasyon, f, ensure_ascii=False, indent=2)

    return kalibrasyon


def kalibrasyon_yukle() -> dict:
    """Kaydedilmiş kalibrasyon faktörlerini yükle."""
    if not os.path.exists(KALIBRASYON_DOSYASI):
        return {}
    try:
        with open(KALIBRASYON_DOSYASI, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def kalibre_et(olasilik: float, lig: str, tahmin: str,
                kalibrasyon: dict = None) -> float:
    """
    Tek olasılık değerini kalibre et.
    Yeterli veri yoksa değişmeden döner.
    """
    if kalibrasyon is None:
        kalibrasyon = kalibrasyon_yukle()

    lig_k   = kalibrasyon.get(lig, {})
    tahmin_k = lig_k.get(tahmin, {})
    faktor  = tahmin_k.get("faktor", 1.0)
    mac_say = tahmin_k.get("mac", 0)

    if mac_say < MIN_KALIBRASYON_MAC:
        return olasilik

    kalibre = olasilik * faktor
    return round(max(0.05, min(kalibre, 0.95)), 4)


def kalibrasyon_raporu(log_dosyasi: str) -> None:
    """Kalibrasyon raporunu ekrana yaz."""
    kalibrasyon = kalibrasyon_hesapla(log_dosyasi)

    if not kalibrasyon:
        print("  ℹ️  Kalibrasyon verisi yok")
        return

    print("\n  📐 LİG KALİBRASYON RAPORU:")
    print(f"  {'Lig':<20} {'Tahmin Türü':<22} {'Maç':>4} {'Model':>7} {'Gerçek':>7} {'Faktör':>7}")
    print(f"  {'─'*70}")

    for lig in sorted(kalibrasyon.keys()):
        for tahmin in sorted(kalibrasyon[lig].keys()):
            k = kalibrasyon[lig][tahmin]
            if k.get("mac", 0) < 3:
                continue
            model_s  = f"%{k['model_oran']*100:.0f}" if k.get("model_oran") else "  ?"
            gercek_s = f"%{k['gercek_oran']*100:.0f}" if k.get("gercek_oran") else "  ?"
            faktor_s = f"{k['faktor']:.2f}"
            uyari    = " ⚠️" if abs(k.get("faktor", 1) - 1.0) > 0.2 else ""
            print(f"  {lig:<20} {tahmin:<22} {k['mac']:>4} "
                  f"{model_s:>7} {gercek_s:>7} {faktor_s:>7}{uyari}")