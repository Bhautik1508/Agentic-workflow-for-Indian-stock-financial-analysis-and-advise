"""Caching at the fetch layer, keyed `(source, args, trading_day)`.

The verdict cache in `data/cache.py` only helps when the *same* analysis is
repeated. The expensive, flaky work happens upstream of it: a measured run
spent ~21s of ~31s fetching data and ~8s on every LLM call combined. Caching
the verdict does nothing for that.

Four behaviours, each earning its place:

**Positive caching** keyed by trading day, so a second look at a ticker on the
same day does no network I/O for fundamentals.

**Negative caching.** `LTIM.NS` 404s from yfinance on every single run and was
re-fetched every time, paying full latency for a guaranteed failure. Failures
are cached too, with a shorter TTL so a transient outage does not get pinned
for the day.

**Stale-while-revalidate.** If the entry has expired and the refetch fails, the
last good payload is served with its original `as_of` rather than degrading an
analyst to nothing. `data/freshness.py` already surfaces staleness in the UI, so
old-but-labelled beats absent.

**Bounded size.** `.cache/` and `.runlog/` grew without eviction. Fine at 88K;
not fine after a thousand runs on Render's ephemeral disk.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import inspect
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache", "fetch")

# Defaults, all overridable per call site.
DEFAULT_TTL_SECONDS = 6 * 3600          # fundamentals change slowly
DEFAULT_NEGATIVE_TTL_SECONDS = 900      # 15 min: long enough to stop a hot loop
MAX_ENTRIES = int(os.environ.get("FETCH_CACHE_MAX_ENTRIES", "500") or 500)
MAX_BYTES = int(os.environ.get("FETCH_CACHE_MAX_BYTES", str(32 * 1024 * 1024)) or 32 * 1024 * 1024)
ENABLED = (os.environ.get("FETCH_CACHE_ENABLED", "1") or "1").strip().lower() not in ("0", "false", "no")


def trading_day() -> str:
    """NSE/BSE trading day in IST. Part of every key, so an end-of-day payload
    is never served the next morning just because its TTL has not elapsed."""
    return datetime.now(IST).strftime("%Y-%m-%d")


@dataclass
class CacheEntry:
    value: Any
    stored_at: float
    ttl: float
    negative: bool = False
    error: Optional[str] = None

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.stored_at)

    @property
    def expired(self) -> bool:
        return self.age_seconds > self.ttl

    @property
    def as_of(self) -> str:
        return datetime.fromtimestamp(self.stored_at, IST).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value, "stored_at": self.stored_at, "ttl": self.ttl,
            "negative": self.negative, "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheEntry":
        return cls(
            value=data.get("value"), stored_at=float(data.get("stored_at", 0)),
            ttl=float(data.get("ttl", DEFAULT_TTL_SECONDS)),
            negative=bool(data.get("negative", False)), error=data.get("error"),
        )


def _safe(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(text))[:80]


def make_key(source: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> str:
    """`(source, args, trading_day)` — stable and readable at a glance."""
    payload = json.dumps([[str(a) for a in args], {k: str(v) for k, v in sorted(kwargs.items())}],
                         sort_keys=True)
    digest = hashlib.sha256(payload.encode()).hexdigest()[:10]
    readable = _safe("_".join(str(a) for a in args)) or "noargs"
    return f"{_safe(source)}__{readable}__{trading_day()}__{digest}"


def _path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def read(key: str) -> Optional[CacheEntry]:
    path = _path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as fh:
            return CacheEntry.from_dict(json.load(fh))
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def write(key: str, entry: CacheEntry) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _path(key)
    try:
        # Write-then-rename: a crash mid-write must not leave a torn file that
        # every later read has to fail on.
        tmp = f"{path}.tmp{os.getpid()}"
        with open(tmp, "w") as fh:
            json.dump(entry.to_dict(), fh, default=str)
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        logger.debug(f"[fetch-cache] could not persist {key}: {exc}")


def evict(max_entries: int = MAX_ENTRIES, max_bytes: int = MAX_BYTES) -> int:
    """Drop expired entries, then oldest-first until under both limits."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    removed = 0
    files = []
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        if not name.endswith(".json"):
            continue
        try:
            files.append((path, os.path.getmtime(path), os.path.getsize(path)))
        except OSError:
            continue

    # Expired first — they are dead weight regardless of the limits.
    for path, _, _ in list(files):
        entry = read(os.path.basename(path)[:-5])
        if entry is not None and entry.expired and entry.age_seconds > entry.ttl * 4:
            try:
                os.remove(path)
                files = [f for f in files if f[0] != path]
                removed += 1
            except OSError:
                pass

    files.sort(key=lambda f: f[1])  # oldest first
    total = sum(f[2] for f in files)
    while files and (len(files) > max_entries or total > max_bytes):
        path, _, size = files.pop(0)
        try:
            os.remove(path)
            total -= size
            removed += 1
        except OSError:
            pass
    return removed


