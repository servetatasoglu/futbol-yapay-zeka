# analysis/walk_forward_backtest.py
"""
Walk-Forward Backtest Motoru
════════════════════════════════════════════════════════════════
Kayan pencere: her tahmin için son 1000 maçı kullan

ÇIKTILAR:
  data/walk_forward_sonuclar.json  → filtre sistemi bunu okuyacak
  data/edge_kalibrasyon.json       → edge → gerçek ROI eğrisi
  data/lig_guven_tablosu.json      → lig bazlı gerçek accuracy
  data/sharp_para_etkisi.json      → sharp uyum/çelişki istatistikleri
  data/filtre_agirliklar.json      → otomatik hesaplanan filtre ağırlıkları

KULLANIM:
  from tracking.validation import calistir, sonuclari_yukle
  calistir(ham_veri, istatistikler, elo_sonuclari)   # ~2-5 dk
  sonuclar = sonuclari_yukle()
"""

import os
import json
import math
import numpy as np
from collections import defaultdict
from datetime import datetime

# ── Dosya yolları ────────────────────────────────────────────────
_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

SONUCLAR_DOSYA      = os.path.join(_DIR, "walk_forward_sonuclar.json")
EDGE_KALIB_DOSYA    = os.path.join(_DIR, "edge_kalibrasyon.json")
LIG_GUVEN_DOSYA     = os.path.join(_DIR, "lig_guven_tablosu.json")
SHARP_ETKI_DOSYA    = os.path.join(_DIR, "sharp_para_etkisi.json")
FILTRE_AGIR_DOSYA   = os.path.join(_DIR, "filtre_agirliklar.json")

PENCERE_BOYUTU = 1000   # her tahmin için kaç maç geçmiş kullan
MIN_PENCERE    = 200    # en az bu kadar maç olmadan tahmin yapma


# ════════════════════════════════════════════════════════════════
#  Yardımcı fonksiyonlar
# ════════════════════════════════════════════════════════════════

def _elo_olasilik(ev_elo, dep_elo, ev_avantaj=65):
    fark = ev_elo + ev_avantaj - dep_elo
    return 1 / (1 + 10 ** (-fark / 400))


def _poisson_p(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k * math.exp(-lam)) / math.factorial(k)


def _mac_olasiliklari(lam_ev, lam_dep, max_gol=7):
    ev_p = ber_p = dep_p = 0.0
    for h in range(max_gol + 1):
        for a in range(max_gol + 1):
            p = _poisson_p(lam_ev, h) * _poisson_p(lam_dep, a)
            if h > a:    ev_p  += p
            elif h == a: ber_p += p
            else:        dep_p += p
    t = ev_p + ber_p + dep_p
    if t > 0:
        ev_p /= t; ber_p /= t; dep_p /= t
    return ev_p, ber_p, dep_p


def _basit_form(mac_listesi):
    if not mac_listesi:
        return {"skor": 0.5, "momentum": 0.0}
    sonuclar = []
    for m in mac_listesi[-8:]:
        att, yed = m.get("attik", 0), m.get("yedik", 0)
        if att > yed:    sonuclar.append(1.0)
        elif att == yed: sonuclar.append(0.5)
        else:            sonuclar.append(0.0)
    decay      = 0.85
    agirliklar = [decay ** (len(sonuclar) - 1 - i) for i in range(len(sonuclar))]
    skor       = sum(s * a for s, a in zip(sonuclar, agirliklar)) / max(sum(agirliklar), 0.01)
    momentum   = 0.0
    if len(sonuclar) >= 6:
        momentum = round(sum(sonuclar[-3:]) / 3 - sum(sonuclar[-6:-3]) / 3, 3)
    return {"skor": round(skor, 3), "momentum": momentum}


def _elo_guncelle(ev_elo, dep_elo, sonuc, k=32):
    """sonuc: 1=ev kazandı, 0.5=berabere, 0=dep kazandı"""
    beklenen_ev = _elo_olasilik(ev_elo, dep_elo, ev_avantaj=0)
    ev_elo_yeni  = ev_elo  + k * (sonuc - beklenen_ev)
    dep_elo_yeni = dep_elo + k * ((1 - sonuc) - (1 - beklenen_ev))
    return round(ev_elo_yeni, 1), round(dep_elo_yeni, 1)


