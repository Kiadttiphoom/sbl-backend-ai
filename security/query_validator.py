import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


class QueryValidator:
    @staticmethod
    def validate(sql: str, question: str) -> Tuple[bool, str]:
        """
        Validates SQL against locked business rules.
        Returns (is_valid, error_message)
        """
        sql_upper = sql.upper()

        # Rule 1: OLID for branch only
        # If 'สาขา' is in question, ensure OLID is used in WHERE
        if "สาขา" in question:
            if "OLID" not in sql_upper:
                return False, "กฎเหล็ก: เมื่อถามถึง 'สาขา' ต้องใช้คอลัมน์ OLID ในการกรองเท่านั้น"

        # Rule 2: FolID for people only
        # If person-related keywords are in question, check FolID usage
        person_keywords = ["คน", "ผู้ดูแล", "พนักงาน", "ใคร"]
        if any(k in question for k in person_keywords):
            if "FOLID" not in sql_upper and "FOLNAME" not in sql_upper:
                return (
                    False,
                    "กฎเหล็ก: เมื่อถามถึง 'คน/ผู้ดูแล' ต้องใช้คอลัมน์ FolID หรือ FolName เท่านั้น",
                )

        # Rule 3: Money columns must use CAST AS MONEY when compared (e.g., in WHERE or JOIN)
        money_cols = ["INTEREST", "CREDIT", "BAL"]
        for col in money_cols:
            # Look for patterns like "INTEREST >", "CREDIT =", etc.
            # We check if the column name appears near a comparison operator without a CAST
            comparison_pattern = rf"\b{col}\b\s*[>=<]"
            if re.search(comparison_pattern, sql_upper):
                # If found, ensure it is wrapped in CAST
                cast_pattern = rf"CAST\s*\(\s*{col}\s*AS\s*MONEY\s*\)\s*[>=<]"
                if not re.search(cast_pattern, sql_upper):
                    return (
                        False,
                        f"กฎเหล็ก: เมื่อมีการเปรียบเทียบคอลัมน์ {col} ต้องใช้ CAST({col} AS MONEY) เสมอ",
                    )

        # Rule 4: LSM007 must join IF SQL selects FOLNAME
        # Only enforce when SQL actually references FOLNAME — not just because question mentions "ชื่อ"
        if "FOLNAME" in sql_upper:
            if "JOIN" not in sql_upper or "LSM007" not in sql_upper:
                return False, "กฎเหล็ก: เมื่อ SELECT FolName ต้องมีการ JOIN LSM007 เสมอ"

        # Rule 5: NO LIMIT
        if "LIMIT" in sql_upper:
            return False, "กฎเหล็ก: ห้ามใช้คำสั่ง LIMIT ให้ใช้ TOP 100 แทน (SQL Server Syntax)"

        return True, "ok"
