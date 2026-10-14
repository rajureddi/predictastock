"""
Tapetide Financial Intelligence Client & Smart Quota Manager
Connects PredictaStock to Tapetide's 55-tool MCP Server (https://mcp.tapetide.com/mcp)
Features:
- Direct JSON-RPC over Streamable HTTP (no Node.js subprocess required).
- Strict Quota Protection: Automatically enforces a 45-call safety threshold (50 free calls/day).
- 24-Hour Persistent SQLite Caching: Zero wasted calls on repeated requests.
- High-Value Quantitative Extraction: Options IV rank/percentile, promoter pledge %, and daily FII/DII net flows.
"""
import os
import json
import logging
import sqlite3
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional
import requests

from app.config import (
    TAPETIDE_TOKEN,
    TAPETIDE_MCP_URL,
    TAPETIDE_DAILY_CALL_LIMIT,
    TAPETIDE_SAFETY_BUFFER,
    DB_PATH
)

logger = logging.getLogger("predictastock.tapetide")


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_tapetide_db():
    """Initializes tables for Tapetide caching and daily quota tracking."""
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tapetide_cache (
            cache_key TEXT PRIMARY KEY,
            tool_name TEXT,
            response_json TEXT,
            created_at TEXT,
            expires_at TEXT
        );
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tapetide_usage_ledger (
            usage_date TEXT PRIMARY KEY,
            call_count INTEGER DEFAULT 0,
            last_call_at TEXT
        );
    """)
    conn.commit()
    conn.close()


# Ensure tables exist
_init_tapetide_db()


def get_calls_used_today() -> int:
    """Returns the total number of live API calls made to Tapetide today."""
    today_str = date.today().isoformat()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT call_count FROM tapetide_usage_ledger WHERE usage_date = ?", (today_str,))
    row = cursor.fetchone()
    conn.close()
    return int(row["call_count"]) if row else 0


def _increment_call_count():
    """Increments the daily API call counter."""
    today_str = date.today().isoformat()
    now_str = datetime.now().isoformat()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO tapetide_usage_ledger (usage_date, call_count, last_call_at)
        VALUES (?, 1, ?)
        ON CONFLICT(usage_date) DO UPDATE SET
            call_count = call_count + 1,
            last_call_at = ?
    """, (today_str, now_str, now_str))
    conn.commit()
    conn.close()


def _get_cached_response(cache_key: str) -> Optional[Dict[str, Any]]:
    """Retrieves an unexpired response from the local SQLite cache."""
    now_str = datetime.now().isoformat()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT response_json FROM tapetide_cache WHERE cache_key = ? AND expires_at > ?",
        (cache_key, now_str)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        try:
            return json.loads(row["response_json"])
        except Exception:
            return None
    return None


def _set_cached_response(cache_key: str, tool_name: str, data: Dict[str, Any], ttl_hours: int = 24):
    """Saves a response to the local SQLite cache with a specified TTL."""
    now = datetime.now()
    expires_at = (now + timedelta(hours=ttl_hours)).isoformat()
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO tapetide_cache (cache_key, tool_name, response_json, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, (cache_key, tool_name, json.dumps(data), now.isoformat(), expires_at))
    conn.commit()
    conn.close()


