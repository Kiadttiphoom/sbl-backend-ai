import os
import sys
from dotenv import load_dotenv
load_dotenv()
# ── Helper (ต้องอยู่ก่อนทุกอย่าง) ────────────────────────────────────────────

import re

def _get_env(key: str, default: str = None) -> str:
    val = os.getenv(key, default)
    if val and "{" in val:
        # Interpolate {VAR} patterns
        val = re.sub(r"\{(\w+)\}", lambda m: os.getenv(m.group(1), m.group(0)), val)
    return val

def _require_env(key: str) -> str:
    val = _get_env(key)
    if not val:
        print(f"[FATAL] Environment variable '{key}' is required but not set.", file=sys.stderr)
        sys.exit(1)
    return val

# ── LLM ──────────────────────────────────────────────────────────────────────

from typing import List, Optional

OLLAMA_ENDPOINT_1: Optional[str] = _get_env("OLLAMA_ENDPOINT_1")
OLLAMA_ENDPOINT_2: Optional[str] = _get_env("OLLAMA_ENDPOINT_2")
OLLAMA_BASE_URL: Optional[str]   = _get_env("OLLAMA_BASE_URL")

# MODEL_NAME  = ใช้ตอบ user (เล็ก เร็ว)
# SQL_MODEL   = ใช้สร้าง SQL (ใหญ่ แม่น)
MODEL_NAME: str  = _get_env("MODEL_NAME")
SQL_MODEL: str   = _get_env("SQL_MODEL")

LLM_TIMEOUT: int = int(_get_env("LLM_TIMEOUT", "180"))

# ── Database ──────────────────────────────────────────────────────────────────

from typing import List, Optional, Dict

def _build_dsn_from_env(prefix: str) -> str:
    """
    สร้าง ODBC DSN โดยอ่านค่าจาก .env ตาม prefix (เช่น LSPDATA, CRMS)
    เช่น DB_SERVER_{PREFIX}, DB_USER_{PREFIX}, ...
    """
    server   = _get_env(f"DB_SERVER_{prefix}")
    database = _get_env(f"DB_NAME_{prefix}")
    user     = _get_env(f"DB_USER_{prefix}")
    password = _get_env(f"DB_PASS_{prefix}")
    driver   = _get_env(f"DB_DRIVER_{prefix}", "SQL Server")
    
    if not all([server, database, user, password]):
        # Fallback เพื่อให้พังเร็วขึ้นถ้า config ไม่ครบ
        return f"INVALID_CONFIG_FOR_{prefix}"

    return (
        f"DRIVER={{{driver}}};"
        f"SERVER={server};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
    )


# ┌────────────────────────────────────────────────────────────────────────┐
# │ ⚡ REGISTRY: รวมท่อเชื่อมต่อ Database ทั้งหมดในระบบ                        │
# │ วิธีเพิ่ม: 1. เพิ่ม alias ในนี้  2. เพิ่มประกาศตัวแปรใน .env ให้ครบตามชุด         │
# └────────────────────────────────────────────────────────────────────────┘
DATABASES: Dict[str, str] = {
    # [ชุดที่ 1] ระบบเช่าซื้อหลัก (Lspdata) -> ใช้ตาราง LSM010, LSM007
    "lspdata":  _build_dsn_from_env("LSPDATA"),

    # [ชุดที่ 2] ระบบ CRM (crms) -> ใช้ตาราง CRMDetail, CRMFol1, CRMFol2
    "crms":     _build_dsn_from_env("CRMS"),

    # [ชุดที่ 3] สำหรับเพิ่มเองในอนาคต (แค่เอา # ออก และตั้งชื่อ Prefix ใน .env เป็น DB3)
    # "db3":    _build_dsn_from_env("DB3"),

    # [ชุดที่ 4] สำหรับเพิ่มเองในอนาคต (แค่เอา # ออก และตั้งชื่อ Prefix ใน .env เป็น DB4)
    # "db4":    _build_dsn_from_env("DB4"),
}


# Paths
BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
FEW_SHOT_PATH: str = os.path.join(BASE_DIR, "data", "few_shot_examples.json")
SCHEMA_PATH: str   = os.path.join(BASE_DIR, "data", "database_schema.json")

# ── Security ──────────────────────────────────────────────────────────────────

ALLOWED_ORIGINS: List[str] = _get_env("ALLOWED_ORIGINS", "").split(",")

# ── Intent keywords ───────────────────────────────────────────────────────────

STRONG_DATA_KEYWORDS: List[str] = [
    "ยอด", "ยอดหนี้", "ยอดคงเหลือ", "บัญชี", "สัญญา",
    "loan", "balance", "ลูกหนี้", "ดอกเบี้ย",
    "accno", "cusid", "สถานะ", "งวด", "ค่างวด",
    "เลขที่", "เลขสัญญา", "หมายเลข", "รหัส",
]

WEAK_DATA_KEYWORDS: List[str] = [
    "เท่าไหร่", "กี่", "ราคา", "เงิน", "ค้าง",
    "เท่าใด", "จำนวน", "ทั้งหมด",
]