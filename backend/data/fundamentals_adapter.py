"""Build `fundamental_data` from several free sources, per field, with provenance.

Why this exists
---------------
`data_quality` measures `fundamental_data`, which was populated only from
yfinance — and yfinance is rate-limited from Render's IPs, so production ran at
`fundamental_completeness: 0.2` with 8 of 10 critical fields missing.

Meanwhile Screener.in was being scraped successfully **on the same run** and
already held most of those fields. Three separate faults kept them out:

1. The scraper truncated the P&L and balance sheet to five rows each, dropping
   Net Profit, EPS, Interest, Depreciation and Total Assets, and never read the
   cash-flow statement at all.
2. The extractor looked up exact keys (`"pl_Sales"`) while Screener emits
   `"pl_Sales\\xa0+"` — a non-breaking space and an expand marker.
3. Values arrive as scraped HTML (`'₹\\n  8,13,988\\n\\n  Cr.'`), which a plain
   `float()` cannot read.

All three are fixed here. Merging is **per field**, not per provider: a partial
yfinance response is topped up from Screener rather than discarded wholesale,
which is what "first provider with any data wins" would have done.

Every field records where it came from, so a scraped estimate is never mistaken
for an official figure.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from data.screener_summary import find_row, normalize_key

logger = logging.getLogger(__name__)

CRORE = 1e7          # 1 crore = 10,000,000
LAKH_CRORE = 1e12


def parse_number(value: Any) -> Optional[float]:
    """Parse a Screener-scraped figure into a float.

    Handles the currency symbol, Indian digit grouping, percent signs, unit
    suffixes and the newline/non-breaking-space soup that comes out of the HTML.
    Returns None rather than guessing when there is no number present.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).replace("\xa0", " ")
    text = " ".join(text.split())                 # collapse scrape whitespace
    if not text or text in {"-", "--", "N/A", "NA", ""}:
        return None

    multiplier = 1.0
    lowered = text.lower()
    if "lakh cr" in lowered or "lakh crore" in lowered:
        multiplier = LAKH_CRORE
    elif re.search(r"\bcr\b|\bcrore\b|cr\.", lowered):
        multiplier = CRORE

    # Match the first numeric token rather than deleting non-digits: stripping
    # characters turns "2.5 Lakh Cr." into "2.5." (the period from "Cr."),
    # which float() then rejects.
    match = re.search(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group()) * multiplier
    except ValueError:
        return None


def _latest(row: Optional[Dict[str, Any]]) -> Optional[float]:
    """Most recent value of a year-keyed Screener row."""
    if not row:
        return None

    def year_of(label: str) -> int:
        try:
            return int(str(label).split()[-1])
        except (ValueError, IndexError):
            return 0

    for period in sorted(row.keys(), key=year_of, reverse=True):
        value = parse_number(row[period])
        if value is not None:
            return value
    return None


def _yoy(row: Optional[Dict[str, Any]]) -> Optional[float]:
    """Year-on-year growth as a decimal (0.12 = +12%)."""
    if not row or len(row) < 2:
        return None

    def year_of(label: str) -> int:
        try:
            return int(str(label).split()[-1])
        except (ValueError, IndexError):
            return 0

    periods = sorted(row.keys(), key=year_of)
    current, previous = parse_number(row[periods[-1]]), parse_number(row[periods[-2]])
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous)


def _headline(screener: Dict[str, Any], *names: str) -> Optional[float]:
    """A top-of-page scalar, matched tolerantly."""
    wanted = {normalize_key(n) for n in names}
    for key, value in screener.items():
        if isinstance(value, dict):
            continue
        if normalize_key(key) in wanted:
            return parse_number(value)
    return None


