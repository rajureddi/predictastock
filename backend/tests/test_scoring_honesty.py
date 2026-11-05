"""Debt is a ratio, the 92 is a conviction score, and expectancy uses a measured hit rate."""
from app.services.fundamentals import yahoo_debt_to_equity
from app.services.indicators import compute_mathematical_5d_range


def test_yahoo_debt_percent_between_2_and_10_is_a_fraction_of_equity():
    assert yahoo_debt_to_equity(9.83) == 0.0983
    assert yahoo_debt_to_equity(2.5) == 0.025
    assert yahoo_debt_to_equity(150) == 1.5


def test_expectancy_uses_the_measured_hit_rate_not_the_conviction_score():
    out = compute_mathematical_5d_range(
        cmp=100.0,
        atr=2.0,
        vol_5d_pct=3.0,
        signal="Bullish",
        rsi=60.0,
        sma_20=98.0,
        cmf_20=0.2,
        rs_20d=8.0,
        macro_regime={"is_valid": True, "is_bullish": True},
        empirical_hit_rate=44.8,
    )
    assert out["conviction_score"] == out["win_probability_pct"]
    assert out["conviction_score"] >= 80
    gain = out["expected_appreciation_pct"]
    risk = (100.0 - out["stop_loss"]) / 100.0 * 100.0
    measured = round((0.448 * gain) - ((1.0 - 0.448) * risk), 2)
    claimed = round((out["conviction_score"] / 100.0 * gain) - ((1.0 - out["conviction_score"] / 100.0) * risk), 2)
    assert out["empirical_hit_rate_pct"] == 44.8
    assert out["calibrated_expectancy_pct"] == measured
    assert out["calibrated_expectancy_pct"] != claimed