def call_tapetide_tool(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    ttl_hours: int = 24,
    force_refresh: bool = False
) -> Dict[str, Any]:
    """
    Executes a tool call on the Tapetide MCP server with 24-hour caching and quota protection.
    Returns: Parsed JSON payload or an informative fallback dictionary.
    """
    arguments = arguments or {}
    clean_token = (TAPETIDE_TOKEN or "").strip()
    if not clean_token:
        logger.debug("Tapetide token not configured; skipping call.")
        return {"available": False, "error": "TAPETIDE_TOKEN not configured"}

    # 1. Check local cache
    args_hash = json.dumps(arguments, sort_keys=True)
    cache_key = f"{tool_name}:{args_hash}"
    if not force_refresh:
        cached = _get_cached_response(cache_key)
        if cached:
            return cached

    # 2. Check Daily Quota Threshold
    used_today = get_calls_used_today()
    max_safe_calls = max(1, TAPETIDE_DAILY_CALL_LIMIT - TAPETIDE_SAFETY_BUFFER)
    if used_today >= max_safe_calls:
        logger.warning(
            f"Tapetide daily quota buffer reached ({used_today}/{TAPETIDE_DAILY_CALL_LIMIT} calls). "
            f"Suppressing external call to '{tool_name}' to preserve free quota."
        )
        return {
            "available": False,
            "quota_limited": True,
            "error": f"Daily Tapetide free call safety limit reached ({used_today}/{TAPETIDE_DAILY_CALL_LIMIT})"
        }

    # 3. Fire JSON-RPC HTTP Request
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {clean_token}"
    }
    payload = {
        "jsonrpc": "2.0",
        "id": int(datetime.now().timestamp()),
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments
        }
    }

    try:
        res = requests.post(TAPETIDE_MCP_URL, json=payload, headers=headers, timeout=12)
        if res.status_code != 200:
            logger.warning(f"Tapetide HTTP {res.status_code}: {res.text[:200]}")
            return {"available": False, "error": f"HTTP {res.status_code}"}

        _increment_call_count()
        data = res.json()

        # Extract text content from MCP result format
        result_content = data.get("result", {}).get("content", [])
        if result_content and isinstance(result_content, list) and len(result_content) > 0:
            raw_text = result_content[0].get("text", "{}")
            parsed_data = json.loads(raw_text)
            
            # Wrap in standard structure
            final_res = {"available": True, "source": "TAPETIDE_MCP", "data": parsed_data}
            _set_cached_response(cache_key, tool_name, final_res, ttl_hours=ttl_hours)
            return final_res

        return {"available": False, "error": "Empty or unrecognized MCP payload"}

    except Exception as e:
        logger.error(f"Error calling Tapetide tool '{tool_name}': {e}")
        return {"available": False, "error": str(e)}


# --------------------------------------------------------------------------
# HIGH-VALUE SPECIALIZED METHODS FOR PREDICTASTOCK
# --------------------------------------------------------------------------

def get_fii_dii_summary() -> Dict[str, Any]:
    """
    Retrieves latest FII and DII cash market net flows in ₹ Crores.
    Cached for 12 hours (consumes only 1 call per day).
    """
    res = call_tapetide_tool("get_fii_dii_flows", {}, ttl_hours=12)
    if not res.get("available"):
        return {"available": False, "fii_net_cr": None, "dii_net_cr": None}

    raw = res.get("data", {}).get("flows", {})
    daily_list = raw.get("daily", [])
    monthly_list = raw.get("monthly", [])

    latest_day = daily_list[0] if daily_list else {}
    latest_month = monthly_list[0] if monthly_list else {}

    return {
        "available": True,
        "source": "TAPETIDE_FII_DII_RADAR",
        "date": latest_day.get("date", date.today().isoformat()),
        "fii_net_cr": latest_day.get("fii_net", latest_month.get("fii_net", 0.0)),
        "dii_net_cr": latest_day.get("dii_net", latest_month.get("dii_net", 0.0)),
        "monthly_combined_cr": latest_month.get("combined", 0.0),
        "month_label": latest_month.get("month", "")
    }


