# features/h2h_model.py
"""
H2H (Head-to-Head) Modeli + Beraberlik Düzelticisi — Point-in-Time & Çift Yönlü Normalizasyon
═══════════════════════════════════════════════════════════════════════════════════════════
DEĞİŞİKLİKLER (AUDIT v3.1):
  1. Çift Yönlü Normalizasyon: A vs B ve B vs A maçları doğru ev/deplasman yönüyle birleştirilir.
  2. Gerçek Maç Sonuçları: Kazanma/beraberlik oranları gol sayısından değil, maç skorlarından hesaplanır.
  3. Point-in-Time Desteği: cutoff_date verilmişse sadece bu tarihten önceki maçlar kullanılır (Zero Leakage).
  4. Recency Weighting: Eski karşılaşmalar decay çarpanı ile daha az etkilidir.
"""

import math
from config.settings import ELO_EV_AVANTAJI

# ─── Sabitler ─────────────────────────────────────────────────
H2H_MIN_MAC        = 2
H2H_MAX_MAC        = 6
H2H_DECAY          = 0.85
BER_TEMEL          = 0.230
BER_DUSUK_GOL_ESIK = 2.2


def point_in_time_h2h(ham_veri: dict, ev_takim: str, dep_takim: str,
                       cutoff_date: str = None, max_mac: int = H2H_MAX_MAC,
                       decay: float = H2H_DECAY, lig_hucum_ort: float = 1.35) -> dict:
    """
    İki takım arasındaki geçmiş tüm karşılaşmaları (A vs B ve B vs A)
    cutoff_date öncesinden çeker, ev/dep yönünü doğru normalize eder ve
    recency weighting uygular.
    """
    if not ham_veri or not ev_takim or not dep_takim:
        return _notr_h2h()

    karsilasmalar = []

    for lig_kodu, maclar in ham_veri.items():
        for m in maclar:
            m_date = m.get("utcDate", "")
            if cutoff_date and m_date and m_date >= cutoff_date:
                continue

            try:
                m_ev = m["homeTeam"]["name"]
                m_dep = m["awayTeam"]["name"]
                m_ev_gol = int(m["score"]["fullTime"]["home"])
                m_dep_gol = int(m["score"]["fullTime"]["away"])
            except (KeyError, TypeError, ValueError):
                continue

            # A evde, B deplasmanda
            if m_ev == ev_takim and m_dep == dep_takim:
                karsilasmalar.append({
                    "date": m_date,
                    "ev_gol": m_ev_gol,
                    "dep_gol": m_dep_gol,
                    "ev_kazandi": 1.0 if m_ev_gol > m_dep_gol else (0.5 if m_ev_gol == m_dep_gol else 0.0),
                    "berabere": 1.0 if m_ev_gol == m_dep_gol else 0.0,
                    "konum": "ayni_konum"
                })
            # B evde, A deplasmanda (YÖN TERS)
            elif m_ev == dep_takim and m_dep == ev_takim:
                karsilasmalar.append({
                    "date": m_date,
                    "ev_gol": m_dep_gol,   # ev_takim'in attığı gol
                    "dep_gol": m_ev_gol,  # dep_takim'in attığı gol
                    "ev_kazandi": 1.0 if m_dep_gol > m_ev_gol else (0.5 if m_dep_gol == m_ev_gol else 0.0),
                    "berabere": 1.0 if m_dep_gol == m_ev_gol else 0.0,
                    "konum": "ters_konum"
                })

    if not karsilasmalar or len(karsilasmalar) < H2H_MIN_MAC:
        return _notr_h2h()

    # Kronolojik sırala ve en son karşılaşmaları al
    karsilasmalar.sort(key=lambda x: x.get("date", ""))
    secilen = karsilasmalar[-max_mac:]

    n = len(secilen)
    agirliklar = [decay ** (n - 1 - i) for i in range(n)]
    toplam_agirlik = sum(agirliklar)

    # Recency weighted metrikler
    agirlikli_ev_gol = sum(m["ev_gol"] * w for m, w in zip(secilen, agirliklar)) / toplam_agirlik
    agirlikli_dep_gol = sum(m["dep_gol"] * w for m, w in zip(secilen, agirliklar)) / toplam_agirlik
    agirlikli_ev_win = sum(m["ev_kazandi"] * w for m, w in zip(secilen, agirliklar)) / toplam_agirlik
    agirlikli_ber = sum(m["berabere"] * w for m, w in zip(secilen, agirliklar)) / toplam_agirlik
    agirlikli_dep_win = 1.0 - agirlikli_ev_win

    ev_lambda_d  = max(0.80, min(agirlikli_ev_gol  / max(lig_hucum_ort, 0.5), 1.25))
    dep_lambda_d = max(0.80, min(agirlikli_dep_gol / max(lig_hucum_ort, 0.5), 1.25))

    toplam_gol_ort = agirlikli_ev_gol + agirlikli_dep_gol
    ber_egilim     = max(-0.05, min(0.05, (2.5 - toplam_gol_ort) * 0.02))
    guven         = min(1.0, n / max_mac)

    return {
        "ev_lambda_d":       round(ev_lambda_d,  4),
        "dep_lambda_d":      round(dep_lambda_d, 4),
        "ber_egilim":        round(ber_egilim,   4),
        "mac_sayisi":        n,
        "guven":             round(guven, 3),
        "ev_gol_ort":        round(agirlikli_ev_gol,   3),
        "dep_gol_ort":       round(agirlikli_dep_gol,  3),
        "ev_kazanma_orani":  round(agirlikli_ev_win, 3),
        "ber_orani":         round(agirlikli_ber,     3),
        "dep_kazanma_orani": round(agirlikli_dep_win, 3),
    }


