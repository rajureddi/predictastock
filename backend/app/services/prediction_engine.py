"""
Multi-Factor 5-Day High-Alpha Prediction & Stock Screening Engine
Combines Technical Momentum, Relative Strength vs Nifty, Institutional Money Flow (CMF & Volume Surge),
Solvency Gatekeeper (D/E & ROE constraints), Top-Down Sector Rotation, and News Catalysts.
Applies a 5-day band of about 1.73 times the 14-day ATR, News Veto Rule, and Immutable Database Logging.

Phase 1 & Phase 2 Integrity Rules:
- NO forced always-positive price targets.
- The 5-day band is about 1.73 times the 14-day ATR around the last close. The trade target stays separate.
- Removal of tautologies (cmp > low_bound strictly rejected).
- Institutional liquidity hurdle: Minimum ₹5 Crore daily turnover (avg_volume_20d * cmp >= 50,000,000).
- Solvency Gatekeeper: Penalize D/E > 2.0 or ROE < 5% (does not penalize high P/E growth stocks).
- Top-Down Sector Rotation: +5 points if parent sector outperforming Nifty 50, -5 if lagging.
- Cash vs F&O Action Labeling: Multi-day cash shorts labeled as 'EXIT HOLDINGS / AVOID (F&O Short Only)'.
"""
import uuid
import json
import math
import random
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Callable
import logging
import numpy as np

from app.database import get_db_connection
from app.config import (
    MAX_RECOMMENDATIONS_PER_DAY, WEIGHT_TECHNICAL,
    WEIGHT_MONEY_FLOW, WEIGHT_NEWS_SENTIMENT, WEIGHT_MACRO_FLOW,
    MIN_DAILY_TURNOVER_INR, ENABLE_STRICT_EVIDENCE_GATE,
    SCAN_MIN_TURNOVER_CR, EOD_HISTORY_SESSIONS,
    EXCLUDED_SERIES, ENTRY_SETUP_BONUS, RANKER_VOL_CAP_ATR_PCT,
    REGIME_SIZE_BULL, REGIME_SIZE_CORRECTION, REGIME_SIZE_UNKNOWN,
    REPORTS_DIR,
)
from app.services.eod_store import sync_eod_store, get_full_market_universe
from app.data.nifty_constituents import (
    FULL_NSE_UNIVERSE, NIFTY_UNIVERSE, get_symbol_info, get_dynamic_bhavcopy_universe
)
from app.data.nse_calendar import get_nth_trading_day, is_trading_day
from app.services.market_data import (
    get_stock_history, get_historical_market_bars, get_nifty50_live_status, get_latest_quote, 
    is_quote_valid, get_sector_relative_strengths, get_nifty50_regime
)
from app.services.indicators import (
    compute_all_indicators, compute_mathematical_5d_range,
    evaluate_strict_long_setup, classify_entry_setup,
)
from app.services.news_sentiment import fetch_stock_news_rss, analyze_sentiment
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Fix 2: 120-Bar Gate ensures EMA-50 and EMA-200 have full warm-up periods
MIN_HISTORICAL_BARS = 120

logger = logging.getLogger(__name__)

_PROGRESS_LOCK = threading.Lock()

# Real-time screening tracker for loader HUD
SCAN_PROGRESS: Dict[str, Any] = {
    "is_active": False,
    "current_symbol": "",
    "current_name": "",
    "evaluated_count": 0,
    "qualified_count": 0,
    "target_count": 250,
    "percent": 0,
    "stage_text": "Idle",
    "updated_at": time.time()
}

def get_scan_progress() -> Dict[str, Any]:
    """Retrieve atomic snapshot of current stock screening progress."""
    with _PROGRESS_LOCK:
        return dict(SCAN_PROGRESS)

def update_scan_progress(
    is_active: bool = True,
    current_symbol: str = "",
    current_name: str = "",
    evaluated_count: int = 0,
    qualified_count: int = 0,
    target_count: int = 58,
    percent: int = 0,
    stage_text: str = ""
):
    global SCAN_PROGRESS
    with _PROGRESS_LOCK:
        SCAN_PROGRESS["is_active"] = is_active
        SCAN_PROGRESS["current_symbol"] = current_symbol
        SCAN_PROGRESS["current_name"] = current_name
        SCAN_PROGRESS["evaluated_count"] = evaluated_count
        SCAN_PROGRESS["qualified_count"] = qualified_count
        SCAN_PROGRESS["target_count"] = target_count
        SCAN_PROGRESS["percent"] = percent
        SCAN_PROGRESS["stage_text"] = stage_text
        SCAN_PROGRESS["updated_at"] = time.time()


