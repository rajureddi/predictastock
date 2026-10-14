"""
PredictaStock FastAPI Core Application & REST APIs
Connects quantitative modeling, FIFO portfolio engine, and Bloomberg-style Web Terminal.
Phase 1 Integrity Updates:
- Background scheduler started automatically on application startup.
- Strict HTTP 400 validation responses on portfolio errors (rejects overselling and non-positive values).
- Grounded chart volatility cones with directional alignment.
"""
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Depends, Security, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from pathlib import Path
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import logging

from app.config import REPORTS_DIR, BASE_DIR
from app.database import init_db, get_db_connection
from app.data.nse_calendar import is_trading_day
from app.data.nifty_constituents import NIFTY_UNIVERSE, FULL_NSE_UNIVERSE
from app.models import (
    TransactionCreate, UserRegisterRequest, UserLoginRequest,
    CorporateActionCreate, EmailDispatchRequest
)
from app.auth import (
    register_user, authenticate_user, get_current_user_from_key,
    HTTP_BEARER
)
from app.services.market_data import (
    get_nifty50_live_status, get_latest_quote, is_quote_valid,
    get_market_data_coverage, backfill_historical_bhavcopy_dataset
)
from app.services.prediction_engine import (
    generate_daily_recommendations, get_latest_recommendations,
    reset_daily_recommendations, get_scan_progress
)
from app.services.fundamentals import get_company_fundamentals
from app.services.corporate_actions import record_corporate_action, apply_pending_corporate_actions
from app.services.historical_backtest import run_historical_backtest
from app.services.email_dispatcher import dispatch_morning_report
from app.services.portfolio import (
    record_transaction, compute_portfolio_fifo,
    delete_stock_from_portfolio, delete_transaction
)
from app.services.backtester import evaluate_pending_forecasts, get_forecast_scorecard
from app.services.report_generator import generate_morning_report
from app.services.scheduler import start_scheduler
from app.services.tapetide_service import get_quota_status, get_stock_enrichment, get_fii_dii_summary
from app.services.broker_connectors import get_all_services_status, sync_broker_holdings

logger = logging.getLogger(__name__)

# Initialize database schemas and migrations
init_db()

app = FastAPI(
    title="PredictaStock — Indian Market Terminal & Portfolio Engine",
    description="Automated 5-Day Volatility Scenario Engine & Accountability Portfolio Tracker for NSE/BSE",
    version="2.1.0"
)

# Startup lifecycle: Start automated scheduler
@app.on_event("startup")
def startup_event():
    try:
        start_scheduler()
        logger.info("PredictaStock automated scheduler initialized and active.")
    except Exception as e:
        logger.error(f"Failed to start scheduler on startup: {e}")

# Production-Hardened CORS Configuration
from app.config import ALLOWED_ORIGINS, ENVIRONMENT, DEBUG

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# Mount static frontend and report directories
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


@app.get("/")
def serve_index():
    """Serve the Terminal Web Application index page."""
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "PredictaStock API Engine Running. Navigate to /docs for OpenAPI specs."}


@app.get("/api/status")
def get_system_status() -> Dict[str, Any]:
    """Retrieve market hours status, Nifty 50, India VIX, and system health."""
    today = date.today()
    market_open = is_trading_day(today)
    macro = get_nifty50_live_status()
    
    return {
        "is_trading_day": market_open,
        "market_status": "OPEN" if market_open else "CLOSED (Holiday / Weekend)",
        "current_date": today.isoformat(),
        "nifty50": macro.get("nifty50_price"),
        "nifty50_change_pct": macro.get("nifty50_change_pct"),
        "india_vix": macro.get("india_vix"),
        "vix_change_pct": macro.get("vix_change_pct"),
        "macro_feed_valid": macro.get("is_valid", False),
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    }


