# analysis/kupon_log.py
"""
Kupon Takip Sistemi
─────────────────────────────────────────────────────────────
Her önerilen kupon kaydedilir.
Maçlar bitince sonuçlar otomatik doldurulur.
Kupon bazında ROI, isabet oranı hesaplanır.

Kupon türleri:
  - 2'li kupon: 2 maç, ikisi de tutarsa kazanır
  - 3'lü kupon: 3 maç, üçü de tutarsa kazanır
"""

import csv
import os
import json
from datetime import datetime

LOG_DIR       = "logs"
KUPON_LOG     = os.path.join(LOG_DIR, "kupon_log.csv")
KUPON_DETAY   = os.path.join(LOG_DIR, "kupon_detay.json")

HEADER = [
    "Tarih", "KuponID", "Tur", "ToplamOran", "BirlesikP", "Edge",
    "Mac1Ev", "Mac1Dep", "Mac1Tahmin", "Mac1Oran", "Mac1Sonuc",
    "Mac2Ev", "Mac2Dep", "Mac2Tahmin", "Mac2Oran", "Mac2Sonuc",
    "Mac3Ev", "Mac3Dep", "Mac3Tahmin", "Mac3Oran", "Mac3Sonuc",
    "KuponSonuc",   # kazandi / kaybetti / bekliyor
    "KazanılanKat", # kazanılan kat (toplam oran veya 0)
]


def _kupon_id(tarih_str: str, index: int, tur: str) -> str:
    """Benzersiz kupon ID: 20260309_2li_1 gibi"""
    gun = tarih_str.replace(".", "").replace(" ", "_").replace(":", "")[:8]
    return f"{gun}_{tur}_{index}"


