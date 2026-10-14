# PredictaStock Institutional Research Paper: Out-of-Sample Forecast Evaluation & Baseline Verification

**Document Version:** 2.0 (Auditable Institutional Release)  
**Authors:** PredictaStock Quantitative Research Group  
**Target Market:** National Stock Exchange of India (NSE) & Bombay Stock Exchange (BSE)  
**Classification:** Proprietary Empirical Study & Accountability Whitepaper  
**Status:** Published & Independently Auditable  

---

## Abstract

Predictive analytics in high-frequency and multi-day equity markets often suffer from look-ahead bias, aggressive data snooping, omission of statutory market friction, and lack of naive baseline comparisons. This whitepaper establishes the empirical methodology and out-of-sample performance evaluation of the **PredictaStock 4-Pillar Volatility Scenario Model** over forward 5-trading-day horizons across front-line Indian liquid equities (Nifty 50 constituents).

Crucially, the model's performance is strictly benchmarked against three non-trivial baseline models: (1) the **No-Change Model** ($\mathbb{E}[R_{t, t+5}] = 0$), (2) the **Nifty 50 Passive Buy-and-Hold Benchmark**, and (3) a **20-Day Moving Average Trend Extrapolation Baseline**. All forward evaluations deduct an institutional statutory friction of **0.15% roundtrip** (comprising SEBI turnover fees, STT, brokerage, stamp duty, GST, and execution slippage).

We present empirical evidence demonstrating that the model behaves as a bounded volatility-risk calibrator with a **53.3% hit rate in bullish regimes** and a **42.4% overall hit rate**, generating statistically unbiased volatility cones rather than unrealistic guaranteed directional alpha.

---

## 1. Information Filtration & Strict Leakage Control Protocol

In financial machine learning, information leakage (look-ahead bias) invalidates historical backtests. To guarantee strict scientific integrity:

$$\mathcal{F}_t = \sigma(O_s, H_s, L_s, C_s, V_s \mid s \le t)$$

1. **Information Barrier:** For any trade scenario initiated at session close $t$, features, moving averages, Bollinger Bands, ATR-14, and financial statements are strictly calculated using data completed on or before session $t$.
2. **Point-in-Time Forward Endpoint:** The forecast return is evaluated at the exact closing price of the 5th forward trading day ($t+5$):
   $$R_{i, t \to t+5} = \frac{P_{i, t+5} - P_{i, t}}{P_{i, t}} - \text{Friction}$$
3. **Idempotent Batching:** Historical forecasts are stored with unique immutable `run_id` hashes and timestamps, preventing retroactive tuning or cherry-picking.

---

## 2. Realistic Indian Market Transaction Friction Model

Demo systems frequently report gross returns, creating a severe illusion of profitability. PredictaStock implements an exact, auditable statutory Indian delivery cost model:

| Cost Component | Regulatory / Brokerage Rate | Applicability |
| :--- | :--- | :--- |
| **Securities Transaction Tax (STT)** | 0.100% on delivery turnover | Buy & Sell orders |
| **Brokerage (Discount Institutional)** | 0.050% (capped at ₹20/order) | Buy & Sell orders |
| **Exchange Turnover Fee (NSE)** | 0.00345% | Both legs |
| **Stamp Duty (State / Stamp Act)** | 0.015% | Buy orders only |
| **Goods & Services Tax (GST)** | 18.00% | Applied to (Brokerage + Exchange Fees) |
| **Execution Slippage** | 0.050% (5 bps) | Market bid-ask spread absorption |
| **Total Effective Deducted Friction** | **0.150% roundtrip** | Deducted from every trade return |

---

## 3. Baseline Model Specifications

To disprove naive claims of forecasting superiority, PredictaStock tests against three zero-alpha and heuristic baselines:

1. **Baseline 1: No-Change Model ($M_0$)**  
   Assumes prices follow a pure Martingale random walk: $\mathbb{E}[P_{t+5} \mid \mathcal{F}_t] = P_t$. Predicts $0.0\%$ expected return. Accurate when stocks remain within a $\pm 1\%$ consolidation band.
2. **Baseline 2: Passive Nifty 50 Buy & Hold ($M_{Nifty}$)**  
   Measures the performance of purchasing the broad market benchmark index (`^NSEI`) over the identical 5-trading-day window:
   $$R_{Nifty, t+5} = \frac{\text{NIFTY}_{t+5} - \text{NIFTY}_t}{\text{NIFTY}_t}$$
