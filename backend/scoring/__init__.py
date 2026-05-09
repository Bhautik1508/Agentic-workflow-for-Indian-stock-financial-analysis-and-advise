"""Phase 2 — quantitative grounding for verdicts.

The judge LLM is good at narrative synthesis, bad at price math. This package
moves price targets, stop losses, and position sizing onto deterministic
formulas so they can be reproduced and challenged.
"""

from .grounded_pricing import (
    GroundedTargets,
    compute_fundamental_target,
    compute_technical_target,
    compute_atr_stop,
    compute_position_size_modifier,
    reconcile_targets,
)
from .profiles import (
    INVESTOR_PROFILES,
    DEFAULT_PROFILE,
    get_profile,
    profile_weights,
    profile_bands,
    band_for_score,
)
from .vetos import VetoResult, evaluate_vetos
from .counter_factuals import (
    CounterFactual,
    PillarSensitivity,
    compute_counter_factual,
    PILLAR_DISPLAY,
    BAND_ORDER,
)

__all__ = [
    "GroundedTargets",
    "compute_fundamental_target",
    "compute_technical_target",
    "compute_atr_stop",
    "compute_position_size_modifier",
    "reconcile_targets",
    "INVESTOR_PROFILES",
    "DEFAULT_PROFILE",
    "get_profile",
    "profile_weights",
    "profile_bands",
    "band_for_score",
    "VetoResult",
    "evaluate_vetos",
    "CounterFactual",
    "PillarSensitivity",
    "compute_counter_factual",
    "PILLAR_DISPLAY",
    "BAND_ORDER",
]
