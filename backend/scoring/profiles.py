"""Investor risk profiles. Determines (a) how the five analysts are weighted
in the verdict and (b) the score thresholds used for each verdict band.

A retiree and a 25-year-old with a 10-year horizon shouldn't get the same
verdict on a high-beta small-cap. Profile selection is the cleanest way to
honour that without retraining anything."""

from typing import Dict, Tuple


DEFAULT_PROFILE = "balanced"


# Each profile defines:
#   weights: must sum to 1.0
#   bands:   minimum weighted score to earn each band (descending)
#   max_position_size: ceiling for grounded position-size modifier
INVESTOR_PROFILES: Dict[str, Dict] = {
    "conservative": {
        "weights": {
            "financial":  0.30,
            "technical":  0.13,
            "risk":       0.32,
            "sentiment":  0.06,
            "macro_gov":  0.19,
        },
        "bands": {
            "STRONG_BUY":   8.0,
            "BUY":          7.0,
            "HOLD":         5.0,   # below 5.0 starts the SELL ladder
            "SELL":         4.0,
            "STRONG_SELL":  2.5,
        },
        "max_position_size": 0.5,
        "description": "Capital preservation. Risk pillar dominates; needs strong "
                       "fundamentals to justify a BUY; lower position sizing.",
    },
    "balanced": {
        "weights": {
            "financial":  0.30,
            "technical":  0.23,
            "risk":       0.22,
            "sentiment":  0.12,
            "macro_gov":  0.13,
        },
        "bands": {
            "STRONG_BUY":   7.5,
            "BUY":          6.0,
            "HOLD":         4.5,
            "SELL":         3.5,
            "STRONG_SELL":  3.0,
        },
        "max_position_size": 1.0,
        "description": "Standard mix. Same as the default judge weights.",
    },
    "aggressive": {
        "weights": {
            "financial":  0.25,
            "technical":  0.30,
            "risk":       0.13,
            "sentiment":  0.17,
            "macro_gov":  0.15,
        },
        "bands": {
            "STRONG_BUY":   7.0,
            "BUY":          5.5,
            "HOLD":         4.0,
            "SELL":         3.0,
            "STRONG_SELL":  2.0,
        },
        "max_position_size": 1.5,
        "description": "Momentum + sentiment driven; tolerates more risk for upside.",
    },
}


def get_profile(name: str) -> Tuple[str, Dict]:
    """Returns (canonical_name, profile_spec). Falls back to default for unknown names."""
    if not name:
        return DEFAULT_PROFILE, INVESTOR_PROFILES[DEFAULT_PROFILE]
    canonical = name.strip().lower()
    if canonical not in INVESTOR_PROFILES:
        return DEFAULT_PROFILE, INVESTOR_PROFILES[DEFAULT_PROFILE]
    return canonical, INVESTOR_PROFILES[canonical]


def profile_weights(name: str) -> Dict[str, float]:
    _, spec = get_profile(name)
    weights = dict(spec["weights"])
    # Defensive renormalization in case the spec drifts numerically.
    total = sum(weights.values())
    if total > 0 and abs(total - 1.0) > 1e-6:
        weights = {k: v / total for k, v in weights.items()}
    return weights


def profile_bands(name: str) -> Dict[str, float]:
    _, spec = get_profile(name)
    return dict(spec["bands"])


def band_for_score(score: float, profile: str) -> str:
    """Map a 0..10 weighted score onto a verdict band using the profile's thresholds.

    Bands cascade from highest to lowest threshold. A score must equal or exceed
    the threshold to earn the band; anything below STRONG_SELL's threshold also
    returns STRONG_SELL."""
    bands = profile_bands(profile)
    if score >= bands["STRONG_BUY"]:
        return "STRONG_BUY"
    if score >= bands["BUY"]:
        return "BUY"
    if score >= bands["HOLD"]:
        return "HOLD"
    if score >= bands["SELL"]:
        return "SELL"
    return "STRONG_SELL"