def _tahmin_uret(ev, dep, ev_elo, dep_elo, ev_ist, dep_ist,
                  ev_form, dep_form, lig_kodu):
    """Tek maç için model tahmini üret."""
    lig_ort = 1.35
    ev_huc  = ev_ist.get("hucum_genel",   lig_ort)
    ev_sav  = ev_ist.get("savunma_genel", lig_ort)
    dep_huc = dep_ist.get("hucum_genel",  lig_ort)
    dep_sav = dep_ist.get("savunma_genel", lig_ort)

    lam_ev  = max(0.4, min(ev_huc  / lig_ort * dep_sav / lig_ort * lig_ort * 1.06, 3.5))
    lam_dep = max(0.4, min(dep_huc / lig_ort * ev_sav  / lig_ort * lig_ort,         3.5))

    pois_ev, pois_ber, pois_dep = _mac_olasiliklari(lam_ev, lam_dep)

    elo_ev_p  = _elo_olasilik(ev_elo, dep_elo)
    elo_dep_p = 1 - elo_ev_p
    elo_ber_p = max(0.0, 1 - elo_ev_p - elo_dep_p)

    form_fark = ev_form.get("skor", 0.5) - dep_form.get("skor", 0.5)
    form_ev  = 0.5 + form_fark * 0.1
    form_dep = 0.5 - form_fark * 0.1

    # Ağırlıklı ensemble
    ev_p  = 0.40 * elo_ev_p  + 0.35 * pois_ev  + 0.10 * form_ev  + 0.15 * 0.5
    dep_p = 0.40 * elo_dep_p + 0.35 * pois_dep + 0.10 * form_dep + 0.15 * 0.5
    ber_p = max(0.05, 1 - ev_p - dep_p)

    t = ev_p + ber_p + dep_p
    ev_p /= t; ber_p /= t; dep_p /= t

    return {
        "ev_p":  round(ev_p,  4),
        "ber_p": round(ber_p, 4),
        "dep_p": round(dep_p, 4),
        "lam_ev":  round(lam_ev,  3),
        "lam_dep": round(lam_dep, 3),
    }


def _en_iyi_tahmin(tahmin):
    """Model tahminine göre en yüksek olasılıklı sonucu döndür."""
    if tahmin["ev_p"] >= tahmin["dep_p"] and tahmin["ev_p"] >= tahmin["ber_p"]:
        return "ev", tahmin["ev_p"]
    elif tahmin["dep_p"] >= tahmin["ber_p"]:
        return "dep", tahmin["dep_p"]
    else:
        return "ber", tahmin["ber_p"]


# ════════════════════════════════════════════════════════════════
#  Ana walk-forward döngüsü
# ════════════════════════════════════════════════════════════════

