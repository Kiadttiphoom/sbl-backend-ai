"""
Prompt Injection Detection
- Normalizes Unicode full-width / homoglyph characters before matching
- Covers SQL DDL/DML keywords and common jailbreak phrases
"""

import re
import unicodedata
from typing import Tuple

# ── Normalize Unicode (ป้องกัน full-width / lookalike bypass) ─────────────────
def _normalize(text: str) -> str:
    """NFKC normalization: ｄｒｏｐ → drop, ① → 1, etc."""
    return unicodedata.normalize("NFKC", text).lower()

# ── Injection patterns (applied on normalized text) ──────────────────────────
_INJECTION_PATTERNS = [re.compile(p, re.I) for p in [
    # Jailbreak / role override
    r"ignore\s+prev",
    r"system\s+prompt",
    r"new\s+role",
    r"developer\s+mode",
    r"jailbreak",
    r"you\s+are\s+now",
    r"forget\s+everything",
    r"reset\b",
    # Destructive SQL
    r"\bdrop\s+table\b",
    r"\btruncate\b",
    r"\bdelete\s+from\b",
    r"\binsert\s+into\b",
    r"\bupdate\s+\w+\s+set\b",
    r"\bxp_cmdshell\b",
    r"\bsp_execute\b",
    r"\bexec\s*\(",
    r"\bshutdown\b",
    r"\bgrant\b",
    r"\brevoke\b",
    r"\balter\s+(table|database|login)\b",
    # Classic injection probes
    r"select\s+\*\s+from\s+users",
    r"'?\s+or\s+'?1'?\s*=\s*'?1",
    r"--\s*$",
    r";\s*(drop|truncate|delete)",
]]


def detect_prompt_injection(query: str) -> Tuple[bool, str]:
    """
    Returns (is_injected, matched_pattern).
    Normalizes Unicode before matching to catch homoglyph bypasses.
    """
    normalized = _normalize(query)
    for pattern in _INJECTION_PATTERNS:
        if pattern.search(normalized):
            return True, pattern.pattern
    return False, None