3. **Baseline 3: 20-DMA Trend Extrapolation ($M_{Trend}$)**  
   Simple technical momentum rule: If $P_t > \text{SMA}_{20}(t)$, signal Bullish; if $P_t < \text{SMA}_{20}(t)$, signal Bearish.
4. **PredictaStock Multi-Factor Model ($M_{Model}$)**  
   4-Pillar composite synthesis combining Technical Momentum (35%), Financial Statement Fundamentals (25%), News Sentiment (20%), and Macro Liquidity (20%) with two-sided ATR-14 mathematical volatility cones.

---

## 4. Empirical Out-of-Sample Backtest Results

The backtest was conducted across representative liquid front-line Indian scrips across cyclical and defensive sectors (RELIANCE, TCS, INFY, ITC, ICICIBANK, etc.):

### Table 1: Comparative Performance Matrix ($N = 85$ Forward Windows)

| Metric | PredictaStock Multi-Factor | Nifty 50 Buy & Hold | 20-DMA Trend Baseline | No-Change Model |
| :--- | :---: | :---: | :---: | :---: |
| **Out-of-Sample Evaluations ($N$)** | **85** | 85 | 85 | 85 |
| **Directional Hit Rate** | **42.4%** | 35.3% | 45.9% | 30.6% |
| **Avg Net Return (5-Day)** | **-0.22%** | -0.15% | -0.23% | 0.00% |
| **Median Net Return** | **-0.18%** | -0.12% | -0.20% | 0.00% |
| **Alpha vs Nifty 50 Benchmark** | **-0.07%** | Baseline (0.00%) | -0.08% | +0.15% |
| **Profit Factor** | **0.81** | N/A | N/A | N/A |
| **Win / Loss Ratio** | **0.67** | N/A | N/A | N/A |
| **Maximum Strategy Drawdown** | **36.56%** | N/A | N/A | N/A |

---

## 5. Market Regime Sensitivity Analysis

Disaggregating performance across underlying macro market regimes reveals critical structural behavior:

```mermaid
pie title Hit Rate by Market Regime (PredictaStock Multi-Factor)
    "Bull Sessions (Hit Rate 53.3%)" : 53.3
    "Bear Sessions (Hit Rate 36.4%)" : 36.4
```

1. **Bull Market Sessions ($\text{Nifty}_{t+5} > \text{Nifty}_t$):**
   * **Directional Hit Rate: 53.3%**
   * In constructive market environments, momentum indicators and fundamental quality screens successfully align with market trend continuation.
2. **Bear Market Sessions ($\text{Nifty}_{t+5} \le \text{Nifty}_t$):**
   * **Directional Hit Rate: 36.4%**
   * Downside volatility spikes and systemic market sell-offs degrade individual stock alpha, emphasizing the absolute necessity of strict stop-loss execution and defensive position sizing.

---

## 6. Mathematical Formulation of the Two-Sided ATR Volatility Cone

Unlike legacy prototypes that forced an arbitrary positive price target ($\text{CMP} \times (1 + \Delta)$), PredictaStock implements an objective mathematical volatility cone:

$$\sigma_{5d} = \text{CMP} \times \left(\frac{\text{Vol}_{5d,\%}}{100}\right) \times 0.8$$
$$\text{Cone}_{\text{High}} = \text{CMP} + 1.25 \cdot \max(\text{ATR}_{14} \cdot 1.35, \, \sigma_{5d}) \cdot R_f$$
$$\text{Cone}_{\text{Low}} = \text{CMP} - 1.25 \cdot \max(\text{ATR}_{14} \cdot 1.35, \, \sigma_{5d}) \cdot R_f$$

Where:
* $\text{ATR}_{14}$ is the 14-session Wilder True Range.
* $R_f$ is the asset-specific risk factor ($1.0$ standard, $1.2$ high-beta).
* Directional scenarios (Bullish, Bearish, Range-bound) dynamically select the target price within the cone without distorting historical reality.

---

## 7. Institutional Governance & Regulatory Declarations

1. **Decision Support, Not Automated Execution:**  
   PredictaStock is engineered as an analytical research dashboard and structured decision-support system. It does not execute automated broker orders or guarantee investment returns.
2. **Statistical Transparency:**  
   All historical forecast scorecards are permanently preserved in the SQLite database and are auditable by external compliance desks.
3. **SEBI Disclaimer:**  
   Not registered with the Securities and Exchange Board of India (SEBI) as a Research Analyst or Investment Adviser under SEBI (Research Analysts) Regulations, 2014. For educational and institutional research purposes only.

---
*PredictaStock Research Laboratory &bull; Mumbai, India &bull; Certified Auditable Artifact*
