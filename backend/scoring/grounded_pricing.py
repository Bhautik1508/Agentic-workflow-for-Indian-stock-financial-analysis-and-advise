"""Deterministic price-target, stop-loss, and position-size math.

Everything here is pure: same inputs → same outputs. No LLM calls. The judge
overrides the LLM's free-form numbers with these once they're computed."""

from dataclasses import dataclass, asdict, field
from statistics import median
from typing import Any, Dict, List, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf guard
        return None
    return f


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ─────────────────────────────────────────────────────────────────────────────
# Fundamental target — sector-median PE × forward EPS
# ─────────────────────────────────────────────────────────────────────────────

def compute_fundamental_target(
    forward_eps: Any,
    sector_median_pe: Any,
    *,
    fallback_eps_from_pe: Optional[tuple] = None,
) -> Optional[float]:
    """Fair value implied by sector-median P/E times forward EPS.

    If forward EPS is unavailable, derives an implied EPS from
    `(current_price / current_pe)` when both are provided.
    """
    eps = _safe_float(forward_eps)
    sector_pe = _safe_float(sector_median_pe)

    if eps is None and fallback_eps_from_pe is not None:
        price, current_pe = fallback_eps_from_pe
        price_f, pe_f = _safe_float(price), _safe_float(current_pe)
        if price_f and pe_f and pe_f > 0:
            eps = price_f / pe_f

    if eps is None or sector_pe is None or sector_pe <= 0:
        return None
    return round(eps * sector_pe, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Technical target — cluster of resistance levels
# ─────────────────────────────────────────────────────────────────────────────

def compute_technical_target(
    current_price: Any,
    *,
    week_52_high: Any = None,
    fib_1618: Any = None,
    nearest_resistance: Any = None,
    analyst_target: Any = None,
) -> Optional[float]:
    """Median of available upside reference levels above the current price.

    Using the median is robust to one wild outlier (a stale 1.618 fib, an
    aspirational analyst target). At least one valid level above current price
    is required."""
    price = _safe_float(current_price)
    if price is None or price <= 0:
        return None

    candidates: List[float] = []
    for raw in (week_52_high, fib_1618, nearest_resistance, analyst_target):
        v = _safe_float(raw)
        if v is None:
            continue
        # Only count levels meaningfully above current price (>=2% upside).
        if v > price * 1.02:
            candidates.append(v)

    if not candidates:
        return None
    return round(float(median(candidates)), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Stop loss — ATR-anchored
# ─────────────────────────────────────────────────────────────────────────────

def compute_atr_stop(
    entry_price: Any,
    atr_14: Any,
    *,
    multiplier: float = 2.0,
    floor_pct: float = 0.03,
    ceiling_pct: float = 0.15,
) -> Optional[float]:
    """Stop = entry − multiplier × ATR, then bounded between 3 % and 15 % below entry.

    The bounds protect against degenerate inputs (zero ATR → stop = entry,
    huge ATR on a recent shock → stop too far away to be a stop)."""
    entry = _safe_float(entry_price)
    atr = _safe_float(atr_14)
    if entry is None or entry <= 0:
        return None

    if atr is None or atr <= 0:
        # Default to a 5 % stop when ATR is unavailable. Better than guessing.
        return round(entry * (1 - 0.05), 2)

    raw = entry - multiplier * atr
    floor = entry * (1 - ceiling_pct)
    ceiling = entry * (1 - floor_pct)
    bounded = _clamp(raw, floor, ceiling)
    return round(bounded, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Position size — volatility-driven
# ─────────────────────────────────────────────────────────────────────────────

def compute_position_size_modifier(
    volatility_1y_pct: Any,
    *,
    profile_max: float = 1.0,
) -> float:
    """Multiplier in [0.1, profile_max]. Higher realised vol → smaller size.

    Calibration: a 20% annual-vol stock gets ~1.0× sizing; 40% vol gets ~0.5×;
    60%+ gets the floor of 0.1×."""
    vol = _safe_float(volatility_1y_pct)
    if vol is None or vol <= 0:
        return _clamp(0.7 * profile_max, 0.1, profile_max)

    # Linear ramp: at 20% vol → 1.0; at 60%+ vol → 0.1
    raw = 1.0 - (vol - 20.0) / 50.0
    return round(_clamp(raw * profile_max, 0.1, profile_max), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Reconciliation
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class GroundedTargets:
    target_price: Optional[float]
    stop_loss: Optional[float]
    position_size_modifier: float
    upside_pct: Optional[float]
    downside_pct: Optional[float]
    reward_to_risk: Optional[float]
    method: str
    components: Dict[str, Optional[float]] = field(default_factory=dict)
    # The price every other number here is measured against. It was computed
    # and discarded, so the UI could show "16.4% below" without ever showing
    # what it was below — leaving every figure relative to an invisible anchor.
    current_price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def reconcile_targets(
    *,
    current_price: Any,
    fundamental_target: Optional[float],
    technical_target: Optional[float],
    llm_target: Any = None,
    analyst_target: Any = None,
    atr_14: Any = None,
    volatility_1y_pct: Any = None,
    profile_max_size: float = 1.0,
) -> GroundedTargets:
    """Reconcile multiple target estimates into a single grounded view.

    Method precedence:
      1. average of (fundamental, technical) — when both exist
      2. fundamental only
      3. technical only
      4. analyst median
      5. LLM number (last resort, capped at ±25 % of current price)
      6. None — verdict has no price target
    """
    price = _safe_float(current_price)
    components: Dict[str, Optional[float]] = {
        "fundamental": fundamental_target,
        "technical":   technical_target,
        "analyst":     _safe_float(analyst_target),
        "llm":         _safe_float(llm_target),
    }

    target: Optional[float] = None
    method = "none"

    if fundamental_target is not None and technical_target is not None:
        target = round((fundamental_target + technical_target) / 2.0, 2)
        method = "blended_fundamental_technical"
    elif fundamental_target is not None:
        target = fundamental_target
        method = "fundamental_only"
    elif technical_target is not None:
        target = technical_target
        method = "technical_only"
    elif components["analyst"] is not None:
        target = round(components["analyst"], 2)
        method = "analyst_consensus"
    elif components["llm"] is not None and price is not None:
        # Cap the LLM number at ±25 % of current price so it can't go wild.
        llm_v = components["llm"]
        capped = _clamp(llm_v, price * 0.75, price * 1.25)
        target = round(capped, 2)
        method = "llm_capped"

    stop = compute_atr_stop(price, atr_14)
    pos_size = compute_position_size_modifier(volatility_1y_pct, profile_max=profile_max_size)

    upside = downside = rr = None
    if price and target:
        upside = round((target - price) / price * 100, 2)
    if price and stop:
        downside = round((price - stop) / price * 100, 2)
    if upside is not None and downside is not None and downside > 0:
        rr = round(upside / downside, 2)

    return GroundedTargets(
        target_price=target,
        stop_loss=stop,
        position_size_modifier=pos_size,
        upside_pct=upside,
        downside_pct=downside,
        reward_to_risk=rr,
        method=method,
        components=components,
        current_price=round(float(price), 2) if price else None,
    )
