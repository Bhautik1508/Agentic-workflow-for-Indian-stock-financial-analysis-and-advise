"""Evaluation harness: is the verdict engine actually any good?

Three questions, three modules:

- `bands.py`     — how far apart are two verdicts? (regression detection)
- `golden_set.py`— do known tickers still land where we expect? (drift)
- `backtest.py`  — were past verdicts right? (forward returns from the run log)

Kept free of network I/O so the logic is unit-testable; the CLI wrappers in
`scripts/` do the fetching.
"""

from .bands import BAND_ORDER, band_distance, is_regression, normalize_band
from .backtest import MIN_CREDIBLE_SAMPLE, group_by_version, score_by_cohort
from .golden_set import GOLDEN_SET, GoldenCase, compare_to_golden, load_golden_set

__all__ = [
    "BAND_ORDER", "band_distance", "is_regression", "normalize_band",
    "GOLDEN_SET", "GoldenCase", "compare_to_golden", "load_golden_set",
    "MIN_CREDIBLE_SAMPLE", "group_by_version", "score_by_cohort",
]
