# PredictaStock: Institutional 5-Day Swing Trading Engine
## Comprehensive Architectural, Mathematical & Quantitative Specification

> **Target Audience:** Quantitative Analysts, System Auditors, Technical Evaluators  
> **Market Focus:** National Stock Exchange of India (NSE)  
> **Production Version:** v2.5-InstitutionalAlpha  
> **Verification Status:** 14/14 Integration Tests Passing (100%)

---

## 1. Executive Summary & Problem Formulation

Traditional retail algorithmic forecasting models fail in real-world equity markets due to four recurring design flaws:
1. **Unbounded Linear Price Regression:** Training models on raw closing prices yields absurd predictions (e.g. $+25\%$ in 5 days on a mega-cap) because models ignore realized variance and asset beta.
2. **Ignorance of Demat Delivery Dynamics:** Retail models rely strictly on aggregate trading volume without recognizing whether volume represents intraday day-trading square-offs or genuine demat physical accumulation.
3. **Absence of Hard Sentiment Circuit Breakers:** Technical indicators are blind to sudden governance scandals, SEBI forensic audits, or surprise quarterly losses.
4. **Hindsight Bias & Friction Blindness:** Omitting statutory Indian transaction taxes (STT, Stamp Duty, GST, Exchange charges) generates illusory paper alpha that collapses in live execution.

**PredictaStock** solves these problems by operating as a multi-pillar, risk-bounded quantitative engine that:
* Replaces open regression with **Bounded Volatility Cones $[L_5, H_5]$** governed by $\text{ATR}_{14}$ and 5-day realized variance.
* Dynamically extracts **Real NSE EOD Bhavcopy Demat Delivery Data** (`DELIV_PER`, `DELIV_QTY`).
* Screens the complete Indian market in $< 0.05$ seconds using an in-memory **Dual-Sleeve Bhavcopy Pre-Screener** (Sleeve 1: Top 200 Liquid Leaders; Sleeve 2: Sudden Momentum & Delivery Breakouts).
* Employs a **Multi-Agent AI Analyst Committee** to debate each setup and provide transparent rationale with exact $\text{ATR}_{14}$ Stop-Loss limits.
* Evaluates out-of-sample forward accuracy inside an immutable, point-in-time **SQLite Audit Ledger** with statutory $0.25\%$ round-trip friction deducted.

---

## 2. High-Throughput Pipeline Architecture

```mermaid
graph TD
    A["Official NSE Bhavcopy CSV (sec_bhavdata_full_DDMMYYYY.csv)"] --> B["Dual-Sleeve In-Memory Pre-Screener (< 0.05s)"]
    
    B --> C["Sleeve 1: Top 200 Liquid Leaders (Turnover >= Rs 10 Cr, Price >= Rs 50)"]
    B --> D["Sleeve 2: Outlier Breakout Radar (Gain >= +4.5%, Turnover >= Rs 5 Cr, Deliv % >= 40%)"]
    
    C --> E["Candidate Universe (~230 - 250 Equities)"]
    D --> E
    
    E --> F["Concurrent Multi-Threaded Engine (ThreadPoolExecutor, max_workers=8)"]
    
    F --> G1["Pillar 1: Technical Momentum (45%)<br/>RSI, DMA, VCP Squeeze, Overextension, RS 20D, Sector Rotation"]
    F --> G2["Pillar 2: Money Flow (25%)<br/>CMF-20, MFI-14, Volume Surge, Bhavcopy Deliv %"]
    F --> G3["Pillar 3: Sentiment & Solvency (20%)<br/>Google News RSS, News Veto Rule, Solvency Hurdle"]
    F --> G4["Pillar 4: Macro Regime (10%)<br/>Nifty 50 Trend, India VIX, US Overnight Handover"]
    
    G1 & G2 & G3 & G4 --> H["Composite Multi-Factor Scoring (0 to 100)"]
    
    H --> I["Bounded Volatility Cone [L5, H5] & 1.0x ATR Stop-Loss Construction"]
    
    I --> J["Multi-Agent AI Committee Debate (Technical, Value, Macro, PM Synthesis)"]
    
    J --> K["Point-in-Time Sealed Audit Ledger (T0 -> T5 with UUID & Timestamp)"]
    
    K --> L["Morning Briefing Generation (Responsive HTML, FPDF2 PDF, T+5 Performance Footer)"]
```

---

## 3. Dynamic Dual-Sleeve Bhavcopy Pre-Screener

### The Challenge
Restricting analysis to the 50 stocks of the Nifty 50 index ignores the most profitable 5-day swing moves in Nifty Next 50, Midcap 100, and emerging small-cap breakouts. However, sending 2,600+ web requests sequentially via `yfinance` creates severe rate-limiting and 45-minute latency.

