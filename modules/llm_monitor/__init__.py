# modules/llm_monitor/__init__.py
"""
LLM Monitor Module - Core functionality for monitoring LLM usage.
NO Streamlit imports here.
"""

from typing import Optional, Any
from core.logging import log

# Module state
_INITIALIZED = False
_MONITOR_CALLBACK_REGISTERED = False
_LLM_MANAGER = None  # Store reference to llm_manager from services


def _get_manager(services=None):
    """Get or create the LLM monitor instance with injected dependencies."""
    from modules.llm_monitor.llm_monitor_factory import get_llm_monitor, reset_llm_monitor

    if services is not None:
        # Extract dependencies from ServiceLocator
        config = services.get("config") if hasattr(services, "get") else None
        db_manager = services.get("db_manager") if hasattr(services, "get") else None

        if config is not None and db_manager is not None:
            # Reset and recreate with injected dependencies
            reset_llm_monitor()
            return get_llm_monitor(config=config, db_manager=db_manager)

    return get_llm_monitor()


def _create_monitor_callback(monitor):
    """Create a callback function for monitoring LLM calls."""
    def monitor_callback(data: dict):
        """Callback to log LLM calls."""
        # Just pass the data through - user_id and conversation_id
        # should already be in the data from the LLM manager
        monitor.log_llm_call(data)

    # Preserve the function name for debugging
    monitor_callback.__name__ = "monitor_callback"
    monitor_callback.__module__ = "modules.llm_monitor"
    return monitor_callback


def _register_monitor_callback(llm_manager):
    """Register the monitor callback with the LLM manager."""
    global _MONITOR_CALLBACK_REGISTERED

    if _MONITOR_CALLBACK_REGISTERED:
        return

    try:
        # Get the monitor instance
        monitor = _get_manager()

        # Create and register the callback
        callback = _create_monitor_callback(monitor)
        llm_manager.register_monitor_callback(callback)

        _MONITOR_CALLBACK_REGISTERED = True
        log("info", f"LLM monitor callback registered: {callback.__name__} from {callback.__module__}")

    except Exception as e:
        log("error", f"Failed to register monitor callback: {e}", exc_info=True)


def _unregister_monitor_callback(llm_manager):
    """Unregister the monitor callback from the LLM manager."""
    global _MONITOR_CALLBACK_REGISTERED

    try:
        # Find and unregister callbacks from this module
        if hasattr(llm_manager, '_monitor_callbacks'):
            original_count = len(llm_manager._monitor_callbacks)
            llm_manager._monitor_callbacks = [
                cb for cb in llm_manager._monitor_callbacks
                if getattr(cb, '__module__', '') != 'modules.llm_monitor'
            ]
            new_count = len(llm_manager._monitor_callbacks)
            log("info", f"Unregistered monitor callbacks: {original_count - new_count} removed")

        _MONITOR_CALLBACK_REGISTERED = False

    except Exception as e:
        log("error", f"Failed to unregister monitor callback: {e}")


# ---------------------------------------------------------------------------
# Module lifecycle hooks  (NO Streamlit)
# ---------------------------------------------------------------------------

def on_module_activated(services: Optional[Any] = None) -> None:
    """
    Called by ModuleHandler when module is activated.
    This runs in headless context - no Streamlit!

    Args:
        services: Optional ServiceLocator with injected dependencies
                 (config, db_manager, llm_manager, etc.)
    """
    global _LLM_MANAGER

    log("info", "LLM Monitor module activated")

    # Initialize the monitor with injected services if provided
    if services is not None:
        _get_manager(services)
        log("debug", "LLM Monitor initialized with injected services")

        # Store reference to llm_manager from services
        _LLM_MANAGER = services.get("llm_manager") if hasattr(services, "get") else None
        if _LLM_MANAGER:
            log("debug", "LLM Manager obtained from services")
        else:
            log("warning", "LLM manager not available in services")
    else:
        log("debug", "LLM Monitor using default initialization")
        # Try to get llm_manager from elsewhere? For now, warn
        log("warning", "No services provided, cannot access LLM manager")
        return

    # Register the monitor callback with the LLM manager
    if _LLM_MANAGER:
        _register_monitor_callback(_LLM_MANAGER)
    else:
        log("warning", "LLM manager not available, monitor callbacks not registered")


def on_module_deactivated() -> None:
    """Called by ModuleHandler when module is deactivated."""
    global _LLM_MANAGER

    log("info", "LLM Monitor module deactivated")

    # Unregister callbacks if we have the llm_manager
    if _LLM_MANAGER:
        _unregister_monitor_callback(_LLM_MANAGER)
    else:
        log("warning", "LLM manager not available, cannot unregister callbacks")


def on_module_config_changed() -> None:
    """Called when module configuration changes."""
    log("info", "LLM Monitor configuration changed, reloading")
    from modules.llm_monitor.llm_monitor_factory import reset_llm_monitor
    reset_llm_monitor()

    # Re-register callback with fresh monitor instance if we have llm_manager
    if _LLM_MANAGER:
        _unregister_monitor_callback(_LLM_MANAGER)
        _register_monitor_callback(_LLM_MANAGER)


# ---------------------------------------------------------------------------
# Legacy initialization (kept for backward compatibility)
# ---------------------------------------------------------------------------

def initialize() -> bool:
    """Legacy initialization function - kept for backward compatibility."""
    global _INITIALIZED

    try:
        # This should only be called in Streamlit context with llm_manager
        # available via get_llm_manager() from cached.py
        from st_shared.cached import get_llm_manager
        llm_manager = get_llm_manager()

        # Register the monitor callback
        _register_monitor_callback(llm_manager)
        _INITIALIZED = True
        return True
    except Exception as exc:
        log("error", f"Failed to initialize LLM monitor: {exc}", exc_info=True)
        return False
