"""
Same-week comparison of the books a desk would actually argue about.

Every book buys the next open and sells on the same stop, target, and cost
rules. The universe base rate is every liquid name, bought at the next open
and sold on the week close. Delivery and 20-day momentum are scored on that
same forward window, across every Monday, so a factor has to beat the coin
flip out in the open and not inside one hand-picked week.
"""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from app.config import DATA_ERROR_RETURN_PCT, REPORTS_DIR, ROUNDTRIP_FRICTION_PCT
from app.database import get_db_connection
from app.services.trade_simulator import execute_long_bracket
from app.services.weekly_engine_backtest import iter_week_signals

logger = logging.getLogger(__name__)

LIQUID_LACS = 500.0  # ₹5 Cr, matching the live scan floor
HORIZONS = (4, 10, 20)


def _stats(nets: List[float]) -> Dict[str, Any]:
    if not nets:
        return {
            "predicted": 0, "hits": 0, "losses": 0, "win_rate_pct": 0.0,
            "expectancy_pct": 0.0, "profit_factor": 0.0, "avg_up_pct": 0.0, "avg_down_pct": 0.0,
        }
    ups = [value for value in nets if value > 0]
    downs = [value for value in nets if value <= 0]
    total_up = sum(ups)
    total_down = sum(downs)
    return {
        "predicted": len(nets),
        "hits": len(ups),
        "losses": len(downs),
        "win_rate_pct": round(len(ups) / len(nets) * 100.0, 1),
        "expectancy_pct": round(sum(nets) / len(nets), 3),
        "profit_factor": round(total_up / abs(total_down), 2) if total_down < 0 else (99.0 if total_up > 0 else 0.0),
        "avg_up_pct": round(total_up / len(ups), 2) if ups else 0.0,
        "avg_down_pct": round(total_down / len(downs), 2) if downs else 0.0,
    }


def _adjust_splits(sub: pd.DataFrame) -> pd.DataFrame:
    """Apply only the obvious ex-date ratios. A 3% dividend is left alone."""
    prior = sub["close"].shift(1)
    ratio = sub["prev_close"] / prior
    extreme = (ratio - 1.0).abs() >= 0.25
    factor = pd.Series(1.0, index=sub.index)
    factor.loc[extreme.fillna(False)] = ratio.loc[extreme.fillna(False)]
    cumulative = factor.iloc[::-1].cumprod().iloc[::-1].shift(-1, fill_value=1.0)
    out = sub.copy()
    for column in ("open", "high", "low", "close"):
        out[column] = out[column] * cumulative
    return out


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    counts = frame.groupby("symbol").size()
    frame = frame[frame["symbol"].isin(counts[counts >= 60].index)].copy()
    parts = []
    grouped = list(frame.groupby("symbol", sort=False))
    logger.info("Building features for %s symbols", len(grouped))
    for count, (_, sub) in enumerate(grouped, start=1):
        sub = _adjust_splits(sub.sort_values("trading_date"))
        sub["sma20"] = sub["close"].rolling(20, min_periods=20).mean()
        sub["sma50"] = sub["close"].rolling(50, min_periods=50).mean()
        sub["ret20"] = sub["close"].pct_change(20)
        sub["turn20"] = sub["turnover_lacs"].rolling(20, min_periods=10).mean()
        sub["vol20"] = sub["volume"].rolling(20, min_periods=20).mean()
        sub["vol_surge"] = sub["volume"] / sub["vol20"]
        sub["hi20"] = sub["high"].rolling(20, min_periods=20).max().shift(1)
        sub["low3"] = sub["low"].rolling(3, min_periods=3).min()
        previous = sub["close"].shift(1)
        true_range = pd.concat(
            [sub["high"] - sub["low"], (sub["high"] - previous).abs(), (sub["low"] - previous).abs()],
            axis=1,
        ).max(axis=1)
        sub["atr"] = true_range.rolling(14, min_periods=14).mean()
        d_mean = sub["deliv_per"].rolling(60, min_periods=20).mean()
        d_std = sub["deliv_per"].rolling(60, min_periods=20).std()
        sub["deliv_z"] = (sub["deliv_per"] - d_mean) / d_std.replace(0, np.nan)
        sub["entry_open"] = sub["open"].shift(-1)
        sub["exit_4"] = sub["close"].shift(-4)
        parts.append(sub)
        if count % 500 == 0:
            logger.info("Features ready for %s of %s symbols", count, len(grouped))
    out = pd.concat(parts, ignore_index=True)
    symbol = out["symbol"].astype(str).str.upper()
    fund = symbol.str.endswith(("BEES", "ETF", "CASE")) | symbol.str.contains("NIFTY", regex=False)
    out = out[(out["series"].isin(["EQ", "A", "B"])) & ~fund]
    return out


