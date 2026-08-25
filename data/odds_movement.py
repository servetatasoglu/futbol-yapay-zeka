# scrapers/odds_hareket_v2.py
"""
Çok Noktalı Oran Hareketi Takip Modülü
─────────────────────────────────────────────────────────
SORUN (eski sistem):
  hareket_db sadece "ilk oran" saklıyordu.
  → Açılış ve şimdiki oran arasında sadece 2 nokta.
  → Sharp money tespiti için minimum 3 nokta gerekiyor.

ÇÖZÜM (bu modül):
  Her maç için zaman serisi: [{'zaman': ts, 'ev': 2.10, 'dep': 3.40}, ...]
  → En az 3 gözlem sonrasında güvenilir sinyal üretilir.
  → Trendi (hızlanıyor mu, yavaşlıyor mu) da hesaplar.

KULLANIM:
  Bu modülü canli_oranlar.py içindeki _oran_hareketi_hesapla()
  fonksiyonunun yerine kullanın.

  canli_oranlar.py içinde şu satırı değiştirin:
    hareket = _oran_hareketi_hesapla(mac_key, ev_oran, dep_oran, hareket_db)
  Bununla değiştirin:
    from data.odds_movement import oran_hareketi_hesapla_v2
    hareket = oran_hareketi_hesapla_v2(mac_key, ev_oran, dep_oran, hareket_db)
"""

import time


# Zaman serisi için maksimum saklanacak nokta sayısı
MAX_NOKTA = 24   # 4 saatlik pencerede 15dk aralıkla max 16 nokta, biraz pay


def oran_hareketi_hesapla_v2(mac_key: str,
                              ev_oran: float,
                              dep_oran: float,
                              hareket_db: dict) -> dict:
    """
    Zaman serisi bazlı oran hareketi ve sharp money tespiti.

    DEĞİŞİKLİK (eski _oran_hareketi_hesapla vs bu fonksiyon):
      Eski → sadece ilk oran saklanıyor (2 nokta).
      Yeni → zaman serisi liste formatı:
              hareket_db[mac_key] = {
                  'seri': [
                      {'zaman': 1741234567, 'ev': 2.10, 'dep': 3.40},
                      {'zaman': 1741235467, 'ev': 2.05, 'dep': 3.50},
                      ...
                  ]
              }

    Sinyal güvenilirliği:
      < 2 nokta  → "YOK" (veri yok)
      2 nokta    → zayıf sinyal
      3+ nokta   → güvenilir sinyal

    Döndürür:
      dict — canli_oranlar.py'nin beklediği format (geriye uyumlu)
    """
    simdi = time.time()

    # ── Zaman serisi güncelle ──────────────────────────────────
    if mac_key not in hareket_db:
        hareket_db[mac_key] = {"seri": []}

    entry = hareket_db[mac_key]

    # Eski format (sadece ilk_ev_oran / ilk_dep_oran) → yeni formata dönüştür
    if "ilk_ev_oran" in entry and "seri" not in entry:
        entry["seri"] = [{
            "zaman": entry.get("ilk_zaman", simdi - 3600),
            "ev":    entry["ilk_ev_oran"],
            "dep":   entry.get("ilk_dep_oran", dep_oran),
        }]
        # Eski anahtarları sil
        for k in ("ilk_ev_oran", "ilk_dep_oran", "ilk_zaman"):
            entry.pop(k, None)

    seri = entry.get("seri", [])

    # Son nokta ile aynı oran ise güncelleme yapma (gereksiz tekrar)
    if seri:
        son = seri[-1]
        if abs(son["ev"] - ev_oran) < 0.001 and abs(son["dep"] - dep_oran) < 0.001:
            pass  # aynı, güncelleme gerek yok — ama yine de hesapla
        else:
            seri.append({"zaman": simdi, "ev": ev_oran, "dep": dep_oran})
    else:
        seri.append({"zaman": simdi, "ev": ev_oran, "dep": dep_oran})

    # Maksimum nokta sayısını aş
    if len(seri) > MAX_NOKTA:
        seri = seri[-MAX_NOKTA:]
    entry["seri"] = seri

    # ── Hesaplamalar ───────────────────────────────────────────
    n = len(seri)

    # Yeterli veri yok
    if n < 2:
        return {
            "ev_hareket":   0.0,
            "dep_hareket":  0.0,
            "sharp_sinyal": "YOK",
            "hareket_gucu": 0.0,
            "ilk_oran":     True,
            "ilk_ev_oran":  ev_oran,
            "ilk_dep_oran": dep_oran,
            "nokta_sayisi": n,
        }

    ilk_ev  = seri[0]["ev"]
    ilk_dep = seri[0]["dep"]

    # Toplam değişim (açılış → şimdi)
    ev_degisim  = (ilk_ev  - ev_oran)  / ilk_ev  if ilk_ev  > 0 else 0.0
    dep_degisim = (ilk_dep - dep_oran) / ilk_dep if ilk_dep > 0 else 0.0

    # Son 3 noktadaki değişim hızı (trend)
    if n >= 3:
        onceki_ev  = seri[-3]["ev"]
        onceki_dep = seri[-3]["dep"]
        son_ev_deg  = (onceki_ev  - ev_oran)  / onceki_ev  if onceki_ev  > 0 else 0.0
        son_dep_deg = (onceki_dep - dep_oran) / onceki_dep if onceki_dep > 0 else 0.0
        # Trend hızlanıyorsa hareket gücünü artır
        hizlanma_ev  = son_ev_deg  / max(abs(ev_degisim),  0.001)
        hizlanma_dep = son_dep_deg / max(abs(dep_degisim), 0.001)
    else:
        hizlanma_ev  = 1.0
        hizlanma_dep = 1.0

    # Sharp money eşiği
    # 3+ nokta varsa daha sıkı eşik (0.03 → 0.025)
    ESIK = 0.025 if n >= 3 else 0.03

    if ev_degisim > dep_degisim and ev_degisim > ESIK:
        sharp_sinyal = "EV"
        # Hızlanıyorsa bonus güç
        hareket_gucu = min(1.0, ev_degisim * 5 * max(1.0, hizlanma_ev * 0.3 + 0.7))
    elif dep_degisim > ev_degisim and dep_degisim > ESIK:
        sharp_sinyal = "DEP"
        hareket_gucu = min(1.0, dep_degisim * 5 * max(1.0, hizlanma_dep * 0.3 + 0.7))
    else:
        sharp_sinyal = "YOK"
        hareket_gucu = 0.0

    # Veri noktası sayısı güven çarpanı (3+ nokta = tam güven)
    guven_carpani = min(1.0, n / 3.0)
    hareket_gucu  = round(hareket_gucu * guven_carpani, 3)

    return {
        "ev_hareket":   round(ev_degisim * 100,  2),
        "dep_hareket":  round(dep_degisim * 100, 2),
        "sharp_sinyal": sharp_sinyal,
        "hareket_gucu": hareket_gucu,
        "ilk_oran":     False,
        "ilk_ev_oran":  ilk_ev,
        "ilk_dep_oran": ilk_dep,
        "nokta_sayisi": n,        # kaç ölçüm noktası var (debug)
    }


def hareket_ozeti(hareket_db: dict) -> str:
    """
    Tüm hareket verilerinin kısa özeti (debug için).
    """
    if not hareket_db:
        return "Hareket verisi yok"
    satirlar = []
    for mac_key, entry in list(hareket_db.items())[:5]:
        n = len(entry.get("seri", []))
        satirlar.append(f"  {mac_key[:40]:<40} {n} nokta")
    return "\n".join(satirlar)