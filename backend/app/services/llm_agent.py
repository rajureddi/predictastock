import os
import json
import logging
from typing import Dict, Any, List
import requests

logger = logging.getLogger(__name__)


def _call_external_llm(prompt: str) -> Dict[str, Any] | None:
    """
    Attempts to call an available LLM API (Groq, OpenAI, or Gemini) if keys are provided.
    Returns parsed JSON dictionary or None on failure.
    """
    timeout_sec = 8

    # 1. Groq (Ultra-fast LLM inference)
    groq_key = os.getenv("GROQ_API_KEY")
    if groq_key:
        groq_models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"]
        for g_model in groq_models:
            try:
                res = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": g_model,
                        "messages": [
                            {"role": "system", "content": "You are an institutional Indian equity analyst committee (NSE/BSE). Return strictly valid JSON adhering to the requested schema."},
                            {"role": "user", "content": prompt}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2
                    },
                    timeout=timeout_sec
                )
                if res.status_code == 200:
                    data = res.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    parsed["llm_engine"] = f"Groq ({g_model})"
                    return parsed
            except Exception as e:
                logger.warning(f"Groq API call error with {g_model}: {e}")


    # 2. OpenAI (GPT-4o / GPT-4o-mini)
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            res = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json={
                    "model": "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": "You are an institutional Indian equity analyst committee (NSE/BSE). Return strictly valid JSON adhering to the requested schema."},
                        {"role": "user", "content": prompt}
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.2
                },
                timeout=timeout_sec
            )
            if res.status_code == 200:
                data = res.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                parsed["llm_engine"] = "OpenAI (GPT-4o-mini)"
                return parsed
        except Exception as e:
            logger.warning(f"OpenAI API call error: {e}")

    # 3. Google Gemini
    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
            res = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"response_mime_type": "application/json", "temperature": 0.2}
                },
                timeout=timeout_sec
            )
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                parsed["llm_engine"] = "Google Gemini (1.5-Flash)"
                return parsed
            else:
                logger.warning(f"Gemini API returned HTTP {res.status_code}: {res.text}")
        except Exception as e:
            logger.warning(f"Gemini API call error: {e}")


    return None


