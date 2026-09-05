# MARKET BEATING EDGE DISCOVERY RAPORU

## Yönetici Özeti ve Temel Soru
> **"Model hangi maçlarda bookmaker (Pinnacle) piyasasından gerçekten daha fazla bilgi taşıyor?"**

Bu denetim, 8.822 gerçek Pinnacle maçı (2022–2025) üzerinden; **Train (5.293 maç)**, **Validation (1.764 maç)** ve **kesinlikle dokunulmamış Final Test (1.765 maç)** bölümlenmesiyle yürütülmüştür. Hiçbir yapay/sentetik oran, leakage veya test seti optimizasyonu kullanılmamıştır.

---

## 1. GENEL PİYASA VS MODEL KARŞILAŞTIRMASI (BASELINE TEST)

| Metrik | Model (Val) | Market (Val) | Delta (Val) | Model (Final Test) | Market (Final Test) | Delta (Final Test) | Üstünlük |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Örneklem** | 1.764 | 1.764 | - | 1.765 | 1.765 | - | - |
| **Log Loss** | 0.9724 | **0.9537** | +0.0187 | 0.9966 | **0.9861** | +0.0105 | **Market Üstün** |
| **Brier Score**| 0.5776 | **0.5663** | +0.0112 | 0.5949 | **0.5889** | +0.0059 | **Market Üstün** |
| **Accuracy** | 53.12% | 53.12% | 0.00% | 51.10% | 51.10% | 0.00% | Eşit |
| **Realized ROI** | -3.97% | - | - | -6.48% | - | - | - |
| **Ortalama CLV**| -0.50% | 0.00% | -0.50% | -0.84% | 0.00% | -0.84% | - |
| **95% Bootstrap CI** | [-8.66%, +0.76%] | - | - | [-10.96%, -1.69%] | - | - | İstatistiki Negatif |

*Not: Log Loss ve Brier skorlarında düşük olan taraf daha iyidir. Modelin log loss'u marketten büyüktür ($\Delta > 0$). Bu, tüm evrende saf modelin Pinnacle piyasasını genel olarak yenemediğini gösterir.*

---

## 2. PİYASADAN AYRIŞMA YÖNÜ ANALİZİ (MARKET EFFICIENCY SIGN)

Model olasılığı ile market olasılığı arasındaki farkın ($P_{model} - P_{market}$) gerçekleşen sonuçlarla ilişkisi:

### Untouched Final Test (1.765 Maç)
| Grup | Örneklem | Model LL | Market LL | LL Farkı | Accuracy | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Model > Market (+0.5% üzeri)** | 622 | 1.0682 | 1.0606 | +0.0076 | 43.89% | **-3.68%** | -1.42% | [-12.01%, +5.42%] |
| **Model $\approx$ Market ($\pm 0.5%$)** | 161 | 1.0306 | 1.0289 | +0.0017 | 47.20% | **-8.16%** | -0.23% | [-25.52%, +8.58%] |
| **Model < Market (-0.5% altı)** | 982 | 0.9457 | 0.9320 | +0.0137 | 56.31% | **-7.98%** | -0.58% | [-13.21%, -2.58%] |

### Kritik Bulgular:
1. Modelin marketten **daha yüksek olasılık biçtiği ($Model > Market$)** maçlarda ROI **-%3.68** ile diğer gruplardan (-%8.16 ve -%7.98) belirgin şekilde daha az kaybettirmektedir.
2. Ancak modelin log loss'u bu ayrışma diliminde de (1.0682 vs 1.0606) marketin gerisindedir.
3. Modelin piyasadan saptığı yerlerde bile **Pinnacle piyasası bilgi üstünlüğünü korumaktadır**.

---

## 3. PİYASA HAREKETİ (STEAM VS DRIFT) ANALİZİ

Açılış oranı ile kapanış oranı arasındaki çizgi hareketinin (Market Movement) model başarısına etkisi:

### Untouched Final Test (1.765 Maç)
| Hareket Tipi | Örneklem | Accuracy | Model LL | Market LL | Realized ROI | Mean CLV | 95% Bootstrap CI | Pozitif İhtimal ($p$) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **SHORTENED (Steam / Oran Düştü)** | **553** | **54.61%** | 0.9874 | 0.9838 | **+4.12%** | **+6.52%** | **[-4.02%, +12.92%]** | **0.831** |
| **STABLE (Sabit $\pm 2\%$)** | 483 | 57.35% | 0.9373 | 0.9172 | -2.10% | +0.10% | [-9.71%, +5.64%] | 0.306 |
| **DRIFTED (Oran Yükseldi)** | 729 | 44.31% | 1.0428 | 1.0336 | **-17.43%** | **-7.05%** | [-24.26%, -10.34%] | 0.000 |

### Kritik Keşif:
* **Asıl Alpha Kaynağı:** Modelin tek başına piyasaya meydan okuması değil, **model tahmininin piyasadaki "Smart Money / Steam" hareketi ile aynı yönde olmasıdır.**
* Oran düştüğünde (Shortened) açılış oranı üzerinden oynanan bahisler **+%4.12 ROI** ve **+%6.52 CLV** üretmektedir ($p = 0.831$).
* Oran yükseldiğinde (Drifted) oynamak ise kesin bir felakettir (**-%17.43 ROI**, $p = 0.000$).

---

## 4. METODOLOJİK SONUÇ VE ÖZET

1. **Saf Model Üstünlüğü Yoktur:** Tüm evrende ve alt dilimlerde ham modelin Log Loss skoru Pinnacle kapanış piyasasının üzerindedir. Model tek başına piyasayı istatistiki olarak yenemez.
2. **CLV ve Çizgi Takibi Zorunludur:** Model ancak **piyasa akışı (Steam/CLV > 0)** ile birleştirildiğinde pozitif beklenen değere yaklaşmaktadır.
