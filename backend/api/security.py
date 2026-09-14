"""Rate limiting and access gating for the public API.

Every `/analyze` call spends real LLM tokens against your quota, and until now
there was no ceiling at all: one script could drain a day's budget in a minute.

Scope, stated plainly: this limiter is **in-process**. The app runs as a single
Render instance, so a dict is sufficient and honest. It is not a distributed
limiter — if you ever scale to multiple instances, each gets its own allowance
and this needs to move to Redis (the Upstash vars in .env.example are already
there for it).
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default


# Two windows: a short one to stop bursts, a long one to cap daily spend.
#
# The first values here (5 per 5 min) were set to protect the token budget and
# were simply too tight for a person using their own app: analysing two stocks
# in a row hit the cap. Because the limit is per-IP rather than per-ticker, it
# also LOOKED ticker-specific -- "Wipro works, HDFC fails" was really "the
# second request in five minutes fails".
#
# These bounds still stop a script draining the budget while leaving normal
# interactive use alone.
ANALYZE_BURST_LIMIT = _int_env("ANALYZE_BURST_LIMIT", 20)
ANALYZE_BURST_WINDOW = _int_env("ANALYZE_BURST_WINDOW_SECONDS", 300)
ANALYZE_DAILY_LIMIT = _int_env("ANALYZE_DAILY_LIMIT", 200)
ANALYZE_DAILY_WINDOW = _int_env("ANALYZE_DAILY_WINDOW_SECONDS", 86400)

RATE_LIMIT_ENABLED = (os.environ.get("RATE_LIMIT_ENABLED", "1") or "1").strip().lower() \
    not in ("0", "false", "no")

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_MAX_TRACKED_CLIENTS = 10_000


def client_key(request: Request) -> str:
    """Identify the caller.

    Render terminates TLS upstream, so `request.client.host` is the proxy. The
    first hop in X-Forwarded-For is the real client. It is spoofable — this is a
    cost guard, not an authentication boundary, and treating it as the latter
    would be a mistake.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(bucket: Deque[float], window: float, now: float) -> None:
    while bucket and now - bucket[0] > window:
        bucket.popleft()


def _check(key: str, limit: int, window: int, now: float) -> Tuple[bool, int]:
    """Returns (allowed, retry_after_seconds)."""
    bucket = _hits[key]
    _prune(bucket, window, now)
    if len(bucket) >= limit:
        retry_after = int(window - (now - bucket[0])) + 1
        return False, max(1, retry_after)
    return True, 0


def check_analyze_rate_limit(request: Request) -> Optional[Tuple[str, int]]:
    """Non-raising variant for the SSE endpoint. Returns (message, retry_after)
    when the caller is over the limit, else None.

    The streaming endpoint needs this because **EventSource cannot read the body
    of a non-200 response**. An HTTP 429 reaches the browser as an opaque
    `onerror`, so the user sees "Analysis Failed" with no hint that they simply
    need to wait 40 seconds. Reporting it *through* the stream, the way
    data-quality aborts already are, makes the reason visible.
    """
    if not RATE_LIMIT_ENABLED:
        return None
    now = time.time()
    key = client_key(request)
    _evict_stale(now)

    for limit, window, label in (
        (ANALYZE_BURST_LIMIT, ANALYZE_BURST_WINDOW, "burst"),
        (ANALYZE_DAILY_LIMIT, ANALYZE_DAILY_WINDOW, "daily"),
    ):
        allowed, retry_after = _check(f"{key}:{label}", limit, window, now)
        if not allowed:
            logger.warning(f"[rate-limit] {label} limit hit for {key}")
            unit = "minutes" if window < 86400 else "hours"
            amount = window // 60 if window < 86400 else window // 3600
            return (
                f"Rate limit reached: {limit} analyses per {amount} {unit}. "
                f"Please try again in {retry_after} seconds.",
                retry_after,
            )

    for label in ("burst", "daily"):
        _hits[f"{key}:{label}"].append(now)
    return None


def _evict_stale(now: float) -> None:
    if len(_hits) > _MAX_TRACKED_CLIENTS:
        stale = [k for k, v in _hits.items() if not v or now - v[-1] > ANALYZE_DAILY_WINDOW]
        for k in stale[: len(_hits) // 2 or 1]:
            _hits.pop(k, None)


def enforce_analyze_rate_limit(request: Request) -> None:
    """FastAPI dependency. Raises 429 when either window is exhausted."""
    if not RATE_LIMIT_ENABLED:
        return

    now = time.time()
    key = client_key(request)

    # Keep the tracking dict from growing without bound under a spray of IPs.
    if len(_hits) > _MAX_TRACKED_CLIENTS:
        stale = [k for k, v in _hits.items() if not v or now - v[-1] > ANALYZE_DAILY_WINDOW]
        for k in stale[: len(_hits) // 2 or 1]:
            _hits.pop(k, None)

    for limit, window, label in (
        (ANALYZE_BURST_LIMIT, ANALYZE_BURST_WINDOW, "burst"),
        (ANALYZE_DAILY_LIMIT, ANALYZE_DAILY_WINDOW, "daily"),
    ):
        allowed, retry_after = _check(f"{key}:{label}", limit, window, now)
        if not allowed:
            logger.warning(f"[rate-limit] {label} limit hit for {key}")
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit reached ({limit} analyses per "
                    f"{window // 60 if window < 86400 else 24}"
                    f"{'min' if window < 86400 else 'h'}). Try again in {retry_after}s."
                ),
                headers={"Retry-After": str(retry_after)},
            )

    # Only record once both windows pass, so a rejected call is not also charged.
    for label in ("burst", "daily"):
        _hits[f"{key}:{label}"].append(now)


def require_debug_access(request: Request) -> None:
    """Gate diagnostic endpoints.

    Defaults to CLOSED: with no DEBUG_API_TOKEN set the endpoint 404s, so an
    endpoint that returns internal fetch state and tracebacks is not reachable
    just because someone forgot to configure it.
    """
    token = (os.environ.get("DEBUG_API_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="Not found")
    supplied = (
        request.headers.get("x-debug-token")
        or request.query_params.get("token")
        or ""
    ).strip()
    if not supplied or supplied != token:
        raise HTTPException(status_code=404, detail="Not found")


def reset_rate_limits() -> None:
    """Test helper."""
    _hits.clear()