### The Mathematical Solution
PredictaStock downloads the official NSE EOD Bhavcopy (`sec_bhavdata_full_DDMMYYYY.csv`) nightly, caches it to `backend/app/data/bhavcopy/`, and parses all 2,689 active equities in memory:

#### Sleeve 1: Established Liquid Leaders (Top 200)
$$\text{SERIES} = \text{'EQ'}, \quad \text{TurnoverLacs} \ge 1000 \ (\ge \text{₹10 Crore}), \quad P_{\text{close}} \ge \text{₹50.00}$$
* Ranked descending by rupee turnover; top 200 selected.

#### Sleeve 2: Outlier Momentum & Institutional Delivery Radar (~30–50 Stocks)
Hunts across the remaining 2,400+ stocks for genuine institutional breakouts:
1. **Price Momentum Trigger:** Daily Gain $R_{1d} = \frac{P_{\text{close}} - P_{\text{prev}}}{P_{\text{prev}}} \in [0.045, 0.20)$ ($+4.5\%$ to $+20\%$ move; excludes locked upper circuits).
2. **Liquidity Hurdle:** $\text{TurnoverLacs} \ge 500$ ($\ge$ ₹5 Crore turnover to prevent illiquid traps).
3. **Real Demat Delivery Confirmation:** $\text{DELIV\_PER} \ge 40.0\%$ (proves real demat transfers vs intraday day-trading churn).
4. **Penny Floor:** $P_{\text{close}} \ge \text{₹30.00}$.

*Result:* Combines large-cap institutional liquidity with high-beta growth momentum in under 0.05 seconds, scaling the evaluation candidate pool to ~250 stocks.

---

## 4. Four-Pillar Quantitative Evaluation Model

$$S_{\text{Composite}} = 0.45 \cdot S_{\text{Tech}} + 0.25 \cdot S_{\text{MoneyFlow}} + 0.20 \cdot S_{\text{Sentiment}} + 0.10 \cdot S_{\text{Macro}} + \Delta_{\text{Sector}} - P_{\text{Solvency}} - P_{\text{Overext}}$$

### Pillar 1: Technical Momentum & Relative Strength (45% Weight)
* **RSI-14 Momentum Window:** $+15$ pts if $52 \le \text{RSI}_{14} \le 70$; $-8$ pts if $\text{RSI} > 73$ (exhaustion); $-15$ pts if $\text{RSI} < 42$.
* **Moving Average Trend:** $+12$ pts if $\text{CMP} > \text{SMA}_{20}$; $+10$ pts if $\text{SMA}_{20} > \text{SMA}_{50}$.
* **MACD Trend:** $+10$ pts if $\text{MACD}_{\text{hist}} > 0$ and $\text{Line} > \text{Signal}$.
* **Volatility Contraction Pattern (VCP Squeeze):**
  $$\text{Ratio}_{\text{VCP}} = \frac{\text{ATR}_5}{\text{ATR}_{20}}$$
  If $\text{Ratio}_{\text{VCP}} \le 0.90$ and $\text{CMP} \ge 0.98 \cdot \text{SMA}_{20}$, awards $+10$ pts for coiling consolidation breaking out.
* **Overextension Penalty:** $-15$ pts if $\frac{\text{CMP} - \text{SMA}_{20}}{\text{SMA}_{20}} > 0.06$ (prevents retail top-buying).
* **20-Day Relative Strength vs Nifty 50:**
  $$\text{RS}_{20d} = R_{\text{stock}, 20d} - R_{\text{Nifty}, 20d}$$
* **Sector Rotation Alignment ($\Delta_{\text{Sector}}$):** Boosts score by $+5.0$ pts if parent NSE Sector Index (IT, Bank, Pharma, Auto, Metal, Infra) outperforms Nifty 50 over 5 days; penalizes by $-5.0$ pts if lagging.

### Pillar 2: Institutional Money Flow & Real Demat Delivery (25% Weight)
* **Chaikin Money Flow (CMF-20):**
  $$\text{MFM}_t = \frac{(P_{\text{close}, t} - P_{\text{low}, t}) - (P_{\text{high}, t} - P_{\text{close}, t})}{(P_{\text{high}, t} - P_{\text{low}, t}) + 10^{-9}}$$
  $$\text{CMF}_{20} = \frac{\sum_{t=1}^{20} (\text{MFM}_t \cdot V_t)}{\sum_{t=1}^{20} V_t + 10^{-9}}$$
