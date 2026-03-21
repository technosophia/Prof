"""Trainer module — plugin-backed training memory and actions."""

from core.logging import log
from shared.common import check_services
from shared.common import record_plugin_event, register_llm_context_callback

from .context_callbacks import inject_teacher_system_prompt, inject_training_program
from .driver_layer import register_trainer_driver_bindings
from .manager import TrainerManager, set_trainer_manager
from .models import PluginActivation, PluginData, ensure_tables_exist
from .plugin_base import get_plugin_manager

__all__ = [
    "PluginData",
    "PluginActivation",
]


def on_module_activated(services) -> None:
    """Functional initialization. No Streamlit usage."""
    required = check_services(
        ["driver", "db_manager", "user_manager", "conversation_manager"],
        services=services,
        module_name="trainer",
    )
    driver = required["driver"]
    db_manager = required["db_manager"]
    user_manager = required["user_manager"]
    conversation_manager = required["conversation_manager"]

    ensure_tables_exist(db_manager)

    trainer_manager = TrainerManager(
        db_manager=db_manager,
        user_manager=user_manager,
        conversation_manager=conversation_manager,
    )
    set_trainer_manager(trainer_manager)

    plugin_manager = get_plugin_manager()
    if hasattr(plugin_manager, "set_trainer_manager"):
        plugin_manager.set_trainer_manager(trainer_manager)
    if hasattr(plugin_manager, "initialize"):
        plugin_manager.initialize(services)

    register_trainer_driver_bindings(
        driver=driver,
        plugin_manager=plugin_manager,
        trainer_manager=trainer_manager,
        record_plugin_event_fn=record_plugin_event,
    )

    register_llm_context_callback(inject_teacher_system_prompt)
    register_llm_context_callback(inject_training_program)

    log("info", "trainer: activated")


def on_module_deactivated() -> None:
    """Called when module is deactivated."""
    log("info", "trainer: deactivated")


def on_module_config_changed() -> None:
    """Called when module config changes."""
    pass
