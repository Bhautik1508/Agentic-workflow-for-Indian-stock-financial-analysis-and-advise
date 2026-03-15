from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from graph.runner import run_stock_analysis
import json
import os

router = APIRouter()

@router.get("/health")
async def health_check():
    """Health check endpoint used by Render and monitoring tools."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "environment": "production" if os.getenv("RENDER") else "development",
    }

@router.get("/analyze/{company_name}")
async def analyze_stock(company_name: str):
    """
    Main analysis endpoint — returns SSE stream of agent results.
    """
    async def event_generator():
        try:
            from data.market_data import resolve_ticker
            from data.cache import get_cached_analysis, save_analysis_to_cache
            
            # Resolve early to check the cache
            ticker = await resolve_ticker(company_name)
            if ticker == "INVALID":
                yield {
                    "event": "error",
                    "data": json.dumps({"detail": f"Could not find a valid Indian stock ticker for '{company_name}'. Please try a different name."})
                }
                return
                
            cached = get_cached_analysis(ticker)
            if cached:
                # If cached, we stream a "complete" event immediately
                yield {
                    "event": "complete",
                    "data": json.dumps(cached, default=str)
                }
                return
                
            final_report_saved = False
            accumulated_reports = {}
            async for event in run_stock_analysis(company_name):
                # The LangGraph runner yields dicts with "event" and "data"/"state" keys
                # sse-starlette expects a dict with "event" and "data" keys (stringified)
                
                # Check if it's a node_update to stringify the AgentReport payload
                if event["event"] == "node_update":
                    # Sanitize the payload: strip out large raw datasets to prevent json.dumps crashes
                    safe_state = {}
                    for k, v in event["state"].items():
                        if k.endswith("_report") or k in ["final_decision", "confidence_score", "investment_thesis", "key_risks"]:
                            safe_state[k] = v
                            if k.endswith("_report"):
                                accumulated_reports[k] = v
                    
                    # For caching, detect the judge node
                    if event["node"] == "judge_node" and "final_decision" in event["state"]:
                        # Save the final decision and accumulated reports to cache
                        cached_payload = {
                            "message": "Analysis Finished",
                            "reports": accumulated_reports,
                            "judge_report": {
                                "final_decision": event["state"].get("final_decision", "HOLD"),
                                "confidence_score": event["state"].get("confidence_score", 0),
                                "investment_thesis": event["state"].get("investment_thesis", ""),
                                "key_risks": event["state"].get("key_risks", [])
                            }
                        }
                        save_analysis_to_cache(ticker, cached_payload)
                        final_report_saved = True

                    yield {
                        "event": "node_update",
                        "data": json.dumps({
                            "node": event["node"],
                            "state": safe_state
                        }, default=str) # Handle un-serializable enums/objects
                    }
                else:
                    # Regular status or complete events
                    yield {
                        "event": event["event"],
                        "data": json.dumps({"message": event["data"]}) if isinstance(event.get("data"), str) else json.dumps(event.get("data", {}))
                    }
        except Exception as e:
            # Send an error event over the SSE stream before closing
            yield {
                "event": "error",
                "data": json.dumps({"detail": str(e)})
            }
            
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
    """Fetch OHLCV price history with SMA overlays for charting."""
    import yfinance as yf
    import math

    # Validate period
    valid_periods = {"1mo", "3mo", "6mo", "1y"}
    if period not in valid_periods:
        period = "1y"

    try:
        # Append .NS if not already suffixed
        symbol = ticker if "." in ticker else f"{ticker}.NS"
        stock = yf.Ticker(symbol)
        hist = stock.history(period=period)

        if hist.empty:
            raise HTTPException(status_code=404, detail=f"No price data found for {ticker}")

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
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/health")
async def health():
    return {"status": "ok", "message": "Backend is running"}
