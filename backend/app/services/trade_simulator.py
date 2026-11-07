"""
How a weekly long is actually filled, exited, costed, and sized.

Signal on the session close. Fill at the next session's open. A gap through the
target or through the stop is not a fill. Stop and target on the same bar assume
the stop traded first. Costs are statutory delivery friction plus slippage that
widens as turnover thins. A return past the data-error band is a bad print or a
missed corporate action, and it is not a result.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from app.config import (
    DATA_ERROR_RETURN_PCT,
    MAX_GAP_CHASE_PCT,
    MAX_POSITION_PCT,
    PORTFOLIO_START_CAPITAL,
    RISK_PER_TRADE_PCT,
    ROUNDTRIP_FRICTION_PCT,
)


def slippage_pct(turnover_inr: float) -> float:
    """One-way slippage in percent. ₹100 Cr pays 5 bps, ₹10 Cr pays 15, thinner pays 40."""
    crore = (turnover_inr or 0.0) / 1e7
    if crore >= 100.0:
        return 0.05
    if crore >= 10.0:
        return 0.15
    return 0.40


def _locked(open_p: float, high_p: float, low_p: float, close_p: float) -> bool:
    return bool(open_p == high_p == low_p == close_p)


def execute_long_bracket(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    start: int,
    horizon: int,
    signal_close: float,
    stop_price: float,
    target_price: float,
    turnover_inr: float = 0.0,
    jumps: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Fill one long and walk `horizon` sessions beginning at `start`."""
    last = start + horizon
    if signal_close <= 0 or start < 0 or last > len(closes):
        return {"status": "NO_DATA"}
    entry = float(opens[start])
    if not np.isfinite(entry) or entry <= 0:
        return {"status": "NO_DATA"}
    if jumps is not None and bool(np.any(jumps[start:last])):
        return {"status": "DATA_ERROR", "reason": "UNEXPLAINED_JUMP"}

    entry_high = float(highs[start])
    entry_low = float(lows[start])
    entry_close = float(closes[start])
    if _locked(entry, entry_high, entry_low, entry_close) and entry_close > signal_close:
        return {"status": "REJECTED", "reason": "UPPER_CIRCUIT"}
    if entry > signal_close * (1.0 + MAX_GAP_CHASE_PCT / 100.0) or (
        target_price > signal_close and entry >= target_price
    ):
        return {"status": "REJECTED", "reason": "GAP_CHASE"}
    if stop_price > 0 and entry <= stop_price:
        return {"status": "REJECTED", "reason": "GAP_BELOW_STOP"}

    slip = slippage_pct(turnover_inr) / 100.0
    fill_entry = entry * (1.0 + slip)
    exit_raw = float(closes[last - 1])
    reason = "HORIZON"
    for k in range(start, last):
        bar_open = float(opens[k])
        bar_high = float(highs[k])
        bar_low = float(lows[k])
        stop_hit = stop_price > 0 and bar_low <= stop_price
        target_hit = target_price > 0 and bar_high >= target_price
        if stop_hit and target_hit:
            exit_raw = min(bar_open, stop_price)
            reason = "STOP"
            break
        if stop_hit:
            exit_raw = min(bar_open, stop_price)
            reason = "STOP"
            break
        if target_hit:
            exit_raw = bar_open if bar_open > target_price else target_price
            reason = "TARGET"
            break
    if exit_raw <= 0:
        return {"status": "NO_DATA"}
    fill_exit = exit_raw * (1.0 - slip)
    gross = ((fill_exit - fill_entry) / fill_entry) * 100.0
    if abs(gross) > DATA_ERROR_RETURN_PCT:
        return {"status": "DATA_ERROR", "reason": "EXTREME_RETURN", "gross_return_pct": round(gross, 2)}
    net = gross - float(ROUNDTRIP_FRICTION_PCT)
    return {
        "status": "FILLED",
        "entry_price": round(fill_entry, 2),
        "exit_price": round(fill_exit, 2),
        "stop_loss": round(float(stop_price), 2),
        "target_price": round(float(target_price), 2),
        "gross_return_pct": round(gross, 2),
        "net_return_pct": round(net, 2),
        "exit_reason": reason,
        "slippage_pct": round(slip * 100.0, 2),
    }


