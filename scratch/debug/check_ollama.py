import httpx
import asyncio

async def check_ollama():
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            print("Checking Ollama at http://localhost:11434/api/tags ...")
            r = await client.get("http://localhost:11434/api/tags")
            print(f"Status: {r.status_code}")
            print(f"Models: {r.json().get('models', [])[:3]}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(check_ollama())
