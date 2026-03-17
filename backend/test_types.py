import asyncio
import traceback
from agents.macro_governance_analyst import run_macro_governance_analysis
from agents.financial_analyst import run_financial_analysis

async def main():
    state = {
        "company_name": "Test",
        "ticker": "TEST",
        "fundamental_data": {
            "sector": "auto",
            "roe": "0.15", # string instead of float
            "pe_ratio": "25"
        },
        "market_breadth": {
            "crude": {"current": None}, # None handling
            "usdinr": {"current": 83}
        },
        "governance_data": {
            "promoter_pledge_pct": "N/A" # string handling
        },
        "earnings_data": {},
        "peer_data": {
            "sector_median_pe": "20.5"
        }
    }
    
    print("Testing Macro/Gov Analyst...")
    try:
        await run_macro_governance_analysis(state)
        print("Macro/Gov Analyst Success!")
    except Exception as e:
        print("Macro/Gov Analyst Failed:")
        traceback.print_exc()

    print("\nTesting Financial Analyst...")
    try:
        await run_financial_analysis(state)
        print("Financial Analyst Success!")
    except Exception as e:
        print("Financial Analyst Failed:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
