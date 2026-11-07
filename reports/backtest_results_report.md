# PredictaStock Institutional Walk-Forward Backtest & Strategy Audit

**Generated:** 2026-11-07 23:02:28 IST  
**Evaluation Standard:** 5-Trading-Session T+1 Open Path-Dependent Execution  
**Sample Universe:** 10 Front-Line Indian Equities (RELIANCE, TCS, INFY, ICICIBANK, HDFCBANK...)  
**Friction Deducted:** 0.3% (0.25% Statutory Delivery Charges + 0.05% Execution Slippage)  
**Historical Window:** 6mo (50% Development / 20% Validation / 30% Untouched Test)  

---

## 1. Out-of-Sample vs Development Comparison (Non-Diluted Denominators)

| Evaluation Set | Active Trades (N) | Hit Rate (%) | Avg Net Return (%) | Median Net (%) | Win/Loss | Profit Factor | Max DD (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Development (In-Sample 50%)** | 1 | 100.0% | +1.55% | +1.55% | 1.0 | 1.55 | 0.0% |
| **Validation (Holdout 20%)** | 2 | 0.0% | -2.51% | -2.51% | 0.0 | 0.0 | 2.95% |
| **Untouched Final Test (30%)** | 1 | 0.0% | -2.19% | -2.19% | 0.0 | 0.0 | 0.0% |

---

## 2. Compounded ₹10,00,000 Portfolio Ledger Simulation (Untouched Test Cohort)

- **Initial Portfolio Capital:** ₹1,000,000.00
- **Final Portfolio Equity:** ₹995,630.73
- **Compounded Total Return:** -0.44%
- **Compounded Max Drawdown:** 0.44%
- **Annualized Sharpe Ratio:** -5.0
- **Active Trades Taken:** 1 (Skipped due to 5-slot cap: 0)

---

## 3. Strict Evidence Gate & 80% Release Check
*(Regime sizes the position. A candidate still has to clear relative strength, technical, money-flow, RSI, MACD, volume, verified delivery, composite, and solvency.)*

| Metric | Strict Dev (50%) | Strict Val (20%) | Strict Test (30%) |
| :--- | :---: | :---: | :---: |
| **Qualified Trades (N)** | 1 | 2 | 1 |
| **Directional Hit Rate** | 100.0% | 0.0% | 0.0% |
| **Avg Net Return (5-Day)** | +1.55% | -2.51% | -2.19% |
| **Profit Factor** | 1.55 | 0.0 | 0.0 |

**Release Verdict:** **PAPER-TRADE ONLY**
*The book stays paper-trade only. It needs at least 100 untouched trades, expectancy of 0.15% or better, profit factor 1.30, and positive Nifty alpha. Current untouched result: N=1, hit rate 0.0%, net return -2.19%, profit factor 0.00, alpha -0.49%.*

---

## 4. Execution Policy & Microstructure Reality
1. **Signal Timing & T+1 Open:** Signal is generated on Day T0 EOD; fill occurs strictly at Day T+1 Open.
2. **Opening Gap Filter:** Entries with Day T+1 Open > 3.5% gap or above target are discarded (0 rejected).
3. **Pessimistic Tie-Breaker:** Dual-breach daily bars assume the stop-loss triggered prior to the target price.
4. **Execution Friction:** Deducts statutory 0.25% Indian delivery charges plus 0.05% bid-ask slippage (0.30% total).
5. **Point-in-Time Disclosure:** Quarterly balance sheets and income statements strictly filtered by quarter_end + 45 days <= as_of_date. News pillar dynamically renormalized when UNAVAILABLE_PIT to eliminate artificial 5-7 point score drag.
