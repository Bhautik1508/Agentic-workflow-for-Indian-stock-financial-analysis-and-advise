"""One place that decides how this service turns Python objects into JSON.

`json.dumps` writes `float('nan')` and `float('inf')` as the bare tokens `NaN`
and `Infinity`. Those are valid *Python* and invalid *JSON*: `json.loads`
accepts them on the way back in, so every backend-side check passes, while the
browser's `JSON.parse` throws `Unexpected token 'N'` and takes the page down.

That asymmetry is why a NaN shipped unnoticed. It also makes the blast radius
much larger than the defect: a whole analysis run is delivered over one SSE
stream, so a single non-finite number anywhere does not blank one field — it
kills the entire verdict. The same applies to a cached payload or a run log,
which are read back and re-served later.

Upstream code should not produce non-finite numbers (see the still-forming
session guard in `data/market_data.py`), but the cost of being wrong about that
is high enough that every boundary sanitises.
"""
import json
import math
from typing import Any

__all__ = ["json_safe", "dumps", "dump"]


def json_safe(obj: Any) -> Any:
    """Recursively replace non-finite floats with None."""
    if isinstance(obj, float):          # numpy.float64 subclasses float
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj


def dumps(obj: Any, **kwargs) -> str:
    """json.dumps with non-finite floats nulled out.

    Accepts the same keywords as json.dumps so it is a drop-in at every call
    site; `default=str` is a default rather than an override, because these
    payloads carry datetimes and model objects.
    """
    kwargs.setdefault("default", str)
    return json.dumps(json_safe(obj), **kwargs)


def dump(obj: Any, fh, **kwargs) -> None:
    """json.dump counterpart, for anything written to disk and re-served."""
    kwargs.setdefault("default", str)
    json.dump(json_safe(obj), fh, **kwargs)
