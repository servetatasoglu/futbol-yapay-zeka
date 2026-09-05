# 📈 Closing Line Value (CLV) & Statistical Reality Audit

## 1. Predictive Validity of CLV (Item 18)

* **Correlation (CLV vs Realized Return):** `0.0626` (Positive correlation).
* **Positive CLV Bets ($N=167$):** Realized ROI = **`-5.69%`**.
* **Negative CLV Bets ($N=249$):** Realized ROI = **`-12.24%`**.
* **Conclusion:** Bets that beat the Pinnacle closing line beat bets that lost to the closing line by **`6.55%`**. This empirically confirms that Closing Line Value is a valid leading indicator of market efficiency.

---

## 2. Bootstrap Return Significance (Item 19)

* **Methodology:** 1,000 bootstrap iterations over realized bet returns on the untouched final test set.
* **Mean ROI:** `-6.17%`
* **95% Confidence Interval:** `[-17.01%, 5.06%]`
* **$p$-value for $H_0: \text{ROI} \le 0$:** `0.124`
* **Scientific Verdict:** The 95% confidence interval spans across zero. Statistically significant positive expectation cannot be claimed at the 95% level.
