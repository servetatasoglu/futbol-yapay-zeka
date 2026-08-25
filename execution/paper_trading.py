# analysis/paper_trading.py
"""
Paper Trading Engine — Sanal Para ile Sistem Doğrulama
══════════════════════════════════════════════════════════════════

Amaç:
  Sistemin gerçek para koymadan önce doğrulanması.
  200+ sanal bahis sonrasında CLV, ROI ve accuracy ölçülür.
  Ancak pozitif CLV kanıtlanırsa gerçek sermayeye geçilir.

Çalışma mantığı:
  1. Her run'da value_betler → paper_trading log'a yazılır
  2. Maç sonuçları API-Football'dan otomatik çekilir
  3. Sanal P&L, CLV ve accuracy her gün güncellenir
  4. Raporlar: hem terminal (yazdir) hem JSON (data/)

Log dosyaları:
  data/paper_trades.json    — tüm sanal bahisler
  data/paper_summary.json   — performans özeti
"""

import os
import json
import csv
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR    = os.path.join(BASE_DIR, "data")
LOGS_DIR    = os.path.join(BASE_DIR, "logs")
TRADES_PATH = os.path.join(DATA_DIR, "paper_trades.json")
SUMMARY_PATH= os.path.join(DATA_DIR, "paper_summary.json")

# Sanal başlangıç bankası (TL)
PAPER_BASLANGIC_BANKA = 10_000.0


# ════════════════════════════════════════════════════════════════
#  Durum Yönetimi
# ════════════════════════════════════════════════════════════════

