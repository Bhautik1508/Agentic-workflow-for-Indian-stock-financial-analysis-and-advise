"""Phase D — accounting-quality metrics computed in Python, not inferred."""

from pathlib import Path

import pytest

from scoring.quality_metrics import (
    annual_series,
    build_quality_metrics,
    cash_quality,
    dupont_decomposition,
    piotroski_f_score,
    render_for_prompt,
)

# Two years of statements, shaped like Screener's output: non-breaking spaces,
# a TTM column on the P&L that the balance sheet does not have, and percent signs.
GOOD = {
    "pl_Sales\xa0+": {"Mar 2025": "255,324", "Mar 2026": "267,021", "TTM": "275,859"},
    "pl_Net Profit\xa0+": {"Mar 2025": "48,797", "Mar 2026": "49,454", "TTM": "50,055"},
    "pl_OPM %": {"Mar 2025": "26%", "Mar 2026": "27%", "TTM": "27%"},
    "bs_Total Assets": {"Mar 2025": "158,649", "Mar 2026": "181,167"},
    "bs_Borrowings\xa0+": {"Mar 2025": "9,392", "Mar 2026": "11,283"},
    "bs_Equity Capital": {"Mar 2025": "362", "Mar 2026": "362"},
    "bs_Reserves": {"Mar 2025": "94,394", "Mar 2026": "106,878"},
    "cf_Cash from Operating Activity\xa0+": {"Mar 2025": "48,908", "Mar 2026": "52,094"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Year handling
# ─────────────────────────────────────────────────────────────────────────────

def test_annual_series_excludes_ttm():
    """Screener's P&L carries a TTM column the balance sheet lacks. Mixing them
    compares a twelve-month figure against a year-end one."""
    series = annual_series(GOOD["pl_Sales\xa0+"])
    assert [y for y, _ in series] == [2025, 2026]


def test_annual_series_is_ascending():
    assert annual_series(GOOD["bs_Total Assets"]) == [(2025, 158649.0), (2026, 181167.0)]


def test_annual_series_of_nothing():
    assert annual_series(None) == []
    assert annual_series({}) == []


def test_annual_series_skips_blank_cells():
    assert annual_series({"Mar 2025": "", "Mar 2026": "10"}) == [(2026, 10.0)]


# ─────────────────────────────────────────────────────────────────────────────
# Piotroski
# ─────────────────────────────────────────────────────────────────────────────

def test_piotroski_scores_only_what_it_can_evaluate():
    """Screener publishes no current-assets/liabilities split, so the
    current-ratio criterion is unavailable. Counting it as a failure would
    understate every company by a point."""
    r = piotroski_f_score(GOOD)
    assert r.score is not None
    assert r.max_score == 8, "9 classic criteria, one not evaluable from this source"
    assert "Current ratio improving" in r.unavailable
    assert 0 <= r.score <= r.max_score


def test_piotroski_criteria_are_explainable():
    r = piotroski_f_score(GOOD)
    named = {c["name"]: c for c in r.criteria}
    assert named["ROA positive"]["passed"] is True
    assert named["Operating cash flow positive"]["passed"] is True
    assert named["No new equity issued"]["passed"] is True     # 362 -> 362
    assert named["Operating margin improving"]["passed"] is True  # 26% -> 27%
    for c in r.criteria:
        assert c["detail"], f"{c['name']} must explain itself"


def test_piotroski_detects_rising_leverage():
    r = piotroski_f_score(GOOD)
    named = {c["name"]: c for c in r.criteria}
    # debt/assets 5.92% -> 6.23%: leverage rose, so this must fail.
    assert named["Leverage falling"]["passed"] is False


def test_piotroski_detects_equity_dilution():
    diluted = dict(GOOD)
    diluted["bs_Equity Capital"] = {"Mar 2025": "362", "Mar 2026": "400"}
    named = {c["name"]: c for c in piotroski_f_score(diluted).criteria}
    assert named["No new equity issued"]["passed"] is False


def test_piotroski_with_no_data():
    r = piotroski_f_score({})
    assert r.score is None
    assert "not computable" in r.interpretation


def test_piotroski_single_year_cannot_evaluate_trends():
    one_year = {
        "pl_Net Profit\xa0+": {"Mar 2026": "100"},
        "bs_Total Assets": {"Mar 2026": "1000"},
        "cf_Cash from Operating Activity\xa0+": {"Mar 2026": "120"},
    }
    r = piotroski_f_score(one_year)
    named = {c["name"]: c for c in r.criteria}
    assert named["ROA positive"]["passed"] is True        # level, evaluable
    assert named["ROA improving"]["passed"] is None       # trend, not evaluable


# ─────────────────────────────────────────────────────────────────────────────
# DuPont
# ─────────────────────────────────────────────────────────────────────────────

def test_dupont_identity_holds():
    d = dupont_decomposition(GOOD)
    assert d.roe == pytest.approx(d.net_margin * d.asset_turnover * d.equity_multiplier, rel=1e-3)


def test_dupont_names_the_driver():
    """A single ROE cannot distinguish a profitable business from a levered one."""
    d = dupont_decomposition(GOOD)
    assert d.driver in {"margin", "turnover", "leverage"}
    assert d.driver == "margin", "high-margin, low-leverage profile"


def test_dupont_flags_a_leverage_driven_roe():
    levered = {
        "pl_Sales\xa0+": {"Mar 2026": "1000"},
        "pl_Net Profit\xa0+": {"Mar 2026": "30"},        # 3% margin
        "bs_Total Assets": {"Mar 2026": "2000"},          # 0.5x turnover
        "bs_Equity Capital": {"Mar 2026": "50"},
        "bs_Reserves": {"Mar 2026": "150"},               # 10x leverage
    }
    assert dupont_decomposition(levered).driver == "leverage"


def test_dupont_reports_why_it_failed():
    d = dupont_decomposition({"pl_Sales\xa0+": {"Mar 2026": "1000"}})
    assert d.roe is None
    assert d.reason


# ─────────────────────────────────────────────────────────────────────────────
# Cash quality
# ─────────────────────────────────────────────────────────────────────────────

def test_cash_conversion_computed_over_overlapping_years():
    c = cash_quality(GOOD)
    assert c.cash_conversion == pytest.approx(52094 / 49454, rel=1e-3)
    assert c.cash_conversion_3y_avg is not None
    assert c.flag


def test_accruals_ratio_is_negative_when_cash_exceeds_profit():
    """Cash above reported profit is a good sign; the ratio should be negative."""
    assert cash_quality(GOOD).accruals_ratio < 0


def test_poor_cash_conversion_is_flagged():
    weak = dict(GOOD)
    weak["cf_Cash from Operating Activity\xa0+"] = {"Mar 2025": "10,000", "Mar 2026": "12,000"}
    c = cash_quality(weak)
    assert c.cash_conversion_3y_avg < 0.5
    assert "poor" in c.flag.lower()


def test_cash_quality_without_a_cash_flow_statement():
    c = cash_quality({"pl_Net Profit\xa0+": {"Mar 2026": "100"}})
    assert c.cash_conversion is None
    assert c.reason


def test_cash_quality_with_no_overlapping_years():
    c = cash_quality({
        "pl_Net Profit\xa0+": {"Mar 2026": "100"},
        "cf_Cash from Operating Activity\xa0+": {"Mar 2020": "90"},
    })
    assert c.cash_conversion is None
    assert "overlapping" in c.reason


# ─────────────────────────────────────────────────────────────────────────────
# Payload + prompt wiring
# ─────────────────────────────────────────────────────────────────────────────

def test_build_quality_metrics_shape():
    m = build_quality_metrics(GOOD)
    assert set(m) == {"piotroski", "dupont", "cash_quality"}


def test_render_is_readable_and_explicit():
    text = render_for_prompt(build_quality_metrics(GOOD))
    assert "Piotroski F-Score" in text
    assert "DuPont ROE" in text
    assert "Cash conversion" in text
    assert "PASS" in text or "FAIL" in text


def test_render_says_unavailable_rather_than_omitting():
    text = render_for_prompt(build_quality_metrics({}))
    assert "unavailable" in text.lower()


def test_render_handles_no_metrics():
    assert "unavailable" in render_for_prompt(None).lower()


def test_agents_receive_computed_metrics():
    """The agents must interpret these, not derive them — a model asked to
    compute a Piotroski score produces something plausible and unverifiable."""
    agents = Path(__file__).resolve().parent.parent / "agents"
    for name in ("financial_analyst.py", "risk_analyst.py"):
        src = (agents / name).read_text()
        assert "{quality_metrics}" in src, f"{name} prompt lacks the block"
        assert "render_quality" in src, f"{name} does not render it"
