import json
import logging
import re
from typing import Set, Dict
from config import STRONG_DATA_KEYWORDS, WEAK_DATA_KEYWORDS
from schema.loader import load_schema, extract_keywords

logger = logging.getLogger(__name__)

# Load schema once for keyword matching
SCHEMA = load_schema()

# ── Schema-based keywords (โหลดครั้งเดียวตอน import) ─────────────────────────

def _load_schema_keywords() -> Set[str]:
    """
    ดึง keywords จาก schema จริง (column names + Thai desc words)
    ใช้ extract_keywords() จาก schema_utils ที่มีอยู่แล้ว
    """
    try:
        return extract_keywords(SCHEMA)
    except Exception:
        return set()

_SCHEMA_KEYWORDS: Set[str] = _load_schema_keywords()


# ── Intent detection ──────────────────────────────────────────────────────────

def detect_intent(q: str) -> Dict:
    """
    คืน dict:
        intent     : "DATA_QUERY" | "GENERAL"
        confidence : "high" | "medium" | "low"
        matched    : list of matched keywords (สำหรับ debug)
    """
    ql      = q.lower()
    matched = []

    # Strong keywords → confidence high
    for k in STRONG_DATA_KEYWORDS:
        if k.lower() in ql:
            matched.append(k)

    if matched:
        return {"intent": "DATA_QUERY", "confidence": "high", "matched": matched}

    # Schema-derived keywords → confidence medium
    # ตรวจ column names และ Thai desc words จาก database_schema.json
    for k in _SCHEMA_KEYWORDS:
        if k and len(k) >= 3 and k in ql:   # >=3 ป้องกัน false positive จากคำสั้น
            matched.append(k)

    if matched:
        return {"intent": "DATA_QUERY", "confidence": "medium", "matched": matched}

    # Weak keywords → confidence low (อาจเป็น data query หรืออาจไม่ใช่)
    for k in WEAK_DATA_KEYWORDS:
        if k.lower() in ql:
            matched.append(k)

    if matched:
        return {"intent": "DATA_QUERY", "confidence": "low", "matched": matched}

    return {"intent": "GENERAL", "confidence": "high", "matched": []}
