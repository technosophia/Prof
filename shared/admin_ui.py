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

def show_system_admin_page(module_handler, config):
    """Display the System Admin page."""
    st.title("🔧 System Administration")

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

def show_module_admin_pages():
    """Display admin pages from all modules that have them."""
    # This will be populated by modules registering their admin pages
    pass

def show_admin_page():
    """Display the Admin page with tabs for system and modules."""
    st.title("🔧 Admin Panel")

    # Get the module handler from session state
    if 'module_handler' not in st.session_state:
        st.error("Module handler not initialized")
        return

    module_handler = st.session_state.module_handler
    config = get_config()

    # Initialize session state for admin tabs
    if 'admin_current_tab' not in st.session_state:
        st.session_state.admin_current_tab = "System"

    # Get all available tabs
    admin_tabs = ["System"]

    # Check for registered module admin pages
    if 'admin_registry' in st.session_state:
        for module_name in st.session_state.admin_registry.keys():
            if module_name not in admin_tabs:
                admin_tabs.append(module_name)

    # Create tabs
    tabs = st.tabs(admin_tabs)

    # System Admin Tab
    with tabs[0]:
        show_system_admin_page(module_handler, config)

    # Module Admin Tabs
    for i, tab_name in enumerate(admin_tabs[1:], 1):
        with tabs[i]:
            if 'admin_registry' in st.session_state and tab_name in st.session_state.admin_registry:
                try:
                    # Call the registered admin page function
                    st.session_state.admin_registry[tab_name]()
                except Exception as e:
                    st.error(f"Error loading {tab_name} admin page: {str(e)}")
                    log("error", f"Error loading {tab_name} admin page: {str(e)}", exc_info=True)

# NEW: Admin registry management functions
def register_admin_page(module_name, admin_function):
    """Register a module's admin page function."""
    if 'admin_registry' not in st.session_state:
        st.session_state.admin_registry = {}

    st.session_state.admin_registry[module_name] = admin_function
    log("info", f"Registered admin page for module: {module_name}")

def get_admin_registry():
    """Get the admin registry."""
    return st.session_state.get('admin_registry', {})

def inject_ui_initialize():
    """Initialize the UI registry."""
    if 'ui_registry' not in st.session_state:
        st.session_state.ui_registry = {}

# Register render functions for the UI registry
def inject_ui_main_header():
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
