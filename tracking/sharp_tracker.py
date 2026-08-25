# analysis/market_model.py
"""
Market Model — Sharp Money & Oran Hareketi Analizi
══════════════════════════════════════════════════════════════════

Sharp money tracking için 3 temel sinyal:
  1. Oran hareketi yönü (Pinnacle line movement)
  2. Line reversal: oran hareket edip geri dönmüş mü?
  3. Steam move: kısa sürede büyük hareket = sharp bet

Dünya standardı: Piyasayı yönlendiren sharp bettor'lar
Pinnacle ve Betfair'de işlem yapar. Onların oran hareketi
"hangi tarafın kazanacağını" gösterir.

Kaynaklar:
  - The Odds API (canlı + tarihsel oran hareketi)
  - odds_cache.json (yerel cache)
"""

import os
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

MARKET_CACHE_PATH = os.path.join(DATA_DIR, "market_model_cache.json")
ODDS_CACHE_PATH   = os.path.join(DATA_DIR, "odds_cache.json")


# ════════════════════════════════════════════════════════════════
#  Oran Hareketi Analizi
# ════════════════════════════════════════════════════════════════

def oran_hareketi_analiz(mac: dict) -> dict:
    """
    Bir maç için oran hareketi analizi yapar.
    
    Parametreler:
      mac: {"ev": str, "dep": str, "ev_oran": float, "dep_oran": float,
            "ilk_ev_oran": float, "ilk_dep_oran": float, ...}
    
    Dönüş:
      sharp_sinyal: "EV" / "DEP" / "YOK"
      hareket_gucu: 0.0 - 1.0 (güç skoru)
      steam_move: bool (hızlı büyük hareket)
    """
    ev_oran      = float(mac.get("ev_oran", 0) or 0)
    dep_oran     = float(mac.get("dep_oran", 0) or 0)
    ilk_ev_oran  = float(mac.get("ilk_ev_oran", 0) or mac.get("ev_oran", 0) or 0)
    ilk_dep_oran = float(mac.get("ilk_dep_oran", 0) or mac.get("dep_oran", 0) or 0)

    if ev_oran <= 1 or dep_oran <= 1:
        return {"sharp_sinyal": "YOK", "hareket_gucu": 0.0, "steam_move": False,
                "aciklama": "Geçerli oran yok"}

    # Oran hareketi hesapla
    ev_hare  = 0.0 if ilk_ev_oran <= 1 else (ev_oran  - ilk_ev_oran)  / ilk_ev_oran
    dep_hare = 0.0 if ilk_dep_oran <= 1 else (dep_oran - ilk_dep_oran) / ilk_dep_oran

    # Oran aşağı giderse → o tarafa para akıyor (daha az paya düşüyor)
    # Oran aşağı gidince piyasa o tarafı "daha az değerli" görüyor
    # Sharp para: oran düşen taraf = favori güçlendi = o tarafa bahis
    # Oran düşüyor = implied probability artıyor = o tarafa şiddetli alım var

    # EV tarafına para giriyor mu?
    if ev_hare < -0.03:   # Ev oranı %3+ düştü
        sharp_sinyal = "EV"
        hareket_gucu = min(1.0, abs(ev_hare) * 10)
        steam = abs(ev_hare) >= 0.07  # %7+ hızlı = steam move
    elif dep_hare < -0.03:  # Dep oranı %3+ düştü
        sharp_sinyal = "DEP"
        hareket_gucu = min(1.0, abs(dep_hare) * 10)
        steam = abs(dep_hare) >= 0.07
    else:
        sharp_sinyal = "YOK"
        hareket_gucu = 0.0
        steam = False

    # Line reversal: oran önce aşağı gitti, sonra geri döndü mü?
    # (Bu olursa orijinal hareket noise'du, gerçek sharp değil)
    reversal = False
    if sharp_sinyal != "YOK":
        if sharp_sinyal == "EV" and ev_hare > -0.01:   reversal = True
        if sharp_sinyal == "DEP" and dep_hare > -0.01: reversal = True

    aciklama_parcalar = []
    if steam:
        aciklama_parcalar.append(f"🚨 Steam move ({'EV' if ev_hare < 0 else 'DEP'})")
    if sharp_sinyal != "YOK":
        taraf_hare = ev_hare if sharp_sinyal == "EV" else dep_hare
        aciklama_parcalar.append(f"Sharp para → {sharp_sinyal} (%{taraf_hare*100:+.1f} oran hareketi)")
    if reversal:
        aciklama_parcalar.append("⚠️ Line reversal — dikkat")
    if not aciklama_parcalar:
        aciklama_parcalar.append("Belirgin sharp hareketi yok")

    return {
        "sharp_sinyal":  sharp_sinyal,
        "hareket_gucu":  round(hareket_gucu, 3),
        "steam_move":    steam,
        "line_reversal": reversal,
        "ev_hare_pct":   round(ev_hare  * 100, 2),
        "dep_hare_pct":  round(dep_hare * 100, 2),
        "aciklama":      " | ".join(aciklama_parcalar),
    }


