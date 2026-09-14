"""Phase 5 — API hardening and the evaluation harness."""

import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from evaluation.backtest import VerdictRecord, forward_return, score_verdicts
from evaluation.bands import (
    BAND_ORDER,
    band_distance,
    is_directionally_opposed,
    is_regression,
    normalize_band,
)
from evaluation.golden_set import GOLDEN_SET, compare_to_golden, load_golden_set

IST = timezone(timedelta(hours=5, minutes=30))


# ─────────────────────────────────────────────────────────────────────────────
# Rate limiting
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_STARTUP_CHECK", "0")
    import api.security as security
    security.reset_rate_limits()
    import main
    with TestClient(main.app) as c:
        yield c
    security.reset_rate_limits()


def _rate_limit_event(client, ip: str):
    """Return the parsed SSE error payload if the run was rate limited."""
    import json as _json

    body = client.get("/api/analyze/NOSUCHTICKERXYZ",
                      headers={"x-forwarded-for": ip}).text
    for line in body.splitlines():
        if line.startswith("data: "):
            try:
                payload = _json.loads(line[6:])
            except ValueError:
                continue
            if payload.get("rate_limited"):
                return payload
    return None


def test_rate_limit_is_reported_through_the_stream(monkeypatch, client):
    """EventSource cannot read the body of a 429, so an HTTP-level rejection
    reaches the browser as an opaque error and the user sees "Analysis Failed"
    with no reason. The limit must arrive as an SSE error event instead."""
    import api.security as security

    monkeypatch.setattr(security, "ANALYZE_BURST_LIMIT", 2)
    monkeypatch.setattr(security, "RATE_LIMIT_ENABLED", True)
    security.reset_rate_limits()

    ip = "203.0.113.5"
    assert _rate_limit_event(client, ip) is None
    assert _rate_limit_event(client, ip) is None
    payload = _rate_limit_event(client, ip)

    assert payload is not None, "third call should have been rate limited"
    assert payload["retry_after"] > 0
    assert "try again" in payload["detail"].lower()


def test_rate_limit_is_per_client(monkeypatch, client):
    import api.security as security

    monkeypatch.setattr(security, "ANALYZE_BURST_LIMIT", 1)
    monkeypatch.setattr(security, "RATE_LIMIT_ENABLED", True)
    security.reset_rate_limits()

    _rate_limit_event(client, "198.51.100.1")
    assert _rate_limit_event(client, "198.51.100.1") is not None
    assert _rate_limit_event(client, "198.51.100.2") is None, "other clients unaffected"


def test_default_limits_allow_ordinary_interactive_use():
    """The first values (5 per 5 min) blocked a person analysing two stocks in a
    row, and because the limit is per-IP it looked ticker-specific."""
    import api.security as security

    assert security.ANALYZE_BURST_LIMIT >= 15
    assert security.ANALYZE_DAILY_LIMIT >= 100


def test_rate_limit_can_be_disabled(monkeypatch, client):
    import api.security as security

    monkeypatch.setattr(security, "RATE_LIMIT_ENABLED", False)
    security.reset_rate_limits()
    for _ in range(3):
        assert _rate_limit_event(client, "203.0.113.77") is None


def test_client_key_prefers_the_forwarded_header():
    """Render terminates TLS upstream, so request.client.host is the proxy."""
    import api.security as security

    class _Req:
        headers = {"x-forwarded-for": "1.1.1.1, 2.2.2.2"}
        client = type("c", (), {"host": "10.0.0.1"})()

    assert security.client_key(_Req()) == "1.1.1.1"


# ─────────────────────────────────────────────────────────────────────────────
# Debug endpoint gating
# ─────────────────────────────────────────────────────────────────────────────

def test_debug_endpoint_is_closed_without_a_token(monkeypatch, client):
    monkeypatch.delenv("DEBUG_API_TOKEN", raising=False)
    assert client.get("/api/debug/data").status_code == 404


def test_debug_endpoint_rejects_a_wrong_token(monkeypatch, client):
    monkeypatch.setenv("DEBUG_API_TOKEN", "right")
    assert client.get("/api/debug/data?token=wrong").status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# CORS
# ─────────────────────────────────────────────────────────────────────────────

def test_cors_does_not_allow_arbitrary_vercel_origins(client):
    """The old config paired a `.*\\.vercel\\.app` regex with credentials, so
    anyone's deployment could call this API."""
    r = client.get("/api/health", headers={"Origin": "https://attacker.vercel.app"})
    assert r.headers.get("access-control-allow-origin") != "https://attacker.vercel.app"


def test_cors_credentials_are_off_by_default(client):
    r = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-credentials") != "true"


# ─────────────────────────────────────────────────────────────────────────────
# Bands
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("strong buy", "STRONG_BUY"), ("STRONG-BUY", "STRONG_BUY"),
    ("Neutral", "HOLD"), ("hold", "HOLD"), ("nonsense", None), (None, None),
])
def test_normalize_band(raw, expected):
    assert normalize_band(raw) == expected


