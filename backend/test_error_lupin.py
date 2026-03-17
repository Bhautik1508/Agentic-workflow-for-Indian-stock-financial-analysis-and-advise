import asyncio
import os
import traceback
from dotenv import load_dotenv

load_dotenv(".env")
from graph.runner import run_stock_analysis

async def main():
    try:
        async for event in run_stock_analysis("BPCL.NS"):
            if event.get("event") == "node_update":
                state = event.get("state")
                node = event.get("node")
                
                if node == "parallel_analysts" or node == "financial_analysis" or node == "macro_governance_analysis":
                    fin = state.get("financial_analysis")
                    if fin:
                        print("FINANCIAL REP:", fin.model_dump() if hasattr(fin, "model_dump") else fin)
                    mac = state.get("macro_governance_analysis")
                    if mac:
                        print("MACRO REP:", mac.model_dump() if hasattr(mac, "model_dump") else mac)
    except Exception as e:
        print("EXCEPTION RAISED IN PIPELINE:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