def sharp_square_orani(mac_listesi: list) -> dict:
    """
    Bir lig/kategori için sharp vs square para oranını hesapla.
    
    Sharp para = %3+ oran hareketi olan bahisler
    Square para = oran hareketi < %1 olan bahisler
    """
    sharp_count  = 0
    square_count = 0
    toplam       = len(mac_listesi)

    for mac in mac_listesi:
        analiz = oran_hareketi_analiz(mac)
        if analiz["hareket_gucu"] >= 0.3:
            sharp_count += 1
        elif analiz["hareket_gucu"] < 0.1:
            square_count += 1

    return {
        "toplam":       toplam,
        "sharp_n":      sharp_count,
        "square_n":     square_count,
        "sharp_oran":   round(sharp_count / max(toplam, 1) * 100, 1),
        "piyasa_tipi":  (
            "🦅 Aktif Sharp Piyasa" if sharp_count / max(toplam, 1) > 0.3
            else "🐑 Square Piyasa"
        ),
    }


# ════════════════════════════════════════════════════════════════
#  Piyasa Verimliliği Skoru
# ════════════════════════════════════════════════════════════════

def piyasa_verimlilik_skoru(mac: dict) -> float:
    """
    Piyasanın o anki verimliliğini ölç (0-1 arası).
    
    Verimli piyasa = Sharp book + küçük marj + çok bahisçi
    Verimsiz piyasa = Sadece soft bookmaker + büyük marj + az bahisçi
    
    Edge hesabı: Verimsiz piyasada edge daha güvenilir.
    Verimli piyasada (Pinnacle) edge kanıtlanmış demektir.
    """
    over_round   = float(mac.get("over_round", 1.08) or 1.08)
    bahisci_n    = int(mac.get("kitap_sayisi", 1) or 1)
    pinnacle_var = bool(mac.get("pinnacle_var", False))
    bf_var       = bool(mac.get("betfair_var",  False))

    # Marj skoru: düşük marj = verimli piyasa
    if over_round <= 1.03:   marj_sk = 1.0
    elif over_round <= 1.05: marj_sk = 0.85
    elif over_round <= 1.07: marj_sk = 0.65
    elif over_round <= 1.10: marj_sk = 0.40
    else:                     marj_sk = 0.20

    # Bahisçi çeşitliliği
    if bahisci_n >= 20:   bookie_sk = 1.0
    elif bahisci_n >= 10: bookie_sk = 0.7
    elif bahisci_n >= 5:  bookie_sk = 0.5
    else:                  bookie_sk = 0.2

    # Sharp book varlığı
    sharp_sk = 0.0
    if pinnacle_var: sharp_sk += 0.6
    if bf_var:       sharp_sk += 0.4
    sharp_sk = min(1.0, sharp_sk)

    # Ağırlıklı skor
    verimlilik = 0.4 * marj_sk + 0.3 * bookie_sk + 0.3 * sharp_sk
    return round(verimlilik, 3)


def edge_guvenilik_skoru(edge: float, mac: dict) -> dict:
    """
    Edge'in güvenilirliğini piyasa verimliliğine göre ölçer.

    Mantık:
      - Pinnacle'da edge varsa → gerçek edge (piyasa zaten verimli)
      - Sadece soft booklarda edge varsa → şüpheli (piyasa verimsiz olduğu için)
      
    Bu Pinnacle arbitraj metodolojisiyle uyumlu.
    """
    verimlilik   = piyasa_verimlilik_skoru(mac)
    pinnacle_var = bool(mac.get("pinnacle_var", False))

    if edge <= 0:
        return {"guvenilir": False, "guvenilik": 0.0, "mesaj": "Negatif edge"}

    if pinnacle_var and verimlilik > 0.7:
        guvenilik = min(1.0, edge * 10 * verimlilik)
        return {
            "guvenilir": guvenilik > 0.3,
            "guvenilik": round(guvenilik, 3),
            "mesaj":      f"✅ Pinnacle edge — güvenilir (%{edge*100:.1f})",
        }
    elif verimlilik < 0.4:
        # Soft bookmaker — edge büyük görünse de gerçek değil
        guvenilik = edge * 4  # Sert discount
        return {
            "guvenilir": guvenilik > 0.3,
            "guvenilik": round(guvenilik, 3),
            "mesaj":      f"⚠️  Soft book edge — %60 discount uygulandı",
        }
    else:
        guvenilik = edge * 7 * verimlilik
        return {
            "guvenilir": guvenilik > 0.3,
            "guvenilik": round(guvenilik, 3),
            "mesaj":      f"🟡 Orta güvenilir edge (piyasa verimliliği: {verimlilik:.2f})",
        }


# ════════════════════════════════════════════════════════════════
#  Market Model Özet Raporu
# ════════════════════════════════════════════════════════════════

def market_model_raporu(mac_listesi: list) -> str:
    if not mac_listesi:
        return "  ℹ️  Market model: maç listesi boş"

    adetler = {"sharp": 0, "steam": 0, "reversal": 0, "pinnacle": 0}
    for mac in mac_listesi:
        analiz = oran_hareketi_analiz(mac)
        if analiz["hareket_gucu"] > 0.3:   adetler["sharp"] += 1
        if analiz["steam_move"]:            adetler["steam"] += 1
        if analiz["line_reversal"]:         adetler["reversal"] += 1
        if mac.get("pinnacle_var"):         adetler["pinnacle"] += 1

    SEP = "═" * 50
    lines = [
        f"\n{SEP}",
        f"  🦅  MARKET MODEL RAPORU",
        f"{SEP}",
        f"  Toplam maç          : {len(mac_listesi)}",
        f"  Sharp para sinyali  : {adetler['sharp']}",
        f"  Steam move          : {adetler['steam']}",
        f"  Line reversal       : {adetler['reversal']}",
        f"  Pinnacle referanslı : {adetler['pinnacle']}",
        SEP,
    ]
    return "\n".join(lines)
