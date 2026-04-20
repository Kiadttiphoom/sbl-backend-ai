import httpx
import logging
from fastapi import APIRouter
from db.connector import get_connection, available_databases
from db.templates import reload_queries
from core.memory import reload as reload_training
from config import OLLAMA_ENDPOINT_1

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Health"])

@router.get("/health")
async def health_check():
    """Checks DB connectivity for all registered databases and Ollama availability."""
    status = {"status": "ok", "databases": {}, "llm": "unknown"}

    # Check all databases from config.py > DATABASES
    for db_alias in available_databases():
        try:
            with get_connection(db_alias) as conn:
                conn.execute("SELECT 1")
            status["databases"][db_alias] = "connected"
        except Exception as e:
            status["databases"][db_alias] = f"error: {str(e)[:100]}"
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



@router.post("/reload-queries")
async def reload_queries_endpoint():
    """Hot-reload SQL templates from db/queries.json without restart."""
    try:
        success = reload_queries()
        if success:
            return {
                "status": "ok",
                "message": "SQL templates reloaded successfully from queries.json"
            }
        else:
            return {
                "status": "error",
                "message": "Failed to reload queries from JSON"
            }
    except Exception as e:
        logger.error(f"Reload failed: {e}")
        return {
            "status": "error",
            "message": str(e)
        }


@router.post("/reload-examples")
async def reload_examples_endpoint():
    """Hot-reload few-shot examples without restart."""
    try:
        reload_training()
        return {
            "status": "ok",
            "message": "Few-shot examples reloaded successfully"
        }
    except Exception as e:
        logger.error(f"Reload failed: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
