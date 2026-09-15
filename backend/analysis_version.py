"""Version stamp for the analysis engine.

Why a verdict needs to record which engine produced it
------------------------------------------------------
A hit-rate computed across verdicts from different engines is not a measurement
of anything. Before Phase A, every beta was exactly 1.00, fundamental coverage
was 0.2, and there was no benchmark-relative context at all. Averaging those
verdicts together with today's would produce a number that tracks neither
engine — and would keep doing so indefinitely, since old logs never expire on
their own.

So each run records the engine version, and the backtest reports per cohort and
refuses to silently pool them.

**Bump `ANALYSIS_VERSION` whenever a change could move a verdict**: new or
corrected inputs, changed pillar weights, changed thresholds. Prompt wording
counts. Refactors that cannot change output do not.
"""

from __future__ import annotations

from typing import Dict

# Engine version. Date-prefixed so cohorts sort chronologically.
ANALYSIS_VERSION = "2026.09.15-e"

# What changed, and why a cohort boundary exists there. Read by the backtest so
# a break in the numbers can be attributed rather than guessed at.
VERSION_HISTORY: Dict[str, str] = {
    "legacy": (
        "Pre-versioning. Beta was fabricated (benchmark was the stock itself, so "
        "beta = 1.00 for every company), fundamental completeness ~0.2 because "
        "Screener data was fetched but never mapped in, no benchmark-relative "
        "context, and the Altman veto could never fire. Not comparable to later "
        "cohorts."
    ),
    "2026.09.15-a": "Phase A: real benchmark beta, Altman Z computed, single sourced risk-free rate.",
    "2026.09.15-b": "Phase B: per-field fundamentals merge; completeness 0.2 -> 0.9.",
    "2026.09.15-c": "Phase C: index/sector-relative performance, CAPM alpha, India VIX.",
    "2026.09.15-d": "Phase D: Piotroski, DuPont, cash conversion, accruals.",
    "2026.09.15-e": "Phase E: Sortino, Calmar, rolling beta, liquidity, VWAP; 1Y windows pinned.",
}


def describe(version: str) -> str:
    return VERSION_HISTORY.get(version, "unknown engine version")


def is_current(version: str) -> bool:
    return version == ANALYSIS_VERSION
