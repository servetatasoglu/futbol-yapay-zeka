# MODEL AGREEMENT ANALYSIS

## Amaç
Dört alt modelin (Poisson, ELO, XGBoost, LightGBM) aynı maç üzerinde uzlaşma (agreement) veya ayrışma (disagreement) seviyesinin tahmin gücüne ve piyasaya karşı üstünlüğe etkisini incelemek.

Uzlaşma Sınıfları:
* **4/4:** Dört modelin dördü de aynı sonucu (örn. Ev Sahibi) en olası görüyor (Oybirliği).
* **3/4:** Üç model aynı, biri farklı düşünüyor (Çoğunluk).
* **2/4:** İkişer model ayrışmış durumda (Kuvvetli İkiye Bölünme).
* **DISAGREEMENT:** Tam ayrışma.

---

## 1. KESİNLİKLE DOKUNULMAMIŞ FINAL TEST SETİ (1.765 MAÇ)

| Uzlaşma Seviyesi | Örneklem | Pay | Accuracy | Model LL | Market LL | LL Farkı | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **4/4 (Oybirliği)** | 1.140 | 64.6% | **54.12%** | 0.9661 | 0.9547 | +0.0114 | **-6.34%** | -0.83% | [-11.22%, -1.13%] |
| **3/4 (Çoğunluk)** | 580 | 32.9% | 46.21% | 1.0471 | 1.0405 | +0.0066 | **-5.70%** | -0.88% | [-13.74%, +3.31%] |
| **2/4 (Ayrışma)** | 45 | 2.5% | 37.78% | 1.1189 | 1.0825 | +0.0364 | **-20.11%** | -0.71% | [-51.11%, +12.16%] |
| **DISAGREEMENT** | 0 | 0.0% | - | - | - | - | - | - | - |

---

## 2. VALİDASYON SETİ (1.764 MAÇ)

| Uzlaşma Seviyesi | Örneklem | Pay | Accuracy | Model LL | Market LL | LL Farkı | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **4/4 (Oybirliği)** | 1.174 | 66.6% | **56.13%** | 0.9373 | 0.9181 | +0.0193 | -4.43% | -0.47% | [-9.71%, +0.53%] |
| **3/4 (Çoğunluk)** | 546 | 31.0% | 46.34% | 1.0469 | 1.0311 | +0.0159 | -4.35% | -0.45% | [-12.93%, +5.07%] |
| **2/4 (Ayrışma)** | 44 | 2.5% | 56.82% | 0.9833 | 0.9450 | +0.0383 | +13.00% | -2.15% | [-15.57%, +43.34%] |

---

## 3. KRİTİK AUDIT BULGULARI

1. **Ayrışma Durumunda (2/4) Çöküş:**
   * Modeller ikiye bölündüğünde ($2/4$), Final Test'te doğruluk %37.78'e düşmekte, Log Loss 1.1189'a fırlamakta ve getiri **-%20.11** olmaktadır.
   * Modeller uzlaşamadığında kesinlikle **NO BET** kuralı uygulanmalıdır.
2. **Oybirliği (4/4) Yanılsaması:**
   * 4/4 oybirliği sağlanan 1.140 maçta doğruluk %54.12 ile yüksektir. Ancak bu maçlar piyasanın da net favori gördüğü maçlar olduğundan oranlar düşüktür; neticede tek başına oybirliği pozitif ROI sağlamaz (-%6.34).
   * Oybirliği, bir **güvenilirlik ve filtreleme şartıdır**, ancak tek başına kâr kaynağı (alpha) değildir.
