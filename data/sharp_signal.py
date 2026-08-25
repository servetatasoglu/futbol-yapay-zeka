# data/sharp_signal.py
"""
Sharp Money Sinyal Üreteci — Cross-Sectional Analiz
════════════════════════════════════════════════════════════════════
SORUN:
  odds_movement.py zaman serisi tabanlı → ama cache 6 saat olduğu için
  açılış ve kapanış oranı aynı → hareket=0 → sharp_sinyal="YOK" (hep!)

ÇÖZÜM:
  Zaman serisine gerek YOK. Aynı anda birden fazla bahisçi oranı var.
  Pinnacle (sharp kitap) vs soft kitaplar (bet365, unibet, bwin)
  arasındaki implied probability farkını hesapla.

  Pinnacle bir tarafa daha düşük oran (= daha yüksek olasılık) veriyorsa,
  o taraf "sharp money" tarafıdır.

MANTIK:
  1. Pinnacle implied prob hesapla (vig-free)
  2. Soft kitaplar ortalaması hesapla (vig-free)
  3. Fark = Pinnacle_prob - Soft_prob
  4. Fark > +%2 → o taraf sharp side

AUDIT BULGUSU:
  Sharp uyumlu tahminler %63.1 isabet (%44'e karşı)
  → Bu modül audit'in keşfettiği en güçlü sinyali CANLIYA taşır.

KULLANIM:
  from data.sharp_signal import sharp_sinyal_hesapla
  sinyal = sharp_sinyal_hesapla(kitap_oranlari, pinnacle_var)
"""


# ─── Sharp vs Soft kitap sınıflandırması ──────────────────────────────
SHARP_KITAPLAR = {"pinnacle", "betfair_ex_eu", "betfair", "matchbook"}
SOFT_KITAPLAR  = {"bet365", "williamhill", "unibet", "bwin", "marathonbet",
                  "betway", "1xbet", "betclic", "coolbet", "nordicbet"}

# Minimum sinyal eşiği: Pinnacle - Soft farkı bu kadar olmalı
# AUDIT v4: Tier sistemi — fark büyüklüğüne göre ELITE/STRONG/WEAK
# Pinnacle implied prob farkı eşikleri:
TIER_ELITE  = 0.020   # %2.0+ → ELITE: Pinnacle çok agresif fiyatlıyor
TIER_STRONG = 0.012   # %1.2+ → STRONG: Anlamlı fark, güvenilir sinyal
TIER_WEAK   = 0.008   # %0.8+ → WEAK: Zayıf ama var, dikkatli kullan

# Eski isimler — geriye uyum
MIN_FARK_ESIK  = TIER_WEAK    # Artık WEAK bile sinyal üretiyor
GUCLU_FARK     = TIER_STRONG
COK_GUCLU_FARK = TIER_ELITE

# ─── SHARP TIER → EDGE EŞİĞİ HARİTASI ─────────────────────────────────
# v3.0: TIER thresholds lowered to realistic levels
# Old NO_SHARP threshold of 15% was blocking too many valid bets.
# New approach: continuous score, not binary gates.
TIER_EDGE_ESIGI = {
    "ELITE":    0.020,   # %2 edge yeterli — Pinnacle çok net konuşuyor
    "STRONG":   0.030,   # %3 edge — güvenilir sinyal (was 3.5%)
    "WEAK":     0.040,   # %4 edge — zayıf sinyal (was 5.5%)
    "NO_SHARP": 0.060,   # %6 edge — piyasa desteği yok (was 15% — too restrictive)
}

# Beraberlik ek cezası (her tier'a eklenecek)
BER_EK_ESIK = 0.025   # v3.0: 0.040 → 0.025 (draw filter already strict)

# Drift Against Model eşiği: piyasa tahminimizin tersi yönünde bu kadar
# hareket ederse bahis "tehlikeli" olarak işaretlenir
DRIFT_ESIGI = 0.04   # Piyasa tahminimize karşı %4+ oransal düşüş


