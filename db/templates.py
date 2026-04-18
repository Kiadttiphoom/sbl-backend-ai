from typing import Dict, Any, Tuple
import logging
import json
import os

logger = logging.getLogger(__name__)

# Load queries from JSON file
_QUERIES_PATH = os.path.join(os.path.dirname(__file__), "queries.json")

def _load_queries():
    """Load templates from JSON file."""
    with open(_QUERIES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

_QUERIES_DATA = _load_queries()

# Build SQL_TEMPLATES from JSON
SQL_TEMPLATES: Dict[str, str] = {
    name: template_info["sql"]
    for name, template_info in _QUERIES_DATA["templates"].items()
}

# Build TEMPLATE_DESCRIPTIONS from JSON
TEMPLATE_DESCRIPTIONS: Dict[str, str] = {
    name: template_info["description"]
    for name, template_info in _QUERIES_DATA["templates"].items()
}

# Get example questions for each template
TEMPLATE_EXAMPLES: Dict[str, list] = {
    name: template_info.get("example_questions", [])
    for name, template_info in _QUERIES_DATA["templates"].items()
}


def reload_queries():
    """Hot-reload queries from JSON without restarting server."""
    global SQL_TEMPLATES, TEMPLATE_DESCRIPTIONS, TEMPLATE_EXAMPLES, _QUERIES_DATA
    try:
        _QUERIES_DATA = _load_queries()
        SQL_TEMPLATES = {
            name: template_info["sql"]
            for name, template_info in _QUERIES_DATA["templates"].items()
        }
        TEMPLATE_DESCRIPTIONS = {
            name: template_info["description"]
            for name, template_info in _QUERIES_DATA["templates"].items()
        }
        TEMPLATE_EXAMPLES = {
            name: template_info.get("example_questions", [])
            for name, template_info in _QUERIES_DATA["templates"].items()
        }
        logger.info(f"✅ Reloaded {len(SQL_TEMPLATES)} templates from queries.json")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to reload queries: {e}")
        return False


def render_query(template_name: str, params: Dict[str, Any]) -> Tuple[str, list]:
    """
    แปลง template + params เป็น SQL string ที่พร้อมรัน

    - ทุก string param จะถูก escape ' → '' เพื่อป้องกัน injection
    - ตัวแปรพิเศษ :branch_filter และ :stat2_filter จะถูก render แยกต่างหาก
    """
    if template_name not in SQL_TEMPLATES:
        raise ValueError(f"Unknown query template: '{template_name}'")

    query = SQL_TEMPLATES[template_name]

    # ── Render special compound filters ───────────────────────────────────────

    # :branch_filter — optional WHERE clause
    if ":branch_filter" in query:
        bc = params.get("branch_code")
        if bc:
            safe_bc = str(bc).replace("'", "''")
            query = query.replace(":branch_filter", f"AND OLID = '{safe_bc}'")
        else:
            query = query.replace(":branch_filter", "")

    # :stat2_filter — Stat2 IN clause (single code or all warning codes)
    if ":stat2_filter" in query:
        sc = params.get("stat2_code")
        if sc and sc.upper() in ("B", "C", "D"):
            query = query.replace(":stat2_filter", f"LSM010.Stat2 = '{sc.upper()}'")
        else:
            # ไม่ระบุ = ดึงทุก warning group (B, C, D)
            query = query.replace(":stat2_filter", "LSM010.Stat2 IN ('B', 'C', 'D')")

    # ── Render standard :param placeholders ───────────────────────────────────
    for key, value in params.items():
        placeholder = f":{key}"
        if placeholder not in query:
            continue
        if value is None:
            query = query.replace(placeholder, "NULL")
        elif isinstance(value, int):
            query = query.replace(placeholder, str(value))
        else:
            safe_val = str(value).replace("'", "''")
            query = query.replace(placeholder, f"'{safe_val}'")

    logger.debug("Rendered SQL [%s]: %s", template_name, query)
    return query, []