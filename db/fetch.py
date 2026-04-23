"""
Data Fetcher — Multi-Database
- ระบุ db="lspdata" หรือ db="crms" เพื่อเลือก connection pool
- OOM Protection: fetchmany(1000)
"""
import os
import logging
from typing import List, Dict, Any, Literal

import re
from db.connector import get_connection
from core.exceptions import DatabaseError
from config import LLM_TIMEOUT

logger = logging.getLogger(__name__)

_FETCH_LIMIT = 1000
# Type hint สำหรับช่วยบอกว่าใช้ alias อะไรได้บ้าง (str ธรรมดาเพื่อให้ dynamic)
DBName = str

def _get_env(key: str, default: str = None) -> str:
    val = os.getenv(key, default)
    if val and "{" in val:
        # Interpolate {VAR} patterns
        val = re.sub(r"\{(\w+)\}", lambda m: os.getenv(m.group(1), m.group(0)), val)
    return val


def fetch_data(sql: str, db: DBName = "lspdata") -> List[Dict[str, Any]]:
    """
    Executes SQL and returns a list of dicts (max 1,000 rows).

    Args:
        sql: SQL query string
        db:  "lspdata" (LSM010, LSM007) | "crms" (CRMDetail, CRMFol1, CRMFol2)
    """
    try:
        logger.info("Executing SQL [%s]:\n%s", db, sql)
        with get_connection(db) as conn:
            # ใช้ค่าจาก config ซึ่งเป็น int อยู่แล้ว
            conn.timeout = LLM_TIMEOUT
            cursor = conn.cursor()
            cursor.execute(sql)
            if not cursor.description:
                return []
            columns = [col[0] for col in cursor.description]
            rows    = cursor.fetchmany(_FETCH_LIMIT)
            return [dict(zip(columns, row)) for row in rows]
    except DatabaseError:
        raise
    except Exception as e:
        logger.error("fetch_data error [%s]: %s | SQL: %.500s", db, e, sql)
        raise DatabaseError(f"คิวรีฐานข้อมูลล้มเหลว: {e}", details=sql)
