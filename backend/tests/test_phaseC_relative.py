"""Phase C — benchmark- and sector-relative context."""

import pandas as pd
import pytest

from data.relative_strength import (
    BENCHMARK_INDEX,
    build_relative_context,
    classify_vix,
    compute_alpha,
    compute_relative_strength,
    map_sector_to_index,
    period_return_pct,
    render_for_prompt,
    summarise_index,
)


def _series(n=300, start=100.0, step=1.0):
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.Series([start + i * step for i in range(n)], index=idx)


# ─────────────────────────────────────────────────────────────────────────────
# Sector mapping
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("sector,industry,expected", [
    ("Information Technology", None, "NIFTY IT"),      # Screener vocabulary
    ("Technology", None, "NIFTY IT"),                  # yfinance vocabulary
    ("Fast Moving Consumer Goods", None, "NIFTY FMCG"),
    ("Consumer Defensive", None, "NIFTY FMCG"),
    ("Healthcare", None, "NIFTY PHARMA"),
    ("Energy", None, "NIFTY ENERGY"),
    ("Unknownium", None, None),
    (None, None, None),
])
def test_sector_maps_across_both_vocabularies(sector, industry, expected):
    """Two taxonomies reach us — Screener's and yfinance's — and both must map."""
    assert map_sector_to_index(sector, industry) == expected


def test_industry_beats_sector_for_specificity():
    """'Private Sector Bank' should route to NIFTY PVT BANK, not NIFTY BANK."""
    assert map_sector_to_index("Financial Services", "Private Sector Bank") == "NIFTY PVT BANK"
    assert map_sector_to_index("Financial Services", None) == "NIFTY FIN SERVICE"


# ─────────────────────────────────────────────────────────────────────────────
# Returns
# ─────────────────────────────────────────────────────────────────────────────

def test_period_return_is_a_percentage():
    s = pd.Series([100.0, 110.0], index=pd.bdate_range("2025-01-01", periods=2))
    assert period_return_pct(s, 1) == 10.0


def test_period_return_none_when_window_not_covered():
    """A partial window reported as a full one would overstate the move."""
    assert period_return_pct(_series(n=10), 250) is None


def test_period_return_handles_empty():
    assert period_return_pct(pd.Series(dtype=float), 21) is None
    assert period_return_pct(None, 21) is None


def test_relative_strength_computes_excess():
    stock = _series(step=2.0)     # rising faster
    bench = _series(step=1.0)
    out = compute_relative_strength(stock, bench)
    assert out["1M"]["excess_pct"] > 0
    for window in out.values():
        assert set(window) == {"stock_pct", "benchmark_pct", "excess_pct"}


