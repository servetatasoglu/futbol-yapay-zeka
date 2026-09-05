# EDGE BUCKET DEEP ANALYSIS

## Amaç ve Test Protokolü
Modelin market olasılığı üzerine iddia ettiği "Edge" ($P_{model} - P_{market}$) arttıkça, gerçekleşen performansın, kazanma oranının ve ROI'nin gerçekten artıp artmadığını incelemek.

*Kural: Eğer edge arttıkça gerçekleşen performans artmıyorsa, edge tahmincisi güvenilmez ve kalibre edilmemiş kabul edilmelidir.*

---

## 1. VALİDASYON SETİ (1.764 MAÇ)

| Edge Kovası | Örneklem | Accuracy | Brier Model | Log Loss Model | Log Loss Market | ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **0 - 1%** | 120 | 44.17% | 0.6420 | 1.0650 | 1.0551 | -15.44% | +0.36% | [-34.62%, +1.96%] |
| **1 - 2%** | 123 | **53.66%** | 0.5986 | 1.0015 | 0.9949 | **+8.89%** | -0.54% | [-11.16%, +28.85%] |
| **2 - 3%** | 109 | 49.54% | 0.5749 | 0.9669 | 0.9749 | -0.02% | -0.23% | [-19.60%, +19.40%] |
| **3 - 5%** | 166 | 39.16% | 0.6516 | 1.0774 | 1.0674 | -14.20% | -0.91% | [-31.30%, +3.13%] |
| **5 - 7.5%** | 118 | 31.36% | 0.6931 | 1.1314 | 1.1013 | -21.15% | -1.05% | [-41.25%, +0.98%] |
| **7.5 - 10%**| 40 | 30.00% | 0.6791 | 1.1210 | 1.0821 | -21.67% | -2.80% | [-56.07%, +19.15%] |
| **10%+** | 17 | 23.53% | 0.6894 | 1.1349 | 1.0642 | -30.35% | +2.21% | [-83.53%, +34.94%] |

---

## 2. KESİNLİKLE DOKUNULMAMIŞ FINAL TEST SETİ (1.765 MAÇ)

| Edge Kovası | Örneklem | Accuracy | Brier Model | Log Loss Model | Log Loss Market | ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **0 - 1%** | 156 | **50.64%** | 0.6176 | 1.0299 | 1.0302 | **+3.47%** | -0.96% | [-13.05%, +20.13%] |
| **1 - 2%** | 130 | 47.69% | 0.6416 | 1.0665 | 1.0607 | -2.15% | -0.44% | [-20.01%, +17.06%] |
| **2 - 3%** | 133 | 44.36% | 0.6451 | 1.0685 | 1.0677 | -3.90% | -1.80% | [-20.38%, +14.86%] |
| **3 - 5%** | 134 | 44.03% | 0.6382 | 1.0597 | 1.0602 | -2.83% | -2.25% | [-21.17%, +17.28%] |
| **5 - 7.5%** | 103 | 41.75% | 0.6393 | 1.0573 | 1.0477 | -1.62% | -2.02% | [-24.16%, +21.89%] |
| **7.5 - 10%**| 33 | 24.24% | 0.7124 | 1.1606 | 1.0968 | **-36.85%**| -1.04% | [-69.64%, +6.73%] |
| **10%+** | 13 | 23.08% | 0.7224 | 1.1674 | 1.0910 | **-21.23%**| +0.09% | [-100.0%, +72.77%] |

---

## 3. BRUTAL EMPIRICAL AUDIT BULGUSU

> [!CAUTION]
> **EDGE ARTTIKÇA PERFORMANS ARTMIYOR, TAM TERSİNE ÇÖKÜYOR!**
> * Edge %0-2 arasında iken: Accuracy ~%49-%51, ROI ~-%2% ile +%3% civarında stabil.
> * Edge %7.5 üzerine çıktığında: Accuracy %24'e düşüyor, ROI -%36.85'e çakılıyor, Log Loss 1.1606'ya fırlıyor.

### Bu Neden Oluyor? (Kök Neden Analizi)
1. **Model Yanılsaması (Curse of Overconfidence):** Modelin bir maçta markete kıyasla devasa bir avantaj (%7.5+) gördüğü durumlar aslında modelin piyasanın bildiği kritik bir sakatlık, rotasyon veya motivasyon bilgisinden **habersiz olduğu (bilgi eksiği)** durumlardır.
2. **Sahte Value:** Piyasa oranı 3.50 açmışken model "bu takım %45 kazanır (2.22 eder), burada %15 edge var!" diyorsa, neredeyse istisnasız olarak haklı olan piyasadır.
3. **Kural:** **Edge > %5 olan tüm bahisler bir model hatası veya eksik veri belirtisidir ve filtrelenmelidir.**
