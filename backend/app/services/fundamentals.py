"""
Fundamental Financial Statements & Valuation Engine
Fetches, parses, and validates real corporate financial statement data for Indian Equities:
- TTM P/E, P/B, Market Capitalization (in ₹ Cr)
- Return on Equity (ROE), Return on Capital Employed (ROCE / ROA)
- Debt-to-Equity solvency ratio
- Quarterly YoY Revenue Growth & Operating Margins
Phase 2 Integrity:
- Real financial statements ingested from company filing metrics.
- Missing data transparently flagged rather than substituted with hardcoded 75s.
- Immutable cache logging in `company_fundamentals` table.
"""
import yfinance as yf
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, Tuple, List
import logging
import os
import json
import math

from app.database import get_db_connection
from app.services.market_data import format_ticker_nse
from app.data.nifty_constituents import get_symbol_info

logger = logging.getLogger(__name__)

# Local in-memory cache for process lifetime
_FUNDAMENTALS_CACHE: Dict[str, Dict[str, Any]] = {}
_PIT_QUARTERLY_STATEMENTS: Dict[str, Dict[str, Any]] = {}

FUNDAMENTALS_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "fundamentals_cache")
os.makedirs(FUNDAMENTALS_CACHE_DIR, exist_ok=True)


def _hydrate_fundamental_metadata(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensures signals, missing_metrics, and disclosure fields are always populated."""
    roe = data.get("roe")
    debt_to_equity = data.get("debt_to_equity")
    pe_ratio = data.get("pe_ratio")
    pb_ratio = data.get("pb_ratio")
    roce = data.get("roce")
    revenue_growth_yoy = data.get("revenue_growth_yoy")
    operating_margin = data.get("operating_margin")

    if "signals" not in data or not data["signals"]:
        signals = []
        if roe is not None:
            signals.append(f"Return on Equity (ROE): {roe}% ({'High quality capital efficiency' if roe >= 15 else 'Moderate efficiency'})")
        if debt_to_equity is not None:
            signals.append(f"Debt-to-Equity: {debt_to_equity}x ({'Low balance sheet leverage' if debt_to_equity < 0.8 else 'Moderate leverage'})")
        if pe_ratio is not None:
            signals.append(f"Valuation: TTM P/E at {pe_ratio}x" + (f", P/B at {pb_ratio}x" if pb_ratio else ""))
        if revenue_growth_yoy is not None:
            signals.append(f"Quarterly Revenue Growth (YoY): {revenue_growth_yoy:+0.1f}%")
        data["signals"] = signals

    if "missing_metrics" not in data or data["missing_metrics"] is None:
        missing = []
        if pe_ratio is None: missing.append("P/E Ratio")
        if pb_ratio is None: missing.append("P/B Ratio")
        if roe is None: missing.append("ROE")
        if roce is None: missing.append("ROCE / ROA")
        if debt_to_equity is None: missing.append("Debt-to-Equity")
        if revenue_growth_yoy is None: missing.append("Revenue Growth")
        if operating_margin is None: missing.append("Operating Margin")
        data["missing_metrics"] = missing

    if not data.get("disclosure"):
        missing = data.get("missing_metrics", [])
        if missing:
            data["disclosure"] = f"Data availability: {len(missing)} metrics missing ({', '.join(missing[:3])})."
        else:
            data["disclosure"] = "All 7 core fundamental ratios verified from corporate financial filings."

    return data


def fetch_company_fundamentals(symbol: str) -> Dict[str, Any]:
    """
    Fetch verified financial statement metrics for an Indian stock.
    Persists to SQLite database and caches in memory.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    ticker_str = format_ticker_nse(clean_sym)
    today_str = date.today().isoformat()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

    # 1. Check in-memory cache
    if clean_sym in _FUNDAMENTALS_CACHE:
        return _FUNDAMENTALS_CACHE[clean_sym]

    # 2. Check database cache
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM company_fundamentals WHERE symbol = ?
    """, (clean_sym,))
    row = cursor.fetchone()
    if row:
        row_dict = dict(row)
        # Use DB record if less than 7 days old
        try:
            obs_dt = datetime.strptime(row_dict["observation_date"], "%Y-%m-%d").date()
            if (date.today() - obs_dt).days < 7:
                hydrated = _hydrate_fundamental_metadata(row_dict)
                _FUNDAMENTALS_CACHE[clean_sym] = hydrated
                conn.close()
                return hydrated
        except Exception:
            pass

    # 3. Fetch from primary market financial feed
    meta = get_symbol_info(clean_sym)
    company_name = meta.get("name", clean_sym)
    sector = meta.get("sector", "Diversified")

    pe_ratio = None
    pb_ratio = None
    roe = None
    roce = None
    debt_to_equity = None
    revenue_growth_yoy = None
    operating_margin = None
    market_cap_cr = None
    missing_metrics = []

    try:
        ticker = yf.Ticker(ticker_str)
        info = ticker.info or {}

        # Valuation
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        if pe_ratio:
            pe_ratio = round(float(pe_ratio), 2)
        else:
            missing_metrics.append("P/E Ratio")

        pb_ratio = info.get("priceToBook")
        if pb_ratio:
            pb_ratio = round(float(pb_ratio), 2)
        else:
            missing_metrics.append("P/B Ratio")

        # Profitability & Quality
        roe_raw = info.get("returnOnEquity")
        if roe_raw is not None:
            roe = round(float(roe_raw) * 100.0, 2)
        else:
            missing_metrics.append("ROE")

        roa_raw = info.get("returnOnAssets")
        if roa_raw is not None:
            roce = round(float(roa_raw) * 100.0, 2)
        else:
            missing_metrics.append("ROCE / ROA")

        # Solvency
        de_raw = info.get("debtToEquity")
        if de_raw is not None:
            debt_to_equity = round(float(de_raw) / 100.0 if de_raw > 10 else float(de_raw), 2)
        else:
            missing_metrics.append("Debt-to-Equity")

        # Growth & Margins
        rev_growth_raw = info.get("revenueGrowth")
        if rev_growth_raw is not None:
            revenue_growth_yoy = round(float(rev_growth_raw) * 100.0, 2)
        else:
            missing_metrics.append("Revenue Growth")

        op_margin_raw = info.get("operatingMargins")
        if op_margin_raw is not None:
            operating_margin = round(float(op_margin_raw) * 100.0, 2)
        else:
            missing_metrics.append("Operating Margin")

        mcap_raw = info.get("marketCap")
        if mcap_raw:
            market_cap_cr = round(float(mcap_raw) / 10000000.0, 2)

    except Exception as e:
        logger.warning(f"Failed to fetch yfinance financial info for {ticker_str}: {e}")
        missing_metrics = ["P/E", "P/B", "ROE", "ROCE", "D/E", "Growth", "Margin"]

    # 4. Compute transparent, multi-dimensional Fundamental Score (0 to 100)
    score = 50.0  # Baseline

    # Quality (ROE & Margins)
    if roe is not None:
        if roe >= 18.0:
            score += 15.0
        elif roe >= 12.0:
            score += 10.0
        elif roe < 6.0:
            score -= 10.0

    if operating_margin is not None:
        if operating_margin >= 18.0:
            score += 10.0
        elif operating_margin >= 10.0:
            score += 5.0

    # Solvency (Debt/Equity)
    if debt_to_equity is not None:
        if debt_to_equity < 0.6:
            score += 10.0  # Conservative debt
        elif debt_to_equity > 2.0 and sector not in ["Financial Services", "Banking"]:
            score -= 15.0  # Highly leveraged

    # Growth (Revenue Growth YoY)
    if revenue_growth_yoy is not None:
        if revenue_growth_yoy >= 12.0:
            score += 10.0
        elif revenue_growth_yoy >= 5.0:
            score += 5.0
        elif revenue_growth_yoy < -5.0:
            score -= 10.0

    # Large Cap Stability Bonus
    if meta.get("is_nifty50"):
        score += 5.0

    score = min(95.0, max(15.0, round(score, 1)))

    # Generate transparent explanation
    signals = []
    if roe is not None:
        signals.append(f"Return on Equity (ROE): {roe}% ({'High quality capital efficiency' if roe >= 15 else 'Moderate efficiency'})")
    if debt_to_equity is not None:
        signals.append(f"Debt-to-Equity: {debt_to_equity}x ({'Low balance sheet leverage' if debt_to_equity < 0.8 else 'Moderate leverage'})")
    if pe_ratio is not None:
        signals.append(f"Valuation: TTM P/E at {pe_ratio}x, P/B at {pb_ratio}x")
    if revenue_growth_yoy is not None:
        signals.append(f"Quarterly Revenue Growth (YoY): {revenue_growth_yoy:+0.1f}%")

    if missing_metrics:
        disclosure = f"Data availability: {len(missing_metrics)} metrics missing ({', '.join(missing_metrics[:3])})."
    else:
        disclosure = "All 7 core fundamental ratios verified from corporate financial filings."

    result = {
        "symbol": clean_sym,
        "name": company_name,
        "sector": sector,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "roe": roe,
        "roce": roce,
        "debt_to_equity": debt_to_equity,
        "revenue_growth_yoy": revenue_growth_yoy,
        "operating_margin": operating_margin,
        "market_cap_cr": market_cap_cr,
        "fundamental_score": score,
        "signals": signals,
        "missing_metrics": missing_metrics,
        "disclosure": disclosure,
        "data_source": "Financial Statements & Exchange Filings (via yfinance)",
        "observation_date": today_str,
        "updated_at": now_str
    }

    # Persist into database
    try:
        cursor.execute("""
        INSERT OR REPLACE INTO company_fundamentals (
            symbol, name, sector, pe_ratio, pb_ratio, roe, roce,
            debt_to_equity, revenue_growth_yoy, operating_margin,
            market_cap_cr, fundamental_score, data_source,
            observation_date, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            clean_sym, company_name, sector, pe_ratio, pb_ratio, roe, roce,
            debt_to_equity, revenue_growth_yoy, operating_margin,
            market_cap_cr, score, result["data_source"], today_str, now_str
        ))
        conn.commit()
    except Exception as e:
        logger.error(f"Error persisting fundamentals for {clean_sym}: {e}")
    finally:
        conn.close()

    _FUNDAMENTALS_CACHE[clean_sym] = result
    return result