def test_relative_strength_excess_is_none_when_either_side_missing():
    out = compute_relative_strength(_series(), None)
    assert out["1Y"]["excess_pct"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Alpha
# ─────────────────────────────────────────────────────────────────────────────

def test_alpha_capm():
    # expected = 6.5 + 0.85 × (-8 - 6.5) = -5.825 ; alpha = 10 - (-5.825)
    assert compute_alpha(10.0, -8.0, 0.85, 6.5) == pytest.approx(15.82, abs=0.01)


def test_alpha_requires_a_measured_beta():
    """Phase A made beta None when unmeasurable. Alpha must inherit that rather
    than quietly computing against a fabricated beta of 1.0."""
    assert compute_alpha(10.0, -8.0, None, 6.5) is None


def test_alpha_none_without_returns():
    assert compute_alpha(None, -8.0, 0.9, 6.5) is None
    assert compute_alpha(10.0, None, 0.9, 6.5) is None


# ─────────────────────────────────────────────────────────────────────────────
# VIX regime
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("vix,regime", [
    (11.0, "calm"), (15.0, "normal"), (20.0, "elevated"), (30.0, "stressed"), (None, "unknown"),
])
def test_vix_regime_bands(vix, regime):
    assert classify_vix(vix)["regime"] == regime


def test_vix_regime_carries_actionable_note():
    assert classify_vix(30.0)["note"]


# ─────────────────────────────────────────────────────────────────────────────
# Index summary + full context
# ─────────────────────────────────────────────────────────────────────────────

NIFTY = {"indexSymbol": "NIFTY 50", "last": 23118.6, "percentChange": -1.19,
         "perChange30d": -5.12, "perChange365d": -7.78, "pe": 19.54, "pb": 3.4,
         "dy": 1.3, "yearHigh": 26373.2, "yearLow": 22182.55}
NIFTY_IT = {"indexSymbol": "NIFTY IT", "last": 29555.3, "percentChange": -0.8,
            "perChange30d": -5.75, "perChange365d": -17.68, "pe": 24.0}
VIX = {"indexSymbol": "INDIA VIX", "last": 13.27}


def test_summarise_index_extracts_decision_fields():
    out = summarise_index(NIFTY)
    assert out["symbol"] == "NIFTY 50"
    assert out["change_pct_365d"] == -7.78
    assert out["pe"] == 19.54


def test_summarise_index_of_nothing():
    assert summarise_index(None) == {}


def test_build_context_end_to_end():
    ctx = build_relative_context(
        _series(step=2.0), _series(step=1.0),
        {"NIFTY 50": NIFTY, "NIFTY IT": NIFTY_IT, "INDIA VIX": VIX},
        sector="Information Technology", beta=0.85, risk_free_pct=6.5,
    )
    assert ctx["sector_index_symbol"] == "NIFTY IT"
    assert ctx["benchmark_index"]["symbol"] == BENCHMARK_INDEX
    assert ctx["volatility_regime"]["regime"] == "normal"
    assert ctx["alpha_1y_pct"] is not None
    # Sector comparison uses NSE's own published index moves.
    assert ctx["vs_sector"]["1Y"]["sector_pct"] == -17.68
    assert ctx["vs_sector"]["1Y"]["excess_pct"] is not None


def test_build_context_without_a_mappable_sector():
    ctx = build_relative_context(_series(), _series(), {"NIFTY 50": NIFTY},
                                 sector="Unknownium", beta=1.0)
    assert ctx["sector_index_symbol"] is None
    assert ctx["vs_sector"] == {}


def test_build_context_with_no_indices_at_all():
    ctx = build_relative_context(_series(), _series(), {}, sector="Technology", beta=1.0)
    assert ctx["volatility_regime"]["regime"] == "unknown"
    assert ctx["sector_index"] == {}


# ─────────────────────────────────────────────────────────────────────────────
# Prompt rendering
# ─────────────────────────────────────────────────────────────────────────────

def test_render_states_the_comparison_explicitly():
    ctx = build_relative_context(
        _series(step=2.0), _series(step=1.0),
        {"NIFTY 50": NIFTY, "NIFTY IT": NIFTY_IT, "INDIA VIX": VIX},
        sector="Technology", beta=0.85,
    )
    text = render_for_prompt(ctx)
    assert "NIFTY 50" in text and "NIFTY IT" in text
    assert "excess" in text
    assert "India VIX" in text


def test_render_says_unavailable_rather_than_omitting():
    """An agent told nothing will invent something; say the number is missing."""
    text = render_for_prompt(build_relative_context(_series(n=5), None, {}, beta=None))
    assert "unavailable" in text.lower()


def test_render_handles_no_context():
    assert "unavailable" in render_for_prompt(None).lower()


def test_prompts_include_the_relative_block():
    from pathlib import Path
    agents = Path(__file__).resolve().parent.parent / "agents"
    for name in ("technical_analyst.py", "risk_analyst.py"):
        src = (agents / name).read_text()
        assert "{relative_performance}" in src, f"{name} prompt is missing the block"
        assert "relative_performance=relative_block" in src, f"{name} does not pass it"
