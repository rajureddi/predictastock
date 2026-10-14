"""
Technical Analysis, Institutional Money Flow & Volatility Modeling Engine
Calculates institutional indicators: SMA, EMA, RSI, MACD, ATR, CMF, MFI, Volume Surge, and VCP Squeeze.
Generates objective, two-sided 5-day mathematical volatility cones with explicit ATR Stop-Loss.
Phase 1 & Phase 2 Integrity Rules:
- NO forced always-positive target formula.
- Scaled via Brownian diffusion sqrt(5) mean-reverting dynamics (~2.0x ATR).
- Removal of tautologies (cmp > low_bound is strictly rejected).
- Money flow integration (Chaikin Money Flow + Volume Surge Ratio).
- Volatility Contraction Pattern (VCP / Squeeze) identification.
"""
import numpy as np
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
        deliv_qty = bhavcopy_data.get("deliv_qty")
        deliv_per = bhavcopy_data.get("deliv_per")
        sma_deliv_20 = bhavcopy_data.get("sma_deliv_20")
        
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

    # Institutional delivery surge bonus
    if deliv_surge >= 1.4 and deliv_per >= 48.0:
        mf_score += 8     # Delivery accumulation confirmation
    elif deliv_surge < 0.6 and deliv_per < 30.0:
        mf_score -= 5
        
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
    risk_factor: float = 1.0
) -> Dict[str, Any]:
    """
    Two-Sided Volatility-Calibrated 5-Day Forward Scenario:
    Calculates a mathematically sound 5-day diffusion move scaled via sqrt(5) (~2.0x ATR).
    Fixes:
    - Eliminates tautologies (cmp > low_bound and cmp < high_bound).
    - Requires true technical + money flow confirmation for BULLISH.
    - Explicitly computes ATR-based Stop-Loss (cmp - 1.0 * ATR for Long).
    - Accurately classifies Indian cash segment trading actions.
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
            "scenario_type": "Data Insufficient"
        }

    safe_atr = atr if atr > 0 else (cmp * 0.02)
    # Scaled properly via sqrt(5) mean-reverting dynamics (~2.0x ATR)
    vol_move = max(safe_atr * 2.0, cmp * (vol_5d_pct / 100.0) * 1.0)
    
    # 5-Day two-sided volatility cone bounds (L5 and H5)
    low_bound = round(cmp - (vol_move * 1.15 * risk_factor), 2)
    high_bound = round(cmp + (vol_move * 1.15 * risk_factor), 2)
    
    sma_ref = sma_20 if sma_20 > 0 else cmp
    
    # Non-tautological directional confirmation
    is_bullish_confirmed = (
        (cmp >= sma_ref or "Bullish" in str(signal) or (isinstance(signal, (int, float)) and signal > 0)) and 
        52 <= rsi <= 73 and 
        (macd_hist >= -0.05 or "Bullish" in str(signal) or (isinstance(signal, (int, float)) and signal > 0)) and
        (cmf_20 >= 0.0 or vol_surge >= 1.1 or (isinstance(signal, (int, float)) and signal > 0))
    )
    
    is_bearish_confirmed = (
        (cmp < sma_ref or "Bearish" in str(signal) or (isinstance(signal, (int, float)) and signal < 0)) and 
        (rsi <= 48 or cmf_20 < -0.05 or "Bearish" in str(signal) or (isinstance(signal, (int, float)) and signal < 0))
    )

    if is_bullish_confirmed:
        direction = "BULLISH"
        action_label = "BUY / ACCUMULATE (5-Day Swing)"
        # Target aligned with 5-day volatility expansion
        target_price = round(min(high_bound, cmp + (vol_move * 0.85)), 2)
        # Strict 1.0x ATR Stop-Loss below current price
        stop_loss = round(max(low_bound, cmp - (1.0 * safe_atr)), 2)
        expected_pct = round(((target_price - cmp) / cmp) * 100.0, 2)
        
    elif is_bearish_confirmed:
        direction = "BEARISH"
        # In India, retail cannot short cash equities multi-day overnight.
        action_label = "EXIT HOLDINGS / AVOID (F&O Short Only)"
        # Downside breakdown scenario
        target_price = round(max(low_bound, cmp - (vol_move * 0.85)), 2)
        # Stop-Loss for derivatives short
        stop_loss = round(min(high_bound, cmp + (1.0 * safe_atr)), 2)
        expected_pct = round(((target_price - cmp) / cmp) * 100.0, 2)
        
    else:
        direction = "NEUTRAL"
        action_label = "HOLD / MONITOR (Range-Bound)"
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
        "direction": direction,
        "action_label": action_label,
        "scenario_type": f"5-Day Volatility Cone ({direction})"
    }
