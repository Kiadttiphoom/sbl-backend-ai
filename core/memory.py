"""
Training Memory — Dynamic Few-Shot Context Provider
────────────────────────────────────────────────────
Uses vector_store for semantic similarity search.
Falls back to keyword matching if embeddings unavailable.

API:
    get_sql_training_context(query)     → formatted SQL examples relevant to the query
    get_insight_training_context(query) → formatted insight examples relevant to the query
    reload()                            → hot-reload examples from JSON
"""

import logging
from core.vector_store import store

logger = logging.getLogger(__name__)

_initialized = False


def _ensure_initialized():
    """Lazy initialization — runs once on first call."""
    global _initialized
    if not _initialized:
        store.initialize()
        _initialized = True


def get_sql_training_context(query: str = "") -> str:
    """
    Returns formatted SQL few-shot examples.
    
    Smart threshold:
      - <= 25 examples → send ALL (small set, LLM benefits from full context)
      - > 25 examples  → search top 5 most relevant (avoid prompt bloat)
    """
    _ensure_initialized()

    total = len(store.sql_items)

    if total <= 3 or not query:
        # Small set: send all — filtering would hurt accuracy
        relevant = store.sql_items
    else:
        # Large set: similarity search to keep prompt manageable
        # Increased to top_k=5 to provide more context for complex joins
        relevant = store.search_sql(query, top_k=5)

    if not relevant:
        return ""

    context = "\n### SQL EXAMPLES (GOLD STANDARD):\n"
    for i, ex in enumerate(relevant, 1):
        context += f"Example {i}:\n"
        context += f"- Question: {ex['question']}\n"
        context += f"- SQL: ```sql\n{ex['sql']}\n```\n"
        if "comment" in ex:
            context += f"- Logic: {ex['comment']}\n"
        context += "\n"
    return context


def get_insight_training_context(query: str = "") -> str:
    """
    Returns formatted insight few-shot examples.
    
    Smart threshold:
      - <= 15 examples → send ALL
      - > 15 examples  → search top 3 most relevant
    """
    _ensure_initialized()

    total = len(store.insight_items)

    if total <= 3 or not query:
        relevant = store.insight_items
    else:
        relevant = store.search_insight(query, top_k=2)

    if not relevant:
        return ""

    context = "\n### RESPONSE EXAMPLES (GOLD STANDARD):\n"
    for i, ex in enumerate(relevant, 1):
        context += f"Example {i}:\n"
        context += f"- User asked: {ex['question']}\n"
        context += f"- Data found: {ex['context']}\n"
        context += f"- Your professional response: {ex['answer']}\n"
        context += "\n"
    return context


def reload():
    """Hot-reload examples (re-initializes the store)."""
    global _initialized
    _initialized = False
    store.initialize()
    logger.info("Training memory reloaded successfully")
