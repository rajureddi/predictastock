"""
Portfolio Engine & FIFO Cost Basis Tracker for Indian Equities
Calculates First-In-First-Out (FIFO) lot matching, realized & unrealized P&L,
and SEBI/Indian statutory charges (STT, Brokerage, Exchange charges, Stamp Duty, GST).
Phase 1 Integrity Rules:
- Strict transaction validation: rejects negative/zero quantity & price.
- Rejects SELL transactions that exceed currently held shares.
- Correct FIFO cost allocation: allocates buy costs to lots, sell costs to sales;
  never subtracts historical lifetime costs from current unrealized positions.
- Transparent quote handling: marks data unavailable if market feed is offline.
"""
import uuid
from datetime import datetime, date
from typing import Dict, Any, List, Optional
import logging

from app.database import get_db_connection
from app.config import (
    DEFAULT_BROKERAGE_PER_ORDER, STT_RATE_BUY, STT_RATE_SELL,
    EXCHANGE_TURNOVER_FEE, GST_RATE, STAMP_DUTY_RATE,
    LTCG_HOLDING_DAYS_THRESHOLD, SECTOR_CONCENTRATION_ALERT_PCT
)
from app.data.nifty_constituents import get_symbol_info
from app.services.market_data import get_latest_quote, is_quote_valid

logger = logging.getLogger(__name__)


def calculate_indian_statutory_costs(
    price: float,
    quantity: int,
    is_buy: bool = True,
    custom_brokerage: float = None
) -> Dict[str, float]:
    """
    Computes exact statutory Indian equity delivery transaction costs.
    """
    turnover = round(price * quantity, 2)
    
    # 1. Brokerage (Discount broker standard: min of 0.05% or Rs. 20, or custom)
    if custom_brokerage is not None:
        brokerage = round(float(custom_brokerage), 2)
    else:
        brokerage = round(min(turnover * 0.0005, DEFAULT_BROKERAGE_PER_ORDER), 2)
        
    # 2. Securities Transaction Tax (STT): 0.1% on delivery (both Buy & Sell)
    stt_rate = STT_RATE_BUY if is_buy else STT_RATE_SELL
    stt = round(turnover * stt_rate, 2)
    
    # 3. Exchange Turnover Charges: ~0.00345%
    exchange_charges = round(turnover * EXCHANGE_TURNOVER_FEE, 2)
    
    # 4. Stamp Duty: 0.015% (Buy only)
    stamp_duty = round(turnover * STAMP_DUTY_RATE, 2) if is_buy else 0.0
    
    # 5. GST: 18% on (Brokerage + Exchange Charges)
    gst = round((brokerage + exchange_charges) * GST_RATE, 2)
    
    total_costs = round(brokerage + stt + exchange_charges + stamp_duty + gst, 2)
    
    return {
        "turnover": turnover,
        "brokerage": brokerage,
        "stt": stt,
        "exchange_charges": exchange_charges,
        "stamp_duty": stamp_duty,
        "gst": gst,
        "total_costs": total_costs
    }


def get_current_shares_held(symbol: str, user_id: str = "default_trader") -> int:
    """Calculate current net shares held for a given symbol from the transaction ledger for a user."""
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    target_ids = [user_id]
    if user_id in ["default_trader", "usr_default_trader"]:
        target_ids = ["default_trader", "usr_default_trader"]

    placeholders = ",".join("?" for _ in target_ids)
    cursor.execute(f"""
    SELECT transaction_type, quantity 
    FROM portfolio_transactions 
    WHERE symbol = ? AND coalesce(user_id, 'default_trader') IN ({placeholders})
    ORDER BY transaction_date ASC, created_at ASC
    """, [clean_sym] + target_ids)
    rows = cursor.fetchall()
    conn.close()
    
    held = 0
    for r in rows:
        if r["transaction_type"] == "BUY":
            held += r["quantity"]
        elif r["transaction_type"] == "SELL":
            held -= r["quantity"]
    return held


