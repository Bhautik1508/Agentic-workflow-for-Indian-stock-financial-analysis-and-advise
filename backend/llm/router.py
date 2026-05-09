"""Routing for LLM calls. Groq primary; OpenAI fallback hook (disabled until
configured). Wraps every call with telemetry recording + retry logic.

Why a thin router instead of using groq directly:
- Single chokepoint to record latency / token spend
- Single chokepoint to add a non-Groq fallback later (Phase 6)
- Keeps `call_llm_with_retry` from growing into a 200-line monster"""

import asyncio
import logging
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .telemetry import LLMCallRecord, current_telemetry

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_PRIMARY_MODEL = "llama-3.3-70b-versatile"
DEFAULT_FALLBACK_MODEL = "llama-3.1-8b-instant"


def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "tokens" in msg


def _extract_token_counts(response) -> tuple[int, int]:
    """Best-effort extraction of usage stats from a Groq/OpenAI-shaped response."""
    try:
        usage = response.usage
        return int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)
    except (AttributeError, TypeError):
        return 0, 0


async def call_llm(
    client,
    messages: List[Dict[str, Any]],
    *,
    agent: str = "unknown",
    response_format: Optional[Dict[str, Any]] = None,
    primary_model: str = DEFAULT_PRIMARY_MODEL,
    fallback_model: str = DEFAULT_FALLBACK_MODEL,
    temperature: float = 0.1,
) -> str:
    """Single entry point for LLM calls. Records telemetry whether or not the
    call ultimately succeeds, and bumps `fallback_used=True` when we had to
    fail over to the smaller model."""
    response_format = response_format or {"type": "json_object"}
    telemetry = current_telemetry()

    started = time.monotonic()
    started_at_ist = datetime.now(IST).isoformat()
    fallback_used = False
    last_error: Optional[Exception] = None

    # ── Primary attempt ──
    try:
        response = await client.chat.completions.create(
            model=primary_model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )
        text = response.choices[0].message.content.strip()
        prompt_tokens, completion_tokens = _extract_token_counts(response)
        if telemetry is not None:
            telemetry.record(LLMCallRecord(
                agent=agent,
                model=primary_model,
                started_at=started_at_ist,
                duration_ms=int((time.monotonic() - started) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                success=True,
                fallback_used=False,
            ))
        return text
    except Exception as e:
        last_error = e
        if not _is_rate_limit_error(e):
            # Non-rate-limit failure — record and re-raise immediately
            if telemetry is not None:
                telemetry.record(LLMCallRecord(
                    agent=agent,
                    model=primary_model,
                    started_at=started_at_ist,
                    duration_ms=int((time.monotonic() - started) * 1000),
                    prompt_tokens=0,
                    completion_tokens=0,
                    total_tokens=0,
                    success=False,
                    error=str(e)[:200],
                ))
            raise

    # ── Fallback attempt — primary 429'd ──
    fallback_used = True
    delay = random.uniform(3.0, 7.0)
    logger.warning(f"[llm.router] Rate limit on {primary_model}; falling back to {fallback_model} after {delay:.1f}s")
    await asyncio.sleep(delay)
    fb_started = time.monotonic()
    fb_started_at_ist = datetime.now(IST).isoformat()
    try:
        response = await client.chat.completions.create(
            model=fallback_model,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
        )
        text = response.choices[0].message.content.strip()
        prompt_tokens, completion_tokens = _extract_token_counts(response)
        if telemetry is not None:
            telemetry.record(LLMCallRecord(
                agent=agent,
                model=fallback_model,
                started_at=fb_started_at_ist,
                duration_ms=int((time.monotonic() - fb_started) * 1000),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                success=True,
                fallback_used=True,
            ))
        return text
    except Exception as e2:
        # Last-chance retry on the fallback after a longer cooldown
        if _is_rate_limit_error(e2):
            cooldown = random.uniform(10.0, 20.0)
            logger.warning(f"[llm.router] Rate limit on fallback {fallback_model}; cooling down {cooldown:.1f}s")
            await asyncio.sleep(cooldown)
            try:
                response = await client.chat.completions.create(
                    model=fallback_model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format,
                )
                text = response.choices[0].message.content.strip()
                prompt_tokens, completion_tokens = _extract_token_counts(response)
                if telemetry is not None:
                    telemetry.record(LLMCallRecord(
                        agent=agent,
                        model=fallback_model,
                        started_at=fb_started_at_ist,
                        duration_ms=int((time.monotonic() - fb_started) * 1000),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                        success=True,
                        fallback_used=True,
                    ))
                return text
            except Exception as e3:
                last_error = e3
        else:
            last_error = e2

        if telemetry is not None:
            telemetry.record(LLMCallRecord(
                agent=agent,
                model=fallback_model,
                started_at=fb_started_at_ist,
                duration_ms=int((time.monotonic() - fb_started) * 1000),
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                success=False,
                error=str(last_error)[:200] if last_error else "unknown",
                fallback_used=True,
            ))
        raise last_error  # type: ignore[misc]
