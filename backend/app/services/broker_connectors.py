"""
Broker Integrations & Multi-Gateway Connector (Dhan & Upstox)
Provides modular adapters to connect Indian Demat brokers:
1. Dhan HQ API v2 (api.dhan.co) - Zero-brokerage live execution & portfolio holdings.
2. Upstox API v2 (api.upstox.com) - Direct REST execution & long-term holdings synchronization.
3. Unified Portfolio Sync: Directly maps live broker holdings into PredictaStock's FIFO ledger.
"""
import logging
from typing import Dict, Any, List, Optional
import requests

from app.config import (
    DHAN_CLIENT_ID,
    DHAN_ACCESS_TOKEN,
    UPSTOX_API_KEY,
    UPSTOX_ACCESS_TOKEN,
    TAPETIDE_TOKEN
)
from app.services.tapetide_service import get_quota_status
from app.services.portfolio import record_transaction, get_current_shares_held

logger = logging.getLogger("predictastock.brokers")


class DhanConnector:
    """Adapter for Dhan HQ API v2 (api.dhan.co)."""
    BASE_URL = "https://api.dhan.co/v2"

    def __init__(self):
        self.client_id = (DHAN_CLIENT_ID or "").strip()
        self.token = (DHAN_ACCESS_TOKEN or "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.client_id and self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "access-token": self.token,
            "client-id": self.client_id,
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get_holdings(self) -> Dict[str, Any]:
        """Fetches live portfolio holdings from Dhan account."""
        if not self.is_configured:
            return {"status": "NOT_CONFIGURED", "holdings": [], "message": "Dhan credentials not provided in .env"}

        try:
            res = requests.get(f"{self.BASE_URL}/holdings", headers=self._headers(), timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"status": "SUCCESS", "holdings": data if isinstance(data, list) else data.get("data", [])}
            return {"status": "ERROR", "code": res.status_code, "message": res.text[:200]}
        except Exception as e:
            logger.error(f"Dhan holdings fetch failed: {e}")
            return {"status": "ERROR", "message": str(e)}

    def get_funds(self) -> Dict[str, Any]:
        """Fetches available trading balance / margin limits."""
        if not self.is_configured:
            return {"status": "NOT_CONFIGURED"}
        try:
            res = requests.get(f"{self.BASE_URL}/fundlimit", headers=self._headers(), timeout=10)
            return res.json() if res.status_code == 200 else {"status": "ERROR", "code": res.status_code}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}


class UpstoxConnector:
    """Adapter for Upstox API v2 (api.upstox.com)."""
    BASE_URL = "https://api.upstox.com/v2"

    def __init__(self):
        self.api_key = (UPSTOX_API_KEY or "").strip()
        self.token = (UPSTOX_ACCESS_TOKEN or "").strip()

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def get_holdings(self) -> Dict[str, Any]:
        """Fetches long-term holdings from Upstox portfolio."""
        if not self.is_configured:
            return {"status": "NOT_CONFIGURED", "holdings": [], "message": "Upstox access token not configured in .env"}

        try:
            res = requests.get(f"{self.BASE_URL}/portfolio/long-term-holdings", headers=self._headers(), timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"status": "SUCCESS", "holdings": data.get("data", [])}
            return {"status": "ERROR", "code": res.status_code, "message": res.text[:200]}
        except Exception as e:
            logger.error(f"Upstox holdings fetch failed: {e}")
            return {"status": "ERROR", "message": str(e)}


dhan_client = DhanConnector()
upstox_client = UpstoxConnector()


def get_all_services_status() -> Dict[str, Any]:
    """
    Returns unified health and connectivity status across Tapetide, Dhan, and Upstox.
    """
    tapetide_status = get_quota_status()

    return {
        "tapetide": {
            "connected": tapetide_status["active"],
            "status": tapetide_status["status"],
            "calls_used_today": tapetide_status["calls_used_today"],
            "daily_limit": tapetide_status["daily_limit"],
            "calls_remaining": tapetide_status["calls_remaining"],
            "cached_entries": tapetide_status["cached_items_count"],
            "description": "55-Tool Indian Equities MCP Gateway (FII/DII, Options IV, Promoter Pledges)"
        },
        "dhan": {
            "connected": dhan_client.is_configured,
            "status": "CONFIGURED" if dhan_client.is_configured else "CREDENTIALS_NEEDED",
            "description": "Dhan HQ API v2 (Direct NSE/BSE Trading & Holdings Sync)"
        },
        "upstox": {
            "connected": upstox_client.is_configured,
            "status": "CONFIGURED" if upstox_client.is_configured else "CREDENTIALS_NEEDED",
            "description": "Upstox API v2 (Direct NSE/BSE Trading & Holdings Sync)"
        }
    }


