import os
import sys
from dotenv import load_dotenv
load_dotenv()
# ── Helper (ต้องอยู่ก่อนทุกอย่าง) ────────────────────────────────────────────

def _require_env(key: str) -> str:
    val = os.getenv(key)
    if not val:
        print(f"[FATAL] Environment variable '{key}' is required but not set.", file=sys.stderr)
        sys.exit(1)
    return val

# ── LLM ──────────────────────────────────────────────────────────────────────

OLLAMA_ENDPOINT_1 = os.getenv("OLLAMA_ENDPOINT_1", "http://192.168.2.18:11434/api/generate")
OLLAMA_ENDPOINT_2 = os.getenv("OLLAMA_ENDPOINT_2", "http://192.168.2.18:11434/api/chat")

# MODEL_NAME  = ใช้ตอบ user (เล็ก เร็ว)
# SQL_MODEL   = ใช้สร้าง SQL (ใหญ่ แม่น)
MODEL_NAME  = os.getenv("MODEL_NAME",  "qwen2.5:3b")
SQL_MODEL   = os.getenv("SQL_MODEL",   "qwen2.5-coder:3b")

LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

# ── Database ──────────────────────────────────────────────────────────────────

# Database Configuration (pyodbc)
SQL_SERVER = os.getenv("DB_SERVER", "DB_SERVER_ADDRESS")
DATABASE   = os.getenv("DB_NAME",   "DBNAME")
DB_USER    = os.getenv("DB_USER",   "USERNAME")
DB_PASSWORD = os.getenv("DB_PASS", "PASSWORD")

# Connection String for SQL Server 2008 / Standard
# SECURITY WARNING: แนะนำให้ใช้ Database User ที่มีสิทธิ์เฉพาะ SELECT (Read-only) 
# บน Table ที่จำเป็นเท่านั้น เพื่อป้องกันความเสียหายกรณีเกิด SQL Injection
DB_CONFIG = (
    f"DRIVER={{SQL Server}};"
    f"SERVER={SQL_SERVER};"
    f"DATABASE={DATABASE};"
    f"UID={DB_USER};"
    f"PWD={DB_PASSWORD};"
)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEW_SHOT_PATH = os.path.join(BASE_DIR, "data", "few_shot_examples.json")
SCHEMA_PATH   = os.path.join(BASE_DIR, "data", "database_schema.json")

# ── Security ──────────────────────────────────────────────────────────────────

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

# ── Intent keywords ───────────────────────────────────────────────────────────

STRONG_DATA_KEYWORDS = [
    "ยอด", "ยอดหนี้", "ยอดคงเหลือ", "บัญชี", "สัญญา",
    "loan", "balance", "ลูกหนี้", "ดอกเบี้ย",
    "accno", "cusid", "สถานะ", "งวด", "ค่างวด",
    "เลขที่", "เลขสัญญา", "หมายเลข", "รหัส",
]

WEAK_DATA_KEYWORDS = [
    "เท่าไหร่", "กี่", "ราคา", "เงิน", "ค้าง",
    "เท่าใด", "จำนวน", "ทั้งหมด",
]