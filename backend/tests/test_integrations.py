"""
Test Suite: Tapetide Financial Intelligence MCP & Upstox Demat Gateway
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.tapetide_service import (
    get_quota_status,
    get_calls_used_today,
    get_stock_enrichment,
    get_fii_dii_summary,
    get_options_analytics,
    get_promoter_pledge_status
)
from app.services.broker_connectors import (
    get_all_services_status,
    sync_broker_holdings,
    update_integration_credentials,
    upstox_client
)

client = TestClient(app)


def test_tapetide_quota_manager():
    """Verify daily call limits, safety buffers, and quota status."""
    status = get_quota_status()
    assert status["active"] is True
    assert status["daily_limit"] == 50
    assert status["safe_cap"] == 45
    assert status["calls_remaining"] >= 0
    assert status["status"] in ["OPERATIONAL", "QUOTA_PROTECTED"]


def test_tapetide_cached_enrichment():
    """Verify stock enrichment returns options IV, governance, and macro flows."""
    data = get_stock_enrichment("RELIANCE")
    assert data["symbol"] == "RELIANCE"
    assert data["has_tapetide"] is True
    assert "options" in data
    assert "governance" in data
    assert "macro_fii_dii" in data


def test_all_services_status_endpoint():
    """Verify /api/integrations/status returns Tapetide and Upstox schemas."""
    res = client.get("/api/integrations/status")
    assert res.status_code == 200
    data = res.json()
    assert "tapetide" in data
    assert "upstox" in data
    assert "dhan" not in data
    assert data["tapetide"]["daily_limit"] == 50
    assert data["upstox"]["connected"] is True
    assert data["upstox"]["client_id"] == "4UBAFX"


def test_upstox_connector_configured():
    """Verify Upstox connector initialization and token state."""
    assert upstox_client.is_configured is True
    assert upstox_client.token.startswith("eyJ")


def test_upstox_credentials_update():
    """Verify dynamic update of Upstox credentials."""
    test_token = "eyJhbGciOiJIUzI1NiJ9.test_payload.signature"
    res = update_integration_credentials("upstox", {"access_token": test_token})
    assert res["status"] == "UPDATED"
    assert res["service"] == "upstox"
    assert res["is_configured"] is True
    assert upstox_client.token == test_token

    # Re-apply user's live token
    live_token = "eyJ0eXAiOiJKV1QiLCJrZXlfaWQiOiJza192MS4wIiwiYWxnIjoiSFMyNTYifQ.eyJzdWIiOiI0VUJBRlgiLCJqdGkiOiI2YWNmZTFlMWM1OGY4ZjUzODcyNWRiY2YiLCJpc011bHRpQ2xpZW50IjpmYWxzZSwiaXNQbHVzUGxhbiI6ZmFsc2UsImlzRXh0ZW5kZWQiOnRydWUsImlhdCI6MTc5MjAwODY3MywiaXNzIjoidWRhcGktZ2F0ZXdheS1zZXJ2aWNlIiwiZXhwIjoxODIzNTUxMjAwfQ.WtP1s2d0TZjwzQaC-0MGLG8NTUeCQZDNHPSD_ZX7eEI"
    update_integration_credentials("upstox", {"access_token": live_token})
    assert upstox_client.token == live_token
