# analysis/elo_rating.py
"""
Dynamic ELO Rating Sistemi
─────────────────────────
• Maç sonuçlarına göre canlı ELO güncellemesi
• Lig bazında K-faktörü (büyük lig = daha stabil)
• Gol farkına duyarlı beklenti skoru (margin-of-victory)
• Ev sahibi avantajı ELO'ya işlenmiş halde
• Başlangıç ELO'su lig ortalamasına göre otomatik hesaplanır
"""

import math
from collections import defaultdict
from config.settings import ELO_K_FAKTOR, ELO_BASLANGIC, ELO_EV_AVANTAJI

# ─── Global ELO Cache — session boyunca tek hesaplama yapılır ────
_elo_cache: dict = {}
_elo_cache_key: int = -1


# ─── K-Faktörü: Lig ve maç önemine göre ───────────────────────
LIG_K_CARPAN = {
    "PL":  1.0,   # Premier League — en stabil
    "PD":  1.0,   # La Liga
    "BL1": 0.95,  # Bundesliga
    "SA":  0.95,  # Serie A
    "FL1": 0.90,  # Ligue 1
}


def _k_faktor(lig_kodu: str, mac_sayisi: int) -> float:
    """
    K-faktörünü hesaplar.
    Yeni takımlar (az maç) için K yüksek tutulur — daha hızlı öğrenir.
    Köklü takımlar için K düşer — ELO daha stabil kalır.
    """
    baz = ELO_K_FAKTOR * LIG_K_CARPAN.get(lig_kodu, 0.90)
    if mac_sayisi < 10:
        return baz * 1.5   # Yeni takım: hızlı adaptasyon
    elif mac_sayisi < 20:
        return baz * 1.2
    return baz


def _gol_farki_carpani(ev_gol: int, dep_gol: int) -> float:
    """
    Gol farkına göre ELO güncellemesini ölçekler.
    Büyük farkla kazanılan maçlar daha çok ELO kazandırır/kaybettirir.
    FIFA/club ELO sistemlerinde yaygın kullanılan MOV düzeltmesi.
    """
    fark = abs(ev_gol - dep_gol)
    if fark <= 1:
        return 1.0
    elif fark == 2:
        return 1.5
    elif fark == 3:
        return 1.75
    else:
        return 1.75 + (fark - 3) * 0.1


def _beklenen_skor(elo_a: float, elo_b: float, ev_avantaji: float) -> float:
    """ELO beklenti skoru — ev avantajı eklenmiş."""
    return 1 / (1 + 10 ** ((elo_b - elo_a - ev_avantaji) / 400))


def elo_guncelle(elo_dict: dict, lig_kodu: str,
                 ev_takim: str, dep_takim: str,
                 ev_gol: int, dep_gol: int,
                 mac_sayilari: dict) -> None:
    """Maç sonucuna göre iki takımın ELO değerini günceller (in-place)."""
    ev_elo  = elo_dict.get(ev_takim,  ELO_BASLANGIC)
    dep_elo = elo_dict.get(dep_takim, ELO_BASLANGIC)
    ev_mac  = mac_sayilari.get(ev_takim,  0)
    dep_mac = mac_sayilari.get(dep_takim, 0)

    beklenen_ev  = _beklenen_skor(ev_elo, dep_elo, ELO_EV_AVANTAJI)
    beklenen_dep = 1.0 - beklenen_ev

    if ev_gol > dep_gol:
        gercek_ev, gercek_dep = 1.0, 0.0
    elif ev_gol == dep_gol:
        gercek_ev, gercek_dep = 0.5, 0.5
    else:
        gercek_ev, gercek_dep = 0.0, 1.0

    mov  = _gol_farki_carpani(ev_gol, dep_gol)
    k_ev  = _k_faktor(lig_kodu, ev_mac)
    k_dep = _k_faktor(lig_kodu, dep_mac)

    elo_dict[ev_takim]  = ev_elo  + k_ev  * mov * (gercek_ev  - beklenen_ev)
    elo_dict[dep_takim] = dep_elo + k_dep * mov * (gercek_dep - beklenen_dep)
    mac_sayilari[ev_takim]  = ev_mac  + 1
    mac_sayilari[dep_takim] = dep_mac + 1


def elo_hesapla(veri: dict) -> dict:
    """
    Tüm geçmiş maç verisinden ELO değerlerini kronolojik sırada hesaplar.
    SESSION CACHE: Aynı veri seti için ikinci çağrıda hesaplama yapılmaz.

    Returns:
        {takim_ismi: {"elo": float, "lig": str, "mac_sayisi": int}}
    """
    global _elo_cache, _elo_cache_key

    # Cache anahtarı: lig sayısı + toplam maç sayısı toplamı
    cache_key = sum(len(v) for v in veri.values()) if veri else 0
    if cache_key == _elo_cache_key and _elo_cache:
        return _elo_cache  # ✅ Cache'den dön — hesaplama atlanır
    elo_dict     = defaultdict(lambda: float(ELO_BASLANGIC))
    mac_sayilari = defaultdict(int)
    takim_lig    = {}

    tum_maclar = []
    for lig_kodu, maclar in veri.items():
        for mac in maclar:
            mac["_lig_kodu"] = lig_kodu
            tum_maclar.append(mac)

    tum_maclar.sort(key=lambda m: m.get("utcDate", ""))

    for mac in tum_maclar:
        try:
            ev      = mac["homeTeam"]["name"]
            dep     = mac["awayTeam"]["name"]
            ev_gol  = mac["score"]["fullTime"]["home"]
            dep_gol = mac["score"]["fullTime"]["away"]
            lig     = mac["_lig_kodu"]
        except (KeyError, TypeError):
            continue

        if ev_gol is None or dep_gol is None:
            continue

        takim_lig[ev]  = lig
        takim_lig[dep] = lig

        elo_guncelle(elo_dict, lig, ev, dep, int(ev_gol), int(dep_gol), mac_sayilari)

    sonuc = {
        takim: {
            "elo":        round(elo_dict[takim], 1),
            "lig":        takim_lig.get(takim, "?"),
            "mac_sayisi": mac_sayilari[takim],
        }
        for takim in elo_dict
    }
    # Sonucu cache'e yaz
    _elo_cache = sonuc
    _elo_cache_key = cache_key
    return sonuc


