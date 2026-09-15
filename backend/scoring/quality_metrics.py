"""Accounting-quality metrics computed from Screener statements.

Deterministic maths belongs in Python, where it is testable and reproducible.
The agents should *interpret* these numbers, not derive them — a model asked to
compute a Piotroski score from a table will produce something plausible and
unverifiable.

Everything here became possible only once Phase B stopped the scraper
truncating the P&L and balance sheet to five rows and started reading the
cash-flow statement.

Honesty rules, consistent with the rest of the codebase:
  * a metric that cannot be computed returns None with a stated reason;
  * the Piotroski score reports how many criteria were *evaluable*, rather than
    scoring out of 9 with one criterion silently failing forever.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from data.fundamentals_adapter import parse_number
from data.screener_summary import find_row

logger = logging.getLogger(__name__)


def annual_series(row: Optional[Dict[str, Any]]) -> List[Tuple[int, float]]:
    """[(year, value)] ascending, for columns that are real fiscal years.

    Screener's P&L carries a trailing "TTM" column while the balance sheet does
    not. Mixing them would compare a twelve-month figure against a year-end one,
    so non-year columns are dropped for anything year-on-year.
    """
    if not row:
        return []
    out: List[Tuple[int, float]] = []
    for label, raw in row.items():
        parts = str(label).split()
        if not parts:
            continue
        try:
            year = int(parts[-1])
        except ValueError:
            continue                      # "TTM" and friends
        value = parse_number(raw)
        if value is not None:
            out.append((year, value))
    return sorted(out)


def _last_two(row: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    series = annual_series(row)
    if len(series) < 2:
        return (series[-1][1] if series else None), None
    return series[-1][1], series[-2][1]


def _ratio(numerator: Optional[float], denominator: Optional[float]) -> Optional[float]:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


@dataclass
class Criterion:
    name: str
    passed: Optional[bool]          # None = not evaluable
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PiotroskiResult:
    score: Optional[int] = None
    evaluated: int = 0
    max_score: int = 0
    interpretation: str = ""
    criteria: List[Dict[str, Any]] = field(default_factory=list)
    unavailable: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def piotroski_f_score(screener: Optional[Dict[str, Any]]) -> PiotroskiResult:
    """Piotroski F-Score from Screener statements.

    Eight of the nine classic criteria are computable here. The ninth — change
    in current ratio — needs a current-assets/current-liabilities split that
    Screener does not publish, so it is reported as unavailable rather than
    counted as a failure, which would understate every company by one point.
    """
    screener = screener or {}

    net_profit = find_row(screener, "pl_Net Profit", "pl_Profit after tax")
    sales = find_row(screener, "pl_Sales", "pl_Revenue")
    opm = find_row(screener, "pl_OPM %")
    total_assets = find_row(screener, "bs_Total Assets") or find_row(screener, "bs_Total Liabilities")
    borrowings = find_row(screener, "bs_Borrowings")
    equity_capital = find_row(screener, "bs_Equity Capital")
    cfo = find_row(screener, "cf_Cash from Operating Activity")

    ni_now, ni_prev = _last_two(net_profit)
    ta_now, ta_prev = _last_two(total_assets)
    sales_now, sales_prev = _last_two(sales)
    opm_now, opm_prev = _last_two(opm)
    debt_now, debt_prev = _last_two(borrowings)
    eq_now, eq_prev = _last_two(equity_capital)
    cfo_now, _ = _last_two(cfo)

    roa_now, roa_prev = _ratio(ni_now, ta_now), _ratio(ni_prev, ta_prev)
    criteria: List[Criterion] = []

    criteria.append(Criterion(
        "ROA positive", (roa_now > 0) if roa_now is not None else None,
        f"ROA {roa_now:.2%}" if roa_now is not None else "net profit or total assets missing"))

    criteria.append(Criterion(
        "Operating cash flow positive", (cfo_now > 0) if cfo_now is not None else None,
        f"CFO {cfo_now:,.0f}" if cfo_now is not None else "cash-flow statement missing"))

    criteria.append(Criterion(
        "ROA improving",
        (roa_now > roa_prev) if (roa_now is not None and roa_prev is not None) else None,
        f"{roa_prev:.2%} to {roa_now:.2%}" if (roa_now is not None and roa_prev is not None)
        else "needs two years"))

    cfo_ta = _ratio(cfo_now, ta_now)
    criteria.append(Criterion(
        "Earnings backed by cash (CFO/TA > ROA)",
        (cfo_ta > roa_now) if (cfo_ta is not None and roa_now is not None) else None,
        f"CFO/TA {cfo_ta:.2%} vs ROA {roa_now:.2%}" if (cfo_ta is not None and roa_now is not None)
        else "needs CFO and ROA"))

    lev_now, lev_prev = _ratio(debt_now, ta_now), _ratio(debt_prev, ta_prev)
    criteria.append(Criterion(
        "Leverage falling",
        (lev_now < lev_prev) if (lev_now is not None and lev_prev is not None) else None,
        f"debt/assets {lev_prev:.2%} to {lev_now:.2%}"
        if (lev_now is not None and lev_prev is not None) else "needs two years"))

    criteria.append(Criterion(
        "Current ratio improving", None,
        "unavailable — Screener does not split current assets from current liabilities"))

    criteria.append(Criterion(
        "No new equity issued",
        (eq_now <= eq_prev) if (eq_now is not None and eq_prev is not None) else None,
        f"share capital {eq_prev:,.0f} to {eq_now:,.0f}"
        if (eq_now is not None and eq_prev is not None) else "needs two years"))

    criteria.append(Criterion(
        "Operating margin improving",
        (opm_now > opm_prev) if (opm_now is not None and opm_prev is not None) else None,
        f"OPM {opm_prev:.0f}% to {opm_now:.0f}%"
        if (opm_now is not None and opm_prev is not None) else "needs two years"))

    turn_now, turn_prev = _ratio(sales_now, ta_now), _ratio(sales_prev, ta_prev)
    criteria.append(Criterion(
        "Asset turnover improving",
        (turn_now > turn_prev) if (turn_now is not None and turn_prev is not None) else None,
        f"turnover {turn_prev:.2f}x to {turn_now:.2f}x"
        if (turn_now is not None and turn_prev is not None) else "needs two years"))

    evaluable = [c for c in criteria if c.passed is not None]
    unavailable = [c.name for c in criteria if c.passed is None]
    if not evaluable:
        return PiotroskiResult(criteria=[c.to_dict() for c in criteria],
                               unavailable=unavailable,
                               interpretation="not computable — no statement data")

    score = sum(1 for c in evaluable if c.passed)
    maximum = len(evaluable)
    strength = score / maximum
    interpretation = ("strong" if strength >= 0.78 else
                      "moderate" if strength >= 0.5 else "weak")

    return PiotroskiResult(
        score=score, evaluated=maximum, max_score=maximum,
        interpretation=interpretation,
        criteria=[c.to_dict() for c in criteria],
        unavailable=unavailable,
    )


@dataclass
class DuPontResult:
    roe: Optional[float] = None
    net_margin: Optional[float] = None
    asset_turnover: Optional[float] = None
    equity_multiplier: Optional[float] = None
    driver: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def dupont_decomposition(screener: Optional[Dict[str, Any]]) -> DuPontResult:
    """ROE = net margin × asset turnover × equity multiplier.

    A single ROE number cannot distinguish a genuinely profitable business from
    a levered one. The decomposition names which of the three is doing the work.
    """
    screener = screener or {}
    ni, _ = _last_two(find_row(screener, "pl_Net Profit", "pl_Profit after tax"))
    sales, _ = _last_two(find_row(screener, "pl_Sales", "pl_Revenue"))
    ta, _ = _last_two(find_row(screener, "bs_Total Assets") or find_row(screener, "bs_Total Liabilities"))
    reserves, _ = _last_two(find_row(screener, "bs_Reserves"))
    equity_capital, _ = _last_two(find_row(screener, "bs_Equity Capital"))

    equity = None
    if reserves is not None or equity_capital is not None:
        equity = (reserves or 0.0) + (equity_capital or 0.0)

    margin = _ratio(ni, sales)
    turnover = _ratio(sales, ta)
    multiplier = _ratio(ta, equity)

    if None in (margin, turnover, multiplier):
        missing = [n for n, v in (("net margin", margin), ("asset turnover", turnover),
                                  ("equity multiplier", multiplier)) if v is None]
        return DuPontResult(net_margin=margin, asset_turnover=turnover,
                            equity_multiplier=multiplier,
                            reason=f"missing: {', '.join(missing)}")

    roe = margin * turnover * multiplier
    # Which lever dominates: compare each against a rough "unremarkable" level.
    scores = {"margin": margin / 0.10, "turnover": turnover / 1.0,
              "leverage": multiplier / 2.0}
    driver = max(scores, key=scores.get)

    return DuPontResult(
        roe=round(roe, 4), net_margin=round(margin, 4),
        asset_turnover=round(turnover, 3), equity_multiplier=round(multiplier, 3),
        driver=driver,
    )


@dataclass
class CashQualityResult:
    cash_conversion: Optional[float] = None           # CFO / net profit, latest
    cash_conversion_3y_avg: Optional[float] = None
    accruals_ratio: Optional[float] = None            # (NI - CFO) / total assets
    flag: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def cash_quality(screener: Optional[Dict[str, Any]]) -> CashQualityResult:
    """Do reported profits turn into cash?

    The most practical accounting-quality check available from free data.
    Persistent divergence between profit and operating cash flow is the classic
    warning sign, and a single year of it is noise — hence the 3-year average.
    """
    screener = screener or {}
    ni_series = annual_series(find_row(screener, "pl_Net Profit", "pl_Profit after tax"))
    cfo_series = annual_series(find_row(screener, "cf_Cash from Operating Activity"))
    ta_now, _ = _last_two(find_row(screener, "bs_Total Assets") or find_row(screener, "bs_Total Liabilities"))

    if not ni_series or not cfo_series:
        return CashQualityResult(reason="net profit or cash-flow statement unavailable")

    by_year_cfo = dict(cfo_series)
    ratios: List[float] = []
    for year, ni in ni_series:
        cfo = by_year_cfo.get(year)
        if cfo is not None and ni:
            ratios.append(cfo / ni)

    if not ratios:
        return CashQualityResult(reason="no overlapping years between P&L and cash flow")

    latest = ratios[-1]
    recent = ratios[-3:]
    average = sum(recent) / len(recent)

    ni_now = ni_series[-1][1]
    cfo_now = by_year_cfo.get(ni_series[-1][0])
    accruals = _ratio((ni_now - cfo_now) if cfo_now is not None else None, ta_now)

    if average >= 0.9:
        flag = "profits well backed by cash"
    elif average >= 0.7:
        flag = "acceptable cash conversion"
    elif average >= 0.5:
        flag = "weak cash conversion — monitor working capital"
    else:
        flag = "poor cash conversion — earnings quality concern"

    return CashQualityResult(
        cash_conversion=round(latest, 3),
        cash_conversion_3y_avg=round(average, 3),
        accruals_ratio=round(accruals, 4) if accruals is not None else None,
        flag=flag,
    )


def build_quality_metrics(screener: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Everything in this module, as one payload for the state and the prompts."""
    return {
        "piotroski": piotroski_f_score(screener).to_dict(),
        "dupont": dupont_decomposition(screener).to_dict(),
        "cash_quality": cash_quality(screener).to_dict(),
    }


