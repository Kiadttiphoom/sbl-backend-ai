import time
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
        is_obvious_query = any(w in q for w in ["ข้อมูล", "ยอดหนี้", "สัญญา", "เลขที่", "กี่บาท", "เท่าไหร่", "รหัส"])
        
        if is_obvious_query:
            intent, confidence = "DATA_QUERY", "high"
        else:
            res = detect_intent(q)
            intent, confidence = res["intent"], res["confidence"]

        logger.info("INTENT DETECTION: intent=%s, confidence=%s, question='%s'", intent, confidence, q)
        yield _event("intent", intent=intent, confidence=confidence)

        # ── Preparation ──────────────────────────────────────────────────
        hist_str = "\n".join([f"- {m['role']}: {m['content'][:100]}" for m in history[-5:]]) if history else "ไม่มีประวัติการสนทนา"

        db_results = []
        formatted_context = ""
        stats_context = ""

        # ── Step 3: SQL Generation & Guarding ─────────────────────────────
        if intent == "DATA_QUERY":
            try:
                yield _event("status", content="กำลังสร้างคำสั่ง SQL...")
                
                schema_text = get_relevant_schema(q, self.schema)
                training_context = get_sql_training_context(q)
                
                logger.debug("SCHEMA_RETRIEVED:\n%s", schema_text[:500])
                logger.debug("TRAINING_EXAMPLES:\n%s", training_context[:300])
                
                prompt = SQL_SYSTEM.format(
                    schema_text=schema_text, 
                    training_context=training_context,
                    history=hist_str
                )
                logger.debug("FULL_PROMPT_SENT_TO_LLM:\n%s", prompt[:800])
                
                sql_raw = ""
                async for chunk in self.ollama.stream(prompt, model=SQL_MODEL, tokens=500, stop=["###", "Output:"]):
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
                    logger.info("SQL_GUARD_VALIDATE: safe=%s, reason=%s", safe, reason)
                    if not safe:
                        yield _event("warning", content=f"คำสั่ง SQL ไม่ผ่านการตรวจสอบ: {reason}")
                    else:
                        # BUSINESS LOGIC CHECK
                        biz_safe, biz_reason = validate_business_logic(q, sql)
                        logger.info("SQL_BUSINESS_LOGIC: safe=%s, reason=%s", biz_safe, biz_reason)
                        if not biz_safe:
                            yield _event("warning", content=f"ตรวจพบความผิดพลาดตรรกะ: {biz_reason}")
                        else:
                            val_safe, val_reason = sanitize_sql_values(sql)
                            logger.info("SQL_VALUE_SANITIZE: safe=%s, reason=%s", val_safe, val_reason)
                            if not val_safe:
                                yield _event("warning", content="ตรวจพบค่าที่ไม่ปลอดภัยใน SQL")
                            else:
                                yield _event("sql", sql=sql)
                                try:
                                    yield _event("status", content="กำลังดึงข้อมูล...")
                                    logger.info("FETCHING_DATA: sql='%s'", sql[:200])
                                    db_results = fetch_data(sql)
                                    logger.info("FETCH_SUCCESS: rows=%d", len(db_results) if db_results else 0)
                                    if db_results:
                                        yield _event("data_count", count=len(db_results))
                                        yield _event("status", content="กำลังวิเคราะห์ข้อมูล...")
                                        formatted_context = engine.format_db_results(db_results, self.schema, question=q)
                                        stats_context = engine.get_summary_stats(db_results)
                                        logger.info("FORMAT_DB_RESULTS: context='%s'", formatted_context[:300])
                                        logger.info("SUMMARY_STATS: stats='%s'", stats_context)
                                    else:
                                        logger.info("NO_RESULTS: SQL executed but no data returned")
                                        yield _event("info", content="ไม่พบข้อมูลตามเงื่อนไข")
                                except Exception as e:
                                    logger.error("DB_FETCH_ERROR: %s | Stack:", e, exc_info=True)
                                    logger.error("DB error: %s", e)
                                    yield _event("warning", content="เกิดข้อผิดพลาดในการดึงข้อมูล")

            except Exception as e:
                logger.error("LLM SQL error: %s", e)
                yield _event("error", content="ระบบ AI ขัดข้องชั่วคราว")
                return

        # ── Step 4: Insight Generation ────────────────────────────────────
        try:
            yield _event("status", content="กำลังเรียบเรียงคำตอบ...")
            logger.info("INSIGHT_GENERATION: intent=%s, data_rows=%d, formatted_context_len=%d", intent, len(db_results), len(formatted_context) if formatted_context else 0)
            if intent == "GENERAL":
                formatted_context = "(การสนทนาทั่วไป)"
            elif not formatted_context:
                formatted_context = "ไม่พบข้อมูลที่เกี่ยวข้อง"

            # History formatting (Using synchronized hist_str from above)
            insight_training = get_insight_training_context(q)
            
            logger.info("INSIGHT_INPUT: context='%s...' | stats='%s' | training_len=%d | row_count=%d", 
                       formatted_context[:150], stats_context[:100], len(insight_training), len(db_results))

            response_tokens = []
            async for token in self.insight_agent.generate_response(
                q, formatted_context, stats_context, hist_str, insight_training,
                row_count=len(db_results)
            ):
                response_tokens.append(token)
                yield _event("content", content=token)
            
            logger.info("INSIGHT_OUTPUT: total_tokens=%d, response='%s'", len(response_tokens), ''.join(response_tokens)[:200])

        except Exception as e:
            logger.error("INSIGHT_ERROR: %s | Stack:", e, exc_info=True)
            yield _event("error", content="ระบบ AI ไม่สามารถตอบได้ในขณะนี้")
            return

        yield _event("done", time=round(time.time() - start, 2))
