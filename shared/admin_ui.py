# file name: shared/admin_ui.py
"""
Admin UI Module

Provides the admin interface for system management, module control,
and system information display.
"""

import streamlit as st
import os
from shared.logging import log
from shared.database import db_manager
from shared.config import get_config
# Import UIRegistry to fix the NameError
from shared.ui_registry import UIRegistry

def show_admin_page():
    """Display the Admin page."""
    st.title("🔧 Admin Panel")

    # Get the module handler from session state
    if 'module_handler' not in st.session_state:
        st.error("Module handler not initialized")
        return

    module_handler = st.session_state.module_handler
    config = get_config()

    # Get active modules
    active_modules = module_handler.get_active_modules()
    all_modules = module_handler.get_all_modules()

    # Module Management Section
    st.header("📦 Module Management")

    col1, col2 = st.columns([3, 1])
    with col1:
        st.subheader("Available Modules")
    with col2:
        if st.button("🔄 Refresh Modules", key="admin_refresh_modules"):
            module_handler.refresh_modules()
            st.rerun()

    # Display module status
    for module_name, module_info in all_modules.items():
        is_active = module_name in active_modules

        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.write(f"**{module_name}**")
            if module_info.get('description'):
                st.caption(module_info.get('description'))
            if module_info.get('version'):
                st.caption(f"Version: {module_info.get('version')}")

        with col2:
            status = "🟢 Active" if is_active else "🔴 Inactive"
            st.write(status)

        with col3:
            # Create a unique container for each module's buttons
            button_container = st.container()
            with button_container:
                if is_active:
                    # Use a form to handle the disable action properly
                    with st.form(key=f"disable_form_{module_name}"):
                        if st.form_submit_button("Disable",
                                               help=f"Disable {module_name} module",
                                               use_container_width=True):
                            log("debug", f"Attempting to disable module: {module_name}")
                            if module_handler.toggle_module(module_name, False):
                                # Save modules state first
                                module_handler._save_modules_file()
                                log("info", f"Module '{module_name}' disabled, modules file saved")

                                # Force UI registry to refresh on next render
                                if 'ui_registry' in st.session_state:
                                    del st.session_state.ui_registry

                                # Clear admin rendered flag so admin page refreshes
                                if 'admin_rendered' in st.session_state:
                                    del st.session_state.admin_rendered

                                # Use success message and immediate rerun
                                st.success(f"Module '{module_name}' disabled")
                                st.rerun()
                            else:
                                log("error", f"Toggle failed for {module_name}")
                                st.error(f"Failed to disable module '{module_name}'")
                else:
                    # Use a form to handle the enable action properly
                    with st.form(key=f"enable_form_{module_name}"):
                        if st.form_submit_button("Enable",
                                               help=f"Enable {module_name} module",
                                               use_container_width=True):
                            log("debug", f"Attempting to enable module: {module_name}")
                            if module_handler.toggle_module(module_name, True):
                                # Save modules state first
                                module_handler._save_modules_file()
                                log("info", f"Module '{module_name}' enabled, modules file saved")

                                # Force UI registry to refresh on next render
                                if 'ui_registry' in st.session_state:
                                    del st.session_state.ui_registry

                                # Clear admin rendered flag so admin page refreshes
                                if 'admin_rendered' in st.session_state:
                                    del st.session_state.admin_rendered

                                # Use success message and immediate rerun
                                st.success(f"Module '{module_name}' enabled")
                                st.rerun()

    # System Information Section
    st.header("ℹ️ System Information")

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Application")
        st.write(f"**Name:** {config.get('app.name', 'N/A')}")
        st.write(f"**Version:** {config.get('app.version', 'N/A')}")
        st.write(f"**Active Modules:** {len(active_modules)}/{len(all_modules)}")

        # Get UI registry modules count
        if 'ui_registry' in st.session_state:
            st.write(f"**UI Registry Modules:** {len(st.session_state.ui_registry.modules)}")
        else:
            st.write("**UI Registry Modules:** Not initialized")

    with col2:
        st.subheader("Database")

        # Import here to avoid circular imports
        from shared.users import user_manager

        # Get database path
        db_path = os.path.join("data", "app.db") if os.path.exists("data") else "memory"
        st.write(f"**Path:** {db_path}")
        st.write(f"**User Count:** {user_manager.get_user_count()}")

        # Count conversations
        try:
            from shared.conversation import ConversationTable
            with db_manager.get_session() as session:
                from sqlalchemy import func
                conv_count = session.query(func.count(ConversationTable.id)).scalar()
                st.write(f"**Conversation Count:** {conv_count}")
        except Exception as e:
            log("error", f"Error counting conversations: {str(e)}")
            st.write(f"**Conversation Count:** Error")

    # LLM Status Section
    st.header("🤖 LLM Status")

    # Import LLM functions
    try:
        from shared.llm import get_available_llms
        available_llms_list = get_available_llms()

        for llm_item in available_llms_list:
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1:
                status_icon = "🟢" if llm_item["available"] else "🔴"
                st.write(f"{status_icon} **{llm_item['name']}**")
                st.caption(f"{llm_item['type']} - {llm_item['model']}")

            with col2:
                st.write("Available" if llm_item["available"] else "Unavailable")

            with col3:
                if llm_item["requires_api_key"]:
                    has_key = bool(os.getenv(f"{llm_item['type'].upper()}_API_KEY"))
                    st.write("🔑 Key: " + ("✅" if has_key else "❌"))
    except Exception as e:
        log("error", f"Error loading LLM status: {str(e)}")
        st.error("Could not load LLM status")

# Register render functions for the UI registry
def admin_render():
    """Render admin content when admin page is active."""
    # Check if we're on the admin page
    if st.session_state.get('current_page') != 'admin':
        return None

    # Use a container with a unique key to ensure single rendering
    container = st.container(key="admin_container")

    with container:
        # Mark admin as rendered for this session
        st.session_state.admin_rendered = True

        # Render the admin page
        show_admin_page()

        # Return a non-None value to indicate content was rendered
        return True

# Export functions for the UI registry
# Note: We'll only use main_header to avoid duplicate rendering
sidebar = None
main_header = admin_render  # Render admin only in main_header
main_before_conversation = None  # Don't render in main_before_conversation
main_no_user = None
main_after_conversation = None
main_footer = None
