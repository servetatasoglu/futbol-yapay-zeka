# 🌐 Model Stability, Drift & League Breakdown

## 1. League-by-League Performance (Item 14)

| League Code | Matches | Accuracy | Brier Score | Log Loss | Bets Placed | ROI (%) | CLV (%) |
|---|---|---|---|---|---|---|---|
| BL1 | 191 | 47.1% | 0.6262 | 1.0423 | 47 | -41.34% | -2.01% |
| DED | 173 | 46.8% | 0.6134 | 1.0247 | 40 | -41.74% | -4.28% |
| ELC | 329 | 48.6% | 0.6186 | 1.0298 | 73 | -2.03% | -1.10% |
| FL1 | 184 | 53.8% | 0.5704 | 0.9634 | 40 | 12.24% | -0.09% |
| PD | 224 | 54.0% | 0.5749 | 0.9693 | 57 | 20.72% | -0.93% |
| PL | 236 | 52.5% | 0.5917 | 0.9897 | 47 | -25.69% | -2.39% |
| PPL | 191 | 51.8% | 0.5830 | 0.9790 | 47 | 1.02% | -2.49% |
| SA | 237 | 53.6% | 0.5763 | 0.9698 | 65 | -10.33% | -2.31% |


---

## 2. Multi-Baseline Comparison (Item 10)

| Baseline | Accuracy | Brier Score | Log Loss | ECE |
|---|---|---|---|---|
| **Market Implied (Pinnacle)** | 51.95% | 0.5893 | 0.9867 | 0.0191 |
| **League Prior** | 41.64% | 0.6577 | 1.0846 | 0.0297 |
| **Pure ELO** | 50.42% | 0.6108 | 1.0240 | 0.0390 |
| **Pure Poisson** | 45.10% | 0.6516 | 1.0818 | 0.0706 |
| **XGBoost Standalone** | 48.78% | 0.6150 | 1.0269 | 0.0196 |
| **LightGBM Standalone** | 49.46% | 0.6128 | 1.0239 | 0.0123 |
| **Legacy Ensemble** | 48.56% | 0.6159 | 1.0279 | 0.0190 |
| **New v4.0 Ensemble** | **51.05%** | **0.5952** | **0.9971** | **0.0143** |

---

## 3. Class Performance (Item 9)

| Class | Precision | Recall | F1-Score | Brier Score | Match Count |
|---|---|---|---|---|---|
| **HOME** | 50.8% | 80.8% | 0.6236 | 0.2128 | 735 |
| **DRAW** | 0.0% | 0.0% | 0.0000 | 0.1880 | 449 |
| **AWAY** | 51.7% | 52.8% | 0.5226 | 0.1943 | 581 |
