import json
import logging
import os
from typing import Dict, Set, Optional, Any

logger = logging.getLogger(__name__)

def load_schema(path: Optional[str] = None) -> Dict[str, Any]:
    """Loads the database schema from a JSON file."""
    # If no path provided, use config's SCHEMA_PATH
    if path is None:
        from config import SCHEMA_PATH
        path = SCHEMA_PATH
    
    if not os.path.exists(path):
        logger.error("Schema file not found: %s", path)
        return {}
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Error loading schema: %s", e)
        return {}

def extract_keywords(schema: Dict[str, Any]) -> Set[str]:
    """Extracts all table and column descriptions as keywords for intent matching."""
    keywords: Set[str] = set()
    for table, info in schema.items():
        if "description" in info:
            keywords.add(info["description"].lower())
        for col in info.get("columns", {}).values():
            if "desc" in col:
                keywords.add(col["desc"].lower())
    return keywords