def _load(start: date, end: date) -> pd.DataFrame:
    conn = get_db_connection()
    try:
        frame = pd.read_sql_query(
            """
            SELECT symbol, trading_date, open, high, low, close, volume,
                   deliv_per, turnover_lacs, series, prev_close, nifty50_close
            FROM historical_market_bars
            WHERE trading_date >= ? AND trading_date <= ?
            """,
            conn,
            params=((start - timedelta(days=140)).isoformat(), (end + timedelta(days=40)).isoformat()),
        )
    finally:
        conn.close()
    if frame.empty:
        return frame
    frame["trading_date"] = pd.to_datetime(frame["trading_date"])
    return _prepare(frame)


def _books(frame: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
    packed = {}
    for symbol, sub in frame.groupby("symbol", sort=False):
        ordered = sub.sort_values("trading_date")
        dates = ordered["trading_date"].dt.strftime("%Y-%m-%d").tolist()
        close = ordered["close"].to_numpy(float)
        packed[symbol] = {
            "index": {stamp: pos for pos, stamp in enumerate(dates)},
            "dates": dates,
            "open": ordered["open"].to_numpy(float),
            "high": ordered["high"].to_numpy(float),
            "low": ordered["low"].to_numpy(float),
            "close": close,
            "jump": np.r_[False, np.abs(np.diff(close) / np.where(close[:-1] == 0, np.nan, close[:-1])) >= 0.25],
        }
    return packed


def _walk(
    book: Dict[str, Any],
    signal_iso: str,
    horizon: int,
    atr: float,
    turnover_lacs: float,
    stop_multiple: float = 1.0,
) -> Optional[float]:
    pos = book["index"].get(signal_iso)
    if pos is None or pos + 1 + horizon > len(book["close"]):
        return None
    entry_pos = pos + 1
    gap_days = (
        date.fromisoformat(book["dates"][entry_pos]) - date.fromisoformat(signal_iso)
    ).days
    if gap_days > 5:
        return None
    signal_close = float(book["close"][pos])
    if not atr or atr <= 0 or signal_close <= 0:
        return None
    entry = float(book["open"][entry_pos])
    result = execute_long_bracket(
        book["open"], book["high"], book["low"], book["close"],
        entry_pos, horizon, signal_close,
        stop_price=entry - (stop_multiple * atr), target_price=entry + 2.0 * atr,
        turnover_inr=float(turnover_lacs or 0.0) * 1e5,
        jumps=book["jump"],
    )
    if result.get("status") != "FILLED":
        return None
    if abs(float(result["gross_return_pct"])) > DATA_ERROR_RETURN_PCT:
        return None
    return float(result["net_return_pct"])


def _pick_symbols(day: pd.DataFrame, kind: str, rng: np.random.Generator) -> pd.DataFrame:
    liquid = day[(day["turn20"] >= LIQUID_LACS) & (day["close"] >= 20) & day["atr"].notna() & day["entry_open"].notna()]
    if liquid.empty:
        return liquid
    if kind == "random":
        take = min(5, len(liquid))
        return liquid.sample(n=take, random_state=int(rng.integers(0, 1_000_000)))
    if kind == "momentum_20d":
        pool = liquid[liquid["ret20"] > 0]
        return pool.nlargest(5, "ret20")
    if kind == "delivery":
        pool = liquid[(liquid["deliv_z"] > 0.5) & (liquid["close"] > liquid["sma20"])]
        return pool.nlargest(5, "deliv_z")
    if kind == "pullback":
        near = (liquid["low3"] <= liquid["sma20"] * 1.01) & (liquid["close"] >= liquid["sma20"])
        uptrend = (liquid["close"] >= liquid["sma50"]) & (liquid["sma20"] >= liquid["sma50"]) & (liquid["ret20"] > 0)
        pool = liquid[near & uptrend & (liquid["deliv_z"] > 0)]
        return pool.nlargest(5, "deliv_z")
    if kind == "breakout":
        fresh = (liquid["close"] >= liquid["hi20"]) & (liquid["vol_surge"] >= 1.5) & (liquid["close"] >= liquid["sma50"])
        pool = liquid[fresh & (liquid["close"] <= liquid["sma20"] * 1.045)]
        return pool.nlargest(5, "vol_surge")
    return liquid.iloc[0:0]


def _factor_edge(snapshots: pd.DataFrame) -> Dict[str, Any]:
    work = snapshots.replace([np.inf, -np.inf], np.nan).dropna(subset=["deliv_z", "ret20", "forward_pct"])
    if len(work) < 100:
        return {"status": "too_few_names", "names": int(len(work))}
    delivery_ic = float(work["deliv_z"].rank().corr(work["forward_pct"].rank()))
    momentum_ic = float(work["ret20"].rank().corr(work["forward_pct"].rank()))
    work = work.copy()
    work["bucket"] = pd.qcut(work["deliv_z"], 5, duplicates="drop")
    quintiles = []
    for bucket, group in work.groupby("bucket", observed=True):
        forward = group["forward_pct"]
        quintiles.append({
            "bucket": str(bucket),
            "names": int(len(group)),
            "mean_return_pct": round(float(forward.mean()), 3),
            "hit_rate_pct": round(float((forward > 0).mean() * 100.0), 1),
        })
    return {
        "status": "ok",
        "names": int(len(work)),
        "delivery_z_rank_correlation": round(delivery_ic, 4),
        "momentum_20d_rank_correlation": round(momentum_ic, 4),
        "delivery_quintiles": quintiles,
        "reading": (
            "Delivery's own-history z-score has a positive rank correlation with the next week."
            if delivery_ic > 0.02 else
            "Delivery's own-history z-score does not separate next-week winners on this window."
            if delivery_ic > -0.02 else
            "Delivery's own-history z-score lines up with weaker next weeks on this window."
        ),
    }


def research_window(start: date, end: date) -> Dict[str, Any]:
    frame = _load(start, end)
    if frame.empty:
        return {"weeks": {}, "baselines": {}, "factor_edge": {"status": "no_bars"}, "summary": {}}
    packed = _books(frame)
    calendar = sorted(frame["trading_date"].unique())
    calendar_pos = {stamp: pos for pos, stamp in enumerate(calendar)}
    nifty = frame.groupby("trading_date")["nifty50_close"].median()
    weeks = iter_week_signals(start, end)
    kinds = ("random", "momentum_20d", "delivery", "pullback", "breakout")
    nets: Dict[str, Dict[int, List[float]]] = {kind: {h: [] for h in HORIZONS} for kind in kinds}
    week_rows: Dict[str, Dict[str, Any]] = {}
    factor_rows = []
    rng = np.random.default_rng(11)

    for signal, _saturday in weeks:
        signal_ts = pd.Timestamp(signal)
        day = frame[frame["trading_date"] == signal_ts]
        if day.empty:
            continue
        liquid = day[(day["turn20"] >= LIQUID_LACS) & (day["close"] >= 20) & day["entry_open"].notna() & day["exit_4"].notna()]
        gross = (liquid["exit_4"] / liquid["entry_open"] - 1.0) * 100.0
        gross = gross[gross.abs() <= DATA_ERROR_RETURN_PCT]
        net = gross - float(ROUNDTRIP_FRICTION_PCT)
        pos = calendar_pos.get(signal_ts)
        nifty_ret = None
        if pos is not None and pos + 4 < len(calendar):
            start_px = nifty.get(signal_ts)
            end_px = nifty.get(calendar[pos + 4])
            if pd.notna(start_px) and pd.notna(end_px) and start_px:
                nifty_ret = round((float(end_px) / float(start_px) - 1.0) * 100.0, 2)
        week_rows[signal.isoformat()] = {
            "base_rate_pct": round(float((net > 0).mean() * 100.0), 1) if len(net) else None,
            "eq_weight_return_pct": round(float(net.mean()), 3) if len(net) else None,
            "nifty_return_pct": nifty_ret,
            "names": int(len(net)),
        }
        kept = liquid.loc[gross.index] if len(gross) else liquid.iloc[0:0]
        if len(kept):
            factor_rows.append(pd.DataFrame({
                "deliv_z": kept["deliv_z"].to_numpy(),
                "ret20": kept["ret20"].to_numpy(),
                "forward_pct": gross.loc[kept.index].to_numpy() - float(ROUNDTRIP_FRICTION_PCT),
            }))
        for kind in kinds:
            chosen = _pick_symbols(day, kind, rng)
            for row in chosen.itertuples(index=False):
                book = packed.get(row.symbol)
                if book is None:
                    continue
                for horizon in HORIZONS:
                    result = _walk(book, signal.isoformat(), horizon, float(row.atr), float(row.turn20 or 0.0))
                    if result is not None:
                        nets[kind][horizon].append(result)

    baselines = {kind: _stats(nets[kind][4]) for kind in kinds}
    by_horizon = {
        kind: {f"{horizon}_sessions": _stats(nets[kind][horizon]) for horizon in HORIZONS}
        for kind in kinds
    }
    factor_edge = _factor_edge(pd.concat(factor_rows, ignore_index=True)) if factor_rows else {"status": "no_bars"}
    base_values = [row["base_rate_pct"] for row in week_rows.values() if row.get("base_rate_pct") is not None]
    summary = {
        "weeks": len(week_rows),
        "base_rate_pct": round(sum(base_values) / len(base_values), 1) if base_values else None,
        "best_baseline": max(baselines, key=lambda name: baselines[name]["expectancy_pct"]) if baselines else None,
    }
    report = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "weeks": week_rows,
        "baselines": baselines,
        "by_horizon": by_horizon,
        "factor_edge": factor_edge,
        "summary": summary,
    }
    _write(report)
    return report


