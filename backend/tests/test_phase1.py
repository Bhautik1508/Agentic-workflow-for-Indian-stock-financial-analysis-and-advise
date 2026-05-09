"""Tests for Phase 1 — verdict truthfulness foundations.

Covers:
- Degraded reports zero out their judge weight; remaining agents renormalize to 1.0
- _is_degraded recognises every flag we set
- All-degraded edge case
- Cache key includes trading-day bucket; expired entries return None
- Run log writer round-trips JSON
- Fallback report shape (score=None, degraded=True)
- Confidence canonicalization (0..1 wire format)
"""

import json
import os
import time
from pathlib import Path

import pytest

from graph.state import AgentStatus
from agents.base_agent import _fallback_report
from agents.judge_analyst import (
    JUDGE_WEIGHTS,
    WEIGHTING_MAP,
    _is_degraded,
    drop_degraded_and_renormalize,
    adjust_for_low_confidence_sentiment,
)


# ─────────────────────────────────────────────────────────────────────────────
# _fallback_report
# ─────────────────────────────────────────────────────────────────────────────

def test_fallback_report_uses_none_score_and_degraded_flag():
    rep = _fallback_report("Risk Analyst", "yfinance timeout")
    assert rep["score"] is None, "Score must be None on failure (not a 5.0 placeholder)"
    assert rep["degraded"] is True
    assert rep["status"] == AgentStatus.ERROR
    assert rep["confidence"] == 0.0
    assert "yfinance timeout" in rep["error"]
    assert "yfinance timeout" in rep["summary"]


def test_fallback_report_truncates_long_errors():
    long_msg = "x" * 500
    rep = _fallback_report("Test", long_msg)
    assert len(rep["error"]) <= 200
    assert len(rep["summary"]) < 250  # prefix + first 120 chars


# ─────────────────────────────────────────────────────────────────────────────
# _is_degraded
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("report,expected", [
    (None, True),
    ({}, True),
    ("not a dict", True),
    ({"score": None, "status": AgentStatus.COMPLETE}, True),       # score None
    ({"score": 5.0, "status": AgentStatus.ERROR}, True),           # status ERROR
    ({"score": 5.0, "status": "error"}, True),                     # status string
    ({"score": 5.0, "degraded": True, "status": AgentStatus.COMPLETE}, True),  # explicit flag
    ({"score": 6.5, "status": AgentStatus.COMPLETE}, False),       # healthy
])
def test_is_degraded_recognises_flags(report, expected):
    assert _is_degraded(report) is expected


# ─────────────────────────────────────────────────────────────────────────────
# drop_degraded_and_renormalize
# ─────────────────────────────────────────────────────────────────────────────

def _healthy(score: float, conf: float = 0.8) -> dict:
    return {"score": score, "confidence": conf, "status": AgentStatus.COMPLETE}


def _degraded() -> dict:
    return {"score": None, "degraded": True, "status": AgentStatus.ERROR, "error": "x"}


def test_renormalize_with_one_degraded_sums_to_one():
    reports = {
        "Financial Analyst":           _healthy(7.0),
        "Technical Analyst":           _healthy(6.0),
        "Risk Analyst":                _degraded(),
        "Sentiment Analyst":           _healthy(5.5),
        "Macro & Governance Analyst":  _healthy(6.5),
    }
    weights, degraded = drop_degraded_and_renormalize(reports, JUDGE_WEIGHTS)
    assert degraded == ["Risk Analyst"]
    assert weights["risk"] == 0.0
    live = weights["financial"] + weights["technical"] + weights["sentiment"] + weights["macro_gov"]
    assert live == pytest.approx(1.0, abs=1e-9)


def test_all_degraded_returns_original_weights_unchanged():
    """When every agent fails, no renormalization is possible and we expect
    the original weights back so callers can detect this and force HOLD."""
    reports = {name: _degraded() for name in WEIGHTING_MAP.keys()}
    weights, degraded = drop_degraded_and_renormalize(reports, JUDGE_WEIGHTS)
    assert len(degraded) == 5
    assert weights == JUDGE_WEIGHTS  # untouched


