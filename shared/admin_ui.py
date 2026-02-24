# file name: shared/admin_ui.py
"""
Admin UI Module

Provides the admin interface for system management, module control,
and system information display.
Uses the new UI injection mechanism with admin_tab injection point.
"""

import streamlit as st
import os
import sys

from shared.cached import get_config
from shared.cached import get_user_manager
from shared.ui_registry import _discover_ui_modules  # Import the standalone function


from core.logging import log, set_module_level
from shared.cached import _
def force_reload_modules():
    """Force reload all active modules by clearing cache and re-importing."""
    if 'module_handler' not in st.session_state:
        st.error("Module handler not initialized")
        return [], []

    module_handler = st.session_state.module_handler
    active_modules = module_handler.get_active_modules()

    # Track reloaded modules
    reloaded = []
    failed = []

    with st.spinner("Force reloading modules..."):
        for module_name in active_modules:
            try:
                # Clear from sys.modules if already loaded
                module_ui_name = f"{module_name}_ui"
                if module_ui_name in sys.modules:
                    # Remove the module from cache
                    del sys.modules[module_ui_name]
                    log("debug", f"Removed {module_ui_name} from sys.modules cache")

                # Also clear any parent packages if they exist
                if module_name in sys.modules:
                    del sys.modules[module_name]

                # Reload the module UI
                ui_module = module_handler.load_module_ui(module_name)
                if ui_module:
                    reloaded.append(module_name)
                    log("info", f"Successfully reloaded module: {module_name}")
                else:
                    failed.append(module_name)
                    log("error", f"Failed to reload module: {module_name}")

            except Exception as e:
                failed.append(module_name)
                log("error", f"Error reloading module {module_name}: {str(e)}", exc_info=True)

        # Refresh module discovery to pick up any new files
        try:
            module_handler.refresh()
            log("info", "Module discovery refreshed")
        except Exception as e:
            log("error", f"Error refreshing module discovery: {str(e)}")

        # Re-initialize UI registry to pick up new injection points
        if 'ui_registry' in st.session_state:
            try:
                log("info", "Re-initializing UI registry after module reload")
                # Get current active modules
                active_modules = module_handler.get_active_modules()
                # Call the standalone discovery function
                modules, injection_points = _discover_ui_modules(tuple(sorted(active_modules)))
                # Update the registry's internal state
                st.session_state.ui_registry.modules = modules
                st.session_state.ui_registry.injection_points = injection_points
                st.session_state.ui_registry.last_active_hash = tuple(sorted(active_modules))
                log("info", f"UI Registry updated: {len(modules)} modules registered")
            except Exception as e:
                log("error", f"Error re-initializing UI registry: {str(e)}", exc_info=True)

    return reloaded, failed


def show_system_admin_content():
    """Display the System Admin content (for the System tab)."""
    st.header("📦 Module Management")

    # Get module handler from session state
    if 'module_handler' not in st.session_state:
        st.error("Module handler not initialized")
        return

    module_handler = st.session_state.module_handler

    # Get active modules
    try:
        active_modules = module_handler.get_active_modules()
        all_modules = module_handler.get_all_modules()
    except Exception as e:
        st.error(f"Error loading modules: {str(e)}")
        log("error", f"Error in show_system_admin_content: {str(e)}", exc_info=True)
        return

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.subheader("Available Modules")
    with col2:
        # Refresh modules button
        if st.button("🔄 Refresh Modules", key="admin_refresh_modules"):
            try:
                module_handler.refresh()
                st.success("Modules refreshed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Error refreshing modules: {str(e)}")
    with col3:
        # Force reload button
        if st.button("⚡ Force Reload All", key="admin_force_reload",
                    help="Force reload all active modules (clears cache)"):
            reloaded, failed = force_reload_modules()
            if reloaded:
                st.success(f"✅ Successfully reloaded: {', '.join(reloaded)}")
            if failed:
                st.error(f"❌ Failed to reload: {', '.join(failed)}")
            if reloaded or failed:
                st.rerun()

    # Display module status
    for module_name, module_info in all_modules.items():
        is_active = module_name in active_modules

        col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
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
            if is_active:
                # Individual reload button for active modules
                if st.button("🔄 Reload", key=f"reload_{module_name}",
                           help=f"Force reload {module_name} module"):
                    try:
                        # Clear from cache
                        module_ui_name = f"{module_name}_ui"
                        if module_ui_name in sys.modules:
                            del sys.modules[module_ui_name]

                        # Reload
                        ui_module = module_handler.load_module_ui(module_name)
                        if ui_module:
                            # Re-initialize UI registry
                            if 'ui_registry' in st.session_state:
                                # Get current active modules
                                active_mods = module_handler.get_active_modules()
                                # Call the standalone discovery function
                                modules, injection_points = _discover_ui_modules(tuple(sorted(active_mods)))
                                # Update the registry's internal state
                                st.session_state.ui_registry.modules = modules
                                st.session_state.ui_registry.injection_points = injection_points
                                st.session_state.ui_registry.last_active_hash = tuple(sorted(active_mods))
                            st.success(f"✅ Module '{module_name}' reloaded")
                            st.rerun()
                        else:
                            st.error(f"❌ Failed to reload '{module_name}'")
                    except Exception as e:
                        st.error(f"Error reloading module: {str(e)}")
                        log("error", f"Error reloading {module_name}: {str(e)}", exc_info=True)

        with col4:
            if is_active:
                if st.button("Disable", key=f"disable_{module_name}",
                           help=f"Disable {module_name} module",
                           use_container_width=True):
                    if module_handler.toggle_module(module_name, False):
                        st.success(f"Module '{module_name}' disabled")
                        st.rerun()
            else:
                if st.button("Enable", key=f"enable_{module_name}",
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
        db_path = os.path.join("data", "app.db") if os.path.exists("data") else "memory"
        st.write(f"**Path:** {db_path}")

        # Show module cache status
        st.subheader("Module Cache")
        cached_modules = [name for name in sys.modules.keys() if name.endswith('_ui')]
        st.write(f"**Cached UI Modules:** {len(cached_modules)}")
        if cached_modules and st.checkbox("Show cached modules", key="show_cache"):
            st.code("\n".join(sorted(cached_modules)))


def inject_ui_admin_tab():
    """Register the System admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("System", show_system_admin_content)


def inject_ui_initialize():
    """Initialize the admin UI module."""
    # No need to register anything here - handled by UI registry
    pass
