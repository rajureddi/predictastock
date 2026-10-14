"""
Test Suite: Tapetide Financial Intelligence MCP Gateway & Quota Protection
Validates:
1. Pure Tapetide integration with 50 free calls/day ceiling and 45-call safety threshold.
2. Persistent SQLite caching preventing unnecessary API credit consumption.
3. Elimination of broker connectors (Upstox and Dhan removed per user directive).
4. HTTP Endpoints: /api/integrations/status, /api/intelligence/tapetide/{symbol}, /api/integrations/credentials.
"""
import pytest
import uuid
from fastapi.testclient import TestClient

from app.main import app
from app.auth import register_user
from app.services.tapetide_service import (
    get_quota_status,
    get_calls_used_today,
    get_stock_enrichment,
    get_fii_dii_summary,
    get_options_analytics,
    get_promoter_pledge_status,
    update_tapetide_token
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


def test_tapetide_options_and_pledge():
    """Verify specific quantitative indicators extracted from Tapetide MCP."""
    options = get_options_analytics("RELIANCE")
    assert isinstance(options, dict)
    assert "iv_rank" in options
    assert "iv_percentile" in options

    pledge = get_promoter_pledge_status("RELIANCE")
    assert isinstance(pledge, dict)
    assert "pledged_pct" in pledge
    assert "governance_flag" in pledge


def test_integrations_status_endpoint():
    """Verify /api/integrations/status returns Tapetide schema and excludes Dhan/Upstox."""
    res = client.get("/api/integrations/status")
    assert res.status_code == 200
    data = res.json()
    assert "tapetide" in data
    assert "upstox" not in data
    assert "dhan" not in data
    assert data["tapetide"]["daily_limit"] == 50
    assert data["tapetide"]["connected"] is True


def test_intelligence_tapetide_endpoint():
    """Verify /api/intelligence/tapetide/{symbol} HTTP endpoint."""
    res = client.get("/api/intelligence/tapetide/RELIANCE")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "RELIANCE"
    assert "options" in data
    assert "macro_fii_dii" in data


def test_integrations_credentials_endpoint():
    """Verify authenticated update of Tapetide token via /api/integrations/credentials."""
    u_name = f"int_user_{uuid.uuid4().hex[:6]}"
    reg = register_user(u_name, "Pass123456!", f"{u_name}@test.com")
    auth_header = {"Authorization": f"Bearer {reg['access_token']}"}

    live_token = "tpt_rt_ca1802c8e79a236347b7a3761514b7141032312bc67470e7878eb1fa"
    res = client.post(
        "/api/integrations/credentials",
        json={"credentials": {"token": live_token}},
        headers=auth_header
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "UPDATED"
    assert data["service"] == "tapetide"
    assert data["active"] is True


def test_broker_connectors_completely_removed():
    """Verify broker_connectors module is completely removed and cannot be imported."""
    with pytest.raises(ModuleNotFoundError):
        import app.services.broker_connectors  # noqa: F401


def test_no_unique_calls_per_stock():
    """Verify that get_stock_enrichment does not consume live API calls for arbitrary stocks."""
    calls_before = get_calls_used_today()
    enrichment = get_stock_enrichment("UNKNOWN_TICKER_999")
    calls_after = get_calls_used_today()
    assert calls_after == calls_before, "get_stock_enrichment must not consume live calls on arbitrary stocks"
    assert enrichment["mode"] == "MACRO_ONLY_CONSERVATION"


def test_macro_market_dashboard_endpoint():
    """Verify /api/market/macro-dashboard returns all 4 market feeds and quota status."""
    res = client.get("/api/market/macro-dashboard")
    assert res.status_code == 200
    data = res.json()
    assert "fii_dii" in data
    assert "fpi_sectors" in data
    assert "deliveries" in data
    assert "fno_ban" in data
    assert "quota" in data
    assert data["quota"]["daily_limit"] == 50


def test_fno_ban_endpoint():
    """Verify /api/market/fno-ban returns exchange ban list and near-ban symbols."""
    res = client.get("/api/market/fno-ban")
    assert res.status_code == 200
    data = res.json()
    assert "banned_symbols" in data
    assert "near_ban_symbols" in data
    assert isinstance(data["banned_symbols"], list)


def test_deep_audit_endpoint():
    """Verify /api/intelligence/tapetide/{symbol}/deep-audit returns audited options and governance."""
    res = client.post("/api/intelligence/tapetide/RELIANCE/deep-audit")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "RELIANCE"
    assert data["audited"] is True
    assert "options" in data
    assert "governance" in data


def test_top_recommendations_audit():
    """Verify audit_top_recommendations enriches top 5 recommendations with options IV and pledge."""
    from app.services.tapetide_service import audit_top_recommendations
    mock_recs = [
        {"symbol": "RELIANCE", "name": "Reliance Industries", "expected_target_price": 2800.0},
        {"symbol": "TCS", "name": "Tata Consultancy Services", "expected_target_price": 4000.0}
    ]
    enriched = audit_top_recommendations(mock_recs)
    assert len(enriched) == 2
    assert enriched[0]["tapetide_audited"] is True
    assert "iv_rank" in enriched[0]
    assert "promoter_pledged_pct" in enriched[0]


