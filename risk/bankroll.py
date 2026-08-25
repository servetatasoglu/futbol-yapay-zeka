# analysis/bankroll.py
"""
Kelly Criterion Bankroll Yönetimi
───────────────────────────────────
Kelly Criterion: optimal bahis miktarını edge ve olasılığa göre hesaplar.
Sabit birim yerine banka büyüklüğüne göre dinamik bahis.

Half Kelly (1/2) → profesyonel standart.
Full Kelly çok agresif — model hatası olduğunda büyük kayıplar yaşatır.
Half Kelly uzun vadede Full Kelly'den daha iyi Sharpe ratio sağlar.

Kullanım:
    from risk.bankroll import kelly_hesapla, bankroll_raporu
    miktar = kelly_hesapla(olasilik=0.62, oran=2.10, banka=1000, fraksiyon=0.50)
"""

import csv
import os
import math
import random
import json
from datetime import datetime
from typing import Optional


# ── Sabitler ──────────────────────────────────────────────────
# 🔧 DÜZELTİLDİ: Quarter-Kelly (0.25) → 1/20-Kelly (0.05)
# settings.py ile senkronize: BANKROLL_KELLY_FRAKSIYON = 0.05
VARSAYILAN_FRAKSIYON   = 0.05   # 1/20 Kelly — paper-trading onaylanana kadar
# 🔧 DÜZELTİLDİ: Max bahis %4 → %2 — her hata max %2 kaybettirir
MAX_BAHIS_BANKA_ORANI  = 0.02   # Tek bahis bankın max %2'si
MIN_BAHIS_BANKA_ORANI  = 0.005  # Tek bahis bankın min %0.5'i
# 🔧 DÜZELTİLDİ: Stop-loss %25 → %20 — daha erken uyarı
STOP_LOSS_ORANI        = 0.20   # Banka %20 düşerse dur
MIN_BAHIS_TL           = 50.0   # Nesine/Misli alt limit koruması
BASLANGIC_KASA         = 5000.0 # Varsayılan kâr/zarar referans kasası
_BANKROLL_STATE_FILE   = os.path.join("data", "bankroll_state.json")


# ── Kalıcı Bankroll State ──────────────────────────────────────
def get_current_bankroll() -> float:
    """
    Kalıcı bankroll değerini JSON'dan okur.
    Dosya yoksa BASLANGIC_KASA'yı döndürür.
    """
    if os.path.exists(_BANKROLL_STATE_FILE):
        try:
            with open(_BANKROLL_STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return float(data.get("current_bankroll", BASLANGIC_KASA))
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return BASLANGIC_KASA


def update_bankroll(amount: float) -> float:
    """
    Bankroll'u `amount` kadar günceller (pozitif = kazanç, negatif = kayıp).
    Yeni bankroll değerini döndürür ve JSON'a yazar.
    """
    current = get_current_bankroll()
    new_val = current + amount
    new_val = max(0.0, new_val)
    os.makedirs(os.path.dirname(_BANKROLL_STATE_FILE) or ".", exist_ok=True)
    with open(_BANKROLL_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "current_bankroll": round(new_val, 2),
            "baslangic_kasa":   BASLANGIC_KASA,
            "updated_at":       datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)
    return new_val


def reset_bankroll(yeni_kasa: float = BASLANGIC_KASA) -> float:
    """Bankroll'u sıfırlar (yeni sezon veya manuel reset için)."""
    os.makedirs(os.path.dirname(_BANKROLL_STATE_FILE) or ".", exist_ok=True)
    with open(_BANKROLL_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "current_bankroll": round(yeni_kasa, 2),
            "baslangic_kasa":   yeni_kasa,
            "updated_at":       datetime.now().isoformat(),
        }, f, ensure_ascii=False, indent=2)
    return yeni_kasa


