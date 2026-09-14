"""Phase 1 — reliability: lazy semaphore, health probe, single /health route."""

import asyncio

import pytest

import graph.workflow as wf
from llm import health as llm_health


# ─────────────────────────────────────────────────────────────────────────────
# Lazy analyst semaphore
# ─────────────────────────────────────────────────────────────────────────────

def test_semaphore_is_not_created_at_import_time():
    """A module-level asyncio.Semaphore() binds whichever loop exists at import
    on Python 3.9, then raises 'got Future attached to a different loop' the
    moment more analysts contend than ANALYST_CONCURRENCY allows."""
    wf._analyst_semaphore = None
    assert wf._analyst_semaphore is None


def test_semaphore_survives_contention_in_a_fresh_loop():
    """The real regression: 5 analysts against 3 slots, in a loop created after
    import. This is what crashed a full local run."""
    wf._analyst_semaphore = None

    async def worker(i):
        async with wf._get_semaphore():
            await asyncio.sleep(0.01)
            return i

    async def main():
        # More workers than slots, so the semaphore must actually block and
        # create futures — the step that used to blow up.
        return await asyncio.gather(*(worker(i) for i in range(5)))

    loop = asyncio.new_event_loop()
    try:
        assert sorted(loop.run_until_complete(main())) == [0, 1, 2, 3, 4]
    finally:
        loop.close()
    wf._analyst_semaphore = None


def test_semaphore_is_reused_within_a_loop():
    wf._analyst_semaphore = None

    async def main():
        return wf._get_semaphore() is wf._get_semaphore()

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(main()) is True
    finally:
        loop.close()
    wf._analyst_semaphore = None


def test_semaphore_bounds_concurrency_to_the_configured_limit():
    wf._analyst_semaphore = None
    peak = 0
    active = 0

    async def worker():
        nonlocal peak, active
        async with wf._get_semaphore():
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    async def main():
        await asyncio.gather(*(worker() for _ in range(10)))

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
    assert peak <= wf.ANALYST_CONCURRENCY
    wf._analyst_semaphore = None


# ─────────────────────────────────────────────────────────────────────────────
# Health probe
# ─────────────────────────────────────────────────────────────────────────────

def test_configured_models_follow_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-x")
    monkeypatch.setenv("GROQ_MODEL", "groq-x")
    models = llm_health.configured_models()
    assert models["gemini"][0] == "gemini-x"
    assert models["groq"][0] == "groq-x"


def test_health_reports_defaults_matching_the_router(monkeypatch):
    """The CLI used to keep its own copy of these and drifted, reporting on a
    model the app no longer used."""
    for var in ("GEMINI_MODEL", "GEMINI_FALLBACK_MODEL", "GROQ_MODEL", "GROQ_FALLBACK_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")

    from llm.providers import build_default_chain

    health_models = llm_health.configured_models()
    chain_models = {a.model for a in build_default_chain()}
    for name in ("gemini", "groq"):
        assert set(health_models[name]) <= chain_models, (
            f"{name} health check reports models the router will not use"
        )


def test_unconfigured_provider_is_not_unhealthy():
    """No key means 'not a tier', not 'broken' — the app runs on one provider."""
    h = llm_health.ProviderHealth(
        provider="gemini", configured_models=["m"], key_present=False
    )
    assert h.healthy is True


def test_reachable_but_missing_model_is_unhealthy():
    """The Groq outage: provider up, configured model retired."""
    h = llm_health.ProviderHealth(
        provider="groq", configured_models=["llama-3.3-70b-versatile"],
        key_present=True, reachable=True, model_exists=False,
        missing_models=["llama-3.3-70b-versatile"],
    )
    assert h.healthy is False


def test_health_dict_hides_model_list_by_default():
    h = llm_health.ProviderHealth(
        provider="groq", configured_models=["m"], key_present=True,
        available_models=["a", "b"],
    )
    assert "available_models" not in h.to_dict()
    assert h.to_dict(include_model_list=True)["available_models"] == ["a", "b"]


@pytest.mark.asyncio
async def test_full_report_flags_no_provider_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    report = await llm_health.full_report(live=False)
    assert report["healthy"] is False
    assert "No LLM provider configured" in report["error"]


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

def test_only_one_health_route_is_registered():
    """Two @router.get('/health') handlers existed; the second silently
    shadowed the first, so the richer payload was dead code."""
    from api.routes import router

    health_routes = [r for r in router.routes if getattr(r, "path", None) == "/health"]
    assert len(health_routes) == 1


def test_shallow_health_does_no_network_calls(monkeypatch):
    """Render polls this endpoint; it must not call two LLM vendors each time."""
    called = False

    async def _boom(*a, **k):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(llm_health, "full_report", _boom)

    from fastapi.testclient import TestClient
    import main

    monkeypatch.setenv("LLM_STARTUP_CHECK", "0")
    with TestClient(main.app) as client:
        body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert "llm" not in body
    assert called is False
