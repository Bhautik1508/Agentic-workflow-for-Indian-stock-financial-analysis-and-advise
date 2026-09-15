import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from api.security import check_analyze_rate_limit, require_debug_access
from serialization import dumps, json_safe
from graph.runner import run_stock_analysis

logger = logging.getLogger(__name__)
router = APIRouter()

# Shown to the browser in place of a raw exception. The detail goes to the log
# with the run_id, so a user report is still traceable without handing the
# internet our stack traces and upstream URLs.
GENERIC_ERROR = (
    "Analysis could not be completed due to an internal error. "
    "Please try again; if it persists, quote the run id below."
)

@router.get("/verdict/{run_id}")
async def get_frozen_verdict(run_id: str):
    """Phase 5 — return a frozen verdict for sharing.

    Reads the run log written at the end of a successful analysis. The shape
    is intentionally close to the cached payload the SSE stream produces on
    `complete`, so the frontend can hydrate the same components."""
    from graph.run_log import read_run_log

    record = read_run_log(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"No run log found for {run_id}")

    return {
        "run_id":          record.get("run_id"),
        "ticker":          record.get("ticker"),
        "company_name":    record.get("company_name"),
        "timestamp_ist":   record.get("timestamp_ist"),
        "duration_seconds": record.get("duration_seconds"),
        "risk_profile":    (record.get("inputs_summary") or {}).get("risk_profile"),
        "judge_report":    record.get("judge") or {},
        "reports":         record.get("analyst_reports") or {},
        "telemetry":       record.get("telemetry") or {},
        "data_quality":    record.get("data_quality") or {},
    }


@router.get("/health")
async def health_check(deep: bool = False, live: bool = False, models: bool = False):
    """Health check for Render and monitoring tools.

    Shallow by default — Render polls this and must not pay for network calls
    to two LLM vendors on every probe.

      ?deep=true    also probe each provider and verify the configured model IDs
      ?live=true    additionally send a real completion through the router
      ?models=true  include each provider's full model list (verbose)

    `deep` only proves a model is *listed*. Deprecated models stay visible to
    the listing API while 404-ing on use — that gap once reported
    `gemini-2.5-flash` healthy while every real call failed. Use `live` to
    actually exercise the pipeline.
    """
    payload = {
        "status": "ok",
        "version": "1.0.2-yfinance-fix",
        "environment": "production" if os.getenv("RENDER") else "development",
    }

    if not (deep or live):
        return payload

    from data.fetch_cache import stats as cache_stats
    from llm import full_report

    report = await full_report(live=live, include_model_list=models)
    payload["llm"] = report
    # Cheap by default: counting negatives would read every cache file on a
    # poller that runs every 30s.
    payload["cache"] = cache_stats(deep=False)
    payload["status"] = "ok" if report.get("healthy") else "degraded"
    return payload

JUDGE_FIELDS = (
    "final_decision",
    "action",
    "confidence_score",
    "investment_thesis",
    "key_risks",
    "key_catalysts",
    "conviction_level",
    "max_entry_price",
    "target_price_inr",
    "stop_loss_inr",
    "time_horizon",
    "judge_score",
    "score_attribution",
    "strongest_pillar",
    "weakest_pillar",
    # Phase 2
    "risk_profile",
    "grounded_targets",
    "veto",
    "dissent_summary",
    # Phase 3
    "data_quality",
    "stale_sources",
    # Phase 5
    "counter_factual",
)

# Analytics computed before the graph runs. They live on the state rather than
# inside a report, so without this list the SSE filter drops them and the UI
# never learns they exist — which is exactly what happened to Phases C, D and E.
#
# `indices` is deliberately NOT here: it is 139 NSE index records, useful to the
# server and far too large to stream per node update.
# Re-exported so the SSE call sites below read naturally; the contract and the
# reasoning live in serialization.py.
_json_safe = json_safe
_dumps = dumps


ANALYTICS_FIELDS = (
    "relative_context",     # vs Nifty 50 and the sector index, CAPM alpha, India VIX
    "quality_metrics",      # Piotroski, DuPont, cash conversion, accruals
)


