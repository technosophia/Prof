# file name: app.py
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
- Learning path, level assessment through discussion rather than questionnaires.
- Additional Features:
- Retrieval of YouTube playlists and PDFs for importing RAG content.
- Metadata for RAG if necessary for the learning path.

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

# IMPORTANT: Don't alias 'llm' to avoid name conflicts
from shared.llm import llm_generate, set_current_llm, get_available_llms, get_current_llm_info

# Import user management
from shared.database import init_database, db_manager

# Import UI registry system
from shared.ui_registry import UIRegistry
# Import module handler
from shared.module_handler import ModuleHandler, get_active_modules, toggle_module

# Configure logging from config (one line)
configure_logging_from_dict(get_config().get("logging", {}))

db_path = get_config().get("database", {}).get("path", ".") + "/app.db"
init_database(use_memory=False, db_path=db_path)

# Initialize Module Handler - store in session state
if 'module_handler' not in st.session_state:
    log("info", "Initializing module handler in session state")
    st.session_state.module_handler = ModuleHandler()
    st.session_state.module_handler.initialize()

# Use the session state module handler
module_handler = st.session_state.module_handler

from shared.users import init_user_manager
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

# Initialize UI registry - do this here, not inside main()
# The registry will be cached in session state
if 'ui_registry' not in st.session_state:
    log("info", "Initializing UI registry in session state")
    st.session_state.ui_registry = UIRegistry()
    # Pass the module handler to the registry
    st.session_state.ui_registry.set_module_handler(module_handler)
    st.session_state.ui_registry.initialize()

# Get the registry from session state
ui_registry = st.session_state.ui_registry

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


    # Sidebar for language, LLM, navigation, and injected UI modules
    with st.sidebar:
        st.title("🧭 Configuration")
        # Show available languages - sorted (en will naturally be first)
        available_langs = get_available_languages()

        # Log available languages
        log("debug", f"Available languages: {available_langs}")

        # Better mapping for display names (extensible)
        lang_names = {
            "en": "English",
            "fr": "Français",
            # Add more here later
        }

        # Compute default index
        current_lang = st.session_state.current_language
        try:
            default_index = available_langs.index(current_lang)
        except ValueError:
            default_index = 0  # fallback to first

        # Language selector
        lang_option = st.selectbox(
            "🌍 " + _("language_select"),
            options=available_langs,
            format_func=lambda x: lang_names.get(x, x.upper()),
            index=default_index,
            key="language_selector"
        )

        # Handle language change
        if lang_option != st.session_state.current_language:
            old_lang = st.session_state.current_language
            st.session_state.current_language = lang_option
            log("info", f"Language changed from '{old_lang}' to '{lang_option}'")
            st.rerun()

        # Navigation buttons
        col1, col2 = st.columns(2)
        with col1:
            if st.button("💬 Chat", use_container_width=True):
                st.session_state.current_page = "chat"
                st.rerun()

        with col2:
            if st.button("🔧 Admin", use_container_width=True):
                st.session_state.current_page = "admin"
                st.rerun()

        # Get available LLMs
        available_llms_list = get_available_llms()

        # Get current LLM info
        current_llm_info = get_current_llm_info()

        # Create list of available LLMs for dropdown
        llm_options = []
        llm_display_names = []

        for llm_item in available_llms_list:
            if llm_item["available"]:
                status_icon = "🟢" if llm_item["enabled"] else "🔴"
                display_name = f"{status_icon} {llm_item['name']} ({llm_item['type']})"
                llm_options.append(llm_item["id"])
                llm_display_names.append(display_name)

        # LLM selector
        if llm_options:
            # Find current LLM index
            current_index = 0
            if current_llm_info:
                try:
                    current_index = llm_options.index(current_llm_info["id"])
                except ValueError:
                    current_index = 0

            selected_llm_id = st.selectbox(
                "🤖 " + _("select_llm"),
                options=llm_options,
                format_func=lambda x: llm_display_names[llm_options.index(x)],
                index=current_index,
                key="llm_selector"
            )

            # Check if LLM changed
            if selected_llm_id != (current_llm_info.get("id") if current_llm_info else None):
                if set_current_llm(selected_llm_id):
                    log("info", f"LLM changed to: {selected_llm_id}")
                    st.rerun()
                else:
                    st.error(f"Failed to switch to LLM: {selected_llm_id}")

        # INJECTION POINT 2: Sidebar Content from UI Modules
        # Call all registered sidebar render functions
        sidebar_contents = ui_registry.render_all("sidebar")
        st.caption(_("current_language"))

        # Show current LLM info in sidebar
        if current_llm_info:
            st.info(f"**Current LLM:** {current_llm_info['name']}")
            st.caption(f"Type: {current_llm_info['type']}")
            st.caption(f"Model: {current_llm_info['model']}")
            st.caption(f"Status: {'✅ Available' if current_llm_info['available'] else '❌ Unavailable'}")

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
        for content in main_contents_after:
            if content:
                st.divider()

        # INJECTION POINT 7: Main Footer Content
        main_footer = ui_registry.render_all("main_footer")
        for content in main_footer:
            if content:
                st.divider()

    elif st.session_state.current_page == "admin":
        # Admin page content - using the new injection mechanism
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

if __name__ == "__main__":
    main()
