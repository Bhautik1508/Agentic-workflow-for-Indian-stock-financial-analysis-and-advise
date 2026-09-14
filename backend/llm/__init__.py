"""LLM routing layer.

`providers.py` adapts each vendor (Gemini via google-genai, Groq via AsyncGroq)
onto one `complete()` coroutine, so the router is vendor-agnostic.

`telemetry.py` defines the per-call record + a contextvar-based collector that
the runner sets at the start of each analysis, so we get a per-run breakdown
of model usage / latency / cost without threading state through every agent.

`health.py` probes each provider (and optionally sends a real completion) so a
retired model surfaces as a red health check instead of a silent outage.

`router.py` walks an ordered chain of (provider, model) attempts — Gemini
primary, Groq fallback by default — and returns the first success, recording
telemetry for every attempt along the way.

Configure via env (see .env.example):
    GOOGLE_API_KEY, GEMINI_MODEL, GEMINI_THINKING_BUDGET, GEMINI_RETRIES
    GROQ_API_KEY,   GROQ_MODEL,   GROQ_FALLBACK_MODEL
    LLM_PRIMARY_PROVIDER=gemini|groq   # flip the order without a code change
"""

from .telemetry import (
    LLMCallRecord,
    LLMTelemetry,
    current_telemetry,
    set_current_telemetry,
    reset_current_telemetry,
)
from .providers import (
    Attempt,
    CompletionResult,
    GeminiProvider,
    GroqProvider,
    OpenAICompatProvider,
    build_default_chain,
)
from .health import ProviderHealth, check_live, check_providers, full_report
from .router import call_llm

__all__ = [
    "LLMCallRecord",
    "LLMTelemetry",
    "current_telemetry",
    "set_current_telemetry",
    "reset_current_telemetry",
    "Attempt",
    "CompletionResult",
    "GeminiProvider",
    "GroqProvider",
    "OpenAICompatProvider",
    "build_default_chain",
    "call_llm",
    "ProviderHealth",
    "check_providers",
    "check_live",
    "full_report",
]
