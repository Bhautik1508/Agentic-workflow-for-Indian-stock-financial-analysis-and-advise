"""Stamp data sources with `as_of` so the UI can warn the user when a verdict
rests on stale inputs (e.g. weekend cache, FII/DII data only refreshed after
4:30pm IST, screener.in scrape from yesterday).

Every fetch_* call should pass its result through `stamp()` to attach freshness
metadata. Agents can then surface the staleness as a warning on their card."""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

IST = timezone(timedelta(hours=5, minutes=30))

# Default thresholds. Sources can override via the `stale_after_hours` parameter.
DEFAULT_STALE_AFTER_HOURS = 24
INTRADAY_STALE_AFTER_HOURS = 4   # for live price / market breadth data


@dataclass
class Freshness:
    as_of: str               # ISO8601 string in IST
    source: str
    age_hours: float
    is_stale: bool
    stale_after_hours: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def now_ist() -> datetime:
    return datetime.now(IST)


def _coerce_to_aware(dt: datetime) -> datetime:
    """Treat naive datetimes as IST. We never get UTC from yfinance's calendar
    API on a fresh install; treating it as IST is closer to reality than UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt


def compute_freshness(
    as_of: datetime,
    source: str,
    *,
    now: Optional[datetime] = None,
    stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
) -> Freshness:
    """Return a Freshness record. `now` is injectable for deterministic tests."""
    now = now or now_ist()
    as_of = _coerce_to_aware(as_of)
    now = _coerce_to_aware(now)
    delta = now - as_of
    age_hours = round(delta.total_seconds() / 3600.0, 2)
    return Freshness(
        as_of=as_of.isoformat(),
        source=source,
        age_hours=age_hours,
        is_stale=age_hours > stale_after_hours,
        stale_after_hours=stale_after_hours,
    )


def stamp(
    payload: Any,
    source: str,
    *,
    as_of: Optional[datetime] = None,
    stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
) -> Any:
    """Attach a `_freshness` field to a dict payload.

    Mutates and returns the dict for ergonomic chaining. For non-dict payloads
    (lists, primitives) we return the payload unchanged — callers should use
    `freshness_for(source, ...)` and store the metadata side-channel so the
    type contract of the original payload (e.g. list-of-news-items) is preserved.
    """
    fresh = compute_freshness(as_of or now_ist(), source, stale_after_hours=stale_after_hours)
    if isinstance(payload, dict):
        payload["_freshness"] = fresh.to_dict()
        return payload
    return payload  # caller should pair with freshness_for(...) on the side


def freshness_for(
    source: str,
    *,
    as_of: Optional[datetime] = None,
    stale_after_hours: int = DEFAULT_STALE_AFTER_HOURS,
) -> Dict[str, Any]:
    """Return a freshness record dict ready to drop into state alongside a
    list-typed source (e.g. `state['news_freshness'] = freshness_for(...)`)."""
    return compute_freshness(
        as_of or now_ist(),
        source,
        stale_after_hours=stale_after_hours,
    ).to_dict()


def get_freshness(payload: Any) -> Optional[Dict[str, Any]]:
    """Read back the freshness record stamped onto a payload, if any."""
    if isinstance(payload, dict):
        return payload.get("_freshness")
    return None


def collect_stale_sources(state: Dict) -> List[str]:
    """Walk the state and return human-readable labels for any stale sources.

    Looks at both:
      • dict-attached `_freshness` (from `stamp()`), and
      • side-channel keys ending in `_freshness` whose value is a freshness dict.
    """
    stale: List[str] = []
    if not isinstance(state, dict):
        return stale
    for key, value in state.items():
        f = get_freshness(value)
        if f is None and key.endswith("_freshness") and isinstance(value, dict):
            f = value
        if f and f.get("is_stale"):
            label = f.get("source") or key
            stale.append(f"{label} ({f.get('age_hours', 0):.1f}h)")
    return stale
