# modules/llm_monitor/llm_monitor_factory.py
"""
Bridge between Streamlit-cached singletons and the pure functional core.
This is the ONLY file in this module that may import from st_shared.
"""

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

    if config is None or db_manager is None:
        from st_shared.cached import get_config, get_db_manager
        if config is None:
            config = get_config()
        if db_manager is None:
            db_manager = get_db_manager()

    from modules.llm_monitor.llm_monitor import LLMMonitor
    _instance = LLMMonitor(config=config, db_manager=db_manager)
    return _instance


def reset_llm_monitor() -> None:
    """Reset the singleton (for tests)."""
    global _instance
    _instance = None
