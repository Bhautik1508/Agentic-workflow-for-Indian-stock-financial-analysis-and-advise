"""LLM routing layer.

`telemetry.py` defines the per-call record + a contextvar-based collector that
the runner sets at the start of each analysis, so we get a per-run breakdown
of model usage / latency / cost without threading state through every agent.

`router.py` calls Groq via the existing SDK and wraps the call with telemetry
+ retry logic. An OpenAI fallback hook is in place but disabled until an API
key is configured — flipping it on is a one-line change."""

from .telemetry import (
    LLMCallRecord,
    LLMTelemetry,
    current_telemetry,
    set_current_telemetry,
    reset_current_telemetry,
)
from .router import call_llm

__all__ = [
    "LLMCallRecord",
    "LLMTelemetry",
    "current_telemetry",
    "set_current_telemetry",
    "reset_current_telemetry",
    "call_llm",
]
