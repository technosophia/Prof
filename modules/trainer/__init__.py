"""Trainer module — plugin-backed training memory and actions."""

from core.logging import log
from shared.common import record_plugin_event, set_prompt

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
    driver = services.get("driver")
    db_manager = services.get("db_manager")
    user_manager = services.get("user_manager")
    conversation_manager = services.get("conversation_manager")

    if driver is None:
        raise RuntimeError("trainer: 'driver' service not available")
    if db_manager is None:
        raise RuntimeError("trainer: 'db_manager' service not available")
    if user_manager is None:
        raise RuntimeError("trainer: 'user_manager' service not available")
    if conversation_manager is None:
        raise RuntimeError("trainer: 'conversation_manager' service not available")

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
        set_prompt_fn=set_prompt,
        record_plugin_event_fn=record_plugin_event,
    )

    log("info", "trainer: activated")


def on_module_deactivated() -> None:
    """Called when module is deactivated."""
    log("info", "trainer: deactivated")


def on_module_config_changed() -> None:
    """Called when module config changes."""
    pass
