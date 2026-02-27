# modules/rag_manager/__init__.py
"""
RAG Manager Module — Package Init

Functional lifecycle hooks (no Streamlit):
    on_module_activated(services)   — register driver options + LLM callbacks
    on_module_deactivated()         — unregister
    on_module_config_changed()      — refresh config

The module exposes RAGManager for direct use and rag_manager as the singleton
built by the factory. In a Streamlit context the factory uses st_shared.cached;
in a headless context call reset_rag_manager() + get_rag_manager(config, um).

No import of st_shared here. The singleton is obtained lazily via the factory.
"""

from typing import Callable, Dict, List, Optional, Any

from core.logging import log

# Will be set by on_module_activated
_services = None

_INITIALIZED = False
_RAG_OPTIONS_REGISTERED = False
_ENGINE_CONTEXT_CALLBACKS: Dict[str, Callable[[str, List[Dict]], tuple]] = {}


# ---------------------------------------------------------------------------
# Service locator management
# ---------------------------------------------------------------------------

def set_services(services):
    """Set the service locator for this module."""
    global _services
    _services = services
    log("debug", "RAG Manager: services set")


def _get_llm_callback_registry():
    """Get the LLM callback registry from services or fallback to shared.common."""
    if _services and 'llm_callback_registry' in _services:
        return _services.get('llm_callback_registry')
    else:
        # Fallback for backward compatibility
        from shared.common import register_llm_context_callback, unregister_llm_context_callback
        return type('FallbackRegistry', (), {
            'register': staticmethod(register_llm_context_callback),
            'unregister': staticmethod(unregister_llm_context_callback)
        })()


# ---------------------------------------------------------------------------
# Lazy singleton accessor (no Streamlit import at module level)
# ---------------------------------------------------------------------------
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.rag_manager.rag_manager import RAGManager

def _get_manager() -> "RAGManager":
    """Return the RAGManager singleton via the factory."""
    from modules.rag_manager.rag_factory import get_rag_manager
    return get_rag_manager()


# Backward-compat alias used by other parts of the codebase that do
#   from modules.rag_manager import rag_manager
# We expose a proxy that delegates attribute access to the factory singleton.
class _ManagerProxy:
    """
    Lazy proxy for RAGManager singleton.

    Allows `from modules.rag_manager import rag_manager` to work in both
    Streamlit and headless contexts without importing st_shared at module load.
    """
    def __getattr__(self, name: str):
        return getattr(_get_manager(), name)

    def __repr__(self):
        return f"<RAGManagerProxy -> {_get_manager()!r}>"


rag_manager = _ManagerProxy()


# ---------------------------------------------------------------------------
# Engine helpers  (defined BEFORE they're used)
# ---------------------------------------------------------------------------

def _engine_exists(name: str) -> bool:
    """Check if an engine exists and is enabled."""
    mgr = _get_manager()
    if mgr.get_engine(name) is None:
        return False
    return mgr.is_engine_enabled(name)


def _make_engine_context_callback(name: str) -> Callable:
    """Create a context callback for a specific engine."""
    def _callback(user_id: str, messages: List[Dict]) -> tuple:
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if not user_messages:
            return "", "system", "bottom"

        query = user_messages[-1].get("content", "")
        if not query:
            return "", "system", "bottom"

        mgr = _get_manager()
        if not mgr.is_rag_enabled() or not mgr.is_engine_enabled(name):
            return "", "system", "bottom"

        context = mgr.get_rag_context(user_id=user_id, query=query, engine_type=name)
        return context, "system", "bottom"

    _callback.__name__ = f"rag_context_callback_{name}"
    return _callback


def _activate_rag_engine(name: str) -> None:
    """Activate a RAG engine and register its callback."""
    try:
        if not _engine_exists(name):
            log("warning", f"Cannot activate unavailable RAG engine: {name}")
            return

        _get_manager().default_engine = name

        # First, deactivate any existing callback for this engine
        if name in _ENGINE_CONTEXT_CALLBACKS:
            _deactivate_rag_engine(name)

        # Create and register new callback
        callback = _make_engine_context_callback(name)
        _ENGINE_CONTEXT_CALLBACKS[name] = callback

        # Use the registry from services
        registry = _get_llm_callback_registry()
        registry.register(callback)
        log("debug", f"Registered RAG callback for engine: {name}")

    except Exception as exc:
        log("warning", f"Failed to activate RAG engine '{name}': {exc}")


