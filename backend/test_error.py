import asyncio
import os
import traceback
from dotenv import load_dotenv

load_dotenv(".env")
from graph.runner import run_stock_analysis

async def main():
    print(f"GROQ_API_KEY present: {'GROQ_API_KEY' in os.environ}")
    try:
        async for event in run_stock_analysis("TCS"):
            print("Event:", event.get("event"))
            if event.get("event") == "error":
                print("Error Details:", event.get("data"))
            if event.get("event") == "node_update":
                state = event.get("state")
                node = event.get("node")
                
                # Check if it's the financial analyst
                if node == "financial_analysis":
                    print("Financial Analyst Output:", state.get("financial_analysis", {}).get("error", "OK"))
                if node == "macro_governance_analysis":
                    print("Macro Gov Output:", state.get("macro_governance_analysis", {}).get("error", "OK"))
    except Exception as e:
        print("EXCEPTION RAISED:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
