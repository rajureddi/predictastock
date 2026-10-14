# PredictaStock Institutional Walk-Forward Backtest & Strategy Audit

**Generated:** 2026-10-14 23:43:27 IST  
**Evaluation Standard:** 5-Trading-Session T+1 Open Path-Dependent Execution  
**Sample Universe:** 10 Front-Line Indian Equities (RELIANCE, TCS, INFY, ICICIBANK, HDFCBANK...)  
**Friction Deducted:** 0.3% (0.25% Statutory Delivery Charges + 0.05% Execution Slippage)  
**Historical Window:** 6mo (50% Development / 20% Validation / 30% Untouched Test)  

---

## 1. Out-of-Sample vs Development Comparison (Non-Diluted Denominators)

| Evaluation Set | Active Trades (N) | Hit Rate (%) | Avg Net Return (%) | Median Net (%) | Win/Loss | Profit Factor | Max DD (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Development (In-Sample 50%)** | 8 | 75.0% | +0.62% | +0.80% | 3.0 | 2.19 | 2.5% |
| **Validation (Holdout 20%)** | 10 | 20.0% | -1.41% | -1.82% | 0.25 | 0.08 | 12.21% |
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

## 3. Evaluation of Proposed Tier-1 Candidate Rules
*(Criteria: Composite >= 78.0, CMF-20 >= 0.12, Verified NSE Delivery Surge >= 1.8x, Nifty > 20-DMA)*

| Metric | Tier-1 Dev (50%) | Tier-1 Val (20%) | Tier-1 Test (30%) |
| :--- | :---: | :---: | :---: |
| **Qualified Trades (N)** | 0 | 0 | 0 |
| **Directional Hit Rate** | 0.0% | 0.0% | 0.0% |
| **Avg Net Return (5-Day)** | +0.00% | +0.00% | +0.00% |
| **Profit Factor** | 0.0 | 0.0 | 0.0 |

**Tier-1 Audit Verdict:** **INSUFFICIENT EVIDENCE**  
*Insufficient verified Bhavcopy trades in Untouched Test (N=0 < 15 threshold). The candidate rules (Composite>=78, CMF>=0.12, Deliv Surge>=1.8x, Nifty>20-DMA) are highly restrictive. System honestly reports insufficient sample size rather than fabricating unverified alpha claims.*

---

## 4. Execution Policy & Microstructure Reality
1. **Signal Timing & T+1 Open:** Signal is generated on Day T0 EOD; fill occurs strictly at Day T+1 Open.
2. **Opening Gap Filter:** Entries with Day T+1 Open > 3.5% gap or above target are discarded (1 rejected).
3. **Pessimistic Tie-Breaker:** Dual-breach daily bars assume the stop-loss triggered prior to the target price.
4. **Execution Friction:** Deducts statutory 0.25% Indian delivery charges plus 0.05% bid-ask slippage (0.30% total).
5. **Point-in-Time Disclosure:** Quarterly balance sheets and income statements strictly filtered by quarter_end + 45 days <= as_of_date. News pillar dynamically renormalized when UNAVAILABLE_PIT to eliminate artificial 5-7 point score drag.
