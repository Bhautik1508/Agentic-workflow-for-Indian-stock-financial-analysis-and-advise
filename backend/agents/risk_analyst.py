import numpy as np
from agents.base_agent import get_llm, parse_llm_json, agent_with_fallback, call_llm_with_retry
from graph.state import StockAnalysisState, AgentReport, AgentStatus

RISK_SYSTEM_PROMPT = """You are a Senior Risk Manager at a SEBI-registered Portfolio Management Service (PMS) firm
with expertise in Indian equity risk assessment. You combine quantitative risk metrics with
qualitative judgment to evaluate total investment risk.

Your risk framework covers:
1. Market risk (beta, volatility, correlation with Nifty)
2. Liquidity risk (volume, delivery percentage, bid-ask spread)
3. Financial risk (leverage, interest coverage, FCF sustainability)
4. Event risk (bulk deals, circuit hits, surveillance flags)
5. Sectoral risk (cyclicality, regulatory environment, commodity exposure)

Risk scoring (0–10 where 10 = LOWEST risk / safest):
    0–2  = Extremely high risk — avoid unless very high risk tolerance
    3–4  = High risk — suitable only for aggressive investors
    5–6  = Moderate risk — standard equity risk
    7–8  = Below-average risk — relatively defensive investment
    9–10 = Low risk — blue-chip safety profile

Output ONLY valid JSON. No preamble, no explanation outside the JSON."""

RISK_USER_PROMPT = """
Perform comprehensive risk assessment for {company_name} ({ticker}).

━━━ MARKET RISK METRICS ━━━
Beta:           {beta}
  → {beta_interpretation}
     (>1.2 = aggressive, 0.8–1.2 = market-like, <0.8 = defensive)

Annualised Volatility:
  30-Day:   {vol_30d}%
  90-Day:   {vol_90d}%
  1-Year:   {vol_1y}%

Maximum Drawdown (1 Year):   {max_drawdown_1y}%
Sharpe Ratio (1 Year):       {sharpe_ratio}
  → (>1.5 excellent, 1.0–1.5 good, 0.5–1.0 average, <0.5 poor)

Value at Risk (95%, 1-day):  {var_95_1day}%
  → On ₹1 Lakh invested, 95% confidence max 1-day loss: ₹{var_1lakh}

ATR (14-day):                ₹{atr_14}
  → Daily expected movement range

━━━ PRICE POSITION RISK ━━━
% from 52-Week High:         {pct_from_52w_high}%
% from 52-Week Low:          {pct_from_52w_low}%
  → Buying near 52w high = momentum risk; near 52w low = value opportunity

━━━ FINANCIAL / BALANCE SHEET RISK ━━━
Debt-to-Equity:              {debt_to_equity}
Current Ratio:               {current_ratio}
Interest Coverage:           {interest_coverage}x
Total Debt:                  ₹{total_debt_cr} Crore
Free Cash Flow:              ₹{free_cashflow_cr} Crore

━━━ NSE SIGNALS ━━━
Delivery % Today:            {delivery_pct_today}%
  → Interpretation:          {delivery_interpretation}
     (>60% = strong genuine buying, institutional accumulation)
     (40–60% = normal retail + institutional mix)
     (20–40% = speculative / day-trading dominated)
     (<20% = highly speculative, momentum driven, AVOID)
Total Traded Value:          ₹{total_traded_value_cr} Crore
Circuit Limit:               {circuit_limit}
  → Narrow circuit (5% or 10%) = HIGH liquidity risk, potential operator stock
  → Wide circuit (20%) = standard large-cap
  → No circuit = index stock (lowest liquidity risk)
Surveillance Flag:           {surveillance_flag}
  → ASM/GSM = SEBI has flagged this stock — mandatory risk flag

━━━ SECTOR CONTEXT ━━━
Sector:     {sector}
Industry:   {industry}
Market Cap: ₹{market_cap_cr} Crore

Provide risk assessment as JSON with this exact schema:
{{
    "summary": "<2-3 sentence overall risk assessment>",
    "score": <float 0.0–10.0>,
    "confidence": <float 0.0–1.0>,
    "signal_line": "<max 8 words: e.g. 'Beta 0.92. Max drawdown -18% YoY'>",
    "data_table": [
        {{"label": "Beta", "value": "<e.g. 0.92>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Volatility (1Y)", "value": "<e.g. 24.3%>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Max Drawdown", "value": "<e.g. -18%>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Debt/Equity", "value": "<e.g. 0.45>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Sharpe Ratio", "value": "<e.g. 1.2>", "signal": "<positive|neutral|negative>"}}
    ],
    "key_findings": [
        "<finding 1: market risk / beta assessment>",
        "<finding 2: volatility and drawdown analysis>",
        "<finding 3: financial leverage / debt risk>"
    ],
    "risk_flags": [
        "<specific red flag 1 with metric>",
        "<specific red flag 2 with metric>"
    ],
    "risk_level": "very_low" | "low" | "moderate" | "high" | "very_high",
    "beta_category": "defensive" | "market_like" | "aggressive",
    "financial_risk": "very_low" | "low" | "moderate" | "high",
    "liquidity_risk": "very_low" | "low" | "moderate" | "high",
    "max_loss_estimate": "<e.g. worst case 30% drawdown in 1 year based on history>",
    "suitable_for": ["aggressive_investor"] | ["moderate_investor"] | ["conservative_investor"] | ["trader"]
}}
"""

