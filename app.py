"""
[agent]
## Technical Specifications
The technical specifications are as follows:
- Code and comments are exclusively in English.
- The application is multilingual (French/English), managed via gettext.
- Function or class names are explicit.
- Standalone utility functions are grouped by theme in a "lib" directory.
- To determine if a function is a utility, ask the following question: Could it be useful in a completely different program, unrelated to the current specs? If yes, it's a utility function; if not, it belongs to a module.
- All configuration is stored in a JSON file separate from the code.
- Any value that can be changed without modifying the code and is not user data is placed in the configuration.
- All user data is stored in a database.
- Any key or information that should not be in the git repository is stored in a .env file, loaded at startup.
- Provide shell instructions for launching.
- All prompts are stored in a YAML file.
- The requirements.txt file does not contain version numbers.

Tests:
- Each main function from the specs has a non-regression test for its workflow.
- An initialization function creates a starting test dataset that is reset before running tests.

Modules:
- Every module is designed to be scalable and plug-and-play: the application must be able to run, even if diminished, if the module is absent.
- A module is a directory containing ALL files necessary for its operation (tests, configuration, prompts).
- A module injects into the application through injection points what allows it to function.
- The architecture is modular and scalable; all modules are in a "modules" directory.
- A module groups what is needed to code a semantic unit or a functional unit that uses semantic units.
- Each module contains a specification in its header.
- Each module has associated unit tests.
- A module contains: its translations (JSON), its prompts (YAML), its configuration (JSON), its tests (pytest), its display, its business logic, its libraries. Files are always the same from one module to another.
- A module must be independent of other modules, except for common functionalities.
- A module can have sub-modules and its own injection points, but the only dependencies are the parent module and the application's common functionalities. There must be no module that depends on multiple modules. It is a tree structure.

Common:
- Shared modules are in a dedicated "shared" directory to clearly separate them from removable modules; these modules cannot be disabled.
- The application provides injection points for modules for: translations, prompts and LLM calls, configuration, tests, display (side bar, main page, settings tab, user config).
- Everything common comes with a Mock for tests.

Planned Features:
- Base: multi-user, multilingual, multi-LLM, multi-conversation.
- MVP Features:
- RAG with different RAG engines, means to compare and debug them.
- Token stats: monitoring token usage per user.
- Training : follow user progression, learning path, level assessment through discussion rather than questionnaires.
- Additional Features:
- Retrieval of YouTube playlists and PDFs for importing RAG content.

## UI Injection Points

Modules can implement the following injection points by creating functions with the pattern `inject_ui_[injection_point]()` in a `*_ui.py` file:

### Core Application Flow
- `initialize`: Called once at app startup for initializing session state and module setup. No UI expected.
- `sidebar`: Content injected into the main sidebar. Use `st.*` functions to render UI elements.
- `main_header`: Content injected at the top of the main content area (chat page).
- `main_before_conversation`: Content injected before the conversation interface on chat page.
- `main_content`: Content injected when no user is logged in (fallback content).
- `main_after_conversation`: Content injected after the conversation interface on chat page.
- `main_footer`: Content injected at the bottom of the main content area.
- `settings_content`: Content injected into the user settings page when a user is logged in.

### Admin Interface
- `admin_tab`: Returns a tuple `(tab_name: str, render_function: callable)` to create admin tabs. The render function should contain `st.*` calls for the tab content.

### Usage Examples:
1. **For sidebar integration:**
   ```python
   def inject_ui_sidebar():
       st.subheader("My Module")
       if st.button("Do something"):
           st.write("Clicked!")
   ```

2. **For admin tab integration:**
   ```python
   def inject_ui_admin_tab():
       def render_my_admin_tab():
           st.header("My Admin Panel")
           st.write("Admin content here")
       return ("My Module", render_my_admin_tab)
   ```

3. **For settings integration:**
   ```python
   def inject_ui_settings_content():
       st.subheader("Module Settings")
       option = st.selectbox("Choose option", ["A", "B", "C"])
   ```

### Location Requirements:
- UI modules must be placed in `shared/` or `modules/[module_name]/` directories
- File names must end with `_ui.py` (e.g., `my_module_ui.py`)
- Functions must be named exactly `inject_ui_[injection_point]()`
- Functions should use Streamlit commands (`st.button`, `st.write`, etc.) to render content

### Notes:
- Each injection point can be implemented by multiple modules
- Modules can implement multiple injection points
- The registry automatically discovers and caches all UI modules
- Order of execution within an injection point is not guaranteed (use dependencies if needed)
- Modules only appear if their parent module is active (except shared modules which are always active)

"""


import streamlit as st
import os
import sys
import asyncio
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add shared directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "shared"))

# Import everything needed - CONFIG FIRST!
from shared.common import _, get_available_languages
from shared.common import get_config
from shared.common import log, configure_logging_from_dict
from shared.common import init_database, get_db_manager
from shared.common import init_user_manager

# IMPORTANT: Don't alias 'llm' to avoid name conflicts
from shared.common import llm_generate, set_current_llm, get_available_llms, get_current_llm_info

# Import UI registry system
from shared.ui_registry import UIRegistry
# Import module handler
from shared.module_handler import ModuleHandler, get_active_modules, toggle_module

