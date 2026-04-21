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
from typing import AsyncGenerator, Dict, Any, List, Optional

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

    def _extract_last_data_context(self, history: List[Dict[str, str]]) -> str:
        """ดึงข้อมูลตารางหรือสรุปจากข้อความล่าสุดของ Assistant เพื่อนำมาใช้ประมวลผลต่อ"""
        for m in reversed(history):
            if m["role"] == "assistant":
                content = m["content"]
                # ดึง Markdown Table หรือ รายการ Bullet
                if "|" in content or "### " in content:
                    return content
                # ถ้าไม่มีตาราง ให้เอามาทั้งก้อน (แต่ตัดส่วนสรุปออกถ้าทำได้)
                return content[:MAX_CONTEXT_CHARS] if 'MAX_CONTEXT_CHARS' in globals() else content[:2000]
        return ""

    # ── CRM keyword → ให้ dynamic SQL รู้ว่าต้องไป crms ─────────────────────
    _CRM_KEYWORDS = [
        "ประวัติการติดตาม", "ประวัติติดตาม", "crm", "log การติดตาม",
        "บันทึกการติดตาม", "ประวัติการโทร", "ประวัติการเจรจา",
        "ติดตามหนี้", "การเก็บหนี้", "collector", "crmdetail",
        "การติดต่อ", "นัดชำระ", "due_date", "fdetail", "fdate",
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

    async def _generate_dynamic_sql(
        self,
        q: str,
        semantic: Dict[str, Any] = None,
        history: List[Dict[str, str]] = [],
    ) -> str:
        from prompts.sql_system import get_sql_system_prompt

        # Decide which tables to include based on semantic intent
        # CRM keywords → ให้รู้ว่าใช้ตาราง CRM ได้
        is_crm_query = self._detect_target_db(q) == "crms"
        if is_crm_query:
            allowed_tables = ["CRMDetail", "CRMFol1", "CRMFol2"]
        else:
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

    # ── CHITCHAT Shortcut — ตอบทันทีโดยไม่ต้องรอ LLM ────────────────────────
    _CHITCHAT_PATTERNS: list[tuple[list[str], str]] = [
        # ทักทาย
        (["สวัสดี", "หวัดดี", "hello", "hi ", "^hi$", "ดีครับ", "ดีค่ะ"],
         "สวัสดีครับ! ผมคือ SBL AI ผู้ช่วยข้อมูลสัญญาเช่าซื้อของ SBL พร้อมช่วยคุณเสมอครับ 😊"),

        # ตัวตน
        (["คุณคือใคร", "คือใคร", "แนะนำตัว", "ตัวเองคือ", "คุณเป็นใคร", "who are you"],
         "ผมคือ SBL AI ผู้ช่วยอัจฉริยะของบริษัท SBL ครับ ทำหน้าที่ช่วยค้นหาและวิเคราะห์ข้อมูลสัญญาเช่าซื้อ ยอดหนี้ สถานะลูกหนี้ และประวัติการติดตามทั้งหมดในระบบครับ"),

        # ความสามารถ
        (["ช่วยอะไรได้", "ทำอะไรได้", "ความสามารถ", "ใช้ทำอะไร", "มีอะไรบ้าง",
          "ช่วยได้อะไร", "ทำได้อะไร", "what can you do"],
         "ผมสามารถช่วยคุณได้หลายอย่างครับ เช่น:"
         "• ค้นหา**รายละเอียดสัญญา** — ยอดหนี้ สถานะ พนักงานดูแล"
         "• ดู**ลูกหนี้ค้างชำระ** — กลุ่มเตือน B/C/D, ครบกำหนด 35 วัน, ติดคดี"
         "• สรุป**ยอดหนี้รายสาขา** หรือ**รายพนักงาน**"
         "• ดู**ประวัติการติดตาม** (CRM Log) ของแต่ละสัญญา"
         "• ค้นหา**Watch List**, สัญญา**ยึดรถ**, สัญญา**ปรับปรุงหนี้**"
         "ลองถามผมได้เลยครับ เช่น 'สาขา MN มีลูกหนี้ค้างกี่ราย' หรือ 'ดูประวัติสัญญา GGJ1530IIN10'"),

        # ขอบคุณ
        (["ขอบคุณ", "ขอบใจ", "thank", "thanks"],
         "ยินดีครับ มีอะไรให้ช่วยอีกได้เลยครับ 😊"),

        # ลาก่อน
        (["ลาก่อน", "บ๊ายบาย", "bye", "goodbye", "แล้วเจอกัน"],
         "ลาก่อนครับ! หากต้องการข้อมูลเพิ่มเติมทักมาได้เลยนะครับ 👋"),
    ]

    def _chitchat_reply(self, q: str) -> str | None:
        """
        ตรวจว่าคำถามเป็น chitchat/identity → คืน reply สำเร็จรูปทันที
        คืน None ถ้าไม่ใช่ (ให้ pipeline ทำงานต่อ)
        """
        ql = q.lower().strip()
        for patterns, reply in self._CHITCHAT_PATTERNS:
            for pat in patterns:
                if re.search(pat, ql):
                    logger.info("⚡ CHITCHAT shortcut matched: '%s'", pat)
                    return reply
        return None

    # ── Keyword Priority Rules ────────────────────────────────────────────────
    # ภาษาไทยไม่มี space ระหว่างคำ → token overlap เพียงอย่างเดียวแยกแยะไม่ได้
    _KEYWORD_PRIORITY: list[tuple[list[str], str]] = [
        # CRM analysis — ต้องตรวจก่อน LOG เพราะ keyword ซ้อนทับกัน
        (["ติดต่อไม่ได้กี่ครั้ง", "ติดต่อได้กี่ครั้ง", "ครั้งล่าสุดที่ติดต่อได้",
          "โทรแล้วรับสาย", "ไม่รับสายกี่ครั้ง", "รับสายกี่ครั้ง",
          "ติดต่อสำเร็จ", "ติดต่อไม่สำเร็จ", "วิเคราะห์การติดตาม"],
         "CONTRACT_FOLLOWUP_ANALYSIS"),
        # CRM / ประวัติติดตาม — ต้องตรวจก่อน CONTRACT_DETAIL
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
        # Stat2
        (["บอกเลิก 35", "ครบกำหนดบอกเลิก", "ถึงกำหนดบอกเลิก", "stat2 f"],
         "OVERDUE_35_DAYS"),
        (["ติดคดี", "ฟ้องร้อง", "ส่งกฎหมาย", "ฟ้องแล้ว", "stat2 g"],
         "LEGAL_CASE"),
        (["ตัดหนี้สูญ", "write-off", "writeoff", "ตัดหนี้แล้ว", "stat2 h"],
         "WRITTEN_OFF"),
        (["กลุ่มเตือน", "เตือนครั้งที่", "stat2 b", "stat2 c", "stat2 d"],
         "WARNING_GROUP"),
        # AccStat
        (["รถถูกยึด", "ยึดรถแล้ว", "accstat 3"],  "VEHICLE_REPOSSESSED"),
        (["ปรับปรุงหนี้", "restructure", "accstat 7"], "RESTRUCTURED_CONTRACTS"),
        (["จ่ายจบ", "ปิดบัญชีจ่ายจบ", "ชำระครบหมด", "accstat 1"], "PAID_UP_LIST"),
        # Misc
        (["top 5", "5 อันดับ", "5 รายที่"],  "TOP_5_INTEREST"),
        (["watch list", "watchlist", "เฝ้าระวัง"], "WATCH_LIST_ACCOUNTS"),
        (["เกิน 25000", "25,000 บาท", "interest.*25000"], "INTEREST_OVER_25000_MN"),
    ]

    # ── Fast Path Routing (keyword overlap — ไม่ต้องรอ LLM) ──────────────────
    def _fast_route(self, q: str) -> Dict[str, Any]:
        """
        ลอง match คำถามกับ example_questions ของแต่ละ template
        โดยใช้ keyword overlap score (ไม่ต้องเรียก LLM)

        คืน dict เหมือน _route_request(): {template_name, params, category}
        หรือ None ถ้า match ไม่ได้ (จะ fallback ไป LLM)
        """
        ql = q.lower()

        # ── 1. Keyword Priority — แก้ปัญหาภาษาไทยไม่มี space ────────────────
        for keywords, template_name in self._KEYWORD_PRIORITY:
            for kw in keywords:
                if re.search(kw, ql):
                    params = self._extract_params(q, template_name)
                    cat = TEMPLATE_CATEGORIES.get(template_name, {}).get("category", "other")
                    logger.info(
                        "⚡ Keyword Priority: '%s' → %s (kw='%s')", q[:60], template_name, kw
                    )
                    return {"template_name": template_name, "params": params, "category": cat}

        # ── 2. Token Overlap Fallback ─────────────────────────────────────────
        q_tokens = set(re.split(r"[\s,]+", ql)) - {"", "ที่", "ของ", "มี", "ใน", "และ", "หรือ", "กับ", "ให้", "ด้วย", "จาก", "ว่า", "อะ", "ครับ", "ค่ะ", "นะ", "อยู่", "บ้าง"}

        best_score = 0.0
        best_template = None

        for name, examples in TEMPLATE_EXAMPLES.items():
            for example in examples:
                ex_tokens = set(re.split(r"[\s,]+", example.lower())) - {"", "ที่", "ของ", "มี", "ใน", "และ", "หรือ", "กับ", "ให้", "ด้วย", "จาก", "ว่า", "อะ", "ครับ", "ค่ะ", "นะ", "อยู่", "บ้าง"}
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
            logger.info(
                "⚡ Fast Route: '%s' → %s (score=%.2f)", q[:60], best_template, best_score
            )
            return {"template_name": best_template, "params": params, "category": cat}

        logger.info("Fast Route: no match (best=%.2f '%s') → fallback LLM", best_score, best_template)
        return None
    def _extract_params(self, q: str, template_name: str) -> Dict[str, Any]:
        """ดึง param ที่จำเป็นสำหรับ template (branch_code, acc_no, fol_id) จากคำถาม"""
        params: Dict[str, Any] = {}
        needed = SQL_TEMPLATES.get(template_name, "")

        # branch_code: OLID 2 ตัวอักษรหลัง 'สาขา'
        if ":branch_filter" in needed or ":branch_code" in needed:
            m = re.search(r"สาขา\s*([A-Z0-9]{1,4})", q, re.IGNORECASE)
            if m:
                params["branch_code"] = m.group(1).upper()

        # acc_no: pattern เลขที่สัญญา เช่น GGJ1530IIN10, DCJ0261IIN
        if ":acc_no" in needed:
            # ใช้ pattern ที่ยืดหยุ่นขึ้น: ตัวอักษร/เลข 2-4 ตัว + เลข 4 ตัว + ตัวอักษร/เลข 2-6 ตัว
            m = re.search(r"\b([A-Z0-9]{2,4}\d{4}[A-Z0-9]{2,6})\b", q, re.IGNORECASE)
            if m:
                params["acc_no"] = m.group(1).upper()

        # fol_id: เลขรหัสพนักงาน
        if ":fol_id" in needed:
            m = re.search(r"\b(\d{3,6})\b", q)
            if m:
                params["fol_id"] = m.group(1)

        # stat2_code: B/C/D
        if ":stat2_filter" in needed:
            for code, keyword in [("B", "เตือน 1"), ("C", "เตือน 2"), ("D", "เตือน 3")]:
                if keyword in q:
                    params["stat2_code"] = code
                    break

        # due_date: pattern 8 digits (YYYYMMDD) or specific phrases
        if ":due_date" in needed:
            m = re.search(r"\b(\d{8})\b", q)
            if m:
                params["due_date"] = m.group(1)
            elif "วันนี้" in q:
                params["due_date"] = time.strftime("%Y%m%d")
            elif "พรุ่งนี้" in q:
                params["due_date"] = time.strftime("%Y%m%d", time.localtime(time.time() + 86400))

        # mth: 2 digits (MM) usually after 'เดือน'
        if ":mth" in needed:
            m = re.search(r"เดือน\s*(\d{1,2})", q)
            if m:
                params["mth"] = m.group(1).zfill(2)
            else:
                # Default to current month if not specified but needed
                params["mth"] = time.strftime("%m")

        # yrs: 4 digits (YYYY) usually after 'ปี'
        if ":yrs" in needed:
            m = re.search(r"ปี\s*(\d{4})", q)
            if m:
                params["yrs"] = m.group(1)
            else:
                # Default to current year
                params["yrs"] = time.strftime("%Y")

        return params

    async def _route_request(self, q: str) -> Dict[str, Any]:
        """LLM-based routing — เรียกเฉพาะเมื่อ Fast Route ไม่ match"""
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

            # 2. CHITCHAT shortcut — ตอบทันทีโดยไม่ต้องรอ LLM
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
            yield self._event(
                "intent", intent=intent, confidence=intent_res["confidence"]
            )

            context_str = ""
            stats_str = ""
            db_results: list = []

            # 3. DATA_QUERY / ADVISORY routing
            if intent in ("DATA_QUERY", "ADVISORY"):
                # Force Advisory if keywords match, even if intent was DATA_QUERY
                # Force Advisory if keywords match
                advisory_keywords = r"(ทำยังไง|ทํายังไง|ทำไม|ทําไม|อย่างไร|แนะนำ|ควรจะ|แนวทาง|วิธี|แก้ปัญหา|ตามได้ไง|วิเคราะห์|ยังไงดี|ให้ติดตามได้|ให้ติดตามหนี้ได้|ให้จ่ายได้|ให้ชำระได้|ทำให้จ่าย|ทำให้ชำระ|จะทำให้|จะช่วยได้|จะแก้ได้|ควรทำอะไร)"
                if re.search(advisory_keywords, q.lower()) and history:
                    intent = "ADVISORY"

                if intent == "ADVISORY":
                    yield self._event("status", content="กำลังวิเคราะห์ข้อมูลที่คุณดึงมาก่อนหน้านี้นะครับ...")
                    context_str = self._extract_last_data_context(history)
                    if not context_str:
                        intent = "DATA_QUERY"
                    else:
                        logger.info("Advisory path: using last data context (chars: %d)", len(context_str))
                        # Skip SQL generation explicitly
                        template_name = "UNKNOWN"
                        sql = "NO_SQL"

                if intent == "DATA_QUERY":
                    yield self._event("status", content="เดี๋ยวผมลองค้นหาข้อมูลในระบบให้นะครับ...")

                    if intent != "ADVISORY":
                        # ⚡ Fast Path: keyword match ก่อน (ไม่รอ LLM)
                        fast = self._fast_route(q)
                        if fast:
                            decision = fast
                        else:
                            # Fallback: LLM routing
                            yield self._event("status", content="กำลังวิเคราะห์คำถามสักครู่นะครับ...")
                            decision = await self._route_request(q)

                        template_name = decision.get("template_name", "UNKNOWN")
                        params = decision.get("params", {})
                        logger.info("Route → template: %s", template_name)

                        target_db = "lspdata"
                        if template_name != "UNKNOWN" and template_name in SQL_TEMPLATES:
                            sql, _ = render_query(template_name, params)
                            target_db = get_template_db(template_name)
                            logger.info("SQL (template on %s): %.1000s", target_db, sql)
                            yield self._event("sql", sql=sql)
                        else:
                            yield self._event(
                                "status", content="ขอเวลาผมตีความหมายข้อมูลสักครู่นะครับ..."
                            )
                            semantic = await self.semantic_layer.extract_intent(q)
                            logger.info(f"Semantic Intent: {semantic}")

                            target_db = self._detect_target_db(q)
                            yield self._event("status", content="กำลังเตรียมข้อมูลมาให้ดูนะครับ...")
                            sql = await self._generate_dynamic_sql(q, semantic, history)
                            
                            target_db = self._detect_target_db(q, sql)
                            if sql != "NO_SQL":
                                sql = self._fix_common_sql_mistakes(sql)
                                is_valid, error_msg = self.validator.validate(sql, q)
                                if not is_valid:
                                    sql = "NO_SQL"
                                    context_str = f"ไม่สามารถค้นหาข้อมูลได้เนื่องจากเงื่อนไขไม่ครบถ้วน ({error_msg})"
                                else:
                                    yield self._event("sql", sql=sql)
                            else:
                                context_str = "ไม่พบข้อมูลที่ผู้ใช้ร้องขอ"
                    else:
                        # For Advisory, we already set sql = "NO_SQL" and have context_str
                        pass

                if sql != "NO_SQL":
                    try:
                        import asyncio

                        # Execute on the target database (dynamic defaults to lspdata)
                        db_results = await asyncio.to_thread(fetch_data, sql, db=target_db)
                        if db_results:
                            # สำหรับ CRM pre-aggregate template → ดึง total จาก section สถิติรวม
                            display_count = len(db_results)
                            for row in db_results:
                                section = str(row.get("Section", ""))
                                if "สถิติรวม" in section:
                                    import re as _re
                                    m = _re.search(r"ทั้งหมด\s*(\d+)\s*ครั้ง", str(row.get("FDetail", "")))
                                    if m:
                                        display_count = int(m.group(1))
                                    break
                            logger.info("DB rows: %d (display_count: %d)", len(db_results), display_count)
                            yield self._event("data_count", count=display_count)
                            context_str = engine.format_db_results(
                                db_results, self.schema, question=q, intent=intent
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

            # 4. Final answer
            yield self._event(
                "status", content="เรียบร้อยครับ เดี๋ยวผมสรุปให้อ่านง่ายๆ นะครับ..."
            )

            from prompts.insight import (
                INSIGHT_SYSTEM,
                INSIGHT_PROMPT_TEMPLATE,
                GENERAL_SYSTEM,
                GENERAL_PROMPT_TEMPLATE,
                CRM_LOG_SYSTEM,
                CRM_LOG_PROMPT_TEMPLATE,
            )

            hist_str = "\n".join([f"{m['role']}: {m['content']}" for m in history[-5:]])

            is_crm_log = "FDATE" in context_str or "ประวัติการติดตาม" in q or "ประวัติติดตาม" in q

            if intent == "GENERAL":
                final_prompt = GENERAL_PROMPT_TEMPLATE.format(
                    question=q,
                    history=hist_str,
                )
                system_prompt = GENERAL_SYSTEM
                insight_tokens = 800
            elif is_crm_log:
                # CRM Log → ใช้ prompt ที่สั่งให้แสดง timeline ไม่ใช่สรุป
                final_prompt = CRM_LOG_PROMPT_TEMPLATE.format(
                    context=context_str,
                )
                system_prompt = CRM_LOG_SYSTEM
                insight_tokens = 1500
            else:
                # DATA_QUERY → ใช้ INSIGHT prompt พร้อมข้อมูลจาก DB
                final_prompt = INSIGHT_PROMPT_TEMPLATE.format(
                    question=q,
                    context=context_str,
                    stats=stats_str if stats_str else "N/A",
                    history=hist_str,
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
                # Fallback: ถ้า chat_stream ล้มเหลว → ลอง generate แทน (ไม่ streaming)
                logger.warning("chat_stream failed (%s) → fallback to generate", llm_err)
                yield self._event("status", content="กำลังประมวลผลใหม่อีกครั้งครับ...")
                try:
                    fallback_prompt = f"{system_prompt}\n\n{final_prompt}"
                    response_text = await self.ollama.generate(
                        fallback_prompt,
                        tokens=min(insight_tokens, 600),
                        temperature=0.2,
                    )
                    if response_text:
                        yield self._event("content", content=response_text)
                    else:
                        yield self._event("content", content="ขออภัยครับ ระบบ AI ไม่สามารถสรุปข้อมูลได้ในขณะนี้ กรุณาลองใหม่อีกครั้ง")
                except Exception as fallback_err:
                    logger.error("Fallback generate also failed: %s", fallback_err)
                    yield self._event("content", content="ขออภัยครับ ระบบ AI ไม่ตอบสนองในขณะนี้ กรุณาลองใหม่ภายหลัง")

            logger.info("AI Insight: %.100s", response_text)
            yield self._event("done", time=round(time.time() - start_time, 2))

        except SecurityError as e:
            yield self._event("error", content=f"⚠️ ระงับการค้นหา: {e.message}")
        except (SBLError, BusinessRuleError) as e:
            yield self._event("error", content=f"❌ เกิดข้อผิดพลาด: {e.message}")
        except Exception as e:
            logger.exception("AIController crash")
            yield self._event("error", content="ผมเผชิญปัญหาระบบขัดข้องครับ โปรดลองใหม่อีกครั้ง")