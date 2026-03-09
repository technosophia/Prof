"""
Callback registration utilities with duplicate prevention.
Provides helper functions for managing callbacks across different managers.
"""

from typing import List, Callable, Optional, Any
from core.logging import log

def register_callback(
    callback_list: List[Callable],
    callback_func: Callable,
    callback_type: str = "callback",
    allow_replace: bool = True
) -> bool:
    """
    Register a callback with duplicate prevention.

    Args:
        callback_list: The list to store callbacks in
        callback_func: The callback function to register
        callback_type: Type name for logging (e.g., "user message callback")
        allow_replace: Whether to replace existing callback with same name

    Returns:
        bool: True if callback was registered, False if duplicate and not replaced
    """
    callback_name = getattr(callback_func, '__name__', str(callback_func))

    # Check by object identity first
    if callback_func in callback_list:
        log("debug", f"{callback_type} {callback_name} already registered (by object identity)")
        return False

    # Check by function name
    for i, existing_cb in enumerate(callback_list):
        existing_name = getattr(existing_cb, '__name__', str(existing_cb))
        if existing_name == callback_name:
            if allow_replace:
                log("debug", f"{callback_type} with name '{callback_name}' already registered. "
                              f"Replacing existing callback with new one.")
                callback_list[i] = callback_func
                return True
            else:
                log("debug", f"{callback_type} with name '{callback_name}' already registered. "
                              f"Skipping duplicate.")
                return False

    callback_list.append(callback_func)
    log("debug", f"Registered {callback_type}: {callback_name}")
    return True

def unregister_callback(
    callback_list: List[Callable],
    callback_func: Callable,
    callback_type: str = "callback"
) -> bool:
    """
    Unregister a callback.

    Args:
        callback_list: The list containing callbacks
        callback_func: The callback function to unregister
        callback_type: Type name for logging

    Returns:
        bool: True if callback was found and removed, False otherwise
    """
    callback_name = getattr(callback_func, '__name__', str(callback_func))

    # Try to remove by object identity first
    if callback_func in callback_list:
        callback_list.remove(callback_func)
        log("debug", f"Unregistered {callback_type}: {callback_name}")
        return True

    # Fallback to removing by name
    for i, existing_cb in enumerate(callback_list):
        existing_name = getattr(existing_cb, '__name__', str(existing_cb))
        if existing_name == callback_name:
            callback_list.pop(i)
            log("debug", f"Unregistered {callback_type} by name: {callback_name}")
            return True

    log("warning", f"{callback_type} {callback_name} not found for unregistration")
    return False

def clear_callbacks(
    callback_list: List[Callable],
    callback_type: str = "callback"
) -> int:
    """
    Clear all callbacks from a list.

    Args:
        callback_list: The list to clear
        callback_type: Type name for logging

    Returns:
        int: Number of callbacks cleared
    """
    count = len(callback_list)
    callback_list.clear()
    log("debug", f"Cleared {count} {callback_type}(s)")
    return count

def get_callback_count(callback_list: List[Callable]) -> int:
    """Get the number of registered callbacks."""
    return len(callback_list)

def get_callback_names(callback_list: List[Callable]) -> List[str]:
    """Get names of all registered callbacks."""
    return [getattr(cb, '__name__', str(cb)) for cb in callback_list]