# Configure logging from config (one line)
configure_logging_from_dict(get_config().get("logging", {}))

get_available_languages()

# Initialize Module Handler - store in session state
if 'module_handler' not in st.session_state:
    log("info", "Initializing module handler in session state")
    st.session_state.module_handler = ModuleHandler()
    st.session_state.module_handler.initialize()

# Use the session state module handler
module_handler = st.session_state.module_handler

# Initialize user manager with default users
init_user_manager(create_default_users=True)

# Load active module UIs immediately
active_modules = module_handler.get_active_modules()
for module_name in active_modules:
    ui_module = module_handler.load_module_ui(module_name)
    if ui_module:
        log("debug", f"Successfully loaded UI for module: {module_name}")
    else:
        log("warning", f"Could not load UI for module: {module_name}")

db_path = get_config().get("database", {}).get("path", ".") + "/app.db"
init_database(use_memory=False, db_path=db_path)

# Initialize UI registry - do this here, not inside main()
# The registry will be cached in session state
if 'ui_registry' not in st.session_state:
    log("info", "Initializing UI registry in session state")
    st.session_state.ui_registry = UIRegistry()

# Get the registry from session state
ui_registry = st.session_state.ui_registry
ui_registry.set_module_handler(module_handler)

# Page configuration
st.set_page_config(
    page_title="Multilingual App",
    page_icon="🌍",
    layout="centered"
)

# NEW: Initialize critical session state variables BEFORE main()
if "current_user" not in st.session_state:
    st.session_state.current_user = None

if "app_initialized" not in st.session_state:
    st.session_state.app_initialized = False

# NEW: Add a flag to track if user explicitly logged out/switched
if "user_manually_logged_out" not in st.session_state:
    st.session_state.user_manually_logged_out = False

# NEW: Initialize admin tab state
if "admin_current_tab" not in st.session_state:
    st.session_state.admin_current_tab = "System"

if "current_language" not in st.session_state:
    st.session_state.current_language = "en"

def can_access_admin(current_user):
    """Check if current user can access admin panel."""
    if not current_user:
        return False

    # Only admin and master users can access admin
    from shared.common import UserRole
    return current_user.get("role") in [UserRole.ADMIN.value, UserRole.MASTER.value]

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

    # NEW: Call UI module initialization functions
    # INJECTION POINT: Initialize - for setting up session state variables
    log("debug", "Calling UI module initialization functions")
    initialization_results = ui_registry.render_all("initialize")

    # NEW: Auto-login after UI components are initialized
    # This ensures user manager is available and session state is ready
    if get_config().get("app.auto_login", False):
        from shared.users_ui import auto_login_first_user
        auto_login_first_user()

    # NEW: Apply user preferences if a user is logged in
    current_user = st.session_state.get("current_user")

    # Sidebar for language, LLM, navigation, and injected UI modules
    with st.sidebar:

        # Navigation buttons
        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("💬 Chat", use_container_width=True):
                st.session_state.current_page = "chat"
                st.rerun()

        with col2:
            if st.button("⚙️ Settings", use_container_width=True):
                st.session_state.current_page = "settings"
                st.rerun()

        with col3:
            # Only show Admin button for users who can access it
            if can_access_admin(current_user):
                if st.button("🔧 Admin", use_container_width=True):
                    st.session_state.current_page = "admin"
                    st.rerun()
            else:
                # Disabled button for normal users
                st.button("🔧 Admin", use_container_width=True, disabled=True,
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

        # Let UI modules handle ALL content - no default fallback content in app.py
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
        # Admin page content - using the new injection mechanism
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

        # Get all admin tabs from UI modules
        admin_tabs_dict = ui_registry.render_admin_tabs()

        if not admin_tabs_dict:
            st.warning("No admin modules found or active. Install and enable admin modules.")
            st.info("Available modules can be enabled through the System tab (if admin_ui module is loaded).")

            # Provide a way to go back to chat
            if st.button("← Back to Chat"):
                st.session_state.current_page = "chat"
                st.rerun()
            return

        # Get tab names and ensure System is first
        tab_names = list(admin_tabs_dict.keys())
        if "System" in tab_names:
            # Move System to first position
            tab_names.remove("System")
            tab_names = ["System"] + sorted(tab_names)

        # Create tabs
        tabs = st.tabs(tab_names)

        # Render each tab content
        for i, tab_name in enumerate(tab_names):
            with tabs[i]:
                if tab_name in admin_tabs_dict:
                    try:
                        # Call the tab's render function
                        admin_tabs_dict[tab_name]()
                    except Exception as e:
                        st.error(f"Error loading {tab_name} admin page: {str(e)}")
                        log("error", f"Error loading {tab_name} admin page: {str(e)}", exc_info=True)

    # === TEST READINESS MARKER ===
    # Invisible div rendered only after full script execution.
    # Used by pytest-bdd + Playwright to reliably detect when the app is fully loaded,
    # even with heavy synchronous initializations (transformers, DB, modules, etc.).
    st.markdown(
        '<div data-testid="app-fully-loaded"></div>',
        unsafe_allow_html=True
    )

if __name__ == "__main__":
    main()
