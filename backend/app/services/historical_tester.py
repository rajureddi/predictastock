"""
PredictaStock Historical Prediction Reality Check & Backtest Service
Allows users to evaluate what the prediction engine forecast on past dates,
then compares those historical predictions side-by-side with actual subsequent market outcomes.
Guarantees point-in-time integrity (no future data leakage into predictions).
"""
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.database import get_db_connection
from app.data.nse_calendar import is_trading_day, get_nth_trading_day
from app.data.nifty_constituents import NIFTY_UNIVERSE, get_dynamic_bhavcopy_universe
from app.services.market_data import get_stock_history, format_ticker_nse
from app.services.prediction_engine import score_single_stock

logger = logging.getLogger(__name__)


def get_available_test_dates() -> Dict[str, Any]:
    """
    Returns preset past dates (1 week ago, 2 weeks ago, etc.)
    and all past dates already recorded in the SQLite database.
    """
    today = date.today()
    presets = []

    # Calculate trading day offsets
    for label, days_back in [("1 Week Ago", 7), ("2 Weeks Ago", 14), ("3 Weeks Ago", 21), ("1 Month Ago", 30)]:
        target_d = today - timedelta(days=days_back)
        # Find nearest prior trading day
        while not is_trading_day(target_d):
            target_d -= timedelta(days=1)
        presets.append({
            "label": label,
            "date": target_d.isoformat(),
            "formatted": target_d.strftime("%d-%b-%Y")
        })

    # Query distinct dates with recorded runs in SQLite
    recorded_dates = []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT rec_date, COUNT(*) as count 
            FROM recommendations 
            WHERE (is_superseded = 0 OR is_superseded IS NULL)
            GROUP BY rec_date 
            ORDER BY rec_date DESC
        """)
        for row in cursor.fetchall():
            d_str = row["rec_date"]
            if d_str < today.isoformat():
                try:
                    dt = datetime.strptime(d_str, "%Y-%m-%d").date()
                    recorded_dates.append({
                        "date": d_str,
                        "formatted": dt.strftime("%d-%b-%Y"),
                        "pick_count": row["count"],
                        "has_recorded_run": True
                    })
                except Exception:
                    pass
        conn.close()
    except Exception as e:
        logger.warning(f"Error querying recorded dates: {e}")

    return {
        "presets": presets,
        "recorded_dates": recorded_dates,
        "max_test_date": (today - timedelta(days=1)).isoformat()
    }


def run_historical_test(target_date: str, force_recalculate: bool = True) -> Dict[str, Any]:
    """
    Executes a point-in-time prediction for `target_date` and benchmarks it against
    the subsequent 5 trading sessions that actually took place in reality.
    """
    parsed_date = datetime.strptime(target_date, "%Y-%m-%d").date()
    today = date.today()

    if parsed_date >= today:
        raise ValueError("Historical test date must be in the past with subsequent sessions to evaluate.")

    # 1. Load predictions as-of target_date
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol, name, sector, reference_price, expected_target_price,
               stop_loss, expected_appreciation_pct, direction, action_label,
               composite_score, win_probability_pct, reward_to_risk, setup_quality
        FROM recommendations
        WHERE rec_date = ? AND (is_superseded = 0 OR is_superseded IS NULL)
        ORDER BY composite_score DESC
        LIMIT 5
    """, (target_date,))
    stored_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    predictions = []
    run_mode = "PRESENT_ENGINE_SIMULATION"
    run_mode_label = "Present Engine Point-in-Time Simulation"

    # Mode 1: Historical Archived Run (Stored in DB)
    if not force_recalculate:
        if stored_rows and all(float(r.get("expected_appreciation_pct", 0) or 0) > 0 for r in stored_rows):
            logger.info(f"Loaded {len(stored_rows)} existing archived predictions for {target_date}.")
            predictions = stored_rows
            run_mode = "ARCHIVED_DATABASE"
            run_mode_label = "Recorded Historical Run (Sealed Past Data)"
        else:
            return {
                "target_date": target_date,
                "formatted_date": parsed_date.strftime("%d-%b-%Y"),
                "run_mode": "ARCHIVED_DATABASE",
                "run_mode_label": "Recorded Historical Run (Sealed Past Data)",
                "error": f"No sealed historical runs found in database for {target_date}. Please choose a date from Recorded Past Runs, or switch to Present Engine mode to simulate predictions.",
                "total_picks": 0,
                "targets_hit_count": 0,
                "target_hit_rate_pct": 0.0,
                "profitable_count": 0,
                "win_rate_pct": 0.0,
                "avg_predicted_return_pct": 0.0,
                "avg_actual_end_return_pct": 0.0,
                "avg_actual_peak_return_pct": 0.0,
                "avg_win_probability_pct": 0.0,
                "market_regime": "UNKNOWN",
                "nifty_benchmark_return_pct": 0.0,
                "alpha_vs_nifty_pct": 0.0,
                "results": []
            }
    else:
        # Mode 2: Present Model Point-in-Time Simulation
        run_mode = "PRESENT_ENGINE_SIMULATION"
        run_mode_label = "Present Engine Point-in-Time Simulation"
        logger.info(f"Generating point-in-time calibrated predictions as of historical date {target_date}...")
        candidates = []
        universe = get_dynamic_bhavcopy_universe(min_turnover_cr=15.0, min_price=50.0, target_count=50)
        
        # Parallel scoring of candidate universe using ThreadPoolExecutor
        scored_results = []
        def _eval_stock(item):
            sym = item["symbol"]
            try:
                res = score_single_stock(sym, as_of_date=target_date)
                return res
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=8) as executor:
            future_to_sym = {executor.submit(_eval_stock, item): item["symbol"] for item in universe}
            for fut in as_completed(future_to_sym):
                res = fut.result()
                if res and isinstance(res, dict):
                    scored_results.append(res)

        # 1. First tier: strictly qualified setups (Bullish direction, min 1.2% appreciation, >= 58% win prob)
        for res in scored_results:
            if (
                res.get("direction") == "BULLISH"
                and float(res.get("expected_appreciation_pct", 0) or 0) >= 1.2
                and float(res.get("win_probability_pct", 0) or 0) >= 58.0
            ):
                candidates.append(res)

        # 2. Second tier: if strict count < 5, augment with highest win prob bullish setups
        if len(candidates) < 5:
            cand_syms = {c["symbol"] for c in candidates}
            remaining = [
                r for r in scored_results
                if r["symbol"] not in cand_syms
                and r.get("direction") == "BULLISH"
                and float(r.get("expected_appreciation_pct", 0) or 0) >= 1.0
            ]
            remaining.sort(
                key=lambda x: (
                    float(x.get("win_probability_pct", 50.0)) * 0.45
                    + float(x.get("composite_score", 50.0)) * 0.35
                    + float(x.get("rs_20d", 0.0)) * 0.20
                ),
                reverse=True
            )
            candidates.extend(remaining[:(5 - len(candidates))])

        candidates.sort(
            key=lambda x: (
                float(x.get("win_probability_pct", 50.0)) * 0.45
                + float(x.get("composite_score", 50.0)) * 0.35
                + float(x.get("rs_20d", 0.0)) * 0.20
            ),
            reverse=True
        )
        
        # Sector diversity
        seen_sectors = set()
        for c in candidates:
            sec = c.get("sector")
            if sec not in seen_sectors:
                predictions.append(c)
                seen_sectors.add(sec)
                if len(predictions) == 5:
                    break
        if len(predictions) < 5:
            for c in candidates:
                if c not in predictions:
                    predictions.append(c)
                    if len(predictions) == 5:
                        break

    if not predictions:
        return {
            "target_date": target_date,
            "error": f"No qualifying bullish setups found for historical date {target_date}.",
            "items": [],
            "summary": {}
        }

    # 2. Evaluate each prediction against the actual subsequent 5 sessions
    results = []
    total_predicted_return = 0.0
    total_actual_end_return = 0.0
    total_actual_peak_return = 0.0
    targets_hit_count = 0
    profitable_count = 0

    for pick in predictions:
        symbol = pick["symbol"]
        ref_price = float(pick["reference_price"])
        target_price = float(pick["expected_target_price"])
        stop_loss = float(pick.get("stop_loss", ref_price * 0.97))
        pred_gain_pct = float(pick.get("expected_appreciation_pct", 0.0))

        # Fetch actual historical market bars spanning the evaluation window
        df_hist = get_stock_history(symbol, period="6mo")
        future_bars = df_hist[df_hist.index > target_date].head(5) if not df_hist.empty else pd.DataFrame()

        day_by_day = []
        if not future_bars.empty:
            for dt, row in future_bars.iterrows():
                dt_clean = str(dt)[:10]
                c_price = round(float(row["Close"]), 2)
                h_price = round(float(row["High"]), 2)
                l_price = round(float(row["Low"]), 2)
                chg_from_ref = round(((c_price - ref_price) / ref_price) * 100.0, 2)
                day_by_day.append({
                    "day_number": len(day_by_day) + 1,
                    "date": dt_clean,
                    "open": round(float(row["Open"]), 2),
                    "high": h_price,
                    "low": l_price,
                    "close": c_price,
                    "change_pct": chg_from_ref
                })

            actual_peak_price = round(float(future_bars["High"].max()), 2)
            actual_trough_price = round(float(future_bars["Low"].min()), 2)
            actual_end_price = round(float(future_bars["Close"].iloc[-1]), 2)
            actual_end_return = round(((actual_end_price - ref_price) / ref_price) * 100.0, 2)
            actual_peak_return = round(((actual_peak_price - ref_price) / ref_price) * 100.0, 2)

            target_hit = bool(actual_peak_price >= target_price)
            stop_loss_hit = bool(actual_trough_price <= stop_loss)
            is_profitable = bool(actual_end_return > 0.0)

            if target_hit:
                status_badge = "TARGET_HIT"
                badge_label = "TARGET HIT"
                targets_hit_count += 1
            elif is_profitable:
                status_badge = "PROFITABLE"
                badge_label = "PROFITABLE"
            elif stop_loss_hit:
                status_badge = "STOPPED_OUT"
                badge_label = "STOP LOSS HIT"
            else:
                status_badge = "LOSS"
                badge_label = "NEGATIVE RETURN"

            if is_profitable:
                profitable_count += 1

            total_predicted_return += pred_gain_pct
            total_actual_end_return += actual_end_return
            total_actual_peak_return += actual_peak_return
        else:
            actual_peak_price = ref_price
            actual_trough_price = ref_price
            actual_end_price = ref_price
            actual_end_return = 0.0
            actual_peak_return = 0.0
            target_hit = False
            stop_loss_hit = False
            status_badge = "NO_DATA"
            badge_label = "PENDING SESSIONS"

        win_prob = float(pick.get("win_probability_pct", 65.0) or 65.0)
        r_r = float(pick.get("reward_to_risk", 1.5) or 1.5)
        setup_q = str(pick.get("setup_quality", "A") or "A")

        results.append({
            "symbol": symbol,
            "name": pick.get("name", symbol),
            "sector": pick.get("sector", "Other"),
            "target_date": target_date,
            "reference_price": ref_price,
            "predicted_target_price": target_price,
            "predicted_return_pct": pred_gain_pct,
            "stop_loss": stop_loss,
            "win_probability_pct": win_prob,
            "reward_to_risk": r_r,
            "setup_quality": setup_q,
            "actual_peak_price": actual_peak_price,
            "actual_peak_return_pct": actual_peak_return,
            "actual_end_price": actual_end_price,
            "actual_end_return_pct": actual_end_return,
            "target_hit": target_hit,
            "stop_loss_hit": stop_loss_hit,
            "status_badge": status_badge,
            "badge_label": badge_label,
            "sessions_evaluated": len(day_by_day),
            "day_by_day": day_by_day,
            "variance_pct": round(actual_end_return - pred_gain_pct, 2)
        })

    # 3. Benchmark against Nifty 50 over the same historical window
    nifty_return_pct = 0.0
    try:
        nifty = yf.Ticker("^NSEI")
        nifty_df = nifty.history(start=target_date, end=(parsed_date + timedelta(days=12)).isoformat())
        if not nifty_df.empty:
            future_nifty = nifty_df[nifty_df.index.strftime('%Y-%m-%d') > target_date].head(5)
            if not future_nifty.empty:
                n_start = float(nifty_df[nifty_df.index.strftime('%Y-%m-%d') <= target_date]['Close'].iloc[-1])
                n_end = float(future_nifty['Close'].iloc[-1])
                nifty_return_pct = round(((n_end - n_start) / n_start) * 100.0, 2)
    except Exception as ne:
        logger.warning(f"Could not calculate historical Nifty benchmark return: {ne}")

    count = len(results)
    avg_predicted = round(total_predicted_return / count, 2) if count > 0 else 0.0
    avg_actual_end = round(total_actual_end_return / count, 2) if count > 0 else 0.0
    avg_actual_peak = round(total_actual_peak_return / count, 2) if count > 0 else 0.0
    target_hit_rate = round((targets_hit_count / count) * 100.0, 1) if count > 0 else 0.0
    win_rate = round((profitable_count / count) * 100.0, 1) if count > 0 else 0.0
    alpha = round(avg_actual_end - nifty_return_pct, 2)
    avg_win_prob = round(sum(float(r.get("win_probability_pct", 65.0)) for r in results) / count, 1) if count > 0 else 60.0
    regime_type = "CORRECTION / DEFENSIVE" if nifty_return_pct < 0 else "BULLISH EXPANSION"

    return {
        "target_date": target_date,
        "formatted_date": parsed_date.strftime("%d-%b-%Y"),
        "run_mode": run_mode,
        "run_mode_label": run_mode_label,
        "total_picks": count,
        "targets_hit_count": targets_hit_count,
        "target_hit_rate_pct": target_hit_rate,
        "profitable_count": profitable_count,
        "win_rate_pct": win_rate,
        "avg_predicted_return_pct": avg_predicted,
        "avg_actual_end_return_pct": avg_actual_end,
        "avg_actual_peak_return_pct": avg_actual_peak,
        "avg_win_probability_pct": avg_win_prob,
        "market_regime": regime_type,
        "nifty_benchmark_return_pct": nifty_return_pct,
        "alpha_vs_nifty_pct": alpha,
        "results": results
    }
