import logging
from prompts.insight import INSIGHT_SYSTEM, INSIGHT_PROMPT_TEMPLATE, GENERAL_SYSTEM
from config import MODEL_NAME

logger = logging.getLogger(__name__)

class InsightAgent:
    def __init__(self, ollama_client):
        self.ollama = ollama_client

    async def generate_response(self, question, context, stats, history, training, row_count=0, intent="DATA_QUERY"):
        """Generates a professional response based on intent."""
        
        # เลือก System Prompt ตามความเหมาะสม
        system_prompt = INSIGHT_SYSTEM if intent == "DATA_QUERY" else GENERAL_SYSTEM
        
        # ── Fast-Path: Skip LLM for extremely simple single-row counts ────────
        # If user asks "How many" and we have 1 result, answer immediately.
        # But if they ask "Who/Which", we let the LLM handle it for better phrasing.
        if row_count == 1 and any(kw in question for kw in ["กี่ราย", "กี่สัญญา", "กี่ตัว", "จำนวนเท่าไหร่"]):
            logger.info("Fast-path: single-row count — skipping LLM")
            # Extract the count or first value carefully
            val = context.split(': ')[-1] if ': ' in context else context
            yield f"จากการตรวจสอบข้อมูลในระบบ พบรายการดังกล่าวจำนวน **{val}** ครับผม"
            return

        # ── Data Availability Hint ────────────────────────────────────────
        # If there's exactly 1 row, instruct the LLM that this is the ONLY (and thus 'most') result.
        if row_count == 1:
            question = f"(หมายเหตุ: พบข้อมูลพนักงานเพียงคนเดียว ให้ตอบคนนี้ทันที) " + question

        # ── Standard Path: Full LLM reasoning ──────────────────────────────
        prompt = INSIGHT_PROMPT_TEMPLATE.format(
            question=question,
            context=context,
            stats=stats,
            history=history,
            training=training
        )
        
        messages = [
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
