from typing import List, Dict, Optional, Any
import os
from pathlib import Path
from pydantic_ai import Agent
from pydantic_ai.models.ollama import OllamaModel
from agent_skills import AgentSkillsToolset, SandboxExecutor, AgentSkill
from code_sandboxes import EvalSandbox
from config import MODEL_NAME, OLLAMA_BASE_URL
from core.exceptions import SkillError
import logging

logger = logging.getLogger(__name__)

class AgentService:
    _instance: Optional['AgentService'] = None
    
    def __init__(self) -> None:
        # ตั้งค่า Environment สำหรับ Ollama OpenAI Compatible
        if OLLAMA_BASE_URL:
            os.environ["OLLAMA_BASE_URL"] = OLLAMA_BASE_URL
        
        self.model = OllamaModel(model_name=MODEL_NAME)
        self.executor = SandboxExecutor(EvalSandbox())
        self.toolset = AgentSkillsToolset(directories=[], executor=self.executor)
        
        # บังคับโหลด Skills จากโฟลเดอร์โครงการ
        skills_dir: Path = Path(__file__).parent.parent / "skills"
        self._manual_load_skills(skills_dir)
        
        # สร้าง Agent
        self.agent: Agent = Agent(
            model=self.model,
            system_prompt=(
                "### ROLE:\n"
                "คุณคือ SBL Data Bot ที่ทำงานแบบไร้ความรู้สึก (Machine-only)\n\n"
                "### CORE RULES:\n"
                "1. NO CHATTING: ห้ามคุยเล่น ห้ามทักทาย ห้ามอธิบายแผนงาน\n"
                "2. CALL TOOLS IMMEDIATELY: หากผู้ใช้ถามเรื่องข้อมูล ให้เรียกใช้ `load_skill` และ `run_skill_v2` ทันที\n"
                "3. AGENT_FALLBACK: หากไม่มีเครื่องมือที่ตรงความต้องการ 100% ให้ตอบเพียงคำเดียวว่า 'AGENT_FALLBACK'\n"
                "4. NO HESITATION: ห้ามบอกให้รอ ห้ามบอกว่ากำลังหาข้อมูล\n\n"
                "### KNOWLEDGE BASE (Stat2):\n"
                "- 'A':ปกติ, 'B':เตือน1, 'C':เตือน2, 'D':เตือน3(ยกเลิก), 'F':บอกเลิก35วัน, 'G':ติดคดี, 'H':ตัดหนี้\n\n"
                "### OUTPUT FORMAT:\n"
                "- ต้องเริ่มด้วยการเรียก Tool เสมอ หากเรียก Tool ไม่ได้ต้องเป็น AGENT_FALLBACK เท่านั้น"
            )
        )
        
        # ลงทะเบียนเครื่องมือเข้ากับ Agent
        self._register_tools()

    def _manual_load_skills(self, directory: Path) -> None:
        logger.info(f"Loading skills from {directory}")
        for skill_md in directory.rglob("SKILL.md"):
            try:
                skill = AgentSkill.from_skill_md(skill_md)
                self.toolset._discovered_skills[skill.name] = skill
                logger.info(f"AgentService: Loaded skill {skill.name}")
            except Exception as e:
                logger.error(f"Failed to load skill {skill_md}: {e}")
        self.toolset._initialized = True

    def _register_tools(self) -> None:
        @self.agent.tool_plain
        def list_skills() -> str:
            """ดูรายชื่อความสามารถที่มี"""
            return self.toolset._list_skills()

        @self.agent.tool_plain
        def load_skill(skill_name: str) -> str:
            """อ่านวิธีใช้งานสกิล"""
            return self.toolset._load_skill(skill_name)

        @self.agent.tool_plain
        async def run_skill_v2(skill_name: str, search_word: str) -> str:
            """รันสกิลดึงข้อมูล (ต้อง load_skill ก่อน)"""
            # [LOG] แสดง Query ที่ AI กำลังจะใช้
            logger.info(f"🤖 [AI_QUERY] Calling skill '{skill_name}' with parameter: '{search_word}'")
            print(f">>> AI EXECUTION: {skill_name}({search_word})")
            
            try:
                result = await self.toolset._run_skill_script(
                    skill_name=skill_name,
                    script_name="script.py",
                    args=[search_word],
                    ctx=None
                )
                return f"ผลลัพธ์จากฐานข้อมูล: {result.output}"
            except Exception as e:
                logger.error(f"Skill execution error: {e}")
                raise SkillError(f"เกิดข้อผิดพลาดในการรันสกิล {skill_name}: {str(e)}")

    async def ask(self, question: str) -> str:
        """ส่งคำถามให้ Agent ประมวลผลและใช้เครื่องมืออัตโนมัติ"""
        try:
            result = await self.agent.run(question)
            return str(result.output)
        except Exception as e:
            logger.error(f"Agent.run error: {e}")
            return f"ขออภัยครับ มีปัญหาทางเทคนิคในการประมวลผล: {str(e)}"

# Singleton Instance
agent_service: AgentService = AgentService()
