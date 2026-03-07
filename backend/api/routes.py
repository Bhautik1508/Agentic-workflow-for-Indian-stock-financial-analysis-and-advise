from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse
from graph.runner import run_stock_analysis
import json

router = APIRouter()

@router.get("/analyze/{company_name}")
async def analyze_stock(company_name: str):
    """
    Main analysis endpoint — returns SSE stream of agent results.
    """
    async def event_generator():
        try:
            async for event in run_stock_analysis(company_name):
                # The LangGraph runner yields dicts with "event" and "data"/"state" keys
                # sse-starlette expects a dict with "event" and "data" keys (stringified)
                
                # Check if it's a node_update to stringify the AgentReport payload
                if event["event"] == "node_update":
                    yield {
                        "event": "node_update",
                        "data": json.dumps({
                            "node": event["node"],
                            "state": event["state"]
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
    # Placeholder search, can be expanded to actively query yfinance tickers
    return {"results": [{"name": query, "ticker": f"{query.upper()}.NS"}]}

@router.get("/health")
async def health():
    return {"status": "ok", "message": "Backend is running"}