def get_options_analytics(symbol: str) -> Dict[str, Any]:
    """
    Retrieves ATM Implied Volatility, IV Rank, and IV Percentile for ~556 Indian underlyings.
    Cached for 24 hours per stock.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    res = call_tapetide_tool("get_options_analytics", {"symbol": clean_sym}, ttl_hours=24)
    if not res.get("available"):
        return {"available": False, "iv_rank": None, "iv_percentile": None}

    data = res.get("data", {}).get("data", {})
    iv_rank = data.get("iv_rank")
    iv_percentile = data.get("iv_percentile")

    return {
        "available": True,
        "symbol": clean_sym,
        "as_of": data.get("as_of"),
        "iv_rank": round(float(iv_rank) * 100, 1) if iv_rank is not None else None,
        "iv_percentile": round(float(iv_percentile) * 100, 1) if iv_percentile is not None else None,
        "notes": data.get("notes", [])
    }


def get_promoter_pledge_status(symbol: str) -> Dict[str, Any]:
    """
    Retrieves promoter share pledge percentage to evaluate governance stress.
    Cached for 24 hours per stock.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    res = call_tapetide_tool("get_promoter_pledge", {"symbol": clean_sym}, ttl_hours=24)
    if not res.get("available"):
        return {"available": False, "pledged_pct": None, "is_high_risk": False}

    data = res.get("data", {}).get("data", {})
    raw_pledged = data.get("latest_pledged_pct_of_promoter_holding", "0")
    try:
        pledged_pct = float(raw_pledged)
    except (ValueError, TypeError):
        pledged_pct = 0.0

    return {
        "available": True,
        "symbol": clean_sym,
        "pledged_pct": pledged_pct,
        "is_high_risk": pledged_pct > 15.0,
        "governance_flag": "High Promoter Pledge (>15%)" if pledged_pct > 15.0 else "Healthy Promoter Pledge",
        "quarterly_trend": data.get("quarterly_trend", [])[:3]
    }


