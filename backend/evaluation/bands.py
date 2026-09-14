"""Verdict bands as an ordered scale, so "how wrong is this?" has an answer."""

from __future__ import annotations

from typing import Optional

# Ordered worst to best. Position in this list is the scale — the gap between
# adjacent entries is one "band", which is the unit the alerting threshold uses.
BAND_ORDER = ["STRONG_SELL", "SELL", "HOLD", "BUY", "STRONG_BUY"]

_ALIASES = {
    "STRONGBUY": "STRONG_BUY", "STRONG BUY": "STRONG_BUY",
    "STRONGSELL": "STRONG_SELL", "STRONG SELL": "STRONG_SELL",
    "NEUTRAL": "HOLD", "HOLD/NEUTRAL": "HOLD",
}


def normalize_band(value: Optional[str]) -> Optional[str]:
    """Fold casing and spacing variants onto the canonical band name."""
    if not value:
        return None
    text = str(value).strip().upper().replace("-", "_")
    text = _ALIASES.get(text, text)
    text = _ALIASES.get(text.replace("_", " "), text)
    return text if text in BAND_ORDER else None


def band_distance(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Signed distance b - a in bands. None if either is unrecognised.

    Positive means `b` is more bullish than `a`.
    """
    na, nb = normalize_band(a), normalize_band(b)
    if na is None or nb is None:
        return None
    return BAND_ORDER.index(nb) - BAND_ORDER.index(na)


def is_regression(expected: Optional[str], actual: Optional[str], *, tolerance: int = 1) -> bool:
    """True when `actual` has drifted further than `tolerance` bands.

    Tolerance defaults to 1 because a BUY/STRONG_BUY flip on a genuinely
    borderline score is noise, not a regression — alerting on it trains you to
    ignore the alert. A two-band move (BUY -> SELL) is a real change of mind.
    """
    distance = band_distance(expected, actual)
    if distance is None:
        return True          # unparseable verdict is itself a failure
    return abs(distance) > tolerance


def is_directionally_opposed(a: Optional[str], b: Optional[str]) -> bool:
    """True when one says buy and the other says sell. HOLD opposes nothing."""
    na, nb = normalize_band(a), normalize_band(b)
    if na is None or nb is None:
        return False
    mid = BAND_ORDER.index("HOLD")
    ia, ib = BAND_ORDER.index(na), BAND_ORDER.index(nb)
    return (ia - mid) * (ib - mid) < 0
