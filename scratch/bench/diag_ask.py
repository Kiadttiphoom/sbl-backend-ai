import httpx
import asyncio
import json

async def check():
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            url = "http://127.0.0.1:8000/ask?q=ยอดรวมคงเหลือทั้งหมด"
            print(f"Checking {url} ...")
            # /ask returns a stream of NDJSON
            async with client.stream("GET", url) as r:
                print(f"Status: {r.status_code}")
                async for line in r.aiter_lines():
                    if line:
                        print(f"Event: {line}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
