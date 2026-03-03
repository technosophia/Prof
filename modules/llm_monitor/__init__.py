"""LLM monitor module — callback registration and lifecycle hooks."""

from core.logging import log
from shared.common import check_services
from modules.llm_monitor.llm_monitor_factory import get_llm_monitor, reset_llm_monitor

_LLM_MANAGER = None
_MONITOR_CALLBACK = None


def on_module_activated(services) -> None:
    """Functional initialization using injected services."""
    global _LLM_MANAGER, _MONITOR_CALLBACK

    required = check_services(
        ["config", "db_manager", "llm_manager"],
        services=services,
        module_name="llm_monitor",
    )
    config = required["config"]
    db_manager = required["db_manager"]
    llm_manager = required["llm_manager"]

    reset_llm_monitor()
    monitor = get_llm_monitor(config=config, db_manager=db_manager)

    def monitor_callback(monitor_data):
        monitor.log_llm_call(monitor_data)

    monitor_callback.__name__ = "llm_monitor_callback"

    _LLM_MANAGER = llm_manager
    _MONITOR_CALLBACK = monitor_callback
    _LLM_MANAGER.register_monitor_callback(_MONITOR_CALLBACK)

    log("info", "llm_monitor: activated")


def on_module_deactivated() -> None:
    """Unregister monitor callback."""
    global _LLM_MANAGER, _MONITOR_CALLBACK
    if _LLM_MANAGER is not None and _MONITOR_CALLBACK is not None:
        _LLM_MANAGER.unregister_monitor_callback(_MONITOR_CALLBACK)
    _LLM_MANAGER = None
    _MONITOR_CALLBACK = None
    log("info", "llm_monitor: deactivated")


def on_module_config_changed() -> None:
    """Reload monitor with current injected dependencies."""
    pass
