import pyodbc
import logging
from config import DB_CONFIG

logger = logging.getLogger(__name__)

def get_connection():
    """Returns a new pyodbc connection based on config."""
    try:
        conn = pyodbc.connect(DB_CONFIG)
        return conn
    except Exception as e:
        logger.error("Database connection failed: %s", e)
        raise
