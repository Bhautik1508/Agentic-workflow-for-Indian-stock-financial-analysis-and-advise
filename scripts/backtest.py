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

    from evaluation.backtest import load_verdicts, score_verdicts

    verdicts = load_verdicts(args.run_log_dir)
    if not verdicts:
        print(f"No verdicts found in {args.run_log_dir}. Run some analyses first.")
        return 2

    print(f"Loaded {len(verdicts)} verdicts; fetching prices...", file=sys.stderr)
    prices = fetch_prices({v.ticker for v in verdicts})
    result = score_verdicts(verdicts, prices)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0

    print(f"\nVerdicts: {result['verdicts_total']} "
          f"({result['verdicts_directional']} directional, {result['verdicts_hold']} HOLD)\n")
    print(f"  {'Horizon':<10}{'Scored':<9}{'Hits':<7}{'Hit rate':<11}{'Avg return':<12}Note")
    for label, stats in result["by_horizon"].items():
        rate = "n/a" if stats["hit_rate"] is None else f"{stats['hit_rate']*100:.0f}%"
        avg = "n/a" if stats["avg_directional_return_pct"] is None else f"{stats['avg_directional_return_pct']:+.2f}%"
        print(f"  {label:<10}{stats['scored']:<9}{stats['hits']:<7}{rate:<11}{avg:<12}{stats['note']}")

    scored_1m = result["by_horizon"].get("1M", {}).get("scored", 0)
    if scored_1m and scored_1m < 20:
        print(f"\n  Note: only {scored_1m} scorable verdicts at 1M. Too small to conclude "
              f"anything — treat the rate as directional, not evidence.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
