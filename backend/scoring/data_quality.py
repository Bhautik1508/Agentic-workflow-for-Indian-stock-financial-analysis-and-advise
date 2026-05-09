"""Data quality checks at the boundary between fetching and analysis.

The verdict is only as honest as the inputs. If yfinance returns mostly nulls
for a thinly-traded stock, we should refuse to render a verdict instead of
asking the LLM to extrapolate from a 30%-complete picture."""

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


# Critical fundamental fields. If too many of these are missing, the verdict
# is not safely producible — the analysts will fill the gaps with hallucination.
CRITICAL_FUNDAMENTAL_FIELDS = (
    "pe_ratio",
    "market_cap",
    "sector",
    "debt_to_equity",
    "current_ratio",
    "roe",
    "ebitda_margin",
    "profit_margins",
    "revenue_growth",
    "free_cashflow",
)

CRITICAL_PRICE_FIELDS = (
    "current_price",
    "week_52_high",
    "week_52_low",
)

# Below this completeness fraction we abort the run and tell the user honestly.
DEFAULT_ABORT_THRESHOLD = 0.5
# Below this we still proceed but flag the verdict as low-data confidence.
DEFAULT_WARN_THRESHOLD = 0.7


@dataclass
class DataQualityReport:
    fundamental_completeness: float
    price_completeness: float
    overall_completeness: float
    missing_critical_fields: List[str]
    sparse_sources: List[str]
    abort: bool
    abort_reason: Optional[str]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_populated(value: Any) -> bool:
    """A field counts as populated if it has a meaningful value.
    None, empty string, NaN, "N/A", and 0 in some contexts are not."""
    if value is None:
        return False
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("", "n/a", "na", "none", "null", "unknown"):
            return False
        return True
    if isinstance(value, float):
        return value == value  # NaN check
    return True


def _completeness(payload: Dict, fields: tuple) -> tuple[float, List[str]]:
    """Returns (fraction in [0,1], missing field names)."""
    if not isinstance(payload, dict):
        return 0.0, list(fields)
    missing: List[str] = []
    for f in fields:
        if not _is_populated(payload.get(f)):
            missing.append(f)
    populated = len(fields) - len(missing)
    return populated / len(fields), missing


def evaluate_data_quality(
    state: Dict,
    *,
    abort_threshold: float = DEFAULT_ABORT_THRESHOLD,
    warn_threshold: float = DEFAULT_WARN_THRESHOLD,
) -> DataQualityReport:
    """Inspect the populated state dict and decide whether to proceed."""
    fundamental = state.get("fundamental_data") or {}
    price = state.get("price_data") or {}

    fund_score, fund_missing = _completeness(fundamental, CRITICAL_FUNDAMENTAL_FIELDS)
    price_score, price_missing = _completeness(price, CRITICAL_PRICE_FIELDS)

    # Weight fundamental coverage 70%, price coverage 30% (price API is rarely sparse;
    # when it is, that's catastrophic — but missing fundamentals is the more common
    # silent failure that the LLM will paper over).
    overall = round(0.7 * fund_score + 0.3 * price_score, 3)

    sparse_sources: List[str] = []
    if fund_score < warn_threshold:
        sparse_sources.append("fundamental_data")
    if price_score < warn_threshold:
        sparse_sources.append("price_data")

    # Other sources we expect when present — only warn if entirely empty.
    for src_key, label in (
        ("news_data", "news"),
        ("screener_data", "screener.in"),
        ("peer_data", "sector_peers"),
    ):
        val = state.get(src_key)
        if isinstance(val, dict) and not val:
            sparse_sources.append(label)
        elif isinstance(val, list) and not val:
            sparse_sources.append(label)

    warnings: List[str] = []
    if fund_missing:
        warnings.append(
            f"{len(fund_missing)}/{len(CRITICAL_FUNDAMENTAL_FIELDS)} fundamental fields missing: "
            f"{', '.join(fund_missing[:5])}{'…' if len(fund_missing) > 5 else ''}"
        )
    if price_missing:
        warnings.append(
            f"{len(price_missing)}/{len(CRITICAL_PRICE_FIELDS)} price fields missing"
        )

    abort = overall < abort_threshold
    abort_reason: Optional[str] = None
    if abort:
        abort_reason = (
            f"Data completeness {int(overall * 100)}% is below the {int(abort_threshold * 100)}% "
            f"minimum needed to produce a trustworthy verdict. "
            f"Missing: {', '.join(fund_missing[:6]) or 'price data'}."
        )

    return DataQualityReport(
        fundamental_completeness=round(fund_score, 3),
        price_completeness=round(price_score, 3),
        overall_completeness=overall,
        missing_critical_fields=fund_missing + price_missing,
        sparse_sources=sparse_sources,
        abort=abort,
        abort_reason=abort_reason,
        warnings=warnings,
    )
