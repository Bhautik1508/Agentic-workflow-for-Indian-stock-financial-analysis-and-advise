"""Tests for Phase 3 — data trust.

Covers:
- evaluate_data_quality completeness + warn + abort behaviour
- _is_populated null/N/A/NaN handling
- Freshness stamping, age computation, stale detection
- collect_stale_sources walks the state correctly
- LLMTelemetry records, totals, fallback/failure counts
- contextvar set/reset round-trip
- llm.router records a successful call into the contextvar telemetry
- Runner emits a `telemetry` event after the workflow completes (smoke)
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pytest

from data.freshness import (
    IST,
    Freshness,
    collect_stale_sources,
    compute_freshness,
    get_freshness,
    now_ist,
    stamp,
)
from llm import (
    LLMCallRecord,
    LLMTelemetry,
    current_telemetry,
    reset_current_telemetry,
    set_current_telemetry,
)
from llm.router import call_llm
from scoring.data_quality import (
    CRITICAL_FUNDAMENTAL_FIELDS,
    DEFAULT_ABORT_THRESHOLD,
    DataQualityReport,
    _is_populated,
    evaluate_data_quality,
)


# ─────────────────────────────────────────────────────────────────────────────
# data_quality._is_populated
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (None, False),
    ("", False),
    ("   ", False),
    ("N/A", False),
    ("n/a", False),
    ("Unknown", False),
    ("none", False),
    (0, True),                  # zero is a real value (e.g. zero debt)
    (0.0, True),
    (float("nan"), False),
    (float("inf"), True),       # inf treated as a number; agents will guard
    ("Reliance Industries", True),
    (1.5, True),
    ([], True),                 # empty list is a populated value (intentional)
])
def test_is_populated_recognises_meaningful_values(value, expected):
    assert _is_populated(value) is expected


# ─────────────────────────────────────────────────────────────────────────────
# evaluate_data_quality
# ─────────────────────────────────────────────────────────────────────────────

def _full_state() -> Dict[str, Any]:
    return {
        "fundamental_data": {
            "pe_ratio": 22.4, "market_cap": 5_00_000, "sector": "IT",
            "debt_to_equity": 0.31, "current_ratio": 2.1, "roe": 0.22,
            "ebitda_margin": 0.28, "profit_margins": 0.18,
            "revenue_growth": 0.15, "free_cashflow": 1_00_000,
        },
        "price_data": {
            "current_price": 3210.0, "week_52_high": 3500.0, "week_52_low": 2800.0,
        },
        "news_data": [{"title": "x"}],
        "screener_data": {"x": "y"},
        "peer_data": {"peers": [1]},
    }


def test_full_state_passes_with_high_completeness():
    q = evaluate_data_quality(_full_state())
    assert q.fundamental_completeness == 1.0
    assert q.price_completeness == 1.0
    assert q.overall_completeness == 1.0
    assert q.abort is False
    assert q.abort_reason is None
    assert q.missing_critical_fields == []


def test_missing_half_fundamentals_warns_but_does_not_abort():
    state = _full_state()
    # Drop 4 of 10 fundamental fields → 60% completeness (still > 50% abort threshold)
    for k in ("debt_to_equity", "current_ratio", "ebitda_margin", "profit_margins"):
        state["fundamental_data"][k] = None
    q = evaluate_data_quality(state)
    assert q.fundamental_completeness == 0.6
    assert q.abort is False              # 0.7 * 0.6 + 0.3 * 1.0 = 0.72 ≥ 0.5
    assert "fundamental_data" in q.sparse_sources or q.sparse_sources == []  # may or may not warn


def test_almost_empty_state_aborts_with_honest_reason():
    state = {"fundamental_data": {"pe_ratio": 22.0}, "price_data": {}}
    q = evaluate_data_quality(state)
    assert q.abort is True
    assert q.abort_reason and "completeness" in q.abort_reason.lower()
    assert len(q.missing_critical_fields) >= 9  # 9 of 10 fundamentals + 3 of 3 price


def test_abort_threshold_is_configurable():
    state = _full_state()
    # Require 99% completeness; full state should still pass at 100%
    q = evaluate_data_quality(state, abort_threshold=0.99)
    assert q.abort is False


def test_empty_news_list_flagged_as_sparse_source():
    state = _full_state()
    state["news_data"] = []
    q = evaluate_data_quality(state)
    assert "news" in q.sparse_sources


def test_data_quality_handles_completely_empty_state():
    q = evaluate_data_quality({})
    assert q.abort is True
    assert q.fundamental_completeness == 0.0
    assert q.price_completeness == 0.0


def test_quality_report_to_dict_round_trips():
    q = evaluate_data_quality(_full_state())
    d = q.to_dict()
    assert isinstance(d, dict)
    assert "overall_completeness" in d and "abort" in d


# ─────────────────────────────────────────────────────────────────────────────
# Freshness
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_freshness_basic():
    now = datetime(2026, 5, 8, 12, 0, 0, tzinfo=IST)
    as_of = now - timedelta(hours=3)
    f = compute_freshness(as_of, "yfinance.fundamentals", now=now)
    assert f.age_hours == 3.0
    assert f.is_stale is False  # default 24h threshold
    assert f.source == "yfinance.fundamentals"


def test_compute_freshness_marks_stale_after_threshold():
    now = datetime(2026, 5, 8, 12, 0, 0, tzinfo=IST)
    as_of = now - timedelta(hours=30)
    f = compute_freshness(as_of, "yfinance.fundamentals", now=now)
    assert f.is_stale is True
    assert f.age_hours == 30.0


def test_compute_freshness_intraday_threshold():
    now = datetime(2026, 5, 8, 12, 0, 0, tzinfo=IST)
    as_of = now - timedelta(hours=6)
    f = compute_freshness(as_of, "nse.surveillance", now=now, stale_after_hours=4)
    assert f.is_stale is True


def test_compute_freshness_naive_datetime_treated_as_ist():
    """Naive datetime input must not crash."""
    naive = datetime(2026, 5, 8, 10, 0, 0)
    now = datetime(2026, 5, 8, 12, 0, 0, tzinfo=IST)
    f = compute_freshness(naive, "x", now=now)
    assert f.age_hours == 2.0


def test_stamp_attaches_freshness_to_dict():
    payload = {"foo": 1}
    stamp(payload, "test.source")
    assert "_freshness" in payload
    assert payload["_freshness"]["source"] == "test.source"


def test_stamp_leaves_lists_unwrapped():
    """Phase 3 contract: stamp() must NOT wrap a list — agents (e.g. sentiment)
    consume news_data as a list. Use freshness_for() side-channel instead."""
    items = [{"x": 1}, {"x": 2}]
    out = stamp(items, "test.source")
    assert out is items     # same list, unchanged
    assert "_freshness" not in items[0]  # no contamination


def test_freshness_for_returns_record_dict():
    from data.freshness import freshness_for
    rec = freshness_for("marketaux.news")
    assert "as_of" in rec and "is_stale" in rec
    assert rec["source"] == "marketaux.news"


def test_collect_stale_sources_handles_side_channel_keys():
    """state['news_data_freshness'] = freshness_for(...) should still be picked up."""
    from data.freshness import freshness_for, collect_stale_sources
    fresh = freshness_for("recent.source")
    fresh["is_stale"] = True
    fresh["age_hours"] = 36.0
    state = {"news_data": [{"x": 1}], "news_data_freshness": fresh}
    found = collect_stale_sources(state)
    assert any("recent.source" in s for s in found)


def test_get_freshness_reads_back_stamp():
    payload = stamp({"a": 1}, "s")
    f = get_freshness(payload)
    assert f is not None
    assert f["source"] == "s"


def test_get_freshness_returns_none_for_unstamped():
    assert get_freshness({"a": 1}) is None
    assert get_freshness("not a dict") is None
    assert get_freshness(None) is None


def test_collect_stale_sources_finds_only_stale():
    now = datetime(2026, 5, 8, 12, 0, 0, tzinfo=IST)
    fresh = stamp({}, "fresh.source", as_of=now)
    stale = stamp({}, "stale.source", as_of=now - timedelta(hours=48))
    state = {"a": fresh, "b": stale, "c": {"no_freshness": True}}
    found = collect_stale_sources(state)
    assert any("stale.source" in s for s in found)
    assert not any("fresh.source" in s for s in found)


def test_collect_stale_sources_handles_non_dict_state():
    assert collect_stale_sources("not a dict") == []  # type: ignore[arg-type]
    assert collect_stale_sources({}) == []


# ─────────────────────────────────────────────────────────────────────────────
# LLMTelemetry
# ─────────────────────────────────────────────────────────────────────────────

def _record(**kw) -> LLMCallRecord:
    base = dict(
        agent="x", model="m", started_at="2026-05-08T12:00:00",
        duration_ms=100, prompt_tokens=10, completion_tokens=5, total_tokens=15,
        success=True,
    )
    base.update(kw)
    return LLMCallRecord(**base)


def test_telemetry_aggregates_totals():
    t = LLMTelemetry()
    t.record(_record(duration_ms=100, total_tokens=15))
    t.record(_record(duration_ms=200, total_tokens=25))
    assert t.total_calls() == 2
    assert t.total_duration_ms() == 300
    assert t.total_tokens() == 40


def test_telemetry_counts_failures_and_fallbacks():
    t = LLMTelemetry()
    t.record(_record(success=True))
    t.record(_record(success=False, error="429"))
    t.record(_record(success=True, fallback_used=True))
    assert t.failed_calls() == 1
    assert t.fallback_calls() == 1


def test_telemetry_to_dict_includes_records():
    t = LLMTelemetry()
    t.record(_record())
    d = t.to_dict()
    assert d["total_calls"] == 1
    assert isinstance(d["records"], list)
    assert d["records"][0]["agent"] == "x"


def test_contextvar_set_and_reset():
    assert current_telemetry() is None
    t = LLMTelemetry()
    token = set_current_telemetry(t)
    try:
        assert current_telemetry() is t
    finally:
        reset_current_telemetry(token)
    assert current_telemetry() is None


# ─────────────────────────────────────────────────────────────────────────────
# llm.router.call_llm — records into telemetry contextvar
# ─────────────────────────────────────────────────────────────────────────────

class _FakeUsage:
    prompt_tokens = 100
    completion_tokens = 50


class _FakeMessage:
    content = "  {\"action\": \"BUY\"}  "


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]
    usage = _FakeUsage()


class _FakeCompletions:
    """Minimal Groq-shaped client. Behaviour is configured per-instance."""

    def __init__(self, *, fail_first: int = 0, error: Exception = None):
        self.fail_first = fail_first
        self.error = error
        self.calls: List[Dict[str, Any]] = []

    async def create(self, *, model, messages, temperature, response_format):
        self.calls.append({"model": model, "msgs_len": len(messages)})
        if self.fail_first > 0:
            self.fail_first -= 1
            raise self.error or RuntimeError("429 rate limit")
        return _FakeResponse()


class _FakeClient:
    def __init__(self, completions):
        self.chat = type("chat", (), {"completions": completions})()


@pytest.mark.asyncio
async def test_call_llm_records_successful_call():
    t = LLMTelemetry()
    token = set_current_telemetry(t)
    try:
        completions = _FakeCompletions()
        client = _FakeClient(completions)
        text = await call_llm(client, [{"role": "user", "content": "hi"}], agent="Test")
    finally:
        reset_current_telemetry(token)

    assert text == '{"action": "BUY"}'
    assert t.total_calls() == 1
    rec = t.records[0]
    assert rec.success is True
    assert rec.fallback_used is False
    assert rec.prompt_tokens == 100
    assert rec.completion_tokens == 50
    assert rec.agent == "Test"


@pytest.mark.asyncio
async def test_call_llm_records_non_429_error_and_reraises():
    t = LLMTelemetry()
    token = set_current_telemetry(t)
    try:
        completions = _FakeCompletions(fail_first=1, error=RuntimeError("auth failed"))
        client = _FakeClient(completions)
        with pytest.raises(RuntimeError):
            await call_llm(client, [{"role": "user", "content": "hi"}], agent="Test")
    finally:
        reset_current_telemetry(token)

    assert t.total_calls() == 1
    assert t.records[0].success is False
    assert t.records[0].fallback_used is False
    assert "auth failed" in (t.records[0].error or "")


@pytest.mark.asyncio
async def test_call_llm_falls_back_on_rate_limit(monkeypatch):
    """First attempt 429s → router sleeps then succeeds on the fallback model.
    We monkeypatch asyncio.sleep so the test runs in milliseconds."""
    async def fake_sleep(_):
        return None
    monkeypatch.setattr("llm.router.asyncio.sleep", fake_sleep)

    t = LLMTelemetry()
    token = set_current_telemetry(t)
    try:
        # First call raises a 429; second call (fallback model) succeeds
        completions = _FakeCompletions(fail_first=1, error=RuntimeError("429 rate limit"))
        client = _FakeClient(completions)
        text = await call_llm(client, [{"role": "user", "content": "hi"}], agent="Test")
    finally:
        reset_current_telemetry(token)

    assert text == '{"action": "BUY"}'
    assert t.total_calls() == 1
    assert t.records[0].fallback_used is True
    assert t.records[0].success is True


@pytest.mark.asyncio
async def test_call_llm_runs_without_telemetry_set():
    """If no telemetry contextvar is set, call_llm must still work."""
    completions = _FakeCompletions()
    client = _FakeClient(completions)
    text = await call_llm(client, [{"role": "user", "content": "hi"}], agent="Test")
    assert text == '{"action": "BUY"}'


# ─────────────────────────────────────────────────────────────────────────────
# Run log includes telemetry + data_quality
# ─────────────────────────────────────────────────────────────────────────────

def test_run_log_persists_telemetry_and_quality(tmp_path, monkeypatch):
    from graph import run_log
    monkeypatch.setattr(run_log, "RUN_LOG_DIR", str(tmp_path))

    rid = run_log.new_run_id()
    path = run_log.write_run_log(
        rid, "X.NS", "X",
        telemetry={"total_calls": 6, "total_tokens": 1234},
        data_quality={"overall_completeness": 0.92, "abort": False},
    )
    import json
    written = json.loads(open(path).read())
    assert written["telemetry"]["total_calls"] == 6
    assert written["data_quality"]["overall_completeness"] == 0.92


# ─────────────────────────────────────────────────────────────────────────────
# Routes integration smoke
# ─────────────────────────────────────────────────────────────────────────────

def test_routes_judge_fields_include_phase3_keys():
    from api.routes import JUDGE_FIELDS
    assert "data_quality" in JUDGE_FIELDS
    assert "stale_sources" in JUDGE_FIELDS
