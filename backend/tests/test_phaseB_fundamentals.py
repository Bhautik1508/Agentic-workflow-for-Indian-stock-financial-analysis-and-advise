"""Phase B — close the completeness gap using data already being fetched."""

import pytest

from data.fundamentals_adapter import (
    CRORE,
    extract_from_screener,
    merge_fundamentals,
    parse_number,
    scale_crore_fields,
    screener_only_fields,
)
from scoring.data_quality import (
    CRITICAL_FUNDAMENTAL_FIELDS,
    DEFAULT_ABORT_THRESHOLD,
    DEFAULT_WARN_THRESHOLD,
)

# Shaped like a real Screener payload: non-breaking spaces, expand markers,
# currency symbols and the newline soup that comes straight out of the HTML.
SCREENER = {
    "sector": "Information Technology",
    "industry": "Computers - Software & Consulting",
    "Market Cap": "₹\n        8,13,988\n        \n          Cr.",
    "Stock P/E": "15.2",
    "ROE": "51.8\n        \n          %",
    "ROCE": "63.0\n        \n          %",
    "Book Value": "₹\n        296",
    "Dividend Yield": "2.84\n        \n          %",
    "pl_Sales\xa0+": {"Mar 2025": "2,55,324", "Mar 2026": "2,67,021"},
    "pl_Operating Profit": {"Mar 2025": "67,407", "Mar 2026": "72,398"},
    "pl_OPM %": {"Mar 2025": "26%", "Mar 2026": "27%"},
    "pl_Interest": {"Mar 2026": "1,200"},
    "pl_Depreciation": {"Mar 2026": "5,400"},
    "pl_Net Profit\xa0+": {"Mar 2025": "48,553", "Mar 2026": "52,000"},
    "pl_EPS in Rs": {"Mar 2026": "143.5"},
    "bs_Equity Capital": {"Mar 2026": "362"},
    "bs_Reserves": {"Mar 2026": "1,06,878"},
    "bs_Borrowings\xa0+": {"Mar 2026": "11,283"},
    "bs_Total Assets": {"Mar 2026": "1,50,000"},
    "cf_Free Cash Flow": {"Mar 2026": "42,000"},
    "cf_Cash from Operating Activity\xa0+": {"Mar 2026": "48,000"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Value parsing — the reason most fields were None
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("₹\n  8,13,988\n\n  Cr.", 8_13_988 * CRORE),
    ("2.5 Lakh Cr.", 2.5e12),
    ("51.8\n\n %", 51.8),
    ("₹\n 296", 296.0),
    ("1,234.5", 1234.5),
    ("-12.5 %", -12.5),
    ("0", 0.0),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["-", "--", "N/A", "NA", "", "   ", None, "abc"])
def test_parse_number_returns_none_rather_than_guessing(raw):
    assert parse_number(raw) is None


def test_parse_number_does_not_trip_on_the_period_in_cr():
    """Stripping non-digits turned '2.5 Lakh Cr.' into '2.5.', which float()
    rejects. The numeric token is matched instead."""
    assert parse_number("2.5 Cr.") == 2.5 * CRORE


# ─────────────────────────────────────────────────────────────────────────────
# Screener extraction
# ─────────────────────────────────────────────────────────────────────────────

def test_tolerates_non_breaking_space_keys():
    """Screener emits 'pl_Sales\\xa0+'; exact-key lookups silently missed it."""
    out = extract_from_screener(SCREENER)
    assert out["revenue_growth"] == pytest.approx((267021 - 255324) / 255324)


def test_extracts_headline_scalars():
    out = extract_from_screener(SCREENER)
    assert out["pe_ratio"] == 15.2
    assert out["roe"] == pytest.approx(0.518)
    assert out["roce"] == pytest.approx(0.63)
    assert out["book_value"] == 296.0
    assert out["market_cap"] == pytest.approx(8_13_988 * CRORE)


def test_extracts_fields_unlocked_by_removing_the_row_cap():
    """The P&L and balance sheet were sliced to five rows, which dropped Net
    Profit, EPS, Interest, Depreciation and Total Assets."""
    out = extract_from_screener(SCREENER)
    assert out["profit_margins"] == pytest.approx(52000 / 267021)
    assert out["earnings_growth"] is not None
    assert out["eps"] == 143.5
    assert out["total_assets"] == 150000
    assert out["interest_coverage"] == pytest.approx(72398 / 1200)


def test_extracts_cash_flow_which_was_never_scraped():
    out = extract_from_screener(SCREENER)
    assert out["free_cashflow"] == 42000
    assert out["operating_cashflow"] == 48000


def test_opm_is_the_ebitda_margin_not_an_approximation():
    """Screener subtracts interest and depreciation AFTER Operating Profit, so
    that line is EBITDA and OPM% is the EBITDA margin exactly."""
    out = extract_from_screener(SCREENER)
    assert out["ebitda_margin"] == pytest.approx(0.27)


def test_extracts_sector_and_industry():
    out = extract_from_screener(SCREENER)
    assert out["sector"] == "Information Technology"
    assert out["industry"] == "Computers - Software & Consulting"


def test_debt_to_equity_derived_from_balance_sheet():
    out = extract_from_screener(SCREENER)
    assert out["debt_to_equity"] == pytest.approx(11283 / (362 + 106878))


def test_empty_screener_yields_nothing_rather_than_zeros():
    assert extract_from_screener({}) == {}
    assert extract_from_screener(None) == {}


def test_crore_scaling_matches_yfinance_units():
    scaled = scale_crore_fields({"free_cashflow": 42000, "pe_ratio": 15.2})
    assert scaled["free_cashflow"] == 42000 * CRORE
    assert scaled["pe_ratio"] == 15.2, "ratios must not be scaled"


# ─────────────────────────────────────────────────────────────────────────────
# Per-field merge + provenance
# ─────────────────────────────────────────────────────────────────────────────

def test_merge_is_per_field_not_per_provider():
    """A partial yfinance response must be topped up, not discarded because it
    answered at all — which is what "first provider wins" would do."""
    merged, prov = merge_fundamentals([
        ("yfinance", {"pe_ratio": 15.0, "roe": None}),
        ("screener.in", {"pe_ratio": 14.8, "roe": 0.518, "free_cashflow": 1.0}),
    ])
    assert merged["pe_ratio"] == 15.0          # first source wins where present
    assert merged["roe"] == 0.518              # gap filled from the second
    assert merged["free_cashflow"] == 1.0
    assert prov == {"pe_ratio": "yfinance", "roe": "screener.in",
                    "free_cashflow": "screener.in"}


def test_merge_skips_none_and_blank():
    merged, prov = merge_fundamentals([
        ("a", {"sector": None, "industry": "   "}),
        ("b", {"sector": "IT", "industry": "Software"}),
    ])
    assert merged == {"sector": "IT", "industry": "Software"}
    assert set(prov.values()) == {"b"}


def test_merge_of_nothing_is_empty():
    merged, prov = merge_fundamentals([("a", {}), ("b", None)])
    assert merged == {} and prov == {}


def test_screener_alone_covers_most_critical_fields():
    """Production conditions: yfinance rate-limited, Screener the only source.
    This was 0.2; the gate's abort line now sits at 0.5."""
    fields = screener_only_fields(SCREENER)
    covered = [f for f in CRITICAL_FUNDAMENTAL_FIELDS if fields.get(f) is not None]
    completeness = len(covered) / len(CRITICAL_FUNDAMENTAL_FIELDS)
    assert completeness >= 0.8, f"screener-only coverage regressed to {completeness}"
    assert completeness > DEFAULT_ABORT_THRESHOLD


# ─────────────────────────────────────────────────────────────────────────────
# Quality gate calibration
# ─────────────────────────────────────────────────────────────────────────────

def test_thresholds_were_raised_with_the_plumbing_fix():
    """0.30 was calibrated around broken plumbing, where 0.44 was normal."""
    assert DEFAULT_ABORT_THRESHOLD >= 0.50
    assert DEFAULT_WARN_THRESHOLD >= 0.70
    assert DEFAULT_ABORT_THRESHOLD < DEFAULT_WARN_THRESHOLD