def _trades_yukle() -> list:
    if not os.path.exists(TRADES_PATH):
        return []
    try:
        with open(TRADES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _trades_kaydet(trades: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(TRADES_PATH, "w", encoding="utf-8") as f:
        json.dump(trades, f, ensure_ascii=False, indent=2)


def _summary_yukle() -> dict:
    if not os.path.exists(SUMMARY_PATH):
        return {
            "baslangic_banka": PAPER_BASLANGIC_BANKA,
            "mevcut_banka":    PAPER_BASLANGIC_BANKA,
            "toplam_bahis":    0,
            "sonuclanan":      0,
            "kazanan":         0,
            "kaybeden":        0,
            "bekleyen":        0,
            "toplam_kar":      0.0,
            "roi_yuzde":       0.0,
            "max_banka":       PAPER_BASLANGIC_BANKA,
            "min_banka":       PAPER_BASLANGIC_BANKA,
            "max_drawdown":    0.0,
            "ort_clv":         0.0,
            "baslama_tarihi":  datetime.now(timezone.utc).isoformat(),
            "son_guncelleme":  datetime.now(timezone.utc).isoformat(),
        }
    try:
        with open(SUMMARY_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _summary_kaydet(s: dict):
    os.makedirs(DATA_DIR, exist_ok=True)
    s["son_guncelleme"] = datetime.now(timezone.utc).isoformat()
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


# ════════════════════════════════════════════════════════════════
#  Sanal Bahis Kaydet
# ════════════════════════════════════════════════════════════════

def paper_bahis_kaydet(
    ev: str,
    dep: str,
    lig: str,
    tahmin: str,
    oran: float,
    edge: float,
    olasilik: float,
    mac_tarihi: str,
    bahis_miktar: float = 0.0,   # 0 ise otomatik hesapla
    acilis_oran: float = 0.0,
    model_aciklamasi: str = "",
) -> dict:
    """
    Yeni bir sanal bahis kaydeder.
    
    Dönüş: Kaydedilen bahis sözlüğü (id dahil)
    """
    trades  = _trades_yukle()
    summary = _summary_yukle()

    # Aynı maç + tahmin zaten varsa kaydetme
    mevcut_anahtar = f"{ev}|{dep}|{tahmin}|{mac_tarihi}"
    for t in trades:
        if t.get("anahtar") == mevcut_anahtar:
            return t  # Zaten var

    # Bahis miktarı — sanal Kelly (%1 bankroll default)
    banka = summary.get("mevcut_banka", PAPER_BASLANGIC_BANKA)
    if bahis_miktar <= 0:
        bahis_miktar = round(banka * 0.01, 2)   # Sabit %1 (paper modda muhafazakar)
        bahis_miktar = max(50.0, min(bahis_miktar, banka * 0.02))

    trade_id = len(trades) + 1
    trade = {
        "id":               trade_id,
        "anahtar":          mevcut_anahtar,
        "kayit_tarihi":     datetime.now(timezone.utc).isoformat(),
        "mac_tarihi":       mac_tarihi,
        "ev":               ev,
        "dep":              dep,
        "lig":              lig,
        "tahmin":           tahmin,
        "oran":             round(oran, 3),
        "acilis_oran":      round(acilis_oran, 3),
        "edge":             round(edge, 4),
        "olasilik":         round(olasilik, 4),
        "bahis_miktar":     round(bahis_miktar, 2),
        "potansiyel_kazanc":round(bahis_miktar * (oran - 1), 2),
        "durum":            "bekliyor",   # bekliyor / kazandi / kaybetti / iptal
        "gercek_sonuc":     "",
        "kapanisoran":      0.0,
        "clv":              0.0,
        "kar_zarar":        0.0,
        "model_notu":       model_aciklamasi,
    }

    trades.append(trade)
    _trades_kaydet(trades)

    # Summary güncelle
    summary["toplam_bahis"] = summary.get("toplam_bahis", 0) + 1
    summary["bekleyen"]     = summary.get("bekleyen", 0) + 1
    _summary_kaydet(summary)

    print(f"  📝 [Paper] #{trade_id} — {ev} vs {dep} | {tahmin} | "
          f"oran={oran:.2f} | edge=%{edge*100:.1f} | {bahis_miktar:.0f} TL sanal")

    return trade


# ════════════════════════════════════════════════════════════════
#  Sonuç Güncelleme
# ════════════════════════════════════════════════════════════════

def sonuc_guncelle(trade_id: int, gercek_sonuc: str, kapanis_oran: float = 0.0) -> dict:
    """
    Bir sanal bahsin sonucunu günceller.

    Parametreler:
      trade_id     : Bahis ID'si
      gercek_sonuc : 'ev' / 'dep' / 'ber'
      kapanis_oran : Maçın kapanış oranı (CLV için)
    """
    trades  = _trades_yukle()
    summary = _summary_yukle()

    for t in trades:
        if t["id"] != trade_id or t["durum"] != "bekliyor":
            continue

        tahmin = t["tahmin"].lower()
        sonuc  = gercek_sonuc.lower()

        # Kazandı mı?
        kazandi = (
            ("ev" in tahmin and sonuc == "ev") or
            ("dep" in tahmin and sonuc == "dep") or
            ("beraber" in tahmin and sonuc == "ber")
        )

        miktar = t["bahis_miktar"]
        if kazandi:
            kar_zarar = round(miktar * (t["oran"] - 1), 2)
            t["durum"] = "kazandi"
        else:
            kar_zarar = -miktar
            t["durum"] = "kaybetti"

        t["gercek_sonuc"] = gercek_sonuc
        t["kar_zarar"]    = kar_zarar
        t["kapanisoran"]  = round(kapanis_oran, 3)

        # CLV hesapla
        if kapanis_oran > 1 and t["oran"] > 1:
            t["clv"] = round(t["oran"] / kapanis_oran - 1, 4)

        # Summary güncelle
        banka = summary.get("mevcut_banka", PAPER_BASLANGIC_BANKA) + kar_zarar
        summary["mevcut_banka"]  = round(banka, 2)
        summary["bekleyen"]      = max(0, summary.get("bekleyen", 0) - 1)
        summary["sonuclanan"]    = summary.get("sonuclanan", 0) + 1
        summary["toplam_kar"]    = round(summary.get("toplam_kar", 0) + kar_zarar, 2)

        if kazandi:
            summary["kazanan"] = summary.get("kazanan", 0) + 1
        else:
            summary["kaybeden"] = summary.get("kaybeden", 0) + 1

        if banka > summary.get("max_banka", banka):
            summary["max_banka"] = banka
        if banka < summary.get("min_banka", banka):
            summary["min_banka"] = banka

        # Drawdown
        max_b = summary.get("max_banka", PAPER_BASLANGIC_BANKA)
        if max_b > 0:
            dd = (max_b - banka) / max_b * 100
            summary["max_drawdown"] = round(max(summary.get("max_drawdown", 0), dd), 2)

        # ROI
        baslangic = summary.get("baslangic_banka", PAPER_BASLANGIC_BANKA)
        summary["roi_yuzde"] = round((banka - baslangic) / baslangic * 100, 2)

        # Ortalama CLV
        clv_listesi = [t2["clv"] for t2 in trades if t2.get("clv", 0) != 0]
        if clv_listesi:
            summary["ort_clv"] = round(sum(clv_listesi) / len(clv_listesi) * 100, 2)

        break

    _trades_kaydet(trades)
    _summary_kaydet(summary)
    return summary


# ════════════════════════════════════════════════════════════════
#  Otomatik Sonuç Çekme (API-Football)
# ════════════════════════════════════════════════════════════════

def api_sonuclari_guncelle():
    """
    Biten maçların sonuçlarını API-Football'dan otomatik çeker
    ve paper trading log'unu günceller.
    """
    try:
        from config.settings import FOOTBALL_DATA_KEY
    except ImportError:
        return

    if not FOOTBALL_DATA_KEY:
        return

    import requests

    trades  = _trades_yukle()
    simdi   = datetime.now(timezone.utc)
    guncellendi = 0

    # Sonucu beklenen maçları bul
    bekleyenler = [
        t for t in trades
        if t.get("durum") == "bekliyor" and t.get("mac_tarihi")
    ]

    for t in bekleyenler:
        try:
            mac_dt = datetime.fromisoformat(t["mac_tarihi"].replace("Z", "+00:00"))
            if mac_dt.tzinfo is None:
                mac_dt = mac_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        # Maç bitmemiş olabilir (90 dk + 90 dk ek süre)
        if simdi < mac_dt + timedelta(hours=2, minutes=30):
            continue

        # API-Football'dan sonuç çek
        tarih_str = mac_dt.strftime("%Y-%m-%d")
        url = (
            f"https://api.football-data.org/v4/matches"
            f"?dateFrom={tarih_str}&dateTo={tarih_str}"
        )
        try:
            headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            maclar = r.json().get("matches", [])
        except Exception:
            continue

        for mac in maclar:
            ev_api  = mac.get("homeTeam", {}).get("name", "")
            dep_api = mac.get("awayTeam", {}).get("name", "")
            skor    = mac.get("score", {}).get("fullTime", {})
            durum   = mac.get("status", "")

            if durum not in ("FINISHED", "FT"):
                continue

            # İsim eşleştir
            try:
                from data.matcher import isim_benzerlik
                esim = (
                    isim_benzerlik(t["ev"], ev_api) > 0.7 and
                    isim_benzerlik(t["dep"], dep_api) > 0.7
                )
            except ImportError:
                esim = (
                    t["ev"][:4].lower() in ev_api.lower() and
                    t["dep"][:4].lower() in dep_api.lower()
                )

            if not esim:
                continue

            ev_gol  = skor.get("home", 0) or 0
            dep_gol = skor.get("away", 0) or 0

            if ev_gol > dep_gol:
                gercek_sonuc = "ev"
            elif dep_gol > ev_gol:
                gercek_sonuc = "dep"
            else:
                gercek_sonuc = "ber"

            sonuc_guncelle(t["id"], gercek_sonuc)
            guncellendi += 1
            print(f"  ✅ [Paper] #{t['id']} {t['ev']} vs {t['dep']}: "
                  f"{ev_gol}-{dep_gol} → {gercek_sonuc}")
            break

    if guncellendi:
        print(f"  📊 Paper trading: {guncellendi} maç sonuçlandı")


# ════════════════════════════════════════════════════════════════
#  Value Bet Listesini Paper Trading'e Kaydet (Toplu)
# ════════════════════════════════════════════════════════════════

def value_betleri_paper_kaydet(value_betler: list) -> int:
    """
    value_betler listesindeki tüm tahminleri sanal olarak kaydeder.
    Dönüş: Kaydedilen yeni bahis sayısı
    """
    if not value_betler:
        return 0

    kaydedilen = 0
    for bet in value_betler:
        try:
            ev   = bet.get("ev", "")
            dep  = bet.get("dep", "")
            lig  = bet.get("lig_kodu", bet.get("lig", ""))
            tah  = bet.get("tahmin", "")
            oran = float(bet.get("oran", 0) or 0)
            edge = float(bet.get("edge", 0) or 0)
            olasi= float(bet.get("olasilik", 0) or bet.get("p", 0) or 0)
            tarih= bet.get("mac_tarihi", bet.get("tarih", ""))
            acilis=float(bet.get("acilis_oran", 0) or 0)
            not_ = bet.get("aciklamasi", bet.get("tahmin_aciklamasi", ""))

            if not ev or not dep or oran <= 1:
                continue

            sonuc = paper_bahis_kaydet(
                ev=ev, dep=dep, lig=lig, tahmin=tah,
                oran=oran, edge=edge, olasilik=olasi,
                mac_tarihi=tarih, acilis_oran=acilis,
                model_aciklamasi=not_,
            )
            if sonuc:
                kaydedilen += 1

        except Exception as e:
            print(f"  ⚠️  Paper kayıt hatası: {e}")

    return kaydedilen


# ════════════════════════════════════════════════════════════════
#  Rapor
# ════════════════════════════════════════════════════════════════

def paper_raporu() -> dict:
    """Paper trading özet raporu."""
    summary = _summary_yukle()
    trades  = _trades_yukle()

    # Lig bazlı performans
    lig_perf = defaultdict(lambda: {"n": 0, "kazanan": 0, "kar": 0.0})
    for t in trades:
        if t.get("durum") not in ("kazandi", "kaybetti"):
            continue
        lig = t.get("lig", "?")
        lig_perf[lig]["n"]       += 1
        lig_perf[lig]["kar"]     += t.get("kar_zarar", 0)
        if t["durum"] == "kazandi":
            lig_perf[lig]["kazanan"] += 1

    lig_ozet = {}
    for lig, d in lig_perf.items():
        lig_ozet[lig] = {
            "n":       d["n"],
            "acc":     round(d["kazanan"] / max(d["n"], 1) * 100, 1),
            "kar":     round(d["kar"], 2),
        }

    # Tahmin tipi performansı
    tip_perf = defaultdict(lambda: {"n": 0, "kazanan": 0})
    for t in trades:
        if t.get("durum") not in ("kazandi", "kaybetti"):
            continue
        tip = t.get("tahmin", "?")
        tip_perf[tip]["n"] += 1
        if t["durum"] == "kazandi":
            tip_perf[tip]["kazanan"] += 1

    # Bekleyen bahisler
    bekleyenler = [t for t in trades if t.get("durum") == "bekliyor"]

    return {
        **summary,
        "lig_bazli":    dict(lig_ozet),
        "tahmin_tipi":  {
            k: {"n": v["n"],
                "acc": round(v["kazanan"] / max(v["n"], 1) * 100, 1)}
            for k, v in tip_perf.items()
        },
        "bekleyen_listesi": [
            {"id": t["id"], "mac": f"{t['ev']} vs {t['dep']}",
             "tahmin": t["tahmin"], "oran": t["oran"],
             "tarih": t.get("mac_tarihi", "")[:10]}
            for t in bekleyenler[:10]  # En fazla 10 göster
        ],
    }


def paper_yazdir(rapor: dict = None):
    """Paper trading raporunu terminale yazdır."""
    if rapor is None:
        rapor = paper_raporu()

    SEP = "═" * 60
    print(f"\n{SEP}")
    print(f"  📋  PAPER TRADING RAPORU")
    print(SEP)

    banka     = rapor.get("mevcut_banka", PAPER_BASLANGIC_BANKA)
    baslangic = rapor.get("baslangic_banka", PAPER_BASLANGIC_BANKA)
    roi       = rapor.get("roi_yuzde", 0)
    sonuclanan= rapor.get("sonuclanan", 0)
    kazanan   = rapor.get("kazanan", 0)
    acc       = kazanan / max(sonuclanan, 1) * 100
    ort_clv   = rapor.get("ort_clv", 0)
    dd        = rapor.get("max_drawdown", 0)

    print(f"  Başlangıç banka   : {baslangic:,.0f} TL (sanal)")
    print(f"  Mevcut banka      : {banka:,.0f} TL")
    print(f"  Toplam P&L        : {banka-baslangic:+,.0f} TL  (%{roi:+.2f})")
    print(f"  Toplam bahis      : {rapor.get('toplam_bahis', 0)}")
    print(f"  Sonuçlanan        : {sonuclanan}  ({kazanan} kazandı)")
    print(f"  Accuracy          : %{acc:.1f}")
    print(f"  Ortalama CLV      : %{ort_clv:+.2f}")
    print(f"  Max Drawdown      : %{dd:.1f}")
    print(f"  Bekleyen          : {rapor.get('bekleyen', 0)}")

    # Lig bazlı
    lig_b = rapor.get("lig_bazli", {})
    if lig_b:
        print(f"\n  🏆 Lig Performansı:")
        for lig, d in sorted(lig_b.items(), key=lambda x: x[1]["kar"], reverse=True):
            ikon = "✅" if d["kar"] > 0 else "❌"
            print(f"    {ikon} {lig:<14} {d['n']} maç  "
                  f"%{d['acc']:.0f} acc  {d['kar']:+.0f} TL")

    # Karar
    print(f"\n  🎯 Sistem Durumu:")
    if sonuclanan < 50:
        print(f"  ⏳ Kanıtlama devam ediyor ({sonuclanan}/200 maç)")
        print(f"     Gerçek para için 200+ sonuçlanan bahis gerekiyor")
    elif ort_clv > 2.0 and roi > 0:
        print(f"  ✅ Sistem hazır — CLV pozitif, ROI pozitif")
        print(f"     Gerçek sermayeye geçiş değerlendirilebilir")
    elif ort_clv < -2.0:
        print(f"  🔴 CLV negatif — model veya zamanlama hatası var")
        print(f"     Gerçek para koyma! Modeli gözden geçir.")
    else:
        print(f"  🟡 Nötr — izlemeye devam ({sonuclanan}/200 maç)")

    print(SEP)


# ════════════════════════════════════════════════════════════════
#  Kolay Çağrı: main.py'den tek satırda kullan
# ════════════════════════════════════════════════════════════════

def paper_trading_calistir(value_betler: list):
    """
    Main.py'den çağrılacak ana fonksiyon:
    1. Mevcut sonuçları API'den güncelle
    2. Yeni value betleri kaydet
    3. Raporu yazdır
    """
    print(f"\n{'═'*60}")
    print(f"  📋  PAPER TRADING MOD AKTİF")
    print(f"{'═'*60}")

    # Önce bekleyen maçların sonuçlarını güncelle
    api_sonuclari_guncelle()

    # Yeni bahisleri kaydet
    yeni = value_betleri_paper_kaydet(value_betler)
    if yeni:
        print(f"  + {yeni} yeni sanal bahis kaydedildi")

    # Raporu göster
    paper_yazdir()
