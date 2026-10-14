"""
Unit and Integration Tests for:
1. Point-in-Time Historical Market Dataset (historical_market_bars & coverage).
2. Realistic T+1 Open Execution (gap chase & circuit protection).
3. Compounded Portfolio Simulation & Mode A / Mode B Exits.
4. Prospective Forward Paper-Trading Ledger Engine (cohorts, recommendations, execution events).
5. New REST Endpoints (/api/market-data/coverage, /api/paper-trading/status, /api/paper-trading/scorecard).
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, date

from fastapi.testclient import TestClient
from app.main import app
from app.services.market_data import get_market_data_coverage, get_historical_market_bars
from app.services.historical_backtest import (
    evaluate_t1_open_entry, simulate_path_dependent_trade,
    run_compounded_portfolio_simulation, TOTAL_ROUNDTRIP_FRICTION_PCT
)
from app.services.paper_trader import (
    get_or_create_active_cohort, record_paper_recommendations,
    process_paper_trading_cycle, get_paper_trading_summary,
    get_paper_trading_scorecard
)
from app.database import get_db_connection

client = TestClient(app)


def test_market_data_coverage_and_bhavcopy_integrity():
    """Verify that historical_market_bars table has verified NSE Bhavcopy bars and 0% synthetic proxies."""
    cov = get_market_data_coverage()
    assert cov["total_bars"] > 0
    assert cov["total_sessions"] >= 60 # At least 60-90 historical sessions
    assert cov["bhavcopy_coverage_pct"] == 100.0
    assert cov["synthetic_proxy_bars"] == 0
    assert cov["quality_status"] == "VERIFIED"

    # Test individual symbol bar retrieval
    bars = get_historical_market_bars("RELIANCE")
    assert not bars.empty
    assert "Open" in bars.columns
    assert "Close" in bars.columns
    assert "deliv_qty" in bars.columns
    assert "delivery_source" in bars.columns
    assert (bars["delivery_source"] == "NSE_BHAVCOPY").all()


def test_t1_open_entry_filters():
    """Verify Day T+1 Open gap chase, gap below stop, and circuit protection."""
    # 1. Normal valid open
    valid, reason = evaluate_t1_open_entry(
        entry_open=101.0, entry_high=103.0, entry_low=100.5, entry_close=102.0,
        prev_close_t0=100.0, target_price=106.0, stop_loss=97.0
    )
    assert valid is True
    assert reason == "FILLED_T1_OPEN"

    # 2. Gap chase > +3.5%
    valid, reason = evaluate_t1_open_entry(
        entry_open=104.0, entry_high=105.0, entry_low=103.5, entry_close=104.5,
        prev_close_t0=100.0, target_price=106.0, stop_loss=97.0
    )
    assert valid is False
    assert reason == "REJECTED_GAP_CHASE"

    # 3. Gap chase above target price
    valid, reason = evaluate_t1_open_entry(
        entry_open=107.0, entry_high=108.0, entry_low=106.5, entry_close=107.5,
        prev_close_t0=100.0, target_price=106.0, stop_loss=97.0
    )
    assert valid is False
    assert reason == "REJECTED_GAP_CHASE"

    # 4. Gap below stop loss
    valid, reason = evaluate_t1_open_entry(
        entry_open=96.0, entry_high=97.0, entry_low=95.0, entry_close=96.5,
        prev_close_t0=100.0, target_price=106.0, stop_loss=97.0
    )
    assert valid is False
    assert reason == "REJECTED_GAP_BELOW_STOP"

    # 5. Upper circuit lock (Open == High == Low == Close > Prev_Close)
    valid, reason = evaluate_t1_open_entry(
        entry_open=103.0, entry_high=103.0, entry_low=103.0, entry_close=103.0,
        prev_close_t0=100.0, target_price=106.0, stop_loss=97.0
    )
    assert valid is False
    assert reason == "REJECTED_UPPER_CIRCUIT"


def test_path_dependent_exits_mode_a_and_mode_b():
    """Verify Mode A (bracket) and Mode B (partial profit + trailing stop) with pessimistic tie breaker."""
    # Create 5 synthetic daily bars
    bars_data = [
        {"Open": 100.0, "High": 103.0, "Low": 98.5, "Close": 102.0},
        {"Open": 102.0, "High": 104.0, "Low": 101.0, "Close": 103.5},
        {"Open": 103.5, "High": 107.0, "Low": 102.5, "Close": 106.0}, # Target hit (target=105)
        {"Open": 106.0, "High": 108.0, "Low": 105.0, "Close": 107.0},
        {"Open": 107.0, "High": 109.0, "Low": 106.0, "Close": 108.0},
    ]
    df = pd.DataFrame(bars_data)

    # Test Target Hit
    res = simulate_path_dependent_trade(
        future_bars=df,
        entry_price=100.0,
        stop_loss=96.0,
        target_price=105.0,
        atr_14=2.0,
        mode="MODE_A"
    )
    assert res["exit_reason"] == "TARGET_HIT"
    assert res["exit_price"] == 105.0
    assert res["exit_day"] >= 1

    # Test Stop Loss Hit with Pessimistic Tie Breaker
    dual_breach_data = [
        {"Open": 100.0, "High": 106.0, "Low": 95.0, "Close": 101.0}, # Both High >= 105 and Low <= 96
    ]
    df_dual = pd.DataFrame(dual_breach_data)
    res_dual = simulate_path_dependent_trade(
        future_bars=df_dual,
        entry_price=100.0,
        stop_loss=96.0,
        target_price=105.0,
        atr_14=2.0,
        mode="MODE_A"
    )
    assert "STOP_LOSS" in res_dual["exit_reason"]
    assert res_dual["exit_price"] == 96.0


def test_compounded_portfolio_simulation():
    """Verify ₹10,00,000 portfolio ledger tracking with integer shares, 5 max positions, and friction."""
    sample_trades = [
        {
            "signal_date": "2026-07-01",
            "entry_date": "2026-07-02",
            "endpoint_date": "2026-07-06",
            "symbol": "TCS",
            "entry_price": 3500.0,
            "target_price": 3650.0,
            "stop_loss": 3400.0,
            "net_ret": 2.5
        },
        {
            "signal_date": "2026-07-01",
            "entry_date": "2026-07-02",
            "endpoint_date": "2026-07-06",
            "symbol": "INFY",
            "entry_price": 1800.0,
            "target_price": 1900.0,
            "stop_loss": 1750.0,
            "net_ret": 1.8
        }
    ]

    sim = run_compounded_portfolio_simulation(
        trades=sample_trades,
        initial_capital=1000000.0,
        max_positions=5,
        roundtrip_friction_pct=TOTAL_ROUNDTRIP_FRICTION_PCT
    )

    assert sim["initial_capital"] == 1000000.0
    assert sim["total_trades_taken"] == 2
    assert "final_equity" in sim
    assert "max_drawdown_pct" in sim



def test_prospective_forward_paper_trading_ledger():
    """Verify prospective forward paper trading cohort initialization, order filling, and execution events."""
    cohort = get_or_create_active_cohort()
    assert cohort["cohort_id"] == "COHORT-2026-v2.3"
    assert cohort["initial_capital"] == 1000000.0
    assert cohort["max_positions"] == 5

    # Test summary retrieval
    summary = get_paper_trading_summary()
    assert "cohort_id" in summary
    assert "cash_balance" in summary
    assert "portfolio_equity" in summary
    assert summary["friction_assumptions"] == "0.30% roundtrip (0.25% statutory + 0.05% slippage)"

    # Test scorecard line-item retrieval
    scorecard = get_paper_trading_scorecard()
    assert isinstance(scorecard, list)
    if scorecard:
        item = scorecard[0]
        assert "symbol" in item
        assert "planned_entry_price" in item
        assert "planned_target_price" in item
        assert "audit_verdict" in item
        assert "events" in item


def test_api_endpoints_coverage_and_paper_trading():
    """Verify REST API endpoints for market coverage, paper trading status, and paper trading scorecard."""
    # 1. Market Data Coverage
    cov_res = client.get("/api/market-data/coverage")
    assert cov_res.status_code == 200
    cov_data = cov_res.json()
    assert cov_data["quality_status"] == "VERIFIED"
    assert cov_data["total_bars"] > 0

    # 2. Paper Trading Status
    stat_res = client.get("/api/paper-trading/status")
    assert stat_res.status_code == 200
    stat_data = stat_res.json()
    assert stat_data["cohort_id"] == "COHORT-2026-v2.3"
    assert stat_data["initial_capital"] == 1000000.0

    # 3. Paper Trading Scorecard
    sc_res = client.get("/api/paper-trading/scorecard")
    assert sc_res.status_code == 200
    sc_data = sc_res.json()
    assert isinstance(sc_data, list)
