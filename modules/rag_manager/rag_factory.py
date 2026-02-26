"""
RAG Factory — Streamlit Bridge

This is the ONLY file in the rag_manager module that is allowed to import from
st_shared.cached. It constructs the RAGManager singleton by fetching the
Streamlit-cached config and user_manager and injecting them.

Why a separate factory?
    rag_manager.py must be importable without Streamlit (for tests, CLI, etc.).
    This factory is only imported in a Streamlit context (app startup or
    on_module_activated when running inside Streamlit).

Usage:
    from modules.rag_manager.rag_factory import get_rag_manager
    rag_manager = get_rag_manager()

The factory caches the instance; calling get_rag_manager() multiple times
returns the same object.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.rag_manager.rag_manager import RAGManager

_instance: Optional["RAGManager"] = None


def get_rag_manager(config=None, user_manager=None) -> "RAGManager":
    """
    Return the RAGManager singleton.

    If config and user_manager are provided, they are used directly (useful
    for testing or headless use).

    If not provided, they are fetched from st_shared.cached (Streamlit context).

    The instance is cached after first construction.
    """
    global _instance

    if _instance is not None:
        return _instance

    if config is None or user_manager is None:
        # Running inside Streamlit — fetch cached singletons
        from st_shared.cached import get_config, get_user_manager
        if config is None:
            config = get_config()
        if user_manager is None:
            user_manager = get_user_manager()

    from modules.rag_manager.rag_manager import RAGManager
    _instance = RAGManager(config=config, user_manager=user_manager)
    return _instance


def reset_rag_manager() -> None:
    """Reset the singleton (useful for tests)."""
    global _instance
    _instance = None
