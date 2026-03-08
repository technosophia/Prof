# /core/service.py

"""
Service Locator - Dependency injection container for the application.

This module provides a lightweight dependency injection container for services.
It allows modules to access application services without importing from st_shared,
keeping them Streamlit-free.
"""

from typing import Dict, Any, Optional


class ServiceLocator:
    """
    Lightweight dependency injection container for application services.

    The application startup code registers services here. Functional module hooks
    receive this object and use it to access config, managers, etc. without
    importing from st_shared.

    Example (app startup):
        services = ServiceLocator()
        services.register("config", get_plain_config())
        services.register("user_manager", user_manager)
        services.register("llm_manager", llm_manager)

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


# ---------------------------------------------------------------------------
# Global service registry
# ---------------------------------------------------------------------------

# Global service locator instance
_global_services: Optional[ServiceLocator] = None


def get_global_services() -> Optional[ServiceLocator]:
    """Get the global service locator instance."""
    return _global_services


def set_global_services(services: ServiceLocator) -> None:
    """Set the global service locator instance."""
    global _global_services
    _global_services = services


def check_services(required_services: Optional[list[str]] = None, *,
                   services: Optional[ServiceLocator] = None,
                   module_name: str = "") -> Dict[str, Any]:
    """
    Validate required services and return them as a dict.

    Args:
        required_services: Optional list of service names to validate.
        services: Optional ServiceLocator-like object. If omitted, uses global services.
        module_name: Optional module prefix used in raised error messages.

    Returns:
        Dictionary mapping service names to service instances.

    Raises:
        RuntimeError: If services locator not available or required service missing.
    """
    services = services or _global_services
    if services is None:
        prefix = f"{module_name}: " if module_name else ""
        raise RuntimeError(f"{prefix}services locator not available")

    if required_services is None:
        return {}  # No specific services required, just return empty dict

    resolved: Dict[str, Any] = {}
    for service_name in required_services:
        if service_name not in services:
            prefix = f"{module_name}: " if module_name else ""
            raise RuntimeError(f"{prefix}'{service_name}' service not available")
        resolved[service_name] = services.get(service_name)
    return resolved
