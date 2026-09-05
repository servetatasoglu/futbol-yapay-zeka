# PAPER TRADING UYGULAMA VE İZLEME PLANI

## Amaç
Bu denetimde kanıtlanan bulgular ışığında, sistemi hiçbir gerçek sermaye riske atmadan canlı piyasada (Forward-Test / Paper Trading) test etmek için operasyonel çerçeveyi kurmak.

---

## 1. CANLI İZLEME VE KAYIT PROTOKOLÜ

Her fikstür için maç başlama saatinden $T-4$ saat (Açılış/Pre-Match) ve $T-15$ dakika (Kapanış/Closing) olmak üzere iki aşamalı zaman damgalı kayıt zorunludur:

```json
{
  "fixture_id": "PL_2026_09_12_ARS_CHE",
  "prediction_timestamp": "2026-09-12T11:00:00Z",
  "closing_timestamp": "2026-09-12T14:45:00Z",
  "home_team": "Arsenal",
  "away_team": "Chelsea",
  "league": "PL",
  "data_quality_score": 95,
  "model_agreement": "4/4",
  "sub_models": {
    "poisson": [0.55, 0.25, 0.20],
    "elo": [0.58, 0.24, 0.18],
    "xgb": [0.56, 0.24, 0.20],
    "lgbm": [0.57, 0.25, 0.18]
  },
  "raw_model_prob": [0.565, 0.245, 0.190],
  "calibrated_model_prob": [0.542, 0.258, 0.200],
  "pinnacle_open_odds": [1.78, 3.80, 4.70],
  "market_implied_prob": [0.534, 0.250, 0.216],
  "edge": 0.008,
  "selection": "H",
  "pinnacle_close_odds": 1.71,
  "clv": 0.0409,
  "market_movement": "SHORTENED",
  "paper_stake": 100.0,
  "match_result": "2-1",
  "settlement": "WON",
  "pnl": 78.0
}
```

---

## 2. PAPER TRADING STRATEJİ KURALLARI (VALİDASYONDAN TÜRETİLEN)

Discovery aşamasında belirlenen kurallara göre aşağıdaki filtreleri geçemeyen hiçbir sinyale paper trading işlemi açılmayacaktır:

1. **Aşırı Edge Yasağı:** $Edge > \%5$ olan maçlar doğrudan elenir (Model körlüğü ve veri eksikliği koruması).
2. **Kuvvetli Model Uzlaşması Şartı:** Model Agreement en az **3/4 veya 4/4** olmalıdır ($2/4$ veya Disagreement doğrudan NO-BET).
3. **Lig Filtresi:** Eredivisie (DED) ve Bundesliga (BL1) maçları paper trading'e dahil edilmez (Volatilite ve yüksek model hatası nedeniyle).
4. **Oran Koridoru:** Açılış oranı **1.25 ile 2.50** arasında olmalıdır.
5. **Piyasa Akışı Doğrulaması (CLV Guard):** Kapanış oranı açılış oranına göre yükselen (Drifted) maçlar "Paper Cancelled" olarak etiketlenir ve istatistiği ayrı tutulur.

---

## 3. CANLIYA GEÇİŞ KAPILARI (EXIT GATES)

Paper trading'den gerçek parayla canlıya geçiş için asgari gereksinimler:
* **Asgari Örneklem:** En az **500 bağımsız canlı maç**.
* **CLV Şartı:** Gerçekleşen ortalama CLV $> +\%2.0$ olmalıdır.
* **CLV Pozitif Oranı:** Bahislerin en az $\%65$'i kapanış oranını yenmelidir ($CLV > 0$).
* **Log Loss Üstünlüğü:** 500 maç sonunda Model Log Loss $\le$ Market Log Loss gerçekleşmelidir.
* **İstatistiksel Anlamlılık:** 95% Bootstrap alt sınırı sıfırın üzerine çıkmalıdır ($CI_{lower} > 0\%$).
