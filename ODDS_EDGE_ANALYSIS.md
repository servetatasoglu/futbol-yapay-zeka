# ODDS EDGE ANALYSIS

## Amaç
Modelin açılış oranları bazında hangi oran bölgesinde (Odds Bucket) piyasaya karşı daha dirençli olduğunu, nerede bilgi üstünlüğüne yaklaştığını belirlemek.

---

## 1. KESİNLİKLE DOKUNULMAMIŞ FINAL TEST SETİ (1.765 MAÇ)

| Odds Bölgesi | Örneklem | Accuracy | Brier Model | Log Loss Model | Log Loss Market | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1.20 - 1.40** | 191 | **75.92%** | 0.4018 | 0.7238 | 0.6993 | **-1.13%** | -0.18% | [-8.96%, +6.55%] |
| **1.40 - 1.60** | 220 | 56.82% | 0.5855 | 0.9834 | 0.9706 | **-15.22%** | -0.23% | [-25.09%, -6.00%] |
| **1.60 - 1.80** | 270 | 55.19% | 0.5990 | 1.0031 | 1.0007 | **-6.40%** | -0.95% | [-16.01%, +3.65%] |
| **1.80 - 2.00** | 241 | 49.38% | 0.6303 | 1.0462 | 1.0367 | **-6.50%** | -1.00% | [-18.07%, +5.61%] |
| **2.00 - 2.50** | 523 | 43.59% | 0.6519 | 1.0773 | 1.0704 | **-3.07%** | -0.83% | [-12.46%, +6.96%] |
| **2.50 - 3.00** | 241 | 33.20% | 0.6713 | 1.1056 | 1.0985 | **-12.02%** | -1.42% | [-27.77%, +3.84%] |
| **3.00+** | 23 | 30.43% | 0.6290 | 1.0383 | 1.0184 | **-1.13%** | -2.87% | [-58.61%, +58.70%] |

---

## 2. VALİDASYON SETİ (1.764 MAÇ)

| Odds Bölgesi | Örneklem | Accuracy | Brier Model | Log Loss Model | Log Loss Market | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1.20 - 1.40** | 194 | **79.38%** | 0.3638 | 0.6697 | 0.6438 | **+3.68%** | +0.10% | [-3.92%, +10.90%] |
| **1.40 - 1.60** | 208 | 63.94% | 0.5336 | 0.9113 | 0.8859 | -4.63% | -0.88% | [-14.20%, +5.24%] |
| **1.60 - 1.80** | 260 | 56.92% | 0.5962 | 1.0002 | 0.9761 | -3.41% | -0.60% | [-13.26%, +6.88%] |
| **1.80 - 2.00** | 277 | 45.49% | 0.6385 | 1.0664 | 1.0425 | -10.37% | -0.22% | [-21.41%, +0.76%] |
| **2.00 - 2.50** | 557 | 44.52% | 0.6462 | 1.0662 | 1.0505 | -0.40% | -0.73% | [-9.28%, +8.61%] |
| **2.50 - 3.00** | 240 | 36.67% | 0.6460 | 1.0851 | 1.0694 | -5.73% | -0.44% | [-20.89%, +9.24%] |
| **3.00+** | 28 | 32.14% | 0.6720 | 1.0874 | 1.0560 | -4.64% | -1.50% | [-43.21%, +37.14%] |

---

## 3. KRİTİK ÇIKARIMLAR VE FİLTRELEME PRENSİPLERİ

1. **En Dayanıklı Bölge: 1.20 - 1.40 (Ağır Favoriler)**
   * Final testte ROI: **-%1.13**, Validation'da: **+%3.68**. Ortalama getiri başa-baş noktasına yakındır.
   * Model doğruluğu %76-%79 bandındadır.
2. **Kör Nokta: 1.40 - 1.60 (Kırılgan Favoriler)**
   * Final testte en ağır darbe **-%15.22 ROI** ile 1.40-1.60 aralığında yenmiştir. Model bu takımları aşırı favori görmekte, ancak piyasa marjı ve sürpriz beraberlikler modeli cezalandırmaktadır.
3. **Yüksek Oranlı Bahisler (2.50+):**
   * 2.50-3.00 aralığında hem Validation (-%5.73) hem Final Test (-%12.02) negatif getiri üretmektedir.
   * Güven aralıkları çok geniştir (CI: $\pm 25\%$).
