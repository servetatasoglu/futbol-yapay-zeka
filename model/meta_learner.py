# analysis/meta_learner.py
import os
import csv
import json
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, "logs", "tahminler_log.csv")
CEZA_FILE = os.path.join(BASE_DIR, "data", "meta_learner_cezalar.json")
CLV_CEZA_FILE = os.path.join(BASE_DIR, "data", "meta_learner_clv_cezalar.json")
CLV_LOG_FILE = os.path.join(BASE_DIR, "data", "clv_bet_log.json")

def _f(v, d=0.0):
    try: return float(v)
    except: return d

def meta_learner_egit(min_mac_sayisi=100) -> dict:
    """
    Sistemin kendi gecmis bahislerini tarayarak (Self-Reflection),
    Lig + Tahmin Tipi bazinda PnL (ROI) cikarir. Surekli zarar edilen (ROI < -0.10)
    alanlara bir 'ceza carpani' keser ki sistem ayni hataya bir daha dusmesin.
    """
    # BUG-9 DÜZELTMESİ: min_mac_sayisi=100 küçük liglerde (Ligue 1, Portuguesa)
    # hiçbir zaman ulaşılamıyor → ceza mekanizması çalışmıyor.
    # max(30, ...) ile lig bazlı dinamik eşik uygulanır.
    min_mac_sayisi = max(30, min_mac_sayisi)
    if not os.path.exists(LOG_FILE):
        return {}

    # lig_tahmin_key -> {"kazanan": 0, "toplam": 0, "yatirilan": 0.0, "pnl": 0.0}
    istatistikler = {}
    bahis_miktari = 1.0 # Oransal PCL

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            lig = satir.get("Lig", "Diger")
            tahmin = satir.get("Tahmin", "")
            sonuc = str(satir.get("GercekSonuc", "")).lower().strip()
            oran = _f(satir.get("Oran", 1.0))
            
            if not sonuc or sonuc == "bekliyor" or sonuc == "":
                continue # Oynanmamis/bekleyen mac
                
            anahtar = f"{lig}|{tahmin}"
            if anahtar not in istatistikler:
                istatistikler[anahtar] = {"kazanan": 0, "toplam": 0, "yatirilan": 0.0, "pnl": 0.0}
                
            istatistikler[anahtar]["toplam"] += 1
            istatistikler[anahtar]["yatirilan"] += bahis_miktari
            
            kazandi = False
            # 🔴 DENETİM DÜZELTME (31.03.2026): Türetilmiş bahisler kaldırıldı.
            # GercekSonuc sadece "ev", "dep", "ber" olabilir.
            # Eski "Üst/Alt/KG Var/Çifte Şans" eşleştirmeleri hiçbir zaman
            # doğru çalışmıyordu çünkü sonuc_guncelle.py bu değerleri yazmıyordu.
            if ("Ev" in tahmin and "Kazan" in tahmin and sonuc == "ev") or \
               ("Dep" in tahmin and "Kazan" in tahmin and sonuc == "dep") or \
               ("Beraberlik" in tahmin and sonuc == "ber"):
                kazandi = True
                
            if kazandi:
                istatistikler[anahtar]["kazanan"] += 1
                istatistikler[anahtar]["pnl"] += (oran * bahis_miktari) - bahis_miktari
            else:
                istatistikler[anahtar]["pnl"] -= bahis_miktari

    cezalar = {}
    
    for anahtar, stat in istatistikler.items():
        if stat["toplam"] >= min_mac_sayisi:
            roi = stat["pnl"] / stat["yatirilan"]
            hit_rate = stat["kazanan"] / stat["toplam"]
            
            # Modelin berbat oldugu yerler kacinilmaz olarak ceza yemeli
            ceza_katsayisi = 1.0
            
            # %15'ten fazla zarar ediyorsa edge baraji yukseltilsin (katsayi 1.25)
            if roi < -0.15:
                ceza_katsayisi = 1.25
            elif roi < -0.05:
                ceza_katsayisi = 1.10
            # %20'den fazla kar ediyorsa edge baraji dusurulsun (katsayi 0.90)
            elif roi > 0.20:
                ceza_katsayisi = 0.90
                
            cezalar[anahtar] = {
                "toplam_mac": stat["toplam"],
                "hit_rate": round(hit_rate, 3),
                "roi": round(roi, 3),
                "ceza_katsayisi": ceza_katsayisi
            }
            
    os.makedirs(os.path.dirname(CEZA_FILE), exist_ok=True)
    with open(CEZA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "son_guncelleme": datetime.now().isoformat(),
            "kurallar": cezalar
        }, f, indent=4)
        
    return cezalar

