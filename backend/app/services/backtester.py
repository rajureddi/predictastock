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
from datetime import datetime, date, time as dt_time
from typing import Dict, Any, List, Optional
from zoneinfo import ZoneInfo
import sqlite3
import logging
import yfinance as yf
import pandas as pd

from app.database import get_db_connection
from app.services.market_data import format_ticker_nse, get_stock_history, get_latest_quote

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
# NSE closes at 15:30 IST and the bhavcopy posts afterwards. A Day-5 close is not
# final before this time, so a same-day forecast is never settled earlier.
SETTLEMENT_READY_TIME_IST = dt_time(16, 0)

# Rows a scorecard may count: a real Day-5 close, from a run that was not superseded.
SETTLED_ROW_SQL = (
    "fe.status = 'COMPLETED' AND fe.actual_end_price IS NOT NULL "
    "AND (r.is_superseded = 0 OR r.is_superseded IS NULL)"
)


def is_session_settled(end_date_str: str, now: Optional[datetime] = None) -> bool:
    """True once the end_date session has closed and its bhavcopy can exist."""
    now_ist = (now or datetime.now(IST)).astimezone(IST)
    end_day = datetime.strptime(str(end_date_str)[:10], "%Y-%m-%d").date()
    if end_day < now_ist.date():
        return True
    if end_day == now_ist.date():
        return now_ist.time() >= SETTLEMENT_READY_TIME_IST
    return False


def _local_session_rows(symbol: str, start_exclusive: str, end_inclusive: str) -> List[Dict[str, Any]]:
    """Exchange bhavcopy bars from the local EOD store, NSE preferred over BSE."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT trading_date, open, high, low, close, nifty50_close, exchange
            FROM historical_market_bars
            WHERE symbol = ? AND trading_date > ? AND trading_date <= ?
            ORDER BY trading_date, CASE exchange WHEN 'NSE' THEN 0 ELSE 1 END
            """,
            (symbol, start_exclusive, end_inclusive),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        conn.close()
    by_date: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        by_date.setdefault(row["trading_date"], dict(row))
    return [by_date[key] for key in sorted(by_date)]