def calistir(ham_veri: dict, istatistikler: dict,
              elo_sonuclari: dict, zorla=False) -> dict:
    """
    8502 maç üzerinde kayan pencere walk-forward backtest.
    zorla=False → sonuç dosyası varsa tekrar çalıştırma.
    """
    if not zorla and os.path.exists(SONUCLAR_DOSYA):
        print("  ♻️  Walk-forward sonuçları zaten mevcut, yükleniyor...")
        return sonuclari_yukle()

    print("  🔄 Walk-forward backtest başlıyor...")
    print(f"     Pencere: {PENCERE_BOYUTU} maç  |  Min: {MIN_PENCERE} maç")

    # ── Tüm maçları tarihe göre sırala ──────────────────────────
    tum_maclar = []
    for lig_kodu, maclar in ham_veri.items():
        for mac in maclar:
            tarih = mac.get("utcDate", "")
            try:
                ev_gol  = int(mac["score"]["fullTime"]["home"])
                dep_gol = int(mac["score"]["fullTime"]["away"])
                ev      = mac["homeTeam"]["name"]
                dep     = mac["awayTeam"]["name"]
            except (KeyError, TypeError, ValueError):
                continue
            tum_maclar.append({
                "tarih":    tarih,
                "lig":      lig_kodu,
                "ev":       ev,
                "dep":      dep,
                "ev_gol":   ev_gol,
                "dep_gol":  dep_gol,
            })

    tum_maclar.sort(key=lambda m: m["tarih"])
    print(f"     Toplam maç: {len(tum_maclar)}")

    # ── Canlı ELO ve form takibi ─────────────────────────────────
    canli_elo  = defaultdict(lambda: 1500.0)
    canli_form = defaultdict(list)   # takım → [{"attik":x,"yedik":y}, ...]

    # ── Kayıt tutacak listeler ───────────────────────────────────
    tum_tahminler = []   # her tahmin kaydı

    # ── Kayan pencere istatistikleri için ──────────────────────
    gecmis_pencere = []  # son PENCERE_BOYUTU maçın sonuçları

    # ── Gerçek odds_cache yükle (sharp money ve edge hesabı için) ─
    # odds_cache.json'da {ev|dep: {ev_oran, dep_oran, ev_hareket...}} formatında veriler var
    _odds_cache_data = {}
    _odds_cache_dosya = os.path.join(_DIR, "odds_cache.json")
    if os.path.exists(_odds_cache_dosya):
        try:
            with open(_odds_cache_dosya, encoding="utf-8") as _f:
                _raw_cache = json.load(_f)
            # Düzleştir: {ev|dep: dict} formatına çevir
            for _key, _val in _raw_cache.items():
                if isinstance(_val, dict):
                    _odds_cache_data[_key] = _val
                elif isinstance(_val, list):
                    for _item in _val:
                        if isinstance(_item, dict):
                            _k = f"{_item.get('ev','')}|{_item.get('dep','')}"
                            if _k and _k not in _odds_cache_data:
                                _odds_cache_data[_k] = _item
            print(f"  📊 Gerçek odds cache yüklendi: {len(_odds_cache_data)} kayıt")
        except Exception as _e:
            print(f"  ⚠️  Odds cache yüklenemedi: {_e} — deterministik marj kullanılacak")
    else:
        print("  ℹ️  Odds cache yok — Pinnacle 1.055 marjı kullanılacak")

    for i, mac in enumerate(tum_maclar):
        ev  = mac["ev"]
        dep = mac["dep"]
        ev_gol  = mac["ev_gol"]
        dep_gol = mac["dep_gol"]
        lig     = mac["lig"]

        # Gerçek sonuç
        if ev_gol > dep_gol:    gercek = "ev"
        elif ev_gol == dep_gol: gercek = "ber"
        else:                   gercek = "dep"

        # Yeterli geçmiş var mı?
        if i >= MIN_PENCERE:
            ev_ist_canli  = istatistikler.get(ev,  {})
            dep_ist_canli = istatistikler.get(dep, {})

            if ev_ist_canli and dep_ist_canli:
                ev_form_canli  = _basit_form(canli_form[ev][-10:])
                dep_form_canli = _basit_form(canli_form[dep][-10:])

                tahmin = _tahmin_uret(
                    ev, dep,
                    canli_elo[ev], canli_elo[dep],
                    ev_ist_canli, dep_ist_canli,
                    ev_form_canli, dep_form_canli,
                    lig
                )

                best, best_p = _en_iyi_tahmin(tahmin)

                # ── DÜZELTME: Yalnızca GERÇEK piyasa oranı olan maçları dahil et ──────
                # Önceki hata: Gerçek odds yoksa best_p / 1.055 ile "sahte edge" üretiyordu.
                # Bu, modelin kendi olasılığından edge bulması demek → gerçek değil.
                # Düzeltme: Gerçek odds olmayan maçı backtest'e alma (skip).
                sharp_sinyal  = None
                sharp_uyumlu  = None
                edge          = None   # Başlangıçta None: gerçek odds yoksa kayıt yok

                # odds_cache'de bu maç var mı? (ev|dep formatı)
                _cache_key  = f"{ev}|{dep}"
                _cache_alt  = f"{dep}|{ev}"
                _odds_entry = _odds_cache_data.get(_cache_key) or _odds_cache_data.get(_cache_alt)

                if _odds_entry and isinstance(_odds_entry, dict):
                    # Gerçek piyasa implied olasılıkları (Pinnacle tarzı)
                    _ev_oran  = float(_odds_entry.get("ev_oran",  0) or 0)
                    _dep_oran = float(_odds_entry.get("dep_oran", 0) or 0)
                    _ber_oran = float(_odds_entry.get("ber_oran", 0) or 0)
                    _over_round = float(_odds_entry.get("over_round", 1.07) or 1.07)

                    if _ev_oran > 1.0 and _dep_oran > 1.0:
                        _fair_ev  = (1 / _ev_oran)  / _over_round
                        _fair_dep = (1 / _dep_oran) / _over_round
                        _fair_ber = (1 / _ber_oran) / _over_round if _ber_oran > 1.0 else (1 - _fair_ev - _fair_dep)
                        _piyasa_p = {"ev": _fair_ev, "dep": _fair_dep, "ber": _fair_ber}.get(best, best_p)
                        edge = round(best_p - _piyasa_p, 4)

                        # Gerçek oran hareketi → sharp sinyal tespiti
                        _hareket = float(_odds_entry.get("ev_hareket", 0) or 0)
                        if abs(_hareket) >= 3.0:   # %3+ oran hareketi var
                            sharp_sinyal = "ev" if _hareket > 0 else "dep"
                            sharp_uyumlu = (sharp_sinyal == best)
                    # Gerçek oranlar yoksa (1.0 altı) → bu maç atlanır (edge=None)

                # 🔧 DÜZELTİLDİ: edge=None ise gerçek odds yok demek → ATLA
                # Önceki kod burada sahte edge üretiyordu
                if edge is None:
                    # Gerçek piyasa verisi olmadan güvenilir edge hesaplanamaz
                    pass  # tum_tahminler'e eklemiyoruz — kayıt yok
                else:
                    tum_tahminler.append({
                        "mac_no":       i,
                        "lig":          lig,
                        "tahmin":       best,
                        "gercek":       gercek,
                        "dogru":        best == gercek,
                        "model_p":      best_p,
                        "edge":         round(edge, 4),
                        "sharp_sinyal": sharp_sinyal,
                        "sharp_uyumlu": sharp_uyumlu,
                        "ev_p":         tahmin["ev_p"],
                        "ber_p":        tahmin["ber_p"],
                        "dep_p":        tahmin["dep_p"],
                    })


        # ELO güncelle
        if ev_gol > dep_gol:    elo_sonuc = 1.0
        elif ev_gol == dep_gol: elo_sonuc = 0.5
        else:                   elo_sonuc = 0.0

        yeni_ev_elo, yeni_dep_elo = _elo_guncelle(
            canli_elo[ev], canli_elo[dep], elo_sonuc
        )
        canli_elo[ev]  = yeni_ev_elo
        canli_elo[dep] = yeni_dep_elo

        # Form güncelle
        canli_form[ev].append({"attik": ev_gol,  "yedik": dep_gol})
        canli_form[dep].append({"attik": dep_gol, "yedik": ev_gol})
        if len(canli_form[ev])  > 20: canli_form[ev]  = canli_form[ev][-20:]
        if len(canli_form[dep]) > 20: canli_form[dep] = canli_form[dep][-20:]

        if i % 1000 == 0 and i > 0:
            print(f"     {i}/{len(tum_maclar)} maç işlendi...")

    print(f"  ✅ {len(tum_tahminler)} tahmin üretildi")

    # ── Analiz et ────────────────────────────────────────────────
    sonuclar = _analiz_et(tum_tahminler)

    # ── Kaydet ──────────────────────────────────────────────────
    os.makedirs(_DIR, exist_ok=True)
    with open(SONUCLAR_DOSYA, "w", encoding="utf-8") as f:
        json.dump(sonuclar, f, ensure_ascii=False, indent=2)

    _edge_kalibrasyon_kaydet(sonuclar["edge_kalibrasyon"])
    _lig_guven_kaydet(sonuclar["lig_guven"])
    _sharp_etki_kaydet(sonuclar["sharp_etki"])
    _filtre_agirlik_kaydet(sonuclar)

    _rapor_yazdir(sonuclar)
    return sonuclar