def sharp_tier(fark: float) -> str:
    """Pinnacle-Soft fark değerinden sharp tier döndürür."""
    if fark >= TIER_ELITE:
        return "ELITE"
    elif fark >= TIER_STRONG:
        return "STRONG"
    elif fark >= TIER_WEAK:
        return "WEAK"
    return "NO_SHARP"


def sharp_score_surekli(fark: float, n_soft_books: int = 1,
                         steam: bool = False, steam_strength: float = 0.0) -> float:
    """
    v3.0: Continuous sharp score [0.0 – 1.0] instead of binary tier.
    More information preserved, better risk-adjusted sizing.

    Components:
      - Base:        fark magnitude vs TIER_ELITE threshold
      - Consensus:   more soft books = higher confidence
      - Steam bonus: steam move confirms sharp money
    """
    # Base score: normalize fark to [0, 1]
    # TIER_ELITE = 0.020 → score 0.6 at elite threshold, 1.0 at 2x elite
    base = min(1.0, fark / (TIER_ELITE * 2)) if fark > 0 else 0.0

    # Consensus bonus: more soft books = more reliable comparison
    consensus = min(0.2, n_soft_books / 10 * 0.2)

    # Steam bonus: steam move confirms institutional activity
    steam_bonus = min(0.2, steam_strength * 0.3) if steam else 0.0

    score = base + consensus + steam_bonus
    return round(min(1.0, max(0.0, score)), 3)


def kickoff_decay(sharp_score: float, saat_kala: float) -> float:
    """
    v3.0: Sharp signal confidence decays as kickoff approaches.
    Very close to kickoff, public money dominates and sharp signal isı less reliable.

    saat_kala: hours until kickoff
    Returns: decayed sharp_score
    """
    import math
    if saat_kala >= 24:   # > 24h before kickoff: full signal
        return sharp_score
    elif saat_kala >= 4:  # 4-24h: moderate decay
        decay = 1.0 - (0.1 * (24 - saat_kala) / 20)
        return round(sharp_score * max(0.7, decay), 3)
    elif saat_kala >= 1:  # 1-4h: in the closing window, signal is strongest (odd)
        # Actually this is where sharp money IS closing line → signal is valid
        return sharp_score
    else:                 # <1h: in-play / very late, ignore
        return sharp_score * 0.5


def sharp_edge_esigi(tier: str, tahmin: str = "") -> float:
    """
    Sharp tier ve tahmin tipine göre dinamik edge eşiği döndürür.
    Bu fonksiyonu main.py'de edge filtreleme için kullan.
    """
    esik = TIER_EDGE_ESIGI.get(tier, TIER_EDGE_ESIGI["NO_SHARP"])
    if tahmin == "Beraberlik":
        esik += BER_EK_ESIK
    return esik


def drift_against_model_mi(tahmin: str, ev_hareket: float, dep_hareket: float) -> bool:
    """
    Piyasa tahminimizin TERSİ yönünde sert hareket ediyor mu?
    
    Örnek: Modelimiz "Ev Sahibi Kazanır" diyor ama piyasa
    ev oranını sert düşürüyor (ev daha az favori oluyor) → Drift Against Model.
    
    Parametreler:
        tahmin:      "Ev Sahibi Kazanır" | "Deplasman Kazanır" | "Beraberlik"
        ev_hareket:  Ev oranının açılıştan şimdiye % değişimi (pozitif = oran düştü = ev daha favori)
        dep_hareket: Deplasman oranının açılıştan şimdiye % değişimi
    
    Döndürür:
        True  → Piyasa model tahminimizin KARŞISINDA hareket ediyor → Tehlikeli!
        False → Piyasa bizi destekliyor veya nötr
    """
    if not ev_hareket and not dep_hareket:
        return False  # Hareket verisi yok, güvenli varsay

    # Ev sahibi tahmini: piyasa ev oranını olumsuz yönde hareket ettiriyorsa (oranı artırıyorsa) tehlikeli
    # ev_hareket pozitif = oran DÜŞTÜgescribirn = ev daha favori, bizi destekliyor
    # ev_hareket negatif = oran YUKARI gitmiş = ev daha az favori = model aleyhine
    if tahmin == "Ev Sahibi Kazanır":
        # ev oranı açılıştan bu yana artmışsa (ev aleyhine hareket) drift var
        return ev_hareket < -DRIFT_ESIGI * 100  # ev_hareket yüzdelik değerde
    
    elif tahmin == "Deplasman Kazanır":
        # dep oranı artmışsa (dep aleyhine hareket) drift var
        return dep_hareket < -DRIFT_ESIGI * 100
    
    elif tahmin == "Beraberlik":
        # Her iki taraf da güçlü hareket görüyorsa beraberlik aleyhine
        return (ev_hareket > DRIFT_ESIGI * 100 * 2) or (dep_hareket > DRIFT_ESIGI * 100 * 2)
    
    return False


