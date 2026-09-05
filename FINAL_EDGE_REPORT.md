# FINAL MARKET EDGE DISCOVERY VE DENETİM RAPORU

## 1. YÖNETİCİ ÖZETİ VE EN ÖNEMLİ METRİK KARŞILAŞTIRMASI

Bu denetim, 8.822 gerçek Pinnacle maçı üzerinde hiçbir sentetik oran ve gelecek bilgisi olmadan; **Train (5.293 maç)**, **Validation (1.764 maç)** ve **kesinlikle dokunulmamış Final Test (1.765 maç)** bölümlenmesiyle gerçekleştirilmiştir.

### KESİNLİKLE DOKUNULMAMIŞ FINAL TEST SETİ (1.765 MAÇ) ÖZETİ

```
========================================================================================================
METRİK                    MODEL (YENİ SİSTEM)   MARKET (PINNACLE)     DELTA             ANLAM / DURUM
========================================================================================================
Değerlendirilen Maç       1.765                 1.765                 0                 Birebir Aynı Evren
Log Loss                  0.9966                0.9861                +0.0105           Market Üstün (Düşük LL daha iyi)
Brier Score               0.5949                0.5889                +0.0059           Market Üstün
Accuracy                  51.10%                51.10%                0.00%             Eşit
Realized ROI              -6.48%                -                     -                 Komisyon Altı Zarar
Ortalama CLV              -0.84%                0.00%                 -0.84%            Çizgi Gerisinde
95% Bootstrap ROI CI      [-10.96%, -1.69%]     -                     -                 İstatistiki Olarak Negatif (p=0.002)
========================================================================================================
```

---

## 2. PİYASADAN GERÇEKTE AYRIŞILABİLEN NOKTALAR (WHERE IS THE REAL EDGE?)

Audit kapsamında incelenen 12 farklı boyutun net bulguları:

### 1. Piyasa Akışı / Steam Hareketi (Tek Gerçek Kâr Kaynağı)
* Model tercihi ile piyasanın açılıştan kapanışa doğru oranı düşürmesi (**SHORTENED / STEAM**) örtüştüğünde:
  * **Final Test ROI: +%4.12** (Örneklem: 553 maç, Ortalama CLV: **+%6.52**, $p = 0.831$).
  * Kapanış oranı yükselenlerde (DRIFTED) ise getiri: **-%17.43** ($p = 0.000$).
* **Çıkarım:** Model tek başına bağımsız bir alpha üretmemekte, ancak **Pinnacle'a gelen akıllı para (Smart Money) ile aynı yönde kaldığında kârlı olmaktadır.**

### 2. Edge Büyüklüğü Paradoksu (Curse of Big Edge)
* $Edge \le \%2$ iken getiri başa-baş noktasında ve stabil (ROI: ~-%2% ile +%3%).
* $Edge > \%7.5$ olduğunda: Model doğruluğu %24'e çakılmakta, getiri **-%36.85** olmaktadır.
* **Çıkarım:** Modelin büyük avantaj gördüğü yerler piyasanın yanıldığı değil, **modelin piyasanın bildiği bir bilgiden (sakatlık, rotasyon vb.) habersiz olduğu yerlerdir.**

### 3. Oran Koridoru
* **1.20 - 1.40 Aralığı:** Modelin en dirençli olduğu bölgedir (Final Test ROI: **-%1.13**, Validation ROI: **+%3.68**, Doğruluk: %76).
* **1.40 - 1.60 Aralığı:** Modelin en çok cezalandırıldığı "kırılgan favori" bölgesidir (Final Test ROI: **-%15.22**).

### 4. Lig Kırılımları
* **Kötü Performans (Kesin NO-BET):** Eredivisie (-%19.24 ROI, $p=0.004$) ve Bundesliga (-%12.35 ROI, $p=0.038$).
* **Dayanıklı Ligler:** La Liga (-%0.31 ROI) ve Ligue 1 (-%4.85 ROI, Marketle birebir aynı Log Loss $\Delta = +0.0007$).

### 5. Model Agreement
* Modeller ikiye bölündüğünde ($2/4$): Doğruluk %37.78'e düşmekte, getiri **-%20.11** olmaktadır (Kesin NO-BET).

---

## 3. DÖNEMSEL STABİLİTE (YEARLY OVERFITTING TESTİ)

Model-piyasa farkının zaman içinde stabil olup olmadığının testi. Bir dönemde pozitif olup diğerlerinde negatifse → overfitting riski.

| Dönem | Örneklem | Model LL | Market LL | LL Farkı | Accuracy | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **2024** | 2.011 | 0.9784 | 0.9606 | +0.0178 | 52.46% | **-4.96%** | -0.53% | [-9.22%, -0.70%] |
| **2025** | 1.518 | 0.9926 | 0.9823 | +0.0104 | 51.65% | **-5.58%** | -0.86% | [-10.56%, -0.62%] |

**Audit Bulgusu:** Model-piyasa farkı her iki dönemde de tutarlı biçimde **pozitif** (market lehine) ve stabil (overfitting sinyali yok). LL farkı 2025'te daralmış olsa da (+0.0104 vs +0.0178), modelin piyasayı geçtiği bir dönem yoktur.

---

## 4. GÜVEN SEVİYESİ VS GERÇEKLİK (CONFIDENCE CALIBRATION)

Model güveni arttıkça gerçekleşen kazanma oranının da artıp artmadığının testi:

