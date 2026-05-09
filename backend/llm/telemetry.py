"""Per-run LLM telemetry.

The runner sets a `LLMTelemetry` instance into a contextvar at the start of
each analysis. Every call_llm invocation reads that contextvar and appends a
record. After the run, the routes layer harvests it for the run log.

Using a contextvar (not a global, not threading.local) means an event loop
running multiple analyses concurrently will see one collector per task."""

from contextvars import ContextVar
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional


@dataclass
class LLMCallRecord:
    agent: str                       # which agent made the call (best-effort label)
    model: str
    started_at: str                  # ISO IST
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    success: bool
    error: Optional[str] = None
    fallback_used: bool = False      # True when primary model 429'd and we failed over

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LLMTelemetry:
    records: List[LLMCallRecord] = field(default_factory=list)

    def record(self, rec: LLMCallRecord) -> None:
        self.records.append(rec)

    def total_calls(self) -> int:
        return len(self.records)

    def total_tokens(self) -> int:
        return sum(r.total_tokens for r in self.records)

    def total_duration_ms(self) -> int:
        return sum(r.duration_ms for r in self.records)

    def fallback_calls(self) -> int:
        return sum(1 for r in self.records if r.fallback_used)

    def failed_calls(self) -> int:
        return sum(1 for r in self.records if not r.success)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls":       self.total_calls(),
            "total_tokens":      self.total_tokens(),
            "total_duration_ms": self.total_duration_ms(),
            "fallback_calls":    self.fallback_calls(),
            "failed_calls":      self.failed_calls(),
            "records":           [r.to_dict() for r in self.records],
        }


_current_telemetry: ContextVar[Optional[LLMTelemetry]] = ContextVar(
    "current_llm_telemetry", default=None
)


def current_telemetry() -> Optional[LLMTelemetry]:
    return _current_telemetry.get()


def set_current_telemetry(t: LLMTelemetry):
    """Returns a token the caller MUST pass to reset_current_telemetry to undo."""
    return _current_telemetry.set(t)


def reset_current_telemetry(token) -> None:
    _current_telemetry.reset(token)
