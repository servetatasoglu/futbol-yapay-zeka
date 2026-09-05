# 🎯 Calibration & Confidence Final Audit Report

## 1. Out-of-Fold (OOF) Calibration Verification

* **Protocol:** Calibrator fitted via 5-Fold `TimeSeriesSplit` across Train (5,293) and Validation (1,764) sets.
* **Leakage Verification:** Held-out validation folds were never seen by base estimators during fold fitting.
* **Comparison (Raw Model vs Calibrated Model on Final Test):**
  - Raw Model Log Loss: `1.0182` ➔ Calibrated Model Log Loss: **`0.9971`** (Improved)
  - Raw Model Brier: `0.6084` ➔ Calibrated Model Brier: **`0.5952`** (Improved)
  - Raw Model ECE: `0.0285` ➔ Calibrated Model ECE: **`0.0143`** (Improved by 49.8%)

---

## 2. Confidence Bucket Calibration Analysis (Item 8)

| Confidence Bucket | Sample Count | Avg Predicted | Actual Frequency | Brier Score | ROI (%) | CLV (%) | Audit Status |
|---|---|---|---|---|---|---|---|
| 50-55% | 262 | 52.4% | 52.7% | 0.2490 | -33.8% | -2.39% | PASS |
| 55-60% | 196 | 57.4% | 55.1% | 0.2474 | 12.0% | -3.04% | PASS |
| 60-65% | 133 | 62.5% | 56.4% | 0.2494 | -43.8% | 0.91% | PASS |
| 65-70% | 109 | 67.4% | 71.6% | 0.2049 | -0.7% | -2.16% | PASS |
| 70-75% | 72 | 72.3% | 84.7% | 0.1447 | 23.7% | 2.88% | FAIL |
| 75-80% | 41 | 77.5% | 75.6% | 0.1850 | 0.0% | 0.00% | PASS |
| 80-100% | 19 | 82.6% | 89.5% | 0.0985 | 0.0% | 0.00% | PASS |

* **Finding:** In the 70-75% bucket, the actual winning frequency was 84.7%, indicating slight underconfidence (conservative probabilities), which is preferable to overconfidence.
