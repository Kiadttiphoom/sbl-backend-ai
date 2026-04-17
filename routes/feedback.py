import logging
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Feedback"])

import os
import json
from typing import Optional

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: str  # "up" or "down"
    sql: Optional[str] = None

@router.post("/feedback")
async def submit_feedback(body: FeedbackRequest):
    """Logs user feedback and saves positive interactions for learning."""
    logger.info(
        "FEEDBACK [%s] Q='%.100s' A='%.100s'",
        body.rating, body.question, body.answer
    )
    
    # Auto-learning: บันทึกเฉพาะข้อที่ผู้ใช้ "อัปโหวต" เพื่อเตรียมเข้า Few-shot
    if body.rating == "up":
        pending_path = os.path.join("data", "learned_pending.json")
        new_entry = {
            "question": body.question,
            "answer": body.answer,
            "sql": body.sql,
            "status": "pending_approval"
        }
        
        try:
            learned_data = []
            if os.path.exists(pending_path):
                with open(pending_path, "r", encoding="utf-8") as f:
                    learned_data = json.load(f)
            
            learned_data.append(new_entry)
            
            with open(pending_path, "w", encoding="utf-8") as f:
                json.dump(learned_data, f, indent=4, ensure_ascii=False)
                
            logger.info("FEEDBACK_SAVED: Interaction saved to %s", pending_path)
        except Exception as e:
            logger.error("FEEDBACK_SAVE_ERROR: %s", e)

    return {"status": "received", "rating": body.rating}
