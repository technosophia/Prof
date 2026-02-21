"""
Student Pad UI for Trainer Module.
Injects a personal note-taking pad in the main header for normal users (students).
File ends with _ui.py and implements inject_ui_main_header() injection point.
"""

import streamlit as st
from shared.common import _, UserRole
from shared.cached import get_user_manager
from modules.trainer.plugin_base import get_plugin_manager
from modules.trainer.manager import get_trainer_manager


def inject_ui_main_header():
    """
    Inject student pad UI from active plugins.
    This delegates to plugins that implement render_student_header_widgets.
    """
    if not ("current_user" in st.session_state and st.session_state.current_user):
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
    student_pad_plugin = plugin_manager.get_plugin("student_pad")

    # Use trainer_manager to check if plugin is active
    if student_pad_plugin and trainer_manager.is_plugin_active(parent_id, "student_pad"):
        # Create a container for all student header widgets
        with st.container():
            # Add a main expander for student tools
            with st.expander(_("trainer_plugin_student_pad.my_learning_tools"), expanded=False):
                st.caption(_("trainer_plugin_student_pad.quick_access"))
                st.divider()

                # Render the student pad widget directly
                widgets = student_pad_plugin.render_student_header_widgets(user['id'], parent_id)
                for widget in widgets:
                    widget()
