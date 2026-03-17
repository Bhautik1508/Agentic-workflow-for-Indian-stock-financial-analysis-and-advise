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

━━━ SECTOR PEER COMPARISON ({peer_count} peers found) ━━━
Metric         {company_name}    Sector Median    Assessment
P/E Ratio      {pe_ratio}x       {sector_med_pe}x  {pe_vs_sector}
P/B Ratio      {pb_ratio}x       {sector_med_pb}x  {pb_vs_sector}
ROE            {roe_pct}%        {sector_med_roe}%  {roe_vs_sector}

Top Peers:
{peer_table_rows}
(Format each peer: "Ticker | P/E | P/B | ROE | Rev Growth")

━━━ SCREENER.IN 10-YEAR TREND ━━━
Revenue CAGR (5Y):      {revenue_cagr_5y}
Profit CAGR (5Y):       {profit_cagr_5y}
ROCE Trend (Latest):    {roce_latest}
ROE Trend (Latest):     {roe_latest}

Full Screener Data:
{screener_data_summary}

━━━ EARNINGS QUALITY ━━━
Next Earnings: {next_earnings_date} ({days_to_earnings} days away)
Earnings Risk: {earnings_proximity_risk}
  → VERY HIGH: earnings in ≤7 days — major uncertainty, size position conservatively
  → HIGH: earnings in 8–21 days — watch for guidance

Last 4Q Earnings Surprises: {surprises_str}
  (positive = beat, negative = miss)
Beat/Miss Trend: {beat_miss_trend}
Average Surprise: {avg_surprise}%

━━━ BUSINESS DESCRIPTION ━━━
{business_summary}

