import logging
from typing import AsyncGenerator, Optional, List, Dict
from prompts.insight import INSIGHT_SYSTEM, INSIGHT_PROMPT_TEMPLATE, GENERAL_SYSTEM, GENERAL_PROMPT_TEMPLATE
from config import MODEL_NAME
from llm.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

class InsightAgent:
    def __init__(self, ollama_client: OllamaClient) -> None:
        self.ollama = ollama_client

    async def generate_response(
        self, 
        question: str, 
        context: str, 
        stats: str, 
        history: str, 
        training: str, 
        row_count: int = 0, 
        intent: str = "DATA_QUERY"
    ) -> AsyncGenerator[str, None]:
        """Generates a professional response based on intent."""
        
        # เลือก System Prompt ตามความเหมาะสม
        system_prompt: str = INSIGHT_SYSTEM if intent == "DATA_QUERY" else GENERAL_SYSTEM
        
        # ── Table Injection ───────────────────────────────────────────────
        # บังคับพ่นตาราง Markdown ออกไปก่อนเสมอ (กรณีเป็น Data Query และมีข้อมูล)
        # วิธีนี้ช่วยให้ User เห็นข้อมูลทันทีโดยไม่ต้องรอ AI ก๊อปปี้ตาราง (ซึ่ง 3B มักจะขี้เกียจก๊อป)
        if intent == "DATA_QUERY" and context and "|" in context:
            yield f"{context}\n\n---\n"
            # ปรับ System Prompt ไม่ให้ AI พยายามก๊อปตารางซ้ำ
            system_prompt += "\n**หมายเหตุ**: ผมได้วางตารางข้อมูลไว้ให้แล้ว คุณไม่ต้องเขียนตารางซ้ำ ให้สรุปและตอบคำถามจากตารางด้านบนได้เลย"

        # ── Fast-Path: Skip LLM for extremely simple single-row counts ────────
        # If user asks "How many" and we have 1 result, answer immediately.
        # But if they ask "Who/Which", we let the LLM handle it for better phrasing.
        if row_count == 1 and any(kw in question for kw in ["กี่ราย", "กี่สัญญา", "กี่ตัว", "จำนวนเท่าไหร่"]):
            logger.info("Fast-path: single-row count — skipping LLM")
            # Extract the count or first value carefully
            val: str = context.split(': ')[-1] if ': ' in context else context
            yield f"จากการตรวจสอบข้อมูลในระบบ พบรายการดังกล่าวจำนวน **{val}** ครับผม"
            return

        # ── Data Availability Hint ────────────────────────────────────────
        # If there's a small number of rows (e.g. <= 10), force the LLM to list EVERY name.
        if 1 <= row_count <= 10:
            question = f"(คำสั่งพิเศษ: พบข้อมูลพนักงานเพียง {row_count} คน คุณต้องระบุชื่อเล่นหรือชื่อจริงของทุกคนมาในคำตอบให้ครบถ้วน ห้ามใช้คำว่า 'รวมถึง' หรือ 'เป็นต้น') " + question
        elif row_count > 10:
             question = f"(คำสั่งพิเศษ: พบข้อมูลจำนวนมาก {row_count} รายการ ให้สรุปภาพรวมและเอ่ยชื่อตัวอย่างที่สำคัญ) " + question

        # เลือก Template ตามความเหมาะสม
        prompt: str
        if intent == "DATA_QUERY":
            prompt = INSIGHT_PROMPT_TEMPLATE.format(
                question=question,
                context=context,
                stats=stats,
                history=history,
                training=training
            )
        else:
            prompt = GENERAL_PROMPT_TEMPLATE.format(
                history=history,
                question=question
            )
        
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        try:
            async for chunk in self.ollama.chat_stream(
                messages, 
                model=MODEL_NAME, 
                tokens=2000
            ):
                yield chunk
        except Exception as e:
            logger.error("Insight generation failed: %s", e)
            yield "ขออภัยครับ ระบบเกิดข้อผิดพลาดในการสรุปผลข้อมูลเล็กน้อย แต่ข้อมูลเบื้องต้นถูกแสดงผลไว้ที่ส่วน 'ข้อมูลระบบ' แล้วครับ"
