import asyncio
import logging
from typing import Optional
import pandas as pd
from graph.workflow import build_workflow
from graph.state import StockAnalysisState
from graph.run_log import new_run_id
from data.market_data import (
    resolve_ticker, fetch_all_market_data, fetch_news,
    fetch_gdelt_sentiment, fetch_fii_dii_data, fetch_nse_risk_signals,
    fetch_bse_governance, fetch_nse_insider_trading, fetch_world_bank_macro,
    fetch_market_context, fetch_rbi_repo_rate, fetch_risk_data, fetch_technical_data,
    fetch_earnings_data, fetch_institutional_data, fetch_sector_peers,
    fetch_market_breadth, fetch_index_history, fetch_all_indices,
    drop_incomplete_sessions,
)
from data.governance_data import fetch_governance_data
from data.options_data import fetch_options_signals
from data.freshness import stamp, freshness_for, collect_stale_sources, INTRADAY_STALE_AFTER_HOURS
from llm import LLMTelemetry, set_current_telemetry, reset_current_telemetry

logger = logging.getLogger(__name__)


async def run_stock_analysis(
    company_name: str,
    run_id: Optional[str] = None,
    risk_profile: Optional[str] = None,
):
    """
    Executes the full LangGraph pipeline to analyze a stock.
    Yields intermediate states (events) for SSE streaming.
    """
    from scoring import get_profile
    from scoring.data_quality import evaluate_data_quality

    run_id = run_id or new_run_id()
    profile_name, _ = get_profile(risk_profile or "")

    # Phase 3: install per-run LLM telemetry collector. The token is reset in
    # the `finally` so a long-running event loop doesn't leak collectors.
    telemetry = LLMTelemetry()
    telemetry_token = set_current_telemetry(telemetry)

    try:
        yield {"event": "start", "data": {"run_id": run_id, "company_name": company_name, "risk_profile": profile_name}}
        yield {"event": "status", "data": f"Resolving ticker for {company_name}..."}
        ticker = await resolve_ticker(company_name)
        if ticker == "INVALID":
            yield {"event": "error", "data": f"Could not find a valid Indian stock ticker for '{company_name}'. Please try a different name."}
            return

        yield {"event": "status", "data": f"Fetching core fundamental & price data for {ticker}..."}
        market_data = await fetch_all_market_data(ticker)

        # Extract DataFrames for TA and Risk
        hist = market_data.get("price_data", {}).get("history", [])
        hist_df = pd.DataFrame(hist) if hist else pd.DataFrame()

        # Guarded here as well as at the fetch: a `@cached_fetch` hit returns
        # the stored payload without re-running the fetch body, so a payload
        # captured mid-session carries the bad row into every later run of the
        # day. See drop_incomplete_sessions for what that costs.
        before = len(hist_df)
        hist_df = drop_incomplete_sessions(hist_df)
        if len(hist_df) != before:
            hist_df = hist_df.reset_index(drop=True)
            logger.info(
                f"[runner] {ticker}: dropped {before - len(hist_df)} row(s) with "
                f"no close (incomplete session)"
            )

        yield {"event": "status", "data": "Compiling technical indicators, risk models & earnings data locally..."}

        # Real market benchmark for beta. This previously passed the stock's OWN
        # history ("nifty_mock"), which made beta exactly cov(x,x)/var(x) = 1.00
        # for every company ever analysed. If the index is unavailable we pass
        # None, and beta comes back unset — an honest gap beats a fabricated 1.0.
        benchmark = await fetch_index_history()
        benchmark_rows = (benchmark or {}).get("history") or []
        nifty_df = pd.DataFrame(benchmark_rows) if benchmark_rows else None
        if nifty_df is None:
            logger.warning(
                "[runner] market benchmark unavailable — beta and correlation "
                "will be reported as unset for this run"
            )

        # Get sector for peer comparison
        sector = market_data.get("fundamental_data", {}).get("sector", "")

        indices = await fetch_all_indices()

        risk_data, tech_data, earnings_data, institutional_data, peer_data, market_breadth = await asyncio.gather(
            fetch_risk_data(ticker, hist_df, nifty_df),
            fetch_technical_data(ticker, hist_df),
            fetch_earnings_data(ticker),
            fetch_institutional_data(ticker),
            fetch_sector_peers(ticker, sector),
            fetch_market_breadth(),
        )

        yield {"event": "status", "data": "Scraping Sentiment, News & FII/DII datastreams..."}
        news_data = await fetch_news(company_name, ticker)
        gdelt_data = await asyncio.to_thread(fetch_gdelt_sentiment, company_name)
        fii_dii = await asyncio.to_thread(fetch_fii_dii_data)

        yield {"event": "status", "data": "Fetching Macroeconomic, Governance & Options context..."}
        nse_risk = await fetch_nse_risk_signals(ticker.split('.')[0])

        # Fetch new governance data from Screener.in + old BSE governance as fallback
        gov_screener = await asyncio.to_thread(fetch_governance_data, ticker)
        options_data = await asyncio.to_thread(fetch_options_signals, ticker.split('.')[0])

        insider_data = await fetch_nse_insider_trading(ticker.split('.')[0])

        macro_data = {
            **fetch_world_bank_macro(),
            **fetch_market_context(),
            **fetch_rbi_repo_rate()
        }

        # ── Benchmark- and sector-relative context ──
        # "Down 8%" is not a verdict input; "down 8% while the sector is down
        # 15%" is. NSE publishes 30d/365d moves per index, so the sector
        # comparison costs no extra fetch.
        from data.relative_strength import build_relative_context
        from data.market_data import _close_by_date, risk_free_rate_pct

        _fund_for_sector = market_data.get("fundamental_data") or {}
        relative_context = build_relative_context(
            _close_by_date(hist_df),
            _close_by_date(nifty_df) if nifty_df is not None else None,
            indices,
            sector=_fund_for_sector.get("sector"),
            industry=_fund_for_sector.get("industry"),
            beta=(risk_data or {}).get("beta"),
            risk_free_pct=risk_free_rate_pct(),
        )

        # Extract screener data from market_fetch
        screener_data = market_data.get("screener_data", {})

        # ── Accounting-quality metrics ──
        # Computed in Python, not inferred by the model: a model asked to derive
        # a Piotroski score from a table produces something plausible and
        # unverifiable. The agents interpret these; they do not calculate them.
        from scoring.quality_metrics import build_quality_metrics

        quality_metrics = build_quality_metrics(screener_data)

        # ── Altman Z. The veto in scoring/vetos.py has always read
        # `altman_z_score`; nothing ever wrote it, so the distress check was
        # dead code and the risk prompt printed N/A on every run.
        from scoring.altman import compute_altman_z

        altman = compute_altman_z(
            screener_data,
            market_data.get("fundamental_data") or {},
            sector=(market_data.get("fundamental_data") or {}).get("sector"),
            company_name=company_name,
        )
        if altman.score is None:
            logger.info(f"[altman] {ticker}: not computed — {altman.reason}")

        # Build comprehensive governance data
        full_gov_data = {
            **gov_screener,
            "insider_transactions": insider_data,
        }

        # ── Phase 3: stamp `as_of` on each source so the UI can warn about stale data ──
        # Dict payloads get stamped in-place; list payloads (news) get a side-channel
        # `*_freshness` key so their type contract isn't broken.
        price_data = stamp(
            market_data.get("price_data", {}) or {},
            "yfinance.price",
            stale_after_hours=INTRADAY_STALE_AFTER_HOURS,
        )
        fundamental_data = stamp(
            market_data.get("fundamental_data", {}) or {},
            "yfinance.fundamentals",
        )
        fundamental_data["altman_z_score"] = altman.score
        fundamental_data["altman_zone"] = altman.zone
        fundamental_data["altman_variant"] = altman.variant
        fundamental_data["altman_veto_eligible"] = altman.veto_eligible
        fundamental_data["altman_detail"] = altman.to_dict()
        if isinstance(screener_data, dict) and screener_data:
            stamp(screener_data, "screener.in")
        if isinstance(fii_dii, dict) and fii_dii:
            stamp(fii_dii, "moneycontrol.fii_dii")
        if isinstance(nse_risk, dict) and nse_risk:
            stamp(nse_risk, "nse.surveillance", stale_after_hours=INTRADAY_STALE_AFTER_HOURS)

        # Initialize state. news_data stays a list — pair it with side-channel freshness.
        state: StockAnalysisState = {
            "company_name": company_name,
            "ticker": ticker,
            "exchange": "NSE" if ticker.endswith(".NS") else "BSE",
            "price_data": price_data,
            "fundamental_data": fundamental_data,
            "news_data": news_data,
            "news_data_freshness": freshness_for("marketaux.news") if news_data else None,
            "screener_data": screener_data,
            "fii_dii_data": fii_dii,
            "gdelt_data": gdelt_data,
            "nse_data": nse_risk,
            "risk_data": risk_data,
            "technical_data": tech_data,
            "macro_data": macro_data,
            "governance_data": full_gov_data,
            "earnings_data": earnings_data,
            "institutional_data": institutional_data,
            "options_data": options_data,
            "market_breadth": market_breadth,
            "peer_data": peer_data,
            "relative_context": relative_context,
            "quality_metrics": quality_metrics,
            "indices": indices,
            "run_id": run_id,
            "risk_profile": profile_name,
        }

        # ── Phase 3: data-quality gate. Refuse to render a verdict if completeness is too low. ──
        quality = evaluate_data_quality(state)
        state["data_quality"] = quality.to_dict()
        state["stale_sources"] = collect_stale_sources(state)

        if quality.abort:
            yield {
                "event": "error",
                "data": {
                    "detail": quality.abort_reason or "Insufficient data for trustworthy analysis.",
                    "data_quality": quality.to_dict(),
                    "ticker": ticker,
                    "run_id": run_id,
                },
            }
            return

        if quality.warnings:
            yield {"event": "status", "data": "Data quality OK but with warnings — verdict confidence will be capped."}

        workflow = build_workflow()

        yield {"event": "status", "data": "Deploying specialist agents..."}

        # Stream the graph execution
        async for event in workflow.astream(state):
            for node_name, node_state in event.items():
                yield {"event": "node_update", "node": node_name, "state": node_state}

        # Phase 3: surface telemetry as a final event before completion so consumers
        # who don't read the run log can still see model spend.
        yield {
            "event": "telemetry",
            "data": telemetry.to_dict(),
        }

        yield {"event": "complete", "data": "Analysis Finished"}
    finally:
        reset_current_telemetry(telemetry_token)
