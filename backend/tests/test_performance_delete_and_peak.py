"""
Unit and API integration tests for:
1. Performance & Strategy individual stock deletion (paper recommendation & scorecard evaluation).
2. Live Current Market Price (CMP / actual price now) in audit scorecards.
3. Actual 5D Peak price integrity (ensuring real market high, not predicted target price).
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db_connection
from app.services.paper_trader import (
    record_paper_recommendations,
    get_paper_trading_scorecard,
    delete_paper_recommendation,
    delete_paper_recommendations_by_symbol,
    DEFAULT_COHORT_ID
)
from app.services.backtester import (
    get_forecast_scorecard,
    delete_forecast_evaluation,
    delete_forecast_evaluations_by_symbol
)

client = TestClient(app)


def test_scorecard_has_current_price_and_peak_integrity():
    """Verify that scorecard provides current_price and does not falsely mirror planned_target_price as peak."""
    sc = get_paper_trading_scorecard()
    assert isinstance(sc, list)
    if sc:
        for item in sc:
            assert "current_price" in item
            assert "actual_peak_price" in item
            if item["status"] in ("PENDING_OPEN", "REJECTED"):
                # Must never fabricate predicted target price as actual peak
                assert item["actual_peak_price"] is None


def test_delete_paper_recommendation_api():
    """Verify deleting an individual paper recommendation via DELETE endpoint."""
    conn = get_db_connection()
    cursor = conn.cursor()
    test_id = "test-del-rec-001"
    cursor.execute("""
    INSERT OR REPLACE INTO paper_recommendations (
        id, cohort_id, symbol, signal_date, signal_price, signal_direction,
        composite_score, model_version, planned_entry_price, planned_stop_loss,
        planned_target_price, status, created_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        test_id, DEFAULT_COHORT_ID, "TESTSYM", "2026-10-15", 500.0, "BULLISH",
        70.0, "v2.3-HighAlphaQuant", 500.0, 480.0, 530.0, "PENDING_OPEN", "2026-10-15T09:00:00"
    ))
    conn.commit()
    conn.close()

    # Call delete endpoint
    del_res = client.delete(f"/api/paper-trading/recommendation/{test_id}")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted"] is True
    assert del_data["symbol"] == "TESTSYM"

    # Verify gone from DB
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM paper_recommendations WHERE id = ?", (test_id,))
    assert c.fetchone() is None
    conn.close()


def test_delete_scorecard_evaluation_api():
    """Verify deleting a completed forecast evaluation via DELETE endpoint."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, symbol FROM forecast_evaluations LIMIT 1")
    row = cursor.fetchone()
    conn.close()

    assert row is not None, "At least one evaluation should exist in DB"
    test_id = row["id"]
    test_sym = row["symbol"]

    del_res = client.delete(f"/api/scorecard/evaluation/{test_id}")
    assert del_res.status_code == 200
    del_data = del_res.json()
    assert del_data["deleted"] is True
    assert del_data["symbol"] == test_sym

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM forecast_evaluations WHERE id = ?", (test_id,))
    assert c.fetchone() is None
    conn.close()
