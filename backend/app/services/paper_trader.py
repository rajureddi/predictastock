"""
Prospective Forward Paper-Trading Ledger Engine (PredictaStock)
Implements:
1. Cohort-based forward paper trading (immutable cohorts, model_version lock).
2. Prospective recording of live recommendations before market outcomes are known.
3. Realistic T+1 Open fills, gap/circuit rejections, and capacity constraints.
4. Strict path-dependent trade execution (Mode A bracket & Mode B partial profit) with 0.30% friction.
5. Append-only execution events log (SIGNAL_GENERATED, ORDER_FILLED, ORDER_REJECTED, STOP_TRIGGERED, TARGET_HIT, SETTLED_T5).
"""
import uuid
import json
import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple
import math

from app.database import get_db_connection
from app.services.historical_backtest import (
    evaluate_t1_open_entry, simulate_path_dependent_trade,
    TOTAL_ROUNDTRIP_FRICTION_PCT
)
from app.services.market_data import get_historical_market_bars

logger = logging.getLogger(__name__)

DEFAULT_COHORT_ID = "COHORT-2026-v2.3"
DEFAULT_MODEL_VERSION = "v2.3-HighAlphaQuant"
INITIAL_CAPITAL = 1000000.0 # ₹10,00,000 INR
MAX_CONCURRENT_POSITIONS = 5
MAX_ALLOCATION_PER_SLOT = 0.20 # 20% max per position


def get_or_create_active_cohort(
    cohort_id: str = DEFAULT_COHORT_ID,
    model_version: str = DEFAULT_MODEL_VERSION,
    initial_capital: float = INITIAL_CAPITAL
) -> Dict[str, Any]:
    """Retrieve or initialize the active forward paper-trading cohort."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM paper_trading_cohorts WHERE cohort_id = ?", (cohort_id,))
    row = cursor.fetchone()

    if row:
        cohort = dict(row)
        conn.close()
        return cohort

    now_iso = datetime.now().isoformat()
    today_str = date.today().isoformat()
    cursor.execute("""
    INSERT INTO paper_trading_cohorts (
        cohort_id, name, model_version, status, start_date,
        initial_capital, cash_balance, portfolio_equity, max_positions, created_at
    ) VALUES (?, ?, ?, 'ACTIVE', ?, ?, ?, ?, ?, ?)
    """, (
        cohort_id,
        f"Forward Alpha Cohort {model_version}",
        model_version,
        today_str,
        initial_capital,
        initial_capital,
        initial_capital,
        MAX_CONCURRENT_POSITIONS,
        now_iso
    ))
    conn.commit()
    cursor.execute("SELECT * FROM paper_trading_cohorts WHERE cohort_id = ?", (cohort_id,))
    cohort = dict(cursor.fetchone())
    conn.close()
    return cohort


def log_paper_execution_event(
    recommendation_id: str,
    event_type: str,
    event_price: Optional[float] = None,
    details: Optional[Dict[str, Any]] = None,
    conn = None,
    cursor = None
):
    """Append an immutable execution event into paper_execution_events."""
    owns_conn = False
    if conn is None:
        conn = get_db_connection()
        cursor = conn.cursor()
        owns_conn = True
    elif cursor is None:
        cursor = conn.cursor()

    event_id = str(uuid.uuid4())
    cursor.execute("""
    INSERT INTO paper_execution_events (
        id, recommendation_id, event_type, event_timestamp, event_price, details_json
    ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        event_id,
        recommendation_id,
        event_type,
        datetime.now().isoformat(),
        event_price,
        json.dumps(details or {})
    ))
    if owns_conn:
        conn.commit()
        conn.close()



