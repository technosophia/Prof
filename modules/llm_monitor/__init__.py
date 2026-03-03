# modules/llm_monitor/__init__.py
"""
LLM Monitor Module - Core functionality for monitoring LLM usage.

NO Streamlit imports here! This module follows the Functional Core / UI Separation pattern:
- Business logic is in llm_monitor.py (pure functional)
- Streamlit dependencies are injected via ServiceLocator in on_module_activated()
- UI code is isolated in llm_monitor_ui.py

The module lifecycle hooks receive services from the ServiceLocator, which provides
all dependencies (config, db_manager, llm_manager) without touching st_shared.cached.
"""

from typing import Optional, Any
from core.logging import log

# Module state - store references to services for later use (unregistration)
_INITIALIZED = False
_MONITOR_CALLBACK_REGISTERED = False
_LLM_MANAGER = None  # Store reference to llm_manager from services for unregistration
_SERVICES = None     # Store services for later use if needed


def _get_manager(services=None):
    """Get or create the LLM monitor instance with injected dependencies.

    This factory function uses the service locator to inject dependencies
    instead of importing from st_shared.cached.
    """
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
        """Callback to log LLM calls.

        CRITICAL: This callback runs headless - NO Streamlit access!
        The data should already contain user_id and conversation_id from the
        LLM manager (the caller), not from st.session_state.
        """
        monitor.log_llm_call(data)

    # Set metadata for debugging and unregistration
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
        monitor = _get_manager(_SERVICES)

        # Create and register the callback
        callback = _create_monitor_callback(monitor)
        llm_manager.register_monitor_callback(callback)

        _MONITOR_CALLBACK_REGISTERED = True
        log("info", f"LLM monitor callback registered: {callback.__name__} from {callback.__module__}")

    except Exception as e:
        log("error", f"Failed to register monitor callback: {e}", stacktrace=True)


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
# Module lifecycle hooks  (NO Streamlit, called by ModuleHandler)
# ---------------------------------------------------------------------------

def on_module_activated(services: Optional[Any] = None) -> None:
    """
    Called by ModuleHandler when module is activated.

    This is the ONLY place where services are injected. The function:
    1. Stores service references for later use (unregistration)
    2. Initializes the monitor with injected dependencies
    3. Registers callbacks with the LLM manager

    CRITICAL: This runs in headless context - no Streamlit access!

    Args:
        services: ServiceLocator with ALL dependencies the module needs:
                 - config: Configuration object
                 - db_manager: Database manager for storing logs
                 - llm_manager: LLM manager for callback registration
    """
    global _LLM_MANAGER, _SERVICES

    log("info", "LLM Monitor module activated")

    # Store services for later use (unregistration, config changes)
    _SERVICES = services

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
        log("warning", "No services provided - LLM monitor may not function correctly")
        return

    # Register the monitor callback with the LLM manager
    if _LLM_MANAGER:
        _register_monitor_callback(_LLM_MANAGER)
    else:
        log("warning", "LLM manager not available, monitor callbacks not registered")


def on_module_deactivated() -> None:
    """
    Called by ModuleHandler when module is deactivated.

    Cleans up by unregistering callbacks using stored service references.
    """
    global _LLM_MANAGER, _MONITOR_CALLBACK_REGISTERED, _SERVICES, _INITIALIZED

    log("info", "LLM Monitor module deactivated")

    # Unregister callbacks if we have the llm_manager
    if _LLM_MANAGER:
        _unregister_monitor_callback(_LLM_MANAGER)
    else:
        log("warning", "LLM manager not available, cannot unregister callbacks")

    # Reset state
    _LLM_MANAGER = None
    _MONITOR_CALLBACK_REGISTERED = False
    _SERVICES = None
    _INITIALIZED = False


def on_module_config_changed() -> None:
    """
    Called by ModuleHandler when module configuration changes.

    Refreshes the monitor and re-registers callbacks.
    """
    log("info", "LLM Monitor configuration changed, reloading")

    # Reset the monitor instance
    from modules.llm_monitor.llm_monitor_factory import reset_llm_monitor
    reset_llm_monitor()

    # Re-register callback with fresh monitor instance
    if _LLM_MANAGER:
        _unregister_monitor_callback(_LLM_MANAGER)
        _register_monitor_callback(_LLM_MANAGER)


# ---------------------------------------------------------------------------
# Legacy initialization - DEPRECATED
# ---------------------------------------------------------------------------

def initialize() -> bool:
    """
    DEPRECATED: Legacy initialization function.

    This function should NOT be used in new code. It relies on st_shared.cached
    which breaks headless operation. Use on_module_activated(services) instead.

    Kept only for backward compatibility during migration.
    """
    global _INITIALIZED

    log("warning", "LLM Monitor: Using deprecated initialize() - should migrate to on_module_activated(services)")

    try:
        # This is the ONLY place that should import from st_shared.cached
        # Once migration is complete, this function will be removed
        from st_shared.cached import get_llm_manager
        llm_manager = get_llm_manager()

        # Store the llm_manager reference
        global _LLM_MANAGER
        _LLM_MANAGER = llm_manager

        # Register the monitor callback
        _register_monitor_callback(llm_manager)
        _INITIALIZED = True
        return True
    except Exception as exc:
        log("error", f"Failed to initialize LLM monitor: {exc}", stacktrace=True)
        return False


__all__ = [
    "on_module_activated",
    "on_module_deactivated",
    "on_module_config_changed",
    "initialize",  # Deprecated, kept for compatibility
]
