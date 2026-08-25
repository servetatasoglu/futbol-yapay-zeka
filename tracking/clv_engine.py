# analysis/clv_engine.py
"""
CLV Engine v2 — Gerçek Kapanış Oranı Değer Motoru
══════════════════════════════════════════════════════════════════

Dünya standardı CLV Engine özellikleri:
  1. Açılış oranı kaydı (bahis anında)
  2. Kapanış oranı takibi (maç başlamadan son oran)
  3. CLV = (Alınan Oran / Kapanış) - 1  → pozitif = iyi zamanlama
  4. EV (Expected Value) hesabı
  5. Negatif CLV filtresi → otomatik bahis engeli
  6. Lig bazlı CLV dağılımı analizi
  7. Sharp para etkisi ölçümü (CLV vs oran hareketi korelasyonu)

CLV Pozitif Olmanın Önemi:
  - Joseph Buchdahl (12 Yards Away) araştırması kanıtladı:
    CLV pozitif olan bahisçiler uzun vadede karlı
    CLV negatif olanlar kaybeder (sonuç ne olursa olsun)
  - Pinnacle'ın kendi modeli: CLV en güçlü uzun vadeli karlılık göstergesi
"""

import csv
import os
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Optional

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR  = os.path.join(BASE_DIR, "data")
LOGS_DIR  = os.path.join(BASE_DIR, "logs")

# Ana CLV log dosyası (v1 ile uyumlu)
CLV_PATH  = os.path.join(LOGS_DIR, "clv_log.csv")
# Genişletilmiş CLV engine logu (açılış oranı dahil)
CLV_ENGINE_PATH = os.path.join(DATA_DIR, "clv_engine.json")

CLV_HEADER = [
    "Tarih", "Ev", "Dep", "Lig", "Tahmin",
    "AcilisOran",      # Bahis girildiğindeki oran (yeni)
    "AlinanOran",      # Gerçekte alınan oran
    "KapanisOran",     # Maç kapanışındaki oran
    "CLV", "CLVYuzde",
    "EV",              # Expected Value (yeni)
    "OranHareketi",    # (KapanışOran - AçılışOran) / AçılışOran (yeni)
    "GercekSonuc"
]


# ════════════════════════════════════════════════════════════════
#  Yardımcı fonksiyonlar
# ════════════════════════════════════════════════════════════════

def _clv_hesapla(alinan_oran: float, kapanis_oran: float) -> float:
    """CLV = (Alınan Oran / Kapanış Oranı) - 1"""
    if alinan_oran <= 1 or kapanis_oran <= 1:
        return None
    return round(alinan_oran / kapanis_oran - 1, 4)


def _ev_hesapla(model_p: float, alinan_oran: float) -> float:
    """
    EV = (model_p × net_kazanç) - (1 - model_p)
    EV > 0: pozitif beklenti
    EV < 0: negatif beklenti
    """
    if alinan_oran <= 1 or model_p <= 0 or model_p >= 1:
        return 0.0
    net_kazanc = alinan_oran - 1
    ev = model_p * net_kazanc - (1 - model_p)
    return round(ev, 4)


def _oran_hareketi(acilis_oran: float, kapanis_oran: float) -> float:
    """
    Oran hareketi = (kapanış - açılış) / açılış
    Pozitif: oran yükseldi (lehimize hareket)
    Negatif: oran düştü (aleyhimize hareket = sharp bet karşı tarafta)
    """
    if acilis_oran <= 1 or kapanis_oran <= 1:
        return 0.0
    return round((kapanis_oran - acilis_oran) / acilis_oran, 4)


# ════════════════════════════════════════════════════════════════
#  Kayıt fonksiyonları
# ════════════════════════════════════════════════════════════════

