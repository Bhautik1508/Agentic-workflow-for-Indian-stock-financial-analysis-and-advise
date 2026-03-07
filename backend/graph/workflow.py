from langgraph.graph import START, END, StateGraph
from graph.state import StockAnalysisState
from agents.financial_analyst import run_financial_analysis
from agents.sentiment_analyst import run_sentiment_analysis
from agents.technical_analyst import run_technical_analysis
from agents.risk_analyst import run_risk_analysis
from agents.macro_governance_analyst import run_macro_governance_analysis
from agents.judge_analyst import run_judge_analyst

async def financial_node(state: StockAnalysisState):
    report = await run_financial_analysis(state)
    return {"financial_report": report}

async def sentiment_node(state: StockAnalysisState):
    report = await run_sentiment_analysis(state)
    return {"sentiment_report": report}

async def technical_node(state: StockAnalysisState):
    report = await run_technical_analysis(state)
    return {"technical_report": report}

async def risk_node(state: StockAnalysisState):
    report = await run_risk_analysis(state)
    return {"risk_report": report}

async def macro_governance_node(state: StockAnalysisState):
    report = await run_macro_governance_analysis(state)
    return {"macro_governance_report": report}

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
    
    metadata = final_report.get("metadata", {})
    return {
        "final_decision": metadata.get("final_decision", "HOLD"),
        "confidence_score": final_report.get("confidence", 0.0) * 10.0,
        "investment_thesis": final_report.get("summary", ""),
        "key_risks": final_report.get("risk_flags", [])
    }

def build_workflow():
    workflow = StateGraph(StockAnalysisState)
    
    workflow.add_node("financial_node", financial_node)
    workflow.add_node("sentiment_node", sentiment_node)
    workflow.add_node("technical_node", technical_node)
    workflow.add_node("risk_node", risk_node)
    workflow.add_node("macro_governance_node", macro_governance_node)
    workflow.add_node("judge_node", judge_node)
    
    workflow.add_edge(START, "financial_node")
    workflow.add_edge(START, "sentiment_node")
    workflow.add_edge(START, "technical_node")
    workflow.add_edge(START, "risk_node")
    workflow.add_edge(START, "macro_governance_node")
    
    workflow.add_edge("financial_node", "judge_node")
    workflow.add_edge("sentiment_node", "judge_node")
    workflow.add_edge("technical_node", "judge_node")
    workflow.add_edge("risk_node", "judge_node")
    workflow.add_edge("macro_governance_node", "judge_node")
    
    workflow.add_edge("judge_node", END)
    
    return workflow.compile()
