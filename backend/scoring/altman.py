"""Altman Z-score — bankruptcy distress signal.

`scoring/vetos.py` has always read `fundamental_data["altman_z_score"]` and
forced a SELL below the distress threshold. Nothing ever wrote that key, so the
veto was dead code and the risk prompt printed "N/A" on every run. This module
computes it from data the app already scrapes free from Screener.in.

Which model
-----------
The emerging-market variant (Z''), not the 1968 original:

    Z'' = 6.56·X1 + 3.26·X2 + 6.72·X3 + 1.05·X4

    X1 = Working Capital / Total Assets
    X2 = Retained Earnings / Total Assets
    X3 = EBIT / Total Assets
    X4 = Book Value of Equity / Total Liabilities

Z'' drops the Sales/Total-Assets term of the original, which is what made the
original sensitive to industry asset intensity, and uses *book* equity rather
than market capitalisation. Both properties suit Indian non-financials and a
scraped data set better than the original would.

Zones for Z'': > 2.6 safe · 1.1–2.6 grey · < 1.1 distress.

Two honesty constraints
-----------------------
**Financials are excluded.** Z-scores are meaningless for banks, NBFCs and
insurers: their balance sheets are inventories of loans, so working capital and
leverage do not mean what the model assumes. A bank would score as permanently
distressed. Where the sector cannot be established, the score is still computed
for information but marked not veto-eligible — a wrong forced SELL on a healthy
bank is far worse than a missing signal.

**Proxies are declared, not hidden.** Screener does not expose every line item,
so `retained_earnings` uses Reserves, `ebit` uses Operating Profit, and working
capital is derived from Working Capital Days. Each is recorded in `components`
so a reader can see what the number was actually built from.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from data.screener_summary import compute_cagr, find_row, latest_value

logger = logging.getLogger(__name__)

# Z'' zone boundaries.
DISTRESS_BELOW = 1.1
SAFE_ABOVE = 2.6

FINANCIAL_SECTOR_MARKERS = (
    "bank", "financial", "finance", "nbfc", "insurance", "insurer",
    "capital market", "asset management", "broking", "lending", "housing finance",
)


@dataclass
class AltmanResult:
    score: Optional[float] = None
    variant: str = "emerging_markets_z2"
    zone: Optional[str] = None            # safe | grey | distress
    veto_eligible: bool = False
    components: Dict[str, Any] = field(default_factory=dict)
    reason: Optional[str] = None          # why score is None / not veto-eligible

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        text = str(value).replace(",", "").replace("%", "").replace("₹", "").strip()
        if not text or text in {"-", "N/A", "NA"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def is_financial(sector: Optional[str], company_name: Optional[str] = None) -> Optional[bool]:
    """True/False when determinable, None when the sector is unknown.

    None matters: it is the difference between "this is not a bank" and "we do
    not know", and only the former should let a veto fire.
    """
    haystacks = [h for h in (sector, company_name) if h]
    if not haystacks:
        return None
    blob = " ".join(str(h).lower() for h in haystacks)
    if any(marker in blob for marker in FINANCIAL_SECTOR_MARKERS):
        return True
    return False if sector else None


def compute_altman_z(
    screener: Optional[Dict[str, Any]] = None,
    fundamental: Optional[Dict[str, Any]] = None,
    *,
    sector: Optional[str] = None,
    company_name: Optional[str] = None,
) -> AltmanResult:
    """Compute Z'' from Screener rows, falling back to yfinance fields."""
    screener = screener or {}
    fundamental = fundamental or {}
    sector = sector or fundamental.get("sector")

    financial = is_financial(sector, company_name)
    if financial is True:
        return AltmanResult(
            reason="not applicable to financials — a bank's balance sheet breaks the model's assumptions"
        )

    total_assets = _to_float(latest_value(find_row(screener, "bs_Total Liabilities"))) \
        or _to_float(fundamental.get("total_assets"))
    reserves = _to_float(latest_value(find_row(screener, "bs_Reserves")))
    equity_capital = _to_float(latest_value(find_row(screener, "bs_Equity Capital")))
    borrowings = _to_float(latest_value(find_row(screener, "bs_Borrowings"))) \
        or _to_float(fundamental.get("total_debt"))
    other_liabilities = _to_float(latest_value(find_row(screener, "bs_Other Liabilities")))
    ebit = _to_float(latest_value(find_row(screener, "pl_Operating Profit"))) \
        or _to_float(fundamental.get("ebit"))
    sales = _to_float(latest_value(find_row(screener, "pl_Sales", "pl_Revenue")))
    wc_days = _to_float(latest_value(find_row(screener, "ratio_Working Capital Days")))

    components: Dict[str, Any] = {
        "total_assets": total_assets,
        "retained_earnings_proxy_reserves": reserves,
        "equity_capital": equity_capital,
        "borrowings": borrowings,
        "other_liabilities": other_liabilities,
        "ebit_proxy_operating_profit": ebit,
        "sales": sales,
        "working_capital_days": wc_days,
    }

    if not total_assets or total_assets <= 0:
        return AltmanResult(components=components,
                            reason="total assets unavailable — cannot compute")

    book_equity = None
    if reserves is not None or equity_capital is not None:
        book_equity = (reserves or 0.0) + (equity_capital or 0.0)

    total_liabilities = None
    if borrowings is not None or other_liabilities is not None:
        total_liabilities = (borrowings or 0.0) + (other_liabilities or 0.0)

    # Working capital from Screener's Working Capital Days:
    #   WC Days = WC / Sales × 365  =>  WC = WC Days × Sales / 365
    working_capital = None
    if wc_days is not None and sales:
        working_capital = wc_days * sales / 365.0
    components["working_capital_derived"] = working_capital

    missing = [
        name for name, value in (
            ("working_capital", working_capital),
            ("retained_earnings", reserves),
            ("ebit", ebit),
            ("book_equity", book_equity),
            ("total_liabilities", total_liabilities),
        ) if value is None
    ]
    if missing:
        return AltmanResult(components=components,
                            reason=f"missing inputs: {', '.join(missing)}")
    if not total_liabilities:
        return AltmanResult(components=components,
                            reason="total liabilities is zero — X4 undefined")

    x1 = working_capital / total_assets
    x2 = reserves / total_assets
    x3 = ebit / total_assets
    x4 = book_equity / total_liabilities
    score = round(6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4, 2)

    components.update({"X1_wc_ta": round(x1, 4), "X2_re_ta": round(x2, 4),
                       "X3_ebit_ta": round(x3, 4), "X4_eq_tl": round(x4, 4)})

    zone = "distress" if score < DISTRESS_BELOW else "safe" if score > SAFE_ABOVE else "grey"

    # Only a confirmed non-financial may drive a veto.
    veto_eligible = financial is False
    reason = None if veto_eligible else (
        "sector unknown — score reported but not veto-eligible, since a false "
        "distress call on a financial would force a wrong SELL"
    )

    return AltmanResult(score=score, zone=zone, veto_eligible=veto_eligible,
                        components=components, reason=reason)
