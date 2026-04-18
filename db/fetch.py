import logging
from typing import List, Dict, Any
from db.connector import get_connection
from core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

def fetch_data(sql: str) -> List[Dict[str, Any]]:
    """Executes SQL and returns a list of dictionaries."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        # Check if query returned rows
        if cursor.description:
            columns = [column[0] for column in cursor.description]
            # OOM Protection: จำกัดจำนวนแถวที่ดึงมาที่ 1,000 แถวแรกเด็ดขาด
            rows = cursor.fetchmany(1000)
            results = [dict(zip(columns, row)) for row in rows]
            return results
        return []
    except Exception as e:
        logger.error("Fetch data error: %s | SQL: %s", e, sql)
        raise DatabaseError(f"คิวรีฐานข้อมูลล้มเหลว: {str(e)}", details=sql)
    finally:
        conn.close()
