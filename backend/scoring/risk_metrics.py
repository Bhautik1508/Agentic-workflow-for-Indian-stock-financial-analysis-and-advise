"""Risk measures that Sharpe and a raw drawdown number cannot express.

Three gaps this closes:

**Sharpe punishes upside volatility.** A stock that jumps 8% on good results is
penalised exactly as much as one that falls 8%. For a BUY call that is the wrong
question, so Sortino measures deviation *below* a minimum acceptable return.

**A drawdown number has no denominator.** "-38%" is frightening in isolation and
unremarkable next to a 60% gain. Calmar divides return by pain.

**Beta is reported as a constant.** A company whose beta moved from 0.6 to 1.3
has changed what it is, and a single trailing number hides that entirely.

Pure functions — no network, no pandas-specific assumptions beyond a Series.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
MIN_SAMPLE = 30          # below this, a ratio is noise dressed as a measurement


def _finite(value: Optional[float]) -> Optional[float]:
    """Guard against inf/NaN leaking into a report as a number."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def downside_deviation(returns, mar_daily: float = 0.0) -> Optional[float]:
    """Annualised standard deviation of returns *below* the minimum acceptable
    return. None when there is no meaningful downside sample."""
    if returns is None or len(returns) < MIN_SAMPLE:
        return None
    shortfall = returns[returns < mar_daily] - mar_daily
    if len(shortfall) < 2:
        # No downside days at all is a real answer, not an error: deviation 0.
        return 0.0
    value = float((shortfall ** 2).mean() ** 0.5) * math.sqrt(TRADING_DAYS) * 100
    return _finite(round(value, 2))


def sortino_ratio(returns, risk_free_annual: float) -> Optional[float]:
    """Sharpe, but only counting downside volatility as risk."""
    if returns is None or len(returns) < MIN_SAMPLE:
        return None
    rf_daily = risk_free_annual / TRADING_DAYS
    excess_mean = float(returns.mean()) - rf_daily
    dd = downside_deviation(returns, rf_daily)
    if dd is None or dd == 0:
        return None          # undefined rather than infinite
    annual_excess = excess_mean * TRADING_DAYS * 100
    return _finite(round(annual_excess / dd, 3))


def calmar_ratio(annual_return_pct: Optional[float],
                 max_drawdown_pct: Optional[float]) -> Optional[float]:
    """Annual return divided by the worst peak-to-trough fall.

    `max_drawdown_pct` is negative as stored elsewhere in this codebase; its
    magnitude is what matters.
    """
    if annual_return_pct is None or max_drawdown_pct is None:
        return None
    depth = abs(float(max_drawdown_pct))
    if depth < 1e-9:
        return None
    return _finite(round(float(annual_return_pct) / depth, 3))


def _beta_over(stock_returns, benchmark_returns, sessions: int):
    """(beta, sample_size) over the most recent `sessions` overlapping days.

    The sample size is returned because a short history truncates BOTH windows
    to the same rows, making a 1Y and a 2Y beta identical — which would read as
    "risk profile unchanged" when it really means "there is only one window".
    """
    try:
        import pandas as pd
    except ImportError:      # pragma: no cover
        return None
    if stock_returns is None or benchmark_returns is None:
        return None, 0
    joined = pd.DataFrame({"s": stock_returns, "b": benchmark_returns}).dropna().tail(sessions)
    size = len(joined)
    if size < MIN_SAMPLE:
        return None, size
    variance = joined["b"].var()
    if not variance:
        return None, size
    # Same guard as the main beta path: a benchmark that is really the stock.
    corr = joined["s"].corr(joined["b"])
    if corr is not None and corr == corr and corr > 0.999:
        return None, size
    return _finite(round(joined.cov().iloc[0, 1] / variance, 3)), size


@dataclass
class RollingBeta:
    beta_1y: Optional[float] = None
    beta_2y: Optional[float] = None
    trend: str = "unknown"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def rolling_beta(stock_returns, benchmark_returns) -> RollingBeta:
    """Beta over one year against two, to expose a changing risk profile."""
    one, size_one = _beta_over(stock_returns, benchmark_returns, TRADING_DAYS)
    two, size_two = _beta_over(stock_returns, benchmark_returns, TRADING_DAYS * 2)

    if one is None or two is None:
        return RollingBeta(beta_1y=one, beta_2y=two, trend="unknown",
                           note="insufficient overlapping history for a comparison")

    # The longer window must actually be longer. With a short history both
    # truncate to the same rows and the two betas are trivially equal, which
    # would be reported as "unchanged" rather than "not comparable".
    if size_two < size_one * 1.2:
        # beta_2y is left unset rather than echoing the shorter window's value:
        # a 40-session figure is not a two-year beta, and a field named beta_2y
        # asserts that it is. Same discipline as volatility_1y.
        return RollingBeta(
            beta_1y=one, beta_2y=None, trend="unknown",
            note=(f"only {size_two} overlapping sessions — not enough for a two-year "
                  f"window, so no trend can be inferred"),
        )

    delta = one - two
    if abs(delta) < 0.15:
        trend, note = "stable", "risk profile unchanged over the last year"
    elif delta > 0:
        trend, note = "rising", (
            f"beta rose from {two} to {one} — the stock has become more "
            f"market-sensitive than its longer history suggests")
    else:
        trend, note = "falling", (
            f"beta fell from {two} to {one} — less market-sensitive than its "
            f"longer history suggests")
    return RollingBeta(beta_1y=one, beta_2y=two, trend=trend, note=note)


