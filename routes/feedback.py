import logging
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Feedback"])

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: str  # "up" or "down"

@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest):
    """Logs user feedback for quality improvement."""
    logger.info(
        "FEEDBACK [%s] Q='%.100s' A='%.100s'",
        body.rating, body.question, body.answer
    )
    # In production, this can be saved to a database for LLM fine-tuning
    return {"status": "received", "rating": body.rating}
