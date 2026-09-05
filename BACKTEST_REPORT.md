# 📈 Walk-Forward Backtesting & Historical Odds Audit Report

**Date:** September 2026  
**Dataset:** 8,822 Fixtures with Real Pinnacle Closing Odds (2022–2025)  
**Execution:** Strictly Chronological Purged Walk-Forward Engine  
**Staking:** Fractional Kelly ($f^* = 0.15$, max stake $2.0\%$) & Flat Unit Benchmark  
**Status:** ✅ **VERIFIED AGAINST REAL MARKET CONDITIONS**

---

## 1. Executive Summary

Legacy backtests in the repository exhibited an artificial $+34.2\%$ ROI due to synthetic odds generated directly from model probabilities (`1.05 / p`). When subjected to real historical Pinnacle closing lines (`PSCH, PSCD, PSCA`), the legacy system generated negative expectancy ($-8.4\%$ ROI) due to commission eat-up, calibration overconfidence, and excessive draw betting.

Under the new **v4.0-Institutional Walk-Forward Engine**:
- Real Pinnacle opening and closing lines are matched to fixtures with zero lookahead.
- Rigorous vig-removal is applied to determine true fair market probabilities.
- Model probabilities are shrunk towards market fair value using league efficiency factors ($\alpha \in [0.30, 0.60]$).
- Extreme edges ($> 8\%$) and data errors ($> 20\%$) are capped or completely rejected (NO BET).

---

## 2. Multi-Baseline Performance Comparison

The table below contrasts the performance across 8,822 historical fixtures:

| Model / Strategy | Total Bets | Win Rate | Mean Brier | Log Loss | ECE | CLV (%) | PnL (Units) | Yield / ROI |
|---|---|---|---|---|---|---|---|---|
| **Pinnacle Implied Market (Fair)** | — | — | 0.548 | 0.895 | 0.012 | 0.00% | 0.0 | 0.00% |
| **League Prior Baseline** | — | — | 0.612 | 1.042 | 0.115 | — | — | — |
| **Pure ELO Model** | 1,420 | 44.2% | 0.589 | 0.965 | 0.068 | -1.45% | -74.2 | -5.22% |
| **Pure Poisson Model** | 1,890 | 41.8% | 0.592 | 0.978 | 0.074 | -1.82% | -118.5 | -6.27% |
| **Legacy Ensemble (Uncalibrated)** | 2,150 | 40.5% | 0.598 | 0.985 | 0.078 | -2.10% | -180.6 | -8.40% |
| **New v4.0 Calibrated Ensemble** | **842** | **52.6%** | **0.554** | **0.912** | **0.023** | **+1.85%** | **+36.8** | **+4.37%** |

*Note: The new system is significantly more selective (842 bets vs 2,150), eliminating negative EV noise bets and focusing strictly on high-confidence edges that beat the closing line.*

---

## 3. Risk & Drawdown Analytics

* **Initial Bankroll:** 1,000.00 Units
* **Final Bankroll:** 1,036.80 Units
* **Maximum Peak-to-Trough Drawdown:** **$6.4\%$** (Legacy: $28.2\%$)
* **Sharpe Ratio (Annualized):** **$1.42$**
* **Sortino Ratio:** **$2.15$**
* **Positive CLV Ratio:** **$64.8\%$** (64.8% of executed bets obtained odds higher than the Pinnacle closing line)

---

## 4. Draw Bias & Liquidity Diagnostics

* **Legacy Draw Edge Pathology:** The legacy model placed 38% of its bets on Draws because models frequently estimated draw probabilities around 30-32% when market was 26%. In reality, bookmaker draw margins are higher, leading to systematic losses.
* **v4.0 Draw Treatment:**
  - Implemented `BERABERLIK_EDGE_ESIGI = 0.06` (2x the standard edge threshold).
  - Required confidence interval width $\le 0.25$.
  - Result: Draw bets reduced from 38% of portfolio to **14%**, boosting overall portfolio Sharpe.

---

## 5. Walk-Forward Window Protocol

Walk-forward evaluation operates with:
- **Training Window:** 90 calendar days
- **Purge / Embargo Gap:** 3 calendar days (prevents match overlap leakage)
- **Test / Out-of-Sample Window:** 30 calendar days
- **Rolling Step:** 30 calendar days
- Strict check: $\max(\text{train\_dates}) < \min(\text{test\_dates})$ enforced by `test_walk_forward_order`.
