"""
Forecast Evaluation & Historical Backtesting Engine
Evaluates completed 5-day forecasts against verified session close prices on the exact endpoint date
and compares against the Nifty 50 benchmark over the identical historical interval.
Phase 1 Integrity Rules:
- Evaluates against the actual historical session close on end_date, NEVER today's live price.
- Benchmark uses the exact historical Nifty 50 close on end_date.
- Evaluates directional correctness against predicted direction (Bullish, Bearish, Neutral).
- If endpoint price is missing or unverified, remains strictly PENDING.
- Transparently discloses sample size and statistical significance limitations.
"""
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import sqlite3
import logging
import yfinance as yf
import pandas as pd

from app.database import get_db_connection
from app.services.market_data import format_ticker_nse, get_stock_history, get_latest_quote

logger = logging.getLogger(__name__)


def get_historical_session_close(symbol: str, target_date_str: str) -> Optional[float]:
    """
    Retrieve the exact session closing price for a stock on or immediately preceding target_date.
    Returns None if no historical session data exists for that cutoff.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    ticker_str = format_ticker_nse(clean_sym)
    try:
        ticker = yf.Ticker(ticker_str)
        # Fetch 1 month window around target date
        target_dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        start_dt = target_dt - pd.Timedelta(days=7)
        end_dt = target_dt + pd.Timedelta(days=2)
        
        hist = ticker.history(start=start_dt.isoformat(), end=end_dt.isoformat())
        if hist.empty:
            return None
            
        # Filter for sessions up to and including target_date
        filtered = hist[hist.index.strftime('%Y-%m-%d') <= target_date_str]
        if filtered.empty:
            return None
            
        latest_valid_close = float(filtered['Close'].iloc[-1])
        return round(latest_valid_close, 2)
    except Exception as e:
        logger.warning(f"Could not retrieve historical close for {symbol} on {target_date_str}: {e}")
        return None


def get_historical_nifty_close(target_date_str: str) -> Optional[float]:
    """Retrieve historical Nifty 50 (^NSEI) close on target_date."""
    try:
        nifty = yf.Ticker("^NSEI")
        target_dt = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        start_dt = target_dt - pd.Timedelta(days=7)
        end_dt = target_dt + pd.Timedelta(days=2)
        
        hist = nifty.history(start=start_dt.isoformat(), end=end_dt.isoformat())
        if hist.empty:
            return None
            
        filtered = hist[hist.index.strftime('%Y-%m-%d') <= target_date_str]
        if filtered.empty:
            return None
            
        return round(float(filtered['Close'].iloc[-1]), 2)
    except Exception as e:
        logger.warning(f"Could not retrieve historical Nifty close on {target_date_str}: {e}")
        return None


def evaluate_pending_forecasts() -> int:
    """
    Check pending 5-day forecast records whose end_date has arrived.
    Fetches verified historical Day 5 closing prices and Nifty 50 close.
    Phase 1 Rule: If endpoint price is unavailable, leaves record as PENDING.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    today_str = date.today().isoformat()
    cursor.execute("""
    SELECT fe.*, r.symbol as rec_symbol, r.direction as rec_direction, pt.price as user_buy_price
    FROM forecast_evaluations fe
    JOIN recommendations r ON fe.recommendation_id = r.id
    LEFT JOIN portfolio_transactions pt ON pt.recommendation_id = r.id AND pt.transaction_type = 'BUY'
    WHERE fe.status = 'PENDING' AND fe.end_date <= ?
    """, (today_str,))
    
    pending_records = [dict(row) for row in cursor.fetchall()]
    completed_count = 0
    
    for item in pending_records:
        symbol = item["rec_symbol"]
        end_date = item["end_date"]
        
        # 1. Fetch exact historical close on end_date
        actual_close = get_historical_session_close(symbol, end_date)
        if actual_close is None or actual_close <= 0:
            logger.info(f"Historical endpoint close unavailable for {symbol} on {end_date}; keeping PENDING.")
            continue
            
        # 2. Fetch exact historical Nifty 50 close on end_date
        nifty_end = get_historical_nifty_close(end_date)
        nifty_start = item.get("nifty50_start_price")
        
        ref_price = item["original_reference_price"]
        pred_pct = item["predicted_appreciation_pct"]
        predicted_dir = item.get("predicted_direction") or item.get("rec_direction") or "BULLISH"
        
        # Calculate returns
        actual_return_pct = round(((actual_close - ref_price) / ref_price) * 100, 2)
        forecast_error_pct = round(abs(actual_return_pct - pred_pct), 2)
        
        # Directional correctness verified against predicted stance
        if predicted_dir == "BULLISH":
            direction_correct = 1 if actual_return_pct > 0 else 0
        elif predicted_dir == "BEARISH":
            direction_correct = 1 if actual_return_pct < 0 else 0
        else: # NEUTRAL
            direction_correct = 1 if abs(actual_return_pct) <= 2.0 else 0
            
        # Benchmark comparison
        if nifty_start and nifty_end and nifty_start > 0:
            nifty_return_pct = round(((nifty_end - nifty_start) / nifty_start) * 100, 2)
            alpha_pct = round(actual_return_pct - nifty_return_pct, 2)
        else:
            nifty_return_pct = None
            alpha_pct = None
            
        # Real user portfolio buy comparison if exists
        user_buy = item.get("user_buy_price")
        user_return = round(((actual_close - user_buy) / user_buy) * 100, 2) if user_buy else None
        
        cursor.execute("""
        UPDATE forecast_evaluations SET
            actual_end_price = ?,
            actual_appreciation_pct = ?,
            forecast_error_pct = ?,
            direction_correct = ?,
            nifty50_end_price = ?,
            nifty50_return_pct = ?,
            alpha_vs_nifty_pct = ?,
            user_actual_buy_price = ?,
            user_actual_return_pct = ?,
            status = 'COMPLETED',
            evaluated_at = ?
        WHERE id = ?
        """, (
            actual_close, actual_return_pct, forecast_error_pct,
            direction_correct, nifty_end, nifty_return_pct,
            alpha_pct, user_buy, user_return, datetime.now().isoformat(),
            item["id"]
        ))
        completed_count += 1
        
    conn.commit()
    conn.close()
    return completed_count


