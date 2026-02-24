"""
Suggest Plugin UI for Trainer Module.
Injects suggestion banner in the main header for normal users (students).
File ends with _ui.py and implements inject_ui_main_header() injection point.
"""

import streamlit as st
from shared.common import UserRole
from st_shared.cached import get_user_manager
from modules.trainer.plugin_base import get_plugin_manager
from modules.trainer.manager import get_trainer_manager


from st_shared.cached import _
def inject_ui_main_header():
    """
    Inject suggestion banner from active plugins.
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

    # Get the specific suggest plugin
    suggest_plugin = plugin_manager.get_plugin("suggest")

    # Check if plugin is active for this trainer
    if suggest_plugin and trainer_manager.is_plugin_active(parent_id, "suggest"):
        # Render the suggestion banner directly (no expander, should be visible)
        widgets = suggest_plugin.render_student_header_widgets(user['id'], parent_id)
        for widget in widgets:
            widget()
