"""Benchmarker module — scenario replay and scoring registration."""

import os

from core.logging import log
from shared.common import check_services
from modules.benchmarker.benchmarker import ensure_tables_exist
from modules.benchmarker.core_actions import (
    action_create_conversation,
    action_switch_option,
    action_teacher_send_message,
    action_user_send_message,
)
from modules.benchmarker.scoring_pipeline import configure_scoring_pipeline
from modules.trainer.driver_assertions import register_trainer_driver_assertions


def on_module_activated(services) -> None:
    """Functional initialization. No Streamlit usage."""
    required = check_services(
        ["driver", "config", "db_manager", "llm_manager"],
        services=services,
        module_name="benchmarker",
    )
    driver = required["driver"]
    config = required["config"]
    db_manager = required["db_manager"]
    llm_manager = required["llm_manager"]
    cache_fn = services.get("cache") if "cache" in services else None

    ensure_tables_exist(db_manager)

    sessions_dir = config.get("benchmarker.sessions_dir", "data/benchmarker/sessions")
    os.makedirs(sessions_dir, exist_ok=True)

    driver.register_action(
        "create_conversation",
        action_create_conversation,
        "Create a conversation for the current student",
        required_context=["student_id"],
    )
    driver.register_action(
        "user_send_message",
        action_user_send_message,
        "Send a student message and get LLM response",
        required_context=["student_id", "conversation_id"],
    )
    driver.register_action(
        "teacher_send_message",
        action_teacher_send_message,
        "Inject a teacher message into a conversation",
        required_context=["trainer_id", "student_id", "conversation_id"],
    )
    driver.register_action(
        "switch_option",
        action_switch_option,
        "Switch a driver option mid-scenario (system only)",
        required_context=[],
    )

    register_trainer_driver_assertions(driver.register_assertion)

    for llm in llm_manager.get_available_llms():
        llm_id = llm["id"]
        llm_name = llm.get("name", llm_id)
        driver.register_option(
            group="llm",
            name=llm_id,
            activate_fn=lambda lid=llm_id, mgr=llm_manager: mgr.set_current_llm(lid),
            deactivate_fn=lambda: None,
            description=f"{llm_name} — {llm.get('description', '')}",
        )

    configure_scoring_pipeline(cache_fn=cache_fn, db_manager=db_manager)
    log("info", "benchmarker: activated")


def on_module_deactivated() -> None:
    """Benchmarker does not require explicit teardown."""
    log("info", "benchmarker: deactivated")


def on_module_config_changed() -> None:
    """Called when module config changes."""
    pass