def execute_frame(
    frame,
    signal_iso: str,
    horizon: int,
    stop_price: float,
    target_price: float,
    turnover_inr: float,
    last_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Same bracket, read off a back-adjusted OHLC frame indexed by session."""
    if frame is None or getattr(frame, "empty", True):
        return {"status": "NO_DATA"}
    stamps = frame.index.strftime("%Y-%m-%d")
    prior = frame[stamps <= signal_iso]
    forward = frame[stamps > signal_iso]
    if last_iso:
        forward = forward[forward.index.strftime("%Y-%m-%d") <= last_iso]
    if prior.empty or forward.empty:
        return {"status": "NO_DATA"}
    window = forward.iloc[:horizon]
    if len(window) < horizon and last_iso is None:
        return {"status": "NO_DATA"}
    if window.empty:
        return {"status": "NO_DATA"}
    signal_close = float(prior["Close"].iloc[-1])
    jumps = None
    if "unexplained_jump" in frame.columns:
        jumps = frame["unexplained_jump"].fillna(False).to_numpy()
        start = len(prior)
        return execute_long_bracket(
            frame["Open"].to_numpy(float),
            frame["High"].to_numpy(float),
            frame["Low"].to_numpy(float),
            frame["Close"].to_numpy(float),
            start,
            len(window),
            signal_close,
            stop_price,
            target_price,
            turnover_inr,
            jumps,
        )
    return execute_long_bracket(
        window["Open"].to_numpy(float),
        window["High"].to_numpy(float),
        window["Low"].to_numpy(float),
        window["Close"].to_numpy(float),
        0,
        len(window),
        signal_close,
        stop_price,
        target_price,
        turnover_inr,
        None,
    )


def simulate_portfolio(
    trades: List[Dict[str, Any]],
    start_capital: float = PORTFOLIO_START_CAPITAL,
) -> Dict[str, Any]:
    """Fixed fractional risk, one cohort per signal date, no leverage past cash."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for trade in trades:
        groups.setdefault(str(trade.get("signal_date") or ""), []).append(trade)
    equity = float(start_capital)
    peak = equity
    max_dd = 0.0
    curve = []
    for signal_date in sorted(groups):
        risk_cash = equity * (RISK_PER_TRADE_PCT / 100.0)
        deployed = 0.0
        week_pnl = 0.0
        for trade in groups[signal_date]:
            entry = float(trade.get("entry_price") or 0.0)
            stop = float(trade.get("stop_loss") or 0.0)
            if entry <= 0:
                continue
            distance = entry - stop
            if distance <= entry * 0.005:
                distance = entry * 0.01
            size = float(trade.get("regime_size") or 1.0)
            notional = min(
                risk_cash * size * entry / distance,
                equity * (MAX_POSITION_PCT / 100.0) * size,
            )
            notional = min(notional, max(0.0, equity - deployed))
            deployed += notional
            week_pnl += notional * float(trade.get("net_return_pct") or 0.0) / 100.0
        equity = max(0.0, equity + week_pnl)
        peak = max(peak, equity)
        drawdown = ((peak - equity) / peak) * 100.0 if peak else 0.0
        max_dd = max(max_dd, drawdown)
        curve.append({
            "signal_date": signal_date,
            "equity": round(equity, 2),
            "drawdown_pct": round(drawdown, 2),
        })
    return {
        "start_capital": round(float(start_capital), 2),
        "ending_equity": round(equity, 2),
        "total_return_pct": round((equity / start_capital - 1.0) * 100.0, 2) if start_capital else 0.0,
        "max_drawdown_pct": round(max_dd, 2),
        "curve": curve,
    }


def bootstrap_win_rate(trades: List[Dict[str, Any]], draws: int = 1000, seed: int = 7) -> Optional[Dict[str, float]]:
    """Resample whole weeks. Trades inside one week are not independent."""
    weeks: Dict[str, List[float]] = {}
    for trade in trades:
        weeks.setdefault(str(trade.get("signal_date") or ""), []).append(
            1.0 if float(trade.get("net_return_pct") or 0.0) > 0 else 0.0
        )
    blocks = [np.asarray(flags, dtype=float) for flags in weeks.values() if len(flags)]
    if len(blocks) < 8:
        return None
    rng = np.random.default_rng(seed)
    rates = np.empty(draws, dtype=float)
    for i in range(draws):
        chosen = rng.integers(0, len(blocks), size=len(blocks))
        sample = np.concatenate([blocks[j] for j in chosen])
        rates[i] = sample.mean() * 100.0
    return {
        "draws": draws,
        "weeks": len(blocks),
        "p05": round(float(np.percentile(rates, 5)), 1),
        "p50": round(float(np.percentile(rates, 50)), 1),
        "p95": round(float(np.percentile(rates, 95)), 1),
    }


def _sigmoid(z: np.ndarray) -> np.ndarray:
    z = np.clip(z, -20.0, 20.0)
    return 1.0 / (1.0 + np.exp(-z))


def calibrate_hit_model(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Walk-forward logistic fit. Train on the earlier weeks, score the later weeks.

    Coefficients are evidence, not a live weight change. Two hundred correlated
    trades are not enough to replace the desk's factor weights.
    """
    fields = ("rs_20d", "cmf_20", "rsi_14", "vol_surge", "delivery_zscore", "composite_score")
    usable = [t for t in trades if all(t.get(f) is not None for f in fields) and t.get("signal_date")]
    weeks = sorted({t["signal_date"] for t in usable})
    if len(weeks) < 16 or len(usable) < 80:
        return {"status": "too_few_trades", "trades": len(usable), "weeks": len(weeks)}
    cut = weeks[int(len(weeks) * 0.6)]
    train = [t for t in usable if t["signal_date"] < cut]
    test = [t for t in usable if t["signal_date"] >= cut]
    if len(train) < 40 or len(test) < 20:
        return {"status": "too_few_trades", "trades": len(usable), "weeks": len(weeks)}

    def matrix(rows: List[Dict[str, Any]]) -> np.ndarray:
        return np.asarray([[float(r[f]) for f in fields] for r in rows], dtype=float)

    def outcome(rows: List[Dict[str, Any]]) -> np.ndarray:
        return np.asarray([1.0 if float(r["net_return_pct"]) > 0 else 0.0 for r in rows], dtype=float)

    x_train = matrix(train)
    center = x_train.mean(axis=0)
    scale = x_train.std(axis=0)
    scale[scale < 1e-6] = 1.0
    x_train = (x_train - center) / scale
    y_train = outcome(train)
    x_test = (matrix(test) - center) / scale
    y_test = outcome(test)
    design = np.column_stack([np.ones(len(x_train)), x_train])
    weights = np.zeros(design.shape[1])
    for _ in range(25):
        prob = _sigmoid(design @ weights)
        w = prob * (1.0 - prob)
        w = np.clip(w, 1e-4, None)
        gradient = design.T @ (prob - y_train)
        hessian = design.T @ (design * w[:, None])
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            return {"status": "not_enough_variation", "trades": len(usable)}
        weights = weights - step
        if float(np.max(np.abs(step))) < 1e-4:
            break
    test_prob = _sigmoid(np.column_stack([np.ones(len(x_test)), x_test]) @ weights)
    raw = np.asarray([float(r.get("win_probability_pct") or 50.0) / 100.0 for r in test], dtype=float)
    raw = np.clip(raw, 0.05, 0.95)
    brier_model = float(np.mean((test_prob - y_test) ** 2))
    brier_raw = float(np.mean((raw - y_test) ** 2))
    return {
        "status": "ok",
        "train_trades": len(train),
        "test_trades": len(test),
        "test_weeks_from": cut,
        "fields": list(fields),
        "center": [round(float(value), 6) for value in center],
        "scale": [round(float(value), 6) for value in scale],
        "coefficients": {name: round(float(coef), 3) for name, coef in zip(("intercept",) + fields, weights)},
        "test_hit_rate_pct": round(float(y_test.mean() * 100.0), 1),
        "brier_model": round(brier_model, 4),
        "brier_stated_win_prob": round(brier_raw, 4),
        "model_beats_stated_probability": bool(brier_model + 0.005 < brier_raw),
        "applied_to_live_weights": False,
    }
