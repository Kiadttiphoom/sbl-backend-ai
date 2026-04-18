import time
import asyncio
import re
import json
import logging
from typing import List, Dict, Any, AsyncGenerator, Optional, Tuple

from security.injection import detect_prompt_injection
from security.sql_guard import guard, sanitize_sql_values
from security.business_rules import validate_business_logic
from schema.builder import get_relevant_schema
from prompts.sql_system import SQL_SYSTEM
from core.memory import get_sql_training_context
from db.fetch import fetch_data
from analysis.engine import engine
from core.intent import detect_intent
from config import SQL_MODEL
from services.agent_service import agent_service
from core.exceptions import SecurityError, LLMError, DatabaseError, SBLError

logger = logging.getLogger(__name__)

class AskService:
    """
    Service หลักสำหรับจัดการ Flow ทั้งหมดของ AI Agent:
    Security -> Intent -> (Smart Agent / SQL Pipeline) -> Insight
    """

    def __init__(self, ollama_client: Any, insight_agent: Any, schema: Dict[str, Any]) -> None:
        self.ollama = ollama_client
        self.insight_agent = insight_agent
        self.schema = schema

    async def process_ask(self, q: str, history: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """
        Orchestration flow ของการตอบคำถามแบบ Streaming
        """
        start_time: float = time.time()

        try:
            # [LOG] รับข้อความจาก User
            logger.info(f"📥 [RECEIVE] User Query: '{q}'")

            # ── 1. Security Check ──────────────────────────────────────────
            yield self._event("status", content="กำลังตรวจสอบความปลอดภัย...")
            self._verify_security(q)

            # ── 2. Intent Detection ──────────────────────────────────────
            yield self._event("status", content="กำลังวิเคราะห์ความต้องการ...")
            intent_res = detect_intent(q, history)
            intent: str = intent_res["intent"]
            yield self._event("intent", intent=intent, confidence=intent_res["confidence"])

            # ── 3. Processing (Agent or SQL) ─────────────────────────────
            formatted_context: str = ""
            stats_context: str = ""
            db_results: List[Dict[str, Any]] = []

            if intent == "DATA_QUERY":
                # ลองใช้ Smart Agent เป็นอันดับแรก
                yield self._event("status", content="กำลังวิเคราะห์ข้อมูล...")
                try:
                    agent_res = await agent_service.ask(q)
                    
                    # [LOG] แสดงสิ่งที่ Agent ตอบกลับมา
                    logger.info(f"🤖 [AGENT_REPLY]: {agent_res[:100]}...")

                    # ตรวจสอบว่า Agent ปฏิเสธการทำงาน หรือขาน Fallback หรือเริ่มบ่นประวิงเวลาหรือไม่
                    hesitation_keywords = ["รอสักครู่", "ดึงข้อมูล", "หาความสามารถ", "กำลัง", "ใช้วลา"]
                    is_fallback = (
                        "AGENT_FALLBACK" in agent_res or
                        any(phrase in agent_res for phrase in ["ขออภัย", "ไม่มีสกิล", "ไม่สามารถ"]) or
                        (len(agent_res) > 150 and any(kw in agent_res for kw in hesitation_keywords)) # บ่นยาวและมีคำประวิงเวลา
                    )

                    if is_fallback:
                        logger.info(f"⚠️ [FALLBACK_TRIGGERED] Agent hesitated or rejected. Switching to SQL Pipeline...")
                        yield self._event("status", content="กำลังตรวจสอบรายละเอียดเชิงลึกเพื่อความแม่นยำ...")
                        
                        # วิ่งเข้า Legacy SQL Generation ทันที
                        sql_res = await self._handle_sql_generation(q, history)
                        if sql_res:
                            sql, db_results = sql_res
                            yield self._event("sql", sql=sql)
                            if db_results:
                                yield self._event("data_count", count=len(db_results))
                                formatted_context = engine.format_db_results(db_results, self.schema, question=q)
                                stats_context = engine.get_summary_stats(db_results)
                    else:
                        yield self._event("content", content=agent_res)
                        yield self._event("done", time=round(time.time() - start_time, 2))
                        return
                except SBLError as e:
                    logger.warning(f"Smart Agent error, falling back: {e.message}")
                    yield self._event("status", content="กำลังประมวลผลข้อมูลรายงาน...")
                    
                    sql_res = await self._handle_sql_generation(q, history)
                    if sql_res:
                        sql, db_results = sql_res
                        yield self._event("sql", sql=sql)
                        if db_results:
                            yield self._event("data_count", count=len(db_results))
                            formatted_context = engine.format_db_results(db_results, self.schema, question=q)
                            stats_context = engine.get_summary_stats(db_results)

            # ── 4. Insight Generation ────────────────────────────────────
            yield self._event("status", content="กำลังสรุปคำตอบ...")
            async for token in self._generate_insight(q, intent, history, db_results, formatted_context, stats_context):
                yield self._event("content", content=token)

            yield self._event("done", time=round(time.time() - start_time, 2))

        except SecurityError as e:
            yield self._event("error", content=f"⚠️ {e.message}")
        except SBLError as e:
            yield self._event("error", content=f"❌ {e.message}")
        except Exception as e:
            logger.error(f"Unexpected error in AskService: {e}")
            yield self._event("error", content="ขออภัยครับ ระบบขัดข้องชั่วคราว")

    # ── Internal Helpers ──────────────────────────────────────────────────

    def _event(self, type_: str, **kwargs: Any) -> str:
        """Helper สำหรับสร้าง JSON event string"""
        return json.dumps({"type": type_, **kwargs}, ensure_ascii=False) + "\n"

    def _verify_security(self, q: str) -> None:
        """ตรวจสอบความปลอดภัยของคำถาม"""
        injected, pattern = detect_prompt_injection(q)
        if injected:
            logger.warning(f"Injection detected: {pattern}")
            raise SecurityError("คำถามไม่ผ่านการตรวจสอบความปลอดภัย", details=pattern)

    async def _handle_sql_generation(self, q: str, history: List[Dict[str, str]]) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        """จัดการการสร้าง SQL และดึงข้อมูล (Legacy Path)"""
        # (ย้าย Logic เดิมมาไว้ที่นี่เพื่อความสะอาด)
        schema_text = get_relevant_schema(q, self.schema)
        training_context = get_sql_training_context(q)
        hist_str = self._format_history(history)
        
        prompt = SQL_SYSTEM.format(schema_text=schema_text, training_context=training_context, history=hist_str)
        
        sql_raw = ""
        async for chunk in self.ollama.stream(prompt, model=SQL_MODEL, tokens=500, stop=["###", "Output:"]):
            sql_raw += chunk
            if sql_raw.count("```") >= 2: break

        m = re.search(r"```sql(.*?)```", sql_raw, re.S)
        sql = m.group(1).strip() if m else sql_raw.strip()
        sql = guard.sanitize(sql)

        # [LOG] แสดง SQL ที่สร้างได้
        logger.info(f"📝 [SQL_GENERATED] Pipeline created SQL: {sql}")

        if sql.upper() == "NONE": return None

        # Validation
        safe, reason = guard.validate(sql)
        if not safe: raise SecurityError(f"SQL ไม่ปลอดภัย: {reason}")
        
        biz_safe, biz_reason = validate_business_logic(q, sql)
        if not biz_safe: raise SBLError(f"ตรรกะธุรกิจผิดพลาด: {biz_reason}")

        try:
            results = await asyncio.to_thread(fetch_data, sql)
            return sql, results
        except Exception as e:
            raise DatabaseError("ค้นหาข้อมูลล้มเหลว", details=str(e))

    async def _generate_insight(self, q: str, intent: str, history: List[Dict[str, str]], 
                               db_results: List[Dict[str, Any]], context: str, stats: str) -> AsyncGenerator[str, None]:
        """เรียกใช้ Insight Agent เพื่อสรุปคำตอบ"""
        hist_brief = self._format_history(history)
        
        if intent == "GENERAL":
            context = "(คุยทั่วไป)"
        elif not context:
            context = "ไม่พบข้อมูลที่เกี่ยวข้อง"

        full_response = ""
        async for token in self.insight_agent.generate_response(
            q, context, stats, hist_brief, "", row_count=len(db_results), intent=intent
        ):
            full_response += token
            yield token

        # [LOG] แสดงสิ่งที่ AI ตอบกลับผู้ใช้
        logger.info(f"📤 [RESPOND] AI Response: {full_response[:100]}...")

    def _format_history(self, history: List[Dict[str, str]]) -> str:
        """จัดรูปแบบประวัติการสนทนาให้สั้นลง"""
        if not history: return ""
        return "\n".join([f"- {m['role']}: {m['content'][:100]}" for m in history[-5:]])