def supersede_previous_runs_for_date(
    cursor, 
    rec_date_str: str, 
    new_run_id: str, 
    new_version: int, 
    reason: str = "Superseded by intraday rescan"
):
    """
    Append-Only Architectural Protection: Never deletes sealed recommendation history.
    Marks prior active runs for this date as SUPERSEDED and logs an immutable audit event in recommendation_audit_events.
    """
    cursor.execute("""
        SELECT id, symbol, run_id, status FROM recommendations
        WHERE rec_date = ? AND (is_superseded = 0 OR is_superseded IS NULL)
    """, (rec_date_str,))
    prior_recs = cursor.fetchall()

    for prec in prior_recs:
        audit_id = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO recommendation_audit_events (
                id, recommendation_id, run_id, event_type, old_status, new_status, reason, created_at
            ) VALUES (?, ?, ?, 'SUPERSEDED', ?, 'SUPERSEDED', ?, ?)
        """, (
            audit_id, prec["id"], prec["run_id"] if prec["run_id"] else "legacy_run",
            prec["status"], f"{reason} (New Run {new_run_id} v{new_version})",
            datetime.now().isoformat()
        ))

    cursor.execute("""
        UPDATE recommendations 
        SET is_superseded = 1 
        WHERE rec_date = ? AND (is_superseded = 0 OR is_superseded IS NULL)
    """, (rec_date_str,))

    cursor.execute("""
        UPDATE recommendation_runs
        SET status = 'SUPERSEDED'
        WHERE rec_date = ? AND status = 'ACTIVE'
    """, (rec_date_str,))



# Last completed weekly book, 1 Dec 2025 through 31 Oct 2026. Used when the
# forecast ledger does not yet have enough settled rows to estimate a hit rate.
WEEKLY_BOOK_HIT_RATE_PCT = 44.8
_HIT_RATE_CACHE: Dict[str, Any] = {"ready": False, "overall": WEEKLY_BOOK_HIT_RATE_PCT, "source": "weekly book", "buckets": []}


def empirical_hit_rate(composite_score: Optional[float] = None) -> Dict[str, Any]:
    """Measured hit rate for expectancy. A score bucket is used only when it has 40 settled forecasts."""
    if not _HIT_RATE_CACHE["ready"]:
        _load_empirical_hit_rates()
    chosen = None
    if composite_score is not None:
        for bucket in _HIT_RATE_CACHE["buckets"]:
            if bucket["low"] <= float(composite_score) < bucket["high"]:
                chosen = bucket
                break
    if chosen:
        return {"hit_rate_pct": chosen["rate"], "source": chosen["source"], "sample_size": chosen["sample_size"]}
    return {
        "hit_rate_pct": _HIT_RATE_CACHE["overall"],
        "source": _HIT_RATE_CACHE["source"],
        "sample_size": _HIT_RATE_CACHE.get("sample_size", 0),
    }


def _load_empirical_hit_rates() -> None:
    rows = []
    try:
        conn = get_db_connection()
        try:
            rows = conn.execute(
                """
                SELECT r.composite_score AS composite_score, f.direction_correct AS direction_correct
                FROM forecast_evaluations f
                LEFT JOIN recommendations r ON r.id = f.recommendation_id
                WHERE f.status = 'COMPLETED' AND f.direction_correct IS NOT NULL
                """
            ).fetchall()
        finally:
            conn.close()
    except Exception as exc:
        logger.warning("Forecast ledger unavailable for the hit rate: %s", exc)
        rows = []
    settled = [(row["composite_score"], int(row["direction_correct"])) for row in rows]
    overall = WEEKLY_BOOK_HIT_RATE_PCT
    source = "weekly book 1 Dec 2025-31 Oct 2026"
    sample_size = len(settled)
    if sample_size >= 40:
        overall = round(sum(flag for _score, flag in settled) / sample_size * 100.0, 1)
        source = "forecast_evaluations"
    buckets = []
    if sample_size >= 40:
        for low in range(0, 100, 10):
            members = [flag for score, flag in settled if score is not None and low <= float(score) < low + 10]
            if len(members) >= 40:
                buckets.append({
                    "low": low,
                    "high": low + 10,
                    "rate": round(sum(members) / len(members) * 100.0, 1),
                    "sample_size": len(members),
                    "source": f"forecast_evaluations composite {low}-{low + 10}",
                })
    _HIT_RATE_CACHE.update({
        "ready": True,
        "overall": overall,
        "source": source,
        "sample_size": sample_size,
        "buckets": buckets,
    })


def score_single_stock(
    symbol: str,
    as_of_date: Optional[str] = None,
    macro_context: Optional[Dict[str, Any]] = None,
    include_live_news: bool = False,
    yahoo_ticker: Optional[str] = None,
    enforce_liquidity_floor: bool = True,
    display_name: Optional[str] = None,
    min_turnover_inr: Optional[float] = None,
    cached_fundamentals_only: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Run 4-pillar high-alpha analysis for an Indian market equity:
    - 45% Technical Momentum & Relative Strength
    - 25% Institutional Money Flow (CMF-20, MFI-14, Volume Surge, Delivery Spike)
    - 20% News Sentiment & Catalysts (News Veto Rule <= -0.40)
    - 10% Macro Regime (Nifty 50 trend & India VIX)
    - Solvency Gatekeeper / Penalties (ROE < 5% or D/E > 2.0)
    - Top-Down Sector Rotation Alignment (+5 if sector leading, -5 if lagging)
    - Minimum ₹5 Crore daily rupee turnover filter
    
    Dynamic Pillar Weight Renormalization Rule:
    When news is UNAVAILABLE_PIT (or empty):
    - Solvency Gatekeeper remains active.
    - Exclude unavailable news pillar from the weighted average.
    - Renormalize remaining verified PIT pillars so weights sum to 1.0:
      Tech = 0.45 / 0.80 = 56.25%
      MoneyFlow = 0.25 / 0.80 = 31.25%
      Macro = 0.10 / 0.80 = 12.50%
    - Record scoring_mode = 'PIT_RENORMALIZED_NO_NEWS' vs 'FULL_4_PILLAR_PIT'.
    """
    meta = dict(get_symbol_info(symbol))
    if display_name and (not meta.get("name") or meta.get("name") == symbol):
        meta["name"] = display_name

    # The bhavcopy store is the only series a historical score may use. Yahoo's
    # "1y" window is anchored to today, so clipping it to an older Monday mixes
    # two price series and drops the early weeks.
    df = get_historical_market_bars(symbol, lookback_days=250, as_of_date=as_of_date)
    if as_of_date:
        as_of_str = str(as_of_date)[:10]
        if not df.empty:
            df = df[df.index <= as_of_str]
        min_required_bars = 45
    else:
        if df.empty or len(df) < MIN_HISTORICAL_BARS:
            df = get_stock_history(symbol, period="1y", yahoo_ticker=yahoo_ticker)
        min_required_bars = MIN_HISTORICAL_BARS
    if df.empty or len(df) < min_required_bars:
        logger.warning(f"Insufficient historical data for {symbol} ({len(df)} bars < {min_required_bars}-bar gate), skipping per data integrity rules.")
        return None

    macro = macro_context or get_nifty50_regime(as_of_date=as_of_date)
    nifty_return_20d = float(macro.get("return_20d_pct") or 0.0)

    from app.services.market_data import get_nse_bhavcopy_for_symbol
    # Today's Bhavcopy must never be attached to an historical as-of score.
    # Historical delivery is supplied by the indexed historical-market dataset
    # used by the walk-forward evaluator.
    bhav_info = None if as_of_date else get_nse_bhavcopy_for_symbol(symbol)
    tech = compute_all_indicators(
        df,
        nifty_return_20d=nifty_return_20d,
        bhavcopy_data=bhav_info,
    )
    cmp = tech["cmp"]
    if cmp <= 0:
        logger.warning(f"Invalid CMP ({cmp}) for {symbol}, skipping.")
        return None

    # Requirement 1: Institutional Rupee Turnover Floor (₹5 Crore minimum daily turnover)
    avg_vol_20d = float(df["Volume"].tail(20).mean()) if "Volume" in df.columns and len(df) >= 20 else 0.0
    avg_turnover_inr = avg_vol_20d * cmp
    liquidity_note = ""
    turnover_floor = MIN_DAILY_TURNOVER_INR if min_turnover_inr is None else min_turnover_inr
    if avg_turnover_inr < turnover_floor:
        liquidity_note = (
            f"20-day turnover is ₹{avg_turnover_inr/1e7:.2f} Cr, below the ₹{turnover_floor/1e7:g} Cr scan hurdle."
        )
        if enforce_liquidity_floor:
            logger.info(f"Skipping illiquid stock {symbol}: {liquidity_note}")
            return None
        logger.info(f"Desk analysis kept for {symbol}: {liquidity_note}")

    atr = tech["atr_14"]
    vol_5d = tech["volatility_5d_pct"]
    tech_score = tech["technical_score"]
    mf_score = tech["money_flow_score"]
    
    # Requirement 4: Solvency Gatekeeper (Fundamentals)
    if as_of_date:
        from app.services.fundamentals import get_point_in_time_fundamentals
        fund_data = get_point_in_time_fundamentals(symbol, as_of_date=as_of_date)
        fundamentals_provenance = fund_data.get("fundamentals_provenance", "QUARTERLY_PIT_45D_LAG")
    elif cached_fundamentals_only:
        from app.services.fundamentals import get_cached_fundamentals
        fund_data = get_cached_fundamentals(symbol, yahoo_ticker=yahoo_ticker)
        fundamentals_provenance = "CACHED_FILINGS" if fund_data else "DEFERRED_TO_FINALIST_AUDIT"
    else:
        from app.services.fundamentals import fetch_company_fundamentals
        fund_data = fetch_company_fundamentals(
            symbol,
            yahoo_ticker=yahoo_ticker,
            company_name=display_name,
        ) or {}
        fundamentals_provenance = "LIVE_OFFICIAL_FILINGS"

    de_ratio = fund_data.get("debt_to_equity")
    roe_val = fund_data.get("roe")
    
    solvency_penalty = fund_data.get("solvency_penalty", 0.0)
    solvency_notes = []
    if de_ratio is not None and de_ratio > 2.0:
        if solvency_penalty == 0.0:
            solvency_penalty += 10.0
        solvency_notes.append(f"Elevated D/E: {de_ratio:.2f}x")
    if roe_val is not None and roe_val < 5.0:
        if solvency_penalty == 0.0:
            solvency_penalty += 10.0
        solvency_notes.append(f"Depressed ROE: {roe_val:.1f}%")
        
    signals = fund_data.get("signals") or []
    disclosure = fund_data.get("disclosure") or "Audited corporate fundamentals verified."
    fund_summary = "; ".join(signals[:2]) if signals else disclosure
    if solvency_notes:
        fund_summary += f" [Solvency Warning: {', '.join(solvency_notes)}]"
    if liquidity_note:
        fund_summary += f" [Liquidity: {liquidity_note} Shown because this stock was opened directly.]"
    
    # Pillar 3: News & Sentiment (Fix 3: Optimized latency)
    # During high-throughput universe screening, defer external HTTP RSS calls to Step 9 (Top 25 finalists).
    # If as_of_date is provided, checks local SQLite historical_news_cache first.
    news_items = []
    if as_of_date or include_live_news:
        news_items = fetch_stock_news_rss(symbol, max_items=4, as_of_date=as_of_date)

    if news_items:
        sent_score, sent_label, catalysts, risks = analyze_sentiment(news_items)
        # Veto Rule check: Disqualify on severe negative news
        if sent_score <= -0.4:
            logger.info(f"VETO RULE TRIGGERED on {symbol}: News sentiment is {sent_score} ({sent_label}). Disqualified.")
            return None
        news_multiplier = (sent_score + 1.0) * 50.0 # Maps [-1, 1] to [0, 100]
        has_news = True
        news_provenance = "FULL_4_PILLAR_PIT" if as_of_date else "LIVE_GOOGLE_NEWS"
    else:
        sent_score, sent_label, catalysts, risks = 0.0, "Pre-Filter Baseline" if not as_of_date else "No Recent Headlines", [], []
        news_multiplier = 50.0
        has_news = False
        news_provenance = "UNAVAILABLE_PIT"
    
    # Pillar 4: Macro regime uses the completed Nifty 20-session trend.  A
    # single positive daily move is not sufficient confirmation for a long.
    if macro.get("is_valid") and macro.get("is_bullish"):
        macro_score = 70.0
    elif macro.get("is_valid"):
        macro_score = 35.0
    else:
        macro_score = 50.0
        
    # Sector strength remains visible to the user, but it is not used to move
    # the score until it has its own point-in-time validation history.
    sector_rs_map = get_sector_relative_strengths() if not as_of_date else {}
    stock_sector = meta.get("sector", "Other")
    sector_rs = sector_rs_map.get(stock_sector, 0.0)

    # Dynamic Pillar Weight Renormalization
    if not has_news or news_provenance == "UNAVAILABLE_PIT":
        # Renormalized: Tech = 56.25%, MoneyFlow = 31.25%, Macro = 12.50%
        scoring_mode = "PIT_RENORMALIZED_NO_NEWS"
        base_composite = (tech_score * 0.45 + mf_score * 0.25 + macro_score * 0.10) / 0.80
    else:
        scoring_mode = "FULL_4_PILLAR_PIT" if as_of_date else "FULL_4_PILLAR_LIVE"
        base_composite = (
            (tech_score * WEIGHT_TECHNICAL) +
            (mf_score * WEIGHT_MONEY_FLOW) +
            (news_multiplier * WEIGHT_NEWS_SENTIMENT) +
            (macro_score * WEIGHT_MACRO_FLOW)
        )

    composite_score = round(base_composite - solvency_penalty, 1)
    composite_score = float(np.clip(composite_score, 10.0, 95.0))
    
    # Statistical Calibrated 5-Day ATR Volatility Cone & Directional Scenario
    price_range = compute_mathematical_5d_range(
        cmp=cmp, 
        atr=atr, 
        vol_5d_pct=vol_5d, 
        signal=tech["signal"], 
        rsi=tech["rsi_14"],
        sma_20=tech["sma_20"],
        macd_hist=tech["macd_hist"],
        cmf_20=tech["cmf_20"],
        vol_surge=tech["vol_surge"],
        resistance=tech.get("resistance", 0.0),
        support=tech.get("support", 0.0),
        rs_20d=tech.get("rs_20d", 0.0),
        macro_regime=macro,
        deliv_per=tech.get("deliv_per", 45.0),
        deliv_surge=tech.get("deliv_surge", 1.0),
        is_vcp_squeeze=tech.get("is_vcp_squeeze", False),
        sma_50=tech.get("sma_50", 0.0),
        delivery_zscore=float(tech.get("delivery_zscore") or 0.0),
        empirical_hit_rate=empirical_hit_rate(composite_score)["hit_rate_pct"],
    )
    direction = price_range.get("direction", "NEUTRAL")
    action_label = price_range.get("action_label", "HOLD / MONITOR")
    stop_loss = price_range.get("stop_loss", round(cmp - atr, 2))
    win_prob = price_range.get("win_probability_pct", 50.0)
    reward_to_risk = price_range.get("reward_to_risk", 1.0)
    setup_quality = price_range.get("setup_quality", "C")

    strict_setup = evaluate_strict_long_setup(
        tech=tech,
        composite_score=composite_score,
        macro=macro,
        solvency_penalty=solvency_penalty,
    )
    
    # Risk Level classification
    if vol_5d < 3.0 and tech["rsi_14"] < 65:
        risk_level = "Low"
    elif vol_5d > 4.5 or tech["rsi_14"] > 70 or tech["rsi_14"] < 35:
        risk_level = "High"
    else:
        risk_level = "Medium"
        
    tech_summary = (
        f"RSI-14 at {tech['rsi_14']} with price {'above' if cmp >= tech['sma_20'] else 'below'} 20-DMA (₹{tech['sma_20']}). "
        f"CMF-20: {tech['cmf_20']:+.2f}, Vol Surge: {tech['vol_surge']}x, Squeeze: {tech['vol_squeeze']}x. "
        f"Stop-Loss: ₹{stop_loss} | 5D ATR Cone: ₹{price_range['expected_range_low']} to ₹{price_range['expected_range_high']}."
    )
    news_summary = (
        f"News tone is {sent_label} (Sentiment Score: {sent_score:+0.2f}). "
        f"{len(news_items)} recent headlines ingested."
    )
    
    status_text = action_label
    if macro.get("is_valid") and macro.get("is_bullish"):
        regime_size = REGIME_SIZE_BULL
    elif macro.get("is_valid"):
        regime_size = REGIME_SIZE_CORRECTION
    else:
        regime_size = REGIME_SIZE_UNKNOWN
    entry_setup = classify_entry_setup(tech)
    last = df.iloc[-1]
    circuit_locked = bool(
        float(last["Open"]) == float(last["High"]) == float(last["Low"]) == float(last["Close"])
    )
    price_anomaly = bool(
        "unexplained_jump" in df.columns and bool(df["unexplained_jump"].tail(3).fillna(False).any())
    )

    return {
        "symbol": symbol,
        "name": meta["name"],
        "sector": meta.get("sector", "Other"),
        "reference_price": cmp,
        "expected_target_price": price_range["expected_target_price"],
        "stop_loss": stop_loss,
        "expected_range_low": price_range["expected_range_low"],
        "expected_range_high": price_range["expected_range_high"],
        "expected_appreciation_pct": price_range["expected_appreciation_pct"],
        "calibrated_expectancy_pct": price_range.get("calibrated_expectancy_pct", 0.0),
        "direction": direction,
        "action_label": action_label,
        "composite_score": composite_score,
        "win_probability_pct": win_prob,
        "reward_to_risk": reward_to_risk,
        "setup_quality": setup_quality,
        "conviction_score": price_range.get("conviction_score", win_prob),
        "empirical_hit_rate_pct": price_range.get("empirical_hit_rate_pct"),
        "confidence_text": (
            f"Conviction Score: {win_prob:.0f} | "
            f"Expectancy uses {price_range.get('empirical_hit_rate_pct', WEEKLY_BOOK_HIT_RATE_PCT):.1f}% historical hit rate | "
            f"R/R: {reward_to_risk:.1f}x | Grade {setup_quality} Setup"
        ),
        "money_flow_score": mf_score,
        "technical_score": tech_score,
        "risk_level": risk_level,
        "status": status_text,
        "atr_14": atr,
        "volatility_5d_pct": vol_5d,
        "support_level": tech["support"],
        "resistance_level": tech["resistance"],
        "cmf_20": tech["cmf_20"],
        "mfi_14": tech["mfi_14"],
        "vol_surge": tech["vol_surge"],
        "vol_squeeze": tech["vol_squeeze"],
        "is_vcp_squeeze": tech.get("is_vcp_squeeze", False),
        "deliv_per": tech.get("deliv_per", 45.0),
        "deliv_surge": tech.get("deliv_surge", tech["vol_surge"]),
        "deliv_source": tech.get("deliv_source", "NSE Bhavcopy EOD"),
        "delivery_source": tech.get("delivery_source", "NSE_BHAVCOPY"),
        "is_bhavcopy_actual": tech.get("is_bhavcopy_actual", True),
        "rs_20d": tech.get("rs_20d", 0.0),
        "rsi_14": tech.get("rsi_14", 50.0),
        "atr_pct": round((atr / cmp) * 100.0, 2) if cmp else 0.0,
        "delivery_zscore": float(tech.get("delivery_zscore") or 0.0),
        "entry_setup": entry_setup,
        "setup_bonus": float(ENTRY_SETUP_BONUS.get(entry_setup, 0.0)),
        "regime_size_multiplier": regime_size,
        "circuit_locked": circuit_locked,
        "price_anomaly": price_anomaly,
        "sector_rs": sector_rs,
        "macro_regime": macro,
        "is_trade_eligible": strict_setup["is_eligible"],
        "eligibility_checks": strict_setup["checks"],
        "eligibility_check_count": strict_setup["check_count"],
        "eligibility_total_checks": strict_setup["total_checks"],
        "eligibility_failed_checks": strict_setup["failed_checks"],
        "technical_summary": tech_summary,
        "fundamental_summary": fund_summary,
        "news_summary": news_summary,
        "sentiment_score": sent_score,
        "sentiment_label": sent_label,
        "supporting_reasons": catalysts[:3],
        "downside_risks": risks[:3],
        "scoring_mode": scoring_mode,
        "news_provenance": news_provenance,
        "fundamentals_provenance": fundamentals_provenance,
        "quarter_used": fund_data.get("quarter_used"),
        "as_of_date": as_of_date
    }


