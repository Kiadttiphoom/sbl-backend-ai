import asyncio
import os
import sys
import logging
from pathlib import Path

# เพิ่ม Project Root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.tools import Tool
from agent_skills import AgentSkillsToolset, SandboxExecutor, AgentSkill
from code_sandboxes import EvalSandbox
from config import MODEL_NAME, OLLAMA_BASE_URL

# 1. ตั้งค่า Model
# ตรวจสอบว่า OLLAMA_BASE_URL มาจาก .env หรือส่งผ่าน env var โดยตรง
if OLLAMA_BASE_URL:
    os.environ["OLLAMA_BASE_URL"] = OLLAMA_BASE_URL

model = OllamaModel(model_name=MODEL_NAME)

# 2. เตรียมชุดเครื่องมือ (Skills)
skills_dir = Path(__file__).parent.parent / "skills"
executor = SandboxExecutor(EvalSandbox())
toolset = AgentSkillsToolset(directories=[], executor=executor)

def force_load_skills(ts: AgentSkillsToolset, directory: Path):
    for skill_md in directory.rglob("SKILL.md"):
        try:
            skill = AgentSkill.from_skill_md(skill_md)
            ts._discovered_skills[skill.name] = skill
        except Exception:
            pass
    ts._initialized = True

force_load_skills(toolset, skills_dir)

# 3. สร้าง Agent (ปรับให้เข้มงวดสุดๆ สำหรับ Model 3B)
agent = Agent(
    model=model,
    system_prompt=(
        "คุณคือระบบอัตโนมัติ ห้ามพูดคุยโต้ตอบแบบมนุษย์จนกว่าจะได้ข้อมูลจริง!\n"
        "เมื่อได้รับคำสั่ง คุณต้องเรียกใช้เครื่องมือ (Tool Call) ทันทีตามลำดับดังนี้:\n"
        "1. เรียก `load_skill` เพื่ออ่านรายละเอียดสกิลที่เกี่ยวข้อง\n"
        "2. เรียก `run_skill` เพื่อทำงานและดึงข้อมูลออกมา\n"
        "ห้ามเล่าเรื่อง ห้ามบอกว่าจะทำอะไร ให้ 'กดปุ่มเรียกเครื่องมือ' เท่านั้น!"
    )
)

# --- ลงทะเบียน Tools (แบบง่ายที่สุด) ---
@agent.tool_plain
def list_skills() -> str:
    """ดูรายชื่อความสามารถทั้งหมด"""
    return toolset._list_skills()

@agent.tool_plain
def load_skill(skill_name: str) -> str:
    """โหลดคู่มือใช้งานสกิล (ต้องทำก่อนรันทุกครั้ง)"""
    return toolset._load_skill(skill_name)

@agent.tool_plain
def run_skill(skill_name: str, args: list = []) -> str:
    """รันสกิลเพื่อดึงข้อมูลจริง (ใช้หลังจาก load_skill แล้ว)"""
    # หมายเหตุ: ลองรันแบบไม่มี ctx เพื่อลดความซับซ้อนของ Tool signature
    print(f"\n[EXECUTION] Running skill: {skill_name} with {args}...")
    try:
        # เราจำลองการสร้าง ctx เปล่าๆ หรือเรียกตรงไปที่ executor ถ้าทำได้
        # แต่เพื่อความง่าย เราจะใช้ toolset._run_skill_script แบบแอบใส่ ctx ปลอม
        # หรือถ้า Library บังคับ เราจะใช้การรันผ่าน Sandbox โดยตรง
        result = asyncio.run_coroutine_threadsafe(
            toolset._run_skill_script(skill_name, "script.py", args=args, ctx=None),
            asyncio.get_event_loop()
        ).result()
        print(f"[RESULT] {result.output}")
        return str(result.output)
    except Exception as e:
        return f"Error: {str(e)}"

# ปรับปรุง run_skill ให้เป็น async และใช้ง่ายขึ้น
@agent.tool_plain
async def run_skill_v2(skill_name: str, search_word: str) -> str:
    """ใช้สำหรับค้นหาข้อมูลพนักงานหรือรายงาน (ใส่คำค้นหาใน search_word)"""
    print(f"\n🚀 กำลังค้นหาข้อมูล: {skill_name} -> {search_word}")
    try:
        # เรียกใช้สคริปต์จริง
        result = await toolset._run_skill_script(
            skill_name=skill_name, 
            script_name="script.py", 
            args=[search_word], 
            ctx=None # ลองส่ง None ดูว่า Library ยอมไหม
        )
        return f"ข้อมูลที่พบ: {result.output}"
    except Exception as e:
        return f"ไม่พบข้อมูลหรือเกิดข้อผิดพลาด: {str(e)}"

async def main():
    # บังคับขั้นตอนให้ชัดเจนในคำถามเดียว
    question = "ใช้สกิล search-data ค้นหาพนักงานชื่อ 'สมชาย' และสรุปผลมาให้หน่อย"
    
    print(f"User: {question}")
    print("AI is thinking (Running multi-turn tool calling)...")
    
    try:
        # ใช้ run_sync หรือจัดการ loop ให้ดี
        result = await agent.run(question)
        print("\n" + "="*40)
        print("💡 บทสรุปจาก AI:")
        print("-" * 40)
        print(result.output)
        print("="*40)
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
