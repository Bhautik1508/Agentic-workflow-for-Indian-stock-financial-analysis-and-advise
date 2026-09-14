"""Routing for LLM calls. Gemini primary; Groq fallback.

Why a thin router instead of calling a vendor SDK directly:
- Single chokepoint to record latency / token spend
- Single chokepoint to fail across *providers*, not just across models
- Keeps `call_llm_with_retry` from growing into a 200-line monster

Failover policy
---------------
The router walks an ordered chain of `(provider, model)` attempts and returns
the first success. It advances on **any** error, not just rate limits.

That last part is deliberate. The previous version only failed over on 429 and
re-raised everything else, which meant a model decommission (404), an expired
key (401) or a provider 5xx took down every agent with no second chance — which
is exactly what happened when Groq retired the llama-3.x models. Rate limits
still get a backoff sleep before the next attempt; other errors move on
immediately, because waiting does not help a 404.
"""

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .providers import (
    Attempt,
    GeminiProvider,
    GroqProvider,
    OpenAICompatProvider,
    build_default_chain,
)
from .telemetry import LLMCallRecord, current_telemetry

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

# Re-exported for callers that still reference these names.
DEFAULT_PRIMARY_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.5-flash-lite"
DEFAULT_FALLBACK_MODEL = os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b"

_RATE_LIMIT_MARKERS = (
    "429", "rate limit", "rate_limit", "resource_exhausted",
    "quota", "too many requests",
)

# Failures that will repeat identically on the same provider no matter how many
# times we ask. Retrying a revoked key just adds latency to a doomed call, so we
# skip that provider's remaining attempts and move to the next vendor.
_PERMANENT_PROVIDER_MARKERS = (
    "401", "403", "permission_denied", "unauthenticated", "unauthorized",
    "api key not valid", "api_key_invalid", "was reported as leaked",
    "invalid_api_key", "is not set",
)


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _RATE_LIMIT_MARKERS)


def _is_permanent_provider_error(exc: Exception) -> bool:
    """True for auth/credential failures — fatal for this provider, not the run."""
    msg = str(exc).lower()
    if any(marker in msg for marker in _RATE_LIMIT_MARKERS):
        return False  # 429 is transient even though it is a 4xx
    return any(marker in msg for marker in _PERMANENT_PROVIDER_MARKERS)


def _extract_token_counts(response) -> tuple[int, int]:
    """Best-effort extraction of usage stats from an OpenAI-shaped response."""
    try:
        usage = response.usage
        return int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)
    except (AttributeError, TypeError):
        return 0, 0


def _is_schema_rejection(exc: Exception) -> bool:
    """True when a vendor refused the structured-output schema itself."""
    msg = str(exc).lower()
    return (
        "response_schema" in msg
        or "responseschema" in msg
        or ("schema" in msg and ("invalid" in msg or "unsupported" in msg or "400" in msg))
    )


def _looks_like_openai_client(obj) -> bool:
    """True for AsyncGroq / OpenAI / any test double exposing chat.completions.create."""
    return hasattr(getattr(getattr(obj, "chat", None), "completions", None), "create")


def _resolve_chain(
    client,
    primary_model: Optional[str],
    fallback_model: Optional[str],
) -> List[Attempt]:
    """Normalise whatever the caller passed as `client` into an attempt chain.

    Accepts, in order of preference:
      - None                    → the configured Gemini→Groq chain
      - a list of `Attempt`     → used as-is (callers that build their own)
      - an OpenAI-shaped client → single-provider chain, primary then fallback
                                  model. This is the path tests take when they
                                  inject a fake client.
    """
    if isinstance(client, list) and all(isinstance(a, Attempt) for a in client):
        return list(client)

    if client is not None and _looks_like_openai_client(client):
        provider = OpenAICompatProvider(client, name=getattr(client, "_provider_name", "openai_compat"))
        # Single-provider chain: try its primary model, then its cheaper
        # fallback model. Mirrors the pre-Gemini behaviour for injected clients.
        models = [
            primary_model or os.environ.get("GROQ_MODEL") or "openai/gpt-oss-120b",
            fallback_model or os.environ.get("GROQ_FALLBACK_MODEL") or "openai/gpt-oss-20b",
        ]
        return [Attempt(provider, m) for m in dict.fromkeys(models)]

    chain = build_default_chain()
    if primary_model and chain:
        # Caller pinned a model: honour it on the first tier only.
        chain = [Attempt(chain[0].provider, primary_model)] + chain[1:]
    return chain


