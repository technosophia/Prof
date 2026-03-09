"""RAG manager module — driver options and LLM context callback lifecycle."""

from typing import Callable, Dict, List, Optional

from core.logging import log
from shared.common import check_services
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
    # Fall back to any available engine — not a hardcoded list.
    manager = get_rag_manager()
    for candidate in manager.get_engine_ids():
        if _engine_exists(candidate):
            log("warning", f"RAG engine '{name}' unavailable, falling back to '{candidate}'")
            return candidate
    return None


def _activate_rag_engine(name: str) -> None:
    global _ACTIVE_ENGINE_NAME

    resolved_name = _resolve_activation_engine(name)
    if resolved_name is None:
        log("warning", f"Cannot activate unavailable RAG engine: {name}")
        return
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

    required = check_services(
        ["driver", "config", "user_manager", "llm_manager"],
        services=services,
        module_name="rag_manager",
    )
    driver = required["driver"]
    config = required["config"]
    user_manager = required["user_manager"]
    llm_manager = required["llm_manager"]
    cache_fn = services.get("cache") if "cache" in services else None

    set_services(services)
    _LLM_MANAGER = llm_manager
    reset_rag_manager()
    try:
        manager = get_rag_manager(config=config, user_manager=user_manager)
    except Exception as e:
        # Most common cause: syntax error in config.json making rag_manager.engines
        # unparseable, which leaves self.engines empty and causes "Cannot activate" warnings.
        log("error",
            f"rag_manager: failed to initialize RAGManager — {e}. "
            f"Check config.json for syntax errors in the rag_manager.engines section.")
        raise
    manager._cache_fn = cache_fn

    # Register ALL engines declared in config — not a hardcoded list.
    # Engine description comes from the instance itself (set in __init__ or config).
    for name in manager.get_engine_ids():
        if not _engine_exists(name):
            log("debug", f"rag_manager: skipping unavailable engine '{name}'")
            continue
        engine = manager.get_engine(name)
        description = getattr(engine, "description", name)
        driver.register_option(
            group="rag_engine",
            name=name,
            activate_fn=lambda n=name: _activate_rag_engine(n),
            deactivate_fn=lambda n=name: _deactivate_rag_engine(n),
            description=description,
        )
        log("debug", f"rag_manager: registered driver option for engine '{name}'")

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
