"""Benchmark-relative context: "compared to what?".

Nothing in the output answered the most common question about any equity call.
"Down 8%" is not a verdict input; "down 8% while its sector is down 15%" is.

Pure functions only — the NSE/yfinance fetching lives in `market_data.py`, so
the maths here is unit-testable without a network.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Approximate trading sessions per window. NSE runs ~250 sessions a year.
PERIODS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 250}

# Sector -> NSE index. Keyed on substrings because two vocabularies reach us:
# Screener's taxonomy ("Information Technology", "Fast Moving Consumer Goods")
# and yfinance's ("Technology", "Consumer Defensive"). Order matters — the first
# match wins, so the more specific phrases are listed first.
SECTOR_INDEX_RULES = (
    ("information technology", "NIFTY IT"),
    ("technology", "NIFTY IT"),
    ("software", "NIFTY IT"),
    ("private sector bank", "NIFTY PVT BANK"),
    ("public sector bank", "NIFTY PSU BANK"),
    ("bank", "NIFTY BANK"),
    ("financial services", "NIFTY FIN SERVICE"),
    ("finance", "NIFTY FIN SERVICE"),
    ("insurance", "NIFTY FIN SERVICE"),
    ("fast moving consumer goods", "NIFTY FMCG"),
    ("consumer defensive", "NIFTY FMCG"),
    ("fmcg", "NIFTY FMCG"),
    ("healthcare", "NIFTY PHARMA"),
    ("pharma", "NIFTY PHARMA"),
    ("automobile", "NIFTY AUTO"),
    ("auto", "NIFTY AUTO"),
    ("metal", "NIFTY METAL"),
    ("mining", "NIFTY METAL"),
    ("basic materials", "NIFTY METAL"),
    ("oil", "NIFTY ENERGY"),
    ("gas", "NIFTY ENERGY"),
    ("energy", "NIFTY ENERGY"),
    ("power", "NIFTY ENERGY"),
    ("utilities", "NIFTY ENERGY"),
    ("realty", "NIFTY REALTY"),
    ("real estate", "NIFTY REALTY"),
    ("media", "NIFTY MEDIA"),
    ("entertainment", "NIFTY MEDIA"),
    ("telecom", "NIFTY IND DIGITAL"),
    ("communication", "NIFTY IND DIGITAL"),
    ("infrastructure", "NIFTY INFRA"),
    ("construction", "NIFTY INFRA"),
    ("capital goods", "NIFTY INFRA"),
    ("industrials", "NIFTY INFRA"),
    ("consumer cyclical", "NIFTY CONSUMPTION"),
    ("consumer durables", "NIFTY CONSUMPTION"),
    ("services", "NIFTY SERV SECTOR"),
    ("chemical", "NIFTY COMMODITIES"),
    ("commodities", "NIFTY COMMODITIES"),
)

BENCHMARK_INDEX = "NIFTY 50"


def map_sector_to_index(sector: Optional[str], industry: Optional[str] = None) -> Optional[str]:
    """Best NSE sectoral index for a company, or None when unmappable.

    Industry is checked first: it is more specific, so "Private Sector Bank"
    routes to NIFTY PVT BANK rather than the broader NIFTY BANK.
    """
    for source in (industry, sector):
        if not source:
            continue
        text = str(source).strip().lower()
        for needle, index in SECTOR_INDEX_RULES:
            if needle in text:
                return index
    return None


def period_return_pct(series, sessions: int) -> Optional[float]:
    """Percent return over the last `sessions` trading days.

    None when the series is too short — an under-covered window would otherwise
    report a partial-period move as if it were a full one.
    """
    if series is None or len(series) < sessions + 1:
        return None
    try:
        start = float(series.iloc[-(sessions + 1)])
        end = float(series.iloc[-1])
    except (IndexError, ValueError, TypeError):
        return None
    if not start:
        return None
    return round((end - start) / start * 100.0, 2)


def compute_relative_strength(stock_close, benchmark_close) -> Dict[str, Any]:
    """Stock vs benchmark returns per window, plus the excess.

    `excess_pct` is the number that matters: it separates a company falling with
    its market from one falling on its own.
    """
    out: Dict[str, Any] = {}
    for label, sessions in PERIODS.items():
        stock = period_return_pct(stock_close, sessions)
        bench = period_return_pct(benchmark_close, sessions)
        excess = round(stock - bench, 2) if (stock is not None and bench is not None) else None
        out[label] = {"stock_pct": stock, "benchmark_pct": bench, "excess_pct": excess}
    return out


def compute_alpha(
    stock_return_pct: Optional[float],
    market_return_pct: Optional[float],
    beta: Optional[float],
    risk_free_pct: float,
) -> Optional[float]:
    """Annual CAPM alpha in percentage points.

        alpha = R_stock - [ rf + beta · (R_market - rf) ]

    Requires a real beta. Phase A made beta None when it cannot be measured, and
    alpha inherits that: computing it against a fabricated beta of 1.0 would
    just be the excess return wearing a more authoritative name.
    """
    if stock_return_pct is None or market_return_pct is None or beta is None:
        return None
    expected = risk_free_pct + beta * (market_return_pct - risk_free_pct)
    return round(stock_return_pct - expected, 2)


def classify_vix(vix: Optional[float]) -> Dict[str, Any]:
    """India VIX into a regime label.

    Bands follow where India VIX actually spends its time: low teens in calm
    markets, high teens when nervous, 25+ only in genuine stress.
    """
    if vix is None:
        return {"india_vix": None, "regime": "unknown",
                "note": "India VIX unavailable"}
    if vix < 13:
        regime, note = "calm", "Low volatility expectations; trend-following setups favoured"
    elif vix < 18:
        regime, note = "normal", "Typical volatility; no regime adjustment warranted"
    elif vix < 25:
        regime, note = "elevated", "Nervous market; size positions down and widen stops"
    else:
        regime, note = "stressed", "Crisis-level volatility; directional calls carry low confidence"
    return {"india_vix": round(float(vix), 2), "regime": regime, "note": note}


def summarise_index(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The decision-relevant slice of an NSE index record."""
    if not row:
        return {}
    def num(key):
        try:
            return float(row.get(key)) if row.get(key) is not None else None
        except (TypeError, ValueError):
            return None
    return {
        "symbol": row.get("indexSymbol"),
        "last": num("last"),
        "change_pct_today": num("percentChange"),
        "change_pct_30d": num("perChange30d"),
        "change_pct_365d": num("perChange365d"),
        "pe": num("pe"),
        "pb": num("pb"),
        "dividend_yield": num("dy"),
        "year_high": num("yearHigh"),
        "year_low": num("yearLow"),
    }


