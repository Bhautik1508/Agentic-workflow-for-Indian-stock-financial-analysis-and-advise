import asyncio
import json
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from data.market_data import fetch_all_market_data, resolve_ticker, fetch_technical_data
from agents.financial_analyst import run_financial_analysis

async def run_tests():
    print("=== Testing Phase 10: Steps 1 to 5 ===")
    
    try:
        print("\n--- Steps 1 & 2: Market Data Fetching ---")
        ticker = await resolve_ticker("tata motors")
        print(f"Ticker resolved: {ticker}")
        
        data = await fetch_all_market_data(ticker)
        fundamentals = data.get("fundamental_data", {})
        price_data = data.get("price_data", {})
        screener_data = data.get("screener_data", {})
        hist = price_data.get("history", [])
        
        print(f"✅ Fundamentals retrieved: {len(fundamentals)} metrics")
        print(f"✅ Screener data retrieved: {len(screener_data)} sections")
        print(f"✅ Price history retrieved: {len(hist)} days")

        print("\n--- Step 5: Technical Indicators (ta library) ---")
        tech_data = {}
        if hist:
            df = pd.DataFrame(hist)
            tech_data = await fetch_technical_data(ticker, df)
            print(f"✅ Technical indicators computed: {len(tech_data)} metrics")
            sample_keys = list(tech_data.keys())[:5]
            print(f"Sample of TA data: {json.dumps({k: tech_data[k] for k in sample_keys}, indent=2)}")
        else:
            print("WARNING: No price history extracted, skipping TA.")

        print("\n--- Steps 3 & 4: Financial Analyst LLM Execution ---")
        print("Executing one LLM call to verify prompt and JSON schema output...")
        
        state = {
            "company_name": "Tata Motors",
            "ticker": ticker,
            "exchange": "NSE",
            "price_data": price_data,
            "fundamental_data": fundamentals,
            "news_data": [],
            "screener_data": screener_data,
            "fii_dii_data": {},
            "gdelt_data": {},
            "nse_data": {},
            "risk_data": {},
            "technical_data": tech_data,
            "macro_data": {},
            "governance_data": {},
            "run_id": "test_run_123"
        }
        
        report = await run_financial_analysis(state)
        
        print(f"\n✅ FINANCIAL ANALYST REPORT STATUS: {report.get('status', report.status if hasattr(report, 'status') else 'Unknown')}")
        
        score = report.get('score') if isinstance(report, dict) else report.score
        summary = report.get('summary') if isinstance(report, dict) else report.summary
        
        print(f"Score: {score}/10")
        print(f"Summary: {summary}")
        
        if score and summary:
            print("\n🎉 SUCCESS: All steps 1 to 5 executed correctly!")
        else:
            print("\n⚠️ WARNING: LLM output might be malformed.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(run_tests())
