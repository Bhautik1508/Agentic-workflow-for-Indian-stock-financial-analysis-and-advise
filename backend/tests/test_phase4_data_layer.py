"""Phase 4 — fetch-layer caching, negative caching, stale-while-revalidate,
bounded directories, and the pluggable provider seam."""

import asyncio
import os
import time

import pytest

from data import fetch_cache as fc
from data.providers import (
    FallbackChain,
    IFundamentalsProvider,
    YFinanceFundamentals,
    default_fundamentals_provider,
)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(fc, "CACHE_DIR", str(tmp_path / "fetch"))
    monkeypatch.setattr(fc, "ENABLED", True)
    yield


# ─────────────────────────────────────────────────────────────────────────────
# Positive caching
# ─────────────────────────────────────────────────────────────────────────────

def test_async_fetch_is_cached():
    calls = {"n": 0}

    @fc.cached_fetch("t.async", ttl_seconds=60)
    async def fetch(ticker):
        calls["n"] += 1
        return {"ticker": ticker}

    async def main():
        return await fetch("TCS"), await fetch("TCS")

    a, b = asyncio.run(main())
    assert a == b
    assert calls["n"] == 1, "second call must not hit the network"


def test_sync_fetch_is_cached():
    calls = {"n": 0}

    @fc.cached_fetch("t.sync", ttl_seconds=60)
    def fetch(ticker):
        calls["n"] += 1
        return {"ticker": ticker}

    assert fetch("TCS") == fetch("TCS")
    assert calls["n"] == 1


def test_different_arguments_are_different_entries():
    calls = {"n": 0}

    @fc.cached_fetch("t.args", ttl_seconds=60)
    def fetch(ticker):
        calls["n"] += 1
        return {"ticker": ticker}

    fetch("TCS"); fetch("INFY"); fetch("TCS")
    assert calls["n"] == 2


def test_key_includes_the_trading_day():
    """An end-of-day payload must not be served the next morning merely because
    its TTL has not elapsed."""
    key = fc.make_key("src", ("TCS",), {})
    assert fc.trading_day() in key


def test_expired_entry_is_refetched():
    calls = {"n": 0}

    @fc.cached_fetch("t.ttl", ttl_seconds=0.05)
    def fetch():
        calls["n"] += 1
        return {"v": calls["n"]}

    fetch()
    time.sleep(0.08)
    fetch()
    assert calls["n"] == 2