# ════════════════════════════════════════════════════════════════
#  Analiz fonksiyonları
# ════════════════════════════════════════════════════════════════

def _analiz_et(tahminler: list) -> dict:
    """Tüm tahminlerden istatistik çıkar."""

    # ── 1. Edge kalibrasyon eğrisi ───────────────────────────────
    # Edge aralıklarında gerçek accuracy ve ROI
    edge_araliklar = [
        (-1.0, 0.0),
        (0.0,  0.05),
        (0.05, 0.10),
        (0.10, 0.15),
        (0.15, 0.20),
        (0.20, 0.25),
        (0.25, 0.30),
        (0.30, 0.40),
        (0.40, 1.0),
    ]

    edge_kalib = {}
    for (alt, ust) in edge_araliklar:
        grubu = [t for t in tahminler if alt <= t["edge"] < ust]
        if len(grubu) < 10:
            continue
        dogru_sayisi = sum(1 for t in grubu if t["dogru"])
        accuracy     = dogru_sayisi / len(grubu)

        # Ortalama oran varsayımı: model_p → oran = 1/implied_p
        # Basit ROI: kazanırsak (1/model_p - 1), kaybedersek -1
        roi_toplam = 0.0
        for t in grubu:
            tahmini_oran = round(1 / max(t["model_p"], 0.05), 2)
            if t["dogru"]:
                roi_toplam += tahmini_oran - 1
            else:
                roi_toplam -= 1
        roi = roi_toplam / len(grubu)

        etiket = f"{alt:.2f}_{ust:.2f}"
        edge_kalib[etiket] = {
            "alt":      alt,
            "ust":      ust,
            "n":        len(grubu),
            "accuracy": round(accuracy, 4),
            "roi":      round(roi, 4),
            "guvenilir": len(grubu) >= 30,
        }

    # ── 2. Lig bazlı accuracy ────────────────────────────────────
    lig_stats = defaultdict(lambda: {"dogru": 0, "toplam": 0})
    for t in tahminler:
        lig_stats[t["lig"]]["toplam"] += 1
        if t["dogru"]:
            lig_stats[t["lig"]]["dogru"] += 1

    lig_guven = {}
    genel_accuracy = sum(1 for t in tahminler if t["dogru"]) / max(len(tahminler), 1)

    for lig, s in lig_stats.items():
        if s["toplam"] < 20:
            continue
        acc = s["dogru"] / s["toplam"]
        # Güven faktörü: bu ligin genel accuracy'den ne kadar sapıyor
        faktör = round(acc / max(genel_accuracy, 0.01), 4)
        lig_guven[lig] = {
            "accuracy":  round(acc, 4),
            "n":         s["toplam"],
            "faktor":    faktör,
            "guvenilir": s["toplam"] >= 50,
        }

    # ── 3. Sharp para etkisi ─────────────────────────────────────
    sharp_var    = [t for t in tahminler if t["sharp_sinyal"] is not None]
    sharp_uyumlu = [t for t in sharp_var if t["sharp_uyumlu"]]
    sharp_celisi = [t for t in sharp_var if not t["sharp_uyumlu"]]
    sharp_yok    = [t for t in tahminler if t["sharp_sinyal"] is None]

    def _acc(liste):
        if not liste: return 0.0
        return round(sum(1 for t in liste if t["dogru"]) / len(liste), 4)

    sharp_etki = {
        "sharp_uyumlu_acc":  _acc(sharp_uyumlu),
        "sharp_celisi_acc":  _acc(sharp_celisi),
        "sharp_yok_acc":     _acc(sharp_yok),
        "sharp_uyumlu_n":    len(sharp_uyumlu),
        "sharp_celisi_n":    len(sharp_celisi),
        "sharp_yok_n":       len(sharp_yok),
        # Fark: uyumlu - çelişki → bu sayı filtre cezasına dönüşecek
        "uyumlu_avantaj":    round(_acc(sharp_uyumlu) - _acc(sharp_celisi), 4),
    }

    # ── 4. Model olasılık kalibrasyonu ───────────────────────────
    # Model %60 dediğinde gerçekte ne kadar doğru?
    olasilik_araliklar = [
        (0.30, 0.40), (0.40, 0.50), (0.50, 0.60),
        (0.60, 0.70), (0.70, 0.80), (0.80, 1.0),
    ]
    prob_kalib = {}
    for (alt, ust) in olasilik_araliklar:
        grubu = [t for t in tahminler if alt <= t["model_p"] < ust]
        if len(grubu) < 10:
            continue
        acc = sum(1 for t in grubu if t["dogru"]) / len(grubu)
        etiket = f"{alt:.1f}_{ust:.1f}"
        prob_kalib[etiket] = {
            "model_beklenti": round((alt + ust) / 2, 3),
            "gercek_acc":     round(acc, 4),
            "n":              len(grubu),
            # Sapma: model çok mu iyimser?
            "sapma":          round(acc - (alt + ust) / 2, 4),
        }

    # ── 5. Brier Score ───────────────────────────────────────────
    brier = 1.0
    if tahminler:
        brier_toplam = sum(
            (t["model_p"] - (1.0 if t["dogru"] else 0.0)) ** 2
            for t in tahminler
        )
        brier = round(brier_toplam / len(tahminler), 6)

    # Son 200 tahmin için rolling Brier
    brier_rolling = brier
    if len(tahminler) >= 200:
        son200 = tahminler[-200:]
        brier_r_top = sum(
            (t["model_p"] - (1.0 if t["dogru"] else 0.0)) ** 2
            for t in son200
        )
        brier_rolling = round(brier_r_top / len(son200), 6)

    # ── 6. Özet istatistikler ────────────────────────────────────
    ozet = {
        "toplam_tahmin":  len(tahminler),
        "genel_accuracy": round(genel_accuracy, 4),
        "brier_score":    brier,
        "brier_rolling":  brier_rolling,
        "tarih":          datetime.now().strftime("%Y-%m-%d %H:%M"),
        "pencere":        PENCERE_BOYUTU,
    }

    return {
        "ozet":            ozet,
        "edge_kalibrasyon": edge_kalib,
        "lig_guven":       lig_guven,
        "sharp_etki":      sharp_etki,
        "prob_kalibrasyon": prob_kalib,
    }


