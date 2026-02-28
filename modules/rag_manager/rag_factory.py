"""
RAG Factory — Streamlit Bridge

This is the ONLY file in the rag_manager module that is allowed to import
streamlit. It constructs the RAGManager singleton by pulling all dependencies
from the ServiceLocator, so RAGManager itself stays Streamlit-free.

Usage (standard — ServiceLocator populated at startup):
    from modules.rag_manager.rag_factory import get_rag_manager
    rag = get_rag_manager()

Usage (headless / tests — explicit injection):
    rag = get_rag_manager(services=my_service_locator)

Usage (legacy / backward-compatible — direct injection):
    rag = get_rag_manager(config=cfg, user_manager=um)
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING, Any

if TYPE_CHECKING:
    from modules.rag_manager.rag_manager import RAGManager
    from core.service import ServiceLocator

_instance: Optional["RAGManager"] = None


def get_rag_manager(
    services: Optional["ServiceLocator"] = None,
    # Legacy keyword arguments kept for backward compatibility.
    # Callers that pass config/user_manager directly still work.
    config: Optional[Any] = None,
    user_manager: Optional[Any] = None,
) -> "RAGManager":
    """
    Return the RAGManager singleton.

    Resolution order:
      1. Return existing singleton if already built.
      2. If ``services`` is provided, pull config/user_manager/cache from it.
      3. If ``config`` / ``user_manager`` are provided directly (legacy), use them.
      4. Fall back to the global ServiceLocator registered by register_all_services().

    Args:
        services:     ServiceLocator instance (preferred).
        config:       Config object — legacy, used when services is not provided.
        user_manager: User manager — legacy, used when services is not provided.
    """
    global _instance

    if _instance is not None:
        return _instance

    cache_fn = None

    if services is not None:
        # Preferred path: everything comes from the ServiceLocator.
        config       = config       or services.get("config")
        user_manager = user_manager or services.get("user_manager")
        cache_fn     = services.get("cache")

    elif config is None or user_manager is None:
        # Fall back to global ServiceLocator (set up by register_all_services()).
        try:
            from shared.common import _get_services
            global_services = _get_services()
            if global_services is not None:
                config       = config       or global_services.get("config")
                user_manager = user_manager or global_services.get("user_manager")
                cache_fn     = global_services.get("cache")
        except Exception:
            pass  # Headless context with no services registered — callers must pass config/um directly.

    if config is None:
        raise RuntimeError(
            "get_rag_manager(): 'config' not available. "
            "Either call register_all_services() at startup, pass a ServiceLocator, "
            "or pass config= directly."
        )
    if user_manager is None:
        raise RuntimeError(
            "get_rag_manager(): 'user_manager' not available. "
            "Either call register_all_services() at startup, pass a ServiceLocator, "
            "or pass user_manager= directly."
        )

    from modules.rag_manager.rag_manager import RAGManager
    _instance = RAGManager(config=config, user_manager=user_manager, cache_fn=cache_fn)
    return _instance


def reset_rag_manager() -> None:
    """Reset the singleton (useful for tests)."""
    global _instance
    _instance = None
