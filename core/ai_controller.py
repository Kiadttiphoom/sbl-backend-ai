"""
AI Controller — Main Brain of the Agent
────────────────────────────────────────
Refactor v2 (stateful + lean pipeline):

  CHANGES vs v1:
  1. ตัด _route_request() (LLM router) ออก — fast_route ครอบทุก template แล้ว
  2. ตัด semantic_layer.extract_intent() LLM call ออก — เปลี่ยนเป็น pure Python
  3. เพิ่ม stateful SQL context:
       - เก็บ last_sql, last_db ไว้ใน session (ส่งมาจาก history พิเศษ)
       - _try_followup_sql() แปลง last_sql → TOP N / filter ใหม่ ไม่ต้อง gen SQL ใหม่
  4. worst-case LLM calls: 2 (SQL gen + Thai answer) แทน 3-4 เดิม
"""

import os
import re
import json
import logging
import time
import asyncio
from typing import AsyncGenerator, Dict, Any, List, Optional, Tuple

from core.semantic_layer import SemanticLayer
from security.query_validator import QueryValidator
from core.intent import detect_intent
from security.injection import detect_prompt_injection
from security.business_rules import validate_business_logic
from db.templates import (
    SQL_TEMPLATES,
    TEMPLATE_DESCRIPTIONS,
    TEMPLATE_EXAMPLES,
    TEMPLATE_CATEGORIES,
    render_query,
    get_category_list,
    get_template_db,
)
from db.fetch import fetch_data
from services.formatter import engine
from llm.ollama_client import OllamaClient
from config import MODEL_NAME, SQL_MODEL
from core.prompts import get_dynamic_sql_prompt
from core.exceptions import SecurityError, SBLError, BusinessRuleError, LLMError

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


_DB_SCHEMA_DICT = json.loads(_load_schema())
_DB_SCHEMA_TEXT_CACHE: Optional[str] = None


def _get_schema_text():
    global _DB_SCHEMA_TEXT_CACHE
    if _DB_SCHEMA_TEXT_CACHE:
        return _DB_SCHEMA_TEXT_CACHE

    text = "=== SEMANTIC GUIDE ===\n"
    guide = _DB_SCHEMA_DICT.get("_semantic_guide", {})
    text += f"Purpose: {guide.get('purpose')}\n"
    text += f"Join Rules: {guide.get('join_rule')}\n"
    text += f"SQL Dialect: {guide.get('sql_dialect')}\n"
    text += "Common Intents:\n"
    for intent, logic in guide.get("common_intents", {}).items():
        text += f"  - {intent}: {logic}\n"

    text += "\n=== TABLES & COLUMNS ===\n"
    for table, info in _DB_SCHEMA_DICT.items():
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

    _DB_SCHEMA_TEXT_CACHE = text
    return text


# ── Forbidden SQL keywords (compile once) ────────────────────────────────────
_FORBIDDEN_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|ALTER|CREATE|EXEC)\b", re.I
)

# ── Follow-up patterns (stateful SQL reuse) ───────────────────────────────────
_TOP_N_RE       = re.compile(r"(\d+)\s*(?:รายการ(?:แรก)?|อันดับ|ราย(?:แรก)?|top)", re.IGNORECASE)
_TOP_WORD_RE    = re.compile(r"top\s+(\d+)", re.IGNORECASE)
_FOLLOWUP_LIMIT = re.compile(r"^(ขอ|แสดง|เอา|ดู|top)?\s*(\d+)\s*(รายการ|อันดับ|ราย|แรก|สุดท้าย)?$", re.IGNORECASE)

# คำที่บ่งชี้ว่าต้องการดูข้อมูลชุดเดิมแต่จำกัดจำนวน
_LIMIT_PHRASES = [
    "รายการแรก", "อันดับแรก", "ขอดู", "top ", "แค่", "เพียง",
    "5 ราย", "10 ราย", "3 ราย", "ขอ 5", "ขอ 10", "ขอ 3",
]


