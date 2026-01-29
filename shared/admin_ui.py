# file name: shared/admin_ui.py
"""
Admin UI Module

Provides the admin interface for system management, module control,
and system information display.
Uses the new UI injection mechanism with admin_tab injection point.
"""

import streamlit as st
import os
from shared.logging import log
from shared.database import db_manager
from shared.config import get_config
from shared.translate import _

def show_system_admin_content():
    """Display the System Admin content (for the System tab)."""
    st.header("📦 Module Management")

    # Get module handler from session state
    if 'module_handler' not in st.session_state:
        st.error("Module handler not initialized")
        return

    module_handler = st.session_state.module_handler

    # Get active modules
    active_modules = module_handler.get_active_modules()
    all_modules = module_handler.get_all_modules()

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
            button_container = st.container()
            with button_container:
                if is_active:
                    with st.form(key=f"disable_form_{module_name}"):
                        if st.form_submit_button("Disable",
                                               help=f"Disable {module_name} module",
                                               use_container_width=True):
                            if module_handler.toggle_module(module_name, False):
                                st.success(f"Module '{module_name}' disabled")
                                st.rerun()
                else:
                    with st.form(key=f"enable_form_{module_name}"):
                        if st.form_submit_button("Enable",
                                               help=f"Enable {module_name} module",
                                               use_container_width=True):
                            if module_handler.toggle_module(module_name, True):
                                st.success(f"Module '{module_name}' enabled")
                                st.rerun()

    # System Information Section
    st.header("ℹ️ System Information")

    config = get_config()

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Application")
        st.write(f"**Name:** {config.get('app.name', 'N/A')}")
        st.write(f"**Version:** {config.get('app.version', 'N/A')}")
        st.write(f"**Active Modules:** {len(active_modules)}/{len(all_modules)}")

    with col2:
        st.subheader("Database")
        from shared.users import user_manager

        db_path = os.path.join("data", "app.db") if os.path.exists("data") else "memory"
        st.write(f"**Path:** {db_path}")
        st.write(f"**User Count:** {user_manager.get_user_count()}")

def inject_ui_admin_tab():
    """Register the System admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("System", show_system_admin_content)

def inject_ui_initialize():
    """Initialize the admin UI module."""
    # No need to register anything here - handled by UI registry