def compare_stop_widths(
    start: date,
    end: date,
    multiples: tuple = (1.05, 1.5),
) -> Dict[str, Any]:
    """Same research books and 2 ATR target. Only the stop width changes.

    The live engine still risks 1.05 ATR in a bullish regime. This comparison
    does not write that rule.
    """
    frame = _load(start, end)
    if frame.empty:
        return {"status": "no_bars"}
    packed = _books(frame)
    weeks = iter_week_signals(start, end)
    kinds = ("random", "momentum_20d", "delivery", "pullback", "breakout")
    nets: Dict[str, Dict[str, List[float]]] = {f"{multiple:g}": {kind: [] for kind in kinds} for multiple in multiples}
    rng = np.random.default_rng(11)
    for signal, _saturday in weeks:
        day = frame[frame["trading_date"] == pd.Timestamp(signal)]
        if day.empty:
            continue
        for kind in kinds:
            chosen = _pick_symbols(day, kind, rng)
            for row in chosen.itertuples(index=False):
                book = packed.get(row.symbol)
                if book is None:
                    continue
                for multiple in multiples:
                    result = _walk(
                        book, signal.isoformat(), 4, float(row.atr), float(row.turn20 or 0.0),
                        stop_multiple=float(multiple),
                    )
                    if result is not None:
                        nets[f"{multiple:g}"][kind].append(result)
    books = {
        label: {kind: _stats(values) for kind, values in baskets.items()}
        for label, baskets in nets.items()
    }
    report = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "target": "2 ATR",
        "horizon_sessions": 4,
        "note": "Research books only. The live stop rule is unchanged.",
        "stops": books,
    }
    path = Path(REPORTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    (path / "stop_width_comparison.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Stop width on the research book",
        "",
        f"Window: {start.isoformat()} to {end.isoformat()}",
        "Same names, next open, two-ATR target, and the same costs. The live 1.05 ATR stop is not changed.",
        "",
    ]
    for label, baskets in books.items():
        lines.append(f"Stop {label} x ATR:")
        for kind, basket in baskets.items():
            lines.append(
                f"- {kind}: win rate {basket['win_rate_pct']}%, expectancy {basket['expectancy_pct']}%, "
                f"profit factor {basket['profit_factor']}, trades {basket['predicted']}"
            )
        lines.append("")
    (path / "stop_width_comparison.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def _exit_path(
    book: Dict[str, Any],
    entry_pos: int,
    horizon: int,
    stop_price: float,
    target_price: float,
) -> Dict[str, Any]:
    """Replay the bracket the simulator fills, and name how the exit was reached."""
    last = entry_pos + horizon
    for step, bar in enumerate(range(entry_pos, last)):
        bar_open = float(book["open"][bar])
        bar_high = float(book["high"][bar])
        bar_low = float(book["low"][bar])
        stop_hit = stop_price > 0 and bar_low <= stop_price
        target_hit = target_price > 0 and bar_high >= target_price
        if stop_hit:
            if bar_open <= stop_price:
                kind = "overnight_gap" if bar > entry_pos else "entry_through_stop"
            else:
                kind = "entry_day_stop" if bar == entry_pos else "later_intraday_stop"
            return {"kind": kind, "exit_raw": min(bar_open, stop_price), "session": step + 1}
        if target_hit:
            raw = bar_open if bar_open > target_price else target_price
            return {"kind": "target", "exit_raw": raw, "session": step + 1}
    return {"kind": "horizon", "exit_raw": float(book["close"][last - 1]), "session": horizon}


def diagnose_book_losses(
    start: date,
    end: date,
    kind: str = "momentum_20d",
    stop_multiple: float = 1.05,
    horizon: int = 4,
) -> Dict[str, Any]:
    """Break a research book's losing trades into gap, stop, time-stop, and cost.

    Research only. The live 1.05 ATR stop is not read or written here.
    """
    frame = _load(start, end)
    if frame.empty:
        return {"status": "no_bars"}
    packed = _books(frame)
    weeks = iter_week_signals(start, end)
    rng = np.random.default_rng(11)
    losers: List[Dict[str, Any]] = []
    filled = 0
    for signal, _saturday in weeks:
        day = frame[frame["trading_date"] == pd.Timestamp(signal)]
        if day.empty:
            continue
        chosen = _pick_symbols(day, kind, rng)
        for row in chosen.itertuples(index=False):
            book = packed.get(row.symbol)
            if book is None:
                continue
            signal_iso = signal.isoformat()
            pos = book["index"].get(signal_iso)
            if pos is None or pos + 1 + horizon > len(book["close"]):
                continue
            entry_pos = pos + 1
            gap_days = (date.fromisoformat(book["dates"][entry_pos]) - date.fromisoformat(signal_iso)).days
            if gap_days > 5:
                continue
            atr = float(row.atr)
            signal_close = float(book["close"][pos])
            entry = float(book["open"][entry_pos])
            if not atr or atr <= 0 or signal_close <= 0 or entry <= 0:
                continue
            stop_price = entry - (stop_multiple * atr)
            target_price = entry + 2.0 * atr
            result = execute_long_bracket(
                book["open"], book["high"], book["low"], book["close"],
                entry_pos, horizon, signal_close,
                stop_price=stop_price, target_price=target_price,
                turnover_inr=float(row.turn20 or 0.0) * 1e5,
                jumps=book["jump"],
            )
            if result.get("status") != "FILLED":
                continue
            if abs(float(result["gross_return_pct"])) > DATA_ERROR_RETURN_PCT:
                continue
            filled += 1
            net = float(result["net_return_pct"])
            if net > 0:
                continue
            path = _exit_path(book, entry_pos, horizon, stop_price, target_price)
            price_return = (path["exit_raw"] - entry) / entry * 100.0
            planned_stop = stop_multiple * atr / entry * 100.0
            losers.append({
                "symbol": row.symbol,
                "signal": signal_iso,
                "kind": path["kind"],
                "session": path["session"],
                "net_pct": round(net, 3),
                "price_return_pct": round(price_return, 3),
                "cost_drag_pct": round(price_return - net, 3),
                "atr_pct": round(atr / entry * 100.0, 3),
                "planned_stop_pct": round(planned_stop, 3),
                "gap_beyond_stop_pct": round(max(0.0, -price_return - planned_stop), 3),
            })
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for trade in losers:
        groups.setdefault(trade["kind"], []).append(trade)

    def _mean(values: List[float]) -> float:
        return round(sum(values) / len(values), 3) if values else 0.0

    loss_sum = sum(trade["net_pct"] for trade in losers)
    by_kind = {}
    for name, rows in groups.items():
        nets = [trade["net_pct"] for trade in rows]
        by_kind[name] = {
            "trades": len(rows),
            "share_of_losers_pct": round(len(rows) / len(losers) * 100.0, 1) if losers else 0.0,
            "share_of_loss_sum_pct": round(sum(nets) / loss_sum * 100.0, 1) if loss_sum else 0.0,
            "avg_net_pct": _mean(nets),
            "avg_price_return_pct": _mean([trade["price_return_pct"] for trade in rows]),
            "avg_cost_drag_pct": _mean([trade["cost_drag_pct"] for trade in rows]),
            "avg_atr_pct": _mean([trade["atr_pct"] for trade in rows]),
            "avg_planned_stop_pct": _mean([trade["planned_stop_pct"] for trade in rows]),
            "avg_gap_beyond_stop_pct": _mean([trade["gap_beyond_stop_pct"] for trade in rows]),
        }
    atr_values = [trade["atr_pct"] for trade in losers]
    report = {
        "book": kind,
        "stop_multiple": stop_multiple,
        "horizon_sessions": horizon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "filled": filled,
        "losers": len(losers),
        "avg_loser_net_pct": _mean([trade["net_pct"] for trade in losers]),
        "avg_loser_price_return_pct": _mean([trade["price_return_pct"] for trade in losers]),
        "avg_cost_drag_pct": _mean([trade["cost_drag_pct"] for trade in losers]),
        "avg_atr_pct": _mean(atr_values),
        "avg_planned_stop_pct": _mean([trade["planned_stop_pct"] for trade in losers]),
        "losers_with_atr_pct_at_least_5": sum(1 for value in atr_values if value >= 5.0),
        "by_kind": by_kind,
    }
    path = Path(REPORTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    (path / "momentum_loss_diagnosis.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "# Momentum book losers",
        "",
        f"Window: {start.isoformat()} to {end.isoformat()}. Stop {stop_multiple:g} x ATR, target 2 ATR, horizon {horizon}.",
        "Research book only. The live stop is unchanged.",
        "",
        f"Filled {filled}. Losers {len(losers)}. Average loser {report['avg_loser_net_pct']}%.",
        f"Average price path {report['avg_loser_price_return_pct']}%. Average cost drag {report['avg_cost_drag_pct']} points.",
        f"Average ATR {report['avg_atr_pct']}% of the entry. Average planned stop {report['avg_planned_stop_pct']}%.",
        f"Losers whose ATR was at least 5% of price: {report['losers_with_atr_pct_at_least_5']}.",
        "",
    ]
    for name, row in by_kind.items():
        lines.append(
            f"- {name}: {row['trades']} trades ({row['share_of_losers_pct']}% of losers, "
            f"{row['share_of_loss_sum_pct']}% of the loss sum). "
            f"Avg net {row['avg_net_pct']}%, price path {row['avg_price_return_pct']}%, "
            f"costs {row['avg_cost_drag_pct']} points, ATR {row['avg_atr_pct']}% , "
            f"planned stop {row['avg_planned_stop_pct']}%, gap beyond stop {row['avg_gap_beyond_stop_pct']}%."
        )
    lines.append("")
    (path / "momentum_loss_diagnosis.md").write_text("\n".join(lines), encoding="utf-8")
    return report


def _write(report: Dict[str, Any]) -> None:
    path = Path(REPORTS_DIR)
    path.mkdir(parents=True, exist_ok=True)
    (path / "signal_research.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    edge = report.get("factor_edge") or {}
    lines = [
        "# Signal Research",
        "",
        f"Window: {report['start_date']} to {report['end_date']}",
        "Each baseline book buys the next open, risks one ATR, and takes profit at two ATR, with the same costs as the live book.",
        f"Universe week-close base rate: {report['summary'].get('base_rate_pct')}%.",
        "",
        edge.get("reading") or "No factor reading.",
        f"Delivery rank correlation: {edge.get('delivery_z_rank_correlation')}.",
        f"20-day momentum rank correlation: {edge.get('momentum_20d_rank_correlation')}.",
        "",
        "Four-session books:",
    ]
    for name, basket in (report.get("baselines") or {}).items():
        lines.append(
            f"- {name}: win rate {basket['win_rate_pct']}% , expectancy {basket['expectancy_pct']}%, "
            f"profit factor {basket['profit_factor']}, trades {basket['predicted']}"
        )
    lines.append("")
    for name, horizons in (report.get("by_horizon") or {}).items():
        bits = [f"{label} {row['expectancy_pct']}%" for label, row in horizons.items()]
        lines.append(f"- {name} expectancy by hold: {', '.join(bits)}")
    lines.append("")
    (path / "signal_research.md").write_text("\n".join(lines), encoding="utf-8")
