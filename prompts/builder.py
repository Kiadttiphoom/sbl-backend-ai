from typing import Optional, Dict

def build_prompt(system: str, user: str, schema: Optional[Dict] = None) -> str:
    """
    สร้าง prompt สำหรับส่งให้ LLM
    - system : system instructions
    - user   : คำถามหรือ context จาก user
    - schema : dict จาก load_schema() (optional, ใส่เฉพาะตอนสร้าง SQL)
    """
    schema_part = ""
    if schema:
        schema_text = ""
        for table, info in schema.items():
            schema_text += f"\nTable: {table}"
            if "description" in info:
                schema_text += f"  -- {info['description']}"
            schema_text += "\n"

            if "columns" in info:
                for col, data in info["columns"].items():
                    desc        = data.get("desc", "")
                    col_type    = data.get("type", "")
                    remark      = data.get("remark", "")
                    is_pk       = " [PK]" if data.get("is_pk") else ""
                    remark_text = f" ({remark})" if remark else ""
                    schema_text += f"  - {col}{is_pk} [{col_type}] : {desc}{remark_text}\n"
        
        schema_part = f"[DATABASE_SCHEMA]\n{schema_text}"
    return f"{system}\n{schema_part}\n{user}\n[ASSISTANT_RESPONSE]\n"
