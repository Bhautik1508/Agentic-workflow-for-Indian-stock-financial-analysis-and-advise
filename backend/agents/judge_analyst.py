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

JUDGE_SYSTEM_PROMPT = """You are the Chief Investment Officer (CIO) at a top Indian hedge fund.
You synthesise 5 specialist reports into a DECISIVE verdict. You are paid
to make calls — not to default to HOLD.

SCORING BANDS:
STRONG_BUY : score >= 7.5 — All pillars aligned, clear catalyst, strong setup
BUY        : score 6.0–7.5 — Good quality, decent setup, acceptable risk
HOLD       : score 4.5–6.0 — Genuinely mixed signals or awaiting confirmation
SELL       : score 3.0–4.5 — Deteriorating fundamentals or broken trend
STRONG_SELL: score < 3.0 — Governance red flags or structural collapse

DECISION RULES (apply these, do not override with intuition):
- If 3+ analysts score >= 6.5: verdict is BUY unless Risk score < 4.0
- If Financial >= 7.0 AND Technical >= 6.0: verdict is BUY unless Risk < 4.0
- If Risk < 4.0 AND Financial < 5.0 simultaneously: verdict is SELL
- A 5.5 no-news sentiment for a Nifty50 stock = NEUTRAL (not negative)
- A profitable company with 10-15% growth is at minimum a 6.5 financial score

WEIGHTS: Financial 30% | Technical 23% | Risk 22% | Macro/Gov 13% | Sentiment 12%
Output ONLY valid JSON. No preamble."""

JUDGE_USER_PROMPT = """
Synthesise the following 5 specialist reports for {company_name} ({ticker}).

━━━ ANALYST SCORES & SIGNALS ━━━
{analyst_reports}

━━━ SENTIMENT WEIGHT NOTE ━━━
Sentiment news_available: {sentiment_news_available}
Effective sentiment weight: {effective_sentiment_weight}
{sentiment_weight_note}

━━━ PRE-COMPUTED WEIGHTED SCORE ━━━
Mathematical weighted score: {weighted_score}/10
(Use as baseline. Adjust based on your CIO judgement and the rules above.)

━━━ KEY CONTEXT ━━━
Financial valuation: {val_verdict} | Health: {fin_health}
Technical trend: {tech_trend} | Signal: {tech_signal}
Risk level: {risk_level} | Macro: {macro_env} | Governance: {gov_quality}

Return JSON with this EXACT schema:
{{
  "summary": "<1-paragraph conviction synthesis>",
  "action": "STRONG_BUY"|"BUY"|"HOLD"|"SELL"|"STRONG_SELL",
  "score": <float 0-10>,
  "confidence": <float 0.0-1.0>,
  "investment_thesis": "<3-4 sentence compelling narrative>",
  "key_catalysts": ["<catalyst 1>", "<catalyst 2>", "<catalyst 3>"],
  "key_risks": ["<risk 1>", "<risk 2>", "<risk 3>"],
  "target_price": <float INR>,
  "max_entry_price": <float INR>,
  "stop_loss": <float INR>,
  "time_horizon": "short_term"|"medium_term"|"long_term",
  "conviction_level": "high"|"medium"|"low",
  "strongest_pillar": "financial"|"technical"|"risk"|"sentiment"|"macro_governance",
  "weakest_pillar": "financial"|"technical"|"risk"|"sentiment"|"macro_governance",
  "score_attribution": {{
    "financial": "<score and 1-sentence reason>",
    "technical": "<score and 1-sentence reason>",
    "risk": "<score and 1-sentence reason>",
    "sentiment": "<score and 1-sentence reason>",
    "macro_governance": "<score and 1-sentence reason>"
  }}
}}
"""



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

    fin_rep = raw_reports.get("Financial Analyst", {}) or {}
    tech_rep = raw_reports.get("Technical Analyst", {}) or {}
    risk_rep = raw_reports.get("Risk Analyst", {}) or {}
    sent_rep = raw_reports.get("Sentiment Analyst", {}) or {}
    macro_rep = raw_reports.get("Macro & Governance Analyst", {}) or {}
    
    fin_data = fin_rep.get("data", {}) if isinstance(fin_rep, dict) else {}
    tech_data = tech_rep.get("data", {}) if isinstance(tech_rep, dict) else {}
    risk_data = risk_rep.get("data", {}) if isinstance(risk_rep, dict) else {}
    macro_data = macro_rep.get("data", {}) if isinstance(macro_rep, dict) else {}

    val_verdict = fin_data.get('valuation_verdict', 'N/A')
    fin_health  = fin_data.get('financial_health', 'N/A')
    tech_trend  = tech_data.get('trend', 'N/A')
    tech_signal = tech_rep.get('signal_line', 'N/A') if isinstance(tech_rep, dict) else 'N/A'
    risk_level  = risk_data.get('risk_level', 'N/A')
    macro_env   = macro_data.get('macro_environment', 'N/A')
    gov_quality = macro_data.get('governance_quality', 'N/A')

    prompt = JUDGE_USER_PROMPT.format(
        company_name=state.get("company_name", "Unknown"),
        ticker=state.get("ticker", "UNKNOWN"),
        analyst_reports=reports_text,
        sentiment_news_available="True" if sentiment_news_available else "False",
        effective_sentiment_weight=effective_sentiment_weight,
        sentiment_weight_note=sentiment_weight_note,
        weighted_score=weighted_score,
        
        val_verdict=val_verdict,
        fin_health=fin_health,
        tech_trend=tech_trend,
        tech_signal=tech_signal,
        risk_level=risk_level,
        macro_env=macro_env,
        gov_quality=gov_quality
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
