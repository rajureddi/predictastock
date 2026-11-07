"""
Weekly Monday-to-Saturday replay of the live prediction engine.

Each completed week runs the same full-market screen as the live desk, with
prices, liquidity, and headlines cut off on that Monday. The five names are
then judged on the last close through Saturday. Nothing is written into the
live recommendation book.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import (
    REPORTS_DIR,
    ROUNDTRIP_FRICTION_PCT,
    VALIDATION_MAX_DRAWDOWN_PCT,
    VALIDATION_MIN_EXCESS_HIT_RATE_PCT,
    VALIDATION_MIN_EXPECTANCY_PCT,
    VALIDATION_MIN_OUT_OF_SAMPLE_TRADES,
    VALIDATION_MIN_PROFIT_FACTOR,
)
from app.services.trade_simulator import (
    bootstrap_win_rate,
    calibrate_hit_model,
    execute_frame,
    simulate_portfolio,
)
from app.data.nse_calendar import is_trading_day
from app.services.market_data import get_historical_market_bars
from app.services.prediction_engine import select_present_engine_picks

logger = logging.getLogger(__name__)

SCORE_PATH = Path(REPORTS_DIR) / "weekly_engine_backtest.json"
_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {
    "status": "idle",
    "percent": 0,
    "stage": "Waiting for a weekly backtest.",
    "weeks_done": 0,
    "weeks_total": 0,
    "error": None,
    "report": None,
}


def get_weekly_backtest_progress() -> Dict[str, Any]:
    with _LOCK:
        return dict(_STATE)


def load_saved_weekly_backtest() -> Optional[Dict[str, Any]]:
    if not SCORE_PATH.exists():
        return None
    try:
        with open(SCORE_PATH, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:
        logger.warning("Could not read weekly backtest score: %s", exc)
        return None


def last_completed_saturday(today: Optional[date] = None) -> date:
    """Saturday that closes the last week whose sessions are already finished."""
    today = today or date.today()
    days_since_saturday = (today.weekday() - 5) % 7
    last_saturday = today - timedelta(days=days_since_saturday)
    if last_saturday >= today:
        last_saturday -= timedelta(days=7)
    return last_saturday


def resolve_window(
    preset: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    today: Optional[date] = None,
) -> Tuple[date, date, str]:
    """Return the inclusive Monday-search start and the last Saturday to score."""
    today = today or date.today()
    end_cap = last_completed_saturday(today)
    key = (preset or "6mo").strip().lower()
    if key in ("1y", "1yr", "12mo", "year"):
        start = end_cap - timedelta(days=365)
        return start, end_cap, "1y"
    if key in ("custom", "date"):
        if not start_date or not end_date:
            raise ValueError("Custom backtest needs a start date and an end date.")
        start = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
        end = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        if end > end_cap:
            end = end_cap
        if start > end:
            raise ValueError("The custom start date is after the last completed Saturday in that range.")
        return start, end, "custom"
    start = end_cap - timedelta(days=183)
    return start, end_cap, "6mo"


def iter_week_signals(start: date, end_saturday: date) -> List[Tuple[date, date]]:
    """One signal per week: first trading session from Monday through Friday, judged by Saturday."""
    cursor = start
    while cursor.weekday() != 0:
        cursor += timedelta(days=1)
    weeks: List[Tuple[date, date]] = []
    while True:
        saturday = cursor + timedelta(days=5)
        if saturday > end_saturday:
            break
        signal: Optional[date] = None
        for offset in range(0, 5):
            probe = cursor + timedelta(days=offset)
            if is_trading_day(probe):
                signal = probe
                break
        if signal is not None:
            weeks.append((signal, saturday))
        cursor += timedelta(days=7)
    return weeks


def _week_path(frame, signal: date, saturday: date) -> Optional[Dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return None
    signal_ts = str(signal)
    saturday_ts = str(saturday)
    idx = frame.index.strftime("%Y-%m-%d")
    prior = frame[idx <= signal_ts]
    forward = frame[(idx > signal_ts) & (idx <= saturday_ts)]
    if prior.empty or forward.empty:
        return None
    entry = round(float(prior["Close"].iloc[-1]), 2)
    if entry <= 0:
        return None
    exit_price = round(float(forward["Close"].iloc[-1]), 2)
    week_high = round(float(forward["High"].max()), 2)
    week_low = round(float(forward["Low"].min()), 2)
    sessions = []
    for stamp, row in forward.iterrows():
        close_px = round(float(row["Close"]), 2)
        sessions.append({
            "date": str(stamp)[:10],
            "close": close_px,
            "change_pct": round(((close_px - entry) / entry) * 100.0, 2),
        })
    gross = round(((exit_price - entry) / entry) * 100.0, 2)
    net = round(gross - float(ROUNDTRIP_FRICTION_PCT), 2)
    return {
        "entry_price": entry,
        "week_close": exit_price,
        "week_high": week_high,
        "week_low": week_low,
        "gross_return_pct": gross,
        "net_return_pct": net,
        "sessions": sessions,
        "exit_date": sessions[-1]["date"],
    }


def _scored_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept = []
    for row in rows:
        if row.get("verdict") in ("DATA_ERROR", "REJECTED"):
            continue
        if "net_return_pct" not in row or row.get("net_return_pct") is None:
            continue
        kept.append(row)
    return kept


def summarize_basket(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Score one Monday's five-name list, or the whole run, as hit and loss counts."""
    rows = _scored_rows(rows)
    ups = [float(row["net_return_pct"]) for row in rows if float(row["net_return_pct"]) > 0]
    downs = [float(row["net_return_pct"]) for row in rows if float(row["net_return_pct"]) <= 0]
    hits = len(ups)
    losses = len(downs)
    predicted = hits + losses
    total_up = round(sum(ups), 2) if ups else 0.0
    total_down = round(sum(downs), 2) if downs else 0.0
    return {
        "predicted": predicted,
        "hits": hits,
        "losses": losses,
        "win_rate_pct": round((hits / predicted) * 100.0, 1) if predicted else 0.0,
        "loss_rate_pct": round((losses / predicted) * 100.0, 1) if predicted else 0.0,
        "avg_up_pct": round(total_up / hits, 2) if hits else 0.0,
        "avg_down_pct": round(total_down / losses, 2) if losses else 0.0,
        "total_up_pct": total_up,
        "total_down_pct": total_down,
    }


