import logging
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from core.ai_controller import AIController
from llm.ollama_client import OllamaClient
from schema.loader import load_schema

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI Agent"])


class AskRequest(BaseModel):
    question: str
    history: List[Dict[str, str]] = []
    # stateful: frontend ส่ง SQL ที่เพิ่งรันไปพร้อม db เพื่อให้ follow-up ทำงานได้
    last_sql: Optional[str] = None
    last_db:  Optional[str] = "lspdata"


# ── Dependency Initialization ────────────────────────────────────────────────
ollama_client: OllamaClient = OllamaClient()
db_schema: Dict[str, Any] = load_schema()
ai_controller: AIController = AIController(ollama_client, db_schema)


def _inject_session(
    history: List[Dict[str, str]],
    last_sql: Optional[str],
    last_db: str,
) -> List[Dict[str, str]]:
    """
    Prepend a special system message ที่ AIController._extract_session_state() จะดึงออกมา
    ทำให้ไม่ต้องแก้ schema history ของ frontend
    """
    if not last_sql:
        return history
    injected = {"role": "system", "content": f"__sql__:{last_sql}", "db": last_db}
    return [injected] + list(history)


@router.post("/ask")
async def ask_post(body: AskRequest, request: Request) -> StreamingResponse:
    """POST endpoint supporting conversation history + stateful SQL context."""
    logger.info("📥 รับข้อความจากผู้ใช้: %s", body.question)
    if body.history:
        logger.info("   ประวัติการสนทนา: %d ข้อความ", len(body.history))
    if body.last_sql:
        logger.info("   last_sql injected: %.80s", body.last_sql)

    history = _inject_session(body.history, body.last_sql, body.last_db or "lspdata")

    return StreamingResponse(
        ai_controller.process_request(body.question, history),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.get("/ask")
async def ask_get(q: str, request: Request) -> StreamingResponse:
    """GET endpoint for backward compatibility (no history, no stateful SQL)."""
    logger.info("📥 รับข้อความจากผู้ใช้ (GET): %s", q)
    return StreamingResponse(
        ai_controller.process_request(q, []),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )