import re
from typing import Tuple

# Block common prompt injection patterns
INJECTION_PATTERNS = [
    r"ignore prev", r"system prompt", r"new role", r"reset",
    r"delete all", r"drop table", r"truncate", r"select \* from users"
]

def detect_prompt_injection(query: str) -> Tuple[bool, str]:
    """
    Scans the query for known prompt injection patterns.
    Returns (is_injected, pattern_found).
    """
    for pattern in INJECTION_PATTERNS:
        if re.search(pattern, query, re.I):
            return True, pattern
    return False, None
