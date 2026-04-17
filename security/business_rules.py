import logging
from typing import Tuple

logger = logging.getLogger(__name__)

def validate_business_logic(q: str, sql: str) -> Tuple[bool, str]:
    """
    Automated Validation Layer: Checks for keyword-code mismatches in Stat2.
    Ensures the LLM maps natural language terms to the correct database codes.
    """
    # Mapping of business terms to their required database codes
    stat2_mappings = {
        "เตือนครั้งที่ 1": "B",
        "เตือน 1": "B",
        "เตือนครั้งที่ 2": "C",
        "เตือน 2": "C",
        "เตือนครั้งที่ 3": "D",
        "เตือน 3 ครั้ง": "D",
        "บอกเลิก": "D",
        "ยกเลิก": "D",
        "35 วัน": "F",
        "ครบกำหนด 35": "F",
        "ติดคดี": "G",
        "ตัดหนี้": "H",
        "ปกติ": "A",
        "สูญ ปกติ": "A"
    }
    
    sql_upper = sql.upper()
    
    # 1. คัดกรองรหัสที่ "ต้องการ" จริงๆ จากคำถาม
    requested_codes = set()
    for text, code in stat2_mappings.items():
        if text in q:
            requested_codes.add(code)
            
    if not requested_codes:
        return True, "ok"

    # 2. ตรวจสอบรหัสที่ "ปรากฏใน SQL" จริงๆ (มองหา 'X' ที่อยู่หลัง Stat2)
    import re
    # ค้นหาเงื่อนไข Stat2 = 'X' หรือ Stat2 IN ('A', 'B')
    matches = re.findall(r"STAT2\s*(?:=|IN)\s*\(?\s*((?:'[^']+'\s*,?\s*)+)\)?", sql_upper)
    
    sql_codes = set()
    for match in matches:
        # ดึงตัวอักษรข้างใน single quotes ออกมา
        codes_in_match = re.findall(r"'([^']+)'", match)
        sql_codes.update(codes_in_match)

    # 3. ตรวจสอบความถูกต้อง
    # ก) ต้องมีรหัสที่ขอครบทุกตัว
    for code in requested_codes:
        if code not in sql_codes:
            return False, f"พบความต้องการสถานะที่ต้องใช้รหัส '{code}' แต่ใน SQL ไม่มีรหัสนี้"

    # ข) ห้ามมีรหัสที่ไม่ได้ขอแถมมา (Over-fetching)
    # ยกเว้นกรณีคำถามกว้างๆ แต่นี่คือการ Hardening เพื่อความแม่นยำ
    for code in sql_codes:
        if code not in requested_codes:
            return False, f"คำสั่ง SQL แอบดึงรหัสสถานะ '{code}' เกินมา ทั้งที่คำถามเจาะจงแค่ {list(requested_codes)}"
                
    return True, "ok"
