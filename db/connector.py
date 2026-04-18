import pyodbc
import logging
from config import DB_CONFIG
from core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

def get_connection() -> pyodbc.Connection:
    """Returns a new pyodbc connection based on config."""
    try:
        conn = pyodbc.connect(DB_CONFIG)
        return conn
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        raise DatabaseError(f"ไม่สามารถเชื่อมต่อฐานข้อมูลได้: {str(e)}")