def week52_percentile(current: Optional[float], high: Optional[float],
                      low: Optional[float]) -> Optional[float]:
    """Where the price sits in its 52-week range, 0 (low) to 100 (high).

    More useful than distance-from-high alone: -20% from the high means one
    thing in a tight range and another in a range that halved.
    """
    if None in (current, high, low):
        return None
    span = float(high) - float(low)
    if span <= 0:
        return None
    pct = (float(current) - float(low)) / span * 100
    return _finite(round(max(0.0, min(100.0, pct)), 1))


@dataclass
class LiquidityProfile:
    median_daily_value_cr: Optional[float] = None
    median_daily_volume: Optional[float] = None
    thin: Optional[bool] = None
    tier: str = "unknown"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Median daily traded value, in crore. A verdict on a name you cannot exit is a
# different verdict, and `position_size_modifier` had no liquidity input at all.
THIN_CR = 5.0
MODERATE_CR = 50.0


def liquidity_profile(close, volume, sessions: int = 30) -> LiquidityProfile:
    """Median traded value over the recent window."""
    if close is None or volume is None or len(close) < 5 or len(volume) < 5:
        return LiquidityProfile(note="insufficient price/volume history")
    try:
        traded = (close * volume).tail(sessions).dropna()
        median_volume = float(volume.tail(sessions).median())
    except Exception:
        return LiquidityProfile(note="price/volume series not aligned")
    if traded.empty:
        return LiquidityProfile(note="no traded-value data")

    value_cr = float(traded.median()) / 1e7        # rupees -> crore
    if value_cr < THIN_CR:
        tier, thin = "thin", True
        note = (f"median ₹{value_cr:.1f} Cr/day — thin. Position size should be "
                f"capped regardless of conviction; exiting may move the price.")
    elif value_cr < MODERATE_CR:
        tier, thin = "moderate", False
        note = f"median ₹{value_cr:.1f} Cr/day — adequate for retail size."
    else:
        tier, thin = "deep", False
        note = f"median ₹{value_cr:.0f} Cr/day — deep liquidity, no size constraint."

    return LiquidityProfile(
        median_daily_value_cr=round(value_cr, 2),
        median_daily_volume=round(median_volume, 0),
        thin=thin, tier=tier, note=note,
    )


def vwap_relative(high, low, close, volume, window: int = 20) -> Optional[float]:
    """Percent distance of the last close from the rolling VWAP.

    Typical price × volume over `window` sessions. Positive means trading above
    the volume-weighted average — where recent buyers are in profit.
    """
    if any(x is None for x in (high, low, close, volume)) or len(close) < window:
        return None
    try:
        typical = (high + low + close) / 3.0
        pv = (typical * volume).tail(window).sum()
        vol = volume.tail(window).sum()
        if not vol:
            return None
        vwap = float(pv) / float(vol)
        if vwap <= 0:
            return None
        return _finite(round((float(close.iloc[-1]) - vwap) / vwap * 100, 2))
    except Exception:
        return None


def render_for_prompt(payload: Optional[Dict[str, Any]]) -> str:
    """Compact block for the risk prompt."""
    if not payload:
        return "Extended risk metrics unavailable."
    lines = []

    sortino = payload.get("sortino_ratio")
    dd = payload.get("downside_deviation_pct")
    lines.append(
        f"Sortino {sortino} (downside deviation {dd}%) — unlike Sharpe, counts only "
        f"downside volatility as risk"
        if sortino is not None else "Sortino: unavailable"
    )

    calmar = payload.get("calmar_ratio")
    lines.append(f"Calmar {calmar} (1Y return ÷ max drawdown)"
                 if calmar is not None else "Calmar: unavailable")

    rb = payload.get("rolling_beta") or {}
    if rb.get("beta_1y") is not None and rb.get("beta_2y") is not None:
        lines.append(f"Rolling beta: 1Y {rb['beta_1y']} vs 2Y {rb['beta_2y']} — "
                     f"{rb.get('trend')}. {rb.get('note','')}")
    else:
        lines.append(f"Rolling beta: unavailable ({rb.get('note','no data')})")

    pct = payload.get("week52_percentile")
    lines.append(f"52-week range position: {pct}th percentile (0=low, 100=high)"
                 if pct is not None else "52-week range position: unavailable")

    liq = payload.get("liquidity") or {}
    lines.append(f"Liquidity: {liq.get('note')}" if liq.get("note")
                 else "Liquidity: unavailable")

    vwap = payload.get("vwap_relative_pct")
    if vwap is not None:
        side = "above" if vwap >= 0 else "below"
        lines.append(f"Price {abs(vwap)}% {side} its 20-session VWAP")

    return "\n".join(lines)
