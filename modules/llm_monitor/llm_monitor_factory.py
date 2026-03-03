"""Factory for creating the LLM monitor singleton with injected dependencies."""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.llm_monitor.llm_monitor import LLMMonitor

_instance: Optional["LLMMonitor"] = None


def get_llm_monitor(config=None, db_manager=None) -> "LLMMonitor":
    """Get or create the LLM monitor singleton."""
    global _instance
    if _instance is not None:
        return _instance

    if config is None:
        raise RuntimeError("llm_monitor_factory: 'config' is required")
    if db_manager is None:
        raise RuntimeError("llm_monitor_factory: 'db_manager' is required")

    from modules.llm_monitor.llm_monitor import LLMMonitor
    _instance = LLMMonitor(config=config, db_manager=db_manager)
    return _instance


def reset_llm_monitor() -> None:
    """Reset the singleton (for tests)."""
    global _instance
    _instance = None
