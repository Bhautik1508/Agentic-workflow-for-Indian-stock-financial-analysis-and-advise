"""Phase G — the analytics must actually reach the browser.

Phases C, D and E all computed real numbers that `api/routes.py` then filtered
out of the SSE stream, so the frontend had no knowledge they existed. These
tests fail if that regresses.
"""

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
