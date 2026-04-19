"""
Business Rules Validation
- ตรวจสอบว่า SQL ที่ LLM สร้างมา map รหัส Stat2/ACCSTAT/OLID ถูกต้อง
- ป้องกัน over-fetching (AI มโนเงื่อนไข Aging เพิ่มโดยไม่ได้รับอนุญาต)
"""

import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# ── Stat2 / column mappings ───────────────────────────────────────────────────
_STAT2_MAPPINGS: dict[str, str] = {
    "ลูกหนี้ที่ถูกเตือนครั้งที่ 1 ถึง 3": "B,C,D",
    "เตือนครั้งที่ 1 ถึง 3": "B,C,D",
    "เตือน 1 ถึง 3": "B,C,D",
    "เตือน 1-3": "B,C,D",
    "กลุ่มเตือน": "B,C,D",
    "กลุ่มเร่งรัด": "B,C,D,F",
    "บอกเลิก 35 วัน": "F",
    "บอกเลิก 35": "F",
    "เตือนครั้งที่ 1": "B",
    "เตือน 1": "B",
    "เตือนครั้งที่ 2": "C",
    "เตือน 2": "C",
    "เตือนครั้งที่ 3 และยกเลิก": "D",
    "เตือนครั้งที่ 3": "D",
    "เตือน 3 ครั้ง": "D",
    "เตือน 3": "D",
    "บอกเลิก": "D",
    "ยกเลิก": "D",
    "35 วัน": "F",
    "ครบกำหนด 35": "F",
    "ติดคดี": "G",
    "ตัดหนี้": "H",
    "ปกติ": "A",
    "สูญ ปกติ": "A",
    "จ่ายครบ": "1",
    "จ่ายจบ": "1",
    "ปิดสด": "2",
    "สาขา AA": "AA",
    "สาขา MA": "MA",
    "สาขา MF": "MF",
}

_COL_MAPPINGS: dict[str, str] = {
    "1": "ACCSTAT",
    "2": "ACCSTAT",
    "AA": "OLID",
    "MA": "OLID",
    "MF": "OLID",
}

_AGING_CODES = frozenset({"A", "B", "C", "D", "F", "G", "H"})

# Pre-sort by length DESC once at module load
_SORTED_KEYWORDS = sorted(_STAT2_MAPPINGS.keys(), key=len, reverse=True)

_SQL_VALUE_RE = re.compile(r"'([^']+)'")
_SQL_COL_RE   = re.compile(r"(\w+)\s*(?:=|IN|LIKE)")


def validate_business_logic(q: str, sql: str) -> Tuple[bool, str]:
    """
    ตรวจสอบว่า SQL ที่ได้รับ map รหัส Stat2/ACCSTAT/OLID ตรงกับ
    สิ่งที่คำถามขอจริงๆ และไม่มีการ over-fetch รหัส Aging

    Returns (is_valid, reason)
    """
    sql_upper = sql.upper()

    # 1. หา requested codes จากคำถาม (Longest Match First)
    temp_q = q
    requested_codes: set[str] = set()
    for keyword in _SORTED_KEYWORDS:
        if keyword in temp_q:
            requested_codes.update(_STAT2_MAPPINGS[keyword].split(","))
            temp_q = temp_q.replace(keyword, " " * len(keyword))

    if not requested_codes:
        return True, "ok"

    # 2. หา codes และ columns ที่ปรากฏใน SQL จริงๆ
    sql_codes_found = set(_SQL_VALUE_RE.findall(sql_upper))
    sql_cols_found  = set(_SQL_COL_RE.findall(sql_upper))

    # 3a. ต้องมีรหัสที่ขอครบ
    for code in requested_codes:
        if code not in sql_codes_found:
            return False, f"พบความต้องการรหัส '{code}' แต่ใน SQL ไม่มีการระบุรหัสนี้"
        if code in _COL_MAPPINGS and _COL_MAPPINGS[code] not in sql_cols_found:
            target = _COL_MAPPINGS[code]
            return False, f"เงื่อนไข '{code}' ต้องใช้คอลัมน์ {target} แต่ SQL ไม่พบ"

    # 3b. ห้าม over-fetch รหัส Aging ที่ไม่ได้ขอ
    for code in sql_codes_found:
        if code in _AGING_CODES and code not in requested_codes and code != "A":
            return False, f"SQL แอบดึงรหัสสถานะ Aging '{code}' ที่โจทย์ไม่ได้ขอ"

    return True, "ok"
