"""Phase G — the analytics must actually reach the browser.

Phases C, D and E all computed real numbers that `api/routes.py` then filtered
out of the SSE stream, so the frontend had no knowledge they existed. These
tests fail if that regresses.
"""

import json
from pathlib import Path

import pytest

from api.routes import ANALYTICS_FIELDS, JUDGE_FIELDS

FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"


def test_analytics_fields_are_declared():
    assert "relative_context" in ANALYTICS_FIELDS
    assert "quality_metrics" in ANALYTICS_FIELDS


def test_indices_is_not_streamed():
    """139 NSE index records: useful server-side, far too large per node update."""
    assert "indices" not in ANALYTICS_FIELDS
    assert "indices" not in JUDGE_FIELDS


def test_sse_filter_admits_analytics():
    src = (Path(__file__).resolve().parent.parent / "api" / "routes.py").read_text()
    assert "k in ANALYTICS_FIELDS" in src, "the node_update filter must admit analytics"
    assert 'analytics["extended_risk"]' in src, (
        "extended_risk lives inside risk_data, which is not streamed wholesale"
    )


def test_cached_payload_carries_analytics():
    """A cache hit must render identically to a live run."""
    src = (Path(__file__).resolve().parent.parent / "api" / "routes.py").read_text()
    assert '"analytics": analytics' in src


# ─────────────────────────────────────────────────────────────────────────────
# Frontend consumes what the backend now sends
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("symbol", [
    "RelativeContext", "QualityMetrics", "ExtendedRisk",
])
def test_frontend_declares_the_types(symbol):
    src = (FRONTEND / "hooks" / "useAnalysis.ts").read_text()
    assert f"export interface {symbol}" in src


@pytest.mark.parametrize("field", ["relative", "quality", "extendedRisk"])
def test_frontend_state_holds_the_analytics(field):
    src = (FRONTEND / "hooks" / "useAnalysis.ts").read_text()
    assert f"{field}:" in src


def test_frontend_reads_both_live_and_cached_shapes():
    """Live runs deliver these on node_update state; cached runs deliver them
    under `analytics` on the complete event."""
    src = (FRONTEND / "hooks" / "useAnalysis.ts").read_text()
    assert "data.state?.relative_context" in src
    assert "cachedAnalytics.relative_context" in src


def test_comparison_row_shows_relative_performance():
    src = (FRONTEND / "components" / "analysis" / "ComparisonRow.tsx").read_text()
    assert "vs_sector" in src and "vs_benchmark" in src
    assert "alpha_1y_pct" in src


def test_quality_panel_surfaces_the_computed_metrics():
    src = (FRONTEND / "components" / "analysis" / "QualityPanel.tsx").read_text()
    for token in ("piotroski", "dupont", "cash_quality", "rolling_beta", "liquidity"):
        assert token in src, f"QualityPanel does not surface {token}"


def test_analyze_page_renders_the_new_panels():
    src = (FRONTEND / "app" / "analyze" / "[ticker]" / "page.tsx").read_text()
    assert "<QualityPanel" in src
    assert "relative={state.relative}" in src


# ─────────────────────────────────────────────────────────────────────
# NaN must never reach the wire.
#
# `json.dumps` writes float('nan') as the bare token `NaN`, which Python
# accepts on the way back in and the browser's JSON.parse rejects outright.
# That asymmetry is why this shipped: every backend-side check passed while
# the page died on `Unexpected token 'N'`. Because one SSE stream carries the
# whole run, a single NaN anywhere took down the entire analysis rather than
# blanking one field.
# ─────────────────────────────────────────────────────────────────────

def _strict_loads(payload: str):
    """json.loads that refuses NaN/Infinity, the way a browser does."""
    def reject(token):
        raise ValueError(f"non-JSON constant on the wire: {token}")
    return json.loads(payload, parse_constant=reject)


def test_json_safe_replaces_non_finite_with_none():
    from api.routes import _json_safe
    out = _json_safe({
        "annual_return_pct": float("nan"),
        "calmar_ratio": float("inf"),
        "downside": float("-inf"),
        "sortino_ratio": 1.23,
        "keep_none": None,
    })
    assert out["annual_return_pct"] is None
    assert out["calmar_ratio"] is None
    assert out["downside"] is None
    assert out["sortino_ratio"] == 1.23
    assert out["keep_none"] is None


def test_json_safe_walks_nested_containers():
    from api.routes import _json_safe
    out = _json_safe({
        "extended_risk": {
            "rolling_beta": {"beta_1y": float("nan"), "beta_2y": 1.08},
            "history": [1.0, float("nan"), {"x": float("inf")}],
        }
    })
    assert out["extended_risk"]["rolling_beta"]["beta_1y"] is None
    assert out["extended_risk"]["rolling_beta"]["beta_2y"] == 1.08
    assert out["extended_risk"]["history"][1] is None
    assert out["extended_risk"]["history"][2]["x"] is None


