import os
import redis
import json
from typing import Optional, Dict, Any

REDIS_URL = os.getenv("UPSTASH_REDIS_URL")
REDIS_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN")

# Initialize Redis client if vars exist
if REDIS_URL and REDIS_TOKEN:
    try:
        # Upstash REST URL might need tweaking depending on client, assuming standard redis here
        # For true Upstash REST, consider upstash-redis Python SDK.
        # This is a generic standard redis fallback
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        print(f"Warning: Failed to connect to Redis: {e}")
        redis_client = None
else:
    redis_client = None

def get_cached_analysis(ticker: str) -> Optional[Dict[str, Any]]:
    """Get fully cached analysis for a ticker (valid for 30 min)"""
    if not redis_client: return None
    try:
        data = redis_client.get(f"analyzer:cache:{ticker}")
        if data:
            return json.loads(data)
    except Exception:
        pass
    return None

def set_cached_analysis(ticker: str, data: Dict[str, Any], expiry: int = 1800):
    """Store analysis in cache for 30 minutes (1800 seconds)"""
    if not redis_client: return
    try:
        redis_client.setex(f"analyzer:cache:{ticker}", expiry, json.dumps(data))
    except Exception as e:
        print(f"Cache set failed: {e}")
