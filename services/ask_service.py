import time
import asyncio
import re
import json
import logging
from security.injection import detect_prompt_injection
from security.sql_guard import guard, sanitize_sql_values
from security.business_rules import validate_business_logic
from schema.builder import get_relevant_schema
from prompts.sql_system import SQL_SYSTEM
from core.memory import get_sql_training_context, get_insight_training_context
from db.fetch import fetch_data
from analysis.engine import engine
from core.intent import detect_intent
from config import SQL_MODEL

logger = logging.getLogger(__name__)

class AskService:
    def __init__(self, ollama_client, insight_agent, schema):
        self.ollama = ollama_client
        self.insight_agent = insight_agent
        self.schema = schema

    async def process_ask(self, q, history):
        """Orchestrates the full flow: Security -> Intent -> SQL -> Fetch -> Insight."""
        start = time.time()

        # Helper to generate events
        def _event(type_, **kwargs):
            return json.dumps({"type": type_, **kwargs}, ensure_ascii=False) + "\n"

        # ── Step 1: Security ──────────────────────────────────────────────
        yield _event("status", content="กำลังตรวจสอบความปลอดภัย...")
        injected, pattern = detect_prompt_injection(q)
        if injected:
            logger.warning("Prompt injection detected: '%s'", pattern)
            yield _event("error", content="คำถามไม่ผ่านการตรวจสอบความปลอดภัย")
            return

        # ── Step 2: Intent Detection ──────────────────────────────────────
        yield _event("status", content="กำลังวิเคราะห์คำถาม...")
        res = detect_intent(q, history)
        intent, confidence = res["intent"], res["confidence"]

        logger.info("INTENT DETECTION: intent=%s, confidence=%s, matched=%s, question='%s'",
                    intent, confidence, res.get("matched", []), q)
        yield _event("intent", intent=intent, confidence=confidence)

        # ── Preparation ──────────────────────────────────────────────────
        # Structured Context Extraction (Follow-up logic)
        structured_context = self._extract_structured_context(history)
        hist_str = "\n".join([f"- {m['role']}: {m['content'][:100]}" for m in history[-5:]]) if history else "ไม่มีประวัติการสนทนา"
        if structured_context:
            hist_str = f"[LAST_ENTITIES]: {structured_context}\n" + hist_str

        db_results = []
        formatted_context = ""
        stats_context = ""

        # ── Step 3: SQL Generation & Guarding ─────────────────────────────
        if intent == "DATA_QUERY":
            try:
                yield _event("status", content="กำลังสร้างคำสั่ง SQL...")
                
                schema_text = get_relevant_schema(q, self.schema)
                training_context = get_sql_training_context(q)
                
                prompt = SQL_SYSTEM.format(
                    schema_text=schema_text, 
                    training_context=training_context,
                    history=hist_str
                )
                
                sql_raw = ""
                # Optimized stop condition to prevent waiting for redundant tokens
                async for chunk in self.ollama.stream(prompt, model=SQL_MODEL, tokens=500, stop=["###", "Output:", "```\n"]):
                    sql_raw += chunk
                    if "```" in sql_raw and sql_raw.count("```") >= 2:
                        break

                logger.info("SQL_RAW_OUTPUT:\n%s", sql_raw)
                
                m = re.search(r"```sql(.*?)```", sql_raw, re.S)
                sql = m.group(1).strip() if m else sql_raw.strip()
                sql = guard.sanitize(sql)
                
                logger.info("SQL_SANITIZED:\n%s", sql)

                if sql.upper() == "NONE":
                    logger.info("SQL_RESULT: No query (NONE)")
                    yield _event("info", content="ไม่พบข้อมูลที่ตรงกับคำถามในระบบ")
                else:
                    # SAFETY CHECKS
                    safe, reason = guard.validate(sql)
                    if not safe:
                        yield _event("warning", content=f"คำสั่ง SQL ไม่ผ่านการตรวจสอบ: {reason}")
                    else:
                        biz_safe, biz_reason = validate_business_logic(q, sql)
                        if not biz_safe:
                            yield _event("warning", content=f"ตรวจพบความผิดพลาดตรรกะ: {biz_reason}")
                        else:
                            val_safe, val_reason = sanitize_sql_values(sql)
                            if not val_safe:
                                yield _event("warning", content="ตรวจพบค่าที่ไม่ปลอดภัยใน SQL")
                            else:
                                yield _event("sql", sql=sql)
                                try:
                                    db_results = await asyncio.to_thread(fetch_data, sql)
                                    if db_results:
                                        yield _event("data_count", count=len(db_results))
                                        formatted_context = engine.format_db_results(db_results, self.schema, question=q)
                                        stats_context = engine.get_summary_stats(db_results)
                                    else:
                                        yield _event("info", content="ไม่พบข้อมูลตามเงื่อนไข")
                                except Exception as e:
                                    logger.error("DB_FETCH_ERROR: %s", e)
                                    yield _event("warning", content="เกิดข้อผิดพลาดในการดึงข้อมูล")

            except Exception as e:
                logger.error("LLM SQL error: %s", e)
                yield _event("error", content="ระบบ AI ขัดข้องชั่วคราว")
                return

        # ── Step 4: Insight Generation ────────────────────────────────────
        try:
            yield _event("status", content="กำลังเรียบเรียงคำตอบ...")
            if intent == "GENERAL":
                formatted_context = "(การสนทนาทั่วไป)"
            elif not formatted_context:
                formatted_context = "ไม่พบข้อมูลที่เกี่ยวข้อง"

            # ── Optimized Insight Path (Turbo v2) ──
            # ขยายความจำเพิ่มเป็น 5 ข้อความล่าสุด (ตามคำแนะนำของ AI เพื่อนบ้าน)
            # เพื่อให้จำบริบทการคุยได้ดีขึ้น แต่ยังวิ่งไวอยู่ครับ
            hist_brief = "\n".join([f"- {m['role']}: {m['content'][:100]}" for m in history[-5:]]) if history else ""

            response_tokens = []
            async for token in self.insight_agent.generate_response(
                q, formatted_context, stats_context, hist_brief, "",
                row_count=len(db_results), intent=intent
            ):
                response_tokens.append(token)
                yield _event("content", content=token)
            
            logger.info("INSIGHT_OUTPUT: len=%d", len(response_tokens))

        except Exception as e:
            logger.error("INSIGHT_ERROR: %s", e)
            yield _event("error", content="ระบบ AI ไม่สามารถตอบได้ในขณะนี้")
            return

        yield _event("done", time=round(time.time() - start, 2))

    def _extract_structured_context(self, history) -> str:
        """
        วิเคราะห์ประวัติการสนทนาเพื่อหา Entity ล่าสุด เช่น FolID หรือ Stat2 
        เพื่อให้ AI สามารถตอบคำถามต่อเนื่องได้แม่นยำ
        """
        if not history: return ""
        
        entities = {}
        # วนลูบย้อนหลัง 3 ข้อความ
        for m in reversed(history[-3:]):
            content = m.get("content", "")
            # หา Staff ID / FolID (ตัวเลข 1-4 หลัก)
            fol_match = re.search(r"รหัสพนักงาน[:\s]*(\d{1,4})", content)
            if fol_match and "FolID" not in entities:
                entities["FolID"] = fol_match.group(1)
            
            # หาสถานะ (A, B, C, D, F)
            stat_match = re.search(r"สถานะ[:\s]*([ABCDEF])\b", content)
            if stat_match and "Stat2" not in entities:
                entities["Stat2"] = stat_match.group(1)
        
        if not entities: return ""
        return ", ".join([f"{k}={v}" for k, v in entities.items()])