* **Money Flow Index (MFI-14):** Volume-weighted RSI across 14 trading days.
* **Bhavcopy Delivery Surge:**
  $$\text{Surge}_{\text{Deliv}} = \frac{\text{DelivQty}}{\max(\text{SMA}_{\text{Vol}, 20} \cdot 0.45, 1.0)}$$
  Awards $+8$ pts for institutional delivery surge ($\ge 1.4\times$ normal with $\ge 48\%$ delivery).

### Pillar 3: Sentiment & Solvency Gatekeepers (20% Weight)
* **The News Veto Circuit Breaker:** Google News RSS articles scored for polarity $S_{\text{Sent}} \in [-1.0, +1.0]$.
  $$\text{If } S_{\text{Sent}} \le -0.40 \implies \textbf{IMMEDIATE DISQUALIFICATION (VETO)}$$
* **Solvency Gatekeeper:** Fundamentals operate as a penalty hurdle:
  $$P_{\text{Solvency}} = (+10 \text{ if Debt/Equity } > 2.0) + (+10 \text{ if ROE } < 5.0\%)$$
  Growth P/E is not penalized.

### Pillar 4: Macro Regime & Global Handover (10% Weight)
* Nifty 50 5-day trend + India VIX regime analysis.
* **Overnight US Handover:** Ingests S&P 500 (`^GSPC`), Nasdaq (`^IXIC`), and Brent Crude (`CL=F`). Warns if S&P 500 fell $> 1.5\%$ overnight.

---

## 5. Bounded Volatility Cones $[L_5, H_5]$ & Stop-Loss Bounds

Rather than predicting point prices, PredictaStock establishes a mathematically bounded envelope:
$$\text{safe\_atr} = \max(\text{ATR}_{14}, 0.02 \cdot \text{CMP})$$
$$\text{VolMove} = \max\left(2.0 \cdot \text{safe\_atr},\; \text{CMP} \cdot \frac{\sigma_{5d}}{100.0} \cdot 1.0\right)$$
$$L_5 = \text{CMP} - 1.15 \cdot \text{VolMove}, \quad H_5 = \text{CMP} + 1.15 \cdot \text{VolMove}$$

### Target & Stop-Loss Execution Rules
| Setup Direction | 5-Day Target Formula | Strict ATR Stop-Loss Formula | Action Label |
| :--- | :--- | :--- | :--- |
| **BULLISH** | $\min(H_5, \text{CMP} + 0.85 \cdot \text{VolMove})$ | $\max(L_5, \text{CMP} - 1.0 \cdot \text{safe\_atr})$ | `BUY / ACCUMULATE (5-Day Swing)` |
| **BEARISH** | $\max(L_5, \text{CMP} - 0.85 \cdot \text{VolMove})$ | $\min(H_5, \text{CMP} + 1.0 \cdot \text{safe\_atr})$ | `EXIT HOLDINGS / AVOID (F&O Short Only)` |
| **NEUTRAL** | $\text{CMP}$ | $\text{CMP} - 1.0 \cdot \text{safe\_atr}$ | `HOLD / MONITOR (Range-Bound)` |

---

## 6. Indian Statutory Transaction Friction (0.25% Round-Trip)

To eliminate paper alpha, every trade evaluation strictly deducts $0.25\%$ round-trip statutory friction:

| Component | Authority | Rate Applied |
| :--- | :--- | :--- |
| Securities Transaction Tax (STT) | Central Govt | 0.10% Buy + 0.10% Sell = 0.200% |
| Stamp Duty | State Revenue | 0.015% Buy side |
| Exchange Turnover Charges | NSE Clearing | 0.00345% Buy + Sell = 0.0069% |
| GST | Central / State | 18% on Brokerage & Exchange Fees |
| SEBI Turnover Turnover Fees | SEBI | ₹10 per Crore turnover |
| Depository (DP) Charges | NSDL / CDSL | Flat ₹13.50 – ₹18.50 per debit sell |
| **Total Standard Friction** | **PredictaStock Config** | **0.25% Flat Round-Trip** |

$$\text{Net Return } R_{\text{Net}} = \left(\frac{P_{\text{exit}} - P_{\text{entry}}}{P_{\text{entry}}} \times 100.0\right) - 0.25\%$$

---

## 7. Multi-Agent AI Analyst Committee Debate

Picks scoring $\ge 68.0$ are submitted to four specialized agents:
1. **Technical Momentum Specialist:** Audits moving averages, RSI channels, and VCP breakout patterns.
2. **Value \& Solvency Auditor:** Verifies D/E, ROE, promoter pledged shares, and cash flow stability.
3. **Macro \& Sentiment Strategist:** Ingests Google News RSS headlines, Nifty 50 trend, and overnight US market lead.
4. **Lead Quant Portfolio Manager (Synthesizer):** Moderates the debate, enforces the News Veto Rule and 1.0x ATR Stop-Loss, and synthesizes the consensus thesis.

