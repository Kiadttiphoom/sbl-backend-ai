import json
import logging
import re
import math
from typing import Set, Dict, Optional, List
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

# ── Followup patterns (คำถามสั้นๆ ที่แสดงว่าต่อเนื่องจาก context เดิม) ─────────
_FOLLOWUP_PATTERNS = [
    r"^(แล้ว|แล้วก็|แล้วถ้า|แล้วของ)",       # "แล้วพนักงานคนนี้ล่ะ"
    r"(ของเขา|ของคนนี้|ของคนนั้|ของพนักงานนี้)",
    r"^(คนนี้|คนนั้น|เขา|เธอ|มัน|ตัวนี้|รายนี้)",
    r"^(แล้ว.{0,10}ล่ะ|.{0,15}ล่ะ$)",        # "แล้วยอดรวมล่ะ"
    r"^(กี่|เท่าไหร่|เท่าใด|มีกี่|รวม|ทั้งหมด).{0,20}$",  # คำถามสั้น เชิงตัวเลข
    r"(เพิ่มเติม|อีกคน|คนอื่น|รายอื่น)",
    r"^(ดู|แสดง|หา|เช็ค|ตรวจ).{0,15}(ด้วย|อีก|เพิ่ม)$",
]

def _is_followup(q: str, history: List[Dict]) -> bool:
    """
    ตรวจสอบว่าคำถามนี้เป็น followup ของ DATA_QUERY ก่อนหน้าหรือไม่
    เงื่อนไข: history ล่าสุดเป็น DATA_QUERY + คำถามสั้น/มี pronoun
    """
    if not history:
        return False

    # ดู assistant message ล่าสุดว่าเคยตอบ data มาก่อนไหม
    recent = [m for m in history[-4:] if m.get("role") == "assistant"]
    if not recent:
        return False

    last_answer = recent[-1].get("content", "")
    # ถ้า assistant เคยตอบ data (มีตาราง markdown หรือตัวเลข) → บริบทเป็น data
    has_data_context = (
        "|" in last_answer or           # markdown table
        any(c.isdigit() for c in last_answer[:200])
    )
    if not has_data_context:
        return False

    # ตรวจ pattern ของคำถามสั้น/pronoun
    ql = q.strip()
    for pattern in _FOLLOWUP_PATTERNS:
        if re.search(pattern, ql):
            logger.info("Followup detected via pattern '%s' for question: '%s'", pattern, q)
            return True

    # ถ้าคำถามสั้นมาก (≤ 15 ตัวอักษร) และมี data context → likely followup
    if len(ql) <= 15:
        logger.info("Followup detected via short question (%d chars): '%s'", len(ql), q)
        return True

    return False


# ── Intent detection ──────────────────────────────────────────────────────────

def detect_intent(q: str, history: Optional[List[Dict]] = None) -> Dict:
    """
    คืน dict:
        intent     : "DATA_QUERY" | "GENERAL"
        confidence : "high" | "medium" | "low"
        matched    : list of matched keywords (สำหรับ debug)

    Pipeline (เรียงตามลำดับ priority):
        1. Strong keywords  → DATA_QUERY high
        2. Followup context → DATA_QUERY medium  (NEW)
        3. Semantic vector  → DATA_QUERY medium
        4. Weak keywords    → DATA_QUERY low → ลอง SQL เลย ไม่ถามกลับ (CHANGED)
        5. ไม่ match เลย    → GENERAL high
    """
    ql      = q.lower()
    matched = []

    # 1. Strong keywords → confidence high
    for k in STRONG_DATA_KEYWORDS:
        if k.lower() in ql:
            matched.append(k)

    if matched:
        return {"intent": "DATA_QUERY", "confidence": "high", "matched": matched}

    # 2. Followup context (NEW) — ถ้า history บ่งชี้ว่าต่อเนื่องจาก data session
    if _is_followup(q, history or []):
        return {"intent": "DATA_QUERY", "confidence": "medium", "matched": ["followup_context"]}

    # 3. Semantic Fallback (Handle Typos/Synonyms)
    semantic_result = _detect_semantic_intent(ql)
    if semantic_result:
        return semantic_result

    # 4. Weak keywords → confidence "medium" แทน "low" เพื่อไม่ให้หยุดถามกลับ
    #    (ระบบจะลอง SQL เลย ถ้าผลออกมา empty ค่อยบอก user)
    for k in WEAK_DATA_KEYWORDS:
        if k.lower() in ql:
            matched.append(k)

    if matched:
        return {"intent": "DATA_QUERY", "confidence": "medium", "matched": matched}

    return {"intent": "GENERAL", "confidence": "high", "matched": []}


def _detect_semantic_intent(q: str) -> Optional[Dict]:
    """
    ใช้ Vector Similarity เพื่อตรวจสอบว่าคำถามเกี่ยวข้องกับข้อมูลการเงินหรือไม่
    (กันเหนียวกรณี User พิมพ์ผิด หรือใช้คำพ้องความหมาย)
    """
    from core.vector_store import _compute_embedding_sync
    
    # คำที่เป็น "ตัวแทน" ของ Data Query
    concepts = [
        "รายงานข้อมูลลูกหนี้", "ยอดค้างชำระทั้งหมด", "ค้นหาเลขบัญชีสัญญา",
        "สถานะลูกหนี้รายวัน", "ตรวจสอบยอดหนี้เฉลี่ย", "สรุปผลการดำเนินงาน"
    ]
    
    query_vec = _compute_embedding_sync(q)
    if not query_vec:
        return None
        
    for concept in concepts:
        concept_vec = _compute_embedding_sync(concept)
        if not concept_vec: continue
        
        # Calculate Cosine Similarity
        dot = sum(a*b for a, b in zip(query_vec, concept_vec))
        norm_a = math.sqrt(sum(a*a for a in query_vec))
        norm_b = math.sqrt(sum(b*b for b in concept_vec))
        score = dot / (norm_a * norm_b) if norm_a and norm_b else 0
        
        # Threshold 0.65 สำหรับ 3B model embedding
        if score > 0.65:
            logger.info("Semantic match found: '%s' matches concept '%s' (score: %.2f)", q, concept, score)
            return {"intent": "DATA_QUERY", "confidence": "medium", "matched": [f"semantic:{concept}"]}
            
    return None