# PredictaStock: Institutional 5-Day Swing Trading Engine

> **Production Quantitative Trading Engine for National Stock Exchange of India (NSE) Equities**  
> Features an in-memory Dual-Sleeve Bhavcopy Pre-Screener, 4-Pillar Multi-Factor Scoring, Bounded Volatility Cones $[L_5, H_5]$, Multi-Agent AI Consensus Debate, and a Point-in-Time Sealed Audit Ledger with 0.25% Indian Statutory Friction Deduction.

---

## Key Highlights & Quantitative Edge

1. **Dual-Sleeve NSE Bhavcopy Pre-Screener:**
   - Evaluates 2,689 active equities from official daily exchange Bhavcopy CSV in $< 0.05$ seconds.
   - **Sleeve 1 (Liquid Leaders - Top 200):** Daily turnover $\ge$ ₹10 Crore, CMP $\ge$ ₹50.
   - **Sleeve 2 (Outlier Breakout Radar - Top 50):** Daily gain $+4.5\%$ to $+20\%$, turnover $\ge$ ₹5 Crore, real Demat delivery $\ge 40\%$, CMP $\ge$ ₹30.
2. **4-Pillar Multi-Factor Model:**
   - **45% Technical Momentum & Structure:** RSI-14 momentum window, 20/50/200-DMA alignment, MACD, Volatility Contraction Pattern (VCP Squeeze $\le 0.90$), anti-overextension penalty ($> 6\%$ above 20-DMA), and 20-day Relative Strength vs Nifty 50.
   - **25% Institutional Money Flow:** Chaikin Money Flow (CMF-20), Money Flow Index (MFI-14), and official NSE Demat delivery surge ($\ge 1.4\times$ normal).
   - **20% Sentiment & Solvency Gatekeepers:** Google News RSS polarity scoring with **News Veto Rule** (instant disqualification on $S_{\text{Sent}} \le -0.40$), plus $D/E > 2.0$ and $ROE < 5\%$ solvency hurdles.
   - **10% Macro Regime & Sector Rotation:** Nifty 50 20-DMA trend, India VIX regime categorizations, and top-down sectoral alpha ($\pm 5$ pts).
3. **Bounded Volatility Cones & ATR Stop-Loss:**
   - Replaces unconstrained linear price regression with two-sided Brownian diffusion cones $[L_5, H_5]$.
   - Strict non-negotiable $1.0\times \text{ATR}_{14}$ stop-loss and Indian regulatory compliance (BUY vs EXIT/AVOID).
4. **Multi-Agent AI Analyst Debate:**
   - 7 specialized personas (Technical, Fundamental, Options/Volatility, News, Sentiment, Sector, Risk) synthesizing qualitative trade theses.
   - Deterministic rule-based quantitative fallback guarantees zero morning dispatch failure.
5. **Sealed Point-in-Time Audit Ledger ($T_0 \to T_5$):**
   - Every recommendation is frozen in SQLite WAL with UUID and timestamp.
   - Graded 5 trading sessions later against 3 naive baselines (Martingale, Nifty 50, 20-DMA) after deducting **0.25% statutory round-trip friction** (STT, Stamp Duty, GST, Exchange charges, DP fees).

---

## Directory Layout

```
PredictaStock/
├── backend/
│   ├── app/
│   │   ├── data/                  # Bhavcopy CSV store, calendar, constituents
│   │   ├── routes/                # FastAPI endpoint handlers
│   │   ├── services/              # Indicators, engine, backtest, LLM debate
│   │   ├── config.py              # System constants and friction rates
│   │   ├── database.py            # SQLite WAL connection and schemas
│   │   └── main.py                # FastAPI ASGI application
│   ├── static/                    # Responsive web dashboard
│   ├── tests/                     # Comprehensive integration test suite
│   ├── requirements.txt           # Python backend dependencies
│   ├── run.py                     # Uvicorn entry point script
│   └── .env.example               # Environment variable template
├── frontend/                      # Standalone client assets
├── reports/                       # Quantitative whitepapers (.tex & .md)
├── .gitignore                     # Strict exclusion of secrets and runtimes
└── README.md                      # System documentation
```

---

## Quickstart Guide

### 1. Prerequisites
- Python 3.10+ (tested on Python 3.12 - 3.14)
- Git

### 2. Installation
```bash
git clone https://github.com/rajureddi/predictastock.git
cd predictastock/backend
pip install -r requirements.txt
```

### 3. Environment Setup (Optional)
```bash
cp .env.example .env
```
*Note: The engine operates with 100% functionality out-of-the-box using the built-in deterministic quantitative synthesizer. Adding keys for Groq, Gemini, or OpenAI activates real-time LLM multi-agent debate dialogues.*

### 4. Running the Application
```bash
# From backend directory:
python run.py
```
Open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser to access the live dashboard.

### 5. Running Integration Tests
```bash
python -m pytest tests/test_all_phases.py -v
```

---

## Quantitative Documentation & Whitepapers

Detailed architectural specifications, mathematical formulas, and empirical backtest evaluations ($N = 170$ out-of-sample intervals) are available in the `reports/` directory:
- **Complete LaTeX Whitepaper:** [`reports/PredictaStock_Complete_System_Evaluation_and_Architecture_Report.tex`](reports/PredictaStock_Complete_System_Evaluation_and_Architecture_Report.tex)
- **Complete Markdown Specification:** [`reports/PredictaStock_Complete_System_Evaluation_and_Architecture_Report.md`](reports/PredictaStock_Complete_System_Evaluation_and_Architecture_Report.md)

---

## License
Proprietary & Confidential. All rights reserved.
