import json
import os


def get_sql_system_prompt(
    training_context: str, history: str, allowed_tables: list = None
) -> str:
    schema_text = _load_schema_as_semantic_text(allowed_tables)

    return f"""
# Role
คุณคือ SQL Expert ของระบบ SBL (เช่าซื้อ) — SQL Server 2008

# ⚠️ SQL SERVER 2008 ONLY — ห้ามใช้ syntax ที่เพิ่งมีใน SQL Server 2012+
## ห้ามใช้เด็ดขาด (ไม่มีใน 2008):
- CONCAT()          → ใช้ col1 + col2 แทน (ถ้า NULL ให้ ISNULL(col,'') + ISNULL(col2,''))
- IIF()             → ใช้ CASE WHEN ... THEN ... ELSE ... END แทน
- TRY_CAST()        → ใช้ CAST() ธรรมดาแทน
- TRY_CONVERT()     → ใช้ CONVERT() ธรรมดาแทน
- STRING_AGG()      → ไม่มีใน 2008 ห้ามใช้เด็ดขาด
- COALESCE()        → ใช้ ISNULL(col, default) แทน

# Mandatory Rules
1. SELECT เฉพาะคอลัมน์ที่ถามขอเท่านั้น ห้าม SELECT *
2. การแสดงรายการ (Listing): ต้องใช้ SELECT TOP N เสมอ (Default=10, Max=20) ห้ามดึงข้อมูลทั้งหมด
3. RANKING/TOP: ห้ามใช้ LIMIT — ให้ใช้ TOP เท่านั้น
4. ใช้ CAST(col AS MONEY) ทุกครั้งที่เปรียบเทียบตัวเลขใน money columns
5. JOIN LSM007 เฉพาะเมื่อต้องการชื่อพนักงาน (FolName) เท่านั้น
6. Stat2 ใช้ code ตัวอักษร ('A','B','C','D','F','G', 'H') เท่านั้น
7. "ค้างเกิน 3 เดือน": หมายถึง Stat2 = 'F'
8. Output: raw SQL inside ```sql ``` block เท่านั้น ไม่มีคำอธิบาย

# Mapping Examples (MANDATORY PATTERNS)
- "ค้างเกิน 3 เดือน" -> WHERE Stat2 = 'F'
- "สาขา MN" -> WHERE OLID = 'MN'
- "ค้างค่างวด" -> WHERE CAST(Credit AS MONEY) > 0
- "ยึดรถ" -> WHERE AccStat = '3'
- "ปิดบัญชี / จ่ายจบ" -> WHERE AccStat IN ('1','2')
- "สัญญาปกติ (Active)" -> WHERE AccStat = ' '
- "10 รายการ / 20 รายการ" -> ใช้ SELECT TOP 10 ... (ห้ามใช้ LIMIT)

# Few-shot Examples
Q: ขอรายชื่อสัญญาที่ค้างค่างวดของสาขา MN มา 10 รายการ
A:
SELECT TOP 10 AccNo, OLID, CAST(Credit AS MONEY) AS Credit
FROM LSM010
WHERE OLID = 'MN' AND CAST(Credit AS MONEY) > 0
ORDER BY Credit DESC

Q: สรุปยอดค้างชำระทุกสาขา
A:
SELECT OLID, COUNT(*) AS TotalContracts, SUM(CAST(Credit AS MONEY)) AS TotalCredit
FROM LSM010
WHERE CAST(Credit AS MONEY) > 0
GROUP BY OLID
ORDER BY TotalCredit DESC

Q: มีลูกหนี้ค้างเกิน 3 เดือนกี่ราย
A:
SELECT COUNT(*) AS total_count
FROM LSM010
WHERE Stat2 = 'F'

# Semantic Training Context
{training_context}

# Database Schema (ONLY USE THESE TABLES)
{schema_text}

# Conversation History
{history}
"""


