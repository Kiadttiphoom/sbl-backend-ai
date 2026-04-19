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

LLM_TIMEOUT: int = int(_get_env("LLM_TIMEOUT", "120"))

# ── Database ──────────────────────────────────────────────────────────────────

# Database Configuration (pyodbc)
SQL_SERVER: str = _get_env("DB_SERVER")
DATABASE: str   = _get_env("DB_NAME")
DB_USER: str    = _get_env("DB_USER")
DB_PASSWORD: str = _get_env("DB_PASS")

# Connection String for SQL Server
DB_DRIVER: str = _get_env("DB_DRIVER", "SQL Server")
DB_CONFIG: str = (
    f"DRIVER={{{DB_DRIVER}}};"
    f"SERVER={SQL_SERVER};"
    f"DATABASE={DATABASE};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
)

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