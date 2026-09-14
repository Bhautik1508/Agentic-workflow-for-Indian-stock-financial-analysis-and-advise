#!/usr/bin/env python3
"""A/B the same ticker through Gemini and Groq and diff the verdicts.

Answers a question that is otherwise a guess: what does falling back to the
secondary provider actually cost in verdict quality? The router fails over
silently by design, so without this you cannot tell whether a fallback run is
as good as a primary one.

    python scripts/provider_ab.py TCS.NS INFY.NS
    python scripts/provider_ab.py TCS.NS --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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


async def run_with_provider(ticker: str, provider: str, profile: str) -> dict:
    """Force one provider by blanking the other's key for this run."""
    import importlib

    saved = {k: os.environ.get(k) for k in ("GOOGLE_API_KEY", "GROQ_API_KEY")}
    if provider == "gemini":
        os.environ["GROQ_API_KEY"] = ""
    else:
        os.environ["GOOGLE_API_KEY"] = ""

    try:
        import graph.workflow as wf
        importlib.reload(wf)
        from graph.runner import run_stock_analysis
        from llm import LLMTelemetry, reset_current_telemetry, set_current_telemetry

        telemetry = LLMTelemetry()
        token = set_current_telemetry(telemetry)
        verdict: dict = {}
        try:
            async for event in run_stock_analysis(ticker, risk_profile=profile):
                if event.get("event") == "node_update":
                    state = event.get("state") or {}
                    if state.get("final_decision"):
                        verdict = state
        finally:
            reset_current_telemetry(token)

        return {
            "provider": provider,
            "action": verdict.get("final_decision"),
            "confidence": verdict.get("confidence_score"),
            "score": verdict.get("judge_score"),
            "target": verdict.get("target_price_inr"),
            "thesis": (verdict.get("investment_thesis") or "")[:200],
            "served_by": sorted(telemetry.by_provider()),
            "tokens": telemetry.total_tokens(),
        }
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def main_async(args) -> int:
    from evaluation.bands import band_distance, is_directionally_opposed

    rows = []
    for ticker in args.tickers:
        print(f"\n=== {ticker} ===", file=sys.stderr)
        a = await run_with_provider(ticker, "gemini", args.profile)
        print(f"  gemini -> {a['action']} (conf {a['confidence']})", file=sys.stderr)
        b = await run_with_provider(ticker, "groq", args.profile)
        print(f"  groq   -> {b['action']} (conf {b['confidence']})", file=sys.stderr)

        rows.append({
            "ticker": ticker,
            "gemini": a,
            "groq": b,
            "band_distance": band_distance(a["action"], b["action"]),
            "directionally_opposed": is_directionally_opposed(a["action"], b["action"]),
        })

    if args.json:
        print(json.dumps(rows, indent=2, default=str))
    else:
        print(f"\n{'Ticker':<14}{'Gemini':<13}{'Groq':<13}{'Δ bands':<9}Opposed")
        for row in rows:
            print(f"{row['ticker']:<14}{str(row['gemini']['action']):<13}"
                  f"{str(row['groq']['action']):<13}{str(row['band_distance']):<9}"
                  f"{'YES' if row['directionally_opposed'] else 'no'}")
        opposed = sum(1 for r in rows if r["directionally_opposed"])
        if opposed:
            print(f"\n  {opposed}/{len(rows)} disagreed on direction — the fallback tier is "
                  f"not equivalent for these names.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--profile", default="balanced")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
