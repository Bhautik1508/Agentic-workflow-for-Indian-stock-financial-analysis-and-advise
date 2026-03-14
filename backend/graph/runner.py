import asyncio
import pandas as pd
from graph.workflow import build_workflow
from graph.state import StockAnalysisState
from data.market_data import (
    resolve_ticker, fetch_all_market_data, fetch_news,
    fetch_gdelt_sentiment, fetch_fii_dii_data, fetch_nse_risk_signals,
    fetch_bse_governance, fetch_nse_insider_trading, fetch_world_bank_macro,
    fetch_market_context, fetch_rbi_repo_rate, fetch_risk_data, fetch_technical_data,
    fetch_earnings_data
)

async def run_stock_analysis(company_name: str):
    """
    Executes the full LangGraph pipeline to analyze a stock.
    Yields intermediate states (events) for SSE streaming.
    """
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
    
    yield {"event": "status", "data": "Compiling technical indicators, risk models & earnings data locally..."}
    
    # Provide a mock Nifty DataFrame for Beta calculations to prevent crashing if offline
    nifty_mock = hist_df.copy() if not hist_df.empty else None
    
    risk_data, tech_data, earnings_data = await asyncio.gather(
        fetch_risk_data(ticker, hist_df, nifty_mock),
        fetch_technical_data(ticker, hist_df),
        fetch_earnings_data(ticker),
    )
    
    yield {"event": "status", "data": "Scraping Sentiment, News & FII/DII datastreams..."}
    news_data = await fetch_news(company_name, ticker)
    gdelt_data = await asyncio.to_thread(fetch_gdelt_sentiment, company_name)
    fii_dii = await asyncio.to_thread(fetch_fii_dii_data)
    
    yield {"event": "status", "data": "Fetching Macroeconomic & Governance context..."}
    nse_risk = await fetch_nse_risk_signals(ticker.split('.')[0])
    bse_code = "500325" # Mocking BSE code mapping for now
    
    gov_data = await fetch_bse_governance(bse_code)
    insider_data = await fetch_nse_insider_trading(ticker.split('.')[0])
    
    macro_data = {
        **fetch_world_bank_macro(),
        **fetch_market_context(),
        **fetch_rbi_repo_rate()
    }
    
    # Extract screener data from market_fetch
    screener_data = market_data.get("screener_data", {})
    
    # Combine Governance
    promoter_holding_trend = "stable"
    if screener_data and "Shareholding Pattern" in screener_data:
        # Complex to parse generically, keeping placeholder logic for final gov data payload
        pass
        
    full_gov_data = {
        "shareholding": gov_data.get("shareholding"),
        "announcements": gov_data.get("announcements"),
        "insider_transactions": insider_data,
        "promoter_holding_quarterly": [],
        "trend": promoter_holding_trend,
        "promoter_pledge_pct": 0
    }

    # Initialize state
    state: StockAnalysisState = {
        "company_name": company_name,
        "ticker": ticker,
        "exchange": "NSE" if ticker.endswith(".NS") else "BSE",
        "price_data": market_data.get("price_data", {}),
        "fundamental_data": market_data.get("fundamental_data", {}),
        "news_data": news_data,
        "screener_data": screener_data,
        "fii_dii_data": fii_dii,
        "gdelt_data": gdelt_data,
        "nse_data": nse_risk,
        "risk_data": risk_data,
        "technical_data": tech_data,
        "macro_data": macro_data,
        "governance_data": full_gov_data,
        "earnings_data": earnings_data,
        "run_id": "test_run_123"
    }

    workflow = build_workflow()
    
    yield {"event": "status", "data": "Deploying specialist agents..."}
    
    # Stream the graph execution
    async for event in workflow.astream(state):
        # Determine which node(s) just finished
        for node_name, node_state in event.items():
            yield {"event": "node_update", "node": node_name, "state": node_state}

    yield {"event": "complete", "data": "Analysis Finished"}