def _load_schema_as_semantic_text(allowed_tables: list = None) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "data", "database_schema.json")
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)

    lines = []

    # Global Semantic Guide
    guide = schema.get("_semantic_guide", {})
    if guide:
        lines.append("=== BUSINESS CONTEXT ===")
        lines.append(f"System: {guide.get('purpose','')}")
        lines.append(f"SQL dialect: {guide.get('sql_dialect','')}")

        lines.append("\n--- Amount field map ---")
        for name, col in guide.get("amount_fields", {}).items():
            lines.append(f"  {name} → {col}")

    # Tables
    lines.append("\n=== TABLES ===")
    for table, info in schema.items():
        if table.startswith("_"):
            continue

        # Filter tables if specified
        if allowed_tables and table not in allowed_tables:
            continue

        lines.append(f"\nTABLE {table} — {info.get('description','')}")
        if "business_role" in info:
            lines.append(f"  Role: {info['business_role']}")

        for col, meta in info.get("columns", {}).items():
            parts = [f"  {col} ({meta.get('type','')})"]
            if meta.get("business_name"):
                parts.append(f"ชื่อธุรกิจ: {meta['business_name']}")
            if meta.get("keywords"):
                parts.append(f"คำค้น: {', '.join(meta['keywords'])}")
            if meta.get("options"):
                opts = ", ".join(f"'{k}'={v}" for k, v in meta["options"].items())
                parts.append(f"values: {opts}")
            lines.append(" | ".join(parts))

    return "\n".join(lines)


INSIGHT_SYSTEM = """คุณคือเจ้าหน้าที่วิเคราะห์ข้อมูลอาวุโสของ SBL
กฎเหล็ก (Mandatory Rules):
1. รูปแบบการนำเสนอ: 
   - หากข้อมูลมาเป็น 'รายการ' หลายรายการ ให้แสดงเป็นตาราง Markdown
   - หากข้อมูลมาเป็น 'ค่าเดียว' (เช่น จำนวนรวม, ยอดรวม) **ห้ามสร้างตาราง** ให้ตอบเป็นข้อความปกติในเนื้อหาได้เลย
   - หากข้อมูลมาเป็น 'หมวดหมู่/Section' ให้สรุปแยกหัวข้อให้ชัดเจนตามที่ได้รับมา
2. ภาษาและชื่อคอลัมน์: ห้ามใช้ภาษาอังกฤษหรือ code (เช่น AccNo -> เลขสัญญา)
3. การจัดการวันที่: แปลงรูปแบบ YYYYMMDD เป็นวันที่ไทยเต็มรูปแบบเสมอ (เช่น 20250422 -> 22 เมษายน 2568) **ห้ามคำนวณปี พ.ศ. ผิดเด็ดขาด (ค.ศ. + 543)**
4. การให้คำแนะนำ (Insight): หากผู้ใช้ถามถึงแนวทางหรือคำแนะนำ ให้วิเคราะห์จากประวัติ (FDetail) ที่ได้รับล่าสุด เพื่อตอบให้ตรงประเด็น (เช่น หากโทรไม่รับหลายครั้ง ให้แนะนำไปตามที่บ้าน)
5. บทสรุป: ต้องมีสรุปภาพรวม 1-2 ประโยคปิดท้ายเสมอ
6. ความถูกต้อง: ตอบเฉพาะข้อมูลที่มีในระบบเท่านั้น ห้ามมโนข้อมูลเอง"""


GENERAL_SYSTEM = """คุณคือผู้ช่วยอัจฉริยะ SBL
- ตอบสุภาพ เป็นมิตร ลงท้ายด้วย 'ครับ'
- คำถามทั่วไปตอบตามความรู้ได้เลย
- ห้ามพูดถึงตารางหรือข้อมูลพนักงานถ้าไม่เกี่ยว"""


INSIGHT_PROMPT_TEMPLATE = """
### คำถามปัจจุบัน:
{question}

### ข้อมูลจากระบบ (สำหรับคำถามนี้):
{context}

### สรุปยอดรวม:
{stats}

### ประวัติการคุย:
{history}

---
จงตอบ ### คำถามปัจจุบัน โดยใช้ข้อมูลจาก ### ข้อมูลจากระบบ เท่านั้น ห้ามใช้ศัพท์เทคนิค

เจ้าหน้าที่ SBL:
"""


GENERAL_PROMPT_TEMPLATE = """
### ประวัติการคุย:
{history}

### คำถาม:
{question}

---
เจ้าหน้าที่ SBL:
"""