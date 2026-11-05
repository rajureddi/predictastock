"""Debt is a ratio, the 92 is a conviction score, and expectancy uses a measured hit rate."""
from app.services.fundamentals import yahoo_debt_to_equity
from app.services.indicators import compute_mathematical_5d_range, passes_benchmark_swing
from app.services.prediction_engine import blend_pillar_score, choose_empirical_hit_rate


def _cache(buckets, tails, overall=32.7):
    return {
        "overall": overall,
        "source": "forecast_evaluations direction_correct",
        "sample_size": 107,
        "buckets": buckets,
        "tails": tails,
        "outcome": "direction_correct",
    }


def _band(low, high, rate, sample, source):
    return {"low": low, "high": high, "rate": rate, "sample_size": sample, "source": source, "outcome": "direction_correct"}


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


def test_a_thin_upper_band_inherits_the_full_band_below_when_the_blend_is_worse():
    """An 86 must not be priced off the all-rows average, or off a 70+ blend dragged down by 37 bad rows."""
    cache = _cache(
        buckets=[_band(70, 80, 44.4, 54, "composite 70-80")],
        tails={
            "80+": _band(80, 100, 10.8, 37, "composite 80+"),
            "70+": _band(70, 100, 30.8, 91, "composite 70+"),
        },
    )
    high = choose_empirical_hit_rate(86.9, cache)
    mid = choose_empirical_hit_rate(75, cache)
    assert high["hit_rate_pct"] == 44.4
    assert high["source"] == "composite 70-80"
    assert mid["hit_rate_pct"] == 44.4
    assert high["hit_rate_pct"] >= mid["hit_rate_pct"]
    assert high["hit_rate_pct"] != cache["overall"]


def test_a_full_70_plus_pool_is_used_when_it_does_not_undercut_the_lower_band():
    cache = _cache(
        buckets=[_band(70, 80, 44.4, 54, "composite 70-80")],
        tails={
            "80+": _band(80, 100, 40.0, 20, "composite 80+"),
            "70+": _band(70, 100, 46.0, 74, "composite 70+"),
        },
    )
    chosen = choose_empirical_hit_rate(86.9, cache)
    assert chosen["hit_rate_pct"] == 46.0
    assert chosen["source"] == "composite 70+"


def test_benchmark_swing_blocks_the_distribution_cell_and_a_confirmed_downtrend():
    tech = {
        "cmp": 100.0,
        "atr_14": 3.0,
        "signal_day_return_pct": 0.1,
        "cmf_20": -0.02,
        "deliv_surge": 1.6,
    }
    calm = {"close": 100.0, "sma_50": 90.0, "return_20d_pct": 1.0}
    assert passes_benchmark_swing(tech, calm) is False
    tech["cmf_20"] = 0.08
    assert passes_benchmark_swing(tech, calm) is True
    downtrend = {"close": 90.0, "sma_50": 100.0, "return_20d_pct": -2.0}
    assert passes_benchmark_swing(tech, downtrend) is False
    tech["signal_day_return_pct"] = 0.8
    assert passes_benchmark_swing(tech, calm) is False


def test_news_is_one_pillar_not_an_add_on_after_rescaling():
    """A renormalized no-news score plus a news delta is the 29 Oct inflation. The four weights sum to 1."""
    technical, money, macro, news = 90.0, 85.0, 70.0, 55.0
    no_news = blend_pillar_score(technical, money, macro)
    with_news = blend_pillar_score(technical, money, macro, news=news)
    stacked = round(no_news + (news - 50.0) * 0.20, 1)
    assert no_news == 85.9
    assert with_news == 79.8
    assert with_news != stacked
    assert abs(stacked - with_news) > 5


def test_a_full_80_plus_pool_is_used_on_its_own():
    cache = _cache(
        buckets=[_band(70, 80, 44.4, 54, "composite 70-80")],
        tails={"80+": _band(80, 100, 38.0, 40, "composite 80+")},
    )
    chosen = choose_empirical_hit_rate(90, cache)
    assert chosen["hit_rate_pct"] == 38.0
    assert chosen["source"] == "composite 80+"