async def call_llm(
    client=None,
    messages: Optional[List[Dict[str, Any]]] = None,
    *,
    agent: str = "unknown",
    response_format: Optional[Dict[str, Any]] = None,
    primary_model: Optional[str] = None,
    fallback_model: Optional[str] = None,
    temperature: float = 0.1,
    max_output_tokens: Optional[int] = None,
    response_schema: Optional[Any] = None,
) -> str:
    """Single entry point for LLM calls.

    Records telemetry for every attempt — successes and failures alike — so the
    run log shows which provider actually answered and what the retries cost.
    `fallback_used` is True on any attempt after the first.
    """
    messages = messages or []
    json_mode = (response_format or {}).get("type", "json_object") == "json_object"

    chain = _resolve_chain(client, primary_model, fallback_model)
    if not chain:
        raise ValueError(
            "No LLM provider configured. Set GOOGLE_API_KEY (Gemini, primary) "
            "and/or GROQ_API_KEY (Groq, fallback)."
        )

    telemetry = current_telemetry()
    last_error: Optional[Exception] = None
    dead_providers: set = set()

    for index, attempt in enumerate(chain):
        if id(attempt.provider) in dead_providers:
            continue
        started = time.monotonic()
        started_at_ist = datetime.now(IST).isoformat()
        try:
            result = await attempt.provider.complete(
                messages,
                model=attempt.model,
                temperature=temperature,
                json_mode=json_mode,
                max_output_tokens=max_output_tokens,
                response_schema=response_schema,
            )
            if telemetry is not None:
                telemetry.record(LLMCallRecord(
                    agent=agent,
                    model=attempt.model,
                    provider=attempt.provider.name,
                    started_at=started_at_ist,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    total_tokens=result.total_tokens,
                    success=True,
                    fallback_used=index > 0,
                    attempt=index + 1,
                ))
            if index > 0:
                logger.info(
                    f"[llm.router] {agent}: recovered on fallback attempt "
                    f"{index + 1}/{len(chain)} ({attempt})"
                )
            return result.text
        except Exception as exc:
            if response_schema is not None and _is_schema_rejection(exc):
                # The vendor dislikes this schema. Plain JSON mode still gets a
                # usable answer, and the caller validates either way — better
                # than burning the attempt.
                logger.warning(
                    f"[llm.router] {agent}: {attempt} rejected the response schema "
                    f"({str(exc)[:100]}); retrying this attempt without it"
                )
                try:
                    result = await attempt.provider.complete(
                        messages,
                        model=attempt.model,
                        temperature=temperature,
                        json_mode=json_mode,
                        max_output_tokens=max_output_tokens,
                    )
                    if telemetry is not None:
                        telemetry.record(LLMCallRecord(
                            agent=agent,
                            model=attempt.model,
                            provider=attempt.provider.name,
                            started_at=started_at_ist,
                            duration_ms=int((time.monotonic() - started) * 1000),
                            prompt_tokens=result.prompt_tokens,
                            completion_tokens=result.completion_tokens,
                            total_tokens=result.total_tokens,
                            success=True,
                            fallback_used=index > 0,
                            attempt=index + 1,
                        ))
                    return result.text
                except Exception as retry_exc:
                    exc = retry_exc

            last_error = exc
            if telemetry is not None:
                telemetry.record(LLMCallRecord(
                    agent=agent,
                    model=attempt.model,
                    provider=attempt.provider.name,
                    started_at=started_at_ist,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    success=False,
                    error=str(exc)[:200],
                    fallback_used=index > 0,
                    attempt=index + 1,
                ))

            if _is_permanent_provider_error(exc):
                # Credentials are bad — skip this provider's remaining attempts.
                dead_providers.add(id(attempt.provider))
                logger.warning(
                    f"[llm.router] {agent}: {attempt.provider.name} credentials rejected "
                    f"({str(exc)[:120]}); skipping its remaining attempts"
                )

            remaining = [
                a for a in chain[index + 1:] if id(a.provider) not in dead_providers
            ]
            if not remaining:
                break

            if _is_rate_limit_error(exc):
                # Transient — a short, jittered wait is worth it before the next tier.
                delay = random.uniform(3.0, 7.0)
                logger.warning(
                    f"[llm.router] {agent}: rate limited on {attempt}; "
                    f"retrying after {delay:.1f}s → {remaining[0]}"
                )
                await asyncio.sleep(delay)
            elif not _is_permanent_provider_error(exc):
                # 404 / 5xx / empty response — waiting changes nothing.
                logger.warning(
                    f"[llm.router] {agent}: {attempt} failed ({str(exc)[:120]}); "
                    f"failing over to {remaining[0]}"
                )

    logger.error(f"[llm.router] {agent}: all {len(chain)} attempts failed. Last error: {last_error}")
    raise last_error  # type: ignore[misc]
