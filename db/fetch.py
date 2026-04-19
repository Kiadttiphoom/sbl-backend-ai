"""
Data Fetcher
- ใช้ connection pool แทน get_connection() แบบเดิม
- OOM Protection: fetchmany(1000) คงเดิม
"""

import logging
from typing import List, Dict, Any

from db.connector import get_connection
from core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_FETCH_LIMIT = 1000


def fetch_data(sql: str) -> List[Dict[str, Any]]:
    """Executes SQL and returns a list of dicts (max 1,000 rows)."""
    try:
        with get_connection() as conn:
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
        logger.error("fetch_data error: %s | SQL: %.500s", e, sql)
        raise DatabaseError(f"คิวรีฐานข้อมูลล้มเหลว: {e}", details=sql)
