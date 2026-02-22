"""Benchmarker module initialization."""

import os

from shared.common import (
    get_available_llms,
    get_section,
    log,
    register_action,
    register_option,
    set_current_llm,
)

from modules.benchmarker.benchmarker import ensure_tables_exist
from modules.benchmarker.core_actions import (
    action_create_conversation,
    action_set_training_program,
    action_switch_option,
    action_teacher_send_message,
    action_user_send_message,
)

_INITIALIZED = False
_ACTIONS_REGISTERED = False
_LLM_OPTIONS_REGISTERED = False


def initialize() -> bool:
    """Initialize benchmarker module: tables, directories, and actions."""
    global _INITIALIZED, _ACTIONS_REGISTERED, _LLM_OPTIONS_REGISTERED
    try:
        config = get_section("benchmarker")
        sessions_dir = config.get("sessions_dir", "data/benchmarker/sessions")
        os.makedirs(sessions_dir, exist_ok=True)

        ensure_tables_exist()

        if not _ACTIONS_REGISTERED:
            register_action(
                "create_conversation",
                action_create_conversation,
                "Create a conversation for the current student",
                required_context=["student_id"],
            )
            register_action(
                "user_send_message",
                action_user_send_message,
                "Send a student message and get LLM response",
                required_context=["student_id", "conversation_id"],
            )
            register_action(
                "teacher_send_message",
                action_teacher_send_message,
                "Inject a teacher message into a conversation",
                required_context=["trainer_id", "student_id", "conversation_id"],
            )
            register_action(
                "set_training_program",
                action_set_training_program,
                "Set the training program text",
                required_context=["trainer_id"],
            )
            register_action(
                "switch_option",
                action_switch_option,
                "Switch a driver option mid-scenario (system only)",
                required_context=[],
            )
            _ACTIONS_REGISTERED = True

        if not _LLM_OPTIONS_REGISTERED:
            for llm in get_available_llms():
                llm_id = llm["id"]
                llm_name = llm.get("name", llm_id)
                register_option(
                    group="llm",
                    name=llm_id,
                    activate_fn=lambda lid=llm_id: set_current_llm(lid),
                    deactivate_fn=lambda: None,
                    description=f"{llm_name} — {llm.get('description', '')}",
                )
            _LLM_OPTIONS_REGISTERED = True

        _INITIALIZED = True
        log("debug", "Benchmarker module initialized")
        return True
    except Exception as exc:
        log("error", f"Failed to initialize benchmarker module: {exc}", exc_info=True)
        return False
