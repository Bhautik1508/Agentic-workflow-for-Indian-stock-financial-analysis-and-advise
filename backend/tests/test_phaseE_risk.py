"""Phase E — risk measures Sharpe and a bare drawdown cannot express."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scoring.risk_metrics import (
    MIN_SAMPLE,
    calmar_ratio,
    downside_deviation,
    liquidity_profile,
    render_for_prompt,
    rolling_beta,
    sortino_ratio,
    vwap_relative,
    week52_percentile,
)


def _returns(n=400, mu=0.0005, sigma=0.015, seed=7):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mu, sigma, n))


# ─────────────────────────────────────────────────────────────────────────────
# Sortino / downside deviation
# ─────────────────────────────────────────────────────────────────────────────

def test_sortino_ignores_upside_volatility():
    """The point of Sortino: a series with violent UPSIDE spikes is not riskier
    than a calm one, though Sharpe would say otherwise."""
    calm = pd.Series([0.001] * 200)
    spiky = pd.Series(([0.001] * 190) + ([0.08] * 10))     # upside only
    assert downside_deviation(spiky) == 0.0
    assert downside_deviation(calm) == 0.0


def test_downside_deviation_responds_to_losses():
    losses = pd.Series(([0.001] * 150) + ([-0.05] * 50))
    assert downside_deviation(losses) > 0


def test_sortino_none_on_thin_sample():
    assert sortino_ratio(_returns(n=MIN_SAMPLE - 1), 0.065) is None


def test_sortino_none_when_no_downside():
    """Undefined, not infinite — a ratio with a zero denominator is not a number
    to put in front of a user."""
    assert sortino_ratio(pd.Series([0.01] * 100), 0.0) is None


def test_sortino_is_finite():
    value = sortino_ratio(_returns(), 0.065)
    assert value is not None and np.isfinite(value)


# ─────────────────────────────────────────────────────────────────────────────
# Calmar
# ─────────────────────────────────────────────────────────────────────────────

def test_calmar_divides_return_by_drawdown():
    assert calmar_ratio(18.0, -38.0) == pytest.approx(18 / 38, rel=1e-3)


def test_calmar_handles_negative_drawdown_sign():
    """Drawdown is stored negative elsewhere; magnitude is what matters."""
    assert calmar_ratio(20.0, -40.0) == calmar_ratio(20.0, 40.0)


@pytest.mark.parametrize("ret,dd", [(None, -30.0), (10.0, None), (10.0, 0.0)])
def test_calmar_none_when_undefined(ret, dd):
    assert calmar_ratio(ret, dd) is None


# ─────────────────────────────────────────────────────────────────────────────
# Rolling beta
# ─────────────────────────────────────────────────────────────────────────────

def test_rolling_beta_detects_a_rising_profile():
    """A company whose beta moved has changed what it is; a single trailing
    number hides that."""
    rng = np.random.default_rng(3)
    market = pd.Series(rng.normal(0, 0.01, 600))
    old = market.iloc[:350] * 0.5 + rng.normal(0, 0.002, 350)
    new = market.iloc[350:] * 1.8 + rng.normal(0, 0.002, 250)
    stock = pd.concat([old, new]).reset_index(drop=True)
    result = rolling_beta(stock, market.reset_index(drop=True))
    assert result.beta_1y > result.beta_2y
    assert result.trend == "rising"
    assert result.note


def test_rolling_beta_stable_when_unchanged():
    rng = np.random.default_rng(5)
    market = pd.Series(rng.normal(0, 0.01, 600))
    stock = market * 0.9 + rng.normal(0, 0.001, 600)
    assert rolling_beta(stock, market).trend == "stable"


def test_rolling_beta_unknown_on_short_history():
    r = rolling_beta(_returns(n=40), _returns(n=40, seed=2))
    assert r.trend == "unknown"
    assert r.beta_2y is None


def test_rolling_beta_refuses_a_self_benchmark():
    """Same guard as the headline beta: a benchmark that is really the stock."""
    s = _returns(n=600)
    assert rolling_beta(s, s).beta_1y is None


# ─────────────────────────────────────────────────────────────────────────────
# 52-week percentile
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cur,hi,lo,expected", [
    (1000, 1500, 1000, 0.0), (1500, 1500, 1000, 100.0), (1250, 1500, 1000, 50.0),
])
def test_week52_percentile(cur, hi, lo, expected):
    assert week52_percentile(cur, hi, lo) == expected


def test_week52_percentile_clamped_and_guarded():
    assert week52_percentile(2000, 1500, 1000) == 100.0     # above the high
    assert week52_percentile(1200, 1000, 1000) is None      # zero-width range
    assert week52_percentile(None, 1500, 1000) is None


# ─────────────────────────────────────────────────────────────────────────────
# Liquidity
# ─────────────────────────────────────────────────────────────────────────────

def test_liquidity_flags_a_thin_counter():
    """A verdict on a name you cannot exit is a different verdict, and
    position_size_modifier had no liquidity input at all."""
    close = pd.Series([50.0] * 60)
    volume = pd.Series([20_000] * 60)          # ~0.1 Cr/day
    profile = liquidity_profile(close, volume)
    assert profile.thin is True
    assert profile.tier == "thin"
    assert "cap" in profile.note.lower()


def test_liquidity_recognises_depth():
    close = pd.Series([3000.0] * 60)
    volume = pd.Series([2_000_000] * 60)       # ~600 Cr/day
    profile = liquidity_profile(close, volume)
    assert profile.tier == "deep"
    assert profile.thin is False


def test_liquidity_without_data():
    p = liquidity_profile(None, None)
    assert p.median_daily_value_cr is None and p.note


# ─────────────────────────────────────────────────────────────────────────────
# VWAP
# ─────────────────────────────────────────────────────────────────────────────

def test_vwap_relative_sign():
    rising = pd.Series(np.linspace(100, 130, 60))
    vol = pd.Series([1_000_000] * 60)
    assert vwap_relative(rising * 1.01, rising * 0.99, rising, vol) > 0
    falling = pd.Series(np.linspace(130, 100, 60))
    assert vwap_relative(falling * 1.01, falling * 0.99, falling, vol) < 0


def test_vwap_none_on_short_history():
    short = pd.Series([100.0] * 5)
    assert vwap_relative(short, short, short, pd.Series([1] * 5)) is None


# ─────────────────────────────────────────────────────────────────────────────
# Windowing regressions + wiring
# ─────────────────────────────────────────────────────────────────────────────

def test_one_year_metrics_are_pinned_to_252_sessions():
    """Retaining two years of history must not silently widen metrics labelled
    '1y'. Both of these were full-series before and had to be pinned."""
    src = (Path(__file__).resolve().parent.parent / "data" / "market_data.py").read_text()
    assert "returns.tail(252).std()" in src, "volatility_1y must use a 252-session window"
    assert ".dropna().tail(252)" in src, "headline beta must use a 252-session window"


def test_risk_prompt_receives_extended_measures():
    src = (Path(__file__).resolve().parent.parent / "agents" / "risk_analyst.py").read_text()
    assert "{extended_risk}" in src
    assert "render_extended_risk" in src


def test_render_is_explicit_about_gaps():
    text = render_for_prompt({"sortino_ratio": None, "calmar_ratio": None,
                              "rolling_beta": {}, "week52_percentile": None,
                              "liquidity": {}})
    assert text.lower().count("unavailable") >= 3


def test_render_handles_no_payload():
    assert "unavailable" in render_for_prompt(None).lower()