def _vig_free_probs(ev_oran: float, ber_oran: float, dep_oran: float) -> tuple:
    """Oranları vig-free implied probability'ye çevir."""
    if ev_oran <= 1.0 or ber_oran <= 1.0 or dep_oran <= 1.0:
        return (0.33, 0.33, 0.34)
    raw_ev  = 1.0 / ev_oran
    raw_ber = 1.0 / ber_oran
    raw_dep = 1.0 / dep_oran
    toplam  = raw_ev + raw_ber + raw_dep
    if toplam <= 0:
        return (0.33, 0.33, 0.34)
    return (raw_ev / toplam, raw_ber / toplam, raw_dep / toplam)


def _vig_free_probs_2way(opt1_oran: float, opt2_oran: float) -> tuple:
    """İki seçenekli pazarlar (Alt/Üst, KG) için vig-free ihtimal çevrimi."""
    if opt1_oran <= 1.0 or opt2_oran <= 1.0:
        return (0.50, 0.50)
    raw1 = 1.0 / opt1_oran
    raw2 = 1.0 / opt2_oran
    toplam = raw1 + raw2
    if toplam <= 0:
        return (0.50, 0.50)
    return (raw1 / toplam, raw2 / toplam)


def sharp_sinyal_hesapla(kitap_oranlari: dict, pinnacle_var: bool = False) -> dict:
    """
    Kitaplar arası (cross-sectional) sharp money sinyali üretir (3 ihtimalli pazar).

    Parametreler:
        kitap_oranlari: {kitap_adi: (ev_oran, ber_oran, dep_oran), ...}
                        → _cok_kitap_analiz() fonksiyonundan gelir
        pinnacle_var:   Pinnacle oranı mevcut mu

    Döndürür:
        {
            "sharp_sinyal":  "EV" | "DEP" | "BER" | "YOK",
            "hareket_gucu":  0.0 - 1.0 (sinyal gücü),
            "sharp_fark_ev":  float (Pinnacle - Soft farkı, ev tarafı),
            "sharp_fark_dep": float,
            "sharp_fark_ber": float,
            "sharp_kitap":    str (hangi sharp kitap kullanıldı),
            "soft_kitap_n":   int (kaç tane soft kitap var),
            "sinyal_gucunun_kaynagi": str (açıklama)
        }
    """
    sonuc_yok = {
        "sharp_sinyal":  "YOK",
        "hareket_gucu":  0.0,
        "sharp_fark_ev":  0.0,
        "sharp_fark_dep": 0.0,
        "sharp_fark_ber": 0.0,
        "sharp_kitap":    "",
        "soft_kitap_n":   0,
        "sharp_tier":     "NO_SHARP",
        "max_fark":       0.0,
        "sinyal_gucunun_kaynagi": "veri_yok"
    }

    if not kitap_oranlari or len(kitap_oranlari) < 2:
        return sonuc_yok

    # ── 1. Sharp kitap oranlarını bul ─────────────────────────────────
    sharp_oran = None
    sharp_kitap_adi = ""
    for kitap in ["pinnacle", "betfair_ex_eu", "betfair", "matchbook"]:
        if kitap in kitap_oranlari:
            sharp_oran = kitap_oranlari[kitap]
            sharp_kitap_adi = kitap
            break

    if not sharp_oran:
        # Sharp kitap yoksa: soft kitaplar arası farktan sinyal çıkar
        # En düşük oranı veren kitap = en keskin fiyat
        return _soft_only_sinyal(kitap_oranlari)

    # ── 2. Soft kitapların ortalamasını hesapla ──────────────────────
    soft_ev_list  = []
    soft_ber_list = []
    soft_dep_list = []

    for kitap, oranlar in kitap_oranlari.items():
        if kitap in SHARP_KITAPLAR:
            continue  # Sharp kitapları soft havuzuna dahil etme
        ev_o, ber_o, dep_o = oranlar
        if ev_o > 1.0 and dep_o > 1.0:
            soft_ev_list.append(ev_o)
            soft_ber_list.append(ber_o)
            soft_dep_list.append(dep_o)

    soft_n = len(soft_ev_list)
    if soft_n < 1:
        # Sadece sharp kitap var, soft yok → karşılaştırma yapılamaz
        return sonuc_yok

    # Soft ortalama oranlar
    soft_ev  = sum(soft_ev_list)  / soft_n
    soft_ber = sum(soft_ber_list) / soft_n
    soft_dep = sum(soft_dep_list) / soft_n

    # ── 3. Vig-free implied probability hesapla ──────────────────────
    sharp_p_ev, sharp_p_ber, sharp_p_dep = _vig_free_probs(*sharp_oran)
    soft_p_ev,  soft_p_ber,  soft_p_dep  = _vig_free_probs(soft_ev, soft_ber, soft_dep)

    # ── 4. Farkları hesapla ──────────────────────────────────────────
    # Pozitif fark = Pinnacle bu tarafa DAHA YÜKSEK olasılık veriyor
    # = Sharp para bu tarafa akıyor
    fark_ev  = sharp_p_ev  - soft_p_ev
    fark_ber = sharp_p_ber - soft_p_ber
    fark_dep = sharp_p_dep - soft_p_dep

    # ── 5. En büyük pozitif farkı bul → o taraf sharp side ──────────
    farklar = {
        "EV":  fark_ev,
        "BER": fark_ber,
        "DEP": fark_dep,
    }

    en_buyuk_yon = max(farklar, key=farklar.get)
    en_buyuk_fark = farklar[en_buyuk_yon]

    # Eşik kontrolü
    if en_buyuk_fark < MIN_FARK_ESIK:
        return {
            "sharp_sinyal":  "YOK",
            "hareket_gucu":  0.0,
            "sharp_fark_ev":  round(fark_ev,  4),
            "sharp_fark_dep": round(fark_dep, 4),
            "sharp_fark_ber": round(fark_ber, 4),
            "sharp_kitap":    sharp_kitap_adi,
            "soft_kitap_n":   soft_n,
            "sharp_tier":     "NO_SHARP",
            "max_fark":       round(en_buyuk_fark, 4),
            "sinyal_gucunun_kaynagi": f"fark_yetersiz({en_buyuk_fark:.3f}<{MIN_FARK_ESIK})"
        }

    # ── 6. Sinyal gücü hesapla ───────────────────────────────────────
    if en_buyuk_fark >= COK_GUCLU_FARK:
        hareket_gucu = min(1.0, 0.70 + (en_buyuk_fark - COK_GUCLU_FARK) * 5)
        kaynak = f"cok_guclu_sharp({en_buyuk_fark:.3f})"
    elif en_buyuk_fark >= GUCLU_FARK:
        hareket_gucu = 0.40 + (en_buyuk_fark - GUCLU_FARK) * 8
        kaynak = f"guclu_sharp({en_buyuk_fark:.3f})"
    else:
        hareket_gucu = 0.15 + (en_buyuk_fark - MIN_FARK_ESIK) * 6
        kaynak = f"normal_sharp({en_buyuk_fark:.3f})"

    hareket_gucu = round(max(0.10, min(1.0, hareket_gucu)), 3)

    # Soft kitap sayısı güven çarpanı: 3+ soft kitap = tam güven
    guven = min(1.0, soft_n / 3.0)
    hareket_gucu = round(hareket_gucu * guven, 3)

    tier = sharp_tier(en_buyuk_fark)

    return {
        "sharp_sinyal":   en_buyuk_yon,
        "hareket_gucu":   hareket_gucu,
        "sharp_fark_ev":  round(fark_ev,  4),
        "sharp_fark_dep": round(fark_dep, 4),
        "sharp_fark_ber": round(fark_ber, 4),
        "sharp_kitap":    sharp_kitap_adi,
        "soft_kitap_n":   soft_n,
        "sharp_tier":     tier,
        "max_fark":       round(en_buyuk_fark, 4),
        "sinyal_gucunun_kaynagi": kaynak
    }