def record_transaction(
    symbol: str,
    transaction_type: str,
    price: float,
    quantity: int,
    transaction_date: str = None,
    brokerage: float = None,
    recommendation_id: str = None,
    notes: str = None,
    user_id: str = "default_trader"
) -> Dict[str, Any]:
    """
    Record a new buy or sell trade in the permanent immutable transaction ledger.
    Phase 4: Scoped to user_id.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    tx_type = transaction_type.upper().strip()
    
    # Validation 1: Transaction Type
    if tx_type not in ["BUY", "SELL"]:
        raise ValueError(f"Invalid transaction type: '{transaction_type}'. Must be 'BUY' or 'SELL'.")
        
    # Validation 2: Quantity and Price strictly positive
    if not isinstance(quantity, int) or quantity <= 0:
        raise ValueError(f"Invalid quantity: {quantity}. Quantity must be a strictly positive integer.")
    if not isinstance(price, (int, float)) or price <= 0:
        raise ValueError(f"Invalid price: {price}. Price must be a strictly positive number.")
        
    # Validation 3: Oversell rejection
    if tx_type == "SELL":
        currently_held = get_current_shares_held(clean_sym, user_id=user_id)
        if quantity > currently_held:
            raise ValueError(
                f"Cannot record SELL of {quantity} shares of {clean_sym}: "
                f"only {currently_held} shares currently held in portfolio."
            )
            
    conn = get_db_connection()
    cursor = conn.cursor()
    
    t_date = transaction_date or date.today().isoformat()
    t_id = str(uuid.uuid4())
    is_buy = (tx_type == "BUY")
    
    costs = calculate_indian_statutory_costs(price, quantity, is_buy=is_buy, custom_brokerage=brokerage)
    amount = costs["turnover"]
    
    cursor.execute("""
    INSERT INTO portfolio_transactions (
        id, symbol, exchange, transaction_type, transaction_date,
        price, quantity, amount, brokerage, stt, exchange_charges,
        stamp_duty, gst, total_costs, recommendation_id, notes, created_at, user_id
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        t_id, clean_sym, "NSE", tx_type, t_date,
        price, quantity, amount, costs["brokerage"], costs["stt"],
        costs["exchange_charges"], costs["stamp_duty"], costs["gst"],
        costs["total_costs"], recommendation_id, notes, datetime.now().isoformat(), user_id
    ))
    
    conn.commit()
    conn.close()
    
    return {
        "transaction_id": t_id,
        "symbol": clean_sym,
        "type": tx_type,
        "price": price,
        "quantity": quantity,
        "amount": amount,
        "total_costs": costs["total_costs"],
        "date": t_date,
        "user_id": user_id
    }


