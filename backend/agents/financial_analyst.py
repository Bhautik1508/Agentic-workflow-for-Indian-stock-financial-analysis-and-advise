import json
from agents.base_agent import get_llm, parse_llm_json, agent_with_fallback, call_llm_with_retry
from graph.state import StockAnalysisState, AgentReport, AgentStatus

FINANCIAL_SYSTEM_PROMPT = """You are a Senior Equity Research Analyst at a top-tier Indian brokerage with 15+ years
of experience covering NSE and BSE listed companies. You specialize in fundamental analysis
of Indian equities across all sectors — IT, FMCG, Banking, Pharma, Auto, Infrastructure,
and Conglomerates.

Your analysis must:
- Compare valuation multiples against the company's own 5-year history AND sector peers
- Account for India-specific nuances: promoter-driven businesses, RBI regulations for banks,
  SEBI disclosure norms, GST impact on margins, PLI scheme benefits
- Be grounded only in the data provided — never hallucinate numbers
- Give a score from 0–10 where:
    0–3 = Fundamentally weak / Avoid
    4–5 = Below average / Underperform
    5–6 = Average / Neutral
    7–8 = Strong fundamentals / Outperform
    9–10 = Exceptional / Strong Buy on fundamentals alone

Output ONLY valid JSON. No preamble, no explanation outside the JSON."""

FINANCIAL_USER_PROMPT = """
Analyze the fundamentals of {company_name} ({ticker}) — a {sector} company.

━━━ VALUATION METRICS ━━━
P/E Ratio (TTM):        {pe_ratio}
Forward P/E:            {forward_pe}
P/B Ratio:              {pb_ratio}
P/S Ratio:              {ps_ratio}
EV/EBITDA:              {ev_ebitda}
PEG Ratio:              {peg_ratio}
Analyst Target Price:   ₹{analyst_target_price} ({analyst_count} analysts: {analyst_recommendation})

━━━ PROFITABILITY ━━━
ROE:                    {roe}
ROA:                    {roa}
Gross Margin:           {gross_margin}
Operating Margin:       {operating_margin}
Net Profit Margin:      {net_margin}
EBITDA Margin:          {ebitda_margin}

━━━ GROWTH ━━━
Revenue Growth (YoY):   {revenue_growth_yoy}
Earnings Growth (YoY):  {earnings_growth_yoy}
Earnings Growth (QoQ):  {earnings_quarterly_growth}

━━━ FINANCIAL HEALTH ━━━
Debt-to-Equity:         {debt_to_equity}
Current Ratio:          {current_ratio}
Quick Ratio:            {quick_ratio}
Interest Coverage:      {interest_coverage}x
Total Debt:             ₹{total_debt_cr} Crore
Total Cash:             ₹{total_cash_cr} Crore

━━━ CASH FLOW ━━━
Free Cash Flow:         ₹{free_cashflow_cr} Crore
Operating Cash Flow:    ₹{operating_cashflow_cr} Crore
CapEx:                  ₹{capex_cr} Crore

━━━ SHAREHOLDER RETURNS ━━━
Dividend Yield:         {dividend_yield}
Payout Ratio:           {payout_ratio}

━━━ SECTOR PEER COMPARISON ━━━
Ticker | P/E | P/B | ROE | Rev Growth | Market Cap (Cr)
--- | --- | --- | --- | --- | ---
{peer_table}

Sector Median P/E: {sector_median_pe}
→ {company_name} trades at {pe_premium_discount}% {premium_or_discount} to sector median

━━━ SCREENER.IN 10-YEAR TREND ━━━
Revenue CAGR (5Y):      {revenue_cagr_5y}
Profit CAGR (5Y):       {profit_cagr_5y}
ROCE Trend (Latest):    {roce_latest}
ROE Trend (Latest):     {roe_latest}

Full Screener Data:
{screener_data_summary}

━━━ BUSINESS DESCRIPTION ━━━
{business_summary}

Provide your analysis as JSON with this exact schema:
{{
    "summary": "<2-3 sentence overall fundamental assessment>",
    "score": <float 0.0–10.0>,
    "confidence": <float 0.0–1.0>,
    "key_findings": [
        "<finding 1: valuation assessment with specific numbers>",
        "<finding 2: profitability vs sector>",
        "<finding 3: growth trajectory>",
        "<finding 4: balance sheet health>",
        "<finding 5: cash flow quality>"
    ],
    "risk_flags": [
        "<any red flag 1>",
        "<any red flag 2>"
    ],
    "valuation_verdict": "undervalued" | "fairly_valued" | "overvalued",
    "financial_health": "excellent" | "good" | "average" | "poor",
    "growth_quality": "high_quality" | "moderate" | "low_quality" | "declining",
    "pe_vs_history": "<comment on current P/E vs 5-year average>",
    "moat_assessment": "<brief comment on competitive moat>",
    "target_price_fundamental": <float INR, your DCF/PE-based fair value estimate>
}}
"""

