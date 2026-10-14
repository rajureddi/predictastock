"""
Comprehensive Integration Test Suite: Phases 1, 2, 3, and 4
Verifies all institutional-grade criteria demanded in the critical review:
- Phase 1: Zero synthetic fallbacks, two-sided ATR volatility cones, portfolio FIFO integrity.
- Phase 2: Verified fundamentals from financial statements, corporate actions conservation.
- Phase 3: Point-in-time historical backtest against 3 baselines, 0.15% friction.
- Phase 4: User authentication, portfolio partition isolation, health monitoring, report dispatcher.
"""
import pytest
from datetime import date, datetime, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db_connection
from app.services.fundamentals import get_company_fundamentals
from app.services.corporate_actions import record_corporate_action, apply_pending_corporate_actions
from app.services.historical_backtest import run_historical_backtest
from app.services.email_dispatcher import dispatch_morning_report
from app.auth import register_user, authenticate_user

client = TestClient(app)


def test_phase1_two_sided_volatility_cones():
    """Verify that predictions compute mathematically sound two-sided ATR cones."""
    from app.services.indicators import compute_mathematical_5d_range
    # Test Bullish scenario
    bull = compute_mathematical_5d_range(cmp=1000.0, atr=20.0, vol_5d_pct=2.0, signal=0.6, rsi=60.0)
    assert bull["direction"] == "BULLISH"
    assert bull["expected_target_price"] > 1000.0
    assert bull["expected_range_high"] > bull["expected_target_price"]
    assert bull["expected_range_low"] < 1000.0

    # Test Bearish scenario
    bear = compute_mathematical_5d_range(cmp=1000.0, atr=20.0, vol_5d_pct=2.0, signal=-0.6, rsi=40.0)
    assert bear["direction"] == "BEARISH"
    assert bear["expected_target_price"] < 1000.0
    assert bear["expected_range_low"] < bear["expected_target_price"]
    assert bear["expected_range_high"] > 1000.0


def test_phase1_portfolio_strict_rejection():
    """Verify that selling more shares than held or negative prices are strictly rejected with HTTP 400."""
    # Attempt negative price
    res_neg = client.post("/api/portfolio/transaction", json={
        "symbol": "TCS",
        "transaction_type": "BUY",
        "price": -100.0,
        "quantity": 10,
        "transaction_date": "2026-10-10"
    })
    assert res_neg.status_code == 400

    # Attempt oversell
    res_oversell = client.post("/api/portfolio/transaction", json={
        "symbol": "UNOWNED_STOCK_XYZ",
        "transaction_type": "SELL",
        "price": 500.0,
        "quantity": 9999,
        "transaction_date": "2026-10-10"
    })
    assert res_oversell.status_code == 400


def test_phase2_fundamentals_ingestion():
    """Verify company fundamentals are ingested from real financial statements and persisted."""
    funds = get_company_fundamentals("TCS")
    assert funds is not None
    assert funds["symbol"] == "TCS"
    assert funds["pe_ratio"] is not None and funds["pe_ratio"] > 0
    assert funds["roe"] is not None
    assert "data_source" in funds
    assert "Financial Statements" in funds["data_source"]

    # API endpoint check
    res = client.get("/api/fundamentals/TCS")
    assert res.status_code == 200
    data = res.json()
    assert data["symbol"] == "TCS"
    assert "debt_to_equity" in data


def test_phase2_corporate_actions_conservation():
    """Verify corporate action split adjusts lot quantities while strictly conserving total cost basis."""
    import uuid
    test_user_id = f"test_ca_trader_{uuid.uuid4().hex[:6]}"
    
    # 1. Buy 10 shares of TESTSTOCK at Rs. 1000 (Cost basis = Rs. 10,000)
    from app.services.portfolio import record_transaction, compute_portfolio_fifo
    buy_tx = record_transaction(
        symbol="TESTSTOCK",
        transaction_type="BUY",
        price=1000.0,
        quantity=10,
        transaction_date="2026-01-01",
        user_id=test_user_id
    )
    initial_portfolio = compute_portfolio_fifo(user_id=test_user_id)
    initial_holding = [h for h in initial_portfolio["holdings"] if h["symbol"] == "TESTSTOCK"][0]
    assert initial_holding["quantity"] == 10
    assert initial_holding["total_invested"] == 10000.0

    # 2. Record 2:1 Stock Split (Adjustment factor 2.0)
    ca_res = record_corporate_action(
        symbol="TESTSTOCK",
        action_type="SPLIT",
        ex_date=date.today().isoformat(),
        ratio="2:1",
        adjustment_factor=2.0
    )
    assert ca_res["action_type"] == "SPLIT"

    # 3. Apply corporate actions
    applied_cnt = apply_pending_corporate_actions()
    assert applied_cnt >= 1

    # 4. Verify Conservation: Shares should double to 20, price halved to 500, total basis remains 10,000
    updated_portfolio = compute_portfolio_fifo(user_id=test_user_id)
    updated_holding = [h for h in updated_portfolio["holdings"] if h["symbol"] == "TESTSTOCK"][0]
    assert updated_holding["quantity"] == 20
    assert updated_holding["avg_purchase_price"] == 500.0
    assert round(updated_holding["total_invested"], 2) == 10000.0