@router.get("/analyze/{company_name}")
async def analyze_stock(request: Request, company_name: str, profile: str = "balanced"):
    """Main analysis endpoint — returns SSE stream of agent results.

    `profile` is one of conservative|balanced|aggressive (default: balanced)."""

    # Checked here rather than as a dependency: EventSource cannot read the body
    # of a 429, so an HTTP-level rejection reaches the browser as an opaque
    # error and the user sees "Analysis Failed" with no reason. Reported through
    # the stream instead, the way data-quality aborts already are.
    rate_limited = check_analyze_rate_limit(request)

    async def event_generator():
        import time

        if rate_limited is not None:
            message, retry_after = rate_limited
            yield {"event": "error", "data": _dumps(
                {"detail": message, "retry_after": retry_after, "rate_limited": True})}
            return

        from data.market_data import resolve_ticker
        from data.cache import get_cached_analysis, save_analysis_to_cache
        from graph.run_log import new_run_id, write_run_log
        from scoring import get_profile

        run_id = new_run_id()
        profile_name, _ = get_profile(profile or "")
        started = time.monotonic()
        ticker = None
        accumulated_reports: dict = {}
        judge_payload: dict = {}
        analytics: dict = {}
        # Phase 3: harvested at the end of the run, written into cache + run log
        run_telemetry: dict = {}
        run_data_quality: dict = {}

        try:
            # Resolve early to key the cache by canonical ticker (profile-aware)
            ticker = await resolve_ticker(company_name)
            if ticker == "INVALID":
                yield {
                    "event": "error",
                    "data": _dumps({"detail": f"Could not find a valid Indian stock ticker for '{company_name}'. Please try a different name."})
                }
                return

            cache_key = f"{ticker}::{profile_name}"
            cached = get_cached_analysis(cache_key)
            if cached:
                yield {
                    "event": "start",
                    "data": _dumps({"run_id": run_id, "ticker": ticker, "risk_profile": profile_name, "cached": True})
                }
                yield {
                    "event": "complete",
                    "data": _dumps(cached, default=str)
                }
                return

            yield {
                "event": "start",
                "data": _dumps({"run_id": run_id, "ticker": ticker, "risk_profile": profile_name, "cached": False})
            }

            async for event in run_stock_analysis(company_name, run_id=run_id, risk_profile=profile_name):
                if event["event"] == "node_update":
                    safe_state = {}
                    for k, v in event["state"].items():
                        if k.endswith("_report") or k in JUDGE_FIELDS or k in ANALYTICS_FIELDS:
                            safe_state[k] = v
                            if k.endswith("_report"):
                                accumulated_reports[k] = v
                            elif k in ANALYTICS_FIELDS:
                                analytics[k] = v

                    # The extended risk block is computed inside risk_data, which
                    # is not streamed wholesale (it carries a full price series).
                    risk_payload = event["state"].get("risk_data") or {}
                    if risk_payload.get("extended_risk"):
                        analytics["extended_risk"] = risk_payload["extended_risk"]
                        safe_state["extended_risk"] = risk_payload["extended_risk"]

                    if event["node"] == "judge_node" and "final_decision" in event["state"]:
                        judge_payload = {f: event["state"].get(f) for f in JUDGE_FIELDS}

                    yield {
                        "event": "node_update",
                        "data": _dumps(
                            {"node": event["node"], "state": safe_state},
                            default=str,
                        ),
                    }
                elif event["event"] == "telemetry":
                    # Phase 3: terminal telemetry event from the runner
                    run_telemetry = event.get("data") or {}
                    yield {"event": "telemetry", "data": _dumps(run_telemetry, default=str)}
                elif event["event"] == "error":
                    # Forward error events; data may be a dict (e.g. data-quality abort) or a string
                    err_data = event.get("data", {})
                    if isinstance(err_data, dict):
                        # Data-quality aborts are written for the user and carry
                        # no internals, so they pass through as-is.
                        run_data_quality = err_data.get("data_quality") or {}
                        yield {"event": "error", "data": _dumps(err_data, default=str)}
                    else:
                        logger.error(f"[analyze] run={run_id} ticker={ticker}: {err_data}")
                        yield {"event": "error", "data": _dumps(
                            {"detail": str(err_data), "run_id": run_id})}
                    return
                else:
                    yield {
                        "event": event["event"],
                        "data": _dumps({"message": event["data"]}) if isinstance(event.get("data"), str) else _dumps(event.get("data", {}))
                    }

            # Cache the full result *after* the run is complete so we have telemetry to attach.
            cached_payload = {
                "message": "Analysis Finished",
                "reports": accumulated_reports,
                "judge_report": judge_payload,
                # Included so a cache hit renders identically to a live run.
                "analytics": analytics,
                "run_id": run_id,
                "ticker": ticker,
                "risk_profile": profile_name,
                "telemetry": run_telemetry,
                "data_quality": judge_payload.get("data_quality") or run_data_quality,
            }
            if judge_payload:
                save_analysis_to_cache(cache_key, cached_payload)
        except Exception as e:
            # Full detail to the log, generic text to the browser.
            logger.exception(f"[analyze] run={run_id} ticker={ticker} failed")
            yield {
                "event": "error",
                "data": _dumps({"detail": GENERIC_ERROR, "run_id": run_id})
            }
            write_run_log(
                run_id, ticker or "UNKNOWN", company_name,
                inputs_summary={"risk_profile": profile_name},
                analyst_reports=accumulated_reports,
                judge_payload=judge_payload,
                error=str(e),
                duration_seconds=round(time.monotonic() - started, 2),
                telemetry=run_telemetry,
                data_quality=judge_payload.get("data_quality") or run_data_quality,
            )
            return

        # Successful completion: persist run log for backtesting / debugging.
        write_run_log(
            run_id, ticker or "UNKNOWN", company_name,
            inputs_summary={"risk_profile": profile_name},
            analyst_reports=accumulated_reports,
            judge_payload=judge_payload,
            duration_seconds=round(time.monotonic() - started, 2),
            telemetry=run_telemetry,
            data_quality=judge_payload.get("data_quality") or run_data_quality,
        )

    return EventSourceResponse(event_generator())