def format_metric(val, is_pct=False):
    if val is None or val == "N/A":
        return "N/A"
    try:
        f = float(val)
        if is_pct:
            return f"{f*100:.2f}%" if abs(f) < 5 else f"{f:.2f}%"
        return f"{f:.2f}"
    except:
        return str(val)

@agent_with_fallback("Financial Analyst", default_score=5.0)
async def run_financial_analysis(state: StockAnalysisState) -> AgentReport:
    """Run financial fundamentals analysis with advanced parsing."""
    client = get_llm()
    fundamental = state.get("fundamental_data", {})
    price = state.get("price_data", {})
    screener = state.get("screener_data", {})
    
    # Helper string formats
    screener_text = json.dumps(screener, indent=2) if screener else "No Screener data."
    
    # Compute CAGR from Screener year-keyed data
    def compute_cagr(data_row: dict, n_years: int = 5) -> str:
        """Compute CAGR from a year-keyed dict like {'Mar 2020': '100', 'Mar 2025': '200'}"""
        if not data_row or not isinstance(data_row, dict):
            return "N/A"
        try:
            keys = sorted(data_row.keys())
            if len(keys) < 2:
                return "N/A"
            # Get the latest and the one n_years ago
            latest_key = keys[-1]
            start_idx = max(0, len(keys) - n_years - 1)
            start_key = keys[start_idx]
            latest_val = float(data_row[latest_key].replace(',', ''))
            start_val = float(data_row[start_key].replace(',', ''))
            if start_val <= 0 or latest_val <= 0:
                return "N/A"
            actual_years = len(keys) - 1 - start_idx
            if actual_years <= 0:
                return "N/A"
            cagr = ((latest_val / start_val) ** (1 / actual_years) - 1) * 100
            return f"{cagr:.1f}%"
        except:
            return "N/A"
    
    def get_latest_ratio(screener_data: dict, key_prefix: str) -> str:
        """Get the latest value from a year-keyed screener ratio dict."""
        for k, v in screener_data.items():
            if k.startswith(key_prefix) and isinstance(v, dict):
                keys = sorted(v.keys())
                if keys:
                    return v[keys[-1]]
        return "N/A"
    
    # Find Sales/Revenue row and Net Profit row
    revenue_row = screener.get("pl_Sales", screener.get("pl_Revenue", {}))
    profit_row = screener.get("pl_Net Profit", screener.get("pl_Profit after tax", {}))
    revenue_cagr_5y = compute_cagr(revenue_row, 5)
    profit_cagr_5y = compute_cagr(profit_row, 5)
    roce_latest = get_latest_ratio(screener, "ratio_ROCE")
    roe_latest = get_latest_ratio(screener, "ratio_ROE")
    
    # Peer Table & Sector Math
    peers = fundamental.get("sector_peers", [])
    peer_table = "No sector peer data available."
    sector_median_pe = "N/A"
    pe_premium_discount = "N/A"
    premium_or_discount = ""
    
    if peers:
        table_rows = []
        pe_list = []
        for p in peers:
            p_pe = format_metric(p.get('pe'))
            p_pb = format_metric(p.get('pb'))
            p_roe = format_metric(p.get('roe'), True)
            p_rev = format_metric(p.get('revenue_growth'), True)
            p_cap = format_metric(p.get('market_cap_cr'))
            table_rows.append(f"{p['ticker']} | {p_pe} | {p_pb} | {p_roe} | {p_rev} | {p_cap}")
            if p.get('pe') is not None:
                pe_list.append(float(p.get('pe')))
                
        if table_rows:
            peer_table = "\n".join(table_rows)
            
        if pe_list:
            import statistics
            median_pe = statistics.median(pe_list)
            sector_median_pe = f"{median_pe:.2f}"
            
            target_pe = fundamental.get("pe_ratio")
            if target_pe is not None:
                diff = ((float(target_pe) - median_pe) / median_pe) * 100
                pe_premium_discount = f"{abs(diff):.1f}"
                premium_or_discount = "premium" if diff > 0 else "discount"
    
    prompt = FINANCIAL_USER_PROMPT.format(
        company_name=state["company_name"],
        ticker=state["ticker"],
        sector=fundamental.get("sector", "Unknown"),
        current_price=format_metric(price.get("current_price")),
        market_cap_cr=format_metric((price.get("market_cap") or 0) / 10000000),
        week_52_low=format_metric(price.get("week_52_low")),
        week_52_high=format_metric(price.get("week_52_high")),
        pe_ratio=format_metric(fundamental.get("pe_ratio")),
        forward_pe=format_metric(fundamental.get("forward_pe")),
        pb_ratio=format_metric(fundamental.get("pb_ratio")),
        ps_ratio=format_metric(fundamental.get("ps_ratio")),
        ev_ebitda=format_metric(fundamental.get("ev_ebitda")),
        peg_ratio=format_metric(fundamental.get("peg_ratio")),
        analyst_target_price=format_metric(fundamental.get("analyst_target_price")),
        analyst_count=fundamental.get("analyst_count", 0),
        analyst_recommendation=fundamental.get("analyst_recommendation", "N/A"),
        roe=format_metric(fundamental.get("roe"), True),
        roa=format_metric(fundamental.get("roa"), True),
        gross_margin=format_metric(fundamental.get("gross_margin"), True),
        operating_margin=format_metric(fundamental.get("operating_margins"), True),
        net_margin=format_metric(fundamental.get("profit_margins"), True),
        ebitda_margin=format_metric(fundamental.get("ebitda_margin"), True),
        revenue_growth_yoy=format_metric(fundamental.get("revenue_growth"), True),
        earnings_growth_yoy=format_metric(fundamental.get("earnings_growth"), True),
        earnings_quarterly_growth=format_metric(fundamental.get("earnings_quarterly_growth"), True),
        debt_to_equity=format_metric(fundamental.get("debt_to_equity")),
        current_ratio=format_metric(fundamental.get("current_ratio")),
        quick_ratio=format_metric(fundamental.get("quick_ratio")),
        interest_coverage=format_metric(fundamental.get("interest_coverage")),
        total_debt_cr=format_metric((fundamental.get("total_debt") or 0) / 10000000),
        total_cash_cr=format_metric((fundamental.get("total_cash") or 0) / 10000000),
        free_cashflow_cr=format_metric((fundamental.get("free_cashflow") or 0) / 10000000),
        operating_cashflow_cr=format_metric((fundamental.get("operating_cashflow") or 0) / 10000000),
        capex_cr=format_metric((fundamental.get("capex") or 0) / 10000000),
        dividend_yield=format_metric(fundamental.get("dividend_yield"), True),
        payout_ratio=format_metric(fundamental.get("payout_ratio"), True),
        peer_table=peer_table,
        sector_median_pe=sector_median_pe,
        pe_premium_discount=pe_premium_discount,
        premium_or_discount=premium_or_discount,
        revenue_cagr_5y=revenue_cagr_5y,
        profit_cagr_5y=profit_cagr_5y,
        roce_latest=roce_latest,
        roe_latest=roe_latest,
        screener_data_summary=screener_text,
        business_summary=fundamental.get("business_summary", "No description available.")
    )
    
    text = await call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": FINANCIAL_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    
    data = parse_llm_json(text)
    
    return AgentReport(
        agent_name="Financial Analyst",
        status=AgentStatus.COMPLETE,
        summary=data.get("summary", ""),
        score=data.get("score", 5.0),
        key_findings=data.get("key_findings", []),
        risk_flags=data.get("risk_flags", []),
        confidence=data.get("confidence", 0.0),
        data=data
    )
