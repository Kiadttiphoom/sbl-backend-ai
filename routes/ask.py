from typing import List, Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from core.ai_controller import AIController
from llm.ollama_client import OllamaClient
from schema.loader import load_schema

router = APIRouter(tags=["AI Agent"])

class AskRequest(BaseModel):
    question: str
    history: List[Dict[str, str]] = []  # [{"role": "user"|"ai", "content": "..."}, ...]

# ── Dependency Initialization ───────────────────────────────────────────────
ollama_client: OllamaClient = OllamaClient()
db_schema: Dict[str, Any] = load_schema()
ai_controller: AIController = AIController(ollama_client, db_schema)

@router.post("/ask")
async def ask_post(body: AskRequest, request: Request) -> StreamingResponse:
    """POST endpoint supporting conversation history."""
    return StreamingResponse(
        ai_controller.process_request(body.question, body.history),
        media_type="application/x-ndjson"
    )

@router.get("/ask")
async def ask_get(q: str, request: Request) -> StreamingResponse:
    """GET endpoint for backward compatibility (no history)."""
    return StreamingResponse(
        ai_controller.process_request(q, []),
        media_type="application/x-ndjson"
    )