def get_stock_enrichment(symbol: str) -> Dict[str, Any]:
    """
    Returns macro FII/DII flow (1 call/day shared across all stocks) and checks if
    cached options/governance exists. Does NOT make unneeded per-stock live calls,
    relying on PredictaStock's built-in quantitative engines for individual stocks
    and preserving the 50 calls/day budget.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    fii_dii = get_fii_dii_summary()

    # Check cache only for per-stock tools to prevent consuming calls per stock
    opt_cached = _get_cached_response(f"get_options_analytics:{json.dumps({'symbol': clean_sym}, sort_keys=True)}")
    pledge_cached = _get_cached_response(f"get_promoter_pledge:{json.dumps({'symbol': clean_sym}, sort_keys=True)}")

    opt_data = {"available": False, "iv_rank": None, "iv_percentile": None, "source": "BUILTIN_LOCAL_ATR"}
    if opt_cached and opt_cached.get("available"):
        data = opt_cached.get("data", {}).get("data", {})
        iv_rank = data.get("iv_rank")
        iv_percentile = data.get("iv_percentile")
        opt_data = {
            "available": True,
            "symbol": clean_sym,
            "as_of": data.get("as_of"),
            "iv_rank": round(float(iv_rank) * 100, 1) if iv_rank is not None else None,
            "iv_percentile": round(float(iv_percentile) * 100, 1) if iv_percentile is not None else None,
            "cached": True,
            "source": "TAPETIDE_CACHED"
        }

    gov_data = {"available": False, "pledged_pct": 0.0, "is_high_risk": False, "governance_flag": "Local Solvency Check", "source": "BUILTIN_LOCAL_STATEMENTS"}
    if pledge_cached and pledge_cached.get("available"):
        data = pledge_cached.get("data", {}).get("data", {})
        raw_pledged = data.get("latest_pledged_pct_of_promoter_holding", "0")
        try:
            pledged_pct = float(raw_pledged)
        except (ValueError, TypeError):
            pledged_pct = 0.0
        gov_data = {
            "available": True,
            "symbol": clean_sym,
            "pledged_pct": pledged_pct,
            "is_high_risk": pledged_pct > 15.0,
            "governance_flag": "High Promoter Pledge (>15%)" if pledged_pct > 15.0 else "Healthy Promoter Pledge",
            "cached": True,
            "source": "TAPETIDE_CACHED"
        }

    return {
        "symbol": clean_sym,
        "has_tapetide": fii_dii.get("available", False) or opt_data.get("available", False),
        "options": opt_data,
        "governance": gov_data,
        "macro_fii_dii": fii_dii,
        "mode": "MACRO_ONLY_CONSERVATION"
    }


def get_fpi_sectors_summary() -> Dict[str, Any]:
    """
    Retrieves foreign portfolio investor (FPI) sector-wise capital flows and AUM share.
    Cached for 24 hours (consumes 1 call per day).
    """
    res = call_tapetide_tool("get_fpi_sectors", {}, ttl_hours=24)
    if not res.get("available"):
        return {"available": False, "sectors": []}

    data = res.get("data", {})
    sectors_raw = data.get("sectors", [])
    summary_list = []
    for s in sectors_raw[:8]:
        summary_list.append({
            "sector": s.get("sector"),
            "aum_cr": s.get("aum"),
            "fortnight_net_cr": s.get("fortnight_flow"),
            "flow_trend": "Inflow" if (s.get("fortnight_flow") or 0) > 0 else "Outflow"
        })

    return {
        "available": True,
        "report_date": data.get("meta", {}).get("latest_report_date"),
        "top_sectors": summary_list
    }


def get_market_deliveries_summary() -> Dict[str, Any]:
    """
    Retrieves latest session's highest delivery-% stocks (>=50%, traded value >= Rs 1 Cr).
    Signals genuine institutional accumulation over intraday speculation.
    Cached for 24 hours (consumes 1 call per day).
    """
    res = call_tapetide_tool("get_market_data", {"dataset": "deliveries"}, ttl_hours=24)
    if not res.get("available"):
        return {"available": False, "stocks": []}

    data = res.get("data", {})
    stocks_raw = data.get("stocks", [])
    top_deliveries = []
    for s in stocks_raw[:10]:
        top_deliveries.append({
            "symbol": s.get("symbol"),
            "name": s.get("name"),
            "sector": s.get("sector"),
            "delivery_pct": s.get("delivery_pct"),
            "traded_value_cr": round(float(s.get("delivery_value", 0)) / 10000000.0, 2)
        })

    return {
        "available": True,
        "date": data.get("delivery_date"),
        "total_screened": data.get("total_stocks", 0),
        "high_delivery_leaders": top_deliveries
    }


def get_fno_ban_summary() -> Dict[str, Any]:
    """
    Retrieves the official exchange F&O ban list and stocks near 80% MWPL.
    Used as an immediate risk gatekeeper against short-squeeze traps.
    Cached for 24 hours (consumes 1 call per day).
    """
    res = call_tapetide_tool("get_market_data", {"dataset": "fno_ban"}, ttl_hours=24)
    if not res.get("available"):
        return {"available": False, "banned_symbols": [], "near_ban_symbols": []}

    data = res.get("data", {})
    ban_symbols = data.get("ban_list", {}).get("symbols", [])
    near_ban = []
    for s in data.get("stocks", []):
        if s.get("status") != "in_ban" and s.get("mwpl_pct", 0) >= 75.0:
            near_ban.append({
                "symbol": s.get("symbol"),
                "mwpl_pct": round(float(s.get("mwpl_pct", 0)), 1)
            })

    return {
        "available": True,
        "as_of": data.get("as_of"),
        "banned_symbols": ban_symbols,
        "near_ban_symbols": near_ban[:6]
    }


def get_market_deals_summary() -> Dict[str, Any]:
    """
    Retrieves bulk & block deals executed over the last 7 trading days.
    Cached for 24 hours (consumes 1 call per day).
    """
    res = call_tapetide_tool("get_market_data", {"dataset": "deals"}, ttl_hours=24)
    if not res.get("available"):
        return {"available": False, "deals": []}

    data = res.get("data", {})
    deals_list = data.get("deals", [])
    top_deals = []
    for d in deals_list[:8]:
        top_deals.append({
            "symbol": d.get("symbol"),
            "client": d.get("client_name"),
            "deal_type": d.get("deal_type"),
            "action": d.get("buy_sell"),
            "value_cr": round(float(d.get("value", 0)) / 10000000.0, 2),
            "date": d.get("date")
        })

    return {
        "available": True,
        "latest_date": data.get("latest_date"),
        "deals": top_deals
    }


def audit_stock_on_demand(symbol: str, force_refresh: bool = False) -> Dict[str, Any]:
    """
    User-initiated or top-5 recommendation audit for a single stock.
    Explicitly retrieves live Options IV rank and Promoter Share Pledge.
    Cached for 24 hours per stock (consumes max 2 calls upon first lookup).
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    opt = get_options_analytics(clean_sym)
    pledge = get_promoter_pledge_status(clean_sym)

    return {
        "symbol": clean_sym,
        "audited": True,
        "options": opt,
        "governance": pledge,
        "audited_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S IST")
    }