def record_paper_recommendations(
    picks: List[Dict[str, Any]],
    cohort_id: str = DEFAULT_COHORT_ID,
    run_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Ingests live recommendations into the prospective paper-trading ledger before outcomes are known.
    Calculates initial integer share position sizing and registers PENDING_OPEN orders.
    """
    if not picks:
        return []

    cohort = get_or_create_active_cohort(cohort_id=cohort_id)
    conn = get_db_connection()
    cursor = conn.cursor()

    # Check active open positions count
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM paper_recommendations WHERE cohort_id = ? AND status = 'ACTIVE'",
        (cohort_id,)
    )
    active_count = cursor.fetchone()["cnt"]

    recorded = []
    now_iso = datetime.now().isoformat()

    for pick in picks:
        direction = pick.get("direction", "BULLISH").upper()
        # Cash equity: only long setups take trades
        if direction not in ("BULLISH", "BUY"):
            continue

        symbol = pick["symbol"]
        signal_date = pick.get("rec_date", date.today().isoformat())
        ref_price = float(pick.get("reference_price", 0.0))
        target_price = float(pick.get("expected_target_price", ref_price * 1.05))
        stop_loss = float(pick.get("stop_loss", ref_price * 0.97))
        score = float(pick.get("composite_score", 65.0))
        model_version = cohort["model_version"]

        if ref_price <= 0:
            continue

        # Prevent duplicate entries for the same symbol on the same signal date in this cohort
        cursor.execute("""
        SELECT id FROM paper_recommendations
        WHERE cohort_id = ? AND symbol = ? AND signal_date = ?
        """, (cohort_id, symbol, signal_date))
        existing = cursor.fetchone()
        if existing:
            continue

        # Position Sizing: 20% max slot allocation of portfolio equity
        portfolio_equity = float(cohort.get("portfolio_equity", INITIAL_CAPITAL))
        slot_capital = portfolio_equity * MAX_ALLOCATION_PER_SLOT
        qty = math.floor(slot_capital / ref_price)

        rec_id = pick.get("id", str(uuid.uuid4()))
        features = {
            "composite_score": score,
            "cmf_20": pick.get("cmf_20", 0.0),
            "deliv_per": pick.get("deliv_per", 0.0),
            "deliv_surge": pick.get("deliv_surge", 1.0),
            "delivery_source": pick.get("delivery_source", "NSE_BHAVCOPY"),
            "atr_14": pick.get("atr_14", 0.0),
            "volatility_5d_pct": pick.get("volatility_5d_pct", 3.0),
            "rs_20d": pick.get("rs_20d", 0.0),
            "nifty_status": pick.get("nifty_status", "ABOVE_SMA20")
        }

        cursor.execute("""
        INSERT INTO paper_recommendations (
            id, cohort_id, run_id, symbol, signal_date, signal_price,
            signal_direction, composite_score, model_version,
            planned_entry_price, planned_stop_loss, planned_target_price,
            features_json, position_qty, allocated_capital, status,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_OPEN', ?)
        """, (
            rec_id, cohort_id, run_id, symbol, signal_date, ref_price,
            direction, score, model_version,
            ref_price, stop_loss, target_price,
            json.dumps(features), qty, slot_capital,
            now_iso
        ))

        log_paper_execution_event(
            recommendation_id=rec_id,
            event_type="SIGNAL_GENERATED",
            event_price=ref_price,
            details={
                "symbol": symbol,
                "score": score,
                "planned_target": target_price,
                "planned_stop": stop_loss,
                "planned_qty": qty,
                "features": features
            },
            conn=conn,
            cursor=cursor
        )

        recorded.append({
            "id": rec_id,
            "symbol": symbol,
            "signal_date": signal_date,
            "signal_price": ref_price,
            "planned_target": target_price,
            "planned_stop": stop_loss,
            "position_qty": qty,
            "status": "PENDING_OPEN"
        })

    conn.commit()
    conn.close()
    return recorded


def process_paper_trading_cycle(cohort_id: str = DEFAULT_COHORT_ID) -> Dict[str, Any]:
    """
    Executes the prospective paper trading cycle:
    1. Evaluates PENDING_OPEN orders when T+1 market bar is available (checking gap & circuit filters).
    2. Evaluates ACTIVE orders across forward daily bars for Mode B path-dependent exits (stop, target, T+5).
    3. Updates cohort cash balances, total portfolio equity, and execution events.
    """
    cohort = get_or_create_active_cohort(cohort_id=cohort_id)
    conn = get_db_connection()
    cursor = conn.cursor()

    # Step 1: Process PENDING_OPEN orders
    cursor.execute("""
    SELECT * FROM paper_recommendations
    WHERE cohort_id = ? AND status = 'PENDING_OPEN'
    ORDER BY signal_date ASC
    """, (cohort_id,))
    pending_recs = [dict(r) for r in cursor.fetchall()]

    filled_count = 0
    rejected_count = 0

    for rec in pending_recs:
        rec_id = rec["id"]
        symbol = rec["symbol"]
        signal_date = rec["signal_date"]
        signal_price = float(rec["signal_price"])
        target_price = float(rec["planned_target_price"])
        stop_loss = float(rec["planned_stop_loss"])
        qty = int(rec["position_qty"])

        # Fetch forward bars after signal_date
        bars_df = get_historical_market_bars(symbol)
        if bars_df.empty:
            continue

        bars_df = bars_df.sort_index()
        future_bars = bars_df[bars_df.index > signal_date]
        if future_bars.empty:
            continue

        # Day T+1 bar
        t1_bar = future_bars.iloc[0]
        t1_date = str(future_bars.index[0])[:10]
        t1_open = float(t1_bar["Open"])
        t1_high = float(t1_bar["High"])
        t1_low = float(t1_bar["Low"])
        t1_close = float(t1_bar["Close"])

        # Evaluate T+1 Open entry
        is_valid_entry, rejection_reason = evaluate_t1_open_entry(
            entry_open=t1_open,
            entry_high=t1_high,
            entry_low=t1_low,
            entry_close=t1_close,
            prev_close_t0=signal_price,
            target_price=target_price,
            stop_loss=stop_loss
        )

        if not is_valid_entry:
            cursor.execute("""
            UPDATE paper_recommendations
            SET status = 'REJECTED', rejection_reason = ?
            WHERE id = ?
            """, (rejection_reason, rec_id))
            log_paper_execution_event(
                recommendation_id=rec_id,
                event_type="ORDER_REJECTED",
                event_price=t1_open,
                details={"reason": rejection_reason, "t1_open": t1_open, "signal_price": signal_price},
                conn=conn,
                cursor=cursor
            )
            rejected_count += 1
            continue

        # Check cohort capacity & cash availability
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM paper_recommendations WHERE cohort_id = ? AND status = 'ACTIVE'",
            (cohort_id,)
        )
        current_active = cursor.fetchone()["cnt"]
        if current_active >= MAX_CONCURRENT_POSITIONS:
            cursor.execute("""
            UPDATE paper_recommendations
            SET status = 'REJECTED', rejection_reason = 'REJECTED_PORTFOLIO_CAPACITY'
            WHERE id = ?
            """, (rec_id,))
            log_paper_execution_event(
                recommendation_id=rec_id,
                event_type="ORDER_REJECTED",
                event_price=t1_open,
                details={"reason": "REJECTED_PORTFOLIO_CAPACITY", "active_count": current_active},
                conn=conn,
                cursor=cursor
            )
            rejected_count += 1
            continue

        entry_cost = qty * t1_open * (1.0 + (TOTAL_ROUNDTRIP_FRICTION_PCT / 200.0))
        cursor.execute("SELECT cash_balance FROM paper_trading_cohorts WHERE cohort_id = ?", (cohort_id,))
        current_cash = float(cursor.fetchone()["cash_balance"])

        if current_cash < (qty * t1_open):
            # Try adjusted smaller quantity
            qty = math.floor(current_cash / t1_open)
            if qty <= 0:
                cursor.execute("""
                UPDATE paper_recommendations
                SET status = 'REJECTED', rejection_reason = 'REJECTED_INSUFFICIENT_CASH'
                WHERE id = ?
                """, (rec_id,))
                rejected_count += 1
                continue

        entry_notional = qty * t1_open
        entry_fee = entry_notional * (TOTAL_ROUNDTRIP_FRICTION_PCT / 200.0) # 0.15% half friction
        new_cash = current_cash - (entry_notional + entry_fee)

        cursor.execute("""
        UPDATE paper_trading_cohorts
        SET cash_balance = ?
        WHERE cohort_id = ?
        """, (new_cash, cohort_id))

        cursor.execute("""
        UPDATE paper_recommendations
        SET status = 'ACTIVE',
            entry_date = ?,
            entry_price = ?,
            position_qty = ?,
            allocated_capital = ?
        WHERE id = ?
        """, (t1_date, t1_open, qty, entry_notional, rec_id))

        log_paper_execution_event(
            recommendation_id=rec_id,
            event_type="ORDER_FILLED",
            event_price=t1_open,
            details={"entry_date": t1_date, "entry_price": t1_open, "qty": qty, "entry_fee": entry_fee},
            conn=conn,
            cursor=cursor
        )
        filled_count += 1

    conn.commit()

    # Step 2: Process ACTIVE orders for path-dependent exits
    cursor.execute("""
    SELECT * FROM paper_recommendations
    WHERE cohort_id = ? AND status = 'ACTIVE'
    ORDER BY entry_date ASC
    """, (cohort_id,))
    active_recs = [dict(r) for r in cursor.fetchall()]

    closed_count = 0
    for rec in active_recs:
        rec_id = rec["id"]
        symbol = rec["symbol"]
        entry_date = rec["entry_date"]
        entry_price = float(rec["entry_price"])
        target_price = float(rec["planned_target_price"])
        stop_loss = float(rec["planned_stop_loss"])
        qty = int(rec["position_qty"])
        features = json.loads(rec.get("features_json") or "{}")
        atr_14 = float(features.get("atr_14", entry_price * 0.02))

        bars_df = get_historical_market_bars(symbol)
        if bars_df.empty:
            continue

        bars_df = bars_df.sort_index()
        # Bars strictly on or after entry_date
        post_entry_bars = bars_df[bars_df.index >= entry_date]
        if len(post_entry_bars) < 1:
            continue

        # Simulate path-dependent exit
        sim_res = simulate_path_dependent_trade(
            future_bars=post_entry_bars.head(5),
            entry_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            atr_14=atr_14,
            mode="MODE_B"
        )

        exit_day_idx = sim_res.get("exit_day", 0)
        exit_reason = sim_res.get("exit_reason", "PENDING")
        exit_price = float(sim_res.get("exit_price", entry_price))

        # Check if trade has completed
        is_completed = False
        exit_date_str = None

        if exit_reason in ("TARGET_HIT", "STOP_LOSS", "GAP_STOP_LOSS"):
            if exit_day_idx < len(post_entry_bars):
                exit_date_str = str(post_entry_bars.index[exit_day_idx])[:10]
            else:
                exit_date_str = str(post_entry_bars.index[-1])[:10]
            is_completed = True
        elif len(post_entry_bars) >= 5: # T+5 session reached
            exit_reason = "T5_EXPIRY"
            exit_date_str = str(post_entry_bars.index[min(4, len(post_entry_bars)-1)])[:10]
            is_completed = True

        if is_completed and exit_date_str:
            gross_pnl = qty * (exit_price - entry_price)
            total_friction = (entry_price + exit_price) * qty * (TOTAL_ROUNDTRIP_FRICTION_PCT / 100.0) / 2.0
            net_pnl = round(gross_pnl - total_friction, 2)
            net_ret_pct = round((net_pnl / (qty * entry_price)) * 100.0, 2) if entry_price > 0 else 0.0

            cursor.execute("SELECT cash_balance FROM paper_trading_cohorts WHERE cohort_id = ?", (cohort_id,))
            current_cash = float(cursor.fetchone()["cash_balance"])
            net_cash_returned = (qty * exit_price) - (qty * exit_price * (TOTAL_ROUNDTRIP_FRICTION_PCT / 200.0))
            new_cash = current_cash + net_cash_returned

            cursor.execute("""
            UPDATE paper_trading_cohorts
            SET cash_balance = ?
            WHERE cohort_id = ?
            """, (new_cash, cohort_id))

            cursor.execute("""
            UPDATE paper_recommendations
            SET status = 'CLOSED',
                exit_date = ?,
                exit_price = ?,
                exit_reason = ?,
                gross_pnl = ?,
                net_pnl = ?,
                net_return_pct = ?
            WHERE id = ?
            """, (exit_date_str, exit_price, exit_reason, round(gross_pnl, 2), net_pnl, net_ret_pct, rec_id))

            event_type = "TARGET_HIT" if exit_reason == "TARGET_HIT" else ("STOP_TRIGGERED" if "STOP" in exit_reason else "SETTLED_T5")
            log_paper_execution_event(
                recommendation_id=rec_id,
                event_type=event_type,
                event_price=exit_price,
                details={
                    "exit_date": exit_date_str,
                    "exit_reason": exit_reason,
                    "net_pnl": net_pnl,
                    "net_return_pct": net_ret_pct,
                    "friction": round(total_friction, 2)
                },
                conn=conn,
                cursor=cursor
            )
            closed_count += 1

    # Step 3: Compute current portfolio equity = cash + mark-to-market active positions
    cursor.execute("SELECT cash_balance FROM paper_trading_cohorts WHERE cohort_id = ?", (cohort_id,))
    cash_bal = float(cursor.fetchone()["cash_balance"])

    cursor.execute("""
    SELECT symbol, position_qty, entry_price FROM paper_recommendations
    WHERE cohort_id = ? AND status = 'ACTIVE'
    """, (cohort_id,))
    remaining_active = cursor.fetchall()

    mtm_equity = cash_bal
    for act in remaining_active:
        sym = act["symbol"]
        pos_qty = int(act["position_qty"])
        entry_p = float(act["entry_price"])
        bars_df = get_historical_market_bars(sym)
        latest_p = float(bars_df.iloc[-1]["Close"]) if not bars_df.empty else entry_p
        mtm_equity += (pos_qty * latest_p)

    cursor.execute("""
    UPDATE paper_trading_cohorts
    SET portfolio_equity = ?
    WHERE cohort_id = ?
    """, (round(mtm_equity, 2), cohort_id))

    conn.commit()
    conn.close()

    return {
        "status": "SUCCESS",
        "cohort_id": cohort_id,
        "filled_orders": filled_count,
        "rejected_orders": rejected_count,
        "closed_trades": closed_count,
        "current_equity": round(mtm_equity, 2),
        "current_cash": round(cash_bal, 2)
    }


def get_paper_trading_summary(cohort_id: str = DEFAULT_COHORT_ID) -> Dict[str, Any]:
    """Retrieve statistical summary for the active forward paper-trading cohort."""
    cohort = get_or_create_active_cohort(cohort_id=cohort_id)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM paper_recommendations WHERE cohort_id = ?", (cohort_id,))
    all_recs = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_recs = len(all_recs)
    pending_count = sum(1 for r in all_recs if r["status"] == "PENDING_OPEN")
    active_count = sum(1 for r in all_recs if r["status"] == "ACTIVE")
    rejected_count = sum(1 for r in all_recs if r["status"] == "REJECTED")
    closed_recs = [r for r in all_recs if r["status"] == "CLOSED"]
    closed_count = len(closed_recs)

    winning_trades = [r for r in closed_recs if float(r.get("net_pnl", 0.0)) > 0]
    losing_trades = [r for r in closed_recs if float(r.get("net_pnl", 0.0)) < 0]

    win_rate = round((len(winning_trades) / closed_count * 100.0), 2) if closed_count > 0 else 0.0
    total_net_pnl = sum(float(r.get("net_pnl", 0.0)) for r in closed_recs)
    avg_net_return_pct = round(sum(float(r.get("net_return_pct", 0.0)) for r in closed_recs) / closed_count, 2) if closed_count > 0 else 0.0

    gross_gains = sum(float(r.get("net_pnl", 0.0)) for r in winning_trades)
    gross_losses = abs(sum(float(r.get("net_pnl", 0.0)) for r in losing_trades))
    profit_factor = round(gross_gains / gross_losses, 2) if gross_losses > 0 else (round(gross_gains, 2) if gross_gains > 0 else 1.0)

    initial_capital = float(cohort.get("initial_capital", INITIAL_CAPITAL))
    portfolio_equity = float(cohort.get("portfolio_equity", INITIAL_CAPITAL))
    portfolio_return_pct = round(((portfolio_equity - initial_capital) / initial_capital) * 100.0, 2)

    return {
        "cohort_id": cohort_id,
        "name": cohort.get("name"),
        "model_version": cohort.get("model_version"),
        "status": cohort.get("status"),
        "start_date": cohort.get("start_date"),
        "initial_capital": initial_capital,
        "cash_balance": round(float(cohort.get("cash_balance", INITIAL_CAPITAL)), 2),
        "portfolio_equity": portfolio_equity,
        "portfolio_return_pct": portfolio_return_pct,
        "total_recommendations": total_recs,
        "pending_count": pending_count,
        "active_count": active_count,
        "rejected_count": rejected_count,
        "closed_count": closed_count,
        "winning_trades": len(winning_trades),
        "losing_trades": len(losing_trades),
        "win_rate_pct": win_rate,
        "total_net_pnl_inr": round(total_net_pnl, 2),
        "avg_net_return_pct": avg_net_return_pct,
        "profit_factor": profit_factor,
        "friction_assumptions": f"{TOTAL_ROUNDTRIP_FRICTION_PCT:.2f}% roundtrip (0.25% statutory + 0.05% slippage)"
    }


def get_paper_trading_scorecard(cohort_id: str = DEFAULT_COHORT_ID) -> List[Dict[str, Any]]:
    """Retrieve line-item scorecard of all forward paper recommendations and their execution audits."""
    cohort = get_or_create_active_cohort(cohort_id=cohort_id)
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM paper_recommendations
    WHERE cohort_id = ?
    ORDER BY signal_date DESC, created_at DESC
    """, (cohort_id,))
    recs = [dict(r) for r in cursor.fetchall()]

    scorecard = []
    for r in recs:
        rec_id = r["id"]
        cursor.execute("""
        SELECT event_type, event_timestamp, event_price, details_json
        FROM paper_execution_events
        WHERE recommendation_id = ?
        ORDER BY event_timestamp ASC
        """, (rec_id,))
        events = [dict(ev) for ev in cursor.fetchall()]
        for ev in events:
            if ev.get("details_json"):
                try:
                    ev["details"] = json.loads(ev["details_json"])
                except Exception:
                    ev["details"] = {}

        # Determine audit verdict badge
        status = r["status"]
        exit_reason = r.get("exit_reason") or ""
        net_ret = float(r.get("net_return_pct", 0.0))

        if status == "REJECTED":
            audit_verdict = "REJECTED AT OPEN"
        elif status == "ACTIVE":
            audit_verdict = "ACTIVE IN FLIGHT"
        elif status == "PENDING_OPEN":
            audit_verdict = "PENDING T+1 OPEN"
        elif "TARGET" in exit_reason:
            audit_verdict = "TARGET HIT"
        elif "STOP" in exit_reason:
            audit_verdict = "STOPPED OUT"
        elif net_ret > 0:
            audit_verdict = "DIRECTIONAL WIN"
        elif net_ret < 0:
            audit_verdict = "DIRECTIONAL LOSS"
        else:
            audit_verdict = "BREAKEVEN"

        item = {
            "id": rec_id,
            "symbol": r["symbol"],
            "signal_date": r["signal_date"],
            "signal_price": r["signal_price"],
            "direction": r["signal_direction"],
            "composite_score": r["composite_score"],
            "planned_entry_price": r["planned_entry_price"],
            "entry_date": r["entry_date"],
            "entry_price": r["entry_price"],
            "planned_target_price": r["planned_target_price"],
            "planned_stop_loss": r["planned_stop_loss"],
            "exit_date": r["exit_date"],
            "exit_price": r["exit_price"],
            "exit_reason": r["exit_reason"],
            "status": status,
            "rejection_reason": r.get("rejection_reason"),
            "position_qty": r["position_qty"],
            "gross_pnl": r.get("gross_pnl", 0.0),
            "net_pnl": r.get("net_pnl", 0.0),
            "net_return_pct": net_ret,
            "audit_verdict": audit_verdict,
            "events": events
        }
        scorecard.append(item)

    conn.close()
    return scorecard
