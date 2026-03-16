"""Database layer for feedback module."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text

from core.database import Base


FEEDBACK_TYPES = ("message", "conversation", "app")
SENTIMENT_TYPES = ("positive", "negative", "neutral")


class FeedbackTable(Base):
    __tablename__ = "feedback"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(String(36), ForeignKey("conversations.id"), nullable=True, index=True)
    message_id = Column(String(36), nullable=True, index=True)
    feedback_type = Column(Enum(*FEEDBACK_TYPES, name="feedback_type_enum", native_enum=False), nullable=False, index=True)
    sentiment = Column(Enum(*SENTIMENT_TYPES, name="feedback_sentiment_enum", native_enum=False), nullable=True, index=True)
    rating = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


def ensure_tables(db_manager) -> None:
    """Idempotent table creation for the feedback module."""
    FeedbackTable.__table__.create(bind=db_manager._engine, checkfirst=True)


def create_feedback(
    db_manager,
    *,
    user_id: str,
    feedback_type: str,
    conversation_id: Optional[str] = None,
    message_id: Optional[str] = None,
    sentiment: Optional[str] = None,
    rating: Optional[int] = None,
    comment: Optional[str] = None,
) -> str:
    with db_manager.get_session() as session:
        row = FeedbackTable(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            feedback_type=feedback_type,
            sentiment=sentiment,
            rating=rating,
            comment=comment,
        )
        session.add(row)
        session.flush()
        return row.id


def list_feedback(db_manager, *, limit: int, feedback_type: Optional[str] = None, sentiment: Optional[str] = None) -> list[dict]:
    with db_manager.get_session() as session:
        query = session.query(FeedbackTable)
        if feedback_type:
            query = query.filter(FeedbackTable.feedback_type == feedback_type)
        if sentiment:
            query = query.filter(FeedbackTable.sentiment == sentiment)
        rows = query.order_by(FeedbackTable.created_at.desc()).limit(limit).all()
        return [
            {
                "id": row.id,
                "user_id": row.user_id,
                "conversation_id": row.conversation_id,
                "message_id": row.message_id,
                "feedback_type": row.feedback_type,
                "sentiment": row.sentiment,
                "rating": row.rating,
                "comment": row.comment,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def clear_all_feedback(db_manager) -> int:
    with db_manager.get_session() as session:
        count = session.query(FeedbackTable).delete()
        return count
