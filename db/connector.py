"""
Database Connection Pool — Config-Driven Multi-Database
─────────────────────────────────────────────────────────
เพิ่ม Database ใหม่: แค่เพิ่ม 1 บรรทัดใน config.py > DATABASES
  ไม่ต้องแก้ไฟล์นี้เลย!
"""

import pyodbc
import logging
import threading
from contextlib import contextmanager
from typing import Generator

from config import DATABASES
from core.exceptions import DatabaseError

logger = logging.getLogger(__name__)

_POOL_SIZE = 5


class _ConnectionPool:
    """Thread-safe connection pool สำหรับ 1 database."""

    def __init__(self, dsn: str, size: int = _POOL_SIZE):
        self._dsn   = dsn
        self._lock  = threading.Lock()
        self._pool: list[pyodbc.Connection] = []
        self._size  = size

    def _new_conn(self) -> pyodbc.Connection:
        try:
            conn = pyodbc.connect(self._dsn, autocommit=True)
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

        # liveness check — ใช้ explicit cursor เพื่อป้องกัน conn ถูกแทนที่ด้วย Cursor
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.close()
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
            conn = self._new_conn()

        try:
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


# ── Auto-create pools จาก DATABASES config ───────────────────────────────────
# เมื่อ dev เพิ่ม entry ใน DATABASES → pool ถูกสร้างอัตโนมัติ
_pools: dict[str, _ConnectionPool] = {
    name: _ConnectionPool(dsn) for name, dsn in DATABASES.items()
}
logger.info("DB pools initialized: %s", list(_pools.keys()))


@contextmanager
def get_connection(db: str = "lspdata") -> Generator[pyodbc.Connection, None, None]:
    """
    ดึง connection จาก pool ตาม alias ที่ลงทะเบียนใน config.py > DATABASES

    Args:
        db: alias ของ database เช่น "lspdata", "crms"
            (ดู list ทั้งหมดได้ใน config.py > DATABASES)

    Raises:
        DatabaseError: ถ้า alias ไม่ได้ register ไว้ใน DATABASES
    """
    pool = _pools.get(db)
    if pool is None:
        available = list(_pools.keys())
        raise DatabaseError(
            f"ไม่รู้จัก database alias '{db}' — "
            f"มีแค่: {available} "
            f"(เพิ่มใน config.py > DATABASES)"
        )
    with pool.acquire() as conn:
        yield conn


def available_databases() -> list[str]:
    """คืน list ของ database aliases ที่ register ไว้ทั้งหมด"""
    return list(_pools.keys())