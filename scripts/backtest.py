#!/usr/bin/env python3
"""Score past verdicts against realised forward returns.

Reads `backend/.runlog/`, fetches price history for each ticker, and reports
hit-rate per horizon. The previous plan's target was >55% on BUY/STRONG_BUY at
1 month.

    python scripts/backtest.py
    python scripts/backtest.py --json --run-log-dir backend/.runlog

Two deliberate omissions, both about not flattering the numbers: HOLD verdicts
are excluded (there is no honest definition of a correct HOLD without a
benchmark), and a horizon that has not yet elapsed reports `null` rather than 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))


def fetch_prices(tickers, period="1y"):
    import yfinance as yf

    history = {}
    for ticker in sorted(tickers):
        try:
            frame = yf.Ticker(ticker).history(period=period)
            history[ticker] = {
                idx.strftime("%Y-%m-%d"): float(row["Close"])
                for idx, row in frame.iterrows()
            }
            print(f"  fetched {ticker}: {len(history[ticker])} closes", file=sys.stderr)
        except Exception as exc:
            print(f"  {ticker}: price fetch failed ({str(exc)[:70]})", file=sys.stderr)
            history[ticker] = {}
    return history


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-log-dir", default=str(BACKEND / ".runlog"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    from evaluation.backtest import load_verdicts, score_by_cohort

    verdicts = load_verdicts(args.run_log_dir)
    if not verdicts:
        print(f"No verdicts found in {args.run_log_dir}. Run some analyses first.")
        return 2

    print(f"Loaded {len(verdicts)} verdicts; fetching prices...", file=sys.stderr)
    prices = fetch_prices({v.ticker for v in verdicts})
    report = score_by_cohort(verdicts, prices)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"\nEngine version now: {report['current_version']}")
    if not report["pooled_is_meaningful"]:
        print("  Verdicts span MORE THAN ONE engine version. Reported separately —\n"
              "  a hit-rate pooled across engines describes neither of them.")

    for version, result in report["cohorts"].items():
        marker = "  <-- current" if result["is_current"] else ""
        print(f"\n── cohort {version}{marker} ──")
        print(f"   {result['description']}")
        print(f"   {result['verdicts_total']} verdicts "
              f"({result['verdicts_directional']} directional, {result['verdicts_hold']} HOLD)")
        print(f"   {'Horizon':<9}{'Scored':<8}{'Hits':<6}{'Hit rate':<10}{'Avg return':<12}Note")
        for label, stats in result["by_horizon"].items():
            rate = "n/a" if stats["hit_rate"] is None else f"{stats['hit_rate']*100:.0f}%"
            avg = ("n/a" if stats["avg_directional_return_pct"] is None
                   else f"{stats['avg_directional_return_pct']:+.2f}%")
            print(f"   {label:<9}{stats['scored']:<8}{stats['hits']:<6}{rate:<10}{avg:<12}{stats['note']}")

        scored = result["by_horizon"].get("1M", {}).get("scored", 0)
        if not result["sample_is_credible"]:
            print(f"   NOT YET EVIDENCE: {scored} scorable verdicts at 1M against a bar of "
                  f"{result['min_credible_sample']}.")
            print(f"   Do not tune pillar weights on this — it would be fitting to noise.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