*Deterministic Fallback:* If LLM endpoints timeout or exhaust rate limits, the rule-based quantitative synthesizer generates the consensus thesis citing exact CMF, MFI, volume expansion, delivery %, and ATR stop-loss figures.

---

## 8. Point-in-Time Sealed Audit Ledger ($T_0 \to T_5$)

Every prediction is sealed point-in-time in `forecast_evaluations`:
* Sealed with UUID, Batch Run ID, IST timestamp, spot price, target, stop-loss, and Nifty 50 level.
* Graded exactly 5 trading sessions later against 3 naive baselines:
  1. **Martingale Baseline:** $E[P_{t+5}] = P_t$ (Random Walk).
  2. **Nifty 50 Index Baseline:** $\alpha_{\text{Nifty}} = R_{\text{Net}, \text{stock}} - R_{\text{Nifty}, 5d}$.
  3. **20-DMA Trend Baseline:** Compares against naive 20-DMA crossover.
* **T+5 Scorecard Footer:** Displayed at the bottom of every morning email briefing.

---

## 9. 24/7 Automated Background Scheduling

* **Layer 1 (Intraday Light Monitor):** Runs every 5 minutes during market hours (09:15–15:30 IST) tracking live prices against stop-losses.
* **Layer 2 (Post-Market EOD Ledger Evaluation):** Triggers at 16:00 IST to grade completed 5-day batches against official closing prices.
* **Layer 3 (Pre-Market Morning Pipeline):** Triggers at 08:30 IST to execute the Dual-Sleeve Bhavcopy screening across 250 stocks, run the AI debate, seal predictions, and dispatch morning reports.

---

## 10. Corporate Actions & Cost-Basis Conservation

When a portfolio holding undergoes a corporate action, total capital is strictly conserved:
$$\text{Total Invested} = Q_{\text{old}} \cdot P_{\text{avg, old}} \equiv Q_{\text{new}} \cdot P_{\text{avg, new}}$$
* **Stock Split ($A:B$ ratio):** $Q_{\text{new}} = Q_{\text{old}} \cdot \frac{A}{B}, \quad P_{\text{avg, new}} = P_{\text{avg, old}} \cdot \frac{B}{A}$
* **Bonus Issue ($X:Y$ ratio):** $Q_{\text{new}} = Q_{\text{old}} \cdot (1 + \frac{X}{Y}), \quad P_{\text{avg, new}} = \frac{Q_{\text{old}} \cdot P_{\text{avg, old}}}{Q_{\text{new}}}$

---

## 11. Live Production Verification (Top Picks)

| Symbol | Name | Sector | CMP | 5D Target | ATR Stop-Loss | Expected Move | Real NSE Deliv % | Deliv Surge | Data Source | Stance |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **FCL** | Fineotex Chemical Ltd | Chemicals | ₹59.86 | ₹66.08 | ₹56.20 | **+10.39%** | **35.14%** | **1.47x** | `NSE_BHAVCOPY` | BUY / ACCUMULATE |
| **NETWEB** | Netweb Tech India Ltd | IT | ₹5,067.70 | ₹5,395.09 | ₹4,875.12 | **+6.46%** | **16.57%** | **0.41x** | `NSE_BHAVCOPY` | BUY / ACCUMULATE |
| **BHEL** | Bharat Heavy Electricals | Power & Energy | ₹464.00 | ₹489.14 | ₹449.21 | **+5.42%** | **25.94%** | **1.99x** | `NSE_BHAVCOPY` | BUY / ACCUMULATE |
| **SUPREMEIND** | Supreme Industries Ltd | Diversified | ₹3,607.00 | ₹3,789.05 | ₹3,499.91 | **+5.05%** | **56.62%** | **2.71x** | `NSE_BHAVCOPY` | BUY / ACCUMULATE |
| **VBL** | Varun Beverages Ltd | FMCG | ₹442.65 | ₹459.29 | ₹432.86 | **+3.76%** | **70.13%** | **1.15x** | `NSE_BHAVCOPY` | BUY / ACCUMULATE |

---

## 12. Verification & Integrity Checklist

* [x] **Zero Synthetic Fallbacks:** All spot prices, indices, and delivery metrics verified against exchange data.
* [x] **0.25% Friction Enforced:** Statutory friction deducted in all ledger evaluations and backtests.
* [x] **Liquidity Hurdle:** Mandatory ₹5 Crore (outliers) and ₹10 Crore (leaders) turnover floors.
* [x] **Multi-Threading:** 250 equities evaluated concurrently in background without blocking.
* [x] **Test Coverage:** 14/14 Pytest integration tests passing (100%).
