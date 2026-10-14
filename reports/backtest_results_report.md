# PredictaStock Institutional Backtest & Evidence Report

**Generated:** 2026-10-13 03:44:50 IST  
**Evaluation Standard:** 5-Trading-Session Endpoint Evaluation (Close-to-Close)  
**Sample Universe:** 10 Front-Line Indian Equities (RELIANCE, TCS, INFY, ICICIBANK, HDFCBANK...)  
**Friction Deducted:** 0.15% (SEBI Statutory Charges + Slippage)  
**Historical Window:** 6mo

---

## 1. Executive Summary & Out-of-Sample Performance

| Metric | PredictaStock Multi-Factor | Nifty 50 Buy & Hold | 20-DMA Trend Baseline | No-Change Baseline |
| :--- | :---: | :---: | :---: | :---: |
| **Sample Size (N)** | **170** | 170 | 170 | 170 |
| **Directional Hit Rate** | **48.8%** | 35.3% | 50.6% | 29.4% |
| **Avg Net Return (5-Day)** | **-0.08%** | -0.15% | -0.17% | 0.00% |
| **Alpha vs Nifty 50** | **+0.07%** | Baseline (0.00%) | -0.02% | +0.15% |
| **Profit Factor** | **0.92** | N/A | N/A | N/A |
| **Win / Loss Ratio** | **0.89** | N/A | N/A | N/A |
| **Maximum Drawdown** | **41.42%** | N/A | N/A | N/A |

---

## 2. Market Regime Performance Breakdown

- **Bull Market Sessions (Nifty > 0):** Hit Rate = **45.0%**
- **Bear Market Sessions (Nifty <= 0):** Hit Rate = **50.9%**

---

## 3. Methodological Transparency & Limitations

1. **Strict Leakage Prevention:** Features at time $T$ utilize strictly completed data bars on or before $T$.
2. **Realistic Frictions:** Unlike demo platforms, all returns reflect round-trip statutory delivery taxes and slippage.
3. **Statistical Integrity Statement:** PredictaStock is designed as a structured decision-support and risk-calibrating terminal. Out-of-sample returns are probabilistic volatility scenarios, not guaranteed trading predictions.
