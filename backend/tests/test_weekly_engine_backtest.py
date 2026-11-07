"""Weekly Monday-to-Saturday backtest scorecard and the live ranker."""
from datetime import date

import pandas as pd

from app.services.prediction_engine import choose_diverse_picks, rank_engine_candidates
from app.services.weekly_engine_backtest import (
    build_scorecard,
    iter_week_signals,
    last_completed_saturday,
    resolve_window,
)


def _row(symbol, sector, eligible=True, expectancy=1.0, win=70.0, score=80.0):
    return {
        "symbol": symbol,
        "sector": sector,
        "direction": "BULLISH",
        "expected_appreciation_pct": 2.0,
        "is_trade_eligible": eligible,
        "calibrated_expectancy_pct": expectancy,
        "win_probability_pct": win,
        "composite_score": score,
        "rs_20d": 1.0,
    }


def test_last_completed_week_stops_before_an_open_monday():
    assert last_completed_saturday(date(2026, 11, 2)) == date(2026, 10, 31)


def test_weeks_are_monday_signals_through_saturday_not_every_session():
    weeks = iter_week_signals(date(2026, 10, 1), date(2026, 10, 31))
    assert weeks
    assert all(signal.weekday() <= 4 and saturday.weekday() == 5 for signal, saturday in weeks)
    assert all((saturday - signal).days <= 5 for signal, saturday in weeks)
    # Republic Day 2026 is a Monday. That week must move to the next session, not emit a daily row.
    holiday_weeks = iter_week_signals(date(2026, 1, 26), date(2026, 1, 31))
    assert holiday_weeks == [(date(2026, 1, 27), date(2026, 1, 31))]


def test_presets_and_custom_dates():
    start, end, key = resolve_window("6mo", today=date(2026, 11, 2))
    assert key == "6mo"
    assert end == date(2026, 10, 31)
    assert (end - start).days == 183
    start, end, key = resolve_window("1y", today=date(2026, 11, 2))
    assert key == "1y"
    assert (end - start).days == 365
    start, end, key = resolve_window("custom", "2026-05-01", "2026-12-01", today=date(2026, 11, 2))
    assert key == "custom"
    assert start == date(2026, 5, 1)
    assert end == date(2026, 10, 31)


def test_scorecard_counts_hits_losses_and_up_down():
    trades = [
        {"net_return_pct": 2.0},
        {"net_return_pct": 1.0},
        {"net_return_pct": -3.0},
    ]
    card = build_scorecard(trades)
    assert card["hits"] == 2
    assert card["losses"] == 1
    assert card["win_rate_pct"] == 66.7
    assert card["loss_rate_pct"] == 33.3
    assert card["avg_up_pct"] == 1.5
    assert card["avg_down_pct"] == -3.0
    assert card["total_up_pct"] == 3.0
    assert card["total_down_pct"] == -3.0
    assert card["phase_gate"]["ready_for_next_phase"] is False


def _book_trade(net, day, sector="Banks"):
    return {
        "net_return_pct": net,
        "signal_date": day,
        "entry_price": 100.0,
        "stop_loss": 97.0,
        "regime_size": 1.0,
        "sector": sector,
        "verdict": "HIT" if net > 0 else "LOSS",
    }


def test_phase_gate_stays_shut_without_a_base_rate_or_enough_trades():
    trades = [_book_trade(1.2, "2026-01-05") for _ in range(45)] + [_book_trade(-0.4, "2026-01-12") for _ in range(5)]
    card = build_scorecard(trades, benchmark={"base_rate_pct": 40.0})
    assert card["win_rate_pct"] == 90.0
    assert card["phase_gate"]["ready_for_next_phase"] is False


def test_phase_gate_opens_on_edge_payoff_and_drawdown_not_an_80_percent_myth():
    trades = [_book_trade(2.0, f"2026-01-{(index % 20) + 1:02d}") for index in range(80)]
    trades += [_book_trade(-1.0, f"2026-02-{(index % 18) + 1:02d}", sector="IT") for index in range(20)]
    card = build_scorecard(trades, benchmark={"base_rate_pct": 40.0})
    assert card["predicted"] == 100
    assert card["excess_hit_rate_pct"] == 40.0
    assert card["profit_factor"] >= 1.3
    assert card["portfolio"]["max_drawdown_pct"] <= 15.0
    assert card["phase_gate"]["ready_for_next_phase"] is True


def test_data_errors_do_not_count_as_wins():
    card = build_scorecard([
        {"net_return_pct": 800.0, "verdict": "DATA_ERROR"},
        {"net_return_pct": 1.0, "verdict": "HIT"},
    ])
    assert card["predicted"] == 1
    assert card["data_errors"] == 1
    assert card["hits"] == 1


def test_ranker_penalises_a_wild_atr_and_skips_a_blocked_name():
    quiet = _row("QUIET", "Banks", expectancy=1.0, win=70, score=80)
    wild = _row("WILD", "IT", expectancy=1.0, win=70, score=80)
    blocked = _row("BE", "Other", expectancy=9.0, win=90, score=95)
    quiet["atr_pct"] = 2.0
    wild["atr_pct"] = 12.0
    blocked["trade_block"] = "excluded series"
    ranked = rank_engine_candidates([wild, blocked, quiet])
    assert [row["symbol"] for row in ranked[:2]] == ["QUIET", "WILD"]
    assert all(row["symbol"] != "BE" for row in ranked)


def test_ranker_uses_the_live_engine_shortlist():
    scored = [
        _row("AAA", "Banks", expectancy=0.2, win=60, score=70),
        _row("BBB", "Banks", expectancy=3.0, win=80, score=90),
        _row("CCC", "IT", expectancy=2.0, win=75, score=85),
        _row("DDD", "Pharma", eligible=False, expectancy=9.0, win=40, score=40),
    ]
    scored[-1]["expected_appreciation_pct"] = 0.2
    ranked = rank_engine_candidates(scored)
    assert [row["symbol"] for row in ranked[:2]] == ["BBB", "CCC"]
    picks = choose_diverse_picks(ranked, limit=2)
    assert [row["symbol"] for row in picks] == ["BBB", "CCC"]


def test_week_path_uses_sessions_after_monday_through_saturday():
    from app.services.weekly_engine_backtest import _week_path

    frame = pd.DataFrame(
        {
            "Open": [100, 101, 102, 103, 104],
            "High": [101, 106, 103, 108, 105],
            "Low": [99, 100, 101, 102, 103],
            "Close": [100, 102, 101, 107, 104],
        },
        index=pd.to_datetime(["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]),
    )
    path = _week_path(frame, date(2026, 10, 26), date(2026, 10, 31))
    assert path["entry_price"] == 100
    assert path["week_close"] == 104
    assert path["exit_date"] == "2026-10-30"
    assert len(path["sessions"]) == 4
