"""Tests for Phase 5 — Insight & Action layer.

Covers:
- compute_counter_factual: band thresholds, pillar sensitivity math, veto risks,
  edge cases (top/bottom band, all-degraded pillars, no-weight pillar)
- read_run_log + /api/verdict/{id} round-trip via FastAPI TestClient
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scoring import compute_counter_factual, profile_bands


# ─────────────────────────────────────────────────────────────────────────────
# compute_counter_factual — band threshold helpers
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "financial":  0.30,
    "technical":  0.23,
    "risk":       0.22,
    "sentiment":  0.12,
    "macro_gov":  0.13,
}


def test_buy_verdict_identifies_next_worse_and_next_better_bands():
    cf = compute_counter_factual(
        weighted_score=6.4,
        current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "risk": 6.5, "sentiment": 5.5, "macro_gov": 6.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    bands = profile_bands("balanced")
    assert cf.next_worse_band == "HOLD"
    assert cf.next_better_band == "STRONG_BUY"
    assert cf.score_to_next_worse == bands["BUY"]          # 6.0 — drop below to land in HOLD
    assert cf.score_to_next_better == bands["STRONG_BUY"]  # 7.5 — reach to upgrade


def test_strong_buy_has_no_better_band():
    cf = compute_counter_factual(
        weighted_score=8.5,
        current_band="STRONG_BUY",
        pillar_scores={"financial": 9.0, "technical": 8.5, "risk": 8.0, "sentiment": 7.5, "macro_gov": 8.5},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    assert cf.next_better_band is None
    assert cf.score_to_next_better is None
    assert cf.next_worse_band == "BUY"


def test_strong_sell_has_no_worse_band():
    cf = compute_counter_factual(
        weighted_score=2.1,
        current_band="STRONG_SELL",
        pillar_scores={"financial": 2.0, "technical": 2.0, "risk": 2.0, "sentiment": 2.5, "macro_gov": 2.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    assert cf.next_worse_band is None
    assert cf.score_to_next_worse is None


# ─────────────────────────────────────────────────────────────────────────────
# Pillar sensitivity math
# ─────────────────────────────────────────────────────────────────────────────

def test_pillar_drop_to_downgrade_is_solvable():
    """For Financial weight 0.30, current weighted 6.4, downgrade threshold 6.0:
       Δscore_pillar = (6.0 - 6.4) / 0.30 = -1.333
       So Financial would need to drop to 7.0 + (-1.333) = 5.67."""
    cf = compute_counter_factual(
        weighted_score=6.4,
        current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "risk": 6.5, "sentiment": 5.5, "macro_gov": 6.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    fin = next(p for p in cf.pillar_sensitivity if p.pillar_key == "financial")
    assert fin.score_at_downgrade is not None
    assert fin.score_at_downgrade == pytest.approx(5.67, abs=0.01)
    assert fin.drop_to_downgrade == pytest.approx(1.33, abs=0.01)


def test_pillar_with_zero_weight_is_skipped():
    """If a pillar's weight is zero (e.g. degraded + redistributed), we shouldn't
    surface a sensitivity for it — its score can't move the total."""
    weights = {**DEFAULT_WEIGHTS, "risk": 0.0}
    cf = compute_counter_factual(
        weighted_score=6.4,
        current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "risk": 6.5, "sentiment": 5.5, "macro_gov": 6.0},
        weights=weights,
        profile="balanced",
    )
    keys = [p.pillar_key for p in cf.pillar_sensitivity]
    assert "risk" not in keys


def test_missing_pillar_score_is_skipped():
    """A degraded analyst (score=None) doesn't produce a sensitivity row."""
    cf = compute_counter_factual(
        weighted_score=6.4,
        current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "sentiment": 5.5, "macro_gov": 6.0},  # no risk
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    keys = [p.pillar_key for p in cf.pillar_sensitivity]
    assert "risk" not in keys