def kelly_hesapla(
    olasilik: float,
    oran: float,
    banka: float,
    fraksiyon: float = VARSAYILAN_FRAKSIYON,
) -> dict:
    """
    Kelly Criterion ile optimal bahis miktarı hesaplar.

    Formül: f* = (b*p - q) / b
        b = net kazanç (oran - 1)
        p = kazanma olasılığı
        q = kaybetme olasılığı (1 - p)

    Dönüş:
        kelly_tam:    Full Kelly bahis oranı (bankın %'si)
        kelly_fraksiyon: Fractional Kelly bahis oranı
        bahis_miktar: TL/birim olarak bahis miktarı
        risk_seviye:  "düşük" / "orta" / "yüksek"
    """
    if olasilik <= 0 or olasilik >= 1 or oran <= 1 or banka <= 0:
        return {"kelly_tam": 0, "kelly_fraksiyon": 0, "bahis_miktar": 0, "risk_seviye": "geçersiz"}

    b = oran - 1.0
    p = olasilik
    q = 1.0 - p

    kelly_tam = (b * p - q) / b

    if kelly_tam <= 0:
        return {"kelly_tam": 0, "kelly_fraksiyon": 0, "bahis_miktar": 0, "risk_seviye": "negatif_edge"}

    # Asimetrik fraksiyon: Kasayı koruma kalkanı
    # Kasa başlangıcın çok altındaysa fraksiyonu düşür, risk iştahını azalt
    kasa_durum_orani = banka / BASLANGIC_KASA
    dinamik_fraksiyon = fraksiyon
    if kasa_durum_orani < 0.8:
        dinamik_fraksiyon = fraksiyon * 0.5  # Kasa erimişse Kelly'yi yarıya indir (Quarter Kelly)
    elif kasa_durum_orani > 1.2:
        dinamik_fraksiyon = fraksiyon * 1.2  # Kârdaysak risk iştahını hafif artırabilir

    kelly_fraksiyon = kelly_tam * dinamik_fraksiyon

    # Sınırla: çok küçük veya çok büyük bahisleri engelle
    kelly_fraksiyon = max(MIN_BAHIS_BANKA_ORANI, min(MAX_BAHIS_BANKA_ORANI, kelly_fraksiyon))

    bahis_miktar = round(banka * kelly_fraksiyon, 2)
    
    # KULLANICI KURALI: Minimum bahis miktarı 50 TL olmalı
    # Eğer hesaplanan bahis miktarı 50 TL'nin altında kalıyorsa ve bakiye izin veriyorsa 50 TL'ye yuvarla
    if bahis_miktar > 0 and bahis_miktar < MIN_BAHIS_TL:
        if banka >= MIN_BAHIS_TL:
            bahis_miktar = MIN_BAHIS_TL
        else:
            # Banka tamamen erimişse (50 TL altı), elde kalanı bas
            bahis_miktar = banka

    if kelly_fraksiyon < 0.01:
        risk = "düşük"
    elif kelly_fraksiyon < 0.03:
        risk = "orta"
    else:
        risk = "yüksek"

    return {
        "kelly_tam":        round(kelly_tam,        4),
        "kelly_fraksiyon":  round(kelly_fraksiyon,  4),
        "kelly_yuzde":      round(kelly_fraksiyon * 100, 2),
        "bahis_miktar":     bahis_miktar,
        "risk_seviye":      risk,
    }


def value_bet_kelly(bet: dict, banka: float) -> dict:
    """
    Value bet dict'inden Kelly hesaplar.
    main.py'deki bet objesiyle doğrudan çalışır.
    """
    return kelly_hesapla(
        olasilik  = bet.get("olasilik", 0.5),
        oran      = bet.get("oran", 1.0),
        banka     = banka,
        fraksiyon = VARSAYILAN_FRAKSIYON,
    )