def get_historical_session_close(symbol: str, target_date_str: str) -> Optional[float]:
    """
    Closing price of the exact target_date session. None if that session is not on record.

    A close from an earlier session is never returned: settling a Day-5 forecast
    on a Day-4 print is a silent wrong answer, not a fallback.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    target = str(target_date_str)[:10]
    local = _local_session_rows(clean_sym, _day_before(target), target)
    for row in local:
        if row["trading_date"] == target and row["close"] and float(row["close"]) > 0:
            return round(float(row["close"]), 2)

    ticker_str = format_ticker_nse(clean_sym)
    try:
        target_dt = datetime.strptime(target, "%Y-%m-%d").date()
        hist = yf.Ticker(ticker_str).history(
            start=(target_dt - pd.Timedelta(days=7)).isoformat(),
            end=(target_dt + pd.Timedelta(days=2)).isoformat(),
        )
        if hist.empty:
            return None
        exact = hist[hist.index.strftime("%Y-%m-%d") == target]
        if exact.empty:
            return None
        return round(float(exact["Close"].iloc[-1]), 2)
    except Exception as e:
        logger.warning(f"Could not retrieve historical close for {symbol} on {target}: {e}")
        return None


def _day_before(target: str) -> str:
    return (datetime.strptime(target, "%Y-%m-%d").date() - pd.Timedelta(days=1)).isoformat()


def get_historical_nifty_close(target_date_str: str) -> Optional[float]:
    """Nifty 50 close on the exact target_date session. None if it is not on record."""
    target = str(target_date_str)[:10]
    conn = get_db_connection()
    try:
        row = conn.execute(
            "SELECT MAX(nifty50_close) AS close FROM historical_market_bars WHERE trading_date = ? AND nifty50_close > 0",
            (target,),
        ).fetchone()
        if row and row["close"]:
            return round(float(row["close"]), 2)
    except sqlite3.Error:
        pass
    finally:
        conn.close()
    try:
        target_dt = datetime.strptime(target, "%Y-%m-%d").date()
        hist = yf.Ticker("^NSEI").history(
            start=(target_dt - pd.Timedelta(days=7)).isoformat(),
            end=(target_dt + pd.Timedelta(days=2)).isoformat(),
        )
        if hist.empty:
            return None
        exact = hist[hist.index.strftime("%Y-%m-%d") == target]
        if exact.empty:
            return None
        return round(float(exact["Close"].iloc[-1]), 2)
    except Exception as e:
        logger.warning(f"Could not retrieve historical Nifty close on {target}: {e}")
        return None


def classify_barrier_path(
    bars: List[Dict[str, Any]],
    stop_loss: Optional[float],
    target_price: Optional[float],
) -> Dict[str, Any]:
    """Walk the forward sessions. Stop and target on the same bar count as the stop."""
    if not bars:
        return {"barrier_outcome": None, "actual_peak_price": None, "actual_low_price": None}
    highs = [float(b["high"]) for b in bars if b.get("high")]
    lows = [float(b["low"]) for b in bars if b.get("low")]
    outcome = "HORIZON_CLOSE"
    stop = float(stop_loss or 0.0)
    target = float(target_price or 0.0)
    for bar in bars:
        hit_stop = stop > 0 and float(bar["low"]) <= stop
        hit_target = target > 0 and float(bar["high"]) >= target
        if hit_stop:
            outcome = "STOP_HIT"
            break
        if hit_target:
            outcome = "TARGET_HIT"
            break
    return {
        "barrier_outcome": outcome,
        "actual_peak_price": round(max(highs), 2) if highs else None,
        "actual_low_price": round(min(lows), 2) if lows else None,
    }


def evaluate_pending_forecasts(now: Optional[datetime] = None) -> int:
    """
    Settle pending 5-day forecasts whose end_date session has closed.

    The Day-5 close must come from the exact end_date session; a missing print
    leaves the row PENDING. Same-day rows wait until 16:00 IST.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    today_str = (now or datetime.now(IST)).astimezone(IST).date().isoformat()
    cursor.execute("""
    SELECT fe.*, r.symbol as rec_symbol, r.direction as rec_direction,
           r.stop_loss as rec_stop_loss, r.expected_target_price as rec_target_price,
           pt.price as user_buy_price
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
        if not is_session_settled(end_date, now):
            continue
        
        # 1. Fetch exact historical close on end_date
        actual_close = get_historical_session_close(symbol, end_date)
        if actual_close is None or actual_close <= 0:
            logger.info(f"Historical endpoint close unavailable for {symbol} on {end_date}; keeping PENDING.")
            continue

        path = classify_barrier_path(
            _local_session_rows(symbol, item["start_date"], end_date),
            item.get("rec_stop_loss"),
            item.get("rec_target_price") or item.get("predicted_target_price"),
        )
            
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
            barrier_outcome = ?,
            actual_peak_price = ?,
            actual_low_price = ?,
            status = 'COMPLETED',
            evaluated_at = ?
        WHERE id = ?
        """, (
            actual_close, actual_return_pct, forecast_error_pct,
            direction_correct, nifty_end, nifty_return_pct,
            alpha_pct, user_buy, user_return,
            path["barrier_outcome"], path["actual_peak_price"], path["actual_low_price"],
            datetime.now().isoformat(),
            item["id"]
        ))
        completed_count += 1
        
    conn.commit()
    conn.close()
    return completed_count


def repair_corrupted_evaluations() -> int:
    """
    Resets any evaluation prematurely marked COMPLETED with a NULL actual_end_price back to PENDING.
    Returns the count of repaired rows.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE forecast_evaluations
    SET status = 'PENDING',
        actual_end_price = NULL,
        actual_appreciation_pct = NULL,
        forecast_error_pct = NULL,
        direction_correct = NULL,
        evaluated_at = NULL,
        barrier_outcome = NULL
    WHERE status = 'COMPLETED' AND actual_end_price IS NULL
    """)
    repaired = cursor.rowcount
    conn.commit()
    conn.close()
    if repaired > 0:
        logger.info(f"Repaired {repaired} prematurely completed forecast evaluations; reset to PENDING.")
    return repaired


def get_forecast_scorecard() -> Dict[str, Any]:
    """
    Computes overall accuracy scorecard comparing completed predictions against the Nifty 50 baseline.
    Discloses sample size, pending evaluations, and limitations honestly.
    Only counts settled records with verified end prices from active (non-superseded) runs.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT COUNT(*) 
    FROM forecast_evaluations fe
    LEFT JOIN recommendations r ON fe.recommendation_id = r.id
    WHERE fe.status = 'PENDING' AND (r.is_superseded = 0 OR r.is_superseded IS NULL)
    """)
    pending_count = cursor.fetchone()[0]
    
    cursor.execute(f"""
    SELECT fe.*, r.composite_score, r.is_superseded
    FROM forecast_evaluations fe
    LEFT JOIN recommendations r ON fe.recommendation_id = r.id
    WHERE {SETTLED_ROW_SQL}
    ORDER BY fe.evaluated_at DESC
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