def _soft_only_sinyal(kitap_oranlari: dict) -> dict:
    """
    Sharp kitap yoksa: soft kitaplar arası konsensüs ve sapma analizi.
    En düşük ev oranı veren kitap sayısı vs en düşük dep oranı veren →
    çoğunluk hangi taraftaysa o tarafa zayıf sharp sinyal verir.
    """
    if len(kitap_oranlari) < 3:
        return {
            "sharp_sinyal": "YOK", "hareket_gucu": 0.0,
            "sharp_fark_ev": 0.0, "sharp_fark_dep": 0.0, "sharp_fark_ber": 0.0,
            "sharp_kitap": "", "soft_kitap_n": len(kitap_oranlari),
            "sinyal_gucunun_kaynagi": "sharp_kitap_yok"
        }

    ev_oranlar  = [v[0] for v in kitap_oranlari.values()]
    dep_oranlar = [v[2] for v in kitap_oranlari.values()]

    ort_ev  = sum(ev_oranlar)  / len(ev_oranlar)
    ort_dep = sum(dep_oranlar) / len(dep_oranlar)
    min_ev  = min(ev_oranlar)
    min_dep = min(dep_oranlar)

    # Konsensüs farkı: ortalama ile minimum arası
    sapma_ev  = (ort_ev  - min_ev)  / ort_ev  if ort_ev  > 0 else 0
    sapma_dep = (ort_dep - min_dep) / ort_dep if ort_dep > 0 else 0

    # Daha büyük sapma = daha güçlü konsensüs
    if sapma_ev > sapma_dep and sapma_ev > 0.03:
        return {
            "sharp_sinyal": "EV", "hareket_gucu": round(min(0.30, sapma_ev * 3), 3),
            "sharp_fark_ev": round(sapma_ev, 4), "sharp_fark_dep": round(-sapma_dep, 4),
            "sharp_fark_ber": 0.0,
            "sharp_kitap": "konsensus", "soft_kitap_n": len(kitap_oranlari),
            "sinyal_gucunun_kaynagi": f"soft_konsensus_ev({sapma_ev:.3f})"
        }
    elif sapma_dep > sapma_ev and sapma_dep > 0.03:
        return {
            "sharp_sinyal": "DEP", "hareket_gucu": round(min(0.30, sapma_dep * 3), 3),
            "sharp_fark_ev": round(-sapma_ev, 4), "sharp_fark_dep": round(sapma_dep, 4),
            "sharp_fark_ber": 0.0,
            "sharp_kitap": "konsensus", "soft_kitap_n": len(kitap_oranlari),
            "sinyal_gucunun_kaynagi": f"soft_konsensus_dep({sapma_dep:.3f})"
        }

    return {
        "sharp_sinyal": "YOK", "hareket_gucu": 0.0,
        "sharp_fark_ev": 0.0, "sharp_fark_dep": 0.0, "sharp_fark_ber": 0.0,
        "sharp_kitap": "", "soft_kitap_n": len(kitap_oranlari),
        "sinyal_gucunun_kaynagi": "sapma_yetersiz"
    }


