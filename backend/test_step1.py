import asyncio
from data.market_data import fetch_all_market_data, resolve_ticker
import json

async def test_step_1():
    print("--- Testing Phase 10 Step 1: YahooQuery Fundamentals ---")
    ticker = await resolve_ticker("tata motors")
    print(f"Resolved Ticker: {ticker}")
    
    print(f"\nFetching Market Data for {ticker}...")
    try:
        data = await fetch_all_market_data(ticker)
        
        fundamentals = data.get("fundamental_data", {})
        price = data.get("price_data", {})
        
        print("\n✅ Fundamental Data Extracted:")
        # Filter out None values to show what was successfully fetched
        clean_fundamentals = {k: v for k, v in fundamentals.items() if v is not None}
        print(json.dumps(clean_fundamentals, indent=2))
        
        print(f"\n✅ Basic Price Extracted:")
        print(f"Current Price: {price.get('current_price')}")
        print(f"Market Cap: {price.get('market_cap')}")
        
        if fundamentals.get('pe_ratio'):
            print("\n🎉 SUCCESS: YahooQuery fundamental fetch is working!")
        else:
            print("\n⚠️ WARNING: Missing PE ratio, check data payload fallback.")
            
    except Exception as e:
        print(f"\n❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_step_1())
