import asyncio
import sys
import json
import time

# Ensure imports work from the backend directory
sys.path.append('.')

from data.market_data import resolve_ticker, fetch_all_market_data, fetch_news
from agents.financial_analyst import run_financial_analysis
from agents.sentiment_analyst import run_sentiment_analysis
from agents.risk_analyst import run_risk_analysis
from agents.technical_analyst import run_technical_analysis
from agents.macro_analyst import run_macro_analysis
from agents.governance_analyst import run_governance_analysis

async def run_cli_test():
    print("=========================================")
    print("🧠 StockSage AI: CLI Agent Tester")
    print("=========================================")
    
    company_name = input("\nEnter a company name (e.g., 'zomato', 'tcs', 'hdfc'): ").strip()
    if not company_name:
        return

    print(f"\n🔍 Resolving ticker for '{company_name}'...")
    ticker = await resolve_ticker(company_name)
    print(f"🎯 Resolved to: {ticker}")

    print("\n⏳ Fetching market and fundamental data (this may take a moment)...")
    market_data = await fetch_all_market_data(ticker)
    
    # Check if we got the fallback data
    if market_data.get("price_data", {}).get("current_price") == 1500.0 and ticker != "MOCK.NS":
         print("⚠️ WARNING: Fetched mock data (likely hit Yahoo Finance rate limits).")
    else:
         print(f"✅ Data fetched successfully! Current Price: ₹{market_data['price_data'].get('current_price')}")

    print("📰 Fetching recent news via DuckDuckGo...")
    news_data = await fetch_news(company_name)

    # Build the state object manually since we don't have LangGraph wired up yet
    state = {
        "company_name": company_name,
        "ticker": ticker,
        "exchange": "NSE" if ticker.endswith(".NS") else "BSE",
        "price_data": market_data.get("price_data", {}),
        "fundamental_data": market_data.get("fundamental_data", {}),
        "news_data": news_data, 
    }

    print("\n🚀 Starting parallel agent execution...")
    start_time = time.time()
    
    # Run all 6 agents concurrently
    results = await asyncio.gather(
        run_financial_analysis(state),
        run_sentiment_analysis(state),
        run_risk_analysis(state),
        run_technical_analysis(state),
        run_macro_analysis(state),
        run_governance_analysis(state),
        return_exceptions=True
    )
    
    execution_time = time.time() - start_time
    print(f"⏱️ Agents finished in {execution_time:.2f} seconds.\n")
    
    print("=========================================")
    print("📊 AGENT REPORTS")
    print("=========================================\n")
    
    for report in results:
        if isinstance(report, Exception):
            print(f"❌ An agent crashed completely: {report}")
            continue
            
        agent_name = report.get("agent_name", "Unknown Agent")
        status = report.get("status", "unknown")
        
        if status == "error":
            print(f"[{agent_name}] ❌ ERROR: {report.get('summary')}")
        else:
            print(f"[{agent_name}] ✅ SCORE: {report.get('score')}/10 \n   Summary: {report.get('summary')}")
            print(f"   Findings: {report.get('key_findings')}")
            if report.get('risk_flags'):
                print(f"   Risks: {report.get('risk_flags')}")
        print("-" * 50)

if __name__ == "__main__":
    import os
    if not os.environ.get("GOOGLE_API_KEY"):
         print("\n⚠️  WARNING: You don't have GOOGLE_API_KEY set in your terminal session.")
         print("Please export it or make sure it's in your backend/.env before running real inferences.")
         print("Example: export GOOGLE_API_KEY=your_key_here\n")
    
    # Standard python 3.9+ async entry point
    asyncio.run(run_cli_test())
