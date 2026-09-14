"""Tests for the Gemini-primary / Groq-fallback provider layer.

Covers the three things that actually bite in production:
  1. chain ORDER and what happens when a key is missing
  2. Gemini's message translation (system prompt is out-of-band there)
  3. cross-provider failover + the telemetry that proves which vendor answered
"""

import asyncio
from typing import Any, Dict, List

import pytest

from llm import (
    Attempt,
    CompletionResult,
    LLMTelemetry,
    call_llm,
    current_telemetry,
    reset_current_telemetry,
    set_current_telemetry,
)
from llm.providers import (
    GeminiProvider,
    GroqProvider,
    OpenAICompatProvider,
    _gemini_text,
    _gemini_usage,
    _split_system,
    build_default_chain,
)


# ─────────────────────────────────────────────────────────────────────────────
# Chain construction
# ─────────────────────────────────────────────────────────────────────────────

def test_chain_puts_gemini_first_by_default(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    monkeypatch.delenv("LLM_PRIMARY_PROVIDER", raising=False)
    monkeypatch.delenv("GEMINI_RETRIES", raising=False)

    chain = build_default_chain()
    assert [a.provider.name for a in chain][:2] == ["gemini", "gemini"]  # 1 call + 1 retry
    assert [a.provider.name for a in chain][-2:] == ["groq", "groq"]
    assert chain[0].model.startswith("gemini")


def test_primary_provider_env_flips_the_order(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "groq")

    chain = build_default_chain()
    assert chain[0].provider.name == "groq"
    assert chain[-1].provider.name == "gemini"


def test_chain_skips_unconfigured_providers(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "q")
    chain = build_default_chain()
    assert chain, "Groq alone should still produce a usable chain"
    assert {a.provider.name for a in chain} == {"groq"}


def test_chain_is_empty_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert build_default_chain() == []


def test_gemini_retries_env_controls_attempt_count(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_RETRIES", "3")
    assert len(build_default_chain()) == 4  # 1 initial + 3 retries


def test_groq_models_are_not_the_retired_llama_ids(monkeypatch):
    """Regression guard: llama-3.3-70b-versatile / llama-3.1-8b-instant were
    decommissioned by Groq and 404 on every call."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "q")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    monkeypatch.delenv("GROQ_FALLBACK_MODEL", raising=False)
    models = [a.model for a in build_default_chain()]
    assert not any("llama-3.3-70b-versatile" == m or "llama-3.1-8b-instant" == m for m in models)


# ─────────────────────────────────────────────────────────────────────────────
# Gemini message translation + response handling
# ─────────────────────────────────────────────────────────────────────────────

def test_split_system_pulls_system_messages_out():
    system, rest = _split_system([
        {"role": "system", "content": "You are a CIO."},
        {"role": "user", "content": "Analyse TCS"},
    ])
    assert system == "You are a CIO."
    assert len(rest) == 1 and rest[0]["role"] == "user"


def test_split_system_joins_multiple_system_messages():
    system, rest = _split_system([
        {"role": "system", "content": "A"},
        {"role": "system", "content": "B"},
        {"role": "user", "content": "hi"},
    ])
    assert system == "A\n\nB"
    assert len(rest) == 1


class _FakeGeminiUsage:
    prompt_token_count = 1200
    candidates_token_count = 300
    thoughts_token_count = 50


class _FakeGeminiResponse:
    text = '  {"score": 7.5}  '
    usage_metadata = _FakeGeminiUsage()


class _FakeGeminiModels:
    def __init__(self, response=None, error=None):
        self.response = response or _FakeGeminiResponse()
        self.error = error
        self.captured: Dict[str, Any] = {}

    async def generate_content(self, *, model, contents, config):
        self.captured = {"model": model, "contents": contents, "config": config}
        if self.error:
            raise self.error
        return self.response


class _FakeGeminiClient:
    def __init__(self, models):
        self.aio = type("aio", (), {"models": models})()


@pytest.mark.asyncio
async def test_gemini_provider_translates_messages_and_counts_tokens():
    models = _FakeGeminiModels()
    provider = GeminiProvider(api_key="k")
    provider._client = _FakeGeminiClient(models)

    result = await provider.complete(
        [
            {"role": "system", "content": "You are a CIO."},
            {"role": "user", "content": "Analyse TCS"},
        ],
        model="gemini-2.5-flash",
        temperature=0.1,
        json_mode=True,
    )

    assert result.text == '{"score": 7.5}'
    # Thinking tokens are billed as output, so they belong in completion_tokens.
    assert result.prompt_tokens == 1200
    assert result.completion_tokens == 350
    assert result.total_tokens == 1550

    cfg = models.captured["config"]
    assert cfg.system_instruction == "You are a CIO."
    assert cfg.response_mime_type == "application/json"
    # Only the non-system message becomes a Content entry.
    assert len(models.captured["contents"]) == 1
    assert models.captured["contents"][0].role == "user"


@pytest.mark.asyncio
async def test_gemini_provider_maps_assistant_role_to_model():
    models = _FakeGeminiModels()
    provider = GeminiProvider(api_key="k")
    provider._client = _FakeGeminiClient(models)
    await provider.complete(
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        model="gemini-2.5-flash",
    )
    assert [c.role for c in models.captured["contents"]] == ["user", "model"]


def test_gemini_empty_response_raises_rather_than_returning_blank():
    """A blocked/truncated Gemini response must raise so the router fails over,
    instead of returning '' and surfacing as a bogus JSON parse error."""
    class _Blocked:
        text = None
        candidates = []
        prompt_feedback = "SAFETY"

    with pytest.raises(RuntimeError, match="no text"):
        _gemini_text(_Blocked())


def test_gemini_usage_is_zero_when_metadata_missing():
    class _NoUsage:
        pass
    assert _gemini_usage(_NoUsage()) == (0, 0)


def test_gemini_provider_is_unconfigured_without_key():
    assert GeminiProvider(api_key="").is_configured() is False
    assert GeminiProvider(api_key="k").is_configured() is True


# ─────────────────────────────────────────────────────────────────────────────
# Cross-provider failover through the router
# ─────────────────────────────────────────────────────────────────────────────

class _StubProvider:
    """Provider double that fails a configured number of times, then succeeds."""

    def __init__(self, name, *, fail_times=0, error=None):
        self.name = name
        self.fail_times = fail_times
        self.error = error or RuntimeError("boom")
        self.calls: List[str] = []

    def is_configured(self):
        return True

    async def complete(self, messages, *, model, temperature=0.1, json_mode=True, max_output_tokens=None):
        self.calls.append(model)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise self.error
        return CompletionResult(text='{"ok": true}', prompt_tokens=10, completion_tokens=5)


@pytest.mark.asyncio
async def test_router_fails_over_from_gemini_to_groq(monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr("llm.router.asyncio.sleep", no_sleep)

    gemini = _StubProvider("gemini", fail_times=2, error=RuntimeError("503 unavailable"))
    groq = _StubProvider("groq")
    chain = [
        Attempt(gemini, "gemini-2.5-flash"),
        Attempt(gemini, "gemini-2.5-flash"),
        Attempt(groq, "openai/gpt-oss-120b"),
    ]

    t = LLMTelemetry()
    token = set_current_telemetry(t)
    try:
        text = await call_llm(chain, [{"role": "user", "content": "hi"}], agent="Judge Analyst")
    finally:
        reset_current_telemetry(token)

    assert text == '{"ok": true}'
    assert len(gemini.calls) == 2 and len(groq.calls) == 1

    providers_seen = [r.provider for r in t.records]
    assert providers_seen == ["gemini", "gemini", "groq"]
    assert t.records[-1].success is True
    assert t.records[-1].provider == "groq"
    assert t.failed_calls() == 2

    rollup = t.by_provider()
    assert rollup["gemini"]["failures"] == 2
    assert rollup["groq"]["successes"] == 1
    # First attempt failed, so the primary-tier success rate must reflect that.
    assert t.primary_provider_success_rate() == 0.0


@pytest.mark.asyncio
async def test_router_returns_gemini_result_without_touching_groq():
    gemini = _StubProvider("gemini")
    groq = _StubProvider("groq")
    chain = [Attempt(gemini, "gemini-2.5-flash"), Attempt(groq, "openai/gpt-oss-120b")]

    t = LLMTelemetry()
    token = set_current_telemetry(t)
    try:
        text = await call_llm(chain, [{"role": "user", "content": "hi"}], agent="Risk Analyst")
    finally:
        reset_current_telemetry(token)

    assert text == '{"ok": true}'
    assert groq.calls == [], "Groq must not be called when Gemini succeeds"
    assert t.total_calls() == 1
    assert t.records[0].provider == "gemini"
    assert t.records[0].fallback_used is False
    assert t.primary_provider_success_rate() == 1.0


@pytest.mark.asyncio
async def test_rate_limit_sleeps_between_attempts_but_other_errors_do_not(monkeypatch):
    """Backoff is for 429s. Waiting out a 404 just adds latency to a dead call."""
    slept: List[float] = []

    async def record_sleep(d):
        slept.append(d)

    monkeypatch.setattr("llm.router.asyncio.sleep", record_sleep)

    rate_limited = _StubProvider("gemini", fail_times=1, error=RuntimeError("429 rate limit"))
    ok = _StubProvider("groq")
    await call_llm([Attempt(rate_limited, "m1"), Attempt(ok, "m2")], [{"role": "user", "content": "x"}])
    assert len(slept) == 1

    slept.clear()
    not_found = _StubProvider("gemini", fail_times=1, error=RuntimeError("404 model not found"))
    ok2 = _StubProvider("groq")
    await call_llm([Attempt(not_found, "m1"), Attempt(ok2, "m2")], [{"role": "user", "content": "x"}])
    assert slept == []


@pytest.mark.asyncio
async def test_get_llm_returns_a_chain_not_a_vendor_client(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    from agents.base_agent import get_llm

    chain = get_llm()
    assert isinstance(chain, list)
    assert all(isinstance(a, Attempt) for a in chain)
    assert chain[0].provider.name == "gemini"


@pytest.mark.asyncio
async def test_revoked_key_skips_that_providers_remaining_attempts():
    """A 403/401 will repeat identically, so the second Gemini attempt is pure
    wasted latency. The router must jump straight to the next vendor."""
    gemini = _StubProvider(
        "gemini",
        fail_times=99,
        error=RuntimeError("403 PERMISSION_DENIED. Your API key was reported as leaked."),
    )
    groq = _StubProvider("groq")
    chain = [
        Attempt(gemini, "gemini-2.5-flash"),
        Attempt(gemini, "gemini-2.5-flash"),   # must be skipped
        Attempt(groq, "openai/gpt-oss-120b"),
    ]

    t = LLMTelemetry()
    token = set_current_telemetry(t)
    try:
        text = await call_llm(chain, [{"role": "user", "content": "hi"}], agent="Test")
    finally:
        reset_current_telemetry(token)

    assert text == '{"ok": true}'
    assert len(gemini.calls) == 1, "Gemini must be tried once, not twice, on a dead key"
    assert [r.provider for r in t.records] == ["gemini", "groq"]


@pytest.mark.asyncio
async def test_all_providers_dead_raises_last_error():
    gemini = _StubProvider("gemini", fail_times=99, error=RuntimeError("403 unauthorized"))
    groq = _StubProvider("groq", fail_times=99, error=RuntimeError("401 invalid_api_key"))
    chain = [Attempt(gemini, "m"), Attempt(gemini, "m"), Attempt(groq, "n"), Attempt(groq, "n2")]

    with pytest.raises(RuntimeError):
        await call_llm(chain, [{"role": "user", "content": "hi"}], agent="Test")

    # One attempt per provider — the duplicates are skipped once creds are rejected.
    assert len(gemini.calls) == 1
    assert len(groq.calls) == 1


@pytest.mark.asyncio
async def test_rate_limit_is_not_treated_as_permanent(monkeypatch):
    """429 is a 4xx but transient — the same provider must still get its retry."""
    async def no_sleep(_):
        return None
    monkeypatch.setattr("llm.router.asyncio.sleep", no_sleep)

    gemini = _StubProvider("gemini", fail_times=1, error=RuntimeError("429 rate limit exceeded"))
    chain = [Attempt(gemini, "gemini-2.5-flash"), Attempt(gemini, "gemini-2.5-flash")]
    text = await call_llm(chain, [{"role": "user", "content": "hi"}], agent="Test")
    assert text == '{"ok": true}'
    assert len(gemini.calls) == 2