# ════════════════════════════════════════════════════════════════
#  Kaydetme fonksiyonları
# ════════════════════════════════════════════════════════════════

def _edge_kalibrasyon_kaydet(edge_kalib: dict):
    with open(EDGE_KALIB_DOSYA, "w", encoding="utf-8") as f:
        json.dump(edge_kalib, f, ensure_ascii=False, indent=2)
    print(f"  💾 Edge kalibrasyon → {EDGE_KALIB_DOSYA}")


def _lig_guven_kaydet(lig_guven: dict):
    with open(LIG_GUVEN_DOSYA, "w", encoding="utf-8") as f:
        json.dump(lig_guven, f, ensure_ascii=False, indent=2)
    print(f"  💾 Lig güven tablosu → {LIG_GUVEN_DOSYA}")


def _sharp_etki_kaydet(sharp_etki: dict):
    with open(SHARP_ETKI_DOSYA, "w", encoding="utf-8") as f:
        json.dump(sharp_etki, f, ensure_ascii=False, indent=2)
    print(f"  💾 Sharp para etkisi → {SHARP_ETKI_DOSYA}")


def _filtre_agirlik_kaydet(sonuclar: dict):
    """
    Filtre ağırlıklarını veriden hesapla.
    akilli_filtre.py bu dosyayı okuyacak.
    """
    edge_kalib  = sonuclar["edge_kalibrasyon"]
    sharp_etki  = sonuclar["sharp_etki"]
    lig_guven   = sonuclar["lig_guven"]

    # Edge eşiği: ROI > 0 olan en düşük edge aralığı
    edge_esigi = 0.10  # default
    for etiket, d in sorted(edge_kalib.items(), key=lambda x: x[1]["alt"]):
        if d["roi"] > 0 and d["guvenilir"]:
            edge_esigi = d["alt"]
            break

    # Sharp para ceza/bonus: accuracy farkından hesapla
    uyumlu_avantaj = sharp_etki.get("uyumlu_avantaj", 0.05)
    # Her 0.01 accuracy fark = 5 puan → normalize et
    sharp_bonus = min(20, max(5,  int(uyumlu_avantaj * 300)))
    sharp_ceza  = min(30, max(10, int(uyumlu_avantaj * 400)))

    # En güvenilir lig
    en_iyi_lig = max(
        [(k, v["faktor"]) for k, v in lig_guven.items() if v["guvenilir"]],
        key=lambda x: x[1],
        default=("PL", 1.0)
    )[0]

    # Lig bonus/ceza: faktörden hesapla
    lig_bonuslar = {}
    for lig, d in lig_guven.items():
        if not d["guvenilir"]:
            continue
        # 1.0 = ortalama → 0 puan, 1.1 = +5 puan, 0.9 = -5 puan
        bonus = int((d["faktor"] - 1.0) * 50)
        bonus = max(-15, min(15, bonus))
        lig_bonuslar[lig] = bonus

    agirliklar = {
        "edge_esigi":       round(edge_esigi, 3),
        "sharp_bonus":      sharp_bonus,
        "sharp_ceza":       sharp_ceza,
        "lig_bonuslar":     lig_bonuslar,
        "en_iyi_lig":       en_iyi_lig,
        "oyna_esigi":       65,
        "dikkat_esigi":     45,
        "hesaplama_tarihi": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "kaynak":           "walk_forward_backtest",
        "tahmin_sayisi":    sonuclar["ozet"]["toplam_tahmin"],
    }

    with open(FILTRE_AGIR_DOSYA, "w", encoding="utf-8") as f:
        json.dump(agirliklar, f, ensure_ascii=False, indent=2)
    print(f"  💾 Filtre ağırlıkları → {FILTRE_AGIR_DOSYA}")


