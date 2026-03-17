from agents.base_agent import get_llm, parse_llm_json, agent_with_fallback, call_llm_with_retry
from graph.state import StockAnalysisState, AgentReport, AgentStatus

JUDGE_WEIGHTS = {
    "financial":   0.30,
    "technical":   0.23,
    "risk":        0.22,
    "sentiment":   0.12,
    "macro_gov":   0.13,
}

def adjust_for_low_confidence_sentiment(reports: dict, weights: dict) -> tuple[dict, dict]:
    """
    If sentiment report has low confidence (no news data), reduce its effective
    weight to half and redistribute the freed weight to Financial analyst.
    This prevents a data-absent 5.0-6.0 sentiment score from dragging strong
    fundamental stocks toward HOLD.
    """
    sentiment_report = reports.get("Sentiment Analyst", {})
    
    # In case data isn't a dict due to parsing fallback logic
    sentiment_data = sentiment_report.get("data", {}) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "data", {})
    sentiment_confidence = sentiment_report.get("confidence", 1.0) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "confidence", 1.0)

    # Safely get the news_available flag, default True so we don't accidentally halve it if missing
    news_available = sentiment_data.get("news_available", True) if isinstance(sentiment_data, dict) else True

    if not news_available or sentiment_confidence < 0.5:
        freed_weight = weights["sentiment"] * 0.5
        adjusted_weights = {**weights}
        adjusted_weights["sentiment"]  = weights["sentiment"] * 0.5
        adjusted_weights["financial"]  = weights["financial"] + freed_weight
        return reports, adjusted_weights

    return reports, weights

JUDGE_SYSTEM_PROMPT = """You are the Chief Investment Officer (CIO) and final Judge at a top Indian Hedge Fund.
You synthesize the reports from 5 specialist analysts into a final, conviction-driven trading
verdict for NSE/BSE listed equities.

Your weighting framework (Approximate Baseline):
1. Fundamental (30%) - Valuation, Moat, Growth, Profitability
2. Technical (23%) - Price action, volume, trend alignment, entry point
3. Risk (22%) - Volatility, liquidity, balance sheet safety
4. Macro/Governance (13%) - RBI policy, sector tailwinds, management integrity
5. Sentiment (12%) - FII/DII flow, smart money behavior, news momentum

Veto Rules (Automatic downgrade or "SELL" decision):
- Immediate SELL if Governance analyst flags "pledge concern" or "poor governance"
- Immediate SELL if Risk and Fundamental are BOTH below 4.0
- Maximum Rating = HOLD if Technical analyst indicates "strong downtrend" AND "bearish MACD crossover"
- Cannot be BUY if Fundamental score < 5.0 (growth/valuation do not support)

Final decision categories:
- STRONG BUY: (Score > 8.0) All analysts aligned, clear catalyst, favorable macro/setup.
- BUY: (Score 6.5 - 8.0) Good fundamentals, decent setup, acceptable risk.
- HOLD: (Score 4.5 - 6.5) Mixed signals, fully valued, or waiting for technical confirmation.
- SELL: (Score 2.5 - 4.5) Deteriorating fundamentals, broken trend, or high risk.
- STRONG SELL: (Score < 2.5) Governance red flags, immense structural headwinds.

Output ONLY valid JSON. No preamble, no explanation outside the JSON."""

JUDGE_USER_PROMPT = """
Synthesize the following 5 specialist reports for {company_name} ({ticker}) and deliver the final verdict.

━━━ SPECIALIST REPORTS ━━━
{analyst_reports}

━━━ SENTIMENT WEIGHT NOTE ━━━
Sentiment news_available: {sentiment_news_available}
Sentiment confidence:     {sentiment_confidence}
Effective sentiment weight used: {effective_sentiment_weight}

{sentiment_weight_note}

━━━ PRE-COMPUTED SCORE ━━━
Base mathematically weighted score: {weighted_score}
(Use this as a baseline, but feel free to adjust based on veto flags and text analysis)

Provide your final judgement as JSON with this exact schema:
{{
    "summary": "1-paragraph synthesis of the overall consensus and primary catalyst.",
    "score": <float 0.0–10.0 based on the weighted average and your CIO adjustments>,
    "confidence": <float 0.0–1.0 based on inter-analyst agreement>,
    "key_findings": [
        "<synthesis of bullish points>",
    "summary": "<2-3 sentence final verdict>",
    "action": "BUY" | "HOLD" | "SELL",
    "score": <float 0-10>,
    "max_entry_price": <float INR, absolute max to pay based on TA and fundamentals>,
    "target_price": <float INR, blended target from TA and Fundamentals>,
    "stop_loss": <float INR, mandatory invalidation level>,
    "time_horizon": "short_term" | "medium_term" | "long_term",
    "conviction_level": "high" | "medium" | "low",
    "veto_triggered": true | false,
    "score_attribution": {{
        "financial_weight": "<string, e.g. '+3/10 (Undervalued)'>",
        "technical_weight": "<string, e.g. '+1/10 (Neutral setup)'>",
        "macro_gov_weight": "<string, e.g. '-2/10 (Governance veto)'>",
        "risk_weight": "<string, e.g. '0/10 (Standard risk)'>"
    }},
    "weakest_pillar": "financial" | "technical" | "macro_governance" | "risk",
    "strongest_pillar": "financial" | "technical" | "macro_governance" | "risk"
}}
"""

