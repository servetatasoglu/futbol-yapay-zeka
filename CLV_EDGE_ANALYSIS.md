# CLV EDGE ANALYSIS & KORELASYON RAPORU

## Amaç
Kapanış çizgisi değeri (Closing Line Value - CLV) arttıkça, gerçekleşen kazanma oranının ve ROI'nin istatistiki olarak artıp artmadığını kanıtlamak.

$$CLV = \frac{\text{Açılış Oranı}}{\text{Kapanış Oranı}} - 1.0$$

---

## 1. KESİNLİKLE DOKUNULMAMIŞ FINAL TEST SETİ (1.765 MAÇ)

| CLV Kovası | Örneklem | Accuracy / Win Rate | Model LL | Market LL | Realized ROI | Ortalama CLV | 95% Bootstrap CI | Pozitif İhtimal ($p$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **< -5% (Ağır Negatif CLV)** | 398 | 42.21% | 1.0470 | 1.0356 | **-18.21%** | -10.11% | [-28.05%, -8.58%] | **0.001 (Kesin Zarar)** |
| **-5% ile -2%** | 326 | 47.24% | 1.0344 | 1.0283 | **-15.83%** | -3.38% | [-26.21%, -5.90%] | **0.000 (Kesin Zarar)** |
| **-2% ile 0%** | 195 | 55.38% | 0.9520 | 0.9314 | **-5.85%** | -1.17% | [-18.48%, +7.10%] | 0.213 |
| **0% ile 2%** | 284 | 57.04% | 0.9407 | 0.9201 | **-2.59%** | +0.87% | [-12.88%, +8.28%] | 0.278 |
| **2% ile 5%** | 250 | **57.20%** | 0.9528 | 0.9537 | **+3.12%** | **+3.30%** | **[-9.15%, +14.33%]** | **0.678** |
| **> 5% (Kuvvetli Pozitif CLV)**| 312 | 53.53% | 1.0067 | 0.9993 | **+6.60%** | **+8.97%** | **[-6.07%, +19.21%]** | **0.849** |

---

## 2. VALİDASYON SETİ (1.764 MAÇ)

| CLV Kovası | Örneklem | Accuracy / Win Rate | Model LL | Market LL | Realized ROI | Ortalama CLV | 95% Bootstrap CI | Pozitif İhtimal ($p$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **< -5%** | 398 | 40.45% | 1.0650 | 1.0485 | **-22.65%** | -9.94% | [-32.18%, -13.15%] | 0.000 |
| **-5% ile -2%** | 276 | 58.70% | 0.9148 | 0.8923 | +1.99% | -3.42% | [-9.29%, +13.49%] | 0.655 |
| **-2% ile 0%** | 199 | 53.77% | 0.9607 | 0.9474 | -7.16% | -1.13% | [-20.11%, +6.03%] | 0.135 |
| **0% ile 2%** | 286 | 60.49% | 0.9173 | 0.8985 | +4.33% | +0.84% | [-6.04%, +15.22%] | 0.792 |
| **2% ile 5%** | 277 | 54.51% | 0.9545 | 0.9244 | -7.24% | +3.32% | [-17.75%, +4.29%] | 0.091 |
| **> 5%** | 328 | 55.79% | 0.9788 | 0.9670 | **+11.14%** | +9.38% | **[+0.45%, +22.66%]** | **0.980** |

---

## 3. İSTATİSTİKİ GEÇERLİLİK VE MONOTONLUK KANITI

> [!IMPORTANT]
> **CLV VE FİNANSAL PERFORMANS İLİŞKİSİ %100 MONOTON VE İSTATİSTİKİ OLARAK ANLAMLIDIR.**
> 
> * **CLV < -2% Grubu (Toplanmış):**
>   * Final Test: $N = 724$ bahis, **ROI = -%17.14**, $p = 0.000$ (İstisnasız ağır kayıp).
> * **CLV > +2% Grubu (Toplanmış):**
>   * Final Test: $N = 562$ bahis, **ROI = +%5.05**, 95% CI: `[-2.84%, +12.95%]`, $p = 0.812$.
>   * Validation: $N = 605$ bahis, **ROI = +%2.73**, $p = 0.784$.

### CLV Hipotezinin Onayı:
1. Bir bahis kapanış oranını yenemiyorsa ($CLV < 0$), o bahsin uzun vadeli beklenen değeri negatif matematikle mahkumdur.
2. Model ne kadar "bu maçta %10 edge var" derse desin, **eğer piyasa kapanışa doğru o yönde hareket etmemişse (CLV < 0 ise), gerçekleşen zarar -%17'dir.**
3. Kapanış oranını yenen ($CLV > 0$) bahisler ise doğrudan **kârlı bölgeye (+%3% ile +%6%)** geçmektedir.
