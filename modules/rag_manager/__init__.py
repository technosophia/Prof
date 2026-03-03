"""RAG manager module — driver options and LLM context callback lifecycle."""

from typing import Callable, Dict, List, Optional

from core.logging import log
from modules.rag_manager.rag_factory import get_rag_manager, reset_rag_manager


_LLM_MANAGER = None
_services = None
_ENGINE_CONTEXT_CALLBACKS: Dict[str, Callable[[str, List[Dict]], tuple]] = {}
_ACTIVE_ENGINE_NAME: Optional[str] = None


def set_services(services) -> None:
    """Compatibility helper used by tests to inject callback registry services."""
    global _services
    _services = services


def _callback_registry():
    if _services is not None and "llm_callback_registry" in _services:
        return _services.get("llm_callback_registry")
    return None


def _engine_exists(name: str) -> bool:
    manager = get_rag_manager()
    return manager.get_engine(name) is not None and manager.is_engine_enabled(name)


def _make_engine_context_callback(name: str) -> Callable:
    def _callback(user_id: str, messages: List[Dict]) -> tuple:
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if not user_messages:
            return "", "system", "bottom"
        query = user_messages[-1].get("content", "")
        if not query:
            return "", "system", "bottom"

        manager = get_rag_manager()
        if not manager.is_rag_enabled() or not manager.is_engine_enabled(name):
            return "", "system", "bottom"
        if _ACTIVE_ENGINE_NAME != name:
            return "", "system", "bottom"

        context = manager.get_rag_context(user_id=user_id, query=query, engine_type=name)
        return context, "system", "bottom"

    _callback.__name__ = f"rag_context_callback_{name}"
    return _callback


def _register_context_callback(callback: Callable) -> None:
    registry = _callback_registry()
    if registry is not None:
        registry.register(callback)
        return
    if _LLM_MANAGER is None:
        raise RuntimeError("rag_manager: 'llm_manager' is not initialized")
    _LLM_MANAGER.register_context_callback(callback)


def _unregister_context_callback(callback: Callable) -> None:
    registry = _callback_registry()
    if registry is not None:
        registry.unregister(callback)
        return
    if _LLM_MANAGER is not None:
        _LLM_MANAGER.unregister_context_callback(callback)


def _resolve_activation_engine(name: str) -> Optional[str]:
    if _engine_exists(name):
        return name
    for candidate in ("simple", "classic", "faiss_hierarchical"):
        if _engine_exists(candidate):
            return candidate
    return None


def _activate_rag_engine(name: str) -> None:
    global _ACTIVE_ENGINE_NAME

    resolved_name = _resolve_activation_engine(name)
    if resolved_name is None:
        log("warning", f"Cannot activate unavailable RAG engine: {name}")
        return
    if resolved_name != name:
        log("warning", f"RAG engine '{name}' unavailable, falling back to '{resolved_name}'")
    name = resolved_name

    manager = get_rag_manager()
    manager.default_engine = name

    if _ACTIVE_ENGINE_NAME and _ACTIVE_ENGINE_NAME != name:
        _deactivate_rag_engine(_ACTIVE_ENGINE_NAME)

    callback = _ENGINE_CONTEXT_CALLBACKS.get(name)
    if callback is None:
        callback = _make_engine_context_callback(name)
        _ENGINE_CONTEXT_CALLBACKS[name] = callback

    _register_context_callback(callback)
    _ACTIVE_ENGINE_NAME = name
    log("info", f"Activated RAG engine: {name}")


def _deactivate_rag_engine(name: str) -> None:
    global _ACTIVE_ENGINE_NAME

    callback = _ENGINE_CONTEXT_CALLBACKS.get(name)
    if callback is None:
        return

    _unregister_context_callback(callback)

    del _ENGINE_CONTEXT_CALLBACKS[name]
    if _ACTIVE_ENGINE_NAME == name:
        _ACTIVE_ENGINE_NAME = None


def _clear_registered_context_callbacks() -> None:
    global _ACTIVE_ENGINE_NAME

    for callback in list(_ENGINE_CONTEXT_CALLBACKS.values()):
        _unregister_context_callback(callback)
    _ENGINE_CONTEXT_CALLBACKS.clear()
    _ACTIVE_ENGINE_NAME = None


def on_module_activated(services) -> None:
    """Register driver options and activate the default RAG context callback."""
    global _LLM_MANAGER

    driver = services.get("driver")
    config = services.get("config")
    user_manager = services.get("user_manager")
    llm_manager = services.get("llm_manager")
    cache_fn = services.get("cache")

    if driver is None:
        raise RuntimeError("rag_manager: 'driver' service not available")
    if config is None:
        raise RuntimeError("rag_manager: 'config' service not available")
    if user_manager is None:
        raise RuntimeError("rag_manager: 'user_manager' service not available")
    if llm_manager is None:
        raise RuntimeError("rag_manager: 'llm_manager' service not available")

    set_services(services)
    _LLM_MANAGER = llm_manager
    reset_rag_manager()
    manager = get_rag_manager(config=config, user_manager=user_manager)
    manager._cache_fn = cache_fn

    for name, description in [
        ("simple", "Keyword-based retrieval — fast, no embeddings"),
        ("classic", "Vector similarity retrieval — standard RAG"),
        ("faiss_hierarchical", "Hierarchical chunking and retrieval"),
    ]:
        if _engine_exists(name):
            driver.register_option(
                group="rag_engine",
                name=name,
                activate_fn=lambda n=name: _activate_rag_engine(n),
                deactivate_fn=lambda n=name: _deactivate_rag_engine(n),
                description=description,
            )

    _clear_registered_context_callbacks()
    if manager.is_rag_enabled() and manager.default_engine:
        _activate_rag_engine(manager.default_engine)

    log("info", "rag_manager: activated")


def on_module_deactivated() -> None:
    """Unregister RAG callbacks."""
    global _LLM_MANAGER, _services
    _clear_registered_context_callbacks()
    _LLM_MANAGER = None
    _services = None
    log("info", "rag_manager: deactivated")


def on_module_config_changed() -> None:
    """Reload config-dependent state."""
    manager = get_rag_manager()
    manager.refresh_config()
    _clear_registered_context_callbacks()
    if manager.is_rag_enabled() and manager.default_engine:
        _activate_rag_engine(manager.default_engine)


__all__ = [
    "rag_manager",
    "set_services",
    "on_module_activated",
    "on_module_deactivated",
    "on_module_config_changed",
    "_activate_rag_engine",
    "_deactivate_rag_engine",
    "_ENGINE_CONTEXT_CALLBACKS",
    "_make_engine_context_callback",
    "_services",
]


class _ManagerProxy:
    def __getattr__(self, name: str):
        return getattr(get_rag_manager(), name)


rag_manager = _ManagerProxy()
