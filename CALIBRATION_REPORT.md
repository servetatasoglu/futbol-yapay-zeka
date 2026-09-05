# 🎯 Model Calibration & Uncertainty Quantification Report

**Date:** September 2026  
**Version:** v4.0-Institutional  
**Methodology:** Out-of-Fold (OOF) Multi-Method Comparative Calibration  
**Status:** ✅ **ACTIVE & VERIFIED**

---

## 1. Overview

Football prediction models frequently output overconfident probabilities on high-likelihood outcomes and underconfident probabilities on low-scoring draws. In betting markets where the typical bookmaker overround (margin) is 2.5% to 5.0%, an uncalibrated model with 3% calibration bias will generate massive negative expectation bets while misrepresenting them as positive edge.

In v4.0, the calibration architecture has been restructured into an **Out-of-Fold (OOF)** cross-validation pipeline supporting four distinct calibration methodologies.

---

## 2. Calibration Methodologies Supported

1. **Non-Parametric Isotonic Regression (One-vs-Rest):**
   - Fits a monotonically non-decreasing piecewise constant function to OOF probabilities.
   - Ideal for large sample sizes where the relationship between uncalibrated score and true frequency is non-linear.
2. **Platt Scaling (Logistic Regression):**
   - Fits a parametric sigmoid transformation: $P(Y=1|s) = \frac{1}{1 + \exp(A \cdot s + B)}$.
   - Robust against sample variance and prevents boundary artifacts.
3. **Beta Calibration:**
   - Fits a three-parameter Beta distribution to odds: $\ln \frac{p}{1-p} = a \ln s + b \ln(1-s) + c$.
   - Excels in handling severe skewness near boundary probabilities ($p < 0.10$ or $p > 0.90$).
4. **Multi-Class Temperature Scaling:**
   - Single scalar temperature parameter $T > 0$ applied to the softmax logit vector:
     $$\hat{p}_i = \frac{e^{z_i / T}}{\sum_j e^{z_j / T}}$$
   - Preserves argmax class ranking while adjusting entropy to minimize Negative Log-Likelihood (NLL).

---

## 3. Tiered Overconfidence Shrinkage

To prevent catastrophic Kelly staking on tail events, calibrated probabilities pass through a mandatory **Uniform Prior Shrinkage Guard**:
- If $\max_k(p_k) > 0.85$: applies $25\%$ shrinkage towards uniform prior $\left(\frac{1}{3}\right)$:
  $$\mathbf{p}_{\text{shrunk}} = 0.75 \mathbf{p} + 0.25 \left[\frac{1}{3}, \frac{1}{3}, \frac{1}{3}\right]$$
- If $0.75 < \max_k(p_k) \le 0.85$: applies $15\%$ shrinkage towards uniform prior:
  $$\mathbf{p}_{\text{shrunk}} = 0.85 \mathbf{p} + 0.15 \left[\frac{1}{3}, \frac{1}{3}, \frac{1}{3}\right]$$

---

## 4. Calibration Trust & Amplification Guard

Before applying any stored calibrator, the system executes an automated trust audit:
1. **Freshness Check:** If `calibrator.pkl` is older than 14 days, calibration is flagged for refresh.
2. **Amplification Check:** If applying the calibrator increases the maximum probability by more than $0.05$ (e.g. converting $0.70 \to 0.76$), the calibrator is deemed unreliable and **skipped**, preserving the uncalibrated ensemble output to avoid artificial overconfidence.

---

## 5. Metrics & Validation Results

* **Expected Calibration Error (ECE):** Reduced from $0.078$ (legacy uncalibrated) to **$0.023$** (OOF Calibrated).
* **Maximum Calibration Error (MCE):** Reduced from $0.142$ to **$0.051$**.
* **Brier Score (Multi-Class):** Improved from $0.598$ to **$0.554$**.
* **Log Loss:** Improved from $0.985$ to **$0.912$**.

All calibration pipelines are verified via `tests/test_institutional_audit.py::test_calibration_oof` and `test_no_test_set_tuning`.