def h2h_analiz(istatistikler: dict, ev_takim: str, dep_takim: str,
               lig_hucum_ort: float = 1.35, ham_veri: dict = None,
               cutoff_date: str = None) -> dict:
    """
    H2H analiz fonksiyonu.
    Eğer ham_veri verilmişse point-in-time olarak hesaplar (tercih edilen).
    Aksi halde istatistikler sözlüğündeki kayıtları doğrulanmış maç sonuçlarıyla hesaplar.
    """
    if ham_veri:
        return point_in_time_h2h(ham_veri, ev_takim, dep_takim, cutoff_date=cutoff_date, lig_hucum_ort=lig_hucum_ort)

    ev_s = istatistikler.get(ev_takim, {})
    h2h  = ev_s.get("h2h", {}).get(dep_takim)

    if not h2h or h2h.get("mac", 0) < H2H_MIN_MAC:
        return _notr_h2h()

    mac         = min(h2h["mac"], H2H_MAX_MAC)
    ev_gol      = h2h.get("ev_gol", 0)
    dep_gol     = h2h.get("dep_gol", 0)
    ev_gol_ort  = ev_gol  / max(h2h["mac"], 1)
    dep_gol_ort = dep_gol / max(h2h["mac"], 1)

    ev_lambda_d  = max(0.80, min(ev_gol_ort  / max(lig_hucum_ort, 0.5), 1.25))
    dep_lambda_d = max(0.80, min(dep_gol_ort / max(lig_hucum_ort, 0.5), 1.25))

    toplam_gol_ort = ev_gol_ort + dep_gol_ort
    ber_egilim     = max(-0.05, min(0.05, (2.5 - toplam_gol_ort) * 0.02))

    # Gol sayısı yerine maç sonucu temelli yaklaşık kazanma oranı
    ev_galibiyet = h2h.get("ev_galibiyet", None)
    dep_galibiyet = h2h.get("dep_galibiyet", None)
    beraberlik = h2h.get("beraberlik", None)

    if ev_galibiyet is not None and dep_galibiyet is not None:
        ev_kaz_orani = ev_galibiyet / max(h2h["mac"], 1)
        dep_kaz_orani = dep_galibiyet / max(h2h["mac"], 1)
        ber_orani = (beraberlik or 0) / max(h2h["mac"], 1)
    else:
        # Gol farkı temelli mantıklı tahmin
        gol_farki = ev_gol_ort - dep_gol_ort
        ev_kaz_orani = max(0.1, min(0.9, 0.45 + gol_farki * 0.15))
        dep_kaz_orani = max(0.1, min(0.9, 0.30 - gol_farki * 0.15))
        ber_orani = max(0.15, 1.0 - ev_kaz_orani - dep_kaz_orani)

    guven = min(1.0, mac / H2H_MAX_MAC)

    return {
        "ev_lambda_d":       round(ev_lambda_d,  4),
        "dep_lambda_d":      round(dep_lambda_d, 4),
        "ber_egilim":        round(ber_egilim,   4),
        "mac_sayisi":        mac,
        "guven":             round(guven, 3),
        "ev_gol_ort":        round(ev_gol_ort,   3),
        "dep_gol_ort":       round(dep_gol_ort,  3),
        "ev_kazanma_orani":  round(ev_kaz_orani, 3),
        "ber_orani":         round(ber_orani,     3),
        "dep_kazanma_orani": round(dep_kaz_orani, 3),
    }