def build_scorecard(
    trades: List[Dict[str, Any]],
    benchmark: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    scored = _scored_rows(trades)
    basket = summarize_basket(scored)
    hits = basket["hits"]
    losses = basket["losses"]
    sample = basket["predicted"]
    total_up = basket["total_up_pct"]
    total_down = basket["total_down_pct"]
    win_rate = basket["win_rate_pct"]
    avg_up = basket["avg_up_pct"]
    avg_down = basket["avg_down_pct"]
    nets = [float(row["net_return_pct"]) for row in scored]
    expectancy = round(sum(nets) / len(nets), 3) if nets else 0.0
    profit_factor = round(total_up / abs(total_down), 2) if total_down < 0 else (99.0 if total_up > 0 else 0.0)
    base_rate = None if not benchmark else benchmark.get("base_rate_pct")
    excess = None if base_rate is None else round(win_rate - float(base_rate), 1)
    portfolio = None
    if scored and all(row.get("entry_price") and row.get("stop_loss") is not None for row in scored):
        portfolio = simulate_portfolio(scored)
    drawdown = None if portfolio is None else portfolio["max_drawdown_pct"]
    data_errors = sum(1 for row in trades if row.get("verdict") == "DATA_ERROR")
    rejected = sum(1 for row in trades if row.get("verdict") == "REJECTED")
    ready = bool(
        sample >= VALIDATION_MIN_OUT_OF_SAMPLE_TRADES
        and expectancy >= VALIDATION_MIN_EXPECTANCY_PCT
        and profit_factor >= VALIDATION_MIN_PROFIT_FACTOR
        and excess is not None
        and excess >= VALIDATION_MIN_EXCESS_HIT_RATE_PCT
        and drawdown is not None
        and drawdown <= VALIDATION_MAX_DRAWDOWN_PCT
    )
    if ready:
        reason = (
            f"Ready for the next phase. Win rate {win_rate}% versus a {float(base_rate):.1f}% universe base rate "
            f"on {sample} filled trades. Expectancy {expectancy:+.2f}% per trade, profit factor {profit_factor:.2f}, "
            f"portfolio drawdown {drawdown:.1f}%."
        )
    elif sample < VALIDATION_MIN_OUT_OF_SAMPLE_TRADES:
        reason = (
            f"Hold. {sample} filled trades is below the {VALIDATION_MIN_OUT_OF_SAMPLE_TRADES} needed. "
            f"Win rate so far is {win_rate}%."
        )
    elif excess is None:
        reason = (
            f"Hold. Win rate {win_rate}% on {sample} trades, but there is no universe base rate to measure the edge against."
        )
    elif excess < VALIDATION_MIN_EXCESS_HIT_RATE_PCT:
        reason = (
            f"Hold. Win rate {win_rate}% is only {excess:+.1f} points versus the {float(base_rate):.1f}% base rate. "
            f"The book needs at least +{VALIDATION_MIN_EXCESS_HIT_RATE_PCT:.0f} points. "
            f"Expectancy {expectancy:+.2f}%, profit factor {profit_factor:.2f}."
        )
    elif expectancy < VALIDATION_MIN_EXPECTANCY_PCT or profit_factor < VALIDATION_MIN_PROFIT_FACTOR:
        reason = (
            f"Hold. Win rate {win_rate}% on {sample} trades, but expectancy {expectancy:+.2f}% or profit factor "
            f"{profit_factor:.2f} is below the bar ({VALIDATION_MIN_EXPECTANCY_PCT:.2f}% and {VALIDATION_MIN_PROFIT_FACTOR:.2f})."
        )
    else:
        reason = (
            f"Hold. The edge is there on {sample} trades, but portfolio drawdown "
            f"{0.0 if drawdown is None else drawdown:.1f}% is past the {VALIDATION_MAX_DRAWDOWN_PCT:.0f}% limit."
        )
    return {
        "trades": sample,
        "predicted": sample,
        "hits": hits,
        "losses": losses,
        "rejected": rejected,
        "data_errors": data_errors,
        "win_rate_pct": win_rate,
        "loss_rate_pct": basket["loss_rate_pct"],
        "avg_up_pct": avg_up,
        "avg_down_pct": avg_down,
        "total_up_pct": total_up,
        "total_down_pct": total_down,
        "expectancy_pct": expectancy,
        "profit_factor": profit_factor,
        "base_rate_pct": base_rate,
        "excess_hit_rate_pct": excess,
        "friction_pct": float(ROUNDTRIP_FRICTION_PCT),
        "portfolio": portfolio,
        "phase_gate": {
            "ready_for_next_phase": ready,
            "required_trades": VALIDATION_MIN_OUT_OF_SAMPLE_TRADES,
            "required_excess_hit_rate_pct": VALIDATION_MIN_EXCESS_HIT_RATE_PCT,
            "required_profit_factor": VALIDATION_MIN_PROFIT_FACTOR,
            "required_expectancy_pct": VALIDATION_MIN_EXPECTANCY_PCT,
            "max_drawdown_pct": VALIDATION_MAX_DRAWDOWN_PCT,
            "reason": reason,
        },
    }


def _saved_research(start: date, end_saturday: date) -> Dict[str, Any]:
    """Reuse a research file that already covers this window."""
    path = Path(REPORTS_DIR) / "signal_research.json"
    if not path.exists():
        return {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if saved.get("start_date", "9999") <= start.isoformat() and saved.get("end_date", "") >= end_saturday.isoformat():
        return saved
    return {}


def _set_progress(**fields: Any) -> None:
    with _LOCK:
        _STATE.update(fields)


def run_weekly_engine_backtest(
    preset: str = "6mo",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    start, end_saturday, window_key = resolve_window(preset, start_date, end_date)
    weeks = iter_week_signals(start, end_saturday)
    if not weeks:
        raise ValueError("That range has no completed Monday-to-Saturday week to score.")

    _set_progress(
        status="running",
        percent=1,
        stage="Each Monday runs the full present-engine scan. This takes as long as a live scan, once per week.",
        weeks_done=0,
        weeks_total=len(weeks),
        error=None,
        report=None,
    )

    research: Dict[str, Any] = _saved_research(start, end_saturday)
    if not research:
        try:
            _set_progress(stage="Measuring the universe base rate and the baseline books.")
            from app.services.signal_research import research_window
            research = research_window(start, end_saturday)
        except Exception as exc:
            logger.warning("Signal research failed: %s", exc)
    week_lookup = research.get("weeks") or {}

    trades: List[Dict[str, Any]] = []
    week_rows: List[Dict[str, Any]] = []
    universe_size = 0
    for index, (signal, saturday) in enumerate(weeks, start=1):
        def on_progress(evaluated, total, _symbol, _name, _qualified, stage, week_index=index, week_day=signal):
            span = 92 / len(weeks)
            inner = (evaluated / total) * span if total else 0
            _set_progress(
                percent=min(96, round(4 + (week_index - 1) * span + inner)),
                stage=f"Week {week_index} of {len(weeks)} · {week_day.isoformat()} · {stage}",
                weeks_done=week_index - 1,
                weeks_total=len(weeks),
            )

        logger.info("Weekly backtest week %s of %s, signal %s", index, len(weeks), signal.isoformat())
        picks, universe_size = select_present_engine_picks(
            as_of_date=signal.isoformat(),
            on_progress=on_progress,
        )
        week_trades = []
        week_monday = signal - timedelta(days=signal.weekday())
        for pick in picks:
            trade = _fill_weekly_pick(pick, signal, saturday, week_monday)
            if trade is None:
                continue
            week_trades.append(trade)
            trades.append(trade)
        basket = summarize_basket(week_trades)
        bench = week_lookup.get(signal.isoformat()) or {}
        week_rows.append({
            "week_start": week_monday.isoformat(),
            "week_end": saturday.isoformat(),
            "predicted": basket["predicted"],
            "hits": basket["hits"],
            "losses": basket["losses"],
            "rejected": sum(1 for row in week_trades if row.get("verdict") == "REJECTED"),
            "data_errors": sum(1 for row in week_trades if row.get("verdict") == "DATA_ERROR"),
            "win_rate_pct": basket["win_rate_pct"],
            "loss_rate_pct": basket["loss_rate_pct"],
            "avg_up_pct": basket["avg_up_pct"],
            "avg_down_pct": basket["avg_down_pct"],
            "base_rate_pct": bench.get("base_rate_pct"),
            "nifty_return_pct": bench.get("nifty_return_pct"),
            "excess_hit_rate_pct": (
                round(basket["win_rate_pct"] - float(bench["base_rate_pct"]), 1)
                if bench.get("base_rate_pct") is not None and basket["predicted"] else None
            ),
        })

    base_rates = [row["base_rate_pct"] for row in week_rows if row.get("base_rate_pct") is not None]
    benchmark = {"base_rate_pct": round(sum(base_rates) / len(base_rates), 1)} if base_rates else None
    scored = _scored_rows(trades)
    scorecard = build_scorecard(trades, benchmark)
    report = {
        "engine": "score_single_stock",
        "ranker": "rank_engine_candidates",
        "cadence": "weekly_monday_to_saturday",
        "execution": "next_open_stop_target_or_week_close",
        "window": window_key,
        "start_date": start.isoformat(),
        "end_date": end_saturday.isoformat(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "universe_size": universe_size,
        "weeks_scored": len(weeks),
        "weeks_with_picks": sum(1 for row in week_rows if row["predicted"] > 0),
        "picks_per_week": 5,
        "score": {key: value for key, value in scorecard.items() if key != "phase_gate"},
        "phase_gate": scorecard["phase_gate"],
        "bootstrap": bootstrap_win_rate(scored),
        "calibration": calibrate_hit_model(scored),
        "horizons": {
            "week": _horizon_summary(scored, "net_return_pct"),
            "10_sessions": _horizon_summary(scored, "net_10_pct"),
            "20_sessions": _horizon_summary(scored, "net_20_pct"),
        },
        "baselines": research.get("baselines"),
        "factor_edge": research.get("factor_edge"),
        "weeks": week_rows,
        "trades": [
            {key: value for key, value in trade.items() if key != "sessions"}
            for trade in trades
        ],
    }
    SCORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCORE_PATH, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    calibration = report.get("calibration") or {}
    if calibration.get("status") == "ok":
        payload = dict(calibration)
        payload["rank_term_enabled"] = bool(payload.get("model_beats_stated_probability"))
        payload["applied_to_live_weights"] = False
        with open(SCORE_PATH.parent / "win_prob_calibration.json", "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    _write_markdown(report)
    _set_progress(
        status="completed",
        percent=100,
        stage=scorecard["phase_gate"]["reason"],
        weeks_done=len(weeks),
        report=report,
        error=None,
    )
    return report


def _horizon_summary(trades: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    rows = [{"net_return_pct": trade[key]} for trade in trades if trade.get(key) is not None]
    basket = summarize_basket(rows)
    if rows:
        basket["expectancy_pct"] = round(sum(float(row["net_return_pct"]) for row in rows) / len(rows), 3)
    else:
        basket["expectancy_pct"] = 0.0
    return basket


def _fill_weekly_pick(pick: Dict[str, Any], signal: date, saturday: date, week_monday: date) -> Optional[Dict[str, Any]]:
    """Fill next open, walk the engine's own stop and target, and keep 10- and 20-session exits."""
    horizon_end = saturday + timedelta(days=45)
    frame = get_historical_market_bars(pick["symbol"], lookback_days=80, as_of_date=horizon_end.isoformat())
    if frame is None or getattr(frame, "empty", True):
        return None
    stamps = frame.index.strftime("%Y-%m-%d")
    prior = frame[stamps <= signal.isoformat()]
    if prior.empty:
        return None
    signal_close = float(prior["Close"].iloc[-1])
    reference = float(pick.get("reference_price") or 0.0)
    scale = (signal_close / reference) if reference > 0 and signal_close > 0 else 1.0
    stop = float(pick.get("stop_loss") or 0.0) * scale
    target = float(pick.get("expected_target_price") or 0.0) * scale
    turnover = float(prior["Volume"].tail(20).mean()) * signal_close if "Volume" in prior.columns else 0.0
    week = execute_frame(
        frame, signal.isoformat(), horizon=6, stop_price=stop, target_price=target,
        turnover_inr=turnover, last_iso=saturday.isoformat(),
    )
    if week.get("status") == "NO_DATA":
        return None
    hold_10 = execute_frame(frame, signal.isoformat(), horizon=10, stop_price=stop, target_price=target, turnover_inr=turnover)
    hold_20 = execute_frame(frame, signal.isoformat(), horizon=20, stop_price=stop, target_price=target, turnover_inr=turnover)
    status = week.get("status")
    if status == "FILLED":
        net = week["net_return_pct"]
        verdict = "HIT" if net > 0 else "LOSS"
    elif status in ("DATA_ERROR", "REJECTED"):
        net = None
        verdict = status
    else:
        return None
    return {
        "signal_date": signal.isoformat(),
        "week_start": week_monday.isoformat(),
        "week_end": saturday.isoformat(),
        "symbol": pick["symbol"],
        "name": pick.get("name") or pick["symbol"],
        "sector": pick.get("sector") or "Other",
        "series": pick.get("series"),
        "direction": pick.get("direction"),
        "admission_path": pick.get("admission_path"),
        "entry_setup": pick.get("entry_setup"),
        "regime_size": pick.get("regime_size_multiplier"),
        "monday_price": round(signal_close, 2),
        "entry_price": week.get("entry_price"),
        "stop_loss": week.get("stop_loss") or round(stop, 2),
        "predicted_price": round(target, 2),
        "predicted_move_pct": round(float(pick.get("expected_appreciation_pct") or 0), 2),
        "exit_price": week.get("exit_price"),
        "exit_reason": week.get("exit_reason") or week.get("reason"),
        "gross_return_pct": week.get("gross_return_pct"),
        "net_return_pct": net,
        "net_10_pct": hold_10.get("net_return_pct") if hold_10.get("status") == "FILLED" else None,
        "net_20_pct": hold_20.get("net_return_pct") if hold_20.get("status") == "FILLED" else None,
        "verdict": verdict,
        "win_probability_pct": round(float(pick.get("win_probability_pct") or 0), 1),
        "composite_score": pick.get("composite_score"),
        "rs_20d": pick.get("rs_20d"),
        "cmf_20": pick.get("cmf_20"),
        "rsi_14": pick.get("rsi_14"),
        "vol_surge": pick.get("vol_surge"),
        "delivery_zscore": pick.get("delivery_zscore"),
        "atr_pct": pick.get("atr_pct"),
    }


def _write_markdown(report: Dict[str, Any]) -> None:
    score = report["score"]
    gate = report["phase_gate"]
    portfolio = score.get("portfolio") or {}
    boot = report.get("bootstrap") or {}
    lines = [
        "# Weekly Engine Backtest",
        "",
        f"Window: {report['start_date']} to {report['end_date']} ({report['window']})",
        f"Generated: {report['generated_at']}",
        "Cadence: signal on the Monday close, fill at the next open, exit at the stop, the target, or the last close through Saturday.",
        f"Universe: {report['universe_size']} names, the same full-market screen as the live desk.",
        "",
        f"- Win rate: {score['win_rate_pct']}%",
        f"- Universe base rate: {score.get('base_rate_pct')}%",
        f"- Excess hit rate: {score.get('excess_hit_rate_pct')} points",
        f"- Expectancy: {score.get('expectancy_pct')}% per filled trade",
        f"- Profit factor: {score.get('profit_factor')}",
        f"- Hits: {score['hits']}",
        f"- Losses: {score['losses']}",
        f"- Rejected fills: {score.get('rejected', 0)}",
        f"- Data errors removed: {score.get('data_errors', 0)}",
        f"- Average up: {score['avg_up_pct']:+.2f}%",
        f"- Average down: {score['avg_down_pct']:+.2f}%",
        f"- Portfolio: {portfolio.get('total_return_pct')}% on ₹{portfolio.get('start_capital')}, max drawdown {portfolio.get('max_drawdown_pct')}%",
        f"- Win-rate interval (week bootstrap): {boot.get('p05')}% to {boot.get('p95')}%",
        "",
    ]
    calibration = report.get("calibration") or {}
    if calibration.get("status") == "ok":
        if calibration.get("model_beats_stated_probability"):
            fit_line = "The out-of-sample fit beats the stated win probability, so the ranker adds it as an extra term."
        else:
            fit_line = "The stated win probability still ranks. Published factor weights stay in place."
        lines.append(
            f"Win-probability fit: Brier {calibration.get('brier_model')} against stated {calibration.get('brier_stated_win_prob')}. {fit_line}"
        )
        lines.append("")
    lines.extend([
        f"Next phase: {'READY' if gate['ready_for_next_phase'] else 'HOLD'}",
        gate["reason"],
        "",
    ])
    horizons = report.get("horizons") or {}
    if horizons:
        lines.append("Same filled signals, held longer:")
        for name, basket in horizons.items():
            lines.append(
                f"- {name}: win rate {basket.get('win_rate_pct')}% on {basket.get('predicted')} trades, "
                f"expectancy {basket.get('expectancy_pct', 'n/a')}"
            )
        lines.append("")
    baselines = report.get("baselines") or {}
    if baselines:
        lines.append("Baseline books over the same weeks (4-session hold, same costs):")
        for name, basket in baselines.items():
            lines.append(
                f"- {name}: win rate {basket.get('win_rate_pct')}%, expectancy {basket.get('expectancy_pct')}%, "
                f"profit factor {basket.get('profit_factor')}, trades {basket.get('predicted')}"
            )
        lines.append("")
    path = Path(REPORTS_DIR) / "weekly_engine_backtest.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def start_weekly_engine_backtest(
    preset: str = "6mo",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> Dict[str, Any]:
    with _LOCK:
        if _STATE.get("status") == "running":
            return {"status": "RUNNING", "progress": dict(_STATE)}
        _STATE.update({
            "status": "running",
            "percent": 1,
            "stage": "Starting the weekly engine backtest.",
            "weeks_done": 0,
            "weeks_total": 0,
            "error": None,
            "report": None,
        })

    def _worker() -> None:
        try:
            run_weekly_engine_backtest(preset, start_date, end_date)
        except Exception as exc:
            logger.error("Weekly engine backtest failed: %s", exc, exc_info=True)
            _set_progress(status="error", percent=100, stage=str(exc), error=str(exc))

    threading.Thread(target=_worker, name="weekly-engine-backtest", daemon=True).start()
    return {"status": "STARTED", "progress": get_weekly_backtest_progress()}