@app.get("/api/recommendations/today")
def get_today_recommendations() -> List[Dict[str, Any]]:
    """Retrieve today's 5-day stock recommendations with two-sided ATR volatility cones."""
    recs = get_latest_recommendations(limit=5)
    if not recs:
        recs = generate_daily_recommendations()
    return recs


@app.post("/api/recommendations/scan")
def trigger_screening_run(force_refresh: bool = True) -> Dict[str, Any]:
    """Manually trigger the multi-factor screening run across the entire NSE universe."""
    try:
        new_recs = generate_daily_recommendations(force_refresh=True)
        return {
            "status": "COMPLETED",
            "generated_count": len(new_recs),
            "recommendations": new_recs
        }
    except Exception as e:
        logger.error(f"Error during screening run: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Screening execution error: {str(e)}")


@app.post("/api/recommendations/reset")
def reset_and_rescan_recommendations() -> Dict[str, Any]:
    """Reset today's recommendations and generate a brand-new set of diverse stocks."""
    try:
        new_recs = reset_daily_recommendations()
        return {
            "status": "RESET_COMPLETED",
            "generated_count": len(new_recs),
            "recommendations": new_recs
        }
    except Exception as e:
        logger.error(f"Error resetting recommendations: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Reset execution error: {str(e)}")


@app.get("/api/recommendations/progress")
def get_screening_progress() -> Dict[str, Any]:
    """Retrieve real-time stock screening progress percentage and status."""
    return get_scan_progress()


# ---------------------------------------------------------
# AUTHENTICATION & MULTI-USER PORTFOLIO ENDPOINTS
# ---------------------------------------------------------
@app.post("/api/auth/register")
def register_account(req: UserRegisterRequest) -> Dict[str, Any]:
    """Register a new user account with dedicated isolated portfolio partition."""
    try:
        user_info = register_user(req.username, req.password, req.email)
        return {"status": "SUCCESS", "user": user_info}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error during registration: {e}")
        raise HTTPException(status_code=500, detail="Internal registration failure.")


@app.post("/api/auth/login")
def login_account(req: UserLoginRequest) -> Dict[str, Any]:
    """Authenticate credentials and return API session token and JWT tokens."""
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    return {"status": "SUCCESS", "user": user}


@app.post("/api/auth/refresh")
def refresh_session_token(token: str = Query(..., description="JWT refresh token")) -> Dict[str, Any]:
    """Exchange a valid refresh token for a new access token."""
    import jwt
    from app.config import JWT_SECRET_KEY, JWT_ALGORITHM
    from app.auth import is_token_revoked, create_access_token
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if payload.get("token_type") != "refresh":
            raise HTTPException(status_code=401, detail="Invalid token type for refresh.")
        if is_token_revoked(payload.get("jti")):
            raise HTTPException(status_code=401, detail="Refresh token has been revoked.")
        user_id = payload.get("sub")
        username = payload.get("username")
        new_access = create_access_token(user_id, username)
        return {"status": "SUCCESS", "access_token": new_access}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Refresh token expired. Please re-login.")
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid refresh token: {str(e)}")


@app.post("/api/auth/logout")
def logout_session(
    bearer: Optional[HTTPAuthorizationCredentials] = Security(HTTP_BEARER),
    current_user: Dict[str, Any] = Depends(get_current_user_from_key)
) -> Dict[str, Any]:
    """Revoke active JWT access token to invalidate session."""
    import jwt
    from app.config import JWT_SECRET_KEY, JWT_ALGORITHM
    from app.auth import revoke_token
    from datetime import timezone
    if bearer and bearer.credentials:
        try:
            payload = jwt.decode(bearer.credentials, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            jti = payload.get("jti")
            exp = datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc)
            if jti:
                revoke_token(jti, current_user["id"], exp)
        except Exception:
            pass
    return {"status": "SUCCESS", "message": "Session token successfully invalidated."}