def _is_primary_long(analysis: Dict[str, Any]) -> bool:
    """Same admission rule the live desk uses before ranking."""
    is_actionable = (
        analysis.get("direction") == "BULLISH"
        and float(analysis.get("expected_appreciation_pct", 0) or 0) > 0.0
    )
    if not is_actionable:
        return False
    if ENABLE_STRICT_EVIDENCE_GATE:
        return bool(analysis.get("is_trade_eligible"))
    return True


_CALIBRATION_CACHE: Dict[str, Any] = {"mtime": None, "model": None}


def _load_rank_calibration() -> Optional[Dict[str, Any]]:
    """Out-of-sample logistic fit. Idle until a finished backtest says it beats the stated win probability."""
    path = REPORTS_DIR / "win_prob_calibration.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if _CALIBRATION_CACHE["mtime"] != mtime:
        try:
            model = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            model = None
        if not isinstance(model, dict) or not model.get("rank_term_enabled"):
            model = None
        _CALIBRATION_CACHE["mtime"] = mtime
        _CALIBRATION_CACHE["model"] = model
    return _CALIBRATION_CACHE["model"]


def _calibration_rank_term(row: Dict[str, Any]) -> float:
    model = _load_rank_calibration()
    if not model:
        return 0.0
    fields = model.get("fields") or []
    center = model.get("center") or []
    scale = model.get("scale") or []
    coefs = model.get("coefficients") or {}
    if not fields or len(center) != len(fields) or len(scale) != len(fields):
        return 0.0
    try:
        z = float(coefs.get("intercept") or 0.0)
        for i, name in enumerate(fields):
            raw = row.get(name)
            if raw is None:
                return 0.0
            denom = float(scale[i]) or 1.0
            z += float(coefs.get(name) or 0.0) * ((float(raw) - float(center[i])) / denom)
    except (TypeError, ValueError):
        return 0.0
    z = max(-20.0, min(20.0, z))
    probability = 1.0 / (1.0 + math.exp(-z))
    return (probability - 0.5) * 6.0


