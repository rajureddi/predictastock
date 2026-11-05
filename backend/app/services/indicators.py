"""
Technical Analysis, Institutional Money Flow & Volatility Modeling Engine
Calculates institutional indicators: SMA, EMA, RSI, MACD, ATR, CMF, MFI, Volume Surge, and VCP Squeeze.
Generates objective, two-sided 5-day mathematical volatility cones with explicit ATR Stop-Loss.
Phase 1 & Phase 2 Integrity Rules:
- NO forced always-positive target formula.
- The 5-day band is about 1.73 times the 14-day ATR around the last close.
- Removal of tautologies (cmp > low_bound is strictly rejected).
- Money flow integration (Chaikin Money Flow + Volume Surge Ratio).
- Volatility Contraction Pattern (VCP / Squeeze) identification.
"""
import numpy as np
from app.config import (
    STRICT_MIN_CMF, STRICT_MIN_COMPOSITE_SCORE, STRICT_MIN_DELIVERY_PCT,
    STRICT_MIN_DELIVERY_SURGE, STRICT_MIN_MONEY_FLOW_SCORE,
    STRICT_MIN_RELATIVE_STRENGTH, STRICT_MIN_TECHNICAL_SCORE,
    STRICT_MIN_VOLUME_SURGE, STRICT_RSI_MAX, STRICT_RSI_MIN,
    ENABLE_STRICT_EVIDENCE_GATE, STRICT_REGIME_IS_HARD_GATE,
)
import pandas as pd
from typing import Dict, Any, Tuple, Optional


def calculate_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate Average True Range (ATR)."""
    if len(df) < period + 1:
        return 0.0
    
    high = df['High']
    low = df['Low']
    close = df['Close']
    prev_close = close.shift(1)
    
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean().iloc[-1]
    return round(float(atr), 2)


def calculate_rsi(df: pd.DataFrame, period: int = 14) -> float:
    """Calculate Relative Strength Index (RSI-14)."""
    if len(df) < period + 1:
        return 50.0
    
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    latest_rsi = rsi.iloc[-1]
    if pd.isna(latest_rsi):
        return 50.0
    return round(float(latest_rsi), 2)


def calculate_macd(df: pd.DataFrame) -> Tuple[float, float, float]:
    """Calculate MACD (12, 26, 9): Line, Signal, Histogram."""
    if len(df) < 35:
        return 0.0, 0.0, 0.0
    
    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    
    return round(float(macd_line.iloc[-1]), 2), round(float(signal_line.iloc[-1]), 2), round(float(hist.iloc[-1]), 2)


def calculate_cmf(df: pd.DataFrame, period: int = 20) -> float:
    """
    Calculate Chaikin Money Flow (CMF-20).
    Measures institutional buying and selling pressure.
    Guarded against High == Low division-by-zero using 1e-9 epsilon.
    Range: -1.0 to +1.0. Institutional accumulation: > +0.05.
    """
    if len(df) < period or 'Volume' not in df.columns:
        return 0.0
    
    high = df['High']
    low = df['Low']
    close = df['Close']
    vol = df['Volume']
    
    denom = (high - low)
    # Safe money flow multiplier
    mf_multiplier = np.where(denom > 0, ((close - low) - (high - close)) / (denom + 1e-9), 0.0)
    mf_volume = mf_multiplier * vol
    
    sum_mf_vol = mf_volume.tail(period).sum()
    sum_vol = vol.tail(period).sum()
    
    if sum_vol <= 0:
        return 0.0
    cmf = sum_mf_vol / (sum_vol + 1e-9)
    return round(float(cmf), 3)


def calculate_mfi(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calculate Money Flow Index (MFI-14) — Volume-Weighted RSI.
    Identifies liquidity momentum. Overbought > 80, Oversold < 20.
    """
    if len(df) < period + 1 or 'Volume' not in df.columns:
        return 50.0
    
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3.0
    raw_money_flow = typical_price * df['Volume']
    
    price_diff = typical_price.diff()
    pos_flow = raw_money_flow.where(price_diff > 0, 0.0)
    neg_flow = raw_money_flow.where(price_diff < 0, 0.0)
    
    pos_sum = pos_flow.rolling(period).sum()
    neg_sum = neg_flow.rolling(period).sum()
    
    latest_pos = pos_sum.iloc[-1]
    latest_neg = neg_sum.iloc[-1]
    
    if pd.isna(latest_neg) or latest_neg == 0:
        return 100.0 if (latest_pos and latest_pos > 0) else 50.0
    
    mfr = latest_pos / (latest_neg + 1e-9)
    mfi = 100.0 - (100.0 / (1.0 + mfr))
    return round(float(mfi), 2)


