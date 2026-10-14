"""
Upstox Demat Gateway & Portfolio Synchronization Engine
Direct REST API v2 connector for Upstox (https://api.upstox.com/v2):
- Demat holdings synchronization into PredictaStock's FIFO cost basis ledger.
- Fund and margin limit audit.
- User profile and account verification.
- Comprehensive handling of Upstox error codes (including UDAPI1221 Static IP restriction).
"""
import logging
from typing import Dict, Any, List, Optional
import requests

from app.config import (
    UPSTOX_API_KEY,
    UPSTOX_ACCESS_TOKEN,
    TAPETIDE_TOKEN
)
from app.services.tapetide_service import get_quota_status
from app.services.portfolio import record_transaction, get_current_shares_held

logger = logging.getLogger("predictastock.upstox")


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

    def _parse_error_response(self, res: requests.Response) -> Dict[str, Any]:
        """Translates Upstox error payloads into actionable diagnostics."""
        try:
            data = res.json()
            errors = data.get("errors", [])
            if errors:
                err = errors[0]
                code = err.get("errorCode") or err.get("error_code")
                msg = err.get("message", "")
                if code == "UDAPI1221":
                    return {
                        "status": "IP_WHITELIST_REQUIRED",
                        "code": code,
                        "client_id": "4UBAFX",
                        "message": "Upstox app enforces a static IP restriction. In your Upstox Developer App console, whitelist public IP 106.76.167.76 or remove the static IP setting.",
                        "public_ip": "106.76.167.76"
                    }
                return {"status": "ERROR", "code": code, "message": msg}
        except Exception:
            pass
        return {"status": "ERROR", "code": res.status_code, "message": res.text[:200]}

    def get_profile(self) -> Dict[str, Any]:
        """Fetches account owner profile from Upstox."""
        if not self.is_configured:
            return {"status": "NOT_CONFIGURED", "message": "Upstox access token not configured in backend/.env"}
        try:
            res = requests.get(f"{self.BASE_URL}/user/profile", headers=self._headers(), timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"status": "SUCCESS", "profile": data.get("data", {})}
            return self._parse_error_response(res)
        except Exception as e:
            logger.error(f"Upstox profile fetch failed: {e}")
            return {"status": "ERROR", "message": str(e)}

    def get_funds(self) -> Dict[str, Any]:
        """Fetches available trading balance / equity margins."""
        if not self.is_configured:
            return {"status": "NOT_CONFIGURED"}
        try:
            res = requests.get(f"{self.BASE_URL}/user/get-funds-and-margin", headers=self._headers(), timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"status": "SUCCESS", "funds": data.get("data", {})}
            return self._parse_error_response(res)
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    def get_holdings(self) -> Dict[str, Any]:
        """Fetches long-term demat holdings from Upstox portfolio."""
        if not self.is_configured:
            return {"status": "NOT_CONFIGURED", "holdings": [], "message": "Upstox access token not configured in .env"}
        try:
            res = requests.get(f"{self.BASE_URL}/portfolio/long-term-holdings", headers=self._headers(), timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"status": "SUCCESS", "holdings": data.get("data", [])}
            return self._parse_error_response(res)
        except Exception as e:
            logger.error(f"Upstox holdings fetch failed: {e}")
            return {"status": "ERROR", "message": str(e)}

    def get_positions(self) -> Dict[str, Any]:
        """Fetches active day/swing positions from Upstox."""
        if not self.is_configured:
            return {"status": "NOT_CONFIGURED", "positions": []}
        try:
            res = requests.get(f"{self.BASE_URL}/portfolio/short-term-positions", headers=self._headers(), timeout=10)
            if res.status_code == 200:
                data = res.json()
                return {"status": "SUCCESS", "positions": data.get("data", [])}
            return self._parse_error_response(res)
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}


upstox_client = UpstoxConnector()


def get_all_services_status() -> Dict[str, Any]:
    """
    Returns unified health and connectivity status across Tapetide MCP and Upstox Demat Gateway.
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
        "upstox": {
            "connected": upstox_client.is_configured,
            "status": "CONFIGURED" if upstox_client.is_configured else "CREDENTIALS_NEEDED",
            "client_id": "4UBAFX" if upstox_client.is_configured else None,
            "description": "Upstox API v2 - Direct Demat Holdings & Portfolio Sync"
        }
    }


def sync_broker_holdings(broker_name: str = "upstox", user_id: str = "default_trader") -> Dict[str, Any]:
    """
    Imports real holdings from Upstox Demat account into PredictaStock's FIFO transaction ledger.
    """
    if not upstox_client.is_configured:
        return {"status": "FAILED", "message": "Upstox access token not configured in backend/.env"}

    data = upstox_client.get_holdings()
    if data.get("status") == "IP_WHITELIST_REQUIRED":
        return {
            "status": "IP_WHITELIST_REQUIRED",
            "message": data["message"],
            "public_ip": data.get("public_ip", "106.76.167.76"),
            "client_id": "4UBAFX",
            "count": 0
        }

    if data.get("status") != "SUCCESS":
        return {
            "status": "FAILED",
            "message": data.get("message", "Could not fetch holdings from Upstox API"),
            "code": data.get("code"),
            "count": 0
        }

    holdings = data.get("holdings", [])
    synced_stocks = []

    for h in holdings:
        sym = h.get("tradingsymbol", "").replace("-EQ", "").strip().upper()
        qty = int(h.get("quantity", 0))
        avg_price = float(h.get("average_price", 0.0))
        if sym and qty > 0 and avg_price > 0:
            current_held = get_current_shares_held(sym, user_id=user_id)
            diff = qty - current_held
            if diff > 0:
                record_transaction(sym, "BUY", avg_price, diff, notes="SYNCED_FROM_UPSTOX", user_id=user_id)
                synced_stocks.append({"symbol": sym, "synced_qty": diff, "avg_price": avg_price})

    return {
        "status": "SUCCESS",
        "broker": "upstox",
        "stocks_synced": synced_stocks,
        "count": len(synced_stocks)
    }


def update_integration_credentials(service: str, creds: Dict[str, str]) -> Dict[str, Any]:
    """
    Updates API keys/tokens for Upstox or Tapetide dynamically and persists to .env.
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
    if svc == "upstox":
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
        "is_configured": upstox_client.is_configured if svc == "upstox" else bool(os.getenv("TAPETIDE_TOKEN"))
    }
