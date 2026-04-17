import httpx
import asyncio

async def check():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            print("Checking http://127.0.0.1:8000/ ...")
            r = await client.get("http://127.0.0.1:8000/")
            print(f"Status: {r.status_code}")
            print(f"Body: {r.text}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check())
