import asyncio
import logging
from langgraph.graph import START, END, StateGraph
from graph.state import StockAnalysisState, AgentReport, AgentStatus
from agents.financial_analyst import run_financial_analysis
from agents.sentiment_analyst import run_sentiment_analysis
from agents.technical_analyst import run_technical_analysis
from agents.risk_analyst import run_risk_analysis
from agents.macro_governance_analyst import run_macro_governance_analysis
from agents.judge_analyst import run_judge_analyst

logger = logging.getLogger(__name__)

# Bound concurrent LLM calls so we stay under provider rate limits without
# serialising. Each agent call still has its own retry + cross-provider
# failover inside call_llm_with_retry.
ANALYST_CONCURRENCY = 3
_analyst_semaphore = None


def _get_semaphore() -> asyncio.Semaphore:
    """Build the semaphore lazily, inside the running loop.

    A module-level `asyncio.Semaphore()` binds the loop that happened to exist
    at import time on Python 3.9, then throws `got Future attached to a
    different loop` as soon as more than ANALYST_CONCURRENCY analysts contend —
    which is always, with five. Production pins 3.11 where construction is
    lazy anyway, so this was invisible there and fatal locally.
    """
    global _analyst_semaphore
    if _analyst_semaphore is None:
        _analyst_semaphore = asyncio.Semaphore(ANALYST_CONCURRENCY)
    return _analyst_semaphore


async def _run_under_semaphore(agent_name: str, coro):
    async with _get_semaphore():
        try:
            return await coro
        except Exception as e:
            logger.error(f"Analyst {agent_name} raised: {e}", exc_info=True)
            return e


async def run_parallel_analysts(state: StockAnalysisState) -> StockAnalysisState:
    """Run all five analysts concurrently bounded by a semaphore."""
    agent_specs = [
        ("financial_report", "Financial Analyst", run_financial_analysis(state)),
        ("sentiment_report", "Sentiment Analyst", run_sentiment_analysis(state)),
        ("risk_report", "Risk Analyst", run_risk_analysis(state)),
        ("technical_report", "Technical Analyst", run_technical_analysis(state)),
        ("macro_governance_report", "Macro & Governance Analyst", run_macro_governance_analysis(state)),
    ]

    results = await asyncio.gather(
        *[_run_under_semaphore(name, coro) for _, name, coro in agent_specs],
        return_exceptions=False,
    )

    updates = {}
    for (key, agent_name, _), result in zip(agent_specs, results):
        if isinstance(result, Exception):
            updates[key] = AgentReport(
                agent_name=agent_name,
                status=AgentStatus.ERROR,
                summary=f"Agent failed: {str(result)[:120]}",
                score=None,
                key_findings=[],
                risk_flags=[],
                signal_line="Analysis unavailable",
                data_table=[],
                confidence=0.0,
                degraded=True,
                error=str(result)[:200],
                data={"error": str(result)},
            )
        else:
            updates[key] = result

    return {**state, **updates}


async def judge_node(state: StockAnalysisState):
    reports = {
        "Financial Analyst": state.get("financial_report"),
        "Sentiment Analyst": state.get("sentiment_report"),
        "Technical Analyst": state.get("technical_report"),
        "Risk Analyst": state.get("risk_report"),
        "Macro & Governance Analyst": state.get("macro_governance_report"),
    }
    reports = {k: v for k, v in reports.items() if v is not None}

    state_for_judge = dict(state)
    state_for_judge["analyst_reports"] = reports

    final_report = await run_judge_analyst(state_for_judge)

    if isinstance(final_report, dict):
        metadata = final_report.get("data", {}) or {}
        confidence = float(final_report.get("confidence", 0.0) or 0.0)
        thesis = final_report.get("summary", "")
        risk_flags = final_report.get("risk_flags", [])
    else:
        metadata = getattr(final_report, "data", {}) or {}
        confidence = float(getattr(final_report, "confidence", 0.0) or 0.0)
        thesis = getattr(final_report, "summary", "")
        risk_flags = getattr(final_report, "risk_flags", [])

    action = metadata.get("action", "HOLD")
    # Canonical wire format for confidence: float in [0, 1]. Frontend renders as percentage.
    return {
        "final_decision": action,
        "action": action,
        "confidence_score": max(0.0, min(1.0, confidence)),
        "investment_thesis": metadata.get("investment_thesis") or thesis,
        "key_risks": metadata.get("key_risks") or risk_flags,
        "key_catalysts": metadata.get("key_catalysts", []),
        "conviction_level": metadata.get("conviction_level", "medium"),
        "max_entry_price": metadata.get("max_entry_price"),
        "target_price_inr": metadata.get("target_price"),
        "stop_loss_inr": metadata.get("stop_loss"),
        "time_horizon": metadata.get("time_horizon"),
        "judge_score": metadata.get("score"),
        "score_attribution": metadata.get("score_attribution", {}),
        "strongest_pillar": metadata.get("strongest_pillar"),
        "weakest_pillar": metadata.get("weakest_pillar"),
        # Phase 2
        "risk_profile": metadata.get("risk_profile") or state.get("risk_profile"),
        "grounded_targets": metadata.get("grounded_targets"),
        "veto": metadata.get("veto"),
        "dissent_summary": metadata.get("dissent_summary"),
        # Phase 3 — pass-through from runner-injected state fields
        "data_quality": state.get("data_quality"),
        "stale_sources": state.get("stale_sources"),
        # Phase 5
        "counter_factual": metadata.get("counter_factual"),
    }


def build_workflow():
    workflow = StateGraph(StockAnalysisState)

    workflow.add_node("parallel_analysts", run_parallel_analysts)
    workflow.add_node("judge_node", judge_node)

    workflow.add_edge(START, "parallel_analysts")
    workflow.add_edge("parallel_analysts", "judge_node")
    workflow.add_edge("judge_node", END)

    return workflow.compile()