def extract_from_screener(screener: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Map a Screener payload onto the field names `fundamental_data` uses."""
    if not screener:
        return {}

    out: Dict[str, Any] = {}

    # ── Sector / industry (scraped from Screener's own taxonomy) ──
    for field in ("sector", "industry"):
        value = screener.get(field)
        if isinstance(value, str) and value.strip():
            out[field] = value.strip()

    # ── Headline scalars ──
    out["pe_ratio"] = _headline(screener, "Stock P/E", "P/E")
    out["book_value"] = _headline(screener, "Book Value")
    mcap_cr = _headline(screener, "Market Cap")
    if mcap_cr is not None:
        # _headline already applied the crore multiplier from the "Cr." suffix.
        out["market_cap"] = mcap_cr
    roe_pct = _headline(screener, "ROE")
    if roe_pct is not None:
        out["roe"] = roe_pct / 100.0
    roce_pct = _headline(screener, "ROCE")
    if roce_pct is not None:
        out["roce"] = roce_pct / 100.0
    dy = _headline(screener, "Dividend Yield")
    if dy is not None:
        out["dividend_yield"] = dy / 100.0

    # ── Profit & loss (available only since the scraper stopped truncating) ──
    sales = find_row(screener, "pl_Sales", "pl_Revenue")
    net_profit = find_row(screener, "pl_Net Profit", "pl_Profit after tax")
    operating_profit = find_row(screener, "pl_Operating Profit")
    opm = find_row(screener, "pl_OPM %")
    interest = find_row(screener, "pl_Interest")
    depreciation = find_row(screener, "pl_Depreciation")
    eps = find_row(screener, "pl_EPS in Rs")

    out["revenue_growth"] = _yoy(sales)
    out["earnings_growth"] = _yoy(net_profit)
    out["eps"] = _latest(eps)
    out["depreciation"] = _latest(depreciation)

    latest_sales, latest_np = _latest(sales), _latest(net_profit)
    if latest_sales and latest_np is not None:
        out["profit_margins"] = latest_np / latest_sales

    # Screener subtracts interest and depreciation AFTER "Operating Profit", so
    # that line is EBITDA and OPM% is the EBITDA margin — not an approximation.
    opm_latest = _latest(opm)
    if opm_latest is not None:
        out["ebitda_margin"] = opm_latest / 100.0
        out["operating_margins"] = opm_latest / 100.0
    out["ebitda"] = _latest(operating_profit)

    op_latest, int_latest = _latest(operating_profit), _latest(interest)
    if op_latest is not None and int_latest:
        out["interest_coverage"] = op_latest / int_latest

    # ── Balance sheet ──
    equity_capital = _latest(find_row(screener, "bs_Equity Capital"))
    reserves = _latest(find_row(screener, "bs_Reserves"))
    borrowings = _latest(find_row(screener, "bs_Borrowings"))
    total_assets = _latest(find_row(screener, "bs_Total Assets")) \
        or _latest(find_row(screener, "bs_Total Liabilities"))

    out["total_debt"] = borrowings
    out["total_assets"] = total_assets
    if equity_capital is not None or reserves is not None:
        equity = (equity_capital or 0.0) + (reserves or 0.0)
        out["total_equity"] = equity
        if equity and borrowings is not None:
            out["debt_to_equity"] = borrowings / equity

    # ── Cash flow (section was never scraped before) ──
    out["free_cashflow"] = _latest(find_row(screener, "cf_Free Cash Flow"))
    out["operating_cashflow"] = _latest(find_row(screener, "cf_Cash from Operating Activity"))

    return {k: v for k, v in out.items() if v is not None}


def screener_only_fields(screener: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Screener-derived fundamentals, crore-scaled — what production falls back
    to when yfinance is rate-limited."""
    return scale_crore_fields(extract_from_screener(screener))


# Fields whose Screener values are in crore and must be scaled to match
# yfinance's raw-rupee convention before they can be compared or merged.
_CRORE_SCALED = (
    "total_debt", "total_assets", "total_equity", "ebitda",
    "free_cashflow", "operating_cashflow", "depreciation",
)


def scale_crore_fields(values: Dict[str, Any]) -> Dict[str, Any]:
    """Screener reports these in crore; yfinance reports raw rupees."""
    out = dict(values)
    for field in _CRORE_SCALED:
        if out.get(field) is not None:
            out[field] = out[field] * CRORE
    return out


def merge_fundamentals(
    sources: List[Tuple[str, Dict[str, Any]]],
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Merge sources **per field**, in priority order, recording provenance.

    `sources` is [(name, values), ...] most-trusted first. For each field the
    first source with a usable value wins; later sources fill the gaps rather
    than being discarded because an earlier source answered at all.

    Returns (merged, provenance) where provenance maps field -> source name.
    """
    merged: Dict[str, Any] = {}
    provenance: Dict[str, str] = {}

    for name, values in sources:
        if not values:
            continue
        for field, value in values.items():
            if value is None or field in merged:
                continue
            # An empty string is absence wearing a value's clothes.
            if isinstance(value, str) and not value.strip():
                continue
            merged[field] = value
            provenance[field] = name

    return merged, provenance
