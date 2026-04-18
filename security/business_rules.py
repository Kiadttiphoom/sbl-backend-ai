import logging
from typing import Tuple

logger = logging.getLogger(__name__)

def validate_business_logic(q: str, sql: str) -> Tuple[bool, str]:
    """
    Automated Validation Layer: Checks for keyword-code mismatches in Stat2.
    Ensures the LLM maps natural language terms to the correct database codes.
    """
    # Mapping of business terms to their required database codes
    # Use a string of codes separated by commas if multiple codes are required.
    stat2_mappings = {
        "ลูกหนี้ที่ถูกเตือนครั้งที่ 1 ถึง 3": "B,C,D", # กลุ่มเตือน 1-3
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
        "สาขา MF": "MF"
    }

    # Internal Mapping for specific columns
    col_mappings = {
        "1": "ACCSTAT",
        "2": "ACCSTAT",
        "AA": "OLID",
        "MA": "OLID",
        "MF": "OLID"
    }
    
    sql_upper = sql.upper()
    
    # 1. คัดกรองรหัสที่ "ต้องการ" จริงๆ จากคำถาม (แบบ Longest Match First)
    temp_q = q
    requested_codes = set()
    # เรียงลำดับคำสำคัญจากยาวไปสั้น เพื่อให้จับคำที่เจาะจงที่สุดก่อน (เช่น 'บอกเลิก 35 วัน' ก่อน 'บอกเลิก')
    sorted_keywords = sorted(stat2_mappings.keys(), key=len, reverse=True)
    
    for text in sorted_keywords:
        if text in temp_q:
            codes = stat2_mappings[text].split(",")
            requested_codes.update(codes)
            # ลบคำที่ถูก match แล้วออกด้วยพื้นที่ว่าง เพื่อไม่ให้คำสั้นกว่ามา match ซ้ำในที่เดิม
            temp_q = temp_q.replace(text, " " * len(text))
            
    if not requested_codes:
        return True, "ok"

    # 2. ตรวจสอบรหัสที่ "ปรากฏใน SQL" จริงๆ (มองหารหัสที่อยู่ใน single quotes ทั้งหมด)
    import re
    # ดึงค่าทุกอย่างที่อยู่ใน '...' ออกมาตรวจสอบ
    sql_codes_found = set(re.findall(r"'([^']+)'", sql_upper))
    
    # ดึงชื่อคอลัมน์ทั้งหมดใน SQL มาตรวจสอบความสอดคล้อง
    sql_cols_found = set(re.findall(r"(\w+)\s*(?:=|IN|LIKE)", sql_upper))

    # 3. ตรวจสอบความถูกต้อง
    # ก) ต้องมีรหัสที่ขอครบทุกตัว
    for code in requested_codes:
        if code not in sql_codes_found:
            return False, f"พบความต้องการข้อมูลรหัส '{code}' แต่ใน SQL ไม่มีการระบุรหัสนี้"
        
        # ตรวจสอบเพิ่มเติมเชื่อนโยงกับ Column (ถ้ามีใน mapping)
        if code in col_mappings:
            target_col = col_mappings[code]
            if target_col not in sql_cols_found:
                return False, f"โจทย์ระบุเงื่อนไข '{code}' ซึ่งต้องใช้คอลัมน์ {target_col} แต่ใน SQL ไม่พบการใช้งานคอลัมน์นี้"

    # ข) ห้ามมีรหัสที่ไม่ได้ขอแถมมา (Over-fetching Protection)
    # กัน AI มโนเงื่อนไข Aging (A,B,C,D,F,G,H) เพิ่มเองโดยไม่ได้รับอนุญาต
    aging_codes = {"A", "B", "C", "D", "F", "G", "H"}
    for code in sql_codes_found:
        if code in aging_codes and code not in requested_codes:
            # อนุญาตให้แถม 'A' ได้ถ้าไม่ได้ระบุเจาะจง (กรณี Default filter)
            if code != "A":
                return False, f"คำสั่ง SQL แอบดึงรหัสสถานะ Aging '{code}' เกินมา ทั้งที่โจทย์ไม่ได้สั่งให้ดึงกลุ่มหนี้ค้าง"
                
    return True, "ok"
                
    return True, "ok"
