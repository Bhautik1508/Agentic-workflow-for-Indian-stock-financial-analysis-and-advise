#!/usr/bin/env python3
"""Field-coverage regression check for large-cap fundamentals.

Coverage regressions are invisible until a verdict is already wrong. Screener
changes a row label, yfinance tightens a rate limit, a selector breaks — and
`fundamental_completeness` quietly slides while every run still "succeeds" and
the analysts fill the gaps with plausible prose.

Cheap by design: fetches fundamentals only, no LLM calls, so it can run on every
push or nightly without touching the model budget.

    python scripts/check_coverage.py
    python scripts/check_coverage.py --floor 0.8 --limit 5
    python scripts/check_coverage.py --json

Exit codes:  0 = all above the floor   1 = a regression   2 = could not run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except ImportError:
    pass

# Large caps whose fundamentals should always be well covered. Banks are held to
# a lower floor: a bank P&L has no OPM row and no meaningful debt-to-equity, so
# ~0.7 is full marks rather than a regression.
LARGE_CAPS = [
    ("TCS.NS", 0.8), ("INFY.NS", 0.8), ("RELIANCE.NS", 0.8),
    ("ITC.NS", 0.8), ("HDFCBANK.NS", 0.6), ("ICICIBANK.NS", 0.6),
    ("LT.NS", 0.8), ("SUNPHARMA.NS", 0.8),
]


async def coverage_for(ticker: str) -> dict:
    from data.market_data import fetch_all_market_data
    from scoring.data_quality import CRITICAL_FUNDAMENTAL_FIELDS, evaluate_data_quality

    payload = await fetch_all_market_data(ticker)
    fundamentals = payload.get("fundamental_data") or {}
    quality = evaluate_data_quality({
        "fundamental_data": fundamentals,
        "price_data": payload.get("price_data") or {},
    })
    return {
        "ticker": ticker,
        "fundamental_completeness": quality.fundamental_completeness,
        "overall_completeness": quality.overall_completeness,
        "missing": [f for f in CRITICAL_FUNDAMENTAL_FIELDS if fundamentals.get(f) is None],
        "sources": fundamentals.get("_source_counts") or {},
    }


async def main_async(args) -> int:
    cases = LARGE_CAPS[: args.limit] if args.limit else LARGE_CAPS
    rows, failures = [], []

    for ticker, default_floor in cases:
        floor = args.floor if args.floor is not None else default_floor
        try:
            row = await coverage_for(ticker)
        except Exception as exc:
            row = {"ticker": ticker, "fundamental_completeness": 0.0,
                   "overall_completeness": 0.0, "missing": ["<fetch failed>"],
                   "sources": {}, "error": str(exc)[:110]}
        row["floor"] = floor
        row["passed"] = row["fundamental_completeness"] >= floor
        rows.append(row)
        if not row["passed"]:
            failures.append(row)
        if not args.json:
            mark = "ok" if row["passed"] else "!!"
            print(f"  [{mark}] {ticker:14} completeness {row['fundamental_completeness']:.2f} "
                  f"(floor {floor:.2f})  sources={row['sources'] or '-'}")
            if row.get("error"):
                print(f"       fetch error: {row['error']}")
            elif row["missing"]:
                print(f"       missing: {', '.join(row['missing'])}")

    if args.json:
        print(json.dumps({"rows": rows, "failures": len(failures)}, indent=2))
    elif failures:
        print(f"\n{len(failures)} ticker(s) below floor — fundamentals coverage has regressed.")
        print("Likely causes: a Screener row label changed, a selector broke, or "
              "yfinance is rate-limited and the Screener fallback did not cover it.")
    else:
        print(f"\nAll {len(rows)} large caps above their coverage floor.")

    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--floor", type=float, default=None,
                        help="override the per-ticker floor")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 2


if __name__ == "__main__":
    sys.exit(main())