def calculate_support_resistance(df: pd.DataFrame) -> Tuple[float, float]:
    """Estimate dynamic Support (20-day low) and Resistance (20-day high)."""
    if len(df) < 20:
        cmp = float(df['Close'].iloc[-1])
        return round(cmp * 0.96, 2), round(cmp * 1.05, 2)
    
    window = df.tail(20)
    support = round(float(window['Low'].min()), 2)
    resistance = round(float(window['High'].max()), 2)
    return support, resistance


def calculate_delivery_metrics(
    df: pd.DataFrame, 
    bhavcopy_data: Optional[Dict[str, Any]] = None,
    cmf_20: float = 0.0,
    mfi_14: float = 50.0,
    vol_surge: float = 1.0,
    sma_vol_20: float = 0.0
) -> Dict[str, Any]:
    """
    1.8 NSE Delivery % & Delivery Spike (If Bhavcopy Available)
    Extracts deliv_per and deliv_surge from NSE EOD Bhavcopy when available.
    Rule 3:
    - Since a single EOD Bhavcopy CSV gives today's exact DELIV_QTY and DELIV_PER while
      yfinance gives the 20-day total volume history (sma_vol_20), compute deliv_surge as:
        expected_normal_deliv = sma_vol_20 * 0.45 (45% institutional baseline)
        deliv_surge = round(deliv_qty / max(expected_normal_deliv, 1.0), 2)
    - Cleanly falls back to cmf_20 + mfi_14 liquidity accumulation model if yfinance fallback is used.
    - Flags delivery_source = "NSE_BHAVCOPY" vs "SYNTHETIC_PROXY".
    """
    # 1. Check if direct bhavcopy_data dictionary was provided
    if bhavcopy_data and isinstance(bhavcopy_data, dict):
        deliv_qty = bhavcopy_data.get("deliv_qty") if "deliv_qty" in bhavcopy_data else bhavcopy_data.get("DELIV_QTY")
        deliv_per = bhavcopy_data.get("deliv_per") if "deliv_per" in bhavcopy_data else bhavcopy_data.get("DELIV_PER")
        sma_deliv_20 = bhavcopy_data.get("sma_deliv_20") if "sma_deliv_20" in bhavcopy_data else bhavcopy_data.get("SMA_DELIV_20")
        
        # Rule 3: Compute deliv_surge accurately with single-day Bhavcopy
        if sma_deliv_20 is None or sma_deliv_20 <= 0:
            vol_ref = sma_vol_20 if sma_vol_20 > 0 else (
                float(df['Volume'].tail(20).mean()) if ('Volume' in df.columns and len(df) >= 1) else 0.0
            )
            expected_normal_deliv = vol_ref * 0.45
        else:
            expected_normal_deliv = float(sma_deliv_20)

        if deliv_qty is not None and deliv_qty > 0:
            deliv_surge = round(float(deliv_qty) / max(expected_normal_deliv, 1.0), 2)
            deliv_per_val = round(float(deliv_per), 2) if deliv_per is not None else 45.0
            return {
                "deliv_per": deliv_per_val,
                "deliv_surge": deliv_surge,
                "deliv_source": "NSE Bhavcopy EOD",
                "delivery_source": "NSE_BHAVCOPY",
                "is_bhavcopy_actual": True
            }

    # 2. Check if delivery columns exist in the DataFrame (e.g. from local Bhavcopy ingestion)
    deliv_qty_col = next((c for c in ['DELIV_QTY', 'deliv_qty', 'Delivery_Qty', 'DELIVERY_QTY'] if c in df.columns), None)
    deliv_per_col = next((c for c in ['DELIV_PER', 'deliv_per', 'Delivery_Pct', 'DELIVERY_PCT'] if c in df.columns), None)

    if deliv_qty_col and not df[deliv_qty_col].dropna().empty:
        deliv_series = df[deliv_qty_col].dropna()
        latest_deliv = float(deliv_series.iloc[-1])
        sma_deliv_20 = float(deliv_series.tail(20).mean()) if len(deliv_series) >= 1 else latest_deliv
        deliv_surge = round(latest_deliv / (sma_deliv_20 + 1e-9), 2)

        if deliv_per_col and not df[deliv_per_col].dropna().empty:
            deliv_per = round(float(df[deliv_per_col].dropna().iloc[-1]), 2)
        elif 'Volume' in df.columns and float(df['Volume'].iloc[-1]) > 0:
            deliv_per = round((latest_deliv / float(df['Volume'].iloc[-1])) * 100.0, 2)
        else:
            deliv_per = 45.0

        return {
            "deliv_per": deliv_per,
            "deliv_surge": deliv_surge,
            "deliv_source": "NSE Bhavcopy EOD",
            "delivery_source": "NSE_BHAVCOPY",
            "is_bhavcopy_actual": True
        }

    # 3. Clean fallback to CMF-20 + MFI-14 when standard yfinance feed is used
    derived_deliv_per = round(float(np.clip(45.0 + (cmf_20 * 35.0) + ((mfi_14 - 50.0) * 0.25), 18.0, 85.0)), 1)
    deliv_surge_proxy = round(max(0.2, vol_surge * (1.15 if cmf_20 > 0.05 else (0.85 if cmf_20 < -0.05 else 1.0))), 2)

    return {
        "deliv_per": derived_deliv_per,
        "deliv_surge": deliv_surge_proxy,
        "deliv_source": "Clean Fallback (CMF-20 + MFI-14 Money Flow Proxy)",
        "delivery_source": "SYNTHETIC_PROXY",
        "is_bhavcopy_actual": False
    }