def sync_broker_holdings(broker_name: str, user_id: str = "default_trader") -> Dict[str, Any]:
    """
    Imports real holdings from Dhan or Upstox into PredictaStock's FIFO transaction ledger.
    """
    broker = broker_name.lower().strip()
    synced_stocks = []

    if broker == "dhan":
        if not dhan_client.is_configured:
            return {"status": "FAILED", "message": "Dhan credentials not configured in backend/.env"}
        data = dhan_client.get_holdings()
        holdings = data.get("holdings", [])
        for h in holdings:
            sym = h.get("tradingSymbol", "").replace("-EQ", "").strip().upper()
            qty = int(h.get("totalQty", 0))
            avg_price = float(h.get("avgCostPrice", 0.0))
            if sym and qty > 0 and avg_price > 0:
                current_held = get_current_shares_held(sym, user_id=user_id)
                diff = qty - current_held
                if diff > 0:
                    record_transaction(sym, "BUY", avg_price, diff, notes=f"SYNCED_FROM_DHAN", user_id=user_id)
                    synced_stocks.append({"symbol": sym, "synced_qty": diff, "avg_price": avg_price})

    elif broker == "upstox":
        if not upstox_client.is_configured:
            return {"status": "FAILED", "message": "Upstox credentials not configured in backend/.env"}
        data = upstox_client.get_holdings()
        holdings = data.get("holdings", [])
        for h in holdings:
            sym = h.get("tradingsymbol", "").replace("-EQ", "").strip().upper()
            qty = int(h.get("quantity", 0))
            avg_price = float(h.get("average_price", 0.0))
            if sym and qty > 0 and avg_price > 0:
                current_held = get_current_shares_held(sym, user_id=user_id)
                diff = qty - current_held
                if diff > 0:
                    record_transaction(sym, "BUY", avg_price, diff, notes=f"SYNCED_FROM_UPSTOX", user_id=user_id)
                    synced_stocks.append({"symbol": sym, "synced_qty": diff, "avg_price": avg_price})

    else:
        return {"status": "INVALID_BROKER", "message": f"Supported brokers are 'dhan' and 'upstox'."}

    return {
        "status": "SUCCESS",
        "broker": broker,
        "stocks_synced": synced_stocks,
        "count": len(synced_stocks)
    }


def update_integration_credentials(service: str, creds: Dict[str, str]) -> Dict[str, Any]:
    """
    Updates API keys/tokens for Dhan, Upstox, or Tapetide dynamically and persists to .env.
    """
    import os
    from pathlib import Path
    
    svc = service.lower().strip()
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    env_lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            env_lines = f.readlines()

    updates = {}
    if svc == "dhan":
        if "client_id" in creds:
            updates["DHAN_CLIENT_ID"] = creds["client_id"].strip()
            dhan_client.client_id = creds["client_id"].strip()
            os.environ["DHAN_CLIENT_ID"] = creds["client_id"].strip()
        if "access_token" in creds:
            updates["DHAN_ACCESS_TOKEN"] = creds["access_token"].strip()
            dhan_client.token = creds["access_token"].strip()
            os.environ["DHAN_ACCESS_TOKEN"] = creds["access_token"].strip()

    elif svc == "upstox":
        if "api_key" in creds:
            updates["UPSTOX_API_KEY"] = creds["api_key"].strip()
            upstox_client.api_key = creds["api_key"].strip()
            os.environ["UPSTOX_API_KEY"] = creds["api_key"].strip()
        if "access_token" in creds:
            updates["UPSTOX_ACCESS_TOKEN"] = creds["access_token"].strip()
            upstox_client.token = creds["access_token"].strip()
            os.environ["UPSTOX_ACCESS_TOKEN"] = creds["access_token"].strip()

    elif svc == "tapetide":
        if "token" in creds:
            updates["TAPETIDE_TOKEN"] = creds["token"].strip()
            os.environ["TAPETIDE_TOKEN"] = creds["token"].strip()

    # Rewrite .env
    existing_keys = set()
    new_lines = []
    for line in env_lines:
        line_clean = line.strip()
        matched = False
        for k, v in updates.items():
            if line_clean.startswith(f"{k}="):
                new_lines.append(f"{k}={v}\n")
                existing_keys.add(k)
                matched = True
                break
        if not matched:
            new_lines.append(line)

    for k, v in updates.items():
        if k not in existing_keys:
            new_lines.append(f"{k}={v}\n")

    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        logger.warning(f"Could not persist to .env file: {e}")

    return {
        "status": "UPDATED",
        "service": svc,
        "is_configured": dhan_client.is_configured if svc == "dhan" else (upstox_client.is_configured if svc == "upstox" else bool(os.getenv("TAPETIDE_TOKEN")))
    }

