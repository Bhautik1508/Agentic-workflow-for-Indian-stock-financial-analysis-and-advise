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
INR vs USD:       ₹{usdinr_current}  (1-month change: {usdinr_1m_change}%)

Market Indices (1-month performance):
  Nifty 50:       {nifty50_current}  ({nifty50_1m_change}%)
  Nifty Bank:     {nifty_bank_1m_change}%
  Sector Index:   {sector_index_1m_change}%

Commodity Prices:
  Crude Oil (WTI): ${crude_current}  ({crude_1m_change}% 1M)
  Gold:            ${gold_current}  ({gold_1m_change}% 1M)

━━━ CORPORATE GOVERNANCE DATA ━━━

Promoter Shareholding (Last 8 Quarters):
{promoter_holding_table}
Trend: {promoter_trend}

Promoter Pledge %:  {promoter_pledge_pct}%
  → {pledge_interpretation}
  (<5% = safe, 5–20% = watch, >20% = concern, >40% = high risk)

Recent Insider Transactions (Last 6 Months):
{insider_transactions_table}

Recent Corporate Announcements (Last 30 Days):
{corporate_announcements_list}

BSE/NSE Surveillance Status: {surveillance_status}

Provide macro & governance analysis as JSON with this exact schema:
{{
    "summary": "<2-3 sentence combined macro + governance overview>",
    "score": <float 0.0–10.0>,
    "confidence": <float 0.0–1.0>,
    "key_findings": [
        "<finding 1: macro environment for this sector specifically>",
        "<finding 2: RBI/interest rate impact on this company>",
        "<finding 3: promoter holding trend interpretation>",
        "<finding 4: insider trading signal — what management is doing>",
        "<finding 5: governance quality overall>"
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

@agent_with_fallback("Macro & Governance Analyst", default_score=5.0)
async def run_macro_governance_analysis(state: StockAnalysisState) -> AgentReport:
    """Run combined macro and governance analysis."""
    client = get_llm()
    
    fundamental = state.get("fundamental_data", {})
    macro = state.get("macro_data", {})
    gov = state.get("governance_data", {})
    nse = state.get("nse_data", {})
    
    # Format lists to text
    gdp_hist = "\n".join([f"{y}: {v}%" for y, v in macro.get("gdp_growth_pct", [])]) or "Unavailable"
    cpi_hist = "\n".join([f"{y}: {v}%" for y, v in macro.get("cpi_inflation_pct", [])]) or "Unavailable"
    
    usdinr = macro.get("usdinr", {})
    nifty = macro.get("nifty50", {})
    n_bank = macro.get("nifty_bank", {})
    sect = macro.get("sector_idx", {})
    crude = macro.get("crude_oil", {})
    gold = macro.get("gold", {})
    
    promoter_trend = gov.get("trend", "Unknown")
    promoter_table = " | ".join(gov.get("promoter_holding_quarterly", [])) or "No data."
    
    pledge_pct = gov.get("promoter_pledge_pct", 0)
    p_interp = "safe"
    if pledge_pct > 40: p_interp = "high risk"
    elif pledge_pct > 20: p_interp = "concern"
    elif pledge_pct > 5: p_interp = "watch"
    
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
        usdinr_current=format_metric(usdinr.get("current")),
        usdinr_1m_change=format_metric(usdinr.get("1m_change")),
        nifty50_current=format_metric(nifty.get("current")),
        nifty50_1m_change=format_metric(nifty.get("1m_change")),
        nifty_bank_1m_change=format_metric(n_bank.get("1m_change")),
        sector_index_1m_change=format_metric(sect.get("1m_change")),
        crude_current=format_metric(crude.get("current")),
        crude_1m_change=format_metric(crude.get("1m_change")),
        gold_current=format_metric(gold.get("current")),
        gold_1m_change=format_metric(gold.get("1m_change")),
        promoter_holding_table=promoter_table,
        promoter_trend=promoter_trend.upper(),
        promoter_pledge_pct=format_metric(pledge_pct),
        pledge_interpretation=p_interp.upper(),
        insider_transactions_table=insider_txt,
        corporate_announcements_list=ann_txt,
        surveillance_status=nse.get("surveillance_flag", "None")
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
        key_findings=data.get("key_findings", []),
        risk_flags=data.get("risk_flags", []),
        confidence=data.get("confidence", 0.0),
        data=data
    )