def format_metric(val):
    if val is None: return "N/A"
    try: return f"{float(val):.2f}"
    except: return str(val)

@agent_with_fallback("Risk Analyst", default_score=5.0)
async def run_risk_analysis(state: StockAnalysisState) -> AgentReport:
    """Run risk analysis with advanced ta parsing."""
    client = get_llm()
    fundamental = state.get("fundamental_data", {})
    price = state.get("price_data", {})
    risk = state.get("risk_data", {}) # Will be populated by market_data.py
    nse = state.get("nse_data", {})
    
    b = risk.get("beta")
    b_interp = "N/A"
    if b:
        if b > 1.2: b_interp = "aggressive (highly volatile)"
        elif b < 0.8: b_interp = "defensive (lower volatility)"
        else: b_interp = "market-like (tracks broader index)"

    # Compute delivery interpretation label in Python
    delivery_pct = nse.get("delivery_pct_today")
    delivery_interpretation = "N/A (data unavailable)"
    if delivery_pct is not None:
        try:
            dp = float(delivery_pct)
            if dp > 60:
                delivery_interpretation = "Strong genuine buying — institutional accumulation"
            elif dp >= 40:
                delivery_interpretation = "Normal retail + institutional mix"
            elif dp >= 20:
                delivery_interpretation = "Speculative / day-trading dominated"
            else:
                delivery_interpretation = "HIGHLY SPECULATIVE — momentum driven, AVOID"
        except:
            delivery_interpretation = "N/A (parse error)"

    # Compute total traded value in Crore
    ttv = nse.get("total_traded_value")
    total_traded_value_cr = "N/A"
    if ttv is not None:
        try:
            total_traded_value_cr = format_metric(float(ttv) / 1e7)
        except:
            pass

    prompt = RISK_USER_PROMPT.format(
        company_name=state["company_name"],
        ticker=state["ticker"],
        beta=format_metric(b),
        beta_interpretation=b_interp,
        vol_30d=format_metric(risk.get("volatility_30d")),
        vol_90d=format_metric(risk.get("volatility_90d")),
        vol_1y=format_metric(risk.get("volatility_1y")),
        max_drawdown_1y=format_metric(risk.get("max_drawdown_1y")),
        sharpe_ratio=format_metric(risk.get("sharpe_ratio")),
        var_95_1day=format_metric(risk.get("var_95_1day")),
        var_1lakh=format_metric(abs(risk.get("var_95_1day", 0)) * 1000) if risk.get("var_95_1day") else "N/A",
        atr_14=format_metric(risk.get("atr_14")),
        pct_from_52w_high=format_metric(risk.get("pct_from_52w_high")),
        pct_from_52w_low=format_metric(risk.get("pct_from_52w_low")),
        debt_to_equity=format_metric(fundamental.get("debt_to_equity")),
        current_ratio=format_metric(fundamental.get("current_ratio")),
        interest_coverage=format_metric(fundamental.get("interest_coverage")),
        total_debt_cr=format_metric((fundamental.get("total_debt") or 0) / 10000000),
        free_cashflow_cr=format_metric((fundamental.get("free_cashflow") or 0) / 10000000),
        sector=fundamental.get("sector", "Unknown"),
        industry=fundamental.get("industry", "Unknown"),
        market_cap_cr=format_metric((price.get("market_cap") or 0) / 10000000),
        delivery_pct_today=format_metric(delivery_pct),
        delivery_interpretation=delivery_interpretation,
        total_traded_value_cr=total_traded_value_cr,
        circuit_limit=nse.get("circuit_limit", "20%"),
        surveillance_flag=nse.get("surveillance_flag", "None")
    )
    
    text = await call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": RISK_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    
    data = parse_llm_json(text)
    
    return AgentReport(
        agent_name="Risk Analyst",
        status=AgentStatus.COMPLETE,
        summary=data.get("summary", ""),
        score=data.get("score", 5.0),
        key_findings=data.get("key_findings", [])[:3],
        risk_flags=data.get("risk_flags", [])[:3],
        signal_line=data.get("signal_line", ""),
        data_table=data.get("data_table", [])[:5],
        confidence=data.get("confidence", 0.0),
        data=data
    )
