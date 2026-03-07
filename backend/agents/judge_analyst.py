import json
from agents.base_agent import get_llm
from graph.state import StockAnalysisState, AgentReport, AgentStatus

JUDGE_SYSTEM_PROMPT = """You are the Chief Investment Officer (CIO) and final Judge at a top Indian Hedge Fund.
You synthesize the reports from 5 specialist analysts into a final, conviction-driven trading
verdict for NSE/BSE listed equities.

Your weighting framework:
1. Fundamental (30%) - Valuation, Moat, Growth, Profitability
2. Technical (25%) - Price action, volume, trend alignment, entry point
3. Sentiment (15%) - FII/DII flow, smart money behavior, news momentum
4. Risk (15%) - Volatility, liquidity, balance sheet safety
5. Macro/Governance (15%) - RBI policy, sector tailwinds, management integrity

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
        reports = state.get("analyst_reports", {})
        
        # Format all reports into a readable string
        reports_text = ""
        for agent_name, report in reports.items():
            if report.status == AgentStatus.COMPLETE:
                reports_text += f"[{agent_name.upper()}]\n"
                reports_text += f"Score: {report.score}/10 | Confidence: {report.confidence}\n"
                if "Macro" in agent_name:
                    env = report.data.get("macro_environment", "Unknown")
                    gov = report.data.get("governance_quality", "Unknown")
                    reports_text += f"Macro: {env} | Governance: {gov}\n"
                elif "Technical" in agent_name:
                    trend = report.data.get("trend", "Unknown")
                    reports_text += f"Trend: {trend}\n"
                    
                reports_text += f"Summary: {report.summary}\n"
                reports_text += f"Findings: {'; '.join(report.key_findings)}\n"
                if report.risk_flags:
                    reports_text += f"Risks: {'; '.join(report.risk_flags)}\n"
                reports_text += "\n"
            else:
                reports_text += f"[{agent_name.upper()}] Failed or pending.\n\n"

        if not reports_text: reports_text = "No reports generated."

        prompt = JUDGE_USER_PROMPT.format(
            company_name=state.get("company_name", "Unknown"),
            ticker=state.get("ticker", "UNKNOWN"),
            analyst_reports=reports_text
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