def compute_portfolio_fifo(user_id: str = "default_trader") -> Dict[str, Any]:
    """
    Executes First-In-First-Out (FIFO) matching across all transactions for each stock for a specific user.
    Auto-applies pending corporate actions (Splits, Bonus) before computing lots.
    """
    # Phase 2 Corporate Actions Auto-Application
    try:
        from app.services.corporate_actions import apply_pending_corporate_actions
        apply_pending_corporate_actions()
    except Exception as e:
        logger.warning(f"Failed to auto-apply pending corporate actions: {e}")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    target_ids = [user_id]
    if user_id in ["default_trader", "usr_default_trader"]:
        target_ids = ["default_trader", "usr_default_trader"]

    placeholders = ",".join("?" for _ in target_ids)
    cursor.execute(f"""
    SELECT * FROM portfolio_transactions 
    WHERE coalesce(user_id, 'default_trader') IN ({placeholders})
    ORDER BY transaction_date ASC, created_at ASC
    """, target_ids)
    transactions = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # Holdings FIFO tranches: {sym: [{'price': float, 'quantity': int, 'date': date, 'buy_cost_per_share': float}]}
    holdings_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    realized_gross_by_symbol: Dict[str, float] = {}
    realized_net_by_symbol: Dict[str, float] = {}
    total_costs_by_symbol: Dict[str, float] = {}
    
    today = date.today()
    
    for t in transactions:
        sym = t["symbol"]
        if sym not in holdings_by_symbol:
            holdings_by_symbol[sym] = []
            realized_gross_by_symbol[sym] = 0.0
            realized_net_by_symbol[sym] = 0.0
            total_costs_by_symbol[sym] = 0.0
            
        t_costs = t.get("total_costs", 0.0)
        total_costs_by_symbol[sym] += t_costs
        t_qty = t["quantity"]
        t_price = t["price"]
        
        t_date_parsed = (
            datetime.strptime(t["transaction_date"], "%Y-%m-%d").date() 
            if isinstance(t["transaction_date"], str) 
            else t["transaction_date"]
        )
        
        if t["transaction_type"] == "BUY":
            cost_per_share = (t_costs / t_qty) if t_qty > 0 else 0.0
            holdings_by_symbol[sym].append({
                "price": t_price,
                "quantity": t_qty,
                "date": t_date_parsed,
                "buy_cost_per_share": cost_per_share
            })
        elif t["transaction_type"] == "SELL":
            qty_to_sell = t_qty
            sell_cost_per_share = (t_costs / t_qty) if t_qty > 0 else 0.0
            
            while qty_to_sell > 0 and holdings_by_symbol[sym]:
                oldest_tranche = holdings_by_symbol[sym][0]
                tranche_qty = oldest_tranche["quantity"]
                tranche_buy_price = oldest_tranche["price"]
                tranche_buy_cost_per_share = oldest_tranche["buy_cost_per_share"]
                
                matched_qty = min(qty_to_sell, tranche_qty)
                
                gross_gain = (t_price - tranche_buy_price) * matched_qty
                net_gain = (
                    (t_price - sell_cost_per_share) - 
                    (tranche_buy_price + tranche_buy_cost_per_share)
                ) * matched_qty
                
                realized_gross_by_symbol[sym] += gross_gain
                realized_net_by_symbol[sym] += net_gain
                
                qty_to_sell -= matched_qty
                oldest_tranche["quantity"] -= matched_qty
                
                if oldest_tranche["quantity"] == 0:
                    holdings_by_symbol[sym].pop(0)

    # Build active holdings output
    active_holdings = []
    total_invested_portfolio = 0.0
    current_value_portfolio = 0.0
    total_unrealized_pnl = 0.0
    total_unrealized_net_pnl = 0.0
    total_realized_gross_pnl = sum(realized_gross_by_symbol.values())
    total_realized_net_pnl = sum(realized_net_by_symbol.values())
    total_portfolio_costs = sum(total_costs_by_symbol.values())
    
    sector_values: Dict[str, float] = {}
    any_quote_unavailable = False
    
    for sym, tranches in holdings_by_symbol.items():
        remaining_qty = sum(tr["quantity"] for tr in tranches)
        if remaining_qty <= 0:
            continue
            
        total_cost_basis = sum(tr["price"] * tr["quantity"] for tr in tranches)
        allocated_open_buy_costs = sum(tr["buy_cost_per_share"] * tr["quantity"] for tr in tranches)
        avg_buy_price = round(total_cost_basis / remaining_qty, 2)
        
        # Calculate STCG vs LTCG quantities
        stcg_qty = 0
        ltcg_qty = 0
        for tr in tranches:
            holding_days = (today - tr["date"]).days
            if holding_days > LTCG_HOLDING_DAYS_THRESHOLD:
                ltcg_qty += tr["quantity"]
            else:
                stcg_qty += tr["quantity"]
                
        # Get live quote
        quote = get_latest_quote(sym)
        meta = get_symbol_info(sym)
        sector = meta.get("sector", "Other")
        alerts = []
        
        if is_quote_valid(quote):
            cmp = quote["close_price"]
            market_value = round(cmp * remaining_qty, 2)
            unrealized_pnl = round(market_value - total_cost_basis, 2)
            unrealized_pnl_pct = round((unrealized_pnl / total_cost_basis) * 100, 2) if total_cost_basis > 0 else 0.0
            net_pnl_after_costs = round(unrealized_pnl - allocated_open_buy_costs, 2)
            quote_status = "VERIFIED_LIVE"
            
            sector_values[sector] = sector_values.get(sector, 0.0) + market_value
            total_invested_portfolio += total_cost_basis
            current_value_portfolio += market_value
            total_unrealized_pnl += unrealized_pnl
            total_unrealized_net_pnl += net_pnl_after_costs
            
            if quote.get("day_change_pct", 0) <= -3.0:
                alerts.append(f"Intraday pullback: {quote['day_change_pct']}% today")
        else:
            # Explicit Data Unavailable state — NEVER assume ₹1,000!
            any_quote_unavailable = True
            cmp = None
            market_value = None
            unrealized_pnl = None
            unrealized_pnl_pct = 0.0
            net_pnl_after_costs = None
            quote_status = "DATA_UNAVAILABLE"
            alerts.append("Market feed offline: Close price could not be verified from exchange.")
            total_invested_portfolio += total_cost_basis

        active_holdings.append({
            "symbol": sym,
            "name": meta.get("name", sym),
            "sector": sector,
            "quantity": remaining_qty,
            "avg_purchase_price": avg_buy_price,
            "total_invested": round(total_cost_basis, 2),
            "allocated_open_costs": round(allocated_open_buy_costs, 2),
            "latest_price": cmp,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "net_pnl_after_costs": net_pnl_after_costs,
            "realized_gross_pnl": round(realized_gross_by_symbol.get(sym, 0.0), 2),
            "realized_net_pnl": round(realized_net_by_symbol.get(sym, 0.0), 2),
            "stcg_quantity": stcg_qty,
            "ltcg_quantity": ltcg_qty,
            "quote_status": quote_status,
            "current_status": "Active Holding",
            "risk_level": "Medium" if unrealized_pnl_pct < -5.0 else "Low",
            "alerts": alerts
        })
        
    # Sector concentration analysis
    sector_breakdown = {}
    sector_alerts = []
    if current_value_portfolio > 0:
        for sec, val in sector_values.items():
            pct = round((val / current_value_portfolio) * 100, 2)
            sector_breakdown[sec] = pct
            if pct > SECTOR_CONCENTRATION_ALERT_PCT:
                sector_alerts.append(f"Sector Concentration Warning: {sec} represents {pct}% of portfolio (threshold: 25%)")
                
    portfolio_unrealized_pct = round((total_unrealized_pnl / total_invested_portfolio) * 100, 2) if total_invested_portfolio > 0 else 0.0
    net_combined_pnl = round(total_unrealized_net_pnl + total_realized_net_pnl, 2)
    
    return {
        "total_invested": round(total_invested_portfolio, 2),
        "current_market_value": round(current_value_portfolio, 2),
        "unrealized_pnl": round(total_unrealized_pnl, 2),
        "unrealized_pnl_pct": portfolio_unrealized_pct,
        "realized_gross_pnl": round(total_realized_gross_pnl, 2),
        "realized_net_pnl": round(total_realized_net_pnl, 2),
        "total_costs_incurred": round(total_portfolio_costs, 2),
        "net_pnl_after_costs": net_combined_pnl,
        "has_unavailable_quotes": any_quote_unavailable,
        "sector_breakdown": sector_breakdown,
        "sector_alerts": sector_alerts,
        "holdings": active_holdings
    }


