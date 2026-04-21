import time
import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from config import ALLOWED_ORIGINS

from routes import ask, health, feedback
from core.memory import reload as reload_training

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="SBL Smart Data Agent",
    version="3.1.0 (Production Modular)",
    description="SBL Financial AI Agent with strictly schema-driven SQL generation."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    logger.info(f"🚀 Request started: {request.method} {request.url.path}")
    response = await call_next(request)
    process_time = (time.time() - start_time) * 1000
    logger.info(f"✅ Request finished: {request.method} {request.url.path} - Status: {response.status_code} - Timing: {process_time:.2f}ms")
    return response

app.include_router(ask.router)
app.include_router(health.router)
app.include_router(feedback.router)

@app.get("/")
async def home():
    return {
        "status": "AI Agent Running (Modular Architecture)",
        "version": "3.1.0",
    }

@app.post("/reload-examples")
async def reload_examples():
    """Hot-reload few-shot examples without restart."""
    try:
        reload_training()
        return {"status": "ok", "message": "Few-shot examples reloaded successfully"}
    except Exception as e:
        logger.error("Reload failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))  # ✅ แก้ tuple

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)