def stop_loss_kontrol(baslangic_banka: float, guncel_banka: float) -> dict:
    """
    Stop-loss kontrolü. Banka %20 düşerse uyarı ver (eskisi: %25).
    Stop-loss tetiklendiğinde 'bahis_dur': True döner.
    main.py bu flag'i okuyarak value_betler listesini sıfırlamalı.
    """
    kayip_orani = (baslangic_banka - guncel_banka) / baslangic_banka
    tetiklendi  = kayip_orani >= STOP_LOSS_ORANI
    return {
        "kayip_orani":  round(kayip_orani, 4),
        "kayip_yuzde":  round(kayip_orani * 100, 2),
        "tetiklendi":   tetiklendi,
        "bahis_dur":    tetiklendi,   # main.py bu flag'i kontrol eder
        "mesaj":        (
            f"⛔ STOP-LOSS: Banka %{kayip_orani*100:.1f} düştü — bahis önerileri devre dışı!"
            if tetiklendi
            else f"✅ Banka sağlıklı (%{kayip_orani*100:.1f} düşüş, limit %{STOP_LOSS_ORANI*100:.0f})"
        ),
    }


def bankroll_raporu(log_dosyasi: str, baslangic_banka: float = 100.0) -> dict:
    """
    Log dosyasından gerçekleşmiş bahisleri okuyarak banka gelişimini hesaplar.
    """
    if not os.path.exists(log_dosyasi):
        return {}

    banka       = baslangic_banka
    banka_serisi = [banka]
    toplam_bahis = 0
    kazanan      = 0
    max_banka    = banka
    min_banka    = banka
    max_drawdown = 0.0

    with open(log_dosyasi, "r", encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            sonuc = satir.get("GercekSonuc", "").strip()
            if not sonuc:
                continue

            try:
                olasilik = float(satir.get("Olasilik", 0) or 0)
                oran     = float(satir.get("Oran", 0) or 0)
            except ValueError:
                continue

            if olasilik <= 0 or oran <= 1:
                continue

            kelly = kelly_hesapla(olasilik, oran, banka)
            bahis = kelly["bahis_miktar"]

            tahmin = satir.get("Tahmin", "")
            sonuc_map = {
                "Ev Sahibi Kazanır": "ev",
                "Deplasman Kazanır": "dep",
                "Beraberlik":        "ber",
            }
            beklenen = sonuc_map.get(tahmin, "")
            kazandi  = (beklenen == sonuc or tahmin == sonuc)

            if kazandi:
                banka += bahis * (oran - 1)
                kazanan += 1
            else:
                banka -= bahis

            toplam_bahis += 1
            banka_serisi.append(round(banka, 2))

            if banka > max_banka:
                max_banka = banka
            if banka < min_banka:
                min_banka = banka

            drawdown = (max_banka - banka) / max_banka if max_banka > 0 else 0
            if drawdown > max_drawdown:
                max_drawdown = drawdown

    if toplam_bahis == 0:
        return {"mesaj": "Henüz gerçekleşmiş bahis yok"}

    roi = (banka - baslangic_banka) / baslangic_banka * 100
    stop = stop_loss_kontrol(baslangic_banka, banka)

    # ── Sharpe Ratio ────────────────────────────────────────────
    sharpe_ratio = _sharpe_hesapla(banka_serisi)

    # ── 95% Güven Aralığı (ROI) ─────────────────────────────────
    ci_95 = _roi_ci_hesapla(banka_serisi, baslangic_banka)

    # ── Monte Carlo Simülasyonu ─────────────────────────────────
    mc = _monte_carlo_sim(
        toplam_bahis, kazanan, baslangic_banka, banka_serisi
    )

    # ── Max Drawdown Süresi ─────────────────────────────────────
    max_dd_suresi = _max_drawdown_suresi(banka_serisi)

    return {
        "baslangic_banka":    baslangic_banka,
        "guncel_banka":       round(banka, 2),
        "toplam_bahis":       toplam_bahis,
        "kazanan":            kazanan,
        "accuracy":           round(kazanan / toplam_bahis * 100, 1),
        "roi_yuzde":          round(roi, 2),
        "max_banka":          round(max_banka, 2),
        "min_banka":          round(min_banka, 2),
        "max_drawdown_yuzde": round(max_drawdown * 100, 2),
        "max_drawdown_suresi": max_dd_suresi,
        "sharpe_ratio":       sharpe_ratio,
        "roi_ci_95":          ci_95,
        "monte_carlo":        mc,
        "stop_loss":          stop,
        "banka_serisi":       banka_serisi[-20:],  # Son 20 nokta
    }


def _sharpe_hesapla(banka_serisi: list) -> float:
    """
    Sharpe Ratio: Risksiz getiri üstü ortalama getiri / standart sapma.
    Yıllıklaştırılmış (aylık 30 bahis varsayımı × 12 ay = 360).
    
    Sharpe > 2.0: Mükemmel
    Sharpe > 1.5: Çok iyi
    Sharpe > 1.0: İyi
    Sharpe < 0.5: Zayıf
    """
    if len(banka_serisi) < 3:
        return 0.0

    # Bahis bazlı getiriler
    getiriler = []
    for i in range(1, len(banka_serisi)):
        onceki = banka_serisi[i - 1]
        if onceki > 0:
            getiriler.append((banka_serisi[i] - onceki) / onceki)

    if not getiriler:
        return 0.0

    ort = sum(getiriler) / len(getiriler)
    varyans = sum((g - ort) ** 2 for g in getiriler) / max(len(getiriler) - 1, 1)
    std = math.sqrt(varyans)

    if std < 1e-8:
        return 0.0

    # Yıllıklaştır: aylık ~30 bahis × 12 ay = 360 bahis/yıl
    bahis_per_yil = 360
    sharpe = (ort / std) * math.sqrt(bahis_per_yil)
    return round(sharpe, 2)


def _roi_ci_hesapla(banka_serisi: list, baslangic: float) -> dict:
    """
    95% Güven Aralığı — ROI'nin gerçek aralığını tahmin et.
    Bootstrap yöntemi ile hesaplanır.
    """
    if len(banka_serisi) < 10:
        return {"alt": 0, "ust": 0, "mesaj": "Yetersiz veri"}

    # Her bahis adımının getirisi
    getiriler = []
    for i in range(1, len(banka_serisi)):
        onceki = banka_serisi[i - 1]
        if onceki > 0:
            getiriler.append((banka_serisi[i] - onceki) / onceki)

    if len(getiriler) < 10:
        return {"alt": 0, "ust": 0, "mesaj": "Yetersiz getiri verisi"}

    # Bootstrap: 1000 örneklem al, her biri için ortalama ROI hesapla
    bootstrap_rois = []
    n = len(getiriler)
    for _ in range(1000):
        sample = [getiriler[random.randint(0, n - 1)] for _ in range(n)]
        bootstrap_rois.append(sum(sample) / len(sample) * 100)

    bootstrap_rois.sort()
    alt_idx = int(0.025 * len(bootstrap_rois))
    ust_idx = int(0.975 * len(bootstrap_rois))

    return {
        "alt": round(bootstrap_rois[alt_idx], 2),
        "ust": round(bootstrap_rois[ust_idx], 2),
        "mesaj": f"ROI %95 olasılıkla [{bootstrap_rois[alt_idx]:.1f}%, {bootstrap_rois[ust_idx]:.1f}%] arasında",
    }


def _monte_carlo_sim(
    toplam_bahis: int, kazanan: int,
    baslangic: float, banka_serisi: list,
    n_sim: int = 1000, n_bahis: int = 500
) -> dict:
    """
    Monte Carlo Bankroll Simülasyonu.
    Geçmiş performans parametrelerine göre gelecek 500 bahisi simüle et.
    
    Çıktılar:
      - İflas olasılığı (banka < %20 başlangıç)
      - İkiye katlama olasılığı
      - Medyan son banka
      - En kötü %5 sonuç
    """
    if toplam_bahis < 10 or kazanan < 1:
        return {"mesaj": "Yetersiz veri"}

    # Tarihsel parametreler
    win_rate = kazanan / toplam_bahis

    # Ortalama oran (banka serisinden türet)
    getiriler = []
    for i in range(1, len(banka_serisi)):
        if banka_serisi[i - 1] > 0:
            getiriler.append(banka_serisi[i] / banka_serisi[i - 1])

    # Kazanılan bahislerin ortalama getiri oranı
    kazanc_getirileri = [g for g in getiriler if g > 1.0]
    ort_kazanc = sum(kazanc_getirileri) / len(kazanc_getirileri) if kazanc_getirileri else 1.1
    # Kelly / sabit oran varsayımı
    bahis_orani = 0.02  # max %2

    son_bankalar = []
    iflas_sayisi = 0
    ikiye_katlama = 0

    random.seed(42)

    for _ in range(n_sim):
        banka = baslangic
        for _ in range(n_bahis):
            bahis = banka * bahis_orani
            if random.random() < win_rate:
                banka += bahis * (ort_kazanc - 1)
            else:
                banka -= bahis

            if banka < baslangic * 0.1:
                break

        son_bankalar.append(banka)
        if banka < baslangic * 0.2:
            iflas_sayisi += 1
        if banka >= baslangic * 2:
            ikiye_katlama += 1

    son_bankalar.sort()

    return {
        "iflas_olasiligi": round(iflas_sayisi / n_sim * 100, 1),
        "ikiye_katlama_olasiligi": round(ikiye_katlama / n_sim * 100, 1),
        "medyan_banka": round(son_bankalar[n_sim // 2], 2),
        "en_kotu_5_yuzde": round(son_bankalar[int(n_sim * 0.05)], 2),
        "en_iyi_5_yuzde": round(son_bankalar[int(n_sim * 0.95)], 2),
        "simulated_bahis": n_bahis,
    }


def _max_drawdown_suresi(banka_serisi: list) -> int:
    """
    En uzun ardışık kayıp serisi (bahis sayısı olarak).
    Model bozulma tespiti için önemli.
    """
    if len(banka_serisi) < 2:
        return 0

    max_sure = 0
    sure = 0
    for i in range(1, len(banka_serisi)):
        if banka_serisi[i] < banka_serisi[i - 1]:
            sure += 1
            max_sure = max(max_sure, sure)
        else:
            sure = 0

    return max_sure


def bankroll_yazdir(rapor: dict):
    if not rapor or "mesaj" in rapor:
        print(f"  ℹ️  {rapor.get('mesaj', 'Bankroll verisi yok')}")
        return

    SEP = "═" * 58
    print(f"\n{SEP}")
    print(f"  💰  BANKROLL RAPORU (Kelly Criterion)")
    print(SEP)
    print(f"  Başlangıç bankası : {rapor['baslangic_banka']:.2f} birim")
    print(f"  Güncel banka      : {rapor['guncel_banka']:.2f} birim")
    print(f"  ROI               : %{rapor['roi_yuzde']:.1f}")
    print(f"  Toplam bahis      : {rapor['toplam_bahis']}  |  Kazanan: {rapor['kazanan']}  (%{rapor['accuracy']:.1f})")
    print(f"  Max Drawdown      : %{rapor['max_drawdown_yuzde']:.1f}  ({rapor.get('max_drawdown_suresi', 0)} ardışık kayıp)")
    print(f"  Sharpe Ratio      : {rapor.get('sharpe_ratio', 0):.2f}")

    # Güven aralığı
    ci = rapor.get("roi_ci_95", {})
    if ci.get("alt") is not None and ci.get("ust") is not None:
        print(f"  %95 ROI CI        : [{ci['alt']:.1f}%, {ci['ust']:.1f}%]")

    # Monte Carlo
    mc = rapor.get("monte_carlo", {})
    if mc and "iflas_olasiligi" not in mc:
        pass
    elif mc:
        print()
        print(f"  📊 Monte Carlo ({mc.get('simulated_bahis', 500)} bahis simülasyonu):")
        print(f"     İflas risk      : %{mc['iflas_olasiligi']:.1f}")
        print(f"     2x katlama şansı: %{mc['ikiye_katlama_olasiligi']:.1f}")
        print(f"     Medyan banka    : {mc['medyan_banka']:.2f}")
        print(f"     En kötü %%5     : {mc['en_kotu_5_yuzde']:.2f}")
        print(f"     En iyi %%5      : {mc['en_iyi_5_yuzde']:.2f}")

    print(f"\n  Stop-Loss         : {rapor['stop_loss']['mesaj']}")
    print(SEP)