def _is_empty(value: Any) -> bool:
    """Treat an empty payload as a miss worth negative-caching, not a success."""
    if value is None:
        return True
    if isinstance(value, (dict, list, str, tuple, set)) and len(value) == 0:
        return True
    return False


def cached_fetch(
    source: str,
    *,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    negative_ttl_seconds: float = DEFAULT_NEGATIVE_TTL_SECONDS,
    cache_empty: bool = True,
):
    """Cache a fetch function on disk by `(source, args, trading_day)`.

    Wraps sync and async callables alike. A cached *failure* re-raises nothing —
    it returns the same empty value the original call produced, because every
    caller here is already written to degrade on empty rather than on an
    exception.
    """
    def decorator(func: Callable):
        is_async = inspect.iscoroutinefunction(func)

        def _lookup(args, kwargs):
            if not ENABLED:
                return None, None
            key = make_key(source, args, kwargs)
            entry = read(key)
            if entry is None:
                return key, None
            if not entry.expired:
                kind = "negative" if entry.negative else "hit"
                logger.debug(f"[fetch-cache] {kind} {source} age={entry.age_seconds:.0f}s")
                return key, entry
            return key, entry  # expired, but retained for stale-while-revalidate

        def _store(key, value, error=None):
            if not ENABLED or key is None:
                return
            if error is None and _is_empty(value) and not cache_empty:
                # Opted out of negative caching: skip entirely rather than
                # storing the empty as a positive entry, which would pin the
                # miss for the full TTL — the opposite of what was asked for.
                return
            negative = error is not None or _is_empty(value)
            write(key, CacheEntry(
                value=value, stored_at=time.time(),
                ttl=negative_ttl_seconds if negative else ttl_seconds,
                negative=negative, error=error,
            ))

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            key, entry = _lookup(args, kwargs)
            if entry is not None and not entry.expired:
                return entry.value
            try:
                value = await func(*args, **kwargs)
            except Exception as exc:
                if entry is not None and not entry.negative:
                    logger.warning(
                        f"[fetch-cache] {source} failed ({str(exc)[:80]}); serving stale "
                        f"payload from {entry.as_of}"
                    )
                    return entry.value
                _store(key, None, error=str(exc)[:200])
                raise
            _store(key, value)
            return value

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            key, entry = _lookup(args, kwargs)
            if entry is not None and not entry.expired:
                return entry.value
            try:
                value = func(*args, **kwargs)
            except Exception as exc:
                if entry is not None and not entry.negative:
                    logger.warning(
                        f"[fetch-cache] {source} failed ({str(exc)[:80]}); serving stale "
                        f"payload from {entry.as_of}"
                    )
                    return entry.value
                _store(key, None, error=str(exc)[:200])
                raise
            _store(key, value)
            return value

        wrapper = async_wrapper if is_async else sync_wrapper
        wrapper.cache_source = source           # type: ignore[attr-defined]
        wrapper.uncached = func                 # type: ignore[attr-defined]
        return wrapper

    return decorator


def stats(*, deep: bool = True) -> Dict[str, Any]:
    """Cache size and composition.

    `deep=False` skips the per-entry read used to count negatives, so the
    health endpoint can report size without O(n) file reads on every poll.
    """
    base = {"enabled": ENABLED, "max_entries": MAX_ENTRIES, "max_bytes": MAX_BYTES}
    if not os.path.isdir(CACHE_DIR):
        return {**base, "entries": 0, "bytes": 0, "negative": None}
    entries = [n for n in os.listdir(CACHE_DIR) if n.endswith(".json")]
    total = 0
    for name in entries:
        try:
            total += os.path.getsize(os.path.join(CACHE_DIR, name))
        except OSError:
            continue
    negative = None
    if deep:
        negative = sum(
            1 for name in entries
            if (entry := read(name[:-5])) is not None and entry.negative
        )
    return {**base, "entries": len(entries), "bytes": total, "negative": negative}


def clear() -> int:
    """Drop every cached entry. Used by tests and the debug endpoint."""
    if not os.path.isdir(CACHE_DIR):
        return 0
    removed = 0
    for name in os.listdir(CACHE_DIR):
        if name.endswith(".json"):
            try:
                os.remove(os.path.join(CACHE_DIR, name))
                removed += 1
            except OSError:
                pass
    return removed