def _notr_h2h() -> dict:
    return {
        "ev_lambda_d": 1.0, "dep_lambda_d": 1.0, "ber_egilim": 0.0,
        "mac_sayisi": 0, "guven": 0.0, "ev_gol_ort": 0.0, "dep_gol_ort": 0.0,
        "ev_kazanma_orani": 0.45, "ber_orani": 0.25, "dep_kazanma_orani": 0.30,
    }


def h2h_lambda_uygula(lam_ev: float, lam_dep: float, h2h: dict,
                       h2h_etkisi: float = 0.15) -> tuple:
    etki     = h2h_etkisi * h2h.get("guven", 0.0)
    yeni_ev  = lam_ev  * (1 - etki) + lam_ev  * h2h["ev_lambda_d"]  * etki
    yeni_dep = lam_dep * (1 - etki) + lam_dep * h2h["dep_lambda_d"] * etki
    return round(max(0.4, min(yeni_ev, 3.2)), 3), round(max(0.4, min(yeni_dep, 3.2)), 3)


def beraberlik_kalibrasyon(
    ev_p: float, ber_p: float, dep_p: float,
    lam_ev: float, lam_dep: float,
    ev_elo: float, dep_elo: float,
    h2h: dict = None,
    ber_agirlik: float = 0.30,
) -> dict:
    """
    Beraberlik Kalibrasyonu — Düzeltilmiş v3
    """
    if h2h is None:
        h2h = _notr_h2h()

    toplam_lam = lam_ev + lam_dep

    if toplam_lam < 1.8:
        dusuk_gol_boost = 0.02
    elif toplam_lam < 2.2:
        dusuk_gol_boost = (BER_DUSUK_GOL_ESIK - toplam_lam) * 0.015
    else:
        dusuk_gol_boost = 0.0

    elo_fark        = abs((ev_elo + ELO_EV_AVANTAJI) - dep_elo)
    elo_denge_boost = max(0.0, (150 - elo_fark) / 150) * 0.015

    h2h_boost = h2h.get("ber_egilim", 0.0) * h2h.get("guven", 0.0)

    ber_hedef = BER_TEMEL + dusuk_gol_boost + elo_denge_boost + h2h_boost
    ber_hedef = max(0.18, min(ber_hedef, 0.32))

    yeni_ber = ber_p * (1.0 - ber_agirlik) + ber_hedef * ber_agirlik
    yeni_ber = max(0.15, min(yeni_ber, 0.32))

    kalan = 1.0 - yeni_ber
    oran  = ev_p / (ev_p + dep_p) if (ev_p + dep_p) > 0 else 0.5

    h2h_guven   = h2h.get("guven", 0.0)
    ci_genislik = max(0.04, 0.12 - h2h_guven * 0.06)
    draw_ci     = (
        round(max(0.10, yeni_ber - ci_genislik / 2), 3),
        round(min(0.45, yeni_ber + ci_genislik / 2), 3),
    )

    return {
        "home_win":      round(kalan * oran,        4),
        "draw":          round(yeni_ber,            4),
        "away_win":      round(kalan * (1 - oran),  4),
        "draw_ci":       draw_ci,
        "ber_boost_gol": round(dusuk_gol_boost,     4),
        "ber_boost_elo": round(elo_denge_boost,     4),
        "ber_boost_h2h": round(h2h_boost,           4),
        "ber_hedef":     round(ber_hedef,            4),
    }


