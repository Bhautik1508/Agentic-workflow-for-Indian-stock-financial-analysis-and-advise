"""Phase A — stop reporting numbers that are not measurements.

Covers the three defects from DATA_QUALITY_PLAN.md §1: a beta measured against
the stock itself, an Altman veto that could never fire, and a risk-free rate
hardcoded in two places.
"""

import asyncio

import pandas as pd
import pytest

from data.market_data import _close_by_date, fetch_risk_data, risk_free_rate_pct
from scoring.altman import DISTRESS_BELOW, SAFE_ABOVE, compute_altman_z, is_financial


def _series(n=260, start=100.0, step=1.0, start_date="2025-01-01"):
    dates = pd.bdate_range(start=start_date, periods=n)
    return pd.DataFrame({
        "Date": [d.strftime("%Y-%m-%d") for d in dates],
        "Close": [start + i * step for i in range(n)],
        "High": [start + i * step + 1 for i in range(n)],
        "Low": [start + i * step - 1 for i in range(n)],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Date alignment — the reason beta was still wrong after the first fix
# ─────────────────────────────────────────────────────────────────────────────

def test_close_by_date_uses_the_local_calendar_date():
    """yfinance stamps Indian daily bars midnight IST. Converting to UTC gives
    18:30 the PREVIOUS day, which shifted every stock date one day behind the
    benchmark and collapsed correlation toward zero."""
    frame = pd.DataFrame({"Date": ["2025-09-12 00:00:00+05:30"], "Close": [100.0]})
    series = _close_by_date(frame)
    assert series.index[0].strftime("%Y-%m-%d") == "2025-09-12"


def test_close_by_date_handles_naive_dates():
    frame = pd.DataFrame({"Date": ["2025-09-12"], "Close": [100.0]})
    assert _close_by_date(frame).index[0].strftime("%Y-%m-%d") == "2025-09-12"


def test_close_by_date_aligns_tz_aware_with_naive():
    """The real pairing: stock is tz-aware, benchmark is naive. They must join."""
    stock = _close_by_date(pd.DataFrame(
        {"Date": ["2025-09-12 00:00:00+05:30", "2025-09-15 00:00:00+05:30"], "Close": [1.0, 2.0]}))
    bench = _close_by_date(pd.DataFrame(
        {"Date": ["2025-09-12", "2025-09-15"], "Close": [10.0, 11.0]}))
    joined = pd.DataFrame({"s": stock, "b": bench}).dropna()
    assert len(joined) == 2, "tz-aware and naive dates for the same session must align"


def test_close_by_date_on_empty_input():
    assert _close_by_date(pd.DataFrame()).empty


# ─────────────────────────────────────────────────────────────────────────────
# Beta
# ─────────────────────────────────────────────────────────────────────────────

def test_beta_is_not_reported_when_benchmark_is_the_stock_itself():
    """The original defect: runner passed the stock's own history as the
    benchmark, so cov(x,x)/var(x) = 1.00 for every company, always."""
    stock = _series()
    result = asyncio.run(fetch_risk_data("X.NS", stock, stock.copy()))
    assert result.get("beta") is None, "a self-benchmark must yield no beta, not 1.0"


def test_beta_is_none_without_a_benchmark():
    result = asyncio.run(fetch_risk_data("X.NS", _series(), None))
    assert result.get("beta") is None
    assert result.get("benchmark_symbol") is None


def test_beta_is_computed_against_a_real_benchmark():
    stock = _series(step=2.0)
    bench = _series(step=1.0, start=200.0)
    # Perturb the stock so the two are not perfectly collinear.
    stock["Close"] = [c + (i % 7) * 3 for i, c in enumerate(stock["Close"])]
    result = asyncio.run(fetch_risk_data("X.NS", stock, bench))
    assert result.get("beta") is not None
    assert result.get("benchmark_symbol") == "^NSEI"
    assert result.get("beta_sample_days", 0) > 200


def test_beta_not_computed_on_a_thin_overlap():
    """20 shared days is not a beta; reporting one would invent precision."""
    stock = _series()
    bench = _series(n=20)
    result = asyncio.run(fetch_risk_data("X.NS", stock, bench))
    assert result.get("beta") is None


# ─────────────────────────────────────────────────────────────────────────────
# Risk-free rate
# ─────────────────────────────────────────────────────────────────────────────

def test_risk_free_rate_default(monkeypatch):
    monkeypatch.delenv("RISK_FREE_RATE_PCT", raising=False)
    assert risk_free_rate_pct() == 6.50


def test_risk_free_rate_env_override(monkeypatch):
    monkeypatch.setenv("RISK_FREE_RATE_PCT", "7.25")
    assert risk_free_rate_pct() == 7.25


@pytest.mark.parametrize("bad", ["900", "-5", "not-a-number", ""])
def test_risk_free_rate_rejects_nonsense(monkeypatch, bad):
    """A typo must not silently warp every Sharpe ratio in the system."""
    monkeypatch.setenv("RISK_FREE_RATE_PCT", bad)
    assert risk_free_rate_pct() == 6.50


def test_repo_rate_and_sharpe_share_one_source(monkeypatch):
    """These were two independent hardcoded 6.5s, free to drift apart."""
    from data.market_data import fetch_rbi_repo_rate

    monkeypatch.setenv("RISK_FREE_RATE_PCT", "6.00")
    assert fetch_rbi_repo_rate()["repo_rate"] == risk_free_rate_pct()


def test_risk_payload_reports_the_rate_it_used():
    result = asyncio.run(fetch_risk_data("X.NS", _series(), None))
    assert result.get("risk_free_rate_pct") == risk_free_rate_pct()


# ─────────────────────────────────────────────────────────────────────────────
# Altman Z
# ─────────────────────────────────────────────────────────────────────────────

HEALTHY = {
    "bs_Total Liabilities": {"Mar 2026": "100000"},
    "bs_Reserves": {"Mar 2026": "60000"},
    "bs_Equity Capital": {"Mar 2026": "5000"},
    "bs_Borrowings\xa0+": {"Mar 2026": "10000"},
    "bs_Other Liabilities\xa0+": {"Mar 2026": "25000"},
    "pl_Operating Profit": {"Mar 2026": "20000"},
    "pl_Sales\xa0+": {"Mar 2026": "80000"},
    "ratio_Working Capital Days": {"Mar 2026": "60"},
}


def test_altman_computes_for_a_non_financial():
    r = compute_altman_z(HEALTHY, sector="Technology")
    assert r.score is not None
    assert r.zone in {"safe", "grey", "distress"}
    assert r.veto_eligible is True


def test_altman_zone_boundaries():
    assert DISTRESS_BELOW < SAFE_ABOVE
    r = compute_altman_z(HEALTHY, sector="Technology")
    expected = ("distress" if r.score < DISTRESS_BELOW
                else "safe" if r.score > SAFE_ABOVE else "grey")
    assert r.zone == expected


def test_altman_refuses_financials():
    """A bank's balance sheet breaks the model's assumptions; it would score as
    permanently distressed."""
    r = compute_altman_z(HEALTHY, sector="Banking")
    assert r.score is None
    assert "financial" in r.reason.lower()


def test_altman_unknown_sector_is_reported_but_not_veto_eligible():
    """A false forced SELL on a healthy bank is worse than a missing signal."""
    r = compute_altman_z(HEALTHY)
    assert r.score is not None
    assert r.veto_eligible is False
    assert "unknown" in r.reason.lower()


def test_altman_returns_none_with_missing_inputs():
    r = compute_altman_z({}, sector="Technology")
    assert r.score is None
    assert r.reason


def test_altman_tolerates_screener_nbsp_keys():
    """Screener labels carry a non-breaking space — the bug that made CAGR
    'N/A' in every prompt ever sent."""
    r = compute_altman_z(HEALTHY, sector="Technology")
    assert r.components["ebit_proxy_operating_profit"] == 20000.0
    assert r.components["borrowings"] == 10000.0


def test_altman_records_its_proxies():
    """Reserves stand in for retained earnings and operating profit for EBIT;
    the component names say so rather than hiding it."""
    r = compute_altman_z(HEALTHY, sector="Technology")
    assert "retained_earnings_proxy_reserves" in r.components
    assert "ebit_proxy_operating_profit" in r.components
    assert "working_capital_derived" in r.components


@pytest.mark.parametrize("sector,expected", [
    ("Banking", True), ("NBFC", True), ("Insurance", True),
    ("Housing Finance", True), ("Technology", False), ("FMCG", False), (None, None),
])
def test_is_financial_classification(sector, expected):
    assert is_financial(sector) is expected