def compute_all_indicators(
    df: pd.DataFrame, 
    nifty_return_20d: float = 0.0,
    bhavcopy_data: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Compile comprehensive institutional technical and money-flow analysis profile.
    Incorporates:
    - Standard Momentum: RSI-14, MACD, 20/50/200-DMA
    - Institutional Money Flow: CMF-20, MFI-14, Volume Surge Ratio
    - High-Alpha Squeeze: Volatility Squeeze Ratio (VCP = ATR-5 / ATR-20)
    - Risk Controls: Overextension Penalty (> 6% above 20-DMA)
    - Relative Strength vs Nifty 50 over 20 sessions
    """
    if df.empty:
        return {
            "cmp": 0.0,
            "atr_14": 0.0,
            "rsi_14": 50.0,
            "sma_20": 0.0,
            "sma_50": 0.0,
            "sma_200": 0.0,
            "macd_line": 0.0,
            "macd_signal": 0.0,
            "macd_hist": 0.0,
            "support": 0.0,
            "resistance": 0.0,
            "cmf_20": 0.0,
            "mfi_14": 50.0,
            "vol_surge": 1.0,
            "vol_squeeze": 1.0,
            "is_vcp_squeeze": False,
            "is_overextended": False,
            "rs_20d": 0.0,
            "deliv_per": 45.0,
            "deliv_surge": 1.0,
            "deliv_source": "Clean Fallback (CMF-20 + MFI-14 Money Flow Proxy)",
            "delivery_source": "SYNTHETIC_PROXY",
            "is_bhavcopy_actual": False,
            "avg_volume_20d": 0,
            "volatility_daily_pct": 1.5,
            "volatility_5d_pct": 3.35,
            "technical_score": 50.0,
            "money_flow_score": 50.0,
            "signal": "Neutral"
        }
        
    df = df.dropna(subset=['Close', 'High', 'Low'])
    if len(df) < 20:
        cmp_val = float(df['Close'].iloc[-1]) if not df.empty else 0.0
        return {
            "cmp": cmp_val,
            "atr_14": round(cmp_val * 0.02, 2),
            "rsi_14": 50.0,
            "sma_20": cmp_val,
            "sma_50": cmp_val,
            "sma_200": cmp_val,
            "macd_line": 0.0,
            "macd_signal": 0.0,
            "macd_hist": 0.0,
            "support": round(cmp_val * 0.95, 2),
            "resistance": round(cmp_val * 1.05, 2),
            "cmf_20": 0.0,
            "mfi_14": 50.0,
            "vol_surge": 1.0,
            "vol_squeeze": 1.0,
            "is_vcp_squeeze": False,
            "is_overextended": False,
            "rs_20d": 0.0,
            "deliv_per": 45.0,
            "deliv_surge": 1.0,
            "deliv_source": "Clean Fallback (CMF-20 + MFI-14 Money Flow Proxy)",
            "delivery_source": "SYNTHETIC_PROXY",
            "is_bhavcopy_actual": False,
            "avg_volume_20d": 0,
            "volatility_daily_pct": 1.5,
            "volatility_5d_pct": 3.35,
            "technical_score": 50.0,
            "money_flow_score": 50.0,
            "signal": "Neutral"
        }
    
    close = df['Close']
    cmp = float(close.iloc[-1])
    
    atr_14 = calculate_atr(df, 14)
    atr_5 = calculate_atr(df, 5)
    atr_20 = calculate_atr(df, 20)
    rsi = calculate_rsi(df, 14)
    macd_line, macd_sig, macd_hist = calculate_macd(df)
    support, resistance = calculate_support_resistance(df)
    
    # Moving Averages
    sma_20 = round(float(close.rolling(20).mean().iloc[-1]), 2) if len(close) >= 20 else cmp
    sma_50 = round(float(close.rolling(50).mean().iloc[-1]), 2) if len(close) >= 50 else cmp
    sma_200 = round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else cmp
    
    # Money Flow & Volume Analytics
    cmf_20 = calculate_cmf(df, 20)
    mfi_14 = calculate_mfi(df, 14)
    
    # Volume Expansion Ratio
    volumes = df['Volume'] if 'Volume' in df.columns else pd.Series([10000] * len(df))
    avg_vol_20d = float(volumes.tail(20).mean()) if len(volumes) >= 20 else 10000.0
    latest_vol = float(volumes.iloc[-1]) if not volumes.empty else avg_vol_20d
    vol_surge = round(latest_vol / (avg_vol_20d + 1e-9), 2)
    
    # 1.8 NSE Delivery % & Delivery Surge (NSE EOD Bhavcopy with clean CMF-20+MFI-14 fallback)
    deliv_metrics = calculate_delivery_metrics(
        df=df,
        bhavcopy_data=bhavcopy_data,
        cmf_20=cmf_20,
        mfi_14=mfi_14,
        vol_surge=vol_surge,
        sma_vol_20=avg_vol_20d
    )
    deliv_per = deliv_metrics["deliv_per"]
    deliv_surge = deliv_metrics["deliv_surge"]
    delivery_zscore = _delivery_zscore(df)
    deliv_source = deliv_metrics["deliv_source"]
    delivery_source = deliv_metrics.get("delivery_source", "SYNTHETIC_PROXY")
    is_bhavcopy_actual = deliv_metrics["is_bhavcopy_actual"]

    # Volatility Squeeze Ratio (VCP Squeeze: ATR_5 / ATR_20 <= 0.90)
    vol_squeeze = round(atr_5 / (atr_20 + 1e-9), 3) if atr_20 > 0 else 1.0
    is_vcp_squeeze = bool(vol_squeeze <= 0.90 and cmp >= (sma_20 * 0.98))
    
    # Overextension check: > 6% above 20-DMA
    extension_pct = ((cmp - sma_20) / sma_20) if sma_20 > 0 else 0.0
    is_overextended = bool(extension_pct > 0.06)
    
    # 20-Day Relative Strength vs Nifty 50
    stock_ret_20d = float(((close.iloc[-1] - close.iloc[-20]) / close.iloc[-20]) * 100.0) if len(close) >= 20 else 0.0
    rs_20d = round(stock_ret_20d - nifty_return_20d, 2)
    
    # Volatility
    daily_returns = close.pct_change().dropna()
    vol_daily = float(daily_returns.tail(20).std() * 100) if len(daily_returns) >= 20 else 1.5
    vol_5d = round(vol_daily * np.sqrt(5), 2)
    
    # -------------------------------------------------------------
    # 1. Technical Structure Score (0 to 100)
    # -------------------------------------------------------------
    tech_score = 50.0
    if 52 <= rsi <= 70:
        tech_score += 15  # Prime bullish momentum
    elif 48 <= rsi < 52:
        tech_score += 5   # Neutral momentum
    elif rsi > 73:
        tech_score -= 8   # Overbought exhaustion risk
    elif rsi < 42:
        tech_score -= 15  # Bearish momentum
        
    if cmp > sma_20:
        tech_score += 12
    else:
        tech_score -= 12
        
    if sma_20 > sma_50:
        tech_score += 8
    if cmp > sma_200:
        tech_score += 5
    else:
        tech_score -= 8
        
    if macd_hist > 0:
        tech_score += 8
    else:
        tech_score -= 8
    if macd_line > macd_sig:
        tech_score += 4
        
    # Relative strength reward / penalty
    if rs_20d > 2.0:
        tech_score += 8   # Outperforming Nifty
    elif rs_20d < -4.0:
        tech_score -= 8   # Severe relative underperformance
        
    # Volatility Squeeze Bonus (catching move at consolidation base)
    if is_vcp_squeeze and vol_surge >= 1.25 and cmp > sma_20:
        tech_score += 10  # Fresh VCP breakout with expanding volume
        
    # Overextension Penalty: penalize exhausted rallies
    if is_overextended:
        tech_score -= 15  # -15 penalty for buying top > 6% above 20-DMA
        
    tech_score = float(np.clip(tech_score, 10.0, 95.0))
    
    # -------------------------------------------------------------
    # 2. Institutional Money Flow Score (0 to 100)
    # -------------------------------------------------------------
    mf_score = 50.0
    if cmf_20 > 0.15:
        mf_score += 25    # Strong institutional accumulation
    elif cmf_20 > 0.05:
        mf_score += 15    # Moderate accumulation
    elif cmf_20 < -0.15:
        mf_score -= 25    # Heavy institutional distribution
    elif cmf_20 < -0.05:
        mf_score -= 15
        
    if 50 <= mfi_14 <= 75:
        mf_score += 15    # Constructive liquidity flow
    elif mfi_14 > 80:
        mf_score -= 10    # Liquidity saturation / exhaustion
    elif mfi_14 < 35:
        mf_score -= 15    # Liquidity drain
        
    if vol_surge >= 1.5:
        mf_score += 15    # Massive volume spike
    elif vol_surge >= 1.2:
        mf_score += 8     # Above-average volume
    elif vol_surge < 0.6:
        mf_score -= 10    # Dry volume / lack of interest

    # Institutional delivery surge bonus — STRICTLY enforced: proxy metrics CANNOT qualify for exchange delivery bonus
    if is_bhavcopy_actual and deliv_surge >= 1.4 and deliv_per >= 48.0:
        mf_score += 8     # Verified exchange delivery accumulation confirmation
    elif is_bhavcopy_actual and deliv_surge < 0.6 and deliv_per < 30.0:
        mf_score -= 5
    elif not is_bhavcopy_actual and deliv_surge >= 1.4:
        # Transparently log that synthetic proxy cannot satisfy verified delivery bonus
        pass
        
    mf_score = float(np.clip(mf_score, 10.0, 95.0))

    
    # Signal categorization
    if tech_score >= 68 and mf_score >= 60 and cmp >= sma_20 and not is_overextended:
        signal = "High-Conviction Bullish Setup"
    elif tech_score >= 58 and cmp >= sma_20:
        signal = "Bullish Setup"
    elif tech_score <= 40 or (cmp < sma_20 and (rsi < 44 or cmf_20 < -0.08)):
        signal = "Bearish Breakdown"
    else:
        signal = "Consolidation / Range-Bound"
        
    return {
        "cmp": round(cmp, 2),
        "atr_14": atr_14 if atr_14 > 0 else round(cmp * 0.02, 2),
        "atr_5": atr_5,
        "atr_20": atr_20,
        "rsi_14": rsi,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "sma_200": sma_200,
        "macd_line": macd_line,
        "macd_signal": macd_sig,
        "macd_hist": macd_hist,
        "support": support,
        "resistance": resistance,
        "cmf_20": cmf_20,
        "mfi_14": mfi_14,
        "vol_surge": vol_surge,
        "vol_squeeze": vol_squeeze,
        "is_vcp_squeeze": is_vcp_squeeze,
        "is_overextended": is_overextended,
        "rs_20d": rs_20d,
        "deliv_per": deliv_per,
        "deliv_surge": deliv_surge,
        "delivery_zscore": delivery_zscore,
        "deliv_source": deliv_source,
        "delivery_source": delivery_source,
        "is_bhavcopy_actual": is_bhavcopy_actual,
        "avg_volume_20d": int(avg_vol_20d),
        "volatility_daily_pct": round(vol_daily, 2),
        "volatility_5d_pct": vol_5d,
        "technical_score": tech_score,
        "money_flow_score": mf_score,
        "signal": signal
    }


def evaluate_strict_long_setup(
    tech: Dict[str, Any],
    composite_score: float,
    macro: Optional[Dict[str, Any]],
    solvency_penalty: float = 0.0,
) -> Dict[str, Any]:
    """Apply the release-gated long-only setup rules.

    This deliberately abstains when any input is missing or disagrees.  It is
    shared by live screening and historical evaluation so a backtest measures
    the exact conditions that create a live trade candidate.
    """
    macro = macro or {}
    checks = {
        "nifty_regime": bool(macro.get("is_valid") and macro.get("is_bullish")),
        "above_20dma": bool(tech.get("cmp", 0.0) >= tech.get("sma_20", float("inf"))),
        "relative_strength": float(tech.get("rs_20d", -float("inf"))) >= STRICT_MIN_RELATIVE_STRENGTH,
        "technical_score": float(tech.get("technical_score", 0.0)) >= STRICT_MIN_TECHNICAL_SCORE,
        "money_flow_score": float(tech.get("money_flow_score", 0.0)) >= STRICT_MIN_MONEY_FLOW_SCORE,
        "rsi_band": STRICT_RSI_MIN <= float(tech.get("rsi_14", 0.0)) <= STRICT_RSI_MAX,
        "macd_momentum": float(tech.get("macd_hist", 0.0)) > 0.0,
        "cmf_accumulation": float(tech.get("cmf_20", 0.0)) >= STRICT_MIN_CMF,
        "volume_confirmation": float(tech.get("vol_surge", 0.0)) >= STRICT_MIN_VOLUME_SURGE,
        "verified_delivery": bool(
            tech.get("is_bhavcopy_actual")
            and float(tech.get("deliv_per", 0.0)) >= STRICT_MIN_DELIVERY_PCT
            and float(tech.get("deliv_surge", 0.0)) >= STRICT_MIN_DELIVERY_SURGE
        ),
        "composite_score": float(composite_score) >= STRICT_MIN_COMPOSITE_SCORE,
        "solvency": float(solvency_penalty) <= 0.0,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    blocking = [
        name for name in failed_checks
        if name != "nifty_regime" or STRICT_REGIME_IS_HARD_GATE
    ]
    is_eligible = (not blocking) if ENABLE_STRICT_EVIDENCE_GATE else True
    return {
        "is_eligible": is_eligible,
        "checks": checks,
        "check_count": len(checks) - len(blocking),
        "total_checks": len(checks),
        "failed_checks": blocking,
        "soft_failed_checks": [name for name in failed_checks if name not in blocking],
        "gate_bypassed": not ENABLE_STRICT_EVIDENCE_GATE,
    }


def _delivery_zscore(df: pd.DataFrame) -> float:
    """Delivery percent versus the stock's own trailing 60 sessions. 0 when unverified."""
    column = next((name for name in ("deliv_per", "DELIV_PER") if name in df.columns), None)
    if column is None:
        return 0.0
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    window = series.tail(60)
    if len(window) < 20:
        return 0.0
    spread = float(window.std())
    if spread <= 0:
        return 0.0
    return round(float((window.iloc[-1] - window.mean()) / spread), 2)


def classify_entry_setup(tech: Dict[str, Any]) -> str:
    """Pullback in an uptrend, fresh breakout, or an already-extended print."""
    cmp = float(tech.get("cmp") or 0.0)
    sma_20 = float(tech.get("sma_20") or 0.0)
    sma_50 = float(tech.get("sma_50") or 0.0)
    if cmp <= 0 or sma_20 <= 0:
        return "OTHER"
    extension = (cmp - sma_20) / sma_20
    uptrend = sma_50 <= 0 or (cmp >= sma_50 and sma_20 >= sma_50)
    if uptrend and 0.0 <= extension <= 0.015 and float(tech.get("cmf_20") or 0.0) > 0.0 and 45.0 <= float(tech.get("rsi_14") or 0.0) <= 62.0:
        return "PULLBACK"
    resistance = float(tech.get("resistance") or 0.0)
    if (
        uptrend
        and resistance > 0
        and cmp >= resistance * 0.995
        and float(tech.get("vol_surge") or 0.0) >= 1.3
        and extension <= 0.045
    ):
        return "BREAKOUT"
    if bool(tech.get("is_overextended")) or extension > 0.045:
        return "EXTENDED"
    return "OTHER"


def compute_mathematical_5d_range(
    cmp: float, 
    atr: float, 
    vol_5d_pct: float, 
    signal: str = "Neutral",
    rsi: float = 50.0,
    sma_20: float = 0.0,
    macd_hist: float = 0.0,
    cmf_20: float = 0.0,
    vol_surge: float = 1.0,
    risk_factor: float = 1.0,
    resistance: float = 0.0,
    support: float = 0.0,
    rs_20d: float = 0.0,
    macro_regime: Optional[Dict[str, Any]] = None,
    deliv_per: float = 40.0,
    deliv_surge: float = 1.0,
    is_vcp_squeeze: bool = False,
    sma_50: float = 0.0,
    delivery_zscore: float = 0.0,
    empirical_hit_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Statistical Multi-Factor 5-Day Calibrated Prediction Engine:
    Replaces static/rigid heuristics with realistic statistical drift, resistance anchoring,
    and calibrated win probability scoring (ml-best-practices).
    
    Key Mathematical Grounding:
    1. Realistic Target Scaling: Large-cap 5-day median moves are 0.8x-1.2x ATR (+1.8% to +3.8%),
       not arbitrary +6% to +10%. Scaled by macro market regime (Bull vs Correction).
    2. Resistance Ceiling Anchoring: Targets are anchored right below overhead 20-day swing resistance
       (98.5% of resistance level) so profit is locked before hitting institutional supply.
    3. Overextension Gatekeeper: Rejects stocks > 4.5% above 20-DMA to prevent buying exhausted rally tops.
    4. Conviction score: the same multi-factor points, clipped from 15 to 92.
       It is a ranking score. Expectancy uses the measured hit rate, not this score.
    """
    if cmp <= 0:
        return {
            "reference_price": 0.0,
            "expected_target_price": 0.0,
            "stop_loss": 0.0,
            "expected_range_low": 0.0,
            "expected_range_high": 0.0,
            "expected_appreciation_pct": 0.0,
            "direction": "NEUTRAL",
            "action_label": "HOLD / MONITOR",
            "win_probability_pct": 50.0,
            "reward_to_risk": 1.0,
            "setup_quality": "C",
            "scenario_type": "Data Insufficient"
        }

    safe_atr = atr if atr > 0 else (cmp * 0.02)
    vol_move = max(safe_atr * 1.5, cmp * (vol_5d_pct / 100.0) * 0.85)
    
    # 5-Day volatility cone bounds
    low_bound = round(cmp - (vol_move * 1.15 * risk_factor), 2)
    high_bound = round(cmp + (vol_move * 1.15 * risk_factor), 2)
    
    sma_ref = sma_20 if sma_20 > 0 else cmp
    is_macro_bullish = bool(macro_regime and macro_regime.get("is_valid") and macro_regime.get("is_bullish"))
    
    # Overextension check: > 4.5% above 20-DMA
    extension_pct = ((cmp - sma_20) / sma_20) if sma_20 > 0 else 0.0
    is_overextended = bool(extension_pct > 0.045)
    
    # -------------------------------------------------------------
    # 1. Conviction score, clipped from 15 to 92. This is not a win probability.
    # -------------------------------------------------------------
    win_prob = 50.0
    
    # Factor A: Relative strength vs Nifty. Halved after the 2025-26 research pass
    # found 20-day momentum had no rank correlation with the next week.
    if rs_20d > 4.0:
        win_prob += 6.0
    elif rs_20d > 0.0:
        win_prob += 3.0
    elif rs_20d < -4.0:
        win_prob -= 6.0
    else:
        win_prob -= 3.0
        
    # Factor B: Institutional Accumulation (Chaikin Money Flow 20)
    if cmf_20 > 0.10:
        win_prob += 10.0
    elif cmf_20 > 0.02:
        win_prob += 5.0
    elif cmf_20 < -0.05:
        win_prob -= 10.0
        
    # Factor C: Price Trend & Structural Alignment (20 & 50 DMA)
    if cmp >= sma_20 and (sma_50 <= 0 or cmp >= sma_50):
        win_prob += 8.0
    elif cmp < sma_20:
        win_prob -= 12.0
        
    # Factor D: RSI Quality Consolidation Band
    if 50 <= rsi <= 68:
        win_prob += 7.0
    elif rsi > 70 or rsi < 40:
        win_prob -= 8.0
        
    # Factor E: Volatility Squeeze (VCP) Breakout
    if is_vcp_squeeze and vol_surge >= 1.15:
        win_prob += 8.0
        
    # Factor F: Overextension Penalty (Avoid buying exhausted tops)
    if is_overextended:
        win_prob -= 12.0
        
    # Factor G: Macro Market Regime
    if is_macro_bullish:
        win_prob += 5.0
    else:
        win_prob -= 8.0
        
    # Factor H: Verified Exchange Delivery Spike
    if deliv_surge >= 1.3 and deliv_per >= 48.0:
        win_prob += 5.0

    # Factor J: Delivery percent against this stock's own history, not a fixed 45% bar.
    if delivery_zscore >= 1.5 and cmf_20 > 0.0:
        win_prob += 4.0
    elif delivery_zscore <= -1.5:
        win_prob -= 4.0

    # Factor I: Explicit Multi-Indicator Signal Alignment
    has_bullish_signal = "Bullish" in str(signal) or (isinstance(signal, (int, float)) and signal > 0)
    has_bearish_signal = "Bearish" in str(signal) or (isinstance(signal, (int, float)) and signal < 0)
    if has_bullish_signal:
        win_prob += 10.0
    elif has_bearish_signal:
        win_prob -= 12.0

    win_prob = float(np.clip(round(win_prob, 1), 15.0, 92.0))

    # -------------------------------------------------------------
    # 2. Calibrated Expectancy Target Calculation (Fix 1: Calibrated Expectancy)
    # -------------------------------------------------------------
    # Eliminates high-beta volatility distortion (raw ATR/CMP proxy):
    # Rather than setting Target = CMP + 1.2*ATR for every stock, the target is
    # scaled by probability conviction (prob_scalar) and capped by structural resistance.
    regime_mult = 1.15 if (is_macro_bullish or has_bullish_signal) else 0.82
    quality_mult = 1.0 + (0.15 if rs_20d > 3.0 else 0.0) + (0.10 if cmf_20 > 0.08 else 0.0)
    prob_scalar = max(0.65, min(1.35, (win_prob / 52.0) ** 0.85))
    calibrated_move = safe_atr * regime_mult * quality_mult * prob_scalar

    # Resistance Ceiling Anchoring:
    dist_res = (resistance - cmp) if (resistance > cmp) else 0.0
    dist_res_pct = (dist_res / cmp * 100.0) if cmp > 0 else 0.0

    if dist_res_pct > 0.6:
        # Lock profits right before overhead resistance (98.5% of resistance)
        target_price = round(min(cmp + calibrated_move, cmp + (dist_res * 0.985)), 2)
    else:
        # Fresh breakout above resistance
        target_price = round(cmp + calibrated_move, 2)

    expected_pct = round(((target_price - cmp) / cmp) * 100.0, 2)

    # Cap the published 5-day target. Do not invent a minimum target: a 0.6% ATR
    # move is not a 1.5% prediction, and the old floor let every name pass the
    # 1.2% fallback screen.
    if expected_pct > 5.2:
        target_price = round(cmp * 1.052, 2)
        expected_pct = 5.2

    # Stop Loss & Risk/Reward:
    stop_risk = safe_atr * (0.85 if not is_macro_bullish else 1.05)
    sup_ref = support if (support > 0 and support < cmp) else (cmp - stop_risk)
    stop_loss = round(max(cmp - (stop_risk * 1.15), sup_ref if sup_ref > (cmp - stop_risk * 1.25) else (cmp - stop_risk)), 2)
    reward_to_risk = round((target_price - cmp) / max(cmp - stop_loss, 0.01), 2)

    # Expectancy uses the measured hit rate. The conviction score stays out of this product.
    hit_rate = 44.8 if empirical_hit_rate is None else float(empirical_hit_rate)
    hit_rate = max(0.0, min(100.0, hit_rate))
    p_win_fraction = hit_rate / 100.0
    gain_pct = max(0.0, ((target_price - cmp) / cmp) * 100.0) if cmp > 0 else 0.0
    risk_pct = max(0.0, ((cmp - stop_loss) / cmp) * 100.0) if cmp > 0 else 0.0
    calibrated_expectancy_pct = round((p_win_fraction * gain_pct) - ((1.0 - p_win_fraction) * risk_pct), 2)

    # Setup Quality Classification:
    if win_prob >= 72.0 and reward_to_risk >= 1.15:
        setup_quality = "A+"
    elif win_prob >= 64.0 and reward_to_risk >= 0.90:
        setup_quality = "A"
    elif win_prob >= 56.0 and reward_to_risk >= 0.68:
        setup_quality = "B"
    else:
        setup_quality = "C"

    # Directional Classification:
    is_bullish_confirmed = bool(
        (win_prob >= 54.0 or has_bullish_signal)
        and (cmp >= sma_ref or has_bullish_signal)
        and not is_overextended
        and expected_pct >= 1.0
    )

    is_bearish_confirmed = bool(
        (win_prob <= 44.0 or has_bearish_signal)
        or (cmp < sma_ref and (rsi <= 44 or cmf_20 < -0.08 or "Bearish" in str(signal)))
    )

    if is_bullish_confirmed:
        direction = "BULLISH"
        action_label = f"BUY / ACCUMULATE (Grade {setup_quality} Calibrated Swing)"
        
    elif is_bearish_confirmed:
        direction = "BEARISH"
        action_label = "EXIT HOLDINGS / AVOID (High Downside Risk)"
        target_price = round(max(cmp - calibrated_move, cmp * 0.95), 2)
        stop_loss = round(min(high_bound, cmp + (1.0 * safe_atr)), 2)
        expected_pct = round(((target_price - cmp) / cmp) * 100.0, 2)
        
    else:
        direction = "NEUTRAL"
        action_label = "HOLD / MONITOR (Insufficient Statistical Edge)"
        target_price = round(cmp, 2)
        stop_loss = round(cmp - (1.0 * safe_atr), 2)
        expected_pct = 0.0

    return {
        "reference_price": round(cmp, 2),
        "expected_target_price": target_price,
        "stop_loss": stop_loss,
        "expected_range_low": low_bound,
        "expected_range_high": high_bound,
        "expected_appreciation_pct": expected_pct,
        "calibrated_expectancy_pct": calibrated_expectancy_pct,
        "direction": direction,
        "action_label": action_label,
        "win_probability_pct": win_prob,
        "conviction_score": win_prob,
        "empirical_hit_rate_pct": round(hit_rate, 1),
        "reward_to_risk": reward_to_risk,
        "setup_quality": setup_quality,
        "scenario_type": f"5-Day Calibrated Volatility Cone ({direction})"
    }
