# /shared/service.py

"""
Service Locator - Dependency injection container for the application.

This module provides a lightweight dependency injection container that can be
passed to module lifecycle hooks. It allows modules to access application
services without importing from st_shared, keeping them Streamlit-free.
"""

from typing import Dict, Any, Optional


class ServiceLocator:
    """
    Lightweight dependency injection container passed to on_module_activated().

    The application startup code registers services here before activating
    modules. Functional module hooks receive this object and use it to access
    config, managers, etc. without importing from st_shared.

    Example (app startup):
        services = ServiceLocator()
        services.register("config", get_plain_config())
        services.register("user_manager", user_manager)
        services.register("llm_manager", llm_manager)
        module_handler.set_services(services)

    Example (module on_module_activated):
        def on_module_activated(services):
            config = services.get("config")
            llm_manager = services.get("llm_manager")
            llm_manager.register_context_callback(my_callback)
    """

    def __init__(self):
        self._services: Dict[str, Any] = {}

    def register(self, name: str, obj: Any) -> None:
        """Register a service by name."""
        self._services[name] = obj

    def get(self, name: str, default: Any = None) -> Any:
        """Get a service by name. Returns default if not found."""
        return self._services.get(name, default)

    @property
    def config(self) -> Any:
        """Shortcut to the 'config' service."""
        return self._services.get("config")

    def __contains__(self, name: str) -> bool:
        return name in self._services
