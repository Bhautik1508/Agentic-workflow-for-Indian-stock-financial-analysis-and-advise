#!/usr/bin/env python3
"""Run the golden-set tickers and report drift against expected verdict bands.

Intended as a nightly job, not a pre-commit check: each case is a full analysis
(6 LLM calls plus data fetching), so the whole set costs real money and minutes.

    python scripts/run_golden_set.py                  # whole set
    python scripts/run_golden_set.py --limit 3        # smoke test
    python scripts/run_golden_set.py --json

Exit codes:  0 = no regressions   1 = at least one   2 = could not run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND / ".env")
except ImportError:
    pass


async def verdict_for(ticker: str, profile: str) -> tuple[str | None, float]:
    from graph.runner import run_stock_analysis

    started = time.monotonic()
    action = None
    async for event in run_stock_analysis(ticker, risk_profile=profile):
        if event.get("event") == "node_update":
            state = event.get("state") or {}
            if state.get("final_decision"):
                action = state["final_decision"]
        elif event.get("event") == "error":
            break
    return action, round(time.monotonic() - started, 1)


async def main_async(args) -> int:
    from evaluation import compare_to_golden, load_golden_set

    cases = load_golden_set()
    if args.limit:
        cases = cases[: args.limit]

    results: dict[str, str | None] = {}
    for index, case in enumerate(cases, 1):
        try:
            action, seconds = await verdict_for(case.ticker, args.profile)
        except Exception as exc:
            print(f"  [{index}/{len(cases)}] {case.ticker:16} FAILED {str(exc)[:70]}", file=sys.stderr)
            results[case.ticker] = None
            continue
        results[case.ticker] = action
        print(f"  [{index}/{len(cases)}] {case.ticker:16} {action or 'NO VERDICT':<12} "
              f"expected {case.expected_band:<12} {seconds}s", file=sys.stderr)

    report = compare_to_golden(results, cases)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\nGolden set: {report['evaluated']}/{report['total']} evaluated, "
              f"{report['regressions']} regression(s), pass rate {report['pass_rate']*100:.0f}%\n")
        for row in report["rows"]:
            mark = "!!" if row["regression"] else "ok"
            print(f"  [{mark}] {row['ticker']:16} expected {row['expected']:<12} "
                  f"got {str(row['actual']):<12} {row['reason']}")

    return 1 if report["regressions"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="only the first N cases")
    parser.add_argument("--profile", default="balanced")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        return 2


if __name__ == "__main__":
    sys.exit(main())
