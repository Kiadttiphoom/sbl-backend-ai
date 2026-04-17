import asyncio
from llm_client import OllamaClient
from prompt_builder import build_prompt
from config import MODEL_NAME

async def run():
    client = OllamaClient()
    
    # Modified rules
    ANSWER_SYSTEM = """
    # บทบาท (Role)
    คุณคือเจ้าหน้าที่ฝ่ายข้อมูลของ SBL (ผู้ชาย) สุภาพ มั่นใจ และเป็นมืออาชีพ

    # กฎเหล็ก (Mandatory Rules)
    1. **ภาษาไทยเท่านั้น (ONLY THAI)**: ตอบเป็นภาษาไทยที่สุภาพเท่านั้น 
    2. **ตัวตน (Persona)**: แทนตัวเองว่า "ผม" และลงท้ายด้วย "ครับ" เสมอ
    3. **ความถูกต้อง (Strict Accuracy)**: ข้อมูลใน [DATABASE_CONTEXT] คือผลลัพธ์ที่ถูกต้องและตรงกับเงื่อนไขทุกอย่างที่ผู้ใช้ถามมาแล้ว! ให้นำข้อมูลทั้งหมด (เช่น ชื่อ, ตัวเลข) ไปสรุปให้ผู้ใช้ฟังได้เลยทันที ห้ามปฏิเสธว่าไม่มีข้อมูลหากในวงเล็บมีข้อความอยู่
    """
    
    q = "พนักงานคนไหนปล่อยให้ลูกค้าค้างจ่ายเกิน 3 เดือนเยอะที่สุด ขอชื่อตัวท็อปคนนั้นพร้อมจำนวนสัญญาที่ถืออยู่"
    formatted_data = """  - รหัสผู้จัด/ผู้ยึด (พนักงานที่ดูแล): 373\n  - ชื่อผู้ยึด: นางสาวพรศิริ  เดชภักดี\n  - TotalContracts: 5"""
    context_wrapper = f"[DATABASE_CONTEXT]\n(ผลลัพธ์:\n{formatted_data}\n)\n"
    
    final_prompt = build_prompt(ANSWER_SYSTEM, f"{context_wrapper}\n\n[USER_QUESTION]\n{q}")
    
    print("Generating...")
    async for t in client.stream(final_prompt, model=MODEL_NAME, stop=["###"]):
        print(t, end="", flush=True)
    print()

if __name__ == "__main__":
    asyncio.run(run())
