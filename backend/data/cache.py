import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from serialization import dump as json_dump

# Cache lives in backend/.cache (same dir layout as before)
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Intraday cache: results expire after this window OR when the trading day changes,
# whichever comes first. The trading-day bucket means an EOD verdict is never served
# the next morning even if it's <1 hour old in wall-clock terms.
CACHE_EXPIRY_HOURS = 1
IST = timezone(timedelta(hours=5, minutes=30))


def _trading_day_bucket() -> str:
    """Return today's NSE/BSE trading day in IST as YYYY-MM-DD."""
    return datetime.now(IST).strftime("%Y-%m-%d")


def _safe_filename(ticker: str) -> str:
    """RELIANCE.NS -> RELIANCE_NS so periods don't collide with extensions."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", ticker)


def _cache_path(ticker: str, bucket: Optional[str] = None) -> str:
    bucket = bucket or _trading_day_bucket()
    return os.path.join(CACHE_DIR, f"{_safe_filename(ticker)}__{bucket}.json")


def get_cached_analysis(ticker: str) -> Optional[dict]:
    """Return cached analysis only if it's from the current trading day AND within the TTL."""
    cache_file = _cache_path(ticker)
    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    try:
        cached_time = datetime.fromisoformat(data["timestamp"])
    except (KeyError, ValueError):
        return None

    if datetime.now(cached_time.tzinfo or IST) - cached_time > timedelta(hours=CACHE_EXPIRY_HOURS):
        return None

    return data["report"]


def save_analysis_to_cache(ticker: str, report: dict) -> None:
    cache_file = _cache_path(ticker)
    payload = {
        "timestamp": datetime.now(IST).isoformat(),
        "ticker": ticker,
        "trading_day": _trading_day_bucket(),
        "report": report,
    }
    with open(cache_file, "w") as f:
        json_dump(payload, f)