def clv_meta_egit(min_mac_sayisi=10) -> dict:
    """
    Sistemin CLV (Closing Line Value) geçmişini tarayarak anlık ceza/ödül çıkarır.
    PnL (ROI) için binlerce maç gerekirken, CLV 10 maçta bile anlamlı trend verir.
    """
    if not os.path.exists(CLV_LOG_FILE):
        return {}

    try:
        with open(CLV_LOG_FILE, "r", encoding="utf-8") as f:
            clv_db = json.load(f)
    except Exception:
        return {}

    bahisler = clv_db.get("bahisler", [])
    istatistikler = {}

    for b in bahisler:
        clv_degeri = b.get("clv")
        if clv_degeri is None:
            continue
            
        lig = b.get("lig", "Diger")
        tahmin = b.get("tahmin", "")
        anahtar = f"{lig}|{tahmin}"
        
        if anahtar not in istatistikler:
            istatistikler[anahtar] = {"toplam": 0, "clv_toplam": 0.0}
            
        istatistikler[anahtar]["toplam"] += 1
        istatistikler[anahtar]["clv_toplam"] += float(clv_degeri)

    cezalar = {}
    for anahtar, stat in istatistikler.items():
        if stat["toplam"] >= min_mac_sayisi:
            ort_clv = stat["clv_toplam"] / stat["toplam"]
            ceza_katsayisi = 1.0
            
            # CLV %-2'den kötüyse Edge zorlaştır (Ceza)
            if ort_clv <= -0.02:
                ceza_katsayisi = 1.30
            elif ort_clv <= -0.01:
                ceza_katsayisi = 1.15
            # CLV %+2'den iyiyse Edge rahatlat (Ödül)
            elif ort_clv >= 0.02:
                ceza_katsayisi = 0.85

            cezalar[anahtar] = {
                "toplam_mac": stat["toplam"],
                "ort_clv": round(ort_clv, 4),
                "ceza_katsayisi": ceza_katsayisi
            }

    os.makedirs(os.path.dirname(CLV_CEZA_FILE), exist_ok=True)
    with open(CLV_CEZA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "son_guncelleme": datetime.now().isoformat(),
            "kurallar": cezalar
        }, f, indent=4)
        
    return cezalar


def meta_ceza_uygula(lig: str, tahmin: str, esik: float) -> float:
    """
    Hem eski ROI (PnL) cezalarını, hem de yeni CLV cezalarını birleştirerek
    Edge (Değer) barajını dinamik olarak günceller.
    """
    final_esik = esik
    anahtar = f"{lig}|{tahmin}"

    # 1. Klasik ROI Cezası
    if os.path.exists(CEZA_FILE):
        try:
            with open(CEZA_FILE, "r") as f:
                veri = json.load(f)
            kural = veri.get("kurallar", {}).get(anahtar)
            if kural:
                final_esik *= kural.get("ceza_katsayisi", 1.0)
        except Exception:
            pass

    # 2. Yeni CLV Cezası/Ödülü
    if os.path.exists(CLV_CEZA_FILE):
        try:
            with open(CLV_CEZA_FILE, "r") as f:
                veri = json.load(f)
            kural = veri.get("kurallar", {}).get(anahtar)
            if kural:
                final_esik *= kural.get("ceza_katsayisi", 1.0)
        except Exception:
            pass
            
    return round(final_esik, 4)

if __name__ == "__main__":
    print("🧠 Meta-Learner (Kendi Hatasından Öğrenme) Modeli Başlatıldı...")
    sonuc = meta_learner_egit(min_mac_sayisi=100)
    for a, k in sonuc.items():
        durum = "🔴 CEZA" if k['ceza_katsayisi'] > 1.0 else "🟢 ÖDÜL" if k['ceza_katsayisi'] < 1.0 else "⚪ NÖTR"
        print(f"[{a:25s}] Toplam: {k['toplam_mac']:3d} | HitRate: %{k['hit_rate']*100:4.1f} | ROI: %{k['roi']*100:5.1f} -> {durum} (Katsayı: {k['ceza_katsayisi']})")
# -------------------------------------------------------------
# GERİYE DÖNÜK UYUMLULUK (model_birlestir.py bağımlılıkları)
# -------------------------------------------------------------

