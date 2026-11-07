"""Execution, corporate-action adjustment, and the target that used to be invented."""
from datetime import date

import pandas as pd

from app.services.indicators import compute_mathematical_5d_range
from app.services.market_data import back_adjust_corporate_actions
from app.services.trade_simulator import execute_long_bracket


def _bars(rows):
    frame = pd.DataFrame(rows)
    return (
        frame["Open"].to_numpy(float),
        frame["High"].to_numpy(float),
        frame["Low"].to_numpy(float),
        frame["Close"].to_numpy(float),
    )


def test_gap_through_the_open_is_not_a_fill():
    opens, highs, lows, closes = _bars([
        {"Open": 110.0, "High": 112.0, "Low": 109.0, "Close": 111.0},
        {"Open": 111.0, "High": 113.0, "Low": 110.0, "Close": 112.0},
    ])
    result = execute_long_bracket(opens, highs, lows, closes, 0, 2, signal_close=100.0, stop_price=97.0, target_price=106.0)
    assert result["status"] == "REJECTED"
    assert result["reason"] == "GAP_CHASE"


def test_same_bar_stop_and_target_takes_the_stop():
    opens, highs, lows, closes = _bars([
        {"Open": 100.0, "High": 112.0, "Low": 88.0, "Close": 105.0},
        {"Open": 105.0, "High": 106.0, "Low": 104.0, "Close": 105.0},
    ])
    result = execute_long_bracket(opens, highs, lows, closes, 0, 2, signal_close=100.0, stop_price=90.0, target_price=110.0, turnover_inr=2e9)
    assert result["status"] == "FILLED"
    assert result["exit_reason"] == "STOP"
    assert result["net_return_pct"] < 0


def test_extreme_split_adjusts_when_the_gap_session_was_never_stored(monkeypatch):
    monkeypatch.setattr("app.services.market_data._ingested_eod_dates", lambda: set())
    frame = pd.DataFrame(
        {
            "Open": [1000.0, 110.0],
            "High": [1010.0, 115.0],
            "Low": [990.0, 105.0],
            "Close": [1000.0, 110.0],
            "Volume": [1000.0, 9000.0],
            "prev_close": [990.0, 100.0],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-05"]),
    )
    adjusted = back_adjust_corporate_actions(frame)
    assert abs(adjusted["Close"].iloc[0] - 100.0) < 1.0
    assert abs(adjusted["Close"].iloc[1] - 110.0) < 1.0
    assert not bool(adjusted["unexplained_jump"].iloc[-1])


def test_a_small_gap_is_not_rewritten_just_because_a_session_is_missing(monkeypatch):
    monkeypatch.setattr("app.services.market_data._ingested_eod_dates", lambda: set())
    frame = pd.DataFrame(
        {
            "Open": [100.0, 103.0],
            "High": [101.0, 104.0],
            "Low": [99.0, 102.0],
            "Close": [100.0, 103.0],
            "Volume": [1000.0, 1000.0],
            "prev_close": [99.0, 97.0],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-05"]),
    )
    adjusted = back_adjust_corporate_actions(frame)
    assert abs(adjusted["Close"].iloc[0] - 100.0) < 0.01


def test_target_is_not_invented_when_the_atr_move_is_tiny():
    cone = compute_mathematical_5d_range(
        cmp=100.0, atr=0.4, vol_5d_pct=1.0, signal="Bullish", rsi=60.0,
        sma_20=99.0, macd_hist=0.2, cmf_20=0.1, vol_surge=1.2, rs_20d=3.0,
        macro_regime={"is_valid": True, "is_bullish": True},
    )
    assert cone["expected_appreciation_pct"] < 1.2


def test_week_signal_helper_still_bounds_a_holiday_monday():
    from app.services.weekly_engine_backtest import iter_week_signals
    assert iter_week_signals(date(2026, 1, 26), date(2026, 1, 31)) == [(date(2026, 1, 27), date(2026, 1, 31))]