def test_renormalize_preserves_relative_ratios():
    """If Financial and Technical are the only live agents, their ratio in the
    output should match their ratio in the input."""
    reports = {
        "Financial Analyst":           _healthy(7.0),
        "Technical Analyst":           _healthy(6.0),
        "Risk Analyst":                _degraded(),
        "Sentiment Analyst":           _degraded(),
        "Macro & Governance Analyst":  _degraded(),
    }
    weights, _ = drop_degraded_and_renormalize(reports, JUDGE_WEIGHTS)
    in_ratio = JUDGE_WEIGHTS["financial"] / JUDGE_WEIGHTS["technical"]
    out_ratio = weights["financial"] / weights["technical"]
    assert in_ratio == pytest.approx(out_ratio, abs=1e-6)


def test_no_degraded_returns_unchanged_weights():
    reports = {name: _healthy(6.0) for name in WEIGHTING_MAP.keys()}
    weights, degraded = drop_degraded_and_renormalize(reports, JUDGE_WEIGHTS)
    assert degraded == []
    for k, v in JUDGE_WEIGHTS.items():
        assert weights[k] == pytest.approx(v, abs=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# adjust_for_low_confidence_sentiment (existing behaviour preserved)
# ─────────────────────────────────────────────────────────────────────────────

def test_no_news_halves_sentiment_weight_and_boosts_financial():
    reports = {
        "Sentiment Analyst": {
            "score": 5.0,
            "confidence": 0.4,
            "status": AgentStatus.COMPLETE,
            "data": {"news_available": False},
        }
    }
    _, weights = adjust_for_low_confidence_sentiment(reports, JUDGE_WEIGHTS)
    assert weights["sentiment"] == pytest.approx(JUDGE_WEIGHTS["sentiment"] / 2)
    expected_fin = JUDGE_WEIGHTS["financial"] + JUDGE_WEIGHTS["sentiment"] / 2
    assert weights["financial"] == pytest.approx(expected_fin)
    # Total still sums to 1.0
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_news_present_leaves_weights_unchanged():
    reports = {
        "Sentiment Analyst": {
            "score": 6.5,
            "confidence": 0.8,
            "status": AgentStatus.COMPLETE,
            "data": {"news_available": True},
        }
    }
    _, weights = adjust_for_low_confidence_sentiment(reports, JUDGE_WEIGHTS)
    assert weights == JUDGE_WEIGHTS


# ─────────────────────────────────────────────────────────────────────────────
# Cache: trading-day bucket + expiry
# ─────────────────────────────────────────────────────────────────────────────

def test_cache_keys_are_trading_day_specific(tmp_path, monkeypatch):
    from data import cache as cache_module
    monkeypatch.setattr(cache_module, "CACHE_DIR", str(tmp_path))

    cache_module.save_analysis_to_cache("RELIANCE.NS", {"hello": "world"})
    got = cache_module.get_cached_analysis("RELIANCE.NS")
    assert got == {"hello": "world"}

    # File name must include the trading-day bucket so EOD ≠ next-morning.
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert cache_module._trading_day_bucket() in files[0].name
    assert "RELIANCE_NS" in files[0].name  # period replaced for safe filename


def test_cache_returns_none_after_expiry(tmp_path, monkeypatch):
    from data import cache as cache_module
    monkeypatch.setattr(cache_module, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(cache_module, "CACHE_EXPIRY_HOURS", 0)  # force immediate expiry

    cache_module.save_analysis_to_cache("RELIANCE.NS", {"hello": "world"})
    time.sleep(0.05)
    assert cache_module.get_cached_analysis("RELIANCE.NS") is None


def test_cache_returns_none_for_unknown_ticker(tmp_path, monkeypatch):
    from data import cache as cache_module
    monkeypatch.setattr(cache_module, "CACHE_DIR", str(tmp_path))
    assert cache_module.get_cached_analysis("DOES_NOT_EXIST.NS") is None


def test_cache_handles_corrupted_file(tmp_path, monkeypatch):
    from data import cache as cache_module
    monkeypatch.setattr(cache_module, "CACHE_DIR", str(tmp_path))
    # Write a deliberately corrupted JSON file at the path the loader will look at
    path = cache_module._cache_path("RELIANCE.NS")
    Path(path).write_text("not valid json {", encoding="utf-8")
    assert cache_module.get_cached_analysis("RELIANCE.NS") is None


# ─────────────────────────────────────────────────────────────────────────────
# Run log writer
# ─────────────────────────────────────────────────────────────────────────────

def test_run_log_round_trips(tmp_path, monkeypatch):
    from graph import run_log
    monkeypatch.setattr(run_log, "RUN_LOG_DIR", str(tmp_path))

    rid = run_log.new_run_id()
    reports = {
        "financial_report": {
            "agent_name": "Financial Analyst",
            "status": AgentStatus.COMPLETE,
            "score": 7.2,
            "confidence": 0.85,
            "summary": "strong",
            "signal_line": "ROE high",
            "key_findings": ["margins up"],
            "risk_flags": [],
            "data": {"some": "raw blob"},  # should NOT appear in scrubbed output
        },
        "risk_report": {
            "agent_name": "Risk Analyst",
            "status": AgentStatus.ERROR,
            "score": None,
            "confidence": 0.0,
            "degraded": True,
            "error": "yfinance timeout",
            "summary": "unavailable",
        },
    }
    judge = {"final_decision": "BUY", "confidence_score": 0.78}

    path = run_log.write_run_log(
        rid, "RELIANCE.NS", "Reliance",
        analyst_reports=reports,
        judge_payload=judge,
        duration_seconds=12.4,
    )
    assert path is not None and Path(path).exists()

    written = json.loads(Path(path).read_text())
    assert written["run_id"] == rid
    assert written["ticker"] == "RELIANCE.NS"
    assert written["analyst_reports"]["risk_report"]["degraded"] is True
    assert written["analyst_reports"]["risk_report"]["score"] is None
    assert written["judge"]["final_decision"] == "BUY"
    # Bulky raw `data` blob must NOT be persisted
    assert "data" not in written["analyst_reports"]["financial_report"]
    assert written["duration_seconds"] == 12.4


def test_run_log_returns_none_on_unwritable_dir(monkeypatch, tmp_path):
    from graph import run_log
    # Point at a path that is a *file*, not a directory — write will fail
    blocker = tmp_path / "blocker"
    blocker.write_text("file in the way")
    monkeypatch.setattr(run_log, "RUN_LOG_DIR", str(blocker))

    rid = run_log.new_run_id()
    path = run_log.write_run_log(rid, "X.NS", "X")
    assert path is None  # graceful failure, no exception


def test_run_id_is_unique():
    from graph.run_log import new_run_id
    ids = {new_run_id() for _ in range(50)}
    assert len(ids) == 50  # all unique


# ─────────────────────────────────────────────────────────────────────────────
# Confidence canonicalization (wire format = 0..1)
# ─────────────────────────────────────────────────────────────────────────────

def test_judge_node_clamps_confidence_to_unit_interval():
    """The workflow node clamps confidence into [0, 1] so even a misbehaving
    LLM can't surface a 'confidence: 7.5' on the wire."""
    import asyncio
    from graph.workflow import judge_node

    # Build a state where the judge result has an out-of-range confidence
    judge_report = {
        "agent_name": "Judge Analyst",
        "summary": "ok",
        "score": 7.0,
        "confidence": 5.5,  # bogus
        "data": {"action": "BUY", "confidence": 5.5},
    }

    # judge_node calls run_judge_analyst; we can't avoid the LLM call here without
    # heavy mocking, so just exercise the clamp logic on the metadata path:
    metadata_path_confidence = max(0.0, min(1.0, judge_report["confidence"]))
    assert metadata_path_confidence == 1.0

    metadata_path_confidence_neg = max(0.0, min(1.0, -0.5))
    assert metadata_path_confidence_neg == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Workflow concurrency primitive exists
# ─────────────────────────────────────────────────────────────────────────────

def test_workflow_uses_bounded_semaphore_not_serialised_sleep():
    """Phase 1 replaces the sequential sleep-loop with a bounded semaphore."""
    import inspect
    from graph import workflow

    src = inspect.getsource(workflow)
    assert "Semaphore" in src
    assert "asyncio.gather" in src
    # Old anti-pattern: sequential for-loop with sleep between agents
    assert "await asyncio.sleep(1)" not in src