def test_phase3_historical_backtest_endpoint():
    """Verify point-in-time historical backtest endpoint returns 3 baselines, scorecard, and report."""
    res = client.get("/api/backtest/latest")
    assert res.status_code == 200
    data = res.json()
    assert "scorecard" in data
    assert "markdown_report_path" in data
    assert "backtest_data" in data
    bt = data["backtest_data"]
    assert bt is not None
    sample_size = bt.get("total_samples") or bt.get("sample_size")
    assert sample_size > 0
    assert "baselines_comparison" in bt
    baselines = bt["baselines_comparison"]
    assert "predictastock_multi_factor" in baselines
    assert "nifty_50_benchmark" in baselines
    assert "trend_20dma_momentum" in baselines
    assert "no_change_zero_return" in baselines
    perf = bt.get("model_performance") or bt.get("metrics") or {}
    assert "bull_market_hit_rate_pct" in perf
    assert "bear_market_hit_rate_pct" in perf



def test_phase4_user_registration_and_portfolio_isolation():
    """Verify user registration, login, and strict portfolio isolation across accounts."""
    import uuid
    rand_suffix = uuid.uuid4().hex[:6]
    u1_name = f"trader_alpha_{rand_suffix}"
    u2_name = f"trader_beta_{rand_suffix}"
    pwd = "InstitutionalPassword123"

    # 1. Register User 1
    r1 = client.post("/api/auth/register", json={"username": u1_name, "password": pwd, "email": f"{u1_name}@fund.com"})
    assert r1.status_code == 200
    u1_data = r1.json()["user"]
    u1_key = u1_data["api_key"]
    u1_id = u1_data["user_id"]

    # 2. Register User 2
    r2 = client.post("/api/auth/register", json={"username": u2_name, "password": pwd, "email": f"{u2_name}@fund.com"})
    assert r2.status_code == 200
    u2_data = r2.json()["user"]
    u2_key = u2_data["api_key"]
    u2_id = u2_data["user_id"]

    # 3. User 1 buys INFY
    tx1 = client.post(
        "/api/portfolio/transaction",
        json={"symbol": "INFY", "transaction_type": "BUY", "price": 1500.0, "quantity": 10, "transaction_date": "2026-10-01"},
        headers={"X-API-Key": u1_key}
    )
    assert tx1.status_code == 200

    # 4. User 2 checks portfolio: MUST BE EMPTY (0 holdings)
    p2 = client.get("/api/portfolio", headers={"X-API-Key": u2_key}).json()
    assert len(p2["holdings"]) == 0
    assert p2["total_invested"] == 0.0

    # 5. User 1 checks portfolio: has 10 shares of INFY
    p1 = client.get("/api/portfolio", headers={"X-API-Key": u1_key}).json()
    assert len(p1["holdings"]) == 1
    assert p1["holdings"][0]["symbol"] == "INFY"
    assert p1["holdings"][0]["quantity"] == 10


def test_phase4_health_and_observability():
    """Verify /api/health distinguishes system health, data health, and forecast health."""
    res = client.get("/api/health")
    assert res.status_code == 200
    health = res.json()
    assert health["status"] == "HEALTHY"
    assert "system_health" in health
    assert "data_health" in health
    assert "forecast_health" in health
    assert health["system_health"]["database"] == "CONNECTED"
    assert health["system_health"]["tables_intact"] is True
    assert health["data_health"]["quote_engine_mode"] == "Strict Verification (Zero Synthetic Fallbacks)"


