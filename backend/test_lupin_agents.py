import asyncio
import os
import traceback
from dotenv import load_dotenv

load_dotenv(".env")

from agents.financial_analyst import run_financial_analysis
from agents.macro_governance_analyst import run_macro_governance_analysis
from data.market_data import fetch_all_market_data, fetch_risk_data, fetch_technical_data, fetch_earnings_data, fetch_institutional_data, fetch_sector_peers, fetch_market_breadth, fetch_nse_risk_signals, fetch_nse_insider_trading, fetch_world_bank_macro, fetch_market_context, fetch_rbi_repo_rate
from data.governance_data import fetch_governance_data
import pandas as pd

async def main():
    ticker = "LUPIN.NS"
    print("Fetching fundamental data for", ticker)
    market_data = await fetch_all_market_data(ticker)
    
    hist = market_data.get("price_data", {}).get("history", [])
    hist_df = pd.DataFrame(hist) if hist else pd.DataFrame()
    sector = market_data.get("fundamental_data", {}).get("sector", "")
    
    risk_data = await fetch_risk_data(ticker, hist_df, hist_df)
    tech_data = await asyncio.to_thread(fetch_technical_data, ticker, hist_df)
    earnings_data = await fetch_earnings_data(ticker)
    inst_data = await fetch_institutional_data(ticker)
    peer_data = await fetch_sector_peers(ticker, sector)
    market_breadth = await fetch_market_breadth()
    nse_risk = await fetch_nse_risk_signals(ticker.split('.')[0])
    gov_screener = await asyncio.to_thread(fetch_governance_data, ticker)
    insider_data = await fetch_nse_insider_trading(ticker.split('.')[0])
    
    macro_data = {
        **fetch_world_bank_macro(),
        **fetch_market_context(),
        **fetch_rbi_repo_rate()
    }
    full_gov_data = {
        **gov_screener,
        "insider_transactions": insider_data,
    }
    
    state = {
        "company_name": "Lupin",
        "ticker": ticker,
        "price_data": market_data.get("price_data", {}),
        "fundamental_data": market_data.get("fundamental_data", {}),
        "screener_data": market_data.get("screener_data", {}),
        "nse_data": nse_risk,
        "risk_data": risk_data,
        "technical_data": tech_data,
        "macro_data": macro_data,
        "governance_data": full_gov_data,
        "earnings_data": earnings_data,
        "institutional_data": inst_data,
        "market_breadth": market_breadth,
        "peer_data": peer_data,
    }
    
    print("\n--- Running Financial Analyst ---")
    try:
        report = await run_financial_analysis(state)
        print("Status:", getattr(report, "status", None))
        print("Error Data:", getattr(report, "data", {}).get("error", "OK"))
    except Exception as e:
        print("Fin Analyst crashed!")
        traceback.print_exc()
        
    print("\n--- Running Macro Gov Analyst ---")
    try:
        report = await run_macro_governance_analysis(state)
        print("Status:", getattr(report, "status", None))
        print("Error Data:", getattr(report, "data", {}).get("error", "OK"))
    except Exception as e:
        print("Macro Gov crashed!")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
