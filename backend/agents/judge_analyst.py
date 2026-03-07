import json
from agents.base_agent import get_llm
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
    sentiment_confidence = sentiment_report.get("confidence", 1.0)
    sentiment_data = sentiment_report.get("data", {})
    
    # Safely get the news_available flag, default True so we don't accidentally halve it if missing
    news_available = sentiment_data.get("news_available", True)

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
        "<synthesis of technical entry/setup>",
        "<synthesis of macro/sentiment context>"
    ],
    "risk_flags": [
        "<synthesis of main bearish arguments>",
        "<critical veto flags triggered, if any>"
    ],
    "final_decision": "STRONG BUY" | "BUY" | "HOLD" | "SELL" | "STRONG SELL",
    "analyst_alignment": "strong_consensus" | "mixed" | "conflicting" | "bearish_consensus",
    "time_horizon_suggested": "short_term_trade" | "medium_term_position" | "long_term_investment" | "avoid",
    "veto_triggered": true | false
}}
"""

async def run_judge_analyst(state: StockAnalysisState) -> AgentReport:
    """Run the final judge analysis to synthesize reports into a verdict."""
    try:
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
        sentiment_confidence = sentiment_report.get("confidence", 1.0)
        sentiment_data = sentiment_report.get("data", {})
        sentiment_news_available = sentiment_data.get("news_available", True)
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
                    env = report.get("data", {}).get("macro_environment", "Unknown")
                    gov = report.get("data", {}).get("governance_quality", "Unknown")
                    reports_text += f"Macro: {env} | Governance: {gov}\\n"
                elif "Technical" in agent_name:
                    trend = report.get("data", {}).get("trend", "Unknown")
                    reports_text += f"Trend: {trend}\\n"
                    
                reports_text += f"Summary: {report.get('summary', '')}\\n"
                reports_text += f"Findings: {'; '.join(report.get('key_findings', []))}\\n"
                if report.get("risk_flags"):
                    reports_text += f"Risks: {'; '.join(report.get('risk_flags', []))}\\n"
                reports_text += "\\n"
            else:
                reports_text += f"[{agent_name.upper()}] Failed or pending.\\n\\n"

        if not reports_text: reports_text = "No reports generated."

        prompt = JUDGE_USER_PROMPT.format(
            company_name=state.get("company_name", "Unknown"),
            ticker=state.get("ticker", "UNKNOWN"),
            analyst_reports=reports_text,
            sentiment_news_available="True" if sentiment_news_available else "False",
            sentiment_confidence=sentiment_confidence,
            effective_sentiment_weight=effective_sentiment_weight,
            sentiment_weight_note=sentiment_weight_note,
            weighted_score=weighted_score
        )

        response = await client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        
        text = response.choices[0].message.content.strip()
        result = json.loads(text)
        
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
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Judge Analyst Error: {e}")
        return AgentReport(
            agent_name="Judge Analyst",
            status=AgentStatus.ERROR,
            summary=f"Analysis failed: {str(e)}",
            score=5.0,
            confidence=0.0,
            key_findings=[],
            risk_flags=["Judge execution failed"],
            data={}
        )
