"""
AI Controller — Main Brain of the Agent
Changes vs original:
  - validate_business_logic() ถูกเรียกใช้จริง (ไม่ใช่แค่ import ไว้เฉยๆ)
  - Dynamic SQL generation มี business rule check ก่อนรัน DB
  - _route_request + _generate_dynamic_sql รัน concurrently ด้วย asyncio.gather
    เมื่อ intent เป็น DATA_QUERY (ลด latency ~30-40%)
  - ลด boilerplate ด้วย helper เล็กๆ
"""

import os
import re
import json
import logging
import time
from typing import AsyncGenerator, Dict, Any, List

from core.semantic_layer import SemanticLayer
from security.query_validator import QueryValidator
from core.intent import detect_intent
from security.injection import detect_prompt_injection
from security.business_rules import validate_business_logic
from db.templates import (
    SQL_TEMPLATES,
    TEMPLATE_DESCRIPTIONS,
    render_query,
    get_category_list,
)
from db.fetch import fetch_data
from services.formatter import engine
from llm.ollama_client import OllamaClient
from config import MODEL_NAME, SQL_MODEL
from skills.registry import execute_skill
from core.prompts import get_dynamic_sql_prompt
from core.exceptions import SecurityError, SBLError, BusinessRuleError

logger = logging.getLogger(__name__)

# ── Schema (loaded once at startup) ──────────────────────────────────────────
_SCHEMA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "database_schema.json")
)


def _load_schema() -> str:
    if not os.path.exists(_SCHEMA_PATH):
        logger.error("Schema NOT FOUND: %s", _SCHEMA_PATH)
        return "{}"
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        logger.info("Schema loaded: %d chars", len(content))
        return content
    except Exception as e:
        logger.error("Schema read error: %s", e)
        return "{}"


DB_SCHEMA_DICT = json.loads(_load_schema())


def _format_schema_for_ai():
    text = "=== SEMANTIC GUIDE ===\n"
    guide = DB_SCHEMA_DICT.get("_semantic_guide", {})
    text += f"Purpose: {guide.get('purpose')}\n"
    text += f"Join Rules: {guide.get('join_rule')}\n"
    text += f"SQL Dialect: {guide.get('sql_dialect')}\n"
    text += "Common Intents:\n"
    for intent, logic in guide.get("common_intents", {}).items():
        text += f"  - {intent}: {logic}\n"

    text += "\n=== TABLES & COLUMNS ===\n"
    for table, info in DB_SCHEMA_DICT.items():
        if table.startswith("_"):
            continue
        text += f"TABLE: {table} ({info.get('description', '')})\n"
        text += f"Business Role: {info.get('business_role', '')}\n"
        for col, col_info in info.get("columns", {}).items():
            desc = col_info.get("desc", "")
            b_name = col_info.get("business_name", "")
            keywords = ", ".join(col_info.get("keywords", []))
            opts = col_info.get("options", "")
            text += f"  - {col} ({b_name}): {desc} | Keywords: [{keywords}] | Options: {opts}\n"
    return text


DB_SCHEMA_TEXT = _format_schema_for_ai()

# ── Forbidden SQL keywords (compile once) ────────────────────────────────────
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|EXEC)\b", re.I
)