def delete_stock_from_portfolio(symbol: str, user_id: str = "default_trader") -> Dict[str, Any]:
    """
    Deletes all buy and sell transactions for a given stock symbol for a user,
    completely removing the stock and its historical records from the user's active portfolio.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    target_ids = [user_id]
    if user_id in ["default_trader", "usr_default_trader"]:
        target_ids = ["default_trader", "usr_default_trader"]

    placeholders = ",".join("?" for _ in target_ids)
    cursor.execute(f"""
    DELETE FROM portfolio_transactions 
    WHERE symbol = ? AND coalesce(user_id, 'default_trader') IN ({placeholders})
    """, [clean_sym] + target_ids)
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return {
        "status": "SUCCESS",
        "symbol": clean_sym,
        "deleted_count": deleted_count,
        "message": f"Successfully deleted {deleted_count} transaction(s) for {clean_sym}."
    }


def delete_transaction(transaction_id: str, user_id: str = "default_trader") -> Dict[str, Any]:
    """Deletes a specific transaction by transaction ID for a user."""
    conn = get_db_connection()
    cursor = conn.cursor()
    target_ids = [user_id]
    if user_id in ["default_trader", "usr_default_trader"]:
        target_ids = ["default_trader", "usr_default_trader"]

    placeholders = ",".join("?" for _ in target_ids)
    cursor.execute(f"""
    DELETE FROM portfolio_transactions 
    WHERE id = ? AND coalesce(user_id, 'default_trader') IN ({placeholders})
    """, [transaction_id] + target_ids)
    deleted_count = cursor.rowcount
    conn.commit()
    conn.close()
    return {
        "status": "SUCCESS",
        "transaction_id": transaction_id,
        "deleted_count": deleted_count
    }