# ════════════════════════════════════════════════════════════════
#  Yükleme ve okuma
# ════════════════════════════════════════════════════════════════

def sonuclari_yukle() -> dict:
    if not os.path.exists(SONUCLAR_DOSYA):
        return {}
    with open(SONUCLAR_DOSYA, encoding="utf-8") as f:
        return json.load(f)


def filtre_agirliklarini_yukle() -> dict:
    """akilli_filtre.py bunu çağırır."""
    if not os.path.exists(FILTRE_AGIR_DOSYA):
        # Varsayılan değerler (henüz backtest çalışmadıysa)
        return {
            "edge_esigi":   0.10,
            "sharp_bonus":  10,
            "sharp_ceza":   25,
            "lig_bonuslar": {},
            "oyna_esigi":   65,
            "dikkat_esigi": 45,
            "kaynak":       "varsayilan",
        }
    with open(FILTRE_AGIR_DOSYA, encoding="utf-8") as f:
        return json.load(f)


def edge_kalibrasyon_yukle() -> dict:
    if not os.path.exists(EDGE_KALIB_DOSYA):
        return {}
    with open(EDGE_KALIB_DOSYA, encoding="utf-8") as f:
        return json.load(f)


def gercek_edge_sikistir(edge: float) -> float:
    """
    Sabit formül yerine gerçek veriden öğrenilmiş eğriyi kullan.
    Eğer backtest çalışmadıysa eski yönteme düş.
    """
    kalib = edge_kalibrasyon_yukle()
    if not kalib:
        # Eski yöntem
        if edge > 0.25:
            asiri = edge - 0.25
            return round(0.25 + asiri * 0.35, 4)
        return edge

    # Bu edge'in gerçek ROI'sunu bul
    for etiket, d in kalib.items():
        if d["alt"] <= edge < d["ust"]:
            if not d["guvenilir"]:
                # Veri az → muhafazakar sıkıştır
                return round(edge * 0.7, 4)
            if d["roi"] < 0:
                # Bu aralıkta gerçekte para kaybediyoruz → sert sıkıştır
                return round(edge * 0.3, 4)
            elif d["roi"] < 0.05:
                # Marginal → hafif sıkıştır
                return round(edge * 0.8, 4)
            else:
                # Gerçekten karlı → dokunma
                return edge

    return edge


