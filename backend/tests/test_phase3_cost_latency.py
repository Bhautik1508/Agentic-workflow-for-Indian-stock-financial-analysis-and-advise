"""Phase 3 — cost accounting and latency percentiles."""

import pytest

from llm import pricing
from llm.telemetry import LLMCallRecord, LLMTelemetry


def _record(agent="A", model="m", ms=1000, pt=1000, ct=500, success=True, provider="gemini"):
    return LLMCallRecord(
        agent=agent, model=model, started_at="", duration_ms=ms,
        prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct,
        success=success, provider=provider,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Pricing
# ─────────────────────────────────────────────────────────────────────────────

def test_unpriced_model_reports_none_not_zero(monkeypatch):
    """A fabricated $0.00 reads as "this run was free". None reads as unknown,
    which is the truth when no rate is configured."""
    monkeypatch.delenv("LLM_PRICING_JSON", raising=False)
    monkeypatch.setattr(pricing, "DEFAULT_PRICING", {}, raising=False)
    assert pricing.estimate_cost("gemini-3.6-flash", 1000, 500) is None
    assert pricing.is_configured() is False


def test_env_pricing_is_applied(monkeypatch):
    monkeypatch.setenv("LLM_PRICING_JSON", '{"m":{"input":1.0,"output":2.0}}')
    # 1M in @ $1 + 1M out @ $2
    assert pricing.estimate_cost("m", 1_000_000, 1_000_000) == 3.0
    assert pricing.is_configured() is True


def test_pricing_prefix_match(monkeypatch):
    monkeypatch.setenv("LLM_PRICING_JSON", '{"gemini-3.6-flash":{"input":0.3,"output":2.5}}')
    assert pricing.estimate_cost("gemini-3.6-flash-preview-11", 1_000_000, 0) == 0.3


def test_pricing_prefers_the_longest_prefix(monkeypatch):
    monkeypatch.setenv(
        "LLM_PRICING_JSON",
        '{"gemini":{"input":9.0,"output":9.0},"gemini-3.6":{"input":1.0,"output":1.0}}',
    )
    assert pricing.estimate_cost("gemini-3.6-flash", 1_000_000, 0) == 1.0


def test_malformed_pricing_json_is_ignored_not_fatal(monkeypatch):
    monkeypatch.setenv("LLM_PRICING_JSON", "definitely not json")
    monkeypatch.setattr(pricing, "DEFAULT_PRICING", {}, raising=False)
    assert pricing.estimate_cost("m", 10, 10) is None


def test_malformed_entry_is_skipped_but_others_survive(monkeypatch):
    monkeypatch.setenv(
        "LLM_PRICING_JSON",
        '{"bad":{"input":"free"},"good":{"input":1.0,"output":1.0}}',
    )
    assert pricing.estimate_cost("bad", 1_000_000, 0) is None
    assert pricing.estimate_cost("good", 1_000_000, 0) == 1.0


def test_case_insensitive_model_match(monkeypatch):
    monkeypatch.setenv("LLM_PRICING_JSON", '{"Gemini-3.6-Flash":{"input":1.0,"output":1.0}}')
    assert pricing.estimate_cost("gemini-3.6-flash", 1_000_000, 0) == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry: cost
# ─────────────────────────────────────────────────────────────────────────────

def test_run_cost_sums_across_calls(monkeypatch):
    monkeypatch.setenv("LLM_PRICING_JSON", '{"m":{"input":1.0,"output":2.0}}')
    t = LLMTelemetry()
    for _ in range(3):
        t.record(_record(pt=1_000_000, ct=0))
    assert t.total_cost_usd() == 3.0
    assert t.unpriced_calls() == 0


def test_unpriced_run_reports_none_and_counts_calls(monkeypatch):
    monkeypatch.delenv("LLM_PRICING_JSON", raising=False)
    monkeypatch.setattr(pricing, "DEFAULT_PRICING", {}, raising=False)
    t = LLMTelemetry()
    t.record(_record())
    data = t.to_dict()
    assert data["estimated_cost_usd"] is None
    assert data["pricing_configured"] is False
    assert data["unpriced_calls"] == 1


def test_cost_is_attributed_per_provider(monkeypatch):
    monkeypatch.setenv("LLM_PRICING_JSON", '{"m":{"input":1.0,"output":0.0}}')
    t = LLMTelemetry()
    t.record(_record(provider="gemini", pt=1_000_000, ct=0))
    t.record(_record(provider="groq", pt=2_000_000, ct=0))
    rollup = t.by_provider()
    assert rollup["gemini"]["cost_usd"] == 1.0
    assert rollup["groq"]["cost_usd"] == 2.0


def test_failed_calls_cost_nothing(monkeypatch):
    """A failed call records zero tokens, so it must not inflate the bill."""
    monkeypatch.setenv("LLM_PRICING_JSON", '{"m":{"input":1.0,"output":1.0}}')
    t = LLMTelemetry()
    t.record(_record(success=False, pt=0, ct=0))
    assert t.total_cost_usd() == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry: latency
# ─────────────────────────────────────────────────────────────────────────────

def test_latency_percentiles():
    t = LLMTelemetry()
    for ms in (1000, 2000, 3000, 4000, 5000):
        t.record(_record(ms=ms))
    overall = t.latency()["overall"]
    assert overall["p50"] == 3000
    assert overall["max"] == 5000
    assert overall["p95"] >= overall["p50"]


def test_latency_is_broken_out_per_agent():
    """The judge runs after all five analysts, so it sits on the critical path
    and is worth watching separately from the fan-out."""
    t = LLMTelemetry()
    t.record(_record(agent="Financial Analyst", ms=1000))
    t.record(_record(agent="Judge Analyst", ms=9000))
    by_agent = t.latency()["by_agent"]
    assert by_agent["Judge Analyst"]["p50"] == 9000
    assert by_agent["Financial Analyst"]["p50"] == 1000
    assert by_agent["Judge Analyst"]["calls"] == 1


def test_latency_handles_an_empty_run():
    assert LLMTelemetry().latency()["overall"] == {"p50": 0, "p95": 0, "max": 0}


def test_to_dict_exposes_everything_the_ui_strip_needs():
    t = LLMTelemetry()
    t.record(_record())
    data = t.to_dict()
    for key in ("total_calls", "total_tokens", "fallback_calls", "failed_calls",
                "estimated_cost_usd", "pricing_configured", "unpriced_calls",
                "primary_success_rate", "by_provider", "latency", "records"):
        assert key in data, f"telemetry payload is missing {key}"
    assert "estimated_cost_usd" in data["records"][0]


def test_analyst_concurrency_allows_full_fan_out():
    """Measured: at 5 the LLM phase ran 9.9s -> 7.6s with zero failures, because
    all five analysts go out together instead of queueing behind a 3-slot gate."""
    import graph.workflow as wf
    assert wf.ANALYST_CONCURRENCY >= 5
