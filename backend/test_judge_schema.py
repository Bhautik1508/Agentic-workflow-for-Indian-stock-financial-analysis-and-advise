import asyncio
from graph.runner import run_stock_analysis

async def run():
    async for e in run_stock_analysis("BPCL"):
        if getattr(e, "get", None) and e.get("event") == "node_update" and e.get("node") == "judge_node":
            print("\n\n--- RAW JUDGE NODE STATE OUTPUT ---")
            print(repr(e))

asyncio.run(run())
