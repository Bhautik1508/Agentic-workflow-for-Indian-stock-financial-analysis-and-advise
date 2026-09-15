"""Phase F — make sure the evaluation can't quietly mislead."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from analysis_version import ANALYSIS_VERSION, VERSION_HISTORY, describe, is_current
from evaluation.backtest import (
    MIN_CREDIBLE_SAMPLE,
    VerdictRecord,
    group_by_version,
    score_by_cohort,
    score_verdicts,
)

IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 1, 1, tzinfo=IST)


def _prices(n=200, step=1.0):
    return {(START + timedelta(days=i)).strftime("%Y-%m-%d"): 100.0 + i * step
            for i in range(n)}


def _verdict(version="legacy", action="BUY", ticker="X.NS", run_id="r"):
    return VerdictRecord(run_id=run_id, ticker=ticker, action=action, confidence=0.8,
                         timestamp=START, analysis_version=version)


# ─────────────────────────────────────────────────────────────────────────────
# Version stamping
# ─────────────────────────────────────────────────────────────────────────────

def test_current_version_is_documented():
    """Every cohort boundary needs a reason, or a break in the numbers becomes
    unattributable later."""
    assert ANALYSIS_VERSION in VERSION_HISTORY
    assert describe(ANALYSIS_VERSION)
    assert is_current(ANALYSIS_VERSION)


def test_legacy_cohort_is_described_as_incomparable():
    text = describe("legacy").lower()
    assert "beta" in text and "not comparable" in text


def test_unknown_version_does_not_crash():
    assert describe("2099.01.01-z") == "unknown engine version"


def test_run_log_records_the_engine_version(tmp_path, monkeypatch):
    from graph import run_log

    monkeypatch.setattr(run_log, "RUN_LOG_DIR", str(tmp_path))
    path = run_log.write_run_log("rid", "TCS.NS", "TCS", judge_payload={"action": "BUY"})
    import json
    assert json.loads(Path(path).read_text())["analysis_version"] == ANALYSIS_VERSION


# ─────────────────────────────────────────────────────────────────────────────
# Cohort separation — the core of the phase
# ─────────────────────────────────────────────────────────────────────────────

def test_verdicts_group_by_engine_version():
    groups = group_by_version([_verdict("legacy"), _verdict("legacy"), _verdict("2026.09.15-e")])
    assert set(groups) == {"legacy", "2026.09.15-e"}
    assert len(groups["legacy"]) == 2


def test_missing_version_defaults_to_legacy():
    """Existing logs predate the stamp and must not be silently counted as
    current-engine results."""
    assert group_by_version([VerdictRecord("r", "X.NS", "BUY", 0.8, START)]) .get("legacy")


def test_cohorts_are_scored_separately_and_not_pooled():
    """A hit-rate pooled across engines describes neither. Before Phase A every
    beta was 1.00 and fundamentals were 20% complete."""
    prices = {"X.NS": _prices(), "Y.NS": _prices(step=-0.5)}
    report = score_by_cohort([
        _verdict("legacy", "BUY", "X.NS", "a"),
        _verdict(ANALYSIS_VERSION, "BUY", "Y.NS", "b"),
    ], prices, {"1M": 30})

    assert set(report["cohorts"]) == {"legacy", ANALYSIS_VERSION}
    assert report["pooled_is_meaningful"] is False
    assert report["cohorts"][ANALYSIS_VERSION]["is_current"] is True
    assert report["cohorts"]["legacy"]["is_current"] is False


def test_single_cohort_is_poolable():
    report = score_by_cohort([_verdict(ANALYSIS_VERSION, "BUY", "X.NS")],
                             {"X.NS": _prices()}, {"1M": 30})
    assert report["pooled_is_meaningful"] is True


def test_each_cohort_carries_its_description():
    report = score_by_cohort([_verdict("legacy", "BUY", "X.NS")],
                             {"X.NS": _prices()}, {"1M": 30})
    assert report["cohorts"]["legacy"]["description"]


# ─────────────────────────────────────────────────────────────────────────────
# Sample-size honesty
# ─────────────────────────────────────────────────────────────────────────────

def test_small_sample_is_not_credible():
    """The guard that stops a 100% hit-rate on three verdicts being acted on."""
    result = score_verdicts([_verdict(action="BUY", ticker="X.NS")],
                            {"X.NS": _prices()}, {"1M": 30})
    assert result["sample_is_credible"] is False
    assert result["min_credible_sample"] == MIN_CREDIBLE_SAMPLE


def test_large_sample_is_credible():
    verdicts = [_verdict(action="BUY", ticker="X.NS", run_id=f"r{i}")
                for i in range(MIN_CREDIBLE_SAMPLE)]
    result = score_verdicts(verdicts, {"X.NS": _prices()}, {"1M": 30})
    assert result["by_horizon"]["1M"]["scored"] == MIN_CREDIBLE_SAMPLE
    assert result["sample_is_credible"] is True


def test_credible_bar_is_meaningfully_above_the_current_sample():
    """7 run logs exist today; the bar must not be trivially satisfiable."""
    assert MIN_CREDIBLE_SAMPLE >= 30


# ─────────────────────────────────────────────────────────────────────────────
# Tooling exists and is wired
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("script", [
    "check_coverage.py", "backtest.py", "run_golden_set.py", "provider_ab.py",
])
def test_evaluation_scripts_present_and_executable(script):
    path = Path(__file__).resolve().parent.parent.parent / "scripts" / script
    assert path.exists(), f"{script} missing"
    assert path.stat().st_mode & 0o111, f"{script} not executable"


def test_coverage_check_runs_without_llm_calls():
    """It must stay cheap enough for CI: fundamentals only, no model budget."""
    src = (Path(__file__).resolve().parent.parent.parent
           / "scripts" / "check_coverage.py").read_text()
    assert "call_llm" not in src and "run_stock_analysis" not in src


def test_nightly_workflow_does_not_auto_spend_quota():
    """The golden set costs ~108 LLM calls; it must be opt-in, never on push."""
    wf = (Path(__file__).resolve().parent.parent.parent
          / ".github" / "workflows" / "nightly-eval.yml").read_text()
    assert "workflow_dispatch" in wf
    assert "run_golden_set" in wf
    # The schedule stays commented until keys exist as secrets.
    assert "# schedule:" in wf or "schedule:" not in wf


def test_banks_have_a_lower_coverage_floor():
    """A bank P&L has no OPM row and no meaningful debt-to-equity; ~0.7 is full
    marks, not a regression."""
    src = (Path(__file__).resolve().parent.parent.parent
           / "scripts" / "check_coverage.py").read_text()
    assert '("HDFCBANK.NS", 0.6)' in src
    assert '("TCS.NS", 0.8)' in src