def test_band_distance_is_signed():
    assert band_distance("HOLD", "STRONG_BUY") == 2
    assert band_distance("BUY", "SELL") == -2
    assert band_distance("BUY", "BUY") == 0
    assert band_distance("BUY", "garbage") is None


def test_one_band_move_is_not_a_regression():
    """A BUY/STRONG_BUY flip on a borderline score is noise; alerting on it
    trains you to ignore the alert."""
    assert is_regression("BUY", "STRONG_BUY") is False
    assert is_regression("BUY", "HOLD") is False


def test_two_band_move_is_a_regression():
    assert is_regression("BUY", "SELL") is True


def test_unparseable_verdict_counts_as_a_regression():
    assert is_regression("BUY", None) is True
    assert is_regression("BUY", "???") is True


def test_directional_opposition_ignores_hold():
    assert is_directionally_opposed("BUY", "SELL") is True
    assert is_directionally_opposed("BUY", "HOLD") is False
    assert is_directionally_opposed("STRONG_BUY", "STRONG_SELL") is True


# ─────────────────────────────────────────────────────────────────────────────
# Golden set
# ─────────────────────────────────────────────────────────────────────────────

def test_golden_set_covers_multiple_sectors():
    sectors = {c.sector for c in GOLDEN_SET}
    assert len(GOLDEN_SET) >= 15
    assert len(sectors) >= 8, "a regression confined to one sector would be missed"


def test_golden_set_bands_are_valid():
    for case in GOLDEN_SET:
        assert normalize_band(case.expected_band) is not None, case.ticker


def test_golden_set_tickers_are_unique():
    tickers = [c.ticker for c in GOLDEN_SET]
    assert len(tickers) == len(set(tickers))


def test_compare_flags_only_real_drift():
    cases = load_golden_set()[:3]
    results = {c.ticker: c.expected_band for c in cases}
    report = compare_to_golden(results, cases)
    assert report["regressions"] == 0
    assert report["pass_rate"] == 1.0


def test_compare_counts_a_missing_verdict_as_a_regression():
    cases = load_golden_set()[:2]
    report = compare_to_golden({cases[0].ticker: cases[0].expected_band}, cases)
    assert report["missing"] == 1
    assert report["regressions"] == 1


def test_per_case_tolerance_is_respected():
    from evaluation.golden_set import GoldenCase

    wide = [GoldenCase("X.NS", "Test", "HOLD", tolerance=2)]
    assert compare_to_golden({"X.NS": "STRONG_BUY"}, wide)["regressions"] == 0
    narrow = [GoldenCase("X.NS", "Test", "HOLD", tolerance=1)]
    assert compare_to_golden({"X.NS": "STRONG_BUY"}, narrow)["regressions"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Backtest
# ─────────────────────────────────────────────────────────────────────────────

def _series(start, days=200, step=1.0):
    return {(start + timedelta(days=i)).strftime("%Y-%m-%d"): 100.0 + i * step
            for i in range(days)}


def test_forward_return_computes_percentage():
    start = datetime(2026, 1, 1, tzinfo=IST)
    assert forward_return(_series(start), start, 30) == 30.0


def test_forward_return_is_none_when_the_horizon_has_not_elapsed():
    """Counting an unelapsed horizon as 0% would bias the hit-rate toward
    whatever the recent market did."""
    start = datetime(2026, 1, 1, tzinfo=IST)
    assert forward_return(_series(start, days=5), start, 30) is None


def test_forward_return_is_none_without_prices():
    assert forward_return({}, datetime(2026, 1, 1, tzinfo=IST), 30) is None


def test_hold_verdicts_are_excluded_from_hit_rate():
    """There is no honest definition of a 'correct' HOLD without a benchmark."""
    start = datetime(2026, 1, 1, tzinfo=IST)
    prices = {"X.NS": _series(start)}
    result = score_verdicts(
        [VerdictRecord("r", "X.NS", "HOLD", 0.5, start)], prices, {"1M": 30})
    assert result["by_horizon"]["1M"]["scored"] == 0
    assert result["verdicts_hold"] == 1


def test_buy_on_a_rising_series_is_a_hit_and_sell_is_a_miss():
    start = datetime(2026, 1, 1, tzinfo=IST)
    prices = {"A.NS": _series(start), "B.NS": _series(start)}
    result = score_verdicts([
        VerdictRecord("r1", "A.NS", "BUY", 0.8, start),
        VerdictRecord("r2", "B.NS", "SELL", 0.8, start),
    ], prices, {"1M": 30})
    assert result["by_horizon"]["1M"] == pytest.approx(
        {"scored": 2, "hits": 1, "hit_rate": 0.5,
         "avg_directional_return_pct": 0.0, "note": ""}, rel=1e-3)


def test_unscorable_horizon_reports_none_not_zero():
    start = datetime(2026, 1, 1, tzinfo=IST)
    result = score_verdicts(
        [VerdictRecord("r", "X.NS", "BUY", 0.8, start)],
        {"X.NS": _series(start, days=5)}, {"6M": 180})
    assert result["by_horizon"]["6M"]["hit_rate"] is None
    assert "insufficient" in result["by_horizon"]["6M"]["note"]