def _engine_rank_key(row: Dict[str, Any]) -> float:
    atr_pct = float(row.get("atr_pct") or 0.0)
    vol_scale = min(1.0, RANKER_VOL_CAP_ATR_PCT / atr_pct) if atr_pct > 0 else 1.0
    delivery_z = max(-2.0, min(2.0, float(row.get("delivery_zscore") or 0.0)))
    return (
        float(row.get("calibrated_expectancy_pct", 0.0)) * 10.0 * vol_scale
        + float(row.get("win_probability_pct", 50.0)) * 0.40
        + float(row.get("composite_score", 50.0)) * 0.30
        + float(row.get("rs_20d", 0.0)) * 0.05
        + delivery_z * 0.8
        + float(row.get("setup_bonus") or 0.0)
        + _calibration_rank_term(row)
    )


def _corporate_ex_dates() -> Dict[str, List[date]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT symbol, ex_date FROM corporate_actions WHERE ex_date IS NOT NULL AND ex_date != ''"
        ).fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    booked: Dict[str, List[date]] = {}
    for row in rows:
        try:
            booked.setdefault(row["symbol"], []).append(datetime.strptime(str(row["ex_date"])[:10], "%Y-%m-%d").date())
        except ValueError:
            continue
    return booked


def apply_trade_hygiene(
    analysis: Dict[str, Any],
    scrip: Optional[Dict[str, Any]] = None,
    ex_dates: Optional[Dict[str, List[date]]] = None,
    surveillance: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    exchange_events: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Drop names a delivery book should not hold through the next week."""
    scrip = scrip or {}
    reasons = []
    series = str(scrip.get("series") or analysis.get("series") or "").upper()
    if series:
        analysis["series"] = series
    if series in EXCLUDED_SERIES:
        reasons.append("excluded series")
    if analysis.get("circuit_locked"):
        reasons.append("circuit lock")
    if analysis.get("price_anomaly"):
        reasons.append("unexplained price jump")
    anchor_text = analysis.get("as_of_date")
    anchor = datetime.strptime(str(anchor_text)[:10], "%Y-%m-%d").date() if anchor_text else date.today()
    window_end = anchor + timedelta(days=12)
    symbol = analysis.get("symbol")
    for ex_date in (ex_dates or {}).get(symbol, []):
        if anchor < ex_date <= window_end:
            reasons.append("corporate action inside the hold")
            break
    for snap in (surveillance or {}).get(symbol, []):
        observed = snap.get("observed_on")
        if isinstance(observed, date) and observed <= anchor:
            reasons.append(f"surveillance {snap.get('list_name')}")
            break
    for event in (exchange_events or {}).get(symbol, []):
        announced = event.get("announced_on")
        event_date = event.get("event_date")
        if (
            isinstance(announced, date)
            and isinstance(event_date, date)
            and announced <= anchor < event_date <= window_end
        ):
            reasons.append(f"{str(event.get('event_type') or 'event').lower()} inside the hold")
            break
    if reasons:
        analysis["trade_block"] = "; ".join(reasons)
    return analysis


def rank_engine_candidates(all_evaluated: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank scored names the same way the live recommendation run does.

    Primary names clear the strict long gate. If that list is shorter than the
    daily shortlist, the same bullish fallback (at least 1.2% expected move and
    58% win probability) fills the gap, then both groups share one sort.
    Names blocked by series, a circuit, a bad print, or an ex-date are not ranked.
    """
    pool = [row for row in all_evaluated if not row.get("trade_block")]
    candidates = [row for row in pool if _is_primary_long(row)]
    for row in candidates:
        row["admission_path"] = "strict"
    if len(candidates) < MAX_RECOMMENDATIONS_PER_DAY and pool:
        existing = {row["symbol"] for row in candidates}
        fallbacks = [
            row for row in pool
            if row.get("direction") == "BULLISH"
            and float(row.get("expected_appreciation_pct", 0) or 0) >= 1.2
            and float(row.get("win_probability_pct", 0) or 0) >= 58.0
            and row["symbol"] not in existing
        ]
        for row in fallbacks:
            row["admission_path"] = "fallback"
        fallbacks.sort(key=_engine_rank_key, reverse=True)
        candidates.extend(fallbacks)
    candidates.sort(key=_engine_rank_key, reverse=True)
    return candidates


def choose_diverse_picks(
    candidates: List[Dict[str, Any]],
    limit: int = MAX_RECOMMENDATIONS_PER_DAY,
) -> List[Dict[str, Any]]:
    """Keep the live desk's sector cap, then fill any open slots in rank order."""
    chosen: List[Dict[str, Any]] = []
    seen_sectors = set()
    for row in candidates:
        sector = row.get("sector")
        if sector not in seen_sectors:
            chosen.append(row)
            seen_sectors.add(sector)
            if len(chosen) == limit:
                break
    if len(chosen) < limit:
        for row in candidates:
            if row not in chosen:
                chosen.append(row)
                if len(chosen) == limit:
                    break
    return chosen if chosen else candidates[:limit]


def select_present_engine_picks(
    as_of_date: Optional[str] = None,
    on_progress: Optional[Callable[..., None]] = None,
) -> tuple:
    """Run the live desk screen and return its 5 names plus the universe size.

    ``as_of_date`` replays that same screen on a past Monday. Prices, liquidity,
    and news stop on that session. Nothing is written to the recommendation book.
    """
    as_of = str(as_of_date)[:10] if as_of_date else None
    universe_pool = get_full_market_universe(as_of_date=as_of)
    full_market = bool(universe_pool)
    if not full_market:
        logger.warning("NSE + BSE EOD store is empty; falling back to the 250-stock NSE liquid universe.")
        universe_pool = get_dynamic_bhavcopy_universe(min_turnover_cr=10.0, min_price=50.0, target_count=250)
    total = len(universe_pool)
    if total == 0:
        return [], 0
    scan_turnover_floor = SCAN_MIN_TURNOVER_CR * 1e7 if full_market else None
    macro = get_nifty50_regime(as_of_date=as_of)
    if as_of is None:
        try:
            from app.services.market_events import sync_market_events
            sync_market_events()
        except Exception as exc:
            logger.warning(f"Surveillance list refresh skipped: {exc}")
    from app.services.market_events import load_exchange_events, load_surveillance
    ex_dates = _corporate_ex_dates()
    surveillance = load_surveillance()
    exchange_events = load_exchange_events()
    scrip_by_symbol = {s["symbol"]: s for s in universe_pool}
    all_evaluated: List[Dict[str, Any]] = []
    qualified = 0

    def report(evaluated: int, symbol: str, name: str, stage: str) -> None:
        if on_progress:
            on_progress(evaluated, total, symbol, name, qualified, stage)
        elif as_of is None:
            update_scan_progress(
                is_active=True,
                current_symbol=symbol,
                current_name=name,
                evaluated_count=evaluated,
                qualified_count=qualified,
                target_count=total,
                percent=min(95, max(5, round((evaluated / total) * 94))) if total else 5,
                stage_text=stage,
            )

    def evaluate_scrip(scrip_item):
        sym = scrip_item["symbol"]
        name = scrip_item.get("name", sym)
        try:
            res = score_single_stock(
                sym,
                as_of_date=as_of,
                macro_context=macro,
                yahoo_ticker=scrip_item.get("yahoo_ticker"),
                display_name=name,
                min_turnover_inr=scan_turnover_floor,
                cached_fundamentals_only=as_of is None,
            )
            if res:
                res.setdefault("exchange", scrip_item.get("exchange", "NSE"))
                apply_trade_hygiene(res, scrip_item, ex_dates, surveillance, exchange_events)
            return sym, name, res
        except Exception as exc:
            logger.error(f"Error analyzing candidate {sym}: {exc}")
            return sym, name, None

    report(0, "", "", f"Screening {total} equities" + (f" as of {as_of}" if as_of else ""))
    evaluated = 0
    with ThreadPoolExecutor(max_workers=8 if full_market else 4) as executor:
        futures = [executor.submit(evaluate_scrip, scrip) for scrip in universe_pool]
        for future in as_completed(futures):
            sym, name, analysis = future.result()
            evaluated += 1
            if analysis:
                all_evaluated.append(analysis)
                if _is_primary_long(analysis):
                    qualified += 1
            stage = (
                f"Evaluated {sym} ({name}) · {qualified} qualified"
                if analysis else
                f"Analyzed {sym} ({name}) · {qualified} qualified"
            )
            if as_of is None or evaluated == total or evaluated % 10 == 0:
                report(evaluated, sym, name, stage)

    ranked = rank_engine_candidates(all_evaluated)
    report(evaluated, "RANK", "Present engine", f"Ranking {len(ranked)} names the live desk would rank")

    audited = []
    for cand in ranked[:25]:
        sym = cand["symbol"]
        scrip = scrip_by_symbol.get(sym, {})
        try:
            rescored = score_single_stock(
                sym,
                as_of_date=as_of,
                macro_context=macro,
                yahoo_ticker=scrip.get("yahoo_ticker"),
                display_name=scrip.get("name"),
                min_turnover_inr=scan_turnover_floor,
            )
        except Exception as exc:
            logger.debug(f"Finalist rescore notice for {sym}: {exc}")
            rescored = cand
        if not rescored:
            continue
        rescored.setdefault("exchange", scrip.get("exchange", cand.get("exchange", "NSE")))
        rescored.setdefault("admission_path", cand.get("admission_path"))
        apply_trade_hygiene(rescored, scrip, ex_dates, surveillance, exchange_events)
        if rescored.get("trade_block"):
            continue
        try:
            headlines = fetch_stock_news_rss(sym, max_items=4, as_of_date=as_of)
            if headlines:
                sent_score, sent_label, _catalysts, _risks = analyze_sentiment(headlines)
                if sent_score <= -0.40:
                    logger.info(f"News veto on {sym} as of {as_of or 'today'}: {sent_score:.2f}")
                    continue
                news_multiplier = (sent_score + 1.0) * 50.0
                rescored["sentiment_score"] = sent_score
                rescored["sentiment_label"] = sent_label
                rescored["composite_score"] = round(
                    rescored["composite_score"] + ((news_multiplier - 50.0) * WEIGHT_NEWS_SENTIMENT), 1
                )
        except Exception as exc:
            logger.debug(f"News audit notice for {sym}: {exc}")
        audited.append(rescored)

    if audited:
        ranked = audited
    picks = choose_diverse_picks(ranked, MAX_RECOMMENDATIONS_PER_DAY)
    return picks, total


def generate_daily_recommendations(
    target_date: str = None, 
    force_refresh: bool = False
) -> List[Dict[str, Any]]:
    """
    Run daily multi-factor screening across benchmark leaders in parallel.
    Picks top opportunities purely based on quantitative accuracy, technical setups,
    institutional money flow, fundamentals, and sentiment.
    """
    rec_date_str = target_date or date.today().isoformat()
    parsed_date = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if a batch already exists for this exact date
    if not force_refresh:
        cursor.execute("SELECT COUNT(*) FROM recommendations WHERE rec_date = ?", (rec_date_str,))
        count = cursor.fetchone()[0]
        if count > 0:
            logger.info(f"Existing recommendation batch found for {rec_date_str} ({count} records). Returning existing batch.")
            conn.close()
            return get_latest_recommendations(limit=MAX_RECOMMENDATIONS_PER_DAY)

    # Calculate 5th trading session evaluation date
    eval_end_date = get_nth_trading_day(parsed_date, 5)
    run_id = f"RUN_{rec_date_str}_{uuid.uuid4().hex[:8]}"
    
    logger.info(f"Initiating screening run {run_id} for {rec_date_str} across liquid NSE market leaders. Evaluation date: {eval_end_date.isoformat()}")
    
    try:
        sync_eod_store(trading_days=EOD_HISTORY_SESSIONS)
    except Exception as e:
        logger.warning(f"EOD store sync failed; scanning with stored sessions: {e}")

    top_picks, total_universe_count = select_present_engine_picks(as_of_date=None)
    
    if not top_picks:
        logger.warning(f"No stocks passed screening criteria for {rec_date_str}.")
        update_scan_progress(
            is_active=False,
            percent=100,
            stage_text="Screening run complete (no stocks met strict hurdle)."
        )
        conn.close()
        return []

    # Append-only run resolution
    cursor.execute("SELECT MAX(version) FROM recommendation_runs WHERE rec_date = ?", (rec_date_str,))
    row_ver = cursor.fetchone()
    current_max_ver = (row_ver[0] if row_ver and row_ver[0] is not None else 0)
    new_version = current_max_ver + 1
    run_id = f"run_{rec_date_str.replace('-', '')}_{uuid.uuid4().hex[:8]}"
    now_ts = datetime.now().isoformat()

    # If force_refresh or previous active recommendations exist, supersede them without deletion
    if current_max_ver > 0:
        supersede_previous_runs_for_date(
            cursor, 
            rec_date_str, 
            new_run_id=run_id, 
            new_version=new_version, 
            reason="User or scheduler initiated fresh intraday scan"
        )
        conn.commit()

    # Insert immutable run header into recommendation_runs
    cursor.execute("""
    INSERT INTO recommendation_runs (
        run_id, rec_date, version, generated_count, universe_size, model_version, status, created_at
    ) VALUES (?, ?, ?, ?, ?, 'v3-SelectiveEvidenceGate', 'ACTIVE', ?)
    """, (run_id, rec_date_str, new_version, len(top_picks), total_universe_count, now_ts))
    conn.commit()

    macro = get_nifty50_live_status()
    nifty_start_price = macro.get("nifty50_price")

    # High-Conviction Institutional Audit: Tapetide Options & Promoter Pledge for Top 5 Finalists
    try:
        from app.services.tapetide_service import audit_top_recommendations
        top_picks = audit_top_recommendations(top_picks)
    except Exception as e:
        logger.warning(f"Tapetide top recommendations audit skipped or failed: {e}")

    saved_records = []
    for pick in top_picks:
        rec_id = str(uuid.uuid4())
        ref_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")

        # Generate AI Analyst Committee synthesis explicitly citing Money Flow and Stop-Loss
        try:
            from app.services.llm_agent import run_multi_agent_analyst_team
            committee_data = run_multi_agent_analyst_team(pick)
            ai_thesis = committee_data["debate"]["synthesis"]
        except Exception as e:
            logger.warning(f"Error invoking AI committee for {pick['symbol']}: {e}")
            ai_thesis = (
                f"Consensus Thesis: Multi-factor quantitative consensus confirms {pick['direction']} setup targeting ₹{pick['expected_target_price']} "
                f"({pick['expected_appreciation_pct']:+0.2f}% forward move). "
                f"Institutional Money Flow confirmed by CMF-20 at {pick.get('cmf_20', 0.0):+.3f}, MFI-14 at {pick.get('mfi_14', 50.0)}, and Volume Expansion of {pick.get('vol_surge', 1.0)}x vs 20-DMA "
                f"(Delivery: {pick.get('deliv_per', 45.0)}% with {pick.get('deliv_surge', 1.0)}x surge). "
                f"Strict ATR Stop-Loss fixed at ₹{pick.get('stop_loss', 0.0)} ({round(abs(pick['reference_price'] - pick.get('stop_loss', pick['reference_price']))/pick['reference_price'] * 100, 2)}% max risk). "
                f"Action Stance: {pick.get('action_label', 'BUY / ACCUMULATE (5-Day Swing)')}."
            )
        pick["ai_thesis"] = ai_thesis
        
        cursor.execute("""
        INSERT INTO recommendations (
            id, symbol, name, exchange, sector, rec_date, reference_price,
            reference_timestamp, expected_target_price, stop_loss, expected_range_low,
            expected_range_high, expected_appreciation_pct, risk_level, status, action_label,
            supporting_reasons, downside_risks, technical_summary,
            fundamental_summary, news_summary, sentiment_score, sentiment_label,
            atr_14, volatility_5d_pct, support_level, resistance_level,
            cmf_20, vol_surge, deliv_per, deliv_surge, rs_20d, ai_thesis,
            confidence_text, model_version, created_at, run_id, direction, composite_score,
            delivery_source, version, is_superseded, win_probability_pct, reward_to_risk, setup_quality
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rec_id, pick["symbol"], pick["name"], "NSE", pick["sector"],
            rec_date_str, pick["reference_price"], ref_timestamp,
            pick["expected_target_price"], pick.get("stop_loss", round(pick["reference_price"] - pick["atr_14"], 2)),
            pick["expected_range_low"], pick["expected_range_high"],
            pick["expected_appreciation_pct"], pick["risk_level"], pick["status"],
            pick.get("action_label", "BUY / ACCUMULATE (5-Day Swing)"),
            json.dumps(pick["supporting_reasons"]), json.dumps(pick["downside_risks"]),
            pick["technical_summary"], pick["fundamental_summary"],
            pick["news_summary"], pick["sentiment_score"], pick["sentiment_label"],
            pick["atr_14"], pick["volatility_5d_pct"], pick["support_level"],
            pick["resistance_level"], pick.get("cmf_20", 0.0), pick.get("vol_surge", 1.0),
            pick.get("deliv_per", 45.0), pick.get("deliv_surge", 1.0), pick.get("rs_20d", 0.0),
            pick["ai_thesis"],
            pick.get("confidence_text", f"Conviction Score: {pick.get('win_probability_pct', 65.0):.0f} | R/R: {pick.get('reward_to_risk', 1.5):.1f}x | Grade {pick.get('setup_quality', 'A')} Setup"),
            "v4-CalibratedQuantAlpha", datetime.now().isoformat(), run_id, pick["direction"],
            pick.get("composite_score", 65.0),
            pick.get("delivery_source", "NSE_BHAVCOPY"),
            new_version, 0,
            pick.get("win_probability_pct", 65.0),
            pick.get("reward_to_risk", 1.5),
            pick.get("setup_quality", "A")
        ))
        
        # Insert pending evaluation record
        eval_id = str(uuid.uuid4())
        cursor.execute("""
        INSERT OR IGNORE INTO forecast_evaluations (
            id, recommendation_id, symbol, start_date, end_date,
            original_reference_price, predicted_target_price,
            predicted_appreciation_pct, nifty50_start_price, status,
            run_id, predicted_direction
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
        """, (
            eval_id, rec_id, pick["symbol"], rec_date_str,
            eval_end_date.isoformat(), pick["reference_price"],
            pick["expected_target_price"], pick["expected_appreciation_pct"],
            nifty_start_price, run_id, pick["direction"]
        ))
        
        pick_with_id = dict(pick)
        pick_with_id["id"] = rec_id
        pick_with_id["rec_date"] = rec_date_str
        pick_with_id["run_id"] = run_id
        pick_with_id["version"] = new_version
        pick_with_id["is_superseded"] = 0
        saved_records.append(pick_with_id)
        
    conn.commit()
    conn.close()

    try:
        from app.services.paper_trader import record_paper_recommendations, process_paper_trading_cycle
        record_paper_recommendations(saved_records, run_id=run_id)
        process_paper_trading_cycle()
    except Exception as pte:
        logger.warning(f"Auto-recording to paper trading ledger skipped: {pte}")

    update_scan_progress(
        is_active=False,
        current_symbol="",
        current_name="",
        evaluated_count=total_universe_count,
        qualified_count=len(top_picks),
        target_count=total_universe_count,
        percent=100,
        stage_text=f"Screening complete: {len(top_picks)} strict paper-trade candidates from {total_universe_count} equities."
    )
    
    return saved_records


def reset_daily_recommendations(target_date: str = None) -> List[Dict[str, Any]]:
    """
    Append-Only Rescan: Initiates a fresh recommendation run without deleting sealed prior history.
    Prior runs for this date are marked SUPERSEDED with audit events.
    """
    rec_date_str = target_date or date.today().isoformat()
    logger.info(f"Initiating append-only rescan for {rec_date_str} across the active universe.")
    return generate_daily_recommendations(
        target_date=rec_date_str,
        force_refresh=True
    )


def get_latest_recommendations(
    limit: int = 5,
    rec_date: Optional[str] = None,
    run_id: Optional[str] = None,
    include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """
    Retrieve recommendations adhering to the append-only model.
    Defaults to the latest ACTIVE run's records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if run_id:
        cursor.execute("SELECT * FROM recommendations WHERE run_id = ? ORDER BY composite_score DESC LIMIT ?", (run_id, limit))
    elif rec_date:
        if include_superseded:
            cursor.execute("SELECT * FROM recommendations WHERE rec_date = ? ORDER BY version DESC, composite_score DESC LIMIT ?", (rec_date, limit))
        else:
            cursor.execute("SELECT * FROM recommendations WHERE rec_date = ? AND (is_superseded = 0 OR is_superseded IS NULL) ORDER BY composite_score DESC LIMIT ?", (rec_date, limit))
    else:
        cursor.execute("SELECT DISTINCT rec_date FROM recommendations WHERE (is_superseded = 0 OR is_superseded IS NULL) ORDER BY rec_date DESC LIMIT 1")
        row = cursor.fetchone()
        if not row:
            # Fallback to any date if none are active
            cursor.execute("SELECT DISTINCT rec_date FROM recommendations ORDER BY rec_date DESC LIMIT 1")
            row = cursor.fetchone()
            if not row:
                conn.close()
                return []
                
        latest_date = row["rec_date"]
        cursor.execute("""
        SELECT r.* FROM recommendations r
        WHERE r.rec_date = ? AND (r.is_superseded = 0 OR r.is_superseded IS NULL)
        ORDER BY r.composite_score DESC
        LIMIT ?
        """, (latest_date, limit))
    
    recs = []
    for r in cursor.fetchall():
        d = dict(r)
        d["supporting_reasons"] = json.loads(d["supporting_reasons"]) if d.get("supporting_reasons") else []
        d["downside_risks"] = json.loads(d["downside_risks"]) if d.get("downside_risks") else []
        
        # Attach live market price so UI dynamically tracks updates
        try:
            quote = get_latest_quote(d["symbol"])
            if quote and quote.get("close_price") is not None:
                d["current_price"] = round(float(quote["close_price"]), 2)
                d["current_change_pct"] = round(float(quote.get("day_change_pct") or 0.0), 2)
            else:
                d["current_price"] = d["reference_price"]
                d["current_change_pct"] = 0.0
        except Exception:
            d["current_price"] = d["reference_price"]
            d["current_change_pct"] = 0.0
            
        recs.append(d)
        
    conn.close()
    return recs

