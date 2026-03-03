# modules/rag_bench/__init__.py
"""
RAG Benchmark module - Admin tool to view LLM responses with RAG context.
Registers a monitor callback to capture LLM responses.
"""

from core.logging import log
from shared.common import check_services

_LLM_MANAGER = None
_MONITOR_CALLBACK = None
_RAG_CONTEXT_CALLBACK = None


def on_module_activated(services) -> None:
    """Initialize the module with injected services."""
    global _LLM_MANAGER, _MONITOR_CALLBACK, _RAG_CONTEXT_CALLBACK

    # Validate required services
    required = check_services(
        ["config", "llm_manager"],
        services=services,
        module_name="rag_bench",
    )

    llm_manager = required["llm_manager"]
    _LLM_MANAGER = llm_manager

    # Import here to avoid circular imports
    from modules.rag_bench.rag_bench_core import capture_llm_response, capture_rag_context

    # Register monitor callback to capture LLM responses
    _MONITOR_CALLBACK = capture_llm_response
    _MONITOR_CALLBACK.__name__ = "rag_bench_monitor_callback"
    _LLM_MANAGER.register_monitor_callback(_MONITOR_CALLBACK)

    # Register context callback to capture RAG context
    _RAG_CONTEXT_CALLBACK = capture_rag_context
    _RAG_CONTEXT_CALLBACK.__name__ = "rag_bench_context_callback"
    _LLM_MANAGER.register_context_callback(_RAG_CONTEXT_CALLBACK)

    log("info", "rag_bench: activated - monitoring LLM calls for RAG context")


def on_module_deactivated() -> None:
    """Unregister callbacks."""
    global _LLM_MANAGER, _MONITOR_CALLBACK, _RAG_CONTEXT_CALLBACK

    if _LLM_MANAGER is not None:
        if _MONITOR_CALLBACK is not None:
            _LLM_MANAGER.unregister_monitor_callback(_MONITOR_CALLBACK)
        if _RAG_CONTEXT_CALLBACK is not None:
            try:
                _LLM_MANAGER.unregister_context_callback(_RAG_CONTEXT_CALLBACK)
            except Exception:
                pass

    _LLM_MANAGER = None
    _MONITOR_CALLBACK = None
    _RAG_CONTEXT_CALLBACK = None
    log("info", "rag_bench: deactivated")
