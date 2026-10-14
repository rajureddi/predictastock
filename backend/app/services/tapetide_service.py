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
    Combines Options Analytics, Promoter Pledge, and Macro FII/DII flow into a unified
    high-conviction quantitative profile. Consumes max 2 tool calls per unique stock per 24 hours.
    """
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    fii_dii = get_fii_dii_summary()
    opt = get_options_analytics(clean_sym)
    gov = get_promoter_pledge_status(clean_sym)

    return {
        "symbol": clean_sym,
        "has_tapetide": opt.get("available") or gov.get("available") or fii_dii.get("available"),
        "options": opt,
        "governance": gov,
        "macro_fii_dii": fii_dii
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