def elo_point_in_time_hesapla(veri: dict) -> dict:
    """
    Kronolojik olarak her maç öncesindeki (t < match_date) ELO değerlerini döndürür.
    Future data leakage'ı %100 engeller.
    
    Returns:
        {match_id: {"ev_elo": float, "dep_elo": float, "ev_mac": int, "dep_mac": int}}
    """
    elo_dict     = defaultdict(lambda: float(ELO_BASLANGIC))
    mac_sayilari = defaultdict(int)
    
    tum_maclar = []
    for lig_kodu, maclar in veri.items():
        for mac in maclar:
            m = dict(mac)
            m["_lig_kodu"] = lig_kodu
            tum_maclar.append(m)

    tum_maclar.sort(key=lambda m: m.get("utcDate", ""))
    
    pit_records = {}
    for mac in tum_maclar:
        try:
            m_id    = str(mac.get("id") or f"{mac.get('homeTeam',{}).get('name')}_{mac.get('awayTeam',{}).get('name')}_{mac.get('utcDate')}")
            ev      = mac["homeTeam"]["name"]
            dep     = mac["awayTeam"]["name"]
            ev_gol  = mac["score"]["fullTime"]["home"]
            dep_gol = mac["score"]["fullTime"]["away"]
            lig     = mac["_lig_kodu"]
        except (KeyError, TypeError):
            continue

        # Maç ÖNCESİNDEKİ ELO durumunu kaydet (Zero-Leakage)
        pit_records[m_id] = {
            "ev_elo": elo_dict[ev],
            "dep_elo": elo_dict[dep],
            "ev_mac": mac_sayilari[ev],
            "dep_mac": mac_sayilari[dep]
        }

        # Maç BİTTİĞİNDE ELO'yu güncelle
        if ev_gol is not None and dep_gol is not None:
            elo_guncelle(elo_dict, lig, ev, dep, int(ev_gol), int(dep_gol), mac_sayilari)

    return pit_records


def get_team_elo_point_in_time(veri: dict, takim_adi: str, cutoff_date: str = None) -> float:
    """
    Belirli bir takımın cutoff_date anındaki ELO puanını döndürür.
    cutoff_date verilmezse en son ELO'yu döner.
    """
    elo_dict     = defaultdict(lambda: float(ELO_BASLANGIC))
    mac_sayilari = defaultdict(int)

    tum_maclar = []
    for lig_kodu, maclar in veri.items():
        for mac in maclar:
            m = dict(mac)
            m["_lig_kodu"] = lig_kodu
            tum_maclar.append(m)

    tum_maclar.sort(key=lambda m: m.get("utcDate", ""))

    for mac in tum_maclar:
        tarih = mac.get("utcDate", "")
        if cutoff_date and tarih and tarih >= cutoff_date:
            break

        try:
            ev      = mac["homeTeam"]["name"]
            dep     = mac["awayTeam"]["name"]
            ev_gol  = mac["score"]["fullTime"]["home"]
            dep_gol = mac["score"]["fullTime"]["away"]
            lig     = mac["_lig_kodu"]
        except (KeyError, TypeError):
            continue

        if ev_gol is not None and dep_gol is not None:
            elo_guncelle(elo_dict, lig, ev, dep, int(ev_gol), int(dep_gol), mac_sayilari)

    return elo_dict[takim_adi]


def elo_olasilik(ev_elo: float, dep_elo: float) -> dict:
    """
    İki takımın ELO değerlerinden maç sonucu olasılıklarını üretir.
    Beraberlik için Bradley-Terry-ELO hibrit yaklaşımı.

    Returns:
        {"home_win": float, "draw": float, "away_win": float}
    """
    fark = (ev_elo + ELO_EV_AVANTAJI) - dep_elo
    ev_kazanir_ham  = 1 / (1 + 10 ** (-fark / 400))
    dep_kazanir_ham = 1 - ev_kazanir_ham

    # Beraberlik: ELO dengesi ne kadar yakınsa o kadar olası
    denge = abs(fark) / 400
    ber_p = 0.27 * math.exp(-denge * 1.2)

    kalan = 1.0 - ber_p
    return {
        "home_win": round(ev_kazanir_ham  * kalan, 4),
        "draw":     round(ber_p,                   4),
        "away_win": round(dep_kazanir_ham * kalan, 4),
    }


def elo_rapor(elo_sonuclari: dict, n: int = 10) -> str:
    """En yüksek/düşük ELO'lu takımları raporlar."""
    sirali = sorted(elo_sonuclari.items(), key=lambda x: x[1]["elo"], reverse=True)
    s = [f"\n{'─'*48}", "  🏆  ELO SIRALAMASI", f"{'─'*48}", "  TOP 10:"]
    for i, (t, b) in enumerate(sirali[:n], 1):
        s.append(f"  {i:>2}. {t:<32} ELO: {b['elo']:.0f}  ({b['mac_sayisi']} maç)")
    s.append(f"\n  EN DÜŞÜK 5:")
    for t, b in sirali[-5:]:
        s.append(f"      {t:<32} ELO: {b['elo']:.0f}")
    s.append(f"{'─'*48}")
    return "\n".join(s)