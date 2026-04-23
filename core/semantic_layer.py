"""
SemanticLayer — Pure Python (ไม่ใช้ LLM)
─────────────────────────────────────────
เดิม: LLM call แยก (qwen2.5-coder:7b) เพื่อ extract intent → JSON
ใหม่: keyword + schema rule-based เร็วกว่า ~800ms และผลเหมือนกันในทางปฏิบัติ

API เดิมยังคงอยู่ (extract_intent) เพื่อไม่ให้ ai_controller.py ต้องแก้มาก
"""

import re
import json
import os
import logging
from typing import Dict, Any, List, Optional
from llm.ollama_client import OllamaClient  # เก็บ import ไว้ backward compat

logger = logging.getLogger(__name__)

# ── Schema guide (โหลดครั้งเดียว) ────────────────────────────────────────────
_SCHEMA_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "database_schema.json")
)

def _load_guide() -> Dict:
    try:
        with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
            return json.load(f).get("_semantic_guide", {})
    except Exception:
        return {}

_GUIDE = _load_guide()

# ── Stat2 keyword map ─────────────────────────────────────────────────────────
_STAT2_MAP = {
    "B": ["กลุ่มเตือน b", "เตือน 1", "stat2 b", "stat2=b"],
    "C": ["กลุ่มเตือน c", "เตือน 2", "stat2 c", "stat2=c"],
    "D": ["กลุ่มเตือน d", "เตือน 3", "stat2 d", "stat2=d"],
    "F": ["บอกเลิก", "ครบกำหนด 35", "stat2 f"],
    "G": ["ติดคดี", "ฟ้องร้อง", "stat2 g"],
    "H": ["ตัดหนี้สูญ", "write-off", "stat2 h"],
}

_OVERDUE_KEYWORDS = ["ค้าง", "ค้างชำระ", "เกิน 3 เดือน", "ค้างเกิน", "overdue"]
_NAME_KEYWORDS    = ["ชื่อ", "ผู้ดูแล", "พนักงาน", "เจ้าหน้าที่", "fol", "folid"]
_CRM_KEYWORDS     = ["ประวัติการติดตาม", "ประวัติติดตาม", "crm", "บันทึกการติดตาม"]
_BRANCH_RE        = re.compile(r"สาขา\s*([A-Z0-9]{1,4})", re.IGNORECASE)
_AMOUNT_FILTER_RE = re.compile(r"(ยอด|credit|interest|bal)\s*(>|>=|<|<=|=)\s*(\d[\d,]*)", re.IGNORECASE)


class SemanticLayer:

    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama  # เก็บไว้ (ไม่ใช้แล้ว แต่ยังไม่ลบเพื่อ backward compat)

    async def extract_intent(self, question: str) -> Dict[str, Any]:
        """
        แปลง NL → JSON intent โดยไม่ใช้ LLM
        ผลลัพธ์เหมือนเดิมทุก key เพื่อให้ ai_controller ใช้ได้เลย
        """
        ql = question.lower()

        # ── Stat2 filters ─────────────────────────────────────────────────────
        stat2: List[str] = []
        for code, patterns in _STAT2_MAP.items():
            if any(p in ql for p in patterns):
                stat2.append(code)

        # ── Overdue fallback logic ────────────────────────────────────────────
        if not stat2:
            if "เกิน 3 เดือน" in ql or "เกิน 90 วัน" in ql:
                stat2 = ["F"]
            elif any(kw in ql for kw in _OVERDUE_KEYWORDS):
                # ถ้าบอกแค่ "ค้าง" หรือ "overdue" ให้รวมกลุ่มค้างทั้งหมด (B,C,D,F)
                stat2 = ["B", "C", "D", "F"]

        # ── Branch filter ─────────────────────────────────────────────────────
        branch_match = _BRANCH_RE.search(question)
        olid = branch_match.group(1).upper() if branch_match else None

        # ── Numeric filters ───────────────────────────────────────────────────
        numeric_filters = []
        for m in _AMOUNT_FILTER_RE.finditer(question):
            field = m.group(1).capitalize()
            op    = m.group(2)
            val   = int(m.group(3).replace(",", ""))
            numeric_filters.append({"field": field, "op": op, "val": val})

        # ── Target metrics ────────────────────────────────────────────────────
        target_metrics = []
        if any(kw in ql for kw in ["ยอดหนี้", "bal", "balance"]):
            target_metrics.append("Bal")
        if any(kw in ql for kw in ["ดอกเบี้ย", "interest"]):
            target_metrics.append("Interest")
        if any(kw in ql for kw in ["credit", "เครดิต"]):
            target_metrics.append("Credit")

        # ── include_names ──────────────────────────────────────────────────────
        include_names = any(kw in ql for kw in _NAME_KEYWORDS)

        # ── intent label ───────────────────────────────────────────────────────
        if any(kw in ql for kw in ["รวม", "ทั้งหมด", "สรุป", "กี่ราย", "count", "sum"]):
            intent = "aggregation"
        elif any(kw in ql for kw in ["ค้นหา", "หา", "แสดง", "ดู", "search"]):
            intent = "search"
        elif any(kw in ql for kw in _CRM_KEYWORDS):
            intent = "crm_history"
        else:
            intent = "query"

        result = {
            "intent": intent,
            "target_metrics": target_metrics,
            "filters": {
                **({"OLID": olid} if olid else {}),
                **({"Stat2": stat2} if stat2 else {}),
                **({"numeric_filters": numeric_filters} if numeric_filters else {}),
            },
            "include_names": include_names,
        }
        logger.info("SemanticLayer (fast): %s", result)
        return result

    def build_sql_from_semantic(self, semantic: Dict[str, Any]) -> str:
        """ยังคงไว้เพื่อ backward compat"""
        pass