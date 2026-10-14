# PredictaStock Institutional 5-Session Forecast Charter & Methodology Specification

**Version:** 2.2-Institutional Integrity  
**Market:** National Stock Exchange of India (NSE) / Bombay Stock Exchange (BSE)  
**Target Horizon:** Exactly 5 Future NSE Trading Sessions ($T_0 \to T_5$)  
**Evaluation Standard:** Leakage-Controlled Point-in-Time Forward Verification  
**Statutory Friction Model:** 0.15% Round-Trip Deducted (Brokerage, STT, Exchange Fees, GST, Slippage)

---

## 1. What Is Being Forecast? (Target Specification)

PredictaStock predicts a **three-fold statistical profile** for eligible large-cap Indian equities:

1. **Forward Log Return ($\hat{R}$)**:
   $$\hat{R}_{t \to t+5} = \frac{P_{t+5} - P_t}{P_t} \times 100\%$$
   The expected percentage price appreciation or depreciation from the official verified closing price at Day $t$ ($P_t$) to the official closing price at the fifth subsequent NSE trading session ($P_{t+5}$).

2. **Categorical Directional Regime ($\hat{D}$)**:
   $$\hat{D} \in \{\text{BULLISH}, \text{BEARISH}, \text{NEUTRAL}\}$$
   - **BULLISH**: Projected expected gain $\ge +1.5\%$ with favorable multi-factor momentum.
   - **BEARISH**: Projected expected decline $\le -1.5\%$ or breakdown below 20-DMA with negative momentum.
   - **NEUTRAL**: Mean expected return between $-1.5\%$ and $+1.5\%$ (range consolidation).

3. **Two-Sided Statistical Uncertainty Envelope ($L_5$ to $H_5$)**:
   Rather than claiming false point precision, the model projects a mathematical volatility cone based on the 14-day Average True Range (ATR-14) scaled by the square-root of time ($\sqrt{5/14}$):
   $$L_5 = P_t \times (1 + \hat{R}) - 1.5 \times \text{ATR}_{14} \times \sqrt{\frac{5}{14}}$$
   $$H_5 = P_t \times (1 + \hat{R}) + 1.5 \times \text{ATR}_{14} \times \sqrt{\frac{5}{14}}$$
   This cone defines the statistical boundaries within which price action is anticipated under normal market diffusion.

> **Crucial Disclaimer:** This is an experimental quantitative model designed for research, risk management, and disciplined trade structuring. It is NOT financial advice, a guaranteed profit claim, or an assurance of future returns.

---

## 2. When Is the Forecast Made? (Cutoff & Horizon Timing)

- **Execution Cutoff**: Daily automated screening runs at **16:00 IST** (after the 15:30 IST market close and official NSE Bhavcopy audit).
- **Day 0 Price ($P_0$)**: Strictly the verified closing price recorded at Day $t$ close.
- **Day 1 Definition**: Strictly the **first active trading session following Day 0** ($T+1$) as determined by the official NSE Holiday Calendar.
- **Evaluation Cutoff**: Strictly at **16:00 IST on Day $T+5$** using the final official NSE closing price.
- **Traceability**: Every recommendation batch stores an immutable `run_id`, `rec_date`, `ref_timestamp`, and `eval_end_date`.

---

## 3. Universe Eligibility & Exclusion Criteria

While universal search and charting supports all 2,620+ NSE equities on-demand, the **automated daily 5-day predictive screener** is restricted to a liquid, tradeable universe:

