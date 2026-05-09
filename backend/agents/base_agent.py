import os
import functools
import logging
import json
import re
from groq import AsyncGroq
from graph.state import AgentReport, AgentStatus

logger = logging.getLogger(__name__)

def get_llm():
    """Build standardized Groq Client instance using the official SDK."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY environment variable is missing.")
        
    return AsyncGroq(api_key=api_key)

import asyncio
import random
from llm import call_llm as _routed_call_llm


async def call_llm_with_retry(
    client,
    messages,
    response_format=None,
    primary_model='llama-3.3-70b-versatile',
    fallback_model='llama-3.1-8b-instant',
    *,
    agent: str = "unknown",
):
    """Phase 3: thin wrapper that routes through `llm.router.call_llm` so every
    call is recorded in the per-run telemetry contextvar."""
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