def test_dumps_output_is_browser_parseable():
    """The regression itself: the exact shape that crashed the page."""
    from api.routes import _dumps
    payload = {"node": "parallel_analysts", "state": {
        "extended_risk": {"annual_return_pct": float("nan"),
                          "rolling_beta": {"beta_1y": float("nan")}}}}

    # Reproduce the old behaviour to prove the test has teeth.
    with pytest.raises(ValueError):
        _strict_loads(json.dumps(payload))

    revived = _strict_loads(_dumps(payload))
    assert revived["state"]["extended_risk"]["annual_return_pct"] is None
    assert revived["state"]["extended_risk"]["rolling_beta"]["beta_1y"] is None


def test_drop_incomplete_sessions_removes_the_forming_bar():
    import pandas as pd
    from data.market_data import drop_incomplete_sessions

    frame = pd.DataFrame(
        {"Close": [100.0, 101.0, float("nan")], "Volume": [10, 11, 12]},
        index=pd.to_datetime(["2026-09-11", "2026-09-14", "2026-09-15"]),
    )
    cleaned = drop_incomplete_sessions(frame)
    assert len(cleaned) == 2
    assert float(cleaned["Close"].iloc[-1]) == 101.0


def test_drop_incomplete_sessions_tolerates_odd_input():
    import pandas as pd
    from data.market_data import drop_incomplete_sessions

    assert drop_incomplete_sessions(None) is None
    empty = pd.DataFrame()
    assert drop_incomplete_sessions(empty).empty
    no_close = pd.DataFrame({"Volume": [1, 2]})
    assert len(drop_incomplete_sessions(no_close)) == 2


def test_forming_bar_fabricates_a_52_week_high():
    """The reason this matters beyond the crash.

    With the NaN bar present, TCS — down 26% on the year — reported a 52-week
    percentile of 100.0, i.e. sitting at its high. Sanitising the wire would
    have hidden the crash and kept the wrong number.
    """
    import pandas as pd
    from data.market_data import drop_incomplete_sessions
    from scoring.risk_metrics import week52_percentile

    closes = [100.0] * 100 + [80.0] * 100 + [74.0]      # ends near the low
    frame = pd.DataFrame({"Close": closes + [float("nan")]})

    dirty = frame["Close"]
    clean = drop_incomplete_sessions(frame)["Close"]

    # max/min over a NaN-bearing series still work, but the *current price* is
    # read off the last row — which is NaN — and the comparison degrades.
    assert pd.isna(dirty.iloc[-1])
    assert float(clean.iloc[-1]) == 74.0

    pctile = week52_percentile(float(clean.iloc[-1]),
                               float(clean.max()), float(clean.min()))
    assert pctile is not None and pctile < 50, f"expected near the low, got {pctile}"


def test_dumps_accepts_json_dumps_keywords():
    """Several SSE call sites pass `default=str` explicitly. A one-argument
    _dumps raised TypeError there and killed the stream before any
    node_update — which looked exactly like a clean run with no NaN in it."""
    from api.routes import _dumps
    from datetime import datetime

    payload = {"when": datetime(2026, 9, 16, 12, 0), "v": float("nan")}
    revived = _strict_loads(_dumps(payload, default=str))
    assert revived["v"] is None
    assert revived["when"].startswith("2026-09-16")

    # and without the keyword, since other call sites omit it
    assert _strict_loads(_dumps({"v": float("inf")}))["v"] is None


def test_analysis_cache_never_writes_nan_to_disk(tmp_path, monkeypatch):
    """A cached payload is read back and re-served later, so a NaN written to
    disk keeps crashing the page long after the run that produced it."""
    from data import cache as cache_mod

    monkeypatch.setattr(cache_mod, "CACHE_DIR", str(tmp_path))
    cache_mod.save_analysis_to_cache("TCS.NS", {
        "analytics": {"extended_risk": {"annual_return_pct": float("nan"),
                                        "rolling_beta": {"beta_1y": float("nan")}}}
    })
    written = list(tmp_path.glob("*.json"))
    assert written, "cache file was not created"
    raw = written[0].read_text()
    assert "NaN" not in raw
    _strict_loads(raw)          # parses as a browser would


def test_run_log_never_writes_nan_to_disk(tmp_path, monkeypatch):
    """/api/verdict/{id} re-serves run logs, so the frozen page carried the
    same exposure the live page did."""
    from graph import run_log as rl

    monkeypatch.setattr(rl, "RUN_LOG_DIR", str(tmp_path))
    path = rl.write_run_log(
        "run_test_nan", "TCS.NS", "TCS",
        judge_payload={"confidence_score": float("nan")},
        telemetry={"latency": {"overall": {"p50": float("inf")}}},
        data_quality={"overall_completeness": 0.9},
    )
    assert path, "run log was not written"
    raw = Path(path).read_text()
    assert "NaN" not in raw and "Infinity" not in raw
    revived = _strict_loads(raw)
    assert revived["judge"]["confidence_score"] is None
    assert revived["telemetry"]["latency"]["overall"]["p50"] is None
