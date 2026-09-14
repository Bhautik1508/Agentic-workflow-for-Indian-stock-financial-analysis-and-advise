import os
import functools
import logging
import json
import re
from graph.state import AgentReport, AgentStatus
from llm import build_default_chain, call_llm as _routed_call_llm

logger = logging.getLogger(__name__)


def get_llm():
    """Return the configured provider chain: Gemini primary, Groq fallback.

    Named `get_llm` for continuity — every agent already calls it — but it no
    longer hands back a single vendor client. The router walks the chain and
    fails over between providers, so an outage or a decommissioned model at one
    vendor degrades to the other instead of failing the whole analysis.
    """
    chain = build_default_chain()
    if not chain:
        raise ValueError(
            "No LLM provider configured. Set GOOGLE_API_KEY (Gemini, primary) "
            "and/or GROQ_API_KEY (Groq, fallback)."
        )
    return chain


async def call_llm_with_retry(
    client,
    messages,
    response_format=None,
    primary_model=None,
    fallback_model=None,
    *,
    agent: str = "unknown",
):
    """Thin wrapper that routes through `llm.router.call_llm` so every call is
    recorded in the per-run telemetry contextvar.

    `primary_model`/`fallback_model` default to None so the chain built from env
    wins. Pass them only to pin a specific model for one agent.
    """
    return await _routed_call_llm(
        client,
        messages,
        agent=agent,
        response_format=response_format,
        primary_model=primary_model,
        fallback_model=fallback_model,
    )

def parse_llm_json(response_content: str) -> dict:
    """Robustly parse JSON from LLM response, handling markdown fences."""
    content = response_content.strip()
    
    # Remove markdown code fences
    content = re.sub(r'^```json\s*', '', content, flags=re.MULTILINE)
    content = re.sub(r'^```\s*', '', content, flags=re.MULTILINE)
    content = re.sub(r'\s*```$', '', content, flags=re.MULTILINE)
    content = content.strip()
    
    # Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    
    # Try finding JSON object within the text
    match = re.search(r'\{.*\}', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
            
    raise ValueError(f"Could not parse JSON from LLM response: {content[:200]}")

def _fallback_report(agent_name: str, error: str) -> AgentReport:
    """Build a 'degraded' report. score=None signals the judge to drop this agent's
    weight rather than averaging in a 5.0 placeholder that quietly drags verdicts."""
    return AgentReport(
        agent_name=agent_name,
        status=AgentStatus.ERROR,
        summary=f"Analysis unavailable: {error[:120]}",
        score=None,
        key_findings=[],
        risk_flags=[],
        signal_line="Analysis unavailable",
        data_table=[],
        confidence=0.0,
        degraded=True,
        error=error[:200],
        data={"error": error}
    )

def agent_with_fallback(agent_name: str, default_score: float = 5.0):
    """default_score kept for backwards compatibility but is no longer used —
    failed agents now return degraded reports with score=None."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state, *args, **kwargs):
            try:
                return await func(state, *args, **kwargs)
            except Exception as e:
                logger.error(f"{agent_name} failed: {e}", exc_info=True)
                return _fallback_report(agent_name, str(e))
        return wrapper
    return decorator
