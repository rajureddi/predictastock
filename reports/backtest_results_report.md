# PredictaStock Institutional Walk-Forward Backtest & Strategy Audit

**Generated:** 2026-10-19 23:17:02 IST  
**Evaluation Standard:** 5-Trading-Session T+1 Open Path-Dependent Execution  
**Sample Universe:** 10 Front-Line Indian Equities (RELIANCE, TCS, INFY, ICICIBANK, HDFCBANK...)  
**Friction Deducted:** 0.3% (0.25% Statutory Delivery Charges + 0.05% Execution Slippage)  
**Historical Window:** 6mo (50% Development / 20% Validation / 30% Untouched Test)  

---

## 1. Out-of-Sample vs Development Comparison (Non-Diluted Denominators)

| Evaluation Set | Active Trades (N) | Hit Rate (%) | Avg Net Return (%) | Median Net (%) | Win/Loss | Profit Factor | Max DD (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Development (In-Sample 50%)** | 2 | 100.0% | +0.98% | +0.98% | 2.0 | 1.96 | 0.0% |
| **Validation (Holdout 20%)** | 2 | 50.0% | -1.17% | -1.17% | 1.0 | 0.0 | 2.34% |
| **Untouched Final Test (30%)** | 1 | 0.0% | -2.38% | -2.38% | 0.0 | 0.0 | 0.0% |

---

## 2. Compounded ₹10,00,000 Portfolio Ledger Simulation (Untouched Test Cohort)

- **Initial Portfolio Capital:** ₹1,000,000.00
- **Final Portfolio Equity:** ₹995,242.88
- **Compounded Total Return:** -0.48%
- **Compounded Max Drawdown:** 0.48%
- **Annualized Sharpe Ratio:** -5.0
- **Active Trades Taken:** 1 (Skipped due to 5-slot cap: 0)

---

## 3. Strict Evidence Gate & 80% Release Check
*(Every candidate must pass Nifty regime, relative strength, technical, money-flow, RSI, MACD, volume, verified delivery, composite, and solvency checks.)*

| Metric | Strict Dev (50%) | Strict Val (20%) | Strict Test (30%) |
| :--- | :---: | :---: | :---: |
| **Qualified Trades (N)** | 2 | 2 | 1 |
| **Directional Hit Rate** | 100.0% | 50.0% | 0.0% |
| **Avg Net Return (5-Day)** | +0.98% | -1.17% | -2.38% |
| **Profit Factor** | 1.96 | 0.0 | 0.0 |

**Release Verdict:** **PAPER-TRADE ONLY**
*The strict evidence gate remains paper-trade only. It needs at least 50 untouched trades, 80% hit rate, positive net return, and positive Nifty alpha. Current untouched result: N=1, hit rate 0.0%, net return -2.38%, alpha +1.14%.*

---

## 4. Execution Policy & Microstructure Reality
1. **Signal Timing & T+1 Open:** Signal is generated on Day T0 EOD; fill occurs strictly at Day T+1 Open.
2. **Opening Gap Filter:** Entries with Day T+1 Open > 3.5% gap or above target are discarded (0 rejected).
3. **Pessimistic Tie-Breaker:** Dual-breach daily bars assume the stop-loss triggered prior to the target price.
4. **Execution Friction:** Deducts statutory 0.25% Indian delivery charges plus 0.05% bid-ask slippage (0.30% total).
5. **Point-in-Time Disclosure:** Quarterly balance sheets and income statements strictly filtered by quarter_end + 45 days <= as_of_date. News pillar dynamically renormalized when UNAVAILABLE_PIT to eliminate artificial 5-7 point score drag.