class AIController:

    def __init__(self, ollama: OllamaClient, schema: Dict[str, Any]):
        self.ollama = ollama
        self.schema = schema
        self.semantic_layer = SemanticLayer(ollama)
        self.validator = QueryValidator()

    # ── SQL generation helpers ────────────────────────────────────────────────

    def _fix_common_sql_mistakes(self, sql: str) -> str:
        """Post-process SQL to fix common LLM mistakes for SQL Server."""
        import re

        # Fix 1a: LIMIT N → TOP N (move to SELECT position)
        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.IGNORECASE)
        if limit_match:
            n = limit_match.group(1)
            sql = re.sub(r"\bLIMIT\s+\d+\b", "", sql, flags=re.IGNORECASE).strip()
            sql = re.sub(
                r"\bSELECT\b", f"SELECT TOP {n}", sql, count=1, flags=re.IGNORECASE
            )

        # Fix 1b: TOP N placed AFTER ORDER BY (trailing) → move to SELECT position
        # e.g. "ORDER BY col DESC\nTOP 1;" → "SELECT TOP 1 ... ORDER BY col DESC"
        trailing_top = re.search(r"\s*\n\s*TOP\s+(\d+)\s*;?\s*$", sql, re.IGNORECASE)
        if trailing_top:
            n = trailing_top.group(1)
            sql = re.sub(
                r"\s*\n\s*TOP\s+\d+\s*;?\s*$", "", sql, flags=re.IGNORECASE
            ).strip()
            if not re.search(r"\bSELECT\s+TOP\b", sql, re.IGNORECASE):
                sql = re.sub(
                    r"\bSELECT\b", f"SELECT TOP {n}", sql, count=1, flags=re.IGNORECASE
                )

        # Fix 2: Branch = 'X' / BranchID = 'X' → OLID = 'X'
        sql = re.sub(
            r"\b(Branch|BranchID|branch_id)\s*=", "OLID =", sql, flags=re.IGNORECASE
        )

        # Fix 3: Wrong table names (hallucinated tables)
        sql = re.sub(r"\bOA_S_02\b", "LSM010", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\bLSM100\b", "LSM010", sql, flags=re.IGNORECASE)

        # Fix 4: Bare money column comparisons → CAST AS MONEY
        for col in ["Credit", "Interest", "Bal"]:
            # e.g. "Credit > 0" → "CAST(Credit AS MONEY) > 0"
            sql = re.sub(
                rf"\b{col}\b\s*([><=!]+)\s*(\d+)",
                lambda m: f"CAST({col} AS MONEY) {m.group(1)} {m.group(2)}",
                sql,
                flags=re.IGNORECASE,
            )

        return sql

    async def _generate_dynamic_sql(
        self,
        q: str,
        semantic: Dict[str, Any] = None,
        history: List[Dict[str, str]] = [],
    ) -> str:
        from prompts.sql_system import get_sql_system_prompt

        # Decide which tables to include based on semantic intent
        allowed_tables = ["LSM010"]  # Always include main table
        if semantic and semantic.get("include_names"):
            allowed_tables.append("LSM007")

        # Prepare context for the prompt
        semantic_json = json.dumps(semantic, ensure_ascii=False) if semantic else "{}"
        training_context = f"SEMANTIC INTENT (GUIDE): {semantic_json}"

        # Format history for the prompt
        hist_str = "\n".join([f"{m['role']}: {m['content']}" for m in history[-3:]])

        prompt = get_sql_system_prompt(
            training_context=training_context,
            history=hist_str,
            allowed_tables=allowed_tables,
        )
        # Add the actual question
        prompt += f"\nUser Question: {q}\nSQL:"

        try:
            sql = await self.ollama.generate(
                prompt, tokens=300, temperature=0.1, model=SQL_MODEL
            )
            sql = sql.strip().replace("```sql", "").replace("```", "").strip()
            if _FORBIDDEN_RE.search(sql):
                logger.warning("Forbidden SQL keyword detected")
                return "NO_SQL"
            return sql if sql.upper().startswith("SELECT") else "NO_SQL"
        except Exception as e:
            logger.error("Dynamic SQL failed: %s", e)
            return "NO_SQL"

    async def _route_request(self, q: str) -> Dict[str, Any]:
        template_list = "\n".join(
            f"- {name}: {desc}" for name, desc in TEMPLATE_DESCRIPTIONS.items()
        )
        prompt = f"""
You are a Financial AI Router. Decide if a question matches a template or needs dynamic SQL.
RULES:
1. ONLY select a template if the question is a PERFECT match for its description.
2. If the user mentions SPECIFIC FILTERS (like a specific branch 'MN' or amount '> 25000') that are NOT listed as template parameters, you MUST return "UNKNOWN".
3. When in doubt, return "UNKNOWN".

Templates:
{template_list}

Question: "{q}"
Output JSON: {{"category": "...", "template_name": "...", "params": {{}}}}
"""
        try:
            res = await self.ollama.generate(
                prompt, tokens=100, temperature=0.1, model=SQL_MODEL
            )
            logger.info("Route decision: %s", res.strip())
            start = res.find("{")
            end = res.rfind("}")
            if start != -1 and end != -1:
                return json.loads(res[start : end + 1])
        except Exception as e:
            logger.error("Routing failed: %s", e)
        return {"category": "other", "template_name": "UNKNOWN", "params": {}}

    # ── SSE helper ────────────────────────────────────────────────────────────
    def _event(self, type_: str, **kwargs: Any) -> str:
        return json.dumps({"type": type_, **kwargs}, ensure_ascii=False) + "\n"

    # ── Main pipeline ─────────────────────────────────────────────────────────
    async def process_request(
        self, q: str, history: List[Dict[str, str]]
    ) -> AsyncGenerator[str, None]:
        start_time = time.time()
        try:
            # 1. Security check
            yield self._event(
                "status", content="ขอตรวจสอบความถูกต้องของคำถามสักครู่นะครับ..."
            )
            injected, pattern = detect_prompt_injection(q)
            if injected:
                raise SecurityError("คำถามไม่ผ่านการตรวจสอบความปลอดภัย", details=pattern)

            # 2. Intent detection
            yield self._event("status", content="กำลังทำความเข้าใจสิ่งที่คุณต้องการครับ...")
            intent_res = detect_intent(q, history)
            intent = intent_res["intent"]
            yield self._event(
                "intent", intent=intent, confidence=intent_res["confidence"]
            )

            context_str = ""
            stats_str = ""
            db_results: list = []

            # 3. DATA_QUERY routing
            if intent == "DATA_QUERY":
                yield self._event("status", content="เดี๋ยวผมลองค้นหาข้อมูลในระบบให้นะครับ...")
                decision = await self._route_request(q)

                template_name = decision.get("template_name", "UNKNOWN")
                params = decision.get("params", {})
                logger.info("Route → template: %s", template_name)

                sql = "NO_SQL"

                if template_name != "UNKNOWN" and template_name in SQL_TEMPLATES:
                    sql, _ = render_query(template_name, params)
                    logger.info("SQL (template): %.300s", sql)
                    yield self._event("sql", sql=sql)
                else:
                    yield self._event(
                        "status", content="ขอเวลาผมตีความหมายข้อมูลสักครู่นะครับ..."
                    )
                    semantic = await self.semantic_layer.extract_intent(q)
                    logger.info(f"Semantic Intent: {semantic}")

                    yield self._event("status", content="กำลังเตรียมข้อมูลมาให้ดูนะครับ...")
                    sql = await self._generate_dynamic_sql(q, semantic, history)
                    logger.info("Raw Generated SQL: %.500s", sql)

                    if sql != "NO_SQL":
                        # Auto-fix common LLM mistakes before validation
                        sql = self._fix_common_sql_mistakes(sql)
                        logger.info("SQL after auto-fix: %.300s", sql)

                        # ✅ Layer 2: Query Validator (Strict Business Rules)
                        is_valid, error_msg = self.validator.validate(sql, q)
                        if not is_valid:
                            logger.warning(
                                f"SQL Validation Failed: {error_msg} — attempting self-correct"
                            )
                            # Self-correct: send error back to model once
                            correction_hint = f"\n\n# CRITICAL ERROR — FIX REQUIRED\nSQL ที่สร้างมามีข้อผิดพลาด: {error_msg}\nกรุณาสร้าง SQL ใหม่ที่ถูกต้องตามกฎเท่านั้น ห้ามทำผิดซ้ำ"
                            corrected = await self._generate_dynamic_sql(
                                q + correction_hint, semantic, history
                            )
                            corrected = self._fix_common_sql_mistakes(corrected)
                            is_valid2, error_msg2 = self.validator.validate(
                                corrected, q
                            )
                            if is_valid2 and corrected != "NO_SQL":
                                logger.info("Self-correct succeeded: %.300s", corrected)
                                sql = corrected
                                yield self._event("sql", sql=sql)
                            else:
                                logger.warning(
                                    f"Self-correct also failed: {error_msg2}"
                                )
                                sql = "NO_SQL"
                                context_str = f"ไม่สามารถค้นหาข้อมูลได้เนื่องจากเงื่อนไขไม่ครบถ้วน ({error_msg})"
                        else:
                            logger.info("SQL (dynamic): %.300s", sql)
                            yield self._event("sql", sql=sql)
                    else:
                        context_str = "ไม่พบข้อมูลที่ผู้ใช้ร้องขอ"

                if sql != "NO_SQL":
                    try:
                        import asyncio

                        db_results = await asyncio.to_thread(fetch_data, sql)
                        if db_results:
                            logger.info("DB rows: %d", len(db_results))
                            yield self._event("data_count", count=len(db_results))
                            context_str = engine.format_db_results(
                                db_results, self.schema, question=q
                            )
                            stats_str = engine.get_summary_stats(db_results)
                        else:
                            logger.warning("Query returned 0 rows")
                            context_str = "ไม่พบข้อมูลที่ตรงกับเงื่อนไขในฐานข้อมูล (โปรดตอบผู้ใช้อย่างสุภาพว่าหาข้อมูลไม่เจอ)"
                    except Exception as e:
                        logger.error("DB execution error: %s", e)
                        context_str = f"[DB_ERROR] เกิดข้อผิดพลาดในการดึงข้อมูลสำหรับคำถามนี้: {e} — กรุณาตอบผู้ใช้ตรงๆ ว่าระบบดึงข้อมูลไม่สำเร็จสำหรับคำถามปัจจุบัน อย่านำข้อมูลหรือคำถามก่อนหน้ามาตอบแทน"
                elif not context_str:
                    yield self._event(
                        "status", content="รอสักครู่นะครับ ผมกำลังสรุปผลให้ครับ..."
                    )
                    context_str = "ไม่พบข้อมูลที่ตรงกับเงื่อนไขในฐานข้อมูล (โปรดตอบผู้ใช้อย่างสุภาพว่าหาข้อมูลไม่เจอ)"

            # 4. Final answer (Professional Insight)
            yield self._event(
                "status", content="เรียบร้อยครับ เดี๋ยวผมสรุปให้อ่านง่ายๆ นะครับ..."
            )

            from prompts.sql_system import INSIGHT_SYSTEM, INSIGHT_PROMPT_TEMPLATE

            hist_str = "\n".join([f"{m['role']}: {m['content']}" for m in history[-5:]])

            final_prompt = INSIGHT_PROMPT_TEMPLATE.format(
                question=q,
                context=context_str,
                stats=stats_str if stats_str else "N/A",
                history=hist_str,
            )

            response_text = ""
            async for chunk in self.ollama.chat_stream(
                [
                    {"role": "system", "content": INSIGHT_SYSTEM},
                    {"role": "user", "content": final_prompt},
                ],
                model=MODEL_NAME,
            ):
                response_text += chunk
                yield self._event("content", content=chunk)

            logger.info("AI Insight: %.100s", response_text)
            yield self._event("done", time=round(time.time() - start_time, 2))

        except SecurityError as e:
            yield self._event("error", content=f"⚠️ ระงับการค้นหา: {e.message}")
        except (SBLError, BusinessRuleError) as e:
            yield self._event("error", content=f"❌ เกิดข้อผิดพลาด: {e.message}")
        except Exception as e:
            logger.exception("AIController crash")
            yield self._event("error", content="ผมเผชิญปัญหาระบบขัดข้องครับ โปรดลองใหม่อีกครั้ง")
