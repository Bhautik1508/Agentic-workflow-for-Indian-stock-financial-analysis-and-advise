"""A fixed set of tickers with expected verdict bands, to catch drift.

Why a range rather than one expected band: these are real companies whose
fundamentals move. The test is "has the engine changed its mind more than the
market did?", not "does it return exactly what it returned in May". Each case
records an acceptable band plus the tolerance in bands.

Refresh `expected_band` deliberately when a company's situation genuinely
changes — that edit is the audit trail for why the baseline moved.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .bands import band_distance, is_regression, normalize_band


@dataclass
class GoldenCase:
    ticker: str
    sector: str
    expected_band: str
    tolerance: int = 1
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Spread across sectors on purpose: a regression that only shows up in IT
# large-caps is one the fixture would otherwise miss.
GOLDEN_SET: List[GoldenCase] = [
    GoldenCase("TCS.NS", "IT", "BUY", note="Large-cap IT, high ROCE, low debt"),
    GoldenCase("INFY.NS", "IT", "BUY", note="Large-cap IT peer"),
    GoldenCase("HDFCBANK.NS", "Banking", "BUY", note="Private bank bellwether"),
    GoldenCase("ICICIBANK.NS", "Banking", "BUY"),
    GoldenCase("RELIANCE.NS", "Conglomerate", "BUY", note="Energy + retail + telecom"),
    GoldenCase("ITC.NS", "FMCG", "BUY", note="High dividend, defensive"),
    GoldenCase("HINDUNILVR.NS", "FMCG", "HOLD", note="Premium valuation"),
    GoldenCase("SUNPHARMA.NS", "Pharma", "BUY"),
    GoldenCase("DRREDDY.NS", "Pharma", "HOLD"),
    GoldenCase("MARUTI.NS", "Auto", "BUY"),
    GoldenCase("TATAMOTORS.NS", "Auto", "HOLD", tolerance=2, note="High beta, cyclical"),
    GoldenCase("LT.NS", "Infrastructure", "BUY"),
    GoldenCase("ULTRACEMCO.NS", "Cement", "HOLD"),
    GoldenCase("BHARTIARTL.NS", "Telecom", "BUY"),
    GoldenCase("ASIANPAINT.NS", "Consumer", "HOLD", note="De-rating from premium multiples"),
    GoldenCase("TITAN.NS", "Consumer", "HOLD"),
    GoldenCase("ADANIENT.NS", "Conglomerate", "HOLD", tolerance=2,
               note="Governance-sensitive; wide tolerance is deliberate"),
    GoldenCase("ZOMATO.NS", "Tech", "HOLD", tolerance=2, note="Loss-making growth name"),
]

GOLDEN_SET_PATH = os.path.join(os.path.dirname(__file__), "golden_set.json")


def load_golden_set(path: Optional[str] = None) -> List[GoldenCase]:
    """Load from JSON when present, else the built-in list. The JSON file lets
    you re-baseline without editing code."""
    target = path or GOLDEN_SET_PATH
    if os.path.exists(target):
        try:
            with open(target) as fh:
                return [GoldenCase(**row) for row in json.load(fh)]
        except (json.JSONDecodeError, OSError, TypeError):
            pass
    return list(GOLDEN_SET)


def save_golden_set(cases: List[GoldenCase], path: Optional[str] = None) -> str:
    target = path or GOLDEN_SET_PATH
    with open(target, "w") as fh:
        json.dump([c.to_dict() for c in cases], fh, indent=2)
    return target


def compare_to_golden(
    results: Dict[str, Optional[str]],
    cases: Optional[List[GoldenCase]] = None,
) -> Dict[str, Any]:
    """Compare actual verdicts (ticker -> band) against the expected set."""
    cases = cases if cases is not None else load_golden_set()
    rows: List[Dict[str, Any]] = []
    regressions = 0
    missing = 0

    for case in cases:
        actual = results.get(case.ticker)
        if actual is None:
            missing += 1
            # A run that produced no verdict is a failure, not a neutral skip.
            # Counting it only in `missing` let pass_rate report 100% while a
            # row was flagged as a regression.
            regressions += 1
            rows.append({
                "ticker": case.ticker, "sector": case.sector,
                "expected": case.expected_band, "actual": None,
                "distance": None, "regression": True, "reason": "no verdict produced",
            })
            continue
        distance = band_distance(case.expected_band, actual)
        regressed = is_regression(case.expected_band, actual, tolerance=case.tolerance)
        regressions += int(regressed)
        rows.append({
            "ticker": case.ticker, "sector": case.sector,
            "expected": case.expected_band, "actual": normalize_band(actual) or actual,
            "distance": distance, "regression": regressed,
            "reason": (f"moved {abs(distance)} bands (tolerance {case.tolerance})"
                       if regressed and distance is not None else ""),
        })

    evaluated = len(cases)
    return {
        "total": evaluated,
        "evaluated": evaluated - missing,
        "missing": missing,
        "regressions": regressions,
        "pass_rate": round((evaluated - regressions) / evaluated, 3) if evaluated else 0.0,
        "rows": rows,
    }
