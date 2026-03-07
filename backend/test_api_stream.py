import httpx
import json
import asyncio

async def test_sse_endpoint():
    """Test the streaming output of the FastAPI /analyze endpoint"""
    print("Testing SSE Stream for 'wipro'...")
    url = "http://127.0.0.1:8000/api/analyze/wipro"
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    print(f"Error: {response.status_code}")
                    return
                
                async for line in response.aiter_lines():
                    if line:
                        print(line)
                        
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    asyncio.run(test_sse_endpoint())
