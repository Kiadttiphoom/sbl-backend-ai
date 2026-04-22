"""
Dynamic Few-Shot Vector Store
─────────────────────────────
Provides similarity search for SQL and Insight examples.

Modes:
  1. Keyword matching (DEFAULT — fast, no extra model required)
  2. Vector similarity via Ollama embeddings (opt-in: set EMBED_MODEL env var)

Usage:
    from vector_store import store
    store.initialize()
    results = store.search_sql("ยอดหนี้คงเหลือ", top_k=5)
"""

import json
import math
import logging
import os
import hashlib
import pickle
import re
import random
from typing import Optional, List, Dict

import httpx

from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

CACHE_PATH = "vector_cache.pkl"

# ── IMPORTANT: Only use vector search if a DEDICATED fast embedding model is set
# Default qwen2.5:3b is too slow for real-time embedding (~3s per call)
# Recommended: EMBED_MODEL=nomic-embed-text (< 100ms per call)
_DEDICATED_EMBED_MODEL = os.getenv("EMBED_MODEL", "")


# ── Embedding helpers ─────────────────────────────────────────────────────────

def _get_embed_url() -> str:
    from config import OLLAMA_ENDPOINT_1
    return OLLAMA_ENDPOINT_1.replace("/api/generate", "/api/embed")


def _compute_embedding_sync(text: str) -> Optional[List[float]]:
    """Compute embedding vector using Ollama (synchronous)."""
    if not _DEDICATED_EMBED_MODEL:
        return None  # Skip if no dedicated model configured
    try:
        r = httpx.post(
            _get_embed_url(),
            json={"model": _DEDICATED_EMBED_MODEL, "input": text},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        embs = data.get("embeddings")
        if embs and len(embs) > 0:
            return embs[0]
        return data.get("embedding")
    except Exception as e:
        logger.debug("Embedding failed: %s", e)
        return None


# ── Similarity helpers ────────────────────────────────────────────────────────

def _cosine_sim(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def _keyword_score(query: str, text: str) -> int:
    """
    Keyword-overlap score.
    Extracts Thai words and English tokens >= 2 chars.
    """
    q_tokens = set(re.findall(r'[\u0E00-\u0E7F]+|\w{2,}', query.lower()))
    t_tokens = set(re.findall(r'[\u0E00-\u0E7F]+|\w{2,}', text.lower()))
    return len(q_tokens & t_tokens)


# ── Main Store Class ──────────────────────────────────────────────────────────

class FewShotStore:
    """
    Dynamic Few-Shot store.
    
    Default mode: Keyword matching (instant, no extra calls)
    Opt-in mode:  Vector similarity (set EMBED_MODEL env var)
    """

    def __init__(self):
        self.sql_items: List[Dict] = []
        self.insight_items: List[Dict] = []
        self._has_vectors = False

    def initialize(self):
        """Initialize the store."""
        self.sql_items = []
        self.insight_items = []
        self._has_vectors = False
        logger.info("Few-shot store initialized (empty mode)")

        # ── Vector mode: only if dedicated EMBED_MODEL is configured ──────
        if _DEDICATED_EMBED_MODEL:
            # Try cache first
            if os.path.exists(CACHE_PATH):
                try:
                    with open(CACHE_PATH, "rb") as f:
                        cache = pickle.load(f)
                    self.sql_items = cache["sql"]
                    self.insight_items = cache["insight"]
                    self._has_vectors = cache.get("has_vectors", False)
                    logger.info(
                        "Loaded %d SQL + %d insight from cache (vector mode)",
                        len(self.sql_items), len(self.insight_items),
                    )
                    return
                except Exception as e:
                    logger.warning("Cache load failed: %s", e)

            # Compute embeddings
            logger.info("Computing embeddings with %s ...", _DEDICATED_EMBED_MODEL)
            ok = True
            for item in self.sql_items:
                emb = _compute_embedding_sync(item["question"])
                if emb is None:
                    ok = False
                    break
                item["embedding"] = emb

            if ok:
                for item in self.insight_items:
                    emb = _compute_embedding_sync(item["question"])
                    if emb is None:
                        ok = False
                        break
                    item["embedding"] = emb

            self._has_vectors = ok
            if ok:
                logger.info("✓ Vector embeddings ready (%d examples)", 
                           len(self.sql_items) + len(self.insight_items))
                try:
                    with open(CACHE_PATH, "wb") as f:
                        pickle.dump({
                            "sql": self.sql_items,
                            "insight": self.insight_items,
                            "has_vectors": True,
                        }, f)
                except Exception:
                    pass
            else:
                logger.warning("Embedding failed — falling back to keyword mode")
        else:
            # ── Keyword mode (DEFAULT — instant, no extra model) ──────────
            logger.info(
                "Loaded %d SQL + %d insight examples (keyword mode). "
                "For vector search, set EMBED_MODEL=nomic-embed-text",
                len(self.sql_items), len(self.insight_items),
            )

    def reload(self):
        """Force-reload examples (currently just re-initializes empty store)."""
        self.initialize()

    # ── Search ────────────────────────────────────────────────────────────

    def _search(self, items: List[Dict], query: str, top_k: int) -> List[Dict]:
        if not items:
            return []

        # Vector mode (only if EMBED_MODEL is configured and embeddings exist)
        if self._has_vectors and _DEDICATED_EMBED_MODEL:
            q_emb = _compute_embedding_sync(query)
            if q_emb:
                scored = [
                    (item, _cosine_sim(q_emb, item.get("embedding", [])))
                    for item in items
                ]
                scored.sort(key=lambda x: x[1], reverse=True)
                return [item for item, _ in scored[:top_k]]

        # Keyword mode (DEFAULT — instant)
        scored = [
            (
                item,
                _keyword_score(
                    query,
                    item.get("question", "") + " " + item.get("comment", ""),
                ),
            )
            for item in items
        ]
        # Sort by score DESC
        scored.sort(key=lambda x: x[1], reverse=True)

        results = [item for item, s in scored[:top_k] if s > 0]
        
        # FIX: If no keywords match, return 5 RANDOM examples instead of the first 5 in the file
        # This prevents "Pattern Latching" where the AI always follows the top-most example
        if not results:
            if len(items) <= top_k:
                return items
            return random.sample(items, top_k)
            
        return results

    def search_sql(self, query: str, top_k: int = 5) -> List[Dict]:
        return self._search(self.sql_items, query, top_k)

    def search_insight(self, query: str, top_k: int = 3) -> List[Dict]:
        return self._search(self.insight_items, query, top_k)


# Singleton
store = FewShotStore()
