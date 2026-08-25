# analysis/monte_carlo.py
"""
Monte Carlo Maç Simülasyon Motoru — FAZ 2
──────────────────────────────────────────
Neden Monte Carlo?
  • Poisson analitik model deterministik — her seferinde aynı sonuç
  • MC simülasyonu λ değerlerindeki BELIRSIZLIĞI modeller
  • Angers gibi "aşırı istatistik" anomalilerini doğal olarak frenler
  • Confidence interval verir: "ev kazanır %55 ± %4" gibi
  • Over/Under, BTS gibi yan piyasalar için de güvenilir olasılık üretir

Yöntem:
  1. λ_ev ve λ_dep'i Poisson modelinden al
  2. Her simülasyonda λ'yı Gamma dağılımından örnekle (belirsizlik)
  3. O λ ile Poisson'dan rastgele gol sayısı çek
  4. N=10.000 simülasyon — yeterli hassasiyet, hızlı çalışır
  5. Sonuçları say, olasılığa çevir
  6. Bootstrap ile %95 güven aralığı hesapla
"""

import random
import math
from config.settings import MC_SIMULASYON_SAYISI, MC_LAMBDA_BELIRSIZLIK


def _poisson_ornekle(lam: float) -> int:
    """
    Knuth algoritması ile Poisson rastgele sayı üretimi.
    Python'un random modülü kullanılır — numpy bağımlılığı yok.
    """
    if lam <= 0:
        return 0
    # Büyük lambda için normal yaklaşım (performans)
    if lam > 30:
        val = random.gauss(lam, math.sqrt(lam))
        return max(0, int(round(val)))
    L = math.exp(-lam)
    k = 0
    p = 1.0
    while p > L:
        k += 1
        p *= random.random()
    return k - 1


def _gamma_ornekle(lam: float, belirsizlik: float) -> float:
    """
    Lambda'yı Gamma dağılımından örnekle.
    Bu, istatistik veri yetersizliğindeki belirsizliği modeller.

    Gamma(alpha, beta) parametreleri:
      alpha = 1/belirsizlik² (şekil)
      beta  = lam * belirsizlik² (ölçek)

    Sonuç: ortalama = lam, std = lam * belirsizlik
    belirsizlik = 0.15 → λ'nın %15 standart sapmayla rastgele değişmesi
    """
    alpha = 1.0 / (belirsizlik ** 2)
    beta  = lam * (belirsizlik ** 2)
    return random.gammavariate(alpha, beta)


def monte_carlo_simule(lam_ev: float, lam_dep: float,
                        n: int = None,
                        belirsizlik: float = None) -> dict:
    """
    N simülasyon çalıştırır ve tüm bahis piyasaları için olasılık üretir.

    Args:
        lam_ev:      Ev sahibi beklenen gol (Poisson modelinden)
        lam_dep:     Deplasman beklenen gol
        n:           Simülasyon sayısı (varsayılan: settings'ten)
        belirsizlik: Lambda belirsizlik katsayısı (0.10-0.25 arası önerilir)

    Returns:
        {
          "home_win": float, "draw": float, "away_win": float,
          "over15_p", "over25_p", "over35_p",
          "bts_p",
          "home_win_ci": (alt, ust),   # %95 güven aralığı
          "draw_ci": (alt, ust),
          "away_win_ci": (alt, ust),
          "sim_sayisi": int,
          "sim_lam_ev_ort": float,     # Simülasyonda kullanılan λ ortalaması
          "sim_lam_dep_ort": float,
        }
    """
    if n is None:
        n = MC_SIMULASYON_SAYISI
    if belirsizlik is None:
        belirsizlik = MC_LAMBDA_BELIRSIZLIK

    ev_kazan  = 0
    beraberlik = 0
    dep_kazan  = 0
    over15    = 0
    over25    = 0
    over35    = 0
    bts       = 0

    lam_ev_toplam  = 0.0
    lam_dep_toplam = 0.0

    # Bootstrap için batch kaydet (güven aralığı için)
    BATCH = 100
    batch_ev   = []
    batch_ber  = []
    batch_dep  = []
    batch_ev_sayac  = 0
    batch_ber_sayac = 0
    batch_dep_sayac = 0

    for i in range(n):
        # Lambda'yı Gamma ile örnekle — belirsizlik enjeksiyonu
        sim_lam_ev  = _gamma_ornekle(lam_ev,  belirsizlik)
        sim_lam_dep = _gamma_ornekle(lam_dep, belirsizlik)

        lam_ev_toplam  += sim_lam_ev
        lam_dep_toplam += sim_lam_dep

        # Gol sayılarını Poisson'dan örnekle
        gol_ev  = _poisson_ornekle(sim_lam_ev)
        gol_dep = _poisson_ornekle(sim_lam_dep)

        toplam_gol = gol_ev + gol_dep

        # Sonuç sayaçları
        if gol_ev > gol_dep:
            ev_kazan += 1
            batch_ev_sayac += 1
        elif gol_ev == gol_dep:
            beraberlik += 1
            batch_ber_sayac += 1
        else:
            dep_kazan += 1
            batch_dep_sayac += 1

        if toplam_gol > 1:
            over15 += 1
        if toplam_gol > 2:
            over25 += 1
        if toplam_gol > 3:
            over35 += 1
        if gol_ev >= 1 and gol_dep >= 1:
            bts += 1

        # Her BATCH simülasyonda batch oranını kaydet
        if (i + 1) % BATCH == 0:
            batch_ev.append(batch_ev_sayac / BATCH)
            batch_ber.append(batch_ber_sayac / BATCH)
            batch_dep.append(batch_dep_sayac / BATCH)
            batch_ev_sayac  = 0
            batch_ber_sayac = 0
            batch_dep_sayac = 0

    # Ana olasılıklar
    ev_p   = ev_kazan  / n
    ber_p  = beraberlik / n
    dep_p  = dep_kazan / n

    # %95 güven aralığı (bootstrap batch ortalamaları)
    def _ci(batch_list):
        if len(batch_list) < 4:
            return (0.0, 1.0)
        sirali = sorted(batch_list)
        alt_idx = int(len(sirali) * 0.025)
        ust_idx = int(len(sirali) * 0.975)
        return (round(sirali[alt_idx], 4), round(sirali[ust_idx], 4))

    return {
        # Ana sonuç olasılıkları
        "home_win":  round(ev_p,  4),
        "draw":      round(ber_p, 4),
        "away_win":  round(dep_p, 4),

        # Yan piyasalar
        "over15_p":  round(over15 / n, 4),
        "over25_p":  round(over25 / n, 4),
        "over35_p":  round(over35 / n, 4),
        "bts_p":     round(bts    / n, 4),

        # Güven aralıkları
        "home_win_ci": _ci(batch_ev),
        "draw_ci":     _ci(batch_ber),
        "away_win_ci": _ci(batch_dep),

        # Simülasyon meta
        "sim_sayisi":       n,
        "sim_lam_ev_ort":  round(lam_ev_toplam  / n, 3),
        "sim_lam_dep_ort": round(lam_dep_toplam / n, 3),
    }