def test_phase4_report_dispatch_auditing():
    """Verify report dispatch executes, logs audit trail, and marks daily_reports status."""
    res = client.post("/api/reports/dispatch", json={"recipient_email": "auditor@institutional.com"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ["DELIVERED", "LOCAL_AUDITED", "FAILED_LOCAL_LOGGED"]
    assert data["recipient"] == "auditor@institutional.com"


def test_recommendations_reset_and_stock_rotation():
    """Verify POST /api/recommendations/reset purges and generates fresh rotated stocks across sectors."""
    res = client.post("/api/recommendations/reset")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "RESET_COMPLETED"
    assert data["generated_count"] >= 3
    recs = data["recommendations"]
    assert len(recs) >= 3
    symbols = [r["symbol"] for r in recs]
    # Check that all symbols in this batch are strictly distinct
    assert len(symbols) == len(set(symbols))
    # Check that each recommendation contains required mathematical 5-day forecast fields
    for r in recs:
        assert "expected_target_price" in r
        assert "expected_range_low" in r
        assert "expected_range_high" in r
        assert "expected_appreciation_pct" in r
        assert "risk_level" in r
        assert "sector" in r


def test_phase1_high_alpha_indicators_and_delivery():
    """Verify CMF, MFI, Delivery extraction, and ATR Stop-Loss computation."""
    import pandas as pd
    import numpy as np
    from app.services.indicators import (
        calculate_cmf, calculate_mfi, calculate_delivery_metrics,
        compute_all_indicators, compute_mathematical_5d_range
    )

    # 1. Test CMF with High == Low zero-division safety
    flat_df = pd.DataFrame({
        "High": [100.0] * 25,
        "Low": [100.0] * 25,
        "Close": [100.0] * 25,
        "Volume": [10000] * 25
    })
    cmf_flat = calculate_cmf(flat_df, 20)
    assert isinstance(cmf_flat, float)
    assert cmf_flat == 0.0

    # 2. Test MFI calculation
    sample_df = pd.DataFrame({
        "High": [100.0 + i for i in range(25)],
        "Low": [98.0 + i for i in range(25)],
        "Close": [99.0 + i for i in range(25)],
        "Volume": [50000 + i * 1000 for i in range(25)]
    })
    mfi_val = calculate_mfi(sample_df, 14)
    assert 0.0 <= mfi_val <= 100.0

    # 3. Test Delivery extraction: with simulated Bhavcopy columns
    bhav_df = sample_df.copy()
    bhav_df["DELIV_QTY"] = [30000 + i * 500 for i in range(25)]
    bhav_df["DELIV_PER"] = [55.0] * 25
    deliv_res = calculate_delivery_metrics(bhav_df)
    assert deliv_res["is_bhavcopy_actual"] is True
    assert deliv_res["deliv_source"] == "NSE Bhavcopy EOD"
    assert deliv_res["deliv_per"] == 55.0
    assert deliv_res["deliv_surge"] > 0

    # 4. Test Delivery clean fallback to CMF + MFI
    fallback_res = calculate_delivery_metrics(sample_df, cmf_20=0.15, mfi_14=65.0, vol_surge=1.3)
    assert fallback_res["is_bhavcopy_actual"] is False
    assert "Clean Fallback" in fallback_res["deliv_source"]
    assert 20.0 <= fallback_res["deliv_per"] <= 85.0
    assert fallback_res["deliv_surge"] > 0

    # 5. Test Stop-Loss in ATR range
    range_res = compute_mathematical_5d_range(
        cmp=1500.0, atr=30.0, vol_5d_pct=3.0, signal="Bullish", rsi=60.0
    )
    assert range_res["direction"] == "BULLISH"
    assert "stop_loss" in range_res
    assert range_res["stop_loss"] < 1500.0
    assert range_res["stop_loss"] == round(1500.0 - 30.0, 2)
    assert "BUY" in range_res["action_label"]


def test_phase2_llm_agent_metrics_wiring():
    """Verify that llm_agent committee thesis explicitly cites Money Flow and Stop-Loss."""
    from app.services.llm_agent import run_multi_agent_analyst_team

    sample_stock = {
        "symbol": "TCS",
        "name": "Tata Consultancy Services Ltd",
        "sector": "Information Technology",
        "reference_price": 3500.0,
        "atr_14": 50.0,
        "stop_loss": 3450.0,
        "rsi_14": 58.0,
        "cmf_20": 0.12,
        "mfi_14": 62.0,
        "vol_surge": 1.45,
        "vol_squeeze": 0.88,
        "deliv_per": 54.0,
        "deliv_surge": 1.40,
        "rs_20d": 3.5,
        "sector_rs": 2.1,
        "direction": "BULLISH",
        "action_label": "BUY / ACCUMULATE (5-Day Swing)",
        "volatility_5d_pct": 3.2,
        "sentiment_score": 0.35,
        "sentiment_label": "Bullish",
        "expected_target_price": 3620.0,
        "expected_range_low": 3420.0,
        "expected_range_high": 3650.0,
        "expected_appreciation_pct": 3.43
    }

    result = run_multi_agent_analyst_team(sample_stock)
    assert "analysts" in result
    thesis = result["debate"]["synthesis"]
    thesis_norm = thesis.lower().replace("\u2011", "-")
    assert "cmf" in thesis_norm or "money flow" in thesis_norm
    assert "stop-loss" in thesis_norm or "stop loss" in thesis_norm
    assert "3450" in thesis

    trade_plan = result["debate"]["trade_plan"]
    assert "institutional_money_flow" in trade_plan
    assert "3450" in trade_plan["downside_invalidation"]


def test_phase4_t5_scorecard_footer():
    """Verify that T+5 audit scorecard footer produces 3-line summary with friction deduction."""
    from app.services.email_dispatcher import get_t5_scorecard_footer
    from app.config import ROUNDTRIP_FRICTION_PCT

    scorecard = get_t5_scorecard_footer()
    assert "line1" in scorecard
    assert "line2" in scorecard
    assert "line3" in scorecard
    assert "three_line_text" in scorecard
    assert "footer_html" in scorecard

    assert "LAST WEEK'S 5-DAY PICKS WIN RATE" in scorecard["line1"].upper()
    assert str(ROUNDTRIP_FRICTION_PCT) in scorecard["line1"]
    lines = scorecard["three_line_text"].strip().split("\n")
    assert len(lines) == 3


def test_nse_bhavcopy_caching_and_delivery_surge():
    """Verify official NSE EOD Bhavcopy caching, symbol mapping, and accurate deliv_surge calculation."""
    from app.services.market_data import load_nse_bhavcopy, get_nse_bhavcopy_for_symbol
    from app.services.indicators import calculate_delivery_metrics
    import pandas as pd

    # 1. Test loader and caching
    bhav_map = load_nse_bhavcopy()
    assert isinstance(bhav_map, dict)
    assert len(bhav_map) > 0

    # 2. Test O(1) resolution for both 'RELIANCE' and 'RELIANCE.NS'
    rel = get_nse_bhavcopy_for_symbol("RELIANCE")
    rel_ns = get_nse_bhavcopy_for_symbol("RELIANCE.NS")
    assert rel is not None
    assert rel_ns is not None
    assert rel["symbol"] == rel_ns["symbol"]
    assert rel["delivery_source"] == "NSE_BHAVCOPY"
    assert rel["deliv_per"] >= 0.0
    assert rel["deliv_qty"] >= 0.0

    # 3. Test accurate deliv_surge calculation:
    # expected_normal_deliv = sma_vol_20 * 0.45
    # deliv_surge = round(deliv_qty / max(expected_normal_deliv, 1.0), 2)
    fake_bhav = {
        "symbol": "TESTSYM",
        "deliv_qty": 90000.0,
        "deliv_per": 60.0,
        "is_bhavcopy_actual": True,
        "delivery_source": "NSE_BHAVCOPY"
    }
    dummy_df = pd.DataFrame({"Close": [100.0] * 20, "Volume": [200000.0] * 20})
    res = calculate_delivery_metrics(dummy_df, bhavcopy_data=fake_bhav, sma_vol_20=200000.0)
    
    # expected_normal_deliv = 200,000 * 0.45 = 90,000
    # deliv_surge = 90,000 / 90,000 = 1.0
    assert res["deliv_surge"] == 1.0
    assert res["deliv_per"] == 60.0
    assert res["is_bhavcopy_actual"] is True


def test_dynamic_bhavcopy_universe_selection():
    """Verify that dynamic Dual-Sleeve Bhavcopy pre-screener selects Liquid Leaders and Outlier Breakouts."""
    from app.data.nifty_constituents import get_dynamic_bhavcopy_universe

    universe = get_dynamic_bhavcopy_universe(min_turnover_cr=10.0, min_price=50.0, target_count=250)
    assert isinstance(universe, list)
    assert len(universe) >= 50
    assert len(universe) <= 250

    sleeve_types = {item.get("sleeve") for item in universe}
    assert "LIQUID_LEADER" in sleeve_types

    # Verify attributes across all items
    for item in universe:
        assert "symbol" in item
        assert "turnover_lacs" in item
        assert "close_price" in item
        if item.get("sleeve") == "LIQUID_LEADER":
            assert item["turnover_lacs"] >= 1000.0  # >= Rs 10 Crore
            assert item["close_price"] >= 50.0
        elif item.get("sleeve") == "OUTLIER_SURGE":
            assert item["turnover_lacs"] >= 500.0   # >= Rs 5 Crore
            assert item["close_price"] >= 30.0
            assert item.get("deliv_per", 0.0) >= 40.0




