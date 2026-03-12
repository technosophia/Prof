"""
Student Pad UI for Trainer Module.
Injects a personal note-taking pad in the main header for normal users (students).
File ends with _ui.py and implements inject_ui_main_header() injection point.
"""

import streamlit as st
from shared.common import UserRole
from modules.trainer.plugin_base import get_plugin_manager
from modules.trainer.manager import get_trainer_manager


def _get_student_pad_plugin():
    """Get the student pad plugin instance (uses factory)."""
    from modules.trainer.plugins.student_pad.student_pad_factory import get_student_pad_plugin
    return get_student_pad_plugin()


def inject_ui_main_header():
    """
    Inject student pad UI from active plugins.
    This delegates to plugins that implement render_student_header_widgets.
    """
    if "current_user" not in st.session_state or not st.session_state.current_user:
        return

    user = st.session_state.current_user
    user_role = st.session_state.current_user['role']

    if user_role != UserRole.NORMAL.value:
        return

    parent_id = user.get('parent_id')
    if not parent_id:
        return

    # Get the plugin manager and trainer manager
    plugin_manager = get_plugin_manager()
    trainer_manager = get_trainer_manager()

    # Get the specific student pad plugin
    student_pad_plugin = plugin_manager.get_ui_plugin("student_pad")


    # Fallback to factory if not found in plugin manager (during migration)
    if student_pad_plugin is None:
        student_pad_plugin = _get_student_pad_plugin()

    # Use trainer_manager to check if plugin is active
    if student_pad_plugin and trainer_manager.is_plugin_active(parent_id, "student_pad"):
        with st.container():
            with st.expander("📝 My Learning Tools", expanded=False):
                st.caption("Quick access to your personal notes")
                st.divider()

                widgets = student_pad_plugin.render_student_header_widgets(user['id'], parent_id)
                for widget in widgets:
                    widget()
