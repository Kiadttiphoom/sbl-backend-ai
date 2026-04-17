import time
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://192.168.2.18:11434")
SQL_MODEL = os.getenv("SQL_MODEL", "qwen2.5-coder:3b")

async def test_latency(prompt, label):
    print(f"\n--- Testing: {label} ---")
    start = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(
                f"{OLLAMA_HOST}/api/generate",
                json={
                    "model": SQL_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 50}
                }
            )
            data = response.json()
            end = time.time()
            total_time = end - start
            tokens = data.get("eval_count", 0)
            tps = tokens / data.get("eval_duration", 1) * 1e9 if data.get("eval_duration") else 0
            
            print(f"Total Time: {total_time:.2f}s")
            print(f"Tokens Generated: {tokens}")
            print(f"Tokens Per Second: {tps:.2f}")
            print(f"Response: {data.get('response', '')[:50]}...")
        except Exception as e:
            print(f"Error: {e}")

async def main():
    # 1. Very Short Prompt
    await test_latency("Say hello in Thai", "Short Prompt (Hello)")
    
    # 2. Medium Prompt (Simulated System Rules)
    medium_prompt = "Rule 1: Be polite. Rule 2: Use Thai. Rule 3: Start with SELECT. " * 10
    await test_latency(medium_prompt + "How are you?", "Medium Prompt (Rules)")

    # 3. Large Prompt (Simulated Schema - approx 2000 tokens)
    large_prompt = "Column: " + "A" * 100 + " Description: This is a column. " * 50
    await test_latency(large_prompt + "Generate SQL SELECT *", "Large Prompt (Simulated Schema)")

if __name__ == "__main__":
    asyncio.run(main())