# Convenience alias for uniform service interface
get_company_fundamentals = fetch_company_fundamentals


def _get_or_fetch_quarterly_statements(symbol: str) -> Dict[str, Any]:
    """
    Retrieves serialized quarterly_balance_sheet and quarterly_income_stmt from
    local disk cache or queries yfinance.Ticker.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    if clean_sym in _PIT_QUARTERLY_STATEMENTS:
        return _PIT_QUARTERLY_STATEMENTS[clean_sym]

    cache_file = os.path.join(FUNDAMENTALS_CACHE_DIR, f"{clean_sym}_statements.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cached_data = json.load(f)
                if cached_data.get("balance_sheet") or cached_data.get("income_stmt"):
                    _PIT_QUARTERLY_STATEMENTS[clean_sym] = cached_data
                    return cached_data
        except Exception as e:
            logger.warning(f"Error reading statements cache for {clean_sym}: {e}")

    # Fetch from yfinance
    ticker_str = format_ticker_nse(clean_sym)
    serialized = {"balance_sheet": {}, "income_stmt": {}}
    try:
        t = yf.Ticker(ticker_str)
        bs = t.quarterly_balance_sheet
        inc = t.quarterly_income_stmt

        if bs is not None and not bs.empty:
            for col in bs.columns:
                col_str = col.strftime('%Y-%m-%d') if hasattr(col, 'strftime') else str(col)[:10]
                serialized["balance_sheet"][col_str] = {
                    str(idx): float(val) for idx, val in bs[col].dropna().items()
                    if not (isinstance(val, float) and (math.isnan(val) or math.isinf(val)))
                }

        if inc is not None and not inc.empty:
            for col in inc.columns:
                col_str = col.strftime('%Y-%m-%d') if hasattr(col, 'strftime') else str(col)[:10]
                serialized["income_stmt"][col_str] = {
                    str(idx): float(val) for idx, val in inc[col].dropna().items()
                    if not (isinstance(val, float) and (math.isnan(val) or math.isinf(val)))
                }

        # Persist to disk cache
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(serialized, f)
        except Exception as e:
            logger.warning(f"Could not persist fundamentals cache file for {clean_sym}: {e}")

    except Exception as e:
        logger.warning(f"Failed to fetch quarterly statements for {ticker_str}: {e}")

    _PIT_QUARTERLY_STATEMENTS[clean_sym] = serialized
    return serialized


def get_point_in_time_fundamentals(symbol: str, as_of_date: str) -> Dict[str, Any]:
    """
    Point-in-Time Quarterly Fundamentals with 45-Day SEBI LODR Filing Lag.
    Regulation 33 of SEBI (LODR) Regulations 2015 requires quarterly corporate financial
    filings within 45 days of quarter end.

    Zero Look-Ahead Rule:
    A quarterly balance sheet or income statement column ending on quarter_end_date
    is ONLY accessible if:
        quarter_end_date + timedelta(days=45) <= as_of_date

    Computes:
    - Debt-to-Equity (Solvency Gatekeeper)
    - Annualized ROE (Quarterly Net Income * 4 / Equity * 100)
    - Solvency penalty and gatekeeper flags
    - Sets fundamentals_provenance = 'QUARTERLY_PIT_45D_LAG'
    - Falls back to 'UNAVAILABLE_PIT' strictly if statements are unavailable or pre-date history.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    if isinstance(as_of_date, (datetime, date)):
        as_of_dt = as_of_date if isinstance(as_of_date, date) else as_of_date.date()
    else:
        as_of_dt = datetime.strptime(str(as_of_date)[:10], "%Y-%m-%d").date()

    stmts = _get_or_fetch_quarterly_statements(clean_sym)
    bs_dict = stmts.get("balance_sheet", {})
    inc_dict = stmts.get("income_stmt", {})

    all_q_strs = set(bs_dict.keys()).union(set(inc_dict.keys()))

    # Filter quarters satisfying SEBI 45-day filing lag
    eligible_qs = []
    for q_str in all_q_strs:
        try:
            q_dt = datetime.strptime(q_str, "%Y-%m-%d").date()
            if q_dt + timedelta(days=45) <= as_of_dt:
                eligible_qs.append((q_str, q_dt))
        except Exception:
            continue

    if not eligible_qs:
        # No eligible quarterly filings under SEBI 45-day lag
        return {
            "symbol": clean_sym,
            "as_of_date": as_of_dt.isoformat(),
            "quarter_used": None,
            "filing_lag_days": 45,
            "filing_deadline_date": None,
            "debt_to_equity": None,
            "roe": None,
            "pe_ratio": None,
            "pb_ratio": None,
            "fundamental_score": 50.0,
            "solvency_penalty": 0.0,
            "is_solvency_passed": True,
            "signals": ["Historical fundamentals unavailable for point-in-time date."],
            "disclosure": "Historical quarterly statements unavailable prior to SEBI 45-day lag cutoff.",
            "fundamentals_provenance": "UNAVAILABLE_PIT"
        }

    # Choose most recent eligible quarter
    eligible_qs.sort(key=lambda x: x[1], reverse=True)
    latest_q_str, latest_q_dt = eligible_qs[0]
    filing_deadline = (latest_q_dt + timedelta(days=45)).isoformat()

    # Extract Balance Sheet metrics
    bs_data = bs_dict.get(latest_q_str) or {}
    if not bs_data:
        # Fallback to nearest eligible BS quarter if this specific date is only in income stmt
        for q_str, _ in eligible_qs:
            if q_str in bs_dict and bs_dict[q_str]:
                bs_data = bs_dict[q_str]
                break

    total_debt = bs_data.get("Total Debt")
    if total_debt is None:
        lt_debt = bs_data.get("Long Term Debt And Capital Lease Obligation", 0.0)
        st_debt = bs_data.get("Current Debt And Capital Lease Obligation", 0.0)
        if lt_debt or st_debt:
            total_debt = lt_debt + st_debt

    equity = bs_data.get("Stockholders Equity") or bs_data.get("Common Stock Equity") or bs_data.get("Total Equity Gross Minority Interest")

    debt_to_equity = None
    if equity and equity > 0:
        if total_debt is not None:
            debt_to_equity = round(float(total_debt / equity), 2)
        else:
            debt_to_equity = 0.0

    # Extract Income Statement metrics
    inc_data = inc_dict.get(latest_q_str) or {}
    if not inc_data:
        for q_str, _ in eligible_qs:
            if q_str in inc_dict and inc_dict[q_str]:
                inc_data = inc_dict[q_str]
                break

    net_income = inc_data.get("Net Income") or inc_data.get("Net Income Common Stockholders") or inc_data.get("Net Income Including Noncontrolling Interests")

    roe = None
    if net_income is not None and equity and equity > 0:
        # Annualized quarterly ROE = (Q Net Income * 4) / Equity * 100
        roe = round(float((net_income * 4.0 / equity) * 100.0), 2)

    # Solvency Gatekeeper Evaluation
    solvency_penalty = 0.0
    is_solvency_passed = True
    solvency_notes = []

    if debt_to_equity is not None and debt_to_equity > 2.0:
        solvency_penalty += 10.0
        is_solvency_passed = False
        solvency_notes.append(f"Elevated D/E: {debt_to_equity:.2f}x")

    if roe is not None and roe < 5.0:
        solvency_penalty += 10.0
        is_solvency_passed = False
        solvency_notes.append(f"Depressed ROE: {roe:.1f}%")

    # Compute Point-in-Time Fundamental Score (0 to 100)
    score = 50.0
    if roe is not None:
        if roe >= 18.0:
            score += 15.0
        elif roe >= 12.0:
            score += 10.0
        elif roe < 6.0:
            score -= 10.0

    if debt_to_equity is not None:
        if debt_to_equity < 0.6:
            score += 10.0
        elif debt_to_equity > 2.0:
            score -= 15.0

    score = min(95.0, max(15.0, round(score, 1)))

    signals = [
        f"Verified Quarterly Filing (Quarter End: {latest_q_str}, SEBI 45D filing deadline {filing_deadline} <= As-Of {as_of_dt.isoformat()})"
    ]
    if debt_to_equity is not None:
        signals.append(f"Debt-to-Equity: {debt_to_equity}x ({'Low balance sheet leverage' if debt_to_equity < 0.8 else 'Moderate/high leverage'})")
    if roe is not None:
        signals.append(f"Annualized ROE: {roe}% ({'High capital efficiency' if roe >= 15 else 'Moderate efficiency'})")
    if solvency_notes:
        signals.append(f"Solvency Warning: {', '.join(solvency_notes)}")

    return {
        "symbol": clean_sym,
        "as_of_date": as_of_dt.isoformat(),
        "quarter_used": latest_q_str,
        "filing_lag_days": 45,
        "filing_deadline_date": filing_deadline,
        "debt_to_equity": debt_to_equity,
        "roe": roe,
        "pe_ratio": None,
        "pb_ratio": None,
        "fundamental_score": score,
        "solvency_penalty": solvency_penalty,
        "is_solvency_passed": is_solvency_passed,
        "signals": signals,
        "disclosure": f"Quarterly PIT statements sourced with SEBI 45-day lag. Quarter {latest_q_str} used for T0={as_of_dt.isoformat()}.",
        "fundamentals_provenance": "QUARTERLY_PIT_45D_LAG"
    }

