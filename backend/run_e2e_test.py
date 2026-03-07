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
            print(f"\n🎉 DONE: {event['data']}")
        elif event["event"] == "error":
            print(f"\n❌ ERROR: {event['data']}")
            
if __name__ == "__main__":
    asyncio.run(main())
