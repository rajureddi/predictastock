"""
PredictaStock Configuration & System Constants
Complies with Indian Stock Market Rules (NSE/BSE) and Use Case Specification v2
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# Automatically load environment variables from backend/.env and project root .env
load_dotenv(BASE_DIR / "backend" / ".env")
load_dotenv(BASE_DIR / ".env")


# Database
DB_PATH = DATA_DIR / "predictastock.db"

# Timezone & Trading Hours
MARKET_TIMEZONE = "Asia/Kolkata"
MARKET_OPEN_TIME = "09:15"
MARKET_CLOSE_TIME = "15:30"

# Execution Schedule Targets (IST)
SCHEDULE_MAIN_ANALYSIS = "16:30"      # 4:30 PM post-market analysis
SCHEDULE_MORNING_REFRESH = "04:30"    # 4:30 AM pre-market news & global cues
SCHEDULE_REPORT_BUILD = "05:15"       # 5:15 AM HTML report generation
SCHEDULE_PDF_BUILD = "05:25"          # 5:25 AM PDF conversion
SCHEDULE_REPORT_VALIDATE = "05:35"    # 5:35 AM validation & integrity check
SCHEDULE_EMAIL_DEADLINE = "05:45"     # 5:45 AM final email delivery deadline

# Prediction Horizon
PREDICTION_HORIZON_DAYS = 5           # Exact 5 trading sessions

# Indian Equity Statutory Charges (Delivery trades)
STT_RATE_BUY = 0.001                  # 0.10% on purchase value
STT_RATE_SELL = 0.001                 # 0.10% on sale value
STAMP_DUTY_RATE = 0.00015             # 0.015% on buy turnover
EXCHANGE_TURNOVER_FEE = 0.0000345     # ~0.00345% NSE turnover charge
SEBI_CHARGES_RATE = 0.000001          # ₹10 per crore
GST_RATE = 0.18                       # 18% on (Brokerage + Exchange fees + SEBI fees)
DEFAULT_BROKERAGE_PER_ORDER = 20.0    # Flat ₹20 (e.g. Zerodha/AngelOne/Fyers) or 0.03%
ROUNDTRIP_FRICTION_PCT = 0.25         # 0.25% institutional delivery friction (0.20% STT + Stamp Duty + GST/Exchange/DP fees)

# Capital Gains Tax Rates (Indian Income Tax Law)
STCG_TAX_RATE = 0.20                  # 20% on gains held <= 365 days
LTCG_TAX_RATE = 0.125                 # 12.5% on gains held > 365 days (above ₹1.25 Lakh exemption)
LTCG_HOLDING_DAYS_THRESHOLD = 365

# Risk & Quality Thresholds
MAX_RECOMMENDATIONS_PER_DAY = 5       # Curated high-conviction shortlist
SECTOR_CONCENTRATION_ALERT_PCT = 25.0 # Warning if single sector exceeds 25% of portfolio
MAX_PRICE_DISCREPANCY_PCT = 0.5       # Flag if primary vs backup prices differ by > 0.5%
MIN_DAILY_TURNOVER_INR = 50_000_000   # ₹5 Crore minimum daily rupee turnover (filters out operator-driven illiquid scrips)

# Full-market scan universe (NSE + BSE bhavcopy store)
# NSE series: EQ normal, BE/BZ trade-to-trade, SM/ST SME. BSE groups: A, B, T, X, XT, Z, ZP, M/MT/MS (SME).
SCAN_EXCHANGES = tuple(os.getenv("SCAN_EXCHANGES", "NSE,BSE").split(","))
# EQ and BSE A/B only. BE/BZ/T/Z are trade-for-trade or restricted and are not a delivery book.
SCAN_NSE_SERIES = tuple(os.getenv("SCAN_NSE_SERIES", "EQ").split(","))
SCAN_BSE_GROUPS = tuple(os.getenv("SCAN_BSE_GROUPS", "A,B").split(","))
SCAN_MIN_TURNOVER_CR = float(os.getenv("SCAN_MIN_TURNOVER_CR", "5.0"))   # 20-session average daily turnover
SCAN_MIN_PRICE = float(os.getenv("SCAN_MIN_PRICE", "20.0"))
SCAN_MAX_UNIVERSE = int(os.getenv("SCAN_MAX_UNIVERSE", "3000"))
EOD_HISTORY_SESSIONS = int(os.getenv("EOD_HISTORY_SESSIONS", "260"))
# Older sessions the archive backfill pulls when someone runs it. The daily scan stays on EOD_HISTORY_SESSIONS.
HISTORY_BACKFILL_SESSIONS = int(os.getenv("HISTORY_BACKFILL_SESSIONS", "520"))

# Re-Weighted 5-Day Swing Model Weights (Total 1.0)
WEIGHT_TECHNICAL = 0.45               # 45% Technical Momentum & Relative Strength
WEIGHT_MONEY_FLOW = 0.25              # 25% Institutional Money Flow (CMF-20, MFI-14, Volume Surge)
WEIGHT_NEWS_SENTIMENT = 0.20          # 20% News Sentiment & Catalysts (<= -0.40 Veto Rule)
WEIGHT_MACRO_FLOW = 0.10              # 10% Macro Regime (Nifty 50 trend & India VIX)
WEIGHT_FUNDAMENTAL = 0.00             # Solvency Gatekeeper (D/E & ROE penalties; doesn't penalize growth momentum P/E)

# Default App & Deployment Security Settings
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
DEBUG = os.getenv("DEBUG", "true" if ENVIRONMENT == "development" else "false").lower() in ("true", "1")
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))

# Allowed CORS Origins (Configurable via ALLOWED_ORIGINS env var)
ALLOWED_ORIGINS = [
    orig.strip() for orig in os.getenv(
        "ALLOWED_ORIGINS", 
        "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if orig.strip()
]

# JWT Session & Token Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "predictastock_production_hardened_secret_key_v2.5")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "1440")) # 24 Hours
JWT_REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))         # 7 Days

# Proposed Tier-1 Candidate Quality Filter Thresholds
TIER1_MIN_COMPOSITE_SCORE = 78.0
TIER1_MIN_DELIVERY_SURGE = 1.8
TIER1_MIN_CMF = 0.12
TIER1_REQUIRE_NIFTY_ABOVE_20DMA = True

# Selective long-only prediction gate.  These are eligibility conditions, not an
# accuracy promise. Regime is a position-size dial, not a veto: a correction
# cuts size in half instead of deleting every signal.
ENABLE_STRICT_EVIDENCE_GATE = True
STRICT_REGIME_IS_HARD_GATE = False
STRICT_MIN_COMPOSITE_SCORE = 70.0
STRICT_MIN_TECHNICAL_SCORE = 68.0
STRICT_MIN_MONEY_FLOW_SCORE = 60.0
STRICT_MIN_CMF = 0.05
STRICT_MIN_VOLUME_SURGE = 1.10
STRICT_MIN_DELIVERY_PCT = 45.0
STRICT_MIN_DELIVERY_SURGE = 1.00
STRICT_RSI_MIN = 54.0
STRICT_RSI_MAX = 68.0
STRICT_MIN_RELATIVE_STRENGTH = 0.0

# Release gate. A 5-day long book is judged on edge over the universe it trades,
# payoff, and drawdown. An 80% hit rate is not a real-world target.
VALIDATION_MIN_OUT_OF_SAMPLE_TRADES = 100
VALIDATION_MIN_EXCESS_HIT_RATE_PCT = 4.0
VALIDATION_MIN_PROFIT_FACTOR = 1.30
VALIDATION_MIN_EXPECTANCY_PCT = 0.15
VALIDATION_MAX_DRAWDOWN_PCT = 15.0
VALIDATION_TARGET_HIT_RATE_PCT = VALIDATION_MIN_EXCESS_HIT_RATE_PCT  # legacy name, no longer an 80% bar

# Trade construction. Slippage is in percent, scaled by 20-session turnover.
MAX_GAP_CHASE_PCT = 3.5
DATA_ERROR_RETURN_PCT = 40.0
RISK_PER_TRADE_PCT = 0.75
MAX_POSITION_PCT = 20.0
PORTFOLIO_START_CAPITAL = 1_000_000.0
REGIME_SIZE_BULL = 1.0
REGIME_SIZE_CORRECTION = 0.5
REGIME_SIZE_UNKNOWN = 0.5
RANKER_VOL_CAP_ATR_PCT = 4.0
EXCLUDED_SERIES = ("BE", "BZ", "SM", "ST", "T", "Z", "ZP", "M", "MT", "MS", "P", "W")
# From the 2025-12 to 2026-10 research pass: pullback lost the least, breakouts
# lost the most, and 20-day momentum had no rank correlation with the next week.
ENTRY_SETUP_BONUS = {"PULLBACK": 0.5, "BREAKOUT": -1.0, "EXTENDED": -2.0, "OTHER": 0.0}

# Benchmark swing. Research book 1 Dec 2025 through 31 Oct 2026, quiet pullbacks
# with the distribution cell removed and Gate A applied: 39 trades, +0.646% net,
# profit factor 1.66, weekly equity 1.13, max drawdown 7.6%.
BENCHMARK_SWING_HOLD_SESSIONS = 6
BENCHMARK_SWING_TARGET_ATR = 2.0
BENCHMARK_SWING_STOP_ATR = 1.05
BENCHMARK_SWING_MAX_ATR_PCT = 4.0
BENCHMARK_SWING_MAX_SIGNAL_DAY_PCT = 0.50
BENCHMARK_SWING_EXPECTANCY_PCT = 0.646
BENCHMARK_SWING_PROFIT_FACTOR = 1.66
BENCHMARK_SWING_ENDING_EQUITY = 1.13
BENCHMARK_SWING_MAX_DRAWDOWN_PCT = 7.6


# Tapetide MCP / Financial Data Gateway (https://mcp.tapetide.com/mcp)
TAPETIDE_TOKEN = os.getenv("TAPETIDE_TOKEN", "tpt_rt_ca1802c8e79a236347b7a3761514b7141032312bc67470e7878eb1fa")
TAPETIDE_MCP_URL = os.getenv("TAPETIDE_MCP_URL", "https://mcp.tapetide.com/mcp")
TAPETIDE_DAILY_CALL_LIMIT = int(os.getenv("TAPETIDE_DAILY_CALL_LIMIT", "50"))
TAPETIDE_SAFETY_BUFFER = 5  # Reserve 5 calls as safety buffer (stop at 45 calls)




