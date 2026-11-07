"""
Unit tests for the Quantitative ML Alpha Model (v5).
Validates feature extraction, calibrated inference, and regime gating.
"""
import pandas as pd
import numpy as np

from app.services.ml_alpha_model import (
    FEATURE_NAMES,
    extract_ml_features_from_df,
    predict_calibrated_win_rate,
)
from app.services.indicators import compute_mathematical_5d_range


def _synthetic_bars(num_bars: int = 150) -> pd.DataFrame:
    """Creates a deterministic upward trending price history for testing."""
    dates = pd.date_range("2026-01-01", periods=num_bars, freq="B")
    base_price = 1000.0 + np.linspace(0, 150, num_bars)
    
    df = pd.DataFrame({
        "Open": base_price - 1.0,
        "High": base_price + 5.0,
        "Low": base_price - 5.0,
        "Close": base_price,
        "Volume": [100000 + i * 500 for i in range(num_bars)],
        "deliv_per": [45.0 + (i % 10) for i in range(num_bars)],
    }, index=dates.strftime("%Y-%m-%d"))
    return df


def test_feature_extraction_names_and_completeness():
    df = _synthetic_bars(150)
    macro = {"is_valid": True, "is_bullish": True, "nifty_dist_sma50": 1.5, "return_20d_pct": 2.5}
    features = extract_ml_features_from_df(df, nifty_context=macro)
    
    assert set(features.keys()) == set(FEATURE_NAMES)
    for feat in FEATURE_NAMES:
        val = features[feat]
        assert not np.isnan(val), f"Feature {feat} contains NaN"
        assert isinstance(val, (int, float)), f"Feature {feat} is not numeric"


def test_predict_calibrated_win_rate_shape_and_range():
    df = _synthetic_bars(150)
    features = extract_ml_features_from_df(df)
    
    bull_res = predict_calibrated_win_rate(features, is_nifty_bullish=True)
    assert "win_probability_pct" in bull_res
    assert "is_trade_eligible" in bull_res
    assert "setup_grade" in bull_res
    assert 15.0 <= bull_res["win_probability_pct"] <= 85.0
    assert bull_res["setup_grade"] in ["A+", "A", "B", "C"]
    
    # Bearish market regime must revoke eligibility regardless of stock features
    bear_res = predict_calibrated_win_rate(features, is_nifty_bullish=False)
    assert bear_res["is_trade_eligible"] is False


def test_barrier_physics_in_indicators():
    # Test calibrated triple-barrier mode with ML win probability
    res = compute_mathematical_5d_range(
        cmp=1000.0,
        atr=20.0,
        vol_5d_pct=2.5,
        signal="Bullish Setup",
        rsi=55.0,
        sma_20=980.0,
        sma_50=950.0,
        ml_win_prob_pct=65.0,
        macro_regime={"is_valid": True, "is_bullish": True},
    )
    
    # In ML mode:
    # Target is ~1.25x ATR * prob_scalar (~+2.5% to +3.0%), not +8% to +10%
    target_gain_pct = (res["expected_target_price"] - 1000.0) / 1000.0 * 100.0
    assert 1.5 <= target_gain_pct <= 4.0
    
    # Stop loss gives ~1.5x ATR breathing room against noise
    stop_dist_pct = (1000.0 - res["stop_loss"]) / 1000.0 * 100.0
    assert 2.5 <= stop_dist_pct <= 4.0
    assert res["direction"] == "BULLISH"
    assert res["win_probability_pct"] == 65.0
