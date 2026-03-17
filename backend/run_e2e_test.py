import asyncio
from graph.runner import run_stock_analysis

async def main():
    print("Starting E2E Test on Tata Motors...")
    async for event in run_stock_analysis("tata motors"):
        if event["event"] == "status":
            print(f"STATUS: {event['data']}")
        elif event["event"] == "node_update":
            node = event["node"]
            print(f"\n✅ NODE FINISHED: {node}")
        elif event["event"] == "complete":
            d = event.get('data', {})
            print(f"\n🎉 DONE: Analysis Finished")
            print(f"   Final Decision:    {d.get('final_decision')}")
            print(f"   Action:            {d.get('action')}")
            print(f"   Conviction Level:  {d.get('conviction_level')}")
            print(f"   Max Entry Price:   {d.get('max_entry_price')}")
            print(f"   Key Catalysts:     {d.get('key_catalysts')}")
        elif event["event"] == "error":
            print(f"\n❌ ERROR: {event['data']}")
            
if __name__ == "__main__":
    asyncio.run(main())
