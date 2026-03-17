from agents.base_agent import get_llm, parse_llm_json, agent_with_fallback, call_llm_with_retry
from graph.state import StockAnalysisState, AgentReport, AgentStatus

MACRO_GOV_SYSTEM_PROMPT = """You are a dual-specialist analyst combining:

1. MACROECONOMIC ANALYSIS: Senior Economist at a leading Indian asset management firm.
   You track RBI monetary policy, GDP trends, inflation dynamics, sector rotation signals,
   and global macro factors affecting Indian equities (USD/INR, oil prices, FII flows).

2. CORPORATE GOVERNANCE ANALYSIS: SEBI-certified governance expert.
   You evaluate promoter integrity, transparency, capital allocation discipline, board
   quality, insider trading patterns, and corporate announcements.

For Indian equities, you know:
- Promoter holding below 35% OR declining >2% in a quarter is a red flag
- Pledge >30% of promoter holding is a serious governance concern
- Consistent insider buying by promoters/management is bullish
- RBI rate cuts benefit rate-sensitive sectors (banking, NBFC, real estate, auto)
- Rising USD/INR hurts importers (oil, tech hardware) but helps IT exporters

Combined macro+governance scoring (0–10):
    0–2  = Very concerning — poor governance AND/OR severely adverse macro
    3–4  = Below average — one significant concern in either dimension
    5–6  = Neutral/Average — standard macro environment, average governance
    7–8  = Supportive — good governance, tailwinds from macro
    9–10 = Excellent — top-tier governance, strong macro tailwinds

Output ONLY valid JSON. No preamble, no explanation outside the JSON."""

MACRO_GOV_USER_PROMPT = """
Analyze macroeconomic context AND corporate governance quality for {company_name} ({ticker}).
Sector: {sector} | Industry: {industry}

━━━ MACROECONOMIC DATA ━━━

India GDP Growth:
{gdp_growth_history}

CPI Inflation:
{cpi_inflation_history}

RBI Repo Rate:    {repo_rate}%  (Last change: {last_rate_change}, Stance: {rbi_stance})

━━━ BROADER MARKET MACRO ━━━
Market Regime:       {market_regime}
India VIX:           {vix_current} ({fear_level})
USD/INR:             {usdinr_current} ({usdinr_1m_change}% 1M)
  → Strong INR (appreciation): positive for importers (oil, pharma API)
  → Weak INR (depreciation): positive for IT exporters, negative for oil/auto

Crude Oil WTI:       ${crude_current} ({crude_1m_change}% 1M)
  → Sector impact: {crude_sector_impact}
  → High crude: bad for auto, aviation, chemicals; good for ONGC, oil PSUs
  → Low crude: good for paint, tyre, airline companies

Gold:                ${gold_current} ({gold_1m_change}% 1M)

━━━ CORPORATE GOVERNANCE (Source: {shareholding_source}) ━━━
Promoter Holding:    {promoter_holding_pct}%
  Trend (last 8Q):   {promoter_trend}
  → increasing: promoters buying back = very bullish signal
  → decreasing: promoters reducing stake = red flag

Promoter Pledge:     {promoter_pledge_pct}%  → Risk: {pledge_risk}
  → very_low (<5%): negligible risk
  → low (5–20%): acceptable, monitor
  → moderate (20–35%): elevated — margin call risk in market downturn
  → high (35–50%): serious concern
  → very_high (>50%): GOVERNANCE VETO RISK

DII Holding:         {dii_holding_pct}%
FII Holding:         {fii_holding_pct}%
Public/Retail:       {public_holding_pct}%

Recent Insider Transactions (Last 6 Months):
{insider_transactions_table}

Recent Corporate Announcements (Last 30 Days):
{corporate_announcements_list}

BSE/NSE Surveillance Status: {surveillance_status}

━━━ INSTITUTIONAL OWNERSHIP ━━━
Institutional Ownership: {institutional_ownership_pct}%
Insider Ownership:        {insider_ownership_pct}%

Top 5 Institutional Holders:
{top_institutions_table}

Provide macro & governance analysis as JSON with this exact schema:
{{
    "summary": "<2-3 sentence combined macro + governance overview>",
    "score": <float 0.0–10.0>,
    "confidence": <float 0.0–1.0>,
    "signal_line": "<max 8 words: e.g. 'RBI neutral. Promoter holding stable 50.1%'>",
    "data_table": [
        {{"label": "RBI Stance", "value": "<e.g. Neutral>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Promoter Hold", "value": "<e.g. 50.1%>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Pledge Risk", "value": "<e.g. None>", "signal": "<positive|neutral|negative>"}},
        {{"label": "INR/USD", "value": "<e.g. ₹83.2>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Insider Signal", "value": "<e.g. Neutral>", "signal": "<positive|neutral|negative>"}}
    ],
    "key_findings": [
        "<finding 1: macro environment for this sector specifically>",
        "<finding 2: RBI/interest rate impact on this company>",
        "<finding 3: promoter holding trend interpretation>"
    ],
    "risk_flags": [
        "<governance red flag if any>",
        "<macro headwind if any>"
    ],
    "macro_environment": "very_supportive" | "supportive" | "neutral" | "headwind" | "severe_headwind",
    "governance_quality": "excellent" | "good" | "average" | "poor" | "concerning",
    "promoter_confidence": "high" | "moderate" | "low",
    "insider_signal": "strong_buy" | "buy" | "neutral" | "sell" | "strong_sell",
    "rate_cycle_impact": "positive" | "neutral" | "negative",
    "sector_macro_tailwind": true | false,
    "promoter_signal": "accumulating" | "stable" | "reducing" | "unknown",
    "governance_veto_risk": true | false,
    "macro_tailwind": true | false,
    "currency_impact": "positive" | "neutral" | "negative",
    "governance_score_detail": {{
        "promoter_holding": <float 0–10>,
        "pledge_risk": <float 0–10>,
        "insider_activity": <float 0–10>,
        "board_quality": <float 0–10>,
        "disclosure_quality": <float 0–10>
    }}
}}
"""

