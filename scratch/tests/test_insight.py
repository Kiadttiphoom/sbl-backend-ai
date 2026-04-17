import asyncio
import json
from config import MODEL_NAME
from llm_client import OllamaClient
from insight_agent import InsightAgent

async def run():
    client = OllamaClient()
    agent = InsightAgent(client)
    
    q = "พนักงานคนไหนปล่อยให้ลูกค้าค้างจ่ายเกิน 3 เดือนเยอะที่สุด ขอชื่อตัวท็อปคนนั้นพร้อมจำนวนสัญญาที่ถืออยู่"
    formatted_data = """  - รหัสผู้จัด/ผู้ยึด (พนักงานที่ดูแล): 373
  - ชื่อผู้ยึด: นางสาวพรศิริ  เดชภักดี
  - TotalContracts: 5"""
    
    print("Generating...")
    async for t in agent.generate_response(q, formatted_data):
        print(t, end="", flush=True)
    print()

if __name__ == "__main__":
    asyncio.run(run())