def apply_all_veto_rules(state: dict, reports: dict) -> list:
    """
    Evaluates hard risk rules across all data.
    Returns a list of veto reasons (strings). If empty, no veto.
    """
    vetoes = []
    
    # 1. Earnings Proximity Veto
    earnings_risk = reports.get("financial", {}).get("earnings_risk", "unknown")
    if earnings_risk == "very_high":
        vetoes.append("EARNINGS_PROXIMITY: Earnings within 7 days. Action restricted to HOLD/wait-and-see.")
        
    # 2. Options Signal vs Technical Veto
    options_sig = reports.get("technical", {}).get("options_signal", "neutral")
    tech_sig = reports.get("technical", {}).get("signal", "buy")
    if (options_sig == "bearish" and "buy" in tech_sig) or (options_sig == "bullish" and "sell" in tech_sig):
        vetoes.append(f"OPTIONS_DIVERGENCE: Tech signal is {tech_sig} but options chain indicates {options_sig}. Requires high conviction to proceed.")
        
    # 3. Governance Veto
    gov_veto = reports.get("macro_governance", {}).get("governance_veto_risk", False)
    pledge_risk = reports.get("macro_governance", {}).get("governance_score_detail", {}).get("pledge_risk", 10)
    if gov_veto or pledge_risk < 2:  # Assuming score < 2 means terrible pledge
        vetoes.append("GOVERNANCE_VETO: Promoter pledge is critically high (>50%) or governance is severely compromised. Cap score at 4/10.")
        
    # 4. Market VIX Veto
    fear_level = state.get("market_breadth", {}).get("fear_level", "normal")
    if fear_level == "high_fear":
        vetoes.append("SYSTEMIC_RISK: India VIX > 25. Extremely high market volatility. Reduce position sizes significantly.")
        
    # 5. Risk Assessment Veto
    risk_report = reports.get("risk", {})
    if risk_report.get("risk_level") == "very_high" or risk_report.get("financial_risk") == "high":
        vetoes.append("FUNDAMENTAL_RISK_VETO: Severe company-specific risk or financial distress detected. Action restricted to SELL/AVOID.")
        
    return vetoes

