import asyncio
import sys
# Make sure we can import from backend dir
sys.path.append('.')

from data.market_data import resolve_ticker, fetch_all_market_data

async def run_tests():
    print("--- Testing Ticker Resolution ---")
    test_cases = ["reliance", "tch mahindra", "hdfc bank"]
    for company in test_cases:
        ticker = await resolve_ticker(company)
        print(f"'{company}' resolves to -> {ticker}")

    print("\n--- Testing Market Data Fetch ---")
    ticker = "ZOMATO.NS" 
    print(f"Fetching data for {ticker}...")
    try:
        data = await fetch_all_market_data(ticker)
        print(f"Successfully fetched price data keys: {data['price_data'].keys()}")
        print(f"Current Price: {data['price_data'].get('current_price')}")
        print(f"Market Cap: {data['price_data'].get('market_cap')}")
        print(f"Fundamentals (PE): {data['fundamental_data'].get('pe_ratio')}")
        print("Data fetch test: PASSED")
    except Exception as e:
        print(f"Data fetch test: FAILED -> {e}")

if __name__ == "__main__":
    asyncio.run(run_tests())
