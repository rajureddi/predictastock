"""
Test Suite: Tapetide Financial Intelligence MCP & Broker Connectors (Dhan & Upstox)
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
    update_integration_credentials
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
    """Verify /api/integrations/status returns Tapetide, Dhan, and Upstox schemas."""
    res = client.get("/api/integrations/status")
    assert res.status_code == 200
    data = res.json()
    assert "tapetide" in data
    assert "dhan" in data
    assert "upstox" in data
    assert data["tapetide"]["daily_limit"] == 50
    assert "status" in data["tapetide"]


def test_broker_credentials_update():
    """Verify dynamic update of broker credentials."""
    # Test Dhan update
    res_dhan = update_integration_credentials("dhan", {"client_id": "TEST_ID_123", "access_token": "TEST_TOKEN_456"})
    assert res_dhan["status"] == "UPDATED"
    assert res_dhan["service"] == "dhan"
    assert res_dhan["is_configured"] is True

    # Test Upstox update
    res_upstox = update_integration_credentials("upstox", {"api_key": "TEST_KEY_123", "access_token": "TEST_TOKEN_789"})
    assert res_upstox["status"] == "UPDATED"
    assert res_upstox["service"] == "upstox"
    assert res_upstox["is_configured"] is True
