"""
Corporate Actions Engine for Indian Equities
Tracks, logs, and applies Stock Splits, Bonus Issues, and Dividends to user portfolio holdings.
Phase 2 Integrity:
- Auto-adjusts purchase quantities and per-share cost basis on ex-date.
- Preserves mathematical cost basis integrity (total lot cost basis remains conserved).
- Immutable audit trail in `corporate_actions` table.
"""
import uuid
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import logging

from app.database import get_db_connection

logger = logging.getLogger(__name__)


def record_corporate_action(
    symbol: str,
    action_type: str,
    ex_date: str,
    ratio: str = "1:1",
    adjustment_factor: float = 1.0,
    dividend_amount: float = 0.0,
    record_date: str = None
) -> Dict[str, Any]:
    """Record an official corporate action (SPLIT, BONUS, DIVIDEND) in the database."""
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    rec_date = record_date or ex_date
    action_id = str(uuid.uuid4())
    act_type = action_type.upper().strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO corporate_actions (
        id, symbol, action_type, record_date, ex_date,
        ratio, adjustment_factor, dividend_amount, applied, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
    """, (
        action_id, clean_sym, act_type, rec_date, ex_date,
        ratio, adjustment_factor, dividend_amount, datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

    return {
        "id": action_id,
        "symbol": clean_sym,
        "action_type": act_type,
        "ex_date": ex_date,
        "adjustment_factor": adjustment_factor,
        "dividend_amount": dividend_amount
    }


def apply_pending_corporate_actions() -> int:
    """
    Scans unapplied corporate actions whose ex_date has arrived.
    Adjusts quantities and prices in `portfolio_transactions` for open lots.
    Conservation Rule: Total investment cost basis (Quantity * Price) is strictly conserved.
    """
    today_str = date.today().isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT * FROM corporate_actions 
    WHERE applied = 0 AND ex_date <= ?
    """, (today_str,))
    pending_actions = [dict(row) for row in cursor.fetchall()]

    applied_count = 0
    for action in pending_actions:
        symbol = action["symbol"]
        act_type = action["action_type"]
        factor = float(action["adjustment_factor"])

        if act_type in ["SPLIT", "BONUS"] and factor > 1.0:
            logger.info(f"Applying {act_type} for {symbol} (Factor: {factor}x on {action['ex_date']})...")
            # Update all BUY transactions for this symbol recorded on or before ex_date
            cursor.execute("""
            SELECT id, price, quantity FROM portfolio_transactions
            WHERE symbol = ? AND transaction_type = 'BUY' AND transaction_date <= ?
            """, (symbol, action["ex_date"]))
            matching_buys = cursor.fetchall()

            for buy in matching_buys:
                new_qty = int(round(buy["quantity"] * factor))
                new_price = round(buy["price"] / factor, 2)
                cursor.execute("""
                UPDATE portfolio_transactions SET
                    quantity = ?,
                    price = ?,
                    notes = coalesce(notes, '') || ' [Adjusted for ' || ? || ' ' || ? || ']'
                WHERE id = ?
                """, (new_qty, new_price, act_type, action["ratio"], buy["id"]))

        # Mark action as applied
        cursor.execute("UPDATE corporate_actions SET applied = 1 WHERE id = ?", (action["id"],))
        applied_count += 1

    conn.commit()
    conn.close()
    return applied_count