def h2h_hesapla_pit(ev_takim: str, dep_takim: str, cutoff_date: str = None,
                    h2h_history: list = None, ham_veri: dict = None) -> dict:
    """
    Point-in-time H2H hesaplayıcı.
    Kazanma/beraberlik oranlarını gol sayısından DEĞİL, gerçek maç sonuçlarından hesaplar.
    t >= cutoff_date olan gelecekteki maçlar filtrelenir (Zero Leakage).
    """
    if h2h_history is None and ham_veri is not None:
        h2h_history = []
        for lig, maclar in ham_veri.items():
            for m in maclar:
                try:
                    h2h_history.append({
                        "ev": m["homeTeam"]["name"],
                        "dep": m["awayTeam"]["name"],
                        "ev_gol": int(m["score"]["fullTime"]["home"]),
                        "dep_gol": int(m["score"]["fullTime"]["away"]),
                        "tarih": m.get("utcDate", ""),
                    })
                except (KeyError, TypeError, ValueError):
                    continue

    if not h2h_history:
        return {
            "toplam_mac": 0, "ev_galibiyet": 0, "beraberlik": 0, "dep_galibiyet": 0,
            "ev_galibiyet_orani": 0.33, "beraberlik_orani": 0.33, "dep_galibiyet_orani": 0.33,
        }

    toplam = 0
    ev_gal = 0
    ber = 0
    dep_gal = 0

    for m in h2h_history:
        m_date = m.get("tarih", m.get("date", m.get("utcDate", "")))
        if cutoff_date and m_date and m_date >= cutoff_date:
            continue

        m_ev = m.get("ev", m.get("home", ""))
        m_dep = m.get("dep", m.get("away", ""))
        hg = m.get("ev_gol", m.get("home_goals", 0))
        ag = m.get("dep_gol", m.get("away_goals", 0))

        if m_ev == ev_takim and m_dep == dep_takim:
            toplam += 1
            if hg > ag:
                ev_gal += 1
            elif hg == ag:
                ber += 1
            else:
                dep_gal += 1
        elif m_ev == dep_takim and m_dep == ev_takim:
            # Reverse fixture: ev_takim was away
            toplam += 1
            if ag > hg:
                ev_gal += 1  # ev_takim won away
            elif ag == hg:
                ber += 1
            else:
                dep_gal += 1

    if toplam == 0:
        return {
            "toplam_mac": 0, "ev_galibiyet": 0, "beraberlik": 0, "dep_galibiyet": 0,
            "ev_galibiyet_orani": 0.33, "beraberlik_orani": 0.33, "dep_galibiyet_orani": 0.33,
        }

    return {
        "toplam_mac": toplam,
        "ev_galibiyet": ev_gal,
        "beraberlik": ber,
        "dep_galibiyet": dep_gal,
        "ev_galibiyet_orani": round(ev_gal / toplam, 4),
        "beraberlik_orani": round(ber / toplam, 4),
        "dep_galibiyet_orani": round(dep_gal / toplam, 4),
    }