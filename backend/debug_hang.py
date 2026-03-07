import asyncio
from yahooquery import Ticker
from data.market_data import resolve_ticker, scrape_screener

async def debug_yq(ticker):
    print(f"Initializing Ticker({ticker})...")
    stock = Ticker(ticker)
    print("Calling summary_detail...")
    sd = stock.summary_detail
    print("Calling financial_data...")
    fd = stock.financial_data
    print("Calling price...")
    price = stock.price
    print("Done YQ.")

async def debug_screener(slug):
    print(f"Calling scrape_screener({slug})...")
    scrape_screener(slug)
    print("Done Screener.")

async def main():
    ticker = await resolve_ticker("tata motors")
    print(f"Resolved to {ticker}")
    
    try:
        await asyncio.wait_for(debug_yq(ticker), timeout=10)
    except asyncio.TimeoutError:
        print("YQ TIMED OUT!")
        
    try:
        slug = ticker.split(".")[0]
        await asyncio.wait_for(debug_screener(slug), timeout=10)
    except asyncio.TimeoutError:
        print("SCREENER TIMED OUT!")

if __name__ == "__main__":
    asyncio.run(main())
