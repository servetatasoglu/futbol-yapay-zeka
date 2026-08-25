# analysis/risk_limiter.py
"""
Risk Limiter — Aşama 5.2
═════════════════════════

Profesyonel risk yönetimi kuralları:
  1. Günde max 5 bahis
  2. Haftada max 20 bahis  
  3. Tek lig max %40 portföy (diversifikasyon)
  4. Max drawdown tetiklenirse otomatik bahis azaltma

KULLANIM:
  from risk.risk_limiter import risk_kontrol, gunluk_limit_uygula
  
  # Yeni bahisleri limite vur
  izinli = gunluk_limit_uygula(value_betler, "logs/tahminler_log.csv")
  
  # Risk durumunu kontrol et
  durum = risk_kontrol("logs/tahminler_log.csv")
"""

import csv
import os
from datetime import datetime, timedelta
from collections import Counter


# ── Limitler ─────────────────────────────────────────────────────
GUNLUK_MAX_BAHIS   = 5
HAFTALIK_MAX_BAHIS = 20
TEK_LIG_MAX_ORAN   = 0.40   # Tek lig portföyün max %40'ı
DRAWDOWN_AZALTMA   = 0.50   # Drawdown modunda bahis sayısı %50 azalır


def _bugunki_bahis_sayisi(log_dosyasi: str) -> int:
    """Log'dan bugün kaydedilmiş bahis sayısını bul."""
    bugun = datetime.now().strftime("%d.%m.%Y")
    sayac = 0
    if not os.path.exists(log_dosyasi):
        return 0
    with open(log_dosyasi, "r", encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            tarih = satir.get("Tarih", "").strip()
            if tarih.startswith(bugun):
                sayac += 1
    return sayac


def _haftalik_bahis_sayisi(log_dosyasi: str) -> int:
    """Log'dan son 7 günde kaydedilmiş bahis sayısını bul."""
    sayac = 0
    esik = datetime.now() - timedelta(days=7)
    if not os.path.exists(log_dosyasi):
        return 0
    with open(log_dosyasi, "r", encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            tarih_str = satir.get("Tarih", "").strip()
            for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%Y-%m-%d"):
                try:
                    tarih = datetime.strptime(tarih_str[:16], fmt)
                    if tarih >= esik:
                        sayac += 1
                    break
                except (ValueError, IndexError):
                    continue
    return sayac


def risk_kontrol(log_dosyasi: str = "logs/tahminler_log.csv") -> dict:
    """
    Mevcut risk durumunu kontrol et.
    
    Returns:
        {
            "gunluk_bahis": int,
            "haftalik_bahis": int,
            "gunluk_kalan": int,
            "haftalik_kalan": int,
            "bahis_izinli": bool,
            "mesaj": str,
            "uyarilar": list[str],
        }
    """
    gunluk = _bugunki_bahis_sayisi(log_dosyasi)
    haftalik = _haftalik_bahis_sayisi(log_dosyasi)

    # Drawdown kontrolü
    drawdown_modu = False
    try:
        from risk.bankroll import bankroll_raporu
        from config.settings import BANKROLL_BASLANGIC
        rapor = bankroll_raporu(log_dosyasi, BANKROLL_BASLANGIC)
        if rapor and isinstance(rapor, dict):
            dd = rapor.get("max_drawdown_yuzde", 0)
            if dd > 10:
                drawdown_modu = True
    except Exception:
        pass

    # Limitlerde drawdown azaltma
    eff_gunluk = int(GUNLUK_MAX_BAHIS * (1 - DRAWDOWN_AZALTMA)) if drawdown_modu else GUNLUK_MAX_BAHIS
    eff_haftalik = int(HAFTALIK_MAX_BAHIS * (1 - DRAWDOWN_AZALTMA)) if drawdown_modu else HAFTALIK_MAX_BAHIS

    gunluk_kalan = max(0, eff_gunluk - gunluk)
    haftalik_kalan = max(0, eff_haftalik - haftalik)
    izinli_bahis = min(gunluk_kalan, haftalik_kalan)

    uyarilar = []
    if drawdown_modu:
        uyarilar.append(f"⚠️ Drawdown modu: limitler %{DRAWDOWN_AZALTMA*100:.0f} azaltıldı (günlük {eff_gunluk}, haftalık {eff_haftalik})")
    if gunluk_kalan == 0:
        uyarilar.append(f"🔴 Günlük bahis limiti doldu ({gunluk}/{eff_gunluk})")
    if haftalik_kalan == 0:
        uyarilar.append(f"🔴 Haftalık bahis limiti doldu ({haftalik}/{eff_haftalik})")

    mesaj = f"Günlük: {gunluk}/{eff_gunluk} | Haftalık: {haftalik}/{eff_haftalik} | Kalan: {izinli_bahis}"

    return {
        "gunluk_bahis": gunluk,
        "haftalik_bahis": haftalik,
        "gunluk_kalan": gunluk_kalan,
        "haftalik_kalan": haftalik_kalan,
        "bahis_izinli": izinli_bahis > 0,
        "izinli_bahis": izinli_bahis,
        "drawdown_modu": drawdown_modu,
        "mesaj": mesaj,
        "uyarilar": uyarilar,
    }


def gunluk_limit_uygula(bahisler: list,
                          log_dosyasi: str = "logs/tahminler_log.csv") -> list:
    """
    Bahis listesine günlük/haftalık limit uygula.
    En yüksek edge'li bahisleri seçer, kalanı atar.
    Ayrıca tek lig %40 diversifikasyon kuralı uygular.
    
    Returns:
        Limitlere uyan bahis listesi (edge sıralı)
    """
    durum = risk_kontrol(log_dosyasi)

    if not durum["bahis_izinli"]:
        for u in durum["uyarilar"]:
            print(f"  {u}")
        return []

    max_bahis = durum["izinli_bahis"]

    # Edge sıralaması (en iyiler önce)
    sirali = sorted(bahisler, key=lambda x: x.get("efektif_edge", 0), reverse=True)

    # Diversifikasyon: tek lig max %40
    secilen = []
    lig_sayac = Counter()

    for b in sirali:
        if len(secilen) >= max_bahis:
            break

        lig = b.get("lig_kodu", "") or b.get("lig", "")

        # Tek lig max_oranı kontrolü
        lig_mevcut = lig_sayac[lig]
        toplam_mevcut = len(secilen) + 1
        if toplam_mevcut > 1:  # İlk bahiste kontrol yapma
            lig_oran = (lig_mevcut + 1) / toplam_mevcut
            if lig_oran > TEK_LIG_MAX_ORAN and lig_mevcut >= 2:
                continue  # Bu lig zaten çok fazla, atla

        secilen.append(b)
        lig_sayac[lig] += 1

    elenen = len(bahisler) - len(secilen)
    if elenen > 0:
        print(f"  🛡️ Risk limiti: {len(bahisler)} → {len(secilen)} bahis "
              f"(günlük:{durum['gunluk_kalan']}, haftalık:{durum['haftalik_kalan']})")

    return secilen


def risk_yazdir(log_dosyasi: str = "logs/tahminler_log.csv"):
    """Risk durumunu konsola yazdır."""
    durum = risk_kontrol(log_dosyasi)

    print(f"\n  🛡️ RİSK LİMİTLERİ:")
    print(f"     Günlük   : {durum['gunluk_bahis']}/{GUNLUK_MAX_BAHIS} bahis  "
          f"({'✅' if durum['gunluk_kalan'] > 0 else '🔴'} {durum['gunluk_kalan']} kalan)")
    print(f"     Haftalık : {durum['haftalik_bahis']}/{HAFTALIK_MAX_BAHIS} bahis  "
          f"({'✅' if durum['haftalik_kalan'] > 0 else '🔴'} {durum['haftalik_kalan']} kalan)")

    if durum["drawdown_modu"]:
        print(f"     ⚠️ Drawdown modu aktif — limitler %50 azaltıldı")

    for u in durum["uyarilar"]:
        print(f"     {u}")