| Criterion | Threshold | Rationalization |
| :--- | :--- | :--- |
| **Index Universe** | Nifty 50 & Nifty 100 Constituents | High institutional liquidity and transparent price discovery. |
| **Minimum History** | $\ge 60$ Consecutive Trading Sessions | Sufficient sample for reliable ATR-14, 20-DMA, and RSI computation. |
| **Minimum Price** | $P_t \ge ₹20$ | Elimination of penny stocks and low-liquidity manipulatory scrips. |
| **Average Daily Turnover** | $\ge ₹5\text{ Cr}$ (20-day rolling) | Ensures institutional order execution without catastrophic slippage. |
| **Regulatory Standing** | Normal Segment (Series `EQ`) | Excludes GSM, ASM, trade-to-trade (Series `BE`/`BZ`), and suspended stocks. |
| **Missing Data Policy** | **Strict Disqualification** | Incomplete data drops model coverage; **never** assigned a default synthetic score. |

---

## 4. Trusted Data Sources & Cutoff Timestamps

Every input into the quantitative engine has an auditable source and timestamp:

1. **Price & Volume Data**: Primary feed from NSE EOD Bhavcopy via Yahoo Finance (`.NS`), audited against exchange trade logs. Timestamp: Day $t$ 16:00 IST.
2. **Benchmark Returns**: Nifty 50 Index (`^NSEI`) and India VIX (`^INDIAVIX`) EOD levels.
3. **Corporate Financials**: Audited quarterly statements (P/E, P/B, ROE, ROCE, Debt/Equity, YoY Growth) from corporate exchange filings. Timestamp: Latest quarterly observation date. Missing metrics lower coverage; never defaulted to hardcoded numbers.
4. **News Sentiment**: Real-time Google News RSS headlines with exact publication timestamps. Disqualified via Veto Rule if severe negative sentiment ($\le -0.4$) is detected.

---

## 5. Description vs. Forecast (Model Architecture)

It is critical to distinguish between **describing past price action** and **forecasting future behavior**:

- **Descriptive Features (Inputs)**:
  - 14-day RSI (oscillator momentum)
  - Distance from 20-day Moving Average ($P_t - \text{DMA}_{20}$)
  - 14-day ATR (volatility measurement)
  - 5-day historical realized volatility ($\sigma_{5\text{d}}$)
  *None of these alone prove a stock will rise.*
- **Predictive Composite Engine (Output)**:
  Features are normalized and combined into an evidence-weighted composite score:
  $$\text{Score} = 0.40 \times \text{Technical} + 0.25 \times \text{Fundamental} + 0.20 \times \text{Sentiment} + 0.15 \times \text{Macro}$$
  Only candidates exceeding an institutional threshold ($\ge 65.0$) are eligible for forward scenario modeling.

---

## 6. How Is the Model Judged? (Zero-Alpha Baselines & Costs)

To prevent spurious claims of "predictive edge," all forward evaluations and backtests are audited against **three naive zero-alpha baselines**:

1. **No-Change Model ($R = 0$)**: Assumes tomorrow's price is today's price (martingale random walk).
2. **Nifty 50 Buy-and-Hold**: Passive market benchmark return over the identical 5-session period.
3. **20-DMA Trend Extrapolation**: Simple mechanical momentum rule (long if price > 20-DMA).

### Statutory Friction Model
Every trade outcome accounts for realistic Indian institutional friction of **0.15% round-trip**:
- Brokerage: 0.03%
- Securities Transaction Tax (STT): 0.10% on delivery
- Exchange Turnover & SEBI Turnover Charges: ~0.0035%
- GST (18% on brokerage & charges): ~0.006%
- Bid-Ask Slippage: 0.01%
- **Total Deducted per Round-Trip**: **0.15%**

### Core Performance Metrics
- **Directional Hit Rate**: % of forecasts where $\text{sgn}(P_{t+5} - P_t) == \text{sgn}(\hat{R})$.
- **Net Alpha vs Nifty 50**: Excess return above benchmark after statutory friction.
- **Profit Factor**: Gross profits divided by gross losses.
- **Max Drawdown**: Peak-to-trough decline across consecutive evaluation cycles.
- **Market Regime Breakdown**: Performance segmented into Bull ($R_{\text{Nifty}} > 0$) vs Bear ($R_{\text{Nifty}} \le 0$) regimes.