# ════════════════════════════════════════════════════════════════════
#  2-YÖNLÜ SHARP SİNYAL (Alt/Üst, KG Var/Yok)
#  Goal Market'ler 2 seçenekli olduğu için ayrı fonksiyon gerekiyor.
# ════════════════════════════════════════════════════════════════════

def sharp_sinyal_hesapla_2way(kitap_oranlari: dict, pinnacle_var: bool = False,
                               opt1_name="OPT1", opt2_name="OPT2") -> dict:
    """
    İki ihtimalli pazarlar (Alt/Üst, KG) için Sharp Sinyali üretir.

    Parametreler:
        kitap_oranlari: {"pinnacle": (oran1, oran2), "bet365": (oran1, oran2)}
        pinnacle_var:   Pinnacle oranı mevcut mu
        opt1_name:      İlk seçenek adı (ör: "OVER", "BTTS_YES")
        opt2_name:      İkinci seçenek adı (ör: "UNDER", "BTTS_NO")

    Döndürür:
        {"sharp_sinyal": opt1_name|opt2_name|"YOK", "hareket_gucu": float, ...}
    """
    sonuc_yok = {
        "sharp_sinyal":  "YOK",
        "hareket_gucu":  0.0,
        "sharp_fark_1":  0.0,
        "sharp_fark_2":  0.0,
        "sharp_kitap":   "",
        "soft_kitap_n":  0,
        "sharp_tier":    "NO_SHARP",
        "max_fark":      0.0,
        "sinyal_gucunun_kaynagi": "veri_yok"
    }

    if not kitap_oranlari or len(kitap_oranlari) < 2:
        return sonuc_yok

    # Sharp kitap bul
    sharp_kitap_adi = None
    sharp_oranlar   = None

    if pinnacle_var and "pinnacle" in kitap_oranlari:
        sharp_kitap_adi = "pinnacle"
        sharp_oranlar = kitap_oranlari["pinnacle"]
    else:
        for s_kitap in SHARP_KITAPLAR:
            if s_kitap in kitap_oranlari:
                sharp_kitap_adi = s_kitap
                sharp_oranlar = kitap_oranlari[s_kitap]
                break

    if not sharp_oranlar:
        return sonuc_yok

    # Vig-free implied probability
    sharp_p1, sharp_p2 = _vig_free_probs_2way(sharp_oranlar[0], sharp_oranlar[1])

    soft_p1_toplam = 0.0
    soft_p2_toplam = 0.0
    soft_sayici    = 0

    for kitap_adi, oranlar in kitap_oranlari.items():
        if kitap_adi in SHARP_KITAPLAR:
            continue
        p1, p2 = _vig_free_probs_2way(oranlar[0], oranlar[1])
        soft_p1_toplam += p1
        soft_p2_toplam += p2
        soft_sayici += 1

    if soft_sayici == 0:
        return sonuc_yok

    ort_soft_p1 = soft_p1_toplam / soft_sayici
    ort_soft_p2 = soft_p2_toplam / soft_sayici

    fark_1 = sharp_p1 - ort_soft_p1
    fark_2 = sharp_p2 - ort_soft_p2

    en_buyuk_fark = 0.0
    sinyal = "YOK"

    if fark_1 > MIN_FARK_ESIK and fark_1 > fark_2:
        sinyal = opt1_name
        en_buyuk_fark = fark_1
    elif fark_2 > MIN_FARK_ESIK and fark_2 > fark_1:
        sinyal = opt2_name
        en_buyuk_fark = fark_2

    guc = 0.0
    if en_buyuk_fark >= TIER_ELITE:
        guc = 1.0
    elif en_buyuk_fark >= TIER_STRONG:
        guc = 0.8
    elif en_buyuk_fark >= TIER_WEAK:
        guc = 0.5

    return {
        "sharp_sinyal":  sinyal,
        "hareket_gucu":  guc,
        "sharp_fark_1":  round(fark_1, 4),
        "sharp_fark_2":  round(fark_2, 4),
        "sharp_kitap":   sharp_kitap_adi,
        "soft_kitap_n":  soft_sayici,
        "sharp_tier":    sharp_tier(en_buyuk_fark),
        "max_fark":      round(en_buyuk_fark, 4),
        "sinyal_gucunun_kaynagi": f"{sharp_kitap_adi} vs {soft_sayici} Soft"
    }