Provide your analysis as JSON with this exact schema:
{{
    "summary": "<2-3 sentence overall fundamental assessment>",
    "score": <float 0.0–10.0>,
    "confidence": <float 0.0–1.0>,
    "signal_line": "<max 8 words: most important finding as a data statement, e.g. 'Fairly valued. ROE 18.2% sector-leading'>",
    "data_table": [
        {{"label": "P/E Ratio", "value": "<e.g. 22.4x>", "signal": "<positive|neutral|negative>"}},
        {{"label": "vs Sector", "value": "<e.g. -12% discount>", "signal": "<positive|neutral|negative>"}},
        {{"label": "ROE", "value": "<e.g. 18.2%>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Revenue Growth", "value": "<e.g. +22% YoY>", "signal": "<positive|neutral|negative>"}},
        {{"label": "Debt/Equity", "value": "<e.g. 0.31>", "signal": "<positive|neutral|negative>"}}
    ],
    "key_findings": [
        "<finding 1: valuation assessment with specific numbers>",
        "<finding 2: profitability vs sector>",
        "<finding 3: growth trajectory>"
    ],
    "risk_flags": [
        "<any red flag 1>",
        "<any red flag 2>"
    ],
    "valuation_verdict": "undervalued" | "fairly_valued" | "overvalued",
    "pe_premium_discount_pct": <float, % above or below sector median P/E, positive for premium, negative for discount>,
    "financial_health": "excellent" | "good" | "average" | "poor",
    "growth_quality": "high_quality" | "moderate" | "low_quality" | "declining",
    "pe_vs_history": "<comment on current P/E vs 5-year average>",
    "moat_assessment": "<brief comment on competitive moat>",
    "earnings_risk": "very_high" | "high" | "moderate" | "low",
    "earnings_quality": "consistently_beating" | "mostly_beating" | "mixed" | "consistently_missing" | "unknown",
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
    earnings = state.get("earnings_data", {})
    
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
            latest_val = float(str(data_row[latest_key]).replace(',', ''))
            start_val = float(str(data_row[start_key]).replace(',', ''))
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
    
    # Peer Table & Sector Math (using new peer_data)
    peer_data = state.get("peer_data") or fundamental.get("sector_peers", {}) # Fallback to old for safety
    if isinstance(peer_data, list):
        # Handle graceful fallback if new logic isn't fully returning dict
        peers = peer_data
        peer_count = len(peers)
        sector_med_pe = "N/A"
        sector_med_pb = "N/A"
        sector_med_roe = "N/A"
    else:
        peers = peer_data.get("peers", [])
        peer_count = peer_data.get("peer_count", len(peers))
        sector_med_pe = peer_data.get("sector_median_pe", "N/A")
        sector_med_pb = peer_data.get("sector_median_pb", "N/A")
        sector_med_roe = peer_data.get("sector_median_roe", "N/A")
        if sector_med_roe != "N/A":
            sector_med_roe = f"{float(sector_med_roe) * 100:.2f}"
            
    peer_table_rows = "No sector peer data available."
    
    # Premium/Discount calculations
    pe_vs_sector = "N/A"
    pb_vs_sector = "N/A"
    roe_vs_sector = "N/A"
    
    target_pe = fundamental.get("pe_ratio")
    target_pb = fundamental.get("pb_ratio")
    target_roe_raw = fundamental.get("roe")
    try:
        target_roe = float(target_roe_raw) if target_roe_raw is not None else None
    except (ValueError, TypeError):
        target_roe = None
    
    if target_pe is not None and sector_med_pe != "N/A":
        try:
            diff_pe = ((float(target_pe) - float(sector_med_pe)) / float(sector_med_pe)) * 100
            if diff_pe > 0: pe_vs_sector = f"trading at {abs(diff_pe):.1f}% PREMIUM to sector"
            else: pe_vs_sector = f"trading at {abs(diff_pe):.1f}% DISCOUNT to sector"
        except: pass

    if target_pb is not None and sector_med_pb != "N/A":
        try:
            diff_pb = ((float(target_pb) - float(sector_med_pb)) / float(sector_med_pb)) * 100
            if diff_pb > 0: pb_vs_sector = f"trading at {abs(diff_pb):.1f}% PREMIUM to sector"
            else: pb_vs_sector = f"trading at {abs(diff_pb):.1f}% DISCOUNT to sector"
        except: pass
        
    if target_roe is not None and sector_med_roe != "N/A":
        try:
            diff_roe = ((float(target_roe) * 100) - float(sector_med_roe))
            if diff_roe > 0: roe_vs_sector = f"{abs(diff_roe):.1f}% HIGHER than sector"
            else: roe_vs_sector = f"{abs(diff_roe):.1f}% LOWER than sector"
        except: pass
    
    if peers:
        table_rows = []
        for p in peers:
            p_pe = format_metric(p.get('pe'))
            p_pb = format_metric(p.get('pb'))
            p_roe = format_metric(p.get('roe'), True)
            p_rev = format_metric(p.get('revenue_growth'), True)
            table_rows.append(f"{p.get('ticker', 'Unknown')} | {p_pe} | {p_pb} | {p_roe} | {p_rev}")
                
        if table_rows:
            peer_table_rows = "\n".join(table_rows)
    
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
        peer_count=peer_count,
        sector_med_pe=sector_med_pe,
        sector_med_pb=sector_med_pb,
        sector_med_roe=sector_med_roe,
        pe_vs_sector=pe_vs_sector,
        pb_vs_sector=pb_vs_sector,
        roe_pct=format_metric((target_roe * 100) if target_roe is not None else None),
        roe_vs_sector=roe_vs_sector,
        peer_table_rows=peer_table_rows,
        revenue_cagr_5y=revenue_cagr_5y,
        profit_cagr_5y=profit_cagr_5y,
        roce_latest=roce_latest,
        roe_latest=roe_latest,
        screener_data_summary=screener_text,
        business_summary=fundamental.get("business_summary", "No description available."),
        next_earnings_date=earnings.get("next_earnings_date", "Unknown"),
        days_to_earnings=earnings.get("days_to_earnings", "unknown"),
        earnings_proximity_risk=earnings.get("earnings_proximity_risk", "unknown").upper(),
        surprises_str=", ".join([f"{s:+.2f}%" for s in earnings.get("earnings_surprises_last_4q", [])]) or "No data",
        avg_surprise=earnings.get("avg_earnings_surprise") if earnings.get("avg_earnings_surprise") is not None else "N/A",
        beat_miss_trend=earnings.get("beat_miss_trend", "unknown").replace("_", " ").upper(),
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
        key_findings=data.get("key_findings", [])[:3],
        risk_flags=data.get("risk_flags", [])[:3],
        signal_line=data.get("signal_line", ""),
        data_table=data.get("data_table", [])[:5],
        confidence=data.get("confidence", 0.0),
        data=data
    )
