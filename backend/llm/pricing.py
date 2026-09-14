"""Per-model token pricing, so every run can report what it cost.

A deliberate design note on the numbers
---------------------------------------
This module ships the *mechanism* fully working but the *rates* unset. Vendor
prices change, and the models this app defaults to (`gemini-3.5-flash-lite`,
`gemini-3.6-flash`) are newer than any table that could be baked in here with
confidence. Inventing plausible-looking rates for a tool that reports money
would be worse than reporting nothing: a wrong cost is believed, a missing one
is questioned.

So an unpriced model yields `cost_usd = None` and `pricing_configured = False`,
which the UI renders as "pricing not set" rather than as "$0.00". Fill the rates
in once and every run reports real money.

Two ways to set them, override order low to high:

1. Edit `DEFAULT_PRICING` below.
2. Set `LLM_PRICING_JSON` to a JSON object — handy on Render, where you can
   update prices without a redeploy:

       LLM_PRICING_JSON={"gemini-3.5-flash-lite":{"input":0.10,"output":0.40}}

   Values are USD per 1M tokens. Keys are matched case-insensitively, and a
   prefix match is attempted so `gemini-3.6-flash-preview` inherits
   `gemini-3.6-flash` unless it has its own entry.

Current rates: Gemini https://ai.google.dev/pricing · Groq https://groq.com/pricing
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1,000,000 tokens."""
    input_per_1m: float
    output_per_1m: float
    note: str = ""

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            (prompt_tokens / 1_000_000.0) * self.input_per_1m
            + (completion_tokens / 1_000_000.0) * self.output_per_1m
        )


# Intentionally empty — see the module docstring. Add entries as:
#   "gemini-3.6-flash": ModelPrice(input_per_1m=..., output_per_1m=..., note="checked YYYY-MM-DD"),
DEFAULT_PRICING: Dict[str, ModelPrice] = {}


def _load_env_pricing() -> Dict[str, ModelPrice]:
    raw = (os.environ.get("LLM_PRICING_JSON") or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning(f"[pricing] LLM_PRICING_JSON is not valid JSON ({exc}); ignoring it")
        return {}

    out: Dict[str, ModelPrice] = {}
    for model, entry in (parsed or {}).items():
        try:
            out[str(model).lower()] = ModelPrice(
                input_per_1m=float(entry["input"]),
                output_per_1m=float(entry["output"]),
                note="from LLM_PRICING_JSON",
            )
        except (TypeError, ValueError, KeyError):
            logger.warning(f"[pricing] ignoring malformed entry for '{model}'")
    return out


def pricing_table() -> Dict[str, ModelPrice]:
    """Defaults merged with env overrides. Read fresh so env changes apply
    without a restart in long-lived processes."""
    table = {k.lower(): v for k, v in DEFAULT_PRICING.items()}
    table.update(_load_env_pricing())
    return table


def price_for(model: str) -> Optional[ModelPrice]:
    """Exact match, else the longest prefix match, else None."""
    if not model:
        return None
    table = pricing_table()
    key = str(model).lower()
    if key in table:
        return table[key]
    candidates = [k for k in table if key.startswith(k)]
    if candidates:
        return table[max(candidates, key=len)]
    return None


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Optional[float]:
    """USD for one call, or None when the model has no configured rate."""
    price = price_for(model)
    if price is None:
        return None
    return round(price.cost(int(prompt_tokens or 0), int(completion_tokens or 0)), 6)


def is_configured() -> bool:
    return bool(pricing_table())
