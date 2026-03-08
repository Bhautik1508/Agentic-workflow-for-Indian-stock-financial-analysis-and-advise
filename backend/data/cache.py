import json
import os
from datetime import datetime, timedelta

# Create cache dir next to this file or at the root of backend
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_EXPIRY_HOURS = 1  # 1 hour cache

from typing import Optional

def get_cached_analysis(ticker: str) -> Optional[dict]:
    cache_file = os.path.join(CACHE_DIR, f"{ticker}.json")
    if not os.path.exists(cache_file): return None
    
    with open(cache_file, "r") as f:
        data = json.load(f)
        
    cached_time = datetime.fromisoformat(data["timestamp"])
    if datetime.now() - cached_time > timedelta(hours=CACHE_EXPIRY_HOURS):
        return None  # Expired
        
    return data["report"]

def save_analysis_to_cache(ticker: str, report: dict):
    cache_file = os.path.join(CACHE_DIR, f"{ticker}.json")
    with open(cache_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "report": report
        }, f)
