import os
import functools
import logging
import json
import re
from pydantic import ValidationError

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
    response_schema=None,
):
    """Thin wrapper that routes through `llm.router.call_llm` so every call is
    recorded in the per-run telemetry contextvar.

    `primary_model`/`fallback_model` default to None so the chain built from env
    wins. Pass them only to pin a specific model for one agent.
    """
    _log_prompt_size(agent, messages)
    return await _routed_call_llm(
        client,
        messages,
        agent=agent,
        response_format=response_format,
        primary_model=primary_model,
        fallback_model=fallback_model,
        response_schema=response_schema,
    )


# Rough chars-per-token for English prose + numbers. Good enough to catch a
# prompt that has grown an order of magnitude; not a billing-grade counter.
_CHARS_PER_TOKEN = 4
DEFAULT_PROMPT_TOKEN_BUDGET = int(os.environ.get("AGENT_PROMPT_TOKEN_BUDGET", "6000") or 6000)


def estimate_tokens(messages) -> int:
    return sum(len(str(m.get("content", ""))) for m in messages) // _CHARS_PER_TOKEN


def _log_prompt_size(agent: str, messages) -> None:
    """Warn when an agent's prompt outgrows its budget.

    One agent was pasting an entire unbounded Screener payload into its prompt,
    which is invisible until you read a token bill. A log line is cheap.
    """
    estimated = estimate_tokens(messages)
    if estimated > DEFAULT_PROMPT_TOKEN_BUDGET:
        logger.warning(
            f"[prompt-budget] {agent}: ~{estimated} tokens exceeds budget of "
            f"{DEFAULT_PROMPT_TOKEN_BUDGET}. Trim the context being pasted in."
        )


def validate_report(data: dict, schema, agent_name: str) -> dict:
    """Validate a parsed LLM response against its schema.

    Two-tier on purpose (see models/reports.py): vocabulary drift is coerced by
    the model's validators, while a structural failure — no summary, no score,
    score out of range — raises. The raise is caught by `agent_with_fallback`,
    which produces a degraded report with score=None, so the judge drops that
    pillar's weight instead of averaging in a fabricated number.
    """
    if schema is None:
        return data
    try:
        return schema.model_validate(data).model_dump()
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in exc.errors()[:4]
        )
        raise ValueError(f"{agent_name} output failed schema validation — {problems}") from exc


def parse_and_validate(text: str, schema, agent_name: str) -> dict:
    """parse_llm_json + schema validation, the path every agent should use."""
    return validate_report(parse_llm_json(text), schema, agent_name)

def str_field(data, key: str, default: str = "unknown") -> str:
    """Return a string for `key`, substituting `default` for missing OR None.

    `dict.get(key, default)` returns the default only when the key is ABSENT.
    Upstream payloads — yfinance especially — routinely include the key with an
    explicit None, which then dies on `.lower()` / `.upper()` / `.replace()`.

    This is not hypothetical: `fundamental.get("sector", "Unknown").lower()`
    crashed the Macro & Governance analyst on *every* production run, because
    yfinance is rate-limited from Render's IPs and returns sector=None. The
    agent degraded to a null score on each analysis and the judge lost a whole
    pillar, silently.
    """
    value = data.get(key) if isinstance(data, dict) else None
    if value is None:
        return default
    return str(value)


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