def mc_model_birlestir(mc_sonuc: dict, analitik_sonuc: dict,
                        mc_agirlik: float = 0.35) -> dict:
    """
    Monte Carlo sonucunu analitik modelle (ELO+Poisson) birleştirir.

    Neden %35 MC ağırlığı?
      • MC daha doğru ama daha yavaş ve gürültülü
      • Analitik model (ELO+Poisson) teorik zemin sağlıyor
      • İkisinin ortalaması her ikisinin zayıflığını dengeler

    Ağırlık konfigürasyonu settings'ten okunabilir.
    """
    analitik_w = 1.0 - mc_agirlik

    ev_p  = mc_agirlik * mc_sonuc["home_win"] + analitik_w * analitik_sonuc["home_win"]
    ber_p = mc_agirlik * mc_sonuc["draw"]     + analitik_w * analitik_sonuc["draw"]
    dep_p = mc_agirlik * mc_sonuc["away_win"] + analitik_w * analitik_sonuc["away_win"]

    toplam = ev_p + ber_p + dep_p
    ev_p  /= toplam
    ber_p /= toplam
    dep_p /= toplam

    # MC ile analitik modelin ne kadar yakın olduğu
    mc_analitik_uyum = 1.0 - (
        abs(mc_sonuc["home_win"] - analitik_sonuc["home_win"]) +
        abs(mc_sonuc["draw"]     - analitik_sonuc["draw"])     +
        abs(mc_sonuc["away_win"] - analitik_sonuc["away_win"])
    ) / 2.0

    return {
        "home_win": round(ev_p,  4),
        "draw":     round(ber_p, 4),
        "away_win": round(dep_p, 4),

        # Yan piyasalar MC'den gelir (analitik model bunları hesaplamıyor)
        "over15_p":  mc_sonuc["over15_p"],
        "over25_p":  mc_sonuc["over25_p"],
        "over35_p":  mc_sonuc["over35_p"],
        "bts_p":     mc_sonuc["bts_p"],

        # Güven aralıkları
        "home_win_ci": mc_sonuc["home_win_ci"],
        "draw_ci":     mc_sonuc["draw_ci"],
        "away_win_ci": mc_sonuc["away_win_ci"],

        # Uyum skoru
        "mc_analitik_uyum": round(mc_analitik_uyum, 3),

        # Ham MC değerleri (şeffaflık için)
        "mc_ev_p":  mc_sonuc["home_win"],
        "mc_ber_p": mc_sonuc["draw"],
        "mc_dep_p": mc_sonuc["away_win"],
    }