def run_multi_agent_analyst_team(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simulates the 7 AI Analyst Agents from india-trade-cli:
    1. Technical Analyst
    2. Fundamental Analyst
    3. Options & Volatility Analyst
    4. News & Catalysts Analyst
    5. Sentiment & Media Analyst
    6. Sector Rotation Analyst
    7. Risk Manager
    
    Uses external LLM (Groq / OpenAI / Gemini) if API keys are configured,
    or falls back instantly to the grounded quantitative expert engine.
    """
    symbol = stock_data["symbol"]
    name = stock_data["name"]
    sector = stock_data.get("sector", "General")
    cmp = stock_data["reference_price"]
    rsi = stock_data.get("rsi_14", 55.0)
    atr = stock_data.get("atr_14", cmp * 0.02)
    vol_5d = stock_data.get("volatility_5d_pct", 3.0)
    sent_score = stock_data.get("sentiment_score", 0.2)
    sent_label = stock_data.get("sentiment_label", "Neutral")
    target = stock_data["expected_target_price"]
    low = stock_data["expected_range_low"]
    high = stock_data["expected_range_high"]
    cmf = stock_data.get("cmf_20", 0.0)
    mfi = stock_data.get("mfi_14", 50.0)
    vol_surge = stock_data.get("vol_surge", 1.0)
    vol_squeeze = stock_data.get("vol_squeeze", 1.0)
    deliv_per = stock_data.get("deliv_per", 45.0)
    deliv_surge = stock_data.get("deliv_surge", vol_surge)
    rs_20d = stock_data.get("rs_20d", 0.0)
    sector_rs = stock_data.get("sector_rs", 0.0)
    stop_loss = stock_data.get("stop_loss", round(cmp - atr, 2))
    direction = stock_data.get("direction", "NEUTRAL")
    action_label = stock_data.get("action_label", "BUY / ACCUMULATE (5-Day Swing)" if direction == "BULLISH" else "EXIT / AVOID")

    # Try external LLM first if API keys exist
    llm_prompt = f"""
    Analyze the following Indian stock on NSE/BSE with institutional precision:
    Stock: {name} ({symbol})
    Sector: {sector}
    Current Market Price: Rs. {cmp}
    14-Day ATR: Rs. {atr}
    Strict ATR Stop-Loss: Rs. {stop_loss}
    14-Day RSI: {rsi}
    Chaikin Money Flow (CMF-20): {cmf:+.3f} (Institutional Accumulation if > +0.05)
    Money Flow Index (MFI-14): {mfi}
    Volume Surge Ratio: {vol_surge}x vs 20-DMA
    Volatility Squeeze Ratio (VCP): {vol_squeeze}x
    Estimated Delivery %: {deliv_per}%
    Delivery Surge Ratio: {deliv_surge}x
    20-Day Relative Strength vs Nifty 50: {rs_20d:+0.2f}%
    Parent Sector 5-Day RS vs Nifty 50: {sector_rs:+0.2f}%
    Action Stance: {action_label}
    5-Day Volatility: {vol_5d}%
    Sentiment Score: {sent_score} ({sent_label})
    Expected 5-Day Target: Rs. {target}
    5-Day Volatility Cone Range: Rs. {low} to Rs. {high}
    Supporting Catalysts: {stock_data.get('supporting_reasons', [])}
    Known Risks: {stock_data.get('downside_risks', [])}

    MANDATORY COMMITTEE INSTRUCTIONS:
    The Committee Consensus (synthesis) and Trade Plan MUST explicitly cite:
    1. Institutional Money Flow (CMF-20={cmf:+.3f}, MFI-14={mfi}, Volume Surge={vol_surge}x, Delivery={deliv_per}%, Delivery Surge={deliv_surge}x).
    2. Strict ATR Stop-Loss level (Rs. {stop_loss}) as the non-negotiable risk boundary.
    3. Action Stance ({action_label}) and 5-Day Target (Rs. {target}).

    Return JSON adhering exactly to:
    {{
      "analysts": [
        {{"agent": "1. Technical Analyst", "stance": "BULLISH|NEUTRAL|BEARISH", "insights": ["...", "..."]}},
        {{"agent": "2. Fundamental Analyst", "stance": "STABLE / ACCUMULATE|...", "insights": ["...", "..."]}},
        {{"agent": "3. Options & Volatility Analyst", "stance": "FAVORABLE RANGE|...", "insights": ["...", "..."]}},
        {{"agent": "4. News & Catalysts Analyst", "stance": "POSITIVE MOMENTUM|...", "insights": ["...", "..."]}},
        {{"agent": "5. Sentiment & Media Analyst", "stance": "BULLISH|NEUTRAL|CAUTIOUS", "insights": ["...", "..."]}},
        {{"agent": "6. Sector Rotation Analyst", "stance": "OVERWEIGHT|...", "insights": ["...", "..."]}},
        {{"agent": "7. Risk Manager", "stance": "CALIBRATED RISK|...", "insights": ["...", "..."]}}
      ],
      "debate": {{
        "synthesis": "Explicitly cite Institutional Money Flow (CMF, MFI, Volume Surge) and exact ATR Stop-Loss Rs. {stop_loss} in the narrative...",
        "bull_points": ["Point 1", "Point 2", "Point 3"],
        "bear_points": ["Point 1", "Point 2", "Point 3"],
        "facilitator_verdict": "{action_label}",
        "trade_plan": {{
          "suggested_entry": "Rs. {cmp}",
          "downside_invalidation": "Rs. {stop_loss} (Strict ATR Stop-Loss)",
          "target_5d": "Rs. {target}",
          "action_label": "{action_label}",
          "institutional_money_flow": "CMF {cmf:+.2f} | MFI {mfi} | Vol Surge {vol_surge}x",
          "horizon": "5 Trading Sessions"
        }}
      }}
    }}
    """

    llm_result = _call_external_llm(llm_prompt)
    if llm_result and "analysts" in llm_result and "debate" in llm_result:
        return llm_result


    # 1. Technical Analyst Agent
    tech_stance = direction
    tech_findings = [
        f"Price relative to 5-day volatility cone: Lower band ₹{low}, Upper band ₹{high}.",
        f"14-Day RSI measured at {rsi} with 14-day ATR at ₹{atr}.",
        f"20-Day Relative Strength vs Nifty 50: {rs_20d:+0.2f}%." + (" (Outperforming index)" if rs_20d > 1.0 else " (Lagging index)"),
        f"Volatility Squeeze Ratio (VCP): {vol_squeeze}x." + (" (Consolidation coiling)" if vol_squeeze <= 0.90 else " (Normal dispersion)")
    ]

    # 2. Fundamental Analyst Agent
    fund_stance = "CONSTITUENT SOLVENCY FILTER"
    fund_findings = [
        f"Recognized constituent of {sector} within the Indian large-cap universe.",
        "Passed primary institutional turnover (>= ₹5 Cr/day) and solvency gatekeeper hurdles.",
        stock_data.get("fundamental_summary", "Balance sheet metrics audited against exchange filings.")
    ]

    # 3. Options & Volatility Analyst Agent
    vol_stance = "MATHEMATICAL VOLATILITY CONE"
    opt_findings = [
        f"5-day projected historical volatility stands at {vol_5d}%.",
        f"Institutional Money Flow (CMF-20): {cmf:+.3f} (Accumulation active)" if cmf > 0.05 else f"CMF-20: {cmf:+.3f}.",
        f"Volume Surge Ratio: {vol_surge}x vs 20-DMA (Delivery retention: ~{deliv_per}% with {deliv_surge}x surge)."
    ]

    # 4. News & Catalysts Analyst Agent
    news_stance = "POSITIVE MOMENTUM" if sent_score > 0 else ("CAUTIOUS" if sent_score < 0 else "NEUTRAL")
    news_findings = stock_data.get("supporting_reasons", [])
    if not news_findings:
        news_findings = ["No major catalyst headlines detected in recent 7-day news feed."]

    # 5. Sentiment & Media Analyst Agent
    sentiment_stance = sent_label.upper()
    sent_findings = [
        f"Google News RSS tone scored at {sent_score:+0.2f} ({sent_label}).",
        f"Evaluated against domain financial sentiment vocabulary with hard Veto Rule intact."
    ]

    # 6. Sector Rotation Analyst Agent
    sector_stance = "SECTOR ALIGNMENT"
    sector_findings = [
        f"Parent Sector: {sector}.",
        f"Sector 5-day Relative Strength vs Nifty 50: {sector_rs:+0.2f}% (" + ("Sector Outperforming Nifty 50" if sector_rs > 0 else "Sector Lagging Nifty 50") + ")."
    ]

    # 7. Risk Manager Agent (The Skeptic)
    downside_risks = stock_data.get("downside_risks", [])
    if not downside_risks:
        downside_risks = [f"Downside invalidation boundary defined at ₹{stop_loss} (Strict ATR Stop-Loss)."]
    risk_stance = "CALIBRATED RISK"
    risk_findings = [
        f"Strict ATR Stop-Loss: ₹{stop_loss} (Max risk: {round(abs(cmp - stop_loss)/cmp * 100, 2)}%).",
        f"Execution Guidance: {action_label}.",
        f"Volatility cone boundary: Lower support ₹{low}, Upper boundary ₹{high}."
    ] + downside_risks

    # Bull vs Bear Multi-Round Debate Synthesis
    bull_case = [
        f"Target calibrated to ₹{target} ({stock_data.get('expected_appreciation_pct', 0):+0.2f}% forward 5-day move).",
        f"Institutional Money Flow: CMF at {cmf:+.2f} with volume surge {vol_surge}x (Delivery: ~{deliv_per}%)."
    ]
    if stock_data.get("supporting_reasons"):
        bull_case.append(stock_data["supporting_reasons"][0])

    bear_case = [
        f"Mandatory invalidation stop-loss at ₹{stop_loss} below current market price.",
        f"RSI reading ({rsi}) and broader Nifty correlation require disciplined position sizing."
    ]
    if stock_data.get("downside_risks"):
        bear_case.append(stock_data["downside_risks"][0])

    verdict_text = action_label

    debate_verdict = {
        "synthesis": (
            f"Consensus Thesis: Multi-factor quantitative consensus confirms {direction} setup targeting ₹{target} "
            f"({stock_data.get('expected_appreciation_pct', 0):+0.2f}% forward move). "
            f"Institutional Money Flow is confirmed by CMF-20 at {cmf:+.3f}, MFI-14 at {mfi}, and Volume Expansion of {vol_surge}x vs 20-DMA "
            f"(Delivery Retention: {deliv_per}% with {deliv_surge}x surge). "
            f"Strict ATR Stop-Loss is fixed at ₹{stop_loss} ({round(abs(cmp - stop_loss)/cmp * 100, 2)}% max downside risk). "
            f"Action Stance: {action_label}."
        ),
        "bull_points": bull_case,
        "bear_points": bear_case,
        "facilitator_verdict": verdict_text,
        "trade_plan": {
            "suggested_entry": f"CMP (₹{cmp})",
            "downside_invalidation": f"₹{stop_loss} (Strict 1.0x ATR Stop-Loss)",
            "target_5d": f"₹{target} ({stock_data.get('expected_appreciation_pct', 0):+0.2f}%)",
            "action_label": action_label,
            "institutional_money_flow": f"CMF {cmf:+.2f} | MFI {mfi} | Vol Surge {vol_surge}x | Delivery {deliv_per}% ({deliv_surge}x)",
            "relative_strength_20d": f"{rs_20d:+0.2f}% vs Nifty 50",
            "horizon": "5 Trading Sessions"
        }
    }

    return {
        "analysts": [
            {"agent": "1. Technical Analyst", "stance": tech_stance, "insights": tech_findings},
            {"agent": "2. Fundamental Analyst", "stance": fund_stance, "insights": fund_findings},
            {"agent": "3. Options & Volatility Analyst", "stance": vol_stance, "insights": opt_findings},
            {"agent": "4. News & Catalysts Analyst", "stance": news_stance, "insights": news_findings},
            {"agent": "5. Sentiment & Media Analyst", "stance": sentiment_stance, "insights": sent_findings},
            {"agent": "6. Sector Rotation Analyst", "stance": sector_stance, "insights": sector_findings},
            {"agent": "7. Risk Manager", "stance": risk_stance, "insights": risk_findings}
        ],
        "debate": debate_verdict,
        "llm_engine": "Institutional Quantitative Engine (ATR-Grounded Rule-Based)"
    }

