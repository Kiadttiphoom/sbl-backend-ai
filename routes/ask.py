from typing import List, Dict, Any
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.ask_service import AskService
from llm.ollama_client import OllamaClient
from insight.agent import InsightAgent
from schema.loader import load_schema

router = APIRouter(tags=["AI Agent"])

class AskRequest(BaseModel):
    question: str
    history: List[Dict[str, str]] = []  # [{"role": "user"|"ai", "content": "..."}, ...]

# ── Dependency Initialization ───────────────────────────────────────────────
# These act as singletons for the router's lifecycle
ollama_client: OllamaClient = OllamaClient()
insight_agent: InsightAgent = InsightAgent(ollama_client)
db_schema: Dict[str, Any] = load_schema()
ask_service: AskService = AskService(ollama_client, insight_agent, db_schema)

@router.post("/ask")
async def ask_post(body: AskRequest, request: Request) -> StreamingResponse:
    """POST endpoint supporting conversation history."""
    return StreamingResponse(
        ask_service.process_ask(body.question, body.history),
        media_type="application/x-ndjson"
    )

@router.get("/ask")
async def ask_get(q: str, request: Request) -> StreamingResponse:
    """GET endpoint for backward compatibility (no history)."""
    return StreamingResponse(
        ask_service.process_ask(q, []),
        media_type="application/x-ndjson"
    )
