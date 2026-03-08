import asyncio
from langgraph.graph import START, END, StateGraph
from graph.state import StockAnalysisState, AgentReport, AgentStatus
from agents.financial_analyst import run_financial_analysis
from agents.sentiment_analyst import run_sentiment_analysis
from agents.technical_analyst import run_technical_analysis
from agents.risk_analyst import run_risk_analysis
from agents.macro_governance_analyst import run_macro_governance_analysis
from agents.judge_analyst import run_judge_analyst

async def run_parallel_analysts(state: StockAnalysisState) -> StockAnalysisState:
    tasks = [
        run_financial_analysis(state),
        run_sentiment_analysis(state),
        run_risk_analysis(state),
        run_technical_analysis(state),
        run_macro_governance_analysis(state),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    keys = ["financial_report", "sentiment_report", "risk_report",
            "technical_report", "macro_governance_report"]
    
    updates = {}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            updates[key] = AgentReport(
                agent_name=key,
                status=AgentStatus.ERROR,
                summary=f"Agent failed: {str(result)}",
                score=5.0,
                key_findings=["Agent encountered an error"],
                risk_flags=[],
                confidence=0.0,
                data={}
            )
        else:
            updates[key] = result
    
    return {**state, **updates}

async def judge_node(state: StockAnalysisState):
    # Pack reports for the judge
    reports = {
        "Financial Analyst": state.get("financial_report"),
        "Sentiment Analyst": state.get("sentiment_report"),
        "Technical Analyst": state.get("technical_report"),
        "Risk Analyst": state.get("risk_report"),
        "Macro & Governance Analyst": state.get("macro_governance_report")
    }
    
    # Filter out empty reports if any
    reports = {k: v for k, v in reports.items() if v is not None}
    
    # Temporary inject to state so judge knows mapping
    state_for_judge = dict(state)
    state_for_judge["analyst_reports"] = reports
    
    final_report = await run_judge_analyst(state_for_judge)
    
    metadata = final_report.get("data", {}) if isinstance(final_report, dict) else final_report.data
    return {
        "final_decision": metadata.get("final_decision", "HOLD"),
        "confidence_score": final_report.get("confidence", 0.0) * 10.0 if isinstance(final_report, dict) else getattr(final_report, 'confidence', 0.0) * 10.0,
        "investment_thesis": final_report.get("summary", "") if isinstance(final_report, dict) else getattr(final_report, 'summary', ""),
        "key_risks": final_report.get("risk_flags", []) if isinstance(final_report, dict) else getattr(final_report, 'risk_flags', [])
    }

def build_workflow():
    workflow = StateGraph(StockAnalysisState)
    
    workflow.add_node("parallel_analysts", run_parallel_analysts)
    workflow.add_node("judge_node", judge_node)
    
    workflow.add_edge(START, "parallel_analysts")
    workflow.add_edge("parallel_analysts", "judge_node")
    workflow.add_edge("judge_node", END)
    
    return workflow.compile()