# ════════════════════════════════════════════════════════════════
#  Rapor
# ════════════════════════════════════════════════════════════════

def _rapor_yazdir(sonuclar: dict):
    ozet       = sonuclar["ozet"]
    edge_kalib = sonuclar["edge_kalibrasyon"]
    lig_guven  = sonuclar["lig_guven"]
    sharp_etki = sonuclar["sharp_etki"]

    print()
    print("═" * 60)
    print("  📊  WALK-FORWARD BACKTEST RAPORU")
    print("═" * 60)
    print(f"  Toplam tahmin  : {ozet['toplam_tahmin']}")
    print(f"  Genel accuracy : %{ozet['genel_accuracy']*100:.1f}")
    print(f"  Brier Score    : {ozet.get('brier_score', 'N/A')}")
    if ozet.get('brier_rolling') and ozet['brier_rolling'] != ozet.get('brier_score'):
        print(f"  Rolling Brier  : {ozet['brier_rolling']} (son 200 tahmin)")
    print()

    print("  📈 Edge Kalibrasyon:")
    print(f"  {'Aralık':<14} {'n':>5} {'Accuracy':>10} {'ROI':>8} {'Güvenilir'}")
    print("  " + "-" * 50)
    for etiket, d in sorted(edge_kalib.items(), key=lambda x: x[1]["alt"]):
        guvenir = "✅" if d["guvenilir"] else "⚠️ "
        print(f"  {d['alt']:+.2f} – {d['ust']:+.2f}   "
              f"{d['n']:>5}   %{d['accuracy']*100:>6.1f}   "
              f"%{d['roi']*100:>+6.1f}   {guvenir}")

    print()
    print("  🏆 Lig Güven Tablosu (veriden):")
    print(f"  {'Lig':<20} {'n':>5} {'Accuracy':>10} {'Faktör':>8}")
    print("  " + "-" * 50)
    for lig, d in sorted(lig_guven.items(), key=lambda x: -x[1]["faktor"]):
        print(f"  {lig:<20} {d['n']:>5}   %{d['accuracy']*100:>6.1f}   {d['faktor']:>6.3f}")

    print()
    print("  💰 Sharp Para Etkisi:")
    print(f"  Uyumlu accuracy  : %{sharp_etki['sharp_uyumlu_acc']*100:.1f}  (n={sharp_etki['sharp_uyumlu_n']})")
    print(f"  Çelişki accuracy : %{sharp_etki['sharp_celisi_acc']*100:.1f}  (n={sharp_etki['sharp_celisi_n']})")
    print(f"  Sharp yok acc    : %{sharp_etki['sharp_yok_acc']*100:.1f}  (n={sharp_etki['sharp_yok_n']})")
    print(f"  ► Uyumlu avantaj : +{sharp_etki['uyumlu_avantaj']*100:.1f} puan")
    print()

    agirliklar = filtre_agirliklarini_yukle()
    print("  ⚙️  Hesaplanan Filtre Ağırlıkları:")
    print(f"  Edge eşiği    : +{agirliklar['edge_esigi']:.3f}")
    print(f"  Sharp bonus   : +{agirliklar['sharp_bonus']}")
    print(f"  Sharp ceza    : -{agirliklar['sharp_ceza']}")
    print(f"  En iyi lig    : {agirliklar['en_iyi_lig']}")
    print("═" * 60)