async def run_judge_analysis(state: dict) -> dict:
    # 1) Re-parse all analyst outputs from state
    fa = state.get("financial_analysis", {})
    ta = state.get("technical_analysis", {})
    ma = state.get("macro_governance_analysis", {})
    ra = state.get("risk_analysis", {})
    
    # Bundle for the veto function
    reports_bundle = {
        "financial": fa,
        "technical": ta,
        "macro_governance": ma,
        "risk": ra
    }
    
    # 2) Run hard systemic veto checks
    vetoes = apply_all_veto_rules(state, reports_bundle)
    if vetoes:
        veto_status_string = "🚨 VETO(ES) TRIGGERED:\n- " + "\n- ".join(vetoes)
    else:
        veto_status_string = "✅ PASS: No hard systemic system vetoes triggered."
    
    # 3) Setup format vars
    prompt = JUDGE_USER_PROMPT.format(
        company_name=state.get("company_name", "the asset"),
        
        val_verdict=fa.get("valuation_verdict", "N/A"),
        fin_health=fa.get("financial_health", "N/A"),
        pe_premium_discount=f"{fa.get('pe_premium_discount_pct', 'N/A')}%",
        fin_details=str({k:v for k,v in fa.items() if k not in ["valuation_verdict", "financial_health"]}),
        
        trend=ta.get("trend_analysis", "N/A"),
        tech_signal=ta.get("signal", "N/A"),
        tech_target=ta.get("technical_target", "N/A"),
        options_signal=ta.get("options_signal", "N/A"),
        tech_tailwind=ta.get("market_tailwind", False),
        tech_details=str({k:v for k,v in ta.items() if k not in ["trend_analysis", "signal"]}),
        
        macro_env=ma.get("macro_environment", "N/A"),
        gov_quality=ma.get("governance_quality", "N/A"),
        insider_signal=ma.get("insider_signal", "N/A"),
        gov_veto=ma.get("governance_veto_risk", False),
        macro_tailwind=ma.get("macro_tailwind", False),
        currency_impact=ma.get("currency_impact", "N/A"),
        macro_gov_details=str({k:v for k,v in ma.items() if k not in ["macro_environment", "governance_quality", "insider_signal"]}),
        
        risk_level=ra.get("risk_level", "N/A"),
        fin_risk=ra.get("financial_risk", "N/A"),
        event_risk=ra.get("event_risk", "N/A"),
        stop_buffer=ra.get("recommended_stop_loss_buffer", "N/A"),
        size_mod=ra.get("position_size_modifier", "N/A"),
        risk_details=str({k:v for k,v in ra.items() if k not in ["risk_level", "financial_risk"]}),
        
        veto_status_string=veto_status_string
    )
    
    client = get_llm()
    text = await call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    
    result = parse_llm_json(text)
    return result

