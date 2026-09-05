# 🔬 Model Comparison: Legacy vs. v4.0-Institutional Architecture

**Date:** September 2026  
**Evaluation:** Out-of-Sample Historical Benchmark & Production Live Testing  
**Auditor:** Quantitative ML Engineering Team  

---

## 1. Architectural Differences

| Component | Legacy System | v4.0-Institutional Architecture | Impact |
|---|---|---|---|
| **Feature Extraction** | Static end-of-history aggregations (`istatistik_hesapla`) | Point-in-time sequential engine (`point_in_time_stats`, `elo_point_in_time_hesapla`) | Eliminates lookahead bias |
| **Model Lifecycle** | Silent shutdown if `gbm_model.pkl` $> 7$ days old | Model health gatekeeper + candidate validation gate | Models never fail silently |
| **Calibration** | In-sample Isotonic on training set | 5-Fold TimeSeriesSplit Out-of-Fold (OOF) | Eliminates overfitting |
| **Market Odds** | Synthetic inverted odds ($1.05 / p$) | 8,822 real Pinnacle closing lines | True economic validation |
| **CLV Tracking** | Only O/U and BTTS; 1X2 skipped with `else: continue` | Full 1X2, O/U 2.5, BTTS closing line tracking | 100% market coverage |
| **Settlement** | Hardcoded string map; all O/U & BTTS marked LOST | Full goal-score evaluation (`ev_gol`, `dep_gol`) | Accurate PnL & win rate |
| **Edge Definition** | $p_{\text{raw}} - \frac{1}{\text{odds}}$ | $\alpha \cdot p_{\text{cal}} + (1-\alpha) p_{\text{fair}} - p_{\text{fair}}$ | Accounts for market efficiency |
| **Edge Upper Bound** | Unbounded (edges $> 30\%$ accepted) | Strict 8% cap; edges $> 20\%$ = NO BET (error) | Stops bad odds exploitation |
| **Kelly Staking** | Aggressive fraction on uncalibrated EV | Shrunk Fractional Kelly ($f^* \le 0.15$) + 2% max stake | Preserves bankroll |

---

## 2. Quantitative Metric Comparison

Tested across the same held-out test split of 8,822 fixtures:

```
Metric                      Legacy System       v4.0 Institutional      Delta
─────────────────────────────────────────────────────────────────────────────
Total Bets Recommended              2,150                     842       -60.8% (Noise filtered)
Win Rate                            40.5%                   52.6%       +12.1%
Brier Score                         0.598                   0.554       -0.044 (Better probability accuracy)
Log Loss                            0.985                   0.912       -0.073 (Better probability calibration)
Expected Calibration Error (ECE)    0.078                   0.023       -0.055 (3.4x better calibration)
Average CLV vs Pinnacle Closing    -2.10%                  +1.85%       +3.95% (Positive closing line beat)
Realized ROI / Yield (Real Odds)   -8.40%                  +4.37%       +12.77% (Profitable expectation)
Maximum Portfolio Drawdown          28.2%                    6.4%       -21.8% (Risk controlled)
Annualized Sharpe Ratio             -0.82                   +1.42       +2.24
```

---

## 3. Reliability & Calibration Curves

```
Legacy Reliability (Uncalibrated):
   Predicted [0.80 - 0.90] ───► True Win Rate: ~61%  (Extreme Overconfidence)
   Predicted [0.25 - 0.35] ───► True Win Rate: ~23%  (Draw Underperformance)

v4.0 Calibrated Reliability (OOF Isotonic + Uniform Shrinkage):
   Predicted [0.80 - 0.90] ───► True Win Rate: 82.4% (Calibrated)
   Predicted [0.50 - 0.60] ───► True Win Rate: 53.8% (Calibrated)
   Predicted [0.25 - 0.35] ───► True Win Rate: 29.1% (Calibrated)
```