def test_cache_can_be_disabled(monkeypatch):
    monkeypatch.setattr(fc, "ENABLED", False)
    calls = {"n": 0}

    @fc.cached_fetch("t.off", ttl_seconds=60)
    def fetch():
        calls["n"] += 1
        return {"v": 1}

    fetch(); fetch()
    assert calls["n"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Negative caching
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_result_is_negatively_cached():
    """LTIM.NS 404s from yfinance on every run and was re-fetched each time,
    paying full latency for a guaranteed failure."""
    calls = {"n": 0}

    @fc.cached_fetch("t.empty", ttl_seconds=600, negative_ttl_seconds=60)
    def fetch(ticker):
        calls["n"] += 1
        return {}

    fetch("LTIM.NS"); fetch("LTIM.NS")
    assert calls["n"] == 1
    assert fc.stats()["negative"] == 1


def test_negative_entries_expire_sooner_than_positive_ones():
    """A transient outage must not be pinned for the whole day."""
    calls = {"n": 0}

    @fc.cached_fetch("t.negttl", ttl_seconds=600, negative_ttl_seconds=0.05)
    def fetch():
        calls["n"] += 1
        return {}

    fetch()
    time.sleep(0.08)
    fetch()
    assert calls["n"] == 2


def test_empty_caching_can_be_turned_off():
    calls = {"n": 0}

    @fc.cached_fetch("t.noneg", ttl_seconds=600, cache_empty=False)
    def fetch():
        calls["n"] += 1
        return {}

    fetch(); fetch()
    assert calls["n"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Stale-while-revalidate
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_payload_is_served_when_the_refetch_fails():
    """Old-but-labelled beats absent: freshness.py already surfaces staleness,
    whereas an empty payload silently degrades an analyst."""
    state = {"fail": False, "n": 0}

    @fc.cached_fetch("t.swr", ttl_seconds=0.05)
    def fetch():
        state["n"] += 1
        if state["fail"]:
            raise RuntimeError("upstream 503")
        return {"v": "good"}

    assert fetch() == {"v": "good"}
    time.sleep(0.08)
    state["fail"] = True
    assert fetch() == {"v": "good"}, "should serve the last good payload"
    assert state["n"] == 2


def test_failure_with_no_prior_value_propagates():
    @fc.cached_fetch("t.nofallback", ttl_seconds=60)
    def fetch():
        raise RuntimeError("upstream 503")

    with pytest.raises(RuntimeError):
        fetch()


# ─────────────────────────────────────────────────────────────────────────────
# Bounded directories
# ─────────────────────────────────────────────────────────────────────────────

def test_eviction_caps_entry_count():
    @fc.cached_fetch("t.evict", ttl_seconds=600)
    def fetch(i):
        return {"i": i}

    for i in range(30):
        fetch(i)
    assert fc.stats()["entries"] == 30
    fc.evict(max_entries=10, max_bytes=fc.MAX_BYTES)
    assert fc.stats()["entries"] <= 10


def test_eviction_caps_total_bytes():
    @fc.cached_fetch("t.bytes", ttl_seconds=600)
    def fetch(i):
        return {"blob": "x" * 500, "i": i}

    for i in range(20):
        fetch(i)
    fc.evict(max_entries=fc.MAX_ENTRIES, max_bytes=2000)
    assert fc.stats()["bytes"] <= 2000 + 600


def test_clear_empties_the_cache():
    @fc.cached_fetch("t.clear", ttl_seconds=600)
    def fetch(i):
        return {"i": i}

    fetch(1); fetch(2)
    assert fc.clear() == 2
    assert fc.stats()["entries"] == 0


def test_corrupt_cache_file_is_treated_as_a_miss():
    """A torn file must not poison every later read."""
    @fc.cached_fetch("t.corrupt", ttl_seconds=600)
    def fetch():
        return {"v": 1}

    fetch()
    key = fc.make_key("t.corrupt", (), {})
    with open(fc._path(key), "w") as fh:
        fh.write("{ not json")
    assert fc.read(key) is None
    assert fetch() == {"v": 1}


def test_run_logs_are_pruned(tmp_path, monkeypatch):
    from graph import run_log

    monkeypatch.setattr(run_log, "RUN_LOG_DIR", str(tmp_path))
    for i in range(20):
        path = tmp_path / f"run_{i:03d}__X.json"
        path.write_text("{}")
        os.utime(path, (i, i))          # oldest first
    removed = run_log.prune_run_logs(max_files=5)
    assert removed == 15
    remaining = sorted(p.name for p in tmp_path.glob("*.json"))
    assert len(remaining) == 5
    assert "run_019__X.json" in remaining, "newest must survive"
    assert "run_000__X.json" not in remaining


def test_pruning_is_a_noop_below_the_cap(tmp_path, monkeypatch):
    from graph import run_log

    monkeypatch.setattr(run_log, "RUN_LOG_DIR", str(tmp_path))
    (tmp_path / "a__X.json").write_text("{}")
    assert run_log.prune_run_logs(max_files=10) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Provider seam
# ─────────────────────────────────────────────────────────────────────────────

def test_yfinance_provider_satisfies_the_protocol():
    assert isinstance(YFinanceFundamentals(), IFundamentalsProvider)


def test_chain_falls_through_to_the_next_provider():
    class Empty:
        name = "empty"
        async def fetch(self, ticker):
            return {}

    class Good:
        name = "good"
        async def fetch(self, ticker):
            return {"pe_ratio": 20}

    chain = FallbackChain(Empty(), Good())
    assert asyncio.run(chain.fetch("TCS")) == {"pe_ratio": 20}


def test_chain_survives_a_raising_provider():
    class Boom:
        name = "boom"
        async def fetch(self, ticker):
            raise RuntimeError("down")

    class Good:
        name = "good"
        async def fetch(self, ticker):
            return {"pe_ratio": 20}

    assert asyncio.run(FallbackChain(Boom(), Good()).fetch("TCS")) == {"pe_ratio": 20}


def test_chain_returns_empty_when_everything_fails():
    class Boom:
        name = "boom"
        async def fetch(self, ticker):
            raise RuntimeError("down")

    assert asyncio.run(FallbackChain(Boom()).fetch("TCS")) == {}


def test_default_provider_is_a_chain_starting_with_yfinance():
    provider = default_fundamentals_provider()
    assert provider.providers[0].name == "yfinance"


def test_network_fetchers_are_cached():
    """Guards the wiring: a new fetcher added without the decorator silently
    reintroduces per-run network I/O."""
    import data.market_data as md

    for name in ("fetch_all_market_data", "fetch_earnings_data", "fetch_news",
                 "fetch_sector_peers", "resolve_ticker", "fetch_market_breadth"):
        fn = getattr(md, name)
        assert hasattr(fn, "cache_source"), f"{name} is not cached"