def format_metric(val):
    if val is None: return "N/A"
    try: return f"{float(val):.2f}"
    except: return str(val)

def _format_institutions_table(holders: list) -> str:
    """Format top institutional holders list into a readable table string."""
    if not holders:
        return "No institutional holder data available."
    lines = ["Holder                          | Shares        | % Out"]
    lines.append("-" * 60)
    for h in holders:
        name = str(h.get("Holder", "Unknown"))[:30].ljust(30)
        shares = f"{h.get('Shares', 0):,}" if isinstance(h.get("Shares"), int) else str(h.get("Shares", "N/A"))
        pct = f"{h.get('% Out', 'N/A')}%"
        lines.append(f"{name} | {shares:>13} | {pct}")
    return "\n".join(lines)

@agent_with_fallback("Macro & Governance Analyst", default_score=5.0)
async def run_macro_governance_analysis(state: StockAnalysisState) -> AgentReport:
    """Run combined macro and governance analysis."""
    client = get_llm()
    
    fundamental = state.get("fundamental_data", {})
    macro = state.get("macro_data", {})
    gov = state.get("governance_data", {})
    nse = state.get("nse_data", {})
    inst = state.get("institutional_data", {})
    market_breadth = state.get("market_breadth", {})
    sector = fundamental.get("sector", "Unknown").lower()
    
    # Format lists to text
    gdp_hist = "\n".join([f"{y}: {v}%" for y, v in macro.get("gdp_growth_pct", [])]) or "Unavailable"
    cpi_hist = "\n".join([f"{y}: {v}%" for y, v in macro.get("cpi_inflation_pct", [])]) or "Unavailable"
    
    usdinr = market_breadth.get("usdinr", {})
    crude = market_breadth.get("crude", {})
    gold = market_breadth.get("gold", {})
    
    # Crude sector impact logic
    crude_sector_impact = "neutral"
    if "auto" in sector or "aviation" in sector or "chemicals" in sector or "paint" in sector or "tyre" in sector:
        crude_sector_impact = "negative (input cost headwind)" if (crude.get("current", 0) > 80) else "positive (input cost tailwind)"
    elif "oil" in sector or "energy" in sector:
        crude_sector_impact = "positive (realization tailwind)" if (crude.get("current", 0) > 80) else "negative (realization headwind)"
    
    promoter_trend = gov.get("trend", "Unknown")
    
    pledge_pct = gov.get("promoter_pledge_pct", 0)
    p_interp = gov.get("pledge_risk", "unknown")
    if p_interp == "unknown":
        if pledge_pct > 50: p_interp = "very_high"
        elif pledge_pct > 35: p_interp = "high"
        elif pledge_pct > 20: p_interp = "moderate"
        elif pledge_pct > 5: p_interp = "low"
        else: p_interp = "very_low"
    
    insiders = gov.get("insider_transactions", [])
    insider_txt = "\n".join([str(i) for i in insiders]) if insiders else "No recent notable insider records found."
    
    announcements = gov.get("announcements", [])
    ann_txt = "\n".join([str(a) for a in announcements]) if announcements else "No major recent announcements."

    prompt = MACRO_GOV_USER_PROMPT.format(
        company_name=state["company_name"],
        ticker=state["ticker"],
        sector=fundamental.get("sector", "Unknown"),
        industry=fundamental.get("industry", "Unknown"),
        gdp_growth_history=gdp_hist,
        cpi_inflation_history=cpi_hist,
        repo_rate=macro.get("repo_rate", 6.50),
        last_rate_change=macro.get("last_change", "N/A"),
        rbi_stance=macro.get("stance", "N/A"),
        market_regime=market_breadth.get("market_regime", "neutral").upper(),
        vix_current=format_metric(market_breadth.get("india_vix", {}).get("current")),
        fear_level=market_breadth.get("fear_level", "normal").replace("_", " ").upper(),
        usdinr_current=format_metric(usdinr.get("current")),
        usdinr_1m_change=format_metric(usdinr.get("1m_change")),
        crude_current=format_metric(crude.get("current")),
        crude_1m_change=format_metric(crude.get("1m_change")),
        crude_sector_impact=crude_sector_impact.upper(),
        gold_current=format_metric(gold.get("current")),
        gold_1m_change=format_metric(gold.get("1m_change")),
        shareholding_source="Screener.in (Latest)",
        promoter_holding_pct=format_metric(gov.get("promoter_holding_pct", "N/A")),
        promoter_trend=promoter_trend.replace("_", " ").upper(),
        promoter_pledge_pct=format_metric(pledge_pct),
        pledge_risk=p_interp.replace("_", " ").upper(),
        dii_holding_pct=format_metric(gov.get("dii_holding_pct", "N/A")),
        fii_holding_pct=format_metric(gov.get("fii_holding_pct", "N/A")),
        public_holding_pct=format_metric(gov.get("public_holding_pct", "N/A")),
        insider_transactions_table=insider_txt,
        corporate_announcements_list=ann_txt,
        surveillance_status=nse.get("surveillance_flag", "None"),
        institutional_ownership_pct=inst.get("institutional_ownership_pct") if inst.get("institutional_ownership_pct") is not None else "N/A",
        insider_ownership_pct=inst.get("insider_ownership_pct") if inst.get("insider_ownership_pct") is not None else "N/A",
        top_institutions_table=_format_institutions_table(inst.get("top_5_institutions", [])),
    )
    
    text = await call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": MACRO_GOV_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    
    data = parse_llm_json(text)
    
    return AgentReport(
        agent_name="Macro & Governance Analyst",
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
