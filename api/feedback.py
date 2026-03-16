"""Feedback API routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import get_current_user
from core.logging import log
from core.database import get_db_manager
from shared.common import get_conversation_manager
from modules.feedback.feedback_core import submit_feedback

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class MessageFeedbackRequest(BaseModel):
    conversation_id: str
    message_index: int = Field(ge=0)
    sentiment: str
    comment: str = ""


class ConversationFeedbackRequest(BaseModel):
    conversation_id: str
    comment: str


class AppFeedbackRequest(BaseModel):
    comment: str
    rating: int | None = Field(default=None, ge=1, le=5)


def _get_owned_conversation_or_404(conversation_id: str, current_user: dict):
    conversation = get_conversation_manager().get_conversation(conversation_id, include_messages=True)
    if not conversation or conversation.user_id != current_user["id"]:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.post("/message", status_code=201)
async def create_message_feedback(payload: MessageFeedbackRequest, current_user: dict = Depends(get_current_user)):
    try:
        conversation = _get_owned_conversation_or_404(payload.conversation_id, current_user)
        if payload.sentiment not in {"positive", "negative"}:
            raise HTTPException(status_code=400, detail="Invalid sentiment")
        if payload.message_index >= len(conversation.messages):
            raise HTTPException(status_code=400, detail="message_index out of range")

        feedback_id = submit_feedback(
            get_db_manager(),
            user_id=current_user["id"],
            feedback_type="message",
            conversation_id=payload.conversation_id,
            message_id=f"message-index:{payload.message_index}",
            sentiment=payload.sentiment,
            comment=payload.comment.strip() or None,
        )
        return {"id": feedback_id}
    except HTTPException:
        raise
    except Exception as exc:
        log("error", f"feedback message route failed: {exc}", stacktrace=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/conversation", status_code=201)
async def create_conversation_feedback(
    payload: ConversationFeedbackRequest,
    current_user: dict = Depends(get_current_user),
):
    try:
        _get_owned_conversation_or_404(payload.conversation_id, current_user)
        feedback_id = submit_feedback(
            get_db_manager(),
            user_id=current_user["id"],
            feedback_type="conversation",
            conversation_id=payload.conversation_id,
            sentiment="neutral",
            comment=payload.comment.strip() or None,
        )
        return {"id": feedback_id}
    except HTTPException:
        raise
    except Exception as exc:
        log("error", f"feedback conversation route failed: {exc}", stacktrace=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc


@router.post("/app", status_code=201)
async def create_app_feedback(payload: AppFeedbackRequest, current_user: dict = Depends(get_current_user)):
    try:
        feedback_id = submit_feedback(
            get_db_manager(),
            user_id=current_user["id"],
            feedback_type="app",
            sentiment="neutral",
            rating=payload.rating,
            comment=payload.comment.strip() or None,
        )
        return {"id": feedback_id}
    except HTTPException:
        raise
    except Exception as exc:
        log("error", f"feedback app route failed: {exc}", stacktrace=True)
        raise HTTPException(status_code=500, detail="Internal server error") from exc
