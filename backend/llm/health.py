"""Provider health checks.

Exists because a vendor retiring a model took the whole app down silently:
Groq removed `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`, every call
404'd, and nothing anywhere noticed. Later the same class of failure repeated
on the other side — the whole `gemini-2.5-*` family became 404 for
newly-created keys.

Two levels, deliberately:

- `check_providers()` lists each vendor's models and asserts the configured IDs
  are present. Cheap, but **not sufficient** — a deprecated model stays visible
  to the listing API while 404-ing on use. That exact gap reported
  `gemini-2.5-flash` as healthy while every real call failed.
- `check_live()` sends a real completion through the router. Slower, and the
  only check that actually proves the pipeline works.

Shared by `GET /api/health?deep=true` and `scripts/check_llm_health.py` so the
two cannot drift.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from .providers import (
    DEFAULT_GEMINI_FALLBACK_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_GROQ_FALLBACK_MODEL,
    DEFAULT_GROQ_MODEL,
    GeminiProvider,
    GroqProvider,
)

# A health check must never hang the caller — Render polls /api/health.
PROBE_TIMEOUT_SECONDS = float(os.environ.get("LLM_HEALTH_TIMEOUT", "20") or 20)


@dataclass
class ProviderHealth:
    provider: str
    configured_models: List[str]
    key_present: bool
    reachable: bool = False
    model_exists: Optional[bool] = None
    missing_models: List[str] = field(default_factory=list)
    available_model_count: int = 0
    available_models: List[str] = field(default_factory=list)
    latency_ms: int = 0
    error: Optional[str] = None

    @property
    def healthy(self) -> bool:
        """An unconfigured provider is not unhealthy — it is simply not a tier."""
        if not self.key_present:
            return True
        return self.reachable and bool(self.model_exists)

    def to_dict(self, *, include_model_list: bool = False) -> Dict[str, Any]:
        data = asdict(self)
        data["healthy"] = self.healthy
        if not include_model_list:
            data.pop("available_models", None)
        return data


def _truncate(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[:limit] + "..."


def configured_models() -> Dict[str, List[str]]:
    """The model IDs the router will actually use, in chain order."""
    return {
        "gemini": [
            os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL,
            os.environ.get("GEMINI_FALLBACK_MODEL") or DEFAULT_GEMINI_FALLBACK_MODEL,
        ],
        "groq": [
            os.environ.get("GROQ_MODEL") or DEFAULT_GROQ_MODEL,
            os.environ.get("GROQ_FALLBACK_MODEL") or DEFAULT_GROQ_FALLBACK_MODEL,
        ],
    }


def _list_gemini_models(api_key: str) -> List[str]:
    from google import genai

    client = genai.Client(api_key=api_key)
    names: List[str] = []
    for model in client.models.list():
        actions = getattr(model, "supported_actions", None) or []
        if not actions or "generateContent" in actions:
            names.append(str(model.name).replace("models/", ""))
    return sorted(names)


def _list_groq_models(api_key: str) -> List[str]:
    from groq import Groq

    return sorted(m.id for m in Groq(api_key=api_key).models.list().data)


async def _probe(provider_name: str, models: List[str]) -> ProviderHealth:
    provider = GeminiProvider() if provider_name == "gemini" else GroqProvider()
    health = ProviderHealth(
        provider=provider_name,
        configured_models=models,
        key_present=provider.is_configured(),
    )
    if not health.key_present:
        health.error = f"{'GOOGLE' if provider_name == 'gemini' else 'GROQ'}_API_KEY not set"
        return health

    lister = _list_gemini_models if provider_name == "gemini" else _list_groq_models
    api_key = provider._api_key  # noqa: SLF001 — same package, deliberate
    started = time.monotonic()
    try:
        names = await asyncio.wait_for(
            asyncio.to_thread(lister, api_key), timeout=PROBE_TIMEOUT_SECONDS
        )
        health.reachable = True
        health.available_models = names
        health.available_model_count = len(names)
        health.missing_models = [m for m in models if m not in names]
        health.model_exists = not health.missing_models
        if health.missing_models:
            health.error = f"configured model(s) not listed: {', '.join(health.missing_models)}"
    except asyncio.TimeoutError:
        health.error = f"timed out after {PROBE_TIMEOUT_SECONDS:.0f}s"
    except Exception as exc:
        health.error = _truncate(exc)
    health.latency_ms = int((time.monotonic() - started) * 1000)
    return health


async def check_providers() -> List[ProviderHealth]:
    """Probe every provider concurrently."""
    wanted = configured_models()
    return list(await asyncio.gather(*(_probe(name, models) for name, models in wanted.items())))


async def check_live() -> Dict[str, Any]:
    """Send a real completion through the router — the only check that proves
    the pipeline end to end, including which vendor actually answered."""
    from agents.base_agent import get_llm

    from .router import call_llm
    from .telemetry import LLMTelemetry, reset_current_telemetry, set_current_telemetry

    telemetry = LLMTelemetry()
    token = set_current_telemetry(telemetry)
    started = time.monotonic()
    result: Dict[str, Any] = {"ok": False, "error": None}
    try:
        chain = get_llm()
        result["chain"] = [str(a) for a in chain]
        text = await asyncio.wait_for(
            call_llm(
                chain,
                [
                    {"role": "system", "content": "Reply with JSON only."},
                    {"role": "user", "content": 'Return exactly {"ok":true}'},
                ],
                agent="HealthCheck",
            ),
            timeout=PROBE_TIMEOUT_SECONDS * 3,
        )
        result["ok"] = True
        result["response"] = _truncate(text, 80)
    except asyncio.TimeoutError:
        result["error"] = "live completion timed out"
    except Exception as exc:
        result["error"] = _truncate(exc)
    finally:
        reset_current_telemetry(token)

    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    result["served_by"] = next((r.provider for r in telemetry.records if r.success), None)
    result["by_provider"] = telemetry.by_provider()
    return result


async def full_report(*, live: bool = False, include_model_list: bool = False) -> Dict[str, Any]:
    """Everything the /api/health?deep=true endpoint and the CLI both render."""
    providers = await check_providers()
    primary = (os.environ.get("LLM_PRIMARY_PROVIDER") or "gemini").strip().lower()
    report: Dict[str, Any] = {
        "primary_provider": primary,
        "providers": [p.to_dict(include_model_list=include_model_list) for p in providers],
        "healthy": all(p.healthy for p in providers)
                   and any(p.key_present for p in providers),
    }
    if not any(p.key_present for p in providers):
        report["error"] = ("No LLM provider configured. Set GOOGLE_API_KEY (Gemini, primary) "
                           "and/or GROQ_API_KEY (Groq, fallback).")
    if live:
        report["live"] = await check_live()
        report["healthy"] = report["healthy"] and report["live"]["ok"]
    return report
