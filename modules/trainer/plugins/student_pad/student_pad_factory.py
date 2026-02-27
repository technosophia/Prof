"""
Student Pad Plugin Factory - Bridge between Streamlit-cached singletons and functional core.
This is the ONLY file in this module that may import from st_shared.cached.
"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from modules.trainer.plugins.student_pad import StudentPadPlugin

_instance: Optional["StudentPadPlugin"] = None


def get_student_pad_plugin(config=None, db_manager=None, user_manager=None,
                          conversation_manager=None, llm_manager=None) -> "StudentPadPlugin":
    """Get or create the StudentPadPlugin singleton with injected dependencies."""
    global _instance
    if _instance is not None:
        return _instance

    # This is the ONLY place where st_shared.cached is allowed!
    if any(v is None for v in [config, db_manager, user_manager, conversation_manager, llm_manager]):
        from st_shared.cached import (
            get_config, get_db_manager, get_user_manager,
            get_conversation_manager, get_llm_manager
        )
        if config is None:
            config = get_config()
        if db_manager is None:
            db_manager = get_db_manager()
        if user_manager is None:
            user_manager = get_user_manager()
        if conversation_manager is None:
            conversation_manager = get_conversation_manager()
        if llm_manager is None:
            llm_manager = get_llm_manager()

    from modules.trainer.plugins.student_pad import StudentPadPlugin
    from modules.trainer.plugins.student_pad.plugin import PluginManifest

    manifest = PluginManifest(
        id="student_pad",
        name="Student Pad",
        version="1.0.0",
        description="Personal note-taking pad for students with version history",
        author="System",
        enabled_by_default=True,
        category="memory"
    )

    _instance = StudentPadPlugin(manifest)
    # Initialize with services (this will set self.db, etc.)
    _instance.initialize(services=None)  # None triggers fallback to st_shared.cached
    return _instance


def reset_student_pad_plugin() -> None:
    """Reset the singleton (for tests)."""
    global _instance
    _instance = None
