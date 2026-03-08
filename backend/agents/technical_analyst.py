from agents.base_agent import get_llm, parse_llm_json, agent_with_fallback, call_llm_with_retry
from graph.state import StockAnalysisState, AgentReport, AgentStatus

TECHNICAL_SYSTEM_PROMPT = """You are a Chartered Market Technician (CMT) and head of technical research at a leading
Indian stockbroking firm. You have 12+ years of experience analysing NSE/BSE charts using
price action, indicators, and volume analysis.

Your technical analysis framework:
- Primary trend identification via moving average alignment
- Momentum confirmation via RSI, MACD, Stochastic
- Volume confirmation of price moves (OBV, volume ratio)
- Volatility assessment via Bollinger Bands and ATR
- Support/resistance via Fibonacci, pivot levels, and price history
- Chart pattern recognition (head & shoulders, cup & handle, flags, wedges)

Technical scoring (0–10):
    0–2  = Strong bearish setup — multiple bearish signals aligned
    3–4  = Bearish — more bearish signals than bullish
    5    = Neutral — mixed signals, no clear bias
    6–7  = Bullish — multiple bullish signals, some caution
    8–10 = Strong bullish setup — all indicators aligned bullish, high-volume breakout

Output ONLY valid JSON. No preamble, no explanation outside the JSON."""

TECHNICAL_USER_PROMPT = """
Perform complete technical analysis for {company_name} ({ticker}).
Current Price: ₹{current_price}

━━━ TREND ANALYSIS ━━━
Moving Averages:
  SMA 20:  ₹{sma_20}  → Price is {above_below_sma20} this MA
  SMA 50:  ₹{sma_50}  → Price is {above_below_sma50} this MA
  SMA 200: ₹{sma_200} → Price is {above_below_sma200} this MA
  EMA 21:  ₹{ema_21}

MA Alignment: {ma_trend}
Golden Cross (50>200): {golden_cross}

ADX (Trend Strength): {adx}  → Trend is {trend_strength}
+DI: {adx_plus_di}   /   -DI: {adx_minus_di}
Trend Direction: {trend_direction}

━━━ MOMENTUM ━━━
RSI (14):      {rsi_14} → {rsi_interpretation}
RSI (9):       {rsi_9}

MACD:          {macd}
MACD Signal:   {macd_signal}
MACD Histogram:{macd_histogram}  → {macd_crossover}

Stochastic %K: {stoch_k}   %D: {stoch_d}
ROC (10):      {roc_10}%

━━━ VOLATILITY (BOLLINGER BANDS) ━━━
Upper Band:  ₹{bb_upper}
Middle Band: ₹{bb_middle}
Lower Band:  ₹{bb_lower}
%B:          {bb_pct_b} → Price is at {bb_pct_b_pct}% of the band range
Band Width:  {bb_width} → {bb_squeeze}
Price Position: {bb_position}
ATR (14):    ₹{atr_14} → Daily expected range ±₹{atr_14}

━━━ VOLUME ANALYSIS ━━━
Today's Volume:      {volume_today:,}
20-Day Avg Volume:   {volume_sma_20:,}
Volume Ratio:        {volume_ratio}x  → {volume_interpretation}
OBV Trend:           {obv_trend}  → {obv_interpretation}

━━━ SUPPORT & RESISTANCE ━━━
52-Week High:        ₹{high_52w}  ({pct_from_52w_high}% from current)
52-Week Low:         ₹{low_52w}
Pivot Point:         ₹{pivot}
Resistance 1 (R1):   ₹{resistance_1}
Support 1 (S1):      ₹{support_1}

Fibonacci Levels (52W range):
  0%   (Low):  ₹{fib_0}
  23.6%:       ₹{fib_236}
  38.2%:       ₹{fib_382}
  50.0%:       ₹{fib_500}
  61.8%:       ₹{fib_618}
  78.6%:       ₹{fib_786}
  100% (High): ₹{fib_100}

Provide technical analysis as JSON with this exact schema:
{{
    "summary": "<2-3 sentence overall technical assessment>",
    "score": <float 0.0–10.0>,
    "confidence": <float 0.0–1.0>,
    "key_findings": [
        "<finding 1: primary trend assessment with MA alignment>",
        "<finding 2: momentum reading with RSI/MACD>",
        "<finding 3: volume confirmation or divergence>",
        "<finding 4: Bollinger Band position and squeeze/expansion>",
        "<finding 5: key support/resistance levels to watch>"
    ],
    "risk_flags": [
        "<bearish signal or divergence to watch>",
        "<overhead resistance level that could cap upside>"
    ],
    "trend": "strong_uptrend" | "uptrend" | "sideways" | "downtrend" | "strong_downtrend",
    "momentum": "overbought" | "bullish" | "neutral" | "bearish" | "oversold",
    "volume_confirmation": true | false,
    "immediate_support":  <float INR — nearest key support>,
    "immediate_resistance": <float INR — nearest key resistance>,
    "technical_target": <float INR — bullish target if setup plays out>,
    "stop_loss_technical": <float INR — invalidation level>,
    "chart_pattern": "<detected pattern if any, e.g. 'cup and handle forming' or 'none'>",
    "entry_zone": "<suggested entry price range e.g. ₹X–₹Y on dip>"
}}
"""