@app.get("/api/auth/me")
def get_current_user_profile(current_user: Dict[str, Any] = Depends(get_current_user_from_key)) -> Dict[str, Any]:
    """Retrieve currently authenticated user profile and partition identity."""
    return {"status": "AUTHENTICATED", "user": current_user}


@app.get("/api/portfolio")
def get_portfolio(current_user: Dict[str, Any] = Depends(get_current_user_from_key)) -> Dict[str, Any]:
    """Retrieve user portfolio computed with First-In-First-Out (FIFO) and Indian taxes."""
    user_id = current_user["id"]
    return compute_portfolio_fifo(user_id=user_id)


@app.post("/api/portfolio/transaction")
def add_portfolio_transaction(
    data: TransactionCreate,
    current_user: Dict[str, Any] = Depends(get_current_user_from_key)
) -> Dict[str, Any]:
    """Record a user investment (buy or sell) in the immutable transaction ledger."""
    try:
        user_id = current_user["id"]
        res = record_transaction(
            symbol=data.symbol,
            transaction_type=data.transaction_type,
            price=data.price,
            quantity=data.quantity,
            transaction_date=data.transaction_date,
            brokerage=data.brokerage,
            recommendation_id=data.recommendation_id,
            notes=data.notes,
            user_id=user_id
        )
        return {"status": "SUCCESS", "transaction": res}
    except ValueError as ve:
        logger.warning(f"Transaction validation rejected: {ve}")
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error recording transaction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error processing transaction.")


@app.delete("/api/portfolio/stock/{symbol}")
def delete_portfolio_stock(
    symbol: str,
    current_user: Dict[str, Any] = Depends(get_current_user_from_key)
) -> Dict[str, Any]:
    """
    Deletes all transactions recorded for a specific stock symbol for the authenticated user,
    completely removing the stock from the user's active portfolio holdings.
    """
    user_id = current_user["id"]
    return delete_stock_from_portfolio(symbol=symbol, user_id=user_id)


@app.delete("/api/portfolio/transaction/{transaction_id}")
def delete_portfolio_transaction_endpoint(
    transaction_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_from_key)
) -> Dict[str, Any]:
    """Deletes a specific individual transaction by its unique ID for the authenticated user."""
    user_id = current_user["id"]
    return delete_transaction(transaction_id=transaction_id, user_id=user_id)


# --------------------------------------------------------------------------
# EXTERNAL INTEGRATIONS: TAPETIDE MCP & UPSTOX DEMAT GATEWAY
# --------------------------------------------------------------------------
@app.get("/api/integrations/status")
def get_integrations_status_endpoint() -> Dict[str, Any]:
    """Returns connectivity and daily quota usage for Tapetide MCP and Upstox Demat Gateway."""
    return get_all_services_status()


@app.post("/api/integrations/broker/sync")
def sync_broker_holdings_endpoint(
    broker: str = Query("upstox", description="Broker identifier: 'upstox'"),
    current_user: Dict[str, Any] = Depends(get_current_user_from_key)
) -> Dict[str, Any]:
    """Synchronizes external broker holdings directly into the user's FIFO transaction ledger."""
    user_id = current_user["id"]
    return sync_broker_holdings(broker_name=broker, user_id=user_id)


@app.get("/api/intelligence/tapetide/{symbol}")
def get_tapetide_enrichment_endpoint(symbol: str) -> Dict[str, Any]:
    """Fetches high-value Tapetide quantitative metrics (Options IV rank, promoter pledge %, FII/DII flow)."""
    return get_stock_enrichment(symbol)


@app.post("/api/integrations/credentials")
def update_credentials_endpoint(
    body: Dict[str, Any],
    current_user: Dict[str, Any] = Depends(get_current_user_from_key)
) -> Dict[str, Any]:
    """Updates API credentials for Upstox or Tapetide and saves them into the runtime environment."""
    from app.services.broker_connectors import update_integration_credentials
    service = body.get("service", "")
    creds = body.get("credentials", {})
    return update_integration_credentials(service, creds)