@agent_with_fallback("Judge Analyst", default_score=5.0)
async def run_judge_analyst(state: StockAnalysisState) -> AgentReport:
    """Run the final judge analysis to synthesize reports into a verdict."""
    client = get_llm()
    raw_reports = state.get("analyst_reports", {})
    
    # Add dynamic weighting based on confidence rules
    reports, effective_weights = adjust_for_low_confidence_sentiment(raw_reports, JUDGE_WEIGHTS)
    
    # Safely map external analyst names to internal weighting keys
    # "Financial Analyst" -> "financial", etc.
    weighting_map = {
        "Financial Analyst": "financial",
        "Technical Analyst": "technical",
        "Risk Analyst": "risk",
        "Sentiment Analyst": "sentiment",
        "Macro & Governance Analyst": "macro_gov"
    }
    
    # Calculate mathematical baseline weighted score
    calculated_score = 0.0
    for agent_name, report in reports.items():
        if report and isinstance(report, dict) and report.get("status") == AgentStatus.COMPLETE:
            score = report.get("score", 5.0)
            if agent_name in weighting_map:
                calculated_score += score * effective_weights[weighting_map[agent_name]]
    
    weighted_score = round(calculated_score, 2)
    
    # Get sentiments flags for the prompt inclusion
    sentiment_report = reports.get("Sentiment Analyst", {})
    sentiment_confidence = sentiment_report.get("confidence", 1.0) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "confidence", 1.0)
    sentiment_data = sentiment_report.get("data", {}) if isinstance(sentiment_report, dict) else getattr(sentiment_report, "data", {})
    sentiment_news_available = sentiment_data.get("news_available", True) if isinstance(sentiment_data, dict) else True
    effective_sentiment_weight = effective_weights["sentiment"]
    
    if not sentiment_news_available or sentiment_confidence < 0.5:
        sentiment_weight_note = "NOTE: Sentiment score is based on FII/DII data only (no news).\\n Its weight has been halved. Do not let the sentiment score override strong fundamental\\n or technical signals. A 6.0 no-news sentiment for a Nifty50 stock is a NEUTRAL signal,\\n not a negative one — treat it accordingly."
    else:
        sentiment_weight_note = "Sentiment data is robust. Weight remains standard."

    # Format all reports into a readable string
    reports_text = ""
    for agent_name, report in reports.items():
        if report and isinstance(report, dict) and report.get("status") == AgentStatus.COMPLETE:
            reports_text += f"[{agent_name.upper()}]\\n"
            reports_text += f"Score: {report.get('score', 0)}/10 | Confidence: {report.get('confidence', 0.0)}\\n"
            
            # Check based on dict access
            if "Macro" in agent_name:
                env = report.get("data", {}).get("macro_environment", "Unknown") if isinstance(report.get("data"), dict) else "Unknown"
                gov = report.get("data", {}).get("governance_quality", "Unknown") if isinstance(report.get("data"), dict) else "Unknown"
                reports_text += f"Macro: {env} | Governance: {gov}\\n"
            elif "Technical" in agent_name:
                trend = report.get("data", {}).get("trend", "Unknown") if isinstance(report.get("data"), dict) else "Unknown"
                reports_text += f"Trend: {trend}\\n"
                
            reports_text += f"Summary: {report.get('summary', '')}\\n"
            reports_text += f"Findings: {'; '.join(report.get('key_findings', []))}\\n"
            if report.get("risk_flags"):
                reports_text += f"Risks: {'; '.join(report.get('risk_flags', []))}\\n"
            reports_text += "\\n"
        else:
            reports_text += f"[{agent_name.upper()}] Failed or pending.\\n\\n"

    if not reports_text: reports_text = "No reports generated."

    # 1) Re-parse all analyst outputs from state
    fa = state.get("financial_analysis", {})
    ta = state.get("technical_analysis", {})
    ma = state.get("macro_governance_analysis", {})
    ra = state.get("risk_analysis", {})
    
    # Bundle for the veto function
    reports_bundle = {
        "financial": fa,
        "technical": ta,
        "macro_governance": ma,
        "risk": ra
    }
    
    # 2) Run hard systemic veto checks
    vetoes = apply_all_veto_rules(state, reports_bundle)
    if vetoes:
        veto_status_string = "🚨 VETO(ES) TRIGGERED:\n- " + "\n- ".join(vetoes)
    else:
        veto_status_string = "✅ PASS: No hard systemic system vetoes triggered."

    prompt = JUDGE_USER_PROMPT.format(
        company_name=state.get("company_name", "Unknown"),
        ticker=state.get("ticker", "UNKNOWN"),
        analyst_reports=reports_text,
        sentiment_news_available="True" if sentiment_news_available else "False",
        sentiment_confidence=sentiment_confidence,
        effective_sentiment_weight=effective_sentiment_weight,
        sentiment_weight_note=sentiment_weight_note,
        weighted_score=weighted_score,
        
        val_verdict=fa.get("valuation_verdict", "N/A"),
        fin_health=fa.get("financial_health", "N/A"),
        pe_premium_discount=f"{fa.get('pe_premium_discount_pct', 'N/A')}%",
        fin_details=str({k:v for k,v in fa.items() if k not in ["valuation_verdict", "financial_health"]}),
        
        trend=ta.get("trend_analysis", "N/A"),
        tech_signal=ta.get("signal", "N/A"),
        tech_target=ta.get("technical_target", "N/A"),
        options_signal=ta.get("options_signal", "N/A"),
        tech_tailwind=ta.get("market_tailwind", False),
        tech_details=str({k:v for k,v in ta.items() if k not in ["trend_analysis", "signal"]}),
        
        macro_env=ma.get("macro_environment", "N/A"),
        gov_quality=ma.get("governance_quality", "N/A"),
        insider_signal=ma.get("insider_signal", "N/A"),
        gov_veto=ma.get("governance_veto_risk", False),
        macro_tailwind=ma.get("macro_tailwind", False),
        currency_impact=ma.get("currency_impact", "N/A"),
        macro_gov_details=str({k:v for k,v in ma.items() if k not in ["macro_environment", "governance_quality", "insider_signal"]}),
        
        risk_level=ra.get("risk_level", "N/A"),
        fin_risk=ra.get("financial_risk", "N/A"),
        event_risk=ra.get("event_risk", "N/A"),
        stop_buffer=ra.get("recommended_stop_loss_buffer", "N/A"),
        size_mod=ra.get("position_size_modifier", "N/A"),
        risk_details=str({k:v for k,v in ra.items() if k not in ["risk_level", "financial_risk"]}),
        
        veto_status_string=veto_status_string
    )

    text = await call_llm_with_retry(
        client=client,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    
    result = parse_llm_json(text)
    
    return AgentReport(
        agent_name="Judge Analyst",
        status=AgentStatus.COMPLETE,
        summary=result.get("summary", ""),
        score=result.get("score"),
        confidence=result.get("confidence", 0.0),
        key_findings=result.get("key_findings", []),
        risk_flags=result.get("risk_flags", []),
        data=result
    )
