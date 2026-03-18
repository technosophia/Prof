"""Core logic for feedback module (Streamlit-free)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from core.logging import log
from modules.feedback.feedback_db import (
    FEEDBACK_TYPES,
    SENTIMENT_TYPES,
    clear_all_feedback,
    create_feedback,
    ensure_tables,
    list_feedback,
)

EXPECTED_SERVICES = ["config", "db_manager", "user_manager", "conversation_manager", "driver"]


def check_services(services) -> dict[str, bool]:
    return {name: (name in services and services.get(name) is not None) for name in EXPECTED_SERVICES}


def get_feedback_config(config) -> dict[str, Any]:
    return {
        "max_display": config.get("modules.feedback.max_display", 50),
        "sidebar_expanded": config.get("modules.feedback.sidebar_expanded", False),
    }


def time_ago(dt: datetime, now: Optional[datetime] = None) -> str:
    if dt is None:
        return "unknown"
    if now is None:
        now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta_seconds = int((now - dt).total_seconds())
    if delta_seconds < 0:
        return "just now"
    if delta_seconds < 60:
        return "just now"
    minutes = delta_seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours > 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days > 1 else ''} ago"


def submit_feedback(
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
    if feedback_type not in FEEDBACK_TYPES:
        raise ValueError(f"Invalid feedback_type '{feedback_type}'")
    if sentiment is not None and sentiment not in SENTIMENT_TYPES:
        raise ValueError(f"Invalid sentiment '{sentiment}'")
    if rating is not None and (rating < 1 or rating > 5):
        raise ValueError("rating must be between 1 and 5")
    if feedback_type == "message" and message_id is None:
        raise ValueError("message feedback requires message_id")

    return create_feedback(
        db_manager,
        user_id=user_id,
        feedback_type=feedback_type,
        conversation_id=conversation_id,
        message_id=message_id,
        sentiment=sentiment,
        rating=rating,
        comment=comment,
    )


def get_feedback_rows(db_manager, user_manager, *, limit: int, feedback_type: Optional[str] = None, sentiment: Optional[str] = None) -> list[dict[str, Any]]:
    rows = list_feedback(db_manager, limit=limit, feedback_type=feedback_type, sentiment=sentiment)
    if not rows:
        return []

    # Fetch all users at once to avoid N+1 queries in the loop.
    all_users = user_manager.get_all_users_dict()

    result = []
    for row in rows:
        user = all_users.get(row["user_id"])
        username = user.get("name", row["user_id"]) if user else row["user_id"]
        result.append({**row, "username": username})
    return result


def feedback_on_module_activated(services) -> None:
    required = [name for name in EXPECTED_SERVICES if name not in services or services.get(name) is None]
    if required:
        raise RuntimeError(f"feedback: missing required services: {required}")

    db_manager = services.get("db_manager")
    ensure_tables(db_manager)

    driver = services.get("driver")

    def _submit_action(**kwargs):
        return {"feedback_id": submit_feedback(db_manager, **kwargs)}

    driver.register_action("feedback.submit", _submit_action, "Submit feedback record")
    log("debug", "feedback: activated")


def feedback_on_module_deactivated() -> None:
    log("debug", "feedback: deactivated (no removable callbacks registered)")


def clear_feedback(db_manager) -> int:
    return clear_all_feedback(db_manager)
