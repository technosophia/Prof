"""
Trainer Module
=============
Student training and progression tracking system.

This module provides tools for trainers (master users) to manage students (normal users),
track their progress, and customize the learning experience.

Features:
- Student dashboard with conversation stats
- Configurable system prompts for teacher AI
- Plugin system for extensibility
- Import/export of configuration
- Student note-taking pads (via plugin) with student UI injection

Dependencies:
- shared.users: User management and roles
- shared.conversation: Conversation tracking
- core.database: Database storage

UI Injection Points:
- Admin tab (for masters): inject_ui_admin_tab() in trainer_admin_ui.py
- Student pad (for normal users): inject_ui_main_header() in plugins/student_pad/student_pad_ui.py

File Naming Convention:
- *_ui.py files contain injection points for the main application
- *_admin_ui.py files contain admin tab injection points
"""

from shared.common import log, get_db_manager
from .models import StudentNote, PluginData, PluginActivation
from .manager import get_trainer_manager
from .plugin_base import get_plugin_manager

__all__ = [
    'get_trainer_manager',
    'get_plugin_manager',
    'StudentNote',
    'PluginData',
    'PluginActivation'
]


def initialize():
    """Initialize the Trainer module."""
    log("info", "Initializing Trainer module")

    # Initialize database tables (automatically created via Base)
    db = get_db_manager()

    # Initialize plugin system
    plugin_manager = get_plugin_manager()
    log("info", f"Loaded {len(plugin_manager.get_all_plugins())} Trainer plugins")

    return True
