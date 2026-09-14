#!/usr/bin/env python3
"""Probe every configured LLM provider: reachable? does the model exist? how slow?

Built because a vendor retiring a model took the whole app down silently. Groq
removed `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`; every call 404'd
and nothing noticed. This is the check that would have caught it in one second.

Run it after rotating a key, after changing GEMINI_MODEL/GROQ_MODEL, and in CI.

Usage:
    python scripts/check_llm_health.py            # probe + list available models
    python scripts/check_llm_health.py --live     # also send a real 1-token completion
    python scripts/check_llm_health.py --json

Exit codes:  0 = every configured provider healthy   1 = a problem   2 = nothing configured
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
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


def _truncate(text: str, limit: int = 130) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


# ── Gemini ───────────────────────────────────────────────────────────────────

def probe_gemini(configured_models: list[str]) -> dict:
    result = {
        "provider": "gemini", "configured_model": ", ".join(configured_models),
        "key_present": bool(os.environ.get("GOOGLE_API_KEY")),
        "reachable": False, "model_exists": None, "models": [], "error": None,
    }
    if not result["key_present"]:
        result["error"] = "GOOGLE_API_KEY not set"
        return result

    try:
        from google import genai
        client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        names = []
        for m in client.models.list():
            actions = getattr(m, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                names.append(str(m.name).replace("models/", ""))
        result["reachable"] = True
        result["models"] = sorted(names)
        missing = [m for m in configured_models if m not in names]
        result["model_exists"] = not missing
        if missing:
            result["error"] = f"configured model(s) not listed: {', '.join(missing)}"
    except Exception as exc:
        result["error"] = _truncate(exc)
    return result


# ── Groq ─────────────────────────────────────────────────────────────────────

def probe_groq(configured_models: list[str]) -> dict:
    result = {
        "provider": "groq", "configured_model": ", ".join(configured_models),
        "key_present": bool(os.environ.get("GROQ_API_KEY")),
        "reachable": False, "model_exists": None, "models": [], "error": None,
    }
    if not result["key_present"]:
        result["error"] = "GROQ_API_KEY not set"
        return result

    try:
        from groq import Groq
        client = Groq(api_key=os.environ["GROQ_API_KEY"])
        names = sorted(m.id for m in client.models.list().data)
        result["reachable"] = True
        result["models"] = names
        missing = [m for m in configured_models if m not in names]
        result["model_exists"] = not missing
        if missing:
            result["error"] = f"configured model(s) not served: {', '.join(missing)}"
    except Exception as exc:
        result["error"] = _truncate(exc)
    return result


# ── Live completion through the real router ──────────────────────────────────

async def probe_live() -> dict:
    from llm import (LLMTelemetry, call_llm, reset_current_telemetry,
                     set_current_telemetry)
    from agents.base_agent import get_llm

    telemetry = LLMTelemetry()
    token = set_current_telemetry(telemetry)
    started = time.monotonic()
    out: dict = {"ok": False, "error": None}
    try:
        chain = get_llm()
        out["chain"] = [str(a) for a in chain]
        text = await call_llm(
            chain,
            [{"role": "system", "content": "Reply with JSON only."},
             {"role": "user", "content": 'Return exactly {"ok":true}'}],
            agent="HealthCheck",
        )
        out["ok"] = True
        out["response"] = _truncate(text, 80)
    except Exception as exc:
        out["error"] = _truncate(exc)
    finally:
        reset_current_telemetry(token)

    out["duration_ms"] = int((time.monotonic() - started) * 1000)
    out["by_provider"] = telemetry.by_provider()
    out["primary_success_rate"] = telemetry.primary_provider_success_rate()
    out["served_by"] = next(
        (r.provider for r in telemetry.records if r.success), None
    )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="also send a real completion through the router")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--list-models", action="store_true",
                        help="print every model each provider serves")
    args = parser.parse_args()

    # Import the defaults rather than restating them — a second copy here would
    # drift from the router and report on a model the app does not actually use.
    from llm.providers import (DEFAULT_GEMINI_MODEL, DEFAULT_GEMINI_FALLBACK_MODEL,
                               DEFAULT_GROQ_MODEL, DEFAULT_GROQ_FALLBACK_MODEL)

    gemini_models = [
        os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
        os.environ.get("GEMINI_FALLBACK_MODEL") or DEFAULT_GEMINI_FALLBACK_MODEL,
    ]
    groq_models = [
        os.environ.get("GROQ_MODEL") or DEFAULT_GROQ_MODEL,
        os.environ.get("GROQ_FALLBACK_MODEL") or DEFAULT_GROQ_FALLBACK_MODEL,
    ]
    primary = (os.environ.get("LLM_PRIMARY_PROVIDER") or "gemini").lower()

    probes = [probe_gemini(gemini_models), probe_groq(groq_models)]
    configured = [p for p in probes if p["key_present"]]

    live = asyncio.run(probe_live()) if args.live else None

    if args.json:
        print(json.dumps({"primary_provider": primary, "probes": probes,
                          "live": live}, indent=2))
    else:
        print(f"Primary provider: {primary}\n")
        for p in probes:
            if not p["key_present"]:
                print(f"  [--] {p['provider']:8} no API key set - tier skipped")
                continue
            if not p["reachable"]:
                print(f"  [!!] {p['provider']:8} UNREACHABLE - {p['error']}")
                continue
            mark = "ok" if p["model_exists"] else "!!"
            state = "serves" if p["model_exists"] else "DOES NOT SERVE"
            print(f"  [{mark}] {p['provider']:8} reachable, {state} {p['configured_model']}"
                  f"  ({len(p['models'])} models listed)")
            if p["error"]:
                print(f"       {p['error']}")
            if args.list_models:
                for name in p["models"]:
                    print(f"         - {name}")

        if not args.live:
            print("\n  note: a model can be LISTED yet 404 on use (deprecated models stay\n"
                  "        visible to the listing API). Use --live to actually exercise it.")

        if live:
            print()
            if live["ok"]:
                print(f"  [ok] live completion served by '{live['served_by']}' "
                      f"in {live['duration_ms']}ms")
                if live["served_by"] != primary:
                    print(f"  [!!] expected '{primary}' to serve this - "
                          f"you are silently running on the fallback tier")
            else:
                print(f"  [!!] live completion FAILED - {live['error']}")
            print(f"       chain: {' -> '.join(live['chain'])}")

    if not configured:
        print("\nNo provider configured. Set GOOGLE_API_KEY and/or GROQ_API_KEY.")
        return 2

    problems = [p for p in configured if not p["reachable"] or not p["model_exists"]]
    if live and not live["ok"]:
        problems.append({"provider": "live"})
    if problems:
        print(f"\n{len(problems)} problem(s) found.")
        return 1

    print("\nAll configured providers healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