def format_metric(val):
    if val is None: return "N/A"
    try: return f"{float(val):.2f}"
    except: return str(val)

@agent_with_fallback("Technical Analyst", default_score=5.0)
async def run_technical_analysis(state: StockAnalysisState) -> AgentReport:
    client = get_llm()
    
    ta_data = state.get("technical_data", {})
    price_data = state.get("price_data", {})
    
    c = ta_data.get("current_price", price_data.get("current_price", 0))
    
    # Interpretations
    rsi = ta_data.get("rsi_14", 50)
    rsi_interp = "neutral"
    if rsi >= 70: rsi_interp = "oversold" if rsi < 30 else "overbought"
    elif rsi <= 30: rsi_interp = "oversold"
    elif rsi > 50: rsi_interp = "bullish"
    elif rsi <= 50: rsi_interp = "bearish"

    vol_ratio = ta_data.get("volume_ratio", 1.0)
    vol_interp = "normal volume"
    if vol_ratio > 1.5: vol_interp = "high conviction volume"
    elif vol_ratio < 0.5: vol_interp = "low interest volume"

    bb_pctile = ta_data.get("bb_width_pctile", 50)
    bb_squeeze = "squeeze (bottom 20% of 52w range, expect breakout)" if bb_pctile < 20 else "normal/expansion"

    obv_trend = ta_data.get("obv_trend", "neutral")
    obv_interp = "buying pressure" if obv_trend == "rising" else "selling pressure"
    
    macd_hist = ta_data.get("macd_histogram") or 0
    macd_prev = ta_data.get("macd_histogram_prev") or 0
    macd_crossover = "neutral"
    if macd_hist > 0 and macd_prev <= 0: macd_crossover = "bullish crossover"
    elif macd_hist < 0 and macd_prev >= 0: macd_crossover = "bearish crossover"
    elif macd_hist > 0 and macd_hist > macd_prev: macd_crossover = "bullish momentum expanding"
    elif macd_hist > 0 and macd_hist < macd_prev: macd_crossover = "bullish momentum fading"
    elif macd_hist < 0 and macd_hist < macd_prev: macd_crossover = "bearish momentum expanding"
    elif macd_hist < 0 and macd_hist > macd_prev: macd_crossover = "bearish momentum fading"

    fib = ta_data.get("fibonacci_levels", {})

    prompt = TECHNICAL_USER_PROMPT.format(
        company_name=state["company_name"],
        ticker=state["ticker"],
        current_price=format_metric(c),
        sma_20=format_metric(ta_data.get("sma_20")),
        above_below_sma20="ABOVE" if ta_data.get("above_sma_20") else "BELOW",
        sma_50=format_metric(ta_data.get("sma_50")),
        above_below_sma50="ABOVE" if ta_data.get("above_sma_50") else "BELOW",
        sma_200=format_metric(ta_data.get("sma_200")),
        above_below_sma200="ABOVE" if ta_data.get("above_sma_200") else "BELOW",
        ema_21=format_metric(ta_data.get("ema_21")),
        ma_trend=ta_data.get("ma_trend", "mixed").replace("_", " ").title(),
        golden_cross="YES" if ta_data.get("golden_cross") else "NO",
        adx=format_metric(ta_data.get("adx")),
        trend_strength=ta_data.get("trend_strength", "weak").upper(),
        adx_plus_di=format_metric(ta_data.get("adx_plus_di")),
        adx_minus_di=format_metric(ta_data.get("adx_minus_di")),
        trend_direction=ta_data.get("trend_direction", "neutral").upper(),
        rsi_14=format_metric(rsi),
        rsi_interpretation=rsi_interp.upper(),
        rsi_9=format_metric(ta_data.get("rsi_9")),
        macd=format_metric(ta_data.get("macd")),
        macd_signal=format_metric(ta_data.get("macd_signal")),
        macd_histogram=format_metric(ta_data.get("macd_histogram")),
        macd_crossover=macd_crossover.upper(),
        stoch_k=format_metric(ta_data.get("stoch_k")),
        stoch_d=format_metric(ta_data.get("stoch_d")),
        roc_10=format_metric(ta_data.get("roc_10")),
        bb_upper=format_metric(ta_data.get("bb_upper")),
        bb_middle=format_metric(ta_data.get("bb_middle")),
        bb_lower=format_metric(ta_data.get("bb_lower")),
        bb_pct_b=format_metric(ta_data.get("bb_pct_b")),
        bb_pct_b_pct=format_metric((ta_data.get("bb_pct_b") or 0) * 100),
        bb_width=format_metric(ta_data.get("bb_width")),
        bb_squeeze=bb_squeeze.upper(),
        bb_position=ta_data.get("bb_position", "inside").replace("_", " ").upper(),
        atr_14=format_metric(ta_data.get("atr_14")),
        volume_today=ta_data.get("volume_today", 0),
        volume_sma_20=ta_data.get("volume_sma_20", 0),
        volume_ratio=format_metric(vol_ratio),
        volume_interpretation=vol_interp.upper(),
        obv_trend=obv_trend.upper(),
        obv_interpretation=obv_interp.upper(),
        high_52w=format_metric(ta_data.get("high_52w")),
        pct_from_52w_high=format_metric(ta_data.get("pct_from_52w_high")),
        low_52w=format_metric(ta_data.get("low_52w")),
        pivot=format_metric(ta_data.get("pivot")),
        resistance_1=format_metric(ta_data.get("resistance_1")),
        support_1=format_metric(ta_data.get("support_1")),
        fib_0=format_metric(fib.get("fib_0")),
        fib_236=format_metric(fib.get("fib_236")),
        fib_382=format_metric(fib.get("fib_382")),
        fib_500=format_metric(fib.get("fib_500")),
        fib_618=format_metric(fib.get("fib_618")),
        fib_786=format_metric(fib.get("fib_786")),
        fib_100=format_metric(fib.get("fib_100"))
    )
    
    text = await call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": TECHNICAL_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    
    data = parse_llm_json(text)
    
    return AgentReport(
        agent_name="Technical Analyst",
        status=AgentStatus.COMPLETE,
        summary=data.get("summary", ""),
        score=data.get("score", 5.0),
        key_findings=data.get("key_findings", []),
        risk_flags=data.get("risk_flags", []),
        confidence=data.get("confidence", 0.0),
        data=data
    )
