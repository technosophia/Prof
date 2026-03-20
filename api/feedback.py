"""Feedback API routes - FIXED to store actual message IDs."""

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

        # NEW: Get the actual message ID from the database
        # Find the message by matching conversation_id, index, and role
        # Messages are stored in order, so we can use the index
        target_message = conversation.messages[payload.message_index]

        # Query database to get the real message ID
        db_manager = get_db_manager()
        with db_manager.get_session() as session:
            from shared.conversation import MessageTable

            # Find the message by content and timestamp to get its ID
            db_message = session.query(MessageTable).filter_by(
                conversation_id=payload.conversation_id,
                role=target_message.role,
                content=target_message.content
            ).first()

            if not db_message:
                raise HTTPException(status_code=404, detail="Message ID not found in database")

            actual_message_id = db_message.id

        feedback_id = submit_feedback(
            db_manager,
            user_id=current_user["id"],
            feedback_type="message",
            conversation_id=payload.conversation_id,
            message_id=actual_message_id,  # Use the actual database message ID
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