def _deactivate_rag_engine(name: str) -> None:
    """Deactivate a RAG engine and unregister its callback."""
    callback = _ENGINE_CONTEXT_CALLBACKS.get(name)
    if callback is not None:
        # Use the registry from services
        registry = _get_llm_callback_registry()
        try:
            registry.unregister(callback)
            log("debug", f"Unregistered RAG callback for engine: {name}")
        except Exception as exc:
            log("warning", f"Failed to unregister RAG callback for {name}: {exc}")

        # Then remove from our internal dictionary
        del _ENGINE_CONTEXT_CALLBACKS[name]


def _clear_registered_context_callbacks() -> None:
    """Clear all registered context callbacks."""
    registry = _get_llm_callback_registry()

    for name, callback in list(_ENGINE_CONTEXT_CALLBACKS.items()):
        try:
            registry.unregister(callback)
            log("debug", f"Unregistered RAG callback for engine: {name}")
        except Exception as exc:
            log("debug", f"Failed to unregister RAG callback for {name}: {exc}")

    _ENGINE_CONTEXT_CALLBACKS.clear()


# ---------------------------------------------------------------------------
# Driver registration  (no Streamlit, safe to call headless)
# ---------------------------------------------------------------------------

def initialize() -> bool:
    """Register RAG engine options into the app driver."""
    global _INITIALIZED, _RAG_OPTIONS_REGISTERED
    try:
        if not _RAG_OPTIONS_REGISTERED:
            log("info", "rag_manager: registering rag_engine driver options")
            for name, description in [
                ("simple", "Keyword-based retrieval — fast, no embeddings"),
                ("classic", "Vector similarity retrieval — standard RAG"),
                ("faiss_hierarchical", "Hierarchical chunking and retrieval — best for long documents"),
            ]:
                if _engine_exists(name):  # Now this is defined
                    from shared.common import register_option
                    register_option(
                        group="rag_engine",
                        name=name,
                        activate_fn=lambda n=name: _activate_rag_engine(n),
                        deactivate_fn=lambda n=name: _deactivate_rag_engine(n),
                        description=description,
                    )
                    log("debug", f"  Registered rag_engine option: {name}")
            _RAG_OPTIONS_REGISTERED = True
            from shared.common import get_driver
            options = [opt["name"] for opt in get_driver().list_options().get("rag_engine", [])]
            log("info", f"rag_manager: registered rag_engine options={options}")

        _INITIALIZED = True
        return True
    except Exception as exc:
        log("error", f"Failed to initialize rag_manager driver options: {exc}", exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Module lifecycle hooks  (NO Streamlit)
# ---------------------------------------------------------------------------

def on_module_activated(services: Optional[Any] = None) -> None:
    """
    Called by ModuleHandler when the module is activated.

    Receives an optional ServiceLocator. If running headless (tests, CLI),
    services may be None or a plain ServiceLocator.

    Registers:
    - Driver options (rag_engine group)
    - LLM context callbacks for the default engine
    """
    # Store services for later use
    if services is not None:
        set_services(services)

        # If a ServiceLocator was provided, use it to build the manager with
        # injected dependencies instead of Streamlit-cached ones.
        cfg = services.get("config") if hasattr(services, "get") else None
        um = services.get("user_manager") if hasattr(services, "get") else None
        if cfg is not None and um is not None:
            from modules.rag_manager.rag_factory import get_rag_manager, reset_rag_manager
            from modules.rag_manager.rag_factory import _instance
            if _instance is None:
                get_rag_manager(config=cfg, user_manager=um)

    initialize()
    try:
        mgr = _get_manager()
        if mgr.is_rag_enabled() and mgr.default_engine:
            _activate_rag_engine(mgr.default_engine)
            log("info", f"RAG engine '{mgr.default_engine}' activated on module startup")
    except Exception as exc:
        log("warning", f"Failed to activate default RAG engine on startup: {exc}")


def on_module_deactivated() -> None:
    """Called by ModuleHandler when the module is deactivated."""
    global _INITIALIZED
    _clear_registered_context_callbacks()
    _INITIALIZED = False
    global _services
    _services = None


def on_module_config_changed() -> None:
    """Called by ModuleHandler when the module config changes."""
    _get_manager().refresh_config()
    _clear_registered_context_callbacks()


__all__ = [
    "RAGManager",
    "rag_manager",
    "initialize",
    "on_module_activated",
    "on_module_deactivated",
    "on_module_config_changed",
    "set_services",
    "_activate_rag_engine",
    "_deactivate_rag_engine",
    "_ENGINE_CONTEXT_CALLBACKS",
    "_make_engine_context_callback",
]
