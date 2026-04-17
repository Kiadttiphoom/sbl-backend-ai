import re
import logging
from typing import Tuple

logger = logging.getLogger(__name__)

class SQLGuard:
    def __init__(self):
        # Forbidden keywords for SQL Server 2008 (Read-only agent)
        self.forbidden = [
            "DROP", "DELETE", "UPDATE", "INSERT", "TRUNCATE", "ALTER", "CREATE",
            "EXEC", "PROCEDURE", "UNION", "GRANT", "REVOKE", "XP_"
        ]

    def sanitize(self, sql: str) -> str:
        """Cleans the SQL string of comments and potentially dangerous characters."""
        # Remove SQL comments
        sql = re.sub(r'--.*', '', sql)
        sql = re.sub(r'/\*.*?\*/', '', sql, flags=re.S)
        return sql.strip()

    def validate(self, sql: str) -> Tuple[bool, str]:
        """Validates that the SQL is read-only and doesn't contain forbidden patterns."""
        sql_upper = sql.upper()
        
        # Check for forbidden keywords
        for word in self.forbidden:
            if re.search(rf"\b{word}\b", sql_upper):
                return False, f"Forbidden keyword detected: {word}"
        
        # Ensure it's a SELECT statement
        if not sql_upper.startswith("SELECT"):
            return False, "Only SELECT statements are allowed"
            
        return True, "ok"

def sanitize_sql_values(sql: str) -> Tuple[bool, str]:
    """Checks for suspicious patterns inside string literals (Injection)."""
    string_literals = re.findall(r"'([^']*)'", sql)
    for lit in string_literals:
        if re.search(r"(;|\b(DROP|DELETE|INSERT|UPDATE|EXEC|UNION)\b)", lit, re.I):
            return False, f"Suspicious value in SQL literal: {lit[:50]}"
    return True, "ok"

guard = SQLGuard()
