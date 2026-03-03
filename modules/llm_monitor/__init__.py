"""LLM monitor module — callback registration and lifecycle hooks."""

from core.logging import log
from modules.llm_monitor.llm_monitor_factory import get_llm_monitor, reset_llm_monitor

_LLM_MANAGER = None
_MONITOR_CALLBACK = None


def on_module_activated(services) -> None:
    """Functional initialization using injected services."""
    global _LLM_MANAGER, _MONITOR_CALLBACK

    config = services.get("config")
    db_manager = services.get("db_manager")
    llm_manager = services.get("llm_manager")

    if config is None:
        raise RuntimeError("llm_monitor: 'config' service not available")
    if db_manager is None:
        raise RuntimeError("llm_monitor: 'db_manager' service not available")
    if llm_manager is None:
        raise RuntimeError("llm_monitor: 'llm_manager' service not available")

    reset_llm_monitor()
    monitor = get_llm_monitor(config=config, db_manager=db_manager)

    def monitor_callback(monitor_data):
        monitor.record_llm_call(monitor_data)

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
