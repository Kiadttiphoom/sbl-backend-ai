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

    # 4. Semantic Fallback (Handle Typos/Synonyms)
    # Only if dedicated EMBED_MODEL is configured
    semantic_result = _detect_semantic_intent(ql)
    if semantic_result:
        return semantic_result

    # 5. Weak keywords → confidence low
    for k in WEAK_DATA_KEYWORDS:
        if k.lower() in ql:
            matched.append(k)

    if matched:
        return {"intent": "DATA_QUERY", "confidence": "low", "matched": matched}

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
