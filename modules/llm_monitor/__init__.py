# modules/llm_monitor/__init__.py
"""
LLM Monitor Module - Core functionality for monitoring LLM usage.
NO Streamlit imports here.
"""

from typing import Optional
from core.logging import log

# Module state
_INITIALIZED = False
_INSTANCE = None


def _get_manager(services=None):
    """Get or create the LLM monitor instance with injected dependencies."""
    from modules.llm_monitor.llm_monitor_factory import get_llm_monitor, reset_llm_monitor

    if services is not None:
        config = services.get("config")
        db_manager = services.get("db_manager")
        if config and db_manager:
            # Reset if we have new services
            reset_llm_monitor()
            return get_llm_monitor(config=config, db_manager=db_manager)

    return get_llm_monitor()


def on_module_activated(services=None) -> None:
    """
    Called by ModuleHandler when module is activated.
    This runs in headless context - no Streamlit!
    """
    global _INITIALIZED

    log("info", "LLM Monitor module activated")

    # Initialize the monitor with injected services
    monitor = _get_manager(services)

    # Register LLM callbacks through the LLM manager
    if services and services.get("llm_manager"):
        llm_manager = services.get("llm_manager")

        def monitor_callback(data: dict):
            """Callback to log LLM calls."""
            monitor.log_llm_call(data)

        llm_manager.register_monitor_callback(monitor_callback)
        log("debug", "LLM monitor callback registered with LLM manager")

    _INITIALIZED = True


def on_module_deactivated() -> None:
    """Called by ModuleHandler when module is deactivated."""
    global _INITIALIZED

    log("info", "LLM Monitor module deactivated")
    _INITIALIZED = False


def on_module_config_changed() -> None:
    """Called when module configuration changes."""
    log("info", "LLM Monitor configuration changed, reloading")
    from modules.llm_monitor.llm_monitor_factory import reset_llm_monitor
    reset_llm_monitor()
