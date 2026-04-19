import os
import json
import logging
from typing import Dict, Any
from llm.ollama_client import OllamaClient
from config import SQL_MODEL

logger = logging.getLogger(__name__)


class SemanticLayer:
    def __init__(self, ollama: OllamaClient):
        self.ollama = ollama

    async def extract_intent(self, question: str) -> Dict[str, Any]:
        """
        Step 1: Convert NL to Business Intent (JSON)
        Uses the rich database_schema.json to map question to metrics/filters.
        """
        # Load the rich schema for context
        schema_path = os.path.join(
            os.path.dirname(__file__), "..", "data", "database_schema.json"
        )
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        guide = schema.get("_semantic_guide", {})

        prompt = f"""
You are a Financial Semantic Interpreter for SBL.
Your goal is to map a user question to a structured JSON intent using the BUSINESS CONTEXT below.

BUSINESS CONTEXT:
- Purpose: {guide.get('purpose')}
- Common Intents: {json.dumps(guide.get('common_intents'), ensure_ascii=False)}
- Amount Fields: {json.dumps(guide.get('amount_fields'), ensure_ascii=False)}
- Aging Groups: {json.dumps(guide.get('stat2_groups'), ensure_ascii=False)}

SCHEMA SUMMARY:
(Map natural language to these tables/columns)
- LSM010: Primary table for contracts, balances, interest, and status.
- LSM007: Employee/Officer table (Use for names).

RULES:
1. Identify the 'intent' (e.g., search, summary, aggregation).
2. Extract 'filters' (branch, amount, status, employee).
3. Map natural language terms to EXACT columns using the Amount Fields and Aging Groups.
4. Set 'include_names' to true ONLY IF the question EXPLICITLY asks for employee/officer names (e.g., "ชื่อ", "ผู้ดูแล", "พนักงาน"). If asking for contracts or amounts only, set to false.

Output ONLY JSON:
{{
  "intent": "...",
  "target_metrics": ["Bal", "Interest", ...],
  "filters": {{
    "OLID": "...",
    "Stat2": [...],
    "numeric_filters": [{{"field": "...", "op": ">", "val": 25000}}]
  }},
  "include_names": true/false
}}

Question: "{question}"
JSON:"""
        try:
            res = await self.ollama.generate(prompt, temperature=0, model=SQL_MODEL)
            # Basic JSON extraction
            start = res.find("{")
            end = res.rfind("}")
            if start != -1 and end != -1:
                return json.loads(res[start : end + 1])
        except Exception as e:
            logger.error(f"Semantic extraction failed: {e}")
        return {"intent": "unknown", "filters": {}}

    def build_sql_from_semantic(self, semantic: Dict[str, Any]) -> str:
        """
        Step 2: (Internal) Use the intent to guide SQL generation
        This is now more predictable because we know exactly what filters are needed.
        """
        # We will use this in AIController to pass better instructions to the SQL Generator
        pass