def clv_log_baslat():
    os.makedirs(LOGS_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(CLV_PATH):
        with open(CLV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(CLV_HEADER)


def clv_kaydet(
    ev: str, dep: str, lig: str, tahmin: str,
    alinan_oran: float,
    kapanis_oran: float,
    acilis_oran: float = 0.0,
    model_p: float = 0.0,
    tarih: str = "",
    gercek_sonuc: str = "",
) -> Optional[dict]:
    """
    CLV değerini hesaplayıp log'a yazar.

    Parametreler:
      alinan_oran  : Gerçekte girildiğimiz oran
      kapanis_oran : Maç öncesi son oran (Pinnacle/sharp book)
      acilis_oran  : Bahsin açıldığı ilk oran (varsa)
      model_p      : Modelin tahmin ettiği olasılık (EV için)
    """
    clv_log_baslat()

    if alinan_oran <= 1 or kapanis_oran <= 1:
        return None

    clv        = _clv_hesapla(alinan_oran, kapanis_oran)
    clv_yuzde  = round(clv * 100, 2) if clv is not None else "None"
    ev_katsayi = _ev_hesapla(model_p, alinan_oran) if model_p > 0 else "None"
    oran_har   = _oran_hareketi(acilis_oran, kapanis_oran) if acilis_oran > 1 else "None"

    with open(CLV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            tarih, ev, dep, lig, tahmin,
            round(acilis_oran, 3) if acilis_oran else "None", 
            round(alinan_oran, 3) if alinan_oran else "None", 
            round(kapanis_oran, 3) if kapanis_oran else "None",
            round(clv, 4) if clv is not None else "None", 
            clv_yuzde,
            round(ev_katsayi, 4) if ev_katsayi != "None" else "None", 
            round(oran_har, 4) if oran_har != "None" else "None",
            gercek_sonuc
        ])

    if clv is None:
        return None

    return {
        "clv":          round(clv, 4) if clv is not None else 0.0,
        "clv_yuzde":    clv_yuzde,
        "ev":           round(ev_katsayi, 4) if ev_katsayi != "None" else 0.0,
        "oran_hareketi":round(oran_har, 4) if oran_har != "None" else 0.0,
        "yorum":        _clv_yorum(clv) if clv is not None else "CLV Yok",
    }


def _clv_yorum(clv: float) -> str:
    if clv >= 0.05:   return "✅ Güçlü CLV — mükemmel zamanlama"
    if clv >= 0.02:   return "🟢 Pozitif CLV — iyi zamanlama"
    if clv >= 0.00:   return "🟡 Nötr CLV — kabul edilebilir"
    if clv >= -0.03:  return "🟠 Hafif negatif CLV — dikkat"
    return "🔴 Negatif CLV — geç/kötü zamanlama"


# ════════════════════════════════════════════════════════════════
#  CLV Filtresi — Bahis öncesi otomatik kontrol
# ════════════════════════════════════════════════════════════════

def clv_filtresi(tahmin: dict) -> dict:
    """
    Bir tahminin CLV geçmişine bakarak devam edilip edilmeyeceğini söyler.

    Mantık:
      - Bu lig + tahmin tipi için son 20 CLV değerinin ortalamasına bak
      - Ortalama < -0.03 ise → ATLA (kötü zamanlama sistemi)
      - Ortalama > +0.02 ise → OYNA (çifte onay)
    """
    lig   = tahmin.get("lig_kodu", "")
    tip   = tahmin.get("tahmin", "")
    alinan = float(tahmin.get("oran", 0) or 0)

    gecmis_clv = _gecmis_clv_yukle(lig, tip, son_n=20)

    if not gecmis_clv:
        return {"durum": "veri_yok", "ort_clv": 0.0, "karar": "OYNA", "mesaj": "CLV geçmişi yok — devam"}

    ort = sum(gecmis_clv) / len(gecmis_clv)

    if ort < -0.03:
        return {
            "durum":   "negatif",
            "ort_clv": round(ort * 100, 2),
            "karar":   "ATLA",
            "mesaj":   f"⚠️  {lig} lig CLV ortalaması %{ort*100:.1f} — zamanlamayı düzelt",
        }
    elif ort >= 0.02:
        return {
            "durum":   "pozitif",
            "ort_clv": round(ort * 100, 2),
            "karar":   "OYNA",
            "mesaj":   f"✅ CLV pozitif %{ort*100:.1f} — sistem piyasadan önce value buluyor",
        }
    else:
        return {
            "durum":   "notr",
            "ort_clv": round(ort * 100, 2),
            "karar":   "DIKKAT",
            "mesaj":   f"🟡 CLV nötr %{ort*100:.1f} — izlemeye devam",
        }


def _gecmis_clv_yukle(lig: str, tahmin_tipi: str, son_n: int = 20) -> list:
    """CLV log'undan son N kaydı oku."""
    if not os.path.exists(CLV_PATH):
        return []
    satirlar = []
    try:
        with open(CLV_PATH, "r", encoding="utf-8") as f:
            for satir in csv.DictReader(f):
                if lig and satir.get("Lig", "") != lig:
                    continue
                clv_str = satir.get("CLV") or satir.get("CLVYuzde")
                if not clv_str:
                    continue
                try:
                    clv_val = float(clv_str)
                    # CLVYuzde ise yüzdeyi ondalığa çevir
                    if abs(clv_val) > 1:
                        clv_val /= 100
                    satirlar.append(clv_val)
                except (ValueError, TypeError):
                    continue
    except Exception:
        return []
    return satirlar[-son_n:]


# ════════════════════════════════════════════════════════════════
#  Gelişmiş CLV Avcısı — The Odds API entegrasyonu
# ════════════════════════════════════════════════════════════════

def gercek_clv_avcisi(tahminler_log: str = None):
    """
    GERÇEK CLV (Closing Line Value) BULUCU — Gelişmiş Versiyon

    Yenilikler v2:
      - Pinnacle öncelikli oran seçimi (sharp book)
      - Açılış oranı bağlamı (oran hareketi ölçümü)
      - Model olasılığından EV hesabı
      - Lig bazlı CLV istatistiki güncelleme
    """
    if not tahminler_log or not os.path.exists(tahminler_log):
        return

    try:
        from config.settings import LIGLER, ODDS_API_KEY
    except ImportError:
        return

    if not ODDS_API_KEY:
        return

    import requests
    from datetime import datetime, timezone

    # Zaten CLV'si hesaplanmışları bul
    islenmisler = set()
    if os.path.exists(CLV_PATH):
        try:
            with open(CLV_PATH, "r", encoding="utf-8") as f:
                for s in csv.DictReader(f):
                    islenmisler.add(f"{s.get('Ev','')}||{s.get('Dep','')}||{s.get('Tahmin','')}")
        except Exception:
            pass

    # Bekleyen bahisleri oku
    try:
        with open(tahminler_log, "r", encoding="utf-8") as f:
            satirlar = list(csv.DictReader(f))
    except Exception:
        return

    simdi = datetime.now(timezone.utc)
    aranacak_ligler = defaultdict(list)

    for satir in satirlar:
        ev_t  = satir.get("Ev", "").strip()
        dep_t = satir.get("Dep", "").strip()
        tahmin_t = satir.get("Tahmin", "").strip()
        anahtar  = f"{ev_t}||{dep_t}||{tahmin_t}"

        if anahtar in islenmisler:
            continue

        tarih_str = satir.get("MacTarihi", "")
        if not tarih_str:
            continue

        try:
            mac_dt = datetime.fromisoformat(tarih_str.replace("Z", "+00:00"))
            if mac_dt.tzinfo is None:
                mac_dt = mac_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        fark_dk = (mac_dt - simdi).total_seconds() / 60.0

        # Başlamasına tam olarak 5 ile 10 dakika kala olan kapanış oranlarını yakala
        if 5 <= fark_dk <= 10:
            lig = satir.get("Lig", "")
            aranacak_ligler[lig].append({
                "ev":         ev_t,
                "dep":        dep_t,
                "tahmin":     tahmin_t,
                "alinan_oran": satir.get("Oran", "0"),
                "acilis_oran": satir.get("AcilisOran", "0"),
                "model_p":     satir.get("Olasilik", "0"),
                "tarih":       tarih_str,
            })

    if not aranacak_ligler:
        return

    yeni_kayit = 0

    for lig_kodu, bekleyen_maclar in aranacak_ligler.items():
        bilgi = LIGLER.get(lig_kodu)
        if not bilgi:
            continue

        odds_key = bilgi.get("odds_key", "")
        if not odds_key:
            continue

        url = (
            f"https://api.the-odds-api.com/v4/sports/{odds_key}/odds/"
            f"?apiKey={ODDS_API_KEY}&regions=eu,uk&markets=h2h&oddsFormat=decimal"
        )
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception:
            continue

        # Oranları indexle — Pinnacle öncelikli
        _ONCELIK = ["pinnacle", "betfair_ex_eu", "betfair", "bet365", "unibet"]
        api_maclar = {}
        for game in data:
            try:
                e = game.get("home_team", "")
                d = game.get("away_team", "")
                ev_oran = dep_oran = ber_oran = 0.0

                for bookie_key in _ONCELIK:
                    for bookie in game.get("bookmakers", []):
                        if bookie.get("key") != bookie_key:
                            continue
                        for mk in bookie.get("markets", []):
                            if mk["key"] == "h2h":
                                for out in mk["outcomes"]:
                                    n = out["name"]
                                    p = float(out["price"])
                                    if n == e:            ev_oran  = p
                                    elif n == d:          dep_oran = p
                                    elif n.lower() in ("draw", "beraberlik"): ber_oran = p
                    if ev_oran > 1.0:
                        break  # Pinnacle/sharp book bulundu

                if ev_oran > 1.0:
                    api_maclar[f"{e}|{d}"] = {
                        "ev": ev_oran, "dep": dep_oran, "ber": ber_oran
                    }
            except Exception:
                continue

        # İsim benzerliği ile eşleştir
        try:
            from data.matcher import isim_benzerlik
            _esim = True
        except ImportError:
            _esim = False

        for b_mac in bekleyen_maclar:
            try:
                alinan_oran  = float(b_mac["alinan_oran"]  or 0)
                acilis_oran  = float(b_mac["acilis_oran"]   or 0)
                model_p      = float(b_mac["model_p"]       or 0)
            except (ValueError, TypeError):
                continue

            if alinan_oran <= 1:
                continue

            # API'deki maçla eşleştir
            eslesen = None
            for api_k, api_v in api_maclar.items():
                api_e, api_d = api_k.split("|")
                if _esim:
                    try:
                        if isim_benzerlik(b_mac["ev"], api_e) > 0.75 and \
                           isim_benzerlik(b_mac["dep"], api_d) > 0.75:
                            eslesen = api_v
                            break
                    except Exception:
                        pass
                else:
                    if b_mac["ev"][:4].lower() in api_e.lower() and \
                       b_mac["dep"][:4].lower() in api_d.lower():
                        eslesen = api_v
                        break

            if not eslesen:
                continue

            # Tahmin yönüne göre kapanış oranını seç
            t = b_mac["tahmin"]
            if "Ev" in t or t in ("Ev Sahibi Kazanır", "Ev Sahibi Kazanir"):
                kapanis = eslesen["ev"]
            elif "Dep" in t or t in ("Deplasman Kazanır", "Deplasman Kazanir"):
                kapanis = eslesen["dep"]
            elif "Beraber" in t or t == "Beraberlik":
                kapanis = eslesen["ber"]
            else:
                continue

            if kapanis <= 1:
                continue

            sonuc = clv_kaydet(
                b_mac["ev"], b_mac["dep"], lig_kodu, b_mac["tahmin"],
                alinan_oran=alinan_oran,
                kapanis_oran=kapanis,
                acilis_oran=acilis_oran,
                model_p=model_p,
                tarih=b_mac["tarih"],
            )
            if sonuc:
                yeni_kayit += 1
                clv_val = sonuc["clv_yuzde"]
                yorum   = _clv_yorum(sonuc["clv"])
                print(f"    📈 CLV: {b_mac['ev']} vs {b_mac['dep']} → "
                      f"%{clv_val:+.1f} {yorum}")

    if yeni_kayit > 0:
        print(f"  ✅ CLV Engine: {yeni_kayit} maçın kapanış oranı kaydedildi")
        _lig_clv_istatistigi_guncelle()


# ════════════════════════════════════════════════════════════════
#  Lig Bazlı CLV İstatistiği
# ════════════════════════════════════════════════════════════════

def _lig_clv_istatistigi_guncelle():
    """Lig bazlı ortalama CLV'yi hesapla ve kaydet."""
    if not os.path.exists(CLV_PATH):
        return

    lig_clv = defaultdict(list)
    try:
        with open(CLV_PATH, "r", encoding="utf-8") as f:
            for satir in csv.DictReader(f):
                lig  = satir.get("Lig", "")
                clv_str = satir.get("CLV", "")
                if not clv_str or not lig:
                    continue
                try:
                    lig_clv[lig].append(float(clv_str))
                except (ValueError, TypeError):
                    continue
    except Exception:
        return

    istatistik = {}
    for lig, degerler in lig_clv.items():
        if len(degerler) < 5:
            continue
        ort = sum(degerler) / len(degerler)
        pozitif = sum(1 for c in degerler if c > 0) / len(degerler)
        istatistik[lig] = {
            "n":             len(degerler),
            "ort_clv":       round(ort, 4),
            "ort_clv_yuzde": round(ort * 100, 2),
            "pozitif_oran":  round(pozitif * 100, 1),
            "durum":         "pozitif" if ort > 0.01 else ("notr" if ort > -0.02 else "negatif"),
        }

    try:
        path = os.path.join(DATA_DIR, "clv_lig_istatistik.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(istatistik, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def lig_clv_istatistigi_yukle() -> dict:
    """Lig bazlı CLV istatistiğini yükle."""
    path = os.path.join(DATA_DIR, "clv_lig_istatistik.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ════════════════════════════════════════════════════════════════
#  Ana Rapor
# ════════════════════════════════════════════════════════════════

def clv_raporu(min_ornek: int = 5) -> dict:
    """Gelişmiş CLV raporu — lig bazlı analiz dahil."""
    if not os.path.exists(CLV_PATH):
        return {"mesaj": "CLV log dosyası henüz yok"}

    satirlar = []
    try:
        with open(CLV_PATH, "r", encoding="utf-8") as f:
            for satir in csv.DictReader(f):
                try:
                    clv       = float(satir.get("CLV") or satir.get("CLVYuzde", 0) or 0)
                    # CLVYuzde formatında geldiyse normalize et
                    if abs(clv) > 1:
                        clv /= 100
                    satirlar.append({
                        "clv":      clv,
                        "ev":       float(satir.get("EV", 0) or 0),
                        "lig":      satir.get("Lig", ""),
                        "tahmin":   satir.get("Tahmin", ""),
                        "alinan":   float(satir.get("AlinanOran", 0) or 0),
                        "kapanis":  float(satir.get("KapanisOran", 0) or 0),
                        "gercek":   satir.get("GercekSonuc", ""),
                        "oran_har": float(satir.get("OranHareketi", 0) or 0),
                    })
                except (ValueError, TypeError, KeyError):
                    continue
    except Exception:
        return {"mesaj": "CLV log okunamadı"}

    if len(satirlar) < min_ornek:
        return {
            "mesaj":   f"Yeterli CLV verisi yok ({len(satirlar)}/{min_ornek})",
            "ornek_n": len(satirlar),
        }

    clv_vals   = [s["clv"] for s in satirlar]
    pozitifler = [c for c in clv_vals if c > 0]
    ort_clv    = sum(clv_vals) / len(clv_vals)
    ort_ev     = sum(s["ev"] for s in satirlar) / len(satirlar)

    # Gerçek ROI hesabı
    gercek_sonuclu = [s for s in satirlar if s["gercek"]]
    roi = 0.0
    if gercek_sonuclu:
        kazanc = 0.0
        for s in gercek_sonuclu:
            t = s["tahmin"]
            g = s["gercek"]
            kazandi = (
                ("Ev" in t and g == "ev") or
                ("Dep" in t and g == "dep") or
                ("Beraber" in t and g == "ber")
            )
            if kazandi:
                kazanc += s["alinan"] - 1
            else:
                kazanc -= 1
        roi = kazanc / len(gercek_sonuclu) * 100

    # Lig bazlı CLV
    lig_bazli = defaultdict(list)
    for s in satirlar:
        if s["lig"]:
            lig_bazli[s["lig"]].append(s["clv"])

    lig_ozet = {
        lig: {
            "n": len(vals),
            "ort_clv_pct": round(sum(vals) / len(vals) * 100, 2),
            "durum": "✅" if sum(vals)/len(vals) > 0.01 else ("🟡" if sum(vals)/len(vals) > -0.02 else "🔴")
        }
        for lig, vals in lig_bazli.items() if len(vals) >= 3
    }

    # Sharp money korelasyonu (oran hareketi vs CLV)
    oran_hareketliler = [s for s in satirlar if abs(s["oran_har"]) > 0.01]
    lehimize_hare = [s for s in oran_hareketliler if s["oran_har"] > 0]
    aleyhimize_hare = [s for s in oran_hareketliler if s["oran_har"] < 0]

    return {
        "toplam_bahis":      len(satirlar),
        "ortalama_clv_pct":  round(ort_clv * 100, 2),
        "pozitif_clv_oran":  round(len(pozitifler) / len(clv_vals) * 100, 1),
        "ortalama_ev":       round(ort_ev * 100, 2),
        "max_clv_pct":       round(max(clv_vals) * 100, 2),
        "min_clv_pct":       round(min(clv_vals) * 100, 2),
        "roi_yuzde":         round(roi, 2),
        "lig_bazli_clv":     lig_ozet,
        "sharp_etki": {
            "lehimize_hare_n":   len(lehimize_hare),
            "aleyhimize_hare_n": len(aleyhimize_hare),
            "lehimize_ort_clv":  round(sum(s["clv"] for s in lehimize_hare) / max(len(lehimize_hare), 1) * 100, 2),
            "aleyhimize_ort_clv":round(sum(s["clv"] for s in aleyhimize_hare) / max(len(aleyhimize_hare), 1) * 100, 2),
        },
        "genel_yorum": (
            "✅ Pozitif CLV — model piyasadan önce value buluyor. Uzun vadede karlı."
            if ort_clv > 0.02 else (
                "🟡 Nötr CLV — sistem piyasayla aynı hızda. Zamanlama iyileştirilebilir."
                if ort_clv > -0.02 else
                "🔴 Negatif CLV — sistem piyasadan geç giriyor. Oran kaynağı veya zamanlama düzeltilmeli."
            )
        ),
    }


def clv_yazdir(rapor: dict):
    SEP = "═" * 60
    print(f"\n{SEP}")
    print(f"  📈  CLV ENGINE v2 RAPORU")
    print(SEP)

    if "mesaj" in rapor:
        print(f"  ℹ️  {rapor['mesaj']}")
        print(SEP)
        return

    print(f"  Toplam bahis       : {rapor['toplam_bahis']}")
    print(f"  Ortalama CLV       : %{rapor['ortalama_clv_pct']:+.2f}")
    print(f"  Pozitif CLV oranı  : %{rapor['pozitif_clv_oran']:.1f}")
    print(f"  Ortalama EV        : %{rapor['ortalama_ev']:+.2f}")
    print(f"  Max CLV            : %{rapor['max_clv_pct']:+.2f}")
    print(f"  Min CLV            : %{rapor['min_clv_pct']:+.2f}")
    print(f"  Gerçek ROI         : %{rapor['roi_yuzde']:+.2f}")
    print()

    if rapor.get("lig_bazli_clv"):
        print(f"  🏆 Lig Bazlı CLV:")
        for lig, d in sorted(rapor["lig_bazli_clv"].items(),
                              key=lambda x: x[1]["ort_clv_pct"], reverse=True):
            print(f"    {lig:<12} {d['durum']}  %{d['ort_clv_pct']:+.2f}  (n={d['n']})")
    print()

    if rapor.get("sharp_etki"):
        se = rapor["sharp_etki"]
        print(f"  💰 Sharp Para Etkisi (oran hareketi > %1):")
        print(f"    Lehimize hareket  : {se['lehimize_hare_n']}  maç → ort CLV %{se['lehimize_ort_clv']:+.2f}")
        print(f"    Aleyhimize hareket: {se['aleyhimize_hare_n']} maç → ort CLV %{se['aleyhimize_ort_clv']:+.2f}")
    print()
    print(f"  {rapor['genel_yorum']}")
    print(SEP)
