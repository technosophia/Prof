"""Benchmarker module."""

from shared.common import register_action
from .core_actions import (
    action_create_conversation,
    action_set_training_program,
    action_teacher_send_message,
    action_user_send_message,
)


def initialize() -> bool:
    """Register benchmarker core actions in the app driver."""
    register_action(
        name="create_conversation",
        handler_fn=action_create_conversation,
        description="Create a new conversation for the current student",
        required_context=["student_id"],
    )
    register_action(
        name="user_send_message",
        handler_fn=action_user_send_message,
        description="Send a message as the current student and get LLM response",
        required_context=["student_id", "conversation_id"],
    )
    register_action(
        name="teacher_send_message",
        handler_fn=action_teacher_send_message,
        description="Send a message as the teacher in a student conversation",
        required_context=["trainer_id", "student_id", "conversation_id"],
    )
    register_action(
        name="set_training_program",
        handler_fn=action_set_training_program,
        description="Set the training program text for the current trainer",
        required_context=["trainer_id"],
    )
    return True
