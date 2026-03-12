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

from shared.module_handler import module_handler, reload_module
from st_shared.cached import get_config
from st_shared.cached import get_user_manager

from core.logging import log, set_log_module_level
from st_shared.cached import _, _discover_ui_modules, get_active_modules


def _refresh_ui_registry(active_modules):
    """Re-discover injection points and update the UI registry in session state."""
    if 'ui_registry' not in st.session_state:
        return
    try:
        modules, injection_points = _discover_ui_modules(tuple(sorted(active_modules)))
        st.session_state.ui_registry.modules = modules
        st.session_state.ui_registry.injection_points = injection_points
        st.session_state.ui_registry.last_active_hash = tuple(sorted(active_modules))
        log("info", f"UI Registry updated: {len(modules)} modules registered")
    except Exception as e:
        log("error", f"Error re-initializing UI registry: {str(e)}", stacktrace=True)


def force_reload_modules():
    """Hot-reload all active modules via module_handler.reload_module()."""
    active_modules = get_active_modules()

    reloaded = []
    failed = []

    with st.spinner("Force reloading modules..."):
        for module_name in active_modules:
            try:
                if reload_module(module_name):
                    # Also reload the UI file so inject_ui_* picks up new code
                    module_handler.load_module_ui(module_name)
                    reloaded.append(module_name)
                    log("info", f"Successfully reloaded module: {module_name}")
                else:
                    failed.append(module_name)
                    log("error", f"reload_module() returned False for: {module_name}")
            except Exception as e:
                failed.append(module_name)
                log("error", f"Error reloading module {module_name}: {str(e)}", stacktrace=True)

        # Refresh module discovery to pick up any new files
        try:
            module_handler.refresh()
            log("info", "Module discovery refreshed")
        except Exception as e:
            log("error", f"Error refreshing module discovery: {str(e)}")

        _refresh_ui_registry(get_active_modules())

    return reloaded, failed


def show_system_admin_content():
    """Display the System Admin content (for the System tab)."""
    st.header("📦 Module Management")

    # Get active modules
    try:
        active_modules = get_active_modules()
        all_modules = module_handler.get_all_modules()
    except Exception as e:
        st.error(f"Error loading modules: {str(e)}")
        log("error", f"Error in show_system_admin_content: {str(e)}", stacktrace=True)
        return

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        st.subheader("Available Modules")
    with col2:
        if st.button("🔄 Refresh Modules", key="admin_refresh_modules"):
            try:
                module_handler.refresh()
                st.success("Modules refreshed successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"Error refreshing modules: {str(e)}")
    with col3:
        if st.button("⚡ Force Reload All", key="admin_force_reload",
                    help="Hot-reload all active modules (no app restart needed)"):
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
                if st.button("🔄 Reload", key=f"reload_{module_name}",
                           help=f"Hot-reload {module_name} (no app restart needed)"):
                    try:
                        if reload_module(module_name):
                            module_handler.load_module_ui(module_name)
                            _refresh_ui_registry(get_active_modules())
                            st.success(f"✅ Module '{module_name}' reloaded")
                            st.rerun()
                        else:
                            st.error(f"❌ Failed to reload '{module_name}'")
                    except Exception as e:
                        st.error(f"Error reloading module: {str(e)}")
                        log("error", f"Error reloading {module_name}: {str(e)}", stacktrace=True)

        with col4:
            if is_active:
                if st.button("Disable", key=f"disable_{module_name}",
                           help=f"Disable {module_name} module",
                           width='stretch'):
                    if module_handler.toggle_module(module_name, False):
                        st.success(f"Module '{module_name}' disabled")
                        st.rerun()
            else:
                if st.button("Enable", key=f"enable_{module_name}",
                           help=f"Enable {module_name} module",
                           width='stretch'):
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

        config = get_config()
        db_url = config.get("database.path", "sqlite:///data/app.db")

        from core.database import extract_sqlite_file_path
        file_path = extract_sqlite_file_path(db_url)

        if file_path:
            db_display = file_path
            db_exists = os.path.exists(file_path)
            if db_exists:
                db_size = os.path.getsize(file_path) / (1024 * 1024)
                st.write(f"**Path:** `{db_display}`")
                st.write(f"**Size:** {db_size:.2f} MB")
            else:
                st.write(f"**Path:** `{db_display}` (file not found)")
        else:
            st.write(f"**URL:** `{db_url}`")
            if db_url == 'sqlite:///:memory:':
                st.write("**Type:** In-memory database")

        from core.database import get_db_manager
        db_manager = get_db_manager()
        if db_manager.is_initialized():
            st.write(f"**Status:** {'🟢 Connected' if db_manager.is_initialized() else '🔴 Not connected'}")
            st.write(f"**Tables created:** {'✅ Yes' if db_manager.are_tables_created() else '❌ No'}")

            migration_status = db_manager.get_migration_status()
            if migration_status.get("alembic_available") and not migration_status.get("in_memory"):
                st.write(f"**Schema revision:** {migration_status.get('current_revision', 'N/A')}")

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
    pass
