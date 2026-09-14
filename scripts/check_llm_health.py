#!/usr/bin/env python3
"""Probe every configured LLM provider: reachable? does the model exist? how slow?

Built because a vendor retiring a model took the whole app down silently. Groq
removed `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`; every call 404'd
and nothing noticed. Later the whole `gemini-2.5-*` family went 404 for
newly-created keys.

A thin CLI over `llm.health` — the same code path `GET /api/health?deep=true`
uses, so the endpoint and this script cannot report different things. An
earlier version kept its own copy of the model defaults and promptly drifted,
reporting on a model the app no longer used.

Usage:
    python scripts/check_llm_health.py               # verify configured models
    python scripts/check_llm_health.py --live        # also send a real completion
    python scripts/check_llm_health.py --list-models # print every model served
    python scripts/check_llm_health.py --json

Exit codes:  0 = healthy   1 = a problem   2 = nothing configured
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


def render(report: dict, *, show_models: bool) -> None:
    print(f"Primary provider: {report['primary_provider']}\n")

    for p in report["providers"]:
        name = p["provider"]
        wanted = ", ".join(p["configured_models"])
        if not p["key_present"]:
            print(f"  [--] {name:8} no API key set - tier skipped")
            continue
        if not p["reachable"]:
            print(f"  [!!] {name:8} UNREACHABLE - {p['error']}")
            continue
        mark = "ok" if p["model_exists"] else "!!"
        state = "serves" if p["model_exists"] else "DOES NOT SERVE"
        print(f"  [{mark}] {name:8} reachable in {p['latency_ms']}ms, {state} {wanted}"
              f"  ({p['available_model_count']} models listed)")
        if p["error"]:
            print(f"       {p['error']}")
        if show_models:
            for model in p.get("available_models", []):
                print(f"         - {model}")

    live = report.get("live")
    if live:
        print()
        if live["ok"]:
            print(f"  [ok] live completion served by '{live['served_by']}' in {live['duration_ms']}ms")
            if live["served_by"] != report["primary_provider"]:
                print(f"  [!!] expected '{report['primary_provider']}' to serve this - "
                      f"you are silently running on the fallback tier")
        else:
            print(f"  [!!] live completion FAILED - {live['error']}")
        print(f"       chain: {' -> '.join(live.get('chain', []))}")
    else:
        print("\n  note: a model can be LISTED yet 404 on use (deprecated models stay\n"
              "        visible to the listing API). Use --live to actually exercise it.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="also send a real completion through the router")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-models", action="store_true",
                        help="print every model each provider serves")
    args = parser.parse_args()

    from llm.health import full_report

    report = asyncio.run(full_report(live=args.live, include_model_list=args.list_models))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        render(report, show_models=args.list_models)

    if report.get("error"):
        print(f"\n{report['error']}")
        return 2
    if not report["healthy"]:
        print("\nProblems found.")
        return 1
    print("\nAll configured providers healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
