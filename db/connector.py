"""
Database Connection Pool
- ใช้ connection pooling แทนการเปิด/ปิด connection ทุกครั้ง
- Thread-safe pool ด้วย threading.Lock
"""

import pyodbc
import logging
import threading
from contextlib import contextmanager
from typing import Generator

from config import DB_CONFIG
from core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_POOL_SIZE = 5

class _ConnectionPool:
    def __init__(self, dsn: str, size: int = _POOL_SIZE):
        self._dsn   = dsn
        self._lock  = threading.Lock()
        self._pool: list[pyodbc.Connection] = []
        self._size  = size

    def _new_conn(self) -> pyodbc.Connection:
        try:
            conn = pyodbc.connect(self._dsn, autocommit=True)
            # Keep connection alive on SQL Server
            conn.timeout = 30
            return conn
        except Exception as e:
            logger.error("DB connect failed: %s", e)
            raise DatabaseError(f"ไม่สามารถเชื่อมต่อฐานข้อมูลได้: {e}")

    @contextmanager
    def acquire(self) -> Generator[pyodbc.Connection, None, None]:
        conn = None
        with self._lock:
            if self._pool:
                conn = self._pool.pop()

        if conn is None:
            conn = self._new_conn()

        try:
            # Quick liveness check
            conn.execute("SELECT 1")
            yield conn
        except Exception:
            # Connection dead — close and give a fresh one
            try:
                conn.close()
            except Exception:
                pass
            conn = self._new_conn()
            yield conn
        finally:
            with self._lock:
                if len(self._pool) < self._size:
                    self._pool.append(conn)
                else:
                    try:
                        conn.close()
                    except Exception:
                        pass


_pool = _ConnectionPool(DB_CONFIG, size=_POOL_SIZE)


@contextmanager
def get_connection() -> Generator[pyodbc.Connection, None, None]:
    """Context manager: ดึง connection จาก pool และคืนกลับอัตโนมัติ"""
    with _pool.acquire() as conn:
        yield conn
