"""Compact, tolerant rendering of the Screener.in payload for prompts.

Two problems this solves.

**Size.** The financial agent pasted the whole payload in via
`json.dumps(screener, indent=2)` — ~1,400 tokens of 12-year series for TCS, and
unbounded in principle, since it grows with however many rows Screener returns.

**Key drift.** Screener's row labels carry a non-breaking space and a trailing
marker: the Sales row arrives as `pl_Sales\\xa0+`, not `pl_Sales`. Every lookup
of the form `screener.get("pl_Sales")` therefore returned None, and Revenue
CAGR / Profit CAGR rendered as "N/A" in every prompt the system has ever sent.
Matching is normalised here so that cannot recur.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Rows worth showing. Everything else is noise for a valuation judgement.
# (display label, candidate Screener names in priority order)
WANTED_ROWS: List[Tuple[str, Tuple[str, ...]]] = [
    ("Sales",            ("pl_Sales", "pl_Revenue")),
    ("Operating Profit", ("pl_Operating Profit",)),
    ("OPM %",            ("pl_OPM %",)),
    ("Net Profit",       ("pl_Net Profit", "pl_Profit after tax", "pl_PAT")),
    ("ROCE %",           ("ratio_ROCE %", "ratio_ROCE")),
    ("ROE %",            ("ratio_ROE %", "ratio_ROE")),
    ("Debtor Days",      ("ratio_Debtor Days",)),
    ("Borrowings",       ("bs_Borrowings",)),
    ("Reserves",         ("bs_Reserves",)),
]

# Single-value headline stats Screener puts at the top of the page.
HEADLINE_KEYS = (
    "Market Cap", "Current Price", "Stock P/E", "Book Value",
    "Dividend Yield", "ROCE", "ROE", "Face Value", "High / Low",
)

DEFAULT_MAX_YEARS = 6


def clean_value(value: Any) -> str:
    """Collapse scrape whitespace. Screener's headline figures arrive straight
    out of the HTML as '₹\n  7,96,269\n\n  Cr.', which wastes tokens and reads
    badly in a prompt."""
    return " ".join(str(value).replace("\xa0", " ").split())


def normalize_key(key: str) -> str:
    """Fold the variants Screener emits onto one comparable form.

    Handles the non-breaking space, the trailing '+' (Screener's expand marker)
    and a trailing '%', none of which are part of the row's identity.
    """
    text = str(key).replace("\xa0", " ").strip()
    text = text.rstrip("+").strip()
    text = text.rstrip("%").strip()
    return " ".join(text.split()).lower()


def find_row(screener: Dict[str, Any], *candidates: str) -> Optional[Dict[str, Any]]:
    """Return the first year-keyed row matching any candidate name."""
    if not isinstance(screener, dict):
        return None
    normalized = {normalize_key(k): v for k, v in screener.items()}
    for candidate in candidates:
        value = normalized.get(normalize_key(candidate))
        if isinstance(value, dict) and value:
            return value
    return None


def _sorted_periods(row: Dict[str, Any]) -> List[str]:
    """Screener keys look like 'Mar 2021'. Sort by trailing year when possible."""
    def sort_key(label: str):
        parts = str(label).split()
        try:
            return (int(parts[-1]), label)
        except (ValueError, IndexError):
            return (0, label)
    return sorted(row.keys(), key=sort_key)


def compute_cagr(row: Optional[Dict[str, Any]], n_years: int = 5) -> str:
    """CAGR over the last `n_years` of a year-keyed row."""
    if not row:
        return "N/A"
    periods = _sorted_periods(row)
    if len(periods) < 2:
        return "N/A"
    start_idx = max(0, len(periods) - n_years - 1)
    span = len(periods) - 1 - start_idx
    if span <= 0:
        return "N/A"
    try:
        latest = float(str(row[periods[-1]]).replace(",", "").replace("%", ""))
        start = float(str(row[periods[start_idx]]).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return "N/A"
    if start <= 0 or latest <= 0:
        return "N/A"
    return f"{((latest / start) ** (1 / span) - 1) * 100:.1f}%"


def latest_value(row: Optional[Dict[str, Any]]) -> str:
    if not row:
        return "N/A"
    periods = _sorted_periods(row)
    return str(row[periods[-1]]) if periods else "N/A"


def summarize_screener(
    screener: Dict[str, Any],
    *,
    max_years: int = DEFAULT_MAX_YEARS,
) -> str:
    """Render the rows the prompt actually reasons about, last `max_years` only.

    Replaces a full `json.dumps(..., indent=2)`: same decision-relevant content,
    a fraction of the tokens, and stable in size as Screener adds history.
    """
    if not isinstance(screener, dict) or not screener:
        return "No Screener data."

    lines: List[str] = []

    headline = [
        f"{key}: {clean_value(screener[key])}"
        for key in HEADLINE_KEYS
        if isinstance(screener.get(key), str) and clean_value(screener.get(key))
    ]
    if headline:
        lines.append(" | ".join(headline))

    for label, candidates in WANTED_ROWS:
        row = find_row(screener, *candidates)
        if not row:
            continue
        periods = _sorted_periods(row)[-max_years:]
        series = "  ".join(f"{p.split()[-1]}:{clean_value(row[p])}" for p in periods)
        lines.append(f"{label}: {series}")

    return "\n".join(lines) if lines else "No Screener data."