def kuponlari_kaydet(kupon_2li: list, kupon_3lu: list, tarih_str: str):
    """Önerilen tüm kuponları CSV'ye yazar."""
    os.makedirs(LOG_DIR, exist_ok=True)

    if not os.path.exists(KUPON_LOG):
        with open(KUPON_LOG, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADER)

    satirlar = []

    # 2'li kuponlar
    for i, k in enumerate(kupon_2li, 1):
        b = k["bahisler"]
        kid = _kupon_id(tarih_str, i, "2li")
        satirlar.append([
            tarih_str, kid, "2li",
            f"{k['toplam_oran']:.2f}",
            f"{k['birlesik_p']:.4f}",
            f"{k['edge']:.4f}",
            # Mac 1
            b[0]["ev"], b[0]["dep"], b[0]["tahmin"], f"{b[0]['oran']:.2f}", "",
            # Mac 2
            b[1]["ev"], b[1]["dep"], b[1]["tahmin"], f"{b[1]['oran']:.2f}", "",
            # Mac 3 yok
            "", "", "", "", "",
            "bekliyor", "",
        ])

    # 3'lü kuponlar
    for i, k in enumerate(kupon_3lu, 1):
        b = k["bahisler"]
        kid = _kupon_id(tarih_str, i, "3lu")
        satirlar.append([
            tarih_str, kid, "3lu",
            f"{k['toplam_oran']:.2f}",
            f"{k['birlesik_p']:.4f}",
            f"{k['edge']:.4f}",
            # Mac 1
            b[0]["ev"], b[0]["dep"], b[0]["tahmin"], f"{b[0]['oran']:.2f}", "",
            # Mac 2
            b[1]["ev"], b[1]["dep"], b[1]["tahmin"], f"{b[1]['oran']:.2f}", "",
            # Mac 3
            b[2]["ev"], b[2]["dep"], b[2]["tahmin"], f"{b[2]['oran']:.2f}", "",
            "bekliyor", "",
        ])
        
    try:
        from execution.sqlite_logger import sqlite_kupon_kaydet
        sqlite_kupon_kaydet(satirlar)
    except Exception as e:
        print(f"  ⚠️  SQLite kupon yedeği alınamadı: {e}")

    with open(KUPON_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for satir in satirlar:
            w.writerow(satir)

    toplam = len(kupon_2li) + len(kupon_3lu)
    if toplam > 0:
        print(f"  📋 {toplam} kupon kaydedildi → {KUPON_LOG}")


def kupon_sonuclari_guncelle(tahmin_log: str):
    """
    DÜZELTİLDİ v2: Tahminler_log'dan fallback ile kupon sonuçları güncellenir.
    Sorun: tahmin log'daki Ev/Dep adları büyük/küçük harf veya kısaltma farklılığı
    nedeniyle eşleşemiyordu. Şimdi hem tam eşleşme hem bulanık eşleştirme var.
    """
    if not os.path.exists(KUPON_LOG):
        return

    # API'den güncel sonuçları çek
    try:
        from execution.result_updater import _api_sonuclari_cek
        api_sonuclar = _api_sonuclari_cek()
    except Exception:
        api_sonuclar = {}

    # tahminler_log'dan fallback dict oluştur
    tahmin_sonuc_dict: dict = {}
    if os.path.exists(tahmin_log):
        with open(tahmin_log, "r", encoding="utf-8") as f:
            for satir in csv.DictReader(f):
                gercek = satir.get("GercekSonuc", "").strip()
                if not gercek:
                    continue
                # Normalize: log'da ev/ber/dep formatında olmalı
                ev_str  = satir.get("Ev",  "").strip()
                dep_str = satir.get("Dep", "").strip()
                tarih   = satir.get("MacTarihi", "").strip()[:10]
                # Birden fazla anahtar formatıyla kaydet
                for key in [
                    f"{ev_str}||{dep_str}",
                    f"{ev_str.lower()}||{dep_str.lower()}",
                    f"{ev_str[:15]}||{dep_str[:15]}",
                ]:
                    tahmin_sonuc_dict[key] = {"sonuc": gercek, "tarih": tarih}

    # API sonuçları varsa öncelik onlarda
    sonuc_dict = api_sonuclar if api_sonuclar else tahmin_sonuc_dict
    if not sonuc_dict:
        return

    TAHMIN_SONUC_MAP = {
        "Ev Sahibi Kazanır": "ev",
        "Beraberlik":        "ber",
        "Deplasman Kazanır": "dep",
    }

    bugun = datetime.utcnow().date()

    with open(KUPON_LOG, "r", encoding="utf-8") as f:
        reader     = csv.DictReader(f)
        satirlar   = list(reader)
        fieldnames = reader.fieldnames or HEADER

    guncellenen = 0

    for satir in satirlar:
        if satir.get("KuponSonuc", "").strip() != "bekliyor":
            continue

        tur        = satir.get("Tur", "2li")
        mac_sayisi = 3 if tur == "3lu" else 2

        mac_alanlari = [
            ("Mac1Ev", "Mac1Dep", "Mac1Tahmin", "Mac1Sonuc"),
            ("Mac2Ev", "Mac2Dep", "Mac2Tahmin", "Mac2Sonuc"),
            ("Mac3Ev", "Mac3Dep", "Mac3Tahmin", "Mac3Sonuc"),
        ]

        tum_sonuclar_var = True
        hepsi_tuttu      = True

        for ev_k, dep_k, tahmin_k, sonuc_k in mac_alanlari[:mac_sayisi]:
            ev     = satir.get(ev_k, "").strip()
            dep    = satir.get(dep_k, "").strip()
            tahmin = satir.get(tahmin_k, "").strip()

            if not ev or not dep:
                continue

            # Tarih bilgisi bilinmiyorsa bu maçı atla (güvenli taraf)
            # MacTarihi kuponda kayıtlı değil, API'den gelen tarihle karşılaştır
            anahtar = f"{ev}||{dep}"
            kayit   = sonuc_dict.get(anahtar)

            # Bulanık eşleştirme
            if kayit is None:
                for api_key, api_val in sonuc_dict.items():
                    api_ev, api_dep = api_key.split("||")
                    if (ev in api_ev or api_ev in ev) and \
                       (dep in api_dep or api_dep in dep):
                        kayit = api_val
                        break

            if kayit is None:
                tum_sonuclar_var = False
                break

            # Tarih kontrolü — gelecekteki maç mı?
            tarih_str = kayit.get("tarih", "") if isinstance(kayit, dict) else ""
            if tarih_str:
                try:
                    from datetime import datetime as dt
                    mac_tarihi = dt.strptime(tarih_str, "%Y-%m-%d").date()
                    if mac_tarihi > bugun:
                        tum_sonuclar_var = False
                        break
                except ValueError:
                    tum_sonuclar_var = False
                    break
            else:
                # Tarih bilinmiyor → güvenli ol, atla
                tum_sonuclar_var = False
                break

            gercek   = kayit["sonuc"] if isinstance(kayit, dict) else kayit
            satir[sonuc_k] = gercek
            beklenen = TAHMIN_SONUC_MAP.get(tahmin, "")
            if gercek != beklenen:
                hepsi_tuttu = False

        if tum_sonuclar_var:
            if hepsi_tuttu:
                satir["KuponSonuc"]   = "kazandi"
                satir["KazanılanKat"] = satir.get("ToplamOran", "")
            else:
                satir["KuponSonuc"]   = "kaybetti"
                satir["KazanılanKat"] = "0"
            guncellenen += 1

    with open(KUPON_LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(satirlar)

    if guncellenen > 0:
        print(f"  ✅ {guncellenen} kupon sonucu güncellendi → {KUPON_LOG}")


def kupon_backtest(cikti: bool = True) -> dict:
    """
    Kupon log'dan performans raporu üretir.
    """
    if not os.path.exists(KUPON_LOG):
        return {}

    with open(KUPON_LOG, "r", encoding="utf-8") as f:
        satirlar = list(csv.DictReader(f))

    if not satirlar:
        return {}

    toplam     = len(satirlar)
    bekliyenler = sum(1 for s in satirlar if s.get("KuponSonuc") == "bekliyor")
    kazananlar  = sum(1 for s in satirlar if s.get("KuponSonuc") == "kazandi")
    kaybedenler = sum(1 for s in satirlar if s.get("KuponSonuc") == "kaybetti")
    gerceklesen = kazananlar + kaybedenler

    # ROI hesabı (her kupona 1 birim)
    kar_zarar = 0.0
    for s in satirlar:
        if s.get("KuponSonuc") == "kazandi":
            try:
                kar_zarar += float(s.get("ToplamOran", 1)) - 1
            except ValueError:
                kar_zarar += 0
        elif s.get("KuponSonuc") == "kaybetti":
            kar_zarar -= 1

    roi = (kar_zarar / gerceklesen * 100) if gerceklesen > 0 else 0.0

    # Tur bazında kırılım
    tur_bazli = {}
    for s in satirlar:
        tur = s.get("Tur", "?")
        if tur not in tur_bazli:
            tur_bazli[tur] = {"toplam": 0, "kazandi": 0, "kaybetti": 0, "kar": 0.0}
        tur_bazli[tur]["toplam"] += 1
        if s.get("KuponSonuc") == "kazandi":
            tur_bazli[tur]["kazandi"] += 1
            try:
                tur_bazli[tur]["kar"] += float(s.get("ToplamOran", 1)) - 1
            except ValueError:
                pass
        elif s.get("KuponSonuc") == "kaybetti":
            tur_bazli[tur]["kaybetti"] += 1
            tur_bazli[tur]["kar"] -= 1

    rapor = {
        "toplam_kupon":  toplam,
        "gerceklesen":   gerceklesen,
        "bekliyor":      bekliyenler,
        "kazandi":       kazananlar,
        "kaybetti":      kaybedenler,
        "isabet_orani":  round(kazananlar / gerceklesen, 4) if gerceklesen > 0 else 0,
        "roi":           round(roi, 2),
        "kar_zarar":     round(kar_zarar, 2),
        "tur_bazli":     tur_bazli,
    }

    if cikti:
        _rapor_yazdir(rapor)

    return rapor


def _rapor_yazdir(rapor):
    SEP = "═" * 58
    print(f"\n{SEP}")
    print(f"  🎫  KUPON BACKTEST RAPORU")
    print(SEP)
    print(f"  Toplam kupon : {rapor['toplam_kupon']}")
    print(f"  Gerçeklesen  : {rapor['gerceklesen']}  "
          f"(Bekliyor: {rapor['bekliyor']})")

    if rapor["gerceklesen"] > 0:
        emoji = "📈" if rapor["roi"] > 0 else "📉"
        print(f"\n  🎯 İsabet      : %{rapor['isabet_orani']*100:.1f}  "
              f"({rapor['kazandi']} kazandı / {rapor['kaybetti']} kaybetti)")
        print(f"  {emoji} ROI         : %{rapor['roi']:.1f}")
        print(f"  💰 Kar/Zarar   : {rapor['kar_zarar']:+.2f} birim")

        print(f"\n  📋 Tür Bazında:")
        for tur, d in rapor["tur_bazli"].items():
            g = d["kazandi"] + d["kaybetti"]
            if g > 0:
                isabet = d["kazandi"] / g * 100
                roi_tur = d["kar"] / g * 100
                emoji_t = "📈" if roi_tur > 0 else "📉"
                print(f"     {tur:<6} → İsabet: %{isabet:.1f}  "
                      f"{emoji_t} ROI: %{roi_tur:.1f}  "
                      f"({d['kazandi']}/{g})")

    print(SEP)
    