class AIController:

    def __init__(self, ollama: OllamaClient, schema: Dict[str, Any]):
        self.ollama = ollama
        self.schema = schema
        self.semantic_layer = SemanticLayer(ollama)
        self.validator = QueryValidator()

    # ── SQL generation helpers ────────────────────────────────────────────────
    def _fix_common_sql_mistakes(self, sql: str) -> str:
        """Post-process SQL to fix common LLM mistakes for SQL Server 2008."""

        # 1. Handle LIMIT -> TOP transformation
        limit_match = re.search(r"\bLIMIT\s+(\d+)\b", sql, re.IGNORECASE)
        if limit_match:
            n = int(limit_match.group(1))
            if n > 20: n = 20  # Max 20
            sql = re.sub(r"\bLIMIT\s+\d+\b", "", sql, flags=re.IGNORECASE).strip()
            if not re.search(r"\bSELECT\s+TOP\b", sql, re.IGNORECASE):
                sql = re.sub(r"\bSELECT\b", f"SELECT TOP {n}", sql, count=1, flags=re.IGNORECASE)

        # 2. Enforce MAX 20 on existing TOP
        top_match = re.search(r"\bSELECT\s+TOP\s+(\d+)\b", sql, re.IGNORECASE)
        if top_match:
            n = int(top_match.group(1))
            if n > 20:
                sql = re.sub(r"\bSELECT\s+TOP\s+\d+\b", f"SELECT TOP 20", sql, count=1, flags=re.IGNORECASE)
        
        # 3. Add default TOP 10 if it's a listing query (no aggregations) and no TOP set
        is_agg = re.search(r"\b(COUNT|SUM|AVG|MIN|MAX)\b", sql, re.IGNORECASE)
        has_top = re.search(r"\bSELECT\s+TOP\b", sql, re.IGNORECASE)
        if not is_agg and not has_top and sql.upper().startswith("SELECT"):
            sql = re.sub(r"\bSELECT\b", "SELECT TOP 10", sql, count=1, flags=re.IGNORECASE)

        # 4. Correct common hallucinations & DB-specific fixes
        sql = re.sub(r"\b(Branch|BranchID|branch_id)\s*=", "OLID =", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\bOA_S_02\b", "LSM010", sql, flags=re.IGNORECASE)
        sql = re.sub(r"\bLSM100\b", "LSM010", sql, flags=re.IGNORECASE)

        for col in ["Credit", "Interest", "Bal"]:
            sql = re.sub(
                rf"\b{col}\b\s*([><=!]+)\s*(\d+)",
                lambda m: f"CAST({col} AS MONEY) {m.group(1)} {m.group(2)}",
                sql,
                flags=re.IGNORECASE,
            )

        return sql

    def _extract_last_data_context(self, history: List[Dict[str, str]]) -> str:
        """ดึงข้อมูลตารางหรือสรุปจากข้อความล่าสุดของ Assistant เพื่อนำมาใช้ประมวลผลต่อ"""
        for m in reversed(history):
            if m["role"] == "assistant":
                content = m["content"]
                if "|" in content or "### " in content:
                    return content
                return content[:2000]
        return ""

    def _save_last_result(self, session_id, result):
        if not hasattr(self, "_session_memory"):
            self._session_memory = {}

        self._session_memory[session_id] = result

    # ── CRM keyword → ให้ dynamic SQL รู้ว่าต้องไป crms ─────────────────────
    _CRM_KEYWORDS = [
        "ประวัติการติดตาม", "ประวัติติดตาม", "crm", "log การติดตาม",
        "บันทึกการติดตาม", "ประวัติการโทร", "ประวัติการเจรจา",
        "ตามหนี้", "การเก็บหนี้", "collector", "แนวทางการตาม",
        "การติดต่อ", "นัดชำระ", "คุยว่าอะไร", "ผลการโทร",
    ]

    def _detect_target_db(self, q: str, sql: str = "") -> str:
        """ตรวจ keyword ใน question หรือ SQL เพื่อเลือก database"""
        haystack = (q + " " + sql).lower()
        crm_tables = {"crmdetail", "crmfol1", "crmfol2"}
        if any(t in haystack for t in crm_tables):
            return "crms"
        if any(kw in haystack for kw in self._CRM_KEYWORDS):
            return "crms"
        return "lspdata"

    # ── Stateful follow-up SQL reuse ──────────────────────────────────────────
    def _extract_session_state(self, history: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        ดึง last_sql และ last_db จาก history
        Frontend ควรส่ง special message: {"role": "system", "content": "__sql__:<sql>", "db": "<db>"}
        ถ้าไม่มี → fallback ดึง SQL จาก event ใน content string แทน
        """
        for m in reversed(history):
            role = m.get("role", "")
            content = m.get("content", "")
            # รูปแบบ 1: system message พิเศษที่ frontend inject
            if role == "system" and content.startswith("__sql__:"):
                sql = content[len("__sql__:"):]
                db  = m.get("db", "lspdata")
                return {"last_sql": sql.strip(), "last_db": db}
            # รูปแบบ 2: assistant message ที่มี SQL ฝังอยู่ (จาก event sql)
            if role == "assistant" and "__last_sql__:" in content:
                parts = content.split("__last_sql__:")
                if len(parts) > 1:
                    sql_part = parts[1].split("__end_sql__")[0].strip()
                    return {"last_sql": sql_part, "last_db": "lspdata"}
        return {"last_sql": None, "last_db": "lspdata"}

    def _try_followup_sql(self, q: str, session: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """
        ถ้าคำถามเป็น follow-up ที่แค่ต้องการ LIMIT หรือ ORDER ต่างออกไป
        → แก้ last_sql แทนที่จะ gen ใหม่ทั้งก้อน
        คืน (sql, db) หรือ None ถ้าไม่ใช่ follow-up แบบนี้
        """
        last_sql = session.get("last_sql")
        if not last_sql:
            return None

        ql = q.strip().lower()

        # ── Pattern 1: "ขอ N รายการแรก" / "top N" ──────────────────────────
        n = None
        m = _TOP_N_RE.search(ql)
        if m:
            n = int(m.group(1))
        m2 = _TOP_WORD_RE.search(ql)
        if m2:
            n = int(m2.group(1))

        # คำถามสั้นที่เป็นแค่ตัวเลข เช่น "5 รายการ"
        if not n and _FOLLOWUP_LIMIT.match(ql):
            mm = re.search(r"(\d+)", ql)
            if mm:
                n = int(mm.group(1))

        if n and any(phrase in ql for phrase in _LIMIT_PHRASES + ["รายการแรก", "ขอ", "top"]):
            # เอา SELECT TOP ที่มีอยู่ออกก่อน แล้วใส่ใหม่
            sql = re.sub(r"\bSELECT\s+TOP\s+\d+\b", "SELECT", last_sql, flags=re.IGNORECASE)
            sql = re.sub(r"\bSELECT\b", f"SELECT TOP {n}", sql, count=1, flags=re.IGNORECASE)
            db  = session.get("last_db", "lspdata")
            logger.info("⚡ Follow-up SQL reuse (TOP %d): %.120s", n, sql)
            return (sql, db)

        return None

    async def _generate_dynamic_sql(
        self,
        q: str,
        semantic: Dict[str, Any] = None,
        history: List[Dict[str, str]] = [],
    ) -> str:
        from prompts.sql_system import get_sql_system_prompt

        is_crm_query = self._detect_target_db(q) == "crms"
        if is_crm_query:
            allowed_tables = ["CRMDetail", "CRMFol1", "CRMFol2"]
        else:
            allowed_tables = ["LSM010", "LSM011"]
            if semantic and semantic.get("include_names"):
                allowed_tables.append("LSM007")

        semantic_json = json.dumps(semantic, ensure_ascii=False) if semantic else "{}"
        training_context = f"SEMANTIC INTENT (GUIDE): {semantic_json}"
        hist_str = "\n".join([f"{m['role']}: {m['content']}" for m in history[-3:]])

        prompt = get_sql_system_prompt(
            training_context=training_context,
            history=hist_str,
            allowed_tables=allowed_tables,
        )
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

    # ── CHITCHAT Shortcut ─────────────────────────────────────────────────────
    _CHITCHAT_PATTERNS: list[tuple[list[str], str]] = [
        (["สวัสดี", "หวัดดี", "hello", "hi ", "^hi$", "ดีครับ", "ดีค่ะ"],
         "สวัสดีครับ! ผมคือ SBL AI ผู้ช่วยข้อมูลสัญญาเช่าซื้อของ SBL พร้อมช่วยคุณเสมอครับ 😊"),
        (["คุณคือใคร", "คือใคร", "แนะนำตัว", "ตัวเองคือ", "คุณเป็นใคร", "who are you"],
         "ผมคือ SBL AI ผู้ช่วยอัจฉริยะของบริษัท SBL ครับ ทำหน้าที่ช่วยค้นหาและวิเคราะห์ข้อมูลสัญญาเช่าซื้อ ยอดหนี้ สถานะลูกหนี้ และประวัติการติดตามทั้งหมดในระบบครับ"),
        (["ช่วยอะไรได้", "ทำอะไรได้", "ความสามารถ", "ใช้ทำอะไร", "มีอะไรบ้าง",
          "ช่วยได้อะไร", "ทำได้อะไร", "what can you do"],
         "ผมสามารถช่วยคุณได้หลายอย่างครับ เช่น:\n"
         "• ค้นหา**รายละเอียดสัญญา** — ยอดหนี้ สถานะ พนักงานดูแล\n"
         "• ดู**ลูกหนี้ค้างชำระ** — กลุ่มเตือน B/C/D, ครบกำหนด 35 วัน, ติดคดี\n"
         "• สรุป**ยอดหนี้รายสาขา** หรือ**รายพนักงาน**\n"
         "• ดู**ประวัติการติดตาม** (CRM Log) ของแต่ละสัญญา\n"
         "• ค้นหา**Watch List**, สัญญา**ยึดรถ**, สัญญา**ปรับปรุงหนี้**\n"
         "ลองถามผมได้เลยครับ เช่น 'สาขา MN มีลูกหนี้ค้างกี่ราย' หรือ 'ดูประวัติสัญญา GGJ1530IIN10'"),
        (["ขอบคุณ", "ขอบใจ", "thank", "thanks"],
         "ยินดีครับ มีอะไรให้ช่วยอีกได้เลยครับ 😊"),
        (["ลาก่อน", "บ๊ายบาย", "bye", "goodbye", "แล้วเจอกัน"],
         "ลาก่อนครับ! หากต้องการข้อมูลเพิ่มเติมทักมาได้เลยนะครับ 👋"),
    ]

    def _chitchat_reply(self, q: str) -> str | None:
        ql = q.lower().strip()
        for patterns, reply in self._CHITCHAT_PATTERNS:
            for pat in patterns:
                if re.search(pat, ql):
                    logger.info("⚡ CHITCHAT shortcut matched: '%s'", pat)
                    return reply
        return None

    # ── Keyword Priority Rules ────────────────────────────────────────────────
    _KEYWORD_PRIORITY: list[tuple[list[str], str]] = [
        (["ติดต่อไม่ได้กี่ครั้ง", "ติดต่อได้กี่ครั้ง", "ครั้งล่าสุดที่ติดต่อได้",
          "โทรแล้วรับสาย", "ไม่รับสายกี่ครั้ง", "รับสายกี่ครั้ง",
          "ติดต่อสำเร็จ", "ติดต่อไม่สำเร็จ", "วิเคราะห์การติดตาม"],
         "CONTRACT_FOLLOWUP_ANALYSIS"),
        (["ประวัติการติดตาม", "ประวัติติดตาม", "log การติดตาม",
          "บันทึกการติดตาม", "ประวัติการโทร", "ประวัติการเจรจา", "crm log"],
         "CONTRACT_FOLLOWUP_LOG"),
        (["คิวเก็บเงิน", "นัดจ่ายวันที่", "นัดชำระวันที่", "due_date", "วันนี้มีใครนัด"],
         "CRM_APPOINTMENT_LIST"),
        (["วัดผล collector", "ผลงานพนักงานติดตาม", "พนักงานคนไหนโทรเยอะ"],
         "COLLECTOR_ACTIVITY_SUMMARY"),
        (["สถิติผลการโทร", "สถิติการติดตาม", "ผลการโทรแยกประเภท", "ปิดเครื่องกี่ราย"],
         "CRM_FOLLOWUP_STATUS_COUNTS"),
        (["crm ล่าสุด", "ประวัติติดต่อในระบบ crms", "รายการการติดตามล่าสุด"],
         "CRM_CONTACT_LIST"),
        (["บอกเลิก 35", "ครบกำหนดบอกเลิก", "ถึงกำหนดบอกเลิก", "stat2 f"],
         "OVERDUE_35_DAYS"),
        (["ติดคดี", "ฟ้องร้อง", "ส่งกฎหมาย", "ฟ้องแล้ว", "stat2 g"],
         "LEGAL_CASE"),
        (["ตัดหนี้สูญ", "write-off", "writeoff", "ตัดหนี้แล้ว", "stat2 h"],
         "WRITTEN_OFF"),
        (["กลุ่มเตือน", "เตือนครั้งที่", "stat2 b", "stat2 c", "stat2 d"],
         "WARNING_GROUP"),
        (["รถถูกยึด", "ยึดรถแล้ว", "accstat 3"],  "VEHICLE_REPOSSESSED"),
        (["ปรับปรุงหนี้", "restructure", "accstat 7"], "RESTRUCTURED_CONTRACTS"),
        (["จ่ายจบ", "ปิดบัญชีจ่ายจบ", "ชำระครบหมด", "accstat 1"], "PAID_UP_LIST"),
        (["top 5", "5 อันดับ", "5 รายที่"],  "TOP_5_INTEREST"),
        (["watch list", "watchlist", "เฝ้าระวัง"], "WATCH_LIST_ACCOUNTS"),
        (["เกิน 25000", "25,000 บาท", "interest.*25000"], "INTEREST_OVER_25000_MN"),
    ]

    def _fast_route(self, q: str) -> Dict[str, Any]:
        ql = q.lower()

        # 1. Keyword Priority
        for keywords, template_name in self._KEYWORD_PRIORITY:
            for kw in keywords:
                if re.search(kw, ql):
                    params = self._extract_params(q, template_name)
                    cat = TEMPLATE_CATEGORIES.get(template_name, {}).get("category", "other")
                    logger.info("⚡ Keyword Priority: '%s' → %s (kw='%s')", q[:60], template_name, kw)
                    return {"template_name": template_name, "params": params, "category": cat}

        # 2. Token Overlap Fallback
        stop_words = {"", "ที่", "ของ", "มี", "ใน", "และ", "หรือ", "กับ", "ให้", "ด้วย", "จาก", "ว่า", "อะ", "ครับ", "ค่ะ", "นะ", "อยู่", "บ้าง"}
        q_tokens = set(re.split(r"[\s,]+", ql)) - stop_words

        best_score = 0.0
        best_template = None

        for name, examples in TEMPLATE_EXAMPLES.items():
            for example in examples:
                ex_tokens = set(re.split(r"[\s,]+", example.lower())) - stop_words
                if not ex_tokens:
                    continue
                overlap = len(q_tokens & ex_tokens)
                score = overlap / max(len(q_tokens), len(ex_tokens))
                if score > best_score:
                    best_score = score
                    best_template = name

        _FAST_ROUTE_THRESHOLD = 0.35
        if best_score >= _FAST_ROUTE_THRESHOLD and best_template:
            params = self._extract_params(q, best_template)
            cat = TEMPLATE_CATEGORIES.get(best_template, {}).get("category", "other")
            logger.info("⚡ Fast Route: '%s' → %s (score=%.2f)", q[:60], best_template, best_score)
            return {"template_name": best_template, "params": params, "category": cat}

        logger.info("Fast Route: no match (best=%.2f '%s') → dynamic SQL", best_score, best_template)
        return None

    def _extract_params(self, q: str, template_name: str) -> Dict[str, Any]:
        """ดึง param ที่จำเป็นสำหรับ template"""
        params: Dict[str, Any] = {}
        needed = SQL_TEMPLATES.get(template_name, "")

        if ":branch_filter" in needed or ":branch_code" in needed:
            m = re.search(r"สาขา\s*([A-Z0-9]{1,4})", q, re.IGNORECASE)
            if m:
                params["branch_code"] = m.group(1).upper()

        if ":acc_no" in needed:
            m = re.search(r"\b([A-Z0-9]{2,4}\d{4}[A-Z0-9]{2,6})\b", q, re.IGNORECASE)
            if m:
                params["acc_no"] = m.group(1).upper()

        if ":fol_id" in needed:
            m = re.search(r"\b(\d{3,6})\b", q)
            if m:
                params["fol_id"] = m.group(1)

        if ":cus_id" in needed:
            m = re.search(r"\b([Cc]\d{3,10})\b", q)
            if m:
                params["cus_id"] = m.group(1).upper()

        if ":eng_no" in needed:
            m = re.search(r"\b([A-Z0-9]{5,20})\b", q, re.IGNORECASE)
            if m:
                params["eng_no"] = m.group(1).upper()

        if ":stat2_filter" in needed:
            for code, keyword in [("B", "เตือน 1"), ("C", "เตือน 2"), ("D", "เตือน 3")]:
                if keyword in q:
                    params["stat2_code"] = code
                    break

        if ":due_date" in needed:
            m = re.search(r"\b(\d{8})\b", q)
            if m:
                params["due_date"] = m.group(1)
            elif "วันนี้" in q:
                params["due_date"] = time.strftime("%Y%m%d")
            elif "พรุ่งนี้" in q:
                params["due_date"] = time.strftime("%Y%m%d", time.localtime(time.time() + 86400))

        if ":mth" in needed:
            m = re.search(r"เดือน\s*(\d{1,2})", q)
            if m:
                params["mth"] = m.group(1).zfill(2)
            else:
                params["mth"] = time.strftime("%m")

        if ":yrs" in needed:
            m = re.search(r"ปี\s*(\d{4})", q)
            if m:
                params["yrs"] = m.group(1)
            else:
                params["yrs"] = time.strftime("%Y")

        return params

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
            yield self._event("status", content="ขอตรวจสอบความถูกต้องของคำถามสักครู่นะครับ...")
            injected, pattern = detect_prompt_injection(q)
            if injected:
                raise SecurityError("คำถามไม่ผ่านการตรวจสอบความปลอดภัย", details=pattern)

            # 2. CHITCHAT shortcut
            chitchat_reply = self._chitchat_reply(q)
            if chitchat_reply is not None:
                yield self._event("intent", intent="CHITCHAT", confidence="high")
                yield self._event("content", content=chitchat_reply)
                yield self._event("done", elapsed=round(time.time() - start_time, 2))
                return

            # 3. Intent detection
            yield self._event("status", content="กำลังทำความเข้าใจสิ่งที่คุณต้องการครับ...")
            intent_res = detect_intent(q, history)
            intent = intent_res["intent"]
            yield self._event("intent", intent=intent, confidence=intent_res["confidence"])

            context_str = ""
            stats_str = ""
            db_results: list = []
            sql = "NO_SQL"
            target_db = "lspdata"

            # ── 4. DATA_QUERY / ADVISORY routing ──────────────────────────────
            # ──────────────────────────────
            # 🔥 INTENT HELPER
            # ──────────────────────────────
            def is_advisory(question: str, history) -> bool:
                advisory_keywords = r"(ตามยังไง|จัดการยังไง|วิเคราะห์|แนะนำ|แนวทาง|สเต็ป|ท่าไหน|ทำยังไง|ทำไม|อย่างไร|ควรจะ|วิธี|แก้ปัญหา|ยังไงดี|ควรทำอะไร|เหมาะสมไหม|เป็นไปได้ไหม)"
                return bool(history) and re.search(advisory_keywords, question.lower())


            # ──────────────────────────────
            # 🔥 MAIN FLOW (แทน block เดิม)
            # ──────────────────────────────
            async def handle_ai(self, q, history, session_id):
                start_time = time.time()

                intent = "DATA_QUERY"

                # 🔥 HARD OVERRIDE
                if is_advisory(q, history):
                    intent = "ADVISORY"

                context_str = ""
                sql = "NO_SQL"
                db_results = []
                target_db = None

                # ──────────────────────────────
                # 🔥 1. ADVISORY (NO SQL)
                # ──────────────────────────────
                if intent == "ADVISORY":
                    yield self._event("status", content="กำลังวิเคราะห์ข้อมูลก่อนหน้านี้นะครับ...")

                    context_str = self._extract_last_data_context(history)

                    if not context_str:
                        yield self._event("content", content="ไม่มีข้อมูลก่อนหน้าให้วิเคราะห์ครับ")
                        yield self._event("done", time=round(time.time() - start_time, 2))
                        return

                    response_text = await self._call_insight_llm(context_str, q, history)

                    yield self._event("content", content=response_text)
                    yield self._event("done", time=round(time.time() - start_time, 2))
                    return

                # ──────────────────────────────
                # 🔥 2. DATA QUERY (SQL ONLY)
                # ──────────────────────────────
                yield self._event("status", content="เดี๋ยวผมลองค้นหาข้อมูลในระบบให้นะครับ...")

                # 🔹 Follow-up
                session = self._extract_session_state(history)
                followup_result = self._try_followup_sql(q, session)

                if followup_result:
                    sql, target_db = followup_result
                    yield self._event("sql", sql=sql)

                else:
                    # 🔹 Fast route
                    fast = self._fast_route(q)

                    if fast:
                        template_name = fast.get("template_name", "UNKNOWN")
                        params = fast.get("params", {})

                        if template_name in SQL_TEMPLATES:
                            sql, _ = render_query(template_name, params)
                            target_db = get_template_db(template_name)
                            yield self._event("sql", sql=sql)

                    if not sql or sql == "NO_SQL":
                        # 🔹 Dynamic SQL
                        yield self._event("status", content="ขอเวลาผมตีความหมายข้อมูลสักครู่นะครับ...")

                        semantic = await self.semantic_layer.extract_intent(q)
                        target_db = self._detect_target_db(q)

                        sql = await self._generate_dynamic_sql(q, semantic, history)

                        if sql != "NO_SQL":
                            sql = self._fix_common_sql_mistakes(sql)

                            is_valid, error_msg = self.validator.validate(sql, q)
                            if not is_valid:
                                sql = "NO_SQL"
                                context_str = f"ไม่สามารถค้นหาข้อมูลได้ ({error_msg})"
                            else:
                                yield self._event("sql", sql=sql)
                        else:
                            context_str = "ไม่พบข้อมูลที่ผู้ใช้ร้องขอ"

                # ──────────────────────────────
                # 🔥 EXECUTE SQL
                # ──────────────────────────────
                if sql != "NO_SQL":
                    try:
                        db_results = await asyncio.to_thread(fetch_data, sql, db=target_db)

                        if db_results:
                            # 🔥 SAVE MEMORY (สำคัญมาก)
                            self._save_last_result(session_id, db_results)

                            context_str = engine.format_db_results(
                                db_results, self.schema, question=q, intent=intent
                            )

                            # ❗ NO LLM
                            yield self._event("content", content=context_str)

                        else:
                            yield self._event("content", content="ไม่พบข้อมูลที่ตรงกับเงื่อนไข")

                    except Exception as e:
                        yield self._event("content", content=f"เกิดข้อผิดพลาด: {e}")

                else:
                    yield self._event("content", content=context_str or "ไม่พบข้อมูล")

                yield self._event("done", time=round(time.time() - start_time, 2))

            # ── 5. Final answer (LLM call #2) ──────────────────────────────────
            yield self._event("status", content="เรียบร้อยครับ เดี๋ยวผมสรุปให้อ่านง่ายๆ นะครับ...")

            from prompts.insight import (
                INSIGHT_SYSTEM,
                INSIGHT_PROMPT_TEMPLATE,
                GENERAL_SYSTEM,
                GENERAL_PROMPT_TEMPLATE,
                CRM_LOG_SYSTEM,
                CRM_LOG_PROMPT_TEMPLATE,
            )

            full_context = context_str
            ai_context = context_str

            # บีบอัดข้อมูลสำหรับ AI (ส่งแค่ 7 แถวล่าสุด)
            if "FDATE" in context_str or "|" in context_str:
                lines = context_str.split("\n")
                header_lines = [l for l in lines[:3] if "|" in l or "---" in l]
                data_lines = [l for l in lines[3:] if "|" in l]
                if len(data_lines) > 7:
                    ai_context = "\n".join(header_lines + data_lines[:7] + ["... (ข้อมูลก่อนหน้านี้ถูกตัดออกเพื่อการประมวลผลที่รวดเร็ว)"])

            stats_str = stats_str if stats_str else ""
            hist_str = "\n".join([f"{m['role']}: {m['content']}" for m in history[-5:]])

            is_crm_log = (
                intent != "ADVISORY"
                and ("FDATE" in context_str or "Section" in context_str)
            )

            if intent == "GENERAL":
                final_prompt = GENERAL_PROMPT_TEMPLATE.format(question=q, history=hist_str)
                system_prompt = GENERAL_SYSTEM
                insight_tokens = 800
            elif intent == "ADVISORY":
                final_prompt = INSIGHT_PROMPT_TEMPLATE.format(
                    question=q, context=ai_context,
                    stats=stats_str if stats_str else "N/A", history=hist_str,
                )
                system_prompt = INSIGHT_SYSTEM
                insight_tokens = 1200
            elif is_crm_log:
                final_prompt = CRM_LOG_PROMPT_TEMPLATE.format(context=context_str)
                system_prompt = CRM_LOG_SYSTEM
                insight_tokens = 1500
            else:
                final_prompt = INSIGHT_PROMPT_TEMPLATE.format(
                    question=q, context=ai_context,
                    stats=stats_str if stats_str else "N/A", history=hist_str,
                )
                system_prompt = INSIGHT_SYSTEM
                insight_tokens = 1200

            response_text = ""
            try:
                async for chunk in self.ollama.chat_stream(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": final_prompt},
                    ],
                    model=MODEL_NAME,
                    tokens=insight_tokens,
                ):
                    response_text += chunk
                    yield self._event("content", content=chunk)
            except LLMError as llm_err:
                logger.warning("chat_stream failed (%s) → fallback to generate", llm_err)
                yield self._event("status", content="กำลังประมวลผลใหม่อีกครั้งครับ...")
                try:
                    fallback_prompt = f"{system_prompt}\n\n{final_prompt}"
                    response_text = await self.ollama.generate(
                        fallback_prompt, tokens=min(insight_tokens, 600), temperature=0.2,
                    )
                    if response_text:
                        yield self._event("content", content=response_text)
                    else:
                        yield self._event("content", content="ขออภัยครับ ระบบ AI ไม่สามารถสรุปข้อมูลได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง")
                except Exception as fallback_err:
                    logger.error("Fallback generate also failed: %s", fallback_err)
                    yield self._event("content", content="ขออภัยครับ ระบบ AI ไม่ตอบสนองในขณะนี้ กรุณาลองใหม่ภายหลัง")

            # ── Emit last_sql ให้ frontend เก็บไว้เป็น session state ──────────
            if sql != "NO_SQL":
                yield self._event("session_sql", sql=sql, db=target_db)

            logger.info("AI Insight: %.100s", response_text)
            yield self._event("done", time=round(time.time() - start_time, 2))

        except SecurityError as e:
            yield self._event("error", content=f"⚠️ ระงับการค้นหา: {e.message}")
        except (SBLError, BusinessRuleError) as e:
            yield self._event("error", content=f"❌ เกิดข้อผิดพลาด: {e.message}")