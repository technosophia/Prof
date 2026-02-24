"""RAG Manager Module."""

from typing import Callable, Dict, List

from core.logging import log, set_module_level
from shared.common import (
    register_llm_context_callback,
    register_option,
    unregister_llm_context_callback,
)

from .rag_manager import RAGManager, rag_manager

_INITIALIZED = False
_RAG_OPTIONS_REGISTERED = False
_ENGINE_CONTEXT_CALLBACKS: Dict[str, Callable[[str, List[Dict]], tuple[str, str, str]]] = {}


def _engine_exists(name: str) -> bool:
    """Return True when engine exists and is enabled in current configuration."""
    if rag_manager.get_engine(name) is None:
        return False

    engines_config = rag_manager.rag_config.get("engines", {})
    if name in engines_config:
        return bool(engines_config[name].get("enabled", False))

    return True


def _make_engine_context_callback(name: str) -> Callable[[str, List[Dict]], tuple[str, str, str]]:
    """Build a context callback bound to a specific engine name."""

    def _callback(user_id: str, messages: List[Dict]) -> tuple[str, str, str]:
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if not user_messages:
            return "", "system", "bottom"

        query = user_messages[-1].get("content", "")
        if not query:
            return "", "system", "bottom"

        context = rag_manager.get_rag_context(user_id=user_id, query=query, engine_type=name)
        return context, "system", "bottom"

    _callback.__name__ = f"rag_context_callback_{name}"
    return _callback


def _activate_rag_engine(name: str) -> None:
    """Activate a RAG engine and register its context callback."""
    try:
        if not _engine_exists(name):
            log("warning", f"Cannot activate unavailable RAG engine: {name}")
            return

        rag_manager.default_engine = name

        callback = _ENGINE_CONTEXT_CALLBACKS.get(name)
        if callback is None:
            callback = _make_engine_context_callback(name)
            _ENGINE_CONTEXT_CALLBACKS[name] = callback

        register_llm_context_callback(callback)
    except Exception as exc:
        log("warning", f"Failed to activate RAG engine '{name}': {exc}")


def _deactivate_rag_engine(name: str) -> None:
    """Deactivate a RAG engine and unregister its context callback."""
    callback = _ENGINE_CONTEXT_CALLBACKS.get(name)
    if callback is not None:
        unregister_llm_context_callback(callback)



def _clear_registered_context_callbacks() -> None:
    """Unregister all registered RAG context callbacks."""
    for callback in list(_ENGINE_CONTEXT_CALLBACKS.values()):
        try:
            unregister_llm_context_callback(callback)
        except Exception as exc:
            log("debug", f"Failed to unregister RAG callback: {exc}")


def on_module_activated() -> None:
    """Module lifecycle hook called by ModuleHandler on activation."""
    initialize()


def on_module_deactivated() -> None:
    """Module lifecycle hook called by ModuleHandler on deactivation."""
    global _INITIALIZED
    _clear_registered_context_callbacks()
    _INITIALIZED = False


def on_module_config_changed() -> None:
    """Module lifecycle hook called when module config changes."""
    rag_manager.refresh_config()
    _clear_registered_context_callbacks()


def initialize() -> bool:
    """Register RAG engine options into the app driver."""
    global _INITIALIZED, _RAG_OPTIONS_REGISTERED
    try:
        if _RAG_OPTIONS_REGISTERED:
            log("debug", "rag_manager: rag_engine options already registered")
        if not _RAG_OPTIONS_REGISTERED:
            log("info", "rag_manager: registering rag_engine driver options")
            for name, description in [
                ("simple", "Keyword-based retrieval — fast, no embeddings"),
                ("classic", "Vector similarity retrieval — standard RAG"),
                (
                    "faiss_hierarchical",
                    "Hierarchical chunking and retrieval — best for long documents",
                ),
            ]:
                if _engine_exists(name):
                    register_option(
                        group="rag_engine",
                        name=name,
                        activate_fn=lambda n=name: _activate_rag_engine(n),
                        deactivate_fn=lambda n=name: _deactivate_rag_engine(n),
                        description=description,
                    )
            _RAG_OPTIONS_REGISTERED = True
            from shared.common import get_driver
            options = [opt["name"] for opt in get_driver().list_options().get("rag_engine", [])]
            log("info", f"rag_manager: registered rag_engine options={options}")

        _INITIALIZED = True
        return True
    except Exception as exc:
        log("error", f"Failed to initialize rag_manager module driver options: {exc}", exc_info=True)
        return False


__all__ = [
    "RAGManager",
    "rag_manager",
    "initialize",
    "on_module_activated",
    "on_module_deactivated",
    "on_module_config_changed",
]