def build_relative_context(
    stock_close,
    benchmark_close,
    indices_by_symbol: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    sector: Optional[str] = None,
    industry: Optional[str] = None,
    beta: Optional[float] = None,
    risk_free_pct: float = 6.5,
) -> Dict[str, Any]:
    """Everything the agents need to answer "compared to what?"."""
    indices_by_symbol = indices_by_symbol or {}

    relative = compute_relative_strength(stock_close, benchmark_close)
    one_year = relative.get("1Y", {})
    alpha = compute_alpha(
        one_year.get("stock_pct"), one_year.get("benchmark_pct"), beta, risk_free_pct
    )

    sector_index_symbol = map_sector_to_index(sector, industry)
    sector_index = summarise_index(indices_by_symbol.get(sector_index_symbol)) \
        if sector_index_symbol else {}

    # Stock vs its SECTOR, not just vs the market. NSE publishes 30d/365d moves
    # per index, so no extra history fetch is needed.
    sector_relative: Dict[str, Any] = {}
    if sector_index:
        for label, nse_key in (("1M", "change_pct_30d"), ("1Y", "change_pct_365d")):
            stock_pct = relative.get(label, {}).get("stock_pct")
            index_pct = sector_index.get(nse_key)
            sector_relative[label] = {
                "stock_pct": stock_pct,
                "sector_pct": index_pct,
                "excess_pct": round(stock_pct - index_pct, 2)
                if (stock_pct is not None and index_pct is not None) else None,
            }

    vix_row = indices_by_symbol.get("INDIA VIX") or {}
    try:
        vix_value = float(vix_row.get("last")) if vix_row.get("last") is not None else None
    except (TypeError, ValueError):
        vix_value = None

    return {
        "vs_benchmark": relative,
        "benchmark_index": summarise_index(indices_by_symbol.get(BENCHMARK_INDEX)),
        "sector_index_symbol": sector_index_symbol,
        "sector_index": sector_index,
        "vs_sector": sector_relative,
        "alpha_1y_pct": alpha,
        "volatility_regime": classify_vix(vix_value),
    }


def render_for_prompt(context: Optional[Dict[str, Any]]) -> str:
    """Human-readable block for the analyst prompts.

    States the comparison explicitly rather than leaving the model to infer it,
    and says "unavailable" where a number is genuinely missing — an agent that
    is told nothing will invent something.
    """
    if not context:
        return "Relative performance data unavailable."

    lines = []
    vs_bench = context.get("vs_benchmark") or {}
    bench = context.get("benchmark_index") or {}
    bench_name = bench.get("symbol") or "NIFTY 50"

    rows = []
    for label in ("1M", "3M", "6M", "1Y"):
        window = vs_bench.get(label) or {}
        stock, index, excess = window.get("stock_pct"), window.get("benchmark_pct"), window.get("excess_pct")
        if stock is None and index is None:
            continue
        rows.append(
            f"  {label:<4} stock {stock if stock is not None else 'n/a':>8}%   "
            f"{bench_name} {index if index is not None else 'n/a':>8}%   "
            f"excess {excess if excess is not None else 'n/a':>8}%"
        )
    if rows:
        lines.append(f"Versus {bench_name}:")
        lines.extend(rows)
    else:
        lines.append(f"Versus {bench_name}: unavailable")

    sector_index = context.get("sector_index") or {}
    vs_sector = context.get("vs_sector") or {}
    if sector_index and vs_sector:
        name = sector_index.get("symbol")
        lines.append(f"Versus sector index {name}:")
        for label in ("1M", "1Y"):
            window = vs_sector.get(label) or {}
            stock, index, excess = window.get("stock_pct"), window.get("sector_pct"), window.get("excess_pct")
            if stock is None and index is None:
                continue
            lines.append(
                f"  {label:<4} stock {stock if stock is not None else 'n/a':>8}%   "
                f"{name} {index if index is not None else 'n/a':>8}%   "
                f"excess {excess if excess is not None else 'n/a':>8}%"
            )
        if sector_index.get("pe") is not None:
            lines.append(f"  sector index P/E {sector_index['pe']}, "
                         f"P/B {sector_index.get('pb')}, yield {sector_index.get('dividend_yield')}%")
    else:
        lines.append("Versus sector index: no sectoral index mapped for this company")

    alpha = context.get("alpha_1y_pct")
    lines.append(
        f"CAPM alpha (1Y): {alpha}%" if alpha is not None
        else "CAPM alpha (1Y): unavailable (requires a measured beta)"
    )

    regime = context.get("volatility_regime") or {}
    if regime.get("india_vix") is not None:
        lines.append(f"India VIX {regime['india_vix']} — regime {regime['regime'].upper()}. {regime.get('note','')}")
    else:
        lines.append("India VIX: unavailable")

    return "\n".join(lines)