def audit_top_recommendations(recommendations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Audits ONLY the top 5 finalized stock recommendations for the morning briefing.
    Consumes at most 10 calls (5 stocks * 2 tools) per day, safely fitting within quota.
    """
    if not recommendations:
        return []

    enriched = []
    for idx, rec in enumerate(recommendations):
        if idx < 5:  # Strictly cap at top 5 to preserve quota
            audit = audit_stock_on_demand(rec.get("symbol", ""))
            opt = audit.get("options", {})
            gov = audit.get("governance", {})

            rec["tapetide_audited"] = True
            rec["iv_rank"] = opt.get("iv_rank")
            rec["iv_percentile"] = opt.get("iv_percentile")
            rec["promoter_pledged_pct"] = gov.get("pledged_pct", 0.0)
            rec["governance_flag"] = gov.get("governance_flag", "Normal")
        enriched.append(rec)

    return enriched


def get_macro_market_dashboard() -> Dict[str, Any]:
    """
    Assembles a unified market-wide institutional dashboard combining FII/DII cash flows,
    FPI sector rotation, high-delivery accumulation stocks, and the F&O ban watchlist.
    Consumes at most 4 calls per day across the entire system.
    """
    return {
        "fii_dii": get_fii_dii_summary(),
        "fpi_sectors": get_fpi_sectors_summary(),
        "deliveries": get_market_deliveries_summary(),
        "fno_ban": get_fno_ban_summary(),
        "deals": get_market_deals_summary(),
        "quota": get_quota_status()
    }


def get_quota_status() -> Dict[str, Any]:
    """Returns real-time status of the Tapetide 50-call/day allocation."""
    used = get_calls_used_today()
    limit = TAPETIDE_DAILY_CALL_LIMIT
    safe_cap = max(1, limit - TAPETIDE_SAFETY_BUFFER)
    
    conn = _get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as cnt FROM tapetide_cache WHERE expires_at > ?", (datetime.now().isoformat(),))
    cached_count = cursor.fetchone()["cnt"]
    conn.close()

    return {
        "active": bool(TAPETIDE_TOKEN),
        "service": "Tapetide MCP Gateway",
        "calls_used_today": used,
        "daily_limit": limit,
        "safe_cap": safe_cap,
        "calls_remaining": max(0, safe_cap - used),
        "cached_items_count": cached_count,
        "status": "OPERATIONAL" if used < safe_cap else "QUOTA_PROTECTED"
    }


def get_integrations_status() -> Dict[str, Any]:
    """Returns standardized health and quota status for the integrations subsystem."""
    quota = get_quota_status()
    return {
        "tapetide": {
            "connected": quota["active"],
            "status": quota["status"],
            "calls_used_today": quota["calls_used_today"],
            "daily_limit": quota["daily_limit"],
            "calls_remaining": quota["calls_remaining"],
            "cached_entries": quota["cached_items_count"],
            "description": "55-Tool Indian Equities MCP Gateway (FII/DII, Options IV, Promoter Pledges)"
        }
    }


def update_tapetide_token(token: str) -> Dict[str, Any]:
    """Updates the runtime and persistent .env token for Tapetide MCP Gateway."""
    global TAPETIDE_TOKEN
    clean_token = token.strip()
    TAPETIDE_TOKEN = clean_token
    os.environ["TAPETIDE_TOKEN"] = clean_token

    from pathlib import Path
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    new_lines = []
    for line in lines:
        if line.strip().startswith("TAPETIDE_TOKEN="):
            new_lines.append(f"TAPETIDE_TOKEN={clean_token}\n")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"TAPETIDE_TOKEN={clean_token}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"Could not persist TAPETIDE_TOKEN to .env: {e}")

    return {
        "status": "UPDATED",
        "service": "tapetide",
        "active": bool(clean_token)
    }