@app.get("/api/scorecard")
def get_evaluation_scorecard() -> Dict[str, Any]:
    """Retrieve 5-day forecast evaluation scorecard benchmarked against Nifty 50."""
    evaluate_pending_forecasts()
    return get_forecast_scorecard()


@app.post("/api/reports/generate")
def create_report() -> Dict[str, Any]:
    """Generate the official morning HTML and PDF report briefing."""
    return generate_morning_report()


@app.get("/api/quote/{symbol}")
def get_symbol_quote(symbol: str) -> Dict[str, Any]:
    """Get latest market quote and metadata for any scrip."""
    return get_latest_quote(symbol)


@app.get("/api/universe")
def get_universe(full: bool = True) -> List[Dict[str, Any]]:
    """
    Get list of constituents across the Indian equity universe.
    Returns all 2,620+ NSE equities when full=True (default), or top liquid benchmark leaders.
    """
    if full:
        return FULL_NSE_UNIVERSE
    return NIFTY_UNIVERSE


@app.get("/api/search")
def search_stocks(q: str = "") -> List[Dict[str, Any]]:
    """
    Real-time autocomplete and search across all 2,620+ Indian NSE-listed equities
    by symbol, ticker prefix, or company name.
    """
    if not q or not q.strip():
        return FULL_NSE_UNIVERSE[:50]
    query = q.strip().upper()

    exact = []
    prefix = []
    contains_sym = []
    contains_name = []

    for item in FULL_NSE_UNIVERSE:
        sym = item["symbol"]
        name = item["name"].upper()
        if sym == query:
            exact.append(item)
        elif sym.startswith(query):
            prefix.append(item)
        elif query in sym:
            contains_sym.append(item)
        elif query in name:
            contains_name.append(item)

    results = exact + prefix + contains_sym + contains_name
    seen = set()
    unique = []
    for item in results:
        if item["symbol"] not in seen:
            seen.add(item["symbol"])
            unique.append(item)
    return unique[:50]



@app.get("/api/chart/{symbol}")
def get_chart_data(symbol: str, period: str = "3mo") -> Dict[str, Any]:
    """Retrieve historical price chart data and projected 5-day ATR volatility cone."""
    import pandas as pd
    from app.services.market_data import get_stock_history
    from app.services.indicators import compute_all_indicators, compute_mathematical_5d_range
    from app.data.nse_calendar import get_nth_trading_day
    from app.data.nifty_constituents import get_symbol_info

    clean_sym = symbol.upper().replace(".NS", "").strip()
    df = get_stock_history(clean_sym, period=period)
    if df.empty or len(df) < 5:
        raise HTTPException(status_code=404, detail=f"No price history found for {clean_sym}")

    dates = [d.strftime("%Y-%m-%d") if hasattr(d, 'strftime') else str(d)[:10] for d in df.index]
    closes = [round(float(c), 2) for c in df['Close']]
    sma_series = df['Close'].rolling(20).mean()
    sma20 = [round(float(s), 2) if not pd.isna(s) else None for s in sma_series]

    tech = compute_all_indicators(df)
    cmp = tech["cmp"]
    atr = tech["atr_14"]
    vol_5d = tech["volatility_5d_pct"]

    range_data = compute_mathematical_5d_range(
        cmp=cmp, 
        atr=atr, 
        vol_5d_pct=vol_5d, 
        signal=tech["signal"], 
        rsi=tech["rsi_14"]
    )
    target = range_data["expected_target_price"]
    high = range_data["expected_range_high"]
    low = range_data["expected_range_low"]

    today = date.today()
    projected_dates = []
    projected_targets = []
    projected_highs = []
    projected_lows = []

    for i in range(1, 6):
        day_date = get_nth_trading_day(today, i)
        projected_dates.append(day_date.isoformat())
        progress = i / 5.0
        projected_targets.append(round(cmp + (target - cmp) * progress, 2))
        projected_highs.append(round(cmp + (high - cmp) * progress, 2))
        projected_lows.append(round(cmp + (low - cmp) * progress, 2))

    meta = get_symbol_info(clean_sym)

    return {
        "symbol": clean_sym,
        "name": meta.get("name", clean_sym),
        "dates": dates,
        "closes": closes,
        "sma20": sma20,
        "cmp": cmp,
        "atr_14": atr,
        "rsi_14": tech["rsi_14"],
        "support": tech["support"],
        "resistance": tech["resistance"],
        "expected_target_price": target,
        "expected_range_low": low,
        "expected_range_high": high,
        "expected_appreciation_pct": range_data["expected_appreciation_pct"],
        "direction": range_data.get("direction", "NEUTRAL"),
        "projected_dates": projected_dates,
        "projected_targets": projected_targets,
        "projected_highs": projected_highs,
        "projected_lows": projected_lows
    }


