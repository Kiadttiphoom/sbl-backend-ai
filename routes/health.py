import httpx
import logging
from fastapi import APIRouter
from db.connector import get_connection
from config import OLLAMA_ENDPOINT_1

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check():
    """Checks DB connectivity and Ollama availability."""
    status = {"status": "ok", "db": "unknown", "llm": "unknown"}
    
    # Check DB
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.close()
        conn.close()
        status["db"] = "connected"
    except Exception as e:
        status["db"] = f"error: {str(e)[:100]}"
        status["status"] = "degraded"
    
    # Check Ollama
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            base_url = OLLAMA_ENDPOINT_1.replace("/api/generate", "")
            r = await client.get(base_url)
            if r.status_code == 200:
                status["llm"] = "connected"
            else:
                status["llm"] = f"http {r.status_code}"
                status["status"] = "degraded"
    except Exception as e:
        status["llm"] = f"error: {str(e)[:100]}"
        status["status"] = "degraded"
    
    return status
