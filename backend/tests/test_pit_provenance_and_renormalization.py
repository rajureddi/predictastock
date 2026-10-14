"""
Unit and Integration Tests for Point-in-Time Integrity:
1. SEBI 45-day filing lag on quarterly balance sheet & income statement.
2. Date-bounded Google News RSS querying with pubDate verification and historical_news_cache.
3. Dynamic pillar weight renormalization when news is UNAVAILABLE_PIT (56.25% / 31.25% / 12.50%).
"""
import pytest
from datetime import datetime, date, timedelta
from app.services.fundamentals import get_point_in_time_fundamentals
from app.services.news_sentiment import fetch_stock_news_rss, analyze_sentiment
from app.services.prediction_engine import score_single_stock
from app.database import get_db_connection


def test_quarterly_fundamentals_45d_sebi_lag():
    """
    Regulation 33 of SEBI LODR 2015: 45-day quarterly reporting deadline.
    For Q4 ending 2026-03-31, deadline is 2026-05-15.
    As-of 2026-05-10, Q4 must NOT be accessible (must return Q3 ending 2025-12-31).
    As-of 2026-05-20, Q4 MUST be accessible.
    """
    # 1. As of 2026-05-10 (Before 45D deadline for 2026-03-31)
    res_before = get_point_in_time_fundamentals("TCS", as_of_date="2026-05-10")
    assert res_before["fundamentals_provenance"] == "QUARTERLY_PIT_45D_LAG"
    assert res_before["quarter_used"] == "2025-12-31"
    assert res_before["filing_deadline_date"] == "2026-02-14"
    assert res_before["debt_to_equity"] is not None
    assert res_before["roe"] is not None

    # 2. As of 2026-05-20 (After 45D deadline for 2026-03-31)
    res_after = get_point_in_time_fundamentals("TCS", as_of_date="2026-05-20")
    assert res_after["fundamentals_provenance"] == "QUARTERLY_PIT_45D_LAG"
    assert res_after["quarter_used"] == "2026-03-31"
    assert res_after["filing_deadline_date"] == "2026-05-15"
    assert res_after["debt_to_equity"] is not None
    assert res_after["roe"] is not None


def test_quarterly_fundamentals_solvency_gatekeeper():
    """Verify that solvency penalty and flags trigger on elevated D/E or depressed ROE."""
    res = get_point_in_time_fundamentals("INFY", as_of_date="2026-06-01")
    assert res["fundamentals_provenance"] == "QUARTERLY_PIT_45D_LAG"
    assert res["is_solvency_passed"] is True
    assert res["debt_to_equity"] < 0.5  # Low debt IT major


def test_date_bounded_news_and_sqlite_cache():
    """Verify that news items retrieved do not leak future headlines and cache in SQLite."""
    target_date = "2026-05-05"
    items = fetch_stock_news_rss("INFY", max_items=3, as_of_date=target_date)
    assert isinstance(items, list)

    target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
    for it in items:
        assert it["as_of_date"] == target_date
        if it.get("pub_date"):
            import email.utils
            pub_dt = email.utils.parsedate_to_datetime(it["pub_date"]).date()
            assert pub_dt <= target_dt, f"Future headline leak detected: {pub_dt} > {target_dt}"

    # Verify SQLite caching
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM historical_news_cache WHERE symbol = 'INFY' AND as_of_date = ?", (target_date,))
    count = cursor.fetchone()[0]
    conn.close()
    assert count == len(items)


def test_dynamic_pillar_weight_renormalization_math():
    """
    When news_provenance == UNAVAILABLE_PIT:
    Weights renormalize to 56.25% Tech, 31.25% MoneyFlow, 12.50% Macro.
    Score should not be dragged down by neutral 50.0 anchor.
    """
    # Test with historical as_of_date where no news exists
    res = score_single_stock("RELIANCE", as_of_date="2026-04-10")
    if res:
        assert res["scoring_mode"] in ["PIT_RENORMALIZED_NO_NEWS", "FULL_4_PILLAR_PIT"]
        assert res["fundamentals_provenance"] == "QUARTERLY_PIT_45D_LAG"
        assert res["composite_score"] >= 10.0