def adaptif_agirlik_hesapla(ev_mac, dep_mac, ev_elo, dep_elo, lam_ev, lam_dep, ev_form, dep_form, h2h):
    """
    CLV-informed adaptif ağırlık hesapla.
    
    3 katman:
      Katman 1: Veri miktarına göre temel ağırlıklar
      Katman 2: Maç özelliklerine göre ayarlama
      Katman 3: CLV feedback'ten öğrenilen güven çarpanları
    """
    min_mac = min(ev_mac, dep_mac)
    elo_fark = abs(ev_elo - dep_elo)
    
    # ── Katman 1: Temel ağırlıklar (veri miktarına göre) ─────
    w_elo = 0.30
    w_poisson = 0.45
    w_mc = 0.15
    w_form = 0.10
    
    if min_mac < 8:
        w_elo = 0.50; w_poisson = 0.25; w_mc = 0.15; w_form = 0.10
    elif min_mac < 15:
        w_elo = 0.40; w_poisson = 0.35; w_mc = 0.15; w_form = 0.10
    elif min_mac > 40:
        w_elo = 0.25; w_poisson = 0.50; w_mc = 0.15; w_form = 0.10
    
    # ── Katman 2: Maç özelliklerine göre ayarla ──────────────
    if elo_fark > 250:
        w_elo = min(w_elo + 0.10, 0.60)
        w_poisson = max(w_poisson - 0.05, 0.20)
        w_mc = max(w_mc - 0.05, 0.10)
    
    ev_form_val = ev_form.get("form_puan", 0.5) if isinstance(ev_form, dict) else 0.5
    dep_form_val = dep_form.get("form_puan", 0.5) if isinstance(dep_form, dict) else 0.5
    form_fark = abs(ev_form_val - dep_form_val)
    if form_fark > 0.25:
        w_form = min(w_form + 0.05, 0.15)
        w_poisson = max(w_poisson - 0.05, 0.20)
    
    # ── Katman 3: CLV Feedback — öğrenilen güven çarpanları ──
    try:
        from tracking.learner import model_agirlik_onerisi
        clv_guven = model_agirlik_onerisi()
        w_elo *= clv_guven.get("elo_guven", 1.0)
        w_poisson *= clv_guven.get("poisson_guven", 1.0)
        w_form *= clv_guven.get("form_guven", 1.0)
        # mc_guven could be added in future, assume 1.0 for now
    except Exception:
        pass  # learner yoksa nötr devam
    
    # Normalize
    toplam = w_elo + w_poisson + w_form + w_mc
    w_elo /= toplam
    w_poisson /= toplam
    w_form /= toplam
    w_mc /= toplam
    
    return {"elo": round(w_elo, 3), "poisson": round(w_poisson, 3), "mc": round(w_mc, 3), "form": round(w_form, 3)}

def model_birlestir_v3(elo_p, poisson_p, mc_p, ev_form, dep_form, h2h, agirliklar, ber_kalibrasyon):
    w_e = agirliklar.get("elo", 0.30)
    w_p = agirliklar.get("poisson", 0.45)
    w_m = agirliklar.get("mc", 0.15)
    w_f = agirliklar.get("form", 0.10)
    
    # BUG FIX: Monte Carlo was calculated but completely ignored in 1X2 blending.
    hw = elo_p["home_win"] * w_e + poisson_p["home_win"] * w_p + mc_p.get("home_win", 0.33) * w_m
    aw = elo_p["away_win"] * w_e + poisson_p["away_win"] * w_p + mc_p.get("away_win", 0.33) * w_m
    
    # ber_kalibrasyon h2h_model'den dict olarak dönebilir
    if isinstance(ber_kalibrasyon, dict):
        dr_base = ber_kalibrasyon.get("draw", 0.25)
    else:
        dr_base = float(ber_kalibrasyon)
        
    dr = dr_base * (1 - w_m) + mc_p.get("draw", 0.33) * w_m
    
    e_f = ev_form.get("form_puan", 0.5) if isinstance(ev_form, dict) else float(ev_form)
    d_f = dep_form.get("form_puan", 0.5) if isinstance(dep_form, dict) else float(dep_form)
    hw += (e_f - d_f) * 0.02
    aw += (d_f - e_f) * 0.02
    
    t = hw + aw + dr
    if t <= 0: t = 1
    
    return {
        "home_win": hw / t,
        "draw": dr / t,
        "away_win": aw / t
    }

def feature_vektor(ev_takim_db, dep_takim_db, elo_p, poisson_p, mc_p, ev_form, dep_form, h2h, ev_elo, dep_elo, agirliklar):
    return {
        "ev_elo": ev_elo,
        "dep_elo": dep_elo,
        "ev_form": ev_form,
        "dep_form": dep_form,
        "elo_hw": elo_p["home_win"],
        "poisson_hw": poisson_p["home_win"]
    }