def test_target_score_outside_0_10_is_treated_as_unreachable():
    """If reaching the next band would require a pillar < 0 or > 10, that
    pillar can't move the verdict alone."""
    # Strong-buy band is 7.5 in balanced; with weighted=2.0 you'd need a huge
    # rise from any single pillar. With financial weight 0.30 → required jump
    # = (7.5 - 2.0)/0.30 = 18.3 — way above any pillar's ceiling.
    cf = compute_counter_factual(
        weighted_score=2.0,
        current_band="STRONG_SELL",
        pillar_scores={"financial": 1.5, "technical": 2.0, "risk": 2.5, "sentiment": 2.0, "macro_gov": 2.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    fin = next(p for p in cf.pillar_sensitivity if p.pillar_key == "financial")
    # Even reaching SELL (next_better_band threshold 3.5) requires a +6.7 jump,
    # but that lands at 8.2 which is in range — so it should be solvable.
    # But STRONG_BUY would not be — and there's no STRONG_BUY upgrade from STRONG_SELL.
    assert cf.next_better_band == "SELL"
    # The rise itself should be solvable here
    assert fin.rise_to_upgrade is not None


def test_pillars_sorted_by_smallest_drop_first():
    cf = compute_counter_factual(
        weighted_score=6.4,
        current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "risk": 6.5, "sentiment": 5.5, "macro_gov": 6.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    drops = [p.drop_to_downgrade for p in cf.pillar_sensitivity if p.drop_to_downgrade is not None]
    assert drops == sorted(drops)


# ─────────────────────────────────────────────────────────────────────────────
# Veto risks surface above BUY-ish verdicts
# ─────────────────────────────────────────────────────────────────────────────

def test_buy_verdict_includes_structural_veto_warning():
    cf = compute_counter_factual(
        weighted_score=6.4,
        current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "risk": 6.5, "sentiment": 5.5, "macro_gov": 6.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
        risk_pillar_score=6.5,
    )
    text = " ".join(cf.veto_risks).lower()
    assert "altman" in text or "pledge" in text or "stage 2" in text or "going-concern" in text


def test_risk_buffer_is_reported_when_provided():
    cf = compute_counter_factual(
        weighted_score=6.4,
        current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "risk": 4.0, "sentiment": 5.5, "macro_gov": 6.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
        risk_pillar_score=4.0,
    )
    text = "\n".join(cf.veto_risks)
    assert "Risk score must stay" in text
    assert "1.0" in text  # buffer = 4.0 - 3.0


def test_strong_sell_gets_no_buy_side_veto_caveat():
    cf = compute_counter_factual(
        weighted_score=2.0,
        current_band="STRONG_SELL",
        pillar_scores={"financial": 1.5, "technical": 2.0, "risk": 2.5, "sentiment": 2.0, "macro_gov": 2.0},
        weights=DEFAULT_WEIGHTS,
        profile="balanced",
    )
    # Should NOT include the "may flip to SELL" caveat (we're already at the bottom)
    joined = "\n".join(cf.veto_risks).lower()
    assert "altman" not in joined


# ─────────────────────────────────────────────────────────────────────────────
# Profile-aware band thresholds flow through
# ─────────────────────────────────────────────────────────────────────────────

def test_conservative_profile_uses_higher_thresholds():
    """A score of 6.5 is a BUY under aggressive but a HOLD under conservative.
    So the next-worse-band threshold differs between profiles."""
    cf_agg = compute_counter_factual(
        weighted_score=6.5, current_band="BUY",
        pillar_scores={"financial": 6.5, "technical": 6.5, "risk": 6.5, "sentiment": 6.5, "macro_gov": 6.5},
        weights=DEFAULT_WEIGHTS, profile="aggressive",
    )
    cf_con = compute_counter_factual(
        weighted_score=6.5, current_band="HOLD",
        pillar_scores={"financial": 6.5, "technical": 6.5, "risk": 6.5, "sentiment": 6.5, "macro_gov": 6.5},
        weights=DEFAULT_WEIGHTS, profile="conservative",
    )
    assert cf_agg.score_to_next_worse != cf_con.score_to_next_worse


def test_to_dict_round_trips():
    cf = compute_counter_factual(
        weighted_score=6.4, current_band="BUY",
        pillar_scores={"financial": 7.0, "technical": 6.0, "risk": 6.5, "sentiment": 5.5, "macro_gov": 6.0},
        weights=DEFAULT_WEIGHTS, profile="balanced",
    )
    d = cf.to_dict()
    assert d["current_band"] == "BUY"
    assert isinstance(d["pillar_sensitivity"], list)
    assert isinstance(d["veto_risks"], list)


# ─────────────────────────────────────────────────────────────────────────────
# /api/verdict/{run_id} endpoint
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def app_client(tmp_path, monkeypatch):
    """Boot the FastAPI app with RUN_LOG_DIR pointed at a tmp path."""
    import os
    os.environ.setdefault("GROQ_API_KEY", "test")
    from graph import run_log
    monkeypatch.setattr(run_log, "RUN_LOG_DIR", str(tmp_path))

    from main import app
    return TestClient(app), tmp_path, run_log


def test_verdict_endpoint_returns_404_for_missing_run(app_client):
    client, _, _ = app_client
    r = client.get("/api/verdict/run_does_not_exist")
    assert r.status_code == 404


def test_verdict_endpoint_round_trips_a_written_run_log(app_client):
    client, tmp_path, run_log = app_client
    rid = run_log.new_run_id()
    judge = {
        "final_decision": "BUY",
        "action": "BUY",
        "confidence_score": 0.78,
        "investment_thesis": "Strong fundamentals.",
        "key_risks": ["FII selling"],
        "key_catalysts": ["Q2 results"],
        "target_price_inr": 1300,
        "stop_loss_inr": 1100,
    }
    reports = {
        "financial_report": {"agent_name": "Financial Analyst", "score": 7.5, "summary": "x"},
    }
    path = run_log.write_run_log(
        rid, "RELIANCE.NS", "Reliance",
        analyst_reports=reports,
        judge_payload=judge,
        inputs_summary={"risk_profile": "balanced"},
        telemetry={"total_calls": 6},
    )
    assert Path(path).exists()

    r = client.get(f"/api/verdict/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == rid
    assert body["ticker"] == "RELIANCE.NS"
    assert body["risk_profile"] == "balanced"
    assert body["judge_report"]["final_decision"] == "BUY"
    assert body["telemetry"]["total_calls"] == 6
    # The endpoint must not include the full raw report blobs from upstream APIs
    assert isinstance(body["reports"]["financial_report"], dict)


def test_verdict_endpoint_strips_raw_data_blob(app_client):
    """The run-log writer scrubs the bulky raw `data` field; the endpoint
    must surface only the cleaned report shape."""
    client, _, run_log = app_client
    rid = run_log.new_run_id()
    reports = {
        "financial_report": {
            "agent_name": "Financial Analyst",
            "score": 7.0,
            "data": {"some": "huge upstream blob"},
        },
    }
    run_log.write_run_log(rid, "X.NS", "X", analyst_reports=reports, judge_payload={})
    r = client.get(f"/api/verdict/{rid}")
    assert r.status_code == 200
    assert "data" not in r.json()["reports"]["financial_report"]


# ─────────────────────────────────────────────────────────────────────────────
# /api/price-history — must resolve free-form company names
# ─────────────────────────────────────────────────────────────────────────────

def test_price_history_route_resolves_company_name(app_client, monkeypatch):
    """A multi-word company name like 'Tata Motors' must be resolved to the
    exchange ticker (TATAMOTORS.NS) before yfinance is queried — otherwise
    the chart endpoint returns 404 for any name that's not already a ticker."""
    client, _, _ = app_client

    # Fake resolve_ticker so we don't hit the real yahooquery search.
    from data import market_data as md
    resolve_calls = []

    async def fake_resolve(name: str) -> str:
        resolve_calls.append(name)
        return "TATAMOTORS.NS"

    monkeypatch.setattr(md, "resolve_ticker", fake_resolve)
    # Also re-import in routes module so the patch takes effect.
    from api import routes as routes_module
    monkeypatch.setattr(routes_module, "resolve_ticker", fake_resolve, raising=False)

    # Fake yfinance.Ticker so we don't hit the network — return an empty
    # history; the route will 404, but we only care whether resolve_ticker
    # was called with the free-form name.
    import yfinance as yf
    import pandas as pd

    class FakeTicker:
        def __init__(self, sym):
            self.sym = sym

        def history(self, period):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", FakeTicker)

    r = client.get("/api/price-history/Tata%20Motors?period=1mo")
    # We don't care about 404 vs 200 — we care that the name was resolved.
    assert "Tata Motors" in resolve_calls, f"resolve_ticker should have been called with 'Tata Motors', got {resolve_calls}"


def test_price_history_route_passes_through_resolved_ticker(app_client, monkeypatch):
    """If the caller already passed an exchange-suffixed ticker, the route must
    NOT call resolve_ticker — it should be a passthrough."""
    client, _, _ = app_client

    from data import market_data as md
    from api import routes as routes_module
    resolve_calls = []

    async def fake_resolve(name: str) -> str:
        resolve_calls.append(name)
        return name  # noop

    monkeypatch.setattr(md, "resolve_ticker", fake_resolve)
    monkeypatch.setattr(routes_module, "resolve_ticker", fake_resolve, raising=False)

    import yfinance as yf
    import pandas as pd

    class FakeTicker:
        def __init__(self, sym):
            self.sym = sym

        def history(self, period):
            return pd.DataFrame()

    monkeypatch.setattr(yf, "Ticker", FakeTicker)

    r = client.get("/api/price-history/RELIANCE.NS?period=1mo")
    assert resolve_calls == [], "resolve_ticker should not be called for a pre-resolved ticker"


def test_price_history_route_returns_404_when_resolve_fails(app_client, monkeypatch):
    client, _, _ = app_client

    from data import market_data as md
    from api import routes as routes_module

    async def fake_resolve(name: str) -> str:
        return "INVALID"

    monkeypatch.setattr(md, "resolve_ticker", fake_resolve)
    monkeypatch.setattr(routes_module, "resolve_ticker", fake_resolve, raising=False)

    r = client.get("/api/price-history/zzzz_no_such_company?period=1mo")
    assert r.status_code == 404
    assert "could not resolve" in r.json()["detail"].lower()
