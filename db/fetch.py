import logging
from db.connector import get_connection

logger = logging.getLogger(__name__)

def fetch_data(sql: str):
    """Executes SQL and returns a list of dictionaries."""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        # Check if query returned rows
        if cursor.description:
            columns = [column[0] for column in cursor.description]
            results = [dict(zip(columns, row)) for row in cursor.fetchall()]
            return results
        return []
    except Exception as e:
        logger.error("Fetch data error: %s | SQL: %s", e, sql)
        raise
    finally:
        conn.close()
