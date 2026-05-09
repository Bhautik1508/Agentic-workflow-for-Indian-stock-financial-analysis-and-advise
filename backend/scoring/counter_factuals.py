"""Counter-factual analysis: 'what would change the verdict?'.

Given the current weighted score and the per-pillar scores, this module
computes — for each pillar, holding the others constant — how much its score
would have to move to push the overall score across the next band threshold.
It also lists structural risks (veto triggers) that would override the
band-based verdict regardless of weighted math.

The goal is to make the verdict feel earned: instead of 'BUY, 78%
confidence', the user sees 'BUY — would become HOLD if Financial drops
below 5.4 OR Risk score falls below 3.0'."""

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

from .profiles import profile_bands

PILLAR_DISPLAY = {
    "financial":  "Financial",
    "technical":  "Technical",
    "risk":       "Risk",
    "sentiment":  "Sentiment",
    "macro_gov":  "Macro & Gov",
}

BAND_ORDER = ["STRONG_SELL", "SELL", "HOLD", "BUY", "STRONG_BUY"]


@dataclass
class PillarSensitivity:
    pillar:                  str    # display label (e.g. 'Financial')
    pillar_key:              str    # internal key (e.g. 'financial')
    current_score:           float
    weight:                  float
    score_at_downgrade:      Optional[float]   # value the pillar would need to drop *to*
    drop_to_downgrade:       Optional[float]   # how far below current
    score_at_upgrade:        Optional[float]
    rise_to_upgrade:         Optional[float]


@dataclass
class CounterFactual:
    current_band:           str
    current_score:          float
    next_worse_band:        Optional[str]
    next_better_band:       Optional[str]
    score_to_next_worse:    Optional[float]    # threshold to fall below
    score_to_next_better:   Optional[float]    # threshold to reach
    pillar_sensitivity:     List[PillarSensitivity] = field(default_factory=list)
    veto_risks:             List[str] = field(default_factory=list)
    notes:                  List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


def _band_thresholds_sorted(profile: str) -> List[tuple]:
    """Return [(band, threshold)] sorted descending by threshold."""
    bands = profile_bands(profile)
    return sorted(bands.items(), key=lambda kv: kv[1], reverse=True)


def _next_lower_threshold(current_band: str, profile: str) -> tuple:
    """Returns (next_worse_band, threshold_to_drop_below) — both may be None."""
    if current_band == "STRONG_SELL":
        return None, None
    idx = BAND_ORDER.index(current_band)
    next_band = BAND_ORDER[idx - 1]
    bands = profile_bands(profile)
    # The threshold for the *current* band is the floor — drop below it and we
    # land in the next worse band.
    return next_band, bands.get(current_band)


def _next_higher_threshold(current_band: str, profile: str) -> tuple:
    """Returns (next_better_band, threshold_to_reach) — both may be None."""
    if current_band == "STRONG_BUY":
        return None, None
    idx = BAND_ORDER.index(current_band)
    next_band = BAND_ORDER[idx + 1]
    bands = profile_bands(profile)
    return next_band, bands.get(next_band)


def _solve_pillar_target(
    current_total: float,
    target_total: float,
    weight: float,
    current_pillar_score: float,
) -> Optional[float]:
    """Given weighted score = sum_i w_i * s_i, isolate one pillar:
       target_total = current_total - w*current_score + w*new_score
       → new_score = (target_total - current_total) / w + current_score

    Returns None if the pillar has zero weight (can't move the total)
    or if the required value is outside [0, 10]."""
    if weight <= 0:
        return None
    new_score = (target_total - current_total) / weight + current_pillar_score
    if new_score < 0 or new_score > 10:
        return None
    return round(new_score, 2)


def compute_counter_factual(
    *,
    weighted_score: float,
    current_band: str,
    pillar_scores: Dict[str, float],
    weights: Dict[str, float],
    profile: str,
    risk_pillar_score: Optional[float] = None,
) -> CounterFactual:
    """Build the full counter-factual view.

    Pillars whose score is None / missing are skipped (degraded analysts can't
    contribute to a what-if). Weights are taken as-is — whatever the judge
    actually used after dropping degraded pillars."""

    next_worse, drop_threshold = _next_lower_threshold(current_band, profile)
    next_better, rise_threshold = _next_higher_threshold(current_band, profile)

    sensitivity: List[PillarSensitivity] = []
    for key, label in PILLAR_DISPLAY.items():
        score = pillar_scores.get(key)
        weight = weights.get(key, 0.0)
        if score is None or weight <= 0:
            continue

        # To downgrade: the total must fall below `drop_threshold`. We want the
        # value the pillar would need to drop *to* such that total = drop_threshold.
        score_at_down: Optional[float] = None
        drop_to_down: Optional[float] = None
        if drop_threshold is not None:
            target = _solve_pillar_target(weighted_score, drop_threshold, weight, score)
            if target is not None and target < score:
                score_at_down = target
                drop_to_down = round(score - target, 2)

        # To upgrade: total must reach `rise_threshold`.
        score_at_up: Optional[float] = None
        rise_to_up: Optional[float] = None
        if rise_threshold is not None:
            target = _solve_pillar_target(weighted_score, rise_threshold, weight, score)
            if target is not None and target > score:
                score_at_up = target
                rise_to_up = round(target - score, 2)

        sensitivity.append(PillarSensitivity(
            pillar=label,
            pillar_key=key,
            current_score=round(score, 2),
            weight=round(weight, 4),
            score_at_downgrade=score_at_down,
            drop_to_downgrade=drop_to_down,
            score_at_upgrade=score_at_up,
            rise_to_upgrade=rise_to_up,
        ))

    # Sort by sensitivity: pillars where a small drop downgrades the verdict come first.
    # If no drop is possible (e.g. STRONG_SELL is current), fall back to weight order.
    def sort_key(p: PillarSensitivity) -> float:
        return p.drop_to_downgrade if p.drop_to_downgrade is not None else 1e9
    sensitivity.sort(key=sort_key)

    # Veto / structural risks (independent of weighted math).
    veto_risks: List[str] = []
    if risk_pillar_score is not None and risk_pillar_score >= 3.0:
        gap = round(risk_pillar_score - 3.0, 1)
        veto_risks.append(
            f"Risk score must stay ≥ 3.0; currently {risk_pillar_score:.1f} (buffer {gap:.1f})."
        )
    if current_band in ("STRONG_BUY", "BUY"):
        veto_risks.append(
            "Any of: Altman Z < 1.8, promoter pledge > 50%, NSE ASM Stage 2+, "
            "or going-concern qualification → SELL or STRONG_SELL regardless of score."
        )

    notes: List[str] = []
    if not sensitivity:
        notes.append("No live pillars available for sensitivity analysis.")
    elif drop_threshold is None and rise_threshold is None:
        notes.append("Verdict is at a band boundary.")

    return CounterFactual(
        current_band=current_band,
        current_score=round(weighted_score, 2),
        next_worse_band=next_worse,
        next_better_band=next_better,
        score_to_next_worse=drop_threshold,
        score_to_next_better=rise_threshold,
        pillar_sensitivity=sensitivity,
        veto_risks=veto_risks,
        notes=notes,
    )
