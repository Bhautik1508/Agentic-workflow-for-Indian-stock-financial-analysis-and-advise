"""Forward-return backtest over the run log — "were we right?".

Every analysis already writes a run log with the verdict, the ticker and a
timestamp. Joining those against realised prices is the only thing that turns
the verdict from a plausible-sounding narrative into a measured claim.

Honesty constraints baked in:

- A verdict is only scorable once the horizon has actually elapsed. A BUY from
  yesterday has no 1-month return, and counting it as 0% would quietly bias the
  hit-rate toward whatever the recent market did.
- HOLD is excluded from hit-rate. There is no honest definition of a "correct"
  HOLD without a benchmark, and inventing one inflates the number.
- The sample size is reported next to every rate. A 100% hit-rate on 3 verdicts
  is not evidence of anything, and presenting it without n invites that error.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .bands import normalize_band

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

# Bands that express a directional call. HOLD is deliberately absent.
BULLISH = {"BUY", "STRONG_BUY"}
BEARISH = {"SELL", "STRONG_SELL"}

HORIZONS = {"1M": 30, "3M": 90, "6M": 180}


# A hit-rate is only meaningful above a sample size. Below this the number is
# noise, and tuning anything on it is fitting to noise — stated explicitly
# because a 100% hit-rate on three verdicts is exactly the sort of figure that
# gets acted on.
MIN_CREDIBLE_SAMPLE = 50


@dataclass
class VerdictRecord:
    run_id: str
    ticker: str
    action: str
    confidence: Optional[float]
    timestamp: datetime
    profile: Optional[str] = None
    target_price: Optional[float] = None
    stop_loss: Optional[float] = None
    analysis_version: str = "legacy"


def load_verdicts(run_log_dir: str) -> List[VerdictRecord]:
    """Read every run log that produced a directional or hold verdict."""
    out: List[VerdictRecord] = []
    if not os.path.isdir(run_log_dir):
        return out
    for name in sorted(os.listdir(run_log_dir)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(run_log_dir, name)) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        judge = data.get("judge") or {}
        action = normalize_band(judge.get("action") or judge.get("final_decision"))
        ticker = data.get("ticker")
        stamp = data.get("timestamp_ist")
        if not (action and ticker and stamp):
            continue
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        out.append(VerdictRecord(
            analysis_version=data.get("analysis_version") or "legacy",
            run_id=data.get("run_id", name),
            ticker=ticker,
            action=action,
            confidence=judge.get("confidence_score"),
            timestamp=when,
            profile=(data.get("inputs_summary") or {}).get("risk_profile"),
            target_price=judge.get("target_price_inr"),
            stop_loss=judge.get("stop_loss_inr"),
        ))
    return out


def forward_return(prices: Dict[str, float], start: datetime, days: int) -> Optional[float]:
    """Percent return from the close on/after `start` to the close ~`days` later.

    `prices` maps YYYY-MM-DD to close. Returns None when either end is missing,
    which is the honest answer for a horizon that has not elapsed.
    """
    if not prices:
        return None
    ordered = sorted(prices)

    def close_on_or_after(day: datetime) -> Optional[tuple]:
        key = day.strftime("%Y-%m-%d")
        for d in ordered:
            if d >= key:
                return d, prices[d]
        return None

    begin = close_on_or_after(start)
    if begin is None:
        return None
    end = close_on_or_after(start + timedelta(days=days))
    if end is None or end[0] == begin[0]:
        return None
    if begin[1] <= 0:
        return None
    return round((end[1] - begin[1]) / begin[1] * 100.0, 2)


def group_by_version(verdicts: List[VerdictRecord]) -> Dict[str, List[VerdictRecord]]:
    """Split verdicts by the engine that produced them."""
    cohorts: Dict[str, List[VerdictRecord]] = {}
    for v in verdicts:
        cohorts.setdefault(v.analysis_version, []).append(v)
    return cohorts


def score_verdicts(
    verdicts: List[VerdictRecord],
    price_history: Dict[str, Dict[str, float]],
    horizons: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Join verdicts to realised returns and summarise per horizon.

    `price_history` maps ticker -> {YYYY-MM-DD: close}. Passed in rather than
    fetched so this stays unit-testable.
    """
    horizons = horizons or HORIZONS
    per_horizon: Dict[str, Dict[str, Any]] = {}
    rows: List[Dict[str, Any]] = []

    for label, days in horizons.items():
        hits = 0
        scored = 0
        returns: List[float] = []
        for v in verdicts:
            ret = forward_return(price_history.get(v.ticker, {}), v.timestamp, days)
            if ret is None:
                continue
            if v.action not in BULLISH and v.action not in BEARISH:
                continue        # HOLD has no honest definition of "right"
            scored += 1
            correct = (ret > 0) if v.action in BULLISH else (ret < 0)
            hits += int(correct)
            returns.append(ret if v.action in BULLISH else -ret)
            rows.append({
                "run_id": v.run_id, "ticker": v.ticker, "action": v.action,
                "horizon": label, "return_pct": ret, "correct": correct,
                "confidence": v.confidence,
            })
        per_horizon[label] = {
            "scored": scored,
            "hits": hits,
            # None, not 0.0 — an unmeasured horizon is unknown, not a failure.
            "hit_rate": round(hits / scored, 3) if scored else None,
            "avg_directional_return_pct": round(sum(returns) / len(returns), 2) if returns else None,
            "note": "insufficient elapsed time" if scored == 0 else "",
        }

    directional = [v for v in verdicts if v.action in BULLISH or v.action in BEARISH]
    scored_1m = per_horizon.get("1M", {}).get("scored", 0)
    return {
        "verdicts_total": len(verdicts),
        "verdicts_directional": len(directional),
        "verdicts_hold": len(verdicts) - len(directional),
        "by_horizon": per_horizon,
        "sample_is_credible": scored_1m >= MIN_CREDIBLE_SAMPLE,
        "min_credible_sample": MIN_CREDIBLE_SAMPLE,
        "rows": rows,
    }


def score_by_cohort(
    verdicts: List[VerdictRecord],
    price_history: Dict[str, Dict[str, float]],
    horizons: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Score each engine cohort separately, and never pool them.

    Pooling a pre-Phase-A cohort (beta fabricated at 1.00, fundamentals 20%
    complete) with the current engine produces a hit-rate that describes neither.
    """
    from analysis_version import ANALYSIS_VERSION, describe

    cohorts = group_by_version(verdicts)
    out: Dict[str, Any] = {
        "current_version": ANALYSIS_VERSION,
        "cohorts": {},
        "pooled_is_meaningful": len(cohorts) <= 1,
    }
    for version, group in sorted(cohorts.items()):
        result = score_verdicts(group, price_history, horizons)
        result["description"] = describe(version)
        result["is_current"] = version == ANALYSIS_VERSION
        out["cohorts"][version] = result
    return out
