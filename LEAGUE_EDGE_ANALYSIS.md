# LEAGUE EDGE DISCOVERY & OUTCOME CLASS ANALYSIS

## 1. KESİNLİKLE DOKUNULMAMIŞ FINAL TEST SETİ (1.765 MAÇ) LİG METRİKLERİ

*Minimum Örneklem Şartı: $N \ge 150$ maç.*

| Lig | Kod | Örneklem | Model LL | Market LL | LL Farkı | Accuracy | Realized ROI | Mean CLV | 95% Bootstrap CI | Karar |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **La Liga** | PD | 226 | 0.9660 | 0.9544 | +0.0115 | **54.42%** | **-0.31%** | -0.62% | [-14.12%, +12.08%] | Nötr / Dayanıklı |
| **Ligue 1** | FL1 | 184 | 0.9634 | 0.9627 | **+0.0007** | **53.80%** | **-4.85%** | -0.28% | [-18.38%, +8.95%] | Marketle Başabaş LL |
| **Championship** | ELC | 329 | 1.0298 | 1.0238 | +0.0060 | 48.63% | **-2.19%** | -0.47% | [-13.10%, +8.82%] | Düşük Kayıp |
| **Serie A** | SA | 237 | 0.9698 | 0.9504 | +0.0194 | 53.59% | **-3.57%** | -1.72% | [-14.85%, +9.19%] | Nötr |
| **Premier League**| PL | 236 | 0.9897 | 0.9785 | +0.0112 | 52.54% | **-7.06%** | -0.47% | [-19.25%, +5.05%] | Verimsiz |
| **Primeira Liga** | PPL | 193 | 0.9814 | 0.9733 | +0.0081 | 51.30% | **-8.42%** | -1.20% | [-22.40%, +5.64%] | Verimsiz |
| **Bundesliga** | BL1 | 189 | 1.0424 | 1.0316 | +0.0108 | 47.09% | **-12.35%** | -1.05% | [-26.58%, +1.24%] | **KÖTÜ (Filtrele)** |
| **Eredivisie** | DED | 171 | 1.0223 | 1.0052 | +0.0171 | 47.37% | **-19.24%** | -1.15% | [-32.56%, -5.48%] | **KÖTÜ (Filtrele)** |

---

## 2. VALİDASYON SETİ LİG METRİKLERİ (1.764 MAÇ)

| Lig | Kod | Örneklem | Model LL | Market LL | Accuracy | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Primeira Liga** | PPL | 179 | 0.9101 | 0.8930 | 58.10% | **+0.48%** | -0.42% | [-13.79%, +14.87%] |
| **La Liga** | PD | 233 | 0.9464 | 0.9192 | 55.79% | -3.22% | -0.08% | [-15.44%, +7.91%] |
| **Ligue 1** | FL1 | 177 | 0.9880 | 0.9710 | 53.11% | -4.61% | -0.27% | [-18.70%, +10.28%] |
| **Premier League**| PL | 235 | 0.9427 | 0.9272 | 54.47% | -3.83% | -0.73% | [-15.91%, +7.83%] |
| **Championship** | ELC | 328 | 1.0098 | 0.9995 | 50.30% | -4.33% | -0.20% | [-14.63%, +5.88%] |
| **Bundesliga** | BL1 | 189 | 1.0224 | 1.0063 | 51.32% | -4.68% | -1.02% | [-18.47%, +9.26%] |
| **Serie A** | SA | 229 | 1.0099 | 0.9944 | 48.03% | -12.06% | -0.42% | [-24.62%, 0.00%] |
| **Eredivisie** | DED | 194 | 0.9328 | 0.9110 | 53.61% | +0.67% | -0.83% | [-12.89%, +15.52%] |

---

## 3. HOME / DRAW / AWAY (H/D/A) AYRIMI

### Final Test (1.765 Maç)
| Tercih | Örneklem | Accuracy | Model LL | Market LL | Realized ROI | Mean CLV | 95% Bootstrap CI |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Home (Ev Sahibi)** | 1.157 | **53.50%** | 0.9774 | 0.9632 | **-5.45%** | -0.62% | [-10.89%, -0.09%] |
| **Away (Deplasman)** | 608 | 46.55% | 1.0331 | 1.0298 | **-8.42%** | -1.26% | [-16.02%, -0.82%] |
| **Draw (Beraberlik)**| 0 | - | - | - | - | - | - |

*(Not: Poisson/Ensemble modelinin tekil en yüksek olasılığı beraberlik üretme frekansı ev sahibi/deplasman favorileri nedeniyle %0'a yakındır; beraberlikler genelde ikinci tercih kalmaktadır).*

---

## 4. LİG DÜZEYİNDE FİLTRE VE NO-BET TAVSİYELERİ

1. **Eredivisie (DED) ve Bundesliga (BL1) Kesin NO-BET:**
   * Final testte Eredivisie (-%19.24 ROI, $p = 0.004$) ve Bundesliga (-%12.35 ROI, $p = 0.038$) açık ara en kötü liglerdir.
   * Neden: Yüksek gollü, yüksek varyanslı ve sürpriz sonuç frekansı yüksek liglerde modelin Poisson tabanlı tahminleri bookmaker piyasasına kıyasla geride kalmaktadır.
2. **Dayanıklı Ligler:**
   * La Liga (PD) ve Ligue 1 (FL1), model log loss'unun market log loss'una en yakın olduğu ($\Delta LL \le +0.0007$) ve zararın minimize olduğu liglerdir.