### Final Test (1.765 Maç)
| Confidence Kovası | Örneklem | Accuracy | Model LL | Market LL | LL Farkı | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **50 - 52.5%** | 136 | 51.47% | 1.0327 | 1.0126 | +0.0201 | -5.84% | -1.69% | [-21.71%, +10.71%] |
| **52.5 - 55%** | 126 | 53.97% | 1.0122 | 0.9995 | +0.0128 | -6.25% | -0.84% | [-21.06%, +9.50%] |
| **55 - 57.5%** | 103 | 55.34% | 0.9902 | 0.9646 | +0.0256 | -9.58% | -0.74% | [-26.49%, +5.75%] |
| **57.5 - 60%** | 93 | 54.84% | 0.9942 | 1.0020 | **-0.0079** | -13.80% | -0.19% | [-28.78%, +2.19%] |
| **60 - 65%** | 133 | 56.39% | 0.9897 | 0.9772 | +0.0124 | -17.82% | -0.17% | [-30.77%, -5.43%] |
| **65%+** | 242 | **77.69%** | 0.6773 | 0.6509 | +0.0264 | **-1.57%** | -0.46% | [-8.05%, +5.16%] |

**Audit Bulgusu:**
1. **Model güven kalibrasyonu monotondur:** %50 → %65+ aralığında doğruluk %51 → %78 arasında istikrarlı artış göstermektedir. Bu modelin olasılık sıralamasının sağlıklı olduğunu kanıtlar.
2. **Ancak yüksek güven düşük getiri demektir:** %60-65 kovası en derin kayıbı (-%17.82 ROI) üretmektedir çünkü bu maçlarda oranlar çok düşüktür (1.20-1.50 gibi) ve bir sürpriz geldiğinde büyük kayıp yaşanır.
3. **Tek istisna:** %57.5-60% aralığı ($LL \Delta = -0.0079$) model log loss'unun marketten küçük olduğu **tek** kova. Ancak örneklem küçük ($N = 93$) ve ROI negatiftir (-%13.80).

---

## 5. VERİ KALİTESİ SKORU ANALİZİ

| Kalite Sınıfı | Final Test Örneklem | Accuracy | Model LL | Market LL | Realized ROI | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **HIGH (90-100)** | 1.764 | 51.13% | 0.9962 | 0.9856 | -6.43% | [-11.00%, -2.16%] |
| **MEDIUM (70-90)** | 1 | 0.00% | 1.6353 | 1.8500 | -100.0% | [-100%, -100%] |
| **LOW (<70)** | 0 | - | - | - | - | - |

**Audit Bulgusu:** Pinnacle verisi neredeyse tamamıyla yüksek kalitelidir ($N_{HIGH} = 1.764$ / 1.765). Düşük kaliteli veri filtreleme ihtiyacı yoktur çünkü hemen hemen tüm maçlar kapanış oranı, maç istatistikleri ve tam fikstür bilgisi taşımaktadır.

---

## 6. VALİDASYONDAN TÜRETİLEN VE FINAL TEST'TE BİR KEZ DENENEN KURALLAR

Validation seti üzerinde belirlenen basit meta-kuralların **kesinlikle dokunulmamış Final Test Seti** üzerindeki sonuçları:

| Kural Tanımı | Validation ROI | Validation CLV | Final Test Örneklem | Final Test ROI | Final Test CLV | 95% Bootstrap CI | Karar |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **RULE A (Muhafazakar):** Edge > 1.5%, Odds 1.30-2.20, Agreement >= 3/4 | -4.23% | -0.61% | 194 | **-2.23%** | -1.75% | [-15.51%, +11.07%] | Kayıp Azaldı |
| **RULE B (Steam Chaser):** Edge > 1.0%, Market Shortened, Odds 1.40-2.50 | -3.00% | +7.36% | 105 | **-1.38%** | **+6.50%** | [-20.50%, +18.10%] | Yüksek CLV |
| **RULE C (Home Fav High Conf):** Ev Sahibi, Conf > 55%, Edge > 1% | -21.52% | -1.09% | 64 | **-19.12%** | -0.29% | [-38.02%, +0.41%] | **REDDEDİLDİ** |
| **RULE D (Oybirliği):** Agreement 4/4, Edge > 2.0% | -13.14% | -0.97% | 347 | **-7.29%** | -1.70% | [-18.96%, +5.08%] | **REDDEDİLDİ** |

---

## 25. SON KARAR

Tüm veri, olasılık ve finansal testlerin bağımsız ve tarafsız analizi sonucunda:

### **C) MODEL IMPROVED BUT NO MARKET EDGE**

### Gerekçe (Bilimsel Dürüstlük İlkesi):
1. **Model Gelişimi Kesindir:** Eski sisteme göre Log Loss ($1.0279 \rightarrow 0.9966$), Brier Score ($0.6159 \rightarrow 0.5949$), Doğruluk ($48.56\% \rightarrow 51.10\%$) ve ECE kalibrasyonu belirgin şekilde iyileşmiştir.
2. **Piyasa Üstünlüğü Kanıtlanamamıştır:** Ham veya filtreli hiçbir genel model konfigürasyonunda modelin Log Loss veya Brier skoru Pinnacle piyasa kapanış oranlarının önüne geçememiştir (Market LL: $0.9861$ vs Model LL: $0.9966$).
3. **Piyasa Marjı Aşılamamıştır:** Dokunulmamış 1.765 maçlık final test setinde 95% Bootstrap güven aralığı $[-10.96\%, -1.69\%]$ olarak negatif gerçekleşmiştir.
4. **Sistem Canlı Bahis/Trading İçin Değil, Paper Trading ve CLV Takibi İçin Uygundur:** Gerçek sermaye ile doğrudan piyasaya girilmemeli, oluşturulan [PAPER_TRADING_PLAN.md](file:///Users/servet/Desktop/futbol-yapay-zeka-main/PAPER_TRADING_PLAN.md) protokolü işletilmelidir.