@app.get("/api/debate/{symbol}")
def get_stock_analyst_debate(symbol: str) -> Dict[str, Any]:
    """Run AI Analyst Multi-Agent Consensus and Bull vs Bear debate synthesis for a scrip."""
    from app.services.prediction_engine import score_single_stock
    from app.services.llm_agent import run_multi_agent_analyst_team

    clean_sym = symbol.upper().replace(".NS", "").strip()
    try:
        stock_analysis = score_single_stock(clean_sym)
        if not stock_analysis:
            raise HTTPException(status_code=404, detail=f"Stock {clean_sym} analysis unavailable or vetoed.")

        debate_result = run_multi_agent_analyst_team(stock_analysis)
        return {
            "symbol": clean_sym,
            "name": stock_analysis["name"],
            "reference_price": stock_analysis["reference_price"],
            "expected_target_price": stock_analysis["expected_target_price"],
            "expected_range_low": stock_analysis["expected_range_low"],
            "expected_range_high": stock_analysis["expected_range_high"],
            "expected_appreciation_pct": stock_analysis["expected_appreciation_pct"],
            "direction": stock_analysis.get("direction", "NEUTRAL"),
            "composite_score": stock_analysis["composite_score"],
            "analysts": debate_result["analysts"],
            "debate": debate_result["debate"],
            "llm_engine": debate_result.get("llm_engine", "Quantitative Synthesizer")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating debate for {clean_sym}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Debate failed: {str(e)}")


@app.get("/api/intelligence/{symbol}")
def get_stock_intelligence_endpoint(symbol: str) -> Dict[str, Any]:
    """Retrieve live internet hot news, price-deciding factors, and price-volume liquidity flow."""
    from app.services.stock_intelligence import get_stock_deep_intelligence
    clean_sym = symbol.upper().replace(".NS", "").strip()
    try:
        return get_stock_deep_intelligence(clean_sym)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stock intelligence for {clean_sym}: {str(e)}")


# ---------------------------------------------------------
# PHASE 2: VERIFIED FUNDAMENTALS & CORPORATE ACTIONS
# ---------------------------------------------------------
@app.get("/api/fundamentals/{symbol}")
def get_fundamentals_endpoint(symbol: str) -> Dict[str, Any]:
    """Retrieve verified financial statement fundamental metrics (P/E, ROE, ROCE, D/E, Revenue Growth)."""
    clean_sym = symbol.upper().replace(".NS", "").strip()
    funds = get_company_fundamentals(clean_sym)
    if not funds:
        raise HTTPException(status_code=404, detail=f"Fundamentals unavailable for {clean_sym}")
    return funds


@app.get("/api/corporate-actions")
def list_corporate_actions() -> List[Dict[str, Any]]:
    """Retrieve audit history of splits, bonus issues, and dividends."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM corporate_actions ORDER BY ex_date DESC, created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.post("/api/corporate-actions")
def record_corporate_action_endpoint(action: CorporateActionCreate) -> Dict[str, Any]:
    """Record an official corporate action (SPLIT, BONUS, DIVIDEND) in the database."""
    try:
        res = record_corporate_action(
            symbol=action.symbol,
            action_type=action.action_type,
            ex_date=action.ex_date,
            ratio=action.ratio or "1:1",
            adjustment_factor=action.adjustment_factor or 1.0,
            dividend_amount=action.dividend_amount or 0.0,
            record_date=action.record_date
        )
        return {"status": "SUCCESS", "corporate_action": res}
    except Exception as e:
        logger.error(f"Error recording corporate action: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/corporate-actions/apply")
def apply_corporate_actions_endpoint() -> Dict[str, Any]:
    """Execute pending corporate actions with conservation of cost basis."""
    try:
        count = apply_pending_corporate_actions()
        return {"status": "SUCCESS", "applied_count": count}
    except Exception as e:
        logger.error(f"Error applying corporate actions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------
# PHASE 3: POINT-IN-TIME HISTORICAL BACKTESTING
# ---------------------------------------------------------
@app.get("/api/backtest/latest")
def get_latest_backtest() -> Dict[str, Any]:
    """Retrieve latest scorecard, parsed backtest data, and markdown report."""
    import json
    report_file = REPORTS_DIR / "backtest_results_report.md"
    json_file = REPORTS_DIR / "backtest_results.json"
    scorecard = get_forecast_scorecard()
    report_content = None
    backtest_data = None

    if report_file.exists():
        try:
            with open(report_file, "r", encoding="utf-8") as f:
                report_content = f.read()
        except Exception as e:
            logger.warning(f"Failed to read markdown report: {e}")

    if json_file.exists():
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                backtest_data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read backtest_results.json: {e}")

    return {
        "scorecard": scorecard,
        "backtest_data": backtest_data,
        "markdown_report_path": str(report_file) if report_file.exists() else None,
        "markdown_content": report_content
    }


@app.post("/api/backtest/run")
def run_backtest_endpoint(
    lookback: str = Query("1y", pattern="^(3mo|6mo|1y|2y)$"),
    friction: float = Query(0.15, ge=0.0, le=2.0)
) -> Dict[str, Any]:
    """Trigger a leakage-controlled historical backtesting simulation with realistic friction."""
    try:
        return run_historical_backtest(lookback_period=lookback, roundtrip_friction_pct=friction)
    except Exception as e:
        logger.error(f"Backtest execution error: {e}")
        raise HTTPException(status_code=500, detail=f"Backtest execution failed: {str(e)}")


# ---------------------------------------------------------
# HISTORICAL MARKET DATASET & PROSPECTIVE PAPER TRADING
# ---------------------------------------------------------
@app.get("/api/market-data/coverage")
def get_market_data_coverage_endpoint() -> Dict[str, Any]:
    """Retrieve Point-in-Time Historical Market Data coverage, verified Bhavcopy status, and session counts."""
    try:
        return get_market_data_coverage()
    except Exception as e:
        logger.error(f"Market data coverage error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/market-data/backfill")
def backfill_bhavcopy_endpoint(
    trading_days: int = Query(90, ge=10, le=250)
) -> Dict[str, Any]:
    """Trigger backfill of official NSE Bhavcopies and OHLCV bars into historical_market_bars."""
    try:
        summary = backfill_historical_bhavcopy_dataset(trading_days=trading_days)
        return {"status": "SUCCESS", "summary": summary}
    except Exception as e:
        logger.error(f"Bhavcopy backfill error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/paper-trading/status")
def get_paper_trading_status_endpoint(cohort_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve forward paper-trading cohort metrics, cash balance, and compounded portfolio equity."""
    try:
        from app.services.paper_trader import get_paper_trading_summary
        return get_paper_trading_summary(cohort_id=cohort_id or "COHORT-2026-v2.3")
    except Exception as e:
        logger.error(f"Paper trading status error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/paper-trading/scorecard")
def get_paper_trading_scorecard_endpoint(cohort_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieve line-item audit scorecard for prospective paper recommendations."""
    try:
        from app.services.paper_trader import get_paper_trading_scorecard
        return get_paper_trading_scorecard(cohort_id=cohort_id or "COHORT-2026-v2.3")
    except Exception as e:
        logger.error(f"Paper trading scorecard error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/paper-trading/cycle")
def run_paper_trading_cycle_endpoint(cohort_id: Optional[str] = None) -> Dict[str, Any]:
    """Execute forward paper-trading cycle (fill T+1 opens with gap/circuit filters, evaluate path-dependent exits)."""
    try:
        from app.services.paper_trader import process_paper_trading_cycle
        return process_paper_trading_cycle(cohort_id=cohort_id or "COHORT-2026-v2.3")
    except Exception as e:
        logger.error(f"Paper trading cycle error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



# ---------------------------------------------------------
# PHASE 4: SYSTEM HEALTH & OPERATIONAL OBSERVABILITY
# ---------------------------------------------------------
@app.get("/api/health")
def get_health_status() -> Dict[str, Any]:
    """
    Distinguishes System Health (DB, process), Data Health (macro feed, quotes),
    and Forecast Health (hit rate, pending vs completed).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT count(*) as cnt FROM recommendations")
    rec_cnt = cursor.fetchone()["cnt"]
    cursor.execute("SELECT count(*) as cnt FROM portfolio_transactions")
    tx_cnt = cursor.fetchone()["cnt"]
    cursor.execute("SELECT count(*) as cnt FROM users")
    user_cnt = cursor.fetchone()["cnt"]
    cursor.execute("SELECT count(*) as cnt FROM price_observations")
    obs_cnt = cursor.fetchone()["cnt"]
    cursor.execute("SELECT symbol, observation_timestamp, primary_price FROM price_observations ORDER BY observation_timestamp DESC LIMIT 1")
    last_obs = cursor.fetchone()
    conn.close()

    macro = get_nifty50_live_status()
    scorecard = get_forecast_scorecard()

    return {
        "status": "HEALTHY",
        "timestamp": datetime.now().isoformat(),
        "system_health": {
            "database": "CONNECTED",
            "tables_intact": True,
            "total_recommendations": rec_cnt,
            "total_transactions": tx_cnt,
            "total_users": user_cnt,
            "total_price_observations": obs_cnt
        },
        "data_health": {
            "nifty50_live": macro.get("is_valid", False),
            "nifty50_price": macro.get("nifty50_price"),
            "india_vix": macro.get("india_vix"),
            "last_recorded_quote": dict(last_obs) if last_obs else None,
            "quote_engine_mode": "Strict Verification (Zero Synthetic Fallbacks)"
        },
        "forecast_health": {
            "completed_evaluations": scorecard.get("total_completed_forecasts", 0),
            "directional_accuracy_pct": scorecard.get("directional_accuracy_pct", 0.0),
            "avg_forecast_error_pct": scorecard.get("avg_forecast_error_pct", 0.0),
            "alpha_vs_nifty_pct": scorecard.get("avg_alpha_pct", 0.0)
        }
    }


# ---------------------------------------------------------
# PHASE 4: AUTOMATED REPORT DISPATCHER
# ---------------------------------------------------------
@app.post("/api/reports/dispatch")
def dispatch_report_endpoint(req: Optional[EmailDispatchRequest] = None) -> Dict[str, Any]:
    """Dispatch the morning 5:45 AM briefing via SMTP or audited sandbox log."""
    r_date = req.report_date if req else None
    r_email = req.recipient_email if req else None
    return dispatch_morning_report(report_date=r_date, recipient_email=r_email)