def get_forecast_scorecard() -> Dict[str, Any]:
    """
    Computes overall accuracy scorecard comparing completed predictions against the Nifty 50 baseline.
    Discloses sample size, pending evaluations, and limitations honestly.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM forecast_evaluations WHERE status = 'PENDING'")
    pending_count = cursor.fetchone()[0]
    
    cursor.execute("""
    SELECT * FROM forecast_evaluations 
    WHERE status = 'COMPLETED'
    ORDER BY evaluated_at DESC
    """)
    completed = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    total = len(completed)
    if total == 0:
        return {
            "total_completed_forecasts": 0,
            "pending_forecasts": pending_count,
            "sample_size": 0,
            "directional_accuracy_pct": 0.0,
            "avg_forecast_error_pct": 0.0,
            "avg_model_return_pct": 0.0,
            "avg_nifty_return_pct": 0.0,
            "avg_alpha_pct": 0.0,
            "downside_surprise_count": 0,
            "status_text": f"Evaluation Pending ({pending_count} forecasts awaiting Day-5 market session close)",
            "limitations_note": "No completed 5-day out-of-sample forecast cycles yet recorded.",
            "evaluations": []
        }
        
    correct_count = sum(1 for c in completed if c.get("direction_correct") == 1)
    accuracy_pct = round((correct_count / total) * 100, 1)
    avg_error = round(sum(c["forecast_error_pct"] for c in completed if c.get("forecast_error_pct") is not None) / total, 2)
    avg_return = round(sum(c["actual_appreciation_pct"] for c in completed if c.get("actual_appreciation_pct") is not None) / total, 2)
    
    valid_nifty = [c["nifty50_return_pct"] for c in completed if c.get("nifty50_return_pct") is not None]
    avg_nifty = round(sum(valid_nifty) / len(valid_nifty), 2) if valid_nifty else 0.0
    
    valid_alpha = [c["alpha_vs_nifty_pct"] for c in completed if c.get("alpha_vs_nifty_pct") is not None]
    avg_alpha = round(sum(valid_alpha) / len(valid_alpha), 2) if valid_alpha else 0.0
    
    downside_surprises = sum(1 for c in completed if c.get("actual_appreciation_pct") is not None and c["actual_appreciation_pct"] < -3.0)
    
    sample_significance = (
        "Statistically Insufficient (Sample < 30)" if total < 30
        else "Moderate Sample Size"
    )

    # Decorate top evaluations with current live price for dashboard view
    for item in completed[:30]:
        sym = item.get("symbol")
        if sym:
            quote = get_latest_quote(sym)
            item["current_price"] = (
                round(float(quote["close_price"]), 2)
                if (quote and quote.get("close_price") is not None)
                else (item.get("actual_end_price") or item.get("original_reference_price"))
            )
            item["current_change_pct"] = round(float(quote.get("day_change_pct") or 0.0), 2) if quote else 0.0

    return {
        "total_completed_forecasts": total,
        "pending_forecasts": pending_count,
        "sample_size": total,
        "sample_significance": sample_significance,
        "directional_accuracy_pct": accuracy_pct,
        "avg_forecast_error_pct": avg_error,
        "avg_model_return_pct": avg_return,
        "avg_nifty_return_pct": avg_nifty,
        "avg_alpha_pct": avg_alpha,
        "downside_surprise_count": downside_surprises,
        "status_text": f"Evaluated {total} Forecasts ({sample_significance})",
        "limitations_note": "Directional accuracy requires extensive out-of-sample history across market cycles before asserting statistical edge.",
        "evaluations": completed[:15]
    }


def delete_forecast_evaluation(eval_id: str) -> Dict[str, Any]:
    """Deletes an individual completed forecast evaluation record by ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol FROM forecast_evaluations WHERE id = ?", (eval_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return {"status": "NOT_FOUND", "deleted": False, "message": f"Evaluation {eval_id} not found."}

    sym = row["symbol"]
    cursor.execute("DELETE FROM forecast_evaluations WHERE id = ?", (eval_id,))
    conn.commit()
    conn.close()
    return {
        "status": "SUCCESS",
        "deleted": True,
        "deleted_id": eval_id,
        "symbol": sym,
        "message": f"Successfully deleted forecast evaluation for {sym}."
    }


def delete_forecast_evaluations_by_symbol(symbol: str) -> Dict[str, Any]:
    """Deletes all forecast evaluations for a specific symbol."""
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM forecast_evaluations WHERE symbol = ?", (clean_sym,))
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return {
        "status": "SUCCESS",
        "deleted": bool(deleted_count > 0),
        "deleted_count": deleted_count,
        "symbol": clean_sym,
        "message": f"Successfully deleted {deleted_count} forecast evaluation(s) for {clean_sym}."
    }