@router.get("/search/{query}")
async def search_companies(query: str):
    """Autocomplete endpoint for company name search"""
    from yahooquery import search
    try:
        results = search(query)
        valid_results = []
        if results and "quotes" in results:
            for r in results["quotes"]:
                exchange = r.get("exchange", "")
                symbol = r.get("symbol", "")
                # Skip -BL (block-deal) variants that yfinance can't resolve
                if "-BL" in symbol:
                    continue
                if exchange in ["NSI", "BSI", "NSE", "BSE", "NMS"] and r.get("quoteType") == "EQUITY":
                    # Map exchange codes to display labels
                    exchange_label = "NSE" if exchange in ["NSI", "NSE", "NMS"] else "BSE"
                    valid_results.append({
                        "name": r.get("longname", r.get("shortname", r.get("symbol"))),
                        "ticker": symbol,
                        "exchange": exchange_label,
                        "sector": r.get("sector", r.get("industry", "")),
                    })
        return {"results": valid_results[:6]}
    except Exception as e:
        return {"results": []}

@router.get("/price-history/{ticker}")
async def get_price_history(ticker: str, period: str = "1y"):
    """Fetch OHLCV price history with SMA overlays for charting.

    Accepts either a resolved exchange ticker (e.g. RELIANCE.NS) or a free-form
    company name (e.g. "Tata Motors"); names without an exchange suffix are
    resolved via the same `resolve_ticker` path the analysis flow uses."""
    import yfinance as yf
    import math
    from data.market_data import resolve_ticker

    # Validate period
    valid_periods = {"1mo", "3mo", "6mo", "1y"}
    if period not in valid_periods:
        period = "1y"

    try:
        # If the caller passed a free-form name (no exchange suffix), resolve it
        # the same way /api/analyze does — converts "Tata Motors" → "TATAMOTORS.NS".
        if "." in ticker:
            symbol = ticker
        else:
            resolved = await resolve_ticker(ticker)
            if resolved == "INVALID":
                raise HTTPException(
                    status_code=404,
                    detail=f"Could not resolve a NSE/BSE ticker for '{ticker}'.",
                )
            symbol = resolved

        stock = yf.Ticker(symbol)
        hist = stock.history(period=period)

        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No price data found for {symbol}")

        # Compute SMAs
        hist["SMA20"] = hist["Close"].rolling(window=20).mean()
        hist["SMA50"] = hist["Close"].rolling(window=50).mean()

        # Build records
        records = []
        for date, row in hist.iterrows():
            def safe(v):
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    return None
                return round(v, 2)

            records.append({
                "date": date.strftime("%Y-%m-%d"),
                "open": safe(row.get("Open")),
                "high": safe(row.get("High")),
                "low": safe(row.get("Low")),
                "close": safe(row.get("Close")),
                "volume": int(row.get("Volume", 0)),
                "sma20": safe(row.get("SMA20")),
                "sma50": safe(row.get("SMA50")),
            })

        return {"ticker": symbol, "period": period, "data": records}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[price-history] {ticker} failed")
        raise HTTPException(status_code=500, detail="Could not load price history.")

@router.get("/debug/data", dependencies=[Depends(require_debug_access)])
async def debug_data_fetch(ticker: str = "TCS.NS"):
    """Diagnostic: tests yfinance fetching directly.

    Gated by DEBUG_API_TOKEN and closed by default — it was previously public
    and returned internal fetch state plus full tracebacks to anyone who asked.
    """
    import yfinance as yf
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="5d")
        return {
            "success": True,
            "ticker": ticker,
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "pe_ratio": info.get("trailingPE"),
            "sector": info.get("sector"),
            "history_rows": len(hist),
            "info_keys_count": len(info)
        }
    except Exception as e:
        logger.exception(f"[debug/data] {ticker} failed")
        # Traceback goes to the log, not over the wire.
        return {"success": False, "ticker": ticker, "error": str(e)[:200]}
