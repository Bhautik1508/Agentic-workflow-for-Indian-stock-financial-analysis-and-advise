"""Per-run LLM telemetry.

The runner sets a `LLMTelemetry` instance into a contextvar at the start of
each analysis. Every call_llm invocation reads that contextvar and appends a
record. After the run, the routes layer harvests it for the run log.

Using a contextvar (not a global, not threading.local) means an event loop
running multiple analyses concurrently will see one collector per task."""

import statistics
from contextvars import ContextVar
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from .pricing import estimate_cost, is_configured as pricing_is_configured


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
    fallback_used: bool = False      # True for any attempt after the first
    provider: str = "unknown"        # "gemini" | "groq" | test doubles
    attempt: int = 1                 # 1-based position in the failover chain

    @property
    def estimated_cost_usd(self) -> Optional[float]:
        """None when this model has no configured rate — see llm/pricing.py.
        None is rendered as "not set"; it is deliberately not 0.0, which would
        read as "this call was free"."""
        return estimate_cost(self.model, self.prompt_tokens, self.completion_tokens)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["estimated_cost_usd"] = self.estimated_cost_usd
        return data


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

    def by_provider(self) -> Dict[str, Dict[str, Any]]:
        """Per-provider rollup. Makes "did Gemini actually serve this run, or did
        everything quietly fall through to Groq?" answerable from the run log."""
        out: Dict[str, Dict[str, Any]] = {}
        for r in self.records:
            bucket = out.setdefault(
                r.provider,
                {"calls": 0, "successes": 0, "failures": 0, "tokens": 0, "duration_ms": 0},
            )
            bucket["calls"] += 1
            bucket["successes" if r.success else "failures"] += 1
            bucket["tokens"] += r.total_tokens
            bucket["duration_ms"] += r.duration_ms
            cost = r.estimated_cost_usd
            if cost is not None:
                bucket["cost_usd"] = round((bucket.get("cost_usd") or 0.0) + cost, 6)
        return out

    def primary_provider_success_rate(self) -> Optional[float]:
        """Share of first-attempt calls that succeeded. None when no calls were made."""
        first_attempts = [r for r in self.records if r.attempt == 1]
        if not first_attempts:
            return None
        return round(sum(1 for r in first_attempts if r.success) / len(first_attempts), 3)

    def total_cost_usd(self) -> Optional[float]:
        """Sum of priced calls. None when nothing could be priced at all."""
        costs = [c for c in (r.estimated_cost_usd for r in self.records) if c is not None]
        return round(sum(costs), 6) if costs else None

    def unpriced_calls(self) -> int:
        return sum(1 for r in self.records if r.estimated_cost_usd is None)

    def _percentiles(self, values: List[int]) -> Dict[str, int]:
        if not values:
            return {"p50": 0, "p95": 0, "max": 0}
        ordered = sorted(values)
        # Nearest-rank p95: with 6 calls per run, interpolation would invent
        # precision the sample size does not support.
        idx95 = max(0, min(len(ordered) - 1, int(round(0.95 * len(ordered))) - 1))
        return {
            "p50": int(statistics.median(ordered)),
            "p95": int(ordered[idx95]),
            "max": int(ordered[-1]),
        }

    def latency(self) -> Dict[str, Any]:
        """Overall and per-agent latency. The judge is serialised behind all
        five analysts, so it sits on the critical path and is worth watching
        separately from the fan-out."""
        per_agent: Dict[str, Any] = {}
        for record in self.records:
            per_agent.setdefault(record.agent, []).append(record.duration_ms)
        return {
            "overall": self._percentiles([r.duration_ms for r in self.records]),
            "by_agent": {
                agent: {**self._percentiles(durations), "calls": len(durations)}
                for agent, durations in sorted(per_agent.items())
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls":       self.total_calls(),
            "total_tokens":      self.total_tokens(),
            "total_duration_ms": self.total_duration_ms(),
            "fallback_calls":    self.fallback_calls(),
            "failed_calls":      self.failed_calls(),
            "by_provider":       self.by_provider(),
            "primary_success_rate": self.primary_provider_success_rate(),
            "estimated_cost_usd": self.total_cost_usd(),
            "pricing_configured": pricing_is_configured(),
            "unpriced_calls":    self.unpriced_calls(),
            "latency":           self.latency(),
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
