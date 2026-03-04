# /prof.py
"""
Main entry point for application
"""

from st_shared.warnings import ignore_warnings
ignore_warnings()


import streamlit as st
import os
import sys
import asyncio
from dotenv import load_dotenv

# Load environment variables FIRST
from core.logging import log, set_log_module_level
from core.database import init_database
from shared.module_handler import ServiceLocator, module_handler
from st_shared.cached import _, get_available_languages, get_active_modules
load_dotenv()

# Add shared directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "shared"))

# Import everything needed - CONFIG FIRST!

from st_shared.cached import get_config
from core.logging import configure_logging_from_dict

from st_shared.cached import get_db_manager, get_user_manager, get_conversation_manager, get_driver
from shared.common import init_user_manager
from st_shared.cached import get_prompt_manager, get_llm_manager
from shared.export_import import auto_import_conversations_from_config
from st_shared.cached import get_language_service

# IMPORTANT: Don't alias 'llm' to avoid name conflicts
from shared.common import llm_conversation_generate, set_current_llm, get_available_llms, get_current_llm_info
from st_shared.cached import register_all_services
# Import UI registry system
from shared.ui_registry import UIRegistry
# Import module handler
from st_shared.users_ui import auto_login_first_user

# Configure logging from config (one line)
configure_logging_from_dict(get_config().get("logging", {}))

get_available_languages()

db_path = get_config().get("database", {}).get("path", "data/app.db")
init_database(use_memory=False, db_path=db_path)

register_all_services()
# Add other services as needed
module_handler.initialize()
# IMPORTANT: Activate all modules to trigger on_module_activated() hooks
module_handler.activate_all()

# Get the language service and set up the resolver
language_service = get_language_service()

def streamlit_language_resolver():
    """Get current language from Streamlit session state."""
    import streamlit as st
    if "current_language" not in st.session_state:
        st.session_state.current_language = "en"
    return st.session_state.current_language

language_service.set_language_resolver(streamlit_language_resolver)

# Load active module UIs immediately
active_modules = get_active_modules()
for module_name in active_modules:
    ui_module = module_handler.load_module_ui(module_name)
    if ui_module:
        log("debug", f"Successfully loaded UI for module: {module_name}")
    else:
        log("warning", f"Could not load UI for module: {module_name}")

# Auto-upgrade database schema if needed
log("debug", "Checking database schema version...")
try:
    # This will automatically upgrade to latest if needed
    get_db_manager().check_and_upgrade_schema()
    log("debug", "Database schema is up to date")
except Exception as e:
    log("error", f"Database schema upgrade failed: {e}", stacktrace=True)
    st.error(f"Database migration failed: {e}. Please check logs.")

init_user_manager(create_default_users=True)
get_prompt_manager()
auto_import_conversations_from_config(
    user_manager=get_user_manager(),
    conversation_manager=get_conversation_manager(),
    config=get_config(),
)

# Initialize UI registry - do this here, not inside main()
# The registry will be cached in session state
if 'ui_registry' not in st.session_state:
    log("debug", "Initializing UI registry in session state")
    st.session_state.ui_registry = UIRegistry()

# Get the registry from session state
ui_registry = st.session_state.ui_registry
ui_registry.set_module_handler(module_handler, get_config().get("ui.shared_dir", None))

# Page configuration
st.set_page_config(
    page_title="IAthena",
    page_icon="🌍",
    layout="wide"
)

# Initialize critical session state variables BEFORE main()
if "current_user" not in st.session_state:
    st.session_state.current_user = None

if "app_initialized" not in st.session_state:
    st.session_state.app_initialized = False

# Add a flag to track if user explicitly logged out/switched
if "user_manually_logged_out" not in st.session_state:
    st.session_state.user_manually_logged_out = False

# Initialize admin tab state
if "admin_current_tab" not in st.session_state:
    st.session_state.admin_current_tab = "System"

if "current_language" not in st.session_state:
    st.session_state.current_language = "en"

# Track active admin tab index for lazy loading
if "active_admin_tab_index" not in st.session_state:
    st.session_state.active_admin_tab_index = 0

def can_access_admin(current_user):
    """Check if current user can access admin panel."""
    if not current_user:
        return False

    # Only admin and master users can access admin
    from shared.common import UserRole
    return current_user.get("role") in [UserRole.ADMIN.value, UserRole.MASTER.value]


def render_admin_tabs_lazy(admin_tabs_dict):
    if not admin_tabs_dict:
        return

    tab_names = list(admin_tabs_dict.keys())
    if "System" in tab_names:
        tab_names.remove("System")
        tab_names = ["System"] + sorted(tab_names)

    test_mode = os.getenv("TEST_MODE") == "true" or "pytest" in sys.modules
    if test_mode:
        # Use regular tabs that render all content (test mode expects this)
        tabs = st.tabs(tab_names)
        for i, tab_name in enumerate(tab_names):
            with tabs[i]:
                try:
                    admin_tabs_dict[tab_name]()
                except Exception as e:
                    st.error(f"Error loading {tab_name} admin page: {str(e)}")
                    log("error", f"Error loading {tab_name} admin page: {str(e)}", stacktrace=True)
        return

    # Segmented control looks like tabs but supports lazy loading
    selected_tab = st.segmented_control(
        "Admin Sections",
        options=tab_names,
        default=tab_names[0],
        selection_mode="single",
        label_visibility="collapsed"
    )

    st.divider()

    if selected_tab and selected_tab in admin_tabs_dict:
        admin_tabs_dict[selected_tab]()