def render_for_prompt(metrics: Optional[Dict[str, Any]]) -> str:
    """Compact block for the financial/risk prompts."""
    if not metrics:
        return "Accounting-quality metrics unavailable."

    lines: List[str] = []

    p = metrics.get("piotroski") or {}
    if p.get("score") is not None:
        lines.append(f"Piotroski F-Score: {p['score']}/{p['max_score']} ({p['interpretation']})")
        for c in p.get("criteria", []):
            if c.get("passed") is None:
                continue
            lines.append(f"  [{'PASS' if c['passed'] else 'FAIL'}] {c['name']} — {c['detail']}")
        if p.get("unavailable"):
            lines.append(f"  (not evaluable: {', '.join(p['unavailable'])})")
    else:
        lines.append("Piotroski F-Score: unavailable")

    d = metrics.get("dupont") or {}
    if d.get("roe") is not None:
        lines.append(
            f"DuPont ROE {d['roe']:.1%} = margin {d['net_margin']:.1%} × "
            f"turnover {d['asset_turnover']}x × leverage {d['equity_multiplier']}x "
            f"— driven by {d['driver']}"
        )
    else:
        lines.append(f"DuPont: unavailable ({d.get('reason', 'no data')})")

    c = metrics.get("cash_quality") or {}
    if c.get("cash_conversion_3y_avg") is not None:
        lines.append(
            f"Cash conversion (CFO/net profit): latest {c['cash_conversion']:.2f}x, "
            f"3-yr avg {c['cash_conversion_3y_avg']:.2f}x — {c['flag']}"
        )
        if c.get("accruals_ratio") is not None:
            lines.append(f"Accruals ratio (NI-CFO)/assets: {c['accruals_ratio']:.2%} "
                         f"(lower is better)")
    else:
        lines.append(f"Cash conversion: unavailable ({c.get('reason', 'no data')})")

    return "\n".join(lines)
