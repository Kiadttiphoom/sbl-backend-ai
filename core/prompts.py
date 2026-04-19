import json
from typing import Dict, Any

def get_dynamic_sql_prompt(schema_text: str, semantic: Dict[str, Any], question: str) -> str:
    """
    Returns the system prompt for SQL generation.
    NO hardcoded mappings here. All logic is driven by schema and semantic intent.
    """
    semantic_json = json.dumps(semantic, ensure_ascii=False) if semantic else "{}"
    
    return f"""
You are an expert SQL Server 2008 developer.
DATABASE SCHEMA:
{schema_text}

SEMANTIC INTENT (GUIDE):
{semantic_json}

CORE PRINCIPLES:
1. DYNAMICISM: Rely SOLELY on the SCHEMA. NEVER hardcode mappings in your logic.
2. MINIMALISM: Select ONLY asked columns. NO EXTRA COLUMNS.
3. NO ALIAS: Use original names from the schema ONLY. NEVER use "AS".
4. SYNTAX: SQL Server 2008 (Use TOP 100).
5. MONEY: Use CAST(column AS MONEY) for numeric filters in WHERE clause.
6. FORMAT: Output RAW T-SQL only. No markdown, no comments.

Question: "{question}"
"""
