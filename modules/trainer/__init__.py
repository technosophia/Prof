"""
Trainer Module
=============
Student training and progression tracking system.
"""

from core.logging import log
from shared.common import get_driver
from st_shared.cached import get_db_manager

from .models import PluginData, PluginActivation, ensure_tables_exist
from .manager import get_trainer_manager
from .plugin_base import get_plugin_manager
from .driver_layer import register_trainer_driver_bindings

__all__ = [
    "get_trainer_manager",
    "get_plugin_manager",
    "PluginData",
    "PluginActivation",
]

_DRIVER_REGISTRATION_DONE = False


def initialize():
    """Initialize the Trainer module."""
    global _DRIVER_REGISTRATION_DONE

    log("debug", "Initializing Trainer module")

    get_db_manager()
    ensure_tables_exist()
    plugin_manager = get_plugin_manager()
    if hasattr(plugin_manager, "set_trainer_manager"):
        plugin_manager.set_trainer_manager(get_trainer_manager())
    log("debug", f"Loaded {len(plugin_manager.get_all_plugins())} Trainer plugins")

    if _DRIVER_REGISTRATION_DONE:
        log("debug", "trainer: driver options/actions/assertions already registered")
        return True

    log("info", "trainer: registering memory_backend options, actions and assertions with driver")
    register_trainer_driver_bindings()

    registered_options = [opt["name"] for opt in get_driver().list_options().get("memory_backend", [])]
    registered_actions = [a["name"] for a in get_driver().list_actions()]
    registered_assertions = [a["name"] for a in get_driver().list_assertions()]
    log("info", f"trainer: registered memory_backend options={registered_options}")
    log(
        "info",
        f"trainer: registered actions={[a for a in registered_actions if a in ['trigger_memory_analysis', 'set_training_program', 'add_student_note']]}",
    )
    log("info", f"trainer: registered assertions={registered_assertions}")

    _DRIVER_REGISTRATION_DONE = True
    return True