def main():
    # Log main function entry
    log("debug", "Entering main function")

    # NEW: Check if app needs initialization
    if not st.session_state.app_initialized:
        # Initialize session state for page navigation
        if "current_page" not in st.session_state:
            st.session_state.current_page = "chat"

        # Initialize session state for UI modules
        if "ui_modules_initialized" not in st.session_state:
            st.session_state.ui_modules_initialized = False

        # Initialize the just_auto_logged_in flag
        if "just_auto_logged_in" not in st.session_state:
            st.session_state.just_auto_logged_in = False

        # Mark as initialized
        st.session_state.app_initialized = True
        log("debug", "App initialization complete")

    # INJECTION POINT: Initialize - for setting up session state variables
    log("debug", "Calling UI module initialization functions")
    initialization_results = ui_registry.render_all("initialize")

    auto_login_first_user()

    # Apply user preferences if a user is logged in
    current_user = st.session_state.get("current_user")

    # Sidebar for language, LLM, navigation, and injected UI modules
    with st.sidebar:

        # Navigation buttons
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("💬 Chat", width='stretch'):
                st.session_state.current_page = "chat"
                st.rerun()

        with col2:
            if st.button("⚙️ Settings", width='stretch'):
                st.session_state.current_page = "settings"
                st.rerun()

        with col3:
            # Only show Admin button for users who can access it
            if can_access_admin(current_user):
                if st.button("🔧 Admin", width='stretch'):
                    st.session_state.current_page = "admin"
                    st.rerun()
            else:
                # Disabled button for normal users
                st.button("🔧 Admin", width='stretch', disabled=True,
                         help="Admin access requires Master or Admin role")

        # INJECTION POINT 2: Sidebar Content from UI Modules
        # Call all registered sidebar render functions
        sidebar_contents = ui_registry.render_all("sidebar")

        # Show current language and LLM info
        st.caption(_("current_language"))

    # Main content - Page Router
    if st.session_state.current_page == "chat":
        # Chat page content
        st.title(_("hello_world"))

        # INJECTION POINT 3: Main Header Content from UI Modules
        header_contents = ui_registry.render_all("main_header")

        # INJECTION POINT 4: Main Content from UI Modules (before conversation interface)
        main_contents_before = ui_registry.render_all("main_before_conversation")

        # INJECTION POINT 5: Main Content when no user is logged in
        no_user_contents = ui_registry.render_all("main_content")

        # Let UI modules handle ALL content - no default fallback content in prof.py
        # Each UI module should handle its own fallback logic

        # INJECTION POINT 6: Main Content after conversation interface
        main_contents_after = ui_registry.render_all("main_after_conversation")

        # INJECTION POINT 7: Main Footer Content
        main_footer = ui_registry.render_all("main_footer")

    elif st.session_state.current_page == "settings":
        # Settings page content
        st.title("⚙️ User Settings")

        current_user = st.session_state.get("current_user")

        if not current_user:
            st.warning("Please log in to access settings.")
            st.info("Use the sidebar to select or create a user.")

            if st.button("Back to Chat"):
                st.session_state.current_page = "chat"
                st.rerun()
        else:
            # INJECTION POINT: Settings Content from UI Modules
            settings_contents = ui_registry.render_all("settings_content")

            if not settings_contents:
                st.info("No settings modules available. Install settings modules to customize your preferences.")

            # Add a back button
            if st.button("← Back to Chat"):
                st.session_state.current_page = "chat"
                st.rerun()

    elif st.session_state.current_page == "admin":
        # Admin page content - using lazy loading for better performance
        # Check if user can access admin
        current_user = st.session_state.get("current_user")
        if not can_access_admin(current_user):
            st.error("❌ Access Denied")
            st.warning("You need Master or Admin role to access the Admin panel.")

            if st.button("← Back to Chat"):
                st.session_state.current_page = "chat"
                st.rerun()
            return

        st.title("🔧 Admin Panel")

        # Get all admin tabs from UI modules (minimal cost - just gets tab names)
        admin_tabs_dict = ui_registry.render_admin_tabs()

        if not admin_tabs_dict:
            st.warning("No admin modules found or active. Install and enable admin modules.")
            st.info("Available modules can be enabled through the System tab (if admin_ui module is loaded).")

            # Provide a way to go back to chat
            if st.button("← Back to Chat"):
                st.session_state.current_page = "chat"
                st.rerun()
            return

        # Render with lazy loading - only the active tab actually executes its code
        render_admin_tabs_lazy(admin_tabs_dict)

    # === TEST READINESS MARKER ===
    # Invisible div rendered only after full script execution.
    # Used by pytest-bdd + Playwright to reliably detect when the app is fully loaded,
    # even with heavy synchronous initializations (transformers, DB, modules, etc.).
    st.markdown(
        '<div data-testid="app-fully-loaded"></div>',
        unsafe_allow_html=True
    )
    log("info", "Loading page done...")

if __name__ == "__main__":
    main()
