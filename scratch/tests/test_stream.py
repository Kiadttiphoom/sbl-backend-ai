import httpx
import json
import asyncio

async def test_streaming():
    url = "http://localhost:8000/ask?q=สวัสดี"
    print(f"Testing streaming from {url}...")
    
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("GET", url) as response:
                print(f"Status: {response.status_code}")
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if data['type'] == 'metadata':
                            print(f"[Metadata] Intent: {data.get('intent')}")
                        elif data['type'] == 'content':
                            print(data['content'], end="", flush=True)
                        elif data['type'] == 'done':
                            print(f"\n[Done] Time: {data.get('total_time')}")
                    except Exception as e:
                        print(f"\nError parsing line: {line}\n{e}")
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    asyncio.run(test_streaming())
